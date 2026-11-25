#!/usr/bin/env python3
"""Compile a seeded sample of approved candidates to a new corpus directory."""
import argparse
import hashlib
import json
import random
from pathlib import Path


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
    args = parser.parse_args()
    compile_corpus(args.candidates, args.output, args.stratum, args.count, args.seed)


if __name__ == '__main__':
    main()