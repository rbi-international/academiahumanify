# Setup and Operations

Covers local environment, git workflow, testing, Docker, and getting the app in
front of testers.

---

## 1. Local environment

Requirements: Python 3.11+, Node 20+, git. Ollama only from M5 onward.

```bash
git clone <your-repo-url> academiahumanify
cd academiahumanify
make setup
make test          # expect: 22 passed
```

`make setup` creates `backend/.venv`, installs `requirements.txt` and
`requirements-dev.txt`, and installs the frontend packages once M13 exists.

Manual equivalent:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

### Ollama (from M5)

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:8b       # dev model, fits a 6GB card
ollama serve
```

Your RTX 3060 with 6GB runs a small model comfortably. It will not run a
70B-class model, and it does not need to. Local Ollama is for development and
tests. Production points the same `LLMProvider` interface at a hosted endpoint.

### Environment variables

Copy `.env.example` to `.env`. Nothing secret is committed.

```
LLM_PROVIDER=stub           # stub | ollama | openai_compat
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b
OPENAI_COMPAT_BASE_URL=
OPENAI_COMPAT_API_KEY=
OPENAI_COMPAT_MODEL=
DATABASE_URL=sqlite:///./dev.db
LOG_LEVEL=INFO
MAX_CHARS=200000
```

`LLM_PROVIDER=stub` is the default so a fresh clone runs the full test suite
with no model, no key, and no network.

---

## 2. Git workflow

`main` is always green. One branch per milestone.

```bash
git checkout -b feat/03-stylometry
# build, test
make test
git add -A
git commit -m "feat(stylometry): voice feature extraction

- sentence length distribution, connective inventory, hedging density
- active/passive ratio, nominalisation rate
- low-confidence flag for samples under 80 words

Tests: 11 added, 33 total passing"
git checkout main
git merge --squash feat/03-stylometry
git commit
git tag m03-stylometry
```

Rules:
- never commit with failing tests
- never commit `.env`, `.venv/`, `node_modules/`, `*.db`
- one milestone per branch, so a bad milestone reverts cleanly
- tag every completed milestone, so you can bisect when something breaks later

### Pre-commit (optional but recommended)

```bash
pip install pre-commit
pre-commit install
```

Runs ruff, mypy, and pytest on staged changes.

---

## 3. Testing

```bash
make test                 # everything
pytest tests/unit         # fast, no network, no model
pytest tests/integration  # full pipeline against StubProvider
pytest -m llm             # only tests needing a live model, skipped by default
pytest -k protection      # one module
pytest --cov=app          # coverage
```

Three layers:

| Layer | Speed | Needs |
|---|---|---|
| unit | milliseconds | nothing |
| integration | seconds | StubProvider |
| llm (opt-in) | slow | Ollama or a hosted endpoint |

The deterministic core is deliberately large so most of the product is testable
without a model at all. Keep it that way.

**Fixture corpus.** `tests/fixtures/` holds real paper excerpts across CS,
biology, physics, and social science. Every fidelity bug found in the wild gets
added here as a permanent case.

---

## 4. Project layout

```
academiahumanify/
├── CLAUDE.md               read first, context for Claude Code
├── Makefile
├── .env.example
├── backend/
│   ├── app/
│   │   ├── api/v1/         REST surface, thin, no logic
│   │   ├── core/           protection.py, config, errors, logging
│   │   ├── pipeline/       base.py contracts, one file per stage
│   │   ├── llm/            provider interface, stub, ollama, openai-compat
│   │   ├── schemas/        pydantic, boundary only
│   │   ├── services/       orchestrator, jobs, export
│   │   └── db/             models, migrations
│   ├── tests/{unit,integration,fixtures}
│   ├── pytest.ini
│   └── requirements.txt
├── frontend/               React 18 + TS + Tailwind + shadcn
├── prompts/{system,fewshot}
├── docker/
├── docs/                   ARCHITECTURE.md, BUILD_PLAN.md, SETUP.md, PROGRESS.md
└── scripts/
```

---

## 5. Docker (from M15)

```bash
cp .env.example .env
docker compose up --build
# frontend  http://localhost:3000
# api       http://localhost:8000
# api docs  http://localhost:8000/docs
```

Services: `api`, `worker`, `db` (postgres), `frontend`. Ollama stays on the host
rather than in a container, so it can use the GPU without device passthrough
complications.

Two compose files: `docker-compose.yml` for local, `docker-compose.prod.yml`
adding restart policies, resource limits, and no bind mounts.

---

## 6. Getting it to testers

Three stages. Do not skip to stage three.

### Stage A: same room, your machine

`make run`, share your screen, watch someone use it. You will learn more from
three people in a room than from thirty anonymous sessions. Do this before any
deployment work.

### Stage B: temporary public URL, no infrastructure

```bash
cloudflared tunnel --url http://localhost:8000
```

Gives a public HTTPS URL pointing at your laptop. Good for a handful of trusted
testers over a few days. Nothing to provision, nothing to pay for, and you can
watch the logs live while they use it. Your machine has to stay on.

### Stage C: real hosting

Once feedback justifies it:

| Piece | Option | Notes |
|---|---|---|
| Backend | Render, Railway, or Fly.io | deploy the Docker image directly |
| Frontend | Vercel or Netlify | static build, free tier is enough |
| Database | managed postgres on the same host | do not self-manage this early |
| Model | Together, Fireworks, or DeepInfra | per-token, no GPU to rent |

Do **not** rent a GPU to self-host a 72B model for a test cohort. Per-token
hosted inference is far cheaper until you have steady volume, and it lets you
swap models by changing one config value.

### Access control for testers

- invite codes or basic auth, so it is not open to the world
- a per-user daily character cap, so one tester cannot burn your inference budget
- a visible ethics notice before the first run

### Feedback capture (this is the point of M16)

Store, per run: input hash, settings used, prompt version, model, every
`StageReport`, the output, and the tester's thumbs up or down plus a comment.

The reason this matters: when a tester says "it changed my meaning in section 4",
you need to reproduce that exact run. Without the prompt version and settings
stored alongside the output, you cannot. This is also the dataset that makes a
distillation fine-tune possible much later.

---

## 7. Cost control

- cache by segment hash, identical paragraphs are never re-billed
- cap document size, `MAX_CHARS`
- run conservative sections through a smaller model, they need less capability
- log token counts per run from day one, so pricing is not guesswork later
