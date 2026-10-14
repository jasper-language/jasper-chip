# rtl/gc_scan_coproc.py
#
# GCScanCoProc（扫描/写屏障事件协处理器）
# ---------------------------------
# 作为“写屏障事件收集器”，接收每核的 store 事件。
# Step17：事件格式升级为：card_id + obj_id
#   - card_id：addr >> card_shift（模拟 card table 粒度）
#   - obj_id ：addr >> obj_shift（研究阶段用 shift 近似对象粒度）
# 仍然用两个 32bit 信号承载（保持接口骨架稳定）：
#   wb_addr=card_id, wb_data=obj_id
#
# Step16 更新（关键）：
#   - 将“每核独立消费”改为“共享扫描引擎”模型：
#       * 每核仍有一个输入 FIFO（写屏障事件入口）
#       * 但只有一个共享的 consumer（扫描引擎）按带宽 consume_every 消费事件
#       * consumer 使用轮询仲裁（round-robin）从有数据的核上取 1 条
#   - 目的：
#       * 更贴近真实多核系统：扫描资源往往是共享的
#       * 背压与公平性更真实：某些核可能因为 scan 带宽不足而更早被卡住
#
# 仍保留（研究/测试可观测性）：
#   - ev_count / last_addr / last_data：统计“被 scan 引擎消费”的事件数量与最后一条事件
#
# consume_every:
#   - 1   : 每个 cycle 尽可能消费 1 条（最大带宽）
#   - N>1 : 每 N 个 cycle 至多消费 1 条（更慢，制造背压）
#   - 0   : 不消费（极端背压源）
#
from amaranth import *
from amaranth.lib.fifo import SyncFIFOBuffered


