# Corpus Linguistics - Study 3 - Arianne

## Phase 1 - Data Collection and Preprocessing

The [Phase 1 pipeline](cl_st3_ph1_arianne/cl_st3_ph1_arianne_pipeline.md) documents collection and pending work, with commands run from `cl_st3_ph1_arianne/`. See the [research design](docs/research_design.md) for the methodology.

Greenpeace and WWF datasets have been collected. WRI listings and manually saved articles have been processed into a provisional paragraph-level dataset requiring review. The GETTR manifest contains 541 posts selected by UTC date, English-language detection, nonempty text and the case-insensitive seed `climate change`, with a `word_count` field; exact and flagged potential duplicates have been removed. Automated language and duplicate detection are approximate.

The provisional social-media target is 200 GETTR posts. Twitter collection remains pending discussion with Professor Berber Sardinha because most Stream Grab archives are unavailable for download.

For press reports, the NOW pipeline selects lines containing `climate change`, matches source metadata within 1 November 2015–30 November 2022, and reconciles article IDs, months and countries before exporting manifests and review diagnostics. Review the diagnostics before sampling; selected lines are not necessarily complete articles.

Climate-relevance screening with `gpt-6-luna` completed for all 155,597 reconciled NOW records. A resumed run with a 2,000-token output limit resolved the 11 previously invalid responses. Classifications remain provisional and require human review. The pipeline records results, commands, dependencies, output locations and overwrite warnings. Other source collection, segmentation, LLM generation, preprocessing and validation remain pending.



## Phase 2 - Climate Change Target Corpus organisation and Lexical Multi-dimensional Analysis


