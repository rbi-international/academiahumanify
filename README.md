# AcademiaHumanify

An academic editor. It takes a research draft and makes it read like excellent
human writing: clearer, better paced, in the author's own voice, with
machine-writing tells removed. **It changes zero facts.**

It is an editor, not a detector-evasion tool. There is no AI-probability score
and no optimisation against any detector. The scoreboard is prose quality and
factual fidelity.

## What it does

- **Protects the science.** Every citation, number, p-value, equation, and DOI is
  masked before a model sees the text and verified present afterwards, so a
  rewrite can never quietly change `p < 0.05` into `p < 0.5` or drop a citation.
- **Rewrites for a human voice.** It removes uniform sentence length, hollow
  connectives, tricolons, nominalisations, and inflated diction, and can match a
  sample of the author's own past writing.
- **Compares models.** Run one draft through several models at once, score each
  rewrite on fidelity and readability, and pick the best. A premium model can act
  as an optional judge.
- **Shows its work.** A sentence-level changelog explains every edit (merged,
  split, reordered, deverbalised, connective replaced, redundancy removed), and a
  verification report flags any claim whose strength drifted.

## How it is built

```
Ingest -> Segment -> Protect -> Rewrite -> Restore -> Verify -> Changelog
          (regex)   (regex)     (LLM)     (regex)    (rules)    (diff)
```

Generation and protection are separate systems. The model is creative; the
protection layer is deterministic and is not allowed to fail. The whole pipeline
runs offline against a deterministic stub, so most of the product is testable
with no model, no key, and no network.

Provider-agnostic: local models via Ollama, or hosted premium and open-weight
models (OpenAI, Anthropic, Gemini, Qwen, DeepSeek, Llama, gpt-oss) through a
single OpenAI-compatible interface. Models are chosen from a config file, not
code.

## Getting started

See [HOW_TO_RUN.md](HOW_TO_RUN.md) for setup, running the tests, the offline
demo, the model-comparison tool, and configuring API keys.

Quick version:

```bash
conda env create -f environment.yml
conda activate academiahumanify
pip install -e ".[dev]"
python -m pytest          # runs fully offline
python scripts/demo.py    # see the pipeline on a sample paragraph
```

## Status

The deterministic core and the model layer are complete and tested, wired into a
single orchestrated run, with a model-comparison and evaluation subsystem. The
HTTP API and the web frontend are the next milestones.

## License

To be decided.
