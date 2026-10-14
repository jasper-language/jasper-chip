# Full-system accelerator integration simulation (FPGA replacement)
from amaranth import *; from amaranth.sim import Simulator
from rtl.jasper_gc_accelerator_config import JasperGCAcceleratorConfig, AcceleratorProfile
from rtl.jasper_gc_accelerator_ip import JasperGCAcceleratorIP

# Region address mapping: bits 28:30 select region (0-3)
# region 0 = 0x00000000, region 1 = 0x10000000, region 2 = 0x20000000, region 3 = 0x30000000
R = [0x00000000, 0x10000000, 0x20000000, 0x30000000]

# ─── Helpers ────────────────────────────────────────────────────────────────

async def push_cmd(ctx, dut, typ, cid, epoch, base, size=64, flags=0):
    ctx.set(dut.iface.cmd_valid, 1)
    ctx.set(dut.iface.cmd_type, typ)
    ctx.set(dut.iface.cmd_correlation_id, cid)
    ctx.set(dut.iface.cmd_epoch, epoch)
    ctx.set(dut.iface.cmd_region_base, base)
    ctx.set(dut.iface.cmd_region_size, size)
    ctx.set(dut.iface.cmd_flags, flags)
    await ctx.tick()
    ctx.set(dut.iface.cmd_valid, 0)

async def pull_comp(ctx, dut, timeout=100):
    for _ in range(timeout):
        if ctx.get(dut.iface.comp_valid):
            return (ctx.get(dut.iface.comp_correlation_id),
                    ctx.get(dut.iface.comp_status),
                    ctx.get(dut.iface.comp_epoch))
        await ctx.tick()
    raise AssertionError(f"completion timeout after {timeout} cycles")

# ─── 1. All 4 engines concurrent on 4 regions ──────────────────────────────

def test_four_engines_concurrent():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        cmds = [(0, 10, R[0]), (1, 11, R[1]),
                (2, 12, R[2]), (3, 13, R[3])]
        for typ, cid, base in cmds:
            await push_cmd(ctx, dut, typ, cid, 1, base)
        seen = set()
        for _ in range(200):
            if ctx.get(dut.iface.comp_valid):
                cid = ctx.get(dut.iface.comp_correlation_id)
                seen.add(cid)
                await ctx.tick()
                if len(seen) == 4:
                    break
            else:
                await ctx.tick()
        assert seen == {10, 11, 12, 13}, f"missing completions: {seen}"
    sim.add_testbench(proc); sim.run()
    print("  PASS")

# ─── 2. Multi-outstanding (same engine, multiple commands) ─────────────────

def test_multi_outstanding():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        for i in range(4):
            await push_cmd(ctx, dut, 0, i, 1, R[i])
        seen = set()
        for _ in range(200):
            if ctx.get(dut.iface.comp_valid):
                cid = ctx.get(dut.iface.comp_correlation_id)
                seen.add(cid)
                await ctx.tick()
                if len(seen) == 4:
                    break
            else:
                await ctx.tick()
        assert seen == {0, 1, 2, 3}, f"missing: {seen}"
    sim.add_testbench(proc); sim.run()
    print("  PASS")

# ─── 3. Backpressure: hold comp_ready ─────────────────────────────────────

def test_comp_backpressure():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        ctx.set(dut.iface.comp_ready, 0)
        ctx.set(dut.iface.current_epoch, 1)
        await push_cmd(ctx, dut, 0, 10, 1, R[0])
        for _ in range(30):
            await ctx.tick()
        assert ctx.get(dut.iface.comp_valid) == 1, "completion should be held"
        cid = ctx.get(dut.iface.comp_correlation_id)
        ctx.set(dut.iface.comp_ready, 1)
        await ctx.tick()
        assert cid == 10
    sim.add_testbench(proc); sim.run()
    print("  PASS")

# ─── 4. Epoch mismatch rejection ──────────────────────────────────────────

