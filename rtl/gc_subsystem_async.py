# rtl/gc_subsystem_async.py
# 异步 GC 退休：GC_NEW/DROP/CLONE/PIN/UNPIN 永不 stall CPU 流水线。
#
# 关键变更 vs gc_subsystem.py：
#   - gc_fire 不再依赖 gc_enq_ready — 插槽分配即退休（写 rd 标记为"等待中"）
#   - 新增 GCReplayFIFO (depth=2) 解耦插槽分配与命令发送
#   - stall_gc_issue 不再 stall 流水线（仅当 replay FIFO 满 + gc_enq_ready 假时做安全阀）
#   - stall_gc_order 仍有效 — 16 插槽全满时不能退休
#   - 分数板 (scoreboard) 跟踪待响应的 rd，依赖指令在 issue 阶段自然等（像 cache miss）
#   - 旁路网络 (forwarding) 从 GC 响应写回 rd，OoO 核自动唤醒

from amaranth import *
from amaranth.lib.fifo import SyncFIFO

from .gc_config import get_profile as _get_gc_profile, JasperGCConfig
from .gc_slots_bank import create_slots_bank
from .gc_wb_combine import GCWBCombine

def with_gc_profile(profile: str, **kwargs):
    cfg = _get_gc_profile(profile)
    d = cfg.to_dict()
    d.update(kwargs)
    return GCSubsystemAsync(**d)

def _bits(n):
    return (n - 1).bit_length() if n > 1 else 1


