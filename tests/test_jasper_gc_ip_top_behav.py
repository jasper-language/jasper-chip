# tests/test_jasper_gc_ip_top_behav.py
# Behavioral tests for JasperGCIP top-level: event flow, count, epoch/seq/domain preservation.
from amaranth import *; from amaranth.sim import Simulator
from rtl.jasper_gc_config import JasperGCConfig, BackendProfile, DispatchPolicy, MergePolicy, BackpressurePolicy
from rtl.jasper_gc_ip import JasperGCIP


def _top(cfg):
    dut = JasperGCIP(cfg)
    sim = Simulator(dut); sim.add_clock(1e-6)
    return dut, sim


def test_1L_events_flow():
    """Lite: 1 event in, 1 result out."""
    cfg = JasperGCConfig.from_profile(BackendProfile.LITE)
    dut, sim = _top(cfg)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 1); ctx.set(dut.gc_enable, 1)
        ctx.set(dut.gc_result_ready, 1)
        ctx.set(dut.gc_event_valid, 1); ctx.set(dut.gc_event_type, 0)
        ctx.set(dut.gc_event_addr, 0x1000); ctx.set(dut.gc_event_tag, 42)
        ctx.set(dut.gc_event_epoch, 1)
        await ctx.tick(); ctx.set(dut.gc_event_valid, 0)
        for _ in range(60):
            if ctx.get(dut.gc_result_valid):
                print("  PASS")
                return
            await ctx.tick()
        assert False, "no result"
    sim.add_testbench(proc); sim.run()


def test_1L_10_pipelined():
    """Standard: 10 events pipelined (push+drain interleaved)."""
    cfg = JasperGCConfig.from_profile(BackendProfile.STANDARD)
    dut, sim = _top(cfg)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 1); ctx.set(dut.gc_enable, 1)
        ctx.set(dut.gc_result_ready, 1)
        N = 10; drained = 0
        for i in range(N):
            ctx.set(dut.gc_event_valid, 1); ctx.set(dut.gc_event_type, 0)
            ctx.set(dut.gc_event_addr, 0x1000 + i * 4); ctx.set(dut.gc_event_tag, i)
            ctx.set(dut.gc_event_epoch, 1)
            await ctx.tick(); ctx.set(dut.gc_event_valid, 0)
            if ctx.get(dut.gc_result_valid):
                drained += 1
        for _ in range(300):
            if ctx.get(dut.gc_result_valid):
                drained += 1
                if drained >= N: break
            await ctx.tick()
        print("  PASS" if drained == N else f"FAIL: {drained}/{N}")
        assert drained == N
    sim.add_testbench(proc); sim.run()


def test_gateway_single_port_10():
    """Gateway 2L×1: 10 events via port 0, pipelined."""
    cfg = JasperGCConfig.from_profile(BackendProfile.GATEWAY)
    dut, sim = _top(cfg)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 1); ctx.set(dut.gc_enable, 1)
        ctx.set(dut.gc_result_ready, 1)
        N = 10; drained = 0
        for i in range(N):
            ctx.set(dut.gc_event_valid, 1); ctx.set(dut.gc_event_type, 0)
            ctx.set(dut.gc_event_addr, 0x1000 + i * 8); ctx.set(dut.gc_event_tag, i)
            ctx.set(dut.gc_event_epoch, 1)
            await ctx.tick(); ctx.set(dut.gc_event_valid, 0)
            if ctx.get(dut.gc_result_valid):
                drained += 1
        for _ in range(300):
            if ctx.get(dut.gc_result_valid):
                drained += 1
                if drained >= N: break
            await ctx.tick()
        print("  PASS" if drained == N else f"FAIL: {drained}/{N}")
        assert drained == N
    sim.add_testbench(proc); sim.run()


