### WRI listing manifest

Run `python cl_st3_ph1_arianne/corpus/00_sources/ngo/parse_wri_listings.py` from the project root (requires `beautifulsoup4`). It reads local `wri_listings/wri-pNN.html` files and overwrites `wri_list.jsonl`; use `--listings` and `--output` to specify different paths. No network requests are made.

The manifest contains every listing result, not a sample or a date-filtered corpus. `Listing Pages` records the originating page numbers, and repeated identical URLs are merged; conflicting metadata causes an error. `Post ID` is a stable SHA-256 hash of the URL prefixed with `wri`.

Fields follow `grp_list.jsonl` where possible. Unlike that file's millisecond timestamps, `Post Date` is the listing's date as `YYYY-MM-DD`: the listing does not provide a publication time or timezone. `Authors` is null because the listing does not provide authors. Tags are taken from the result's text section, not duplicated image tags. The displayed date should be checked against the article's original publication date before applying the 1 November 2015–30 November 2022 window. Article text and region require separately saved article pages.

Run `python cl_st3_ph1_arianne/corpus/00_sources/ngo/select_wri_articles.py` to generate the provisional collection log using seed `20261118`. This overwrites `wri_article_collection_log.md`, including any manual notes; use `--output` to write elsewhere and `--seed` to change the seed. Candidates are sorted by URL and sampled without replacement within listing-page strata; entries on multiple pages are assigned to their lowest numbered page. The program fails if a stratum lacks enough listing-date-eligible records. This is not a uniform sample across all articles. Verify original dates and English language on saved articles and document exclusions and replacements in the log.

Run the checks with `python -m unittest discover -s cl_st3_ph1_arianne/corpus/00_sources/ngo -p 'test_*wri*.py'`.