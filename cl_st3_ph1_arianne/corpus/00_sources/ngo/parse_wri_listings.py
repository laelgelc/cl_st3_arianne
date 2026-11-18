#!/usr/bin/env python3
"""Create a JSONL manifest from locally saved WRI listing pages."""

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
BASE_URL = "https://www.wri.org"


def parse_listing(path):
    match = re.fullmatch(r"wri-p(\d+)\.html", path.name)
    if not match:
        raise ValueError(f"Unexpected listing filename: {path.name}")
    page = int(match.group(1))
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    cards = soup.select(".search-results-container")
    if not cards:
        raise ValueError(f"No result cards found in {path}")
    records = []
    for card in cards:
        title_link = card.select_one(".search-results-text h3 a[href]")
        date = card.select_one(".search-results-text .post-date")
        kind = card.select_one(".content-type-region.bundle")
        if not title_link or not date or not kind:
            raise ValueError(f"Missing required card metadata in {path}")
        title = title_link.get_text(" ", strip=True)
        url = urljoin(BASE_URL, title_link["href"])
        if not title or not title_link["href"].strip():
            raise ValueError(f"Empty title or URL in {path}")
        try:
            date_iso = datetime.strptime(date.get_text(" ", strip=True), "%B %d, %Y").date().isoformat()
        except ValueError as exc:
            raise ValueError(f"Invalid listing date in {path}: {date.get_text(' ', strip=True)!r}") from exc
        tags = [tag.get_text(" ", strip=True) for tag in card.select(".search-results-text .tags li")]
        records.append({
            "Source": "WRI",
            "Post Term": kind.get_text(" ", strip=True),
            "Post Tags": ", ".join(tags),
            "Title": title,
            "Post URL": url,
            "Authors": None,
            "Post Date": date_iso,
            "Post ID": "wri" + hashlib.sha256(url.encode("utf-8")).hexdigest(),
            "Listing Pages": [page],
        })
    return records


def build_manifest(directory):
    paths = sorted(directory.glob("wri-p*.html"), key=lambda path: int(re.fullmatch(r"wri-p(\d+)\.html", path.name).group(1)) if re.fullmatch(r"wri-p(\d+)\.html", path.name) else -1)
    if not paths:
        raise ValueError(f"No WRI listing files found in {directory}")
    by_url = {}
    for path in paths:
        for record in parse_listing(path):
            url = record["Post URL"]
            if url in by_url:
                previous = by_url[url]
                if any(previous[key] != record[key] for key in ("Title", "Post Date", "Post Term", "Post Tags")):
                    raise ValueError(f"Conflicting metadata for {url} in {path}")
                page = record["Listing Pages"][0]
                if page not in previous["Listing Pages"]:
                    previous["Listing Pages"].append(page)
            else:
                by_url[url] = record
    return list(by_url.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listings", type=Path, default=HERE / "wri_listings")
    parser.add_argument("--output", type=Path, default=HERE / "wri_list.jsonl")
    args = parser.parse_args()
    records = build_manifest(args.listings)
    with args.output.open("w", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Wrote {len(records)} unique records to {args.output}")


if __name__ == "__main__":
    main()