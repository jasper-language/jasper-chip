# -*- coding: utf-8 -*-
"""Step67: Generate a CSV report from many deterministic fuzz runs.

This turns the Step65/66 fuzz into a *measurable* artifact:
  - per-seed stats (max link occupancy, stale-drop counts, op mix)
  - pass/fail bit

Usage examples:
  python -m tools.step67_fuzz_report --seeds 0x1,0x2,0xC0FFEE --cycles 120 --out reports/step67_fuzz.csv
  python -m tools.step67_fuzz_report --count 20 --seed0 0x1000 --cycles 120
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import subprocess
import sys

import json


DEFAULT_OUT = Path("reports") / "step67_fuzz_report.csv"


def _parse_seeds(s: str) -> list[int]:
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return [int(p, 0) for p in parts]


def run_report(
    *,
    seeds: list[int],
    cycles: int,
    drain_cycles: int,
    card_depth: int,
    reloc_depth: int,
    queries: int,
    out_csv: Path,
    continue_on_fail: bool = False,
) -> list[dict[str, int | str]]:
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, int | str]] = []
    for s in seeds:
        # NOTE: Amaranth's pysim can hang if we run multiple Simulator instances in one Python process.
        # Run each seed in a fresh process and parse JSON stats.
        cmd = [
            sys.executable,
            "-m",
            "tools.step65_fuzz_run",
            "--seed",
            hex(int(s)),
            "--cycles",
            str(int(cycles)),
            "--drain-cycles",
            str(int(drain_cycles)),
            "--card-depth",
            str(int(card_depth)),
            "--reloc-depth",
            str(int(reloc_depth)),
            "--queries",
            str(int(queries)),
            "--json",
        ]
        try:
            cp = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL)
            st = json.loads(cp.stdout.strip() or "{}")
            row: dict[str, int | str] = {k: int(v) for k, v in st.items()}
            # Ensure we always emit basic config fields.
            row.setdefault("seed", int(s))
            row.setdefault("cycles", int(cycles))
            row.setdefault("drain_cycles", int(drain_cycles))
            row.setdefault("card_link_depth", int(card_depth))
            row.setdefault("reloc_link_depth", int(reloc_depth))
            row.setdefault("query_count", int(queries))
            row["ok"] = 1
            row["err"] = ""
        except subprocess.CalledProcessError as e:
            row = {
                "seed": int(s),
                "cycles": int(cycles),
                "drain_cycles": int(drain_cycles),
                "card_link_depth": int(card_depth),
                "reloc_link_depth": int(reloc_depth),
                "query_count": int(queries),
                "ok": 0,
                "err": (e.stderr or "")[:200],
            }
            rows.append(row)
            if not continue_on_fail:
                break
        else:
            rows.append(row)

    # Normalize headers (union of keys) then write CSV.
    keys = sorted({k for r in rows for k in r.keys()})
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=str, default="")
    ap.add_argument("--count", type=int, default=0)
    ap.add_argument("--seed0", type=lambda s: int(s, 0), default=0x1000)
    ap.add_argument("--cycles", type=int, default=120)
    ap.add_argument("--drain-cycles", type=int, default=220)
    ap.add_argument("--card-depth", type=int, default=2)
    ap.add_argument("--reloc-depth", type=int, default=2)
    ap.add_argument("--queries", type=int, default=6)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--continue-on-fail", action="store_true")
    args = ap.parse_args()

    if args.seeds:
        seeds = _parse_seeds(args.seeds)
    else:
        n = int(args.count) if args.count else 10
        seeds = [int(args.seed0) + i for i in range(n)]

    rows = run_report(
        seeds=seeds,
        cycles=args.cycles,
        drain_cycles=args.drain_cycles,
        card_depth=args.card_depth,
        reloc_depth=args.reloc_depth,
        queries=args.queries,
        out_csv=args.out,
        continue_on_fail=bool(args.continue_on_fail),
    )

    ok = sum(1 for r in rows if int(r.get("ok", 0)) == 1)
    print(f"Wrote {args.out} ({ok}/{len(rows)} ok)")


if __name__ == "__main__":
    main()
