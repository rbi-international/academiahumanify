# Build Plan

Sixteen milestones. **One per session.** Each has a definition of done that must
be met before the checkbox is ticked. Nothing above M5 needs a GPU or a network
call, which means the hard part is provable before a single token is generated.

Legend: `[x]` done, `[ ]` pending.

---

## Phase 1: Deterministic core (no model needed)

### [x] M1. Protection core
`app/core/protection.py`

Mask every span that must not change, verify it survived, restore it.

Done when:
- masks citations (numeric and author-year), numbers, p-values, equations,
  LaTeX environments, table and figure refs, DOIs, URLs, model names, units
- round trip is byte-identical
- verification catches dropped, invented, and duplicated placeholders
- placeholders contain no digits (else masking consumes its own output)
- **13 tests passing**

### [x] M2. Segmenter
`app/pipeline/segment.py`

Split into paragraphs, tag each with its section, freeze what must not move.

Done when:
- classifies headings across numbered, roman, markdown, all-caps, title-case
- section carries forward to following paragraphs
- freezes headings, equations, tables, captions, references
- disables section awareness and reports it when a document has no headings
- **9 tests passing**

### [x] M3. Stylometry extractor
`app/pipeline/stylometry.py`

Turn a writing sample into explicit numeric targets the prompt can aim at.

Extract:
- sentence length mean, variance, min, max
- connective inventory and repetition counts
- hedging density (may, suggest, appear, tend)
- active to passive ratio
- nominalisation rate (utilisation vs use)
- clause depth, paragraph length distribution
- tell counters: tricolons, "moreover" family, em dashes, uniform openings

Done when:
- `VoiceProfile.features` populated from a sample of 80 words or more
- degrades gracefully on short samples, reports low confidence
- same extractor runs on the draft, producing the **Style Report**
- 10 or more tests, including a short-sample and an empty-sample case

### [x] M4. Claim extractor
`app/pipeline/claims.py`

Pull the assertions out of a paragraph so drift can be measured later.

Done when:
- extracts claim tuples (subject, relation, object, hedge strength)
- hedge strength on a 5 point scale from "may suggest" to "demonstrates"
- deterministic, regex and rule based, no model
- 8 or more tests

---

## Phase 2: Model layer

### [ ] M5. LLM provider interface
`app/llm/base.py`, `app/llm/stub.py`, `app/llm/ollama.py`, `app/llm/openai_compat.py`

Done when:
- `LLMProvider` protocol: `complete(prompt, system, **opts) -> str`
- `StubProvider` returns deterministic canned output so the whole pipeline is
  testable with zero network
- Ollama provider works against a local small Qwen3
- OpenAI-compatible provider covers Together, Fireworks, DeepInfra, Groq
- retries with backoff, timeout, token accounting
- **provider selected by config, never imported directly above `app/llm/`**
- 8 or more tests, all against the stub

### [ ] M6. Prompt library
`prompts/system/`, `prompts/fewshot/`

Done when:
- versioned prompt files, one per stage, loaded by id and version
- rewrite prompt states: preserve every `⟦P...⟧` token exactly, never invent one
- intensity variants: conservative, balanced, enhanced
- style variants: formal conservative, modern interdisciplinary
- few-shot before/after pairs for CS, biology, physics, social science
- a prompt registry with checksums so a changed prompt is visible in the log

### [ ] M7. Rewrite stage
`app/pipeline/rewrite.py`

Done when:
- masked segment plus voice profile plus intensity in, rewritten masked text out
- retries on integrity failure with a corrective instruction, max 3, then fails
- frozen segments bypass the model entirely
- concurrency with a semaphore, ordered reassembly
- tested end to end against StubProvider

### [ ] M8. Verify stage
`app/pipeline/verify.py`

Done when:
- hard gate: placeholder integrity via M1
- soft gate: claim drift via M4, flags strengthened or weakened claims
- soft gate: sentence count deviation beyond section tolerance
- returns a structured report, never raises on soft failures
- 10 or more tests including a deliberately drifting rewrite

### [ ] M9. Changelog stage
`app/pipeline/changelog.py`

Done when:
- sentence-level alignment between original and rewritten
- each change carries a reason: merged, split, reordered, deverbalised,
  connective replaced, redundancy removed
- output feeds both the diff view and the export

### [ ] M10. Orchestrator
`app/services/orchestrator.py`

Done when:
- wires M1 to M9 into one run
- assembles the audit trail from every `StageReport`
- partial failure isolation: one bad segment does not kill the run
- integration test on a full sample paper using StubProvider

---

## Phase 3: Surface

### [ ] M11. FastAPI backend
`app/api/v1/`

Endpoints: `POST /humanize`, `GET /runs/{id}`, `GET /runs/{id}/changelog`,
`POST /style-report`, `GET /health`.

Done when:
- async job model, long papers do not block
- Pydantic schemas at the boundary only
- structured logging with run id
- rate limiting
- OpenAPI docs generated

### [ ] M12. Persistence
`app/db/`

Done when:
- SQLAlchemy models: user, document, run, segment_version, report
- Alembic migrations
- version history and comparison between runs

### [ ] M13. Frontend
`frontend/`

Done when:
- upload or paste, section-aware view, intensity control, voice sample input
- side-by-side diff with per-change reasons
- Style Report panel
- LaTeX preview via Monaco
- the ethics notice is visible before the first run, not buried

### [ ] M14. Export
Markdown, LaTeX, docx, PDF. Round trip must preserve citations and equations.

---

## Phase 4: Ship to testers

### [ ] M15. Docker
`docker/`

Done when:
- multi-stage backend image, non-root user
- frontend build served by nginx or caddy
- `docker compose up` gives a working stack: api, worker, postgres, frontend
- `.env.example` documents every variable
- healthchecks on every service

### [ ] M16. Deploy for user testing
See `docs/SETUP.md` section 6.

Done when:
- testers reach a URL and use it without installing anything
- feedback capture: a thumbs up or down plus a comment per run, stored with the
  run id so a complaint can be traced to its exact input and output
- basic auth or invite codes so it is not open to the world
- error tracking

---

## Deferred on purpose

Revisit only after M16 and real user feedback.

- Fine-tuning or distillation (needs accepted-output data we do not have yet)
- LoRA adapters per discipline
- Plagiarism checking (needs a corpus and a licence)
- Multi-user collaboration
- Reference manager integrations
