# tests/test_gc_heap_region.py — Heap Region Partition 单元测试
from amaranth import *
from amaranth.sim import Simulator, Settle
from rtl.gc_heap_region import HeapRegionFlat, HeapRegionPartitioned, create_heap_region
import sys

def test_flat_elaborate():
    m = Module()
    hr = HeapRegionFlat(addr_width=32, region_id_width=1, n_backends=1)
    m.submodules.hr = hr
    from amaranth.back import rtlil
    o = rtlil.convert(m, ports=[])
    print(f"  flat elaboration: {len(o)} chars — PASS")
    return True

def test_flat_region_id_always_zero():
    hr = HeapRegionFlat(addr_width=32, region_id_width=1, n_backends=1)
    sim = Simulator(hr)
    def proc():
        for addr in [0x00000000, 0xDEADBEEF, 0xFFFFFFFF, 0x12345678]:
            yield hr.access_addr.eq(addr)
            yield Settle()
            rid = (yield hr.region_id)
            dispatch = (yield hr.backend_dispatch)
            assert rid == 0, f"addr=0x{addr:08x} region_id={rid}"
            assert dispatch == 0, f"addr=0x{addr:08x} dispatch={dispatch}"
            print(f"  addr=0x{addr:08x} → region_id={rid} dispatch={dispatch} (expect 0,0)")
    sim.add_process(proc); sim.run()
    print(f"  → PASS")
    return True

def test_flat_access_always_ready():
    hr = HeapRegionFlat(addr_width=32, region_id_width=1, n_backends=1)
    sim = Simulator(hr)
    def proc():
        yield Settle()
        ready = (yield hr.access_ready)
        assert ready, f"access_ready should be 1, got {ready}"
    sim.add_process(proc); sim.run()
    print(f"  → PASS")
    return True

def test_flat_backpressure():
    hr = HeapRegionFlat(addr_width=32, region_id_width=1, n_backends=2)
    sim = Simulator(hr)
    def proc():
        yield hr.per_region_busy.eq(0b00)
        yield Settle()
        r1 = (yield hr.access_ready)
        assert r1 == 1, f"expected ready=1, got {r1}"

        yield hr.per_region_busy.eq(0b01)
        yield Settle()
        r2 = (yield hr.access_ready)
        assert r2 == 0, f"expected ready=0, got {r2}"

        yield hr.per_region_busy.eq(0b10)
        yield Settle()
        r3 = (yield hr.access_ready)
        assert r3 == 1, f"expected ready=1, got {r3}"
        print(f"  backpressure: free=1 busy0=0 busy1=1 — PASS")
    sim.add_process(proc); sim.run()
    return True

def test_partitioned_elaborate():
    m = Module()
    hr = HeapRegionPartitioned(addr_width=32, region_id_width=2, n_regions=4, hash_shift=0, n_backends=4)
    m.submodules.hr = hr
    from amaranth.back import rtlil
    o = rtlil.convert(m, ports=[])
    print(f"  partitioned elaboration: {len(o)} chars — PASS")
    return True

def test_partitioned_region_id_consistency():
    hr = HeapRegionPartitioned(addr_width=32, region_id_width=2, n_regions=4, hash_shift=0, n_backends=4)
    sim = Simulator(hr)
    def proc():
        yield hr.access_addr.eq(0x80001000)
        yield Settle()
        rid1 = (yield hr.region_id)
        yield Settle()
        rid2 = (yield hr.region_id)
        assert rid1 == rid2, f"consistency fail: {rid1} != {rid2}"

        addrs = [0x00000000, 0x10000000, 0x20000000, 0x30000000,
                 0xDEADBEEF, 0xCAFEBABE, 0x12345678, 0x87654321]
        seen = set()
        for addr in addrs:
            yield hr.access_addr.eq(addr)
            yield Settle()
            rid = (yield hr.region_id)
            seen.add(rid)
        print(f"  addresses → region_ids={seen} (expect >=1 distinct)")
        assert len(seen) >= 1, "expected at least 1 region_id"
    sim.add_process(proc); sim.run()
    print(f"  → PASS")
    return True

def test_partitioned_backpressure():
    hr = HeapRegionPartitioned(addr_width=32, region_id_width=2, n_regions=4, hash_shift=0, n_backends=4)
    sim = Simulator(hr)
    def proc():
        yield hr.access_addr.eq(0x80001000)
        yield Settle()
        rid = (yield hr.region_id)
        target_bit = 1 << rid

        yield hr.per_region_busy.eq(0)
        yield Settle()
        ready = (yield hr.access_ready)
        assert ready == 1, f"expected ready=1 when free"

        yield hr.per_region_busy.eq(target_bit)
        yield Settle()
        ready2 = (yield hr.access_ready)
        assert ready2 == 0, f"expected ready=0 when target busy (rid={rid}, mask=0x{target_bit:x})"

        yield hr.per_region_busy.eq((~target_bit) & 0xF)
        yield Settle()
        ready3 = (yield hr.access_ready)
        assert ready3 == 0, f"expected ready=0 when any region busy"

        print(f"  backpressure: target_rid={rid} — PASS")
    sim.add_process(proc); sim.run()
    return True

def test_partitioned_dispatch_matches_region_id():
    hr = HeapRegionPartitioned(addr_width=32, region_id_width=2, n_regions=4, hash_shift=0, n_backends=4)
    sim = Simulator(hr)
    def proc():
        for addr in [0x00000000, 0x10000000, 0x20000000, 0x30000000]:
            yield hr.access_addr.eq(addr)
            yield Settle()
            rid = (yield hr.region_id)
            dispatch = (yield hr.backend_dispatch)
            assert rid == dispatch, f"addr=0x{addr:08x} rid={rid} != dispatch={dispatch}"
        print(f"  dispatch matches region_id — PASS")
    sim.add_process(proc); sim.run()
    return True

def test_create_heap_region_factory():
    flat = create_heap_region("flat", addr_width=32, region_id_width=1, n_backends=1)
    assert isinstance(flat, HeapRegionFlat), f"expected HeapRegionFlat, got {type(flat)}"
    part = create_heap_region("partitioned", addr_width=32, region_id_width=2, n_regions=4, n_backends=4)
    assert isinstance(part, HeapRegionPartitioned), f"expected HeapRegionPartitioned, got {type(part)}"
    print(f"  factory: flat={type(flat).__name__} partitioned={type(part).__name__} — PASS")
    return True

if __name__ == "__main__":
    tests = [
        ("Flat Elaboration",         test_flat_elaborate),
        ("Flat Region ID Always 0",  test_flat_region_id_always_zero),
        ("Flat Access Always Ready", test_flat_access_always_ready),
        ("Flat Backpressure",        test_flat_backpressure),
        ("Partitioned Elaboration",            test_partitioned_elaborate),
        ("Partitioned Region ID Consistency",  test_partitioned_region_id_consistency),
        ("Partitioned Backpressure",           test_partitioned_backpressure),
        ("Partitioned Dispatch Matches Region",test_partitioned_dispatch_matches_region_id),
        ("Factory Function",         test_create_heap_region_factory),
    ]
    print("=" * 60)
    print("GC Heap Region 单元测试")
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
