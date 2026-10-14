# -*- coding: utf-8 -*-
"""Step69: Select Pareto-optimal inter-chip buffering depths.

This is the "parameter convergence" helper for the 3-chip GC harness.

Consumes Step68 aggregated summary (CSV) and emits:
  - a Pareto frontier over depth-pairs that satisfy correctness threshold
  - one deterministic "recommended" depth-pair

Input (default):  reports/step68_fuzz_summary.csv
Output (default): reports/step69_pareto.csv + reports/step69_pareto.md

Correctness filter:
  ok_rate_pct >= --ok-threshold (default: 100)

Pareto objectives (all minimized):
  1) total_depth = card_link_depth + reloc_link_depth
  2) worst_avg_max_link = max(avg_max_card_link_level, avg_max_reloc_link_level)
  3) sum_avg_max_link = avg_max_card_link_level + avg_max_reloc_link_level

A row A dominates row B iff all 3 objectives are <= and at least one is <.

Recommendation rule:
  Pick the Pareto row with lexicographically minimal tuple:
    (total_depth, worst_avg_max_link, sum_avg_max_link, card_link_depth, reloc_link_depth)

Examples:
  python -m tools.step69_select_pareto
  python -m tools.step69_select_pareto --in-summary reports/step68_fuzz_summary.csv --ok-threshold 100
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path


DEFAULT_IN = Path("reports") / "step68_fuzz_summary.csv"
DEFAULT_OUT_CSV = Path("reports") / "step69_pareto.csv"
DEFAULT_OUT_MD = Path("reports") / "step69_pareto.md"


@dataclass(frozen=True)
class Row:
    card_depth: int
    reloc_depth: int
    ok_rate_pct: int
    avg_max_card: int
    avg_max_reloc: int
    seeds: int
    ok: int

    @property
    def total_depth(self) -> int:
        return int(self.card_depth + self.reloc_depth)

    @property
    def worst_avg_max(self) -> int:
        return int(max(self.avg_max_card, self.avg_max_reloc))

    @property
    def sum_avg_max(self) -> int:
        return int(self.avg_max_card + self.avg_max_reloc)

    @property
    def key(self) -> tuple[int, int]:
        return int(self.card_depth), int(self.reloc_depth)

    def obj_tuple(self) -> tuple[int, int, int, int, int]:
        return (self.total_depth, self.worst_avg_max, self.sum_avg_max, self.card_depth, self.reloc_depth)


def _read_summary(path: Path) -> list[Row]:
    rows: list[Row] = []
    with path.open("r", newline="") as f:
        r = csv.DictReader(f)
        for d in r:
            def gi(k: str, default: int = 0) -> int:
                try:
                    return int(d.get(k, default))
                except Exception:
                    return int(default)

            rows.append(
                Row(
                    card_depth=gi("card_link_depth"),
                    reloc_depth=gi("reloc_link_depth"),
                    ok_rate_pct=gi("ok_rate_pct"),
                    avg_max_card=gi("avg_max_card_link_level"),
                    avg_max_reloc=gi("avg_max_reloc_link_level"),
                    seeds=gi("seeds"),
                    ok=gi("ok"),
                )
            )
    return rows


def _dominates(a: Row, b: Row) -> bool:
    oa = (a.total_depth, a.worst_avg_max, a.sum_avg_max)
    ob = (b.total_depth, b.worst_avg_max, b.sum_avg_max)
    return (oa[0] <= ob[0] and oa[1] <= ob[1] and oa[2] <= ob[2]) and (oa != ob)


def pareto_front(rows: list[Row]) -> list[Row]:
    front: list[Row] = []
    for i, r in enumerate(rows):
        dominated = False
        for j, other in enumerate(rows):
            if i == j:
                continue
            if _dominates(other, r):
                dominated = True
                break
        if not dominated:
            front.append(r)
    # Deterministic ordering
    front.sort(key=lambda x: x.obj_tuple())
    return front


def recommend(front: list[Row]) -> Row | None:
    if not front:
        return None
    return min(front, key=lambda x: x.obj_tuple())


def write_csv(front: list[Row], rec: Row | None, out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        fieldnames = [
            "rank",
            "card_link_depth",
            "reloc_link_depth",
            "total_depth",
            "ok_rate_pct",
            "avg_max_card_link_level",
            "avg_max_reloc_link_level",
            "worst_avg_max_link",
            "sum_avg_max_link",
            "is_recommended",
            "seeds",
            "ok",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for idx, r in enumerate(front, start=1):
            w.writerow(
                {
                    "rank": idx,
                    "card_link_depth": r.card_depth,
                    "reloc_link_depth": r.reloc_depth,
                    "total_depth": r.total_depth,
                    "ok_rate_pct": r.ok_rate_pct,
                    "avg_max_card_link_level": r.avg_max_card,
                    "avg_max_reloc_link_level": r.avg_max_reloc,
                    "worst_avg_max_link": r.worst_avg_max,
                    "sum_avg_max_link": r.sum_avg_max,
                    "is_recommended": 1 if (rec is not None and r.key == rec.key) else 0,
                    "seeds": r.seeds,
                    "ok": r.ok,
                }
            )


def write_md(front: list[Row], rec: Row | None, ok_threshold: int, out_md: Path) -> None:
    out_md.parent.mkdir(parents=True, exist_ok=True)
    with out_md.open("w", encoding="utf-8") as f:
        f.write("# Step69 Pareto selection (link depths)\n\n")
        f.write(f"Filter: ok_rate_pct >= {int(ok_threshold)}.\n\n")
        if rec is None:
            f.write("No depth-pairs satisfy the correctness filter.\n")
            return

        f.write("## Recommended depth pair\n\n")
        f.write(
            f"- card_link_depth = **{rec.card_depth}**\n"
            f"- reloc_link_depth = **{rec.reloc_depth}**\n"
            f"- total_depth = {rec.total_depth}\n"
            f"- ok_rate_pct = {rec.ok_rate_pct}% ({rec.ok}/{rec.seeds})\n"
            f"- avg_max_card_link_level = {rec.avg_max_card}\n"
            f"- avg_max_reloc_link_level = {rec.avg_max_reloc}\n\n"
        )

        f.write("## Pareto frontier\n\n")
        f.write(
            "| rank | card_depth | reloc_depth | total_depth | ok_rate | avg_max_card | avg_max_reloc | worst_avg_max | sum_avg_max |\n"
        )
        f.write("|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n")
        for i, r in enumerate(front, start=1):
            f.write(
                f"| {i} | {r.card_depth} | {r.reloc_depth} | {r.total_depth} | "
                f"{r.ok_rate_pct}% | {r.avg_max_card} | {r.avg_max_reloc} | "
                f"{r.worst_avg_max} | {r.sum_avg_max} |\n"
            )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-summary", type=Path, default=DEFAULT_IN)
    ap.add_argument("--out-csv", type=Path, default=DEFAULT_OUT_CSV)
    ap.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    ap.add_argument("--ok-threshold", type=int, default=100)
    args = ap.parse_args()

    rows = _read_summary(args.in_summary)
    filtered = [r for r in rows if int(r.ok_rate_pct) >= int(args.ok_threshold)]

    front = pareto_front(filtered)
    rec = recommend(front)

    write_csv(front, rec, args.out_csv)
    write_md(front, rec, int(args.ok_threshold), args.out_md)

    if rec is None:
        print(f"Wrote {args.out_csv} and {args.out_md}. No feasible depth-pairs.")
    else:
        print(
            f"Wrote {args.out_csv} and {args.out_md}. Recommended: "
            f"card={rec.card_depth} reloc={rec.reloc_depth} (ok_rate={rec.ok_rate_pct}%)."
        )


if __name__ == "__main__":
    main()
