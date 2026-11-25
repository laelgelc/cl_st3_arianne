# Corpus Linguistics - Study 3 - Arianne

## Phase 1 - Data Collection and Preprocessing

The [Phase 1 pipeline](cl_st3_ph1_arianne/cl_st3_ph1_arianne_pipeline.md) documents collection and pending work, with commands run from `cl_st3_ph1_arianne/`. See the [research design](docs/research_design.md) for the methodology.

Greenpeace and WWF datasets have been collected. WRI listings and manually saved articles have been processed into a provisional paragraph-level dataset requiring review. The GETTR manifest contains 541 posts selected by UTC date, English-language detection, nonempty text and the case-insensitive seed `climate change`, with a `word_count` field; exact and flagged potential duplicates have been removed. Automated language and duplicate detection are approximate.

The provisional social-media target is 200 GETTR posts. Twitter collection remains pending discussion with Professor Berber Sardinha because most Stream Grab archives are unavailable for download.

For press reports, the NOW pipeline selects lines containing `climate change`, matches source metadata within 1 November 2015–30 November 2022, and reconciles article IDs, months and countries before exporting manifests and review diagnostics. Review the diagnostics before sampling; selected lines are not necessarily complete articles.

Climate-relevance screening with `gpt-6-luna` completed for all 155,597 reconciled NOW records. A resumed run with a 2,000-token output limit resolved the 11 previously invalid responses. Classifications remain provisional and require human review. The pipeline records results, commands, dependencies, output locations and overwrite warnings. Other source collection, segmentation, LLM generation, preprocessing and validation remain pending.



## Phase 2 - Climate Change Target Corpus organisation and Lexical Multi-dimensional Analysis

The [Phase 2 pipeline](cl_st3_ph2_arianne/cl_st3_ph2_arianne_pipeline.md) documents candidate preparation, review and compilation. Source-specific adapters prepare candidates in Phase 1; a shared compiler selects approved candidates using a recorded random seed and adds each stratum to the target corpus.

GETTR candidates have a review spreadsheet for checking language, duplicates, completeness and provenance. The NOW adapter prepared all 52,308 CORE-classified articles for review; the spreadsheet contains previews, so reviewers must open the linked full texts and check relevance, English, dates, duplicates and completeness. Source files must remain at their recorded paths for validation. Screening is not approval; only manually approved candidates can be sampled. The targets for `social-post` and `press-news` are 200 each, with GETTR provisional.

### Target corpus organisation

Stratum codes combine actor and register: `gov-treaty`, `gov-report`, `press-news`, `ngo-story`, `acad-abstract`, `social-post` and `sceptic-blog`. Sources and generation conditions are recorded separately rather than encoded in the stratum. The compiler currently writes one UTF-8 file per selected human unit under `cl_st3_ph2_arianne/corpus/human/<stratum>/`, alongside `manifest.ndjson` and `sampling.json`. The manifest links stable unit and text IDs to provenance, grouping and length metadata; sampling metadata records the seed and candidate-manifest hash. Adding a new stratum merges the manifest and preserves existing texts; back up the corpus before updating it.

The planned layout places generated texts under `llm/generic/<stratum>/` and `llm/summary-guided/<stratum>/`, and summaries under `summaries/<stratum>/`. Each generated text has its own `text_id` and shares a `unit_id` with its human unit. These outputs, their model allocation and adapters for the remaining sources are still to be implemented. The design targets 1,191 human units and two generated texts per unit; generic texts are paired by assignment, not necessarily by shared content.

```text
cl_st3_ph2_arianne/corpus/
├── manifest.ndjson
├── sampling.json
├── human/
│   └── <stratum>/
├── llm/                         # planned
│   ├── generic/<stratum>/
│   └── summary-guided/<stratum>/
└── summaries/<stratum>/         # planned
```

For lexical multidimensional analysis, feature measurements will be joined to metadata by `text_id`: binary presence/absence values for analysis, with raw counts and text lengths retained for sensitivity checks. A missing measurement must remain distinct from an absent feature. Token counting, feature extraction and SAS export remain pending.


