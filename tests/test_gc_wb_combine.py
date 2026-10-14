# tests/test_gc_wb_combine.py — 验证写屏障合并缓冲 (GCWBCombine)
from amaranth import *
from amaranth.sim import Simulator, Tick, Settle

from rtl.gc_wb_combine import GCWBCombine


class WbCombineTb(Elaboratable):
    def __init__(self, depth=4, max_age=4):
        self.dut = GCWBCombine(depth=depth, max_age=max_age)

        self.wb_combine_enable = self.dut.wb_combine_enable
        self.mem1_addr = self.dut.mem1_addr
        self.mem1_is_store = self.dut.mem1_is_store
        self.mem1_wdata = self.dut.mem1_wdata
        self.store_grant = self.dut.store_grant
        self.wb_card_shift = self.dut.wb_card_shift
        self.wb_obj_shift = self.dut.wb_obj_shift
        self.wb_ptr_filter = self.dut.wb_ptr_filter
        self.flush = self.dut.flush
        self.wbq_w_rdy = self.dut.wbq_w_rdy

        self.wbq_w_data = self.dut.wbq_w_data
        self.wbq_w_en = self.dut.wbq_w_en
        self.stall_store = self.dut.stall_store
        self.wb_valid = self.dut.wb_valid

    def elaborate(self, platform):
        m = Module()
        m.submodules.dut = self.dut
        return m


def drive_store(tb, addr, wdata, is_ptr=1):
    """One store: set signals, sample posedge, clear."""
    yield tb.mem1_addr.eq(addr)
    yield tb.mem1_is_store.eq(1)
    yield tb.mem1_wdata.eq(wdata | ((is_ptr & 1) << 31))
    yield tb.store_grant.eq(1)
    yield Settle()
    yield Tick()
    yield tb.store_grant.eq(0)
    yield tb.mem1_is_store.eq(0)


def flush_n(tb, n=8):
    """Hold flush high for n ticks, return collected wbq events."""
    ev = []
    for _ in range(n):
        yield tb.flush.eq(1)
        yield Settle()
        en = yield tb.wbq_w_en
        if en:
            data = yield tb.wbq_w_data
            ev.append((data & 0xFFFFFFFF, (data >> 32) & 0xFFFFFFFF))
        yield Tick()
    yield tb.flush.eq(0)
    yield Settle()
    return ev


# ── Test 1: basic combining ─────────────────────────────────────
def test_basic_combining():
    """2 stores to same card -> 1 WB event."""
    tb = WbCombineTb(depth=4, max_age=16)
    sim = Simulator(tb)
    sim.add_clock(1e-6)
    results = []

    def proc():
        nonlocal results
        yield tb.wbq_w_rdy.eq(1)
        yield tb.wb_ptr_filter.eq(0)
        yield tb.wb_card_shift.eq(6)
        yield tb.wb_obj_shift.eq(4)
        yield Settle()

        yield from drive_store(tb, 0x40, 0xDEAD)
        yield from drive_store(tb, 0x44, 0xBEEF)
        results = yield from flush_n(tb, 4)

    sim.add_process(proc)
    sim.run()

    assert len(results) == 1, f"expected 1 merged event, got {len(results)}"
    card, obj = results[0]
    assert card == 1, f"card_id mismatch: expected 1, got {card}"
    print(f"test_basic_combining: OK (1 event, card={card})")


# ── Test 2: stall on buffer full ────────────────────────────────
def test_flush_on_full():
    """5 stores, wbq full -> 4 buffered + stall on 5th."""
    tb = WbCombineTb(depth=4, max_age=16)
    sim = Simulator(tb)
    sim.add_clock(1e-6)
    stalled_5th = [False]

    def proc():
        yield tb.wbq_w_rdy.eq(0)  # wbq full
        yield tb.wb_ptr_filter.eq(0)
        yield tb.wb_card_shift.eq(6)
        yield tb.wb_obj_shift.eq(4)
        yield Settle()

        for i in range(5):
            addr = 0x40 + i * 0x100  # different cards
            yield from drive_store(tb, addr, 0x1000 + i)
            yield Settle()
            stall = yield tb.stall_store
            if i == 4 and stall:
                stalled_5th[0] = True
            yield Tick()

    sim.add_process(proc)
    sim.run()

    assert stalled_5th[0], "expected stall on 5th store with depth=4"
    print("test_flush_on_full: OK (stalled on 5th)")


