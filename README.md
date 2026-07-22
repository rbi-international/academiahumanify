# AcademiaHumanify

An academic editor. It takes a research draft and makes it read like excellent
human writing: clearer, better paced, in the author's own voice, with
machine-writing tells removed. It changes zero facts.

It is not a detector-evasion tool. See `CLAUDE.md` section 2.

## Quick start

```bash
make setup
make test      # 22 passed
```

## Where to look

| File | Purpose |
|---|---|
| `CLAUDE.md` | Read first. Product rules, invariants, working agreement |
| `docs/ARCHITECTURE.md` | Why the design is shaped this way |
| `docs/BUILD_PLAN.md` | 16 milestones, one per session, with checkboxes |
| `docs/SETUP.md` | Environment, git, testing, Docker, deployment |
| `docs/PROGRESS.md` | Running log of what was built and what broke |

## Status

M1 protection core and M2 segmenter complete. 22 tests passing.
Next: M3 stylometry extractor.