class GCScanCoProc(Elaboratable):
    def __init__(
        self,
        ncores=4,
        fifo_depth=16,
        consume_every=1,
        batch_size=1,
        # Step18：card 去重（remembered-set/card table 最核心的优化之一）
        # - 同一个 card 被反复写入时，不需要为每次写入都入队；
        # - 只需要把该 card 标记为“脏”，scan 引擎处理一次即可。
        #
        # 这里采用一个“很小但可研究”的实现：
        # - 每核维护一个小的 card 集合（cardset_size 项），记录当前已入队/待处理的 card_id
        # - 若写屏障事件的 card_id 已存在，则直接丢弃（视为去重成功，不占用 FIFO）
        # - 若不存在且集合已满，则 backpressure（wb_ready=0）直到有 card 被消费并释放
        dedup_enable=True,
        cardset_size=16,
        # Step20：scan 输出 remembered-set（card stream）队列深度
        out_depth=32,
    ):
        self.ncores = int(ncores)
        self.fifo_depth = int(fifo_depth)
        self.consume_every = int(consume_every)
        # Step17：批处理/突发消费大小（模拟一次扫描一个 card 可能会处理多个事件）
        # - batch_size=1：保持 Step16 行为（每次节拍最多消费 1 条）
        # - batch_size>1：当节拍到来时，会进入“突发期”，在接下来的若干个 cycle 连续消费 batch_size 条
        # credit 目前用 8bit，避免 batch_size 过大导致溢出
        self.batch_size = min(255, max(1, int(batch_size)))

        self.dedup_enable = bool(dedup_enable)
        self.cardset_size = max(1, int(cardset_size))
        self.out_depth = max(1, int(out_depth))
        # 全局 epoch 广播 (from GCCycleController)
        self.epoch = Signal(8)
        self.epoch_advance = Signal()

        # 每核写屏障事件输入（valid/ready）
        self.wb_valid = Array(Signal(name=f"wb{i}_valid") for i in range(self.ncores))
        self.wb_ready = Array(Signal(name=f"wb{i}_ready") for i in range(self.ncores))
        self.wb_addr  = Array(Signal(32, name=f"wb{i}_addr")  for i in range(self.ncores))
        self.wb_data  = Array(Signal(32, name=f"wb{i}_data")  for i in range(self.ncores))

        # 可观测统计：消费计数 + 最近消费的一条事件
        self.ev_count  = Array(Signal(32, name=f"scan{i}_evcnt") for i in range(self.ncores))
        self.last_addr = Array(Signal(32, name=f"scan{i}_last_addr") for i in range(self.ncores))
        self.last_data = Array(Signal(32, name=f"scan{i}_last_data") for i in range(self.ncores))

        # Step18：去重相关可观测统计（研究/测试用）
        # - in_count：写屏障输入被“接受”的次数（valid&ready）
        # - uniq_enq：真正入队的“唯一 card”次数
        # - dup_drop：因为 card 已在集合中而被去重丢弃的次数
        self.in_count  = Array(Signal(32, name=f"scan{i}_in")   for i in range(self.ncores))
        self.uniq_enq  = Array(Signal(32, name=f"scan{i}_uniq") for i in range(self.ncores))
        self.dup_drop  = Array(Signal(32, name=f"scan{i}_dup")  for i in range(self.ncores))

        # Step19：GC epoch / dirty generation（研究用）
        # - 真实 GC 往往按“epoch/轮次”管理 dirty card：一轮 GC 结束后进入新 epoch，允许同一卡在新轮次再次入队。
        # - 这里用 1bit epoch 做最小模型：epoch_advance=1 时翻转 epoch。
        # - 去重集合里的条目带 epoch 标记：只有 epoch 匹配才视为“已入队”，否则视为可覆盖的 stale 条目。
        self.epoch_advance = Signal(name="scan_epoch_advance")
        self.epoch = Signal(1, reset=0, name="scan_epoch")

        # Step20：scan 输出队列（remembered-set card stream）
        # - consumer 每消费一条写屏障事件，会产出一条记录：(core_id, card_id, epoch)
        # - out_ready 默认 reset=1，若 SoC 未显式连接，也不会把系统卡住
        core_id_w = max(1, (self.ncores - 1).bit_length())
        self.out_valid = Signal(name="scan_out_valid")
        self.out_ready = Signal(reset=1, name="scan_out_ready")
        self.out_card_id = Signal(32, name="scan_out_card")
        self.out_core_id = Signal(core_id_w, name="scan_out_core")
        self.out_epoch   = Signal(1, name="scan_out_epoch")

        # 研究阶段：不触发 trap
        self.trap = Array(Signal(name=f"scantrap{i}") for i in range(self.ncores))

    def elaborate(self, platform):
        m = Module()

        # Step19：epoch 翻转（1bit generation）
        # - 测试/研究时可以在仿真里拉高 epoch_advance 1 拍来切换 epoch。
        # - 不需要清空集合：旧 epoch 的条目会被当作 stale（可覆盖/不命中）。
        with m.If(self.epoch_advance):
            m.d.sync += self.epoch.eq(~self.epoch)

        fifos = []
        card_valid_sets = []
        card_id_sets = []
        card_epoch_sets = []
        for i in range(self.ncores):
            fifo = SyncFIFOBuffered(width=65, depth=self.fifo_depth)
            m.submodules[f"scan_fifo{i}"] = fifo
            fifos.append(fifo)

            m.d.comb += [
                fifo.w_data.eq(Cat(self.wb_addr[i], self.wb_data[i], self.epoch)),
                self.trap[i].eq(0),
            ]

            in_card = self.wb_addr[i]

            if self.dedup_enable:
                card_valid = Array(Signal(name=f"cset{i}_v{j}") for j in range(self.cardset_size))
                card_id    = Array(Signal(32, name=f"cset{i}_c{j}") for j in range(self.cardset_size))
                card_epoch = Array(Signal(1,  name=f"cset{i}_e{j}") for j in range(self.cardset_size))

                hit = Signal(name=f"cset{i}_hit")
                free_found = Signal(name=f"cset{i}_free_found")
                free_idx = Signal(range(self.cardset_size), name=f"cset{i}_free_idx")

                hit_v = Const(0)
                free_found_v = Const(0)
                free_idx_v = Const(0)
                for j in range(self.cardset_size):
                    is_hit = card_valid[j] & (card_epoch[j] == self.epoch) & (card_id[j] == in_card)
                    hit_v = hit_v | is_hit
                    is_free = (~card_valid[j]) | (card_epoch[j] != self.epoch)
                    free_idx_v = Mux((~free_found_v) & is_free, j, free_idx_v)
                    free_found_v = free_found_v | is_free

                m.d.comb += [
                    hit.eq(hit_v),
                    free_found.eq(free_found_v),
                    free_idx.eq(free_idx_v),
                ]

                can_push_new = Signal(name=f"cset{i}_can_push")
                m.d.comb += can_push_new.eq(free_found & fifo.w_rdy)

                ready = hit | can_push_new
                w_en  = self.wb_valid[i] & (~hit) & can_push_new

                m.d.comb += [
                    self.wb_ready[i].eq(ready),
                    fifo.w_en.eq(w_en),
                ]

                accept = Signal(name=f"scan{i}_accept")
                m.d.comb += accept.eq(self.wb_valid[i] & self.wb_ready[i])
                with m.If(accept):
                    m.d.sync += self.in_count[i].eq(self.in_count[i] + 1)
                with m.If(accept & hit):
                    m.d.sync += self.dup_drop[i].eq(self.dup_drop[i] + 1)
                with m.If(w_en):
                    m.d.sync += self.uniq_enq[i].eq(self.uniq_enq[i] + 1)

                with m.If(w_en):
                    m.d.sync += [
                        card_valid[free_idx].eq(1),
                        card_id[free_idx].eq(in_card),
                        card_epoch[free_idx].eq(self.epoch),
                    ]

                card_valid_sets.append(card_valid)
                card_id_sets.append(card_id)
                card_epoch_sets.append(card_epoch)
            else:
                ready = fifo.w_rdy
                w_en  = self.wb_valid[i] & fifo.w_rdy

                m.d.comb += [
                    self.wb_ready[i].eq(ready),
                    fifo.w_en.eq(w_en),
                ]

                accept = Signal(name=f"scan{i}_accept")
                m.d.comb += accept.eq(self.wb_valid[i] & self.wb_ready[i])
                with m.If(accept):
                    m.d.sync += self.in_count[i].eq(self.in_count[i] + 1)
                with m.If(w_en):
                    m.d.sync += self.uniq_enq[i].eq(self.uniq_enq[i] + 1)

        fifos = Array(fifos)

        # Step20：card stream 输出队列
        # - 记录格式：Cat(card_id[32], core_id[core_id_w], epoch[1])
        core_id_w = max(1, (self.ncores - 1).bit_length())
        out_fifo_w = 32 + core_id_w + 1
        m.submodules.out_q = out_q = SyncFIFOBuffered(width=out_fifo_w, depth=self.out_depth)

        # 输出端口：默认 out_ready reset=1，会自动 drain，避免 TopSoC 不连接时被“填满卡死”
        m.d.comb += [
            self.out_valid.eq(out_q.r_rdy),
            self.out_card_id.eq(out_q.r_data[0:32]),
            self.out_core_id.eq(out_q.r_data[32:32 + core_id_w]),
            self.out_epoch.eq(out_q.r_data[32 + core_id_w:32 + core_id_w + 1]),
            out_q.r_en.eq(out_q.r_rdy & self.out_ready),
        ]

        # Step61: Clear cardset entry only when a card record leaves the scan chip (out_q pop handshake).
        # Rationale:
        # - With inter-chip backpressure, "consumed into out_q" does NOT mean "delivered".
        # - Also, epoch may advance while a card is waiting; clearing must match the record's epoch bit, not self.epoch.
        pop_fire = Signal()
        pop_card = Signal(32)
        pop_core = Signal(core_id_w)
        pop_epoch = Signal(1)
        m.d.comb += [
            pop_fire.eq(out_q.r_rdy & self.out_ready),
            pop_card.eq(out_q.r_data[0:32]),
            pop_core.eq(out_q.r_data[32:32 + core_id_w]),
            pop_epoch.eq(out_q.r_data[32 + core_id_w:32 + core_id_w + 1]),
        ]

        if self.dedup_enable:
            for i in range(self.ncores):
                with m.If(pop_fire & (pop_core == i)):
                    for j in range(self.cardset_size):
                        with m.If(card_valid_sets[i][j] & (card_epoch_sets[i][j] == pop_epoch) & (card_id_sets[i][j] == pop_card)):
                            m.d.sync += card_valid_sets[i][j].eq(0)

        # 注意：dedup_enable==False 时，card_*_sets 虽然存在但不会被使用。

        # ----------------------
        # 共享扫描引擎：带宽控制 + RR 选择一个核消费 1 条
        # Step17：加入“突发期 credit”，支持批处理扫描模型。
        # ----------------------
        rr_ptr = Signal(range(self.ncores), reset=0)

        # 带宽节拍器：consume_every==1 时每拍允许消费
        # consume_every==0 时永不允许消费
        tick = Signal()
        if self.consume_every <= 0:
            m.d.comb += tick.eq(0)
        elif self.consume_every == 1:
            m.d.comb += tick.eq(1)
        else:
            ctr = Signal(range(self.consume_every), reset=0)
            m.d.comb += tick.eq(ctr == (self.consume_every - 1))
            with m.If(ctr == (self.consume_every - 1)):
                m.d.sync += ctr.eq(0)
            with m.Else():
                m.d.sync += ctr.eq(ctr + 1)

        # 找到一个有数据的 fifo（从 rr_ptr 开始轮询）
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

        m.d.comb += [sel.eq(sel_v), have.eq(have_v)]

        # Step17：突发消费 credit。
        # - tick 到来时如果 credit==0，则装载 credit=batch_size
        # - credit>0 时，每个 cycle 尽可能消费 1 条（直到 credit 用尽）
        credit = Signal(8, reset=0)

        # 默认不读
        for i in range(self.ncores):
            m.d.comb += fifos[i].r_en.eq(0)

        # Step20：out_q 默认不写
        m.d.comb += out_q.w_en.eq(0)

        # 装载突发期
        with m.If((credit == 0) & tick):
            m.d.sync += credit.eq(self.batch_size)

        do_consume = Signal()
        # Step20：consumer 只有在 out_q 有空间时才真正消费（否则会丢 card stream）
        m.d.comb += do_consume.eq((credit != 0) & have & out_q.w_rdy)

        # 若突发期内没有任何数据可读，则直接结束突发期（避免 credit 空转）
        with m.If((credit != 0) & ~have):
            m.d.sync += credit.eq(0)

        # 当允许消费时，从 sel 对应 fifo 取 1 条
        with m.If(do_consume):
            m.d.comb += fifos[sel].r_en.eq(1)
            consume_card = Signal(32)
            consume_obj  = Signal(32)
            consume_epoch = Signal(1)
            m.d.comb += [
                consume_card.eq(fifos[sel].r_data[0:32]),
                consume_obj.eq(fifos[sel].r_data[32:64]),
                consume_epoch.eq(fifos[sel].r_data[64:65]),
            ]

            # Step20：把消费到的 card 输出到 out_q，供 sweep/标记阶段使用
            # 记录：Cat(card_id, core_id, epoch)
            m.d.comb += [
                out_q.w_en.eq(1),
                out_q.w_data.eq(Cat(consume_card, (Const(0, core_id_w) if self.ncores == 1 else sel), consume_epoch)),
            ]

            # 通用更新：rr 指针、credit、统计
            m.d.sync += [
                rr_ptr.eq(sel + 1),
                credit.eq(credit - 1),
                # 统计：只要 r_en=1 就认为消费 1 条
                self.ev_count[sel].eq(self.ev_count[sel] + 1),
                self.last_addr[sel].eq(consume_card),
                self.last_data[sel].eq(consume_obj),
            ]

        return m
