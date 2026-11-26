import importlib.util
import hashlib
import json
import os
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


@pytest.mark.parametrize('relative', [True, False])
def test_linked_review_paths_and_hashes(tmp_path, monkeypatch, relative):
    from openpyxl import Workbook

    root = Path(__file__).resolve().parents[1]
    text = 'Climate change\nsecond line'
    source = tmp_path / 'full.txt'
    source.write_text(text, encoding='utf-8')
    path = os.path.relpath(source, root) if relative else str(source)
    digest = hashlib.sha256(text.encode()).hexdigest()
    row = dict(candidate_id='one', text=text, publication_datetime_utc='2021-01-01',
               review_status='pending', review_notes='', review_source_path=path,
               source_text_sha256=digest, source_manifest=str(tmp_path / 'source.ndjson'),
               stratum='social-post', actor='a', register='r', source='s', source_id='1')
    manifest = tmp_path / 'candidates.ndjson'
    write_rows(manifest, [row])
    book = Workbook()
    sheet = book.active
    sheet.title = 'Review'
    sheet.append(('candidate_id', 'text_preview', 'publication_datetime_utc', 'review_status', 'review_notes', 'text_sha256', 'full_text_path'))
    sheet.append(('one', text, '2021-01-01', 'approved', '', digest, path))
    xlsx = tmp_path / 'review.xlsx'
    book.save(xlsx)
    monkeypatch.chdir(tmp_path)
    reviewed = tmp_path / 'reviewed.ndjson'
    import_review(manifest, xlsx, reviewed)
    assert json.loads(reviewed.read_text())['review_source_path'] == path
    compile_corpus(reviewed, tmp_path / 'corpus', 'social-post', 1, 42)
    result = json.loads((tmp_path / 'corpus/manifest.ndjson').read_text())
    assert result['review_source_path'] == os.path.relpath(source, root)
    assert result['source_manifest'] == os.path.relpath(tmp_path / 'source.ndjson', root)
    sampling = json.loads((tmp_path / 'corpus/sampling.json').read_text())['strata']['social-post']
    assert sampling['candidate_manifest'] == os.path.relpath(reviewed, root)
    assert sampling['candidate_sha256'] == hashlib.sha256(reviewed.read_bytes()).hexdigest()

    sheet['G2'] = str(source) if relative else os.path.relpath(source, root)
    book.save(xlsx)
    with pytest.raises(ValueError, match='Changed source data'):
        import_review(manifest, xlsx, tmp_path / 'bad.ndjson')
    sheet['G2'] = path
    book.save(xlsx)
    source.write_text('changed', encoding='utf-8')
    with pytest.raises(ValueError, match='Changed source file'):
        import_review(manifest, xlsx, tmp_path / 'bad.ndjson')


def test_corpus_retains_legacy_basename_and_existing_absolute_provenance(tmp_path):
    row = dict(candidate_id='one', text='Climate text', review_status='approved',
               stratum='first', actor='a', register='r', source='s', source_id='1',
               source_manifest='legacy.ndjson', review_source_path='/legacy/full.txt')
    candidates = tmp_path / 'candidates.ndjson'
    write_rows(candidates, [row])
    corpus = tmp_path / 'corpus'
    compile_corpus(candidates, corpus, 'first', 1, 1)
    first = json.loads((corpus / 'manifest.ndjson').read_text())
    assert first['source_manifest'] == 'legacy.ndjson'
    first['review_source_path'] = '/legacy/full.txt'
    write_rows(corpus / 'manifest.ndjson', [first])
    old = (corpus / 'manifest.ndjson').read_bytes()
    write_rows(candidates, [dict(row, candidate_id='two', stratum='second')])
    compile_corpus(candidates, corpus, 'second', 1, 1)
    assert (corpus / 'manifest.ndjson').read_bytes().startswith(old)


