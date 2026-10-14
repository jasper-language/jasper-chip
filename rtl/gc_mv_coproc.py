# rtl/gc_mv_coproc.py
#
# GCMvCoProc（移动/转发表协处理器）
# --------------------------------
# Step7（A->B->C 之后的下一步，面向可扩展性）：
#   - 引入 cmd_tag/rsp_tag，用 tag 做请求/响应匹配（为“多 outstanding + 乱序返回”铺路）
#   - 增加一个最小的“乱序返回”模型：同一核最多缓存 2 条 pending，按 delay=tag[1:0]
#     计数到 0 后即可返回；如果两条同时就绪，优先返回 slot1 -> slot0，从而制造乱序。
#
# Step47：把“RELOC 产生的 old->new 转发表”真正落地：
#   - MV_RELOC：写入 forwarding table（old=rs1, new=rs2），并返回 0
#   - MV_QUERY：查询 forwarding table，如果命中返回 new，否则返回 rs1
#   - 额外提供 SoC 级 sideband：upd_valid/old/new（由 sweep RELOC commit 触发），
#     用于确保读屏障与 sweep 的 relocation 语义一致（避免 CPU 侧提前/错误写表）。
#
# Step48：
#   - forwarding table 的 lookup 改为“最新写入优先”（ring wrap 后仍 latest-wins）
#   - MV_QUERY 支持有限深度 chase（old->mid->new），默认深度 2
#
# Step49：
#   - forwarding table 改为 SoC 级共享（跨核可见），避免“core0 relocate 对 core1 不可见”。
#     仍保持 Step48 的 latest-wins 与 chase 语义。
#
# 说明：
#   - 这是研究/验证用模型，不代表最终硬件实现形态。
#   - forwarding table 采用小型寄存器 CAM（map_depth 条），足以支撑“最小可验证读屏障”。

from amaranth import *
from amaranth.lib.fifo import SyncFIFO


MV_RELOC = 0
MV_QUERY = 1


