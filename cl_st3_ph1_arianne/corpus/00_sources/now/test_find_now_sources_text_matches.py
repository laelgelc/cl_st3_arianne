import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name('find_now_sources_text_matches.py')


class MatchNowSourcesTests(unittest.TestCase):
    def test_inclusive_dates_and_diagnostics(self):
        with tempfile.TemporaryDirectory(dir=SCRIPT.parent) as tmp:
            root = Path(tmp)
            articles, sources, output = (root / name for name in ('articles', 'sources', 'output'))
            articles.mkdir()
            sources.mkdir()
            (articles / 'selected.txt').write_text(
                '@@1 climate change\n@@2 climate change\n@@3 climate change\n'
                '@@4 climate change\n@@1 climate change\ninvalid line\n', encoding='utf-8')
            (sources / 'sources.txt').write_text(
                '1\tx\t15-11-01\tUS\tSource\thttps://example.org/1\tFirst\n'
                '2\tx\t22-11-30\tGB\tSource\thttps://example.org/2\tLast\n'
                '3\tx\t15-10-31\tUS\tSource\thttps://example.org/3\tEarly\n'
                '4\tx\t22-12-01\tUS\tSource\thttps://example.org/4\tLate\n', encoding='utf-8')
            result = subprocess.run([sys.executable, str(SCRIPT), '--initial-date', '2015-11-01',
                                     '--final-date', '2022-11-30', '--input-sources', str(sources),
                                     '--input-articles', str(articles), '--match', str(output)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

            def rows(name):
                with (output / name).open(encoding='utf-8', newline='') as handle:
                    return list(csv.DictReader(handle, delimiter='\t'))

            matches = rows('matched_sources.tsv')
            self.assertEqual([(r['article_id'], r['date_iso']) for r in matches],
                             [('1', '2015-11-01'), ('2', '2022-11-30')])
            self.assertEqual({r['article_id'] for r in rows('unmatched_article_ids.tsv')}, {'3', '4'})
            self.assertEqual(rows('duplicate_article_ids.tsv')[0]['article_id'], '1')
            self.assertEqual(rows('malformed_selected_article_lines.tsv')[0]['line_number'], '6')

    def test_rejects_reversed_dates(self):
        result = subprocess.run([sys.executable, str(SCRIPT), '--initial-date', '2022-12-01',
                                 '--final-date', '2015-11-01', '--input-sources', '.',
                                 '--input-articles', '.', '--match', 'unused'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must not be later', result.stdout)


if __name__ == '__main__':
    unittest.main()