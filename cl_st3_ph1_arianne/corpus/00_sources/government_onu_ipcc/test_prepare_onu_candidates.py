import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

import prepare_onu_candidates as adapter

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
    for ident, name, section in [('ONU_001', 'UNFCCC', 'Preâmbulo'), ('ONU_028', 'Protocolo de Kyoto', 'Preâmbulo'), ('ONU_037', 'Protocolo de Kyoto', 'Artigo 9'), ('ONU_057', 'Acordo de Paris', 'Preâmbulo')]:
        sheet.append([ident, datetime(2026, 9, 28), f'Tratado ONU {name} {section}', adapter.TREATIES[name][3]])
    book.save(metadata)
    (texts / 'ONU_001.txt').write_bytes(b'=first\r\ntext')
    (texts / 'ONU_028.txt').write_text('Kyoto text', encoding='utf-8')
    (texts / 'ONU_057.txt').write_text('Paris text', encoding='utf-8')
    return metadata, texts


def test_linked_review_and_provenance(tmp_path):
    metadata, texts = fixture(tmp_path)
    out = tmp_path / 'out'
    assert adapter.prepare(metadata, texts, out)['candidates'] == 3
    rows = read(out / 'candidates.ndjson')
    assert [r['review_status'] for r in rows] == ['pending'] * 3
    assert rows[0]['text'] == '=first\r\ntext'
    assert rows[0]['collection_date'] == '2026-09-28'
    assert rows[0]['publication_datetime_utc'] is None
    assert rows[0]['temporal_eligibility'] == 'permitted temporal exception'
    assert rows[1]['temporal_eligibility'] == 'permitted temporal exception'
    assert rows[2]['temporal_eligibility'] == 'eligible'
    assert rows[0]['section_reference'] == 'Preâmbulo'
    assert not Path(rows[0]['review_source_path']).is_absolute()
    assert any(d['id'] == 'ONU_037' and d['issue'] == 'missing text file' for d in read(out / 'diagnostics.jsonl'))
    book = load_workbook(out / 'review.xlsx')
    assert book['Review']['B2'].data_type == 's'
    book['Review']['D2'] = 'approved'
    book.save(out / 'review.xlsx')
    compiler.import_review(out / 'candidates.ndjson', out / 'review.xlsx', tmp_path / 'reviewed.ndjson')
    assert read(tmp_path / 'reviewed.ndjson')[0]['review_status'] == 'approved'
    (texts / 'ONU_001.txt').write_text('changed')
    with pytest.raises(ValueError, match='source file'):
        compiler.import_review(out / 'candidates.ndjson', out / 'review.xlsx', tmp_path / 'other.ndjson')
    with pytest.raises(FileExistsError):
        adapter.prepare(metadata, texts, out)


def test_inconsistent_metadata_and_extra_files(tmp_path):
    metadata, texts = fixture(tmp_path)
    book = load_workbook(metadata)
    sheet = book.active
    sheet.append(['ONU_001', None, 'duplicate', 'bad'])
    sheet.append(['ONU_002', None, 'Tratado ONU UNFCCC Artigo 99', 'bad'])
    sheet.append(['ONU_003', datetime(2026, 9, 28), 'Tratado ONU UNFCCC Preâmbulo', adapter.TREATIES['UNFCCC'][3]])
    book.save(metadata)
    (texts / 'extra.txt').write_text('extra')
    out = tmp_path / 'out'
    adapter.prepare(metadata, texts, out)
    issues = {x['issue'] for x in read(out / 'diagnostics.jsonl')}
    assert {'duplicate metadata id', 'invalid or incomplete metadata', 'inconsistent treaty URL', 'duplicate treaty section', 'invalid treaty section', 'extra text file without metadata', 'missing text file'} <= issues
    assert len(read(out / 'candidates.ndjson')) == 4


def test_failure_cleans_new_output(tmp_path):
    with pytest.raises(FileNotFoundError):
        adapter.prepare(tmp_path / 'missing', tmp_path, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_treaty_review_compiles_with_canonical_stratum(tmp_path):
    metadata, texts = fixture(tmp_path)
    out = tmp_path / 'review'
    adapter.prepare(metadata, texts, out)
    rows = read(out / 'candidates.ndjson')
    assert {row['stratum'] for row in rows} == {'gov-treaty'}
    book = load_workbook(out / 'review.xlsx')
    for row in range(2, 5):
        book.active.cell(row, 4).value = 'approved'
    book.save(out / 'review.xlsx')
    reviewed = tmp_path / 'reviewed.ndjson'
    compiler.import_review(out / 'candidates.ndjson', out / 'review.xlsx', reviewed)
    # Previously generated ONU bundles used this legacy code.
    legacy = read(reviewed)
    for row in legacy:
        row['stratum'] = 'treaty-segment'
    reviewed.write_text(''.join(json.dumps(row) + '\n' for row in legacy), encoding='utf-8')
    corpus = tmp_path / 'corpus'
    compiler.compile_corpus(reviewed, corpus, 'gov-treaty', 3, 42)
    assert {row['stratum'] for row in read(corpus / 'manifest.ndjson')} == {'gov-treaty'}
    assert {row['stratum'] for row in read(reviewed)} == {'treaty-segment'}