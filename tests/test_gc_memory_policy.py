# tests/test_gc_memory_policy.py — GC 内存策略单元测试
from amaranth import *
from amaranth.sim import Simulator, Tick
from rtl.gc_memory_policy import GCMemoryPolicy, GCMemoryPolicyParams
import sys

def test_elaboration():
    """验证模块可以 elaboration"""
    m = Module()
    mp = GCMemoryPolicy()
    m.submodules.mp = mp
    from amaranth.back import rtlil
    o = rtlil.convert(m, ports=[])
    print(f"  elaboration: {len(o)} chars — PASS")
    return True

def test_bypass_signal():
    """验证 bypass 策略输出"""
    p = GCMemoryPolicyParams(dcache_bypass_enable=True, bypass_gc_scan=True)
    mp = GCMemoryPolicy(p)
    sim = Simulator(mp); sim.add_clock(1e-6)
    def proc():
        # GC_SCAN access → should bypass
        yield mp.access_valid.eq(1)
        yield mp.access_source.eq(1)  # GC_SCAN
        yield mp.access_addr.eq(0x80001000)
        yield Tick()
        bypass = (yield mp.bypass_dcache)
        print(f"  bypass_dcache(scan): {bypass} — {'PASS' if bypass else 'FAIL'}")
        assert bypass, "GC_SCAN should bypass"

        # MUTATOR access → should NOT bypass
        yield mp.access_source.eq(0)
        yield Tick()
        bypass2 = (yield mp.bypass_dcache)
        print(f"  bypass_dcache(mut):  {bypass2} — {'PASS' if not bypass2 else 'FAIL'}")
        assert not bypass2, "MUTATOR should not bypass"
    sim.add_sync_process(proc); sim.run()
    return True

def test_metadata_cache_hit():
    """验证 metadata cache hit/miss/replacement"""
    p = GCMemoryPolicyParams(
        metadata_cache_enable=True,
        metadata_cache_size=1024,   # 16 sets × 2 ways × 32B line
        metadata_cache_ways=2,
        metadata_cache_line_size=32,
    )
    mp = GCMemoryPolicy(p)
    sim = Simulator(mp); sim.add_clock(1e-6)
    def proc():
        # Access with source=MUTATOR → should not use metadata cache
        yield mp.access_valid.eq(1)
        yield mp.access_source.eq(0)  # MUTATOR
        yield mp.access_addr.eq(0x80001000)
        yield Tick()
        use = (yield mp.use_metadata_cache)
        hit = (yield mp.metadata_cache_hit)
        print(f"  meta cache (mut): use={use} hit={hit} — {'PASS' if not use else 'FAIL'}")
        assert not use, "MUTATOR should not use metadata cache"

        # Access with source=GC_META → should use metadata cache
        yield mp.access_source.eq(5)  # GC_META
        yield Tick()
        use2 = (yield mp.use_metadata_cache)
        hit2 = (yield mp.metadata_cache_hit)
        print(f"  meta cache (meta): use={use2} hit={hit2} — {'PASS' if use2 and not hit2 else 'FAIL'}")
        assert use2, "GC_META should use metadata cache"
        assert not hit2, "Should miss (cold)"

        # Miss → fill via dmem response
        yield mp.dmem_rsp_valid.eq(1)
        yield mp.dmem_rsp_data.eq(0xABCD)
        yield Tick()
        yield Tick()
        yield Tick()
        yield mp.dmem_rsp_valid.eq(0)

        # Access again → should hit
        yield mp.access_addr.eq(0x80001000)
        yield Tick()
        hit3 = (yield mp.metadata_cache_hit)
        data = (yield mp.metadata_cache_data)
        print(f"  meta cache (hit):  hit={hit3} data=0x{data:04x} — {'PASS' if hit3 and data == 0xABCD else 'FAIL'}")
        assert hit3, "Should hit after fill"
        assert data == 0xABCD, f"Data mismatch: 0x{data:04x}"

        # Write update
        yield mp.access_is_write.eq(1)
        yield mp.access_data.eq(0x1234)
        yield Tick()
        yield mp.access_is_write.eq(0)

        # Read back → should get updated value
        yield mp.access_addr.eq(0x80001000)
        yield Tick()
        hit4 = (yield mp.metadata_cache_hit)
        data4 = (yield mp.metadata_cache_data)
        print(f"  meta cache (write): hit={hit4} data=0x{data4:04x} — {'PASS' if hit4 and data4 == 0x1234 else 'FAIL'}")
        assert hit4 and data4 == 0x1234, f"Write update failed: 0x{data4:04x}"

    sim.add_sync_process(proc); sim.run()
    return True

