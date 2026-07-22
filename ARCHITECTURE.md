# AcademiaHumanify: Architecture

## 1. What this product is

An academic editor. It takes a draft and makes it read like excellent human
writing: clearer, better paced, in the author's own voice, with the machine
tells removed. It changes zero facts.

It is explicitly **not** a detector-evasion tool. There is no "AI probability
score" and no optimisation against Turnitin. The scoreboard is prose quality
and factual fidelity. That decision shapes every module below.

## 2. The one hard problem

Rewriting text is easy. Rewriting it without corrupting the science is hard.
A model told to "improve flow" will happily turn `p < 0.05` into `p < 0.5`,
merge two sentences and lose a citation, or firm up a hedged claim into one the
data does not support.

The architecture answers this by refusing to trust the model with anything that
must not change:

> Generation and protection are separate systems.
> The model is creative. The protection layer is deterministic and is not
> allowed to fail.

## 3. Layers

```
   Ingest  ->  Segment  ->  Protect  ->  Rewrite  ->  Restore  ->  Verify  ->  Report
                             (regex)      (LLM)       (regex)      (regex +      (diff)
                                                                    LLM claim
                                                                    check)
```

| Stage | Deterministic? | Purpose |
|---|---|---|
| Ingest | yes | Parse docx / md / LaTeX / txt into raw text |
| Segment | yes | Split into paragraphs, tag each with its section |
| Protect | **yes** | Mask citations, numbers, equations, refs, DOIs |
| Stylometry | yes | Measure the user's voice sample into explicit features |
| Rewrite | no (LLM) | Rewrite masked prose to target voice and intensity |
| Restore | **yes** | Put every protected span back exactly |
| Verify | mixed | Placeholder integrity (hard gate) + claim drift (soft flag) |
| Changelog | yes | Sentence-level diff with a reason per change |

The two bolded stages are the moat. They are pure functions with no model
involved, so they can be exhaustively tested and never regress.

## 4. Fidelity guarantees

**Hard gate (build fails, retry triggered):**
- every protected placeholder present exactly once in model output
- no invented or mangled placeholders
- REFERENCES section never enters the rewrite path at all

**Soft gate (flagged to the user, does not block):**
- claim drift: hedging strength changed, a claim strengthened or weakened
- sentence count deviates beyond a section-specific tolerance

**Section-aware intensity override.** Methods and Results are forced to
CONSERVATIVE regardless of the user setting. Those sections carry the
reproducibility burden, and flow matters less than exactness there. Discussion
and Introduction get the full range.

## 5. Voice matching

Not fine-tuning. The user pastes a paragraph of their **own past academic
writing** (not an improvised sample on a topic, which produces a false voice and
leaks its content into the output).

Two signals go into the prompt:
1. `exemplar`: the raw sample, for feel.
2. `features`: measured stylometry, for reliability. Mean sentence length and
   variance, connective inventory, hedging density, active/passive ratio,
   nominalisation rate, clause depth.

Explicit numeric targets are followed far more reliably than "match this vibe".

## 6. Model strategy

Provider-agnostic `LLMProvider` interface from day one. Nothing above the
`llm/` package knows which model is running.

- **Dev / local:** small Qwen3 via Ollama. Runs on a 6GB card.
- **Production:** Qwen3 72B-class via a hosted endpoint (Together, Fireworks,
  DeepInfra). Apache 2.0, so no license ceiling on a commercial product.
- **Later, for cost only:** distil the prompted big-model outputs into a small
  fine-tune. Same family, same tokenizer, so the swap is trivial.

Fine-tuning is deferred deliberately. There is no clean paired dataset for
"AI-flavoured vs human-flavoured", and manufacturing one teaches the model to
invert whichever paraphraser produced the synthetic half. The prompt plus
exemplar approach reaches most of the quality with none of that debt, and it
personalises per user, which a single fine-tune cannot.

## 7. Repository layout

```
academiahumanify/
├── backend/
│   ├── app/
│   │   ├── api/v1/         REST surface, thin. No logic.
│   │   ├── core/           protection.py, config, errors, logging
│   │   ├── pipeline/       base.py (contracts), one file per stage
│   │   ├── llm/            provider interface + ollama / openai-compat
│   │   ├── schemas/        pydantic request and response models
│   │   ├── services/       orchestration, job queue, export
│   │   └── db/             models, migrations, session
│   └── tests/
│       ├── unit/           pure functions, fast, no network
│       ├── integration/    pipeline end to end with a stub LLM
│       └── fixtures/       real paper excerpts across fields
├── frontend/               React 18 + TS + Tailwind + shadcn
├── prompts/
│   ├── system/             versioned system prompts, one file per stage
│   └── fewshot/            per-field before/after exemplars
├── docker/
├── docs/
└── scripts/
```

Prompts live in version control as files, not as strings inside Python. They
are product logic and they change more often than code does. Treating them as
assets means you can diff them, A/B them, and roll one back without a deploy.

## 8. Build order

1. **Protection core** (done, 10 unit tests green)
2. Segmenter with section detection
3. Stylometry extractor
4. LLM provider interface plus a deterministic stub provider for tests
5. Rewrite stage and the prompt library
6. Verify stage: claim drift
7. Orchestrator wiring stages 1 to 6
8. FastAPI surface
9. React frontend
10. Docker, then export formats

Nothing above step 4 needs a GPU or a network call, which means the hard part
is provable before a single token is generated.
