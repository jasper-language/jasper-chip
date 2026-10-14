# rtl/gc_slots_bank.py
# GC Slots Bank 统一接口 + Standard / Banked 实现
from amaranth import *

# ── 接口协议 ──────────────────────────────────────────────────
#
# 所有 GCSlotsBank 实现必须支持以下信号:
#
# 分配路径:
#   alloc_valid   : Signal()  in  分配请求有效
#   alloc_ready   : Signal()  out 分配接受
#   alloc_tag     : Signal(8)  in  分配标签 (用于 match)
#
# 释放路径:
#   free_valid    : Signal()  in  释放请求有效
#   free_ready    : Signal()  out 释放接受
#   free_tag      : Signal(8)  in  释放标签
#
# 匹配路径:
#   match_valid   : Signal()  in  匹配请求有效
#   match_ready   : Signal()  out 匹配接受
#   match_tag     : Signal(8)  in  匹配标签
#   match_found   : Signal()  out 是否找到匹配
#   match_idx     : Signal(N)  out 匹配 slot 索引
#
# 状态:
#   busy          : Signal()  out bank 忙
#   bank_count    : Signal(4) out bank 数量 (对 banked 实现为实际 bank 数)


# ── 优先级编码器辅助 ─────────────────────────────────────────
def _prio_enc(signals, nbits):
    """Return (found, idx) — first 1 in list of 1-bit signals."""
    found = Const(0)
    idx = Const(0)
    for i, s in enumerate(signals):
        idx = Mux(found, idx, Const(i, nbits))
        found = found | s
    return found, idx


# ── GCSlotsBankStandard — 单一 flat 优先级编码器 ─────────────
class GCSlotsBankStandard(Elaboratable):
    """Standard 实现: 单一 flat slots 阵列 + 优先级编码器.

    与现有 gc_subsystem 中 GC slots 行为一致.
    """
    def __init__(self, gc_slots=16, bank_count=1):
        self.gc_slots = gc_slots
        self._idx_bits = (gc_slots - 1).bit_length() if gc_slots > 1 else 1

        self.alloc_valid = Signal()
        self.alloc_ready = Signal()
        self.alloc_tag = Signal(8)

        self.free_valid = Signal()
        self.free_ready = Signal()
        self.free_tag = Signal(8)

        self.match_valid = Signal()
        self.match_ready = Signal()
        self.match_tag = Signal(8)
        self.match_found = Signal()
        self.match_idx = Signal(self._idx_bits)

        self.busy = Signal()
        self.bank_count = Signal(4)

    def elaborate(self, platform):
        m = Module()
        P = self
        N = P.gc_slots
        ib = P._idx_bits

        gw = Array([Signal(reset=0) for _ in range(N)])
        gt = Array([Signal(8) for _ in range(N)])

        # ── Free slot priority encoder ────────────────────
        free_raw = Array([~w for w in gw])
        free_found, free_idx = _prio_enc(free_raw, ib)

        # ── Alloc ─────────────────────────────────────────
        m.d.comb += P.alloc_ready.eq(free_found)
        with m.If(P.alloc_valid & P.alloc_ready):
            m.d.sync += [
                gw[free_idx].eq(1),
                gt[free_idx].eq(P.alloc_tag),
            ]

        # ── Free ──────────────────────────────────────────
        m.d.comb += P.free_ready.eq(1)
        with m.If(P.free_valid & P.free_ready):
            for i in range(N):
                with m.If(gt[i] == P.free_tag):
                    m.d.sync += gw[i].eq(0)

        # ── Match ─────────────────────────────────────────
        match_raw = Array([gw[i] & (P.match_tag == gt[i]) for i in range(N)])
        match_found, match_idx = _prio_enc(match_raw, ib)
        m.d.comb += [
            P.match_ready.eq(1),
            P.match_found.eq(match_found),
            P.match_idx.eq(Mux(match_found, match_idx, 0)),
        ]

        # ── Status ────────────────────────────────────────
        m.d.comb += [
            P.busy.eq(0),
            P.bank_count.eq(1),
        ]

        return m


