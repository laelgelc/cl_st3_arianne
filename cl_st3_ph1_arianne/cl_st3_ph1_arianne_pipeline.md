# Corpus Linguistics - Study 3 - Phase 1 - Arianne

Run commands from `cl_st3_ph1_arianne/`; paths are relative to that directory. The research window is 1 November 2015–30 November 2022 inclusive. See the [research design](../docs/research_design.md) for methodology.

## 1. Define corpus scope, strata, and sampling targets

## 2. Construct and validate climate discourse search queries

### 2.1. Identify seed terms and validate search precision

The following seed terms are defined for selecting texts from GETTR, NOW, and Twitter:

- Climate Change

Search precision validation is pending.

### 2.2. Expand and prune terms; assemble disjunctive queries

## 3. Collect and document human-authored texts by source and register

### 3.1. Government minutes and treaties

### 3.2. Government synthesis reports

### 3.3. Press news reports

### 3.4. NGO institutional stories

Greenpeace and WWF datasets have been collected in `corpus/00_sources/ngo/grp.jsonl` and `corpus/00_sources/ngo/wwf.jsonl`.

#### WRI listing manifest

Parse saved listing pages 10–46 locally. Requires `beautifulsoup4`; this command overwrites the manifest. See `corpus/00_sources/ngo/wri_manifest.md` for options and validation details.

```shell
python corpus/00_sources/ngo/parse_wri_listings.py
```

**Output:** `corpus/00_sources/ngo/wri_list.jsonl` (740 unique records; unfiltered listing manifest).

#### WRI article collection and extraction

Select 67 candidates with seed `20261118`: one each from pages 10, 15, 20, 25, 30, 35 and 40, and two from each other page. Listing dates alone do not establish eligibility; verify original dates and English language. This is not a uniform random sample of all eligible articles.

**Warning:** Regenerating the log overwrites manual notes and replacements; use `--output` to write elsewhere.

```shell
python corpus/00_sources/ngo/select_wri_articles.py
```

**Output:** `corpus/00_sources/ngo/wri_article_collection_log.md`. Selected pages were saved manually in `corpus/00_sources/ngo/wri_pages/`.

The page 23 entry `wri-p23-02.html` was manually replaced because the [original, dated 2019-11-18](https://www.wri.org/insights/pour-la-durabilite-de-la-production-du-cacao-les-pays-et-les-societes-doivent-sengager), was French; the [replacement is dated 2019-11-08](https://www.wri.org/insights/us-climate-action-week-hope-amidst-despair).

#### WRI article extraction

Extract paragraphs and list items from saved pages using `beautifulsoup4`. The output is created exclusively; use `--output` for another path if it already exists.

```shell
python corpus/00_sources/ngo/parse_wri_articles.py
```

**Output:** `corpus/00_sources/ngo/wri.jsonl` (1,144 records from 67 articles; provisional).

Displayed original dates are used, including for `wri-p18-01.html` and `wri-p43-01.html` where metadata dates differ. Approved external canonical URLs for `wri-p20-01.html`, `wri-p21-01.html`, `wri-p28-01.html` and `wri-p31-01.html` are included alongside their WRI URLs; `wri-p28-01.html` is only an excerpt linking to CNN. Dates are date-only, missing regions are null, and tables, captions and callouts are excluded. Review language, dates, text boundaries and later updates; document exclusions or replacements before finalizing. No additional WWF keyword filter is applied.

### 3.5. Academic research abstracts

### 3.6. Social media posts: GETTR and Twitter

#### GETTR manifest

Select posts from `corpus/00_sources/gettr/gettr_2021-07.ndjson` within the UTC research window. Keep nonempty, exact-text-unique English posts containing `climate change` case-insensitively; copy `txt` to `text` and add a whitespace-based `word_count`. Requires `langdetect==1.0.9`; language detection is approximate and needs manual review.

```shell
python corpus/00_sources/gettr/create_gettr_manifest.py
```

**Output:** Initially 595 posts; the preserved pre-deduplication manifest is `corpus/00_sources/gettr/gettr_before_near_dedup.ndjson`. Existing output is not overwritten; use `--output` for another path. Twitter collection is pending.

#### GETTR possible repost review

Generate a candidate report from the original manifest (standard Python library only):

```shell
python corpus/00_sources/gettr/report_gettr_duplicates.py --input corpus/00_sources/gettr/gettr_before_near_dedup.ndjson --output corpus/00_sources/gettr/new_candidates.ndjson
```

**Output:** The existing `corpus/00_sources/gettr/gettr_duplicate_candidates.ndjson` contains 80 candidate pairs, all marked `remove duplicate` with notes `potential duplicate`. Row numbers refer to the preserved original manifest.

For comparison only, the report unescapes HTML, normalizes case and whitespace, and removes URLs and `RT`/`repost` markers. It compares all pairs with at least five words per normalized text, using a character similarity threshold of 0.85. This threshold is not validated: distinct posts may be removed and other duplicates missed.

Apply all reported pairs as potential duplicates, keeping the earliest original row in each connected group. This can group indirectly related posts. The command writes new files exclusively and checks candidate IDs and text against the original manifest:

```shell
python corpus/00_sources/gettr/apply_gettr_duplicates.py --output corpus/00_sources/gettr/gettr_deduplicated_new.ndjson --report-output corpus/00_sources/gettr/gettr_decisions_new.ndjson
```

**Output:** The current `corpus/00_sources/gettr/gettr.ndjson` contains 541 posts (54 removed). The command above writes separate files and does not overwrite the current manifest or report.

### 3.7. Sceptical blog posts

## 4. Select and segment human sampling units

### 4.1. Identify cohesive sections and extract segments

### 4.2. Record source provenance and segment boundaries

## 5. Prepare prompts and generate the LLM subcorpus

### 5.1. Create neutral informational summaries

### 5.2. Construct system and scene-reconstruction prompts

### 5.3. Allocate human units across models and generate paired texts

## 6. Clean and preprocess human and LLM texts

## 7. Validate corpus balance, pairing, metadata, and text lengths

## 8. Tag and prepare the corpus for Phase 2 analysis

