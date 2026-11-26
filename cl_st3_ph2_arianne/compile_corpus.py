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


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def normalize_newlines(value):
    return value.replace('\r\n', '\n').replace('\r', '\n') if isinstance(value, str) else value


def corpus_record(row, stratum):
    unit = stratum + '-' + hashlib.sha256(row['candidate_id'].encode('utf-8')).hexdigest()
    rel = Path('human') / stratum / (unit + '.txt')
    provenance = {k: v for k, v in row.items() if k != 'text'}
    for field in ('source_manifest', 'review_source_path'):
        value = provenance.get(field)
        if isinstance(value, str) and Path(value).is_absolute():
            provenance[field] = os.path.relpath(value, PROJECT_ROOT)
    return {**provenance,
        'unit_id': unit, 'text_id': unit + '-human', 'authorship': 'human',
        'condition': None, 'assigned_model': None, 'filepath': rel.as_posix(),
        'word_count': len(row['text'].split()), 'word_count_method': 'python str.split',
        'token_count': None, 'token_count_method': None,
        'text_sha256': hashlib.sha256(row['text'].encode('utf-8')).hexdigest()}


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
                        not isinstance(path, str) or not path or values[6] != path or
                        text != preview):
                    raise ValueError(f'Changed source data for {cid}')
                if hashlib.sha256((PROJECT_ROOT / path).read_bytes()).hexdigest() != digest:
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


def compile_corpus(input_path, output, stratum, count, seed, source_quotas=None):
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
        # Early ONU review bundles used a noncanonical stratum code.
        if (row.get('stratum') == 'treaty-segment' and cid.startswith('onu:')
                and row.get('actor') == 'government' and row.get('register') == 'treaty'):
            row['stratum'] = 'gov-treaty'
        if row.get('stratum') == stratum and row['review_status'] == 'approved':
            if not all(isinstance(row.get(k), str) and row[k].strip() for k in ('text', 'actor', 'register', 'source', 'source_id')):
                raise ValueError(f'Incomplete candidate {cid}')
            candidates.append(row)
    if len(candidates) < count:
        raise ValueError(f'Need {count} approved candidates; found {len(candidates)}')
    if not stratum or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in stratum):
        raise ValueError('Invalid stratum code')
    rng = random.Random(seed)
    if source_quotas is None:
        selected = rng.sample(sorted(candidates, key=lambda x: x['candidate_id']), count)
    else:
        if not source_quotas or any(not isinstance(k, str) or not k.strip() or type(v) is not int or v <= 0 for k, v in source_quotas.items()) or sum(source_quotas.values()) != count:
            raise ValueError('Source quotas must be positive and sum to count')
        selected = []
        for source, quota in sorted(source_quotas.items()):
            pool = sorted((row for row in candidates if row['source'] == source), key=lambda x: x['candidate_id'])
            if len(pool) < quota:
                raise ValueError(f'Need {quota} approved candidates for {source}; found {len(pool)}')
            selected.extend(rng.sample(pool, quota))
    existing = output.exists()
    if existing and output.is_dir() and not output.is_symlink() and not any(output.iterdir()):
        existing = False
    old_manifest = b''
    old_sampling = None
    records = []
    sampling = {}
    sampling_extra = {}
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
            sampling_extra = {k: v for k, v in previous.items() if k != 'strata'}
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
        manifest.append(corpus_record(row, stratum))
    for field in ('unit_id', 'text_id', 'filepath'):
        if {row[field] for row in manifest} & {row[field] for row in records}:
            raise ValueError(f'Duplicate {field} in corpus')
    sampling[stratum] = {'method': 'random.Random.sample over candidate_id sorted approved records',
        'seed': seed, 'stratum': stratum, 'count': count, 'eligible_count': len(candidates),
        'candidate_manifest': os.path.relpath(input_path.absolute(), PROJECT_ROOT), 'candidate_sha256': hashlib.sha256(data).hexdigest()}
    if source_quotas is not None:
        sampling[stratum]['method'] = 'random.Random.sample within each source in sorted source and candidate_id order'
        sampling[stratum]['source_quotas'] = dict(sorted(source_quotas.items()))
        sampling[stratum]['eligible_by_source'] = {source: sum(row['source'] == source for row in candidates) for source in sorted(source_quotas)}
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
        (stage / 'sampling.json').write_text(json.dumps({**sampling_extra, 'strata': sampling}, indent=2) + '\n', encoding='utf-8')
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


