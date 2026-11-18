#!/usr/bin/env python3
"""Select a reproducible page-stratified sample from the WRI manifest."""

import argparse
import json
import random
from datetime import date
from pathlib import Path


HERE = Path(__file__).resolve().parent
START = date(2015, 11, 1)
END = date(2022, 11, 30)
SEED = 20261118
SINGLE_PAGES = {10, 15, 20, 25, 30, 35, 40}


def select(records, seed=SEED):
    by_page = {page: [] for page in range(10, 47)}
    seen = set()
    for record in records:
        url = record["Post URL"]
        if not url or url in seen:
            raise ValueError(f"Empty or duplicate URL: {url!r}")
        seen.add(url)
        listing_date = date.fromisoformat(record["Post Date"])
        if START <= listing_date <= END:
            pages = sorted(set(record["Listing Pages"]) & by_page.keys())
            if pages:
                # Assign a repeated listing to one stratum, preventing duplicate selection.
                by_page[pages[0]].append(record)

    rng = random.Random(seed)
    selected = []
    for page in sorted(by_page, reverse=True):
        candidates = sorted(by_page[page], key=lambda record: record["Post URL"])
        quota = 1 if page in SINGLE_PAGES else 2
        if len(candidates) < quota:
            raise ValueError(f"Page {page}: need {quota} eligible records, found {len(candidates)}")
        for index, record in enumerate(rng.sample(candidates, quota), 1):
            selected.append((page, index, record))
    return selected


def render_log(selected, seed):
    lines = [
        "# WRI article collection log", "",
        "- Target: 67 articles; listing-date window: 1 November 2015–30 November 2022, inclusive.",
        f"- Page-stratified random sample from `wri_list.jsonl`; seed: {seed}. One from pages 10, 15, 20, 25, 30, 35 and 40, two from each other page (10–46).",
        "- These are provisional selections: verify each article's original publication date and English language before inclusion. Listing dates may be update dates.",
        "- Record exclusions and replacements below; do not silently rerun the selection after collection begins.", "",
        "## File naming", "",
        "Save each article as `wri-pNN-SS.html`, where `NN` is the saved listing page and `SS` is its selection number. Use unique filenames for replacements.", "",
        "## Article log", "",
        "| Filename | Listing page | Listing date | Article URL |",
        "|---|---:|---|---|",
    ]
    for page, index, record in selected:
        lines.append(f"| wri-p{page:02d}-{index:02d}.html | {page} | {record['Post Date']} | {record['Post URL']} |")
    lines.extend(["", "## Sampling notes and substitutions", "", "- Pending article verification.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=HERE / "wri_list.jsonl")
    parser.add_argument("--output", type=Path, default=HERE / "wri_article_collection_log.md")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    with args.manifest.open(encoding="utf-8") as source:
        records = [json.loads(line) for line in source if line.strip()]
    selected = select(records, args.seed)
    args.output.write_text(render_log(selected, args.seed), encoding="utf-8")
    print(f"Wrote {len(selected)} provisional selections to {args.output}")


if __name__ == "__main__":
    main()