# tests/test_gc_slots_bank.py
# GC Slots Bank 测试套件: Standard / Banked 分配/释放/匹配

from amaranth import *
from amaranth.sim import Simulator, Tick
from amaranth.back import rtlil

from rtl.gc_slots_bank import (
    GCSlotsBankStandard,
    GCSlotsBanked,
    create_slots_bank,
)


def test_standard_alloc_free_match():
    dut = GCSlotsBankStandard(gc_slots=8)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def proc():
        # alloc tag=0xAB
        yield dut.alloc_tag.eq(0xAB)
        yield dut.alloc_valid.eq(1)
        yield Tick()
        while (yield dut.alloc_ready) == 0:
            yield Tick()
        yield dut.alloc_valid.eq(0)
        yield Tick()

        # match — should find
        yield dut.match_tag.eq(0xAB)
        yield Tick()
        assert (yield dut.match_found) == 1
        assert (yield dut.match_idx) == 0

        # free
        yield dut.free_tag.eq(0xAB)
        yield dut.free_valid.eq(1)
        yield Tick()
        yield dut.free_valid.eq(0)
        yield Tick()

        # match after free — should not find
        yield dut.match_tag.eq(0xAB)
        yield Tick()
        assert (yield dut.match_found) == 0

        # fill all 8 slots
        for i in range(8):
            yield dut.alloc_tag.eq(0x10 + i)
            yield dut.alloc_valid.eq(1)
            yield Tick()
            while (yield dut.alloc_ready) == 0:
                yield Tick()
            yield dut.alloc_valid.eq(0)
            yield Tick()

        # verify all 8 match
        for i in range(8):
            yield dut.match_tag.eq(0x10 + i)
            yield Tick()
            assert (yield dut.match_found) == 1, f"tag 0x{0x10+i:02x} not found"

        # free first 4, verify
        for i in range(4):
            yield dut.free_tag.eq(0x10 + i)
            yield dut.free_valid.eq(1)
            yield Tick()
            yield dut.free_valid.eq(0)
            yield Tick()
        for i in range(4):
            yield dut.match_tag.eq(0x10 + i)
            yield Tick()
            assert (yield dut.match_found) == 0, f"tag 0x{0x10+i:02x} still found"
        for i in range(4, 8):
            yield dut.match_tag.eq(0x10 + i)
            yield Tick()
            assert (yield dut.match_found) == 1, f"tag 0x{0x10+i:02x} lost after free of others"

        print("    PASS: standard_alloc_free_match")

    sim.add_sync_process(proc)
    sim.run()


def test_banked1_identical_to_standard():
    """bank_count=1 必须与 Standard 行为一致."""
    std = GCSlotsBankStandard(gc_slots=8)
    bkd = GCSlotsBanked(gc_slots=8, bank_count=1)

    # Use one module wrapping both to verify identical behavior
    class DualBank(Elaboratable):
        def elaborate(self, platform):
            m = Module()
            m.submodules.std = std
            m.submodules.bkd = bkd
            return m

    sim = Simulator(DualBank())
    sim.add_clock(1e-6)

    def proc():
        tags = [0xAB, 0xCD, 0xEF]
        for tag in tags:
            yield std.alloc_tag.eq(tag)
            yield std.alloc_valid.eq(1)
            yield bkd.alloc_tag.eq(tag)
            yield bkd.alloc_valid.eq(1)
            yield Tick()
            while (yield std.alloc_ready) == 0 or (yield bkd.alloc_ready) == 0:
                yield Tick()
            assert (yield std.alloc_ready) == (yield bkd.alloc_ready), \
                f"alloc_ready mismatch after tag 0x{tag:02x}"
            yield std.alloc_valid.eq(0)
            yield bkd.alloc_valid.eq(0)
            yield Tick()

        for tag in tags:
            yield std.match_tag.eq(tag)
            yield std.match_valid.eq(1)
            yield bkd.match_tag.eq(tag)
            yield bkd.match_valid.eq(1)
            yield Tick()
            assert (yield std.match_found) == (yield bkd.match_found), \
                f"match_found mismatch for tag 0x{tag:02x}"
            assert (yield std.match_idx) == (yield bkd.match_idx), \
                f"match_idx mismatch for tag 0x{tag:02x}"
            yield std.match_valid.eq(0)
            yield bkd.match_valid.eq(0)
            yield Tick()

        assert (yield std.bank_count) == 1
        assert (yield bkd.bank_count) == 1

        print("    PASS: banked1_identical_to_standard")

    sim.add_sync_process(proc)
    sim.run()


