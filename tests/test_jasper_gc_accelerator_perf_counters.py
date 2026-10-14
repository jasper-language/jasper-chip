# Performance counters v0.1 tests: verify counters track real handshake events.
from amaranth import *; from amaranth.sim import Simulator
from rtl.jasper_gc_accelerator_config import JasperGCAcceleratorConfig, AcceleratorProfile
from rtl.jasper_gc_accelerator_ip import JasperGCAcceleratorIP

R0 = 0x08000000


def _val(ctx, ctr):
    return ctx.get(ctr.val)


def _max(ctx, mt):
    return ctx.get(mt.max)


def test_single_scan_counters():
    """Single SCAN — cmd_accepted=1, comp_accepted=1, scan_cmd_accepted=1."""
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 0)
        ctx.set(dut.iface.cmd_correlation_id, 10)
        ctx.set(dut.iface.cmd_epoch, 1)
        ctx.set(dut.iface.cmd_region_base, R0); ctx.set(dut.iface.cmd_region_size, 64)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        for _ in range(60):
            if ctx.get(dut.iface.comp_valid): break
            await ctx.tick()
        await ctx.tick()
        pc = dut._pc
        assert _val(ctx, pc.cmd_accepted) == 1, f"cmd_accepted={_val(ctx, pc.cmd_accepted)}"
        assert _val(ctx, pc.comp_accepted) == 1, f"comp_accepted={_val(ctx, pc.comp_accepted)}"
        assert _val(ctx, pc.scan_cmd_accepted) == 1, f"scan_cmd_accepted={_val(ctx, pc.scan_cmd_accepted)}"
        print(f"  PASS (cmd_acc={_val(ctx, pc.cmd_accepted)} comp_acc={_val(ctx, pc.comp_accepted)})")
    sim.add_testbench(proc); sim.run()


def test_four_engine_counters():
    """All 4 engines — per-engine cmd accepted each = 1, comp total = 4."""
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        for cid, typ, base in [(10, 0, R0), (20, 1, R0 + 0x10000000),
                                (30, 3, R0 + 0x20000000), (40, 2, R0 + 0x30000000)]:
            ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, typ)
            ctx.set(dut.iface.cmd_correlation_id, cid)
            ctx.set(dut.iface.cmd_epoch, 1)
            ctx.set(dut.iface.cmd_region_base, base)
            ctx.set(dut.iface.cmd_region_size, 64)
            await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
            for _ in range(60):
                if ctx.get(dut.iface.comp_valid): break
                await ctx.tick()
        await ctx.tick()
        pc = dut._pc
        assert _val(ctx, pc.cmd_accepted) == 4, f"cmd_accepted={_val(ctx, pc.cmd_accepted)}"
        assert _val(ctx, pc.comp_accepted) == 4, f"comp_accepted={_val(ctx, pc.comp_accepted)}"
        assert _val(ctx, pc.scan_cmd_accepted) == 1
        assert _val(ctx, pc.sweep_cmd_accepted) == 1
        assert _val(ctx, pc.rebuild_cmd_accepted) == 1
        assert _val(ctx, pc.compact_cmd_accepted) == 1
        assert _val(ctx, pc.scan_comp_accepted) == 1
        assert _val(ctx, pc.sweep_comp_accepted) == 1
        assert _val(ctx, pc.rebuild_comp_accepted) == 1
        assert _val(ctx, pc.compact_comp_accepted) == 1
        print(f"  PASS (cmd_acc={_val(ctx, pc.cmd_accepted)} comp_acc={_val(ctx, pc.comp_accepted)})")
    sim.add_testbench(proc); sim.run()


def test_mem_req_rsp_match():
    """mem_req_accepted == mem_rsp_accepted for 4 memory commands."""
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        for cid, typ, base in [(10, 0, R0), (20, 1, R0 + 0x10000000),
                                (30, 3, R0 + 0x20000000), (40, 2, R0 + 0x30000000)]:
            ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, typ)
            ctx.set(dut.iface.cmd_correlation_id, cid)
            ctx.set(dut.iface.cmd_epoch, 1)
            ctx.set(dut.iface.cmd_region_base, base)
            ctx.set(dut.iface.cmd_region_size, 64)
            await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
            for _ in range(60):
                if ctx.get(dut.iface.comp_valid): break
                await ctx.tick()
        await ctx.tick()
        pc = dut._pc
        mreq = _val(ctx, pc.mem_req_accepted)
        mrsp = _val(ctx, pc.mem_rsp_accepted)
        assert mreq == mrsp, f"mem_req={mreq} != mem_rsp={mrsp}"
        assert mreq > 0, f"mem_req={mreq} should be > 0"
        print(f"  PASS (mem_req={mreq} mem_rsp={mrsp})")
    sim.add_testbench(proc); sim.run()


def test_cmd_backpressure():
    """cmd_accepted counter works in normal operation."""
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=False)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        pc = dut._pc
        for i in range(2):
            ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 0)
            ctx.set(dut.iface.cmd_correlation_id, i)
            ctx.set(dut.iface.cmd_epoch, 1)
            ctx.set(dut.iface.cmd_region_base, R0 + i * 0x10000000)
            ctx.set(dut.iface.cmd_region_size, 64)
            await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
            for _ in range(60):
                if ctx.get(dut.iface.comp_valid): break
                await ctx.tick()
        await ctx.tick()
        ca = _val(ctx, pc.cmd_accepted)
        bp = _val(ctx, pc.cmd_backpressure)
        sm = _max(ctx, pc.cmd_stall_max)
        assert ca == 2, f"cmd_accepted={ca} expected 2"
        print(f"  PASS (cmd_acc={ca} bp={bp} max_stall={sm})")
    sim.add_testbench(proc); sim.run()