def test_stream_buffer():
    """验证 stream buffer: seq hit, bypass 互斥"""
    ok = True
    
    # 1. Seq → hit
    p = GCMemoryPolicyParams(stream_buffer_enable=True, stream_buffer_entries=4,
        dcache_bypass_enable=False, bypass_gc_scan=False)
    mp = GCMemoryPolicy(p); sim = Simulator(mp); sim.add_clock(1e-6)
    def t1():
        nonlocal ok
        yield mp.access_source.eq(1); yield mp.access_valid.eq(1)
        yield mp.access_addr.eq(0x80001000); yield Tick()
        yield mp.access_addr.eq(0x80001040); yield Tick()  # seq → fill (prefetches 0x80001080)
        yield mp.access_addr.eq(0x80001080); yield Tick()  # access prefetched → HIT!
        h = (yield mp.stream_buffer_hit)
        ok &= h == 1
        print(f"  stream (seq):   hit={h} (expect 1) {'PASS' if h else 'FAIL'}")

        yield mp.access_addr.eq(0x90000000); yield Tick()  # non-seq → miss
        h2 = (yield mp.stream_buffer_hit)
        ok &= h2 == 0
        print(f"  stream (non-s): hit={h2} (expect 0) {'PASS' if not h2 else 'FAIL'}")
    sim.add_sync_process(t1); sim.run()

    # 2. Bypass → no hit
    p2 = GCMemoryPolicyParams(stream_buffer_enable=True, stream_buffer_entries=4,
        dcache_bypass_enable=True, bypass_gc_scan=True)
    mp2 = GCMemoryPolicy(p2); sim2 = Simulator(mp2); sim2.add_clock(1e-6)
    def t2():
        nonlocal ok
        yield mp2.access_source.eq(1); yield mp2.access_valid.eq(1)
        yield mp2.access_addr.eq(0x80001000); yield Tick()
        yield mp2.access_addr.eq(0x80001040); yield Tick()
        yield mp2.access_addr.eq(0x80001080); yield Tick()
        h = (yield mp2.stream_buffer_hit)
        ok &= h == 0
        print(f"  stream (bypass):hit={h} (expect 0) {'PASS' if not h else 'FAIL'}")
    sim2.add_sync_process(t2); sim2.run()
    return ok

def test_cache_partition():
    """验证 partition 策略输出"""
    p = GCMemoryPolicyParams(cache_partition_enable=True, mutator_reserved_ways=6, gc_reserved_ways=2)
    mp = GCMemoryPolicy(p)
    sim = Simulator(mp); sim.add_clock(1e-6)
    def proc():
        yield Tick()
        mw = (yield mp.reserved_mutator_ways)
        gw = (yield mp.reserved_gc_ways)
        print(f"  partition: mut={mw} gc={gw} — {'PASS' if mw == 6 and gw == 2 else 'FAIL'}")
        assert mw == 6, f"mutator_ways: {mw}"
        assert gw == 2, f"gc_ways: {gw}"

        # Disabled
        p2 = GCMemoryPolicyParams(cache_partition_enable=False)
        mp2 = GCMemoryPolicy(p2)
        s2 = Simulator(mp2); s2.add_clock(1e-6)
        def p2p():
            yield Tick()
            mw2 = (yield mp2.reserved_mutator_ways)
            assert mw2 == 0, f"disabled should be 0: {mw2}"
            print(f"  partition (off): mut={mw2} — PASS")
        s2.add_sync_process(p2p); s2.run()
    sim.add_sync_process(proc); sim.run()
    return True

if __name__ == "__main__":
    tests = [
        ("Elaboration", test_elaboration),
        ("Bypass Signal", test_bypass_signal),
        ("Metadata Cache Hit/Miss", test_metadata_cache_hit),
        ("Stream Buffer", test_stream_buffer),
        ("Cache Partition", test_cache_partition),
    ]
    print("=" * 60)
    print("GC Memory Policy 单元测试")
    print("=" * 60)
    all_ok = True
    for name, fn in tests:
        print(f"\n[{name}]")
        try:
            ok = fn()
            print(f"  → {'PASS' if ok else 'FAIL'}")
            all_ok &= ok
        except Exception as e:
            print(f"  → FAIL: {e}")
            all_ok = False
    print(f"\n{'='*60}")
    print(f"{'ALL PASS' if all_ok else 'SOME FAILED'}")
    sys.exit(0 if all_ok else 1)
