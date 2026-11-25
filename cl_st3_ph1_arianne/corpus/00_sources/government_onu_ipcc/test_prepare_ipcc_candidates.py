import hashlib
import importlib.util
import json
from datetime import datetime

import pytest
from openpyxl import Workbook, load_workbook

import prepare_ipcc_candidates as adapter
from prepare_onu_candidates import PROJECT_ROOT

spec = importlib.util.spec_from_file_location('compiler', PROJECT_ROOT / 'cl_st3_ph2_arianne/compile_corpus.py')
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
    sheet.append(['IPCC_Report_001', datetime(2026, 9, 21), 'Climate Change 20014 Cap.1', 'https://www.ipcc.ch/report/ar5/syr/'])
    sheet.append(['IPCC_Report_002', None, 'missing', 'bad'])
    sheet.append(['IPCC_Report_001', None, 'duplicate', 'bad'])
    sheet.append(['bad id', None, None, None])
    book.save(metadata)
    (texts / 'IPCC_Report_001.txt').write_bytes(b'=first\r\ntext')
    (texts / 'extra.txt').write_bytes(b'=first\r\ntext')
    return metadata, texts


def test_review_provenance_and_diagnostics(tmp_path):
    metadata, texts = fixture(tmp_path)
    output = tmp_path / 'output'
    stats = adapter.prepare(metadata, texts, output)
    assert stats['candidates'] == 2 and stats['metadata_records'] == 2
    rows = read(output / 'candidates.ndjson')
    row = next(r for r in rows if r['source_id'] == 'IPCC_Report_001')
    assert row['text'] == '=first\r\ntext'
    assert row['source_sha256'] == hashlib.sha256(metadata.read_bytes()).hexdigest()
    assert row['source_text_sha256'] == hashlib.sha256(b'=first\r\ntext').hexdigest()
    assert row['metadata_row'] == 2 and row['collection_date'] == '2026-09-21'
    assert row['publication_datetime_utc'] is None and row['temporal_eligibility'] == 'unknown'
    assert all(r['stratum'] == 'gov-report' and r['review_status'] == 'pending' for r in rows)
    issues = {d['issue'] for d in read(output / 'diagnostics.jsonl')}
    assert {'suspicious year or number in subject', 'invalid or incomplete metadata', 'duplicate metadata id',
            'invalid metadata id', 'missing text file', 'extra text file without metadata', 'duplicate text'} <= issues
    book = load_workbook(output / 'review.xlsx')
    assert book.active['B2'].data_type == 's'
    book.active['D2'] = 'approved'
    book.save(output / 'review.xlsx')
    reviewed = tmp_path / 'reviewed.ndjson'
    compiler.import_review(output / 'candidates.ndjson', output / 'review.xlsx', reviewed)
    assert read(reviewed)[0]['review_status'] == 'approved'
    (texts / 'IPCC_Report_001.txt').write_text('changed')
    with pytest.raises(ValueError, match='source file'):
        compiler.import_review(output / 'candidates.ndjson', output / 'review.xlsx', tmp_path / 'other.ndjson')
    with pytest.raises(FileExistsError):
        adapter.prepare(metadata, texts, output)


def test_failure_cleanup_and_bad_header(tmp_path):
    metadata, texts = fixture(tmp_path)
    book = load_workbook(metadata)
    book.active['A1'] = 'wrong'
    book.save(metadata)
    with pytest.raises(ValueError, match='header'):
        adapter.prepare(metadata, texts, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()