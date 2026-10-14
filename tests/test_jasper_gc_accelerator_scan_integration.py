# Integration tests: ScanEngine through CommandQueue→Scheduler→CompletionQueue
from amaranth import *; from amaranth.sim import Simulator
from rtl.jasper_gc_accelerator_config import JasperGCAcceleratorConfig, AcceleratorProfile
from rtl.jasper_gc_accelerator_queue import CommandQueue, CompletionQueue
from rtl.jasper_gc_accelerator_scheduler import RegionScheduler
from rtl.jasper_gc_scan_engine import ScanEngine

R0 = 0x08000000; R1 = 0x18000000


def _build():
    cfg = JasperGCAcceleratorConfig(profile=AcceleratorProfile.ACCEL_STANDARD)
    m = Module()
    m.cmdq = CommandQueue(depth=cfg.command_queue_depth)
    m.sched = RegionScheduler(region_count=2)
    m.scan = ScanEngine(step_size=64)
    m.compq = CompletionQueue(depth=cfg.completion_queue_depth)
    m.submodules.cmdq = m.cmdq; m.submodules.sched = m.sched
    m.submodules.scan = m.scan; m.submodules.compq = m.compq

    # Hold cmdq pop while scheduler waits for scan engine
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
        m.scan.in_valid.eq(m.sched.out_valid),
        m.sched.out_ready.eq(m.scan.in_ready),
        m.scan.in_correlation_id.eq(m.sched.out_correlation_id),
        m.scan.in_epoch.eq(m.sched.out_epoch),
        m.scan.in_merge_domain.eq(m.sched.out_merge_domain),
        m.scan.in_region_base.eq(m.sched.out_region_base),
        m.scan.in_region_size.eq(m.sched.out_region_size),
        m.scan.out_ready.eq(m.compq.in_ready),
        m.compq.in_valid.eq(m.scan.out_valid | m.sched.comp_valid),
        m.compq.in_correlation_id.eq(Mux(m.sched.comp_valid, m.sched.comp_correlation_id, m.scan.out_correlation_id)),
        m.compq.in_epoch.eq(Mux(m.sched.comp_valid, m.sched.comp_epoch, m.scan.out_epoch)),
        m.compq.in_merge_domain.eq(Mux(m.sched.comp_valid, m.sched.comp_merge_domain, m.scan.out_merge_domain)),
        m.compq.in_status.eq(Mux(m.sched.comp_valid, m.sched.comp_status, m.scan.out_status)),
        m.compq.in_bytes_scanned.eq(m.scan.out_bytes_scanned),
        m.compq.in_objects_scanned.eq(m.scan.out_objects_scanned),
        m.compq.in_live_objects.eq(m.scan.out_live_objects),
        m.compq.in_dead_objects.eq(m.scan.out_dead_objects),
        m.compq.in_bytes_moved.eq(0), m.compq.in_objects_moved.eq(0),
        m.compq.in_metadata_updates.eq(0), m.compq.in_error_code.eq(m.scan.out_error_code),
    ]
    return m


def test_scan_basic():
    m = _build(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.compq.out_ready, 1)
        ctx.set(m.cmdq.cmd_valid, 1); ctx.set(m.cmdq.cmd_correlation_id, 42)
        ctx.set(m.cmdq.cmd_region_base, R0); ctx.set(m.cmdq.cmd_region_size, 64)
        await ctx.tick(); ctx.set(m.cmdq.cmd_valid, 0)
        for cyc in range(30):
            if ctx.get(m.compq.out_valid):
                assert ctx.get(m.compq.out_correlation_id) == 42, f"cid={ctx.get(m.compq.out_correlation_id)}"
                print("  PASS")
                return
            await ctx.tick()
        assert False, "no completion"
    sim.add_testbench(proc); sim.run()


def test_scan_two():
    m = _build(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.compq.out_ready, 1)
        for cid, base in [(10, R0), (20, R1)]:
            ctx.set(m.cmdq.cmd_valid, 1); ctx.set(m.cmdq.cmd_correlation_id, cid)
            ctx.set(m.cmdq.cmd_region_base, base); ctx.set(m.cmdq.cmd_region_size, 64)
            await ctx.tick(); ctx.set(m.cmdq.cmd_valid, 0)
            for _ in range(30):
                if ctx.get(m.compq.out_valid):
                    break
                await ctx.tick()
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_scan_backpressure():
    m = _build(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.compq.out_ready, 0)
        ctx.set(m.cmdq.cmd_valid, 1); ctx.set(m.cmdq.cmd_correlation_id, 10)
        ctx.set(m.cmdq.cmd_region_base, R0); ctx.set(m.cmdq.cmd_region_size, 64)
        await ctx.tick(); ctx.set(m.cmdq.cmd_valid, 0)
        for cyc in range(10):
            if ctx.get(m.compq.out_valid):
                break
            await ctx.tick()
        # Scan done but completion blocked
        ctx.set(m.compq.out_ready, 1)
        for cyc in range(10):
            if ctx.get(m.compq.out_valid):
                print("  PASS")
                return
            await ctx.tick()
        assert False, "no completion after unblock"
    sim.add_testbench(proc); sim.run()


def test_scan_five():
    m = _build(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.compq.out_ready, 1)
        seen = set()
        for i in range(5):
            ctx.set(m.cmdq.cmd_valid, 1); ctx.set(m.cmdq.cmd_correlation_id, i)
            ctx.set(m.cmdq.cmd_region_base, R0 + i * 0x10000000)
            ctx.set(m.cmdq.cmd_region_size, 64)
            await ctx.tick(); ctx.set(m.cmdq.cmd_valid, 0)
            # Wait for this scan's completion before pushing next
            for _ in range(30):
                if ctx.get(m.compq.out_valid):
                    seen.add(ctx.get(m.compq.out_correlation_id))
                    break
                await ctx.tick()
        assert len(seen) == 5, f"got {len(seen)}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()