class GCSubsystemAsync(Elaboratable):
    """异步 GC 退休子系统 — GC 指令永不 stall 流水线。"""
    def __init__(self, core_id=0, gc_slots=16, rb_cache_ways=4, rb_slots=4,
                 wb_depth=4, mv_depth=4, wb_ptr_filter=0,
                 wb_card_shift=6, wb_obj_shift=4, rb_mode=0, debug=False,
                 wb_combine_depth=0,
                 gc_slots_bank_impl="standard", gc_slots_bank_count=1):
        self.core_id = core_id
        self.core_id_out = Signal()
        self.stat_gc_fire_count = Signal(32)
        self.stat_wb_events = Signal(32)
        self.stat_rb_queries = Signal(32)
        self.stat_stall_cycles = Signal(32)
        self._gc_slots = gc_slots
        self._rb_cache_ways = rb_cache_ways
        self._rb_slots = rb_slots
        self._wb_depth = wb_depth
        self._mv_depth = mv_depth
        self._wb_ptr_filter = wb_ptr_filter
        self._wb_card_shift = wb_card_shift
        self._wb_obj_shift = wb_obj_shift
        self._rb_mode = rb_mode
        self._debug = debug
        self._wb_combine_depth = wb_combine_depth
        self._gc_slots_bank_impl = gc_slots_bank_impl
        self._gc_slots_bank_count = max(1, gc_slots_bank_count)

        bi = _bits
        inp = dict(
            is_valid=1, is_opcode=7, is_rd=5, is_funct3=3, is_rs1=5, is_rs2=5,
            id2_valid=1, id2_rd=5, id2_is_gc=1, id2_is_load=1, id2_opcode=7,
            mem1_valid=1, mem1_is_store=1, mem1_addr=32, mem1_wdata=32,
            mem2_valid=1, mem2_is_load=1, mem2_rd=5, mem2_addr=32,
            mem2_wb_data=32, mem2_wb_en=1,
            wb_valid=1, wb_is_load=1, wb_rd=5, wb_wb_en=1, wb_wb_data=32,
            ex1_valid=1, ex1_wb_en=1, ex1_rd=5, ex1_wb_data=32,
            ex2_valid=1, ex2_wb_en=1, ex2_rd=5, ex2_wb_data=32,
            mem1_valid2=1, mem1_wb_en=1, mem1_rd=5, mem1_wb_data=32,
        )
        for s, w in inp.items():
            setattr(self, s, Signal(w))

        self.stall = Signal()
        self.stall_dep_id2 = Signal()
        self.fence_active = Signal()
        self.dmem_grant = Signal(reset=1)
        self.rb_inj_valid = Signal()
        self.rb_inj_value = Signal(32)
        self.rb_inj_rd = Signal(5)

        # Coprocessor inputs
        self.gc_enq_ready = Signal()
        self.gc_rsp_valid = Signal()
        self.gc_rsp_tag = Signal(8)
        self.gc_rsp_rd = Signal(5)
        self.gc_rsp_data = Signal(32)
        self.mv_cmd_ready = Signal()
        self.mv_rsp_valid = Signal()
        self.mv_rsp_tag = Signal(8)
        self.mv_rsp_rd = Signal(5)
        self.mv_rsp_data = Signal(32)
        self.wb_enq_ready = Signal()

        gl = bi(gc_slots)
        rl = bi(rb_slots)
        ce = bi(rb_cache_ways)
        self.gc_fire = Signal()
        self.gc_rsp_match = Signal()
        self.gc_rsp_match_idx = Signal(gl)
        self.cache_hit = Signal()
        self.cache_hit_data = Signal(32)
        self.cache_hit_fire = Signal()
        self.fire = Signal()
        self.stall_rb = Signal()
        self.stall_store = Signal()
        self.stall_gc_order = Signal()
        self.stall_gc_issue = Signal()
        self.pending_rd_mask = Signal(32)
        self.gc_fwd_rs1 = Signal(32)
        self.gc_fwd_rs2 = Signal(32)
        self.free_found = Signal()
        self.free_idx = Signal(rl)
        self.match_found = Signal()
        self.match_idx = Signal(rl)
        self.sel_rd = Signal(5)
        self.sel_val = Signal(32)
        self.mv_tag_ctr = Signal(8)
        self.mv_reloc_fire = Signal()
        self.is_gc_mv_reloc = Signal()
        self.mv_bp_valid = Signal()
        self.mv_bp_rd = Signal(5)
        self.mv_bp_data = Signal(32)
        self.barrier_need = Signal()
        self.need_load_rb = Signal()
        self.enq_ready = Signal()
        self.wb_enq_valid = Signal()
        self.wb_addr = Signal(32)
        self.wb_data = Signal(32)
        self.rb_inj_ready = Signal()
        self.gc_enq_valid = Signal()
        self.gc_tag = Signal(8)
        self.gc_op = Signal(3)
        self.gc_rd_out = Signal(5)
        self.gc_rs1 = Signal(32)
        self.gc_rs2 = Signal(32)
        self.gc_rsp_take = Signal()
        self.mv_cmd_valid = Signal()
        self.mv_cmd_op = Signal(3)
        self.mv_cmd_rd = Signal(5)
        self.mv_cmd_rs1 = Signal(32)
        self.mv_cmd_rs2 = Signal(32)
        self.mv_cmd_tag = Signal(8)

        if self._debug:
            self.dbg_gc_fire = Signal()
            self.dbg_gc_waiting = Signal()

    def elaborate(self, platform):
        m = Module()
        GC = self._gc_slots; RBL = self._rb_slots
        RBW = self._rb_cache_ways; WBD = self._wb_depth; MVD = self._mv_depth
        gl = _bits(GC); rl = _bits(RBL)

        def prio_enc(signals):
            """Return (found, idx) — first 1 in list of 1-bit signals.
            Flat Mux chain avoids O(2^N) AST blowup in Amaranth shape inference."""
            found = Const(0)
            idx = Const(0)
            for i, s in enumerate(signals):
                # Condition is s at i=0 (no prior found), ~prev_found at i>0.
                # True → keep idx (already found, or haven't found yet).
                # False → capture i (this slot is the first free one).
                idx = Mux(found if i > 0 else s, idx, Const(i, _bits(len(signals))))
                found = found | s  # Must update AFTER idx (bug fix)
            return found, idx

        # ── GC slots bank (supports standard or banked) ──
        m.submodules.gc_slots = gc_slots = create_slots_bank(
            self._gc_slots_bank_impl, gc_slots=GC, bank_count=self._gc_slots_bank_count)
        gc_tag_ctr = Signal(8)

        # GCReq replay FIFO (depth=2): decouples slot alloc from engine enqueue
        m.submodules.gc_replay = gc_replay = SyncFIFO(
            width=8 + 3 + 5 + 32 + 32, depth=2)
        m.d.comb += [
            gc_replay.r_en.eq(gc_replay.r_rdy & self.gc_enq_ready),
        ]

        # gc_fire: only depends on slot available, never on gc_enq_ready
        m.d.comb += self.gc_fire.eq(
            self.is_valid & (self.is_opcode == 11) & (~self.is_gc_mv_reloc) &
            gc_slots.alloc_ready & ~self.fence_active & ~self.stall)

        # Alloc
        m.d.comb += [
            gc_slots.alloc_valid.eq(self.gc_fire),
            gc_slots.alloc_tag.eq(gc_tag_ctr),
        ]
        with m.If(self.gc_fire):
            m.d.sync += gc_tag_ctr.eq(gc_tag_ctr + 1)
            # Push to replay FIFO (combinational, captured at posedge)
            m.d.comb += gc_replay.w_en.eq(1)
            m.d.comb += gc_replay.w_data.eq(Cat(
                gc_tag_ctr, self.is_funct3, self.is_rd,
                self.gc_fwd_rs1, self.gc_fwd_rs2))

        # Replay FIFO drives GC engine outputs
        m.d.comb += [
            self.gc_enq_valid.eq(gc_replay.r_rdy),
            self.gc_tag.eq(gc_replay.r_data[0:8]),
            self.gc_op.eq(gc_replay.r_data[8:11]),
            self.gc_rd_out.eq(gc_replay.r_data[11:16]),
            self.gc_rs1.eq(gc_replay.r_data[16:48]),
            self.gc_rs2.eq(gc_replay.r_data[48:80]),
        ]

        # GC response match via bank
        m.d.comb += [
            gc_slots.match_valid.eq(self.gc_rsp_valid),
            gc_slots.match_tag.eq(self.gc_rsp_tag),
            gc_slots.free_valid.eq(gc_slots.match_found & self.gc_rsp_valid),
            gc_slots.free_tag.eq(self.gc_rsp_tag),
            self.gc_rsp_match.eq(gc_slots.match_found),
            self.gc_rsp_match_idx.eq(Mux(gc_slots.match_found, gc_slots.match_idx, 0)),
            self.gc_rsp_take.eq(gc_slots.match_found),
        ]

        # GC stall signals
        m.d.comb += [
            self.is_gc_mv_reloc.eq(self.is_valid & (self.is_opcode == 11) & (self.is_funct3 == 7)),
            self.stall_gc_order.eq(self.is_valid & (self.is_opcode == 11) &
                                   (~self.is_gc_mv_reloc) & (~gc_slots.alloc_ready)),
            # stall_gc_issue: ONLY when replay FIFO full AND gc_enq_ready false
            # (depth=2, extremely rare; primarily acts as safety valve)
            self.stall_gc_issue.eq(self.is_valid & (self.is_opcode == 11) &
                                   (~self.is_gc_mv_reloc) & gc_slots.alloc_ready &
                                   (~gc_replay.w_rdy) & ~self.fence_active),
            self.mv_reloc_fire.eq(self.is_gc_mv_reloc & self.mv_cmd_ready & ~self.stall),
        ]

        # ── GC forwarding (2×6-stage Mux) ──
        def fwd_chain(signal, src):
            val = Const(0)
            for valid, rd, data in src:
                val = Mux(valid & (rd == signal) & (rd != 0), data, val)
            return val

        fwd_src1 = [
            (self.wb_valid & self.wb_wb_en, self.wb_rd, self.wb_wb_data),
            (self.mem2_valid & self.mem2_wb_en, self.mem2_rd, self.mem2_wb_data),
            (self.mem1_valid2 & self.mem1_wb_en, self.mem1_rd, self.mem1_wb_data),
            (self.ex2_valid & self.ex2_wb_en, self.ex2_rd, self.ex2_wb_data),
            (self.ex1_valid & self.ex1_wb_en, self.ex1_rd, self.ex1_wb_data),
            (gc_slots.match_found & (self.gc_rsp_rd == self.is_rs1), self.gc_rsp_rd, self.gc_rsp_data),
        ]
        fwd_src2 = [
            (self.wb_valid & self.wb_wb_en, self.wb_rd, self.wb_wb_data),
            (self.mem2_valid & self.mem2_wb_en, self.mem2_rd, self.mem2_wb_data),
            (self.mem1_valid2 & self.mem1_wb_en, self.mem1_rd, self.mem1_wb_data),
            (self.ex2_valid & self.ex2_wb_en, self.ex2_rd, self.ex2_wb_data),
            (self.ex1_valid & self.ex1_wb_en, self.ex1_rd, self.ex1_wb_data),
            (gc_slots.match_found & (self.gc_rsp_rd == self.is_rs2), self.gc_rsp_rd, self.gc_rsp_data),
        ]
        m.d.comb += [
            self.gc_fwd_rs1.eq(fwd_chain(self.is_rs1, fwd_src1)),
            self.gc_fwd_rs2.eq(fwd_chain(self.is_rs2, fwd_src2)),
        ]

        # ── RB pending table ──
        rv = Array([Signal() for _ in range(RBL)])
        rt = Array([Signal(8) for _ in range(RBL)])
        rr = Array([Signal(5) for _ in range(RBL)])
        rk = Array([Signal(32) for _ in range(RBL)])

        rb_free_found, rb_free_idx = prio_enc([~v for v in rv])
        m.d.comb += [self.free_found.eq(rb_free_found), self.free_idx.eq(rb_free_idx)]

        mv_tag = Signal(8)
        m.d.sync += mv_tag.eq(mv_tag + 1)
        m.d.comb += self.mv_tag_ctr.eq(mv_tag)

        mv_rm, mv_ri = prio_enc([rv[i] & (self.mv_rsp_tag == rt[i]) for i in range(RBL)])
        m.d.comb += [self.match_found.eq(mv_rm), self.match_idx.eq(Mux(mv_rm, mv_ri, 0))]

        inj_fire = Signal()
        m.d.comb += inj_fire.eq(self.rb_inj_valid & self.enq_ready)
        load_fire = Signal()
        m.d.comb += load_fire.eq(self.need_load_rb & self.enq_ready & ~inj_fire)
        m.d.comb += [
            self.fire.eq(load_fire | inj_fire),
            self.sel_rd.eq(Mux(load_fire, self.mem2_rd, Mux(inj_fire, self.rb_inj_rd, 0))),
            self.sel_val.eq(Mux(load_fire, self.mem2_wb_data, Mux(inj_fire, self.rb_inj_value, 0))),
            self.rb_inj_ready.eq(self.enq_ready & ~load_fire),
        ]
        with m.If(self.fire):
            m.d.sync += [
                rv[rb_free_idx].eq(1),
                rt[rb_free_idx].eq(mv_tag),
                rr[rb_free_idx].eq(self.sel_rd),
                rk[rb_free_idx].eq(self.sel_val),
            ]
        with m.If(mv_rm & self.mv_rsp_valid):
            m.d.sync += rv[mv_ri].eq(0)
            m.d.comb += [
                self.mv_bp_valid.eq(1),
                self.mv_bp_rd.eq(rr[mv_ri]),
                self.mv_bp_data.eq(self.mv_rsp_data),
            ]

        # ── RB Cache ──
        cache_idx = self.mem2_addr[0:2]
        cache_tag = self.mem2_wb_data[2:32]
        cv = Array([Signal() for _ in range(RBW)])
        ct = Array([Signal(30) for _ in range(RBW)])
        cd = Array([Signal(32) for _ in range(RBW)])
        crr = Signal(range(RBW), reset=0)
        m.d.comb += [
            self.cache_hit.eq(cv[cache_idx] & (ct[cache_idx] == cache_tag)),
            self.cache_hit_data.eq(cd[cache_idx]),
            self.cache_hit_fire.eq(self.need_load_rb & self.cache_hit & ~self.fire),
        ]
        with m.If(mv_rm & self.mv_rsp_valid):
            upd_tag = rk[mv_ri][2:32]
            m.d.sync += [
                cv[crr].eq(1),
                ct[crr].eq(upd_tag),
                cd[crr].eq(self.mv_rsp_data),
                crr.eq(Mux(crr == RBW - 1, 0, crr + 1)),
            ]

        # ── MV command queue ──
        m.submodules.mvq = mvq = SyncFIFO(width=80, depth=MVD)

        # ── RB stall + need_load_rb ──
        _rb = self._rb_mode
        _rb_cond = Signal()
        m.d.comb += _rb_cond.eq(Mux(_rb == 0, 1,
                               Mux(_rb == 1, self.mem2_addr[31],
                               self.mem2_addr[28:31] != 0)))
        m.d.comb += [
            self.need_load_rb.eq(self.mem2_valid & self.mem2_is_load & (self.mem2_rd != 0) & _rb_cond),
            self.stall_rb.eq(self.need_load_rb & (~self.fire) & (~self.cache_hit_fire)),
            self.enq_ready.eq(mvq.w_rdy & rb_free_found),
        ]
        MVQ = Const(1, 3)
        m.d.comb += [
            mvq.w_en.eq(self.fire),
            mvq.w_data.eq(Cat(mv_tag, MVQ, self.sel_rd, self.sel_val, Const(0, 32))),
            mvq.r_en.eq(mvq.r_rdy & self.mv_cmd_ready & ~self.is_gc_mv_reloc),
            self.mv_cmd_valid.eq(self.mv_reloc_fire | mvq.r_rdy),
            self.mv_cmd_tag.eq(Mux(self.mv_reloc_fire, mv_tag, mvq.r_data[0:8])),
            self.mv_cmd_op.eq(Mux(self.mv_reloc_fire, Const(0, 3), mvq.r_data[8:11])),
            self.mv_cmd_rd.eq(Mux(self.mv_reloc_fire, self.is_rd, mvq.r_data[11:16])),
            self.mv_cmd_rs1.eq(Mux(self.mv_reloc_fire, self.gc_fwd_rs1, mvq.r_data[16:48])),
            self.mv_cmd_rs2.eq(Mux(self.mv_reloc_fire, self.gc_fwd_rs2, mvq.r_data[48:80])),
        ]

        # ── WB FIFO ──
        m.submodules.wbq = wbq = SyncFIFO(width=64, depth=WBD)
        ptr_hit = Signal()
        m.d.comb += ptr_hit.eq(Mux(self._wb_ptr_filter == 1, self.mem1_wdata[31], 1))
        store_grant = Signal()
        m.d.comb += store_grant.eq(self.mem1_valid & self.mem1_is_store & self.dmem_grant)
        m.d.comb += self.barrier_need.eq(ptr_hit)

        if self._wb_combine_depth > 0:
            m.submodules.wb_combine = wb_combine = GCWBCombine(
                depth=self._wb_combine_depth)
            m.d.comb += [
                wb_combine.wb_combine_enable.eq(1),
                wb_combine.mem1_addr.eq(self.mem1_addr),
                wb_combine.mem1_is_store.eq(self.mem1_is_store),
                wb_combine.mem1_wdata.eq(self.mem1_wdata),
                wb_combine.store_grant.eq(store_grant),
                wb_combine.wb_card_shift.eq(self._wb_card_shift),
                wb_combine.wb_obj_shift.eq(self._wb_obj_shift),
                wb_combine.wb_ptr_filter.eq(self._wb_ptr_filter),
                wb_combine.flush.eq(0),
                wb_combine.wbq_w_rdy.eq(wbq.w_rdy),
                self.stall_store.eq(wb_combine.stall_store),
                wbq.w_data.eq(wb_combine.wbq_w_data),
                wbq.w_en.eq(wb_combine.wbq_w_en),
            ]
        else:
            m.d.comb += [
                self.stall_store.eq(ptr_hit & ~wbq.w_rdy),
                wbq.w_data.eq(Cat(self.mem1_addr >> self._wb_card_shift,
                                self.mem1_addr >> self._wb_obj_shift)),
                wbq.w_en.eq(store_grant & ptr_hit),
            ]

        m.d.comb += [
            self.wb_enq_valid.eq(wbq.r_rdy),
            self.wb_addr.eq(wbq.r_data[0:32]),
            self.wb_data.eq(wbq.r_data[32:64]),
        ]
        m.d.comb += wbq.r_en.eq(wbq.r_rdy & self.wb_enq_ready)

        # ── Scoreboard ──
        pnd = Signal(32, reset=0)
        pset = Signal(32)
        pclr = Signal(32)
        load_set = Signal()
        mv_set = Signal()
        mv_clr = Signal()
        gc_set = Signal()
        gc_clr = Signal()
        cache_clr = Signal()
        load_clr = Signal()
        id2_base = Signal()
        id2_set = Signal()
        m.d.comb += id2_base.eq(
            (~self.stall) & (~self.stall_dep_id2) & self.id2_valid & (self.id2_rd != 0))
        m.d.comb += [
            load_set.eq(id2_base & self.id2_is_load &
                        ~(pclr.bit_select(self.id2_rd, 1))),
            mv_set.eq(self.fire & (self.sel_rd != 0)),
            mv_clr.eq(self.mv_rsp_valid & mv_rm & (rr[mv_ri] != 0)),
            gc_set.eq(id2_base & self.id2_is_gc & (~self.is_gc_mv_reloc)),
            gc_clr.eq(gc_slots.match_found & (self.gc_rsp_rd != 0)),
            cache_clr.eq(self.cache_hit_fire & (self.mem2_rd != 0)),
            load_clr.eq(self.wb_valid & self.wb_is_load & (self.wb_rd != 0) & self.wb_wb_en),
            id2_set.eq(load_set | gc_set),
            pset.eq(Mux(id2_set, (Const(1, 32) << self.id2_rd), 0) |
                   Mux(mv_set,  (Const(1, 32) << self.sel_rd), 0)),
            pclr.eq(Mux(load_clr, (Const(1, 32) << self.wb_rd), 0) |
                   Mux(mv_clr, (Const(1, 32) << rr[mv_ri]), 0) |
                   Mux(cache_clr, (Const(1, 32) << self.mem2_rd), 0) |
                   Mux(gc_clr, (Const(1, 32) << self.gc_rsp_rd), 0)),
            self.pending_rd_mask.eq(pnd),
        ]
        m.d.sync += pnd.eq((pnd | pset) & ~pclr)

        m.d.comb += self.core_id_out.eq(self.core_id)
        if self._debug:
            m.d.sync += [
                self.stat_gc_fire_count.eq(self.stat_gc_fire_count + self.gc_fire),
                self.stat_wb_events.eq(self.stat_wb_events + (self.wb_enq_valid & self.wb_enq_ready)),
                self.stat_rb_queries.eq(self.stat_rb_queries + (self.fire & ~self.is_gc_mv_reloc)),
                self.stat_stall_cycles.eq(self.stat_stall_cycles + (self.stall_rb | self.stall_store | self.stall_gc_order | self.stall_gc_issue)),
            ]

        if self._debug:
            m.d.comb += [
                self.dbg_gc_fire.eq(self.gc_fire),
                self.dbg_gc_waiting.eq(gc_slots.busy),
            ]
        return m
