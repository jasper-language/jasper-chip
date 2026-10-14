# tests/test_jasper_gc_accelerator_metadata_rebuild_integration.py
# 3-engine integration: ScanEngine + SweepEngine + MetadataRebuildEngine
from amaranth import *; from amaranth.sim import Simulator
from rtl.jasper_gc_accelerator_config import JasperGCAcceleratorConfig, AcceleratorProfile
from rtl.jasper_gc_accelerator_queue import CommandQueue, CompletionQueue
from rtl.jasper_gc_accelerator_scheduler import RegionScheduler
from rtl.jasper_gc_scan_engine import ScanEngine
from rtl.jasper_gc_sweep_engine import SweepEngine
from rtl.jasper_gc_metadata_rebuild_engine import MetadataRebuildEngine

R0 = 0x08000000; R1 = 0x18000000


def _build():
    cfg = JasperGCAcceleratorConfig(profile=AcceleratorProfile.ACCEL_STANDARD)
    m = Module()
    m.cmdq = CommandQueue(depth=cfg.command_queue_depth)
    m.sched = RegionScheduler(region_count=4, support_sweep=True, support_rebuild=True)
    m.scan = ScanEngine(step_size=64)
    m.sweep = SweepEngine(step_size=64)
    m.mre = MetadataRebuildEngine(step_size=64)
    m.compq = CompletionQueue(depth=cfg.completion_queue_depth)
    m.submodules.cmdq = m.cmdq; m.submodules.sched = m.sched
    m.submodules.scan = m.scan; m.submodules.sweep = m.sweep
    m.submodules.mre = m.mre; m.submodules.compq = m.compq

    # Hold
    sched_hold = Signal()
    with m.If(m.sched.out_valid):
        with m.If(~m.sched.out_ready):
            m.d.sync += sched_hold.eq(1)
        with m.Else(): m.d.sync += sched_hold.eq(0)
    with m.Else(): m.d.sync += sched_hold.eq(0)

    m.d.comb += [
        m.sched.in_valid.eq(m.cmdq.out_valid),
        m.cmdq.out_ready.eq(m.sched.in_ready & ~sched_hold),
        m.sched.in_type.eq(m.cmdq.out_type),
        m.sched.in_correlation_id.eq(m.cmdq.out_correlation_id),
        m.sched.in_epoch.eq(m.cmdq.out_epoch),
        m.sched.in_region_base.eq(m.cmdq.out_region_base),
        m.sched.in_region_size.eq(m.cmdq.out_region_size),
        m.sched.in_merge_domain.eq(m.cmdq.out_merge_domain),
        m.sched.current_epoch.eq(1),
    ]

    # Route: SCAN=0→scan, SWEEP=1→sweep, REBUILD=3→mre
    to_scan = Signal(); to_sweep = Signal(); to_mre = Signal()
    m.d.comb += [
        to_scan.eq(m.sched.out_valid & (m.sched.out_type == 0)),
        to_sweep.eq(m.sched.out_valid & (m.sched.out_type == 1)),
        to_mre.eq(m.sched.out_valid & (m.sched.out_type == 3)),
    ]
    m.d.comb += [
        m.scan.in_valid.eq(to_scan),
        m.sweep.in_valid.eq(to_sweep),
        m.mre.in_valid.eq(to_mre),
        m.sched.out_ready.eq(Mux(to_scan, m.scan.in_ready,
                              Mux(to_sweep, m.sweep.in_ready,
                              Mux(to_mre, m.mre.in_ready, 1)))),
        m.scan.in_correlation_id.eq(m.sched.out_correlation_id),
        m.scan.in_epoch.eq(m.sched.out_epoch), m.scan.in_merge_domain.eq(m.sched.out_merge_domain),
        m.scan.in_region_base.eq(m.sched.out_region_base), m.scan.in_region_size.eq(m.sched.out_region_size),
        m.sweep.in_correlation_id.eq(m.sched.out_correlation_id),
        m.sweep.in_epoch.eq(m.sched.out_epoch), m.sweep.in_merge_domain.eq(m.sched.out_merge_domain),
        m.sweep.in_region_base.eq(m.sched.out_region_base), m.sweep.in_region_size.eq(m.sched.out_region_size),
        m.mre.in_correlation_id.eq(m.sched.out_correlation_id),
        m.mre.in_epoch.eq(m.sched.out_epoch), m.mre.in_merge_domain.eq(m.sched.out_merge_domain),
        m.mre.in_region_base.eq(m.sched.out_region_base), m.mre.in_region_size.eq(m.sched.out_region_size),
    ]

    # Region unlock
    issue_region = Signal(max(4, 1))
    with m.If(m.sched.out_valid & m.sched.out_ready):
        m.d.sync += issue_region.eq(m.sched.out_region_base[28:30])

    # Arbitration: mre > sweep > scan
    sel_mre = Signal(); sel_sw = Signal(); sel_sc = Signal()
    m.d.comb += [
        sel_mre.eq(m.mre.out_valid),
        sel_sw.eq(m.sweep.out_valid & ~m.mre.out_valid),
        sel_sc.eq(m.scan.out_valid & ~m.sweep.out_valid & ~m.mre.out_valid),
    ]
    m.d.comb += [
        m.mre.out_ready.eq(sel_mre & m.compq.in_ready),
        m.sweep.out_ready.eq(sel_sw & m.compq.in_ready),
        m.scan.out_ready.eq(sel_sc & m.compq.in_ready),
    ]

    scan_done = Signal(); sweep_done = Signal(); mre_done = Signal()
    m.d.comb += [
        scan_done.eq(m.scan.out_valid & m.scan.out_ready),
        sweep_done.eq(m.sweep.out_valid & m.sweep.out_ready),
        mre_done.eq(m.mre.out_valid & m.mre.out_ready),
        m.sched.unlock.eq(scan_done | sweep_done | mre_done),
        m.sched.unlock_region.eq(issue_region),
    ]

    # Completion mux: mre > sweep > scan
    def _eng_sel(scan_val, sweep_val, mre_val):
        return Mux(m.mre.out_valid, mre_val,
              Mux(m.sweep.out_valid, sweep_val, scan_val))

    m.d.comb += [
        m.compq.in_valid.eq(m.sched.comp_valid | m.mre.out_valid | m.sweep.out_valid | m.scan.out_valid),
        m.compq.in_status.eq(Mux(m.sched.comp_valid, m.sched.comp_status,
                             _eng_sel(m.scan.out_status, m.sweep.out_status, m.mre.out_status))),
        m.compq.in_correlation_id.eq(Mux(m.sched.comp_valid, m.sched.comp_correlation_id,
                                    _eng_sel(m.scan.out_correlation_id, m.sweep.out_correlation_id, m.mre.out_correlation_id))),
        m.compq.in_epoch.eq(Mux(m.sched.comp_valid, m.sched.comp_epoch,
                           _eng_sel(m.scan.out_epoch, m.sweep.out_epoch, m.mre.out_epoch))),
        m.compq.in_merge_domain.eq(Mux(m.sched.comp_valid, m.sched.comp_merge_domain,
                                  _eng_sel(m.scan.out_merge_domain, m.sweep.out_merge_domain, m.mre.out_merge_domain))),
        m.compq.in_bytes_scanned.eq(_eng_sel(m.scan.out_bytes_scanned, m.sweep.out_bytes_scanned, m.mre.out_bytes_scanned)),
        m.compq.in_objects_scanned.eq(_eng_sel(m.scan.out_objects_scanned, m.sweep.out_objects_scanned, m.mre.out_objects_scanned)),
        m.compq.in_metadata_updates.eq(Mux(m.mre.out_valid, m.mre.out_metadata_updates,
                                       Mux(m.sweep.out_valid, m.sweep.out_metadata_updates, 0))),
        m.compq.in_live_objects.eq(_eng_sel(m.scan.out_live_objects, m.sweep.out_live_objects, 0)),
        m.compq.in_dead_objects.eq(_eng_sel(m.scan.out_dead_objects, m.sweep.out_dead_objects, 0)),
        m.compq.in_bytes_moved.eq(_eng_sel(0, m.sweep.out_bytes_moved, 0)),
        m.compq.in_objects_moved.eq(_eng_sel(0, m.sweep.out_objects_moved, 0)),
        m.compq.in_error_code.eq(_eng_sel(m.scan.out_error_code, m.sweep.out_error_code, m.mre.out_error_code)),
    ]
    return m