def replace_unit(input_path, output, candidate_id, seed):
    """Replace one rejected candidate; input_path must be a validated review manifest."""
    if output.is_symlink() or not output.is_dir():
        raise ValueError('Existing output must be a corpus directory, not a symlink')
    for name in ('manifest.ndjson', 'sampling.json'):
        if (output / name).is_symlink() or not (output / name).is_file():
            raise ValueError('Existing output is not a complete corpus')
    manifest_lines = (output / 'manifest.ndjson').read_bytes().splitlines(keepends=True)
    records = [json.loads(line) for line in manifest_lines if line.strip()]
    for field in ('candidate_id', 'unit_id', 'text_id', 'filepath'):
        values = [row.get(field) for row in records]
        if any(not isinstance(value, str) or not value for value in values) or len(values) != len(set(values)):
            raise ValueError(f'Invalid or duplicate existing {field}')
    matches = [row for row in records if row['candidate_id'] == candidate_id]
    if len(matches) != 1:
        raise ValueError('Candidate to replace must exist exactly once in corpus')
    removed = matches[0]
    stratum = removed.get('stratum')
    if not isinstance(stratum, str) or not stratum or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in stratum):
        raise ValueError('Invalid stratum code')
    old_path = Path(removed['filepath'])
    if old_path.is_absolute() or old_path.parts[:2] != ('human', stratum) or len(old_path.parts) != 3:
        raise ValueError('Unsafe corpus filepath')
    old_file = output / old_path
    if any(p.is_symlink() for p in (output / 'human', output / 'human' / stratum, old_file)) or not old_file.is_file():
        raise ValueError('Unsafe or missing corpus text')
    if hashlib.sha256(old_file.read_bytes()).hexdigest() != removed.get('text_sha256'):
        raise ValueError('Corpus text hash mismatch')
    sampling = json.loads((output / 'sampling.json').read_text(encoding='utf-8'))
    if 'stratum' in sampling:
        sampling = {'strata': {sampling['stratum']: sampling}}
    strata = sampling['strata']
    if stratum not in strata:
        raise ValueError('Missing stratum sampling history')
    history = sampling.setdefault('replacements', [])
    if not isinstance(history, list):
        raise ValueError('Invalid replacement history')
    data = input_path.read_bytes()
    candidates = [json.loads(line) for line in data.decode('utf-8').splitlines() if line.strip()]
    ids = [row.get('candidate_id') for row in candidates]
    if any(not isinstance(cid, str) or not cid for cid in ids) or len(ids) != len(set(ids)):
        raise ValueError('Candidate IDs must be unique nonempty strings')
    if any(row.get('review_status') not in ('pending', 'approved', 'rejected') for row in candidates):
        raise ValueError('Invalid review status')
    rejected = [row for row in candidates if row['candidate_id'] == candidate_id]
    if len(rejected) != 1 or rejected[0]['review_status'] != 'rejected':
        raise ValueError('Candidate to replace must be rejected in reviewed manifest')
    if not isinstance(rejected[0].get('text'), str) or hashlib.sha256(rejected[0]['text'].encode('utf-8')).hexdigest() != removed['text_sha256']:
        raise ValueError('Rejected candidate text does not match corpus')
    existing_ids = {row['candidate_id'] for row in records}
    same_source = 'source_quotas' in strata[stratum]
    eligible = []
    for row in candidates:
        candidate_stratum = row.get('stratum')
        if candidate_stratum == 'treaty-segment' and row['candidate_id'].startswith('onu:') and row.get('actor') == 'government' and row.get('register') == 'treaty':
            candidate_stratum = 'gov-treaty'
        if candidate_stratum != stratum or row['review_status'] != 'approved' or row['candidate_id'] in existing_ids or (same_source and row.get('source') != removed.get('source')):
            continue
        if not all(isinstance(row.get(k), str) and row[k].strip() for k in ('text', 'actor', 'register', 'source', 'source_id')):
            raise ValueError(f'Incomplete candidate {row["candidate_id"]}')
        eligible.append({**row, 'stratum': candidate_stratum})
    if not eligible:
        raise ValueError('No eligible approved replacement candidates')
    selected = random.Random(seed).choice(sorted(eligible, key=lambda row: row['candidate_id']))
    replacement = corpus_record(selected, stratum)
    for field in ('unit_id', 'text_id', 'filepath'):
        if replacement[field] in {row[field] for row in records}:
            raise ValueError(f'Duplicate {field} in corpus')
    history.append({'method': 'random.Random.choice over candidate_id sorted eligible approved records',
        'seed': seed, 'stratum': stratum, 'eligible_count': len(eligible),
        'source_constraint': removed.get('source') if same_source else None,
        'candidate_manifest': os.path.relpath(input_path.absolute(), PROJECT_ROOT),
        'candidate_sha256': hashlib.sha256(data).hexdigest(),
        'removed_candidate_id': candidate_id, 'removed_unit_id': removed['unit_id'],
        'replacement_candidate_id': replacement['candidate_id'], 'replacement_unit_id': replacement['unit_id']})
    work = Path(tempfile.mkdtemp(prefix='.replace-', dir=output.parent))
    backup = work / 'backup'
    published = False
    try:
        stage = work / 'staged'
        shutil.copytree(output, stage, symlinks=True)
        (stage / old_path).unlink()
        with (stage / replacement['filepath']).open('x', encoding='utf-8') as out:
            out.write(selected['text'])
        new_line = (json.dumps(replacement, ensure_ascii=False) + '\n').encode('utf-8')
        lines = [new_line if line.strip() and json.loads(line).get('candidate_id') == candidate_id else line for line in manifest_lines]
        (stage / 'manifest.ndjson').write_bytes(b''.join(lines))
        (stage / 'sampling.json').write_text(json.dumps(sampling, indent=2) + '\n', encoding='utf-8')
        os.rename(output, backup)
        try:
            os.rename(stage, output)
            published = True
        except Exception:
            os.rename(backup, output)
            raise
    finally:
        if published or not backup.exists():
            shutil.rmtree(work)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--stratum')
    parser.add_argument('--count', type=int)
    parser.add_argument('--seed', required=True, type=int)
    parser.add_argument('--replace-candidate', help='Replace this rejected corpus candidate (requires review import)')
    parser.add_argument('--review-xlsx', type=Path, help='Import review decisions before sampling')
    parser.add_argument('--reviewed-manifest', type=Path, help='New NDJSON path for validated decisions')
    parser.add_argument('--source-quota', action='append', metavar='SOURCE=COUNT', help='Sample a fixed count per source; repeat for each source')
    args = parser.parse_args()
    if bool(args.review_xlsx) != bool(args.reviewed_manifest):
        parser.error('--review-xlsx and --reviewed-manifest must be supplied together')
    if args.replace_candidate:
        if not args.review_xlsx or args.stratum is not None or args.count is not None or args.source_quota:
            parser.error('--replace-candidate requires review import and excludes --stratum, --count and --source-quota')
        if any(path.resolve().is_relative_to(args.output.resolve()) for path in (args.candidates, args.review_xlsx, args.reviewed_manifest)):
            parser.error('Review inputs and output must be outside the corpus directory')
    elif args.stratum is None or args.count is None:
        parser.error('--stratum and --count are required for compilation')
    quotas = None
    if args.source_quota:
        quotas = {}
        for value in args.source_quota:
            source, separator, amount = value.rpartition('=')
            if not separator or not source.strip() or source != source.strip() or not amount.isdecimal() or int(amount) <= 0 or source in quotas:
                parser.error('Each --source-quota must be a unique SOURCE=positive integer')
            quotas[source] = int(amount)
        if sum(quotas.values()) != args.count:
            parser.error('Source quotas must sum to --count')
    if args.review_xlsx:
        import_review(args.candidates, args.review_xlsx, args.reviewed_manifest)
    if args.replace_candidate:
        replace_unit(args.reviewed_manifest, args.output, args.replace_candidate, args.seed)
    else:
        compile_corpus(args.reviewed_manifest or args.candidates, args.output, args.stratum, args.count, args.seed, quotas)


if __name__ == '__main__':
    main()