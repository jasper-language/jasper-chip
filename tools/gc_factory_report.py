#!/usr/bin/env python3
"""Summarize Jasper-GC factory synthesis and 5nm throughput estimates."""

from __future__ import annotations

import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


RUNS = [
    ("16t_domain_full", ROOT / "build/gc_domain_64c16t/JasperGCDomain64c16t_yosys.log",
     ROOT / "build/gc_domain_64c16t/JasperGCDomain64c16t.il",
     ROOT / "build/gc_domain_64c16t/JasperGCDomain64c16t.v"),
    ("32t_domain_stat", ROOT / "build/gc_domain_128c32t/JasperGCDomain128c32t_yosys.log",
     ROOT / "build/gc_domain_128c32t/JasperGCDomain128c32t.il",
     ROOT / "build/gc_domain_128c32t/JasperGCDomain128c32t.v"),
    ("64t_factory_stat", ROOT / "build/gc_factory_256c64t/JasperGCFactory256c64t_yosys.log",
     ROOT / "build/gc_factory_256c64t/JasperGCFactory256c64t.il",
     ROOT / "build/gc_factory_256c64t/JasperGCFactory256c64t.v"),
]


def _mb(path: Path) -> str:
    if not path.exists():
        return "n/a"
    return f"{path.stat().st_size / 1024 / 1024:.1f}"


def _extract_stat(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    txt = path.read_text(errors="ignore")
    idx = txt.rfind("Count including submodules")
    if idx >= 0:
        txt = txt[idx:]
    patterns = {
        "wires": r"\n\s*(\d+) wires",
        "wire_bits": r"\n\s*(\d+) wire bits",
        "ports": r"\n\s*(\d+) ports",
        "port_bits": r"\n\s*(\d+) port bits",
        "cells": r"\n\s*(\d+) cells",
        "mem_mb": r"MEM:\s*([0-9.]+) MB peak",
        "time_s": r"time:\s*([0-9.]+)s",
    }
    out: dict[str, str] = {}
    for key, pat in patterns.items():
        matches = re.findall(pat, txt)
        out[key] = matches[-1] if matches else "n/a"
    return out


def main() -> None:
    report = ROOT / "reports/gc_factory_5nm_5p1ghz_synth.md"
    report.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Jasper-GC Factory 5nm / 5.1GHz Synthesis Snapshot",
        "",
        "This is a generic Yosys/Verilator snapshot, not PDK signoff STA.",
        "",
        "## Tool Availability",
        "",
        f"- yosys: `{shutil.which('yosys') or 'not found'}`",
        f"- verilator: `{shutil.which('verilator') or 'not found'}`",
        f"- openroad/openlane/sta: `{shutil.which('openroad') or shutil.which('openlane') or shutil.which('sta') or 'not found'}`",
        "- 5nm liberty/SDC: `not found in repo`",
        "",
        "## Synthesis Runs",
        "",
        "|run|wires|wire_bits|ports|port_bits|cells|yosys_time_s|peak_mem_mb|rtlil_mb|verilog_mb|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for name, log, il, v in RUNS:
        s = _extract_stat(log)
        lines.append(
            f"|{name}|{s.get('wires','n/a')}|{s.get('wire_bits','n/a')}|"
            f"{s.get('ports','n/a')}|{s.get('port_bits','n/a')}|{s.get('cells','n/a')}|"
            f"{s.get('time_s','n/a')}|{s.get('mem_mb','n/a')}|{_mb(il)}|{_mb(v)}|"
        )

    freq = 5.1
    stable_epc = 132
    aggressive_epc = 256
    lines += [
        "",
        "## 5nm / 5.1GHz Throughput Model",
        "",
        f"- Stable RTL point: `{stable_epc} events/cycle * {freq}GHz = {stable_epc * freq * 1000:.0f} MEv/s`",
        f"- Aggressive ingress point: `{aggressive_epc} events/cycle * {freq}GHz = {aggressive_epc * freq * 1000:.0f} MEv/s`",
        "",
        "|event_rate_per_core_cycle|cpu_demand_mev_s|stable_headroom|aggressive_headroom|",
        "|---:|---:|---:|---:|",
    ]
    for rate in (0.05, 0.10, 0.20):
        demand = 256 * freq * rate * 1000
        stable = stable_epc * freq * 1000
        aggressive = aggressive_epc * freq * 1000
        lines.append(f"|{rate:.2f}|{demand:.0f}|{stable / demand:.2f}x|{aggressive / demand:.2f}x|")

    lines += [
        "",
        "## Timing Status",
        "",
        "- Verilator lint passes for the generated 16t domain Verilog after suppressing generated-netlist width/priority warnings.",
        "- Yosys `ltp -noff` on the flattened 16t synthesized domain reports a longest topological path length of `101` generic gates, rooted in accelerator compact-engine control (`accel.ce`).",
        "- True 5.1GHz STA is blocked until a 5nm standard-cell liberty, wire RC assumptions, and SDC constraints are available.",
        "- Ready-aware `HYBRID` dispatch is constrained out of large synthesis paths; large profiles use static `HASH_LSB` routing.",
        "- Large ingress groups use a registered one-entry dispatch buffer/credit point; the 256c/64t smoke remains at `132 events/cycle` after this register cut.",
        "",
    ]
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {report}")


if __name__ == "__main__":
    main()
