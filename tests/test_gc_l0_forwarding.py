# tests/test_gc_l0_forwarding.py
from amaranth import *
from amaranth.sim import Simulator, Tick, Delay
from rtl.gc_l0_forwarding import L0ForwardingDisabled, L0ForwardingEnabled


def _run_sync(dut, proc):
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_testbench(proc)
    sim.run()


def _run_comb(dut, proc):
    sim = Simulator(dut)
    sim.add_process(proc)
    sim.run()


def test_disabled_always_miss():
    dut = L0ForwardingDisabled()

    def proc():
        yield dut.query_valid.eq(1)
        yield dut.query_old_ptr.eq(0x1234)
        yield Delay()

        assert (yield dut.rsp_valid) == 1
        assert (yield dut.rsp_hit) == 0
        assert (yield dut.rsp_new_ptr) == 0x1234
        assert (yield dut.query_ready) == 1
        assert (yield dut.update_ready) == 1

    _run_comb(dut, proc)
    print("  disabled_always_miss: PASS")


def test_enabled_hit_miss():
    dut = L0ForwardingEnabled(entries=4)

    def proc():
        yield dut.update_valid.eq(1)
        yield dut.update_old_ptr.eq(0x1000)
        yield dut.update_new_ptr.eq(0x2000)
        yield Tick()
        yield dut.update_valid.eq(0)
        yield Tick()

        yield dut.query_valid.eq(1)
        yield dut.query_old_ptr.eq(0x1000)
        yield Tick()

        assert (yield dut.rsp_valid) == 1
        assert (yield dut.rsp_hit) == 1
        assert (yield dut.rsp_new_ptr) == 0x2000

        yield dut.query_valid.eq(0)
        yield Tick()

        yield dut.query_valid.eq(1)
        yield dut.query_old_ptr.eq(0x9999)
        yield Tick()

        assert (yield dut.rsp_valid) == 1
        assert (yield dut.rsp_hit) == 0
        assert (yield dut.rsp_new_ptr) == 0x9999

        yield dut.query_valid.eq(0)

    _run_sync(dut, proc)
    print("  enabled_hit_miss: PASS")


def test_enabled_evict():
    dut = L0ForwardingEnabled(entries=4)

    def proc():
        updates = [(0x00, 0x1000), (0x01, 0x2000), (0x02, 0x3000), (0x03, 0x4000)]
        for old, new in updates:
            yield dut.update_valid.eq(1)
            yield dut.update_old_ptr.eq(old)
            yield dut.update_new_ptr.eq(new)
            yield Tick()
            yield dut.update_valid.eq(0)
            yield Tick()

        for old, new in updates:
            yield dut.query_valid.eq(1)
            yield dut.query_old_ptr.eq(old)
            yield Tick()
            yield dut.query_valid.eq(0)

            assert (yield dut.rsp_hit) == 1, f"Expected hit for 0x{old:08x}"
            assert (yield dut.rsp_new_ptr) == new, f"Expected 0x{new:08x} for 0x{old:08x}"

        slot0_old = 0x04
        slot0_new = 0x5000
        yield dut.update_valid.eq(1)
        yield dut.update_old_ptr.eq(slot0_old)
        yield dut.update_new_ptr.eq(slot0_new)
        yield Tick()
        yield dut.update_valid.eq(0)
        yield Tick()

        yield dut.query_valid.eq(1)
        yield dut.query_old_ptr.eq(0x00)
        yield Tick()
        yield dut.query_valid.eq(0)

        assert (yield dut.rsp_hit) == 0, "Old slot 0 entry should be evicted"

        yield dut.query_valid.eq(1)
        yield dut.query_old_ptr.eq(slot0_old)
        yield Tick()
        yield dut.query_valid.eq(0)

        assert (yield dut.rsp_hit) == 1
        assert (yield dut.rsp_new_ptr) == slot0_new

        for old, new in updates[1:]:
            yield dut.query_valid.eq(1)
            yield dut.query_old_ptr.eq(old)
            yield Tick()
            yield dut.query_valid.eq(0)

            assert (yield dut.rsp_hit) == 1, f"Slot for 0x{old:08x} should still be valid"
            assert (yield dut.rsp_new_ptr) == new

    _run_sync(dut, proc)
    print("  enabled_evict: PASS")


def test_enabled_flush():
    dut = L0ForwardingEnabled(entries=4)

    def proc():
        yield dut.update_valid.eq(1)
        yield dut.update_old_ptr.eq(0x1000)
        yield dut.update_new_ptr.eq(0x2000)
        yield Tick()
        yield dut.update_valid.eq(0)
        yield Tick()

        yield dut.query_valid.eq(1)
        yield dut.query_old_ptr.eq(0x1000)
        yield Tick()
        yield dut.query_valid.eq(0)
        assert (yield dut.rsp_hit) == 1

        yield dut.flush.eq(1)
        yield Tick()
        yield dut.flush.eq(0)
        yield Tick()

        yield dut.query_valid.eq(1)
        yield dut.query_old_ptr.eq(0x1000)
        yield Tick()
        yield dut.query_valid.eq(0)
        assert (yield dut.rsp_hit) == 0

    _run_sync(dut, proc)
    print("  enabled_flush: PASS")


def test_elaborate():
    for cls in [L0ForwardingDisabled]:
        dut = cls()
        dut.elaborate(platform=None)
    for entries in [4, 8, 16]:
        dut = L0ForwardingEnabled(entries=entries)
        dut.elaborate(platform=None)
    print("  elaborate: PASS")


if __name__ == "__main__":
    tests = [
        ("disabled_always_miss", test_disabled_always_miss),
        ("enabled_hit_miss", test_enabled_hit_miss),
        ("enabled_evict", test_enabled_evict),
        ("enabled_flush", test_enabled_flush),
        ("elaborate", test_elaborate),
    ]
    print("=" * 50)
    print("GC L0 Forwarding Test")
    print("=" * 50)
    all_ok = True
    for name, fn in tests:
        try:
            fn()
            print(f"  {name:25s} OK")
        except Exception as e:
            print(f"  {name:25s} FAIL: {e}")
            all_ok = False
    print(f"\n{'ALL PASS' if all_ok else 'SOME FAILED'}")
    import sys; sys.exit(0 if all_ok else 1)
