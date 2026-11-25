import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest
from openpyxl import load_workbook

import prepare_now_candidates as adapter

COMPILER = Path(__file__).resolve().parents[4] / 'cl_st3_ph2_arianne/compile_corpus.py'
spec = importlib.util.spec_from_file_location('compiler', COMPILER)
compiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compiler)


def archive(path, rows):
    data = b''.join((json.dumps(row) + '\n').encode() for row in rows)
    with tarfile.open(path, 'w:xz') as tar:
        info = tarfile.TarInfo('climate_now_screened.ndjson')
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))


def record(article_id, category='CORE'):
    return {'article_id': str(article_id), 'filepath': f'{article_id}.txt',
        'date_iso': '2016-01-03', 'source_name': 'News', 'url': 'https://example.test',
        'country_code': 'ph', 'source_files': '["source.txt"]',
        'llm_screening': {'category': category, 'confidence': 0.9},
        'llm_screening_metadata': {'model': 'test'}}


def test_prepare_review_and_compiler(tmp_path):
    source = tmp_path / 'input.tar.xz'
    archive(source, [record(1), record(2, 'PERIPHERAL'), record(3)])
    (tmp_path / '1.txt').write_bytes(b'=formula\r\narticle\n')
    (tmp_path / '3.txt').write_text('Climate article', encoding='utf-8')
    manifest, review = tmp_path / 'candidates.ndjson', tmp_path / 'review.xlsx'
    assert adapter.prepare(source, tmp_path, manifest, review) == 2
    rows = [json.loads(line) for line in manifest.read_text().splitlines()]
    assert [r['candidate_id'] for r in rows] == ['now:1', 'now:3']
    assert rows[0]['text'] == '=formula\r\narticle\n'
    assert rows[0]['now_metadata']['country_code'] == 'ph'
    assert rows[0]['llm_screening_metadata']['model'] == 'test'
    assert not Path(rows[0]['review_source_path']).is_absolute()
    assert (adapter.PROJECT_ROOT / rows[0]['review_source_path']).resolve() == (tmp_path / '1.txt').resolve()
    assert (adapter.PROJECT_ROOT / rows[0]['source_manifest']).resolve() == source.resolve()
    assert all(r['review_status'] == 'pending' for r in rows)
    book = load_workbook(review)
    assert book['Review']['B2'].data_type == 's'
    book['Review']['D2'] = 'approved'
    book.save(review)
    reviewed = tmp_path / 'reviewed.ndjson'
    compiler.import_review(manifest, review, reviewed)
    compiler.compile_corpus(reviewed, tmp_path / 'corpus', 'press-news', 1, 3)
    item = json.loads((tmp_path / 'corpus/manifest.ndjson').read_text())
    assert (tmp_path / 'corpus' / item['filepath']).read_bytes() == b'=formula\r\narticle\n'


@pytest.mark.parametrize('text', ['a' * 32768, 'abc\x01def', '😀' * 16384])
def test_unrepresentable_text_review_roundtrip(tmp_path, text):
    source = tmp_path / 'input.tar.xz'
    archive(source, [record(1)])
    (tmp_path / '1.txt').write_text(text, encoding='utf-8')
    manifest, review = tmp_path / 'out.ndjson', tmp_path / 'review.xlsx'
    assert adapter.prepare(source, tmp_path, manifest, review) == 1
    assert json.loads(manifest.read_text())['text'] == text
    book = load_workbook(review)
    book['Review']['D2'] = 'approved'
    book.save(review)
    reviewed = tmp_path / 'reviewed.ndjson'
    compiler.import_review(manifest, review, reviewed)
    assert json.loads(reviewed.read_text())['text'] == text


@pytest.mark.parametrize('column', ['B', 'C', 'F', 'G'])
def test_rejects_review_tampering(tmp_path, column):
    source = tmp_path / 'input.tar.xz'
    archive(source, [record(1)])
    (tmp_path / '1.txt').write_text('article')
    manifest, review = tmp_path / 'out.ndjson', tmp_path / 'review.xlsx'
    adapter.prepare(source, tmp_path, manifest, review)
    book = load_workbook(review)
    book['Review'][column + '2'] = 'tampered'
    book.save(review)
    with pytest.raises(ValueError):
        compiler.import_review(manifest, review, tmp_path / 'reviewed')


def test_rejects_changed_source(tmp_path):
    source = tmp_path / 'input.tar.xz'
    archive(source, [record(1)])
    article = tmp_path / '1.txt'
    article.write_text('article')
    manifest, review = tmp_path / 'out.ndjson', tmp_path / 'review.xlsx'
    adapter.prepare(source, tmp_path, manifest, review)
    article.write_text('changed')
    with pytest.raises(ValueError, match='source'):
        compiler.import_review(manifest, review, tmp_path / 'reviewed')


def test_rejects_changed_manifest_text(tmp_path):
    source = tmp_path / 'input.tar.xz'
    archive(source, [record(1)])
    (tmp_path / '1.txt').write_text('article')
    manifest, review = tmp_path / 'out.ndjson', tmp_path / 'review.xlsx'
    adapter.prepare(source, tmp_path, manifest, review)
    row = json.loads(manifest.read_text())
    row['text'] = 'article changed'
    manifest.write_text(json.dumps(row) + '\n')
    with pytest.raises(ValueError, match='source'):
        compiler.import_review(manifest, review, tmp_path / 'reviewed')


def test_duplicate_missing_and_no_overwrite(tmp_path):
    source = tmp_path / 'input.tar.xz'
    output = tmp_path / 'out.ndjson'
    archive(source, [record(1), record(1)])
    (tmp_path / '1.txt').write_text('text')
    with pytest.raises(ValueError, match='duplicate'):
        adapter.prepare(source, tmp_path, output)
    assert not output.exists()
    archive(source, [record(2)])
    with pytest.raises(FileNotFoundError):
        adapter.prepare(source, tmp_path, output)
    output.write_text('existing')
    with pytest.raises(FileExistsError):
        adapter.prepare(source, tmp_path, output)
    assert output.read_text() == 'existing'


def test_path_escape_rejected(tmp_path):
    source = tmp_path / 'input.tar.xz'
    row = record(1)
    row['filepath'] = '../outside.txt'
    archive(source, [row])
    with pytest.raises(ValueError, match='escapes'):
        adapter.prepare(source, tmp_path, tmp_path / 'out')