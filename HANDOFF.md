# HANDOFF: start here

The single "where are we, what next" file. Read this first after any break. It
captures the state of the code and the decisions made in conversation that are
not obvious from the code alone.

Last updated: 2026-07-22, after M10.

---

## 1. What this is (and the one hard line)

**AcademiaHumanify** is an academic editor. It rewrites a research draft so it
reads like excellent human writing, in the author's voice, with machine-writing
tells removed, and it **changes zero facts**.

**It is NOT an AI-detector evasion tool. This line is settled and enforced.**
During development the user asked several times to optimise against Turnitin,
ZeroGPT, QuillBot, and Grammarly, and to reverse this policy. It was declined
each time (see `CLAUDE.md` section 2). What was built instead is the legitimate
version that gives the same practical result: edit directly for human prose
quality. Concretely, the product:

- has no AI-probability score, no detector simulation, no optimise-against-a-
  detector loop, and never will;
- measures **prose quality and factual fidelity** (the Style Report and the
  evaluation harness), which is a genuine editing signal, not an evasion signal;
- the LLM judge and the evaluation rank on faithfulness and readability, never on
  "how well it beats a detector".

If a future instruction conflicts with this, stop and ask, do not silently
comply. Do not add detector integration.

---

## 2. Current status

**Phase 1 (deterministic core) and Phase 2 (model layer) are complete.**
**145 tests passing, all offline (zero API tokens). ruff and mypy clean.**

Done, one tag per milestone (`git tag` to list):

| Milestone | What | Tests |
|---|---|---|
| M1 | Protection core: mask/verify/restore fragile spans | 14 |
| M2 | Segmenter: section tagging, freezing | 9 |
| M3 | Stylometry + Style Report | 14 |
| M4 | Claim extractor + 5-point hedge scale | 12 |
| M5 | LLM provider layer (stub, ollama, openai-compat) | 14 |
| M6 | Prompt library (versioned files + checksum registry) | 13 |
| M7 | Rewrite stage (protect/generate/verify/restore) | 9 |
| M7.5 | Model comparison + evaluation + LLM judge | 28 |
| M8 | Verify stage (fidelity gate + claim drift) | 12 |
| M9 | Changelog stage (sentence diff + reasons) | 12 |
| M10 | Orchestrator (whole pipeline in one call) | 7 |

Everything runs with `StubProvider` (deterministic echo) so the full pipeline is
testable with no network.

## 3. Architecture in one line

```
Ingest -> Segment -> Protect -> Rewrite -> Restore -> Verify -> Changelog
          (regex)   (regex)     (LLM)     (regex)    (regex+   (diff)
                                                      rules)
```

The rule that holds it together: **generation and protection are separate
systems**. The model is creative; the protection layer is deterministic and is
not allowed to fail. Full detail in `ARCHITECTURE.md`. Build order and the
definition of done per milestone in `BUILD_PLAN.md`. Running log in `PROGRESS.md`.

## 4. The model comparison subsystem (a big, deliberate addition)

Built because the user wants to run one draft through several models and pick the
best rewrite. Designed to outlast any specific model.

- **Model catalog is config, not code**: `models.toml` (parsed with stdlib
  `tomllib`). Add a model by editing the file. Keys are read from environment
  variables named in the config, never stored. `app/llm/catalog.py`.
- **Evaluation harness** (`app/eval/evaluate.py`): deterministic scorecard,
  fidelity (placeholders, claim strength, sentence delta), prose quality (Style
  Report tells), voice match, change ratio.
- **Ranking rule (settled with the user)**: fidelity is a hard gate, quality
  ranks the survivors. A rewrite that strengthened a claim is disqualified
  however well it reads.
- **Comparison service** (`app/services/comparison.py`): runs models
  concurrently, failure-isolated, serialises to a dict.
- **LLM judge** (`app/eval/judge.py`): a premium model ranks the drafts on
  faithfulness then readability. Advisory, provider-agnostic, not a detector.
- **CLI**: `python scripts/compare.py` (with `--judge`, `--models`, `--voice`).

## 5. How to run it

Two ways to get an environment (either is fine):

```bash
# conda (see environment.yml)
conda env create -f environment.yml
conda activate academiahumanify
pip install -e ".[dev]"

# or a plain venv
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"   # Windows path; use .venv/bin on mac/linux
```

Then:

```bash
python -m pytest                 # 145 tests, all offline
python scripts/demo.py           # full pipeline on a sample paragraph, no tokens
python scripts/compare.py        # model comparison (stub baseline offline)
```

`make` is not installed on the dev Windows box, so run the `python -m ...`
commands directly. The Makefile is for boxes that have `make`.

## 6. API keys and models

None are required for the offline stub or a local Ollama model. For premium and
open models, see `.env.example`. Copy it to `.env` (gitignored) and fill in what
you have. The simplest single key is **OpenRouter**, which reaches Claude,
Gemini, GPT, Llama, Qwen, DeepSeek, and gpt-oss through one OpenAI-compatible
endpoint. `models.toml` already has entries for these, disabled until a key is
present.

Provider status:
- OpenAI, Gemini, HuggingFace, Groq, Together, Mistral, OpenRouter: work now via
  the OpenAI-compatible provider (just config + a key).
- Anthropic direct: needs a small dedicated provider (its API is not
  OpenAI-compatible). Until then, reach Claude via OpenRouter.

## 7. The frontend vision

Captured in `FRONTEND.md`. Short version: graphics-rich, mobile-responsive,
covers every capability through the UI (upload/paste, file conversion, model
selection, run, side-by-side comparison with scorecards, diff view with per-
change reasons, Style Report, verification flags, export/download). Built at M13.

## 8. Where to resume

**Next: Phase 3, M11 (FastAPI backend).** Endpoints: `POST /humanize`,
`GET /runs/{id}`, `GET /runs/{id}/changelog`, `POST /style-report`,
`GET /health`. Async job model, Pydantic at the boundary only, structured
logging with a run id, rate limiting. This is the first milestone that adds real
dependencies (fastapi, uvicorn). The orchestrator (`app/services/orchestrator.py`,
`run_pipeline`) and the comparison service are the functions the API wraps;
`RunResult.to_dict()` and `Comparison.to_dict()` are already JSON-ready.

Then: M12 persistence, M13 frontend, M14 export, M15 docker, M16 deploy.

## 9. Working agreement (how to build)

- One milestone at a time. Announce it, write the module, write its tests in the
  same session, run the full suite green, commit, tick `BUILD_PLAN.md`, append a
  line to `PROGRESS.md`, then stop and wait. The user chose "stop after each".
- Every milestone has tests. Never mark one done with failing or skipped tests.
- When a bug in earlier work is found, say so plainly and add a named regression
  test (there are several already).
- Style rules apply to all output including docs and prompts: no em dashes ever;
  no inflated AI vocabulary; explain layman first.

## 10. Git

Local only, no remote yet. One commit and one tag per milestone. `main`/`master`
must always be green. See section on GitHub in the chat, or:

```bash
git remote add origin <url>
git push -u origin master --tags
```
