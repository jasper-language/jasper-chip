# -*- coding: utf-8 -*-
"""Step66: Batch fuzz sweep runner.

Runs N random seeds; prints a repro command on first failure.

Usage:
  python -m tools.step66_fuzz_sweep --count 50 --cycles 300
"""

from __future__ import annotations

import argparse
import random
import subprocess
import sys

from tests.test_step65_randomized_dual_link_fuzz import FuzzCfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--cycles", type=int, default=300)
    ap.add_argument("--drain-cycles", type=int, default=260)
    ap.add_argument("--seed0", type=lambda s: int(s, 0), default=0x20260104)
    ap.add_argument("--card-depth", type=int, default=2)
    ap.add_argument("--reloc-depth", type=int, default=2)
    ap.add_argument("--queries", type=int, default=3)
    args = ap.parse_args()

    rng = random.Random(args.seed0)
    for i in range(args.count):
        seed = rng.getrandbits(32)
        cfg = FuzzCfg(
            seed=seed,
            cycles=args.cycles,
            card_link_depth=args.card_depth,
            reloc_link_depth=args.reloc_depth,
            query_count=args.queries,
        )
        # NOTE: Amaranth's pysim can hang if we run multiple Simulator instances in one Python process.
        # Run each seed in a fresh process.
        cmd = [
            sys.executable,
            "-m",
            "tools.step65_fuzz_run",
            "--seed",
            f"0x{cfg.seed:08x}",
            "--cycles",
            str(cfg.cycles),
            "--drain-cycles",
            str(int(args.drain_cycles)),
            "--card-depth",
            str(cfg.card_link_depth),
            "--reloc-depth",
            str(cfg.reloc_link_depth),
            "--queries",
            str(cfg.query_count),
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
            print(f"[{i+1}/{args.count}] PASS seed=0x{seed:08x}")
        except subprocess.CalledProcessError as e:
            print(f"[{i+1}/{args.count}] FAIL seed=0x{seed:08x}: exit={e.returncode}", file=sys.stderr)
            print("Repro:", file=sys.stderr)
            print(f"  python -m tools.step65_fuzz_run --seed 0x{seed:08x} --cycles {args.cycles} "
                  f"--card-depth {args.card_depth} --reloc-depth {args.reloc_depth} --queries {args.queries}", file=sys.stderr)
            raise


if __name__ == "__main__":
    main()