def test_epoch_mismatch():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 5)
        await push_cmd(ctx, dut, 0, 10, 3, R[0])
        cid, status, _ = await pull_comp(ctx, dut)
        assert status == 3, f"expected STALE_EPOCH(3), got {status}"
        assert cid == 10
    sim.add_testbench(proc); sim.run()
    print("  PASS")

# ─── 5. Unsupported command type rejection ─────────────────────────────────

def test_unsupported_type():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        await push_cmd(ctx, dut, 6, 10, 1, R[0])
        cid, status, _ = await pull_comp(ctx, dut)
        assert status == 5, f"expected UNSUPPORTED(5), got {status}"
        assert cid == 10
    sim.add_testbench(proc); sim.run()
    print("  PASS")

# ─── 6. Region conflict (same region, different engines) ───────────────────

def test_region_conflict():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        await push_cmd(ctx, dut, 0, 10, 1, R[0])
        await push_cmd(ctx, dut, 1, 11, 1, R[0])
        seen = set()
        for _ in range(100):
            if ctx.get(dut.iface.comp_valid):
                cid = ctx.get(dut.iface.comp_correlation_id)
                seen.add(cid)
                await ctx.tick()
                if len(seen) == 2:
                    break
            else:
                await ctx.tick()
        assert seen == {10, 11}, f"missing: {seen}"
    sim.add_testbench(proc); sim.run()
    print("  PASS")

# ─── 7. ChipletLink memory model ──────────────────────────────────────────

def test_chiplet_link_model():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_STANDARD)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True,
                                memory_model="chiplet_link", link_latency=3,
                                burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        await push_cmd(ctx, dut, 0, 10, 1, R[1])
        cid, status, _ = await pull_comp(ctx, dut, timeout=80)
        assert cid == 10
        assert status in (0, 1, 2), f"unexpected status {status}"
    sim.add_testbench(proc); sim.run()
    print("  PASS")

# ─── 8. Coherent memory model ─────────────────────────────────────────────

def test_coherent_model():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_STANDARD)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True,
                                memory_model="coherent",
                                burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        await push_cmd(ctx, dut, 0, 10, 1, R[1])
        cid, status, _ = await pull_comp(ctx, dut, timeout=80)
        assert cid == 10
    sim.add_testbench(proc); sim.run()
    print("  PASS")

# ─── 9. Per-engine memory (4 engines, each with own MemoryAccess) ─────────

def test_per_engine_memory():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, per_engine_memory=True,
                                burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        cmds = [(0, 10, R[0]), (1, 11, R[1]),
                (2, 12, R[2]), (3, 13, R[3])]
        for typ, cid, base in cmds:
            await push_cmd(ctx, dut, typ, cid, 1, base)
        seen = set()
        for _ in range(200):
            if ctx.get(dut.iface.comp_valid):
                cid = ctx.get(dut.iface.comp_correlation_id)
                seen.add(cid)
                await ctx.tick()
                if len(seen) == 4:
                    break
            else:
                await ctx.tick()
        assert seen == {10, 11, 12, 13}, f"missing: {seen}"
    sim.add_testbench(proc); sim.run()
    print("  PASS")

# ─── 10. ChipletLink + per_engine_memory ──────────────────────────────────

def test_per_engine_chiplet():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_STANDARD)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, per_engine_memory=True,
                                memory_model="chiplet_link", link_latency=2,
                                burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        cmds = [(0, 10, R[1]), (1, 11, R[2])]
        for typ, cid, base in cmds:
            await push_cmd(ctx, dut, typ, cid, 1, base)
        seen = set()
        for _ in range(100):
            if ctx.get(dut.iface.comp_valid):
                cid = ctx.get(dut.iface.comp_correlation_id)
                seen.add(cid)
                await ctx.tick()
                if len(seen) == 2:
                    break
            else:
                await ctx.tick()
        assert seen == {10, 11}, f"missing: {seen}"
    sim.add_testbench(proc); sim.run()
    print("  PASS")

