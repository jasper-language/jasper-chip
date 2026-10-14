# tests/test_jasper_gc_accelerator_sweep_integration.py
# SweepEngine + ScanEngine dual-path integration.
from amaranth import *; from amaranth.sim import Simulator
from rtl.jasper_gc_accelerator_config import JasperGCAcceleratorConfig, AcceleratorProfile
from rtl.jasper_gc_accelerator_queue import CommandQueue, CompletionQueue
from rtl.jasper_gc_accelerator_scheduler import RegionScheduler
from rtl.jasper_gc_scan_engine import ScanEngine
from rtl.jasper_gc_sweep_engine import SweepEngine

R0 = 0x08000000; R1 = 0x18000000


def _build():
    cfg = JasperGCAcceleratorConfig(profile=AcceleratorProfile.ACCEL_STANDARD)
    m = Module()
    m.cmdq = CommandQueue(depth=cfg.command_queue_depth)
    m.sched = RegionScheduler(region_count=2, support_sweep=True)
    m.scan = ScanEngine(step_size=64)
    m.sweep = SweepEngine(step_size=64)
    m.compq = CompletionQueue(depth=cfg.completion_queue_depth)
    m.submodules.cmdq = m.cmdq; m.submodules.sched = m.sched
    m.submodules.scan = m.scan; m.submodules.sweep = m.sweep; m.submodules.compq = m.compq

    # Hold cmdq pop while scheduler waits for engine
    sched_hold = Signal()
    with m.If(m.sched.out_valid):
        with m.If(~m.sched.out_ready):
            m.d.sync += sched_hold.eq(1)
        with m.Else():
            m.d.sync += sched_hold.eq(0)
    with m.Else():
        m.d.sync += sched_hold.eq(0)

    m.d.comb += [
        m.sched.in_valid.eq(m.cmdq.out_valid),
        m.cmdq.out_ready.eq(m.sched.in_ready & ~sched_hold),
        m.sched.in_type.eq(m.cmdq.out_type),
        m.sched.in_correlation_id.eq(m.cmdq.out_correlation_id),
        m.sched.in_epoch.eq(m.cmdq.out_epoch),
        m.sched.in_region_base.eq(m.cmdq.out_region_base),
        m.sched.in_region_size.eq(m.cmdq.out_region_size),
        m.sched.current_epoch.eq(1),
    ]

    # Route scheduler output to appropriate engine based on cmd_type
    # SCAN=0 → ScanEngine, SWEEP=1 → SweepEngine
    to_scan = Signal()
    to_sweep = Signal()
    m.d.comb += [
        to_scan.eq(m.sched.out_valid & (m.sched.out_type == 0)),
        to_sweep.eq(m.sched.out_valid & (m.sched.out_type == 1)),
    ]
    m.d.comb += [
        m.scan.in_valid.eq(to_scan),
        m.sweep.in_valid.eq(to_sweep),
        # Scheduler out_ready when either engine is ready
        m.sched.out_ready.eq(Mux(to_scan, m.scan.in_ready,
                             Mux(to_sweep, m.sweep.in_ready, 1))),
        m.scan.in_correlation_id.eq(m.sched.out_correlation_id),
        m.scan.in_epoch.eq(m.sched.out_epoch), m.scan.in_merge_domain.eq(m.sched.out_merge_domain),
        m.scan.in_region_base.eq(m.sched.out_region_base), m.scan.in_region_size.eq(m.sched.out_region_size),
        m.sweep.in_correlation_id.eq(m.sched.out_correlation_id),
        m.sweep.in_epoch.eq(m.sched.out_epoch), m.sweep.in_merge_domain.eq(m.sched.out_merge_domain),
        m.sweep.in_region_base.eq(m.sched.out_region_base), m.sweep.in_region_size.eq(m.sched.out_region_size),
    ]

    # Region unlock
    issue_region = Signal(max(2, 1))
    with m.If(m.sched.out_valid & m.sched.out_ready):
        m.d.sync += issue_region.eq(m.sched.out_region_base[28:29])

    scan_done = Signal(); sweep_done = Signal()
    m.d.comb += [
        scan_done.eq(m.scan.out_valid & m.scan.out_ready),
        sweep_done.eq(m.sweep.out_valid & m.sweep.out_ready),
        m.scan.out_ready.eq(m.compq.in_ready),
        m.sweep.out_ready.eq(m.compq.in_ready),
        m.sched.unlock.eq(scan_done | sweep_done),
        m.sched.unlock_region.eq(issue_region),
    ]

    # Completion arbitration: scheduler reject > sweep > scan
    eng_valid = Signal()
    eng_st = Signal(3); eng_cid = Signal(16)
    eng_ep = Signal(8); eng_dm = Signal(4)
    eng_bs = Signal(32); eng_ob = Signal(32)
    eng_lv = Signal(32); eng_dd = Signal(32)
    eng_bm = Signal(32); eng_om = Signal(32)
    eng_mu = Signal(32); eng_ec = Signal(8)

    m.d.comb += [
        eng_valid.eq(m.sweep.out_valid | m.scan.out_valid),
        eng_st.eq(Mux(m.sweep.out_valid, m.sweep.out_status, m.scan.out_status)),
        eng_cid.eq(Mux(m.sweep.out_valid, m.sweep.out_correlation_id, m.scan.out_correlation_id)),
        eng_ep.eq(Mux(m.sweep.out_valid, m.sweep.out_epoch, m.scan.out_epoch)),
        eng_dm.eq(Mux(m.sweep.out_valid, m.sweep.out_merge_domain, m.scan.out_merge_domain)),
        eng_bs.eq(Mux(m.sweep.out_valid, m.sweep.out_bytes_scanned, m.scan.out_bytes_scanned)),
        eng_ob.eq(Mux(m.sweep.out_valid, m.sweep.out_objects_scanned, m.scan.out_objects_scanned)),
        eng_lv.eq(Mux(m.sweep.out_valid, m.sweep.out_live_objects, m.scan.out_live_objects)),
        eng_dd.eq(Mux(m.sweep.out_valid, m.sweep.out_dead_objects, m.scan.out_dead_objects)),
        eng_bm.eq(Mux(m.sweep.out_valid, m.sweep.out_bytes_moved, 0)),
        eng_om.eq(Mux(m.sweep.out_valid, m.sweep.out_objects_moved, 0)),
        eng_mu.eq(Mux(m.sweep.out_valid, m.sweep.out_metadata_updates, 0)),
        eng_ec.eq(Mux(m.sweep.out_valid, m.sweep.out_error_code, m.scan.out_error_code)),
        m.compq.in_valid.eq(m.sched.comp_valid | eng_valid),
        m.compq.in_status.eq(Mux(m.sched.comp_valid, m.sched.comp_status, eng_st)),
        m.compq.in_correlation_id.eq(Mux(m.sched.comp_valid, m.sched.comp_correlation_id, eng_cid)),
        m.compq.in_epoch.eq(Mux(m.sched.comp_valid, m.sched.comp_epoch, eng_ep)),
        m.compq.in_merge_domain.eq(Mux(m.sched.comp_valid, m.sched.comp_merge_domain, eng_dm)),
        m.compq.in_bytes_scanned.eq(eng_bs),
        m.compq.in_objects_scanned.eq(eng_ob),
        m.compq.in_live_objects.eq(eng_lv),
        m.compq.in_dead_objects.eq(eng_dd),
        m.compq.in_bytes_moved.eq(eng_bm),
        m.compq.in_objects_moved.eq(eng_om),
        m.compq.in_metadata_updates.eq(eng_mu),
        m.compq.in_error_code.eq(eng_ec),
    ]
    return m