def test_gateway_dual_port_interleaved():
    """Gateway 2L×1: 10 events port0 + 10 events port1 interleaved, all drain."""
    cfg = JasperGCConfig.from_profile(BackendProfile.GATEWAY)
    dut, sim = _top(cfg)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 1); ctx.set(dut.gc_enable, 1)
        ctx.set(dut.gc_result_ready, 1)
        N = 10; drained = 0
        for i in range(N):
            ctx.set(dut.gc_event_valid, 1); ctx.set(dut.gc_event_type, 0)
            ctx.set(dut.gc_event_addr, 0x1000 + i * 8); ctx.set(dut.gc_event_tag, i)
            ctx.set(dut.gc_event_epoch, 1)
            await ctx.tick(); ctx.set(dut.gc_event_valid, 0)
            if ctx.get(dut.gc_result_valid):
                drained += 1
            ctx.set(dut.gc_event1_valid, 1); ctx.set(dut.gc_event1_type, 0)
            ctx.set(dut.gc_event1_addr, 0x1004 + i * 8); ctx.set(dut.gc_event1_tag, i + 10)
            ctx.set(dut.gc_event1_epoch, 1)
            await ctx.tick(); ctx.set(dut.gc_event1_valid, 0)
            if ctx.get(dut.gc_result_valid):
                drained += 1
        for _ in range(500):
            if ctx.get(dut.gc_result_valid):
                drained += 1
                if drained >= N * 2: break
            await ctx.tick()
        print("  PASS" if drained == N * 2 else f"FAIL: {drained}/{N*2}")
        assert drained == N * 2
    sim.add_testbench(proc); sim.run()


def test_cluster_merge_domain():
    """Server Base 2L×2: merge_domain preserved through cluster OrderedMerge."""
    cfg = JasperGCConfig.from_profile(BackendProfile.SERVER_BASE)
    dut, sim = _top(cfg)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 1); ctx.set(dut.gc_enable, 1)
        ctx.set(dut.gc_result_ready, 1)
        ctx.set(dut.gc_event_valid, 1); ctx.set(dut.gc_event_type, 0)
        ctx.set(dut.gc_event_addr, 0x1000); ctx.set(dut.gc_event_tag, 99)
        ctx.set(dut.gc_event_epoch, 1)
        await ctx.tick(); ctx.set(dut.gc_event_valid, 0)
        for _ in range(300):
            if ctx.get(dut.gc_result_valid):
                dm = ctx.get(dut.gc_result_merge_domain)
                print("  PASS" if dm == 0 else f"FAIL: domain={dm}")
                assert dm == 0
                return
            await ctx.tick()
        assert False, "no result"
    sim.add_testbench(proc); sim.run()


def test_cluster_single_event():
    """Server Base 2L×2: single event through full cluster."""
    cfg = JasperGCConfig.from_profile(BackendProfile.SERVER_BASE)
    dut, sim = _top(cfg)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 1); ctx.set(dut.gc_enable, 1)
        ctx.set(dut.gc_result_ready, 1)
        ctx.set(dut.gc_event_valid, 1); ctx.set(dut.gc_event_type, 0)
        ctx.set(dut.gc_event_addr, 0x1000); ctx.set(dut.gc_event_tag, 99)
        ctx.set(dut.gc_event_epoch, 1)
        await ctx.tick(); ctx.set(dut.gc_event_valid, 0)
        for _ in range(300):
            if ctx.get(dut.gc_result_valid):
                print("  PASS")
                return
            await ctx.tick()
        assert False, "no result"
    sim.add_testbench(proc); sim.run()


def test_gateway_dual_tag_epoch_seq():
    """Gateway 2L×1: dual-port events preserve tag/epoch/seq through tile merge."""
    cfg = JasperGCConfig.from_profile(BackendProfile.GATEWAY)
    dut, sim = _top(cfg)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 1); ctx.set(dut.gc_enable, 1)
        ctx.set(dut.gc_result_ready, 1)
        # Port 0: tag=7, epoch=1, seq=1
        ctx.set(dut.gc_event_valid, 1); ctx.set(dut.gc_event_type, 0)
        ctx.set(dut.gc_event_addr, 0x1000); ctx.set(dut.gc_event_tag, 7)
        ctx.set(dut.gc_event_epoch, 1); ctx.set(dut.gc_event_seq, 1)
        await ctx.tick(); ctx.set(dut.gc_event_valid, 0)
        # Interleave drain while pushing port 1
        if ctx.get(dut.gc_result_valid):
            pass  # drain happening
        ctx.set(dut.gc_event1_valid, 1); ctx.set(dut.gc_event1_type, 0)
        ctx.set(dut.gc_event1_addr, 0x2000); ctx.set(dut.gc_event1_tag, 8)
        ctx.set(dut.gc_event1_epoch, 1); ctx.set(dut.gc_event1_seq, 2)
        await ctx.tick(); ctx.set(dut.gc_event1_valid, 0)
        results = {}
        for _ in range(200):
            if ctx.get(dut.gc_result_valid):
                tag = ctx.get(dut.gc_result_tag)
                results[tag] = (ctx.get(dut.gc_result_epoch), ctx.get(dut.gc_result_seq))
                if len(results) >= 2: break
            await ctx.tick()
        ok = results.get(7) == (1, 1) and results.get(8) == (1, 2)
        print("  PASS" if ok else f"FAIL: results={results}")
        assert ok
    sim.add_testbench(proc); sim.run()


