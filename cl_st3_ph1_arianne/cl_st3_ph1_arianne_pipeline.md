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

#### Select NOW matching lines

Filter the raw NOW text files for the case-insensitive whole-word phrase `climate change`, preserving their directory structure. This first stage selects lines, not complete articles, and does not apply the research date window. Requires only the Python standard library. Matching output files are overwritten; use a clean output directory to avoid retaining stale results.

```shell
python corpus/00_sources/now/select_now_files.py \
    --input corpus/00_sources/now/01_now_dataset_raw/02_now_text_raw \
    --output corpus/00_sources/now/01_now_dataset/02_now_text
```

**Output:** `corpus/00_sources/now/01_now_dataset/02_now_text/`; processing is also logged to `corpus/00_sources/now/select_now_files.log`.

#### Match NOW source metadata

Match selected article IDs to source metadata within the inclusive research window. Requires only the Python standard library. The output files are overwritten; unmatched IDs include articles outside the date range as well as missing or invalid metadata.

```shell
python corpus/00_sources/now/find_now_sources_text_matches.py \
    --initial-date 2015-11-01 \
    --final-date 2022-11-30 \
    --input-sources corpus/00_sources/now/01_now_dataset_raw/01_now_sources_raw \
    --input-articles corpus/00_sources/now/01_now_dataset/02_now_text \
    --match corpus/00_sources/now/01_now_dataset/01_now_matched_sources
```

**Output:** `corpus/00_sources/now/01_now_dataset/01_now_matched_sources/`, including `matched_sources.tsv`, diagnostics and the processing log. Review duplicate, malformed and unreadable inputs before using the results.

#### Organise NOW articles and create manifest

Reconcile selected lines with `matched_sources.tsv` by article ID, metadata publication date, directory month and filename country. The inclusive research window is applied to metadata dates; grouping uses the matched year and month. Conflicting metadata, missing or invalid metadata countries and differing eligible text occurrences are excluded for review. A filename such as `xx` does not supply a missing metadata country. Requires `pandas` and `openpyxl`. Matching does not prove article identity, and selected lines are not necessarily complete articles. The XLSX export removes Excel-forbidden control characters; NDJSON and TSV preserve the original metadata.

Use fresh output and manifest directories to preserve the previous run. Existing outputs are overwritten on rerun; stale article files are not removed, but are excluded from a successful run's manifest. A failed run can leave partial outputs; do not use its manifest. Manifest paths are relative to the working directory.

```shell
python corpus/00_sources/now/organise_now_articles.py \
    --input-articles corpus/00_sources/now/01_now_dataset/02_now_text \
    --matched-sources corpus/00_sources/now/01_now_dataset/01_now_matched_sources/matched_sources.tsv \
    --output-articles corpus/00_sources/now/02_now_organised_reconciled \
    --manifest-dir corpus/00_sources/now/02_now_organised_reconciled
```

**Output:** `corpus/00_sources/now/02_now_organised_reconciled/`, containing `climate_now.ndjson`, `climate_now.tsv`, `climate_now.xlsx`, article files and diagnostics. Review `unmatched_occurrences.tsv`, `duplicate_article_ids.tsv` and `duplicate_metadata_rows.tsv`, as well as the matcher diagnostics, before sampling.

The previous, unreconciled run contained 367,242 IDs. Its counts do not describe the new manifest; the matcher also reported malformed metadata, so excluded records are not necessarily invalid.

#### Screen NOW texts with an LLM

Screen the reconciled manifest using the climate relevance prompt and `gpt-6-luna`. The input consists of selected matching lines, not necessarily complete articles; classifications are provisional and require human review. Review reconciliation diagnostics before screening and evaluate a pilot before committing to a full run. Live calls require the `openai` Python SDK, `OPENAI_API_KEY`, model access and network connectivity; costs and rate limits apply. The programme does not send `temperature`.

Run a dry run in a separate directory (it writes run-level outputs but makes no API calls):

```shell
python corpus/00_sources/now/llm_screening.py \
    --manifest corpus/00_sources/now/02_now_organised_reconciled/climate_now.ndjson \
    --output corpus/00_sources/now/03_now_screened/dry_run \
    --prompt corpus/00_sources/now/llm_screening_prompts/llm_screening_v2.md \
    --model gpt-6-luna --limit 10 --dry-run
```

Pilot with 10 texts, then test concurrency with 200. `--resume` skips compatible successful results; without it existing per-article results may be overwritten. Use a new output directory when changing the model, prompt or inputs; review failures and invalid responses before continuing.

```shell
python corpus/00_sources/now/llm_screening.py \
    --manifest corpus/00_sources/now/02_now_organised_reconciled/climate_now.ndjson \
    --output corpus/00_sources/now/03_now_screened/llm_screening_v2_gpt-6-luna \
    --prompt corpus/00_sources/now/llm_screening_prompts/llm_screening_v2.md \
    --model gpt-6-luna --limit 10
```

```shell
python corpus/00_sources/now/llm_screening.py \
    --manifest corpus/00_sources/now/02_now_organised_reconciled/climate_now.ndjson \
    --output corpus/00_sources/now/03_now_screened/llm_screening_v2_gpt-6-luna \
    --prompt corpus/00_sources/now/llm_screening_prompts/llm_screening_v2.md \
    --model gpt-6-luna --limit 200 --workers 20 --resume --max-output-tokens 2000
```

Full run after pilot review:

```shell
python corpus/00_sources/now/llm_screening.py \
    --manifest corpus/00_sources/now/02_now_organised_reconciled/climate_now.ndjson \
    --output corpus/00_sources/now/03_now_screened/llm_screening_v2_gpt-6-luna \
    --prompt corpus/00_sources/now/llm_screening_prompts/llm_screening_v2.md \
    --model gpt-6-luna --workers 20 --resume --max-output-tokens 2000 --max-retries 5
```

For EC2, the existing wrapper activates its configured Conda environment and **requests instance shutdown on exit, including failure**. Review its hard-coded environment and SNS settings, IAM permissions and storage persistence before use; ensure the manifest and article paths are available on the instance from the phase directory.

```shell
bash corpus/00_sources/now/run_python_ec2.sh \
    corpus/00_sources/now/llm_screening.py \
    --manifest corpus/00_sources/now/02_now_organised_reconciled/climate_now.ndjson \
    --output corpus/00_sources/now/03_now_screened/llm_screening_v2_gpt-6-luna \
    --prompt corpus/00_sources/now/llm_screening_prompts/llm_screening_v2.md \
    --model gpt-6-luna --workers 20 --resume --max-output-tokens 2000 --max-retries 5
```

**Output:** The chosen output directory contains `climate_now_screened.ndjson`, per-article JSON, failure and invalid-response reports, run manifests, summary and log. Check these outputs and manually validate classifications; screening does not establish article completeness or eligibility.

The completed run in `corpus/00_sources/now/03_now_screened/llm_screening_v2_gpt-6-luna/` contains 155,597 unique classifications: 52,308 `CORE`, 72,199 `PERIPHERAL` and 31,090 `EXCLUDE`. A resumed run with `--max-output-tokens 2000` successfully classified the 11 previously invalid responses and reused 155,586 existing results; the current failure and invalid-response reports are empty. All input IDs are represented, but classification accuracy and eligibility still require human review.

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

