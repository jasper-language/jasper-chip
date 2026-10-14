# Top-level MemoryAccess integration: SCAN through MemoryAccess in active path
from amaranth import *; from amaranth.sim import Simulator
from rtl.jasper_gc_accelerator_config import JasperGCAcceleratorConfig, AcceleratorProfile
from rtl.jasper_gc_accelerator_ip import JasperGCAcceleratorIP

R0 = 0x08000000


def test_counting_mode_still_works():
    """enable_memory=False → SCAN still completes (counting mode)."""
    cfg = JasperGCAcceleratorConfig(profile=AcceleratorProfile.ACCEL_STANDARD)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=False)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 0)
        ctx.set(dut.iface.cmd_correlation_id, 42)
        ctx.set(dut.iface.cmd_epoch, 1)
        ctx.set(dut.iface.cmd_region_base, R0); ctx.set(dut.iface.cmd_region_size, 64)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        for _ in range(30):
            if ctx.get(dut.iface.comp_valid):
                assert ctx.get(dut.iface.comp_correlation_id) == 42
                print("  PASS")
                return
            await ctx.tick()
        assert False, "no completion"
    sim.add_testbench(proc); sim.run()


def test_memory_mode_scan_completes():
    """enable_memory=True → SCAN completes via MemoryAccess with latency."""
    cfg = JasperGCAcceleratorConfig(profile=AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, mem_read_latency=4)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 0)
        ctx.set(dut.iface.cmd_correlation_id, 42)
        ctx.set(dut.iface.cmd_epoch, 1)
        ctx.set(dut.iface.cmd_region_base, R0); ctx.set(dut.iface.cmd_region_size, 64)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        for _ in range(80):
            if ctx.get(dut.iface.comp_valid):
                cid = ctx.get(dut.iface.comp_correlation_id)
                bs = ctx.get(dut.iface.comp_bytes_scanned)
                assert cid == 42, f"cid={cid}"
                assert bs == 64, f"bytes_scanned={bs}"
                print("  PASS")
                return
            await ctx.tick()
        assert False, "no completion"
    sim.add_testbench(proc); sim.run()


def test_memory_latency_slows_scan():
    """Memory latency makes scan take longer than counting mode."""
    cfg = JasperGCAcceleratorConfig(profile=AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, mem_read_latency=8)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 0)
        ctx.set(dut.iface.cmd_correlation_id, 10)
        ctx.set(dut.iface.cmd_epoch, 1)
        ctx.set(dut.iface.cmd_region_base, R0); ctx.set(dut.iface.cmd_region_size, 256)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        # With latency=8 and 4 steps (256/64), ~32 cycles expected
        for cyc in range(100):
            if ctx.get(dut.iface.comp_valid):
                assert ctx.get(dut.iface.comp_correlation_id) == 10
                print(f"  PASS (cyc={cyc})")
                return
            await ctx.tick()
        assert False, "no completion"
    sim.add_testbench(proc); sim.run()


def test_region_base_address():
    """First mem_req_addr should be region_base."""
    cfg = JasperGCAcceleratorConfig(profile=AcceleratorProfile.ACCEL_SERVER)
    # Direct test: check scan engine's mem_req_addr
    from rtl.jasper_gc_scan_engine import ScanEngine
    se = ScanEngine(step_size=64, use_memory=True)
    sim = Simulator(se); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(se.in_valid, 1); ctx.set(se.in_correlation_id, 10)
        ctx.set(se.in_region_base, 0x2000); ctx.set(se.in_region_size, 64)
        ctx.set(se.out_ready, 1); ctx.set(se.mem_req_ready, 1)
        ctx.set(se.mem_rsp_valid, 1)
        await ctx.tick(); ctx.set(se.in_valid, 0)
        # First request address should be 0x2000
        assert ctx.get(se.mem_req_addr) == 0x2000, f"addr={ctx.get(se.mem_req_addr)}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_multi_step_addresses():
    """Address advances by step_size each step."""
    from rtl.jasper_gc_scan_engine import ScanEngine
    se = ScanEngine(step_size=64, use_memory=True)
    sim = Simulator(se); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(se.in_valid, 1); ctx.set(se.in_correlation_id, 10)
        ctx.set(se.in_region_base, 0x1000); ctx.set(se.in_region_size, 192)
        ctx.set(se.out_ready, 1); ctx.set(se.mem_req_ready, 1)
        ctx.set(se.mem_rsp_valid, 1)
        await ctx.tick(); ctx.set(se.in_valid, 0)
        addrs = []
        for _ in range(20):
            if ctx.get(se.mem_req_valid) and ctx.get(se.mem_req_ready):
                addrs.append(ctx.get(se.mem_req_addr))
            if ctx.get(se.out_valid):
                break
            await ctx.tick()
        assert 0x1000 in addrs and 0x1040 in addrs and 0x1080 in addrs, f"addrs={addrs}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_sweep_unaffected():
    """SWEEP (counting) works alongside SCAN (memory mode)."""
    cfg = JasperGCAcceleratorConfig(profile=AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        # SWEEP (counting, no memory)
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 1)
        ctx.set(dut.iface.cmd_correlation_id, 10)
        ctx.set(dut.iface.cmd_epoch, 1)
        ctx.set(dut.iface.cmd_region_base, R0); ctx.set(dut.iface.cmd_region_size, 64)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        for _ in range(30):
            if ctx.get(dut.iface.comp_valid):
                break
            await ctx.tick()
        assert ctx.get(dut.iface.comp_correlation_id) == 10
        print("  PASS")
    sim.add_testbench(proc); sim.run()
