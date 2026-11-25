#!/usr/bin/env python3
"""Prepare NGO stories for manual review in a new, never-overwritten directory.

Open the full text file before reviewing; the spreadsheet contains only a preview.
Inspect diagnostics.jsonl for records requiring investigation, including unknown dates.
Epoch millisecond dates are interpreted in UTC; publication values remain date-only.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[3]
START, END = date(2015, 11, 1), date(2022, 11, 30)
COLUMNS = ('candidate_id', 'text_preview', 'publication_datetime_utc', 'review_status', 'review_notes', 'text_sha256', 'full_text_path')
INVALID_XML = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]')


def publication_date(value):
    try:
        if type(value) is int:
            return datetime.fromtimestamp(value / 1000, timezone.utc).date()
        if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            return date.fromisoformat(value)
    except (ValueError, OverflowError, OSError):
        pass
    return None


def prepare(inputs, output, start=START, end=END):
    """Create candidates, linked review, diagnostics and statistics under output."""
    if start > end:
        raise ValueError('Start date must not be after end date')
    output = Path(output).absolute()
    output.mkdir()  # exclusive, also protects inputs and prior review decisions
    try:
        return _prepare(inputs, output, start, end)
    except BaseException:
        shutil.rmtree(output)
        raise


def _prepare(inputs, output, start, end):
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.worksheet.datavalidation import DataValidation

    groups = defaultdict(list)
    diagnostics = []
    stats = {'window': {'start': start.isoformat(), 'end': end.isoformat()}, 'sources': {}}
    for source, path in inputs.items():
        path = Path(path)
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        counts = Counter()
        stats['sources'][source] = {'path': os.path.relpath(path.resolve(), PROJECT_ROOT), 'sha256': digest, 'counts': counts}
        for number, line in enumerate(raw.splitlines(), 1):
            if not line.strip():
                continue
            counts['paragraph_rows'] += 1
            try:
                row = json.loads(line)
                if not isinstance(row, dict) or not isinstance(row.get('Post ID'), str) or not row['Post ID'].strip():
                    raise ValueError('missing or invalid Post ID')
            except (ValueError, UnicodeError) as exc:
                counts['malformed_rows'] += 1
                diagnostics.append({'source': source, 'line': number, 'issue': 'malformed row', 'detail': str(exc), 'raw_hex': line.hex()})
                continue
            groups[(source, row['Post ID'])].append((number, row))

    text_dir = output / 'texts'
    text_dir.mkdir()
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet('Review')
    sheet.freeze_panes = 'A2'
    sheet.append(COLUMNS)
    count = 0
    with (output / 'candidates.ndjson').open('x', encoding='utf-8', newline='\n') as manifest:
        for (source, post_id), rows in sorted(groups.items()):
            counts = stats['sources'][source]['counts']
            counts['stories'] += 1
            lines = [n for n, _ in rows]
            dates = [publication_date(row.get('Post Date')) for _, row in rows]
            if None in dates or len(set(dates)) != 1:
                counts['uncertain_date_stories'] += 1
                diagnostics.append({'source': source, 'post_id': post_id, 'lines': lines, 'issue': 'unknown or conflicting dates', 'values': [r.get('Post Date') for _, r in rows]})
                continue
            published = dates[0]
            if not start <= published <= end:
                counts['out_of_window_stories'] += 1
                continue
            warnings = []
            metadata = [{k: v for k, v in row.items() if k not in ('Paragraph', 'Text Paragraph')} for _, row in rows]
            if any(item != metadata[0] for item in metadata[1:]):
                warnings.append('conflicting story metadata')
            paragraphs = []
            for number, row in rows:
                label, text = row.get('Paragraph'), row.get('Text Paragraph')
                match = re.fullmatch(r'Paragraph ([1-9][0-9]*)', label) if isinstance(label, str) else None
                if not match or not isinstance(text, str) or not text.strip():
                    warnings.append(f'invalid paragraph at line {number}')
                paragraphs.append((int(match.group(1)) if match else None, number, text))
            indexes = [p[0] for p in paragraphs]
            if None not in indexes and (len(set(indexes)) != len(indexes) or sorted(indexes) != list(range(1, len(indexes) + 1))):
                warnings.append('duplicate or missing paragraph numbers')
            if any(not isinstance(p[2], str) or not p[2].strip() for p in paragraphs):
                counts['invalid_text_stories'] += 1
                diagnostics.append({'source': source, 'post_id': post_id, 'lines': lines, 'issue': 'invalid paragraph text', 'rows': [r for _, r in rows]})
                continue
            if warnings:
                counts['warning_stories'] += 1
                diagnostics.append({'source': source, 'post_id': post_id, 'lines': lines, 'issue': 'paragraph or metadata conflict', 'warnings': warnings, 'rows': [r for _, r in rows]})
            # Only trust numerical ordering when it is complete and unambiguous.
            if not any('paragraph' in warning for warning in warnings):
                paragraphs.sort(key=lambda p: p[0])
            text = '\n\n'.join(p[2] for p in paragraphs)
            cid = f'ngo:{source}:{post_id}'
            filename = hashlib.sha256(cid.encode('utf-8')).hexdigest() + '.txt'
            text_path = text_dir / filename
            text_path.write_bytes(text.encode('utf-8'))
            text_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
            row = {'schema_version': 1, 'candidate_id': cid, 'stratum': 'ngo-story', 'actor': 'NGO', 'register': 'institutional story',
                   'source': str(metadata[0].get('Source') or source), 'source_id': source + ':' + post_id,
                   'source_url': metadata[0].get('Post URL'), 'publication_datetime_utc': published.isoformat(),
                   'text': text, 'source_manifest': os.path.relpath(Path(inputs[source]).resolve(), PROJECT_ROOT), 'source_sha256': stats['sources'][source]['sha256'],
                   'source_text_sha256': text_hash, 'review_source_path': os.path.relpath(text_path, PROJECT_ROOT),
                   'ngo_metadata': metadata[0], 'source_lines': lines, 'review_status': 'pending', 'review_notes': '',
                   'review_warning': 'Review full text, relevance, date, completeness and duplicates. ' + '; '.join(warnings)}
            manifest.write(json.dumps(row, ensure_ascii=False) + '\n')
            preview = INVALID_XML.sub(lambda m: f'\\u{ord(m.group()):04x}', text.replace('\r\n', '\n').replace('\r', '\n')[:200])
            values = (cid, preview, published.isoformat(), 'pending', None, text_hash, row['review_source_path'])
            if count >= 1048575:
                raise ValueError('Excel review row limit exceeded')
            cells = []
            for value in values:
                if value is not None and (len(value.encode('utf-16-le')) // 2 > 32767 or INVALID_XML.search(value)):
                    raise ValueError(f'Excel cannot represent review metadata for {cid}')
                cell = WriteOnlyCell(sheet, value=value)
                if value is not None:
                    cell.data_type = 's'
                cells.append(cell)
            sheet.append(cells)
            count += 1
            counts['candidates'] += 1
    validation = DataValidation(type='list', formula1='"pending,approved,rejected"')
    sheet.data_validations.append(validation)
    validation.add(f'D2:D{max(2, count + 1)}')
    sheet.auto_filter.ref = f'A1:G{count + 1}'
    with (output / 'review.xlsx').open('xb') as handle:
        workbook.save(handle)
    with (output / 'diagnostics.jsonl').open('x', encoding='utf-8') as handle:
        for issue in diagnostics:
            handle.write(json.dumps(issue, ensure_ascii=False) + '\n')
    stats['candidates'] = count
    stats['diagnostics'] = len(diagnostics)
    (output / 'stats.json').write_text(json.dumps(stats, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for source in ('grp', 'wwf', 'wri'):
        parser.add_argument('--' + source, type=Path, default=HERE / (source + '.jsonl'))
    parser.add_argument('--output-dir', type=Path, required=True, help='New directory for all review artifacts')
    parser.add_argument('--start', type=date.fromisoformat, default=START)
    parser.add_argument('--end', type=date.fromisoformat, default=END)
    args = parser.parse_args()
    stats = prepare({s: getattr(args, s) for s in ('grp', 'wwf', 'wri')}, args.output_dir, args.start, args.end)
    print(json.dumps(stats, indent=2))
    print('Review diagnostics.jsonl and the full text files before making any decisions.')


if __name__ == '__main__':
    main()