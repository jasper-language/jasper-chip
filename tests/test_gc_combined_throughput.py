# tests/test_gc_combined_throughput.py
# Measure combined throughput of: multi-backend gateway pipeline + accelerator.
import pytest
from amaranth import *
from amaranth.sim import Simulator
from rtl.gc_multi_backend_cluster import GCMultiBackendCluster
from rtl.jasper_gc_accelerator_ip import JasperGCAcceleratorIP
from rtl.jasper_gc_accelerator_config import JasperGCAcceleratorConfig, AcceleratorProfile
import sys

pytestmark = pytest.mark.slow

# ── Multi-backend interface ──────────────────────────────────────
MB_TYPES = [("1L×1", 1, 1), ("2L×1", 1, 2), ("1L×2", 2, 1), ("2L×2", 2, 2)]

def run_multi_backend(tile_count, lane_per_tile, cycles=400):
    """Measure multi-backend event acceptance rate."""
    dut = GCMultiBackendCluster(
        tile_count=tile_count, lane_per_tile=lane_per_tile,
        metadata_cache_size=256, metadata_ways=2)
    sim = Simulator(dut); sim.add_clock(1e-6)
    result = {}
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 0); ctx.set(dut.fill_ready, 1)
        total_lanes = tile_count * lane_per_tile
        for p in range(total_lanes):
            ctx.set(dut.out_ready, 1)
        # Warmup
        for _ in range(8):
            ctx.set(dut.in_valid, 1); ctx.set(dut.in_addr, 0x1000)
            ctx.set(dut.in_type, 0); ctx.set(dut.fill_ready, 1)
            await ctx.tick(); ctx.set(dut.in_valid, 0); await ctx.tick()
            for _ in range(4):
                ctx.set(dut.out_ready, 1); await ctx.tick()
        # Flush warmup responses
        for _ in range(16):
            ctx.set(dut.out_ready, 1); await ctx.tick()
            if not ctx.get(dut.busy): break
        # Stress: fire events as fast as accepted
        accepted = 0; outputs = 0
        addrs = [0x1000 + (i * 0x40) for i in range(32)]
        for i in range(cycles):
            a = addrs[i % len(addrs)]
            ctx.set(dut.in_valid, 1); ctx.set(dut.in_addr, a)
            ctx.set(dut.in_type, i % 3); ctx.set(dut.in_tag, i & 0xFF)
            ctx.set(dut.in_epoch, 0)
            ctx.set(dut.out_ready, 1); ctx.set(dut.fill_ready, 1)
            await ctx.tick()
            if ctx.get(dut.in_ready): accepted += 1
            if ctx.get(dut.out_valid): outputs += 1
        ctx.set(dut.in_valid, 0)
        for _ in range(32):
            ctx.set(dut.out_ready, 1); await ctx.tick()
            if ctx.get(dut.out_valid): outputs += 1
            if not ctx.get(dut.busy) and not ctx.get(dut.out_valid): break
        result["rate"] = accepted / cycles
        result["accepted"] = accepted
        result["outputs"] = outputs
    sim.add_testbench(proc); sim.run()
    return result

# ── Accelerator interface ─────────────────────────────────────────
def run_accelerator(config, enable_memory, mem_lat, cycles=400):
    """Measure accelerator command acceptance rate."""
    dut = JasperGCAcceleratorIP(
        config=config, enable_memory=enable_memory,
        mem_read_latency=mem_lat, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    result = {}
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        await ctx.tick()
        # Stress: send commands round-robin through types
        sent = 0; completed = 0
        bases = [0x00000000, 0x10000000, 0x20000000, 0x30000000]
        for i in range(cycles):
            typ = i % 4
            ctx.set(dut.iface.cmd_type, typ)
            ctx.set(dut.iface.cmd_correlation_id, i)
            ctx.set(dut.iface.cmd_epoch, 1)
            ctx.set(dut.iface.cmd_region_base, bases[typ])
            ctx.set(dut.iface.cmd_region_size, 64)
            ctx.set(dut.iface.cmd_valid, 1)
            await ctx.tick()
            if ctx.get(dut.iface.cmd_ready):
                sent += 1
            ctx.set(dut.iface.cmd_valid, 0)
            if ctx.get(dut.iface.comp_valid):
                ctx.set(dut.iface.comp_ready, 1)
                completed += 1
                await ctx.tick()
                ctx.set(dut.iface.comp_ready, 1)
            else:
                ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.cmd_valid, 0)
        # Drain completions
        for _ in range(cycles):
            ctx.set(dut.iface.comp_ready, 1); await ctx.tick()
            if ctx.get(dut.iface.comp_valid):
                completed += 1
            if not ctx.get(dut.iface.cmd_ready):
                pass
        rate = sent / cycles if cycles else 0
        comp_rate = completed / cycles if cycles else 0
        result["send_rate"] = rate
        result["comp_rate"] = comp_rate
        result["sent"] = sent
        result["completed"] = completed
    sim.add_testbench(proc); sim.run()
    return result

