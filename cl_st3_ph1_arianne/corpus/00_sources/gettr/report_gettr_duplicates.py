#!/usr/bin/env python3
"""Report possible GETTR reposts for manual review without changing the manifest."""

import argparse
import html
import json
import re
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
URL = re.compile(r'https?://\S+', re.IGNORECASE)
REPOST = re.compile(r'\b(?:rt|repost)(?:\s+@\w+)?\s*:', re.IGNORECASE)


def normalize(text):
    text = html.unescape(text).casefold()
    text = URL.sub(' ', text)
    text = REPOST.sub(' ', text)
    return ' '.join(text.split())


def candidates(records, threshold=0.85, min_words=5):
    normalized = [normalize(record['text']) for record in records]
    for i, j in combinations(range(len(records)), 2):
        left, right = normalized[i], normalized[j]
        if min(len(left.split()), len(right.split())) < min_words:
            continue
        ratio = SequenceMatcher(None, left, right, autojunk=False).ratio()
        # A complete embedded repost may have additional commentary around it.
        containment = min(len(left), len(right)) / max(len(left), len(right)) if left in right or right in left else 0
        if ratio >= threshold or containment >= threshold:
            yield {
                'left_row': i + 1, 'left_id': records[i].get('_id'), 'left_text': records[i]['text'],
                'right_row': j + 1, 'right_id': records[j].get('_id'), 'right_text': records[j]['text'],
                'similarity': round(ratio, 4), 'containment': round(containment, 4),
                'decision': '', 'notes': '',
            }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=HERE / 'gettr.ndjson')
    parser.add_argument('--output', type=Path, default=HERE / 'gettr_duplicate_candidates.ndjson')
    parser.add_argument('--threshold', type=float, default=0.85)
    parser.add_argument('--min-words', type=int, default=5)
    args = parser.parse_args()
    if not 0 < args.threshold <= 1 or args.min_words < 1:
        parser.error('threshold must be in (0, 1] and min-words must be positive')
    with args.input.open(encoding='utf-8') as source:
        records = [json.loads(line) for line in source if line.strip()]
    pairs = sorted(candidates(records, args.threshold, args.min_words),
                   key=lambda pair: (-max(pair['similarity'], pair['containment']), pair['left_row'], pair['right_row']))
    with args.output.open('x', encoding='utf-8') as output:
        for pair in pairs:
            output.write(json.dumps(pair, ensure_ascii=False) + '\n')
    print(f'Reported {len(pairs)} candidate pairs from {len(records)} posts; no posts removed')


if __name__ == '__main__':
    main()