---
sessionId: session-261118-132832-1hnq
---

# Requirements

### Scope
Update `docs/research_design.md` to use 200 GETTR posts as the provisional social-media target. Twitter collection remains pending discussion with Professor Berber Sardinha because most archives are unavailable for download. Do not design or implement an AWS collection workflow.

# Technical Design

### Changes
- Update the corpus diagram and source summary to describe GETTR alone and remove the unsupported claim of coverage across mainstream and alternative platforms.
- Replace the GETTR and Twitter rows in the model-allocation matrix with one GETTR row: 200 human posts and 50 generated texts per model. Existing corpus totals and 1:1 parity remain unchanged.
- State that the allocation is provisional and Twitter may be reconsidered with the advisor; avoid implying GETTR covers the entire 2015–2022 period.

# Testing

### Validation
Check all Twitter and GETTR references for consistency, verify the allocation matrix and corpus totals arithmetically, and confirm the pending status is explicit.

# Delivery Steps

### ✓ Step 1: Revise social-media scope and source summary
The research design identifies GETTR as the sole provisional social-media source.

- Update the corpus diagram and source table in `docs/research_design.md` to target 200 GETTR posts.
- Record that Twitter is pending advisor discussion due to archive availability.
- Remove unsupported cross-platform coverage claims.

### ✓ Step 2: Align model allocation and validate totals
The allocation matrix reflects the 200-post GETTR target without changing corpus totals.

- Replace the two platform rows with a single GETTR row allocating 50 texts to each model.
- Verify row and column sums, human–LLM parity, and consistency of all affected references.