#!/usr/bin/env python3
"""Generate and review summaries. Run with --help for commands and options.

Generate checkpoints, export a JSONL review file, edit only review_status,
review_notes and summary, then import into a new JSONL file. Review statuses are pending,
approved and rejected. All paths are explicit; no corpus files are modified.
Requires the openai Python package only for generation.
"""
import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path, PurePosixPath


PROMPT = Path(__file__).with_name('summary_prompt.md')
MODEL = 'gpt-6.1-terra'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def words(text):
    return len(text.split())


def valid_summary(text):
    if not isinstance(text, str) or not text.strip() or words(text) > 100:
        raise ValueError('Summary must contain 1 to 100 words')
    return text.strip()


def sources(corpus, stratum=None, limit=None):
    if limit is not None and (type(limit) is not int or limit <= 0):
        raise ValueError('Limit must be positive')
    root = corpus.resolve(strict=True)
    rows = []
    ids, paths = set(), set()
    candidates = []
    for line in (root / 'manifest.ndjson').read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get('authorship') != 'human' or (stratum is not None and row.get('stratum') != stratum):
            continue
        uid = row.get('unit_id')
        if not isinstance(uid, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', uid) or uid in ids:
            raise ValueError(f'Invalid or duplicate unit ID: {uid}')
        ids.add(uid)
        candidates.append(row)
    candidates.sort(key=lambda row: row['unit_id'])
    for row in candidates[:limit]:
        uid, name, sha = row.get('unit_id'), row.get('filepath'), row.get('text_sha256')
        if not isinstance(name, str) or '\\' in name:
            raise ValueError(f'Invalid source path for {uid}')
        rel = PurePosixPath(name)
        if rel.is_absolute() or '..' in rel.parts or not rel.parts or rel.parts[0] != 'human' or name in paths:
            raise ValueError(f'Unsafe or duplicate source path: {name}')
        path = (root / name).resolve(strict=True)
        if not path.is_relative_to(root / 'human') or not path.is_file():
            raise ValueError(f'Unsafe source path: {name}')
        data = path.read_bytes()
        if not isinstance(sha, str) or digest(data) != sha:
            raise ValueError(f'Source hash mismatch: {uid}')
        text = data.decode('utf-8')
        paths.add(name)
        rows.append({'unit_id': uid, 'filepath': name, 'source_sha256': sha,
                     'source_word_count': words(text), 'stratum': row.get('stratum'),
                     'source_id': row.get('source_id'), 'text': text})
    return rows


def publish(path, data):
    """Publish complete bytes exclusively, leaving an existing file untouched."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
            temp = Path(out.name)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.link(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def encoded(row):
    return (json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')


def checkpoint_path(directory, uid):
    return directory / (uid + '.json')


def metadata(source, prompt, model, max_output_tokens):
    return {key: source[key] for key in ('unit_id', 'filepath', 'source_sha256', 'source_word_count', 'stratum', 'source_id')} | {
        'model': model, 'prompt': prompt, 'prompt_sha256': digest(prompt.encode('utf-8')),
        'max_output_tokens': max_output_tokens,
        'word_count_method': 'python str.split'}


def load_checkpoint(path, expected=None):
    row = json.loads(path.read_text(encoding='utf-8'))
    if expected is not None and any(row.get(k) != v for k, v in expected.items()):
        raise ValueError(f'Checkpoint provenance mismatch: {path}')
    summary = valid_summary(row.get('summary'))
    if row.get('summary_word_count') != words(summary) or row.get('review_status') != 'pending':
        raise ValueError(f'Invalid checkpoint: {path}')
    return row


def generate(corpus, directory, prompt_path=PROMPT, model=MODEL, client=None, stratum=None, limit=None, max_output_tokens=2000):
    prompt = prompt_path.read_text(encoding='utf-8')
    if not prompt.strip() or not model.strip():
        raise ValueError('Prompt and model must not be empty')
    if type(max_output_tokens) is not int or max_output_tokens <= 0:
        raise ValueError('max_output_tokens must be positive')
    items = sources(corpus, stratum, limit)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for item in items:
        expected = metadata(item, prompt, model, max_output_tokens)
        target = checkpoint_path(directory, item['unit_id'])
        if target.exists() or target.is_symlink():
            load_checkpoint(target, expected)
            continue
        if client is None:
            from openai import OpenAI
            client = OpenAI()
        response = client.responses.create(model=model, instructions=prompt, input=item['text'], max_output_tokens=max_output_tokens)
        if getattr(response, 'status', None) != 'completed':
            raise ValueError(f'Incomplete or failed API response for {item["unit_id"]}')
        summary = valid_summary(getattr(response, 'output_text', None))
        row = {**expected, 'summary': summary, 'summary_word_count': words(summary),
               'review_status': 'pending', 'review_notes': '',
               'response_id': getattr(response, 'id', None), 'actual_model': getattr(response, 'model', None)}
        publish(target, encoded(row))


def review_rows(corpus, directory, stratum=None, limit=None):
    rows = []
    for item in sources(corpus, stratum, limit):
        path = checkpoint_path(directory, item['unit_id'])
        row = load_checkpoint(path)
        for key in ('unit_id', 'filepath', 'source_sha256', 'source_word_count', 'stratum', 'source_id'):
            if row.get(key) != item[key]:
                raise ValueError(f'Checkpoint source mismatch: {path}')
        rows.append(row)
    return rows


def export_review(corpus, directory, output, stratum=None, limit=None):
    publish(output, b''.join(encoded(row) for row in review_rows(corpus, directory, stratum, limit)))


def import_review(corpus, directory, review, output, stratum=None, limit=None):
    originals = {row['unit_id']: row for row in review_rows(corpus, directory, stratum, limit)}
    reviewed = []
    seen = set()
    for line in Path(review).read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        uid = row.get('unit_id')
        if uid not in originals or uid in seen:
            raise ValueError(f'Unknown or duplicate unit: {uid}')
        original = originals[uid]
        if set(row) != set(original) or any(row[k] != v for k, v in original.items() if k not in ('summary', 'review_status', 'review_notes')):
            raise ValueError(f'Changed immutable review fields: {uid}')
        if row['review_status'] not in ('pending', 'approved', 'rejected'):
            raise ValueError(f'Invalid review status: {uid}')
        if not isinstance(row['review_notes'], str):
            raise ValueError(f'Invalid review notes: {uid}')
        row['summary'] = valid_summary(row['summary'])
        row['summary_word_count'] = words(row['summary'])
        row['generated_summary'] = original['summary']
        row['checkpoint_sha256'] = digest(checkpoint_path(directory, uid).read_bytes())
        reviewed.append(row)
        seen.add(uid)
    if seen != set(originals):
        raise ValueError('Review is missing units')
    publish(output, b''.join(encoded(row) for row in reviewed))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('generate', 'export-review', 'import-review'):
        command = sub.add_parser(name)
        command.add_argument('--corpus', type=Path, required=True)
        command.add_argument('--checkpoints', type=Path, required=True)
        command.add_argument('--stratum', help='Select a single stratum')
        command.add_argument('--limit', type=int, help='Select the first N matching units sorted by unit ID')
        if name == 'generate':
            command.add_argument('--prompt', type=Path, default=PROMPT)
            command.add_argument('--model', default=MODEL)
            command.add_argument('--max-output-tokens', type=int, default=2000)
        else:
            command.add_argument('--output', type=Path, required=True)
            if name == 'import-review':
                command.add_argument('--review', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'generate':
        generate(args.corpus, args.checkpoints, args.prompt, args.model, stratum=args.stratum, limit=args.limit, max_output_tokens=args.max_output_tokens)
    elif args.command == 'export-review':
        export_review(args.corpus, args.checkpoints, args.output, args.stratum, args.limit)
    else:
        import_review(args.corpus, args.checkpoints, args.review, args.output, args.stratum, args.limit)


if __name__ == '__main__':
    main()