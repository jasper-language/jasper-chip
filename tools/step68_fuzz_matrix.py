# -*- coding: utf-8 -*-
"""Step68: Fuzz matrix over (card_link_depth × reloc_link_depth) and seeds.

This tool turns the Step65 fuzz into a *parameter-sweep artifact*:
  - one CSV row per (depth_pair, seed)
  - an aggregated summary CSV + markdown table per depth_pair

Why: we can now quantify how inter-chip buffering depth impacts backpressure
and end-to-end progress, while keeping all Step58~67 correctness contracts.

Examples:
  python -m tools.step68_fuzz_matrix --card-depths 1,2 --reloc-depths 1,2 --seeds 0x1,0x2 --cycles 120
  python -m tools.step68_fuzz_matrix --card-depths 1,2,4 --reloc-depths 1,2 --count 10 --seed0 0x2000
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys


DEFAULT_OUT_MATRIX = Path("reports") / "step68_fuzz_matrix.csv"
DEFAULT_OUT_SUMMARY = Path("reports") / "step68_fuzz_summary.csv"
DEFAULT_OUT_MD = Path("reports") / "step68_fuzz_summary.md"


def _parse_int_list(s: str) -> list[int]:
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return [int(p, 0) for p in parts]


def _parse_depths(s: str) -> list[int]:
    ds = _parse_int_list(s)
    assert ds and all(d > 0 for d in ds)
    return ds


def _gen_seeds(*, seeds: str, count: int, seed0: int) -> list[int]:
    if seeds:
        return _parse_int_list(seeds)
    n = int(count) if int(count) else 10
    return [int(seed0) + i for i in range(n)]


def _run_one(
    *,
    seed: int,
    cycles: int,
    drain_cycles: int,
    card_depth: int,
    reloc_depth: int,
    queries: int,
) -> dict[str, int | str]:
    cmd = [
        sys.executable,
        "-m",
        "tools.step65_fuzz_run",
        "--seed",
        hex(int(seed)),
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
        row.setdefault("seed", int(seed))
        row["card_link_depth"] = int(card_depth)
        row["reloc_link_depth"] = int(reloc_depth)
        row["query_count"] = int(queries)
        row["ok"] = 1
        row["err"] = ""
        return row
    except subprocess.CalledProcessError as e:
        return {
            "seed": int(seed),
            "card_link_depth": int(card_depth),
            "reloc_link_depth": int(reloc_depth),
            "query_count": int(queries),
            "cycles": int(cycles),
            "drain_cycles": int(drain_cycles),
            "ok": 0,
            "err": (e.stderr or "")[:200],
        }


def run_matrix(
    *,
    seeds: list[int],
    card_depths: list[int],
    reloc_depths: list[int],
    cycles: int,
    drain_cycles: int,
    queries: int,
    out_matrix: Path,
    out_summary: Path,
    out_md: Path,
) -> tuple[list[dict[str, int | str]], list[dict[str, int | str]]]:
    out_matrix.parent.mkdir(parents=True, exist_ok=True)
    out_summary.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, int | str]] = []
    for cd in card_depths:
        for rd in reloc_depths:
            for s in seeds:
                rows.append(
                    _run_one(
                        seed=int(s),
                        cycles=int(cycles),
                        drain_cycles=int(drain_cycles),
                        card_depth=int(cd),
                        reloc_depth=int(rd),
                        queries=int(queries),
                    )
                )

    keys = sorted({k for r in rows for k in r.keys()})
    with out_matrix.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # Aggregate per depth-pair.
    def _group_key(r: dict[str, int | str]) -> tuple[int, int]:
        return int(r.get("card_link_depth", 0)), int(r.get("reloc_link_depth", 0))

    groups: dict[tuple[int, int], list[dict[str, int | str]]] = {}
    for r in rows:
        groups.setdefault(_group_key(r), []).append(r)

    summary_rows: list[dict[str, int | str]] = []
    for (cd, rd), rs in sorted(groups.items()):
        n = len(rs)
        ok = sum(1 for r in rs if int(r.get("ok", 0)) == 1)

        def avg(field: str) -> int:
            vals = [int(r.get(field, 0)) for r in rs if int(r.get("ok", 0)) == 1]
            return int(round(sum(vals) / max(1, len(vals))))

        summary_rows.append(
            {
                "card_link_depth": int(cd),
                "reloc_link_depth": int(rd),
                "seeds": int(n),
                "ok": int(ok),
                "ok_rate_pct": int(round(100.0 * ok / max(1, n))),
                "avg_max_card_link_level": avg("max_card_link_level"),
                "avg_max_reloc_link_level": avg("max_reloc_link_level"),
                "avg_reloc_commits": avg("reloc_commits"),
                "avg_wb_events": avg("wb_events"),
                "avg_epoch_flips": avg("epoch_flips"),
            }
        )

    skeys = list(summary_rows[0].keys()) if summary_rows else [
        "card_link_depth",
        "reloc_link_depth",
        "seeds",
        "ok",
        "ok_rate_pct",
    ]
    with out_summary.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=skeys)
        w.writeheader()
        for r in summary_rows:
            w.writerow(r)

    # Markdown table.
    with out_md.open("w", encoding="utf-8") as f:
        f.write("# Step68 fuzz summary\n\n")
        f.write("Columns: ok/total seeds, ok rate, avg max link occupancy.\n\n")
        f.write("| card_depth | reloc_depth | ok/total | ok_rate | avg_max_card | avg_max_reloc |\n")
        f.write("|---:|---:|---:|---:|---:|---:|\n")
        for r in summary_rows:
            f.write(
                f"| {int(r['card_link_depth'])} | {int(r['reloc_link_depth'])} | "
                f"{int(r['ok'])}/{int(r['seeds'])} | {int(r['ok_rate_pct'])}% | "
                f"{int(r['avg_max_card_link_level'])} | {int(r['avg_max_reloc_link_level'])} |\n"
            )

    return rows, summary_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card-depths", type=str, default="1,2")
    ap.add_argument("--reloc-depths", type=str, default="1,2")
    ap.add_argument("--seeds", type=str, default="")
    ap.add_argument("--count", type=int, default=0)
    ap.add_argument("--seed0", type=lambda s: int(s, 0), default=0x2000)
    ap.add_argument("--cycles", type=int, default=120)
    ap.add_argument("--drain-cycles", type=int, default=220)
    ap.add_argument("--queries", type=int, default=6)
    ap.add_argument("--out-matrix", type=Path, default=DEFAULT_OUT_MATRIX)
    ap.add_argument("--out-summary", type=Path, default=DEFAULT_OUT_SUMMARY)
    ap.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    args = ap.parse_args()

    card_depths = _parse_depths(args.card_depths)
    reloc_depths = _parse_depths(args.reloc_depths)
    seeds = _gen_seeds(seeds=args.seeds, count=args.count, seed0=args.seed0)

    rows, summary = run_matrix(
        seeds=seeds,
        card_depths=card_depths,
        reloc_depths=reloc_depths,
        cycles=args.cycles,
        drain_cycles=args.drain_cycles,
        queries=args.queries,
        out_matrix=args.out_matrix,
        out_summary=args.out_summary,
        out_md=args.out_md,
    )

    ok = sum(1 for r in rows if int(r.get("ok", 0)) == 1)
    print(
        f"Wrote {args.out_matrix} and {args.out_summary} (+md). "
        f"Rows: {len(rows)}, ok: {ok}/{len(rows)}, depth_pairs: {len(summary)}"
    )


if __name__ == "__main__":
    main()