# ── Test 3: wb_ptr_filter + merge ──────────────────────────────
def test_ptr_filter_merge():
    """Pointer stores merged; non-pointer filtered."""
    tb = WbCombineTb(depth=4, max_age=16)
    sim = Simulator(tb)
    sim.add_clock(1e-6)
    results = []

    def proc():
        nonlocal results
        yield tb.wbq_w_rdy.eq(1)
        yield tb.wb_ptr_filter.eq(1)
        yield tb.wb_card_shift.eq(6)
        yield tb.wb_obj_shift.eq(4)
        yield Settle()

        yield from drive_store(tb, 0x40, 0x1234, is_ptr=1)
        yield from drive_store(tb, 0x44, 0x5678, is_ptr=1)
        yield from drive_store(tb, 0x48, 0x0000, is_ptr=0)
        results = yield from flush_n(tb, 4)

    sim.add_process(proc)
    sim.run()

    assert len(results) == 1, \
        f"expected 1 event (non-pointer filtered), got {len(results)}"
    card, obj = results[0]
    assert card == 1, f"card_id mismatch: expected 1, got {card}"
    print(f"test_ptr_filter_merge: OK (1 event, card={card})")


# ── Test 4: force flush ─────────────────────────────────────────
def test_force_flush():
    """Force flush drains all pending entries."""
    tb = WbCombineTb(depth=4, max_age=16)
    sim = Simulator(tb)
    sim.add_clock(1e-6)
    results = []

    def proc():
        nonlocal results
        yield tb.wbq_w_rdy.eq(1)
        yield tb.wb_ptr_filter.eq(0)
        yield tb.wb_card_shift.eq(6)
        yield tb.wb_obj_shift.eq(4)
        yield Settle()

        for i in range(3):
            yield from drive_store(tb, 0x40 + i * 0x100, 0x1000 + i)

        results = yield from flush_n(tb, 8)

    sim.add_process(proc)
    sim.run()

    assert len(results) == 3, f"expected 3 events flushed, got {len(results)}"
    print(f"test_force_flush: OK ({len(results)} events flushed)")


# ── Test 5: bypass when disabled ────────────────────────────────
def test_bypass_when_disabled():
    """wb_combine_enable=0 -> stores go directly to wbq."""
    tb = WbCombineTb(depth=4, max_age=16)
    sim = Simulator(tb)
    sim.add_clock(1e-6)
    results = []

    def proc():
        nonlocal results
        yield tb.wbq_w_rdy.eq(1)
        yield tb.wb_combine_enable.eq(0)
        yield tb.wb_ptr_filter.eq(0)
        yield tb.wb_card_shift.eq(6)
        yield tb.wb_obj_shift.eq(4)
        yield Settle()

        # Store 1: read wbq during the same cycle as store_grant
        yield tb.mem1_addr.eq(0x40)
        yield tb.mem1_is_store.eq(1)
        yield tb.mem1_wdata.eq(0x8000AAAA)
        yield tb.store_grant.eq(1)
        yield Settle()
        en = yield tb.wbq_w_en
        if en:
            data = yield tb.wbq_w_data
            results.append((data & 0xFFFFFFFF, (data >> 32) & 0xFFFFFFFF))
        yield Tick()
        yield tb.store_grant.eq(0)
        yield tb.mem1_is_store.eq(0)
        yield Settle()

        # Store 2
        yield tb.mem1_addr.eq(0x44)
        yield tb.mem1_is_store.eq(1)
        yield tb.mem1_wdata.eq(0x8000BBBB)
        yield tb.store_grant.eq(1)
        yield Settle()
        en = yield tb.wbq_w_en
        if en:
            data = yield tb.wbq_w_data
            results.append((data & 0xFFFFFFFF, (data >> 32) & 0xFFFFFFFF))
        yield Tick()
        yield tb.store_grant.eq(0)
        yield tb.mem1_is_store.eq(0)
        yield Settle()

    sim.add_process(proc)
    sim.run()

    assert len(results) == 2, f"expected 2 events (bypass), got {len(results)}"
    print(f"test_bypass_when_disabled: OK ({len(results)} events)")


if __name__ == "__main__":
    test_basic_combining()
    test_flush_on_full()
    test_ptr_filter_merge()
    test_force_flush()
    test_bypass_when_disabled()
    print("\nAll tests passed.")