# ─── 11. Stress: 16 commands, no-loss, all 4 engines ──────────────────────

def test_stress_16_cmds():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_EXTREME)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        n = 16
        seen = set()
        for i in range(n):
            typ = i % 4
            await push_cmd(ctx, dut, typ, i, 1, R[i % 4])
            for _ in range(100):
                if ctx.get(dut.iface.comp_valid):
                    cid = ctx.get(dut.iface.comp_correlation_id)
                    seen.add(cid)
                    await ctx.tick()
                    break
                await ctx.tick()
        assert seen == set(range(n)), f"no-loss: got {len(seen)}/{n}"
    sim.add_testbench(proc); sim.run()
    print("  PASS")

# ─── 12. Counting mode + all 4 engines ────────────────────────────────────

def test_counting_mode_all():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=False, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        cmds = [(0, 10, R[0]), (1, 11, R[1]),
                (2, 12, R[2]), (3, 13, R[3])]
        for typ, cid, base in cmds:
            await push_cmd(ctx, dut, typ, cid, 1, base)
        seen = set()
        for _ in range(200):
            if ctx.get(dut.iface.comp_valid):
                cid = ctx.get(dut.iface.comp_correlation_id)
                seen.add(cid)
                await ctx.tick()
                if len(seen) == 4:
                    break
            else:
                await ctx.tick()
        assert seen == {10, 11, 12, 13}, f"missing: {seen}"
    sim.add_testbench(proc); sim.run()
    print("  PASS")

# ─── 13. Profile-specific integration ─────────────────────────────────────

async def _profile_test(ctx, dut, count, eng_types):
    ctx.set(dut.iface.comp_ready, 1)
    ctx.set(dut.iface.current_epoch, 1)
    seen = set()
    for i in range(count):
        typ = eng_types[i % len(eng_types)]
        await push_cmd(ctx, dut, typ, i, 1, R[i % 4])
        for _ in range(100):
            if ctx.get(dut.iface.comp_valid):
                cid = ctx.get(dut.iface.comp_correlation_id)
                seen.add(cid)
                await ctx.tick()
                break
            await ctx.tick()
    assert seen == set(range(count)), f"got {len(seen)}/{count}: {seen}"

def test_lite_profile():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_LITE)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await _profile_test(ctx, dut, 4, [0, 1])
    sim.add_testbench(proc); sim.run()
    print("  PASS")

def test_standard_profile():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_STANDARD)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await _profile_test(ctx, dut, 6, [0, 1, 3])
    sim.add_testbench(proc); sim.run()
    print("  PASS")

def test_server_profile():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await _profile_test(ctx, dut, 8, [0, 1, 2, 3])
    sim.add_testbench(proc); sim.run()
    print("  PASS")

def test_extreme_profile():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_EXTREME)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await _profile_test(ctx, dut, 12, [0, 1, 2, 3])
    sim.add_testbench(proc); sim.run()
    print("  PASS")

# ─── 14. Multi-outstanding with backpressure ─────────────────────────────

def test_multi_outstanding_backpressure():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        ctx.set(dut.iface.comp_ready, 0)
        ctx.set(dut.iface.current_epoch, 1)
        cmds = [(0, 10, R[0]), (1, 11, R[1]),
                (2, 12, R[2]), (3, 13, R[3])]
        for typ, cid, base in cmds:
            await push_cmd(ctx, dut, typ, cid, 1, base)
        for _ in range(20):
            await ctx.tick()
        ctx.set(dut.iface.comp_ready, 1)
        seen = set()
        for _ in range(200):
            if ctx.get(dut.iface.comp_valid):
                cid = ctx.get(dut.iface.comp_correlation_id)
                seen.add(cid)
                await ctx.tick()
                if len(seen) == 4:
                    break
            else:
                await ctx.tick()
        assert seen == {10, 11, 12, 13}, f"missing: {seen}"
    sim.add_testbench(proc); sim.run()
    print("  PASS")