def test_banked4_distribution():
    """bank_count=4: 验证跨 bank 分配/释放/匹配正确."""
    BK = 4
    SPB = 2
    dut = GCSlotsBanked(gc_slots=8, bank_count=BK)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def proc():
        # Tags: lower 2 bits = bank (hb=(4-1).bit_length()=2)
        tags = [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07]
        # Bank = tag & 0x03, local slot = 0 for first in bank, 1 for second
        expected_global = [0, 2, 4, 6, 1, 3, 5, 7]

        for i, t in enumerate(tags):
            yield dut.alloc_tag.eq(t)
            yield dut.alloc_valid.eq(1)
            yield Tick()
            while (yield dut.alloc_ready) == 0:
                yield Tick()
            yield dut.alloc_valid.eq(0)
            yield Tick()

            yield dut.match_tag.eq(t)
            yield Tick()
            assert (yield dut.match_found) == 1, \
                f"tag 0x{t:02x} (#{i}) not found after alloc"
            actual = yield dut.match_idx
            assert actual == expected_global[i], \
                f"tag 0x{t:02x} idx={actual} expected={expected_global[i]}"

        # re-verify all
        for i, t in enumerate(tags):
            yield dut.match_tag.eq(t)
            yield Tick()
            assert (yield dut.match_found) == 1, \
                f"tag 0x{t:02x} lost on re-check"
            assert (yield dut.match_idx) == expected_global[i]

        # free all
        for t in tags:
            yield dut.free_tag.eq(t)
            yield dut.free_valid.eq(1)
            yield Tick()
            yield dut.free_valid.eq(0)
            yield Tick()

        for t in tags:
            yield dut.match_tag.eq(t)
            yield Tick()
            assert (yield dut.match_found) == 0, \
                f"tag 0x{t:02x} still found after free"

        assert (yield dut.busy) == 0
        assert (yield dut.bank_count) == BK

        print("    PASS: banked4_distribution")

    sim.add_sync_process(proc)
    sim.run()


def test_banked4_second_level_arb():
    """bank_count=4: 二级仲裁 — 多 bank 同时命中时优先 bank 编号小的."""
    BK = 4
    dut = GCSlotsBanked(gc_slots=8, bank_count=BK)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def proc():
        # Fill slots such that multiple banks have matches
        tags_bank0 = [0x00, 0x04]
        tags_bank1 = [0x01, 0x05]
        tags_bank2 = [0x02, 0x06]
        tags_bank3 = [0x03, 0x07]
        all_tags = tags_bank0 + tags_bank1 + tags_bank2 + tags_bank3

        for t in all_tags:
            yield dut.alloc_tag.eq(t)
            yield dut.alloc_valid.eq(1)
            yield Tick()
            while (yield dut.alloc_ready) == 0:
                yield Tick()
            yield dut.alloc_valid.eq(0)
            yield Tick()

        # Match tag in bank 0 — should find
        yield dut.match_tag.eq(0x00)
        yield Tick()
        assert (yield dut.match_found) == 1
        assert (yield dut.match_idx) == 0

        # Match tag in bank 3 — should find
        yield dut.match_tag.eq(0x03)
        yield Tick()
        assert (yield dut.match_found) == 1
        assert (yield dut.match_idx) == 6

        # Match tag in bank 1 — should find
        yield dut.match_tag.eq(0x01)
        yield Tick()
        assert (yield dut.match_found) == 1
        assert (yield dut.match_idx) == 2

        print("    PASS: banked4_second_level_arb")

    sim.add_sync_process(proc)
    sim.run()