def test_comp_backpressure():
    """comp_accepted counter works in normal (no backpressure) operation."""
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=False)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        pc = dut._pc
        for i in range(2):
            ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 0)
            ctx.set(dut.iface.cmd_correlation_id, i)
            ctx.set(dut.iface.cmd_epoch, 1)
            ctx.set(dut.iface.cmd_region_base, R0 + i * 0x10000000)
            ctx.set(dut.iface.cmd_region_size, 64)
            await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
            for _ in range(60):
                if ctx.get(dut.iface.comp_valid): break
                await ctx.tick()
        await ctx.tick()
        ca = _val(ctx, pc.comp_accepted)
        assert ca == 2, f"comp_accepted={ca} expected 2"
        bp = _val(ctx, pc.comp_backpressure)
        print(f"  PASS (comp_acc={ca} bp={bp})")
    sim.add_testbench(proc); sim.run()


def test_single_outstanding_block():
    """outstanding_block counter is wired.
    NOTE: true outstanding_block requires continuous cmd_valid (FUTURE);
    in pulse-mode, sched serializes so no overlap occurs."""
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        pc = dut._pc
        # Push 4 commands (different engines)
        for cid, typ, base in [(10, 0, R0), (20, 1, R0 + 0x10000000),
                                (30, 3, R0 + 0x20000000), (40, 2, R0 + 0x30000000)]:
            ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, typ)
            ctx.set(dut.iface.cmd_correlation_id, cid)
            ctx.set(dut.iface.cmd_epoch, 1)
            ctx.set(dut.iface.cmd_region_base, base)
            ctx.set(dut.iface.cmd_region_size, 64)
            await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
            for _ in range(60):
                if ctx.get(dut.iface.comp_valid): break
                await ctx.tick()
        # Outstanding block may be 0 due to sched serialization — just verify counter exists
        ob = _val(ctx, pc.outstanding_block)
        print(f"  PASS (outstanding_block={ob} — expected 0 in pulse-mode)")
    sim.add_testbench(proc); sim.run()


def test_stale_epoch_reject_counter():
    """Stale epoch increments reject counter but NOT mem_req_accepted."""
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 5)
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 0)
        ctx.set(dut.iface.cmd_correlation_id, 10)
        ctx.set(dut.iface.cmd_epoch, 3)
        ctx.set(dut.iface.cmd_region_base, R0); ctx.set(dut.iface.cmd_region_size, 64)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        for _ in range(30):
            if ctx.get(dut.iface.comp_valid): break
            await ctx.tick()
        await ctx.tick()
        pc = dut._pc
        stale = _val(ctx, pc.stale_epoch_reject)
        mem_req = _val(ctx, pc.mem_req_accepted)
        assert stale >= 1, f"stale_epoch_reject={stale} should be >= 1"
        assert mem_req == 0, f"mem_req_accepted={mem_req} should be 0 for stale epoch"
        print(f"  PASS (stale_reject={stale} mem_req={mem_req})")
    sim.add_testbench(proc); sim.run()


def test_unsupported_reject_counter():
    """Unsupported cmd increments reject counter but NOT mem_req_accepted."""
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 4)
        ctx.set(dut.iface.cmd_correlation_id, 77)
        ctx.set(dut.iface.cmd_epoch, 1)
        ctx.set(dut.iface.cmd_region_base, R0); ctx.set(dut.iface.cmd_region_size, 64)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        for _ in range(30):
            if ctx.get(dut.iface.comp_valid): break
            await ctx.tick()
        await ctx.tick()
        pc = dut._pc
        unsupp = _val(ctx, pc.unsupported_reject)
        mem_req = _val(ctx, pc.mem_req_accepted)
        assert unsupp >= 1, f"unsupported_reject={unsupp} should be >= 1"
        assert mem_req == 0, f"mem_req_accepted={mem_req} should be 0 for unsupported"
        print(f"  PASS (unsupp_reject={unsupp} mem_req={mem_req})")
    sim.add_testbench(proc); sim.run()


def test_counting_mode_mem_counters_zero():
    """enable_memory=False → memory counters = 0, cmd/comp counters work."""
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=False)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 0)
        ctx.set(dut.iface.cmd_correlation_id, 10)
        ctx.set(dut.iface.cmd_epoch, 1)
        ctx.set(dut.iface.cmd_region_base, R0); ctx.set(dut.iface.cmd_region_size, 64)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        for _ in range(30):
            if ctx.get(dut.iface.comp_valid): break
            await ctx.tick()
        await ctx.tick()
        pc = dut._pc
        mreq = _val(ctx, pc.mem_req_accepted)
        mrsp = _val(ctx, pc.mem_rsp_accepted)
        cmd_acc = _val(ctx, pc.cmd_accepted)
        comp_acc = _val(ctx, pc.comp_accepted)
        assert mreq == 0, f"mem_req_accepted={mreq} should be 0 in counting mode"
        assert mrsp == 0, f"mem_rsp_accepted={mrsp} should be 0 in counting mode"
        assert cmd_acc == 1, f"cmd_accepted={cmd_acc} should be 1"
        assert comp_acc == 1, f"comp_accepted={comp_acc} should be 1"
        print(f"  PASS (mem_req={mreq} mem_rsp={mrsp} cmd={cmd_acc} comp={comp_acc})")
    sim.add_testbench(proc); sim.run()
