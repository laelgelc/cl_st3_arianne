import importlib.util
import json
from pathlib import Path

import pytest

from compile_corpus import compile_corpus, import_review

ADAPTER = Path(__file__).resolve().parents[1] / 'cl_st3_ph1_arianne/corpus/00_sources/gettr/prepare_gettr_candidates.py'
spec = importlib.util.spec_from_file_location('adapter', ADAPTER)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def write_rows(path, rows):
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')


def test_source_quotas_sample_deterministically_and_require_approval(tmp_path):
    rows = [dict(candidate_id=f'{source}:{i}', stratum='ngo-story', review_status='approved',
                 text='Climate text', actor='NGO', register='story', source=source, source_id=str(i))
            for source in ('Greenpeace', 'WWF', 'WRI') for i in range(4)]
    rows[-1]['review_status'] = 'pending'
    path = tmp_path / 'candidates.ndjson'
    write_rows(path, rows)
    quotas = {'Greenpeace': 2, 'WWF': 1, 'WRI': 2}
    for name in ('one', 'two'):
        compile_corpus(path, tmp_path / name, 'ngo-story', 5, 42, quotas)
    result = [json.loads(line) for line in (tmp_path / 'one/manifest.ndjson').read_text().splitlines()]
    assert (tmp_path / 'one/manifest.ndjson').read_bytes() == (tmp_path / 'two/manifest.ndjson').read_bytes()
    assert {source: sum(row['source'] == source for row in result) for source in quotas} == quotas
    sampling = json.loads((tmp_path / 'one/sampling.json').read_text())['strata']['ngo-story']
    assert sampling['source_quotas'] == quotas and sampling['eligible_by_source']['WRI'] == 3
    with pytest.raises(ValueError, match='Need 4 approved candidates for WRI'):
        compile_corpus(path, tmp_path / 'blocked', 'ngo-story', 6, 42, {'Greenpeace': 1, 'WWF': 1, 'WRI': 4})
    with pytest.raises(ValueError, match='sum to count'):
        compile_corpus(path, tmp_path / 'blocked', 'ngo-story', 5, 42, {'WRI': 1})
    assert not (tmp_path / 'blocked').exists()


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


def test_add_stratum_preserves_legacy_corpus_and_rejects_duplicates(tmp_path):
    source = tmp_path / 'source.ndjson'
    write_rows(source, [{'_id': '1', 'text': 'Climate change', 'cdate': 1625164646880}])
    candidates = tmp_path / 'candidates.ndjson'
    adapter.prepare(source, candidates)
    row = json.loads(candidates.read_text())
    row['review_status'] = 'approved'
    write_rows(candidates, [row])
    corpus = tmp_path / 'corpus'
    compile_corpus(candidates, corpus, 'social-post', 1, 42)
    first = (corpus / 'manifest.ndjson').read_bytes()
    first_record = json.loads(first)
    first_text = (corpus / first_record['filepath']).read_bytes()
    original_sampling = json.loads((corpus / 'sampling.json').read_text())['strata']['social-post']
    (corpus / 'sampling.json').write_text(json.dumps(original_sampling))
    other = dict(row, candidate_id='other:1', stratum='press-news')
    write_rows(candidates, [other])
    compile_corpus(candidates, corpus, 'press-news', 1, 7)
    result = (corpus / 'manifest.ndjson').read_bytes()
    assert result.startswith(first) and len(result.splitlines()) == 2
    assert (corpus / first_record['filepath']).read_bytes() == first_text
    sampling = json.loads((corpus / 'sampling.json').read_text())['strata']
    assert sampling['social-post'] == original_sampling
    assert sampling['press-news']['seed'] == 7
    with pytest.raises(FileExistsError):
        compile_corpus(candidates, corpus, 'press-news', 1, 7)
    write_rows(candidates, [dict(other, candidate_id=row['candidate_id'], stratum='ngo-story')])
    with pytest.raises(ValueError, match='Candidate ID already exists'):
        compile_corpus(candidates, corpus, 'ngo-story', 1, 7)
    assert (corpus / 'manifest.ndjson').read_bytes() == result


def test_add_stratum_rolls_back_publication_failure(tmp_path, monkeypatch):
    import compile_corpus as compiler

    source = tmp_path / 'source.ndjson'
    write_rows(source, [{'_id': '1', 'text': 'Climate change', 'cdate': 1625164646880}])
    candidates = tmp_path / 'candidates.ndjson'
    adapter.prepare(source, candidates)
    row = json.loads(candidates.read_text())
    row['review_status'] = 'approved'
    write_rows(candidates, [row])
    corpus = tmp_path / 'corpus'
    compile_corpus(candidates, corpus, 'social-post', 1, 42)
    before = [(corpus / name).read_bytes() for name in ('manifest.ndjson', 'sampling.json')]
    write_rows(candidates, [dict(row, candidate_id='other', stratum='press-news')])
    replace = compiler.os.replace

    def fail_sampling(src, dst):
        if Path(dst).name == 'sampling.json':
            raise OSError('simulated failure')
        return replace(src, dst)

    monkeypatch.setattr(compiler.os, 'replace', fail_sampling)
    with pytest.raises(OSError, match='simulated'):
        compile_corpus(candidates, corpus, 'press-news', 1, 7)
    assert [(corpus / name).read_bytes() for name in ('manifest.ndjson', 'sampling.json')] == before
    assert not (corpus / 'human/press-news').exists()


