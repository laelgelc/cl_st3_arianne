import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from openpyxl import load_workbook

import prepare_ngo_candidates as adapter

COMPILER = Path(__file__).resolve().parents[4] / 'cl_st3_ph2_arianne/compile_corpus.py'
spec = importlib.util.spec_from_file_location('compiler', COMPILER)
compiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compiler)


def record(post_id, number, text, published='2020-01-01', **extra):
    return {'Source': 'NGO', 'Post ID': post_id, 'Post Date': published,
            'Post URL': 'https://example.test', 'Title': 'Title',
            'Paragraph': f'Paragraph {number}', 'Text Paragraph': text, **extra}


def write(path, rows):
    path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')


def read(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def test_schemas_order_window_long_text_and_import(tmp_path):
    epoch = int(datetime(2015, 11, 1, tzinfo=timezone.utc).timestamp() * 1000)
    inputs = {s: tmp_path / (s + '.jsonl') for s in ('grp', 'wwf', 'wri')}
    write(inputs['grp'], [record('same', 2, 'second', epoch), record('same', 1, '=first', epoch), record('old', 1, 'old', '2015-10-31')])
    long_text = '😀' * 20000 + '\x01end'
    write(inputs['wwf'], [record('same', 1, long_text, '2022-11-30')])
    write(inputs['wri'], [record('wri1', 1, 'last', '2022-12-01'), record('wri2', 1, 'wri', '2022-11-04', **{'Listing Date': '2022-11-04'})])
    out = tmp_path / 'bundle'
    stats = adapter.prepare(inputs, out)
    rows = read(out / 'candidates.ndjson')
    assert stats['candidates'] == 3
    assert len({r['source_id'] for r in rows}) == 3
    assert rows[0]['text'] == '=first\n\nsecond'
    assert rows[0]['publication_datetime_utc'] == '2015-11-01'
    assert all(r['review_status'] == 'pending' for r in rows)
    assert all(r['stratum'] == 'ngo-story' for r in rows)
    book = load_workbook(out / 'review.xlsx')
    assert book['Review']['B2'].data_type == 's'
    book['Review']['D2'] = 'approved'
    book.save(out / 'review.xlsx')
    compiler.import_review(out / 'candidates.ndjson', out / 'review.xlsx', tmp_path / 'reviewed.ndjson')
    assert next(r for r in read(tmp_path / 'reviewed.ndjson') if r['source_id'] == 'wwf:same')['text'] == long_text
    compiler.compile_corpus(tmp_path / 'reviewed.ndjson', tmp_path / 'corpus', 'ngo-story', 1, 1)
    with pytest.raises(FileExistsError):
        adapter.prepare(inputs, out)


def test_diagnostics_conflicts_and_malformed(tmp_path):
    source = tmp_path / 'input.jsonl'
    rows = [record('duplicate', 1, 'a'), record('duplicate', 1, 'b'),
            record('date', 1, 'a', '2020-01-01'), record('date', 2, 'b', '2023-01-01'),
            record('unknown', 1, 'a', None), record('missing', 2, 'a'),
            record('badtext', 1, None), record('metadata', 1, 'a'), record('metadata', 2, 'b', Title='different')]
    write(source, rows)
    with source.open('a') as f:
        f.write('{broken\n')
    out = tmp_path / 'bundle'
    stats = adapter.prepare({'grp': source}, out)
    candidates = read(out / 'candidates.ndjson')
    issues = read(out / 'diagnostics.jsonl')
    assert stats['sources']['grp']['counts']['malformed_rows'] == 1
    assert stats['sources']['grp']['counts']['uncertain_date_stories'] == 2
    assert len(issues) == 7
    assert {r['source_id'] for r in candidates} == {'grp:duplicate', 'grp:missing', 'grp:metadata'}
    assert candidates[0]['text'] == 'a\n\nb'
    assert 'duplicate' in candidates[0]['review_warning']


def test_changed_full_text_rejected_and_failure_cleanup(tmp_path):
    source = tmp_path / 'source.jsonl'
    write(source, [record('a', 1, 'text')])
    out = tmp_path / 'out'
    adapter.prepare({'grp': source}, out)
    row = read(out / 'candidates.ndjson')[0]
    Path(row['review_source_path']).write_text('changed')
    with pytest.raises(ValueError, match='source file'):
        compiler.import_review(out / 'candidates.ndjson', out / 'review.xlsx', tmp_path / 'reviewed')
    with pytest.raises(FileNotFoundError):
        adapter.prepare({'grp': tmp_path / 'absent'}, tmp_path / 'failed')
    assert not (tmp_path / 'failed').exists()