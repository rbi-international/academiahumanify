"""Compare several models on the same draft and rank the rewrites.

Runs the real comparison service. Offline, only the stub baseline is available
and it changes nothing; the moment you enable a model in models.toml and set its
API key (or run a local Ollama model), it joins the comparison.

Examples:

    python scripts/compare.py
    python scripts/compare.py --file draft.txt --models qwen3-8b-ollama,stub-echo
    python scripts/compare.py --intensity conservative --voice my_writing.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.llm.catalog import default_catalog  # noqa: E402
from app.pipeline.base import Intensity, RunContext  # noqa: E402
from app.services import compare  # noqa: E402

RULE = "=" * 74

SAMPLE = (
    "It was observed that the utilisation of the proposed method resulted in a "
    "significant improvement of accuracy by 12.4% on the benchmark dataset [17]. "
    "Moreover, the results demonstrate that the model may suggest a potential "
    "benefit for downstream tasks (p < 0.05)."
)


def _status(candidate: object, is_best: bool) -> str:
    c = candidate
    if not c.ok:  # type: ignore[attr-defined]
        return "ERROR"
    if not c.eligible:  # type: ignore[attr-defined]
        return "failed fidelity"
    return "BEST" if is_best else "ok"


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare models on one draft.")
    parser.add_argument("--file", type=Path, help="draft text file (defaults to a sample)")
    parser.add_argument("--models", help="comma-separated model ids (defaults to all available)")
    parser.add_argument("--intensity", default="balanced",
                        choices=[i.value for i in Intensity])
    parser.add_argument("--voice", type=Path, help="a file with a sample of your own writing")
    args = parser.parse_args()

    catalog = default_catalog()
    text = args.file.read_text(encoding="utf-8") if args.file else SAMPLE
    voice = args.voice.read_text(encoding="utf-8") if args.voice else None
    model_ids = (
        [m.strip() for m in args.models.split(",")]
        if args.models
        else [s.id for s in catalog.available()]
    )

    ctx = RunContext(intensity=Intensity(args.intensity), voice_sample=voice)

    print(RULE)
    print(" Model comparison. Fidelity is a hard gate, quality ranks the rest.")
    print(f" Models: {', '.join(model_ids)}")
    print(RULE)
    print("\nDRAFT:\n")
    print(text.strip())

    comparison = compare(text, model_ids, ctx, catalog=catalog)
    best = comparison.best()

    print(f"\n{RULE}\n RANKING\n{RULE}")
    print(f"{'rank':<5}{'model':<32}{'status':<16}{'quality':<9}{'tells-':<8}{'tokens':<8}")
    print(f"{'':<5}{'':<32}{'':<16}{'rank':<9}{'removed':<8}{'':<8}")
    for i, c in enumerate(comparison.candidates, start=1):
        is_best = best is not None and c.model_id == best.model_id
        if c.ok and c.evaluation is not None:
            quality = f"{c.evaluation.quality_rank:.3f}"
            removed = str(c.evaluation.quality.tells_removed)
        else:
            quality = "-"
            removed = "-"
        print(f"{i:<5}{c.display_name[:31]:<32}{_status(c, is_best):<16}"
              f"{quality:<9}{removed:<8}{c.tokens:<8}")
        if not c.ok and c.error:
            print(f"     note: {c.error}")

    print(f"\n{RULE}\n WINNER\n{RULE}")
    if best is None:
        print("No candidate passed the fidelity gate. Nothing changed a fact safely.")
    else:
        ev = best.evaluation
        print(f"{best.display_name}  (quality rank {ev.quality_rank:.3f})")
        if ev.fidelity.claim_weakened:
            print("note: a claim was weakened relative to the original. Review it.")
        if ev.fidelity.sentence_flag:
            print("note: sentence count moved a lot. Review the structure.")
        print("\nBEFORE:\n")
        print(comparison.original_text)
        print("\nAFTER:\n")
        print(best.rewritten_text)

    print(f"\n{RULE}")
    print(" Ran locally. Hosted models run only when their API key is set.")
    print(RULE)


if __name__ == "__main__":
    main()
