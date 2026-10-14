# tests/test_jasper_gc_compact_engine.py
from amaranth import *; from amaranth.sim import Simulator
from amaranth.back import rtlil
from rtl.jasper_gc_compact_engine import CompactEngine


def test_elab():
    m = Module(); m.submodules.ce = CompactEngine(step_size=64)
    rtlil.convert(m, ports=[]); print("  OK")


def test_zero_size():
    ce = CompactEngine(step_size=64)
    sim = Simulator(ce); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ce.in_valid, 1); ctx.set(ce.in_correlation_id, 10)
        ctx.set(ce.in_region_base, 0x1000); ctx.set(ce.in_region_size, 0)
        ctx.set(ce.out_ready, 1)
        await ctx.tick(); ctx.set(ce.in_valid, 0)
        await ctx.tick()
        assert ctx.get(ce.out_valid) == 1
        assert ctx.get(ce.out_objects_moved) == 0
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_one_step():
    ce = CompactEngine(step_size=64)
    sim = Simulator(ce); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ce.in_valid, 1); ctx.set(ce.in_correlation_id, 42)
        ctx.set(ce.in_region_base, 0x1000); ctx.set(ce.in_region_size, 32)
        ctx.set(ce.out_ready, 1)
        await ctx.tick(); ctx.set(ce.in_valid, 0)
        await ctx.tick()
        assert ctx.get(ce.out_valid) == 1
        assert ctx.get(ce.out_correlation_id) == 42
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_multi_step():
    ce = CompactEngine(step_size=64)
    sim = Simulator(ce); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ce.in_valid, 1); ctx.set(ce.in_correlation_id, 10)
        ctx.set(ce.in_region_base, 0x1000); ctx.set(ce.in_region_size, 256)
        ctx.set(ce.out_ready, 1)
        await ctx.tick(); ctx.set(ce.in_valid, 0)
        for _ in range(15):
            if ctx.get(ce.out_valid):
                assert ctx.get(ce.out_bytes_scanned) == 256
                break
            await ctx.tick()
        else:
            assert False, "no completion"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_backpressure():
    ce = CompactEngine(step_size=64)
    sim = Simulator(ce); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ce.in_valid, 1); ctx.set(ce.in_correlation_id, 99)
        ctx.set(ce.in_region_base, 0x1000); ctx.set(ce.in_region_size, 64)
        ctx.set(ce.out_ready, 0)
        await ctx.tick(); ctx.set(ce.in_valid, 0)
        for _ in range(10):
            if ctx.get(ce.out_valid): break
            await ctx.tick()
        assert ctx.get(ce.out_valid) == 1
        assert ctx.get(ce.busy) == 1
        ctx.set(ce.out_ready, 1)
        await ctx.tick()
        assert ctx.get(ce.out_valid) == 0
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_cid_epoch_domain():
    ce = CompactEngine(step_size=64)
    sim = Simulator(ce); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ce.in_valid, 1); ctx.set(ce.in_correlation_id, 77)
        ctx.set(ce.in_epoch, 5); ctx.set(ce.in_merge_domain, 3)
        ctx.set(ce.in_region_base, 0x1000); ctx.set(ce.in_region_size, 64)
        ctx.set(ce.out_ready, 1)
        await ctx.tick(); ctx.set(ce.in_valid, 0)
        await ctx.tick()
        assert ctx.get(ce.out_correlation_id) == 77
        assert ctx.get(ce.out_epoch) == 5
        assert ctx.get(ce.out_merge_domain) == 3
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_moved_stats():
    ce = CompactEngine(step_size=64, move_ratio=0.7)
    sim = Simulator(ce); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ce.in_valid, 1); ctx.set(ce.in_correlation_id, 10)
        ctx.set(ce.in_region_base, 0x1000); ctx.set(ce.in_region_size, 128)
        ctx.set(ce.out_ready, 1)
        await ctx.tick(); ctx.set(ce.in_valid, 0)
        for _ in range(15):
            if ctx.get(ce.out_valid):
                assert ctx.get(ce.out_objects_moved) >= 0
                assert ctx.get(ce.out_metadata_updates) >= 1
                break
            await ctx.tick()
        else:
            assert False, "no completion"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_busy_during_compact():
    ce = CompactEngine(step_size=64)
    sim = Simulator(ce); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ce.in_valid, 1); ctx.set(ce.in_correlation_id, 10)
        ctx.set(ce.in_region_base, 0x1000); ctx.set(ce.in_region_size, 256)
        ctx.set(ce.out_ready, 1)
        await ctx.tick(); ctx.set(ce.in_valid, 0)
        assert ctx.get(ce.in_ready) == 0
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_back_to_back():
    ce = CompactEngine(step_size=64)
    sim = Simulator(ce); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(ce.out_ready, 1)
        for cid in [10, 20]:
            ctx.set(ce.in_valid, 1); ctx.set(ce.in_correlation_id, cid)
            ctx.set(ce.in_region_base, 0x1000); ctx.set(ce.in_region_size, 64)
            await ctx.tick(); ctx.set(ce.in_valid, 0)
            await ctx.tick()
            assert ctx.get(ce.out_valid) == 1
            await ctx.tick()
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_no_dup():
    ce = CompactEngine(step_size=64)
    sim = Simulator(ce); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(ce.out_ready, 1)
        cids = []
        for i in range(4):
            ctx.set(ce.in_valid, 1); ctx.set(ce.in_correlation_id, i)
            ctx.set(ce.in_region_base, 0x1000); ctx.set(ce.in_region_size, 64)
            await ctx.tick(); ctx.set(ce.in_valid, 0)
            await ctx.tick()
            assert ctx.get(ce.out_valid) == 1
            cids.append(ctx.get(ce.out_correlation_id))
            await ctx.tick()
        assert len(set(cids)) == 4
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_compact_writeback():
    ce = CompactEngine(step_size=64, move_ratio=0.7)
    sim = Simulator(ce); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ce.in_valid, 1); ctx.set(ce.in_correlation_id, 42)
        ctx.set(ce.in_region_base, 0x1000); ctx.set(ce.in_region_size, 128)
        ctx.set(ce.out_ready, 1)
        ctx.set(ce.mem_req_ready, 1)
        await ctx.tick(); ctx.set(ce.in_valid, 0)
        writes_seen = 0
        for _ in range(30):
            if ctx.get(ce.relocation_active):
                if ctx.get(ce.mem_req_valid) and ctx.get(ce.mem_req_is_write):
                    writes_seen += 1
            if ctx.get(ce.out_valid):
                break
            await ctx.tick()
        assert writes_seen > 0, f"expected writes, got {writes_seen}"
        assert writes_seen == ctx.get(ce.out_objects_moved)
        print(f"  PASS (writes={writes_seen})")
    sim.add_testbench(proc); sim.run()


