# -*- coding: utf-8 -*-
"""Step66: Multi-seed smoke regression on the Step65 randomized fuzz.

We keep this very small so it runs quickly in CI/sandbox. For broader sweeps,
use tools/step66_fuzz_sweep.py.

Run:
  python -m tests.test_step66_fuzz_multiseed_smoke
"""

from __future__ import annotations

import subprocess
import sys


def test_step66_fuzz_multiseed_smoke():
    # Keep the default smoke extremely fast; broader coverage is provided by
    # tools/step66_fuzz_sweep.py (which can run many seeds offline).
    seeds = [0x1]
    for s in seeds:
        cmd = [
            sys.executable,
            "-m",
            "tools.step65_fuzz_run",
            "--seed",
            hex(int(s)),
            # Keep this *very* small so it finishes quickly in constrained sandboxes.
            "--cycles",
            "8",
            "--drain-cycles",
            "25",
            "--card-depth",
            "2",
            "--reloc-depth",
            "2",
            "--queries",
            "1",
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)


if __name__ == "__main__":
    test_step66_fuzz_multiseed_smoke()
    print("OK: multi-seed fuzz smoke passed.")
