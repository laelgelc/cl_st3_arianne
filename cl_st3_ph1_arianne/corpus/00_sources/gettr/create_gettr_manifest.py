#!/usr/bin/env python3
"""Create a GETTR manifest from local NDJSON; requires langdetect==1.0.9."""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from langdetect import DetectorFactory, LangDetectException, detect

HERE = Path(__file__).resolve().parent
START = datetime(2015, 11, 1, tzinfo=timezone.utc).timestamp() * 1000
END = datetime(2022, 12, 1, tzinfo=timezone.utc).timestamp() * 1000
URL = re.compile(r'https?://\S+', re.IGNORECASE)
DetectorFactory.seed = 0


def select(record, seen):
    timestamp = record.get('cdate')
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not START <= timestamp < END:
        return None
    text = record.get('txt')
    if not isinstance(text, str) or not text.strip() or 'climate change' not in text.casefold() or text in seen:
        return None
    try:
        if detect(URL.sub('', text)) != 'en':
            return None
    except LangDetectException:
        return None
    seen.add(text)
    return {**record, 'text': text, 'word_count': len(text.split())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=HERE / 'gettr_2021-07.ndjson')
    parser.add_argument('--output', type=Path, default=HERE / 'gettr.ndjson')
    args = parser.parse_args()
    seen = set()
    total = selected = 0
    with args.input.open(encoding='utf-8') as source, args.output.open('x', encoding='utf-8') as output:
        for line in source:
            total += 1
            record = select(json.loads(line), seen)
            if record is not None:
                output.write(json.dumps(record, ensure_ascii=False) + '\n')
                selected += 1
    print(f'Selected {selected} of {total} records')


if __name__ == '__main__':
    main()