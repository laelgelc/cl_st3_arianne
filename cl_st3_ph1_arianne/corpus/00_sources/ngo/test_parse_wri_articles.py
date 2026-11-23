import tempfile
import unittest
from pathlib import Path

import parse_wri_articles as parser


URL = 'https://www.wri.org/insights/example'
HTML = '''<html lang="en"><head><link rel="canonical" href="{url}">
<meta name="wri_published" content="{meta}"></head><body>
<article class="node--type-article"><h1>Title</h1>
<div class="insights-tags"><span class="taxonomy-term">Insights</span></div>
<div class="author-listing">By: Jane <a>Doe</a></div>
<span class="originally-published"><time datetime="{date}T12:00:00Z">{display}</time></span>
<a class="tag-button" href="/climate">Climate</a>
<a class="tag-button" href="/regions/africa">Africa</a>
<div class="article__main"><div class="main-content">
<p>Text <a>with link</a> and punctuation.</p><figure><p>Caption</p></figure>
<table><tr><td><p>Table cell</p></td></tr></table><div class="post-body-content"><p>Expert role</p></div>
<p>Another paragraph.</p><p> </p></div></div></article><p>Footer</p></body></html>'''


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'wri-p10-01.html'

    def write(self, url=URL, date='2015-11-01', meta='November 1 2015'):
        from datetime import date as date_type
        display = date_type.fromisoformat(date).strftime('%B %d, %Y')
        self.path.write_text(HTML.format(url=url, date=date, meta=meta, display=display), encoding='utf-8')

    def test_extract_and_boundaries(self):
        self.write()
        rows = parser.parse_article(self.path, '2022-01-01', URL)
        self.assertEqual([r['Text Paragraph'] for r in rows], ['Text with link and punctuation.', 'Another paragraph.'])
        self.assertEqual(rows[0]['Post Date'], '2015-11-01')
        self.assertEqual(rows[0]['Post Tags'], 'Climate')
        self.assertEqual(rows[0]['Region'], 'Africa')
        self.assertEqual(rows[1]['Paragraph'], 'Paragraph 2')
        self.write(date='2022-11-30', meta='November 30 2022')
        self.assertEqual(len(parser.parse_article(self.path, '2022-11-30', URL)), 2)

    def test_lists_in_source_order_without_nested_duplicates(self):
        self.write()
        html = self.path.read_text(encoding='utf-8').replace(
            '<p>Another paragraph.</p>',
            '<ul><li>First <strong>item</strong>.</li>'
            '<li><p>Wrapped paragraph.</p><p>Second paragraph.</p></li>'
            '<li>Parent before<ul><li>Nested item.</li></ul>Parent after</li>'
            '<li> </li></ul><figure><ul><li>Caption item</li></ul></figure>'
            '<p>Another paragraph.</p>')
        self.path.write_text(html, encoding='utf-8')
        rows = parser.parse_article(self.path, '2022-01-01', URL)
        self.assertEqual([r['Text Paragraph'] for r in rows], [
            'Text with link and punctuation.', 'First item.', 'Wrapped paragraph.',
            'Second paragraph.', 'Parent before', 'Nested item.', 'Parent after',
            'Another paragraph.',
        ])
        self.assertEqual([r['Paragraph'] for r in rows],
                         [f'Paragraph {i}' for i in range(1, 9)])

    def test_displayed_date_and_approved_external_canonical(self):
        self.path = self.root / 'wri-p28-01.html'
        external = 'https://www.cnn.com/2018/10/08/opinions/un-climate-report-decarbonization-steer/index.html'
        self.write(url=external, meta='November 2 2015')
        rows = parser.parse_article(self.path, '2020-01-01', URL)
        self.assertEqual(rows[0]['Post Date'], '2015-11-01')
        self.assertEqual(rows[0]['Post URL'], URL)
        self.assertEqual(rows[0]['Canonical URL'], external)

    def test_reject_invalid_mismatch_and_outside_date(self):
        for kwargs, error in [({'url': 'https://other.example/story'}, 'canonical mismatch'),
                              ({'date': '2015-10-31', 'meta': 'October 31 2015'}, 'outside timeframe'),
                              ({'date': '2022-12-01', 'meta': 'December 1 2022'}, 'outside timeframe')]:
            self.write(**kwargs)
            with self.assertRaisesRegex(ValueError, error):
                parser.parse_article(self.path, '2020-01-01', URL)
        self.path.write_text('<html><title>Error</title></html>', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'missing article'):
            parser.parse_article(self.path, '2020-01-01', URL)

    def test_log_and_duplicates(self):
        self.write()
        other = self.root / 'wri-p10-02.html'
        other.write_text(self.path.read_text(), encoding='utf-8')
        log = self.root / 'log.md'
        log.write_text(f'| {self.path.name} | 10 | 2020-01-01 | {URL} |\n| {other.name} | 10 | 2020-01-01 | {URL} |\n| wri-p10-03.html | 10 | 2020-01-01 | {URL} |\n', encoding='utf-8')
        rows, issues = parser.extract(self.root, log)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(issues), 2)
        self.assertIn('duplicate', issues[0])
        self.assertIn('missing', issues[1])


if __name__ == '__main__':
    unittest.main()