def test_cluster_epoch_seq_domain():
    """Server Base 2L×2: epoch/seq/domain preserved through cluster pipeline."""
    cfg = JasperGCConfig.from_profile(BackendProfile.SERVER_BASE)
    dut, sim = _top(cfg)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 3); ctx.set(dut.gc_enable, 1)
        ctx.set(dut.gc_result_ready, 1)
        ctx.set(dut.gc_event_valid, 1); ctx.set(dut.gc_event_type, 0)
        ctx.set(dut.gc_event_addr, 0x1000); ctx.set(dut.gc_event_tag, 99)
        ctx.set(dut.gc_event_epoch, 3); ctx.set(dut.gc_event_seq, 1)
        await ctx.tick(); ctx.set(dut.gc_event_valid, 0)
        for _ in range(300):
            if ctx.get(dut.gc_result_valid):
                ep = ctx.get(dut.gc_result_epoch)
                sq = ctx.get(dut.gc_result_seq)
                dm = ctx.get(dut.gc_result_merge_domain)
                ok = ep == 3 and sq == 1 and dm == 0
                print("  PASS" if ok else f"FAIL: epoch={ep} seq={sq} domain={dm}")
                assert ok
                return
            await ctx.tick()
        assert False, "no result"
    sim.add_testbench(proc); sim.run()


def test_cluster_same_domain_ordering():
    """Gateway 2L×1: 2 events to same domain drain in injection order.
    Gateway uses single 2L tile without cluster — tile merge preserves order."""
    cfg = JasperGCConfig.from_profile(BackendProfile.GATEWAY)
    dut, sim = _top(cfg)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 1); ctx.set(dut.gc_enable, 1)
        ctx.set(dut.gc_result_ready, 1)
        order = []
        for tag in [10, 11]:
            ctx.set(dut.gc_event_valid, 1); ctx.set(dut.gc_event_type, 0)
            ctx.set(dut.gc_event_addr, 0x1000 + tag * 4)
            ctx.set(dut.gc_event_tag, tag); ctx.set(dut.gc_event_epoch, 1)
            await ctx.tick(); ctx.set(dut.gc_event_valid, 0)
            for _ in range(30):
                if ctx.get(dut.gc_result_valid):
                    order.append(ctx.get(dut.gc_result_tag))
                    break
                await ctx.tick()
        ok = order == [10, 11]
        print("  PASS" if ok else f"FAIL: order={order}")
        assert ok
    sim.add_testbench(proc); sim.run()


def test_cluster_cross_domain_parallel():
    """Server Base 2L×2: events to different domains both drain.
    addr=0x0000 → port 0 (tile0 lane0, domain 0)
    addr=0x0002 → port 2 (tile1 lane0, domain 1)"""
    cfg = JasperGCConfig.from_profile(BackendProfile.SERVER_BASE)
    dut, sim = _top(cfg)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 1); ctx.set(dut.gc_enable, 1)
        ctx.set(dut.gc_result_ready, 1)
        domains = set()
        ctx.set(dut.gc_event_valid, 1); ctx.set(dut.gc_event_type, 0)
        ctx.set(dut.gc_event_addr, 0x0000); ctx.set(dut.gc_event_tag, 10)
        ctx.set(dut.gc_event_epoch, 1); ctx.set(dut.core_id, 0)
        await ctx.tick(); ctx.set(dut.gc_event_valid, 0)
        for _ in range(60):
            if ctx.get(dut.gc_result_valid):
                domains.add(ctx.get(dut.gc_result_merge_domain))
                break
            await ctx.tick()
        ctx.set(dut.gc_event_valid, 1); ctx.set(dut.gc_event_type, 0)
        ctx.set(dut.gc_event_addr, 0x0002); ctx.set(dut.gc_event_tag, 20)
        ctx.set(dut.gc_event_epoch, 1); ctx.set(dut.core_id, 1)
        await ctx.tick(); ctx.set(dut.gc_event_valid, 0)
        for _ in range(60):
            if ctx.get(dut.gc_result_valid):
                domains.add(ctx.get(dut.gc_result_merge_domain))
                break
            await ctx.tick()
        ok = len(domains) == 2
        print("  PASS" if ok else f"FAIL: domains={domains}")
        assert ok
    sim.add_testbench(proc); sim.run()


