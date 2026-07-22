"""Offline smoke test: run everything built so far on a real paragraph.

This calls no model and hits no network. It uses the deterministic protection,
segmentation, stylometry, and claim stages, then drives the mask -> rewrite ->
verify -> restore safety loop through the StubProvider so you can see the
fidelity guarantees hold on real text.

The "rewrite" here is a few stand-in string edits fed through the stub, standing
in for the model, so the safety loop is exercised without spending a token. The
actual model-generated rewrite arrives at milestone M7.

Run it (no third-party packages needed):

    python scripts/demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the repo root importable however this file is launched.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The placeholder tokens use ⟦ ⟧, which a default Windows console (cp1252) cannot
# print. Force UTF-8 so the demo runs the same in an Anaconda prompt as on a Mac.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.core.protection import protect, restore_verified  # noqa: E402
from app.llm import ProviderConfig, get_provider  # noqa: E402
from app.pipeline.base import Document, Intensity, RunContext, Segment  # noqa: E402
from app.pipeline.claims import extract_claims  # noqa: E402
from app.pipeline.rewrite import RewriteStage  # noqa: E402
from app.pipeline.segment import Segmenter  # noqa: E402
from app.pipeline.stylometry import extract  # noqa: E402
from app.prompts import (  # noqa: E402
    Discipline,
    StyleVariant,
    compose_rewrite_system,
)

RULE = "=" * 70

SAMPLE = (
    "It was observed that the utilisation of the proposed method resulted in a "
    "significant improvement of accuracy by 12.4% on the benchmark dataset [17]. "
    "Moreover, the results demonstrate that the model may suggest a potential "
    "benefit for downstream tasks (p < 0.05)."
)


def banner(title: str) -> None:
    print(f"\n{RULE}\n {title}\n{RULE}")


def main() -> None:
    print(RULE)
    print(" AcademiaHumanify offline smoke test (no model, no network, no tokens)")
    print(RULE)
    print("\nORIGINAL DRAFT:\n")
    print(SAMPLE)

    # 1. Protection: mask every fragile span, prove the round trip is exact.
    banner("1. PROTECTION  (mask fragile spans, verify, restore)")
    protected = protect(SAMPLE)
    print("Masked text the model would see:\n")
    print(protected.masked)
    print("\nWhat each placeholder stands for:")
    for token, original in protected.mapping.items():
        print(f"  {token}  ->  {original!r}")
    round_trip = restore_verified(protected.masked, protected)
    print(f"\nRound trip is byte-identical to the original: {round_trip == SAMPLE}")

    # 2. Segmentation: which section, what is frozen.
    banner("2. SEGMENTATION  (section tagging, freezing)")
    doc = Segmenter().run(Document(text=SAMPLE), RunContext(intensity=Intensity.BALANCED))
    report = doc.reports[-1]
    print(f"segments={report.notes['segments']}  "
          f"section_aware={report.notes['section_aware']}")
    for seg in doc.segments:
        print(f"  [{seg.index}] section={seg.section} frozen={seg.frozen} kind={seg.kind}")

    # 3. Stylometry: the Style Report of the author's own tells.
    banner("3. STYLE REPORT  (the writer's own tells, an editing signal)")
    profile = extract(SAMPLE)
    print(f"words={profile.word_count}  sentences={profile.sentence_count}  "
          f"confidence={profile.confidence.value}")
    f = profile.features
    print(f"sentence length: mean={f.sentence_length_mean:.1f} "
          f"variance={f.sentence_length_variance:.1f}")
    print(f"passive ratio={f.passive_ratio:.2f}  "
          f"nominalisation rate={f.nominalisation_rate:.1f}/100 words")
    print("tells:", profile.style_report())

    # 4. Claims: what is asserted and how firmly (for later drift checks).
    banner("4. CLAIMS  (subject / relation / object / hedge strength)")
    for claim in extract_claims(SAMPLE):
        print(f"  [{claim.hedge.name}] {claim.subject!r} --{claim.relation}--> {claim.object!r}")

    # 5. The composed rewrite prompt the model would receive.
    banner("5. REWRITE PROMPT  (composed from versioned files, with checksums)")
    rendered = compose_rewrite_system(
        Intensity.BALANCED, StyleVariant.MODERN_INTERDISCIPLINARY, Discipline.CS
    )
    print("Fragments used (id @ version, checksum):")
    for ref in rendered.refs:
        print(f"  {ref.id} @ v{ref.version}  {ref.checksum[:12]}")
    print(f"\nSystem prompt is {len(rendered.text)} characters "
          f"(first 220 shown):\n")
    print(rendered.text[:220] + " ...")

    # 6. The real M7 rewrite stage: mask -> model -> verify -> restore.
    banner("6. REWRITE STAGE  (the real M7 stage, driven by the stub provider)")
    # The stub stands in for the model. These are the edits a model would make,
    # written against the masked text so every ⟦P...⟧ token and the hedge survive.
    # A real model (or a local Ollama Qwen3) plugs into the exact same stage and
    # generates this itself instead of us scripting it.
    masked_rewrite = (
        protected.masked
        .replace(
            "It was observed that the utilisation of the proposed method "
            "resulted in a significant improvement of accuracy by",
            "The proposed method improved accuracy by",
        )
        .replace(
            "Moreover, the results demonstrate that the model may suggest a "
            "potential benefit for downstream tasks",
            "These results may suggest a benefit for downstream tasks",
        )
    )
    stub = get_provider(ProviderConfig(kind="stub", extra={"scripted": [masked_rewrite]}))
    prose = Segment(index=0, text=SAMPLE, frozen=False, kind="paragraph")
    rewrite_doc = Document(text=SAMPLE, segments=(prose,))
    result_doc = RewriteStage(stub, max_workers=1).run(
        rewrite_doc, RunContext(intensity=Intensity.BALANCED)
    )
    rewritten = result_doc.segments[0].text
    print("stage report:", result_doc.reports[-1].notes)

    print("\nBEFORE:\n")
    print(SAMPLE)
    print("\nAFTER (machine tells removed, every fact and hedge intact):\n")
    print(rewritten)

    print(f"\n{RULE}")
    print(" Everything above ran offline and deterministically. No API tokens spent.")
    print(f"{RULE}")


if __name__ == "__main__":
    main()
