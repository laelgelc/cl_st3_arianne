import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import summarise_corpus as summary


class SummaryWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.corpus = self.root / 'corpus'
        (self.corpus / 'human').mkdir(parents=True)
        self.checkpoints = self.root / 'checkpoints'
        self.prompt = self.root / 'prompt.md'
        self.prompt.write_text('Instructions', encoding='utf-8')
        self.manifest = []
        for uid in ('one', 'two'):
            text = f'{uid} source text'
            path = f'human/{uid}.txt'
            (self.corpus / path).write_text(text, encoding='utf-8')
            self.manifest.append({'unit_id': uid, 'filepath': path, 'authorship': 'human',
                                  'stratum': 'pilot' if uid == 'one' else 'other', 'source_id': uid + '-source',
                                  'text_sha256': summary.digest(text.encode())})
        self.write_manifest()
        self.client = SimpleNamespace(responses=SimpleNamespace(create=Mock(
            return_value=SimpleNamespace(status='completed', output_text='A concise summary.'))))

    def write_manifest(self):
        (self.corpus / 'manifest.ndjson').write_text(
            ''.join(json.dumps(row) + '\n' for row in self.manifest), encoding='utf-8')

    def generate(self):
        summary.generate(self.corpus, self.checkpoints, self.prompt, client=self.client)

    def test_generation_resume_and_provenance(self):
        self.generate()
        self.assertEqual(self.client.responses.create.call_count, 2)
        call = self.client.responses.create.call_args_list[0].kwargs
        self.assertEqual(call, {'model': 'gpt-6.1-terra', 'instructions': 'Instructions', 'input': 'one source text', 'max_output_tokens': 2000})
        self.generate()
        self.assertEqual(self.client.responses.create.call_count, 2)
        self.prompt.write_text('Changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'provenance'):
            self.generate()

    def test_failure_leaves_completed_checkpoint_for_retry(self):
        self.client.responses.create.side_effect = [SimpleNamespace(status='completed', output_text='First'), RuntimeError('API error')]
        with self.assertRaisesRegex(RuntimeError, 'API error'):
            self.generate()
        self.assertTrue((self.checkpoints / 'one.json').exists())
        self.assertFalse((self.checkpoints / 'two.json').exists())
        self.client.responses.create.side_effect = None
        self.generate()
        self.assertEqual(self.client.responses.create.call_count, 3)

    def test_invalid_responses_not_checkpointed(self):
        for response in (SimpleNamespace(status='incomplete', output_text='partial'),
                         SimpleNamespace(status='completed', output_text=''),
                         SimpleNamespace(status='completed', output_text='word ' * 101)):
            self.client.responses.create.return_value = response
            with self.assertRaises(ValueError):
                self.generate()
            self.assertFalse((self.checkpoints / 'one.json').exists())

    def test_review_validation_and_no_overwrite(self):
        self.generate()
        review, output = self.root / 'review.jsonl', self.root / 'reviewed.jsonl'
        summary.export_review(self.corpus, self.checkpoints, review)
        rows = [json.loads(line) for line in review.read_text().splitlines()]
        rows[0]['summary'] = 'Edited summary with four words'
        rows[0]['review_status'] = 'approved'
        rows[0]['review_notes'] = 'Checked against source'
        review.write_bytes(b''.join(summary.encoded(row) for row in rows))
        summary.import_review(self.corpus, self.checkpoints, review, output)
        result = json.loads(output.read_text().splitlines()[0])
        self.assertEqual(result['summary_word_count'], 5)
        self.assertEqual(result['source_word_count'], 3)
        self.assertEqual(result['review_notes'], 'Checked against source')
        self.assertEqual(result['generated_summary'], 'A concise summary.')
        self.assertEqual(result['checkpoint_sha256'], summary.digest((self.checkpoints / 'one.json').read_bytes()))
        with self.assertRaises(FileExistsError):
            summary.import_review(self.corpus, self.checkpoints, review, output)
        rows[0]['source_sha256'] = 'tampered'
        review.write_bytes(b''.join(summary.encoded(row) for row in rows))
        with self.assertRaisesRegex(ValueError, 'immutable'):
            summary.import_review(self.corpus, self.checkpoints, review, self.root / 'bad')
        self.assertFalse((self.root / 'bad').exists())

    def test_review_rejects_missing_duplicate_invalid_status_and_long_summary(self):
        self.generate()
        review = self.root / 'review.jsonl'
        summary.export_review(self.corpus, self.checkpoints, review)
        rows = [json.loads(line) for line in review.read_text().splitlines()]
        cases = [[rows[0]], [rows[0], rows[0]],
                 [{**rows[0], 'review_status': 'yes'}, rows[1]],
                 [{**rows[0], 'summary': 'x ' * 101}, rows[1]]]
        for case in cases:
            review.write_bytes(b''.join(summary.encoded(row) for row in case))
            with self.assertRaises(ValueError):
                summary.import_review(self.corpus, self.checkpoints, review, self.root / 'out')

    def test_source_hash_and_paths(self):
        self.manifest[0]['filepath'] = '../escape'
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            self.generate()
        self.manifest[0]['filepath'] = 'human/one.txt'
        self.write_manifest()
        (self.corpus / 'human/one.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.generate()
        self.assertEqual(self.client.responses.create.call_count, 0)

    def test_symlink_escape_and_changed_source_on_import(self):
        external = self.root / 'external.txt'
        external.write_text('one source text')
        (self.corpus / 'human/one.txt').unlink()
        (self.corpus / 'human/one.txt').symlink_to(external)
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            self.generate()
        (self.corpus / 'human/one.txt').unlink()
        (self.corpus / 'human/one.txt').write_text('one source text')
        self.generate()
        review = self.root / 'review'
        summary.export_review(self.corpus, self.checkpoints, review)
        (self.corpus / 'human/one.txt').write_text('altered')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            summary.import_review(self.corpus, self.checkpoints, review, self.root / 'out')

    def test_pilot_selection_and_metadata(self):
        self.manifest.reverse()
        self.write_manifest()
        self.client.responses.create.return_value = SimpleNamespace(status='completed', output_text='Pilot', id='resp-1', model='actual-model')
        summary.generate(self.corpus, self.checkpoints, self.prompt, client=self.client, limit=1, max_output_tokens=123)
        self.assertEqual(self.client.responses.create.call_args.kwargs['max_output_tokens'], 123)
        row = json.loads((self.checkpoints / 'one.json').read_text())
        self.assertEqual((row['stratum'], row['source_id'], row['prompt'], row['response_id'], row['actual_model']),
                         ('pilot', 'one-source', 'Instructions', 'resp-1', 'actual-model'))
        with self.assertRaisesRegex(ValueError, 'provenance'):
            summary.generate(self.corpus, self.checkpoints, self.prompt, client=self.client, limit=1)
        review, output = self.root / 'pilot.jsonl', self.root / 'out.jsonl'
        summary.export_review(self.corpus, self.checkpoints, review, stratum='pilot', limit=1)
        summary.import_review(self.corpus, self.checkpoints, review, output, stratum='pilot', limit=1)
        self.assertEqual(len(output.read_text().splitlines()), 1)
        with self.assertRaises(FileNotFoundError):
            summary.export_review(self.corpus, self.checkpoints, self.root / 'all')
        with self.assertRaises(ValueError):
            summary.generate(self.corpus, self.checkpoints, self.prompt, client=self.client, limit=0)

    def test_review_notes_must_be_text(self):
        self.generate()
        review = self.root / 'review'
        summary.export_review(self.corpus, self.checkpoints, review)
        rows = [json.loads(line) for line in review.read_text().splitlines()]
        rows[0]['review_notes'] = 1
        review.write_bytes(b''.join(summary.encoded(row) for row in rows))
        with self.assertRaises(ValueError):
            summary.import_review(self.corpus, self.checkpoints, review, self.root / 'out')

    def test_xlsx_review_roundtrip_and_validation(self):
        from openpyxl import load_workbook
        self.generate()
        review, output = self.root / 'review.xlsx', self.root / 'reviewed.ndjson'
        summary.export_review(self.corpus, self.checkpoints, review)
        book = load_workbook(review)
        sheet = book['Summaries']
        sheet['F2'] = 'Corrected summary'
        sheet['G2'] = 'approved'
        sheet['H2'] = 'Checked'
        book.save(review)
        summary.import_review(self.corpus, self.checkpoints, review, output)
        row = json.loads(output.read_text().splitlines()[0])
        self.assertEqual((row['summary'], row['review_status'], row['review_notes']),
                         ('Corrected summary', 'approved', 'Checked'))
        self.assertEqual(row['generated_summary'], 'A concise summary.')
        sheet['D2'] = 'changed'
        book.save(review)
        with self.assertRaisesRegex(ValueError, 'immutable'):
            summary.import_review(self.corpus, self.checkpoints, review, self.root / 'bad')
        sheet['D2'] = self.manifest[0]['text_sha256']
        sheet['F2'] = '=1+1'
        book.save(review)
        with self.assertRaisesRegex(ValueError, 'workbook row'):
            summary.import_review(self.corpus, self.checkpoints, review, self.root / 'bad')

    def test_xlsx_rejects_missing_and_duplicate_rows(self):
        from openpyxl import load_workbook
        self.generate()
        review = self.root / 'review.xlsx'
        summary.export_review(self.corpus, self.checkpoints, review)
        book = load_workbook(review)
        sheet = book['Summaries']
        sheet.delete_rows(3)
        book.save(review)
        with self.assertRaisesRegex(ValueError, 'missing'):
            summary.import_review(self.corpus, self.checkpoints, review, self.root / 'out')
        sheet.append([cell.value for cell in sheet[2]])
        book.save(review)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            summary.import_review(self.corpus, self.checkpoints, review, self.root / 'out')

    def test_changed_source_with_updated_manifest_rejects_resume(self):
        self.generate()
        text = 'new source text'
        (self.corpus / 'human/one.txt').write_text(text)
        self.manifest[0]['text_sha256'] = summary.digest(text.encode())
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'provenance'):
            self.generate()

    def test_cli_passes_selection_and_token_options(self):
        with patch('sys.argv', ['summarise_corpus.py', 'generate', '--corpus', 'c', '--checkpoints', 'd',
                                '--stratum', 'pilot', '--limit', '3', '--max-output-tokens', '321']), \
             patch.object(summary, 'generate') as generate:
            summary.main()
        self.assertEqual(generate.call_args.kwargs, {'stratum': 'pilot', 'limit': 3, 'max_output_tokens': 321, 'env_file': summary.ENV_FILE})

    def test_api_key_file_and_environment_precedence(self):
        env_file = self.root / '.env'
        env_file.write_text('# comment\nexport OPENAI_API_KEY="file-key"\n', encoding='utf-8')
        with patch.dict(os.environ, {}, clear=True):
            summary.load_api_key(env_file)
            self.assertEqual(os.environ['OPENAI_API_KEY'], 'file-key')
            os.environ['OPENAI_API_KEY'] = 'shell-key'
            summary.load_api_key(env_file)
            self.assertEqual(os.environ['OPENAI_API_KEY'], 'shell-key')
        with patch.dict(os.environ, {}, clear=True):
            summary.load_api_key(self.root / 'missing')
            self.assertNotIn('OPENAI_API_KEY', os.environ)

    def test_generation_loads_key_before_creating_client(self):
        import sys
        env_file = self.root / '.env'
        env_file.write_text('OPENAI_API_KEY=from-file\n', encoding='utf-8')
        def create_client():
            self.assertEqual(os.environ['OPENAI_API_KEY'], 'from-file')
            return self.client
        with patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules, {'openai': SimpleNamespace(OpenAI=create_client)}):
            summary.generate(self.corpus, self.checkpoints, self.prompt, env_file=env_file)
        self.assertEqual(self.client.responses.create.call_count, 2)


if __name__ == '__main__':
    unittest.main()