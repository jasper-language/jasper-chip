#!/usr/bin/env python3
"""Export and synthesize the 256-core Jasper-GC factory SKU.

This is a tool-flow benchmark, not a PDK signoff run. It generates RTLIL and
Verilog from Amaranth, then uses Yosys generic synthesis statistics when Yosys
is available.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from amaranth.hdl import Signal
from amaranth.back import rtlil

from rtl.jasper_gc_unified_config import (
    AcceleratorMode,
    BackendMode,
    JasperGCUnifiedConfig,
    ProductProfile,
    SweepMode,
)
from rtl.jasper_gc_config import DispatchPolicy
from rtl.jasper_gc_unified_ip import JasperGCUnifiedIP


def _collect_ports(obj) -> list[Signal]:
    ports: list[Signal] = []
    seen: set[int] = set()

    def add(value) -> None:
        if isinstance(value, Signal) and id(value) not in seen:
            seen.add(id(value))
            ports.append(value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                add(item)

    for name in dir(obj):
        if name.startswith("_"):
            continue
        add(getattr(obj, name))
    return ports


def _factory_ip(cpu_cores: int, tile_count: int, accelerator: str) -> JasperGCUnifiedIP:
    accel_mode = {
        "disabled": AcceleratorMode.DISABLED,
        "inline": AcceleratorMode.INLINE,
        "external": AcceleratorMode.EXTERNAL,
    }[accelerator]
    cfg = JasperGCUnifiedConfig.from_product_profile(
        ProductProfile.SERVER,
        cpu_core_count=cpu_cores,
        tile_count=tile_count,
        lane_per_tile=2,
        backend_mode=BackendMode.MULTI_BACKEND,
        sweep_mode=SweepMode.MULTI_ENGINE,
        accelerator_mode=accel_mode,
        accelerator_enable_memory=False,
    )
    backend_cfg, _ = cfg.resolve()
    backend_cfg.dispatch_policy = DispatchPolicy.HASH_LSB
    cfg.backend_config = backend_cfg
    return JasperGCUnifiedIP(cfg)


def _run_yosys(out_dir: Path, top: str, il_path: Path, synth: bool = True) -> None:
    if shutil.which("yosys") is None:
        print("SKIP yosys: not found")
        return

    steps = [
        f"read_rtlil {il_path.name}",
        "proc",
        "opt",
        "memory_collect",
        "opt",
        f"write_verilog -noattr {top}.v",
        "stat",
    ]
    if synth:
        steps += [
            f"synth -top {top}",
            "stat",
            f"write_json {top}_synth.json",
        ]
    script = "\n".join(steps)
    script_path = out_dir / f"{top}.ys"
    log_path = out_dir / f"{top}_yosys.log"
    script_path.write_text(script + "\n", encoding="utf-8")
    with log_path.open("w", encoding="utf-8") as log:
        subprocess.check_call(["yosys", "-s", script_path.name], cwd=out_dir,
                              stdout=log, stderr=subprocess.STDOUT)
    print(f"Wrote {out_dir / (top + '.v')}")
    print(f"Wrote {log_path}")
    if synth:
        print(f"Wrote {out_dir / (top + '_synth.json')}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="build/gc_factory_256c")
    ap.add_argument("--top", default="JasperGCFactory256")
    ap.add_argument("--skip-yosys", action="store_true")
    ap.add_argument("--no-synth", action="store_true",
                    help="Run Yosys proc/opt/stat only; skip synth/ABC/json.")
    ap.add_argument("--cpu-cores", type=int, default=256)
    ap.add_argument("--tile-count", type=int, default=64)
    ap.add_argument("--accelerator", choices=["disabled", "inline", "external"],
                    default="inline")
    args = ap.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    top = args.top

    ip = _factory_ip(args.cpu_cores, args.tile_count, args.accelerator)
    ports = _collect_ports(ip)
    il_path = out_dir / f"{top}.il"
    print(f"Converting {top}: ports={len(ports)}")
    il = rtlil.convert(ip, name=top, ports=ports)
    il_path.write_text(il, encoding="utf-8")
    print(f"Wrote {il_path}")

    if not args.skip_yosys:
        _run_yosys(out_dir, top, il_path, synth=not args.no_synth)


if __name__ == "__main__":
    main()
