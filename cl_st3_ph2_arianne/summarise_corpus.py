#!/usr/bin/env python3
"""Generate and review summaries. Run with --help for commands and options.

Generate checkpoints, export a JSONL or XLSX review file, edit only review_status,
review_notes and summary, then import into a new JSONL file. Review statuses are pending,
approved and rejected. All paths are explicit; no corpus files are modified.
Requires the openai Python package only for generation.
Generation emits JSON lines to stderr: progress, failures, invalid responses and a
run summary. Rerun the same command to retry missing units; valid checkpoints are
reused. Diagnostic records exclude response text, prompts and exception messages.
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path, PurePosixPath


PROMPT = Path(__file__).with_name('summary_prompt.md')
MODEL = 'gpt-6.1-terra'
ENV_FILE = Path(__file__).resolve().parent / 'env' / '.env'


def load_api_key(path):
    """Load a simple OPENAI_API_KEY assignment without overriding the environment."""
    path = Path(path)
    if not path.exists():
        return
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if line.startswith('export '):
            line = line[7:].strip()
        key, separator, value = line.partition('=')
        if separator and key.strip() == 'OPENAI_API_KEY':
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            os.environ.setdefault('OPENAI_API_KEY', value)
            break


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


class GenerationError(Exception):
    """One or more units failed; rerun to retry missing checkpoints."""


def diagnostic(event, **fields):
    print(json.dumps({'event': event, **fields}, sort_keys=True), file=sys.stderr, flush=True)


def exception_diagnostics(error):
    allowed = ('APIError', 'APIStatusError', 'APIConnectionError', 'APITimeoutError',
               'AuthenticationError', 'PermissionDeniedError', 'BadRequestError',
               'NotFoundError', 'ConflictError', 'UnprocessableEntityError',
               'RateLimitError', 'InternalServerError', 'OpenAIError')
    name = type(error).__name__
    result = {'error_type': name if name in allowed else 'unknown'}
    status = getattr(error, 'status_code', None)
    if type(status) is int and 100 <= status <= 599:
        result['http_status'] = status
    return result


def response_diagnostics(response):
    status = getattr(response, 'status', None)
    result = {'status': status if status in ('completed', 'incomplete', 'failed', 'cancelled', 'queued', 'in_progress') else 'unknown'}
    details = getattr(response, 'incomplete_details', None)
    reason = getattr(details, 'reason', None)
    if reason in ('max_output_tokens', 'content_filter'):
        result['reason'] = reason
    usage = getattr(response, 'usage', None)
    for key in ('input_tokens', 'output_tokens', 'total_tokens'):
        value = getattr(usage, key, None)
        if type(value) is int and value >= 0:
            result[key] = value
    return result


def generate(corpus, directory, prompt_path=PROMPT, model=MODEL, client=None, stratum=None, limit=None, max_output_tokens=2000, env_file=ENV_FILE):
    prompt = prompt_path.read_text(encoding='utf-8')
    if not prompt.strip() or not model.strip():
        raise ValueError('Prompt and model must not be empty')
    if type(max_output_tokens) is not int or max_output_tokens <= 0:
        raise ValueError('max_output_tokens must be positive')
    items = sources(corpus, stratum, limit)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    counts = {'total': len(items), 'reused': 0, 'generated': 0, 'failed': 0}
    outcome = 'aborted'
    try:
        for index, item in enumerate(items, 1):
            uid = item['unit_id']
            diagnostic('progress', unit_id=uid, index=index, total=len(items))
            expected = metadata(item, prompt, model, max_output_tokens)
            target = checkpoint_path(directory, uid)
            if target.is_symlink():
                diagnostic('failure', unit_id=uid, reason='unsafe_checkpoint')
                raise ValueError('Checkpoint must not be a symlink')
            if target.exists():
                try:
                    load_checkpoint(target, expected)
                except (ValueError, OSError):
                    diagnostic('failure', unit_id=uid, reason='invalid_checkpoint')
                    raise
                counts['reused'] += 1
                continue
            if client is None:
                try:
                    from openai import OpenAI
                    load_api_key(env_file)
                    client = OpenAI()
                except Exception as error:
                    counts['failed'] += 1
                    diagnostic('failure', unit_id=uid, reason='client_setup', **exception_diagnostics(error))
                    break
            try:
                response = client.responses.create(model=model, instructions=prompt, input=item['text'], max_output_tokens=max_output_tokens)
            except Exception as error:
                counts['failed'] += 1
                info = exception_diagnostics(error)
                diagnostic('failure', unit_id=uid, reason='api_exception', **info)
                if info['error_type'] in ('AuthenticationError', 'PermissionDeniedError') or info.get('http_status') in (401, 403):
                    break
                continue
            info = response_diagnostics(response)
            text = getattr(response, 'output_text', None)
            validation = None
            if info['status'] != 'completed':
                validation = 'response_not_completed'
            elif not isinstance(text, str) or not text.strip():
                validation = 'empty_summary'
            elif words(text) > 100:
                validation = 'summary_too_long'
            if validation:
                counts['failed'] += 1
                diagnostic('invalid_response', unit_id=uid, validation=validation, **info)
                continue
            text = text.strip()
            row = {**expected, 'summary': text, 'summary_word_count': words(text),
                   'review_status': 'pending', 'review_notes': '',
                   'response_id': getattr(response, 'id', None), 'actual_model': getattr(response, 'model', None)}
            publish(target, encoded(row))
            counts['generated'] += 1
            diagnostic('generated', unit_id=uid, **info)
        outcome = 'failed' if counts['failed'] else 'completed'
    except KeyboardInterrupt:
        outcome = 'interrupted'
        raise
    finally:
        diagnostic('run_summary', outcome=outcome, **counts)
    if counts['failed']:
        raise GenerationError('Generation failed for one or more units; rerun to retry')


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
    rows = review_rows(corpus, directory, stratum, limit)
    if Path(output).suffix.lower() != '.xlsx':
        publish(output, b''.join(encoded(row) for row in rows))
        return
    from openpyxl import Workbook
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    from openpyxl.worksheet.datavalidation import DataValidation

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Summaries'
    headers = ('unit_id', 'stratum', 'filepath', 'source_sha256', 'checkpoint_sha256',
               'summary', 'review_status', 'review_notes')
    sheet.append(headers)
    for row in rows:
        values = [row['unit_id'], row['stratum'], row['filepath'], row['source_sha256'],
                  digest(checkpoint_path(directory, row['unit_id']).read_bytes()),
                  row['summary'], row['review_status'], row['review_notes']]
        for value in values:
            if isinstance(value, str) and (len(value) > 32767 or ILLEGAL_CHARACTERS_RE.search(value)):
                raise ValueError(f'Value cannot be represented in XLSX: {row["unit_id"]}; use JSONL')
        sheet.append(values)
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = 's'
    validation = DataValidation(type='list', formula1='"pending,approved,rejected"')
    sheet.add_data_validation(validation)
    validation.add(f'G2:G{max(2, len(rows) + 1)}')
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    data = io.BytesIO()
    workbook.save(data)
    publish(output, data.getvalue())


def import_review(corpus, directory, review, output, stratum=None, limit=None):
    originals = {row['unit_id']: row for row in review_rows(corpus, directory, stratum, limit)}
    reviewed = []
    seen = set()
    if Path(review).suffix.lower() == '.xlsx':
        from openpyxl import load_workbook
        workbook = load_workbook(review, read_only=True, data_only=False)
        try:
            sheet = workbook['Summaries']
            lines = sheet.iter_rows()
            headers = ('unit_id', 'stratum', 'filepath', 'source_sha256', 'checkpoint_sha256',
                       'summary', 'review_status', 'review_notes')
            if tuple(cell.value for cell in next(lines)) != headers:
                raise ValueError('Invalid review workbook columns')
            rows = []
            for cells in lines:
                if all(cell.value is None for cell in cells):
                    continue
                if len(cells) != len(headers) or any(cell.data_type == 'f' for cell in cells):
                    raise ValueError('Invalid review workbook row')
                values = dict(zip(headers, (cell.value for cell in cells)))
                uid = values['unit_id']
                if uid not in originals:
                    raise ValueError(f'Unknown unit: {uid}')
                original = originals[uid]
                if any(values[k] != original[k] for k in ('stratum', 'filepath', 'source_sha256')) or values['checkpoint_sha256'] != digest(checkpoint_path(directory, uid).read_bytes()):
                    raise ValueError(f'Changed immutable review fields: {uid}')
                rows.append({**original, 'summary': values['summary'], 'review_status': values['review_status'],
                             'review_notes': values['review_notes'] if values['review_notes'] is not None else ''})
        finally:
            workbook.close()
    else:
        rows = [json.loads(line) for line in Path(review).read_text(encoding='utf-8').splitlines() if line.strip()]
    for row in rows:
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
            command.add_argument('--env-file', type=Path, default=ENV_FILE, help='Optional API key file (default: phase directory/env/.env)')
        else:
            command.add_argument('--output', type=Path, required=True)
            if name == 'import-review':
                command.add_argument('--review', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'generate':
        try:
            generate(args.corpus, args.checkpoints, args.prompt, args.model, stratum=args.stratum, limit=args.limit, max_output_tokens=args.max_output_tokens, env_file=args.env_file)
        except KeyboardInterrupt:
            raise SystemExit(130)
        except Exception:
            diagnostic('fatal', reason='generation_failed')
            raise SystemExit(1)
    elif args.command == 'export-review':
        export_review(args.corpus, args.checkpoints, args.output, args.stratum, args.limit)
    else:
        import_review(args.corpus, args.checkpoints, args.review, args.output, args.stratum, args.limit)


if __name__ == '__main__':
    main()