class GCMvCoProc(Elaboratable):
    def __init__(self, ncores=4, fifo_depth=8, map_depth=8, chase_depth=2):
        self.ncores = int(ncores)
        self.fifo_depth = int(fifo_depth)
        self.map_depth = int(map_depth)
        # Step48: MV_QUERY will optionally chase forwarding pointers.
        # chase_depth=1 means a single lookup (old->new).
        # chase_depth>=2 means do lookup(lookup(old))... up to the depth.
        self.chase_depth = int(chase_depth)

        # Step52: epoch support. When epoch_advance pulses, MV toggles epoch bit.
        # Forwarding entries are tagged with epoch, and lookups only match current epoch.
        self.epoch_advance = Signal(name="mv_epoch_advance")

        # 命令（每核入队）
        self.cmd_enq_valid = Array(Signal(name=f"mvcmd{i}_valid") for i in range(self.ncores))
        self.cmd_enq_ready = Array(Signal(name=f"mvcmd{i}_ready") for i in range(self.ncores))
        self.cmd_tag       = Array(Signal(8, name=f"mvcmd{i}_tag") for i in range(self.ncores))
        self.cmd_op        = Array(Signal(3, name=f"mvcmd{i}_op") for i in range(self.ncores))
        self.cmd_rd        = Array(Signal(5, name=f"mvcmd{i}_rd") for i in range(self.ncores))
        self.cmd_rs1       = Array(Signal(32, name=f"mvcmd{i}_rs1") for i in range(self.ncores))
        self.cmd_rs2       = Array(Signal(32, name=f"mvcmd{i}_rs2") for i in range(self.ncores))

        # 响应（每核一个 response slot，由 take 清除）
        self.rsp_valid = Array(Signal(name=f"mvrsp{i}_valid") for i in range(self.ncores))
        self.rsp_tag   = Array(Signal(8, name=f"mvrsp{i}_tag") for i in range(self.ncores))
        self.rsp_rd    = Array(Signal(5, name=f"mvrsp{i}_rd") for i in range(self.ncores))
        self.rsp_data  = Array(Signal(32, name=f"mvrsp{i}_data") for i in range(self.ncores))
        self.rsp_take  = Array(Signal(name=f"mvrsp{i}_take") for i in range(self.ncores))

        self.trap = Array(Signal(name=f"mvtrap{i}") for i in range(self.ncores))

        # Step47: forwarding-table updates from sweep RELOC commit (per-core pulse)
        # Step49: table is shared, but inputs remain per-core for easy wiring.
        self.upd_valid = Array(Signal(name=f"mvupd{i}_valid") for i in range(self.ncores))
        self.upd_old   = Array(Signal(32, name=f"mvupd{i}_old") for i in range(self.ncores))
        self.upd_new   = Array(Signal(32, name=f"mvupd{i}_new") for i in range(self.ncores))
        self.upd_epoch = Array(Signal(1, name=f"mvupd{i}_epoch") for i in range(self.ncores))

    def elaborate(self, platform):
        m = Module()

        # -------------------------------------------------
        # Forwarding table (SoC-wide shared, tiny CAM)
        # -------------------------------------------------
        map_valid = Array(Signal(name=f"mvmap_v{j}") for j in range(self.map_depth))
        map_old   = Array(Signal(32, name=f"mvmap_o{j}") for j in range(self.map_depth))
        map_new   = Array(Signal(32, name=f"mvmap_n{j}") for j in range(self.map_depth))
        map_epoch = Array(Signal(1, name=f"mvmap_e{j}") for j in range(self.map_depth))
        map_ptr   = Signal(range(self.map_depth), reset=0, name="mvmap_ptr")

        # Step52: current epoch bit (toggles on epoch_advance)
        epoch = Signal(1, reset=0, name="mv_epoch")
        with m.If(self.epoch_advance):
            m.d.sync += epoch.eq(~epoch)

        # -------------------------------------------------
        # Step48: combinational lookup must be *recency correct*.
        #
        # The table is a ring buffer (map_ptr points to the next write slot).
        # If the same key is written multiple times and the ring wraps, we must
        # return the newest mapping, not the one with the highest physical index.
        #
        # Strategy: search newest->oldest by walking indices:
        #   (ptr-1), (ptr-2), ..., (ptr-map_depth) with wrap.
        # -------------------------------------------------
        def lookup_latest(key: Value) -> Value:
            out_v = key
            found_v = Const(0)
            ptr = map_ptr
            for k in range(1, self.map_depth + 1):
                idx = Mux(ptr >= k, ptr - k, ptr + (self.map_depth - k))
                hit = map_valid[idx] & (map_epoch[idx] == epoch) & (map_old[idx] == key)
                choose = (~found_v) & hit
                out_v = Mux(choose, map_new[idx], out_v)
                found_v = found_v | hit
            return out_v

        def lookup_chain(key: Value) -> Value:
            out = lookup_latest(key)
            for _ in range(1, max(1, self.chase_depth)):
                out = lookup_latest(out)
            return out

        # -------------------------------------------------
        # Sideband updates may (in corner tests) arrive from multiple cores in the same cycle.
        # Step51: make updates robust by buffering and draining (latest-wins in ring still holds).
        #
        # Strategy:
        #   - Capture per-core sideband updates into per-core pending slots (depth=1 each).
        #   - Capture command-path MV_RELOC writes into a separate pending slot.
        #   - Drain at most 1 update per cycle into the shared forwarding table.
        #   - Priority: sideband > cmd; sideband drained round-robin to avoid starvation.
        #
        # Note: if the same source issues another update while its pending slot is still full,
        # we drop the new update and bump dbg_upd_overflow (should not happen for sweep engine).
        # -------------------------------------------------
        pending_sb = Array(Signal(name=f"mv_updpend{i}") for i in range(self.ncores))
        pending_old = Array(Signal(32, name=f"mv_updpend{i}_old") for i in range(self.ncores))
        pending_new = Array(Signal(32, name=f"mv_updpend{i}_new") for i in range(self.ncores))
        pending_epoch = Array(Signal(1, name=f"mv_updpend{i}_epoch") for i in range(self.ncores))

        pending_cmd = Signal(name="mv_updpend_cmd")
        pending_cmd_old = Signal(32, name="mv_updpend_cmd_old")
        pending_cmd_new = Signal(32, name="mv_updpend_cmd_new")

        upd_rr = Signal(range(self.ncores), name="mv_upd_rr")

        # Debug: how many updates were dropped due to pending-slot overflow.
        self.dbg_upd_overflow = Signal(32, name="mv_dbg_upd_overflow")

        # Comb: select which sideband pending slot to drain (round-robin, starting from upd_rr)
        sb_found = Signal(name="mv_sb_found")
        sb_sel = Signal(range(self.ncores), name="mv_sb_sel")

        found_v = Const(0)
        sel_v = Const(0)
        for k in range(self.ncores):
            idx = upd_rr + k
            idx = Mux(idx >= self.ncores, idx - self.ncores, idx)
            hit = pending_sb[idx] | self.upd_valid[idx]
            choose = (~found_v) & hit
            sel_v = Mux(choose, idx, sel_v)
            found_v = found_v | hit

        m.d.comb += [
            sb_found.eq(found_v),
            sb_sel.eq(sel_v),
        ]

        # True when we are draining a *fresh* sideband update (not an already pending one).
        sb_drain_fresh = Signal(name="mv_sb_drain_fresh")
        m.d.comb += sb_drain_fresh.eq(sb_found & (~pending_sb[sb_sel]) & self.upd_valid[sb_sel])

        # Sync: capture sideband updates into pending slots
        for i in range(self.ncores):
            with m.If(self.upd_valid[i] & (~pending_sb[i]) & (~(sb_drain_fresh & (sb_sel == i)))):
                m.d.sync += [
                    pending_sb[i].eq(1),
                    pending_old[i].eq(self.upd_old[i]),
                    pending_new[i].eq(self.upd_new[i]),
                    pending_epoch[i].eq(self.upd_epoch[i]),
                ]
            with m.Elif(self.upd_valid[i] & pending_sb[i]):
                m.d.sync += self.dbg_upd_overflow.eq(self.dbg_upd_overflow + 1)

        # -------------------------------------------------
        # per-core fifo（把 tag 一起入队）

        # -------------------------------------------------
        fifos_list = []
        for i in range(self.ncores):
            fifo = SyncFIFO(width=8 + 3 + 5 + 32 + 32, depth=self.fifo_depth)
            fifos_list.append(fifo)
            m.submodules[f"mv_fifo{i}"] = fifo

            m.d.comb += [
                fifo.w_data.eq(Cat(self.cmd_tag[i], self.cmd_op[i], self.cmd_rd[i], self.cmd_rs1[i], self.cmd_rs2[i])),
                fifo.w_en.eq(self.cmd_enq_valid[i] & fifo.w_rdy),
                self.cmd_enq_ready[i].eq(fifo.w_rdy),
            ]

            with m.If(self.rsp_take[i]):
                m.d.sync += self.rsp_valid[i].eq(0)

            m.d.comb += self.trap[i].eq(0)

        fifos = Array(fifos_list)

        # round-robin 选择一个有数据的核
        rr_ptr = Signal(range(self.ncores), reset=0)
        sel = Signal(range(self.ncores))
        have = Signal()

        sel_v = rr_ptr
        have_rr = Const(0)
        for k in range(self.ncores):
            idx = rr_ptr + k
            idx = Mux(idx >= self.ncores, idx - self.ncores, idx)
            req = fifos[idx].r_rdy
            sel_v = Mux((~have_rr) & req, idx, sel_v)
            have_rr = have_rr | req

        m.d.comb += [sel.eq(sel_v), have.eq(have_rr)]

        # ----------------------
        # pending slots（同一核最多缓存 2 条，制造乱序返回）
        # ----------------------
        p_valid  = Array(Signal(2, name=f"p{i}_valid") for i in range(self.ncores))
        p_tag0   = Array(Signal(8, name=f"p{i}_tag0") for i in range(self.ncores))
        p_tag1   = Array(Signal(8, name=f"p{i}_tag1") for i in range(self.ncores))
        p_op0    = Array(Signal(3, name=f"p{i}_op0") for i in range(self.ncores))
        p_op1    = Array(Signal(3, name=f"p{i}_op1") for i in range(self.ncores))
        p_rd0    = Array(Signal(5, name=f"p{i}_rd0") for i in range(self.ncores))
        p_rd1    = Array(Signal(5, name=f"p{i}_rd1") for i in range(self.ncores))
        p_rs10   = Array(Signal(32, name=f"p{i}_rs10") for i in range(self.ncores))
        p_rs11   = Array(Signal(32, name=f"p{i}_rs11") for i in range(self.ncores))
        p_rs20   = Array(Signal(32, name=f"p{i}_rs20") for i in range(self.ncores))
        p_rs21   = Array(Signal(32, name=f"p{i}_rs21") for i in range(self.ncores))
        p_delay0 = Array(Signal(2, name=f"p{i}_dly0") for i in range(self.ncores))
        p_delay1 = Array(Signal(2, name=f"p{i}_dly1") for i in range(self.ncores))

        # 每拍 delay 递减（独立于 rr 选择）
        for i in range(self.ncores):
            with m.If(p_valid[i][0] & (p_delay0[i] != 0)):
                m.d.sync += p_delay0[i].eq(p_delay0[i] - 1)
            with m.If(p_valid[i][1] & (p_delay1[i] != 0)):
                m.d.sync += p_delay1[i].eq(p_delay1[i] - 1)

        # 如果选中的核有 fifo 数据，并且该核有空 pending slot，则读取 fifo 放入 pending
        free0 = Signal()
        free1 = Signal()
        m.d.comb += [
            free0.eq(~p_valid[sel][0]),
            free1.eq(~p_valid[sel][1]),
        ]

        can_deq = Signal()
        m.d.comb += can_deq.eq(have & (free0 | free1))

        # fifo 字段
        f_tag = Signal(8)
        f_op  = Signal(3)
        f_rd  = Signal(5)
        f_rs1 = Signal(32)
        f_rs2 = Signal(32)
        m.d.comb += [
            f_tag.eq(fifos[sel].r_data[0:8]),
            f_op.eq(fifos[sel].r_data[8:11]),
            f_rd.eq(fifos[sel].r_data[11:16]),
            f_rs1.eq(fifos[sel].r_data[16:48]),
            f_rs2.eq(fifos[sel].r_data[48:80]),
            fifos[sel].r_en.eq(can_deq),
        ]

        # ---------------------------------------------
        # Command-path MV_RELOC capture (writes into same update drain path)
        # ---------------------------------------------
        do_cmd_reloc = Signal(name="do_cmd_reloc")
        m.d.comb += do_cmd_reloc.eq(can_deq & (f_op == MV_RELOC))

        # ---------------------------------------------
        # Drain ONE update into the shared forwarding table per cycle.
        # Priority: sideband (sb_found) > pending_cmd > immediate cmd-path.
        #
        # For sideband, we may drain an update that arrives in the same cycle (self.upd_valid),
        # preserving Step47/48 behavior for the common case "at most one update per cycle".
        # ---------------------------------------------
        sb_old = Signal(32, name="mv_sb_old")
        sb_new = Signal(32, name="mv_sb_new")
        sb_epoch = Signal(1, name="mv_sb_epoch")
        m.d.comb += [
            sb_old.eq(Mux(pending_sb[sb_sel], pending_old[sb_sel], self.upd_old[sb_sel])),
            sb_new.eq(Mux(pending_sb[sb_sel], pending_new[sb_sel], self.upd_new[sb_sel])),
            sb_epoch.eq(Mux(pending_sb[sb_sel], pending_epoch[sb_sel], self.upd_epoch[sb_sel])),
        ]

        # True when we are draining a *fresh* sideband update (not an already pending one).

        cmd_apply_now = Signal(name="mv_cmd_apply_now")
        m.d.comb += cmd_apply_now.eq((~sb_found) & (~pending_cmd) & do_cmd_reloc)

        with m.If(sb_found):
            # Drain sideband (pending or fresh)
            m.d.sync += [
                map_valid[map_ptr].eq(1),
                map_old[map_ptr].eq(sb_old),
                map_new[map_ptr].eq(sb_new),
                map_epoch[map_ptr].eq(sb_epoch),
                map_ptr.eq(Mux(map_ptr == (self.map_depth - 1), 0, map_ptr + 1)),
                upd_rr.eq(Mux(sb_sel == (self.ncores - 1), 0, sb_sel + 1)),
            ]
            # If we drained an already pending slot, clear it.
            with m.If(pending_sb[sb_sel]):
                m.d.sync += pending_sb[sb_sel].eq(0)

        with m.Elif(pending_cmd):
            m.d.sync += [
                map_valid[map_ptr].eq(1),
                map_old[map_ptr].eq(pending_cmd_old),
                map_new[map_ptr].eq(pending_cmd_new),
                map_epoch[map_ptr].eq(epoch),
                map_ptr.eq(Mux(map_ptr == (self.map_depth - 1), 0, map_ptr + 1)),
                pending_cmd.eq(0),
            ]

        with m.Elif(cmd_apply_now):
            # Apply cmd-path write immediately (no backlog)
            m.d.sync += [
                map_valid[map_ptr].eq(1),
                map_old[map_ptr].eq(f_rs1),
                map_new[map_ptr].eq(f_rs2),
                map_epoch[map_ptr].eq(epoch),
                map_ptr.eq(Mux(map_ptr == (self.map_depth - 1), 0, map_ptr + 1)),
            ]

        with m.Else():
            pass

        # ---------------------------------------------
        # Capture cmd-path MV_RELOC into pending slot when not applied immediately
        # ---------------------------------------------
        with m.If(do_cmd_reloc & (~cmd_apply_now)):
            with m.If(~pending_cmd):
                m.d.sync += [
                    pending_cmd.eq(1),
                    pending_cmd_old.eq(f_rs1),
                    pending_cmd_new.eq(f_rs2),
                ]
            with m.Else():
                m.d.sync += self.dbg_upd_overflow.eq(self.dbg_upd_overflow + 1)

        with m.If(can_deq):
            # 读取后 rr 前进
            m.d.sync += rr_ptr.eq(sel + 1)

            # delay = tag[1:0]（可控、可复现）
            dly = f_tag[0:2]

            # 放入空 slot：先 slot0 再 slot1
            with m.If(free0):
                m.d.sync += [
                    p_valid[sel][0].eq(1),
                    p_tag0[sel].eq(f_tag),
                    p_op0[sel].eq(f_op),
                    p_rd0[sel].eq(f_rd),
                    p_rs10[sel].eq(f_rs1),
                    p_rs20[sel].eq(f_rs2),
                    p_delay0[sel].eq(dly),
                ]
            with m.Else():
                m.d.sync += [
                    p_valid[sel][1].eq(1),
                    p_tag1[sel].eq(f_tag),
                    p_op1[sel].eq(f_op),
                    p_rd1[sel].eq(f_rd),
                    p_rs11[sel].eq(f_rs1),
                    p_rs21[sel].eq(f_rs2),
                    p_delay1[sel].eq(dly),
                ]

        # ----------------------
        # 生成响应：每核一个 response slot；slot1 优先 -> slot0
        # ----------------------
        for i in range(self.ncores):
            can_rsp = Signal(name=f"can_rsp{i}")
            s1_ready = Signal(name=f"s1_ready{i}")
            s0_ready = Signal(name=f"s0_ready{i}")

            m.d.comb += [
                can_rsp.eq(~self.rsp_valid[i]),
                s1_ready.eq(p_valid[i][1] & (p_delay1[i] == 0)),
                s0_ready.eq(p_valid[i][0] & (p_delay0[i] == 0)),
            ]

            with m.If(can_rsp & (s1_ready | s0_ready)):
                with m.If(s1_ready):
                    data1 = Signal(32, name=f"rsp_data1_{i}")
                    m.d.comb += data1.eq(Mux(p_op1[i] == MV_QUERY, lookup_chain(p_rs11[i]), Const(0, 32)))
                    m.d.sync += [
                        self.rsp_valid[i].eq(1),
                        self.rsp_tag[i].eq(p_tag1[i]),
                        self.rsp_rd[i].eq(p_rd1[i]),
                        self.rsp_data[i].eq(data1),
                        p_valid[i][1].eq(0),
                    ]
                with m.Else():
                    data0 = Signal(32, name=f"rsp_data0_{i}")
                    m.d.comb += data0.eq(Mux(p_op0[i] == MV_QUERY, lookup_chain(p_rs10[i]), Const(0, 32)))
                    m.d.sync += [
                        self.rsp_valid[i].eq(1),
                        self.rsp_tag[i].eq(p_tag0[i]),
                        self.rsp_rd[i].eq(p_rd0[i]),
                        self.rsp_data[i].eq(data0),
                        p_valid[i][0].eq(0),
                    ]

        return m