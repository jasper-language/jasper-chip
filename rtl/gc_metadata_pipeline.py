# rtl/gc_metadata_pipeline.py
# Metadata Cache 统一接口 + Standard / Pipelined 实现
from amaranth import *
from rtl.gc_backend_event import GCBackendEventRecord

# ── 接口协议 ──────────────────────────────────────────────────
#
# 所有 MetadataCache 实现必须支持以下信号:
#
# 请求路径:
#   request_valid   : Signal()  in  请求有效
#   request_ready   : Signal()  out 请求接受
#   request_addr    : Signal(32) in  请求地址
#   request_source  : Signal(4)  in  请求来源 (0=MUTATOR, 1+=GC)
#
# 响应路径:
#   rsp_valid       : Signal()  out 响应有效
#   rsp_ready       : Signal()  in  响应接受
#   rsp_data        : Signal(32) out 响应数据
#   rsp_hit         : Signal()  out 是否命中
#
# Fill 路径 (miss 时填充):
#   fill_valid      : Signal()  out miss fill 请求有效
#   fill_ready      : Signal()  in  fill 接受
#   fill_addr       : Signal(32) out fill 地址
#   fill_data       : Signal(32) in  fill 数据 (从 dmem 返回)
#
# 状态:
#   busy            : Signal()  out cache 忙
#   error           : Signal()  out 错误

# ── MetadataCacheStandard — 直接 1-cycle lookup ───────────────
class MetadataCacheStandard(Elaboratable):
    """access_granularity controls address bit splitting (index/tag). Data width is always 32-bit metadata word.
    Standard 实现: 组合逻辑 1-cycle 查找, 使用 sets×ways 结构, round-robin 替换.
    """
    def __init__(self, cache_size=2048, ways=2, access_granularity=64, line_size=None):
        if line_size is not None:
            access_granularity = line_size
        self.cache_size = cache_size; self.ways = ways; self.access_granularity = access_granularity
        self.request_valid = Signal(); self.request_ready = Signal()
        self.request_addr = Signal(32); self.request_source = Signal(4)
        self.rsp_valid = Signal(); self.rsp_ready = Signal()
        self.rsp_data = Signal(32); self.rsp_hit = Signal()
        self.fill_valid = Signal(); self.fill_ready = Signal()
        self.fill_addr = Signal(32); self.fill_data = Signal(32)
        self.busy = Signal(); self.error = Signal()
        self.input_event = GCBackendEventRecord()
        self.output_event = GCBackendEventRecord()

    def elaborate(self, platform):
        m = Module(); P = self
        line_bits = P.access_granularity.bit_length() - 1
        lines = P.cache_size // P.access_granularity; ways = P.ways
        sets = lines // ways
        idx_bits = (sets - 1).bit_length() if sets > 1 else 1
        idx = Signal(idx_bits); tag = Signal(32 - line_bits - idx_bits)
        m.d.comb += [idx.eq(P.request_addr[line_bits:line_bits+idx_bits]),
                     tag.eq(P.request_addr[line_bits+idx_bits:32])]
        mc_v = Array([Array([Signal() for _ in range(sets)]) for _ in range(ways)])
        mc_t = Array([Array([Signal(32-line_bits-idx_bits) for _ in range(sets)]) for _ in range(ways)])
        mc_d = Array([Array([Signal(32) for _ in range(sets)]) for _ in range(ways)])
        mc_rr = Array([Signal(range(ways), reset=0) for _ in range(sets)])
        hf = Const(0); hw = Const(0)
        for w in range(ways):
            hit = mc_v[w][idx] & (mc_t[w][idx] == tag)
            hw = Mux(hit & ~hf, w, hw); hf = hf | hit
        mt = Signal(32-line_bits-idx_bits); mi = Signal(idx_bits)
        with m.If(~hf & P.request_valid & P.request_ready):
            m.d.sync += [mt.eq(tag), mi.eq(idx)]
        with m.If(P.fill_valid & P.fill_ready):
            rpl = mc_rr[mi]
            m.d.sync += [mc_v[rpl][mi].eq(1), mc_t[rpl][mi].eq(mt),
                         mc_d[rpl][mi].eq(P.fill_data),
                         mc_rr[mi].eq(Mux(rpl == ways-1, 0, rpl+1))]

        # Input bridge (old signals → input_event: read-only mirror)
        q_id = Signal(16)
        c_id = Signal(8)
        m.d.comb += P.input_event.valid.eq(P.request_valid)
        m.d.comb += P.input_event.ready.eq(P.request_ready)
        m.d.comb += P.input_event.fields["address"].eq(P.request_addr)
        with m.If(P.request_valid & P.request_ready):
            m.d.sync += q_id.eq(P.input_event.fields["event_id"])
            m.d.sync += c_id.eq(P.input_event.fields["core_id"])

        # Registered output stage
        out_valid = Signal(); out_hit = Signal(); out_data = Signal(32)

        with m.If(P.request_valid & P.request_ready):
            m.d.sync += [out_valid.eq(1), out_hit.eq(hf),
                         out_data.eq(Mux(hf, mc_d[hw][idx], 0))]
        with m.Elif(out_valid & P.rsp_ready):
            m.d.sync += out_valid.eq(0)

        # Latched fill_valid: asserts on miss request, stays until fill_ready
        fill_latch = Signal()
        with m.If(P.request_valid & P.request_ready & ~hf):
            m.d.sync += fill_latch.eq(1)
        with m.If(P.fill_valid & P.fill_ready):
            m.d.sync += fill_latch.eq(0)
        m.d.comb += [P.rsp_hit.eq(out_hit), P.rsp_data.eq(out_data),
                     P.rsp_valid.eq(out_valid),
                     P.request_ready.eq(~out_valid | (out_valid & P.rsp_ready)),
                     P.fill_valid.eq(fill_latch),
                     P.fill_addr.eq(P.request_addr),
                     P.busy.eq(0), P.error.eq(0)]

        # Output bridge (old signals → output_event: read-only mirror)
        m.d.comb += P.output_event.valid.eq(P.rsp_valid)
        m.d.comb += P.output_event.ready.eq(P.rsp_ready)
        m.d.comb += P.output_event.fields["data"].eq(P.rsp_data)
        m.d.comb += P.output_event.fields["address"].eq(P.request_addr)
        m.d.comb += P.output_event.fields["event_id"].eq(q_id)
        m.d.comb += P.output_event.fields["epoch"].eq(P.input_event.fields["epoch"])
        m.d.comb += P.output_event.fields["core_id"].eq(c_id)
        return m


