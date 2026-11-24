import csv
import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

import organise_now_articles as organiser


def put(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def rows(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def metadata_file(path, entries):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(organiser.METADATA_COLUMNS)
        for article_id, day, country in entries:
            writer.writerow([article_id, "x", day[2:], day, country, "source", "url", "title", "selected.txt", "sources.txt"])
    return path


def test_reconciliation(tmp_path):
    source, output = tmp_path / "input", tmp_path / "output"
    put(source / "15-11-text/15-11-us.txt", "@@1 same\n@@1 same\n@@2 first\n@@2 different\n@@3 conflict\n@@4 no metadata\n@@5 outside day\n@@6 wrong country\n")
    metadata = tmp_path / "matched_sources.tsv"
    header = "article_id\tnow_field_2\tdate_original\tdate_iso\tcountry_code\tsource_name\turl\ttitle\tarticle_file\tsource_file\n"
    def entry(id, day="15", country="US", title="title", file="a.txt"):
        return f"{id}\tx\t15-11-{day}\t2015-11-{day}\t{country}\tsource\turl\t{title}\tselected.txt\t{file}\n"
    put(metadata, header + entry(1) + entry(1, file="b.txt") + entry(2) + entry(3) + entry(3, title="other") + entry(5, day="01") + entry(6, country="CA"))
    organiser.organise(source, output, output, date(2015, 11, 10), date(2015, 11, 20), metadata)
    result = rows(output / "climate_now.tsv")
    assert [r["article_id"] for r in result] == ["1"]
    assert result[0]["date_iso"] == "2015-11-15"
    assert json.loads(result[0]["source_files"]) == ["a.txt", "b.txt"]
    assert (output / "2015_11/us/1.txt").read_text() == "same\n"
    reasons = {r["article_id"]: r["reason"] for r in rows(output / "unmatched_occurrences.tsv")}
    assert reasons == {"2": "ambiguous_text", "3": "conflicting_metadata", "4": "no_in_window_metadata", "5": "no_in_window_metadata", "6": "month_country_mismatch"}
    assert {r["article_id"] for r in rows(output / "duplicate_article_ids.tsv")} == {"1", "2"}
    assert {(r["duplicate_id"], r["status"]) for r in rows(output / "duplicate_metadata_rows.tsv")} == {("1", "equivalent"), ("3", "conflicting")}


def test_eligible_occurrence_and_mismatched_duplicate(tmp_path):
    source, output = tmp_path / "input", tmp_path / "output"
    put(source / "15-11-text/15-11-us.txt", "@@1 eligible\n")
    put(source / "15-12-text/15-12-us.txt", "@@1 other month\n")
    metadata = metadata_file(tmp_path / "matched_sources.tsv", [("1", "2015-11-30", "US")])
    organiser.organise(source, output, output, date(2015, 11, 30), date(2015, 12, 1), metadata)
    assert [r["article_id"] for r in rows(output / "climate_now.tsv")] == ["1"]
    assert rows(output / "unmatched_occurrences.tsv")[0]["reason"] == "month_country_mismatch"


@pytest.mark.parametrize("country,reason", [("  ", "missing_metadata_country"), ("? ", "invalid_metadata_country"), ("y ", "invalid_metadata_country")])
def test_missing_metadata_country_is_reported_not_inferred(tmp_path, country, reason):
    source, output = tmp_path / "input", tmp_path / "output"
    put(source / "19-07-text/19-07-xx.txt", "@@50934304 climate change\n")
    metadata = metadata_file(tmp_path / "matched_sources.tsv", [("50934304", "2019-07-06", country)])
    organiser.organise(source, output, output, date(2019, 7, 1), date(2019, 7, 31), metadata)
    assert rows(output / "climate_now.tsv") == []
    assert rows(output / "unmatched_occurrences.tsv")[0]["reason"] == reason


def test_invalid_metadata_is_fatal(tmp_path, capsys):
    source, output = tmp_path / "input", tmp_path / "output"
    put(source / "15-11-text/15-11-us.txt", "@@1 text\n")
    metadata = tmp_path / "matched_sources.tsv"
    args = ["--input-articles", str(source), "--output-articles", str(output), "--matched-sources", str(metadata)]
    assert organiser.main(args) == 1
    put(metadata, "article_id\tdate_iso\n1\tbad\n")
    assert organiser.main(args) == 1
    metadata_file(metadata, [("1", "2015-02-30", "us")])
    assert organiser.main(args) == 1
    assert "Invalid date_iso" in capsys.readouterr().err
    assert not output.exists()


def test_month_bounds_duplicates_diagnostics_and_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "input"
    output = tmp_path / "résultats"
    manifests = tmp_path / "manifests"
    put(source / "15-10-text/15-10-us.txt", "@@9 outside\n")
    put(source / "15-11-text/15_11-US1.txt", "@@1 first café\nnot an article\n@@1 second\n")
    put(source / "text-15-12/15-12-zz.txt", "@@1 later\n@@2 other\n")
    put(source / "text-15-12/bad.txt", "@@3 ignored\n")
    put(source / "text-15-13/15-13-us.txt", "@@4 ignored\n")
    put(source / "16-01-text/16-01-us.txt", "@@5 outside\n")
    metadata = metadata_file(tmp_path / "matched_sources.tsv", [("1", "2015-11-30", "us"), ("2", "2015-12-01", "zz")])
    organiser.organise(source, output, manifests, date(2015, 11, 30), date(2015, 12, 1), metadata)

    assert not (output / "2015_11/us/1.txt").exists()
    assert (output / "2015_12/zz/2.txt").read_text(encoding="utf-8") == "other\n"
    duplicate = rows(output / "duplicate_article_ids.tsv")[0]
    assert duplicate["occurrence_count"] == "3"
    assert duplicate["first_article_file"] == "15-11-text/15_11-US1.txt"
    assert rows(output / "malformed_selected_article_lines.tsv")[0]["line_preview"] == "not an article"
    assert rows(output / "malformed_article_filenames.tsv")[0]["article_file"] == "text-15-12/bad.txt"
    json_text = (manifests / "climate_now.ndjson").read_text(encoding="utf-8")
    assert "résultats" in json_text and "\\u00e9" not in json_text
    records = [json.loads(line) for line in json_text.splitlines()]
    assert [record["article_id"] for record in records] == ["2"]
    assert list(records[0]) == organiser.MANIFEST_COLUMNS
    assert all((tmp_path / record["filepath"]).is_file() for record in records)
    for frame in (pd.read_csv(manifests / "climate_now.tsv", sep="\t", dtype=str),
                  pd.read_excel(manifests / "climate_now.xlsx", dtype=str)):
        assert frame.to_dict("records") == records


def test_rerun_excludes_stale_articles_and_empty_manifest(tmp_path):
    source, output = tmp_path / "input", tmp_path / "output"
    article = source / "15-11-text/15-11-us.txt"
    put(article, "@@1 old\n@@2 retained\n")
    metadata = metadata_file(tmp_path / "matched_sources.tsv", [("1", "2015-11-01", "us"), ("2", "2015-11-30", "us")])
    organiser.organise(source, output, output, date(2015, 11, 1), date(2015, 11, 30), metadata)
    put(article, "@@2 new\n")
    organiser.organise(source, output, output, date(2015, 11, 1), date(2015, 11, 30), metadata)
    assert (output / "2015_11/us/1.txt").exists()
    assert [row["article_id"] for row in rows(output / "climate_now.tsv")] == ["2"]
    organiser.organise(source, output, output, date(2016, 1, 1), date(2016, 1, 1), metadata)
    assert rows(output / "climate_now.tsv") == []
    assert list(pd.read_excel(output / "climate_now.xlsx").columns) == organiser.MANIFEST_COLUMNS


def test_excel_removes_illegal_controls_without_changing_other_manifests(tmp_path):
    source, output = tmp_path / "input", tmp_path / "output"
    put(source / "19-07-text/19-07-us.txt", "@@1 climate change\n")
    metadata = metadata_file(tmp_path / "matched_sources.tsv", [("1", "2019-07-06", "us")])
    content = metadata.read_text(encoding="utf-8").replace("\ttitle\tselected.txt", '\t"title\x01 café\tkept"\tselected.txt')
    metadata.write_text(content, encoding="utf-8")
    organiser.organise(source, output, output, date(2019, 7, 1), date(2019, 7, 31), metadata)
    assert rows(output / "climate_now.tsv")[0]["title"] == "title\x01 café\tkept"
    assert json.loads((output / "climate_now.ndjson").read_text(encoding="utf-8"))["title"] == "title\x01 café\tkept"
    assert pd.read_excel(output / "climate_now.xlsx").iloc[0]["title"] == "title café\tkept"


def test_validation_and_unreadable_input(tmp_path, capsys):
    source = tmp_path / "input"
    article = source / "15-11-text/15-11-us.txt"
    put(article, "@@1 text\n")
    output = tmp_path / "out"
    metadata = metadata_file(tmp_path / "matched_sources.tsv", [("1", "2015-11-01", "us")])
    args = ["--input-articles", str(source), "--output-articles", str(output), "--matched-sources", str(metadata)]
    assert organiser.main(args + ["--initial-date", "bad"]) == 1
    assert organiser.main(args + ["--initial-date", "2023-01-01"]) == 1
    assert organiser.main(["--input-articles", str(source), "--output-articles", str(source / "nested"), "--matched-sources", str(metadata)]) == 1
    assert organiser.main(["--input-articles", str(source), "--output-articles", str(tmp_path), "--matched-sources", str(metadata)]) == 1
    assert organiser.main(args + ["--manifest-dir", str(source / "nested")]) == 1
    assert not (source / "nested").exists()
    original_open = Path.open

    def failing_open(path, *args, **kwargs):
        if path == article:
            raise PermissionError("denied")
        return original_open(path, *args, **kwargs)

    with patch.object(Path, "open", failing_open):
        assert organiser.main(args) == 1
    assert "denied" in capsys.readouterr().err
    assert not (output / "climate_now.tsv").exists()


@pytest.mark.parametrize("name, expected", [("15-11-text", (2015, 11)), ("text-22-11", (2022, 11)), ("text_15-11-xje", (2015, 11)), ("text-22-00", None), ("22-13-text", None), ("2022-11-text", None)])
def test_parse_month(name, expected):
    assert organiser.parse_month(name) == expected


@pytest.mark.parametrize("name,country", [("text_16-11-AU.txt", "au"), ("18-10-in-1.txt", "in"), ("16_11-us2.txt", "us")])
def test_previously_rejected_filenames(tmp_path, name, country):
    source, output = tmp_path / "input", tmp_path / "output"
    put(source / "16-11-text" / name, "@@123 climate change\n")
    metadata = metadata_file(tmp_path / "matched_sources.tsv", [("123", "2016-11-01", country)])
    organiser.organise(source, output, output, date(2016, 11, 1), date(2016, 11, 30), metadata)
    assert (output / "2016_11" / country / "123.txt").is_file()
    assert not rows(output / "malformed_article_filenames.tsv")