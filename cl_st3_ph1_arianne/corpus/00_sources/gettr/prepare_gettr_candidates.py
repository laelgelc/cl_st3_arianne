#!/usr/bin/env python3
"""Prepare review-pending Phase 2 candidates from the selected GETTR manifest."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def prepare(source, output):
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    candidates = []
    ids = set()
    for number, line in enumerate(raw.decode('utf-8').splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        post_id, text, timestamp = record.get('_id'), record.get('text'), record.get('cdate')
        if not isinstance(post_id, str) or not post_id or post_id in ids:
            raise ValueError(f'Invalid or duplicate ID on line {number}')
        if not isinstance(text, str) or not text.strip() or isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            raise ValueError(f'Invalid text or timestamp on line {number}')
        date = datetime.fromtimestamp(timestamp / 1000, timezone.utc)
        if not datetime(2015, 11, 1, tzinfo=timezone.utc) <= date < datetime(2022, 12, 1, tzinfo=timezone.utc):
            raise ValueError(f'Date outside research window on line {number}')
        ids.add(post_id)
        candidates.append({'schema_version': 1, 'candidate_id': 'gettr:' + post_id,
            'stratum': 'social-post', 'actor': 'social media', 'register': 'microblog post',
            'source': 'GETTR', 'source_id': post_id, 'source_url': None,
            'publication_datetime_utc': date.isoformat(), 'text': text,
            'source_manifest': source.name, 'source_sha256': digest,
            'review_status': 'pending', 'review_notes': '',
            'review_warning': 'Verify English, duplicates, completeness and GETTR origin; cdate may reflect imported content.'})
    with output.open('x', encoding='utf-8') as out:
        for candidate in candidates:
            out.write(json.dumps(candidate, ensure_ascii=False) + '\n')
    return len(candidates)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=HERE / 'gettr.ndjson')
    parser.add_argument('--output', type=Path, default=HERE / 'gettr_candidates.ndjson')
    args = parser.parse_args()
    print(f'Prepared {prepare(args.input, args.output)} candidates for review')


if __name__ == '__main__':
    main()