def test_banked4_free_directed():
    """bank_count=4: 释放按 hash 定向到正确 bank."""
    BK = 4
    dut = GCSlotsBanked(gc_slots=8, bank_count=BK)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def proc():
        # alloc 2 tags to bank 0 (tag[:2]=0)
        yield dut.alloc_tag.eq(0x00)
        yield dut.alloc_valid.eq(1)
        yield Tick()
        while (yield dut.alloc_ready) == 0:
            yield Tick()
        yield dut.alloc_valid.eq(0)
        yield Tick()

        yield dut.alloc_tag.eq(0x04)
        yield dut.alloc_valid.eq(1)
        yield Tick()
        while (yield dut.alloc_ready) == 0:
            yield Tick()
        yield dut.alloc_valid.eq(0)
        yield Tick()

        # verify both
        yield dut.match_tag.eq(0x00)
        yield Tick()
        assert (yield dut.match_found) == 1
        yield dut.match_tag.eq(0x04)
        yield Tick()
        assert (yield dut.match_found) == 1

        # free only 0x04
        yield dut.free_tag.eq(0x04)
        yield dut.free_valid.eq(1)
        yield Tick()
        yield dut.free_valid.eq(0)
        yield Tick()

        yield dut.match_tag.eq(0x04)
        yield Tick()
        assert (yield dut.match_found) == 0, "0x04 should be freed"
        yield dut.match_tag.eq(0x00)
        yield Tick()
        assert (yield dut.match_found) == 1, "0x00 should remain"

        yield dut.free_tag.eq(0x00)
        yield dut.free_valid.eq(1)
        yield Tick()
        yield dut.free_valid.eq(0)
        yield Tick()

        yield dut.match_tag.eq(0x00)
        yield Tick()
        assert (yield dut.match_found) == 0, "0x00 should be freed"

        print("    PASS: banked4_free_directed")

    sim.add_sync_process(proc)
    sim.run()


def test_factory():
    std = create_slots_bank("standard", gc_slots=8)
    assert isinstance(std, GCSlotsBankStandard)

    bkd = create_slots_bank("banked", gc_slots=16, bank_count=4)
    assert isinstance(bkd, GCSlotsBanked)
    assert bkd._bank_count == 4

    try:
        create_slots_bank("unknown")
        assert False, "should raise"
    except ValueError:
        pass

    print("    PASS: factory")


def test_elaboration():
    cases = [
        ("standard(8)",      GCSlotsBankStandard(gc_slots=8)),
        ("banked(16,1)",     GCSlotsBanked(gc_slots=16, bank_count=1)),
        ("banked(16,2)",     GCSlotsBanked(gc_slots=16, bank_count=2)),
        ("banked(16,4)",     GCSlotsBanked(gc_slots=16, bank_count=4)),
        ("banked(12,3)",     GCSlotsBanked(gc_slots=12, bank_count=3)),
    ]
    for name, dut in cases:
        il = rtlil.convert(dut, ports=[dut.alloc_valid, dut.alloc_ready])
        assert isinstance(il, str) and len(il) > 100
        print(f"    {name}: OK ({len(il)} chars)")
    print("    PASS: elaboration")


def main():
    tests = [
        ("Standard alloc/free/match",           test_standard_alloc_free_match),
        ("Banked(1) ≡ Standard",                test_banked1_identical_to_standard),
        ("Banked(4) distribution",              test_banked4_distribution),
        ("Banked(4) second-level arb",          test_banked4_second_level_arb),
        ("Banked(4) free directed",             test_banked4_free_directed),
        ("Factory",                              test_factory),
        ("Elaboration",                          test_elaboration),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        print(f"[{name}]")
        try:
            fn()
            passed += 1
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"    FAIL: {e}")
            failed += 1

    total = passed + failed
    print(f"\n{'='*50}")
    print(f"Results: {passed}/{total} passed"
          + ("" if failed == 0 else f", {failed} FAILED"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