def test_replace_unit_review_and_preservation(tmp_path):
    from openpyxl import load_workbook
    from compile_corpus import replace_unit

    source = tmp_path / 'source.ndjson'
    write_rows(source, [{'_id': str(i), 'text': f'Climate change {i}', 'cdate': 1625164646880} for i in range(6)])
    candidates = tmp_path / 'candidates.ndjson'
    adapter.prepare(source, candidates)
    rows = [json.loads(line) for line in candidates.read_text().splitlines()]
    for row in rows:
        row['review_status'] = 'approved'
    write_rows(candidates, rows)
    sheet = tmp_path / 'review.xlsx'
    adapter.export_review(candidates, sheet)
    corpus = tmp_path / 'corpus'
    compile_corpus(candidates, corpus, 'social-post', 2, 42)
    before = [json.loads(line) for line in (corpus / 'manifest.ndjson').read_text().splitlines()]
    removed, kept = before
    (corpus / 'summary.txt').write_text('unchanged')
    old_sampling = json.loads((corpus / 'sampling.json').read_text())['strata']
    book = load_workbook(sheet)
    for row in book['Review'].iter_rows(min_row=2):
        if row[0].value == removed['candidate_id']:
            row[3].value = 'rejected'
    book.save(sheet)
    reviewed = tmp_path / 'reviewed.ndjson'
    import_review(candidates, sheet, reviewed)
    import shutil
    other = tmp_path / 'other'
    shutil.copytree(corpus, other)
    for target in (corpus, other):
        replace_unit(reviewed, target, removed['candidate_id'], 7)
    after = [json.loads(line) for line in (corpus / 'manifest.ndjson').read_text().splitlines()]
    assert after[1] == kept
    assert after[0]['candidate_id'] not in {r['candidate_id'] for r in before}
    assert (corpus / 'manifest.ndjson').read_bytes() == (other / 'manifest.ndjson').read_bytes()
    assert not (corpus / removed['filepath']).exists()
    assert (corpus / kept['filepath']).read_bytes() == (other / kept['filepath']).read_bytes()
    assert (corpus / 'summary.txt').read_text() == 'unchanged'
    sampling = json.loads((corpus / 'sampling.json').read_text())
    assert sampling['strata'] == old_sampling
    assert sampling['replacements'][0]['removed_candidate_id'] == removed['candidate_id']
    assert sampling['replacements'][0]['replacement_candidate_id'] == after[0]['candidate_id']
    extra = tmp_path / 'extra.ndjson'
    write_rows(extra, [dict(rows[0], candidate_id='extra', stratum='other')])
    compile_corpus(extra, corpus, 'other', 1, 1)
    assert json.loads((corpus / 'sampling.json').read_text())['replacements'] == sampling['replacements']


def test_replace_unit_fails_safely(tmp_path, monkeypatch):
    import compile_corpus as compiler

    rows = [dict(candidate_id=str(i), text='Climate text', review_status='approved',
                 stratum='social-post', actor='a', register='r', source='s', source_id=str(i)) for i in range(3)]
    candidates = tmp_path / 'candidates.ndjson'
    write_rows(candidates, rows)
    corpus = tmp_path / 'corpus'
    compile_corpus(candidates, corpus, 'social-post', 1, 42)
    original = {p.relative_to(corpus): p.read_bytes() for p in corpus.rglob('*') if p.is_file()}
    removed = json.loads((corpus / 'manifest.ndjson').read_text())['candidate_id']
    with pytest.raises(ValueError, match='rejected'):
        compiler.replace_unit(candidates, corpus, removed, 4)
    for row in rows:
        if row['candidate_id'] == removed:
            row['review_status'] = 'rejected'
            row['text'] = 'different'
    write_rows(candidates, rows)
    with pytest.raises(ValueError, match='does not match corpus'):
        compiler.replace_unit(candidates, corpus, removed, 4)
    for row in rows:
        row['text'] = 'Climate text'
    write_rows(candidates, rows)
    rename = compiler.os.rename

    # Fail only the staged publish, not the restoration of the backup.
    def fail_once(src, dst):
        if Path(dst) == corpus and Path(src).name == 'staged':
            raise OSError('simulated publish failure')
        return rename(src, dst)

    monkeypatch.setattr(compiler.os, 'rename', fail_once)
    with pytest.raises(OSError, match='simulated'):
        compiler.replace_unit(candidates, corpus, removed, 4)
    assert {p.relative_to(corpus): p.read_bytes() for p in corpus.rglob('*') if p.is_file()} == original


