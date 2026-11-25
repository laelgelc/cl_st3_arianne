#!/usr/bin/env python3
"""Compile a seeded sample of approved candidates to a new corpus directory."""
import argparse
import hashlib
import json
import os
import random
import tempfile
from pathlib import Path


def import_review(manifest, spreadsheet, output):
    """Validate the entire review sheet before publishing a new manifest."""
    from openpyxl import load_workbook

    columns = ('candidate_id', 'text', 'publication_datetime_utc', 'review_status', 'review_notes')
    rows = [json.loads(line) for line in manifest.read_text(encoding='utf-8').splitlines() if line.strip()]
    original = {}
    for row in rows:
        cid = row.get('candidate_id')
        if not isinstance(cid, str) or not cid or cid in original:
            raise ValueError('Candidate IDs must be unique nonempty strings')
        original[cid] = row
    workbook = load_workbook(spreadsheet, data_only=False, read_only=True)
    try:
        sheet = workbook['Review']
        iterator = sheet.iter_rows()
        header = next(iterator, ())
        if tuple(cell.value for cell in header) != columns:
            raise ValueError('Invalid review columns')
        seen = set()
        for cells in iterator:
            if all(cell.value is None for cell in cells):
                continue
            if len(cells) != len(columns) or any(cell.data_type == 'f' for cell in cells):
                raise ValueError('Invalid row or formula in review sheet')
            cid, text, published, status, notes = (cell.value for cell in cells)
            if not isinstance(cid, str) or cid not in original or cid in seen:
                raise ValueError(f'Unknown or duplicate candidate ID: {cid}')
            row = original[cid]
            if text != row.get('text') or published != row.get('publication_datetime_utc'):
                raise ValueError(f'Changed source data for {cid}')
            if status not in ('pending', 'approved', 'rejected') or not isinstance(notes, (str, type(None))):
                raise ValueError(f'Invalid review decision for {cid}')
            seen.add(cid)
            row['review_status'], row['review_notes'] = status, notes or ''
        if seen != set(original):
            raise ValueError('Review sheet is missing candidate IDs')
    finally:
        workbook.close()
    # Publish a complete new file without overwriting existing review decisions.
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent, delete=False) as out:
            temp = Path(out.name)
            for row in rows:
                out.write(json.dumps(row, ensure_ascii=False) + '\n')
            out.flush()
            os.fsync(out.fileno())
        os.link(temp, output)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def compile_corpus(input_path, output, stratum, count, seed):
    if count <= 0:
        raise ValueError('Count must be positive')
    data = input_path.read_bytes()
    candidates = []
    seen = set()
    for line in data.decode('utf-8').splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        cid = row.get('candidate_id')
        if not isinstance(cid, str) or not cid or cid in seen:
            raise ValueError('Candidate IDs must be unique nonempty strings')
        seen.add(cid)
        if row.get('review_status') not in ('pending', 'approved', 'rejected'):
            raise ValueError(f'Invalid review status for {cid}')
        if row.get('stratum') == stratum and row['review_status'] == 'approved':
            if not all(isinstance(row.get(k), str) and row[k].strip() for k in ('text', 'actor', 'register', 'source', 'source_id')):
                raise ValueError(f'Incomplete candidate {cid}')
            candidates.append(row)
    if len(candidates) < count:
        raise ValueError(f'Need {count} approved candidates; found {len(candidates)}')
    if not stratum or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in stratum):
        raise ValueError('Invalid stratum code')
    selected = random.Random(seed).sample(sorted(candidates, key=lambda x: x['candidate_id']), count)
    output.mkdir(parents=True, exist_ok=False)
    target = output / 'human' / stratum
    target.mkdir(parents=True)
    manifest = []
    for row in selected:
        # Identity derives from source identity rather than sampling order.
        unit = stratum + '-' + hashlib.sha256(row['candidate_id'].encode('utf-8')).hexdigest()
        rel = Path('human') / stratum / (unit + '.txt')
        (output / rel).write_text(row['text'], encoding='utf-8')
        manifest.append({**{k: v for k, v in row.items() if k != 'text'},
            'unit_id': unit, 'text_id': unit + '-human', 'authorship': 'human',
            'condition': None, 'assigned_model': None, 'filepath': rel.as_posix(),
            'word_count': len(row['text'].split()), 'word_count_method': 'python str.split',
            'token_count': None, 'token_count_method': None,
            'text_sha256': hashlib.sha256(row['text'].encode('utf-8')).hexdigest()})
    with (output / 'manifest.ndjson').open('x', encoding='utf-8') as out:
        for row in manifest:
            out.write(json.dumps(row, ensure_ascii=False) + '\n')
    (output / 'sampling.json').write_text(json.dumps({'method': 'random.Random.sample over candidate_id sorted approved records',
        'seed': seed, 'stratum': stratum, 'count': count, 'eligible_count': len(candidates),
        'candidate_manifest': str(input_path), 'candidate_sha256': hashlib.sha256(data).hexdigest()}, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--stratum', required=True)
    parser.add_argument('--count', required=True, type=int)
    parser.add_argument('--seed', required=True, type=int)
    parser.add_argument('--review-xlsx', type=Path, help='Import review decisions before sampling')
    parser.add_argument('--reviewed-manifest', type=Path, help='New NDJSON path for validated decisions')
    args = parser.parse_args()
    if bool(args.review_xlsx) != bool(args.reviewed_manifest):
        parser.error('--review-xlsx and --reviewed-manifest must be supplied together')
    if args.review_xlsx:
        import_review(args.candidates, args.review_xlsx, args.reviewed_manifest)
    compile_corpus(args.reviewed_manifest or args.candidates, args.output, args.stratum, args.count, args.seed)


if __name__ == '__main__':
    main()