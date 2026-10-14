# tests/test_gc_backend_merge.py — Backend Merge 单元测试
from amaranth import *
from amaranth.sim import Simulator, Tick, Settle
from rtl.gc_backend_merge import BackendMergeSingle, BackendMergeMulti, create_backend_merge
import sys

def test_single_elaborate():
    m = Module()
    bm = BackendMergeSingle(data_width=32, tag_width=8, backend_count=1)
    m.submodules.bm = bm
    from amaranth.back import rtlil
    o = rtlil.convert(m, ports=[])
    print(f"  single elaboration: {len(o)} chars — PASS")

def test_single_passthrough():
    bm = BackendMergeSingle(data_width=32, tag_width=8, backend_count=1)
    sim = Simulator(bm)
    sim.add_clock(1e-6)
    async def proc(ctx):
        ctx.set(bm.event_valid, 1)
        ctx.set(bm.event_addr, 0xDEAD)
        ctx.set(bm.event_tag, 0x42)
        ctx.set(bm.result_ready, 1)
        await ctx.tick()
        ev = ctx.get(bm.event_ready)
        rv = ctx.get(bm.result_valid)
        rd = ctx.get(bm.result_data)
        rt = ctx.get(bm.result_tag)
        assert ev == 1, f"event_ready={ev}"
        assert rv == 1, f"result_valid={rv}"
        assert rd == 0xDEAD, f"result_data=0x{rd:04x}"
        assert rt == 0x42, f"result_tag=0x{rt:02x}"
        print(f"  event_ready={ev} result_valid={rv} result_data=0x{rd:04x} result_tag=0x{rt:02x} — PASS")
    sim.add_testbench(proc); sim.run()

def test_multi_elaborate():
    m = Module()
    bm = BackendMergeMulti(data_width=32, tag_width=8, backend_count=4, source_width=8)
    m.submodules.bm = bm
    from amaranth.back import rtlil
    o = rtlil.convert(m, ports=[])
    print(f"  multi elaboration: {len(o)} chars — PASS")

def test_multi_one_backend():
    bm = BackendMergeMulti(data_width=32, tag_width=8, backend_count=1, source_width=8)
    sim = Simulator(bm); sim.add_clock(1e-6)
    def proc():
        yield bm.event_valid.eq(1)
        yield bm.event_addr.eq(0xCAFE)
        yield bm.event_tag.eq(0x77)
        yield bm.dispatch_policy.eq(0)
        yield bm.merge_policy.eq(0)
        yield Tick()
        rv = (yield bm.result_valid)
        rd = (yield bm.result_data)
        rt = (yield bm.result_tag)
        assert rv == 1, f"result_valid={rv}"
        assert rd == 0xCAFE, f"result_data=0x{rd:04x}"
        assert rt == 0x77, f"result_tag=0x{rt:02x}"
        print(f"  multi(1): valid={rv} data=0x{rd:04x} tag=0x{rt:02x} — PASS")
    sim.add_process(proc); sim.run()

def test_multi_round_robin_dispatch():
    bm = BackendMergeMulti(data_width=32, tag_width=8, backend_count=4, source_width=8)
    sim = Simulator(bm); sim.add_clock(1e-6)
    def proc():
        yield bm.dispatch_policy.eq(0)
        yield bm.merge_policy.eq(0)
        yield bm.backend_busy.eq(0)
        for i in range(8):
            yield bm.event_valid.eq(1)
            yield bm.event_addr.eq(0x1000 + i)
            yield Tick()
            ready = (yield bm.event_ready)
            rv = (yield bm.result_valid)
            assert ready == 1, f"event {i}: not ready"
            assert rv == 1, f"event {i}: result not valid"
        yield bm.event_valid.eq(0)
        yield Tick()
        print(f"  8 round_robin events accepted — PASS")
    sim.add_process(proc); sim.run()

def test_multi_hash_lsb_dispatch():
    bm = BackendMergeMulti(data_width=32, tag_width=8, backend_count=4, source_width=8)
    sim = Simulator(bm); sim.add_clock(1e-6)
    def proc():
        yield bm.dispatch_policy.eq(1)
        yield bm.merge_policy.eq(0)
        yield bm.backend_busy.eq(0)
        for addr in [0x0000, 0x0001, 0x0002, 0x0003, 0x0004, 0x0005]:
            yield bm.event_addr.eq(addr)
            yield bm.event_valid.eq(1)
            yield Tick()
            ready = (yield bm.event_ready)
            assert ready == 1, f"addr=0x{addr:04x} not ready"
        yield bm.event_valid.eq(0)
        yield Tick()
        print(f"  hash_lsb events accepted — PASS")
    sim.add_process(proc); sim.run()

