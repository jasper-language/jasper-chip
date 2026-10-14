# Accelerator performance benchmark: parameter sweep
import pytest
from amaranth import *; from amaranth.sim import Simulator
from rtl.jasper_gc_accelerator_config import JasperGCAcceleratorConfig, AcceleratorProfile
from rtl.jasper_gc_accelerator_ip import JasperGCAcceleratorIP

pytestmark = pytest.mark.slow

R = [0x00000000, 0x10000000, 0x20000000, 0x30000000]


def _make_config(max_outstanding, cmdq_depth, compq_depth, profile=None):
    if profile is None:
        if max_outstanding <= 4:
            p = AcceleratorProfile.ACCEL_STANDARD
        elif max_outstanding <= 8:
            p = AcceleratorProfile.ACCEL_SERVER
        else:
            p = AcceleratorProfile.ACCEL_EXTREME
    else:
        p = profile
    cfg = JasperGCAcceleratorConfig.from_profile(p)
    cfg.command_queue_depth = cmdq_depth
    cfg.completion_queue_depth = compq_depth
    cfg.max_outstanding_commands = max_outstanding
    return cfg


async def _run_bench(ctx, dut, n, eng_types, timeout=500):
    """Push n commands (push-wait), return (total_cycles, completions)."""
    ctx.set(dut.iface.comp_ready, 1); ctx.set(dut.iface.current_epoch, 1)
    await ctx.tick()
    total = 0
    for i in range(n):
        typ = eng_types[i % len(eng_types)]
        base = R[i % 4]
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, typ)
        ctx.set(dut.iface.cmd_correlation_id, i); ctx.set(dut.iface.cmd_epoch, 1)
        ctx.set(dut.iface.cmd_region_base, base)
        ctx.set(dut.iface.cmd_region_size, 64)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        cycles = 0
        for _ in range(timeout):
            cycles += 1
            if ctx.get(dut.iface.comp_valid):
                break
            await ctx.tick()
        total += cycles
    return total, n


def _report(n, total):
    avg = total / n if n else 0
    tput = n / total if total else 0
    return f"  {n} cmds, {total} cyc, {avg:.2f} cyc/cmd, {tput:.4f} cmds/cyc"


# ─── Sweep max_outstanding ────────────────────────────────────────────────

def test_bench_outstanding_1():
    cfg = _make_config(1, 8, 8, AcceleratorProfile.ACCEL_LITE)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, mem_read_latency=4, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        t, n = await _run_bench(ctx, dut, 8, [0, 1])
        print(_report(n, t))
    sim.add_testbench(proc); sim.run()

def test_bench_outstanding_2():
    cfg = _make_config(2, 8, 8)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, mem_read_latency=4, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        t, n = await _run_bench(ctx, dut, 8, [0, 1])
        print(_report(n, t))
    sim.add_testbench(proc); sim.run()

def test_bench_outstanding_4():
    cfg = _make_config(4, 8, 8)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, mem_read_latency=4, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        t, n = await _run_bench(ctx, dut, 12, [0, 1, 2, 3])
        print(_report(n, t))
    sim.add_testbench(proc); sim.run()

def test_bench_outstanding_8():
    cfg = _make_config(8, 16, 16)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, mem_read_latency=4, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        t, n = await _run_bench(ctx, dut, 16, [0, 1, 2, 3])
        print(_report(n, t))
    sim.add_testbench(proc); sim.run()

# ─── Sweep mem_read_latency ───────────────────────────────────────────────

def test_bench_latency_2():
    cfg = _make_config(4, 8, 8)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, mem_read_latency=2, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        t, n = await _run_bench(ctx, dut, 12, [0, 1, 2, 3])
        print(_report(n, t))
    sim.add_testbench(proc); sim.run()

def test_bench_latency_8():
    cfg = _make_config(4, 8, 8)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, mem_read_latency=8, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        t, n = await _run_bench(ctx, dut, 12, [0, 1, 2, 3])
        print(_report(n, t))
    sim.add_testbench(proc); sim.run()

# ─── Sweep queue depth ────────────────────────────────────────────────────

def test_bench_queue_4():
    cfg = _make_config(2, 4, 4)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, mem_read_latency=4, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        t, n = await _run_bench(ctx, dut, 8, [0, 1])
        print(_report(n, t))
    sim.add_testbench(proc); sim.run()

def test_bench_queue_16():
    cfg = _make_config(4, 16, 16)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, mem_read_latency=4, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        t, n = await _run_bench(ctx, dut, 12, [0, 1, 2, 3])
        print(_report(n, t))
    sim.add_testbench(proc); sim.run()

# ─── ChipletLink latency sweep ────────────────────────────────────────────

def test_bench_chiplet_latency_2():
    cfg = _make_config(2, 8, 8)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True,
                                memory_model="chiplet_link", link_latency=2, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        t, n = await _run_bench(ctx, dut, 8, [0, 1])
        print(_report(n, t))
    sim.add_testbench(proc); sim.run()

def test_bench_chiplet_latency_8():
    cfg = _make_config(2, 8, 8)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True,
                                memory_model="chiplet_link", link_latency=8, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        t, n = await _run_bench(ctx, dut, 8, [0, 1])
        print(_report(n, t))
    sim.add_testbench(proc); sim.run()

# ─── Per-engine memory ────────────────────────────────────────────────────

def test_bench_per_engine():
    cfg = _make_config(4, 8, 8)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, per_engine_memory=True,
                                mem_read_latency=4, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        t, n = await _run_bench(ctx, dut, 12, [0, 1, 2, 3])
        print(_report(n, t))
    sim.add_testbench(proc); sim.run()

# ─── Counting mode baseline ───────────────────────────────────────────────

def test_bench_counting():
    cfg = _make_config(4, 8, 8)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=False, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        t, n = await _run_bench(ctx, dut, 12, [0, 1, 2, 3])
        print(_report(n, t))
    sim.add_testbench(proc); sim.run()