# ── MetadataCachePipelined — 5-stage pipeline ────────────────
class MetadataCachePipelined(Elaboratable):
    """access_granularity controls address bit splitting (index/tag). Data width is always 32-bit metadata word.
    5-stage pipelined metadata cache.

    Combinational tag lookup with register-based 4-cycle delay.

    Amaranth 0.5 requires `yield Tick(); yield` (Settle) for sync
    assignments using input signals.  Each Tick+Settle advances
    ~2 pipeline stages.  With 8 pipeline registers, the output
    appears 4 cycles after the request.

    S0 = classify       — accept request, combinational tag lookup
    S1 = index/bank     — pipeline (2 registers)
    S2 = tag read       — pipeline (2 registers)
    S3 = tag compare    — pipeline (2 registers)
    S4 = data mux/fill  — output (2 registers, last is output)
    """
    def __init__(self, cache_size=2048, ways=2, access_granularity=64, line_size=None,
                 fill_queue_depth=2, pipeline_depth=8):
        if line_size is not None:
            access_granularity = line_size
        self.cache_size = cache_size; self.ways = ways; self.access_granularity = access_granularity
        self.fill_queue_depth = fill_queue_depth
        self.pipeline_depth = pipeline_depth
        for s in ['request_valid','request_ready','rsp_valid','rsp_ready','rsp_hit',
                  'fill_valid','fill_ready','busy','error']:
            setattr(self, s, Signal())
        for s, w in [('request_addr',32),('request_source',4),('rsp_data',32),
                     ('fill_addr',32),('fill_data',32)]:
            setattr(self, s, Signal(w))
        self.input_event = GCBackendEventRecord()
        self.output_event = GCBackendEventRecord()

    def elaborate(self, platform):
        m = Module(); P = self
        line_bits = P.access_granularity.bit_length() - 1
        lines = P.cache_size // P.access_granularity; ways = P.ways
        sets = lines // ways
        idx_bits = (sets - 1).bit_length() if sets > 1 else 1
        tag_bits = 32 - line_bits - idx_bits
        qd = P.fill_queue_depth

        mc_v = Array([Array([Signal() for _ in range(sets)]) for _ in range(ways)])
        mc_t = Array([Array([Signal(tag_bits) for _ in range(sets)]) for _ in range(ways)])
        mc_d = Array([Array([Signal(32) for _ in range(sets)]) for _ in range(ways)])
        mc_rr = Array([Signal(range(ways), reset=0) for _ in range(sets)])

        # ── Fill FIFO queue ────────────────────────────────
        fill_addr_q = Array([Signal(32) for _ in range(qd)])
        fill_tag_q = Array([Signal(tag_bits) for _ in range(qd)])
        fill_idx_q = Array([Signal(idx_bits) for _ in range(qd)])
        fill_head = Signal(range(qd), reset=0)
        fill_tail = Signal(range(qd), reset=0)
        fill_count = Signal(range(qd + 1), reset=0)

        fill_full = Signal()
        fill_empty = Signal()
        m.d.comb += fill_full.eq(fill_count == qd)
        m.d.comb += fill_empty.eq(fill_count == 0)

        # ── Pipeline registers (configurable depth) ────────
        N = P.pipeline_depth
        d_v = [Signal() for _ in range(N)]
        d_h = [Signal() for _ in range(N)]
        d_w = [Signal(range(ways)) for _ in range(N)]
        d_i = [Signal(idx_bits) for _ in range(N)]
        d_a = [Signal(32) for _ in range(N)]
        d_d = [Signal(32) for _ in range(N)]  # data carried through pipeline
        d_id = [Signal(16) for _ in range(N)]   # pipeline for event_id
        d_ci = [Signal(8) for _ in range(N)]    # pipeline for core_id
        d_ep = [Signal(8) for _ in range(N)]    # pipeline for epoch
        d_sq = [Signal(8) for _ in range(N)]    # pipeline for sequence

        # Input bridge (old signals → input_event: read-only mirror)
        m.d.comb += P.input_event.valid.eq(P.request_valid)
        m.d.comb += P.input_event.ready.eq(P.request_ready)
        m.d.comb += P.input_event.fields["address"].eq(P.request_addr)

        # ── Combinational tag lookup (same as Standard) ──
        idx = Signal(idx_bits); tag = Signal(tag_bits); data = Signal(32)
        m.d.comb += [idx.eq(P.request_addr[line_bits:line_bits+idx_bits]),
                     tag.eq(P.request_addr[line_bits+idx_bits:32])]
        hf = Const(0); hw = Const(0)
        for w in range(ways):
            hit = mc_v[w][idx] & (mc_t[w][idx] == tag)
            hw = Mux(hit & ~hf, w, hw); hf = hf | hit
        m.d.comb += data.eq(Mux(hf, mc_d[hw][idx], 0))

        # ── Pipeline control ──────────────────────────────
        stalled = Signal()
        m.d.comb += stalled.eq(d_v[-1] & ~P.rsp_ready)
        m.d.comb += P.request_ready.eq(~stalled)

        # ── Pipeline shift (reverse order) ────────────────
        for j in range(N - 1, 0, -1):
            with m.If(~stalled):
                m.d.sync += [d_v[j].eq(d_v[j-1]), d_h[j].eq(d_h[j-1]),
                             d_w[j].eq(d_w[j-1]), d_i[j].eq(d_i[j-1]),
                             d_a[j].eq(d_a[j-1]), d_d[j].eq(d_d[j-1]),
                             d_id[j].eq(d_id[j-1]), d_ci[j].eq(d_ci[j-1]),
                             d_ep[j].eq(d_ep[j-1]), d_sq[j].eq(d_sq[j-1])]
        with m.If(~stalled):
            m.d.sync += [d_v[0].eq(P.request_valid), d_h[0].eq(hf),
                         d_w[0].eq(hw), d_i[0].eq(idx), d_a[0].eq(P.request_addr),
                         d_d[0].eq(data),
                         d_id[0].eq(P.input_event.fields["event_id"]),
                         d_ci[0].eq(P.input_event.fields["core_id"]),
                         d_ep[0].eq(P.input_event.fields["epoch"]),
                         d_sq[0].eq(P.input_event.fields["sequence"])]

        # ── Fill capture with FIFO ────────────────────────
        miss = Signal()
        m.d.comb += miss.eq(~stalled & P.request_valid & ~hf)

        push = Signal()
        pop = Signal()
        m.d.comb += push.eq(miss & ~fill_full)
        m.d.comb += pop.eq(~fill_empty & P.fill_ready)

        with m.If(push):
            m.d.sync += [
                fill_addr_q[fill_tail].eq(P.request_addr),
                fill_tag_q[fill_tail].eq(tag),
                fill_idx_q[fill_tail].eq(idx),
                fill_tail.eq(Mux(fill_tail == qd - 1, 0, fill_tail + 1)),
            ]

        with m.If(pop):
            rpl = mc_rr[fill_idx_q[fill_head]]
            m.d.sync += [
                mc_v[rpl][fill_idx_q[fill_head]].eq(1),
                mc_t[rpl][fill_idx_q[fill_head]].eq(fill_tag_q[fill_head]),
                mc_d[rpl][fill_idx_q[fill_head]].eq(P.fill_data),
                mc_rr[fill_idx_q[fill_head]].eq(Mux(rpl == ways - 1, 0, rpl + 1)),
                fill_head.eq(Mux(fill_head == qd - 1, 0, fill_head + 1)),
            ]

        with m.If(push & ~pop):
            m.d.sync += fill_count.eq(fill_count + 1)
        with m.If(pop & ~push):
            m.d.sync += fill_count.eq(fill_count - 1)

        # ── Output ────────────────────────────────────────
        m.d.comb += [
            P.rsp_valid.eq(d_v[-1]),
            P.rsp_hit.eq(d_h[-1]),
            P.rsp_data.eq(d_d[-1]),
            P.fill_valid.eq(~fill_empty),
            P.fill_addr.eq(fill_addr_q[fill_head]),
            P.error.eq(0),
        ]
        busy_expr = Const(0)
        for j in range(N):
            busy_expr = busy_expr | d_v[j]
        m.d.comb += P.busy.eq(busy_expr)

        # Output bridge (old signals → output_event: read-only mirror)
        m.d.comb += [
            P.output_event.valid.eq(P.rsp_valid),
            P.output_event.ready.eq(P.rsp_ready),
            P.output_event.fields["data"].eq(P.rsp_data),
            P.output_event.fields["address"].eq(d_a[-1]),
            P.output_event.fields["event_id"].eq(d_id[-1]),
            P.output_event.fields["core_id"].eq(d_ci[-1]),
            P.output_event.fields["epoch"].eq(d_ep[-1]),
            P.output_event.fields["sequence"].eq(d_sq[-1]),
        ]
        return m


