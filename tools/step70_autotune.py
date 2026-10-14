# -*- coding: utf-8 -*-
"""Step70: One-shot inter-chip link-depth autotune pipeline.

This tool composes:
  - Step68 (fuzz matrix + aggregated summary)
  - Step69 (Pareto frontier + deterministic recommendation)

and emits a single machine-readable "recommended depth" artifact that can be
consumed by future steps (e.g., default harness parameters, CI knobs).

Artifacts (defaults):
  - reports/step68_fuzz_matrix.csv
  - reports/step68_fuzz_summary.csv
  - reports/step68_fuzz_summary.md
  - reports/step69_pareto.csv
  - reports/step69_pareto.md
  - reports/step70_recommended_depths.json

Examples:
  # Minimal quick run
  python -m tools.step70_autotune --card-depths 1,2 --reloc-depths 1,2 --seeds 0x1 --cycles 5 --queries 1

  # Generate seeds (count) starting at seed0
  python -m tools.step70_autotune --card-depths 1,2,4 --reloc-depths 1,2 --count 20 --seed0 0x2000
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.step68_fuzz_matrix import (
    DEFAULT_OUT_MATRIX as STEP68_OUT_MATRIX,
    DEFAULT_OUT_SUMMARY as STEP68_OUT_SUMMARY,
    DEFAULT_OUT_MD as STEP68_OUT_MD,
    _gen_seeds,
    _parse_depths,
    run_matrix,
)
from tools.step69_select_pareto import (
    DEFAULT_OUT_CSV as STEP69_OUT_CSV,
    DEFAULT_OUT_MD as STEP69_OUT_MD,
    pareto_front,
    recommend,
    write_csv,
    write_md,
    _read_summary,
)


DEFAULT_OUT_JSON = Path("reports") / "step70_recommended_depths.json"


def run_autotune(
    *,
    card_depths: list[int],
    reloc_depths: list[int],
    seeds: list[int],
    cycles: int,
    drain_cycles: int,
    queries: int,
    ok_threshold: int,
    out_matrix: Path = STEP68_OUT_MATRIX,
    out_summary: Path = STEP68_OUT_SUMMARY,
    out_md68: Path = STEP68_OUT_MD,
    out_pareto_csv: Path = STEP69_OUT_CSV,
    out_pareto_md: Path = STEP69_OUT_MD,
    out_json: Path = DEFAULT_OUT_JSON,
    run_matrix_step: bool = True,
) -> dict:
    """Run Step68 matrix + Step69 Pareto selection, then write recommended JSON.

    Returns the recommended JSON payload (also written to disk).
    """

    # Step68 sweep (optional). In constrained environments you can pre-generate
    # a summary CSV and use --skip-matrix to only run Pareto selection.
    if bool(run_matrix_step):
        run_matrix(
            seeds=list(seeds),
            card_depths=list(card_depths),
            reloc_depths=list(reloc_depths),
            cycles=int(cycles),
            drain_cycles=int(drain_cycles),
            queries=int(queries),
            out_matrix=Path(out_matrix),
            out_summary=Path(out_summary),
            out_md=Path(out_md68),
        )

    # Step69 Pareto
    rows = _read_summary(Path(out_summary))
    filtered = [r for r in rows if int(r.ok_rate_pct) >= int(ok_threshold)]
    front = pareto_front(filtered)
    rec = recommend(front)
    write_csv(front, rec, Path(out_pareto_csv))
    write_md(front, rec, int(ok_threshold), Path(out_pareto_md))

    payload: dict
    if rec is None:
        payload = {
            "ok": 0,
            "ok_threshold": int(ok_threshold),
            "reason": "no depth-pairs satisfy ok_rate filter",
            "card_link_depth": None,
            "reloc_link_depth": None,
            "total_depth": None,
        }
    else:
        payload = {
            "ok": 1,
            "ok_threshold": int(ok_threshold),
            "card_link_depth": int(rec.card_depth),
            "reloc_link_depth": int(rec.reloc_depth),
            "total_depth": int(rec.total_depth),
            "ok_rate_pct": int(rec.ok_rate_pct),
            "seeds": int(rec.seeds),
            "ok_seeds": int(rec.ok),
            "avg_max_card_link_level": int(rec.avg_max_card),
            "avg_max_reloc_link_level": int(rec.avg_max_reloc),
            "worst_avg_max_link": int(rec.worst_avg_max),
            "sum_avg_max_link": int(rec.sum_avg_max),
            "inputs": {
                "card_depths": [int(x) for x in card_depths],
                "reloc_depths": [int(x) for x in reloc_depths],
                "seeds": [int(x) for x in seeds],
                "cycles": int(cycles),
                "drain_cycles": int(drain_cycles),
                "queries": int(queries),
            },
        }

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()

    ap.add_argument("--card-depths", type=str, default="1,2")
    ap.add_argument("--reloc-depths", type=str, default="1,2")

    ap.add_argument("--seeds", type=str, default="")
    ap.add_argument("--count", type=int, default=4)
    ap.add_argument("--seed0", type=lambda s: int(s, 0), default=0x1)

    ap.add_argument("--cycles", type=int, default=40)
    ap.add_argument("--drain-cycles", type=int, default=120)
    ap.add_argument("--queries", type=int, default=4)

    ap.add_argument("--ok-threshold", type=int, default=100)

    ap.add_argument(
        "--skip-matrix",
        action="store_true",
        help="Skip Step68 sweep and only run Step69+JSON using existing --out-summary CSV.",
    )

    ap.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    ap.add_argument("--out-matrix", type=Path, default=STEP68_OUT_MATRIX)
    ap.add_argument("--out-summary", type=Path, default=STEP68_OUT_SUMMARY)
    ap.add_argument("--out-md68", type=Path, default=STEP68_OUT_MD)
    ap.add_argument("--out-pareto-csv", type=Path, default=STEP69_OUT_CSV)
    ap.add_argument("--out-pareto-md", type=Path, default=STEP69_OUT_MD)
    args = ap.parse_args()

    card_depths = _parse_depths(args.card_depths)
    reloc_depths = _parse_depths(args.reloc_depths)
    seeds = _gen_seeds(seeds=args.seeds, count=int(args.count), seed0=int(args.seed0))

    payload = run_autotune(
        card_depths=card_depths,
        reloc_depths=reloc_depths,
        seeds=seeds,
        cycles=int(args.cycles),
        drain_cycles=int(args.drain_cycles),
        queries=int(args.queries),
        ok_threshold=int(args.ok_threshold),
        out_matrix=args.out_matrix,
        out_summary=args.out_summary,
        out_md68=args.out_md68,
        out_pareto_csv=args.out_pareto_csv,
        out_pareto_md=args.out_pareto_md,
        out_json=args.out_json,
        run_matrix_step=(not bool(args.skip_matrix)),
    )
    if int(payload.get("ok", 0)) == 1:
        print(
            "Recommended depths: "
            f"card={payload['card_link_depth']} reloc={payload['reloc_link_depth']} "
            f"(ok_rate={payload.get('ok_rate_pct', '?')}%). "
            f"Wrote {args.out_json}."
        )
    else:
        print(f"No feasible depth-pair at ok_threshold={args.ok_threshold}. Wrote {args.out_json}.")


if __name__ == "__main__":
    main()
