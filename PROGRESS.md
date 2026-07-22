# Progress Log

One line per milestone. Append, never rewrite. Record what was built and
anything surprising, especially bugs found in earlier work.

| Date | Milestone | Notes |
|---|---|---|
| 2026-07-22 | M1 Protection core | Masking self-consumed when placeholders contained digits. Fixed by letter-only encoding. Model names fragmented (GPT-2 split at the digit); added named_model, quantity_unit, alnum_token patterns ahead of the bare-number rule. 13 tests. |
| 2026-07-22 | M2 Segmenter | Heading classifier stripped leading chars with a class including IVXLC, so "1. Introduction" became "ntroduction" and Introduction and Conclusion were silently mislabeled. Also read numbered list items as headings. Both fixed with named regression tests. 9 tests. |
| 2026-07-22 | Bootstrap | The M1/M2 code was absent from disk (only docs and no git repo existed) despite being recorded as done. Rebuilt the repo scaffolding (git, pyproject, Makefile, `app/pipeline/base.py` contracts) and both prior milestones with their tests to restore the documented 22-test baseline before starting M3. |
| 2026-07-22 | M3 Stylometry | Built the extractor: sentence-length stats, connective inventory, hedging density, passive and nominalisation rates, approximate clause depth, paragraph distribution, and the tell counters (tricolons, moreover family, em dashes, uniform openings). Same `extract()` runs on the draft to produce the Style Report. Surprise: the abbreviation-merge in sentence splitting treats a single capital letter followed by a period as an initial, so very short "A. B. C." test sentences merge into one; real-word sentences are needed in tests. Confidence tiers: NONE (empty), LOW (<80 words), OK. 14 tests. 36 total passing. |
| 2026-07-22 | Environment | Created the `.venv` (python -m venv, pip install -e ".[dev]") and confirmed the suite runs inside it. On Windows the interpreter is `.venv/Scripts/python.exe`, not the Makefile's Unix `.venv/bin/`; `make` itself is not installed on this box, so tests run via `python -m pytest` directly. |
| 2026-07-22 | M4 Claims | Claim extractor: (subject, relation, object) plus a five-point hedge scale (SPECULATIVE..DEFINITIVE) as an IntEnum so drift is arithmetic. Picks the earliest relational cue, longest at a tie so "is associated with" beats the bare copula. Softeners (may, possibly) and boosters (clearly) adjust by one step, but only when they sit before the cue, so a "may" in the object cannot soften "demonstrates". Non-claim sentences return None rather than a hollow tuple. 12 tests. 48 total passing. |
