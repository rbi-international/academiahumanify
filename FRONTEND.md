# Frontend specification

The interface must let a user do everything the pipeline can do, without touching
a terminal. Graphics-rich, and fully usable on a phone. Built at milestone M13.

Stack (from `ARCHITECTURE.md`): React 18 + TypeScript + Tailwind + shadcn/ui.
Mobile-first responsive layout. Charts must be accessible and read well in light
and dark. LaTeX preview via KaTeX; code and equation editing via Monaco.

---

## 1. Principles

- **Mobile-first.** Every screen works on a phone: panels stack, controls are
  touch-sized, the diff and comparison views become swipeable tabs instead of
  side-by-side columns.
- **Graphics-rich but honest.** Scorecards, meters, and diffs make the numbers
  legible. No vanity metrics. Never show an "AI score" or a detector reading,
  that is out of scope by charter (see `CLAUDE.md` section 2).
- **The ethics notice is visible before the first run, not buried.** It states
  plainly: this tool improves your writing and preserves your facts; it is not a
  way to disguise authorship.

## 2. Core flows and screens

### 2.1 Input
- Paste text, or **upload a file**: docx, Markdown, LaTeX, txt, PDF.
- Drag-and-drop, and a mobile file/camera picker.
- Detected sections shown back to the user (from the segmenter) so they can see
  what will be frozen (headings, equations, tables, references).

### 2.2 Settings
- Intensity: conservative / balanced / enhanced (with a note that Methods and
  Results are always conservative).
- Style: formal conservative / modern interdisciplinary.
- Discipline: CS / biology / physics / social science (drives the few-shot).
- Voice sample: paste a paragraph of the author's own past writing.

### 2.3 Model selection
- A picker populated from the catalog (`GET /models`). Group by tier: local,
  premium, open-weight. Show which are available (key present) and which are
  greyed out with the env var to set.
- Multi-select to compare several models in one run.
- Optional: choose a judge model.

### 2.4 Run and progress
- Async job. Show per-model progress and a running token/cost estimate.
- Long papers do not block the UI.

### 2.5 Comparison view (the centrepiece)
- One card per model, **ranked**: fidelity gate result, quality score, voice
  match, change ratio, token cost, and the judge's pick and rationale.
- Fidelity failures and claim-drift flags shown as clear badges, not buried.
- Select the winning draft. The user always makes the final call.
- On mobile: a swipeable carousel of candidate cards.

### 2.6 Diff view
- Side-by-side original vs chosen rewrite, sentence aligned.
- Each change carries its reason from the changelog (merged, split, reordered,
  deverbalised, connective replaced, redundancy removed) as a coloured tag.
- Click a change to see the before/after pair.
- On mobile: stacked with a toggle, or an inline diff.

### 2.7 Style Report panel
- The writer's own tells, counted: repeated connectives, uniform sentence
  length, tricolons, nominalisation, AI-flavoured diction, hollow phrases.
- Presented as an editing checklist, framed as "what to fix", never a score.

### 2.8 Verification panel
- Hard gate: pass/fail with any fidelity failures listed.
- Soft flags: claim strengthened/weakened/dropped/added, sentence-count moves.

### 2.9 Export and download
- Download the chosen draft as Markdown, LaTeX, docx, or PDF.
- Round trip must preserve citations and equations (M14).
- Also export the changelog and the Style Report.

## 3. Visual system
- A small, consistent chart set for the scorecards (meters and bars), accessible
  colours, works in light and dark. Follow one design system end to end.
- LaTeX rendered inline in previews.
- Clear empty, loading, and error states for every async action.

## 4. API surface it depends on (built in M11+)
- `POST /humanize` (single model) and a compare endpoint (many models)
- `GET /runs/{id}`, `GET /runs/{id}/changelog`
- `POST /style-report`
- `GET /models` (the catalog for the picker)
- `GET /health`
- file upload/convert endpoints (M14)

## 5. Definition of done (M13)
- Upload or paste, section-aware view, intensity and style and voice controls.
- Model picker with multi-select and availability.
- Comparison view with per-candidate scorecards and selection.
- Side-by-side diff with per-change reasons.
- Style Report and Verification panels.
- Export to at least Markdown and LaTeX.
- Works on a phone screen without horizontal scrolling.
- The ethics notice appears before the first run.