def test_compact_writeback_count():
    ce = CompactEngine(step_size=64, move_ratio=0.7)
    sim = Simulator(ce); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ce.in_valid, 1); ctx.set(ce.in_correlation_id, 7)
        ctx.set(ce.in_region_base, 0x2000); ctx.set(ce.in_region_size, 256)
        ctx.set(ce.out_ready, 1)
        ctx.set(ce.mem_req_ready, 1)
        await ctx.tick(); ctx.set(ce.in_valid, 0)
        for _ in range(30):
            if ctx.get(ce.out_valid):
                assert ctx.get(ce.relocation_count) == ctx.get(ce.out_objects_moved)
                assert ctx.get(ce.relocation_count) > 0
                break
            await ctx.tick()
        else:
            assert False, "no completion"
        print(f"  PASS (relocation_count={ctx.get(ce.relocation_count)})")
    sim.add_testbench(proc); sim.run()


def test_compact_writeback_addr():
    ce = CompactEngine(step_size=64, move_ratio=0.7)
    sim = Simulator(ce); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ce.in_valid, 1); ctx.set(ce.in_correlation_id, 0xAA)
        ctx.set(ce.in_region_base, 0x1000); ctx.set(ce.in_region_size, 128)
        ctx.set(ce.out_ready, 1)
        ctx.set(ce.mem_req_ready, 1)
        ctx.set(ce.reloc_base_addr, 0x2000)
        ctx.set(ce.object_size, 64)
        await ctx.tick(); ctx.set(ce.in_valid, 0)
        write_addrs = []
        for _ in range(30):
            if ctx.get(ce.relocation_active) and ctx.get(ce.mem_req_valid) and ctx.get(ce.mem_req_is_write):
                write_addrs.append(ctx.get(ce.mem_req_addr))
            if ctx.get(ce.out_valid):
                break
            await ctx.tick()
        assert len(write_addrs) > 0
        for i, addr in enumerate(write_addrs):
            assert addr == 0x2000 + i * 64, f"addr[{i}]={addr:#x} != expected {0x2000 + i * 64:#x}"
        print(f"  PASS (addrs={[hex(a) for a in write_addrs]})")
    sim.add_testbench(proc); sim.run()


