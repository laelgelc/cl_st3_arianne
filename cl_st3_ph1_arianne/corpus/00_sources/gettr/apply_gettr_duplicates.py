#!/usr/bin/env python3
"""Apply candidate decisions to an original GETTR manifest, keeping the first row per group."""

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def apply_decisions(records, pairs):
    parents = list(range(len(records)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for pair in pairs:
        indices = []
        for side in ('left', 'right'):
            row = pair[f'{side}_row']
            if isinstance(row, bool) or not isinstance(row, int) or not 1 <= row <= len(records):
                raise ValueError(f'Invalid {side} row: {row}')
            record = records[row - 1]
            if record.get('_id') != pair[f'{side}_id'] or record['text'] != pair[f'{side}_text']:
                raise ValueError(f'Candidate {side} row {row} does not match the input manifest')
            indices.append(row - 1)
        if indices[0] == indices[1]:
            raise ValueError('A candidate pair cannot reference the same row twice')
        left, right = map(root, indices)
        parents[max(left, right)] = min(left, right)

    reviewed = [{**pair, 'decision': 'remove duplicate', 'notes': 'potential duplicate'} for pair in pairs]
    return [record for index, record in enumerate(records) if root(index) == index], reviewed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=HERE / 'gettr_before_near_dedup.ndjson')
    parser.add_argument('--candidates', type=Path, default=HERE / 'gettr_duplicate_candidates.ndjson')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report-output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() == args.report_output.resolve():
        parser.error('Output paths must differ')
    with args.input.open(encoding='utf-8') as source:
        records = [json.loads(line) for line in source if line.strip()]
    with args.candidates.open(encoding='utf-8') as source:
        pairs = [json.loads(line) for line in source if line.strip()]
    selected, reviewed = apply_decisions(records, pairs)
    with args.output.open('x', encoding='utf-8') as output:
        for record in selected:
            output.write(json.dumps(record, ensure_ascii=False) + '\n')
    with args.report_output.open('x', encoding='utf-8') as output:
        for pair in reviewed:
            output.write(json.dumps(pair, ensure_ascii=False) + '\n')
    print(f'Kept {len(selected)} of {len(records)} posts; marked {len(reviewed)} pairs')


if __name__ == '__main__':
    main()