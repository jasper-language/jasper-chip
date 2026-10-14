# rtl/top_soc.py
from amaranth import *
from .mem import SimpleIMem, SimpleDMem, RRArbiter
from .rv12_core import RV12Core
from .gc_scan_coproc import GCScanCoProc
from .gc_sweep_coproc import GCSweepCoProc
from .gc_mv_coproc import GCMvCoProc
from .gc_params import (
    DEFAULT_SWEEP_CARD_TABLE_SIZE,
    DEFAULT_SWEEP_CARD_TABLE_WAYS,
    DEFAULT_SWEEP_CARD_INDEX_MODE,
)

# Step33：scan 默认参数固化（研究用）。
# 说明：scan 参数属于“吞吐/背压”的工程权衡，不影响 ISA 正确性。
# 为了避免每轮手调造成指标漂移，我们把推荐默认值写入 rtl/gc_scan_params.py。
try:
    from .gc_scan_params import (
        SCAN_CARDSET_SIZE as DEFAULT_SCAN_CARDSET_SIZE,
        SCAN_FIFO_DEPTH as DEFAULT_SCAN_FIFO_DEPTH,
        SCAN_CONSUME_EVERY as DEFAULT_SCAN_CONSUME_EVERY,
        SCAN_BATCH_SIZE as DEFAULT_SCAN_BATCH_SIZE,
    )
except Exception:
    DEFAULT_SCAN_CARDSET_SIZE = 16
    DEFAULT_SCAN_FIFO_DEPTH = 16
    DEFAULT_SCAN_CONSUME_EVERY = 1
    DEFAULT_SCAN_BATCH_SIZE = 1