def test_compact_writeback_no_reloc():
    ce = CompactEngine(step_size=64, move_ratio=0.3)
    sim = Simulator(ce); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ce.in_valid, 1); ctx.set(ce.in_correlation_id, 42)
        ctx.set(ce.in_region_base, 0x1000); ctx.set(ce.in_region_size, 128)
        ctx.set(ce.out_ready, 1)
        ctx.set(ce.mem_req_ready, 1)
        await ctx.tick(); ctx.set(ce.in_valid, 0)
        reloc_seen = False
        for _ in range(15):
            if ctx.get(ce.relocation_active):
                reloc_seen = True
            if ctx.get(ce.out_valid):
                break
            await ctx.tick()
        assert not reloc_seen, "relocation_active should not assert"
        assert ctx.get(ce.relocation_count) == 0
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_compact_writeback_backpressure():
    ce = CompactEngine(step_size=64, move_ratio=0.7)
    sim = Simulator(ce); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ce.in_valid, 1); ctx.set(ce.in_correlation_id, 42)
        ctx.set(ce.in_region_base, 0x1000); ctx.set(ce.in_region_size, 192)
        ctx.set(ce.out_ready, 1)
        ctx.set(ce.mem_req_ready, 0)
        await ctx.tick(); ctx.set(ce.in_valid, 0)
        # Wait for relocation phase
        for _ in range(20):
            if ctx.get(ce.relocation_active):
                break
            await ctx.tick()
        assert ctx.get(ce.relocation_active), "never entered relocation"
        assert ctx.get(ce.mem_req_valid)
        # Release with backpressure: assert writes can't flow
        assert ctx.get(ce.mem_req_valid), "write should be pending"
        # Now allow one write
        ctx.set(ce.mem_req_ready, 1)
        await ctx.tick()
        ctx.set(ce.mem_req_ready, 0)
        await ctx.tick()
        # Verify at least one write went through
        writes = 0
        for _ in range(30):
            if ctx.get(ce.relocation_active) and ctx.get(ce.mem_req_valid) and ctx.get(ce.mem_req_is_write):
                writes += 1
            if ctx.get(ce.out_valid):
                break
            await ctx.tick()
        assert writes > 0, "no writes with backpressure"
        print(f"  PASS (writes={writes})")
    sim.add_testbench(proc); sim.run()


def test_forwarding_table_seq_addr():
    ce = CompactEngine(step_size=64, move_ratio=0.7)
    sim = Simulator(ce); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ce.in_valid, 1); ctx.set(ce.in_correlation_id, 10)
        ctx.set(ce.in_region_base, 0x1000); ctx.set(ce.in_region_size, 256)
        ctx.set(ce.out_ready, 1)
        ctx.set(ce.mem_req_ready, 1)
        ctx.set(ce.reloc_base_addr, 0x3000)
        ctx.set(ce.object_size, 128)
        await ctx.tick(); ctx.set(ce.in_valid, 0)
        write_addrs = []
        for _ in range(30):
            if ctx.get(ce.relocation_active) and ctx.get(ce.mem_req_valid) and ctx.get(ce.mem_req_is_write):
                write_addrs.append(ctx.get(ce.mem_req_addr))
            if ctx.get(ce.out_valid):
                break
            await ctx.tick()
        assert len(write_addrs) > 0
        for i, addr in enumerate(write_addrs):
            assert addr == 0x3000 + i * 128, f"addr[{i}]={addr:#x}"
        print(f"  PASS (addrs={[hex(a) for a in write_addrs]})")
    sim.add_testbench(proc); sim.run()


def test_forwarding_table_overflow():
    ce = CompactEngine(step_size=64, move_ratio=0.7, reloc_table_depth=2)
    sim = Simulator(ce); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ce.in_valid, 1); ctx.set(ce.in_correlation_id, 10)
        ctx.set(ce.in_region_base, 0x1000); ctx.set(ce.in_region_size, 512)
        ctx.set(ce.out_ready, 1)
        ctx.set(ce.mem_req_ready, 1)
        ctx.set(ce.reloc_base_addr, 0x4000)
        ctx.set(ce.object_size, 64)
        await ctx.tick(); ctx.set(ce.in_valid, 0)
        writes = 0
        for _ in range(50):
            if ctx.get(ce.relocation_active) and ctx.get(ce.mem_req_valid) and ctx.get(ce.mem_req_is_write):
                writes += 1
            if ctx.get(ce.out_valid):
                break
            await ctx.tick()
        assert writes == 2, f"expected 2 writes (table depth=2), got {writes}"
        print(f"  PASS (writes={writes})")
    sim.add_testbench(proc); sim.run()


def test_reloc_base_addr_configurable():
    for base in [0x0, 0x5000, 0x10000]:
        ce = CompactEngine(step_size=64, move_ratio=0.7)
        sim = Simulator(ce); sim.add_clock(1e-6)
        async def proc(ctx):
            await ctx.tick()
            ctx.set(ce.in_valid, 1); ctx.set(ce.in_correlation_id, 10)
            ctx.set(ce.in_region_base, 0x1000); ctx.set(ce.in_region_size, 128)
            ctx.set(ce.out_ready, 1)
            ctx.set(ce.mem_req_ready, 1)
            ctx.set(ce.reloc_base_addr, base)
            ctx.set(ce.object_size, 64)
            await ctx.tick(); ctx.set(ce.in_valid, 0)
            write_addrs = []
            for _ in range(30):
                if ctx.get(ce.relocation_active) and ctx.get(ce.mem_req_valid) and ctx.get(ce.mem_req_is_write):
                    write_addrs.append(ctx.get(ce.mem_req_addr))
                if ctx.get(ce.out_valid):
                    break
                await ctx.tick()
            assert len(write_addrs) > 0
            for i, addr in enumerate(write_addrs):
                assert addr == base + i * 64, f"base={base:#x}: addr[{i}]={addr:#x}"
        sim.add_testbench(proc); sim.run()
    print(f"  PASS (bases=[0x0, 0x5000, 0x10000])")
