# How to run

Everything here runs offline with no API key. Keys are only needed to compare
hosted premium or open-weight models.

## 1. Requirements

- Python 3.11 or newer (3.12 recommended)
- git
- Optional: [Ollama](https://ollama.com) for free local models
- Optional: an API key for hosted models (see section 5)

## 2. Set up the environment

With conda:

```bash
conda env create -f environment.yml
conda activate academiahumanify
pip install -e ".[dev]"
```

Or with a plain virtual environment:

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate
pip install -e ".[dev]"
```

## 3. Run the tests

```bash
python -m pytest
```

The whole suite runs offline against a deterministic stub. No model, no key, no
network.

## 4. See it work

```bash
# The full pipeline on a sample paragraph: protect, rewrite, verify, changelog.
python scripts/demo.py

# Compare models on one draft and rank the rewrites.
python scripts/compare.py
python scripts/compare.py --file your_draft.txt --voice your_writing_sample.txt
```

Offline, only the deterministic stub and any local Ollama models run. To use a
local model with zero cost:

```bash
ollama pull gpt-oss:20b     # or: ollama pull qwen3:8b
python scripts/compare.py --models stub-echo,gpt-oss-20b-ollama
```

## 5. Use hosted models (optional)

Copy the key template and paste in whatever keys you have:

```bash
cp .env.example .env
```

Open `.env` and paste a key after the matching `=`. The `.env` file is gitignored
and never committed. The simplest option is a single **OpenRouter** key
(https://openrouter.ai), which reaches Claude, Gemini, GPT, and gpt-oss:

```
OPENROUTER_API_KEY=sk-or-...
```

Then run a comparison with real models:

```bash
python scripts/compare.py --models stub-echo,openrouter-gpt-oss-120b,openrouter-claude --judge openrouter-claude
```

The available models live in `models.toml`. Enable one by setting `enabled = true`
and making sure its key is present. If a model returns an error, its id may have
changed; update `model = "..."` to a current id from the provider.

## 6. Command reference

```bash
python -m pytest                       # all tests
python -m pytest -k protection         # one module
python -m ruff check app tests         # lint
python -m mypy app                     # type check
python scripts/demo.py                 # offline pipeline demo
python scripts/compare.py --help       # comparison options
```

Note: `make` targets exist in the Makefile for convenience, but `make` is not
required. The `python -m ...` commands above do the same thing.
