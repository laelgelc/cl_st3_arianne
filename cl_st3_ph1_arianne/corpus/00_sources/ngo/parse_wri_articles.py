#!/usr/bin/env python3
"""Extract provisional WRI paragraphs offline; review all reported exclusions.

Approved external canonicals are retained alongside the logged WRI URLs. The
displayed original publication date is used. Saved text may have later updates.
Output is created exclusively, never overwritten.
"""

import argparse
import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Comment, NavigableString

HERE = Path(__file__).resolve().parent
START = date(2015, 11, 1)
END = date(2022, 11, 30)
APPROVED_EXTERNAL = {
    'wri-p20-01.html': 'https://www.project-syndicate.org/commentary/governments-must-invest-now-in-disaster-preparedness-by-jagan-chapagain-and-andrew-steer-2020-06',
    'wri-p21-01.html': 'https://www.responsible-investor.com/articles/how-can-financial-institutions-deliver-on-the-paris-agreement',
    'wri-p28-01.html': 'https://www.cnn.com/2018/10/08/opinions/un-climate-report-decarbonization-steer/index.html',
    'wri-p31-01.html': 'http://www.climatechangenews.com/2018/04/12/need-long-term-strategies-meet-challenge-climate-change/',
}


def normalized_url(url):
    parts = urlsplit(url.strip())
    if parts.scheme not in ('http', 'https') or not parts.netloc or parts.query or parts.fragment:
        raise ValueError(f'invalid URL: {url!r}')
    return parts.netloc.lower(), parts.path.rstrip('/')


def read_log(path):
    entries = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        match = re.match(r'^\|\s*(wri-p\d+-\d+\.html)\s*\|\s*\d+\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*(https?://[^\s|]+)\s*\|', line)
        if match:
            name, listing_date, url = match.groups()
            if name in entries:
                raise ValueError(f'duplicate log filename: {name}')
            date.fromisoformat(listing_date)
            entries[name] = (listing_date, url)
    if not entries:
        raise ValueError('no collection log entries')
    return entries


def body_text(body):
    paragraphs, fragments = [], []

    def flush():
        text = ' '.join(''.join(fragments).split())
        if text:
            paragraphs.append(text)
        fragments.clear()

    def visit(node, active=False):
        if isinstance(node, Comment):
            return
        if isinstance(node, NavigableString):
            if active:
                fragments.append(str(node))
            return
        boundary = node.name in ('p', 'li', 'ul', 'ol')
        if boundary:
            flush()
        for child in node.children:
            visit(child, active or node.name in ('p', 'li'))
        if boundary:
            flush()

    visit(body)
    return paragraphs


def parse_article(path, listing_date, expected_url):
    soup = BeautifulSoup(path.read_text(encoding='utf-8'), 'html.parser')
    article = soup.select_one('article.node--type-article')
    canonical = soup.select_one('link[rel~=canonical][href]')
    if not article or not canonical or not soup.html:
        raise ValueError('missing article or canonical URL')
    canonical_url = canonical['href']
    approved = APPROVED_EXTERNAL.get(path.name)
    if normalized_url(canonical_url) != normalized_url(expected_url) and (
            not approved or normalized_url(canonical_url) != normalized_url(approved)):
        raise ValueError(f'canonical mismatch: {canonical_url} (logged {expected_url}); review republishing or wrong page')
    if soup.html.get('lang', '').lower().split('-')[0] != 'en':
        raise ValueError('language not explicitly English')
    title = article.select_one('h1')
    body = article.select('.article__main .main-content')
    if not title or not title.get_text(' ', strip=True) or len(body) != 1:
        raise ValueError('missing title or unambiguous article body')
    time = article.select_one('.originally-published time')
    if not time:
        raise ValueError('original publication date missing; listing date is not evidence')
    try:
        published = datetime.strptime(time.get_text(' ', strip=True), '%B %d, %Y').date()
    except ValueError as exc:
        raise ValueError('invalid publication date') from exc
    if not START <= published <= END:
        raise ValueError(f'publication outside timeframe: {published}')
    author = article.select_one('.author-listing')
    authors = re.sub(r'^By:\s*', '', author.get_text(' ', strip=True)) if author else None
    tags, regions = [], []
    for link in article.select('a.tag-button[href]'):
        text = link.get_text(' ', strip=True)
        if not text:
            continue
        target = regions if urlsplit(link['href']).path.startswith('/regions/') else tags
        if text not in target:
            target.append(text)
    for unwanted in body[0].select('figure, figcaption, table, script, style, svg, .caption, .callout, .post-body-content'):
        unwanted.decompose()
    paragraphs = body_text(body[0])
    if not paragraphs:
        raise ValueError('article body has no paragraphs')
    term = article.select_one('.insights-tags .taxonomy-term')
    record = {
        'Source': 'WRI', 'Post Term': term.get_text(' ', strip=True) if term else None,
        'Post Tags': ', '.join(tags), 'Title': title.get_text(' ', strip=True),
        'Post URL': expected_url, 'Canonical URL': canonical_url,
        'Authors': authors or None, 'Post Date': published.isoformat(),
        'Post ID': 'wri' + hashlib.sha256(expected_url.encode('utf-8')).hexdigest(),
        'Category': None, 'Region': ', '.join(regions) or None,
        'Saved File': path.name, 'Listing Date': listing_date,
    }
    return [dict(record, Paragraph=f'Paragraph {i}', **{'Text Paragraph': text})
            for i, text in enumerate(paragraphs, 1)]


def extract(directory, log):
    entries = read_log(log)
    files = {p.name: p for p in directory.glob('*.html')}
    issues = [f'{name}: unlogged file' for name in sorted(files.keys() - entries.keys())]
    records, seen_urls, seen_content = [], {}, {}
    for name, (listing_date, url) in sorted(entries.items()):
        if name not in files:
            issues.append(f'{name}: missing saved page')
            continue
        try:
            rows = parse_article(files[name], listing_date, url)
            key = normalized_url(rows[0]['Canonical URL'])
            content = tuple(row['Text Paragraph'] for row in rows)
            if key in seen_urls or content in seen_content:
                raise ValueError(f'duplicate article of {seen_urls.get(key) or seen_content[content]}')
            seen_urls[key], seen_content[content] = name, name
            records.extend(rows)
        except (ValueError, UnicodeError) as exc:
            issues.append(f'{name}: {exc}')
    return records, issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pages', type=Path, default=HERE / 'wri_pages')
    parser.add_argument('--log', type=Path, default=HERE / 'wri_article_collection_log.md')
    parser.add_argument('--output', type=Path, default=HERE / 'wri.jsonl')
    args = parser.parse_args()
    records, issues = extract(args.pages, args.log)
    if not records:
        raise SystemExit('No validated records; output not created.\n' + '\n'.join(issues))
    with args.output.open('x', encoding='utf-8') as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False) + '\n')
    print(f'Wrote {len(records)} paragraphs from {len({r["Post ID"] for r in records})} articles to {args.output}')
    print(f'{len(issues)} issues requiring review:')
    for issue in issues:
        print(f'- {issue}')
    print('Manual review: English language, article boundaries, tags and original publication dates; saved pages may contain later updates.')


if __name__ == '__main__':
    main()