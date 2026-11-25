import hashlib
import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

import prepare_sceptical_blog_candidates as adapter

spec = importlib.util.spec_from_file_location('compiler', adapter.PROJECT_ROOT / 'cl_st3_ph2_arianne/compile_corpus.py')
compiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compiler)


def read(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def fixture(tmp_path):
    metadata = tmp_path / 'metadata.xlsx'
    texts = tmp_path / 'texts'
    texts.mkdir()
    book = Workbook()
    sheet = book.active
    sheet.append(['Nome do arquivo', 'Data', 'Título do artigo', 'Link do artigo'])
    sheet.append(['blog_cetico_001', datetime(2026, 10, 14, 12), 'Title', 'https://example.org/2023/01/01/post'])
    sheet.append(['blog_cetico_011', None, 'missing', 'bad'])
    sheet.append(['blog_cetico_001', None, 'duplicate', 'bad'])
    sheet.append(['bad id', None, None, None])
    book.save(metadata)
    (texts / 'blog_cetico_001.txt').write_bytes(b'=first\r\ntext')
    (texts / 'blog_cetico_0011.txt').write_bytes(b'=first\r\ntext')
    return metadata, texts


def test_review_diagnostics_and_compiler(tmp_path):
    metadata, texts = fixture(tmp_path)
    output = tmp_path / 'output'
    stats = adapter.prepare(metadata, texts, output)
    assert stats['candidates'] == 2 and stats['metadata_records'] == 2
    rows = read(output / 'candidates.ndjson')
    row = rows[0]
    assert row['text'] == '=first\r\ntext'
    assert row['source_sha256'] == hashlib.sha256(metadata.read_bytes()).hexdigest()
    assert row['source_text_sha256'] == hashlib.sha256(b'=first\r\ntext').hexdigest()
    assert row['metadata_date'] == '2026-10-14T12:00:00' and row['metadata_row'] == 2
    assert all(r['publication_datetime_utc'] is None and r['temporal_eligibility'] == 'unknown' for r in rows)
    assert all(r['review_status'] == 'pending' and r['stratum'] == 'sceptic-blog' for r in rows)
    assert not Path(row['source_manifest']).is_absolute() and not Path(row['review_source_path']).is_absolute()
    assert rows[1]['source_url'] is None and rows[1]['metadata_row'] is None
    issues = {d['issue'] for d in read(output / 'diagnostics.jsonl')}
    assert {'invalid or incomplete metadata', 'duplicate metadata id', 'invalid metadata id',
            'missing text file', 'extra text file without metadata', 'duplicate text', 'irregular text filename'} <= issues
    book = load_workbook(output / 'review.xlsx')
    assert book.active['B2'].data_type == 's'
    book.active['D2'] = 'approved'
    book.save(output / 'review.xlsx')
    reviewed = tmp_path / 'reviewed.ndjson'
    compiler.import_review(output / 'candidates.ndjson', output / 'review.xlsx', reviewed)
    assert read(reviewed)[0]['review_status'] == 'approved'
    compiler.compile_corpus(reviewed, tmp_path / 'corpus', 'sceptic-blog', 1, 42)
    assert read(tmp_path / 'corpus' / 'manifest.ndjson')[0]['stratum'] == 'sceptic-blog'
    (texts / 'blog_cetico_001.txt').write_text('changed')
    with pytest.raises(ValueError, match='source file'):
        compiler.import_review(output / 'candidates.ndjson', output / 'review.xlsx', tmp_path / 'other.ndjson')
    with pytest.raises(FileExistsError):
        adapter.prepare(metadata, texts, output)
    assert read(output / 'candidates.ndjson') == rows


def test_bad_header_and_duplicate_stems_clean_output(tmp_path):
    metadata, texts = fixture(tmp_path)
    book = load_workbook(metadata)
    book.active['A1'] = 'wrong'
    book.save(metadata)
    with pytest.raises(ValueError, match='header'):
        adapter.prepare(metadata, texts, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()
    book.active['A1'] = 'Nome do arquivo'
    book.save(metadata)
    (texts / 'blog_cetico_001.TXT').write_text('other')
    with pytest.raises(ValueError, match='duplicate stems'):
        adapter.prepare(metadata, texts, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


def test_empty_and_invalid_utf8_text(tmp_path):
    metadata, texts = fixture(tmp_path)
    (texts / 'blog_cetico_002.txt').write_bytes(b'')
    adapter.prepare(metadata, texts, tmp_path / 'output')
    assert any(d['issue'] == 'empty text' and d['id'] == 'blog_cetico_002'
               for d in read(tmp_path / 'output' / 'diagnostics.jsonl'))
    (texts / 'blog_cetico_002.txt').write_bytes(b'\xff')
    with pytest.raises(UnicodeDecodeError):
        adapter.prepare(metadata, texts, tmp_path / 'bad-output')
    assert not (tmp_path / 'bad-output').exists()