# -*- coding: utf-8 -*-
"""Step65: CLI runner for the randomized dual-link fuzz regression.

Usage:
  python -m tools.step65_fuzz_run --seed 0xC0FFEE --cycles 1000
"""

from __future__ import annotations

import argparse
import json

from tests.test_step65_randomized_dual_link_fuzz import FuzzCfg, run_fuzz


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=lambda s: int(s, 0), default=0xC0FFEE)
    ap.add_argument("--cycles", type=int, default=400)
    ap.add_argument("--drain-cycles", type=int, default=260)
    ap.add_argument("--card-depth", type=int, default=2)
    ap.add_argument("--reloc-depth", type=int, default=2)
    ap.add_argument("--queries", type=int, default=8)
    ap.add_argument("--json", action="store_true", help="emit a single JSON line with stats")
    args = ap.parse_args()

    cfg = FuzzCfg(
        seed=args.seed,
        cycles=args.cycles,
        drain_cycles=args.drain_cycles,
        card_link_depth=args.card_depth,
        reloc_link_depth=args.reloc_depth,
        query_count=args.queries,
    )
    if args.json:
        st = run_fuzz(cfg, return_stats=True)
        assert st is not None
        print(json.dumps({k: int(v) for k, v in st.items()}, sort_keys=True))
    else:
        run_fuzz(cfg)
        print("OK:", cfg)


if __name__ == "__main__":
    main()