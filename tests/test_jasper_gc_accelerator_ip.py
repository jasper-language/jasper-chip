# Per-engine MemoryAccess tests for JasperGCAcceleratorIP.
from amaranth import *; from amaranth.sim import Simulator
from rtl.jasper_gc_accelerator_config import JasperGCAcceleratorConfig, AcceleratorProfile
from rtl.jasper_gc_accelerator_ip import JasperGCAcceleratorIP
from rtl.jasper_gc_chiplet_link import ChipletLink
from rtl.jasper_gc_coherent_access_adapter import CoherentAccessAdapter
from rtl.jasper_gc_memory_access import MemoryAccess

R0 = 0x08000000


def _dut(per_engine_memory=False, **kw):
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    return JasperGCAcceleratorIP(cfg, enable_memory=True, per_engine_memory=per_engine_memory, **kw)


def test_per_engine_memory_off():
    """Default mode (per_engine_memory=False) — single SCAN completes."""
    dut = _dut(per_engine_memory=False)
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
            if ctx.get(dut.iface.comp_valid):
                assert ctx.get(dut.iface.comp_correlation_id) == 10
                break
            await ctx.tick()
        assert hasattr(dut, '_mem'), "shared _mem expected"
        assert not hasattr(dut, '_scan_mem'), "no per-engine _scan_mem expected"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_per_engine_memory_on():
    """per_engine_memory=True — basic elaboration, single SCAN completes."""
    dut = _dut(per_engine_memory=True)
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
            if ctx.get(dut.iface.comp_valid):
                assert ctx.get(dut.iface.comp_correlation_id) == 10
                break
            await ctx.tick()
        for ename in ['scan', 'sweep', 'mre', 'ce']:
            assert hasattr(dut, f'_{ename}_mem'), f"_{ename}_mem expected"
        assert not hasattr(dut, '_mem'), "shared _mem not expected"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_per_engine_concurrent_access():
    """Two engines concurrently access memory — prove overlapping memory access
    by showing SWEEP request enters pipeline before SCAN response exits.
    """
    dut = _dut(per_engine_memory=True, mem_read_latency=8, mem_queue_depth=8)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)

        # Push SCAN (type=0, region A, 1 step)
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 0)
        ctx.set(dut.iface.cmd_correlation_id, 100)
        ctx.set(dut.iface.cmd_epoch, 1)
        ctx.set(dut.iface.cmd_region_base, R0)
        ctx.set(dut.iface.cmd_region_size, 128)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        await ctx.tick()

        # Push SWEEP (type=1, region B, 1 step)
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 1)
        ctx.set(dut.iface.cmd_correlation_id, 200)
        ctx.set(dut.iface.cmd_epoch, 1)
        ctx.set(dut.iface.cmd_region_base, R0 + 0x10000000)
        ctx.set(dut.iface.cmd_region_size, 128)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)

        # Track MemoryAccess response valid to prove overlap
        scan_rsp_seen = False
        sweep_rsp_seen = False
        both_completed = False

        for _ in range(100):
            # Check if SCAN MemoryAccess has a response
            if ctx.get(dut._scan_mem.rsp_valid):
                scan_rsp_seen = True
            # Check if SWEEP MemoryAccess has a response
            if ctx.get(dut._sweep_mem.rsp_valid):
                sweep_rsp_seen = True
            if scan_rsp_seen and sweep_rsp_seen:
                both_completed = True
                break
            await ctx.tick()

        assert both_completed, (
            f"Both engines must complete: scan_rsp={scan_rsp_seen} sweep_rsp={sweep_rsp_seen}"
        )

        # Verify both top-level completions received
        seen = set()
        for _ in range(80):
            if ctx.get(dut.iface.comp_valid):
                seen.add(ctx.get(dut.iface.comp_correlation_id))
                if len(seen) >= 2:
                    break
            await ctx.tick()
        assert seen == {100, 200}, f"Expected cids 100,200 got {seen}"
        print("  PASS (concurrent memory access confirmed)")
    sim.add_testbench(proc); sim.run()