def test_spreadsheet_review_roundtrip_and_validation(tmp_path):
    from openpyxl import load_workbook

    source = tmp_path / 'source.ndjson'
    write_rows(source, [{'_id': str(i), 'text': '=Climate change ' + str(i), 'cdate': 1625164646880} for i in range(2)])
    candidates = tmp_path / 'candidates.ndjson'
    adapter.prepare(source, candidates)
    sheet_path = tmp_path / 'review.xlsx'
    adapter.export_review(candidates, sheet_path)
    book = load_workbook(sheet_path)
    sheet = book['Review']
    assert sheet['B2'].data_type == 's'
    sheet['D2'] = 'approved'
    sheet['E2'] = 'Reviewed'
    book.save(sheet_path)
    reviewed = tmp_path / 'reviewed.ndjson'
    import_review(candidates, sheet_path, reviewed)
    rows = [json.loads(line) for line in reviewed.read_text().splitlines()]
    assert rows[0]['review_status'] == 'approved' and rows[0]['review_notes'] == 'Reviewed'
    assert rows[0]['text'] == '=Climate change 0'
    compile_corpus(reviewed, tmp_path / 'corpus', 'social-post', 1, 42)
    import_review(candidates, sheet_path, reviewed)
    sheet['E2'] = 'Changed decision'
    book.save(sheet_path)
    with pytest.raises(FileExistsError, match='reviewed manifest'):
        import_review(candidates, sheet_path, reviewed)
    assert reviewed.read_text().splitlines()[0] == json.dumps(rows[0], ensure_ascii=False)
    sheet['B2'] = 'altered'
    book.save(sheet_path)
    with pytest.raises(ValueError, match='Changed source'):
        import_review(candidates, sheet_path, tmp_path / 'bad.ndjson')
    assert not (tmp_path / 'bad.ndjson').exists()


def test_compile_accepts_empty_directory_but_not_unrelated_contents(tmp_path):
    source = tmp_path / 'source.ndjson'
    write_rows(source, [{'_id': '1', 'text': 'Climate change', 'cdate': 1625164646880}])
    candidates = tmp_path / 'candidates.ndjson'
    adapter.prepare(source, candidates)
    row = json.loads(candidates.read_text())
    row['review_status'] = 'approved'
    write_rows(candidates, [row])
    corpus = tmp_path / 'corpus'
    corpus.mkdir()
    compile_corpus(candidates, corpus, 'social-post', 1, 42)
    assert (corpus / 'manifest.ndjson').is_file()
    other = tmp_path / 'other'
    other.mkdir()
    (other / 'keep').write_text('keep')
    with pytest.raises(ValueError, match='complete corpus'):
        compile_corpus(candidates, other, 'social-post', 1, 42)
    assert (other / 'keep').read_text() == 'keep'


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'status', 'formula'])
def test_review_rejects_bad_decisions(tmp_path, change):
    from openpyxl import load_workbook

    source = tmp_path / 'source.ndjson'
    write_rows(source, [{'_id': str(i), 'text': 'Climate change', 'cdate': 1625164646880} for i in range(2)])
    manifest = tmp_path / 'candidates.ndjson'
    adapter.prepare(source, manifest)
    xlsx = tmp_path / 'review.xlsx'
    adapter.export_review(manifest, xlsx)
    book = load_workbook(xlsx)
    sheet = book['Review']
    if change == 'missing':
        sheet.delete_rows(3)
    elif change == 'duplicate':
        sheet['A3'] = sheet['A2'].value
    elif change == 'status':
        sheet['D2'] = 'yes'
    else:
        sheet['E2'] = '=1+1'
    book.save(xlsx)
    output = tmp_path / 'invalid.ndjson'
    with pytest.raises(ValueError):
        import_review(manifest, xlsx, output)
    assert not output.exists()


def test_review_accepts_normalized_line_endings_preserving_original(tmp_path):
    from openpyxl import load_workbook

    source = tmp_path / 'source.ndjson'
    text = 'Climate change\r\nsecond line\rthird line'
    write_rows(source, [{'_id': '1', 'text': text, 'cdate': 1625164646880}])
    manifest = tmp_path / 'candidates.ndjson'
    adapter.prepare(source, manifest)
    xlsx = tmp_path / 'review.xlsx'
    adapter.export_review(manifest, xlsx)
    book = load_workbook(xlsx)
    book['Review']['B2'] = text.replace('\r\n', '\n').replace('\r', '\n')
    book['Review']['D2'] = 'approved'
    book.save(xlsx)
    output = tmp_path / 'reviewed.ndjson'
    import_review(manifest, xlsx, output)
    assert json.loads(output.read_text())['text'] == text

    book['Review']['B2'] = 'Climate change\nchanged line\nthird line'
    book.save(xlsx)
    with pytest.raises(ValueError, match='Changed source'):
        import_review(manifest, xlsx, tmp_path / 'invalid.ndjson')