async def _push_wait(ctx, m, cid, base, cmd_type=0, size=64, merge_domain=0):
    ctx.set(m.cmdq.cmd_valid, 1); ctx.set(m.cmdq.cmd_type, cmd_type)
    ctx.set(m.cmdq.cmd_correlation_id, cid)
    ctx.set(m.cmdq.cmd_epoch, 1)
    ctx.set(m.cmdq.cmd_merge_domain, merge_domain)
    ctx.set(m.cmdq.cmd_region_base, base); ctx.set(m.cmdq.cmd_region_size, size)
    await ctx.tick(); ctx.set(m.cmdq.cmd_valid, 0)
    for _ in range(40):
        if ctx.get(m.compq.out_valid):
            return ctx.get(m.compq.out_correlation_id), ctx.get(m.compq.out_merge_domain)
        await ctx.tick()
    return None, None


def test_rebuild_basic():
    m = _build(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.compq.out_ready, 1)
        cid, dm = await _push_wait(ctx, m, 10, R0, cmd_type=3)
        assert cid == 10, f"cid={cid}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_scan_still_works():
    m = _build(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.compq.out_ready, 1)
        cid, _ = await _push_wait(ctx, m, 10, R0, cmd_type=0)
        assert cid == 10
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_sweep_still_works():
    m = _build(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.compq.out_ready, 1)
        cid, _ = await _push_wait(ctx, m, 10, R0, cmd_type=1)
        assert cid == 10
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_merge_domain_preserved():
    """Merge domain is preserved through all 3 engine types."""
    m = _build(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.compq.out_ready, 1)
        for typ, label in [(0, "SCAN"), (1, "SWEEP"), (3, "REBUILD")]:
            cid, dm = await _push_wait(ctx, m, typ + 10, R0, cmd_type=typ, merge_domain=typ)
            assert dm == typ, f"{label}: domain={dm}, expected {typ}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_scan_rebuild_diff_region():
    m = _build(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.compq.out_ready, 1)
        c1, _ = await _push_wait(ctx, m, 10, R0, cmd_type=0)
        c2, _ = await _push_wait(ctx, m, 20, R0 + 0x10000000, cmd_type=3)
        assert c1 == 10 and c2 == 20
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_three_engines_diff_region():
    m = _build(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.compq.out_ready, 1)
        c1, _ = await _push_wait(ctx, m, 10, R0, cmd_type=0)
        c2, _ = await _push_wait(ctx, m, 20, R0 + 0x10000000, cmd_type=1)
        c3, _ = await _push_wait(ctx, m, 30, R0 + 0x20000000, cmd_type=3)
        assert c1 == 10 and c2 == 20 and c3 == 30
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_unsupported_still_unsupported():
    m = _build(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.compq.out_ready, 1)
        cid, _ = await _push_wait(ctx, m, 77, R0, cmd_type=2)
        assert cid is not None
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_no_loss():
    m = _build(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.compq.out_ready, 1)
        seen = set()
        for i, (cid, typ) in enumerate([(10, 0), (20, 1), (30, 3), (40, 0), (50, 3)]):
            base = R0 + i * 0x10000000
            rc, _ = await _push_wait(ctx, m, cid, base, cmd_type=typ)
            seen.add(rc)
        assert len(seen) == 5, f"got {len(seen)}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()