class TopSoC(Elaboratable):
    @classmethod
    def with_profile(cls, profile: str, **kwargs):
        """Create a TopSoC instance using a named GC parameter profile.

        Notes:
          - This is a research convenience API; it does not change the default constructor behavior.
          - Any explicit **kwargs override profile values.
        """
        from .gc_profile_params import get_profile
        p = get_profile(profile)
        scan = p["scan"]
        sweep = p["sweep"]
        kwargs.setdefault("scan_fifo_depth", int(scan["fifo_depth"]))
        kwargs.setdefault("scan_consume_every", int(scan["consume_every"]))
        kwargs.setdefault("scan_batch_size", int(scan["batch_size"]))
        kwargs.setdefault("scan_cardset_size", int(scan["cardset_size"]))
        kwargs.setdefault("sweep_card_table_size", int(sweep["sets"]))
        kwargs.setdefault("sweep_card_table_ways", int(sweep["ways"]))
        kwargs.setdefault("sweep_card_index_mode", int(sweep["index_mode"]))
        return cls(**kwargs)

    def __init__(
        self,
        ncores=4,
        imem_words=1024,
        dmem_words=4096,
        imem_inits=None,
        dmem_init=None,
        # Step14：scan 协处理器可控带宽（用于背压/吞吐研究）
        scan_fifo_depth=DEFAULT_SCAN_FIFO_DEPTH,
        scan_consume_every=DEFAULT_SCAN_CONSUME_EVERY,
        # Step17：scan 引擎批处理大小（突发消费）
        scan_batch_size=DEFAULT_SCAN_BATCH_SIZE,
        # Step18：scan 侧 card 去重（remembered set/card table）
        scan_dedup_enable=True,
        scan_cardset_size=DEFAULT_SCAN_CARDSET_SIZE,
        # Step22：sweep 侧 card 去重（同 epoch 内不重复处理同一卡）
        sweep_card_dedup_enable=True,
        sweep_card_table_size=DEFAULT_SWEEP_CARD_TABLE_SIZE,
        sweep_card_table_ways=DEFAULT_SWEEP_CARD_TABLE_WAYS,
        sweep_card_index_mode=DEFAULT_SWEEP_CARD_INDEX_MODE,

        # Step16：写屏障指针过滤（0=不过滤，1=仅记录看起来像指针的写入）
        wb_ptr_filter=0,
        # Step17：写屏障事件格式（card_id / obj_id）的粒度参数
        wb_card_shift=6,
        wb_obj_shift=4,
        # Step73：读屏障触发模式（0=所有load，1=addr[31]==1，2=addr[30:28]!=0）
        rb_mode=0,
        extensions="RV32I+GC",
    ):
        self.ncores = ncores
        self.imem_words = imem_words
        self.dmem_words = dmem_words
        self.dmem_init = dmem_init
        self.imem_inits = imem_inits or [[0]*imem_words for _ in range(ncores)]
        self.scan_fifo_depth = scan_fifo_depth
        self.scan_consume_every = scan_consume_every
        self.scan_batch_size = int(scan_batch_size)
        self.scan_dedup_enable = bool(scan_dedup_enable)
        self.scan_cardset_size = int(scan_cardset_size)
        self.sweep_card_dedup_enable = bool(sweep_card_dedup_enable)
        self.sweep_card_table_size = int(sweep_card_table_size)
        self.sweep_card_table_ways = int(sweep_card_table_ways)
        self.sweep_card_index_mode = int(sweep_card_index_mode)

        self.wb_ptr_filter = int(wb_ptr_filter)
        self.wb_card_shift = int(wb_card_shift)
        self.wb_obj_shift  = int(wb_obj_shift)
        self.rb_mode = int(rb_mode)
        self.extensions = extensions
        self.trap = Signal(ncores)

    def elaborate(self, platform):
        m = Module()

        # Shared DMEM + arb
        m.submodules.dmem = dmem = SimpleDMem(words=self.dmem_words, init=self.dmem_init)
        m.submodules.arb  = arb  = RRArbiter(n=self.ncores)

        # ----------------------
        # 3 个 GC 协处理器（骨架）
        # ----------------------
        # scan : 写屏障事件收集/扫描
        # sweep: 引用计数/清理（当前承载 Step3 的 6 条 GC 指令实现）
        # mv   : 移动/转发表（占位骨架，后续支撑读屏障）
        m.submodules.gc_scan  = gc_scan  = GCScanCoProc(
            ncores=self.ncores,
            fifo_depth=self.scan_fifo_depth,
            consume_every=self.scan_consume_every,
            batch_size=self.scan_batch_size,
            dedup_enable=self.scan_dedup_enable,
            cardset_size=self.scan_cardset_size,
        )
        m.submodules.gc_sweep = gc_sweep = GCSweepCoProc(
            ncores=self.ncores,
            card_dedup_enable=self.sweep_card_dedup_enable,
            card_table_size=self.sweep_card_table_size,
            card_table_ways=self.sweep_card_table_ways,
            card_index_mode=self.sweep_card_index_mode,
        )
        m.submodules.gc_mv    = gc_mv    = GCMvCoProc(ncores=self.ncores)

        # Step47：sweep RELOC commit -> mv forwarding table sideband
        for i in range(self.ncores):
            m.d.comb += [
                gc_mv.upd_valid[i].eq(gc_sweep.mv_upd_valid[i]),
                gc_mv.upd_old[i].eq(gc_sweep.mv_upd_old[i]),
                gc_mv.upd_new[i].eq(gc_sweep.mv_upd_new[i]),
            ]

        # Step20：epoch 广播
        # - 任一核执行 GC_EPOCH 后，sweep 会对该核产生 epoch_tick 脉冲。
        # - SoC 层把所有 tick OR 起来广播给 scan（scan 内部翻转 epoch）。
        ep_any = Signal()
        ep_or = Const(0)
        for i in range(self.ncores):
            ep_or = ep_or | gc_sweep.epoch_tick[i]
        m.d.comb += [
            ep_any.eq(ep_or),
            gc_scan.epoch_advance.eq(ep_any),
            gc_mv.epoch_advance.eq(ep_any),
        ]

        # Step21：scan out_q -> sweep（最小‘标记模拟’闭环）
        # - scan 的 out_* 是 “被消费的 card stream”
        # - sweep 作为下一阶段，接收并做计数/记录 last_*
        m.d.comb += [
            gc_sweep.card_in_valid.eq(gc_scan.out_valid),
            gc_scan.out_ready.eq(gc_sweep.card_in_ready),
            gc_sweep.card_in_card_id.eq(gc_scan.out_card_id),
            gc_sweep.card_in_core_id.eq(gc_scan.out_core_id),
            gc_sweep.card_in_epoch.eq(gc_scan.out_epoch),
        ]

        # Cores + IMEMs
        cores = []
        for i in range(self.ncores):
            core = RV12Core(
                core_id=i,
                wb_ptr_filter=self.wb_ptr_filter,
                wb_card_shift=self.wb_card_shift,
                wb_obj_shift=self.wb_obj_shift,
                rb_mode=self.rb_mode,
                extensions=extensions,
            )
            cores.append(core)
            m.submodules[f"core{i}"] = core

            # per-core IMEM
            imem = SimpleIMem(words=self.imem_words, init=self.imem_inits[i])
            m.submodules[f"imem{i}"] = imem
            m.d.comb += [
                imem.addr.eq(core.imem_addr),
                core.imem_rdata.eq(imem.rdata),
            ]

            # DMEM master -> arb
            m.d.comb += [
                arb.m_valid[i].eq(core.dmem_valid),
                arb.m_we[i].eq(core.dmem_we),
                arb.m_addr[i].eq(core.dmem_addr),
                arb.m_wdata[i].eq(core.dmem_wdata),
                arb.m_lock[i].eq(core.dmem_lock),
                core.dmem_rdata.eq(arb.m_rdata[i]),
                # Step15：把仲裁 grant 反馈给 core，让 MEM1 的请求能保持到被选中为止。
                core.dmem_grant.eq(arb.m_grant[i]),
            ]

            # ----------------------
            # GC 指令 -> sweep 协处理器（当前版本：先让原 6 指令保持可用）
            # ----------------------
            m.d.comb += [
                gc_sweep.cmd_enq_valid[i].eq(core.gc_enq_valid),
                core.gc_enq_ready.eq(gc_sweep.cmd_enq_ready[i]),
                gc_sweep.cmd_tag[i].eq(core.gc_tag),
                gc_sweep.cmd_op[i].eq(core.gc_op),
                gc_sweep.cmd_rd[i].eq(core.gc_rd),
                gc_sweep.cmd_rs1[i].eq(core.gc_rs1),
                gc_sweep.cmd_rs2[i].eq(core.gc_rs2),

                core.gc_rsp_valid.eq(gc_sweep.rsp_valid[i]),
                core.gc_rsp_tag.eq(gc_sweep.rsp_tag[i]),
                core.gc_rsp_rd.eq(gc_sweep.rsp_rd[i]),
                core.gc_rsp_data.eq(gc_sweep.rsp_data[i]),
                gc_sweep.rsp_take[i].eq(core.gc_rsp_take),
            ]

            # ----------------------
            # 写屏障事件 -> scan 协处理器
            # ----------------------
            m.d.comb += [
                gc_scan.wb_valid[i].eq(core.wb_enq_valid),
                core.wb_enq_ready.eq(gc_scan.wb_ready[i]),
                gc_scan.wb_addr[i].eq(core.wb_addr),
                gc_scan.wb_data[i].eq(core.wb_data),
            ]

            # ----------------------
            # 读屏障/MV -> mv 协处理器
            # ----------------------
            m.d.comb += [
                gc_mv.cmd_enq_valid[i].eq(core.mv_cmd_valid),
                core.mv_cmd_ready.eq(gc_mv.cmd_enq_ready[i]),
                gc_mv.cmd_tag[i].eq(core.mv_cmd_tag),
                gc_mv.cmd_op[i].eq(core.mv_cmd_op),
                gc_mv.cmd_rd[i].eq(core.mv_cmd_rd),
                gc_mv.cmd_rs1[i].eq(core.mv_cmd_rs1),
                gc_mv.cmd_rs2[i].eq(core.mv_cmd_rs2),

                core.mv_rsp_valid.eq(gc_mv.rsp_valid[i]),
                core.mv_rsp_tag.eq(gc_mv.rsp_tag[i]),
                core.mv_rsp_rd.eq(gc_mv.rsp_rd[i]),
                core.mv_rsp_data.eq(gc_mv.rsp_data[i]),
                gc_mv.rsp_take[i].eq(core.mv_rsp_take),
            ]

            # trap 汇总：核心 trap + sweep trap + （预留）scan/mv trap
            m.d.comb += self.trap[i].eq(core.trap | gc_sweep.trap[i] | gc_scan.trap[i] | gc_mv.trap[i])

        # arb -> dmem
        m.d.comb += [
            dmem.req_valid.eq(arb.s_valid),
            dmem.req_we.eq(arb.s_we),
            dmem.req_addr.eq(arb.s_addr),
            dmem.req_wdata.eq(arb.s_wdata),
            arb.s_rdata.eq(dmem.rsp_rdata),
        ]

        return m
