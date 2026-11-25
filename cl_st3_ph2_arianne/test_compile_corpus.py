import importlib.util
import json
from pathlib import Path

import pytest

from compile_corpus import compile_corpus

ADAPTER = Path(__file__).resolve().parents[1] / 'cl_st3_ph1_arianne/corpus/00_sources/gettr/prepare_gettr_candidates.py'
spec = importlib.util.spec_from_file_location('adapter', ADAPTER)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def write_rows(path, rows):
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')


def test_adapter_and_compilation(tmp_path):
    source = tmp_path / 'source.ndjson'
    write_rows(source, [{'_id': str(i), 'text': f'Climate change {i}', 'cdate': 1625164646880} for i in range(4)])
    candidates = tmp_path / 'candidates.ndjson'
    assert adapter.prepare(source, candidates) == 4
    rows = [json.loads(line) for line in candidates.read_text().splitlines()]
    assert all(row['review_status'] == 'pending' for row in rows)
    with pytest.raises(ValueError, match='found 0'):
        compile_corpus(candidates, tmp_path / 'blocked', 'social-post', 2, 4)
    for row in rows[:3]:
        row['review_status'] = 'approved'
    write_rows(candidates, rows)
    for name in ('one', 'two'):
        compile_corpus(candidates, tmp_path / name, 'social-post', 2, 42)
    a = [json.loads(line) for line in (tmp_path / 'one/manifest.ndjson').read_text().splitlines()]
    b = [json.loads(line) for line in (tmp_path / 'two/manifest.ndjson').read_text().splitlines()]
    assert a == b and len(a) == 2
    assert all((tmp_path / 'one' / row['filepath']).read_text() in [r['text'] for r in rows[:3]] for row in a)
    assert all(row['word_count'] == 3 and row['token_count'] is None for row in a)
    with pytest.raises(FileExistsError):
        compile_corpus(candidates, tmp_path / 'one', 'social-post', 2, 42)


def test_invalid_source_and_duplicate_candidates(tmp_path):
    source = tmp_path / 'source.ndjson'
    row = {'_id': 'x', 'text': 'Climate change', 'cdate': 1625164646880}
    write_rows(source, [row, row])
    with pytest.raises(ValueError, match='duplicate'):
        adapter.prepare(source, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()
    write_rows(source, [dict(row, cdate=0)])
    with pytest.raises(ValueError, match='outside'):
        adapter.prepare(source, tmp_path / 'out')