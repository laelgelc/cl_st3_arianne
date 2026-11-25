import hashlib
import importlib.util
import json
from datetime import datetime

import pytest
from openpyxl import Workbook, load_workbook

import prepare_academic_candidates as adapter

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
    sheet.append(['Nome de arquivo', 'Data de coleta', 'Assunto', 'Link'])
    sheet.append(['Plos_Abs_001', datetime(2026, 9, 11), 'Abstract', 'https://example.org/article'])
    sheet.append(['Plos_Abs_011', None, 'missing', 'bad'])
    sheet.append(['Plos_Abs_001', None, 'duplicate', 'bad'])
    sheet.append(['bad id', None, None, None])
    book.save(metadata)
    (texts / 'Plos_Abs_001.txt').write_bytes(b'=first\r\ntext')
    (texts / 'Plos_Abs_0011.txt').write_bytes(b'=first\r\ntext')
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
    assert row['collection_date'] == '2026-09-11' and row['metadata_row'] == 2
    assert row['publication_datetime_utc'] is None and row['temporal_eligibility'] == 'unknown'
    assert all(r['review_status'] == 'pending' for r in rows)
    assert all(r['stratum'] == 'acad-abstract' for r in rows)
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
    compiler.compile_corpus(reviewed, tmp_path / 'corpus', 'acad-abstract', 1, 42)
    assert read(tmp_path / 'corpus' / 'manifest.ndjson')[0]['stratum'] == 'acad-abstract'
    (texts / 'Plos_Abs_001.txt').write_text('changed')
    with pytest.raises(ValueError, match='source file'):
        compiler.import_review(output / 'candidates.ndjson', output / 'review.xlsx', tmp_path / 'other.ndjson')
    with pytest.raises(FileExistsError):
        adapter.prepare(metadata, texts, output)


def test_bad_header_cleans_output(tmp_path):
    metadata, texts = fixture(tmp_path)
    book = load_workbook(metadata)
    book.active['A1'] = 'wrong'
    book.save(metadata)
    with pytest.raises(ValueError, match='header'):
        adapter.prepare(metadata, texts, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()