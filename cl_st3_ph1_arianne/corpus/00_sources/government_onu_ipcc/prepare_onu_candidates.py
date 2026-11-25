#!/usr/bin/env python3
"""Prepare existing ONU segments for human review, never for automatic inclusion.

Each file is an existing corpus segment, not a verified treaty boundary. Verify
its text, section, source and provenance against the official document. Collection
dates are not publication dates. UNFCCC (1992) and Kyoto (1997) are permitted
exceptions to the 2015-11-01 to 2022-11-30 study window; Paris (2015) is eligible.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.worksheet.datavalidation import DataValidation

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[3]
SOURCE = HERE / 'corpus_onu'
COLUMNS = ('candidate_id', 'text_preview', 'publication_datetime_utc', 'review_status', 'review_notes', 'text_sha256', 'full_text_path')
INVALID_XML = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]')
TREATIES = {
    'UNFCCC': ('UNFCCC', 1992, 'permitted temporal exception', 'https://unfccc.int/documents/36938'),
    'Protocolo de Kyoto': ('Kyoto Protocol', 1997, 'permitted temporal exception', 'https://unfccc.int/process-and-meetings/the-kyoto-protocol/history-of-the-kyoto-protocol/text-of-the-kyoto-protocol'),
    'Acordo de Paris': ('Paris Agreement', 2015, 'eligible', 'https://unfccc.int/process-and-meetings/the-paris-agreement'),
}
SUBJECT = re.compile(r'^Tratado ONU (UNFCCC|Protocolo de Kyoto|Acordo de Paris) (Preâmbulo|Artigo [1-9][0-9]*)$')
WARNING = ('Existing segment boundaries and provenance are unverified; compare full text, section and source with the official treaty. '
           'Collection date is not publication date. Human verification is required before approval.')


def relative(path):
    return os.path.relpath(Path(path).resolve(), PROJECT_ROOT)


def prepare(metadata, texts, output):
    output = Path(output).absolute()
    output.mkdir()
    try:
        return _prepare(Path(metadata), Path(texts), output)
    except BaseException:
        shutil.rmtree(output)
        raise


def _prepare(metadata, texts, output):
    raw_metadata = metadata.read_bytes()
    book = load_workbook(metadata, read_only=True, data_only=True)
    diagnostics, records, sections = [], {}, {}
    try:
        sheet = book.active
        rows = sheet.iter_rows(values_only=True)
        header = next(rows)
        expected = ('Nome de arquivo', 'Data de coleta', 'Assunto', 'Link')
        if tuple(header[:4]) != expected:
            raise ValueError('Unexpected metadata header')
        for number, values in enumerate(rows, 2):
            if not any(value is not None for value in values):
                continue
            ident, collected, subject, url = (list(values[:4]) + [None] * 4)[:4]
            if not isinstance(ident, str) or not re.fullmatch(r'ONU_[0-9]{3}', ident):
                diagnostics.append({'issue': 'invalid metadata id', 'row': number, 'id': str(ident)})
                continue
            if isinstance(collected, (datetime, date)):
                collected = collected.date().isoformat() if isinstance(collected, datetime) else collected.isoformat()
            elif collected is not None:
                collected = str(collected)
                diagnostics.append({'issue': 'unverified collection date', 'id': ident, 'row': number})
            record = {'collection_date': collected, 'subject': subject, 'source_url': url, 'metadata_row': number}
            if ident in records:
                diagnostics.append({'issue': 'duplicate metadata id', 'id': ident, 'rows': [records[ident]['metadata_row'], number]})
                continue
            records[ident] = record
            match = SUBJECT.fullmatch(subject) if isinstance(subject, str) else None
            if not match or not collected or not isinstance(url, str) or not url:
                diagnostics.append({'issue': 'invalid or incomplete metadata', 'id': ident, 'row': number})
            if match and url != TREATIES[match.group(1)][3]:
                diagnostics.append({'issue': 'inconsistent treaty URL', 'id': ident, 'row': number, 'url': url})
            if match:
                key = (match.group(1), match.group(2))
                if key in sections:
                    diagnostics.append({'issue': 'duplicate treaty section', 'id': ident, 'other_id': sections[key], 'subject': subject})
                else:
                    sections[key] = ident
                if match.group(2).startswith('Artigo '):
                    maximum = {'UNFCCC': 26, 'Protocolo de Kyoto': 28, 'Acordo de Paris': 29}[match.group(1)]
                    if int(match.group(2).split()[-1]) > maximum:
                        diagnostics.append({'issue': 'invalid treaty section', 'id': ident, 'subject': subject})
    finally:
        book.close()

    files = sorted(p for p in texts.iterdir() if p.is_file() and p.suffix.lower() == '.txt')
    ids = {p.stem for p in files}
    for ident in sorted(records.keys() - ids):
        diagnostics.append({'issue': 'missing text file', 'id': ident})
    for ident in sorted(ids - records.keys()):
        diagnostics.append({'issue': 'extra text file without metadata', 'id': ident})
    if len(ids) != len(files):
        raise ValueError('Text filenames have duplicate stems')

    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet('Review')
    sheet.freeze_panes = 'A2'
    sheet.append(COLUMNS)
    with (output / 'candidates.ndjson').open('x', encoding='utf-8') as manifest:
        for path in files:
            raw = path.read_bytes()
            text = raw.decode('utf-8')
            digest = hashlib.sha256(raw).hexdigest()
            info = records.get(path.stem, {})
            subject = info.get('subject')
            match = SUBJECT.fullmatch(subject) if isinstance(subject, str) else None
            treaty = TREATIES[match.group(1)] if match else None
            if not text.strip():
                diagnostics.append({'issue': 'empty text', 'id': path.stem})
            row = {'schema_version': 1, 'candidate_id': 'onu:' + path.stem,
                   'stratum': 'treaty-segment', 'actor': 'government', 'register': 'treaty',
                   'source': treaty[0] if treaty else 'ONU (unverified)', 'source_id': path.stem,
                   'source_url': info.get('source_url'), 'section_reference': match.group(2) if match else None,
                   'subject': subject, 'collection_date': info.get('collection_date'),
                   'treaty_year': treaty[1] if treaty else None, 'temporal_eligibility': treaty[2] if treaty else 'unknown',
                   'publication_datetime_utc': None, 'text': text, 'source_manifest': relative(metadata),
                   'source_sha256': hashlib.sha256(raw_metadata).hexdigest(), 'metadata_row': info.get('metadata_row'),
                   'source_text_sha256': digest, 'review_source_path': relative(path),
                   'review_status': 'pending', 'review_notes': '', 'review_warning': WARNING}
            manifest.write(json.dumps(row, ensure_ascii=False) + '\n')
            preview = INVALID_XML.sub(lambda m: f'\\u{ord(m.group()):04x}', text.replace('\r\n', '\n').replace('\r', '\n')[:200])
            cells = []
            for value in (row['candidate_id'], preview, None, 'pending', None, digest, row['review_source_path']):
                cell = WriteOnlyCell(sheet, value=value)
                if value is not None:
                    cell.data_type = 's'
                cells.append(cell)
            sheet.append(cells)
    validation = DataValidation(type='list', formula1='"pending,approved,rejected"')
    sheet.data_validations.append(validation)
    validation.add(f'D2:D{max(2, len(files) + 1)}')
    sheet.auto_filter.ref = f'A1:G{len(files) + 1}'
    with (output / 'review.xlsx').open('xb') as handle:
        workbook.save(handle)
    with (output / 'diagnostics.jsonl').open('x', encoding='utf-8') as handle:
        for item in diagnostics:
            handle.write(json.dumps(item, ensure_ascii=False) + '\n')
    stats = {'candidates': len(files), 'metadata_records': len(records), 'diagnostics': len(diagnostics),
             'warning': WARNING, 'temporal_policy': 'UNFCCC 1992 and Kyoto 1997 are permitted exceptions; Paris 2015 is eligible.'}
    (output / 'stats.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', type=Path, default=SOURCE / 'metadado_tratados_onu.xlsx')
    parser.add_argument('--texts', type=Path, default=SOURCE / 'corpus_para_treetagger')
    parser.add_argument('--output-dir', type=Path, required=True, help='New directory for review artifacts')
    args = parser.parse_args()
    print(json.dumps(prepare(args.metadata, args.texts, args.output_dir), ensure_ascii=False, indent=2))
    print('Inspect diagnostics.jsonl and verify each complete source text before review.')


if __name__ == '__main__':
    main()