# ── Combined test ─────────────────────────────────────────────────
def test_multi_backend_alone():
    """Measure all multi-backend configurations."""
    print("  [Multi-backend event throughput]")
    for label, tc, lp in MB_TYPES:
        r = run_multi_backend(tc, lp)
        print(f"    {label:6s}: {r['accepted']:3d}/{400} events accepted "
              f"= {r['rate']:.4f} evt/cyc  out={r['outputs']}")
    print()

def test_accelerator_alone():
    """Measure accelerator throughput in various modes."""
    print("  [Accelerator command throughput]")
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_STANDARD)
    # Counting only (no memory)
    r = run_accelerator(cfg, enable_memory=False, mem_lat=0)
    print(f"    Counting-only: sent={r['sent']:3d}/{400} completed={r['completed']:3d} "
          f"send_rate={r['send_rate']:.4f} cmd/cyc")
    # With memory
    for lat in [0, 4]:
        r = run_accelerator(cfg, enable_memory=True, mem_lat=lat)
        print(f"    Memory lat={lat}: sent={r['sent']:3d}/{400} completed={r['completed']:3d} "
              f"send_rate={r['send_rate']:.4f} cmd/cyc")
    print()

def test_combined_ceiling():
    """Combined throughput ceiling: multi-backend + accelerator."""
    print("  [Combined ceiling: multi-backend + accelerator]")
    # Best-case multi-backend
    mb_label, mb_tc, mb_lp = ("2L×2", 2, 2)
    mb_r = run_multi_backend(mb_tc, mb_lp)
    mb_rate = mb_r["rate"]
    # Accelerator profiles
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_STANDARD)
    acc_profiles = [
        ("Counting-only", run_accelerator(cfg, False, 0)),
        ("Memory lat=0",  run_accelerator(cfg, True, 0)),
        ("Memory lat=4",  run_accelerator(cfg, True, 4)),
    ]
    print(f"    {'Pathway':30s} {'Throughput':>12s}")
    print(f"    {'─'*42}")
    print(f"    {'Multi-backend ' + mb_label:30s} {mb_rate:>12.4f} evt/cyc")
    for label, r in acc_profiles:
        print(f"    {'Accelerator ' + label:30s} {r['send_rate']:>12.4f} cmd/cyc")
    print()
    print(f"    {'Combined (MB + Counting)':30s} {mb_rate + acc_profiles[0][1]['send_rate']:>12.4f} total/cyc")
    print(f"    {'Combined (MB + Mem lat=4)':30s} {mb_rate + acc_profiles[2][1]['send_rate']:>12.4f} total/cyc")
    print()

def test_gc_chip_comparison():
    """Compare combined path vs GCSweepCoProc alone."""
    print("  [GC chip baseline (from earlier benchmarks)]")
    gc_rates = {"lat=0": 0.3333, "lat=2": 0.1667, "lat=4": 0.1250, "lat=8": 0.0833}
    mb_label, mb_tc, mb_lp = ("2L×2", 2, 2)
    mb_r = run_multi_backend(mb_tc, mb_lp)
    mb_rate = mb_r["rate"]
    print(f"    {'Config':30s} {'Rate (total/cyc)':>16s}")
    print(f"    {'─'*46}")
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_STANDARD)
    acc_r = run_accelerator(cfg, False, 0)
    acc_rate = acc_r["send_rate"]
    print(f"    {'Multi-backend ' + mb_label:30s} {mb_rate:>16.4f}")
    for gc_lat, gc_rate in gc_rates.items():
        print(f"    {'GC chip ' + gc_lat:30s} {gc_rate:>16.4f}")
    print(f"    {'Accelerator counting':30s} {acc_rate:>16.4f}")
    print()
    print(f"  Combined pathways (additive):")
    for gc_lat, gc_rate in gc_rates.items():
        three = mb_rate + gc_rate + acc_rate
        print(f"    {mb_label} + GC {gc_lat} + Acc: {three:.4f} total/cyc")
    print()
    print(f"  Headroom vs GC chip at lat=0 ({list(gc_rates.values())[0]:.4f}):")
    for gc_lat, gc_rate in gc_rates.items():
        three = mb_rate + gc_rate + acc_rate
        ratio = three / 0.3333
        print(f"    {mb_label} + GC {gc_lat} + Acc: {three:.4f} = {ratio:.1f}× baseline")


if __name__ == "__main__":
    print("=" * 60)
    print("Combined Throughput: Multi-Backend + Accelerator + GC Chip")
    print("=" * 60)
    print()
    test_multi_backend_alone()
    test_accelerator_alone()
    test_combined_ceiling()
    test_gc_chip_comparison()
    print("=== Done ===")