def test_multi_broadcast():
    bm = BackendMergeMulti(data_width=32, tag_width=8, backend_count=4, source_width=8)
    sim = Simulator(bm); sim.add_clock(1e-6)
    def proc():
        yield bm.dispatch_policy.eq(2)
        yield bm.merge_policy.eq(0)
        yield bm.backend_busy.eq(0)
        yield bm.event_valid.eq(1)
        yield bm.event_addr.eq(0x1234)
        yield Tick()
        ready = (yield bm.event_ready)
        assert ready == 1, "broadcast not ready"
        print(f"  broadcast event accepted — PASS")
    sim.add_process(proc); sim.run()

def test_multi_affinity():
    bm = BackendMergeMulti(data_width=32, tag_width=8, backend_count=4, source_width=8)
    sim = Simulator(bm); sim.add_clock(1e-6)
    def proc():
        yield bm.dispatch_policy.eq(3)
        yield bm.merge_policy.eq(0)
        yield bm.backend_busy.eq(0)
        for src in [0, 1, 2, 3]:
            yield bm.event_source.eq(src)
            yield bm.event_valid.eq(1)
            yield Tick()
            ready = (yield bm.event_ready)
            assert ready == 1, f"src={src} not ready"
        yield bm.event_valid.eq(0)
        yield Tick()
        print(f"  affinity events accepted — PASS")
    sim.add_process(proc); sim.run()

def test_multi_merge_none():
    bm = BackendMergeMulti(data_width=32, tag_width=8, backend_count=4, source_width=8)
    sim = Simulator(bm); sim.add_clock(1e-6)
    def proc():
        yield bm.dispatch_policy.eq(0)
        yield bm.merge_policy.eq(0)
        yield bm.backend_busy.eq(0)
        yield bm.event_valid.eq(1)
        yield bm.event_addr.eq(0xABCD)
        yield bm.event_tag.eq(0x99)
        yield Tick()
        rd = (yield bm.result_data)
        rt = (yield bm.result_tag)
        assert rd == 0xABCD, f"data=0x{rd:04x}"
        assert rt == 0x99, f"tag=0x{rt:02x}"
        print(f"  merge(none): data=0x{rd:04x} tag=0x{rt:02x} — PASS")
    sim.add_process(proc); sim.run()

def test_multi_backpressure():
    bm = BackendMergeMulti(data_width=32, tag_width=8, backend_count=4, source_width=8)
    sim = Simulator(bm); sim.add_clock(1e-6)
    def proc():
        yield bm.dispatch_policy.eq(0)
        yield bm.merge_policy.eq(0)
        yield bm.event_valid.eq(1)
        yield bm.backend_busy.eq(0b0001)
        yield Tick()
        ready = (yield bm.event_ready)
        assert ready == 0, f"expected not ready when backend 0 busy, got {ready}"

        yield bm.backend_busy.eq(0b0000)
        yield Tick()
        ready2 = (yield bm.event_ready)
        assert ready2 == 1, f"expected ready when backend 0 free, got {ready2}"

        print(f"  backpressure: busy→{ready} free→{ready2} — PASS")
    sim.add_process(proc); sim.run()

def test_factory():
    single = create_backend_merge("single", data_width=32, tag_width=8, backend_count=1)
    assert isinstance(single, BackendMergeSingle), f"expected BackendMergeSingle, got {type(single)}"
    multi = create_backend_merge("multi", data_width=32, tag_width=8, backend_count=4, source_width=8)
    assert isinstance(multi, BackendMergeMulti), f"expected BackendMergeMulti, got {type(multi)}"
    print(f"  factory: single={type(single).__name__} multi={type(multi).__name__} — PASS")

if __name__ == "__main__":
    tests = [
        ("Single Elaborate",         test_single_elaborate),
        ("Single Passthrough",       test_single_passthrough),
        ("Multi Elaborate",          test_multi_elaborate),
        ("Multi(1) like Single",     test_multi_one_backend),
        ("Round Robin Dispatch",     test_multi_round_robin_dispatch),
        ("Hash LSB Dispatch",        test_multi_hash_lsb_dispatch),
        ("Broadcast",                test_multi_broadcast),
        ("Affinity Dispatch",        test_multi_affinity),
        ("Merge None",               test_multi_merge_none),
        ("Backpressure",             test_multi_backpressure),
        ("Factory",                  test_factory),
    ]
    print("=" * 60)
    print("GC Backend Merge 单元测试")
    print("=" * 60)
    all_ok = True
    for name, fn in tests:
        print(f"\n[{name}]")
        try:
            ok = fn()
            if ok is not None:
                print(f"  → {'PASS' if ok else 'FAIL'}")
                all_ok &= ok
        except Exception as e:
            import traceback
            print(f"  → FAIL: {e}")
            traceback.print_exc()
            all_ok = False
    print(f"\n{'='*60}")
    print(f"{'ALL PASS' if all_ok else 'SOME FAILED'}")
    sys.exit(0 if all_ok else 1)
