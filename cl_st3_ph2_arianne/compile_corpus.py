#!/usr/bin/env python3
"""Compile a seeded sample of approved candidates into a corpus directory."""
import argparse
import hashlib
import json
import os
import random
import re
import shutil
import tempfile
from pathlib import Path


def normalize_newlines(value):
    return value.replace('\r\n', '\n').replace('\r', '\n') if isinstance(value, str) else value


def import_review(manifest, spreadsheet, output):
    """Validate the entire review sheet before publishing a new manifest."""
    from openpyxl import load_workbook

    columns = ('candidate_id', 'text', 'publication_datetime_utc', 'review_status', 'review_notes')
    linked_columns = ('candidate_id', 'text_preview', 'publication_datetime_utc', 'review_status', 'review_notes', 'text_sha256', 'full_text_path')
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
        header_values = tuple(cell.value for cell in header)
        if header_values not in (columns, linked_columns):
            raise ValueError('Invalid review columns')
        linked = header_values == linked_columns
        seen = set()
        for cells in iterator:
            if all(cell.value is None for cell in cells):
                continue
            if len(cells) != len(header_values) or any(cell.data_type == 'f' for cell in cells):
                raise ValueError('Invalid row or formula in review sheet')
            values = [cell.value for cell in cells]
            cid, text, published, status, notes = values[:5]
            if not isinstance(cid, str) or cid not in original or cid in seen:
                raise ValueError(f'Unknown or duplicate candidate ID: {cid}')
            row = original[cid]
            original_text = row.get('text')
            if linked:
                if not isinstance(original_text, str):
                    raise ValueError(f'Invalid source text for {cid}')
                digest = hashlib.sha256(original_text.encode('utf-8')).hexdigest()
                path = row.get('review_source_path')
                preview = normalize_newlines(original_text)[:200]
                preview = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]', lambda match: f'\\u{ord(match.group()):04x}', preview)
                if (values[5] != digest or row.get('source_text_sha256') != digest or
                        not isinstance(path, str) or not Path(path).is_absolute() or values[6] != path or
                        text != preview):
                    raise ValueError(f'Changed source data for {cid}')
                if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
                    raise ValueError(f'Changed source file for {cid}')
            elif normalize_newlines(text) != normalize_newlines(original_text):
                raise ValueError(f'Changed source data for {cid}')
            if published != row.get('publication_datetime_utc'):
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
        try:
            os.link(temp, output)
        except FileExistsError:
            if output.is_symlink() or not output.is_file() or output.read_bytes() != temp.read_bytes():
                raise FileExistsError(f'Existing reviewed manifest differs: {output}; choose a new --reviewed-manifest path')
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
    existing = output.exists()
    if existing and output.is_dir() and not output.is_symlink() and not any(output.iterdir()):
        existing = False
    old_manifest = b''
    old_sampling = None
    records = []
    sampling = {}
    if existing:
        if not output.is_dir() or not (output / 'manifest.ndjson').is_file() or not (output / 'sampling.json').is_file():
            raise ValueError('Existing output is not a complete corpus')
        old_manifest = (output / 'manifest.ndjson').read_bytes()
        records = [json.loads(line) for line in old_manifest.decode('utf-8').splitlines() if line.strip()]
        old_sampling = (output / 'sampling.json').read_bytes()
        previous = json.loads(old_sampling)
        if 'stratum' in previous:
            sampling = {previous['stratum']: previous}
        else:
            sampling = previous['strata']
        if stratum in sampling or any(row.get('stratum') == stratum for row in records) or (output / 'human' / stratum).exists():
            raise FileExistsError(f'Stratum already exists: {stratum}')
        for field in ('candidate_id', 'unit_id', 'text_id', 'filepath'):
            values = [row.get(field) for row in records]
            if any(not isinstance(value, str) or not value for value in values) or len(values) != len(set(values)):
                raise ValueError(f'Invalid or duplicate existing {field}')
        if {row['candidate_id'] for row in selected} & {row['candidate_id'] for row in records}:
            raise ValueError('Candidate ID already exists in corpus')
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
    manifest = []
    for row in selected:
        # Identity derives from source identity rather than sampling order.
        unit = stratum + '-' + hashlib.sha256(row['candidate_id'].encode('utf-8')).hexdigest()
        rel = Path('human') / stratum / (unit + '.txt')
        manifest.append({**{k: v for k, v in row.items() if k != 'text'},
            'unit_id': unit, 'text_id': unit + '-human', 'authorship': 'human',
            'condition': None, 'assigned_model': None, 'filepath': rel.as_posix(),
            'word_count': len(row['text'].split()), 'word_count_method': 'python str.split',
            'token_count': None, 'token_count_method': None,
            'text_sha256': hashlib.sha256(row['text'].encode('utf-8')).hexdigest()})
    for field in ('unit_id', 'text_id', 'filepath'):
        if {row[field] for row in manifest} & {row[field] for row in records}:
            raise ValueError(f'Duplicate {field} in corpus')
    sampling[stratum] = {'method': 'random.Random.sample over candidate_id sorted approved records',
        'seed': seed, 'stratum': stratum, 'count': count, 'eligible_count': len(candidates),
        'candidate_manifest': str(input_path), 'candidate_sha256': hashlib.sha256(data).hexdigest()}
    # Stage all new files before touching an existing corpus. Roll back ordinary
    # publication errors; interrupted processes may require manual recovery.
    with tempfile.TemporaryDirectory(prefix='.compile-', dir=output.parent) as temp:
        stage = Path(temp)
        target = stage / 'human' / stratum
        target.mkdir(parents=True)
        for row, item in zip(selected, manifest):
            (stage / item['filepath']).write_text(row['text'], encoding='utf-8')
        merged = old_manifest + (b'\n' if old_manifest and not old_manifest.endswith(b'\n') else b'')
        merged += ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in manifest).encode('utf-8')
        (stage / 'manifest.ndjson').write_bytes(merged)
        (stage / 'sampling.json').write_text(json.dumps({'strata': sampling}, indent=2) + '\n', encoding='utf-8')
        if not existing:
            os.rename(stage, output)
            return
        human = output / 'human'
        if not human.is_dir():
            raise ValueError('Existing corpus has no human directory')
        destination = human / stratum
        moved = False
        try:
            os.rename(target, destination)
            moved = True
            os.replace(stage / 'manifest.ndjson', output / 'manifest.ndjson')
            os.replace(stage / 'sampling.json', output / 'sampling.json')
        except Exception:
            if moved:
                shutil.rmtree(destination)
            (output / 'manifest.ndjson').write_bytes(old_manifest)
            (output / 'sampling.json').write_bytes(old_sampling)
            raise


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