def test_replacement_retains_backup_if_restoration_fails(tmp_path, monkeypatch):
    import compile_corpus as compiler

    rows = [dict(candidate_id=str(i), text='Climate text', review_status='approved',
                 stratum='social-post', actor='a', register='r', source='s', source_id=str(i)) for i in range(2)]
    candidates = tmp_path / 'candidates.ndjson'
    write_rows(candidates, rows)
    corpus = tmp_path / 'corpus'
    compile_corpus(candidates, corpus, 'social-post', 1, 42)
    before = (corpus / 'manifest.ndjson').read_bytes()
    removed = json.loads(before)['candidate_id']
    for row in rows:
        if row['candidate_id'] == removed:
            row['review_status'] = 'rejected'
    write_rows(candidates, rows)
    rename = compiler.os.rename

    def fail_publish_and_restore(src, dst):
        if Path(dst) == corpus:
            raise OSError('simulated failure')
        return rename(src, dst)

    monkeypatch.setattr(compiler.os, 'rename', fail_publish_and_restore)
    with pytest.raises(OSError, match='simulated'):
        compiler.replace_unit(candidates, corpus, removed, 4)
    backups = list(tmp_path.glob('.replace-*/backup/manifest.ndjson'))
    assert len(backups) == 1 and backups[0].read_bytes() == before


def test_replacement_source_quota_and_no_eligible(tmp_path):
    from compile_corpus import replace_unit

    rows = [dict(candidate_id=str(i), text=f'text {i}', review_status='approved',
                 stratum='social-post', actor='a', register='r', source=source, source_id=str(i))
            for i, source in enumerate(('a', 'a', 'b', 'b'))]
    candidates = tmp_path / 'candidates.ndjson'
    write_rows(candidates, rows)
    corpus = tmp_path / 'corpus'
    compile_corpus(candidates, corpus, 'social-post', 2, 1, {'a': 1, 'b': 1})
    before = [json.loads(line) for line in (corpus / 'manifest.ndjson').read_text().splitlines()]
    removed = before[0]
    for row in rows:
        if row['candidate_id'] == removed['candidate_id']:
            row['review_status'] = 'rejected'
        elif row['source'] == removed['source']:
            row['review_status'] = 'pending'
    write_rows(candidates, rows)
    original = (corpus / 'manifest.ndjson').read_bytes()
    with pytest.raises(ValueError, match='No eligible'):
        replace_unit(candidates, corpus, removed['candidate_id'], 1)
    assert (corpus / 'manifest.ndjson').read_bytes() == original
    for row in rows:
        if row['review_status'] == 'pending':
            row['review_status'] = 'approved'
    write_rows(candidates, rows)
    replace_unit(candidates, corpus, removed['candidate_id'], 1)
    after = [json.loads(line) for line in (corpus / 'manifest.ndjson').read_text().splitlines()]
    assert after[0]['source'] == removed['source']


def test_replacement_cli_requires_valid_review(tmp_path):
    import subprocess
    import sys
    from openpyxl import load_workbook

    source = tmp_path / 'source.ndjson'
    write_rows(source, [{'_id': str(i), 'text': f'Climate {i}', 'cdate': 1625164646880} for i in range(3)])
    candidates = tmp_path / 'candidates.ndjson'
    adapter.prepare(source, candidates)
    rows = [json.loads(line) for line in candidates.read_text().splitlines()]
    for row in rows:
        row['review_status'] = 'approved'
    write_rows(candidates, rows)
    corpus = tmp_path / 'corpus'
    compile_corpus(candidates, corpus, 'social-post', 1, 42)
    removed = json.loads((corpus / 'manifest.ndjson').read_text())['candidate_id']
    sheet = tmp_path / 'review.xlsx'
    adapter.export_review(candidates, sheet)
    book = load_workbook(sheet)
    for row in book['Review'].iter_rows(min_row=2):
        if row[0].value == removed:
            row[3].value = 'rejected'
            row[1].value = 'tampered'
    book.save(sheet)
    reviewed = tmp_path / 'reviewed.ndjson'
    command = [sys.executable, str(Path(__file__).with_name('compile_corpus.py')), '--candidates', str(candidates),
               '--output', str(corpus), '--replace-candidate', removed, '--seed', '7',
               '--review-xlsx', str(sheet), '--reviewed-manifest', str(reviewed)]
    before = (corpus / 'manifest.ndjson').read_bytes()
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode != 0 and 'Changed source data' in result.stderr
    assert not reviewed.exists() and (corpus / 'manifest.ndjson').read_bytes() == before
    for row in book['Review'].iter_rows(min_row=2):
        if row[0].value == removed:
            row[1].value = next(item['text'] for item in rows if item['candidate_id'] == removed)
    book.save(sheet)
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads((corpus / 'manifest.ndjson').read_text())['candidate_id'] != removed