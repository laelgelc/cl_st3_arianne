#!/usr/bin/env python3
"""Reconcile NOW lines with matched metadata and export a notebook manifest.

Dates filter metadata publication dates inclusively; article folders are scanned by month.
Month directories use YY-MM-text, text-YY-MM, or text_YY-MM-suffix. Filenames may have a
text_ prefix and a numeric suffix (with or without a hyphen). Only unambiguous,
matching IDs, months and countries are included. Identical metadata rows from
different source files retain all source paths; conflicting metadata is rejected.

Each run overwrites output-articles/YYYY_MM/cc/ID.txt for articles encountered,
duplicate_article_ids.tsv, duplicate_metadata_rows.tsv, unmatched_occurrences.tsv, malformed_selected_article_lines.tsv,
malformed_article_filenames.tsv, and organise_now_articles.log in output-articles;
it also overwrites climate_now.ndjson, climate_now.tsv and climate_now.xlsx in
manifest-dir (default: output-articles). Other files, including stale articles,
are not removed and are not included in the manifest. Use only a manifest from a
successful run, never a directory listing. Failed runs can leave partial outputs
or inconsistent manifests; for isolation use fresh output and manifest directories.
Manifest filepaths are relative to the invocation's working directory.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd


MONTH_PATTERN = re.compile(r"^(?:([0-9]{2})-([0-9]{2})-text|text-([0-9]{2})-([0-9]{2})|text_([0-9]{2})-([0-9]{2})-[a-z]+)$", re.IGNORECASE)
FILENAME_PATTERN = re.compile(r"^(?:text_)?[0-9]{2}[-_][0-9]{2}-([a-z]{2})(?:-?[0-9]+)?\.txt$", re.IGNORECASE)
ARTICLE_PATTERN = re.compile(r"^\s*@@([0-9]+)\b\s*(.*)$")
METADATA_COLUMNS = ["article_id", "now_field_2", "date_original", "date_iso", "country_code", "source_name", "url", "title", "article_file", "source_file"]
SEMANTIC_COLUMNS = ["now_field_2", "date_original", "date_iso", "country_code", "source_name", "url", "title"]
MANIFEST_COLUMNS = ["article_id", "group", "country_code", "filepath", "now_field_2", "date_original", "date_iso", "source_name", "url", "title", "source_files", "metadata_article_files"]


def parse_month(name: str) -> tuple[int, int] | None:
    match = MONTH_PATTERN.fullmatch(name)
    if not match:
        return None
    year, month = next((match.group(i), match.group(i + 1)) for i in (1, 3, 5) if match.group(i))
    if not 1 <= int(month) <= 12:
        return None
    return 2000 + int(year), int(month)


def walk(path: Path):
    def fail(error: OSError) -> None:
        raise error

    for root, directories, files in os.walk(path, onerror=fail):
        directories.sort()
        files.sort()
        yield Path(root), directories, files


def write_tsv(path: Path, header: list[str], rows: list) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def organise(input_dir: Path, output_dir: Path, manifest_dir: Path, initial: date, final: date, matched_sources: Path) -> None:
    if initial > final:
        raise ValueError("--initial-date must not be later than --final-date")
    input_dir = input_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    manifest_dir = manifest_dir.expanduser().resolve()
    matched_sources = matched_sources.expanduser().resolve()
    if not input_dir.is_dir():
        raise ValueError(f"Input articles directory does not exist or is not a directory: {input_dir}")
    for path in (output_dir, manifest_dir):
        if path == input_dir or input_dir in path.parents:
            raise ValueError(f"Output and manifest directories must not be inside the input directory: {path}")
    if output_dir in input_dir.parents:
        raise ValueError(f"Output articles directory must not contain the input directory: {output_dir}")

    metadata = defaultdict(list)
    with matched_sources.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)) or not set(METADATA_COLUMNS).issubset(reader.fieldnames):
            raise ValueError("matched_sources.tsv is missing required columns or has duplicate headers")
        for number, row in enumerate(reader, 2):
            if None in row or any(row[column] is None for column in METADATA_COLUMNS):
                raise ValueError(f"Malformed metadata row {number}")
            row["country_code"] = row["country_code"].strip().lower()
            if not re.fullmatch(r"[0-9]+", row["article_id"]):
                raise ValueError(f"Invalid article ID in metadata row {number}")
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["date_iso"]):
                    raise ValueError()
                published = date.fromisoformat(row["date_iso"])
            except ValueError as exc:
                raise ValueError(f"Invalid date_iso in metadata row {number}") from exc
            if initial <= published <= final:
                metadata[row["article_id"]].append(row)

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("organise_now_articles")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    handler = logging.FileHandler(output_dir / "organise_now_articles.log", mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)

    occurrences = defaultdict(list)
    malformed_lines = []
    malformed_files = []
    manifest = []
    selected = 0
    # Each file belongs to its nearest supported month ancestor, avoiding double
    # processing if a month directory is nested inside another month directory.
    for root, directories, files in walk(input_dir):
        month = None
        for parent in (root, *root.parents):
            if parent == input_dir:
                break
            month = parse_month(parent.name)
            if month:
                break
        if month is None or not (initial.year, initial.month) <= month <= (final.year, final.month):
            continue
        if parse_month(root.name):
            selected += 1
        year_month = f"{month[0]:04d}-{month[1]:02d}"
        group = f"{month[0]:04d}_{month[1]:02d}"
        for filename in files:
            if not filename.endswith(".txt"):
                continue
            source = root / filename
            relative = source.relative_to(input_dir).as_posix()
            match = FILENAME_PATTERN.fullmatch(filename)
            if not match:
                malformed_files.append((relative, year_month, "Filename does not match expected NOW article filename pattern"))
                continue
            country = match.group(1).lower()
            try:
                with source.open(encoding="utf-8", newline="") as handle:
                    for number, line in enumerate(handle, 1):
                        line = line.rstrip("\r\n")
                        if not line:
                            continue
                        article = ARTICLE_PATTERN.match(line)
                        if not article:
                            preview = line.replace("\t", " ").strip()
                            if len(preview) > 250:
                                preview = preview[:250] + "..."
                            malformed_lines.append((relative, number, year_month, country, preview))
                            continue
                        article_id, content = article.groups()
                        occurrence = (relative, number, year_month, country, content)
                        occurrences[article_id].append(occurrence)
            except (OSError, UnicodeError) as exc:
                raise OSError(f"Failed to process article file {source}: {exc}") from exc

    duplicates = []
    unmatched = []
    for article_id, found in sorted(occurrences.items()):
        if len(found) > 1:
            descriptors = ";".join(":".join(map(str, entry[:4])) for entry in found)
            duplicates.append((article_id, len(found), *found[0][:4], descriptors))
        candidates = metadata.get(article_id, [])
        variants = {tuple(row[column] for column in SEMANTIC_COLUMNS) for row in candidates}
        reason = "no_in_window_metadata" if not candidates else "conflicting_metadata" if len(variants) > 1 else "missing_metadata_country" if not candidates[0]["country_code"] else "invalid_metadata_country" if not re.fullmatch(r"[a-z]{2}", candidates[0]["country_code"]) else None
        matching = []
        for occurrence in found:
            relative, number, year_month, country, content = occurrence
            if reason:
                unmatched.append((article_id, relative, number, year_month, country, reason))
            elif year_month != candidates[0]["date_iso"][:7] or country != candidates[0]["country_code"]:
                unmatched.append((article_id, relative, number, year_month, country, "month_country_mismatch"))
            else:
                matching.append(occurrence)
        if len({entry[4] for entry in matching}) > 1:
            unmatched.extend((article_id, *entry[:4], "ambiguous_text") for entry in matching)
            continue
        if matching:
            relative, number, year_month, country, content = matching[0]
            group = year_month.replace("-", "_")
            target = output_dir / group / country / f"{article_id}.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content.strip() + "\n", encoding="utf-8")
            row = candidates[0]
            sources = json.dumps(sorted({item["source_file"] for item in candidates}), ensure_ascii=False)
            article_files = json.dumps(sorted({item["article_file"] for item in candidates}), ensure_ascii=False)
            manifest.append((article_id, group, country, Path(os.path.relpath(target, Path.cwd())).as_posix(), row["now_field_2"], row["date_original"], row["date_iso"], row["source_name"], row["url"], row["title"], sources, article_files))
    write_tsv(output_dir / "duplicate_article_ids.tsv", ["article_id", "occurrence_count", "first_article_file", "first_line_number", "first_year_month", "first_country_code", "all_occurrences"], duplicates)
    metadata_duplicates = [(article_id, "conflicting" if len({tuple(row[column] for column in SEMANTIC_COLUMNS) for row in entries}) > 1 else "equivalent", *(row[column] for column in METADATA_COLUMNS)) for article_id, entries in sorted(metadata.items()) if len(entries) > 1 for row in entries]
    write_tsv(output_dir / "duplicate_metadata_rows.tsv", ["duplicate_id", "status", *METADATA_COLUMNS], metadata_duplicates)
    write_tsv(output_dir / "unmatched_occurrences.tsv", ["article_id", "article_file", "line_number", "year_month", "country_code", "reason"], unmatched)
    write_tsv(output_dir / "malformed_selected_article_lines.tsv", ["article_file", "line_number", "year_month", "country_code", "line_preview"], malformed_lines)
    write_tsv(output_dir / "malformed_article_filenames.tsv", ["article_file", "year_month", "reason"], malformed_files)
    frame = pd.DataFrame(manifest, columns=MANIFEST_COLUMNS)
    frame.to_json(manifest_dir / "climate_now.ndjson", orient="records", lines=True, force_ascii=False)
    frame.to_csv(manifest_dir / "climate_now.tsv", sep="\t", index=False)
    # Excel cannot represent these control characters; preserve them in the other exports.
    excel_frame = frame.replace(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]", "", regex=True)
    excel_frame.to_excel(manifest_dir / "climate_now.xlsx", index=False)
    logger.info("Selected month directories: %d; articles: %d; duplicate IDs: %d; malformed lines: %d; malformed filenames: %d", selected, len(manifest), len(duplicates), len(malformed_lines), len(malformed_files))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--initial-date", default="2015-11-01", help="First publication date (YYYY-MM-DD)")
    parser.add_argument("--final-date", default="2022-11-30", help="Last publication date (YYYY-MM-DD)")
    parser.add_argument("--matched-sources", required=True, help="Matcher's matched_sources.tsv")
    parser.add_argument("--input-articles", required=True, help="Selected article directory")
    parser.add_argument("--output-articles", required=True, help="Organised article and diagnostic directory")
    parser.add_argument("--manifest-dir", help="Manifest directory (default: output-articles)")
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.initial_date) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.final_date):
            raise ValueError("Dates must use YYYY-MM-DD format")
        organise(Path(args.input_articles), Path(args.output_articles), Path(args.manifest_dir or args.output_articles), date.fromisoformat(args.initial_date), date.fromisoformat(args.final_date), Path(args.matched_sources))
    except (ValueError, OSError, UnicodeError, ImportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())