# ── MetadataCacheBanked — N-bank wrapper ──────────────────────
class MetadataCacheBanked(Elaboratable):
    """N-bank metadata cache: address hash → bank select.

    Each bank is an independent MetadataCachePipelined.
    Bank bits from address[bank_bits-1:0] select the bank.
    """
    def __init__(self, bank_count=2, **kwargs):
        self.bank_count = bank_count
        self.bank_kwargs = kwargs
        self.request_valid = Signal(); self.request_ready = Signal()
        self.request_addr = Signal(32); self.request_source = Signal(4)
        self.rsp_valid = Signal(); self.rsp_ready = Signal()
        self.rsp_data = Signal(32); self.rsp_hit = Signal()
        self.fill_valid = Signal(); self.fill_ready = Signal()
        self.fill_addr = Signal(32); self.fill_data = Signal(32)
        self.busy = Signal(); self.error = Signal()
        self.input_event = GCBackendEventRecord()
        self.output_event = GCBackendEventRecord()

    def elaborate(self, platform):
        m = Module(); P = self
        bk = P.bank_count
        bk_bits = (bk - 1).bit_length() if bk > 1 else 1

        banks = [MetadataCachePipelined(**P.bank_kwargs) for _ in range(bk)]
        for i, b in enumerate(banks):
            m.submodules[f"bank_{i}"] = b

        # Bank select from address low bits
        bank_id = Signal(bk_bits)
        m.d.comb += bank_id.eq(P.request_addr[:bk_bits])

        # Dispatch: drive old signals only (bank's internal bridge maps to
        # GCBackendEvent).  Keep input_event passthrough for GCBackendEvent path
        # so event metadata (core_id/event_id/epoch/sequence) can be carried in
        # banked mode as well.
        for i in range(bk):
            sel = Signal(); m.d.comb += sel.eq(bank_id == i)
            m.d.comb += [
                banks[i].request_valid.eq(P.request_valid & sel),
                banks[i].request_addr.eq(P.request_addr),
                banks[i].request_source.eq(P.request_source),
                banks[i].input_event.fields["event_id"].eq(P.input_event.fields["event_id"]),
                banks[i].input_event.fields["core_id"].eq(P.input_event.fields["core_id"]),
                banks[i].input_event.fields["epoch"].eq(P.input_event.fields["epoch"]),
                banks[i].input_event.fields["sequence"].eq(P.input_event.fields["sequence"]),
            ]

        # Request ready: Mux tree over bank_id
        rr = Const(0)
        for i in range(bk):
            rr = Mux(bank_id == i, banks[i].request_ready, rr)
        m.d.comb += P.request_ready.eq(rr)

        # Response priority encoder (lower bank wins, Mux tree, no comb cycle)
        rsp_sel_v = Const(0); rsp_hit_v = Const(0); rsp_data_v = Const(0)
        prev_rsp = Const(0)
        for i in range(bk):
            rsp_sel_v = rsp_sel_v | banks[i].rsp_valid
            rsp_hit_v = Mux(banks[i].rsp_valid & ~prev_rsp, banks[i].rsp_hit, rsp_hit_v)
            rsp_data_v = Mux(banks[i].rsp_valid & ~prev_rsp, banks[i].rsp_data, rsp_data_v)
            prev_rsp = prev_rsp | banks[i].rsp_valid

        m.d.comb += [
            P.rsp_valid.eq(rsp_sel_v),
            P.rsp_hit.eq(Mux(rsp_sel_v, rsp_hit_v, 0)),
            P.rsp_data.eq(Mux(rsp_sel_v, rsp_data_v, 0)),
        ]

        # rsp_ready routing: only selected bank gets it
        rsp_go = Signal()
        m.d.comb += rsp_go.eq(P.rsp_ready & rsp_sel_v)
        for i in range(bk):
            bank_selected = Signal()
            m.d.comb += bank_selected.eq(banks[i].rsp_valid & rsp_sel_v)
            m.d.comb += banks[i].rsp_ready.eq(rsp_go)

        # Busy: OR of all banks (Mux tree)
        busy_v = Const(0)
        for i in range(bk):
            busy_v = busy_v | banks[i].busy
        m.d.comb += P.busy.eq(busy_v)

        # Fill: OR of all banks' fill_valid, Mux fill_addr
        fill_v = Const(0); fill_a = Const(0)
        prev_fill = Const(0)
        for i in range(bk):
            fill_v = fill_v | banks[i].fill_valid
            fill_a = Mux(banks[i].fill_valid & ~prev_fill, banks[i].fill_addr, fill_a)
            prev_fill = prev_fill | banks[i].fill_valid
        m.d.comb += [
            P.fill_valid.eq(fill_v),
            P.fill_addr.eq(fill_a),
            P.error.eq(0),
        ]
        for i in range(bk):
            m.d.comb += [
                banks[i].fill_ready.eq(P.fill_ready),
                banks[i].fill_data.eq(P.fill_data),
            ]

        # GCBackendEvent output bridge: read from selected bank
        out_ev_id = Const(0, 16); out_core_id = Const(0, 8)
        out_ep = Const(0, 8); out_sq = Const(0, 8); out_addr = Const(0, 32)
        prev_bank = Const(0)
        for i in range(bk):
            sel = banks[i].rsp_valid & ~prev_bank
            out_ev_id = Mux(sel, banks[i].output_event.fields["event_id"], out_ev_id)
            out_core_id = Mux(sel, banks[i].output_event.fields["core_id"], out_core_id)
            out_ep = Mux(sel, banks[i].output_event.fields["epoch"], out_ep)
            out_sq = Mux(sel, banks[i].output_event.fields["sequence"], out_sq)
            out_addr = Mux(sel, banks[i].output_event.fields["address"], out_addr)
            prev_bank = prev_bank | banks[i].rsp_valid
        m.d.comb += [
            P.output_event.valid.eq(P.rsp_valid),
            P.output_event.ready.eq(P.rsp_ready),
            P.output_event.fields["data"].eq(P.rsp_data),
            P.output_event.fields["event_id"].eq(out_ev_id),
            P.output_event.fields["core_id"].eq(out_core_id),
            P.output_event.fields["epoch"].eq(out_ep),
            P.output_event.fields["sequence"].eq(out_sq),
            P.output_event.fields["address"].eq(out_addr),
        ]
        return m


# ── 工厂函数 ──────────────────────────────────────────────────
def create_metadata_cache(impl: str, **kwargs):
    if impl == "standard": return MetadataCacheStandard(**kwargs)
    elif impl == "pipelined": return MetadataCachePipelined(**kwargs)
    elif impl == "banked": return MetadataCacheBanked(**kwargs)
    else: raise ValueError(f"Unknown metadata_pipeline_impl: {impl}")