# ── GCSlotsBanked — 实验性多 bank ────────────────────────────
class GCSlotsBanked(Elaboratable):
    """Experimental: 多 bank slots, 每 bank 独立编码器 + 二级仲裁.

    分配: hash(tag) → bank, 在该 bank 内分配.
    释放: hash(tag) → bank, 在该 bank 内释放.
    匹配: 广播到所有 bank, 二级优先级仲裁合并结果.
    """
    def __init__(self, gc_slots=16, bank_count=2):
        self.gc_slots = gc_slots
        self._bank_count = bank_count
        self._slots_per_bank = gc_slots // bank_count if bank_count > 0 else gc_slots
        self._idx_bits = (self._slots_per_bank - 1).bit_length() if self._slots_per_bank > 1 else 1
        self._full_idx_bits = (gc_slots - 1).bit_length() if gc_slots > 1 else 1
        self._hash_bits = max(1, (bank_count - 1).bit_length()) if bank_count > 1 else 0

        self.alloc_valid = Signal()
        self.alloc_ready = Signal()
        self.alloc_tag = Signal(8)

        self.free_valid = Signal()
        self.free_ready = Signal()
        self.free_tag = Signal(8)

        self.match_valid = Signal()
        self.match_ready = Signal()
        self.match_tag = Signal(8)
        self.match_found = Signal()
        self.match_idx = Signal(self._full_idx_bits)

        self.busy = Signal()
        self.bank_count = Signal(4)

    def elaborate(self, platform):
        m = Module()
        P = self
        BK = P._bank_count
        SPB = P._slots_per_bank
        ib = P._idx_bits
        fib = P._full_idx_bits
        hb = P._hash_bits

        if BK <= 1:
            sub = GCSlotsBankStandard(gc_slots=P.gc_slots)
            m.submodules.priv = sub
            m.d.comb += [
                sub.alloc_valid.eq(P.alloc_valid),
                P.alloc_ready.eq(sub.alloc_ready),
                sub.alloc_tag.eq(P.alloc_tag),
                sub.free_valid.eq(P.free_valid),
                P.free_ready.eq(sub.free_ready),
                sub.free_tag.eq(P.free_tag),
                sub.match_valid.eq(P.match_valid),
                P.match_ready.eq(sub.match_ready),
                sub.match_tag.eq(P.match_tag),
                P.match_found.eq(sub.match_found),
                P.match_idx.eq(sub.match_idx),
                P.busy.eq(sub.busy),
                P.bank_count.eq(1),
            ]
            return m

        # ── Per-bank state ────────────────────────────────
        bank_valid = Array([Array([Signal(reset=0) for _ in range(SPB)]) for _ in range(BK)])
        bank_tags = Array([Array([Signal(8) for _ in range(SPB)]) for _ in range(BK)])

        # Hash: use lower bits of tag for bank selection
        bank_sel = Signal(range(BK))
        m.d.comb += bank_sel.eq(P.alloc_tag[:hb])

        # ── Per-bank free encoders ────────────────────────
        bank_free_found = Array([Signal() for _ in range(BK)])
        bank_free_idx = Array([Signal(ib) for _ in range(BK)])
        for b in range(BK):
            raw = Array([~bank_valid[b][i] for i in range(SPB)])
            ff, fi = _prio_enc(raw, ib)
            m.d.comb += [
                bank_free_found[b].eq(ff),
                bank_free_idx[b].eq(fi),
            ]

        # ── Alloc ─────────────────────────────────────────
        alloc_bank_free = Signal()
        m.d.comb += alloc_bank_free.eq(bank_free_found[bank_sel])
        m.d.comb += P.alloc_ready.eq(alloc_bank_free)

        with m.If(P.alloc_valid & P.alloc_ready):
            for bk in range(BK):
                with m.If(bank_sel == bk):
                    for si in range(SPB):
                        with m.If(bank_free_idx[bk] == si):
                            m.d.sync += bank_valid[bk][si].eq(1)
                            m.d.sync += bank_tags[bk][si].eq(P.alloc_tag)

        # ── Free ──────────────────────────────────────────
        free_bank_sel = Signal(range(BK))
        m.d.comb += free_bank_sel.eq(P.free_tag[:hb])

        m.d.comb += P.free_ready.eq(1)
        with m.If(P.free_valid & P.free_ready):
            for bk in range(BK):
                for si in range(SPB):
                    with m.If((free_bank_sel == bk) & (bank_tags[bk][si] == P.free_tag)):
                        m.d.sync += bank_valid[bk][si].eq(0)

        # ── Match ─────────────────────────────────────────
        # Per-bank match encoders
        bank_match_found = Array([Signal() for _ in range(BK)])
        bank_match_idx = Array([Signal(ib) for _ in range(BK)])
        for b in range(BK):
            raw = Array([bank_valid[b][i] & (P.match_tag == bank_tags[b][i]) for i in range(SPB)])
            mf, mi = _prio_enc(raw, ib)
            m.d.comb += [
                bank_match_found[b].eq(mf),
                bank_match_idx[b].eq(mi),
            ]

        # Second-level arbitration: priority encoder over banks
        m.d.comb += P.match_ready.eq(1)
        sl_found_v = Const(0)
        sl_bank_v = Const(0)
        for b in range(BK):
            sel = bank_match_found[b] & ~sl_found_v
            sl_bank_v = Mux(sel, b, sl_bank_v)
            sl_found_v = sl_found_v | bank_match_found[b]

        # Compose full index: bank * SPB + local_idx
        full_idx = Signal(fib)
        m.d.comb += full_idx.eq(sl_bank_v * SPB + bank_match_idx[sl_bank_v])
        m.d.comb += [
            P.match_found.eq(sl_found_v),
            P.match_idx.eq(Mux(sl_found_v, full_idx, 0)),
        ]

        # ── Status ────────────────────────────────────────
        any_busy_v = Const(0)
        for b in range(BK):
            for i in range(SPB):
                any_busy_v = any_busy_v | bank_valid[b][i]
        m.d.comb += [
            P.busy.eq(any_busy_v),
            P.bank_count.eq(BK),
        ]

        return m


# ── 工厂函数 ──────────────────────────────────────────────────
def create_slots_bank(impl: str, **kwargs):
    if impl == "standard":
        return GCSlotsBankStandard(**kwargs)
    elif impl == "banked":
        return GCSlotsBanked(**kwargs)
    else:
        raise ValueError(f"Unknown slots_impl: {impl}")