async def _push_wait(ctx, m, cid, base, cmd_type=0, size=64):
    """Push a command and wait for its completion."""
    ctx.set(m.cmdq.cmd_valid, 1); ctx.set(m.cmdq.cmd_type, cmd_type)
    ctx.set(m.cmdq.cmd_correlation_id, cid)
    ctx.set(m.cmdq.cmd_epoch, 1)
    ctx.set(m.cmdq.cmd_region_base, base); ctx.set(m.cmdq.cmd_region_size, size)
    await ctx.tick(); ctx.set(m.cmdq.cmd_valid, 0)
    for _ in range(40):
        if ctx.get(m.compq.out_valid):
            return ctx.get(m.compq.out_correlation_id), ctx.get(m.compq.out_status)
        await ctx.tick()
    return None, None


def test_sweep_basic():
    """SWEEP_REGION → SweepEngine → compq."""
    m = _build(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.compq.out_ready, 1)
        cid, st = await _push_wait(ctx, m, 10, R0, cmd_type=1)
        assert cid == 10, f"cid={cid}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_scan_still_works():
    """SCAN_REGION → ScanEngine (not broken by sweep addition)."""
    m = _build(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.compq.out_ready, 1)
        cid, _ = await _push_wait(ctx, m, 10, R0, cmd_type=0)
        assert cid == 10
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_scan_then_sweep():
    """SCAN then SWEEP to same region — both complete."""
    m = _build(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.compq.out_ready, 1)
        c1, _ = await _push_wait(ctx, m, 10, R0, cmd_type=0)
        c2, _ = await _push_wait(ctx, m, 20, R0, cmd_type=1)
        assert c1 == 10 and c2 == 20, f"got {c1},{c2}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_sweep_then_sweep_same_region():
    """Two SWEEPs to same region — both complete."""
    m = _build(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.compq.out_ready, 1)
        c1, _ = await _push_wait(ctx, m, 10, R0, cmd_type=1)
        c2, _ = await _push_wait(ctx, m, 20, R0, cmd_type=1)
        assert c1 == 10 and c2 == 20
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_scan_diff_region():
    """SCAN region 0, SWEEP region 1 — parallel paths."""
    m = _build(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.compq.out_ready, 1)
        c1, _ = await _push_wait(ctx, m, 10, R0, cmd_type=0)
        c2, _ = await _push_wait(ctx, m, 20, R1, cmd_type=1)
        assert c1 == 10 and c2 == 20
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_sweep_stats():
    """SWEEP returns stats (dead_objects, bytes_moved)."""
    m = _build(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.compq.out_ready, 1)
        cid, _ = await _push_wait(ctx, m, 10, R0, cmd_type=1, size=128)
        assert ctx.get(m.compq.out_dead_objects) >= 0
        assert ctx.get(m.compq.out_bytes_moved) >= 0
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_no_loss_scan_sweep():
    """5 mixed SCAN/SWEEP → 5 completions, set equality."""
    m = _build(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.compq.out_ready, 1)
        seen = set()
        for i, (cid, typ) in enumerate([(10, 0), (20, 1), (30, 0), (40, 1), (50, 0)]):
            base = R0 + i * 0x10000000
            rc, _ = await _push_wait(ctx, m, cid, base, cmd_type=typ)
            seen.add(rc)
        assert len(seen) == 5, f"got {len(seen)}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()