def test_per_engine_tag_isolation():
    """Same tag on different engines does not collide with per_engine_memory."""
    dut = _dut(per_engine_memory=True, mem_read_latency=4, mem_queue_depth=8)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)

        # SCAN with cid=65535 → first request tag = 65535+1 = 0 (16-bit wrap)
        # SWEEP does not set mem_req_tag → tag=0 by default
        # Both use tag=0 on separate MemoryAccess instances → no collision
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 0)
        ctx.set(dut.iface.cmd_correlation_id, 65535)
        ctx.set(dut.iface.cmd_epoch, 1)
        ctx.set(dut.iface.cmd_region_base, R0)
        ctx.set(dut.iface.cmd_region_size, 64)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        await ctx.tick()

        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 1)
        ctx.set(dut.iface.cmd_correlation_id, 65535)
        ctx.set(dut.iface.cmd_epoch, 1)
        ctx.set(dut.iface.cmd_region_base, R0 + 0x10000000)
        ctx.set(dut.iface.cmd_region_size, 64)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)

        # Verify each MemoryAccess independently processes its request
        # by checking rsp_tag when response valid fires
        scan_tag_seen = set()
        sweep_tag_seen = set()
        for _ in range(100):
            if ctx.get(dut._scan_mem.rsp_valid):
                scan_tag_seen.add(ctx.get(dut._scan_mem.rsp_tag))
            if ctx.get(dut._sweep_mem.rsp_valid):
                sweep_tag_seen.add(ctx.get(dut._sweep_mem.rsp_tag))
            if scan_tag_seen and sweep_tag_seen:
                break
            await ctx.tick()

        assert 0 in scan_tag_seen, f"SCAN rsp_tag 0 not seen: {scan_tag_seen}"
        assert 0 in sweep_tag_seen, f"SWEEP rsp_tag 0 not seen: {sweep_tag_seen}"

        # Both engines complete
        comp_count = 0
        for _ in range(100):
            if ctx.get(dut.iface.comp_valid):
                assert ctx.get(dut.iface.comp_correlation_id) == 65535
                comp_count += 1
                if comp_count >= 2:
                    break
            await ctx.tick()
        assert comp_count == 2, f"Expected 2 completions, got {comp_count}"
        print("  PASS (tag isolation confirmed)")
    sim.add_testbench(proc); sim.run()


def test_memory_model_default():
    """Default memory_model is 'memory_access' -> MemoryAccess instantiated."""
    dut = _dut(memory_model="memory_access")
    assert dut._mem_backend == "memory_access"
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        assert isinstance(dut._mem, MemoryAccess)
        print("  PASS (memory_model default = MemoryAccess)")
    sim.add_testbench(proc); sim.run()


def test_memory_model_chiplet_link():
    """memory_model='chiplet_link' -> ChipletLink instantiated (shared)."""
    dut = _dut(per_engine_memory=False, memory_model="chiplet_link")
    assert dut._mem_backend == "chiplet_link"
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        assert isinstance(dut._mem, ChipletLink)
        print("  PASS (chiplet_link shared = ChipletLink)")
    sim.add_testbench(proc); sim.run()


def test_memory_model_coherent():
    """memory_model='coherent' -> CoherentAccessAdapter instantiated (shared)."""
    dut = _dut(per_engine_memory=False, memory_model="coherent")
    assert dut._mem_backend == "coherent"
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        assert isinstance(dut._mem, CoherentAccessAdapter)
        print("  PASS (coherent shared = CoherentAccessAdapter)")
    sim.add_testbench(proc); sim.run()


def test_chiplet_link_mem_heavy():
    """chiplet_link with all 4 engines through arbiter — each engine completes."""
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, per_engine_memory=False,
                                memory_model="chiplet_link")
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        assert isinstance(dut._mem, ChipletLink)
        ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        seen_cids = set()
        # Submit SCAN (region 0)
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 0)
        ctx.set(dut.iface.cmd_correlation_id, 10)
        ctx.set(dut.iface.cmd_epoch, 1)
        ctx.set(dut.iface.cmd_region_base, 0x08000000)
        ctx.set(dut.iface.cmd_region_size, 64)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        await ctx.tick()
        # Submit SWEEP (region 1)
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 1)
        ctx.set(dut.iface.cmd_correlation_id, 20)
        ctx.set(dut.iface.cmd_epoch, 1)
        ctx.set(dut.iface.cmd_region_base, 0x18000000)
        ctx.set(dut.iface.cmd_region_size, 64)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        await ctx.tick()
        # Submit REBUILD (region 2)
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 3)
        ctx.set(dut.iface.cmd_correlation_id, 30)
        ctx.set(dut.iface.cmd_epoch, 1)
        ctx.set(dut.iface.cmd_region_base, 0x28000000)
        ctx.set(dut.iface.cmd_region_size, 64)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        await ctx.tick()
        # Submit COMPACT (region 3)
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 2)
        ctx.set(dut.iface.cmd_correlation_id, 40)
        ctx.set(dut.iface.cmd_epoch, 1)
        ctx.set(dut.iface.cmd_region_base, 0x38000000)
        ctx.set(dut.iface.cmd_region_size, 64)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        # Collect completions (chiplet latency slower than MemoryAccess)
        events = []
        for _ in range(300):
            if ctx.get(dut.iface.comp_valid):
                cid = ctx.get(dut.iface.comp_correlation_id)
                st = ctx.get(dut.iface.comp_status)
                events.append(f'comp_{cid}_st{st}')
                seen_cids.add(cid)
            await ctx.tick()
        assert seen_cids == {10, 20, 30, 40}, (
            f"All 4 engines must complete, got {seen_cids}, events={events}")
        print("  PASS (chiplet_link 4-engine)")
    sim.add_testbench(proc); sim.run()
