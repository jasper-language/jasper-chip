#!/usr/bin/env python3
"""PPA matrix for the Jasper-GC unified design.

This is an RTL-informed estimate, not signoff power. Throughput is computed from
the selected topology and clock target; area/power use a transparent
node-scaling model until synthesis libraries and switching activity are
available.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProductTier:
    name: str
    cpu_cores: int
    cpu_freq_ghz: float
    gc_ip_freq_ghz: float
    event_rate_per_cpu_cycle: float
    lane_per_backend: int
    backend_count: int
    accelerator: str
    sweep: str
    efficiency: float
    accel_boost: float
    rtl_status: str


@dataclass(frozen=True)
class ProcessNode:
    name: str
    nm: int
    voltage: float
    leakage_mw_per_mm2: float


PRODUCT_TIERS = [
    ProductTier("MCU", 1, 0.40, 0.40, 0.015, 1, 1,
                "disabled", "standard", 0.72, 0.00, "rtl"),
    ProductTier("EDGE", 4, 1.50, 1.20, 0.020, 2, 2,
                "optional_inline", "pipelined", 0.68, 0.08, "rtl"),
    ProductTier("MOBILE", 8, 3.20, 1.80, 0.025, 2, 8,
                "inline", "pipelined", 0.64, 0.15, "rtl"),
    ProductTier("LAPTOP", 16, 4.20, 2.20, 0.025, 2, 16,
                "inline", "multi_engine", 0.60, 0.20, "rtl"),
    ProductTier("DESKTOP", 32, 5.20, 2.60, 0.030, 2, 32,
                "inline_or_external", "multi_engine", 0.56, 0.24, "scaled"),
    ProductTier("SERVER", 64, 3.20, 2.40, 0.035, 2, 64,
                "external", "multi_engine", 0.50, 0.30, "scaled"),
]


PROCESS_NODES = [
    ProcessNode("12nm", 12, 0.80, 18.0),
    ProcessNode("10nm", 10, 0.75, 20.0),
    ProcessNode("7nm", 7, 0.70, 26.0),
    ProcessNode("5nm", 5, 0.65, 34.0),
    ProcessNode("3nm", 3, 0.60, 48.0),
]


def _area_scale(node: ProcessNode) -> float:
    return (node.nm / 12.0) ** 2


def _cap_scale(node: ProcessNode) -> float:
    return 0.45 + 0.55 * _area_scale(node)


def estimate_row(tier: ProductTier, node: ProcessNode) -> dict[str, object]:
    lanes = tier.lane_per_backend * tier.backend_count
    backend_evt_per_cycle = lanes * tier.efficiency
    backend_theory_evt_per_cycle = backend_evt_per_cycle * (1.0 + tier.accel_boost)
    ingress_evt_per_cycle = min(tier.cpu_cores, lanes)
    current_top_evt_per_cycle = min(ingress_evt_per_cycle, backend_theory_evt_per_cycle)
    backend_theory_mev_s = backend_theory_evt_per_cycle * tier.gc_ip_freq_ghz * 1000.0
    current_top_mev_s = current_top_evt_per_cycle * tier.gc_ip_freq_ghz * 1000.0
    cpu_gc_event_demand_mev_s = (
        tier.cpu_cores * tier.cpu_freq_ghz * tier.event_rate_per_cpu_cycle * 1000.0)

    base_backend_area_12 = 0.030
    base_accel_area_12 = 0.180 if tier.accelerator != "disabled" else 0.0
    fabric_area_12 = 0.010 * tier.backend_count * max(1, tier.backend_count).bit_length()
    control_area_12 = 0.040
    area_12 = (
        control_area_12
        + tier.backend_count * tier.lane_per_backend * base_backend_area_12
        + fabric_area_12
        + base_accel_area_12 * max(1, tier.backend_count / 8)
    )
    area_mm2 = area_12 * _area_scale(node)

    active_units = tier.backend_count * tier.lane_per_backend
    accel_units = 0 if tier.accelerator == "disabled" else max(1.0, tier.backend_count / 8)
    dynamic_mw = (
        (4.8 * active_units + 18.0 * accel_units)
        * _cap_scale(node)
        * (node.voltage / 0.80) ** 2
        * (tier.gc_ip_freq_ghz / 0.80)
        * min(1.0, tier.efficiency + tier.accel_boost)
    )
    leakage_mw = area_mm2 * node.leakage_mw_per_mm2
    power_mw = dynamic_mw + leakage_mw

    return {
        "tier": tier.name,
        "node": node.name,
        "cpu_cores": tier.cpu_cores,
        "cpu_freq_ghz": round(tier.cpu_freq_ghz, 2),
        "gc_ip_freq_ghz": round(tier.gc_ip_freq_ghz, 2),
        "lanes": lanes,
        "backends": tier.backend_count,
        "accelerator": tier.accelerator,
        "sweep": tier.sweep,
        "rtl_status": tier.rtl_status,
        "cpu_gc_event_demand_mev_s": round(cpu_gc_event_demand_mev_s, 1),
        "backend_theory_evt_per_cycle": round(backend_theory_evt_per_cycle, 3),
        "ingress_evt_per_cycle": round(ingress_evt_per_cycle, 3),
        "current_top_evt_per_cycle": round(current_top_evt_per_cycle, 3),
        "backend_theory_mev_s": round(backend_theory_mev_s, 1),
        "current_top_mev_s": round(current_top_mev_s, 1),
        "headroom_vs_cpu_demand": round(
            current_top_mev_s / cpu_gc_event_demand_mev_s, 2),
        "area_mm2_est": round(area_mm2, 3),
        "power_mw_est": round(power_mw, 1),
        "backend_theory_mev_s_per_w": round(backend_theory_mev_s / (power_mw / 1000.0), 1),
        "current_top_mev_s_per_w": round(current_top_mev_s / (power_mw / 1000.0), 1),
    }


def build_matrix() -> list[dict[str, object]]:
    return [
        estimate_row(tier, node)
        for tier in PRODUCT_TIERS
        for node in PROCESS_NODES
    ]


def write_csv(rows: list[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(rows: list[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "tier", "node", "cpu_cores", "cpu_freq_ghz", "gc_ip_freq_ghz",
        "lanes", "backends", "accelerator", "sweep", "rtl_status",
        "cpu_gc_event_demand_mev_s", "backend_theory_evt_per_cycle",
        "ingress_evt_per_cycle", "current_top_evt_per_cycle", "backend_theory_mev_s",
        "current_top_mev_s", "headroom_vs_cpu_demand", "area_mm2_est", "power_mw_est",
        "backend_theory_mev_s_per_w", "current_top_mev_s_per_w",
    ]
    lines = [
        "# Jasper-GC PPA Matrix",
        "",
        "This report is generated by `tools/gc_product_ppa_matrix.py`.",
        "",
        "CPU core count is the CPU core count, not a GC internal engine count. "
        "`cpu_freq_ghz` is a 2026-era representative CPU frequency; "
        "`gc_ip_freq_ghz` is the GC clock assumption and may be a separate domain. "
        "Power and area are estimates from a transparent node-scaling model, not signoff values. "
        "`rtl` rows are within the currently validated `tile_count <= 16` RTL envelope; "
        "`scaled` rows extrapolate the same architecture to 32/64 backends.",
        "",
        "`backend_theory_*` is the target backend capacity if the frontend can feed all backends. "
        "`ingress_evt_per_cycle` is the multi-core frontend fabric input capacity after adding "
        "per-CPU event ports. `current_top_*` is limited by both ingress and backend capacity. "
        "MCU and EDGE multi-core ingress paths have RTL smoke coverage; DESKTOP/SERVER remain "
        "scaled until tile_count > 16 is enabled.",
        "",
        "|" + "|".join(cols) + "|",
        "|" + "|".join(["---"] * len(cols)) + "|",
    ]
    for row in rows:
        lines.append("|" + "|".join(str(row[c]) for c in cols) + "|")
    lines.append("")
    path.write_text("\n".join(lines))


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    rows = build_matrix()
    write_csv(rows, repo / "reports/gc_product_ppa_matrix.csv")
    write_markdown(rows, repo / "reports/gc_product_ppa_matrix.md")
    print(f"wrote {len(rows)} rows")


if __name__ == "__main__":
    main()
