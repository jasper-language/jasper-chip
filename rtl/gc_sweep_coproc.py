# rtl/gc_sweep_coproc.py
#
# GCSweepCoProc（清理/引用计数 GC 协处理器）
# ---------------------------------------
#
# 说明：本模块是从 Step3 的 `GCCoProc` 拆分而来，当前仍然实现：
#   - GC 6 指令：NEW/DROP/CLONE/PIN/UNPIN/RELOC
#   - 每核 FIFO + 单引擎 round-robin（每 cycle 最多执行 1 条）
#
# 本轮目标：
#   - 只做“接口与文件拆分”，行为与原 GCCoProc 保持一致，
#     以免引入大改动影响可运行性。
#   - 同时修正一个更安全的写入方式：FIFO 只在 ready 时写入（w_en = valid & w_rdy）。

from amaranth import *
from amaranth.lib.fifo import SyncFIFO, SyncFIFOBuffered
from .isa import GC_NEW, GC_DROP, GC_CLONE, GC_PIN, GC_UNPIN, GC_RELOC, GC_EPOCH


class GCSweepCoProc(Elaboratable):
    def __init__(self, ncores=4, entries=256, fifo_depth=8, engine_latency=0,
                 card_dedup_enable=True, card_table_size=16, card_table_ways=1, card_index_mode=0):
        self.ncores = ncores
        self.entries = entries
        self.fifo_depth = fifo_depth
        # Step22：sweep 侧 card 去重（防止同 epoch 内重复处理同一卡）
        # - scan 侧已有去重，但在 redirty/多核写同一卡等情况下，sweep 仍可能看到重复 card。
        # - 这里采用一个轻量“直接映射表”：index = card_id 低位，记录 (card_id, epoch)。
        # - 同 epoch 命中则视为重复，计入 dup_drop，不增加 mark_count。
        self.card_dedup_enable = card_dedup_enable
        self.card_table_size = card_table_size
        self.card_table_ways = int(card_table_ways)
        self.card_index_mode = int(card_index_mode)  # 0: low bits, 1: xor-fold
        if self.card_table_ways < 1:
            raise ValueError("card_table_ways must be >= 1")
        # 要求 table_size 为 2 的幂（便于用低位做索引，综合友好）
        if self.card_table_size & (self.card_table_size - 1) != 0:
            raise ValueError("card_table_size must be power of two")


        # Step12：可选的协处理器引擎延迟（用于验证 CPU 不应被 GC 全局卡死）
        # - 0 表示保持原行为：取到命令的同一拍就产生响应
        # - >0 表示命令执行后，延迟若干拍再把 rsp_valid 拉高
        self.engine_latency = int(engine_latency)

        # Use Array so we can index with Signals
        # Step6-A：新增 tag（请求/响应匹配用）
        # 说明：
        #   - 研究阶段先用 8bit tag（每核本地递增即可）
        #   - 未来支持多 outstanding / out-of-order 返回时，核心侧用 tag 进行严格匹配
        self.tag_w = 8
        self.cmd_tag       = Array(Signal(self.tag_w, name=f"cmd{i}_tag") for i in range(ncores))
        self.cmd_enq_valid = Array(Signal(name=f"cmd{i}_valid") for i in range(ncores))
        self.cmd_enq_ready = Array(Signal(name=f"cmd{i}_ready") for i in range(ncores))
        self.cmd_op        = Array(Signal(3,  name=f"cmd{i}_op")   for i in range(ncores))
        self.cmd_rd        = Array(Signal(5,  name=f"cmd{i}_rd")   for i in range(ncores))
        self.cmd_rs1       = Array(Signal(32, name=f"cmd{i}_rs1")  for i in range(ncores))
        self.cmd_rs2       = Array(Signal(32, name=f"cmd{i}_rs2")  for i in range(ncores))

        self.rsp_valid     = Array(Signal(name=f"rsp{i}_valid") for i in range(ncores))
        self.rsp_tag       = Array(Signal(self.tag_w, name=f"rsp{i}_tag") for i in range(ncores))
        self.rsp_rd        = Array(Signal(5,  name=f"rsp{i}_rd") for i in range(ncores))
        self.rsp_data      = Array(Signal(32, name=f"rsp{i}_data") for i in range(ncores))
        self.rsp_take      = Array(Signal(name=f"rsp{i}_take") for i in range(ncores))

        self.trap          = Array(Signal(name=f"trap{i}") for i in range(ncores))

        # Step20：GC_EPOCH 指令支持
        # - 该指令用于推进 GC 的 epoch / generation（主要影响 scan 的去重生命周期）
        # - 为了让 SoC 层能“广播”给 scan，本模块提供一个按核的 epoch_tick 脉冲输出。
        #   TopSoC 可把所有核的 epoch_tick OR 起来作为 scan.epoch_advance。
        # Step20：由 GC_EPOCH 指令触发的 epoch 推进脉冲。
        # 语义：当某核执行 GC_EPOCH 并产生“响应”时，对应核的 epoch_tick 拉高 1 拍。
        self.epoch_tick    = Array(Signal(name=f"epoch{i}_tick") for i in range(ncores))

        # Step47：当 RELOC 成功提交时，向 mv 协处理器广播一个 old->new 的更新脉冲。
        # 这是 SoC 级 sideband，用于让读屏障查询与 sweep 的 relocation 语义保持一致。
        self.mv_upd_valid  = Array(Signal(name=f"mvupd{i}_valid") for i in range(ncores))
        self.mv_upd_old    = Array(Signal(32, name=f"mvupd{i}_old") for i in range(ncores))
        self.mv_upd_new    = Array(Signal(32, name=f"mvupd{i}_new") for i in range(ncores))

        # Step59：mv_upd 改为 valid/ready 语义（默认 ready=1，方便旧测试不显式连接）。
        # 目的：在 Clean->Move 链路背压时，避免 mv_upd 脉冲被 wrapper 1-slot pending 丢弃。
        self.mv_upd_ready  = Array(Signal(reset=1, name=f"mvupd{i}_ready") for i in range(ncores))

        # Step21：接收 scan 的 card stream（remembered-set 输出）
        # - scan 协处理器会把“被消费的 card”输出到 out_q，本模块可选择接收并做最小‘标记模拟’。
        # - 研究阶段先只做计数：每消费 1 条 card 记录，mark_count++，并记录 last_*。
        core_id_w = max(1, (ncores - 1).bit_length())
        self.card_in_valid = Signal(name="card_in_valid")
        self.card_in_ready = Signal(name="card_in_ready")
        self.card_in_card_id = Signal(32, name="card_in_card")
        self.card_in_core_id = Signal(core_id_w, name="card_in_core")
        self.card_in_epoch   = Signal(1,  name="card_in_epoch")

        # 统计：总共消费了多少条 card 记录（研究/测试用）
        self.mark_count_total = Signal(32, name="mark_cnt_total")
        # Step22：sweep 去重统计（同 epoch 内重复 card 计数）
        self.mark_dup_drop_total = Signal(32, name="mark_dup_drop_total")

        # Step24：更细的统计（研究/评估 table 冲突与替换）
        self.mark_hit_total   = Signal(32, name="mark_hit_total")
        self.mark_miss_total  = Signal(32, name="mark_miss_total")
        self.mark_replace_total = Signal(32, name="mark_replace_total")  # miss 且无可用槽时发生替换
        # 统计：按核计数（谁的 card 被置脏/扫描）
        self.mark_count_core = Array(Signal(32, name=f"mark_cnt_core{i}") for i in range(ncores))
        # 最近消费的一条 card 记录
        self.last_card_id = Signal(32, name="mark_last_card")
        self.last_core_id = Signal(core_id_w, name="mark_last_core")
        self.last_epoch   = Signal(1,  name="mark_last_epoch")

    def elaborate(self, platform):
        m = Module()

        # Step21：scan card stream 输入 FIFO（避免 out_q->sweep 形成组合环）
        core_id_w = max(1, (self.ncores - 1).bit_length())
        card_w = 32 + core_id_w + 1
        m.submodules.card_q = card_q = SyncFIFOBuffered(width=card_w, depth=16)

        # scan -> sweep 入队握手
        m.d.comb += [
            self.card_in_ready.eq(card_q.w_rdy),
            card_q.w_en.eq(self.card_in_valid & card_q.w_rdy),
            card_q.w_data.eq(Cat(self.card_in_card_id, self.card_in_core_id, self.card_in_epoch)),
        ]

        # 默认：每拍尽可能消费 1 条 card 记录（研究阶段足够）
        do_mark = Signal()
        m.d.comb += do_mark.eq(card_q.r_rdy)
        m.d.comb += card_q.r_en.eq(do_mark)

        
        # Step22/23：sweep 侧 card 去重（同 epoch 内同一卡只“标记”一次）
        # Step23：将“直接映射表”升级为“set-associative 小表”，降低 index 冲突导致的重复处理。
        #
        # 去重维度： (card_id, epoch)
        # - 同 epoch 命中：视为重复，dup_drop++
        # - epoch 不同：视为新一轮 GC（允许再次计入 mark_count）
        #
        # 表结构：
        #   - sets = card_table_size（要求 2 的幂，便于低位取索引）
        #   - ways = card_table_ways（>=1；ways>1 时用每 set 的 rr 指针做替换）
        #   - 每个槽记录：valid, card_id, epoch
        card_id_in = card_q.r_data[0:32]
        core_id_in = card_q.r_data[32:32 + core_id_w]
        epoch_in   = card_q.r_data[32 + core_id_w:32 + core_id_w + 1]

        sets = self.card_table_size
        ways = self.card_table_ways
        if sets & (sets - 1) != 0:
            raise ValueError("card_table_size must be power of two")
        idx_w = (sets - 1).bit_length()
        tab_idx = Signal(idx_w)
        # 索引模式：
        #   0: 直接使用 card_id 的低 idx_w 位（快速，但容易低位冲突）
        #   1: xor-fold：把 card_id 的每个 idx_w-bit chunk 做 XOR 折叠后取索引（降低冲突，研究用）
        idx_low = card_id_in[0:idx_w]
        idx_xor = Signal(idx_w)
        idx_expr = idx_low
        for k in range(1, (32 + idx_w - 1)//idx_w):
            hi = k * idx_w
            if hi >= 32:
                break
            width = min(idx_w, 32 - hi)
            chunk_expr = Cat(card_id_in[hi:hi+width], Const(0, idx_w - width))
            idx_expr = idx_expr ^ chunk_expr
        m.d.comb += idx_xor.eq(idx_expr)
        if self.card_index_mode == 1:
            m.d.comb += tab_idx.eq(idx_xor)
        else:
            m.d.comb += tab_idx.eq(idx_low)

        way_w = max(1, (ways - 1).bit_length())

        # 表项（用 python list-of-lists，便于在生成的 If 中写入）
        tab_valid = [[Signal(name=f"mark_tab_v{s}_{w}") for w in range(ways)] for s in range(sets)]
        tab_card  = [[Signal(32, name=f"mark_tab_card{s}_{w}") for w in range(ways)] for s in range(sets)]
        tab_epoch = [[Signal(1,  name=f"mark_tab_ep{s}_{w}") for w in range(ways)] for s in range(sets)]
        repl_ptr  = [Signal(way_w, name=f"mark_tab_rp{s}") for s in range(sets)]

        hit = Signal()
        hit_way = Signal(way_w)
        ins_way = Signal(way_w)
        empty_found = Signal()
        empty_way = Signal(way_w)

        # 默认值
        m.d.comb += [
            hit.eq(0),
            hit_way.eq(0),
            empty_found.eq(0),
            empty_way.eq(0),
            ins_way.eq(0),
        ]

        # 选择：命中 way / 可用 way / 插入 way（按 set 计算，避免动态索引写入问题）
        for s_i in range(sets):
            with m.If(tab_idx == s_i):
                # --- hit search
                found = Const(0)
                chosen = Const(0, way_w)
                for w_i in range(ways):
                    cond = (self.card_dedup_enable &
                            tab_valid[s_i][w_i] &
                            (tab_card[s_i][w_i] == card_id_in) &
                            (tab_epoch[s_i][w_i] == epoch_in))
                    chosen = Mux((~found) & cond, Const(w_i, way_w), chosen)
                    found = found | cond

                # --- empty search（空槽或旧 epoch 槽可覆盖）
                ef = Const(0)
                ew = Const(0, way_w)
                for w_i in range(ways):
                    cond = (~tab_valid[s_i][w_i]) | (tab_epoch[s_i][w_i] != epoch_in)
                    ew = Mux((~ef) & cond, Const(w_i, way_w), ew)
                    ef = ef | cond

                m.d.comb += [
                    hit.eq(found),
                    hit_way.eq(chosen),
                    empty_found.eq(ef),
                    empty_way.eq(ew),
                    ins_way.eq(Mux(ef, ew, repl_ptr[s_i]) if ways > 1 else Const(0, way_w)),
                ]

        with m.If(do_mark):
            # 最近消费的一条 card 记录（无论是否命中去重，都记录，便于调试）
            m.d.sync += [
                self.last_card_id.eq(card_id_in),
                self.last_core_id.eq(core_id_in),
                self.last_epoch.eq(epoch_in),
            ]

            with m.If(hit):
                # 重复 card：不增加 mark_count，只统计 dup_drop
                m.d.sync += [
                    self.mark_dup_drop_total.eq(self.mark_dup_drop_total + 1),
                    self.mark_hit_total.eq(self.mark_hit_total + 1),
                ]
            with m.Else():
                # 新 card（或新 epoch）：写表并计入 mark_count
                m.d.sync += [
                    self.mark_count_total.eq(self.mark_count_total + 1),
                    self.mark_miss_total.eq(self.mark_miss_total + 1),
                    # miss 且没有可用槽（empty_found=0）时，说明发生了替换
                    self.mark_replace_total.eq(self.mark_replace_total + Mux(empty_found, 0, 1)),
                ]

                # 按核计数：显式 if，避免动态索引在某些后端不友好
                for i in range(self.ncores):
                    with m.If(core_id_in == i):
                        m.d.sync += self.mark_count_core[i].eq(self.mark_count_core[i] + 1)

                # 写入表项：需要对 set/way 做显式选择（左值不可动态索引）
                for s_i in range(sets):
                    with m.If(tab_idx == s_i):
                        for w_i in range(ways):
                            with m.If(ins_way == w_i):
                                m.d.sync += [
                                    tab_valid[s_i][w_i].eq(1),
                                    tab_card[s_i][w_i].eq(card_id_in),
                                    tab_epoch[s_i][w_i].eq(epoch_in),
                                ]
                        # rr 替换指针更新（ways==1 时无意义，但写了也不会出错）
                        m.d.sync += repl_ptr[s_i].eq((ins_way + 1) if ways > 1 else 0)

        N = self.entries

        # ---- Tables
        rc   = Memory(width=16, depth=N, init=[0] * N)
        pin  = Memory(width=1,  depth=N, init=[0] * N)
        used = Memory(width=1,  depth=N, init=[0] * N)

        m.submodules.rc_r   = rc_r   = rc.read_port(domain="comb")
        m.submodules.rc_w   = rc_w   = rc.write_port()
        m.submodules.pin_r  = pin_r  = pin.read_port(domain="comb")
        m.submodules.pin_w  = pin_w  = pin.write_port()
        m.submodules.used_r = used_r = used.read_port(domain="comb")
        m.submodules.used_w = used_w = used.write_port()

        alloc_ptr = Signal(range(N), reset=1)
        rr_ptr    = Signal(range(self.ncores), reset=0)

        # ---- FIFOs (Array)
        fifos_list = []
        for i in range(self.ncores):
            fifo = SyncFIFO(width=self.tag_w + 3 + 5 + 32 + 32, depth=self.fifo_depth)
            fifos_list.append(fifo)
            m.submodules[f"cmd_fifo{i}"] = fifo

            m.d.comb += [
                fifo.w_data.eq(Cat(self.cmd_tag[i], self.cmd_op[i], self.cmd_rd[i], self.cmd_rs1[i], self.cmd_rs2[i])),
                fifo.w_en.eq(self.cmd_enq_valid[i] & fifo.w_rdy),
                self.cmd_enq_ready[i].eq(fifo.w_rdy),
            ]
        fifos = Array(fifos_list)

        # ---- response clear on take
        for i in range(self.ncores):
            with m.If(self.rsp_take[i]):
                m.d.sync += self.rsp_valid[i].eq(0)

        # ---- write port defaults
        m.d.comb += [
            rc_w.en.eq(0),
            pin_w.en.eq(0),
            used_w.en.eq(0),
        ]

        # ---- trap pulse (single engine => at most one core per cycle)
        trap_fire = Signal(reset=0)
        trap_core = Signal(range(self.ncores), reset=0)

        # Step20：epoch tick pulse（用于 scan 的 epoch_advance）
        epoch_fire = Signal(reset=0)
        epoch_core = Signal(range(self.ncores), reset=0)

        # Step47：mv forwarding-table update pulse（RELOC commit sideband）
        mv_fire = Signal(reset=0)
        mv_core = Signal(range(self.ncores), reset=0)
        mv_old  = Signal(32, reset=0)
        mv_new  = Signal(32, reset=0)

        # clear every cycle
        m.d.sync += [
            trap_fire.eq(0),
            epoch_fire.eq(0),
            mv_fire.eq(0),
        ]

        # comb decode to per-core trap outputs (ONLY comb drive of self.trap)
        for i in range(self.ncores):
            m.d.comb += self.trap[i].eq(trap_fire & (trap_core == i))

        # comb decode to per-core epoch outputs
        for i in range(self.ncores):
            m.d.comb += self.epoch_tick[i].eq(epoch_fire & (epoch_core == i))

        # comb decode to per-core mv update outputs
        # Step59: mv forwarding-table update decoupled interface (per-core hold regs).
        mv_out_valid = Array(Signal(reset=0, name=f"mvupd{i}_hold_v") for i in range(self.ncores))
        mv_out_old   = Array(Signal(32, reset=0, name=f"mvupd{i}_hold_old") for i in range(self.ncores))
        mv_out_new   = Array(Signal(32, reset=0, name=f"mvupd{i}_hold_new") for i in range(self.ncores))

        for i in range(self.ncores):
            m.d.comb += [
                self.mv_upd_valid[i].eq(mv_out_valid[i]),
                self.mv_upd_old[i].eq(mv_out_old[i]),
                self.mv_upd_new[i].eq(mv_out_new[i]),
            ]
            with m.If(mv_out_valid[i] & self.mv_upd_ready[i]):
                m.d.sync += mv_out_valid[i].eq(0)


        # ---- Select FIFO round-robin (no comb cycles)
        sel  = Signal(range(self.ncores))
        have = Signal()

        sel_v  = rr_ptr
        have_v = Const(0)

        for k in range(self.ncores):
            idx = rr_ptr + k
            idx = Mux(idx >= self.ncores, idx - self.ncores, idx)
            req = fifos[idx].r_rdy
            sel_v  = Mux((~have_v) & req, idx, sel_v)
            have_v = have_v | req

        m.d.comb += [
            sel.eq(sel_v),
            have.eq(have_v),
        ]

        # Can accept if selected core response slot empty
        can_accept = Signal()
        m.d.comb += can_accept.eq(have & (~self.rsp_valid[sel]))

        # ---- Unpack selected command
        tag = Signal(self.tag_w)
        op  = Signal(3)
        rd  = Signal(5)
        rs1 = Signal(32)
        rs2 = Signal(32)
        m.d.comb += [
            tag.eq(fifos[sel].r_data[0:self.tag_w]),
            op.eq(fifos[sel].r_data[self.tag_w:self.tag_w+3]),
            rd.eq(fifos[sel].r_data[self.tag_w+3:self.tag_w+3+5]),
            rs1.eq(fifos[sel].r_data[self.tag_w+8:self.tag_w+8+32]),
            rs2.eq(fifos[sel].r_data[self.tag_w+40:self.tag_w+40+32]),
        ]

        idx1 = Signal(8)
        idx2 = Signal(8)
        m.d.comb += [idx1.eq(rs1[0:8]), idx2.eq(rs2[0:8])]

        # read old state at idx1
        m.d.comb += [
            rc_r.addr.eq(idx1),
            pin_r.addr.eq(idx1),
            used_r.addr.eq(idx1),
        ]

        # GC_NEW: used[alloc_ptr]
        used_ap_r = used.read_port(domain="comb")
        m.submodules.used_ap_r = used_ap_r
        m.d.comb += used_ap_r.addr.eq(alloc_ptr)

        # GC_RELOC: used[idx2]
        used2_r = used.read_port(domain="comb")
        m.submodules.used2_r = used2_r
        m.d.comb += used2_r.addr.eq(idx2)

        # ---- RELOC two-step (single write port)
        reloc_pending = Signal(reset=0)
        reloc_src     = Signal(8, reset=0)

        # step2: free src
        with m.If(reloc_pending):
            m.d.comb += [
                used_w.en.eq(1), used_w.addr.eq(reloc_src), used_w.data.eq(0),
                rc_w.en.eq(1),   rc_w.addr.eq(reloc_src),   rc_w.data.eq(0),
                pin_w.en.eq(1),  pin_w.addr.eq(reloc_src),  pin_w.data.eq(0),
            ]
            m.d.sync += reloc_pending.eq(0)

        # ---- Execute 1 cmd per cycle when available and not busy with reloc_pending
        # Step12：增加可选 engine_latency，用来在测试中制造‘GC 响应变慢’，
        # 从而验证 CPU 不应该被 gc_waiting 全局卡死（应允许无关指令继续前进）。
        if self.engine_latency == 0:
            with m.If(can_accept & ~reloc_pending & ~((op == GC_RELOC) & mv_out_valid[sel])):
                m.d.comb += fifos[sel].r_en.eq(1)
                m.d.sync += rr_ptr.eq(sel + 1)

                # default response
                m.d.sync += [
                    self.rsp_valid[sel].eq(1),
                    self.rsp_tag[sel].eq(tag),
                    self.rsp_rd[sel].eq(rd),
                    self.rsp_data[sel].eq(0),
                ]

                def raise_trap():
                    m.d.sync += [
                        trap_fire.eq(1),
                        trap_core.eq(sel),
                    ]

                with m.Switch(op):
                    with m.Case(GC_NEW):
                        with m.If(used_ap_r.data == 0):
                            m.d.comb += [
                                used_w.en.eq(1), used_w.addr.eq(alloc_ptr), used_w.data.eq(1),
                                rc_w.en.eq(1),   rc_w.addr.eq(alloc_ptr),   rc_w.data.eq(1),
                                pin_w.en.eq(1),  pin_w.addr.eq(alloc_ptr),  pin_w.data.eq(0),
                            ]
                            m.d.sync += [
                                self.rsp_data[sel].eq(alloc_ptr),
                                alloc_ptr.eq(Mux(alloc_ptr == (N - 1), 1, alloc_ptr + 1))
                            ]
                        with m.Else():
                            raise_trap()

                    with m.Case(GC_CLONE):
                        with m.If(used_r.data):
                            with m.If(rc_r.data == 0xFFFF):
                                raise_trap()
                            with m.Else():
                                m.d.comb += [
                                    rc_w.en.eq(1), rc_w.addr.eq(idx1), rc_w.data.eq(rc_r.data + 1),
                                ]
                                m.d.sync += self.rsp_data[sel].eq(rs1)
                        with m.Else():
                            raise_trap()

                    with m.Case(GC_DROP):
                        # Model semantics:
                        #   - if unused => trap
                        #   - if pinned => trap
                        #   - if rc==0  => trap
                        #   - else rc-- ; if rc becomes 0 then free (used=0)
                        with m.If(used_r.data):
                            with m.If(pin_r.data):
                                raise_trap()
                            with m.Elif(rc_r.data == 0):
                                raise_trap()
                            with m.Else():
                                newrc = Signal(16)
                                m.d.comb += newrc.eq(rc_r.data - 1)
                                m.d.comb += [
                                    rc_w.en.eq(1), rc_w.addr.eq(idx1), rc_w.data.eq(newrc),
                                ]
                                with m.If(newrc == 0):
                                    m.d.comb += [
                                        used_w.en.eq(1), used_w.addr.eq(idx1), used_w.data.eq(0),
                                    ]
                        with m.Else():
                            raise_trap()

                    with m.Case(GC_PIN):
                        with m.If(used_r.data):
                            m.d.comb += [
                                pin_w.en.eq(1), pin_w.addr.eq(idx1), pin_w.data.eq(1),
                            ]
                        with m.Else():
                            raise_trap()

                    with m.Case(GC_UNPIN):
                        with m.If(used_r.data):
                            m.d.comb += [
                                pin_w.en.eq(1), pin_w.addr.eq(idx1), pin_w.data.eq(0),
                            ]
                            with m.If(rc_r.data == 0):
                                m.d.comb += [
                                    used_w.en.eq(1), used_w.addr.eq(idx1), used_w.data.eq(0),
                                ]
                        with m.Else():
                            raise_trap()

                    with m.Case(GC_RELOC):
                        with m.If(used_r.data & (pin_r.data == 0) & (used2_r.data == 0)):
                            # step1: write dst
                            m.d.comb += [
                                used_w.en.eq(1), used_w.addr.eq(idx2), used_w.data.eq(1),
                                rc_w.en.eq(1),   rc_w.addr.eq(idx2),   rc_w.data.eq(rc_r.data),
                                pin_w.en.eq(1),  pin_w.addr.eq(idx2),  pin_w.data.eq(pin_r.data),
                            ]
                            # schedule step2: free src next cycle
                            m.d.sync += [
                                reloc_pending.eq(1),
                                reloc_src.eq(idx1),
                            ]

                            # Step59：写入 mv_upd hold reg（valid/ready 语义，后续由 mv_upd_ready 释放）
                            m.d.sync += [
                                mv_out_valid[sel].eq(1),
                                mv_out_old[sel].eq(rs1),
                                mv_out_new[sel].eq(rs2),
                            ]
                        with m.Else():
                            raise_trap()

                    # Step20：GC_EPOCH
                    # 语义：不改 GC 表，仅产生一次 epoch_tick 脉冲。
                    with m.Case(GC_EPOCH):
                        m.d.sync += [
                            epoch_fire.eq(1),
                            epoch_core.eq(sel),
                        ]

                    with m.Default():
                        raise_trap()

            with m.Elif(have & self.rsp_valid[sel]):
                m.d.sync += rr_ptr.eq(sel + 1)

        else:
            # 延迟模式：引擎全局 busy，先执行 side-effect（表更新），把返回值缓存起来，
            # 等 busy_cnt 倒数到 0 再把 rsp_valid 拉高。
            busy_cnt   = Signal(range(self.engine_latency + 1), reset=0)
            pend_valid = Signal(reset=0)
            pend_core  = Signal(range(self.ncores), reset=0)
            pend_tag   = Signal(self.tag_w, reset=0)
            pend_rd    = Signal(5, reset=0)
            pend_data  = Signal(32, reset=0)
            pend_epoch = Signal(reset=0)

            # busy 倒计时
            with m.If(busy_cnt != 0):
                m.d.sync += busy_cnt.eq(busy_cnt - 1)

            # 到点后把缓存响应发出去（如果对应 core 的 rsp slot 还空）
            with m.If(pend_valid & (busy_cnt == 0) & (~self.rsp_valid[pend_core])):
                m.d.sync += [
                    self.rsp_valid[pend_core].eq(1),
                    self.rsp_tag[pend_core].eq(pend_tag),
                    self.rsp_rd[pend_core].eq(pend_rd),
                    self.rsp_data[pend_core].eq(pend_data),
                    pend_valid.eq(0),
                ]
                with m.If(pend_epoch):
                    m.d.sync += [
                        epoch_fire.eq(1),
                        epoch_core.eq(pend_core),
                        pend_epoch.eq(0),
                    ]

            can_accept_lat = Signal()
            m.d.comb += can_accept_lat.eq(can_accept & ~reloc_pending & (~pend_valid) & (busy_cnt == 0) & ~((op == GC_RELOC) & mv_out_valid[sel]))

            with m.If(can_accept_lat):
                m.d.comb += fifos[sel].r_en.eq(1)
                m.d.sync += rr_ptr.eq(sel + 1)

                # 缓存默认响应（data 默认 0）
                m.d.sync += [
                    pend_valid.eq(1),
                    pend_core.eq(sel),
                    pend_tag.eq(tag),
                    pend_rd.eq(rd),
                    pend_data.eq(0),
                    busy_cnt.eq(self.engine_latency),
                    pend_epoch.eq(op == GC_EPOCH),
                ]

                def raise_trap():
                    m.d.sync += [
                        trap_fire.eq(1),
                        trap_core.eq(sel),
                    ]

                with m.Switch(op):
                    with m.Case(GC_NEW):
                        with m.If(used_ap_r.data == 0):
                            m.d.comb += [
                                used_w.en.eq(1), used_w.addr.eq(alloc_ptr), used_w.data.eq(1),
                                rc_w.en.eq(1),   rc_w.addr.eq(alloc_ptr),   rc_w.data.eq(1),
                                pin_w.en.eq(1),  pin_w.addr.eq(alloc_ptr),  pin_w.data.eq(0),
                            ]
                            m.d.sync += [
                                pend_data.eq(alloc_ptr),
                                alloc_ptr.eq(Mux(alloc_ptr == (N - 1), 1, alloc_ptr + 1))
                            ]
                        with m.Else():
                            raise_trap()

                    with m.Case(GC_CLONE):
                        with m.If(used_r.data):
                            with m.If(rc_r.data == 0xFFFF):
                                raise_trap()
                            with m.Else():
                                m.d.comb += [
                                    rc_w.en.eq(1), rc_w.addr.eq(idx1), rc_w.data.eq(rc_r.data + 1),
                                ]
                                m.d.sync += pend_data.eq(rs1)
                        with m.Else():
                            raise_trap()

                    with m.Case(GC_DROP):
                        with m.If(used_r.data):
                            with m.If(pin_r.data):
                                raise_trap()
                            with m.Elif(rc_r.data == 0):
                                raise_trap()
                            with m.Else():
                                newrc = Signal(16)
                                m.d.comb += newrc.eq(rc_r.data - 1)
                                m.d.comb += [
                                    rc_w.en.eq(1), rc_w.addr.eq(idx1), rc_w.data.eq(newrc),
                                ]
                                with m.If(newrc == 0):
                                    m.d.comb += [
                                        used_w.en.eq(1), used_w.addr.eq(idx1), used_w.data.eq(0),
                                    ]
                        with m.Else():
                            raise_trap()

                    with m.Case(GC_PIN):
                        with m.If(used_r.data):
                            m.d.comb += [
                                pin_w.en.eq(1), pin_w.addr.eq(idx1), pin_w.data.eq(1),
                            ]
                        with m.Else():
                            raise_trap()

                    with m.Case(GC_UNPIN):
                        with m.If(used_r.data):
                            m.d.comb += [
                                pin_w.en.eq(1), pin_w.addr.eq(idx1), pin_w.data.eq(0),
                            ]
                            with m.If(rc_r.data == 0):
                                m.d.comb += [
                                    used_w.en.eq(1), used_w.addr.eq(idx1), used_w.data.eq(0),
                                ]
                        with m.Else():
                            raise_trap()

                    with m.Case(GC_RELOC):
                        with m.If(used_r.data & (pin_r.data == 0) & (used2_r.data == 0)):
                            # step1: write dst
                            m.d.comb += [
                                used_w.en.eq(1), used_w.addr.eq(idx2), used_w.data.eq(1),
                                rc_w.en.eq(1),   rc_w.addr.eq(idx2),   rc_w.data.eq(rc_r.data),
                                pin_w.en.eq(1),  pin_w.addr.eq(idx2),  pin_w.data.eq(pin_r.data),
                            ]
                            # schedule step2: free src next cycle
                            m.d.sync += [
                                reloc_pending.eq(1),
                                reloc_src.eq(idx1),
                            ]

                            # Step59：写入 mv_upd hold reg（valid/ready 语义，后续由 mv_upd_ready 释放）
                            m.d.sync += [
                                mv_out_valid[sel].eq(1),
                                mv_out_old[sel].eq(rs1),
                                mv_out_new[sel].eq(rs2),
                            ]
                        with m.Else():
                            raise_trap()

                    # Step20：GC_EPOCH
                    # 延迟模式下：不做表更新，真正的 epoch_tick 在响应发出那拍通过 pend_epoch 触发。
                    with m.Case(GC_EPOCH):
                        pass

                    with m.Default():
                        raise_trap()

            with m.Elif(have & self.rsp_valid[sel]):
                m.d.sync += rr_ptr.eq(sel + 1)

        return m
