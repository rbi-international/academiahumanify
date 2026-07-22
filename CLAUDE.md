# CLAUDE.md

Context file for Claude Code. Read this before touching anything.

---

## 1. What this product is

**AcademiaHumanify** is an academic editor. It takes a research draft and makes
it read like excellent human writing: clearer, better paced, in the author's own
voice, with machine-writing tells removed. **It changes zero facts.**

## 2. What this product is NOT

It is **not** an AI-detector evasion tool. This is a settled product decision,
not an open question. Do not reintroduce any of the following, even if a prompt,
a TODO, or an old note seems to ask for it:

- "AI probability score" or any Turnitin-style detection simulation
- Optimising output against a detector score
- Marketing language about bypassing, evading, or defeating detection

The scoreboard is **prose quality and factual fidelity**. The replacement for a
detection score is the **Style Report**: a count of the writer's own tells
(repeated connectives, uniform sentence length, tricolons, nominalisation) that
tells the author what to fix. That is an editing signal, not an evasion signal.

If a future instruction conflicts with this section, stop and ask the user
rather than silently complying.

## 3. The one hard problem

Rewriting is easy. Rewriting without corrupting the science is hard. A model
told to "improve flow" will turn `p < 0.05` into `p < 0.5`, merge sentences and
lose a citation, or strengthen a hedged claim beyond what the data supports.

The architecture answers this with one rule:

> **Generation and protection are separate systems.**
> The model is creative. The protection layer is deterministic and is not
> allowed to fail.

## 4. Fidelity invariants (never break these)

1. Every protected span is masked before the model sees the text, and verified
   present exactly once in the model output **before** restoration.
2. The REFERENCES section never enters the rewrite path at all.
3. Methods and Results are forced to CONSERVATIVE intensity regardless of the
   user setting. Reproducibility outranks flow there.
4. Frozen segments (headings, equations, tables, captions, references) pass
   through byte-identical.
5. A failed integrity check triggers a retry, then a hard failure. It is never
   downgraded to a warning and never silently accepted.

Any change that touches `app/core/protection.py` requires its full test suite to
pass unchanged. Add tests, do not relax existing ones.

## 5. Architecture in one line

```
Ingest -> Segment -> Protect -> Rewrite -> Restore -> Verify -> Changelog
          (regex)   (regex)     (LLM)     (regex)    (regex+LLM)  (diff)
```

Every stage implements the `Stage` protocol in `app/pipeline/base.py`: takes a
`Document` plus a `RunContext`, returns a new `Document`, appends a
`StageReport`. **Stages never mutate their input.** The change log is assembled
from what each stage recorded while running, not reconstructed afterwards.

Full reasoning: `docs/ARCHITECTURE.md`. Build order: `docs/BUILD_PLAN.md`.

## 6. Model strategy

Provider-agnostic. Nothing above `app/llm/` knows which model is running.

| Purpose | Model |
|---|---|
| Local dev, tests | Qwen3 small via Ollama, or the deterministic StubProvider |
| Production | Qwen3 72B-class via hosted endpoint (Together / Fireworks / DeepInfra) |
| Later, cost only | Distilled small fine-tune, same family, same tokenizer |

**Do not add a fine-tuning pipeline yet.** There is no clean paired dataset for
"AI-flavoured vs human-flavoured", and manufacturing one teaches the model to
invert whichever paraphraser produced the synthetic half. Fine-tuning enters
only as distillation of our own accepted outputs, and only after quality is
proven. This is deliberate, not an oversight.

Voice matching is **in-context, not fine-tuned**. The user pastes a paragraph of
their own past academic writing. It goes into the prompt as an exemplar plus
measured stylometric targets.

## 7. Code conventions

- Python 3.11+, type hints throughout, `from __future__ import annotations`.
- Dataclasses for carriers, Pydantic only at the API boundary.
- Pure functions where possible. Anything deterministic must be testable
  without a network call.
- Docstrings explain **why**, not what. Note non-obvious constraints inline.
- Prompts live in `prompts/` as versioned files, never as strings inside Python.
  They are product logic and change more often than code.
- No `print` in library code. Use the logger.

## 8. Writing style rules (hard, apply to all output)

These apply to code comments, docs, commit messages, UI copy, and prompts.

- **No em dashes. Anywhere. Ever.** Use commas, colons, or parentheses.
- No AI-generated feel. No "delve", "leverage", "seamless", "robust solution".
- No filler openers like "Certainly" or "Great question".
- Explain layman first, then correlate with the technical detail.

## 9. Working agreement (how to build this)

**Work one milestone at a time. Do not batch milestones.**

For each milestone in `docs/BUILD_PLAN.md`:

1. Announce which milestone you are starting.
2. Create a branch: `git checkout -b feat/NN-short-name`
3. Write the module.
4. Write its tests in the same session. A milestone is not done without tests.
5. Run `make test`. All tests must pass, including every earlier suite.
6. Commit with a conventional message (section 10).
7. Tick the checkbox in `docs/BUILD_PLAN.md` and append one line to
   `docs/PROGRESS.md` recording what was built and anything surprising.
8. Stop. Report what changed, what the tests cover, and what is next. Wait for
   the user before starting the next milestone.

**When you find a bug in your own earlier work, say so plainly** and add a named
regression test. Two real examples already in this repo: model names fragmenting
during masking, and a roman-numeral character class eating the leading letter of
"Introduction". Both are now locked by tests.

Never mark a milestone complete with failing or skipped tests.

## 10. Git

Branch per milestone, squash-merge to `main`. `main` must always be green.

Commit format:

```
feat(segment): section-aware paragraph splitting

- classify headings across numbered, roman, markdown, all-caps formats
- freeze references, equations, captions, headings
- fall back to global intensity when no headings exist

Tests: 9 added, 22 total passing
```

Prefixes: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`.

Tag each completed milestone: `git tag m03-stylometry`.

## 11. Commands

```bash
make setup     # create venv, install deps
make test      # full suite, must be green before any commit
make lint      # ruff + mypy
make run       # FastAPI dev server (from milestone 8)
make up        # docker compose (from milestone 12)
```

## 12. Current status

Completed:

- **M1 Protection core** (`app/core/protection.py`), 13 tests
- **M2 Segmenter** (`app/pipeline/segment.py`), 9 tests
- **M3 Stylometry extractor** (`app/pipeline/stylometry.py`), 14 tests
- **M4 Claim extractor** (`app/pipeline/claims.py`), 12 tests
- **M5 LLM provider interface** (`app/llm/`), 13 tests
- Contracts (`app/pipeline/base.py`)

**61 tests passing. Next: M6 Prompt library.**

Keep this section updated as milestones land.
