#!/usr/bin/env python3
"""Prepare pending NOW CORE candidates and a source-linked review workbook.

Open the full local source path in each review row before making a decision.
The preview is not the full article. Keep source files available for import.
Paths in the screened manifest are relative to the Phase 1 directory.
"""
import argparse
import hashlib
import json
import os
import re
import tarfile
import tempfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
PHASE1 = HERE.parents[2]
PROJECT_ROOT = HERE.parents[3]
DEFAULT_INPUT = HERE / '03_now_screened/llm_screening_v2_gpt-6-luna/climate_now_screened.tar.xz'
REVIEW_COLUMNS = ('candidate_id', 'text_preview', 'publication_datetime_utc', 'review_status', 'review_notes', 'text_sha256', 'full_text_path')
INVALID_XML = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]')


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def candidates(archive, base):
    digest = sha256(archive)
    seen = set()
    with tarfile.open(archive, 'r:xz') as tar:
        members = tar.getmembers()
        if len(members) != 1 or not members[0].isfile() or not members[0].name.endswith('.ndjson'):
            raise ValueError('Expected exactly one NDJSON file in archive')
        with tar.extractfile(members[0]) as source:
            for number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                screening = row.get('llm_screening')
                if not isinstance(screening, dict) or screening.get('category') not in ('CORE', 'PERIPHERAL', 'EXCLUDE'):
                    raise ValueError(f'Invalid screening on line {number}')
                if screening['category'] != 'CORE':
                    continue
                article_id = row.get('article_id')
                if not isinstance(article_id, str) or not re.fullmatch(r'[0-9]+', article_id) or article_id in seen:
                    raise ValueError(f'Invalid or duplicate article ID on line {number}')
                seen.add(article_id)
                path = row.get('filepath')
                if not isinstance(path, str) or not path or Path(path).is_absolute():
                    raise ValueError(f'Invalid article path on line {number}')
                base_resolved = base.resolve()
                article_path = (base_resolved / path).resolve()
                if not article_path.is_relative_to(base_resolved):
                    raise ValueError(f'Article path escapes base on line {number}')
                raw = article_path.read_bytes()
                text = raw.decode('utf-8')
                if not text.strip():
                    raise ValueError(f'Empty article on line {number}')
                published = row.get('date_iso')
                try:
                    if not isinstance(published, str) or date.fromisoformat(published).isoformat() != published:
                        raise ValueError()
                except ValueError as exc:
                    raise ValueError(f'Invalid date on line {number}') from exc
                if not isinstance(row.get('source_name'), str) or not row['source_name'].strip():
                    raise ValueError(f'Missing source name on line {number}')
                yield {'schema_version': 1, 'candidate_id': 'now:' + article_id,
                    'stratum': 'press-news', 'actor': 'news media', 'register': 'news article',
                    'source': row['source_name'], 'source_id': article_id, 'source_url': row.get('url'),
                    'publication_datetime_utc': published, 'text': text,
                    'source_manifest': os.path.relpath(archive.resolve(), PROJECT_ROOT), 'source_sha256': digest,
                    'source_text_sha256': hashlib.sha256(raw).hexdigest(),
                    'review_source_path': os.path.relpath(article_path, PROJECT_ROOT),
                    'now_metadata': {key: value for key, value in row.items() if key not in ('llm_screening', 'llm_screening_metadata')},
                    'llm_screening': screening, 'llm_screening_metadata': row.get('llm_screening_metadata'),
                    'review_status': 'pending', 'review_notes': '',
                    'review_warning': 'Verify relevance, completeness, duplicates and publication date.'}


def export_review(manifest, output):
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.worksheet.datavalidation import DataValidation

    # Validate before opening a streaming worksheet, so rejected records do not
    # leave open XML writers or partial workbooks behind.
    seen = set()
    count = 0
    with manifest.open(encoding='utf-8') as source:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            cid = row.get('candidate_id')
            if not isinstance(cid, str) or not cid or cid in seen:
                raise ValueError('Invalid or duplicate candidate ID')
            seen.add(cid)
            count += 1
            if count > 1048575:
                raise ValueError('Excel review row limit exceeded')
            for value in review_values(row):
                if value is not None and value != '' and (not isinstance(value, str) or
                        len(value.encode('utf-16-le')) // 2 > 32767 or INVALID_XML.search(value)):
                    raise ValueError(f'Excel cannot represent review metadata for {cid}')
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet('Review')
    sheet.freeze_panes = 'A2'
    sheet.append(REVIEW_COLUMNS)
    with manifest.open(encoding='utf-8') as source:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            cells = []
            for value in review_values(row):
                if value is None or value == '':
                    value = None
                cell = WriteOnlyCell(sheet, value=value)
                if value is not None:
                    cell.data_type = 's'
                cells.append(cell)
            sheet.append(cells)
    validation = DataValidation(type='list', formula1='"pending,approved,rejected"')
    sheet.data_validations.append(validation)
    validation.add(f'D2:D{max(2, count + 1)}')
    sheet.auto_filter.ref = f'A1:G{count + 1}'
    with output.open('xb') as destination:
        workbook.save(destination)


def review_values(row):
    text = row['text'].replace('\r\n', '\n').replace('\r', '\n')[:200]
    preview = INVALID_XML.sub(lambda match: f'\\u{ord(match.group()):04x}', text)
    return (row['candidate_id'], preview, row['publication_datetime_utc'],
            row['review_status'], row['review_notes'], row['source_text_sha256'],
            row['review_source_path'])


def prepare(archive, base, output, review=None):
    targets = [output] + ([review] if review is not None else [])
    if len({p.resolve() for p in targets}) != len(targets):
        raise ValueError('Output paths must differ')
    for path in targets:
        if os.path.lexists(path):
            raise FileExistsError(path)
    staged = []
    published = []
    try:
        for target in targets:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.now-', delete=False) as handle:
                staged.append(Path(handle.name))
        count = 0
        with staged[0].open('w', encoding='utf-8', newline='\n') as out:
            for row in candidates(archive, base):
                out.write(json.dumps(row, ensure_ascii=False) + '\n')
                count += 1
        if review is not None:
            staged[1].unlink()
            export_review(staged[0], staged[1])
        for temp, target in zip(staged, targets):
            os.link(temp, target)
            published.append(target)
        return count
    except Exception:
        for target in published:
            target.unlink()
        raise
    finally:
        for temp in staged:
            temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--base', type=Path, default=PHASE1, help='Base directory for source filepaths')
    parser.add_argument('--output', type=Path, default=HERE / 'now_candidates.ndjson')
    parser.add_argument('--review-xlsx', type=Path, default=HERE / 'now_candidates_review.xlsx')
    parser.add_argument('--manifest-only', action='store_true')
    args = parser.parse_args()
    count = prepare(args.input, args.base, args.output, None if args.manifest_only else args.review_xlsx)
    print(f'Prepared {count} pending CORE candidates')


if __name__ == '__main__':
    main()