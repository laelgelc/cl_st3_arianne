#!/usr/bin/env python3
"""Prepare existing sceptical blog texts for human review, never automatic inclusion."""
import argparse
import hashlib
import json
import os
import re
import shutil
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.worksheet.datavalidation import DataValidation

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[3]
COLUMNS = ('candidate_id', 'text_preview', 'publication_datetime_utc', 'review_status', 'review_notes', 'text_sha256', 'full_text_path')
INVALID_XML = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]')
WARNING = ('Verify source identity, full text and publication date before approval. Metadata dates and URL dates are not proof of publication. '
           'Earlier publications are permitted as a user-approved temporal exception; publications after 2022-11-30 are outside scope.')


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
    metadata_hash = hashlib.sha256(metadata.read_bytes()).hexdigest()
    book = load_workbook(metadata, read_only=True, data_only=True)
    diagnostics, records = [], {}
    try:
        rows = book.active.iter_rows(values_only=True)
        if tuple(next(rows, ())[:4]) != ('Nome do arquivo', 'Data', 'Título do artigo', 'Link do artigo'):
            raise ValueError('Unexpected metadata header')
        for number, values in enumerate(rows, 2):
            if not any(value is not None for value in values):
                continue
            ident, raw_date, title, url = (list(values[:4]) + [None] * 4)[:4]
            if not isinstance(ident, str) or not re.fullmatch(r'blog_cetico_[0-9]{3}', ident):
                diagnostics.append({'issue': 'invalid metadata id', 'row': number, 'id': str(ident)})
                continue
            if ident in records:
                diagnostics.append({'issue': 'duplicate metadata id', 'id': ident, 'rows': [records[ident]['metadata_row'], number]})
                continue
            if isinstance(raw_date, (datetime, date)):
                raw_date = raw_date.isoformat()
            elif raw_date is not None:
                raw_date = str(raw_date)
                diagnostics.append({'issue': 'unverified metadata date', 'id': ident, 'row': number})
            records[ident] = {'metadata_date': raw_date, 'title': title, 'source_url': url, 'metadata_row': number}
            parsed = urlparse(url) if isinstance(url, str) else None
            if not raw_date or not isinstance(title, str) or not title.strip() or not parsed or parsed.scheme not in ('http', 'https') or not parsed.netloc:
                diagnostics.append({'issue': 'invalid or incomplete metadata', 'id': ident, 'row': number})
    finally:
        book.close()

    files = sorted(p for p in texts.iterdir() if p.is_file() and p.suffix.lower() == '.txt')
    ids = {p.stem for p in files}
    if len(ids) != len(files):
        raise ValueError('Text filenames have duplicate stems')
    for ident in sorted(records.keys() - ids):
        diagnostics.append({'issue': 'missing text file', 'id': ident})
    for ident in sorted(ids - records.keys()):
        diagnostics.append({'issue': 'extra text file without metadata', 'id': ident})

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Review'
    sheet.freeze_panes = 'A2'
    sheet.append(COLUMNS)
    hashes = {}
    with (output / 'candidates.ndjson').open('x', encoding='utf-8') as manifest:
        for path in files:
            raw = path.read_bytes()
            text = raw.decode('utf-8')
            digest = hashlib.sha256(raw).hexdigest()
            info = records.get(path.stem, {})
            if not re.fullmatch(r'blog_cetico_[0-9]{3}', path.stem):
                diagnostics.append({'issue': 'irregular text filename', 'id': path.stem, 'filename': path.name})
            if not text.strip():
                diagnostics.append({'issue': 'empty text', 'id': path.stem})
            if digest in hashes:
                diagnostics.append({'issue': 'duplicate text', 'id': path.stem, 'other_id': hashes[digest]})
            else:
                hashes[digest] = path.stem
            row = {'schema_version': 1, 'candidate_id': 'sceptical-blog:' + path.stem,
                   'stratum': 'sceptic-blog', 'actor': 'sceptical', 'register': 'blog',
                   'source': 'sceptical blog', 'source_id': path.stem, 'source_url': info.get('source_url'),
                   'title': info.get('title'), 'metadata_date': info.get('metadata_date'),
                   'publication_datetime_utc': None, 'temporal_eligibility': 'unknown',
                   'text': text, 'source_manifest': relative(metadata), 'source_sha256': metadata_hash,
                   'metadata_row': info.get('metadata_row'), 'source_text_sha256': digest,
                   'review_source_path': relative(path), 'review_status': 'pending', 'review_notes': '', 'review_warning': WARNING}
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
    stats = {'candidates': len(files), 'metadata_records': len(records), 'diagnostics': len(diagnostics), 'warning': WARNING}
    (output / 'stats.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', type=Path, default=HERE / 'metadados_blogs_ceticos_climatechange.xlsx')
    parser.add_argument('--texts', type=Path, default=HERE / 'corpus_para_treetagger')
    parser.add_argument('--output-dir', type=Path, required=True, help='New directory for review artifacts')
    args = parser.parse_args()
    print(json.dumps(prepare(args.metadata, args.texts, args.output_dir), ensure_ascii=False, indent=2))
    print('Inspect diagnostics.jsonl and verify each complete source text and publication date before review.')


if __name__ == '__main__':
    main()