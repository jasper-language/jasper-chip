# rtl/rv12_core.py
from amaranth import *
from .sm4 import sm4_result
from .aes32 import aes32_result
from amaranth.lib.fifo import SyncFIFO
from collections.abc import Iterable
from .isa import *
from .gc_subsystem import GCSubsystem, with_gc_profile
from .gc_config import get_profile as _get_gc_profile
from .isa_c_expand import CExpander
from .isa_svnapot import Svnapot
from .isa_svpbmt import Svpbmt
from .vmemory_pipeline import VMemoryPipeline
from .vfdiv_pipeline import VFDivPipeline
from .vfsqrt_pipeline import VFSqrtPipeline
from .vfestimate7_pipeline import VFEstimate7Pipeline
from .vfadd_unit import VFAddUnit
from .vfadd_pipeline import VFAddPipeline
from .qfadd_unit import QFAddUnit
from .qfmul_unit import QFMulUnit
from .qfdiv_unit import QFDivUnit
from .qfsqrt_unit import QFSqrtUnit
from .qffma_unit import QFFMAUnit
from .vffma_pipeline import VFFMAPipeline
from .vfcvt_pipeline import VFCvtPipeline
from .is_advance_control import ISAdvanceControl
from .fp_store_hazard_control import FPStoreHazardControl
from .branch_condition import BranchCondition
from .jump_control import JumpControl
from .pending_register_hazard import PendingRegisterHazard
from .dependency_stall_control import DependencyStallControl
from .pending_mask_control import PendingMaskControl
from .base_rs1_usage_control import BaseRS1UsageControl
from .base_rd_write_control import BaseRDWriteControl

_ISA_EXT_ALIASES = {
    "RV32I": "RV32I",
    "I": "RV32I",
    "RV64I": "RV32I",
    "GC": "GC",
    "M": "M",
    "ZMMUL": "M",
    "ZIHINTPAUSE": "ZIHINTPAUSE",
    "ZIHINTNTL": "ZIHINTNTL",
    "ZTSO": "ZTSO",
    "ZCB": "C",
    "ZCF": "C",
    "ZCD": "C",
    "A": "A",
    "ZALRSC": "A",
    "B": "B",
    "C": "C",
    "F": "F",
    "D": "D",
    "Q": "Q",
    "V": "V",
    "ZBA": "B",
    "ZBB": "B",
    "ZBC": "B",
    "ZBKC": "B",
    "ZBE": "B",
    "ZBF": "B",
    "ZBG": "B",
    "ZBH": "B",
    "ZBI": "B",
    "ZBK": "B",
    "ZBL": "B",
    "ZBM": "B",
    "ZBN": "B",
    "ZBP": "B",
    "ZBR": "B",
    "ZBS": "B",
    "ZBT": "B",
    "ZBU": "B",
    "ZBV": "B",
    "ZBX": "B",
    "ZBZ": "B",
    "ZICOND": "ZICOND",
    "ZKNH": "ZKNH",
    "ZKNE": "ZKNE",
    "ZKND": "ZKND",
    "ZKSH": "ZKSH",
    "ZKSED": "ZKSED",
    "ZAWRS": "ZAWRS",
    "ZIMOP": "ZIMOP",
    "ZCMOP": "ZCMOP",
    "ZCMT": "ZCMT",
    "ZCMP": "ZCMP",
    "ZKN": "ZKN",
    "ZKS": "ZKS",
    "ZKR": "ZKR",
    "ZKT": "ZKT",
    "ZK": "ZK",
    "ZFA": "ZFA",
    "ZFH": "ZFH",
    "ZFHMIN": "ZFHMIN",
    "ZFINX": "ZFINX",
    "ZDINX": "ZDINX",
    "ZHINX": "ZHINX",
    "ZHINXMIN": "ZHINXMIN",
    "ZICSR": "ZICSR",
    "ZIFENCEI": "ZIFENCEI",
    "SVINVAL": "SVINVAL",
    "SVNAPOT": "SVNAPOT",
    "SVPBMT": "SVPBMT",
}

_STANDARD_EXTENSIONS = frozenset({"M", "A", "B", "F", "D", "Q", "C", "V", "ZICSR", "ZIFENCEI", "ZICOND", "ZKNH", "ZKNE", "ZKND", "ZKSH", "ZKSED", "ZAWRS", "ZIMOP", "ZCMOP", "ZKN", "ZKS", "ZKR", "ZKT", "ZK", "ZFA", "ZFH", "ZFHMIN", "ZFINX", "ZDINX", "ZHINX", "ZHINXMIN", "SVINVAL", "SVNAPOT", "SVPBMT"})
_GC_EXTENSIONS = frozenset({"GC"})


def normalize_extension_spec(spec):
    """Normalize extension spec into a canonical set.

    Supported forms:
    - "RV32I+GC+*"
    - "RV32I+GC+M+A"
    - "M" (interpreted as RV32I+GC baseline + M)
    Unknown tokens are ignored in a non-failing way.
    """
    if spec is None:
        spec = "RV32I+GC"
    if not isinstance(spec, str) and isinstance(spec, Iterable):
        tokens = set()
        for raw_token in spec:
            if raw_token is None:
                continue
            tokens.update(str(raw_token).replace("-", "").replace(" ", "").upper().split("+"))
    else:
        tokens = set(str(spec).replace("-", "").replace(" ", "").upper().split("+"))

    extensions = set()
    if "*" in tokens:
        extensions |= set(_STANDARD_EXTENSIONS)
        tokens.discard("*")

    for t in tokens:
        if not t:
            continue
        if t.startswith("ZB") and t not in _ISA_EXT_ALIASES:
            t = "B"
        alias = _ISA_EXT_ALIASES.get(t)
        if alias is None:
            continue
        if alias == "GC":
            extensions.update(_GC_EXTENSIONS)
        else:
            extensions.add(alias)

    extensions.add("RV32I")
    extensions.add("GC")
    return extensions


def sign_extend(value, bits, out_bits=32):
    """Sign-extend a low-`bits` Value to out_bits."""
    sign = value[bits - 1]
    if out_bits == bits:
        return value
    return Cat(value, Cat(*([sign] * (out_bits - bits))))


class RV12Core(Elaboratable):
    @classmethod
    def with_gc_profile(cls, profile: str, **kwargs):
        cfg = _get_gc_profile(profile)
        d = cfg.to_dict()
        d.update(kwargs)
        return cls(**d)

    def __init__(self, core_id=0, xlen=32, wb_ptr_filter=0, wb_card_shift=6, wb_obj_shift=4, rb_mode=0,
                 extensions="RV32I+GC",
                 gc_slots=16, rb_cache_ways=4, rb_slots=4, wb_depth=4, mv_depth=4,
                 wb_combine_depth=0, gc_slots_bank_count=1, gc_slots_bank_impl="standard", **_):
        if isinstance(extensions, str):
            requested_tokens = set(extensions.replace("-", "").replace(" ", "").upper().split("+"))
        elif isinstance(extensions, Iterable):
            requested_tokens = set()
            for requested in extensions or ():
                requested_tokens.update(str(requested).replace("-", "").replace(" ", "").upper().split("+"))
        else:
            requested_tokens = set()
        self.extensions = normalize_extension_spec(extensions)
        self.core_id = core_id
        self.xlen = xlen
        self.enable_c = "C" in self.extensions
        self.enable_m = "M" in self.extensions
        self.enable_a = "A" in self.extensions
        self.enable_b = ("B" in self.extensions) or ("ZKN" in self.extensions) or ("ZKS" in self.extensions) or ("ZK" in self.extensions)
        self.enable_zfinx = "ZFINX" in self.extensions
        self.use_zfinx = "ZFINX" in requested_tokens
        self.enable_zdinx = "ZDINX" in self.extensions
        self.use_zdinx = "ZDINX" in requested_tokens
        self.enable_zhinx = "ZHINX" in self.extensions
        self.use_zhinx = "ZHINX" in requested_tokens
        self.enable_zhinxmin = self.enable_zhinx or ("ZHINXMIN" in self.extensions)
        self.use_zhinxmin = self.use_zhinx or ("ZHINXMIN" in requested_tokens)
        self.use_finx = self.use_zfinx or self.use_zdinx or self.use_zhinxmin
        self.enable_f = bool(
            {"F", "D", "Q", "ZFH", "ZFHMIN"} & self.extensions
        ) and not self.use_finx
        self.enable_d = bool({"D", "Q"} & self.extensions) and not self.use_finx
        self.enable_q = ("Q" in self.extensions) and not self.use_finx
        self.enable_v = "V" in self.extensions
        self.enable_fp32 = self.enable_f or self.use_zfinx
        self.enable_fp64 = self.enable_d or (self.use_zdinx and self.xlen >= 64)
        self.enable_zicond = "ZICOND" in self.extensions
        self.enable_zknh = ("ZKNH" in self.extensions) or ("ZKN" in self.extensions) or ("ZK" in self.extensions)
        self.enable_zkne = ("ZKNE" in self.extensions) or ("ZKN" in self.extensions) or ("ZK" in self.extensions)
        self.enable_zknd = ("ZKND" in self.extensions) or ("ZKN" in self.extensions) or ("ZK" in self.extensions)
        self.enable_zksh = ("ZKSH" in self.extensions) or ("ZKS" in self.extensions)
        self.enable_zksed = ("ZKSED" in self.extensions) or ("ZKS" in self.extensions)
        self.enable_zawrs = "ZAWRS" in self.extensions
        self.enable_zimop = "ZIMOP" in self.extensions
        self.enable_zcmop = "ZCMOP" in self.extensions
        # Zcmt overlaps Zcd encodings, so the project-wide '*' set only enables
        # it when ZCMT is explicitly requested.
        self.enable_zcmt = "ZCMT" in requested_tokens
        self.enable_zcmp = "ZCMP" in requested_tokens
        self.enable_zkr = ("ZKR" in self.extensions) or ("ZK" in self.extensions)
        self.enable_zkt = ("ZKT" in self.extensions) or ("ZK" in self.extensions)
        self.enable_zfa = "ZFA" in self.extensions
        self.enable_zfh = ("ZFH" in self.extensions) or self.enable_zhinx
        self.enable_zfhmin = self.enable_zfh or ("ZFHMIN" in self.extensions) or self.enable_zhinxmin
        self.seed_entropy = Signal(16)
        self.seed_entropy_valid = Signal()
        fp_csr_extensions = {
            "F", "D", "Q", "ZFH", "ZFHMIN", "ZFINX", "ZDINX",
            "ZHINX", "ZHINXMIN",
        }
        self.enable_zicsr = (("ZICSR" in self.extensions) or
                             bool(fp_csr_extensions & self.extensions))
        self.enable_zifencei = "ZIFENCEI" in self.extensions
        self.enable_svinval = "SVINVAL" in self.extensions
        # Svnapot depends on Sv39 and is therefore not applicable to RV32.
        self.enable_svnapot = (self.xlen >= 64) and ("SVNAPOT" in self.extensions)
        # Svpbmt depends on Sv39 and is therefore not applicable to RV32.
        self.enable_svpbmt = (self.xlen >= 64) and ("SVPBMT" in self.extensions)

        self.gc_slots = int(gc_slots)
        self.rb_cache_ways = int(rb_cache_ways)
        self.rb_slots = int(rb_slots)
        self.wb_depth = int(wb_depth)
        self.mv_depth = int(mv_depth)
        self.wb_combine_depth = int(wb_combine_depth)
        self.gc_slots_bank_count = int(gc_slots_bank_count)
        self.gc_slots_bank_impl = str(gc_slots_bank_impl)
        # 写屏障指针过滤：
        #   - 0: 不过滤（所有 store 都上报事件）
        #   - 1: 只上报"看起来像指针"的写入（当前判定：wdata[31]==1）
        self.wb_ptr_filter = int(wb_ptr_filter)
        # Step17：写屏障事件格式升级（card_id / obj_id）
        # - card_id = store_addr >> wb_card_shift   （例如 card_shift=6 => 64B card）
        # - obj_id  = store_addr >> wb_obj_shift    （例如 obj_shift=4 => 16B 对齐对象）
        # 说明：研究阶段用 shift 近似对象粒度；未来可替换为"对象基址/对象句柄"。
        self.wb_card_shift = int(wb_card_shift)
        self.wb_obj_shift  = int(wb_obj_shift)
        # Step73：读屏障触发模式
        #   - 0: 所有 load 都触发 MV_QUERY（研究验证模式，向后兼容）
        #   - 1: 仅当 load_addr[31]==1 时触发（指针标记模式）
        #   - 2: 仅当 load_addr[30:28]!=0 时触发（epoch tag 模式）
        self.rb_mode = int(rb_mode)

        # IMEM interface
        self.imem_addr = Signal(32)
        self.imem_rdata = Signal(32)

        # DMEM (shared via arbiter)
        self.dmem_valid = Signal()
        self.dmem_we    = Signal()
        self.dmem_addr  = Signal(32)
        self.dmem_wdata = Signal(32)
        self.dmem_rdata = Signal(32)
        self.dmem_lock = Signal()

        # Step15：多核共享单端口 DMEM 时，需要“本拍是否被仲裁选中”的反馈。
        # 说明：
        #   - 单核/直连 DMEM 的旧测试无需改线，因此这里默认 reset=1（等价于永远被选中）。
        #   - TopSoC / 多核测试台会把它接到 RRArbiter 的 m_grant[i]。
        #   - Core 会在 MEM1 阶段根据 grant 做 stall，从而让同一笔 load/store 请求
        #     在未被选中时不会“单拍丢失”。
        self.dmem_grant = Signal(reset=1)

        # GC enqueue interface (to shared coproc)
        self.gc_enq_valid = Signal()
        self.gc_enq_ready = Signal()
        # Step6-A：tag（请求/响应匹配）
        # 说明：先做 8bit，每核本地递增。未来当允许多 outstanding 时，tag 用来防止响应串台。
        self.gc_tag       = Signal(8)
        self.gc_op        = Signal(3)
        self.gc_rd        = Signal(5)
        self.gc_rs1       = Signal(self.xlen)
        self.gc_rs2       = Signal(self.xlen)

        # GC response (from shared coproc)
        self.gc_rsp_valid = Signal()
        self.gc_rsp_tag   = Signal(8)
        self.gc_rsp_rd    = Signal(5)
        self.gc_rsp_data  = Signal(self.xlen)
        self.gc_rsp_take  = Signal()

        # ----------------------
        # 写屏障（Write Barrier）事件通道（发往 GCScanCoProc）
        # ----------------------
        # 研究阶段最小实现：
        #   - Step16：最早版本为“写入地址 + 写入数据”。
        #   - Step17：升级为“card_id + obj_id”，更贴近 card table / remembered set。
        #     注意：指针过滤仍然基于原始写入值（mem_wdata）判定。
        #
        # Step6-B/C 更新：
        #   - 核心内部新增一个小 FIFO（wbq）缓存写屏障事件。
        #   - scan 协处理器满时不再立即全局 stall；只有 wbq 满时才阻塞 store。
        #   - 写屏障事件与 store commit 绑定：store 只有在 wbq 有空间时才允许发往 DMEM。
        self.wb_enq_valid = Signal()
        self.wb_enq_ready = Signal()
        self.wb_addr      = Signal(32)
        self.wb_data      = Signal(32)



        # ----------------------
        # 读屏障（Read Barrier）/ MV 协处理器命令通道
        # ----------------------
        # Step8/9：把 mv 协处理器真正接入 CPU。
        # 设计要点：
        #   - 命令/响应都带 tag（8bit），用于乱序返回时做匹配。
        #   - CPU 内部维护一个小的 pending 表（tag->rd），响应到来时写回 regfile。
        #   - 研究阶段，mv 协处理器的 QUERY 返回 rs1 原值，用来验证链路正确。
        self.mv_cmd_valid = Signal()
        self.mv_cmd_ready = Signal()
        self.mv_cmd_tag   = Signal(8)
        self.mv_cmd_op    = Signal(3)
        self.mv_cmd_rd    = Signal(5)
        self.mv_cmd_rs1   = Signal(self.xlen)
        self.mv_cmd_rs2   = Signal(self.xlen)

        self.mv_rsp_valid = Signal()
        self.mv_rsp_tag   = Signal(8)
        self.mv_rsp_rd    = Signal(5)
        self.mv_rsp_data  = Signal(self.xlen)
        self.mv_rsp_take  = Signal()

        # Step9-B：测试注入口（绕开 IMEM/DMEM，把一条“需要读屏障的值”直接送入 mv 流程）
        # 用途：当 pipeline/内存模型还在调试时，仍能稳定验证：
        #   - 多条 pending
        #   - 响应乱序
        #   - 按 tag 正确写回对应 rd
        self.rb_inj_valid = Signal()
        self.rb_inj_ready = Signal()
        self.rb_inj_rd    = Signal(5)
        self.rb_inj_value = Signal(self.xlen)

        # 调试读口：测试时读取寄存器文件内容（不影响综合）
        self.dbg_reg_addr = Signal(5)
        self.dbg_reg_rdata= Signal(self.xlen)
        self.dbg_freg_addr = Signal(5)
        self.dbg_freg_rdata = Signal(64)
        self.dbg_vreg_addr = Signal(5)
        self.dbg_vreg_rdata = Signal(128)
        self.trap = Signal()
        self.dbg_sinval_vma_count = Signal(16)
        self.dbg_sfence_w_inval_count = Signal(16)
        self.dbg_sfence_inval_ir_count = Signal(16)
        # Svinval invalidation transaction interface.  An MMU/TLB can consume
        # the one-cycle valid pulse while the epoch remains available for
        # cache-tag invalidation and verification.
        self.svinval_valid = Signal()
        self.svinval_vaddr = Signal(self.xlen)
        self.svinval_asid = Signal(self.xlen)
        self.svinval_vaddr_valid = Signal()
        self.svinval_asid_valid = Signal()
        self.svinval_ordered = Signal()
        self.svinval_epoch = Signal(16)
        self.svinval_completion_epoch = Signal(16)
        self.svinval_barrier_active = Signal()
        self.pc_dbg = Signal(self.xlen)

        # ----------------------
        # Step10：调试观测信号（研究/单测用）
        # ----------------------
        # 目的：把“load 是否进入读屏障、是否成功入队”这类问题快速定位出来。
        # 这些信号不参与功能，只是把内部关键状态导出给仿真测试读取。
        self.dbg_mem2_valid   = Signal()
        self.dbg_mem2_is_load = Signal()
        self.dbg_mem2_rd      = Signal(5)
        self.dbg_mem2_wb_data = Signal(self.xlen)
        self.dbg_rb_need_load = Signal()
        self.dbg_rb_enq_ready = Signal()
        self.dbg_rb_fire      = Signal()

        # Step12：scoreboard/GC 调试观测
        # 目的：在研究阶段快速定位“依赖没有被挡住”这类 bug。
        # 不参与功能，仅供 tests 读取。
        self.dbg_pending_rd_mask = Signal(32)
        self.dbg_gc_waiting      = Signal()
        self.dbg_gc_fire         = Signal()
        self.dbg_gc_rs1          = Signal(self.xlen)
        self.dbg_gc_rs2          = Signal(self.xlen)
        self.dbg_stall           = Signal()
        self.dbg_stall_gc_order  = Signal()
        self.dbg_stall_gc_issue  = Signal()
        self.dbg_is_valid        = Signal()
        self.dbg_is_is_gc        = Signal()
        self.dbg_is_insn         = Signal(32)
        self.dbg_svinval_enabled = Signal()
        self.dbg_pte = Signal(64)
        self.dbg_vpn = Signal(44)
        self.dbg_pte_leaf = Signal()
        self.dbg_pte_level = Signal(3)
        self.dbg_pte_translated_ppn = Signal(44)
        self.dbg_pte_region_base = Signal(56)
        self.dbg_pte_page_size = Signal(17)
        self.dbg_pte_napot_valid = Signal()
        self.dbg_pte_pbmt = Signal(2)
        self.dbg_pte_pbmte = Signal()
        self.dbg_pte_pma = Signal()
        self.dbg_pte_noncacheable = Signal()
        self.dbg_pte_io = Signal()
        self.dbg_pte_page_fault = Signal()
        self.dbg_q_recent_valid = Signal()
        self.dbg_q_recent_rd = Signal(5)
        self.dbg_q_recent_data = Signal(128)
        self.dbg_q_mem_busy = Signal()
        self.dbg_q_mem_beat = Signal(2)
        self.dbg_fflags = Signal(5)
        self.dbg_stall_front     = Signal()
        self.dbg_stall_dep_id1   = Signal()
        self.dbg_stall_dep_id2   = Signal()
        self.dbg_is_rs1          = Signal(5)
        self.dbg_is_rs2          = Signal(5)

        self.dbg_id2_valid   = Signal()
        self.dbg_id2_is_load = Signal()
        self.dbg_id2_rd      = Signal(5)
        self.dbg_ex1_rd      = Signal(5)
        self.dbg_ex1_is_load = Signal()
        self.dbg_ex1_valid   = Signal()
        self.dbg_ex1_a       = Signal(self.xlen)
        self.dbg_ex1_b       = Signal(self.xlen)
        self.dbg_ex1_src_a   = Signal(self.xlen)
        self.dbg_ex1_src_b   = Signal(self.xlen)
        self.dbg_ex1_funct3  = Signal(3)
        self.dbg_ex1_funct7  = Signal(7)
        self.dbg_ex1_opcode  = Signal(7)
        self.dbg_ex1_rs1     = Signal(5)
        self.dbg_ex1_rs2     = Signal(5)
        self.dbg_mem1_rd     = Signal(5)
        self.dbg_mem1_is_load = Signal()
        self.dbg_mem1_valid  = Signal()
        self.dbg_id1_rd     = Signal(5)
        self.dbg_id1_valid  = Signal()
        self.dbg_id1_is_load = Signal()
        self.dbg_id1_uses_int_rs1 = Signal()
        self.dbg_id1_uses_int_rs2 = Signal()
        self.dbg_id1_writes_int_rd = Signal()

    def elaborate(self, platform):
        m = Module()
        csr_menvcfg = Signal(self.xlen)

        m.submodules.svnapot_pte = svnapot_pte = Svnapot(xlen=self.xlen)
        m.submodules.svpbmt_pte = svpbmt_pte = Svpbmt(xlen=self.xlen)
        m.d.comb += [
            svnapot_pte.pte.eq(self.dbg_pte),
            svnapot_pte.vpn.eq(self.dbg_vpn),
            svnapot_pte.leaf.eq(self.dbg_pte_leaf),
            svnapot_pte.level.eq(self.dbg_pte_level),
            svpbmt_pte.pte.eq(self.dbg_pte),
            svpbmt_pte.leaf.eq(self.dbg_pte_leaf),
            svpbmt_pte.pbmte.eq(csr_menvcfg[62] if self.xlen >= 64 else 0),
            self.dbg_pte_pbmt.eq(self.dbg_pte[61:63]),
            self.dbg_pte_pbmte.eq(csr_menvcfg[62] if self.xlen >= 64 else 0),
        ]
        if self.enable_svnapot:
            m.d.comb += [
                self.dbg_pte_translated_ppn.eq(svnapot_pte.translated_ppn),
                self.dbg_pte_region_base.eq(svnapot_pte.region_base),
                self.dbg_pte_page_size.eq(svnapot_pte.page_size),
                self.dbg_pte_napot_valid.eq(svnapot_pte.napot_valid),
            ]
            napot_fault = svnapot_pte.page_fault
        else:
            m.d.comb += [
                self.dbg_pte_translated_ppn.eq(self.dbg_pte[10:54]),
                self.dbg_pte_region_base.eq(Cat(C(0, 12), self.dbg_pte[10:54])),
                self.dbg_pte_page_size.eq(4096),
                self.dbg_pte_napot_valid.eq(0),
            ]
            napot_fault = self.dbg_pte[63]
        if self.enable_svpbmt:
            m.d.comb += [
                self.dbg_pte_pma.eq(svpbmt_pte.pma),
                self.dbg_pte_noncacheable.eq(svpbmt_pte.noncacheable),
                self.dbg_pte_io.eq(svpbmt_pte.io),
            ]
            pbmt_fault = svpbmt_pte.page_fault
        else:
            m.d.comb += [
                self.dbg_pte_pma.eq(self.dbg_pte_leaf & (self.dbg_pte[61:63] == 0)),
                self.dbg_pte_noncacheable.eq(0),
                self.dbg_pte_io.eq(0),
            ]
            pbmt_fault = self.dbg_pte[61:63] != 0
        m.d.comb += self.dbg_pte_page_fault.eq(napot_fault | pbmt_fault)

        # (wbq and mvq moved into GCSubsystem)


        # (RB pending table, cache, and scoreboard moved into GCSubsystem)


        # ----------------------
        # Register file
        # ----------------------
        regs = Array(Signal(self.xlen, name=f"c{self.core_id}_x{i}") for i in range(32))
        fregs = Array(Signal(128, name=f"c{self.core_id}_f{i}") for i in range(32))
        vregs = Array(Signal(128, name=f"c{self.core_id}_v{i}") for i in range(32))
        def rreg(i): return Mux(i == 0, 0, regs[i])
        def freg(i): return fregs[i]
        csr_mstatus = Signal(self.xlen)
        csr_fflags = Signal(5)
        csr_frm = Signal(3)
        m.d.comb += self.dbg_fflags.eq(csr_fflags)
        csr_jvt = Signal(self.xlen)
        csr_vl = Signal(self.xlen)
        csr_vtype = Signal(self.xlen, init=1 << (self.xlen - 1))
        csr_vlmax = Signal(8)
        csr_vstart = Signal(self.xlen)
        csr_vxsat = Signal()
        csr_vxrm = Signal(2)
        vfdiv_pipe = VFDivPipeline(
            xlen=self.xlen, enable_fp32=self.enable_fp32,
            enable_fp64=self.enable_fp64)
        if self.enable_v:
            m.submodules.vfdiv_pipe = vfdiv_pipe
        m.d.comb += [
            vfdiv_pipe.issue_valid.eq(0), vfdiv_pipe.insn.eq(0),
            vfdiv_pipe.vtype.eq(csr_vtype), vfdiv_pipe.vl.eq(csr_vl),
            vfdiv_pipe.vlmax.eq(csr_vlmax),
            vfdiv_pipe.vstart.eq(csr_vstart), vfdiv_pipe.frm.eq(csr_frm),
            vfdiv_pipe.scalar.eq(0),
            *[vfdiv_pipe.vregs[reg].eq(vregs[reg]) for reg in range(32)],
        ]
        with m.If(vfdiv_pipe.write_valid):
            with m.If(vfdiv_pipe.write_is_f64):
                m.d.sync += vregs[vfdiv_pipe.write_reg].word_select(
                    vfdiv_pipe.write_lane, 64).eq(vfdiv_pipe.write_data)
            with m.Else():
                m.d.sync += vregs[vfdiv_pipe.write_reg].word_select(
                    vfdiv_pipe.write_lane, 32).eq(vfdiv_pipe.write_data[:32])
        with m.If(vfdiv_pipe.fflags_write_valid):
            m.d.sync += csr_fflags.eq(csr_fflags | vfdiv_pipe.fflags_write_value)
        with m.If(vfdiv_pipe.vstart_valid):
            m.d.sync += csr_vstart.eq(vfdiv_pipe.vstart_value)
        vfcvt_pipe = VFCvtPipeline(
            xlen=self.xlen, enable_fp32=self.enable_fp32,
            enable_fp64=self.enable_fp64)
        if self.enable_v:
            m.submodules.vfcvt_pipe = vfcvt_pipe
        m.d.comb += [
            vfcvt_pipe.issue_valid.eq(0), vfcvt_pipe.insn.eq(0),
            vfcvt_pipe.vtype.eq(csr_vtype), vfcvt_pipe.vl.eq(csr_vl),
            vfcvt_pipe.vlmax.eq(csr_vlmax),
            vfcvt_pipe.vstart.eq(csr_vstart),
            vfcvt_pipe.frm.eq(csr_frm),
            *[vfcvt_pipe.vregs[reg].eq(vregs[reg]) for reg in range(32)],
        ]
        with m.If(vfcvt_pipe.write_valid):
            with m.If(vfcvt_pipe.write_is_f64):
                m.d.sync += vregs[vfcvt_pipe.write_reg].word_select(
                    vfcvt_pipe.write_lane, 64).eq(vfcvt_pipe.write_data)
            with m.Else():
                m.d.sync += vregs[vfcvt_pipe.write_reg].word_select(
                    vfcvt_pipe.write_lane, 32).eq(vfcvt_pipe.write_data[:32])
        with m.If(vfcvt_pipe.fflags_write_valid):
            m.d.sync += csr_fflags.eq(
                csr_fflags | vfcvt_pipe.fflags_write_value)
        with m.If(vfcvt_pipe.vstart_valid):
            m.d.sync += csr_vstart.eq(vfcvt_pipe.vstart_value)
        vfredsum_active = Signal()
        vfredsum_index = Signal(8)
        vfredsum_vl = Signal(8)
        vfredsum_vd = Signal(5)
        vfredsum_vs2 = Signal(5)
        vfredsum_is_f64 = Signal()
        vfredsum_widen = Signal()
        vfredsum_vm = Signal()
        vfredsum_vta = Signal()
        vfredsum_accum = Signal(64)
        vfredsum_flags = Signal(5)
        m.submodules.vfredsum_add = vfredsum_add = VFAddUnit()
        m.submodules.qfadd = qfadd = QFAddUnit()
        m.submodules.qfmul = qfmul = QFMulUnit()
        m.submodules.qfdiv = qfdiv = QFDivUnit()
        m.submodules.qfsqrt = qfsqrt = QFSqrtUnit()
        m.submodules.qffma = qffma = QFFMAUnit()
        vfredsum_reg_offset = Signal(5)
        vfredsum_src_reg = Signal(5)
        vfredsum_src_data = Signal(128)
        vfredsum_lane32 = Signal(32)
        vfredsum_lane64 = Signal(64)
        vfredsum_widened = Signal(64)
        vfredsum_lane = Signal(64)
        vfredsum_enabled = Signal()
        vfredsum_dest_data = Signal(128)
        m.d.comb += [
            vfredsum_reg_offset.eq(Mux(vfredsum_is_f64 & ~vfredsum_widen,
                                       vfredsum_index >> 1,
                                       vfredsum_index >> 2)),
            vfredsum_src_reg.eq(vfredsum_vs2 + vfredsum_reg_offset),
            vfredsum_src_data.eq(vregs[vfredsum_src_reg]),
            vfredsum_lane32.eq(
                vfredsum_src_data.word_select(vfredsum_index[0:2], 32)),
            vfredsum_lane64.eq(
                vfredsum_src_data.word_select(vfredsum_index[0], 64)),
            vfredsum_enabled.eq(
                vfredsum_vm | vregs[0].bit_select(vfredsum_index, 1)),
            vfredsum_add.is_f64.eq(vfredsum_is_f64),
            vfredsum_add.a.eq(vfredsum_accum),
            vfredsum_add.b.eq(vfredsum_lane),
            vfredsum_add.rm.eq(csr_frm),
            vfredsum_dest_data.eq(vregs[vfredsum_vd]),
        ]
        widen_exp = vfredsum_lane32[23:31]
        widen_frac = vfredsum_lane32[:23]
        widen_leading = Signal(range(23))
        widen_sub_frac = Signal(53)
        m.d.comb += [
            widen_leading.eq(0),
            widen_sub_frac.eq(
                widen_frac << (52 - widen_leading).as_unsigned()),
            vfredsum_widened.eq(Cat(
                C(0, 29), widen_frac,
                Mux(widen_exp == 0xFF, C(0x7FF, 11),
                    Mux(widen_exp == 0, 0, widen_exp + 896)),
                vfredsum_lane32[31])),
        ]
        for bit in range(23):
            with m.If(widen_frac[bit]):
                m.d.comb += widen_leading.eq(bit)
        with m.If((widen_exp == 0) & widen_frac.any()):
            m.d.comb += vfredsum_widened.eq(Cat(
                widen_sub_frac[:52], widen_leading + 874,
                vfredsum_lane32[31]))
        m.d.comb += vfredsum_lane.eq(Mux(
            vfredsum_widen, vfredsum_widened,
            Mux(vfredsum_is_f64, vfredsum_lane64, vfredsum_lane32)))
        with m.If(vfredsum_is_f64):
            m.d.comb += vfredsum_dest_data[0:64].eq(vfredsum_accum)
            with m.If(vfredsum_vta):
                m.d.comb += vfredsum_dest_data[64:128].eq(C(-1, 64))
        with m.Else():
            m.d.comb += vfredsum_dest_data[0:32].eq(vfredsum_accum[:32])
            with m.If(vfredsum_vta):
                m.d.comb += vfredsum_dest_data[32:128].eq(C(-1, 96))
        with m.If(vfredsum_active):
            with m.If(vfredsum_index < vfredsum_vl):
                with m.If(vfredsum_enabled):
                    m.d.sync += [
                        vfredsum_accum.eq(vfredsum_add.result),
                        vfredsum_flags.eq(vfredsum_flags | vfredsum_add.flags),
                        vfredsum_index.eq(vfredsum_index + 1),
                    ]
                with m.Else():
                    m.d.sync += vfredsum_index.eq(vfredsum_index + 1)
            with m.Else():
                with m.If(vfredsum_vl != 0):
                    m.d.sync += [
                        vregs[vfredsum_vd].eq(vfredsum_dest_data),
                        csr_fflags.eq(csr_fflags | vfredsum_flags),
                    ]
                m.d.sync += [
                    csr_vstart.eq(0),
                    vfredsum_active.eq(0),
                ]

        vmem_pipe = VMemoryPipeline(xlen=self.xlen)
        vmem_is_insn = Signal()
        vmem_backend_clear = Signal()
        vmem_launch = Signal()
        if self.enable_v:
            m.submodules.vmem_pipe = vmem_pipe
        m.d.comb += [
            vmem_is_insn.eq(0), vmem_backend_clear.eq(0),
            vmem_launch.eq(0),
            vmem_pipe.issue_valid.eq(0), vmem_pipe.insn.eq(0),
            vmem_pipe.vtype.eq(csr_vtype), vmem_pipe.vl.eq(csr_vl),
            vmem_pipe.vlmax.eq(csr_vlmax),
            vmem_pipe.vstart.eq(csr_vstart),
            vmem_pipe.base.eq(0), vmem_pipe.stride.eq(0),
            vmem_pipe.dmem_grant.eq(self.dmem_grant),
            vmem_pipe.dmem_rdata.eq(self.dmem_rdata),
            vmem_pipe.dmem_error.eq(0),
            *[vmem_pipe.vregs[reg].eq(vregs[reg]) for reg in range(32)],
        ]
        with m.If(vmem_pipe.write_valid):
            m.d.sync += vregs[vmem_pipe.write_reg].word_select(
                vmem_pipe.write_byte, 8).eq(vmem_pipe.write_data)
        with m.If(vmem_pipe.vl_write_valid):
            m.d.sync += csr_vl.eq(vmem_pipe.vl_write_value)
        with m.If(vmem_pipe.vstart_valid):
            m.d.sync += csr_vstart.eq(vmem_pipe.vstart_value)
        with m.If(vmem_pipe.execute_trap):
            m.d.comb += self.trap.eq(1)
        vffma_pipe = VFFMAPipeline(
            xlen=self.xlen, enable_fp32=self.enable_fp32,
            enable_fp64=self.enable_fp64)
        if self.enable_v:
            m.submodules.vffma_pipe = vffma_pipe
        m.d.comb += [
            vffma_pipe.issue_valid.eq(0), vffma_pipe.insn.eq(0),
            vffma_pipe.vtype.eq(csr_vtype), vffma_pipe.vl.eq(csr_vl),
            vffma_pipe.vlmax.eq(csr_vlmax),
            vffma_pipe.vstart.eq(csr_vstart), vffma_pipe.frm.eq(csr_frm),
            vffma_pipe.scalar.eq(0),
            *[vffma_pipe.vregs[reg].eq(vregs[reg]) for reg in range(32)],
        ]
        with m.If(vffma_pipe.write_valid):
            with m.If(vffma_pipe.write_is_f64):
                m.d.sync += vregs[vffma_pipe.write_reg].word_select(
                    vffma_pipe.write_lane, 64).eq(vffma_pipe.write_data)
            with m.Else():
                m.d.sync += vregs[vffma_pipe.write_reg].word_select(
                    vffma_pipe.write_lane, 32).eq(vffma_pipe.write_data[:32])
        with m.If(vffma_pipe.fflags_write_valid):
            m.d.sync += csr_fflags.eq(csr_fflags | vffma_pipe.fflags_write_value)
        with m.If(vffma_pipe.vstart_clear):
            m.d.sync += csr_vstart.eq(0)
        vfadd_pipe = VFAddPipeline(
            xlen=self.xlen, enable_fp32=self.enable_fp32,
            enable_fp64=self.enable_fp64)
        if self.enable_v:
            m.submodules.vfadd_pipe = vfadd_pipe
        m.d.comb += [
            vfadd_pipe.issue_valid.eq(0), vfadd_pipe.insn.eq(0),
            vfadd_pipe.vtype.eq(csr_vtype), vfadd_pipe.vl.eq(csr_vl),
            vfadd_pipe.vlmax.eq(csr_vlmax),
            vfadd_pipe.vstart.eq(csr_vstart), vfadd_pipe.frm.eq(csr_frm),
            vfadd_pipe.scalar.eq(0),
            *[vfadd_pipe.vregs[reg].eq(vregs[reg]) for reg in range(32)],
        ]
        with m.If(vfadd_pipe.write_valid):
            with m.If(vfadd_pipe.write_is_f64):
                m.d.sync += vregs[vfadd_pipe.write_reg].word_select(
                    vfadd_pipe.write_lane, 64).eq(vfadd_pipe.write_data)
            with m.Else():
                m.d.sync += vregs[vfadd_pipe.write_reg].word_select(
                    vfadd_pipe.write_lane, 32).eq(vfadd_pipe.write_data[:32])
        with m.If(vfadd_pipe.fflags_write_valid):
            m.d.sync += csr_fflags.eq(csr_fflags | vfadd_pipe.fflags_write_value)
        with m.If(vfadd_pipe.vstart_valid):
            m.d.sync += csr_vstart.eq(vfadd_pipe.vstart_value)
        vfsqrt_pipe = VFSqrtPipeline(
            xlen=self.xlen, enable_fp32=self.enable_fp32,
            enable_fp64=self.enable_fp64)
        if self.enable_v:
            m.submodules.vfsqrt_pipe = vfsqrt_pipe
        m.d.comb += [
            vfsqrt_pipe.issue_valid.eq(0), vfsqrt_pipe.insn.eq(0),
            vfsqrt_pipe.vtype.eq(csr_vtype), vfsqrt_pipe.vl.eq(csr_vl),
            vfsqrt_pipe.vlmax.eq(csr_vlmax),
            vfsqrt_pipe.vstart.eq(csr_vstart),
            vfsqrt_pipe.frm.eq(csr_frm),
            *[vfsqrt_pipe.vregs[reg].eq(vregs[reg]) for reg in range(32)],
        ]
        with m.If(vfsqrt_pipe.write_valid):
            with m.If(vfsqrt_pipe.write_is_f64):
                m.d.sync += vregs[vfsqrt_pipe.write_reg].word_select(
                    vfsqrt_pipe.write_lane, 64).eq(vfsqrt_pipe.write_data)
            with m.Else():
                m.d.sync += vregs[vfsqrt_pipe.write_reg].word_select(
                    vfsqrt_pipe.write_lane, 32).eq(vfsqrt_pipe.write_data[:32])
        with m.If(vfsqrt_pipe.fflags_write_valid):
            m.d.sync += csr_fflags.eq(
                csr_fflags | vfsqrt_pipe.fflags_write_value)
        with m.If(vfsqrt_pipe.vstart_valid):
            m.d.sync += csr_vstart.eq(vfsqrt_pipe.vstart_value)
        vfestimate7_pipe = VFEstimate7Pipeline(
            xlen=self.xlen, enable_fp32=self.enable_fp32,
            enable_fp64=self.enable_fp64)
        if self.enable_v:
            m.submodules.vfestimate7_pipe = vfestimate7_pipe
        m.d.comb += [
            vfestimate7_pipe.issue_valid.eq(0),
            vfestimate7_pipe.insn.eq(0),
            vfestimate7_pipe.vtype.eq(csr_vtype),
            vfestimate7_pipe.vl.eq(csr_vl),
            vfestimate7_pipe.vlmax.eq(csr_vlmax),
            vfestimate7_pipe.vstart.eq(csr_vstart),
            vfestimate7_pipe.frm.eq(csr_frm),
            *[vfestimate7_pipe.vregs[reg].eq(vregs[reg])
              for reg in range(32)],
        ]
        with m.If(vfestimate7_pipe.write_valid):
            with m.If(vfestimate7_pipe.write_is_f64):
                m.d.sync += vregs[vfestimate7_pipe.write_reg].word_select(
                    vfestimate7_pipe.write_lane, 64).eq(
                        vfestimate7_pipe.write_data)
            with m.Else():
                m.d.sync += vregs[vfestimate7_pipe.write_reg].word_select(
                    vfestimate7_pipe.write_lane, 32).eq(
                        vfestimate7_pipe.write_data[:32])
        with m.If(vfestimate7_pipe.fflags_write_valid):
            m.d.sync += csr_fflags.eq(
                csr_fflags | vfestimate7_pipe.fflags_write_value)
        with m.If(vfestimate7_pipe.vstart_valid):
            m.d.sync += csr_vstart.eq(vfestimate7_pipe.vstart_value)
        zcmp_push_active = Signal()
        zcmp_push_drain = Signal(3)
        zcmp_push_slot = Signal(4)
        zcmp_push_count = Signal(4)
        zcmp_push_sp = Signal(self.xlen)
        zcmp_push_adj = Signal(8)
        zcmp_push_store = Signal()
        zcmp_push_index = Signal(4)
        zcmp_push_regs = Array(rreg(reg) for reg in (1, 8, 9, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27))
        zcmp_pop_active = Signal()
        zcmp_pop_drain = Signal(3)
        zcmp_pop_slot = Signal(4)
        zcmp_pop_count = Signal(4)
        zcmp_pop_sp = Signal(self.xlen)
        zcmp_pop_adj = Signal(8)
        zcmp_pop_ret = Signal()
        zcmp_pop_zero = Signal()
        zcmp_pop_load = Signal()
        zcmp_pop_last = Signal()
        zcmp_pop_redirect = Signal()
        zcmp_pop_target = Signal(self.xlen)
        zcmp_pop_data = Array(Signal(self.xlen, name=f"zcmp_pop_{i}") for i in range(13))
        m.d.comb += [
            zcmp_push_store.eq(zcmp_push_active & (zcmp_push_drain == 0)),
            zcmp_push_index.eq(zcmp_push_count - 1 - zcmp_push_slot),
            zcmp_pop_load.eq(zcmp_pop_active & (zcmp_pop_drain == 0)),
            zcmp_pop_last.eq(zcmp_pop_slot + 1 >= zcmp_pop_count),
            zcmp_pop_target.eq(Mux(zcmp_pop_count == 1, self.dmem_rdata, zcmp_pop_data[0]) & ~1),
            zcmp_pop_redirect.eq(zcmp_pop_load & self.dmem_grant & zcmp_pop_last & zcmp_pop_ret),
        ]

        with m.If(zcmp_push_active & (zcmp_push_drain != 0)):
            m.d.sync += zcmp_push_drain.eq(zcmp_push_drain - 1)
        with m.Elif(zcmp_push_store & self.dmem_grant):
            with m.If(zcmp_push_slot + 1 >= zcmp_push_count):
                m.d.sync += [
                    regs[2].eq(zcmp_push_sp - zcmp_push_adj),
                    zcmp_push_active.eq(0),
                ]
            with m.Else():
                m.d.sync += zcmp_push_slot.eq(zcmp_push_slot + 1)

        with m.If(zcmp_pop_active & (zcmp_pop_drain != 0)):
            m.d.sync += zcmp_pop_drain.eq(zcmp_pop_drain - 1)
        with m.Elif(zcmp_pop_load & self.dmem_grant):
            m.d.sync += zcmp_pop_data[zcmp_pop_slot].eq(self.dmem_rdata)
            with m.If(zcmp_pop_last):
                for index, reg in enumerate((1, 8, 9, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27)):
                    with m.If(zcmp_pop_count > index):
                        m.d.sync += regs[reg].eq(Mux(
                            zcmp_pop_slot == index, self.dmem_rdata, zcmp_pop_data[index]
                        ))
                m.d.sync += [
                    regs[2].eq(zcmp_pop_sp + zcmp_pop_adj),
                    zcmp_pop_active.eq(0),
                ]
                with m.If(zcmp_pop_zero):
                    m.d.sync += regs[10].eq(0)
            with m.Else():
                m.d.sync += zcmp_pop_slot.eq(zcmp_pop_slot + 1)

        # 调试读口：组合读取寄存器（x0 永远为 0）
        m.d.comb += self.dbg_reg_rdata.eq(Mux(self.dbg_reg_addr == 0, 0, regs[self.dbg_reg_addr]))
        m.d.comb += self.dbg_freg_rdata.eq(freg(self.dbg_freg_addr))
        m.d.comb += self.dbg_vreg_rdata.eq(vregs[self.dbg_vreg_addr])

        # ----------------------
        # Pipeline stage records (minimal fields)
        # ----------------------
        def S(name):
            return Record([
                ("valid", 1),
                ("pc", self.xlen),
                ("insn", 32),

                ("opcode", 7),
                ("rd", 5),
                ("rs1", 5),
                ("rs2", 5),
                ("funct3", 3),
                ("funct7", 7),

                ("imm", self.xlen),
                ("rs1v", self.xlen),
                ("rs2v", self.xlen),

                ("is_load", 1),
                ("is_store", 1),
                ("is_branch", 1),
                ("is_jal", 1),
                ("is_fence", 1),
                ("compressed", 1),
                ("is_gc", 1),

                ("alu", self.xlen),
                ("mem_addr", self.xlen),
                ("mem_wdata", self.xlen),
                ("fp_mem_wdata", 128),

                ("wb_en", 1),
                ("wb_data", self.xlen),
                ("wb2_en", 1),
                ("wb2_rd", 5),
                ("wb2_data", self.xlen),
                ("fp_wb_en", 1),
                ("fp_wb_data", 128),
                ("fp_wb_q", 1),
            ], name=name)

        IF1, IF2, IF3, IF4 = S("IF1"), S("IF2"), S("IF3"), S("IF4")
        ID1, ID2, IS       = S("ID1"), S("ID2"), S("IS")
        EX1, EX2           = S("EX1"), S("EX2")
        MEM1, MEM2         = S("MEM1"), S("MEM2")
        WB                 = S("WB")
        m.d.comb += [
            self.dbg_is_insn.eq(IS.insn),
            self.dbg_svinval_enabled.eq(self.enable_svinval),
        ]

        vcompress_active = Signal()
        vcompress_issue = Signal()
        vcompress_tail = Signal()
        vcompress_vd = Signal(5)
        vcompress_vsew = Signal(2)
        vcompress_vta = Signal()
        vcompress_vl = Signal(8)
        vcompress_vlmax = Signal(8)
        vcompress_source_index = Signal(8)
        vcompress_dest_index = Signal(8)
        vcompress_tail_index = Signal(8)
        vcompress_source = Signal(1024)
        vcompress_mask = Signal(128)
        m.d.comb += vcompress_issue.eq(0)

        with m.If(vcompress_active):
            with m.If(~vcompress_tail):
                with m.If(vcompress_source_index < vcompress_vl):
                    with m.If(vcompress_mask.bit_select(
                            vcompress_source_index, 1)):
                        with m.Switch(vcompress_vsew):
                            with m.Case(0):
                                m.d.sync += vregs[
                                    vcompress_vd + vcompress_dest_index[4:8]
                                ].word_select(vcompress_dest_index[0:4], 8).eq(
                                    vcompress_source.word_select(
                                        vcompress_source_index, 8))
                            with m.Case(1):
                                m.d.sync += vregs[
                                    vcompress_vd + vcompress_dest_index[3:8]
                                ].word_select(vcompress_dest_index[0:3], 16).eq(
                                    vcompress_source.word_select(
                                        vcompress_source_index, 16))
                            with m.Case(2):
                                m.d.sync += vregs[
                                    vcompress_vd + vcompress_dest_index[2:8]
                                ].word_select(vcompress_dest_index[0:2], 32).eq(
                                    vcompress_source.word_select(
                                        vcompress_source_index, 32))
                        m.d.sync += vcompress_dest_index.eq(
                            vcompress_dest_index + 1)
                    m.d.sync += vcompress_source_index.eq(
                        vcompress_source_index + 1)
                with m.Else():
                    m.d.sync += [
                        vcompress_tail.eq(1),
                        vcompress_tail_index.eq(vcompress_dest_index),
                    ]
            with m.Else():
                with m.If(vcompress_vta &
                          (vcompress_tail_index < vcompress_vlmax)):
                    with m.Switch(vcompress_vsew):
                        with m.Case(0):
                            m.d.sync += vregs[
                                vcompress_vd + vcompress_tail_index[4:8]
                            ].word_select(vcompress_tail_index[0:4], 8).eq(0xFF)
                        with m.Case(1):
                            m.d.sync += vregs[
                                vcompress_vd + vcompress_tail_index[3:8]
                            ].word_select(vcompress_tail_index[0:3], 16).eq(0xFFFF)
                        with m.Case(2):
                            m.d.sync += vregs[
                                vcompress_vd + vcompress_tail_index[2:8]
                            ].word_select(vcompress_tail_index[0:2], 32).eq(0xFFFFFFFF)
                    m.d.sync += vcompress_tail_index.eq(
                        vcompress_tail_index + 1)
                with m.Else():
                    m.d.sync += [
                        vcompress_active.eq(0),
                        csr_vstart.eq(0),
                        IS.valid.eq(0),
                    ]


        # Global stall signal (very conservative in Part 1)
        stall = Signal()
        stall_front = Signal()  # Step11/12：前端停顿（包含依赖停顿）
        # Forward declarations for signals used before their main definition
        stall_dep_id2 = Signal()
        id2_dup_is = Signal()
        gc_fire = Signal()
        fence_active = Signal(reset=0)

        # ── GCSubsystem submodule ──────────────────────────
        m.submodules.gc = gc = GCSubsystem(
            core_id=self.core_id, gc_slots=self.gc_slots,
            rb_cache_ways=self.rb_cache_ways, rb_slots=self.rb_slots,
            wb_depth=self.wb_depth, mv_depth=self.mv_depth,
            wb_ptr_filter=self.wb_ptr_filter,
            wb_card_shift=self.wb_card_shift,
            wb_obj_shift=self.wb_obj_shift,
            wb_combine_depth=self.wb_combine_depth,
            gc_slots_bank_count=self.gc_slots_bank_count,
            gc_slots_bank_impl=self.gc_slots_bank_impl,
            rb_mode=self.rb_mode, debug=True,
        )
        fp_rm_required_issue = Signal()
        fp_rm_illegal_issue = Signal()
        fp_rm_required_id2 = Signal()
        fp_rm_illegal_id2 = Signal()
        m.d.comb += [
            fp_rm_required_issue.eq(
                ((IS.opcode == OP_FP) & (
                    (IS.funct7[2:7] == 0b00000) |
                    (IS.funct7[2:7] == 0b00001) |
                    (IS.funct7[2:7] == 0b00010) |
                    (IS.funct7[2:7] == 0b00011) |
                    (IS.funct7[2:7] == 0b01000) |
                    (IS.funct7[2:7] == 0b01011) |
                    (IS.funct7[2:7] == 0b11000) |
                    (IS.funct7[2:7] == 0b11010)
                )) |
                (IS.opcode == MADD) | (IS.opcode == MSUB) |
                (IS.opcode == NMSUB) | (IS.opcode == NMADD)
            ),
            fp_rm_illegal_issue.eq((fp_rm_required_issue & (
                (IS.funct3 == 0b101) | (IS.funct3 == 0b110) |
                ((IS.funct3 == 0b111) & (csr_frm >= 0b101))
            )) | ((IS.opcode == OP_FP) & self.enable_q &
                  (IS.funct7 == 0b0010011) & (IS.funct3 > 0b010)) |
                 ((IS.opcode == OP_FP) & self.enable_q &
                  (IS.funct7 == 0b0010111) & (IS.funct3 > 0b001)) |
                 ((IS.opcode == OP_FP) & self.enable_q &
                  (IS.funct7 == 0b1010011) & (IS.funct3 > 0b010)) |
                 ((IS.opcode == OP_FP) & self.enable_q &
                  (IS.funct7 == 0b1110011) &
                  ((IS.funct3 != 0b001) | (IS.rs2 != 0))) |
                 ((IS.opcode == OP_FP) & self.enable_q &
                  (IS.funct7 == 0b1101011) & (IS.rs2 > 1)) |
                 ((IS.opcode == OP_FP) & self.enable_q &
                  (IS.funct7 == 0b1100011) & (IS.rs2 > 1)) |
                 ((IS.opcode == OP_FP) & self.enable_q &
                  (IS.funct7 == 0b0100011) &
                  ~((IS.rs2 == 0) | ((IS.rs2 == 1) & self.enable_d))) |
                 ((IS.opcode == OP_FP) & self.enable_q &
                  (IS.funct7 == 0b0100001) & (IS.rs2 == 3) &
                  ~self.enable_d) |
                 ((IS.opcode == OP_FP) & self.enable_q &
                  (IS.funct7 == 0b0100000) & (IS.rs2 == 3) &
                  ~self.enable_f) |
                 ((IS.opcode == OP_FP) & self.enable_zfhmin & ~self.enable_zfh &
                  (IS.funct7[0:2] == 0b10) &
                  ~((IS.funct7 == 0b0100010) & (IS.rs2 == 0))) |
                 ((IS.opcode == OP_FP) & self.enable_zfh & (
                ((IS.funct7 == 0b0010010) & (IS.funct3 > 0b010)) |
                ((IS.funct7 == 0b0010110) &
                 (IS.funct3 > (0b011 if self.enable_zfa else 0b001))) |
                ((IS.funct7 == 0b1010010) &
                 ~((IS.funct3 <= 0b010) |
                   (self.enable_zfa &
                    ((IS.funct3 == 0b100) | (IS.funct3 == 0b101))))) |
                ((IS.funct7 == 0b0100010) &
                 ~(((IS.rs2 == 0) & self.enable_zfhmin) |
                   ((IS.rs2 == 1) & self.enable_d) |
                   (self.enable_zfa & ((IS.rs2 == 4) | (IS.rs2 == 5))))) |
                ((IS.funct7 == 0b1111010) &
                 (((IS.rs2 == 1) &
                   ((IS.funct3 != 0) | (not self.enable_zfa))) |
                  (IS.rs2 > 1)))
            ))),
            fp_rm_required_id2.eq(
                ((ID2.opcode == OP_FP) & (
                    (ID2.funct7[2:7] == 0b00000) |
                    (ID2.funct7[2:7] == 0b00001) |
                    (ID2.funct7[2:7] == 0b00010) |
                    (ID2.funct7[2:7] == 0b00011) |
                    (ID2.funct7[2:7] == 0b01000) |
                    (ID2.funct7[2:7] == 0b01011) |
                    (ID2.funct7[2:7] == 0b11000) |
                    (ID2.funct7[2:7] == 0b11010)
                )) |
                (ID2.opcode == MADD) | (ID2.opcode == MSUB) |
                (ID2.opcode == NMSUB) | (ID2.opcode == NMADD)
            ),
            fp_rm_illegal_id2.eq((fp_rm_required_id2 & (
                (ID2.funct3 == 0b101) | (ID2.funct3 == 0b110) |
                ((ID2.funct3 == 0b111) & (csr_frm >= 0b101))
            )) | ((ID2.opcode == OP_FP) & self.enable_q &
                  (ID2.funct7 == 0b0010011) & (ID2.funct3 > 0b010)) |
                 ((ID2.opcode == OP_FP) & self.enable_q &
                  (ID2.funct7 == 0b0010111) & (ID2.funct3 > 0b001)) |
                 ((ID2.opcode == OP_FP) & self.enable_q &
                  (ID2.funct7 == 0b1010011) & (ID2.funct3 > 0b010)) |
                 ((ID2.opcode == OP_FP) & self.enable_q &
                  (ID2.funct7 == 0b1110011) &
                  ((ID2.funct3 != 0b001) | (ID2.rs2 != 0))) |
                 ((ID2.opcode == OP_FP) & self.enable_q &
                  (ID2.funct7 == 0b1101011) & (ID2.rs2 > 1)) |
                 ((ID2.opcode == OP_FP) & self.enable_q &
                  (ID2.funct7 == 0b1100011) & (ID2.rs2 > 1)) |
                 ((ID2.opcode == OP_FP) & self.enable_q &
                  (ID2.funct7 == 0b0100011) &
                  ~((ID2.rs2 == 0) | ((ID2.rs2 == 1) & self.enable_d))) |
                 ((ID2.opcode == OP_FP) & self.enable_q &
                  (ID2.funct7 == 0b0100001) & (ID2.rs2 == 3) &
                  ~self.enable_d) |
                 ((ID2.opcode == OP_FP) & self.enable_q &
                  (ID2.funct7 == 0b0100000) & (ID2.rs2 == 3) &
                  ~self.enable_f) |
                 ((ID2.opcode == OP_FP) & self.enable_zfhmin & ~self.enable_zfh &
                  (ID2.funct7[0:2] == 0b10) &
                  ~((ID2.funct7 == 0b0100010) & (ID2.rs2 == 0))) |
                 ((ID2.opcode == OP_FP) & self.enable_zfh & (
                ((ID2.funct7 == 0b0010010) & (ID2.funct3 > 0b010)) |
                ((ID2.funct7 == 0b0010110) &
                 (ID2.funct3 > (0b011 if self.enable_zfa else 0b001))) |
                ((ID2.funct7 == 0b1010010) &
                 ~((ID2.funct3 <= 0b010) |
                   (self.enable_zfa &
                    ((ID2.funct3 == 0b100) | (ID2.funct3 == 0b101))))) |
                ((ID2.funct7 == 0b0100010) &
                 ~(((ID2.rs2 == 0) & self.enable_zfhmin) |
                   ((ID2.rs2 == 1) & self.enable_d) |
                   (self.enable_zfa & ((ID2.rs2 == 4) | (ID2.rs2 == 5))))) |
                ((ID2.funct7 == 0b1111010) &
                 (((ID2.rs2 == 1) &
                   ((ID2.funct3 != 0) | (not self.enable_zfa))) |
                  (ID2.rs2 > 1)))
            ))),
            gc.is_valid.eq(IS.valid),
            gc.is_opcode.eq(IS.opcode),
            gc.is_rd.eq(Mux(fp_rm_illegal_issue, 0, IS.rd)),
            gc.is_funct3.eq(IS.funct3),
            gc.is_rs1.eq(IS.rs1),
            gc.is_rs2.eq(IS.rs2),
            gc.id2_valid.eq(ID2.valid),
            gc.id2_rd.eq(Mux(fp_rm_illegal_id2, 0, ID2.rd)),
            gc.id2_is_gc.eq(ID2.is_gc),
            gc.id2_is_load.eq(ID2.is_load),
            gc.id2_opcode.eq(ID2.opcode),
            gc.mem1_valid.eq(MEM1.valid),
            # Floating-point payloads are raw IEEE bit patterns, not managed
            # object references. Multi-beat FSD/FSQ must also not enqueue one
            # write-barrier event per held MEM1 cycle.
            gc.mem1_is_store.eq(MEM1.is_store & (MEM1.opcode != STORE_FP)),
            gc.mem1_addr.eq(MEM1.mem_addr),
            gc.mem1_wdata.eq(MEM1.mem_wdata),
            gc.mem2_valid.eq(MEM2.valid),
            # Floating-point payloads are not managed object references and
            # must not consume read-barrier slots. Their architectural load
            # still uses the normal scoreboard and FPR writeback path.
            gc.mem2_is_load.eq(MEM2.is_load & (MEM2.opcode != LOAD_FP)),
            gc.mem2_rd.eq(MEM2.rd),
            gc.mem2_addr.eq(MEM2.mem_addr),
            gc.mem2_wb_data.eq(MEM2.wb_data),
            gc.mem2_wb_en.eq(MEM2.wb_en),
            gc.wb_valid.eq(WB.valid),
            gc.wb_is_load.eq(WB.is_load),
            gc.wb_rd.eq(WB.rd),
            gc.wb_wb_data.eq(WB.wb_data),
            gc.wb_wb_en.eq(WB.wb_en | WB.fp_wb_en),
            gc.ex1_valid.eq(EX1.valid),
            gc.ex1_wb_en.eq(EX1.wb_en),
            gc.ex1_rd.eq(EX1.rd),
            gc.ex1_wb_data.eq(EX1.wb_data),
            gc.ex2_valid.eq(EX2.valid),
            gc.ex2_wb_en.eq(EX2.wb_en),
            gc.ex2_rd.eq(EX2.rd),
            gc.ex2_wb_data.eq(EX2.wb_data),
            gc.mem1_valid2.eq(MEM1.valid),
            gc.mem1_wb_en.eq(MEM1.wb_en),
            gc.mem1_rd.eq(MEM1.rd),
            gc.mem1_wb_data.eq(MEM1.wb_data),
            gc.stall.eq(stall),
            gc.stall_dep_id2.eq(stall_dep_id2),
            gc.fence_active.eq(fence_active),
            gc.dmem_grant.eq(self.dmem_grant),
            gc.rb_inj_valid.eq(self.rb_inj_valid),
            gc.rb_inj_value.eq(self.rb_inj_value),
            gc.rb_inj_rd.eq(self.rb_inj_rd),
            gc.gc_enq_ready.eq(self.gc_enq_ready),
            gc.gc_rsp_valid.eq(self.gc_rsp_valid),
            gc.gc_rsp_tag.eq(self.gc_rsp_tag),
            gc.gc_rsp_rd.eq(self.gc_rsp_rd),
            gc.gc_rsp_data.eq(self.gc_rsp_data),
            gc.mv_cmd_ready.eq(self.mv_cmd_ready),
            gc.mv_rsp_valid.eq(self.mv_rsp_valid),
            gc.mv_rsp_tag.eq(self.mv_rsp_tag),
            gc.mv_rsp_rd.eq(self.mv_rsp_rd),
            gc.mv_rsp_data.eq(self.mv_rsp_data),
            gc.wb_enq_ready.eq(self.wb_enq_ready),
        ]
        # ── GC output signals (driven by GCSubsystem, consumed by pipeline) ──
        stall_rb = Signal(); m.d.comb += stall_rb.eq(gc.stall_rb)
        stall_store = Signal(); m.d.comb += stall_store.eq(gc.stall_store)
        stall_gc_order = Signal(); m.d.comb += stall_gc_order.eq(gc.stall_gc_order)
        stall_gc_issue = Signal(); m.d.comb += stall_gc_issue.eq(gc.stall_gc_issue)
        m.d.comb += gc_fire.eq(gc.gc_fire)
        gc_rsp_match = Signal(); m.d.comb += gc_rsp_match.eq(gc.gc_rsp_match)
        gc_rsp_match_idx = Signal(8); m.d.comb += gc_rsp_match_idx.eq(gc.gc_rsp_match_idx)
        pending_rd_mask = Signal(32); m.d.comb += pending_rd_mask.eq(gc.pending_rd_mask)
        match_found = Signal(); m.d.comb += match_found.eq(gc.match_found)
        mv_reloc_fire = Signal(); m.d.comb += mv_reloc_fire.eq(gc.mv_reloc_fire)
        is_gc_mv_reloc = Signal(); m.d.comb += is_gc_mv_reloc.eq(gc.is_gc_mv_reloc)
        mv_bp_valid = Signal(); m.d.comb += mv_bp_valid.eq(gc.mv_bp_valid)
        mv_bp_rd = Signal(5); m.d.comb += mv_bp_rd.eq(gc.mv_bp_rd)
        mv_bp_data = Signal(32); m.d.comb += mv_bp_data.eq(gc.mv_bp_data)
        cache_hit_fire = Signal(); m.d.comb += cache_hit_fire.eq(gc.cache_hit_fire)
        cache_hit_data = Signal(32); m.d.comb += cache_hit_data.eq(gc.cache_hit_data)
        m.d.comb += [
            self.gc_enq_valid.eq(gc.gc_enq_valid),
            self.gc_tag.eq(gc.gc_tag),
            self.gc_op.eq(gc.gc_op),
            self.gc_rd.eq(gc.gc_rd_out),
            self.gc_rs1.eq(gc.gc_rs1),
            self.gc_rs2.eq(gc.gc_rs2),
            self.gc_rsp_take.eq(gc.gc_rsp_take),
            self.wb_enq_valid.eq(gc.wb_enq_valid),
            self.wb_addr.eq(gc.wb_addr),
            self.wb_data.eq(gc.wb_data),
            self.mv_cmd_valid.eq(gc.mv_cmd_valid),
            self.mv_cmd_tag.eq(gc.mv_cmd_tag),
            self.mv_cmd_op.eq(gc.mv_cmd_op),
            self.mv_cmd_rd.eq(gc.mv_cmd_rd),
            self.mv_cmd_rs1.eq(gc.mv_cmd_rs1),
            self.mv_cmd_rs2.eq(gc.mv_cmd_rs2),
            self.rb_inj_ready.eq(gc.rb_inj_ready),
            self.mv_rsp_take.eq(gc.match_found & self.mv_rsp_valid),
        ]

        pc = Signal(32, reset=0)
        redirect = Signal()
        redirect_pc = Signal(32)
        zcmt_table_fetch = Signal()
        zcmt_table_addr = Signal(32)

        m.d.comb += [
            zcmt_table_fetch.eq(
                self.enable_zcmt & IS.valid & IS.compressed &
                (IS.opcode == JALR) & (IS.funct3 == 0b111)
            ),
            zcmt_table_addr.eq(csr_jvt + Cat(C(0, 2), IS.imm[0:8], C(0, 22))),
        ]

        m.d.comb += self.pc_dbg.eq(pc)

        # (GC slots, mv_tag_ctr, mv_bp moved into GCSubsystem)


        # (wbq output wiring moved into GCSubsystem — outputs driven via gc.wb_enq_valid etc.)

        # (mv_cmd mux moved into GCSubsystem — outputs driven via gc.mv_cmd_valid etc.)
        # Forwarded operands for GC/MV (driven from gc)
        gc_fwd_rs1 = Signal(32); m.d.comb += gc_fwd_rs1.eq(gc.gc_fwd_rs1)
        gc_fwd_rs2 = Signal(32); m.d.comb += gc_fwd_rs2.eq(gc.gc_fwd_rs2)

        # (RB pending table, cache, enqueue/fire/match/mv_rsp handling moved into GCSubsystem)

        # Flush on redirect
        flush_if = Signal()
        m.d.comb += flush_if.eq(redirect)

        # ----------------------
        # IF1: PC select, IMEM request
        # ----------------------
        m.d.comb += self.imem_addr.eq(Mux(
            zcmt_table_fetch, zcmt_table_addr,
            Mux(redirect, redirect_pc, pc),
        ))

        # pipeline register movement helper (simple)
        def step(src, dst, do_flush=False):
            with m.If(stall):
                pass
            with m.Elif(do_flush):
                m.d.sync += dst.valid.eq(0)
            with m.Else():
                m.d.sync += [
                    dst.valid.eq(src.valid),
                    dst.pc.eq(src.pc),
                    dst.insn.eq(src.insn),
                    dst.opcode.eq(src.opcode),
                    dst.rd.eq(src.rd),
                    dst.rs1.eq(src.rs1),
                    dst.rs2.eq(src.rs2),
                    dst.funct3.eq(src.funct3),
                    dst.funct7.eq(src.funct7),
                    dst.imm.eq(src.imm),
                    dst.rs1v.eq(src.rs1v),
                    dst.rs2v.eq(src.rs2v),
                    dst.is_load.eq(src.is_load),
                    dst.is_store.eq(src.is_store),
                    dst.is_branch.eq(src.is_branch),
                    dst.is_jal.eq(src.is_jal),
                    dst.is_fence.eq(src.is_fence),
                    dst.compressed.eq(src.compressed),
                    dst.is_gc.eq(src.is_gc),
                    dst.alu.eq(src.alu),
                    dst.mem_addr.eq(src.mem_addr),
                    dst.mem_wdata.eq(src.mem_wdata),
                    dst.fp_mem_wdata.eq(src.fp_mem_wdata),
                    dst.wb_en.eq(src.wb_en),
                    dst.wb_data.eq(src.wb_data),
                    dst.wb2_en.eq(src.wb2_en),
                    dst.wb2_rd.eq(src.wb2_rd),
                    dst.wb2_data.eq(src.wb2_data),
                    dst.fp_wb_en.eq(src.fp_wb_en),
                    dst.fp_wb_data.eq(src.fp_wb_data),
                    dst.fp_wb_q.eq(src.fp_wb_q),
                ]

        # ----------------------
        # IF stage progression
        # ----------------------
        with m.If(flush_if):
            m.d.sync += [
                IF1.valid.eq(0), IF2.valid.eq(0), IF3.valid.eq(0), IF4.valid.eq(0),
                ID1.valid.eq(0), ID2.valid.eq(0), IS.valid.eq(0),
            ]

        can_fetch = Signal()
        m.d.comb += can_fetch.eq(1)
        is_compressed = Signal(reset=0)

        with m.If(~stall_front & ~redirect):
            # Step10：让“第一条指令”也能生效。
            # 早期版本 IF2.valid 取自 IF1.valid（再延迟一拍），会导致：
            #   - reset 后第 1 拍取到的 insn0 带 valid=0（被当作气泡丢掉）
            #   - 下一拍 insn1 才开始 valid=1，于是看起来像“第二条指令先执行”
            # 对于研究用 CPU，我们直接把 IF2.valid 与 can_fetch 对齐。
            m.d.sync += [
                IF1.valid.eq(can_fetch),
                IF1.pc.eq(self.imem_addr),
            ]
            # CExpander: expand compressed instructions at IF2
            ce_half = Signal(16)
            if self.enable_c:
                m.d.comb += ce_half.eq(Mux(self.imem_addr[1], self.imem_rdata[16:32], self.imem_rdata[0:16]))
                ce = CExpander(
                    xlen=self.xlen,
                    enable_zcmop=self.enable_zcmop,
                    enable_zcmt=self.enable_zcmt,
                    enable_zcmp=self.enable_zcmp,
                )
                m.submodules.ce = ce
                m.d.comb += [ce.valid.eq(1), ce.insn16.eq(ce_half)]
                expanded_insn = Signal(32)
                m.d.comb += expanded_insn.eq(Mux(ce.is_compressed | self.imem_addr[1], ce.insn32, self.imem_rdata))
                m.d.comb += is_compressed.eq(ce.is_compressed)
            else:
                expanded_insn = self.imem_rdata
                m.d.comb += is_compressed.eq(0)

            m.d.sync += [
                IF2.valid.eq(can_fetch),
                # 重要：IF2 的 pc 必须与 insn 对齐。
                # 这里的 IMEM 是“组合读”，imem_rdata 对应的是本 cycle 的 imem_addr(pc)。
                # 如果写成 IF2.pc = IF1.pc，则会出现 pc/insn 错拍（pc 落后 1 拍），
                # 在无分支时看似还能跑，但会导致后续阶段字段错位，
                # 例如出现“load 数据正确但 rd 变成 0”这类离谱现象。
                IF2.pc.eq(self.imem_addr),
                IF2.insn.eq(expanded_insn),
                IF2.compressed.eq(is_compressed),
            ]
            # IF3/IF4：valid 跟随 IF2/IF3 推进，保证“valid=1 的那条”对应同拍的数据。
            m.d.sync += [
                IF3.valid.eq(IF2.valid), IF3.pc.eq(IF2.pc), IF3.insn.eq(IF2.insn),
                IF3.compressed.eq(IF2.compressed),
                IF4.valid.eq(IF3.valid), IF4.pc.eq(IF3.pc), IF4.insn.eq(IF3.insn),
                IF4.compressed.eq(IF3.compressed),
            ]

        with m.If((~stall_front) | redirect):
            with m.If(redirect):
                m.d.sync += pc.eq(redirect_pc)
            with m.Elif(can_fetch):
                m.d.sync += pc.eq(pc + Mux(is_compressed, C(2, self.xlen), C(4, self.xlen)))

        # ----------------------
        # ID1: basic decode fields
        # ----------------------
        with m.If(~stall_front & ~redirect):
            m.d.sync += [
                ID1.valid.eq(IF4.valid),
                ID1.pc.eq(IF4.pc),
                ID1.insn.eq(IF4.insn),
                ID1.compressed.eq(IF4.compressed),

                ID1.opcode.eq(IF4.insn[0:7]),
                ID1.rd.eq(IF4.insn[7:12]),
                ID1.funct3.eq(IF4.insn[12:15]),
                ID1.rs1.eq(IF4.insn[15:20]),
                ID1.rs2.eq(IF4.insn[20:25]),
                ID1.funct7.eq(IF4.insn[25:32]),
            ]

        # ----------------------
        # ID2: reg read + decode/classify + immediate
        # ----------------------
        # Step10 关键修复：
        #   早期版本用“ID2 寄存器旧值”在同一拍组合计算 is_load/imm，
        #   然后又在该拍把结果写回 ID2。这样会造成：
        #     - is_load/imm 永远落后一拍（对应上一条指令）
        #     - 甚至 imm_i 来自 ID1，而 imm_s/imm_b 来自 ID2，字段错拍混在一起
        #   现改为：全部基于 ID1（本拍已锁存的那条指令）组合计算，然后写入 ID2。
        with m.If(~stall_front & ~redirect):
            m.d.sync += [
                ID2.valid.eq(ID1.valid),
                ID2.pc.eq(ID1.pc),
                ID2.insn.eq(ID1.insn),
                ID2.compressed.eq(ID1.compressed),
                ID2.opcode.eq(ID1.opcode),
                ID2.rd.eq(ID1.rd),
                ID2.rs1.eq(ID1.rs1),
                ID2.rs2.eq(ID1.rs2),
                ID2.funct3.eq(ID1.funct3),
                ID2.funct7.eq(ID1.funct7),

                ID2.rs1v.eq(rreg(ID1.rs1)),
                ID2.rs2v.eq(rreg(ID1.rs2)),
            ]

        # classify（基于 ID1.opcode）
        is_load_d  = Signal()
        is_store_d = Signal()
        is_branch_d= Signal()
        is_jal_d   = Signal()
        is_fence_d = Signal()
        is_gc_d    = Signal()

        fp_load_f = Signal()
        fp_load_d = Signal()
        fp_load_q = Signal()
        fp_store_f = Signal()
        fp_store_d = Signal()
        fp_store_q = Signal()
        m.d.comb += [
            is_load_d.eq(
                (ID1.opcode == LOAD) |
                (self.enable_a & (ID1.opcode == AMO)) |
                fp_load_f | fp_load_d | fp_load_q
            ),
            is_store_d.eq(
                (ID1.opcode == STORE) |
                (self.enable_a & (ID1.opcode == AMO) & (ID1.funct7[2:7] != 0b00010)) |
                fp_store_f | fp_store_d | fp_store_q
            ),
            is_branch_d.eq(ID1.opcode == BRANCH),
            is_jal_d.eq(ID1.opcode == JAL),
            is_fence_d.eq(ID1.opcode == MISC_MEM),
            is_gc_d.eq(ID1.opcode == CUSTOM0),
            fp_load_f.eq((ID1.opcode == LOAD_FP) & (
                (self.enable_f & (ID1.funct3 == 0b010)) |
                (self.enable_zfhmin & ~self.use_finx & (ID1.funct3 == 0b001))
            )),
            fp_load_d.eq((self.enable_d) & (ID1.opcode == LOAD_FP) & (ID1.funct3 == 0b011)),
            fp_load_q.eq((self.enable_q) & (ID1.opcode == LOAD_FP) & (ID1.funct3 == 0b100)),
            fp_store_f.eq((ID1.opcode == STORE_FP) & (
                (self.enable_f & (ID1.funct3 == 0b010)) |
                (self.enable_zfhmin & ~self.use_finx & (ID1.funct3 == 0b001))
            )),
            fp_store_d.eq((self.enable_d) & (ID1.opcode == STORE_FP) & (ID1.funct3 == 0b011)),
            fp_store_q.eq((self.enable_q) & (ID1.opcode == STORE_FP) & (ID1.funct3 == 0b100)),
        ]

        # I-immediate (12 bits)
        imm_i_u = Signal(12)
        imm_i_d = Signal(self.xlen)
        m.d.comb += [
            imm_i_u.eq(ID1.insn[20:32]),
            imm_i_d.eq(sign_extend(imm_i_u, 12, self.xlen)),
        ]

        # U-immediate (20 bits), shifted left by 12
        imm_u_u = Signal(20)
        imm_u_d = Signal(self.xlen)
        m.d.comb += [
            imm_u_u.eq(ID1.insn[12:32]),
            imm_u_d.eq(sign_extend(Cat(C(0, 12), imm_u_u), 32, self.xlen)),
        ]

        # S-immediate (12 bits)
        imm_s_u = Signal(12)
        imm_s_d = Signal(self.xlen)
        m.d.comb += [
            imm_s_u.eq(Cat(ID1.insn[7:12], ID1.insn[25:32])),
            imm_s_d.eq(sign_extend(imm_s_u, 12, self.xlen)),
        ]

        # B-immediate (13 bits, includes bit0=0)
        imm_b_u = Signal(13)
        imm_b_d = Signal(self.xlen)
        m.d.comb += [
            imm_b_u.eq(Cat(C(0, 1), ID1.insn[8:12], ID1.insn[25:31], ID1.insn[7:8], ID1.insn[31:32])),
            imm_b_d.eq(sign_extend(imm_b_u, 13, self.xlen)),
        ]

        # J-immediate (21 bits, includes bit0=0)
        imm_j_u = Signal(21)
        imm_j_d = Signal(self.xlen)
        m.d.comb += [
            imm_j_u.eq(Cat(C(0, 1), ID1.insn[21:31], ID1.insn[20:21], ID1.insn[12:20], ID1.insn[31:32])),
            imm_j_d.eq(sign_extend(imm_j_u, 21, self.xlen)),
        ]

        sel_imm_d = Signal(self.xlen)
        m.d.comb += sel_imm_d.eq(
            Mux(
                is_store_d,
                imm_s_d,
                Mux(
                    is_branch_d,
                    imm_b_d,
                    Mux(
                        (ID1.opcode == LUI) | (ID1.opcode == AUIPC),
                        imm_u_d,
                        Mux(
                            is_jal_d,
                            imm_j_d,
                            imm_i_d,
                        ),
                    ),
                ),
            )
        )

        with m.If(~stall_front & ~redirect):
            m.d.sync += [
                ID2.imm.eq(sel_imm_d),
                ID2.is_load.eq(is_load_d),
                ID2.is_store.eq(is_store_d),
                ID2.is_branch.eq(is_branch_d),
                ID2.is_jal.eq(is_jal_d),
                ID2.is_fence.eq(is_fence_d),
                ID2.is_gc.eq(is_gc_d),
            ]

            # (IS ← ID2 moved to backend ~stall block with duplication guard)

            # Step13: if ID2 is a duplicate of IS, clear ID2 to prevent
            # the same instruction from being injected twice.
            with m.If(id2_dup_is):
                m.d.sync += ID2.valid.eq(0)

        # ----------------------
        # Step11/12：scoreboard 依赖阻塞（decode）
        # ----------------------
        # 关键坑（Step12 修复点）：
        #   如果只在 ID2 上做 hazard 检查，会出现“1-cycle hole”：
        #   某条依赖指令在进入 ID2 的那个时钟沿就把 rs1v 锁存了（旧值），
        #   hazard 只能在下一拍才检测到，已经来不及。
        # 因此我们做两级检查：
        #   - stall_dep_id1：基于 ID1（即‘下一拍将进入 ID2 的那条’）提前拦截，避免锁存旧值
        #   - stall_dep_id2：保底检查（若某条指令已在 ID2 中仍不应发射，则阻止其进入 IS）

        # ---- 1) ID1 前瞻检查：阻止进入 ID2 ----
        uses_rs1_id1 = Signal()
        uses_rs2_id1 = Signal()
        writes_rd_id1 = Signal()
        fp_int_src_id1 = Signal()
        fp_int_dst_id1 = Signal()
        fp_int_src_id2 = Signal()
        fp_int_dst_id2 = Signal()
        m.d.comb += [
            fp_int_src_id1.eq((ID1.opcode == OP_FP) & (
                ((ID1.funct7 == 0b1111000) & (ID1.rs2 == 0)) |
                (self.enable_zfhmin & (ID1.funct7 == 0b1111010) & (ID1.rs2 == 0)) |
                (ID1.funct7 == 0b1101000) |
                (ID1.funct7 == 0b1101001) |
                (self.enable_zfh & (ID1.funct7 == 0b1101010)) |
                (self.enable_zfa & (ID1.funct7 == 0b1011001))
            )),
            fp_int_dst_id1.eq((ID1.opcode == OP_FP) & (
                (ID1.funct7 == 0b1100000) |
                (ID1.funct7 == 0b1100001) |
                (self.enable_zfh & (ID1.funct7 == 0b1100010)) |
                (ID1.funct7 == 0b1010000) |
                (ID1.funct7 == 0b1010001) |
                (self.enable_zfh & (ID1.funct7 == 0b1010010)) |
                (ID1.funct7 == 0b1110000) |
                (ID1.funct7 == 0b1110001) |
                (self.enable_zfhmin & (ID1.funct7 == 0b1110010))
            )),
            fp_int_src_id2.eq((ID2.opcode == OP_FP) & (
                ((ID2.funct7 == 0b1111000) & (ID2.rs2 == 0)) |
                (self.enable_zfhmin & (ID2.funct7 == 0b1111010) & (ID2.rs2 == 0)) |
                (ID2.funct7 == 0b1101000) |
                (ID2.funct7 == 0b1101001) |
                (self.enable_zfh & (ID2.funct7 == 0b1101010)) |
                (self.enable_zfa & (ID2.funct7 == 0b1011001))
            )),
            fp_int_dst_id2.eq((ID2.opcode == OP_FP) & (
                (ID2.funct7 == 0b1100000) |
                (ID2.funct7 == 0b1100001) |
                (self.enable_zfh & (ID2.funct7 == 0b1100010)) |
                (ID2.funct7 == 0b1010000) |
                (ID2.funct7 == 0b1010001) |
                (self.enable_zfh & (ID2.funct7 == 0b1010010)) |
                (ID2.funct7 == 0b1110000) |
                (ID2.funct7 == 0b1110001) |
                (self.enable_zfhmin & (ID2.funct7 == 0b1110010))
            )),
        ]
        base_rs1_id1 = BaseRS1UsageControl()
        m.submodules.base_rs1_id1 = base_rs1_id1
        base_rd_id1 = BaseRDWriteControl()
        m.submodules.base_rd_id1 = base_rd_id1
        m.d.comb += [
            base_rs1_id1.valid.eq(ID1.valid),
            base_rs1_id1.is_jal.eq(is_jal_d),
            base_rs1_id1.is_fence.eq(is_fence_d),
            base_rd_id1.opcode.eq(ID1.opcode),
            base_rd_id1.integer_load.eq(is_load_d & ~(fp_load_f | fp_load_d)),
            base_rd_id1.is_jal.eq(is_jal_d),
            base_rd_id1.enable_a.eq(self.enable_a),
            uses_rs1_id1.eq(base_rs1_id1.uses_rs1 &
                ~(self.enable_v & (ID1.opcode == OP_V) & (ID1.funct3 == 0b111) &
                  (ID1.insn[30:32] == 0b11)) &
                ~(self.enable_v & (ID1.opcode == OP_V) & (ID1.funct3 == 0b011) &
                  (ID1.insn[26:32] == 0x27)) &
                ~(self.enable_v & (ID1.opcode == OP_V) & (ID1.insn[26:32] == 0x17) &
                  ((ID1.funct3 == 0b000) | (ID1.funct3 == 0b011))) &
                ~(self.enable_v & (ID1.opcode == OP_V) &
                  (((ID1.insn[26:32] == 0x10) &
                    ((ID1.funct3 == 0b001) | (ID1.funct3 == 0b101))) |
                   ((ID1.insn[26:32] == 0x17) & (ID1.funct3 == 0b101)))) &
                ~(self.enable_v & (ID1.opcode == OP_V) &
                  (ID1.insn[26:32] == 0x13) & (ID1.funct3 == 0b001) &
                  (ID1.rs1 == 0b10000)) &
                ~(self.enable_v & (ID1.opcode == OP_V) &
                  ((ID1.insn[26:32] == 0x0E) | (ID1.insn[26:32] == 0x0F)) &
                  (ID1.funct3 == 0b101)) &
                ~(self.enable_v & (ID1.opcode == OP_V) &
                  (ID1.insn[26:32] >= 0x08) & (ID1.insn[26:32] <= 0x0A) &
                  ((ID1.funct3 == 0b001) | (ID1.funct3 == 0b101))) &
                ~(self.enable_v & (ID1.opcode == OP_V) &
                  ((ID1.insn[26:32] == 0x04) | (ID1.insn[26:32] == 0x06)) &
                  ((ID1.funct3 == 0b001) | (ID1.funct3 == 0b101))) &
                ~(self.enable_v & (ID1.opcode == OP_V) &
                  (((ID1.insn[26:32] == 0x18) | (ID1.insn[26:32] == 0x19) |
                    (ID1.insn[26:32] == 0x1B) | (ID1.insn[26:32] == 0x1C)) &
                   ((ID1.funct3 == 0b001) | (ID1.funct3 == 0b101)) |
                   ((ID1.insn[26:32] == 0x1D) | (ID1.insn[26:32] == 0x1F)) &
                   (ID1.funct3 == 0b101))) &
                ~(self.enable_v & (ID1.opcode == OP_V) &
                  ((ID1.insn[26:32] == 0x00) | (ID1.insn[26:32] == 0x02) |
                   (ID1.insn[26:32] == 0x03) | (ID1.insn[26:32] == 0x09) |
                   (ID1.insn[26:32] == 0x0A) | (ID1.insn[26:32] == 0x0B) |
                   (ID1.insn[26:32] == 0x25) | (ID1.insn[26:32] == 0x28) |
                   (ID1.insn[26:32] == 0x29) | (ID1.insn[26:32] == 0x2A) |
                   (ID1.insn[26:32] == 0x2B)) &
                  ((ID1.funct3 == 0b000) | (ID1.funct3 == 0b011))) &
                ~(self.enable_v & (ID1.opcode == OP_V) &
                  ((ID1.insn[26:32] == 0x04) | (ID1.insn[26:32] == 0x05) |
                   (ID1.insn[26:32] == 0x06) | (ID1.insn[26:32] == 0x07)) &
                  (ID1.funct3 == 0b000)) &
                ~(self.enable_v & (ID1.opcode == OP_V) &
                  (ID1.insn[26:32] >= 0x08) & (ID1.insn[26:32] <= 0x0B) &
                  (ID1.funct3 == 0b010)) &
                ~(self.enable_v & (ID1.opcode == OP_V) &
                  (ID1.insn[26:32] >= 0x18) & (ID1.insn[26:32] <= 0x1F) &
                  ((ID1.funct3 == 0b000) | (ID1.funct3 == 0b011))) &
                ~(self.enable_v & (ID1.opcode == OP_V) &
                  (ID1.insn[26:32] >= 0x20) & (ID1.insn[26:32] <= 0x23) &
                  ((ID1.funct3 == 0b000) | (ID1.funct3 == 0b011))) &
                ~(self.enable_v & (ID1.opcode == OP_V) &
                  (ID1.insn[26:32] >= 0x20) & (ID1.insn[26:32] <= 0x23) &
                  (ID1.funct3 == 0b010)) &
                ~(self.enable_v & (ID1.opcode == OP_V) &
                  (ID1.insn[26:32] >= 0x24) & (ID1.insn[26:32] <= 0x27) &
                  (ID1.funct3 == 0b010)) &
                ~(self.enable_v & (ID1.opcode == OP_V) &
                  ((ID1.insn[26:32] == 0x38) | (ID1.insn[26:32] == 0x3A) |
                   (ID1.insn[26:32] == 0x3B)) & (ID1.funct3 == 0b010)) &
                ~(self.enable_v & (ID1.opcode == OP_V) &
                  (ID1.insn[26:32] >= 0x3C) & (ID1.insn[26:32] <= 0x3F) &
                  (ID1.funct3 == 0b010)) &
                ~(self.enable_v & (ID1.opcode == OP_V) &
                  (ID1.insn[26:32] >= 0x30) & (ID1.insn[26:32] <= 0x37) &
                  (ID1.funct3 == 0b010)) &
                ~(self.enable_v & (ID1.opcode == OP_V) &
                  ((ID1.insn[26:32] == 0x2C) | (ID1.insn[26:32] == 0x2D) |
                   (ID1.insn[26:32] == 0x2E) | (ID1.insn[26:32] == 0x2F)) &
                  ((ID1.funct3 == 0b000) | (ID1.funct3 == 0b011))) &
                ~(self.enable_v & (ID1.opcode == OP_V) &
                  ((ID1.insn[26:32] == 0x29) | (ID1.insn[26:32] == 0x2B) |
                   (ID1.insn[26:32] == 0x2D) | (ID1.insn[26:32] == 0x2F)) &
                  (ID1.funct3 == 0b010)) &
                ~(self.enable_v & (ID1.opcode == OP_V) &
                  (ID1.insn[26:32] == 0x27) & (ID1.funct3 == 0b000)) &
                ~(self.enable_v & (ID1.opcode == OP_V) &
                  (ID1.insn[26:32] == 0x14) & (ID1.funct3 == 0b010) &
                  (ID1.rs1 == 0b10001) & (ID1.rs2 == 0)) &
                ~(self.enable_v & (ID1.opcode == OP_V) &
                  (ID1.insn[26:32] == 0x14) & (ID1.funct3 == 0b010) &
                  (ID1.rs1 == 0b10000)) &
                ~(self.enable_v & (ID1.opcode == OP_V) &
                  (ID1.insn[26:32] == 0x10) & (ID1.funct3 == 0b010) &
                  ((ID1.rs1 == 0b10000) | (ID1.rs1 == 0b10001))) &
                (1 if self.use_finx else
                 ~(((ID1.opcode == OP_FP) & ~fp_int_src_id1) |
                   (ID1.opcode == MADD) | (ID1.opcode == MSUB) |
                   (ID1.opcode == NMSUB) | (ID1.opcode == NMADD)))),
            uses_rs2_id1.eq(ID1.valid & ((ID1.opcode == OP) | is_store_d | is_branch_d | is_gc_d |
                (self.enable_zcmp & ID1.compressed & (ID1.opcode == JALR) & (ID1.funct3 == 0b110)) |
                (self.enable_zfa & (ID1.opcode == OP_FP) & (ID1.funct7 == 0b1011001)) |
                (self.enable_v & (ID1.opcode == OP_V) & (ID1.funct3 == 0b111) &
                 (ID1.funct7 == 0b1000000)) |
                (self.use_finx & (ID1.opcode == OP_FP)) |
                (self.enable_a & (ID1.opcode == AMO))) & ~(fp_store_f | fp_store_d)),
            writes_rd_id1.eq(ID1.valid & (ID1.rd != 0) & (
                base_rd_id1.writes_rd | is_gc_d |
                (self.enable_v & (ID1.opcode == OP_V) & (ID1.funct3 == 0b111) &
                 ((ID1.insn[31] == 0) | (ID1.insn[30:32] == 0b11) |
                  (ID1.funct7 == 0b1000000))) |
                (self.enable_v & (ID1.opcode == OP_V) & (ID1.funct3 == 0b010) &
                 (ID1.funct7 == 0x21) & (ID1.rs1 == 0)) |
                (self.enable_v & (ID1.opcode == OP_V) &
                 (ID1.insn[26:32] == 0x10) & (ID1.funct3 == 0b010) &
                 ((ID1.rs1 == 0b10000) | (ID1.rs1 == 0b10001))) |
                fp_int_dst_id1 |
                (self.use_finx & (ID1.opcode == OP_FP)) |
                ((self.enable_f & (self.xlen >= 64)) & (ID1.opcode == OP_FP_32))
            )),
        ]
        # ---- 2) ID2 保底检查：阻止进入 IS ----
        uses_rs1_id2 = Signal()
        uses_rs2_id2 = Signal()
        writes_rd_id2 = Signal()
        base_rs1_id2 = BaseRS1UsageControl()
        m.submodules.base_rs1_id2 = base_rs1_id2
        base_rd_id2 = BaseRDWriteControl()
        m.submodules.base_rd_id2 = base_rd_id2
        m.d.comb += [
            base_rs1_id2.valid.eq(ID2.valid),
            base_rs1_id2.is_jal.eq(ID2.is_jal),
            base_rs1_id2.is_fence.eq(ID2.is_fence),
            base_rd_id2.opcode.eq(ID2.opcode),
            base_rd_id2.integer_load.eq(ID2.is_load & ~(ID2.opcode == LOAD_FP)),
            base_rd_id2.is_jal.eq(ID2.is_jal),
            base_rd_id2.enable_a.eq(self.enable_a),
            uses_rs1_id2.eq(base_rs1_id2.uses_rs1 &
                ~(self.enable_v & (ID2.opcode == OP_V) & (ID2.funct3 == 0b111) &
                  (ID2.insn[30:32] == 0b11)) &
                ~(self.enable_v & (ID2.opcode == OP_V) & (ID2.funct3 == 0b011) &
                  (ID2.insn[26:32] == 0x27)) &
                ~(self.enable_v & (ID2.opcode == OP_V) & (ID2.insn[26:32] == 0x17) &
                  ((ID2.funct3 == 0b000) | (ID2.funct3 == 0b011))) &
                ~(self.enable_v & (ID2.opcode == OP_V) &
                  (((ID2.insn[26:32] == 0x10) &
                    ((ID2.funct3 == 0b001) | (ID2.funct3 == 0b101))) |
                   ((ID2.insn[26:32] == 0x17) & (ID2.funct3 == 0b101)))) &
                ~(self.enable_v & (ID2.opcode == OP_V) &
                  (ID2.insn[26:32] == 0x13) & (ID2.funct3 == 0b001) &
                  (ID2.rs1 == 0b10000)) &
                ~(self.enable_v & (ID2.opcode == OP_V) &
                  ((ID2.insn[26:32] == 0x0E) | (ID2.insn[26:32] == 0x0F)) &
                  (ID2.funct3 == 0b101)) &
                ~(self.enable_v & (ID2.opcode == OP_V) &
                  (ID2.insn[26:32] >= 0x08) & (ID2.insn[26:32] <= 0x0A) &
                  ((ID2.funct3 == 0b001) | (ID2.funct3 == 0b101))) &
                ~(self.enable_v & (ID2.opcode == OP_V) &
                  ((ID2.insn[26:32] == 0x04) | (ID2.insn[26:32] == 0x06)) &
                  ((ID2.funct3 == 0b001) | (ID2.funct3 == 0b101))) &
                ~(self.enable_v & (ID2.opcode == OP_V) &
                  (((ID2.insn[26:32] == 0x18) | (ID2.insn[26:32] == 0x19) |
                    (ID2.insn[26:32] == 0x1B) | (ID2.insn[26:32] == 0x1C)) &
                   ((ID2.funct3 == 0b001) | (ID2.funct3 == 0b101)) |
                   ((ID2.insn[26:32] == 0x1D) | (ID2.insn[26:32] == 0x1F)) &
                   (ID2.funct3 == 0b101))) &
                ~(self.enable_v & (ID2.opcode == OP_V) &
                  ((ID2.insn[26:32] == 0x00) | (ID2.insn[26:32] == 0x02) |
                   (ID2.insn[26:32] == 0x03) | (ID2.insn[26:32] == 0x09) |
                   (ID2.insn[26:32] == 0x0A) | (ID2.insn[26:32] == 0x0B) |
                   (ID2.insn[26:32] == 0x25) | (ID2.insn[26:32] == 0x28) |
                   (ID2.insn[26:32] == 0x29) | (ID2.insn[26:32] == 0x2A) |
                   (ID2.insn[26:32] == 0x2B)) &
                  ((ID2.funct3 == 0b000) | (ID2.funct3 == 0b011))) &
                ~(self.enable_v & (ID2.opcode == OP_V) &
                  ((ID2.insn[26:32] == 0x04) | (ID2.insn[26:32] == 0x05) |
                   (ID2.insn[26:32] == 0x06) | (ID2.insn[26:32] == 0x07)) &
                  (ID2.funct3 == 0b000)) &
                ~(self.enable_v & (ID2.opcode == OP_V) &
                  (ID2.insn[26:32] >= 0x08) & (ID2.insn[26:32] <= 0x0B) &
                  (ID2.funct3 == 0b010)) &
                ~(self.enable_v & (ID2.opcode == OP_V) &
                  (ID2.insn[26:32] >= 0x18) & (ID2.insn[26:32] <= 0x1F) &
                  ((ID2.funct3 == 0b000) | (ID2.funct3 == 0b011))) &
                ~(self.enable_v & (ID2.opcode == OP_V) &
                  (ID2.insn[26:32] >= 0x20) & (ID2.insn[26:32] <= 0x23) &
                  ((ID2.funct3 == 0b000) | (ID2.funct3 == 0b011))) &
                ~(self.enable_v & (ID2.opcode == OP_V) &
                  (ID2.insn[26:32] >= 0x20) & (ID2.insn[26:32] <= 0x23) &
                  (ID2.funct3 == 0b010)) &
                ~(self.enable_v & (ID2.opcode == OP_V) &
                  (ID2.insn[26:32] >= 0x24) & (ID2.insn[26:32] <= 0x27) &
                  (ID2.funct3 == 0b010)) &
                ~(self.enable_v & (ID2.opcode == OP_V) &
                  ((ID2.insn[26:32] == 0x38) | (ID2.insn[26:32] == 0x3A) |
                   (ID2.insn[26:32] == 0x3B)) & (ID2.funct3 == 0b010)) &
                ~(self.enable_v & (ID2.opcode == OP_V) &
                  (ID2.insn[26:32] >= 0x3C) & (ID2.insn[26:32] <= 0x3F) &
                  (ID2.funct3 == 0b010)) &
                ~(self.enable_v & (ID2.opcode == OP_V) &
                  (ID2.insn[26:32] >= 0x30) & (ID2.insn[26:32] <= 0x37) &
                  (ID2.funct3 == 0b010)) &
                ~(self.enable_v & (ID2.opcode == OP_V) &
                  ((ID2.insn[26:32] == 0x2C) | (ID2.insn[26:32] == 0x2D) |
                   (ID2.insn[26:32] == 0x2E) | (ID2.insn[26:32] == 0x2F)) &
                  ((ID2.funct3 == 0b000) | (ID2.funct3 == 0b011))) &
                ~(self.enable_v & (ID2.opcode == OP_V) &
                  ((ID2.insn[26:32] == 0x29) | (ID2.insn[26:32] == 0x2B) |
                   (ID2.insn[26:32] == 0x2D) | (ID2.insn[26:32] == 0x2F)) &
                  (ID2.funct3 == 0b010)) &
                ~(self.enable_v & (ID2.opcode == OP_V) &
                  (ID2.insn[26:32] == 0x27) & (ID2.funct3 == 0b000)) &
                ~(self.enable_v & (ID2.opcode == OP_V) &
                  (ID2.insn[26:32] == 0x14) & (ID2.funct3 == 0b010) &
                  (ID2.rs1 == 0b10001) & (ID2.rs2 == 0)) &
                ~(self.enable_v & (ID2.opcode == OP_V) &
                  (ID2.insn[26:32] == 0x14) & (ID2.funct3 == 0b010) &
                  (ID2.rs1 == 0b10000)) &
                ~(self.enable_v & (ID2.opcode == OP_V) &
                  (ID2.insn[26:32] == 0x10) & (ID2.funct3 == 0b010) &
                  ((ID2.rs1 == 0b10000) | (ID2.rs1 == 0b10001))) &
                (1 if self.use_finx else
                 ~(((ID2.opcode == OP_FP) & ~fp_int_src_id2) |
                   (ID2.opcode == MADD) | (ID2.opcode == MSUB) |
                   (ID2.opcode == NMSUB) | (ID2.opcode == NMADD)))),
            uses_rs2_id2.eq(ID2.valid & ((ID2.opcode == OP) | ID2.is_store | ID2.is_branch | ID2.is_gc |
                (self.enable_zcmp & ID2.compressed & (ID2.opcode == JALR) & (ID2.funct3 == 0b110)) |
                (self.enable_zfa & (ID2.opcode == OP_FP) & (ID2.funct7 == 0b1011001)) |
                (self.enable_v & (ID2.opcode == OP_V) & (ID2.funct3 == 0b111) &
                 (ID2.funct7 == 0b1000000)) |
                (self.use_finx & (ID2.opcode == OP_FP))) &
                ~(ID2.opcode == STORE_FP)),
            writes_rd_id2.eq(ID2.valid & (ID2.rd != 0) & (
                base_rd_id2.writes_rd |
                (self.enable_v & (ID2.opcode == OP_V) & (ID2.funct3 == 0b111) &
                 ((ID2.insn[31] == 0) | (ID2.insn[30:32] == 0b11) |
                  (ID2.funct7 == 0b1000000))) |
                (self.enable_v & (ID2.opcode == OP_V) & (ID2.funct3 == 0b010) &
                 (ID2.funct7 == 0x21) & (ID2.rs1 == 0)) |
                (self.enable_v & (ID2.opcode == OP_V) &
                 (ID2.insn[26:32] == 0x10) & (ID2.funct3 == 0b010) &
                 ((ID2.rs1 == 0b10000) | (ID2.rs1 == 0b10001))) |
                ID2.is_gc |
                fp_int_dst_id2 |
                (self.use_finx & (ID2.opcode == OP_FP)) |
                ((self.enable_f & (self.xlen >= 64)) & (ID2.opcode == OP_FP_32))
            )),
        ]
        haz_rs1_id2 = Signal()
        haz_rs2_id2 = Signal()
        haz_waw_id2 = Signal()
        # Step13：识别“ID2 与 IS 是同一条指令的重复拷贝”
        # ----------------------------------------------
        # 当前端因为依赖而冻结时，ID2 可能被卡住，IS 仍在推进，
        # 导致同一条指令同时存在于 IS 和 ID2（pc 相同）。
        # 这种重复拷贝不应再触发 hazard/stall，否则会把自己卡死。
        # Step77：pending_clr 在同一周期清除 pending，hazard 检查应无视该位。
        # ----------------------------------------------------
        m.d.comb += id2_dup_is.eq(ID2.valid & IS.valid & (ID2.pc == IS.pc))
        pending_visible_mask = Signal(32)
        pending_clear_mask = Signal(32)
        pending_mask_control = PendingMaskControl(clear_ports=3)
        m.submodules.pending_mask_control = pending_mask_control
        m.d.comb += [
            pending_mask_control.pending_mask.eq(pending_rd_mask),
            pending_mask_control.clear_valid[0].eq(gc_rsp_match),
            pending_mask_control.clear_rd[0].eq(self.gc_rsp_rd),
            pending_mask_control.clear_valid[1].eq(match_found),
            pending_mask_control.clear_rd[1].eq(mv_bp_rd),
            pending_mask_control.clear_valid[2].eq(cache_hit_fire),
            pending_mask_control.clear_rd[2].eq(MEM2.rd),
            pending_clear_mask.eq(pending_mask_control.clear_mask),
            pending_visible_mask.eq(pending_mask_control.visible_mask),
        ]
        pending_haz_id2 = PendingRegisterHazard()
        m.submodules.pending_haz_id2 = pending_haz_id2
        m.d.comb += [
            pending_haz_id2.uses_rs1.eq(uses_rs1_id2),
            pending_haz_id2.uses_rs2.eq(uses_rs2_id2),
            pending_haz_id2.writes_rd.eq(writes_rd_id2),
            pending_haz_id2.rs1.eq(ID2.rs1),
            pending_haz_id2.rs2.eq(ID2.rs2),
            pending_haz_id2.rd.eq(ID2.rd),
            pending_haz_id2.pending_mask.eq(pending_visible_mask),
            haz_rs1_id2.eq(pending_haz_id2.rs1_hazard),
            haz_rs2_id2.eq(pending_haz_id2.rs2_hazard),
            haz_waw_id2.eq(pending_haz_id2.waw_hazard),
        ]
        fp_store_haz_id1 = Signal()
        fp_store_haz_id2 = Signal()
        dep_stall_id2 = DependencyStallControl()
        m.submodules.dep_stall_id2 = dep_stall_id2
        fp_haz_id1_ctrl = FPStoreHazardControl(
            slots=7, enable_h=self.enable_zfhmin, enable_f=self.enable_f,
            enable_d=self.enable_d, enable_q=self.enable_q,
            use_finx=self.use_finx)
        fp_haz_id2_ctrl = FPStoreHazardControl(
            slots=6, enable_h=self.enable_zfhmin, enable_f=self.enable_f,
            enable_d=self.enable_d, enable_q=self.enable_q,
            use_finx=self.use_finx)
        m.submodules.fp_haz_id1_ctrl = fp_haz_id1_ctrl
        m.submodules.fp_haz_id2_ctrl = fp_haz_id2_ctrl
        fp_id1_stages = (ID2, IS, EX1, EX2, MEM1, MEM2, WB)
        fp_id2_stages = (IS, EX1, EX2, MEM1, MEM2, WB)
        m.d.comb += [
            fp_haz_id1_ctrl.store_valid.eq(
                ID1.valid & (ID1.opcode == STORE_FP)),
            fp_haz_id1_ctrl.store_funct3.eq(ID1.funct3),
            fp_haz_id1_ctrl.store_rs2.eq(ID1.rs2),
            fp_haz_id2_ctrl.store_valid.eq(
                ID2.valid & (ID2.opcode == STORE_FP)),
            fp_haz_id2_ctrl.store_funct3.eq(ID2.funct3),
            fp_haz_id2_ctrl.store_rs2.eq(ID2.rs2),
            fp_store_haz_id1.eq(fp_haz_id1_ctrl.hazard),
            fp_store_haz_id2.eq(fp_haz_id2_ctrl.hazard),
            dep_stall_id2.rs1_hazard.eq(haz_rs1_id2),
            dep_stall_id2.rs2_hazard.eq(haz_rs2_id2),
            dep_stall_id2.waw_hazard.eq(haz_waw_id2),
            dep_stall_id2.include_waw.eq(0),
            dep_stall_id2.suppress_integer.eq(id2_dup_is),
            dep_stall_id2.fp_store_hazard.eq(fp_store_haz_id2),
            stall_dep_id2.eq(dep_stall_id2.stall),
        ]
        for index, stage in enumerate(fp_id1_stages):
            m.d.comb += [
                fp_haz_id1_ctrl.load_valid[index].eq(
                    stage.valid & (stage.opcode == LOAD_FP)),
                fp_haz_id1_ctrl.load_funct3[index].eq(stage.funct3),
                fp_haz_id1_ctrl.load_rd[index].eq(stage.rd),
            ]
        for index, stage in enumerate(fp_id2_stages):
            m.d.comb += [
                fp_haz_id2_ctrl.load_valid[index].eq(
                    stage.valid & (stage.opcode == LOAD_FP)),
                fp_haz_id2_ctrl.load_funct3[index].eq(stage.funct3),
                fp_haz_id2_ctrl.load_rd[index].eq(stage.rd),
            ]

        haz_rs1_id1 = Signal()
        haz_rs2_id1 = Signal()
        haz_waw_id1 = Signal()
        pending_haz_id1 = PendingRegisterHazard()
        m.submodules.pending_haz_id1 = pending_haz_id1
        m.d.comb += [
            pending_haz_id1.uses_rs1.eq(uses_rs1_id1),
            pending_haz_id1.uses_rs2.eq(uses_rs2_id1),
            pending_haz_id1.writes_rd.eq(writes_rd_id1),
            pending_haz_id1.rs1.eq(ID1.rs1),
            pending_haz_id1.rs2.eq(ID1.rs2),
            pending_haz_id1.rd.eq(ID1.rd),
            pending_haz_id1.pending_mask.eq(pending_visible_mask),
            haz_rs1_id1.eq(pending_haz_id1.rs1_hazard),
            haz_rs2_id1.eq(pending_haz_id1.rs2_hazard),
            haz_waw_id1.eq(pending_haz_id1.waw_hazard),
        ]
        stall_dep_id1 = Signal()
        dep_stall_id1 = DependencyStallControl()
        m.submodules.dep_stall_id1 = dep_stall_id1
        m.d.comb += [
            dep_stall_id1.rs1_hazard.eq(haz_rs1_id1),
            dep_stall_id1.rs2_hazard.eq(haz_rs2_id1),
            dep_stall_id1.waw_hazard.eq(haz_waw_id1),
            dep_stall_id1.include_waw.eq(1),
            dep_stall_id1.suppress_integer.eq(0),
            dep_stall_id1.fp_store_hazard.eq(fp_store_haz_id1),
            stall_dep_id1.eq(dep_stall_id1.stall),
        ]

        # (GC control signals, pending set/clear, and sync updates moved into GCSubsystem)
        pipeline_any = Signal()
        m.d.comb += pipeline_any.eq(
            IF1.valid | IF2.valid | IF3.valid | IF4.valid |
            ID1.valid | ID2.valid | IS.valid |
            EX1.valid | EX2.valid | MEM1.valid | MEM2.valid | WB.valid
        )

        # 前端停顿：包含后端压力(stall) + 依赖停顿
        m.d.comb += [
            vmem_is_insn.eq(C(self.enable_v) & IS.valid &
                ((IS.opcode == LOAD_FP) | (IS.opcode == STORE_FP)) &
                ((IS.funct3 == 0b000) | (IS.funct3 == 0b101) |
                 (IS.funct3 == 0b110) | (IS.funct3 == 0b111))),
            vmem_backend_clear.eq(~EX1.valid & ~EX2.valid &
                                   ~MEM1.valid & ~MEM2.valid &
                                   ~zcmp_push_active & ~zcmp_pop_active),
            vmem_pipe.insn.eq(IS.insn),
            vmem_pipe.base.eq(rreg(IS.rs1)[:32]),
            vmem_pipe.stride.eq(rreg(IS.rs2)[:32]),
        ]
        m.d.comb += stall_front.eq(
            stall | stall_dep_id1 | stall_dep_id2 | zcmp_push_active |
            zcmp_pop_active | vfdiv_pipe.busy | vfadd_pipe.busy | vffma_pipe.busy | vmem_pipe.busy | (vmem_is_insn & ~vmem_backend_clear) | vfsqrt_pipe.busy | vfestimate7_pipe.busy | vfcvt_pipe.busy |
            vfredsum_active
        )

        # ----------------------
        # EX1: build operands with forwarding (EX2/MEM2/WB -> EX1)
        # ----------------------
        ex1_a = Signal(self.xlen)
        ex1_b = Signal(self.xlen)
        fp_ex1_a = Signal(128)
        fp_ex1_b = Signal(128)
        fp_ex1_c = Signal(128)
        q_load_forward_valid = Signal()
        q_load_forward_data = Signal(128)
        q_recent_valid = Signal()
        q_recent_rd = Signal(5)
        q_recent_data = Signal(128)
        m.d.comb += [
            self.dbg_q_recent_valid.eq(q_recent_valid),
            self.dbg_q_recent_rd.eq(q_recent_rd),
            self.dbg_q_recent_data.eq(q_recent_data),
        ]
        # Step78：EX1 从寄存器文件直接读取，而不是 ID2 快照；并使用明确优先级前递
        # 优先级：GC/mv 回应 > EX1(ALU/访存结果) > EX2 > MEM2(cache hit/MEM 回写) > WB
        m.d.comb += [ex1_a.eq(rreg(IS.rs1)), ex1_b.eq(rreg(IS.rs2))]
        if self.use_finx:
            if self.use_zdinx and self.xlen >= 64:
                m.d.comb += [
                    fp_ex1_a.eq(rreg(IS.rs1)),
                    fp_ex1_b.eq(rreg(IS.rs2)),
                    fp_ex1_c.eq(rreg(IS.funct7[2:7])),
                ]
            else:
                m.d.comb += [
                    fp_ex1_a.eq(Cat(rreg(IS.rs1)[0:32], C(0xffffffff, 32))),
                    fp_ex1_b.eq(Cat(rreg(IS.rs2)[0:32], C(0xffffffff, 32))),
                    fp_ex1_c.eq(Cat(rreg(IS.funct7[2:7])[0:32], C(0xffffffff, 32))),
                ]
        else:
            m.d.comb += [fp_ex1_a.eq(freg(IS.rs1)), fp_ex1_b.eq(freg(IS.rs2))]
            m.d.comb += fp_ex1_c.eq(freg(IS.funct7[2:7]))

        ex1_is_rs1 = Signal()
        ex1_is_rs2 = Signal()
        m.d.comb += [ex1_is_rs1.eq(IS.rs1 != 0), ex1_is_rs2.eq(IS.rs2 != 0)]

        with m.If(ex1_is_rs1):
            with m.If(self.gc_rsp_valid & (self.gc_rsp_rd == IS.rs1) & (self.gc_rsp_rd != 0)):
                m.d.comb += ex1_a.eq(self.gc_rsp_data)
            with m.Elif(mv_bp_valid & (mv_bp_rd == IS.rs1) & (mv_bp_rd != 0)):
                m.d.comb += ex1_a.eq(mv_bp_data)
            with m.Elif(EX1.valid & EX1.wb_en & (~EX1.is_load) & (EX1.rd == IS.rs1) & (EX1.rd != 0)):
                m.d.comb += ex1_a.eq(EX1.wb_data)
            with m.Elif(EX1.valid & EX1.wb2_en & (EX1.wb2_rd == IS.rs1) & (EX1.wb2_rd != 0)):
                m.d.comb += ex1_a.eq(EX1.wb2_data)
            with m.Elif(EX2.valid & EX2.wb_en & (EX2.rd == IS.rs1) & (EX2.rd != 0)):
                m.d.comb += ex1_a.eq(EX2.wb_data)
            with m.Elif(EX2.valid & EX2.wb2_en & (EX2.wb2_rd == IS.rs1) & (EX2.wb2_rd != 0)):
                m.d.comb += ex1_a.eq(EX2.wb2_data)
            with m.Elif(MEM1.valid & MEM1.wb_en & (~MEM1.is_load) & (MEM1.rd == IS.rs1) & (MEM1.rd != 0)):
                m.d.comb += ex1_a.eq(MEM1.wb_data)
            with m.Elif(MEM1.valid & MEM1.wb2_en & (MEM1.wb2_rd == IS.rs1) & (MEM1.wb2_rd != 0)):
                m.d.comb += ex1_a.eq(MEM1.wb2_data)
            with m.Elif(MEM2.valid & cache_hit_fire & (MEM2.rd == IS.rs1) & (MEM2.rd != 0)):
                m.d.comb += ex1_a.eq(cache_hit_data)
            with m.Elif(MEM2.valid & (MEM2.rd == IS.rs1) & (MEM2.rd != 0)):
                m.d.comb += ex1_a.eq(MEM2.wb_data)
            with m.Elif(MEM2.valid & MEM2.wb2_en & (MEM2.wb2_rd == IS.rs1) & (MEM2.wb2_rd != 0)):
                m.d.comb += ex1_a.eq(MEM2.wb2_data)
            with m.Elif(WB.valid & WB.wb_en & (WB.rd == IS.rs1) & (WB.rd != 0)):
                m.d.comb += ex1_a.eq(WB.wb_data)
            with m.Elif(WB.valid & WB.wb2_en & (WB.wb2_rd == IS.rs1) & (WB.wb2_rd != 0)):
                m.d.comb += ex1_a.eq(WB.wb2_data)

        with m.If(ex1_is_rs2):
            with m.If(self.gc_rsp_valid & (self.gc_rsp_rd == IS.rs2) & (self.gc_rsp_rd != 0)):
                m.d.comb += ex1_b.eq(self.gc_rsp_data)
            with m.Elif(mv_bp_valid & (mv_bp_rd == IS.rs2) & (mv_bp_rd != 0)):
                m.d.comb += ex1_b.eq(mv_bp_data)
            with m.Elif(EX1.valid & EX1.wb_en & (~EX1.is_load) & (EX1.rd == IS.rs2) & (EX1.rd != 0)):
                m.d.comb += ex1_b.eq(EX1.wb_data)
            with m.Elif(EX1.valid & EX1.wb2_en & (EX1.wb2_rd == IS.rs2) & (EX1.wb2_rd != 0)):
                m.d.comb += ex1_b.eq(EX1.wb2_data)
            with m.Elif(EX2.valid & EX2.wb_en & (EX2.rd == IS.rs2) & (EX2.rd != 0)):
                m.d.comb += ex1_b.eq(EX2.wb_data)
            with m.Elif(EX2.valid & EX2.wb2_en & (EX2.wb2_rd == IS.rs2) & (EX2.wb2_rd != 0)):
                m.d.comb += ex1_b.eq(EX2.wb2_data)
            with m.Elif(MEM1.valid & MEM1.wb_en & (~MEM1.is_load) & (MEM1.rd == IS.rs2) & (MEM1.rd != 0)):
                m.d.comb += ex1_b.eq(MEM1.wb_data)
            with m.Elif(MEM1.valid & MEM1.wb2_en & (MEM1.wb2_rd == IS.rs2) & (MEM1.wb2_rd != 0)):
                m.d.comb += ex1_b.eq(MEM1.wb2_data)
            with m.Elif(MEM2.valid & cache_hit_fire & (MEM2.rd == IS.rs2) & (MEM2.rd != 0)):
                m.d.comb += ex1_b.eq(cache_hit_data)
            with m.Elif(MEM2.valid & (MEM2.rd == IS.rs2) & (MEM2.rd != 0)):
                m.d.comb += ex1_b.eq(MEM2.wb_data)
            with m.Elif(MEM2.valid & MEM2.wb2_en & (MEM2.wb2_rd == IS.rs2) & (MEM2.wb2_rd != 0)):
                m.d.comb += ex1_b.eq(MEM2.wb2_data)
            with m.Elif(WB.valid & WB.wb_en & (WB.rd == IS.rs2) & (WB.rd != 0)):
                m.d.comb += ex1_b.eq(WB.wb_data)
            with m.Elif(WB.valid & WB.wb2_en & (WB.wb2_rd == IS.rs2) & (WB.wb2_rd != 0)):
                m.d.comb += ex1_b.eq(WB.wb2_data)

        if self.use_finx:
            if self.use_zdinx and self.xlen >= 64:
                m.d.comb += [fp_ex1_a.eq(ex1_a), fp_ex1_b.eq(ex1_b)]
            else:
                m.d.comb += [
                    fp_ex1_a.eq(Cat(ex1_a[0:32], C(0xffffffff, 32))),
                    fp_ex1_b.eq(Cat(ex1_b[0:32], C(0xffffffff, 32))),
                ]

        with m.If(EX1.valid & EX1.fp_wb_en & (EX1.rd == IS.rs1)):
            m.d.comb += fp_ex1_a.eq(EX1.fp_wb_data)
        with m.Elif(EX2.valid & EX2.fp_wb_en & (EX2.rd == IS.rs1)):
            m.d.comb += fp_ex1_a.eq(EX2.fp_wb_data)
        with m.Elif(MEM1.valid & MEM1.fp_wb_en & (MEM1.rd == IS.rs1)):
            m.d.comb += fp_ex1_a.eq(MEM1.fp_wb_data)
        with m.Elif(MEM2.valid & MEM2.fp_wb_en & (MEM2.rd == IS.rs1)):
            m.d.comb += fp_ex1_a.eq(MEM2.fp_wb_data)
        with m.Elif(WB.valid & WB.fp_wb_en & (WB.rd == IS.rs1)):
            m.d.comb += fp_ex1_a.eq(WB.fp_wb_data)

        with m.If(EX1.valid & EX1.fp_wb_en & (EX1.rd == IS.rs2)):
            m.d.comb += fp_ex1_b.eq(EX1.fp_wb_data)
        with m.Elif(EX2.valid & EX2.fp_wb_en & (EX2.rd == IS.rs2)):
            m.d.comb += fp_ex1_b.eq(EX2.fp_wb_data)
        with m.Elif(MEM1.valid & MEM1.fp_wb_en & (MEM1.rd == IS.rs2)):
            m.d.comb += fp_ex1_b.eq(MEM1.fp_wb_data)
        with m.Elif(MEM2.valid & MEM2.fp_wb_en & (MEM2.rd == IS.rs2)):
            m.d.comb += fp_ex1_b.eq(MEM2.fp_wb_data)
        with m.Elif(WB.valid & WB.fp_wb_en & (WB.rd == IS.rs2)):
            m.d.comb += fp_ex1_b.eq(WB.fp_wb_data)
        # A dependent FSQ is released on the same cycle as the final FLQ beat.
        # Forward that complete 128-bit value instead of the placeholder
        # fp_wb_data carried by the load before memory completion.
        with m.If(q_load_forward_valid & (MEM1.rd == IS.rs2) &
                  (IS.opcode == STORE_FP) & (IS.funct3 == 0b100)):
            m.d.comb += fp_ex1_b.eq(q_load_forward_data)
        with m.If(q_recent_valid & (q_recent_rd == IS.rs2) &
                  (IS.opcode == STORE_FP) & (IS.funct3 == 0b100)):
            m.d.comb += fp_ex1_b.eq(q_recent_data)

        with m.If(EX1.valid & EX1.fp_wb_en & (EX1.rd == IS.funct7[2:7])):
            m.d.comb += fp_ex1_c.eq(EX1.fp_wb_data)
        with m.Elif(EX2.valid & EX2.fp_wb_en & (EX2.rd == IS.funct7[2:7])):
            m.d.comb += fp_ex1_c.eq(EX2.fp_wb_data)
        with m.Elif(MEM1.valid & MEM1.fp_wb_en & (MEM1.rd == IS.funct7[2:7])):
            m.d.comb += fp_ex1_c.eq(MEM1.fp_wb_data)
        with m.Elif(MEM2.valid & MEM2.fp_wb_en & (MEM2.rd == IS.funct7[2:7])):
            m.d.comb += fp_ex1_c.eq(MEM2.fp_wb_data)
        with m.Elif(WB.valid & WB.fp_wb_en & (WB.rd == IS.funct7[2:7])):
            m.d.comb += fp_ex1_c.eq(WB.fp_wb_data)

        # EX1 compute (subset)
        alu_out = Signal(self.xlen)
        wb_en = Signal()
        wb_data = Signal(self.xlen)
        wb2_en = Signal()
        wb2_rd = Signal(5)
        wb2_data = Signal(self.xlen)
        fp_wb_en = Signal()
        fp_wb_data = Signal(128)
        fp_wb_q = Signal()
        fp_rm_required = Signal()
        fp_rm_illegal = Signal()
        finx_excluded_move = Signal()
        mem_addr = Signal(self.xlen)
        mem_wdata = Signal(self.xlen)
        fp_mem_wdata = Signal(128)
        lr_sc_valid = Signal(reset=0)
        lr_sc_addr = Signal(self.xlen)
        amo_sc_ok = Signal()
        amo_funct5 = Signal(5)
        m.d.comb += [
            amo_sc_ok.eq(lr_sc_valid & (lr_sc_addr == ex1_a)),
            amo_funct5.eq(IS.funct7[2:7]),
            fp_rm_required.eq(fp_rm_required_issue),
            fp_rm_illegal.eq(fp_rm_illegal_issue),
            finx_excluded_move.eq(
                self.use_finx & (IS.opcode == OP_FP) & (IS.funct3 == 0) &
                (IS.rs2 == 0) & (
                    (self.use_zfinx & ((IS.funct7 == 0b1110000) |
                                       (IS.funct7 == 0b1111000))) |
                    (self.use_zhinxmin & ((IS.funct7 == 0b1110010) |
                                          (IS.funct7 == 0b1111010)))
                )
            ),
        ]

        m.d.comb += [
            alu_out.eq(0),
            wb_en.eq(0),
            wb_data.eq(0),
            wb2_en.eq(0),
            wb2_rd.eq(0),
            wb2_data.eq(0),
            fp_wb_en.eq(0),
            fp_wb_data.eq(0),
            mem_addr.eq(0),
            mem_wdata.eq(ex1_b),
            fp_mem_wdata.eq(0),
            redirect.eq(0),
            redirect_pc.eq(0),
            self.trap.eq(0),
            self.svinval_valid.eq(0),
            self.svinval_vaddr.eq(0),
            self.svinval_asid.eq(0),
            self.svinval_vaddr_valid.eq(0),
            self.svinval_asid_valid.eq(0),
            self.svinval_ordered.eq(0),
        ]

        # Reserved static rounding modes and invalid dynamic frm values are
        # architecturally illegal instructions.  Report the precise trap in
        # the issue cycle and suppress every floating-point side effect.
        with m.If(IS.valid & fp_rm_illegal):
            m.d.comb += self.trap.eq(1)

        m.d.comb += [
            qfadd.a.eq(fp_ex1_a),
            qfadd.b.eq(fp_ex1_b),
            qfadd.subtract.eq(IS.funct7 == 0b0000111),
            qfadd.rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
            qfmul.a.eq(fp_ex1_a),
            qfmul.b.eq(fp_ex1_b),
            qfmul.rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
            qfdiv.a.eq(fp_ex1_a),
            qfdiv.b.eq(fp_ex1_b),
            qfdiv.rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
            qfsqrt.a.eq(fp_ex1_a),
            qfsqrt.rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
            qffma.a.eq(fp_ex1_a),
            qffma.b.eq(fp_ex1_b),
            qffma.c.eq(fp_ex1_c),
            qffma.negate_product.eq((IS.opcode == NMSUB) |
                                     (IS.opcode == NMADD)),
            qffma.negate_addend.eq((IS.opcode == MSUB) |
                                    (IS.opcode == NMADD)),
            qffma.rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
        ]

        zfa_fli_h = Array(Const(value, 16) for value in (
            0xBC00, 0x0400, 0x0100, 0x0200,
            0x1C00, 0x2000, 0x2C00, 0x3000,
            0x3400, 0x3500, 0x3600, 0x3700,
            0x3800, 0x3900, 0x3A00, 0x3B00,
            0x3C00, 0x3D00, 0x3E00, 0x3F00,
            0x4000, 0x4100, 0x4200, 0x4400,
            0x4800, 0x4C00, 0x5800, 0x5C00,
            0x7800, 0x7C00, 0x7C00, 0x7E00,
        ))
        zfa_fli_s = Array(Const(value, 32) for value in (
            0xBF800000, 0x00800000, 0x37800000, 0x38000000,
            0x3B800000, 0x3C000000, 0x3D800000, 0x3E000000,
            0x3E800000, 0x3EA00000, 0x3EC00000, 0x3EE00000,
            0x3F000000, 0x3F200000, 0x3F400000, 0x3F600000,
            0x3F800000, 0x3FA00000, 0x3FC00000, 0x3FE00000,
            0x40000000, 0x40200000, 0x40400000, 0x40800000,
            0x41000000, 0x41800000, 0x43000000, 0x43800000,
            0x47000000, 0x47800000, 0x7F800000, 0x7FC00000,
        ))
        zfa_fli_d = Array(Const(value, 64) for value in (
            0xBFF0000000000000, 0x0010000000000000,
            0x3EF0000000000000, 0x3F00000000000000,
            0x3F70000000000000, 0x3F80000000000000,
            0x3FB0000000000000, 0x3FC0000000000000,
            0x3FD0000000000000, 0x3FD4000000000000,
            0x3FD8000000000000, 0x3FDC000000000000,
            0x3FE0000000000000, 0x3FE4000000000000,
            0x3FE8000000000000, 0x3FEC000000000000,
            0x3FF0000000000000, 0x3FF4000000000000,
            0x3FF8000000000000, 0x3FFC000000000000,
            0x4000000000000000, 0x4004000000000000,
            0x4008000000000000, 0x4010000000000000,
            0x4020000000000000, 0x4030000000000000,
            0x4060000000000000, 0x4070000000000000,
            0x40E0000000000000, 0x40F0000000000000,
            0x7FF0000000000000, 0x7FF8000000000000,
        ))

        m.submodules.branch_condition = branch_condition = BranchCondition(self.xlen)
        m.d.comb += [
            branch_condition.funct3.eq(IS.funct3),
            branch_condition.lhs.eq(ex1_a),
            branch_condition.rhs.eq(ex1_b),
        ]
        m.submodules.jump_control = jump_control = JumpControl(self.xlen)
        m.d.comb += [
            jump_control.pc.eq(IS.pc),
            jump_control.base.eq(ex1_a),
            jump_control.imm.eq(IS.imm),
            jump_control.compressed.eq(IS.compressed),
            jump_control.jalr.eq(IS.opcode == JALR),
        ]

        with m.If(IS.valid & ~fence_active):
            with m.Switch(IS.opcode):
                with m.Case(OP_IMM):  # Immediate
                    with m.If(IS.funct3 == 0b000):
                        # ADDI
                        m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a + IS.imm)]
                    with m.If(IS.funct3 == 0b001):  # SLLI
                        with m.If(self.xlen >= 64):
                            m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a << IS.imm[0:6])]
                        with m.Else():
                            m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a << IS.imm[0:5])]
                    with m.If(IS.funct3 == 0b010):  # SLTI
                        m.d.comb += [wb_en.eq(1), wb_data.eq((ex1_a.as_signed() < IS.imm.as_signed()).as_unsigned())]
                    with m.If(IS.funct3 == 0b011):  # SLTIU
                        m.d.comb += [wb_en.eq(1), wb_data.eq((ex1_a < IS.imm))]
                    with m.If(IS.funct3 == 0b100):  # XORI
                        m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a ^ IS.imm)]
                    with m.If(IS.funct3 == 0b101):  # SRLI / SRAI
                        with m.If(IS.imm[10] == 0):
                            with m.If(self.xlen >= 64):
                                m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a >> IS.imm[0:6])]
                            with m.Else():
                                m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a >> IS.imm[0:5])]
                        with m.Else():
                            with m.If(self.xlen >= 64):
                                m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a.as_signed() >> IS.imm[0:6])]
                            with m.Else():
                                m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a.as_signed() >> IS.imm[0:5])]
                    with m.If(IS.funct3 == 0b110):  # ORI
                        m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a | IS.imm)]
                    with m.If(IS.funct3 == 0b111):  # ANDI
                        m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a & IS.imm)]
                    with m.If(self.enable_b):
                        with m.If((IS.funct3 == 0b101) & (IS.imm[5:12] == 0b0110000)):  # RORI
                            rori_shamt = Signal(6 if self.xlen >= 64 else 5)
                            rori_inv = Signal(6 if self.xlen >= 64 else 5)
                            m.d.comb += [
                                rori_shamt.eq(IS.imm[0:6] if self.xlen >= 64 else IS.imm[0:5]),
                                rori_inv.eq(-rori_shamt),
                                wb_en.eq(1),
                                wb_data.eq((ex1_a >> rori_shamt) | (ex1_a << rori_inv)),
                            ]
                        zbs_i_pos = IS.imm[0:6] if self.xlen >= 64 else IS.imm[0:5]
                        zbs_i_mask = C(1, self.xlen) << zbs_i_pos
                        with m.If(IS.funct3 == 0b001):
                            with m.If(IS.imm[5:12] == 0b0010100):  # BSETI
                                m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a | zbs_i_mask)]
                            with m.If(IS.imm[5:12] == 0b0100100):  # BCLRI
                                m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a & ~zbs_i_mask)]
                            with m.If(IS.imm[5:12] == 0b0110100):  # BINVI
                                m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a ^ zbs_i_mask)]
                        with m.If((IS.funct3 == 0b101) & (IS.imm[5:12] == 0b0100100)):  # BEXTI
                            m.d.comb += [wb_en.eq(1), wb_data.eq((ex1_a >> zbs_i_pos) & 1)]
                        with m.If((IS.funct3 == 0b101) & (IS.imm[0:12] == 0x687)):  # BREV8
                            brev8_parts = []
                            for byte in range(self.xlen // 8):
                                base = byte * 8
                                brev8_parts.append(Cat(*[
                                    ex1_a[base + 7 - bit] for bit in range(8)
                                ]))
                            m.d.comb += [wb_en.eq(1), wb_data.eq(Cat(*brev8_parts))]
                        if self.xlen == 32:
                            with m.If((IS.funct3 == 0b001) & (IS.imm[0:12] == 0x08F)):  # ZIP
                                zip_bits = []
                                for bit in range(16):
                                    zip_bits.extend((ex1_a[bit], ex1_a[bit + 16]))
                                m.d.comb += [wb_en.eq(1), wb_data.eq(Cat(*zip_bits))]
                            with m.If((IS.funct3 == 0b101) & (IS.imm[0:12] == 0x08F)):  # UNZIP
                                unzip_bits = [ex1_a[2 * bit] for bit in range(16)]
                                unzip_bits += [ex1_a[2 * bit + 1] for bit in range(16)]
                                m.d.comb += [wb_en.eq(1), wb_data.eq(Cat(*unzip_bits))]
                    # Zknh SHA-256 unary operations (standard OP-IMM encodings).
                    with m.If(self.enable_zknh & (IS.funct7 == 0b0001000) &
                              (IS.funct3 == 0b001) & (IS.rs2 < 4)):
                        with m.Switch(IS.rs2):
                            with m.Case(0):  # SHA256SUM0
                                m.d.comb += [wb_en.eq(1), wb_data.eq(
                                    ((ex1_a >> 2) | (ex1_a << 30)) ^
                                    ((ex1_a >> 13) | (ex1_a << 19)) ^
                                    ((ex1_a >> 22) | (ex1_a << 10)))]
                            with m.Case(1):  # SHA256SUM1
                                m.d.comb += [wb_en.eq(1), wb_data.eq(
                                    ((ex1_a >> 6) | (ex1_a << 26)) ^
                                    ((ex1_a >> 11) | (ex1_a << 21)) ^
                                    ((ex1_a >> 25) | (ex1_a << 7)))]
                            with m.Case(2):  # SHA256SIG0
                                m.d.comb += [wb_en.eq(1), wb_data.eq(
                                    ((ex1_a >> 7) | (ex1_a << 25)) ^
                                    ((ex1_a >> 18) | (ex1_a << 14)) ^
                                    (ex1_a >> 3))]
                            with m.Case(3):  # SHA256SIG1
                                m.d.comb += [wb_en.eq(1), wb_data.eq(
                                    ((ex1_a >> 17) | (ex1_a << 15)) ^
                                    ((ex1_a >> 19) | (ex1_a << 13)) ^
                                    (ex1_a >> 10))]
                    # Zksh SM3 permutation operations.
                    with m.If(self.enable_zksh & (IS.funct7 == 0b0001000) &
                              (IS.funct3 == 0b001) & ((IS.rs2 == 8) | (IS.rs2 == 9))):
                        with m.If(IS.rs2 == 8):  # SM3P0
                            m.d.comb += [wb_en.eq(1), wb_data.eq(
                                ex1_a ^ ((ex1_a << 9) | (ex1_a >> 23)) ^
                                ((ex1_a << 17) | (ex1_a >> 15)))]
                        with m.Else():  # SM3P1
                            m.d.comb += [wb_en.eq(1), wb_data.eq(
                                ex1_a ^ ((ex1_a << 15) | (ex1_a >> 17)) ^
                                ((ex1_a << 23) | (ex1_a >> 9)))]
                with m.Case(LUI):
                    m.d.comb += [wb_en.eq(1), wb_data.eq(IS.imm)]
                with m.Case(AUIPC):
                    m.d.comb += [wb_en.eq(1), wb_data.eq(IS.pc + IS.imm)]
                with m.Case(LOAD):
                    m.d.comb += mem_addr.eq(ex1_a + IS.imm)
                with m.Case(STORE):
                    m.d.comb += mem_addr.eq(ex1_a + IS.imm)
                with m.Case(OP):      # ADD only
                    with m.If(IS.funct7 == 0b0000000):
                        with m.If(IS.funct3 == 0b000):
                            m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a + ex1_b)]
                        with m.If(IS.funct3 == 0b001):
                            m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a << (ex1_b[0:6] if self.xlen >= 64 else ex1_b[0:5]))]
                        with m.If(IS.funct3 == 0b010):
                            m.d.comb += [wb_en.eq(1), wb_data.eq((ex1_a.as_signed() < ex1_b.as_signed()).as_unsigned())]
                        with m.If(IS.funct3 == 0b011):
                            m.d.comb += [wb_en.eq(1), wb_data.eq((ex1_a < ex1_b).as_unsigned())]
                        with m.If(IS.funct3 == 0b100):
                            m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a ^ ex1_b)]
                        with m.If(IS.funct3 == 0b101):
                            m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a >> (ex1_b[0:6] if self.xlen >= 64 else ex1_b[0:5]))]
                        with m.If(IS.funct3 == 0b110):
                            m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a | ex1_b)]
                        with m.If(IS.funct3 == 0b111):
                            m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a & ex1_b)]
                    with m.If(IS.funct7 == 0b0100000):
                        with m.If(IS.funct3 == 0b000):
                            m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a - ex1_b)]
                        with m.If(IS.funct3 == 0b101):
                            m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a.as_signed() >> (ex1_b[0:6] if self.xlen >= 64 else ex1_b[0:5]))]
                    with m.If(self.enable_m & (IS.funct7 == 0b0000001)):
                        mul_ss_prod = Signal(signed(2 * self.xlen))
                        mul_su_prod = Signal(signed(2 * self.xlen))
                        mul_uu_prod = Signal(2 * self.xlen)
                        mul_hs_a = Signal(signed(self.xlen))
                        mul_hu_b = Signal(self.xlen)
                        m.d.comb += [
                            mul_ss_prod.eq(ex1_a.as_signed() * ex1_b.as_signed()),
                            mul_hs_a.eq(ex1_a.as_signed()),
                            mul_hu_b.eq(ex1_b),
                            mul_su_prod.eq(mul_hs_a * mul_hu_b),
                            mul_uu_prod.eq(ex1_a.as_unsigned() * ex1_b.as_unsigned()),
                        ]
                        with m.If(IS.funct3 == 0b000):  # MUL
                            mul_res = Signal(2 * self.xlen)
                            m.d.comb += mul_res.eq(ex1_a * ex1_b)
                            m.d.comb += [wb_en.eq(1),
                                         wb_data.eq(mul_res[0:self.xlen])]
                        with m.If(IS.funct3 == 0b001):  # MULH
                            m.d.comb += [wb_en.eq(1), wb_data.eq(mul_ss_prod[self.xlen:2 * self.xlen])]
                        with m.If(IS.funct3 == 0b010):  # MULHSU
                            m.d.comb += [wb_en.eq(1), wb_data.eq(mul_su_prod[self.xlen:2 * self.xlen])]
                        with m.If(IS.funct3 == 0b011):  # MULHU
                            m.d.comb += [wb_en.eq(1), wb_data.eq(mul_uu_prod[self.xlen:2 * self.xlen])]
                        with m.If(IS.funct3 == 0b100):  # DIV
                            div_div = Signal(self.xlen)
                            div_abs_a = Signal(self.xlen)
                            div_abs_b = Signal(self.xlen)
                            div_abs_q = Signal(self.xlen)
                            div_signed_q = Signal(self.xlen)
                            div_neg = Signal()
                            div_overflow_64 = (ex1_a == (1 << (self.xlen - 1))) & (ex1_b.as_signed() == -1)
                            div_overflow_32 = (self.xlen >= 64) & (ex1_a[0:32] == 0x80000000) & (ex1_a[32:] == (2**(self.xlen - 32) - 1)) & (ex1_b.as_signed() == -1)
                            div_overflow = div_overflow_64 | div_overflow_32
                            m.d.comb += [
                                div_abs_a.eq(Mux(ex1_a[self.xlen - 1], -ex1_a, ex1_a)),
                                div_abs_b.eq(Mux(ex1_b[self.xlen - 1], -ex1_b, ex1_b)),
                                div_abs_q.eq(Mux(div_abs_b == 0, 0, div_abs_a // div_abs_b)),
                                div_neg.eq(ex1_a[self.xlen - 1] ^ ex1_b[self.xlen - 1]),
                                div_signed_q.eq(Mux(div_neg, -div_abs_q, div_abs_q)),
                                div_div.eq(Mux(div_overflow, ex1_a, div_signed_q)),
                            ]
                            with m.If(div_overflow):
                                m.d.comb += [wb_en.eq(1), wb_data.eq(div_div)]
                            with m.Else():
                                m.d.comb += [wb_en.eq(1), wb_data.eq(Mux(
                                    ex1_b == 0,
                                    (2**self.xlen - 1),
                                    Mux(self.xlen >= 64,
                                        Cat(div_div[0:32], C(0, 32)),
                                        div_div)
                                ))]
                        with m.If(IS.funct3 == 0b101):  # DIVU
                            divu_div = Signal(self.xlen)
                            m.d.comb += divu_div.eq(Mux(ex1_b == 0, (2**self.xlen - 1), ex1_a.as_unsigned() // ex1_b.as_unsigned()))
                            with m.If(self.xlen >= 64):
                                m.d.comb += [wb_en.eq(1), wb_data.eq(Mux(ex1_b == 0, (2**self.xlen - 1), divu_div[0:32]))]
                            with m.Else():
                                m.d.comb += [wb_en.eq(1), wb_data.eq(divu_div)]
                        with m.If(IS.funct3 == 0b110):  # REM
                            rem_abs_a = Signal(self.xlen)
                            rem_abs_b = Signal(self.xlen)
                            rem_div = Signal(self.xlen)
                            rem_u = Signal(self.xlen)
                            m.d.comb += [
                                rem_abs_a.eq(Mux(ex1_a[self.xlen - 1], -ex1_a, ex1_a)),
                                rem_abs_b.eq(Mux(ex1_b[self.xlen - 1], -ex1_b, ex1_b)),
                                rem_div.eq(Mux(rem_abs_b == 0, 0, rem_abs_a // rem_abs_b)),
                                rem_u.eq(rem_abs_a - (rem_div * rem_abs_b)),
                                wb_en.eq(1),
                                wb_data.eq(Mux(ex1_b == 0, Mux(self.xlen >= 64, ex1_a[0:32], ex1_a),
                                               Mux(self.xlen >= 64, (Mux(ex1_a[self.xlen - 1], -rem_u, rem_u)[0:32]), Mux(ex1_a[self.xlen - 1], -rem_u, rem_u))))
                            ]
                        with m.If(IS.funct3 == 0b111):  # REMU
                            remu_div = Signal(self.xlen)
                            m.d.comb += [
                                remu_div.eq(Mux(ex1_b == 0,
                                                ex1_a,
                                                ex1_a.as_unsigned() % ex1_b.as_unsigned())),
                                wb_en.eq(1),
                                wb_data.eq(remu_div),
                            ]
                    with m.If(self.enable_b):
                        with m.If(IS.funct7 == 0b0000100):
                            with m.If(IS.funct3 == 0b100):  # PACK
                                half = self.xlen // 2
                                m.d.comb += [
                                    wb_en.eq(1),
                                    wb_data.eq(Cat(ex1_a[0:half], ex1_b[0:half])),
                                ]
                            with m.If(IS.funct3 == 0b111):  # PACKH
                                m.d.comb += [
                                    wb_en.eq(1),
                                    wb_data.eq(Cat(ex1_a[0:8], ex1_b[0:8], C(0, self.xlen - 16))),
                                ]
                        with m.If(IS.funct7 == 0b0010100):
                            with m.If(IS.funct3 == 0b100):  # XPERM8
                                xperm8_parts = []
                                for out_byte in range(self.xlen // 8):
                                    index = ex1_b[out_byte * 8:out_byte * 8 + 8]
                                    selected = C(0, 8)
                                    for table_byte in reversed(range(self.xlen // 8)):
                                        selected = Mux(
                                            index == table_byte,
                                            ex1_a[table_byte * 8:table_byte * 8 + 8],
                                            selected,
                                        )
                                    xperm8_parts.append(selected)
                                m.d.comb += [wb_en.eq(1), wb_data.eq(Cat(*xperm8_parts))]
                            with m.If(IS.funct3 == 0b010):  # XPERM4
                                xperm4_parts = []
                                for out_nibble in range(self.xlen // 4):
                                    index = ex1_b[out_nibble * 4:out_nibble * 4 + 4]
                                    selected = C(0, 4)
                                    for table_nibble in reversed(range(self.xlen // 4)):
                                        selected = Mux(
                                            index == table_nibble,
                                            ex1_a[table_nibble * 4:table_nibble * 4 + 4],
                                            selected,
                                        )
                                    xperm4_parts.append(selected)
                                m.d.comb += [wb_en.eq(1), wb_data.eq(Cat(*xperm4_parts))]
                        with m.If(IS.funct7 == 0b0010000):
                            with m.If(IS.funct3 == 0b010):  # SH1ADD
                                m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_b + (ex1_a << 1))]
                            with m.If(IS.funct3 == 0b100):  # SH2ADD
                                m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_b + (ex1_a << 2))]
                            with m.If(IS.funct3 == 0b110):  # SH3ADD
                                m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_b + (ex1_a << 3))]
                        zbs_r_pos = ex1_b[0:6] if self.xlen >= 64 else ex1_b[0:5]
                        zbs_r_mask = C(1, self.xlen) << zbs_r_pos
                        with m.If(IS.funct3 == 0b001):
                            with m.If(IS.funct7 == 0b0010100):  # BSET
                                m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a | zbs_r_mask)]
                            with m.If(IS.funct7 == 0b0100100):  # BCLR
                                m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a & ~zbs_r_mask)]
                            with m.If(IS.funct7 == 0b0110100):  # BINV
                                m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a ^ zbs_r_mask)]
                        with m.If((IS.funct3 == 0b101) & (IS.funct7 == 0b0100100)):  # BEXT
                            m.d.comb += [wb_en.eq(1), wb_data.eq((ex1_a >> zbs_r_pos) & 1)]
                        with m.If(IS.funct7 == 0b0110000):
                            rot_shamt = Signal(6 if self.xlen >= 64 else 5)
                            rot_inv = Signal(6 if self.xlen >= 64 else 5)
                            m.d.comb += [
                                rot_shamt.eq(ex1_b[0:6] if self.xlen >= 64 else ex1_b[0:5]),
                                rot_inv.eq(-rot_shamt),
                            ]
                            with m.If(IS.funct3 == 0b001):  # ROL
                                m.d.comb += [
                                    wb_en.eq(1),
                                    wb_data.eq((ex1_a << rot_shamt) | (ex1_a >> rot_inv)),
                                ]
                            with m.If(IS.funct3 == 0b101):  # ROR
                                m.d.comb += [
                                    wb_en.eq(1),
                                    wb_data.eq((ex1_a >> rot_shamt) | (ex1_a << rot_inv)),
                                ]
                        with m.If(IS.funct7 == 0b0100000):
                            with m.If(IS.funct3 == 0b111):  # ANDN
                                m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a & ~ex1_b)]
                            with m.If(IS.funct3 == 0b110):  # ORN
                                m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a | ~ex1_b)]
                            with m.If(IS.funct3 == 0b100):  # XNOR
                                m.d.comb += [wb_en.eq(1), wb_data.eq(~(ex1_a ^ ex1_b))]
                        with m.If((IS.funct7 == 0b0110000) & (IS.funct3 == 0b001)):
                            with m.If(IS.rs2 == 0b00000):  # CLZ
                                clz_val = C(self.xlen, 6)
                                for i in range(self.xlen):
                                    clz_val = Mux(ex1_a[i], C(self.xlen - 1 - i, 6), clz_val)
                                m.d.comb += [wb_en.eq(1), wb_data.eq(clz_val)]
                            with m.If(IS.rs2 == 0b00001):  # CTZ
                                ctz_val = C(self.xlen, 6)
                                for i in range(self.xlen):
                                    ctz_val = Mux(ex1_a[self.xlen - 1 - i], C(self.xlen - 1 - i, 6), ctz_val)
                                m.d.comb += [wb_en.eq(1), wb_data.eq(ctz_val)]
                            with m.If(IS.rs2 == 0b00010):  # CPOP
                                pop = ex1_a[0]
                                for i in range(1, self.xlen):
                                    pop = pop + ex1_a[i]
                                m.d.comb += [wb_en.eq(1), wb_data.eq(pop)]
                        with m.If(IS.funct7 == 0b0000101):
                            signed_lt = Signal()
                            unsigned_lt = Signal()
                            m.d.comb += [
                                signed_lt.eq(ex1_a.as_signed() < ex1_b.as_signed()),
                                unsigned_lt.eq(ex1_a.as_unsigned() < ex1_b.as_unsigned()),
                            ]
                            with m.If(IS.funct3 == 0b100):  # MIN
                                m.d.comb += [wb_en.eq(1), wb_data.eq(Mux(signed_lt, ex1_a, ex1_b))]
                            with m.If(IS.funct3 == 0b101):  # MINU
                                m.d.comb += [wb_en.eq(1), wb_data.eq(Mux(unsigned_lt, ex1_a, ex1_b))]
                            with m.If(IS.funct3 == 0b110):  # MAX
                                m.d.comb += [wb_en.eq(1), wb_data.eq(Mux(signed_lt, ex1_b, ex1_a))]
                            with m.If(IS.funct3 == 0b111):  # MAXU
                                m.d.comb += [wb_en.eq(1), wb_data.eq(Mux(unsigned_lt, ex1_b, ex1_a))]
                            # Zbc carry-less multiply occupies the remaining
                            # funct3 encodings under the same funct7 value.
                            clmul_product = C(0, 2 * self.xlen)
                            clmul_a = Cat(ex1_a, C(0, self.xlen))
                            for bit in range(self.xlen):
                                partial = (clmul_a << bit)[0:2 * self.xlen]
                                clmul_product = clmul_product ^ Mux(
                                    ex1_b[bit], partial, C(0, 2 * self.xlen)
                                )
                            with m.If(IS.funct3 == 0b001):  # CLMUL
                                m.d.comb += [
                                    wb_en.eq(1),
                                    wb_data.eq(clmul_product[0:self.xlen]),
                                ]
                            with m.If(IS.funct3 == 0b011):  # CLMULH
                                m.d.comb += [
                                    wb_en.eq(1),
                                    wb_data.eq(clmul_product[self.xlen:2 * self.xlen]),
                                ]
                            with m.If(IS.funct3 == 0b010):  # CLMULR
                                m.d.comb += [
                                    wb_en.eq(1),
                                    wb_data.eq(clmul_product[self.xlen - 1:2 * self.xlen - 1]),
                                ]
                        with m.If((IS.funct7 == 0b0110000) & (IS.funct3 == 0b100)):
                            with m.If(IS.rs2 == 0b00100):  # SEXT.B
                                m.d.comb += [wb_en.eq(1), wb_data.eq(sign_extend(ex1_a[0:8], 8, self.xlen))]
                            with m.If(IS.rs2 == 0b00101):  # SEXT.H
                                m.d.comb += [wb_en.eq(1), wb_data.eq(sign_extend(ex1_a[0:16], 16, self.xlen))]
                            with m.If(IS.rs2 == 0b00110):  # ZEXT.H
                                m.d.comb += [wb_en.eq(1), wb_data.eq(Cat(ex1_a[0:16], C(0, self.xlen - 16)))]
                        with m.If((IS.funct7 == 0b0010101) & (IS.funct3 == 0b111)):  # ORC.B
                            b0 = Signal()
                            b1 = Signal()
                            b2 = Signal()
                            b3 = Signal()
                            m.d.comb += [
                                b0.eq(ex1_a[0] | ex1_a[1] | ex1_a[2] | ex1_a[3] | ex1_a[4] | ex1_a[5] | ex1_a[6] | ex1_a[7]),
                                b1.eq(ex1_a[8] | ex1_a[9] | ex1_a[10] | ex1_a[11] | ex1_a[12] | ex1_a[13] | ex1_a[14] | ex1_a[15]),
                                b2.eq(ex1_a[16] | ex1_a[17] | ex1_a[18] | ex1_a[19] | ex1_a[20] | ex1_a[21] | ex1_a[22] | ex1_a[23]),
                                b3.eq(ex1_a[24] | ex1_a[25] | ex1_a[26] | ex1_a[27] | ex1_a[28] | ex1_a[29] | ex1_a[30] | ex1_a[31]),
                                wb_en.eq(1),
                                wb_data.eq(Cat(*[b0] * 8, *[b1] * 8, *[b2] * 8, *[b3] * 8)),
                            ]
                        with m.If((IS.funct7 == 0b0110101) & (IS.funct3 == 0b101) & (IS.rs2 == 0b00111)):  # REV8
                            m.d.comb += [
                                wb_en.eq(1),
                                wb_data.eq(Cat(ex1_a[24:32], ex1_a[16:24], ex1_a[8:16], ex1_a[0:8])),
                            ]
                    with m.If(self.enable_zicond):
                        with m.If(IS.funct7 == ZICOND_F7):
                            with m.If(IS.funct3 == 0b101):  # CZERO.EQZ
                                m.d.comb += [wb_en.eq(1), wb_data.eq(Mux(ex1_b == 0, 0, ex1_a))]
                            with m.If(IS.funct3 == 0b111):  # CZERO.NEZ
                                m.d.comb += [wb_en.eq(1), wb_data.eq(Mux(ex1_b != 0, 0, ex1_a))]
                    # Zknh RV32 SHA-512 register-pair operations.
                    with m.If(self.enable_zknh & (IS.funct3 == 0b000)):
                        with m.Switch(IS.funct7):
                            with m.Case(0b0101000):  # SHA512SUM0R
                                m.d.comb += [wb_en.eq(1), wb_data.eq(
                                    (ex1_a << 25) ^ (ex1_a << 30) ^ (ex1_a >> 28) ^
                                    (ex1_b >> 7) ^ (ex1_b >> 2) ^ (ex1_b << 4))]
                            with m.Case(0b0101001):  # SHA512SUM1R
                                m.d.comb += [wb_en.eq(1), wb_data.eq(
                                    (ex1_a << 23) ^ (ex1_a >> 14) ^ (ex1_a >> 18) ^
                                    (ex1_b >> 9) ^ (ex1_b << 18) ^ (ex1_b << 14))]
                            with m.Case(0b0101010):  # SHA512SIG0L
                                m.d.comb += [wb_en.eq(1), wb_data.eq(
                                    (ex1_a >> 1) ^ (ex1_a >> 7) ^ (ex1_a >> 8) ^
                                    (ex1_b << 31) ^ (ex1_b << 25) ^ (ex1_b << 24))]
                            with m.Case(0b0101110):  # SHA512SIG0H
                                m.d.comb += [wb_en.eq(1), wb_data.eq(
                                    (ex1_a >> 1) ^ (ex1_a >> 7) ^ (ex1_a >> 8) ^
                                    (ex1_b << 31) ^ (ex1_b << 24))]
                            with m.Case(0b0101011):  # SHA512SIG1L
                                m.d.comb += [wb_en.eq(1), wb_data.eq(
                                    (ex1_a << 3) ^ (ex1_a >> 6) ^ (ex1_a >> 19) ^
                                    (ex1_b >> 29) ^ (ex1_b << 26) ^ (ex1_b << 13))]
                            with m.Case(0b0101111):  # SHA512SIG1H
                                m.d.comb += [wb_en.eq(1), wb_data.eq(
                                    (ex1_a << 3) ^ (ex1_a >> 6) ^ (ex1_a >> 19) ^
                                    (ex1_b >> 29) ^ (ex1_b << 13))]
                    # RV32 scalar AES encryption and decryption operations.
                    aes_funct5 = IS.funct7[0:5]
                    with m.If((IS.funct3 == 0b000) & (
                        (self.enable_zkne & ((aes_funct5 == 0b10001) | (aes_funct5 == 0b10011))) |
                        (self.enable_zknd & ((aes_funct5 == 0b10101) | (aes_funct5 == 0b10111)))
                    )):
                        aes_inverse = (aes_funct5 == 0b10101) | (aes_funct5 == 0b10111)
                        aes_mix = (aes_funct5 == 0b10011) | (aes_funct5 == 0b10111)
                        m.d.comb += [
                            wb_en.eq(1),
                            wb_data.eq(aes32_result(
                                ex1_a, ex1_b, IS.funct7, inverse=aes_inverse, mix=aes_mix
                            )),
                        ]
                    # Zksed SM4 round and key-schedule operations.
                    sm4_funct5 = IS.funct7[0:5]
                    with m.If(self.enable_zksed & (IS.funct3 == 0b000) &
                              ((sm4_funct5 == 0b11000) | (sm4_funct5 == 0b11010))):
                        m.d.comb += [
                            wb_en.eq(1),
                            wb_data.eq(sm4_result(
                                ex1_a, ex1_b, IS.funct7,
                                key_schedule=(sm4_funct5 == 0b11010)
                            )),
                        ]
                with m.Case(OP_IMM_32):  # RV64 W-suffix immediate (adds still write low 32b for RV32 compatibility)
                    with m.If(self.xlen >= 64):
                        with m.If(IS.funct3 == 0b000):  # ADDIW
                            m.d.comb += [wb_en.eq(1), wb_data.eq(sign_extend((ex1_a[0:32] + IS.imm[0:12])[0:32], 32, self.xlen))]
                        with m.If(IS.funct3 == 0b001):  # SLLIW
                            m.d.comb += [wb_en.eq(1), wb_data.eq(sign_extend((ex1_a[0:32] << IS.imm[0:5])[0:32], 32, self.xlen))]
                        with m.If(IS.funct3 == 0b101):  # SRLIW / SRAIW
                            with m.If(IS.imm[5] == 0):
                                m.d.comb += [wb_en.eq(1), wb_data.eq(sign_extend((ex1_a[0:32] >> IS.imm[0:5])[0:32], 32, self.xlen))]
                            with m.Else():
                                m.d.comb += [wb_en.eq(1), wb_data.eq(sign_extend((ex1_a[0:32].as_signed() >> IS.imm[0:5])[0:32], 32, self.xlen))]
                with m.Case(OP_32):      # RV64 W-suffix R-type
                    with m.If(self.xlen >= 64):
                        with m.If(IS.funct7 == 0b0000000):
                            with m.If(IS.funct3 == 0b000):  # ADDW
                                m.d.comb += [wb_en.eq(1), wb_data.eq(sign_extend((ex1_a[0:32] + ex1_b[0:32])[0:32], 32, self.xlen))]
                            with m.If(IS.funct3 == 0b001):  # SLLW
                                m.d.comb += [wb_en.eq(1), wb_data.eq(sign_extend((ex1_a[0:32] << ex1_b[0:5])[0:32], 32, self.xlen))]
                            with m.If(IS.funct3 == 0b101):  # SRLW
                                m.d.comb += [wb_en.eq(1), wb_data.eq(sign_extend((ex1_a[0:32] >> ex1_b[0:5])[0:32], 32, self.xlen))]
                        with m.If(IS.funct7 == 0b0100000):
                            with m.If(IS.funct3 == 0b000):  # SUBW
                                m.d.comb += [wb_en.eq(1), wb_data.eq(sign_extend((ex1_a[0:32] - ex1_b[0:32])[0:32], 32, self.xlen))]
                            with m.If(IS.funct3 == 0b101):  # SRAW
                                m.d.comb += [wb_en.eq(1), wb_data.eq(sign_extend((ex1_a[0:32].as_signed() >> ex1_b[0:5])[0:32], 32, self.xlen))]
                        with m.If(self.enable_m & (IS.funct7 == 0b0000001)):
                            with m.If(IS.funct3 == 0b000):  # MULW
                                m.d.comb += [wb_en.eq(1), wb_data.eq(sign_extend((ex1_a[0:32] * ex1_b[0:32]) & 0xffffffff, 32, self.xlen))]
                            with m.If(IS.funct3 == 0b100):  # DIVW
                                divw_div = Signal(32)
                                m.d.comb += divw_div.eq(Mux(
                                    ex1_b[0:32] == 0,
                                    0xFFFFFFFF,
                                    Mux(
                                        (ex1_a[0:32] == 0x80000000) & (ex1_b[0:32] == 0xFFFFFFFF),
                                        0x80000000,
                                        (ex1_a[0:32].as_signed() // ex1_b[0:32].as_signed())
                                    )
                                ))
                                m.d.comb += [wb_en.eq(1), wb_data.eq(sign_extend(divw_div, 32, self.xlen))]
                            with m.If(IS.funct3 == 0b101):  # DIVUW
                                m.d.comb += [wb_en.eq(1), wb_data.eq(sign_extend(Mux(ex1_b[0:32] == 0, 0xFFFFFFFF, (ex1_a[0:32].as_unsigned() // ex1_b[0:32].as_unsigned())) & 0xffffffff, 32, self.xlen))]
                            with m.If(IS.funct3 == 0b110):  # REMW
                                m.d.comb += [wb_en.eq(1), wb_data.eq(sign_extend(Mux(
                                    ex1_b[0:32] == 0,
                                    ex1_a[0:32],
                                    (ex1_a[0:32].as_signed() - ((ex1_a[0:32].as_signed() // ex1_b[0:32].as_signed()) * ex1_b[0:32]))
                                ) & 0xffffffff, 32, self.xlen))]
                            with m.If(IS.funct3 == 0b111):  # REMUW
                                m.d.comb += [wb_en.eq(1), wb_data.eq(sign_extend(
                                    Mux(ex1_b[0:32] == 0, ex1_a[0:32], (ex1_a[0:32].as_unsigned() - ((ex1_a[0:32].as_unsigned() // ex1_b[0:32].as_unsigned()) * ex1_b[0:32]))
                                    ) & 0xffffffff,
                                    32,
                                    self.xlen))]
                with m.Case(LOAD_FP):
                    with m.If(self.enable_f | self.enable_d | self.enable_q):
                        with m.If((self.enable_f & (IS.funct3 == 0b010)) |
                                  (self.enable_zfhmin & ~self.use_finx & (IS.funct3 == 0b001))):
                            m.d.comb += [mem_addr.eq(ex1_a + IS.imm), fp_wb_en.eq(1)]
                        with m.If(self.enable_d & (IS.funct3 == 0b011)):
                            m.d.comb += [mem_addr.eq(ex1_a + IS.imm), fp_wb_en.eq(1)]
                        with m.If(self.enable_q & (IS.funct3 == 0b100)):
                            m.d.comb += [mem_addr.eq(ex1_a + IS.imm), fp_wb_en.eq(1)]
                with m.Case(STORE_FP):
                    with m.If(self.enable_f | self.enable_d | self.enable_q):
                        with m.If((self.enable_f & (IS.funct3 == 0b010)) |
                                  (self.enable_zfhmin & ~self.use_finx & (IS.funct3 == 0b001))):
                            m.d.comb += [
                                mem_addr.eq(ex1_a + IS.imm),
                                mem_wdata.eq(fp_ex1_b[0:32]),
                            ]
                        with m.If(self.enable_d & (IS.funct3 == 0b011)):
                            m.d.comb += [
                                mem_addr.eq(ex1_a + IS.imm),
                                mem_wdata.eq(fp_ex1_b[0:32]),
                                fp_mem_wdata.eq(fp_ex1_b),
                            ]
                        with m.If(self.enable_q & (IS.funct3 == 0b100)):
                            m.d.comb += [
                                mem_addr.eq(ex1_a + IS.imm),
                                mem_wdata.eq(fp_ex1_b[0:32]),
                                fp_mem_wdata.eq(fp_ex1_b),
                            ]
                with m.Case(OP_FP):
                    with m.If(self.enable_fp32 |
                              (self.enable_fp64 & (IS.funct7[0:2] == 0b01))):
                        with m.If(self.enable_zfa & self.enable_d & (IS.funct7 == 0b1111001) & (IS.funct3 == 0) & (IS.rs2 == 1)):  # FLI.D
                            m.d.comb += [fp_wb_en.eq(1), fp_wb_data.eq(zfa_fli_d[IS.rs1])]
                        with m.Elif(self.enable_zfa & self.enable_d & (IS.funct7 == 0b1110001) & (IS.funct3 == 0) & (IS.rs2 == 1)):  # FMVH.X.D
                            m.d.comb += [wb_en.eq(1), wb_data.eq(fp_ex1_a[32:64])]
                        with m.Elif(self.enable_zfa & self.enable_d & (IS.funct7 == 0b1011001) & (IS.funct3 == 0)):  # FMVP.D.X
                            m.d.comb += [fp_wb_en.eq(1), fp_wb_data.eq(Cat(ex1_a[0:32], ex1_b[0:32]))]
                        with m.Elif(self.enable_zfa & self.enable_d & (IS.funct7 == 0b0100001) &
                                    ((IS.rs2 == 4) | (IS.rs2 == 5))):  # FROUND.D / FROUNDNX.D
                            dround_exp = Signal(11)
                            dround_frac = Signal(52)
                            dround_sign = Signal()
                            dround_nan = Signal()
                            dround_snan = Signal()
                            dround_inf = Signal()
                            dround_zero = Signal()
                            dround_rm = Signal(3)
                            dround_rm_valid = Signal()
                            dround_mant = Signal(53)
                            dround_shamt = Signal(6)
                            dround_trunc = Signal(53)
                            dround_discarded = Signal(53)
                            dround_half = Signal(53)
                            dround_trunc_lsb = Signal()
                            dround_increment = Signal(54)
                            dround_rounded = Signal(54)
                            dround_inexact = Signal()
                            dround_result = Signal(64)
                            m.d.comb += [
                                dround_exp.eq(fp_ex1_a[52:63]),
                                dround_frac.eq(fp_ex1_a[0:52]),
                                dround_sign.eq(fp_ex1_a[63]),
                                dround_nan.eq((dround_exp == 0x7ff) & (dround_frac != 0)),
                                dround_snan.eq((dround_exp == 0x7ff) & (dround_frac != 0) & ~dround_frac[51]),
                                dround_inf.eq((dround_exp == 0x7ff) & (dround_frac == 0)),
                                dround_zero.eq((dround_exp == 0) & (dround_frac == 0)),
                                dround_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                dround_rm_valid.eq(dround_rm <= 0b100),
                                dround_mant.eq(Cat(dround_frac, C(1, 1))),
                                dround_shamt.eq(1075 - dround_exp),
                                dround_trunc.eq((dround_mant >> dround_shamt) << dround_shamt),
                                dround_discarded.eq(dround_mant - dround_trunc),
                                dround_half.eq(C(1, 53) << (dround_shamt - C(1, 6)).as_unsigned()),
                                dround_trunc_lsb.eq((dround_trunc >> dround_shamt)[0]),
                                dround_increment.eq(0),
                                dround_rounded.eq(dround_trunc + dround_increment),
                                dround_inexact.eq(
                                    ~(dround_nan | dround_inf | dround_zero) &
                                    ((dround_exp < 1023) |
                                     ((dround_exp < 1075) & (dround_discarded != 0)))
                                ),
                                dround_result.eq(fp_ex1_a),
                            ]
                            with m.If((dround_exp >= 1023) & (dround_exp < 1075)):
                                with m.Switch(dround_rm):
                                    with m.Case(0b000):  # RNE
                                        with m.If((dround_discarded > dround_half) |
                                                  ((dround_discarded == dround_half) & dround_trunc_lsb)):
                                            m.d.comb += dround_increment.eq(C(1, 54) << dround_shamt)
                                    with m.Case(0b001):  # RTZ
                                        pass
                                    with m.Case(0b010):  # RDN
                                        with m.If(dround_sign & (dround_discarded != 0)):
                                            m.d.comb += dround_increment.eq(C(1, 54) << dround_shamt)
                                    with m.Case(0b011):  # RUP
                                        with m.If(~dround_sign & (dround_discarded != 0)):
                                            m.d.comb += dround_increment.eq(C(1, 54) << dround_shamt)
                                    with m.Case(0b100):  # RMM
                                        with m.If(dround_discarded >= dround_half):
                                            m.d.comb += dround_increment.eq(C(1, 54) << dround_shamt)
                                m.d.comb += dround_result.eq(Mux(
                                    dround_rounded[53],
                                    Cat(C(0, 52), (dround_exp + 1)[0:11], dround_sign),
                                    Cat(dround_rounded[0:52], dround_exp, dround_sign),
                                ))
                            with m.Elif((dround_exp < 1023) & ~dround_zero):
                                dround_to_one = Signal()
                                m.d.comb += dround_to_one.eq(Mux(
                                    dround_rm == 0b000,
                                    (dround_exp == 1022) & (dround_frac != 0),
                                    Mux(
                                        dround_rm == 0b100,
                                        dround_exp == 1022,
                                        Mux(
                                            dround_rm == 0b010,
                                            dround_sign,
                                            Mux(dround_rm == 0b011, ~dround_sign, 0),
                                        ),
                                    ),
                                ))
                                m.d.comb += dround_result.eq(Mux(
                                    dround_to_one,
                                    Cat(C(0, 52), C(1023, 11), dround_sign),
                                    Cat(C(0, 63), dround_sign),
                                ))
                            with m.Elif(dround_nan):
                                m.d.comb += dround_result.eq(0x7ff8000000000000)
                            with m.If(dround_rm_valid):
                                m.d.comb += [fp_wb_en.eq(1), fp_wb_data.eq(dround_result)]
                                with m.If(dround_snan):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                                with m.Elif((IS.rs2 == 5) & dround_inexact):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                        with m.Elif(self.enable_q &
                                    (IS.funct7 == 0b0101111) &
                                    (IS.rs2 == 0)):  # FSQRT.Q
                            m.d.comb += [
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(qfsqrt.result),
                                fp_wb_q.eq(1),
                            ]
                            with m.If(qfsqrt.flags != 0):
                                m.d.sync += csr_fflags.eq(csr_fflags |
                                                         qfsqrt.flags)
                        with m.Elif(self.enable_q &
                                    (IS.funct7 == 0b0001111)):  # FDIV.Q
                            m.d.comb += [
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(qfdiv.result),
                                fp_wb_q.eq(1),
                            ]
                            with m.If(qfdiv.flags != 0):
                                m.d.sync += csr_fflags.eq(csr_fflags |
                                                         qfdiv.flags)
                        with m.Elif(self.enable_q &
                                    (IS.funct7 == 0b0001011)):  # FMUL.Q
                            m.d.comb += [
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(qfmul.result),
                                fp_wb_q.eq(1),
                            ]
                            with m.If(qfmul.flags != 0):
                                m.d.sync += csr_fflags.eq(csr_fflags |
                                                         qfmul.flags)
                        with m.Elif(self.enable_q &
                                    ((IS.funct7 == 0b0000011) |
                                     (IS.funct7 == 0b0000111))):  # FADD.Q / FSUB.Q
                            m.d.comb += [
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(qfadd.result),
                                fp_wb_q.eq(1),
                            ]
                            with m.If(qfadd.flags != 0):
                                m.d.sync += csr_fflags.eq(csr_fflags |
                                                         qfadd.flags)
                        with m.Elif(self.enable_q & self.enable_f &
                                    (IS.funct7 == 0b0100000) &
                                    (IS.rs2 == 3)):  # FCVT.S.Q
                            qs_exp = Signal(15)
                            qs_frac = Signal(112)
                            qs_sig = Signal(113)
                            qs_rm = Signal(3)
                            qs_shift = Signal(8)
                            qs_sexp = Signal(9)
                            qs_retained = Signal(25)
                            qs_guard = Signal()
                            qs_lower = Signal()
                            qs_discarded = Signal()
                            qs_increment = Signal()
                            qs_rounded = Signal(25)
                            qs_nan = Signal()
                            qs_snan = Signal()
                            qs_inf = Signal()
                            qs_zero = Signal()
                            qs_overflow = Signal()
                            qs_underflow = Signal()
                            qs_to_inf = Signal()
                            qs_final_exp = Signal(8)
                            qs_final_frac = Signal(23)
                            qs_result = Signal(32)
                            m.d.comb += [
                                qs_exp.eq(fp_ex1_a[112:127]),
                                qs_frac.eq(fp_ex1_a[0:112]),
                                qs_sig.eq(Cat(qs_frac, C(1, 1))),
                                qs_rm.eq(Mux(IS.funct3 == 0b111,
                                             csr_frm, IS.funct3)),
                                qs_shift.eq(0),
                                qs_sexp.eq(0),
                                qs_retained.eq(0),
                                qs_guard.eq(0),
                                qs_lower.eq(0),
                                qs_nan.eq((qs_exp == 0x7fff) & (qs_frac != 0)),
                                qs_snan.eq((qs_exp == 0x7fff) &
                                           (qs_frac != 0) & ~qs_frac[111]),
                                qs_inf.eq((qs_exp == 0x7fff) & (qs_frac == 0)),
                                qs_zero.eq((qs_exp == 0) & (qs_frac == 0)),
                            ]
                            with m.If((qs_exp >= 16257) & (qs_exp <= 16510)):
                                m.d.comb += [
                                    qs_shift.eq(89),
                                    qs_sexp.eq(qs_exp - 16256),
                                    qs_retained.eq(qs_sig >> 89),
                                    qs_guard.eq(qs_sig[88]),
                                    qs_lower.eq(qs_sig[0:88] != 0),
                                ]
                            with m.Elif((qs_exp >= 16233) & (qs_exp < 16257)):
                                m.d.comb += [
                                    qs_shift.eq(89 + (16257 - qs_exp)),
                                    qs_retained.eq(qs_sig >> qs_shift),
                                    qs_guard.eq((qs_sig >>
                                                 (qs_shift - 1).as_unsigned())[0]),
                                    qs_lower.eq((qs_sig &
                                        ((C(1, 113) <<
                                          (qs_shift - 1).as_unsigned()) - 1)) != 0),
                                ]
                            with m.Elif(~qs_zero & ~qs_nan & ~qs_inf &
                                        (qs_exp < 16233)):
                                m.d.comb += qs_lower.eq(1)
                            m.d.comb += [
                                qs_discarded.eq(qs_guard | qs_lower),
                                qs_increment.eq(Mux(
                                    qs_rm == 0b000,
                                    qs_guard & (qs_lower | qs_retained[0]),
                                    Mux(qs_rm == 0b001, 0,
                                    Mux(qs_rm == 0b010,
                                        fp_ex1_a[127] & qs_discarded,
                                    Mux(qs_rm == 0b011,
                                        ~fp_ex1_a[127] & qs_discarded,
                                    Mux(qs_rm == 0b100, qs_guard, 0)))))),
                                qs_rounded.eq(qs_retained + qs_increment),
                                qs_overflow.eq((qs_exp > 16510) |
                                    ((qs_sexp == 0xfe) & qs_rounded[24])),
                                qs_to_inf.eq((qs_rm == 0b000) |
                                             (qs_rm == 0b100) |
                                             ((qs_rm == 0b010) &
                                              fp_ex1_a[127]) |
                                             ((qs_rm == 0b011) &
                                              ~fp_ex1_a[127])),
                                qs_final_exp.eq(Mux(
                                    (qs_sexp == 0) & qs_rounded[23], 1,
                                    qs_sexp + qs_rounded[24])),
                                qs_final_frac.eq(Mux(
                                    qs_rounded[24], qs_rounded[1:24],
                                    qs_rounded[0:23])),
                                qs_underflow.eq(qs_discarded &
                                                (qs_final_exp == 0) &
                                                ~qs_overflow),
                                qs_result.eq(Cat(qs_final_frac, qs_final_exp,
                                                 fp_ex1_a[127])),
                            ]
                            with m.If(qs_nan):
                                m.d.comb += qs_result.eq(0x7fc00000)
                            with m.Elif(qs_inf):
                                m.d.comb += qs_result.eq(Cat(
                                    C(0, 23), C(0xff, 8), fp_ex1_a[127]))
                            with m.Elif(qs_zero):
                                m.d.comb += qs_result.eq(Cat(
                                    C(0, 31), fp_ex1_a[127]))
                            with m.Elif(qs_overflow):
                                m.d.comb += qs_result.eq(Cat(
                                    Mux(qs_to_inf, C(0, 23),
                                        C((1 << 23) - 1, 23)),
                                    Mux(qs_to_inf, C(0xff, 8), C(0xfe, 8)),
                                    fp_ex1_a[127]))
                            m.d.comb += [
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(Cat(qs_result, C(0xffffffff, 32))),
                            ]
                            with m.If(qs_snan):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                            with m.Elif(qs_overflow):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b00101)
                            with m.Elif(qs_underflow):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b00011)
                            with m.Elif(qs_discarded):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                        with m.Elif(self.enable_q & self.enable_d &
                                    (IS.funct7 == 0b0100001) &
                                    (IS.rs2 == 3)):  # FCVT.D.Q
                            qd_exp = Signal(15)
                            qd_frac = Signal(112)
                            qd_sig = Signal(113)
                            qd_rm = Signal(3)
                            qd_shift = Signal(8)
                            qd_dexp = Signal(12)
                            qd_retained = Signal(54)
                            qd_guard = Signal()
                            qd_lower = Signal()
                            qd_discarded = Signal()
                            qd_increment = Signal()
                            qd_rounded = Signal(54)
                            qd_nan = Signal()
                            qd_snan = Signal()
                            qd_inf = Signal()
                            qd_zero = Signal()
                            qd_overflow = Signal()
                            qd_underflow = Signal()
                            qd_to_inf = Signal()
                            qd_final_exp = Signal(11)
                            qd_final_frac = Signal(52)
                            qd_result = Signal(64)
                            m.d.comb += [
                                qd_exp.eq(fp_ex1_a[112:127]),
                                qd_frac.eq(fp_ex1_a[0:112]),
                                qd_sig.eq(Cat(qd_frac, C(1, 1))),
                                qd_rm.eq(Mux(IS.funct3 == 0b111,
                                             csr_frm, IS.funct3)),
                                qd_shift.eq(0),
                                qd_dexp.eq(0),
                                qd_retained.eq(0),
                                qd_guard.eq(0),
                                qd_lower.eq(0),
                                qd_nan.eq((qd_exp == 0x7fff) & (qd_frac != 0)),
                                qd_snan.eq((qd_exp == 0x7fff) &
                                           (qd_frac != 0) & ~qd_frac[111]),
                                qd_inf.eq((qd_exp == 0x7fff) & (qd_frac == 0)),
                                qd_zero.eq((qd_exp == 0) & (qd_frac == 0)),
                            ]
                            with m.If((qd_exp >= 15361) & (qd_exp <= 17406)):
                                m.d.comb += [
                                    qd_shift.eq(60),
                                    qd_dexp.eq(qd_exp - 15360),
                                    qd_retained.eq(qd_sig >> 60),
                                    qd_guard.eq(qd_sig[59]),
                                    qd_lower.eq(qd_sig[0:59] != 0),
                                ]
                            with m.Elif((qd_exp >= 15308) & (qd_exp < 15361)):
                                m.d.comb += [
                                    qd_shift.eq(60 + (15361 - qd_exp)),
                                    qd_retained.eq(qd_sig >> qd_shift),
                                    qd_guard.eq((qd_sig >>
                                                 (qd_shift - 1).as_unsigned())[0]),
                                    qd_lower.eq((qd_sig &
                                        ((C(1, 113) <<
                                          (qd_shift - 1).as_unsigned()) - 1)) != 0),
                                ]
                            with m.Elif(~qd_zero & ~qd_nan & ~qd_inf &
                                        (qd_exp < 15308)):
                                m.d.comb += qd_lower.eq(1)
                            m.d.comb += [
                                qd_discarded.eq(qd_guard | qd_lower),
                                qd_increment.eq(Mux(
                                    qd_rm == 0b000,
                                    qd_guard & (qd_lower | qd_retained[0]),
                                    Mux(qd_rm == 0b001, 0,
                                    Mux(qd_rm == 0b010,
                                        fp_ex1_a[127] & qd_discarded,
                                    Mux(qd_rm == 0b011,
                                        ~fp_ex1_a[127] & qd_discarded,
                                    Mux(qd_rm == 0b100, qd_guard, 0)))))),
                                qd_rounded.eq(qd_retained + qd_increment),
                                qd_overflow.eq((qd_exp > 17406) |
                                    ((qd_dexp == 0x7fe) & qd_rounded[53])),
                                qd_to_inf.eq((qd_rm == 0b000) |
                                             (qd_rm == 0b100) |
                                             ((qd_rm == 0b010) &
                                              fp_ex1_a[127]) |
                                             ((qd_rm == 0b011) &
                                              ~fp_ex1_a[127])),
                                qd_final_exp.eq(Mux(
                                    (qd_dexp == 0) & qd_rounded[52], 1,
                                    qd_dexp + qd_rounded[53])),
                                qd_final_frac.eq(Mux(
                                    qd_rounded[53], qd_rounded[1:53],
                                    qd_rounded[0:52])),
                                qd_underflow.eq(qd_discarded &
                                                (qd_final_exp == 0) &
                                                ~qd_overflow),
                                qd_result.eq(Cat(qd_final_frac, qd_final_exp,
                                                 fp_ex1_a[127])),
                            ]
                            with m.If(qd_nan):
                                m.d.comb += qd_result.eq(0x7ff8000000000000)
                            with m.Elif(qd_inf):
                                m.d.comb += qd_result.eq(Cat(
                                    C(0, 52), C(0x7ff, 11), fp_ex1_a[127]))
                            with m.Elif(qd_zero):
                                m.d.comb += qd_result.eq(Cat(
                                    C(0, 63), fp_ex1_a[127]))
                            with m.Elif(qd_overflow):
                                m.d.comb += qd_result.eq(Cat(
                                    Mux(qd_to_inf, C(0, 52),
                                        C((1 << 52) - 1, 52)),
                                    Mux(qd_to_inf, C(0x7ff, 11),
                                        C(0x7fe, 11)),
                                    fp_ex1_a[127]))
                            m.d.comb += [
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(qd_result),
                            ]
                            with m.If(qd_snan):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                            with m.Elif(qd_overflow):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b00101)
                            with m.Elif(qd_underflow):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b00011)
                            with m.Elif(qd_discarded):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                        with m.Elif(self.enable_q & (IS.funct7 == 0b0100011) &
                                    ((IS.rs2 == 0) |
                                     ((IS.rs2 == 1) & self.enable_d))):  # FCVT.Q.S / FCVT.Q.D
                            qfmt_result = Signal(128)
                            qfmt_invalid = Signal()
                            m.d.comb += [
                                qfmt_result.eq(C((0x7fff << 112) |
                                                 (1 << 111), 128)),
                                qfmt_invalid.eq(0),
                            ]
                            with m.If(IS.rs2 == 0):
                                qfmt_s_boxed = Signal()
                                qfmt_s_exp = Signal(8)
                                qfmt_s_frac = Signal(23)
                                qfmt_s_qexp = Signal(15)
                                m.d.comb += [
                                    qfmt_s_boxed.eq(fp_ex1_a[32:128].all()),
                                    qfmt_s_exp.eq(fp_ex1_a[23:31]),
                                    qfmt_s_frac.eq(fp_ex1_a[0:23]),
                                    qfmt_s_qexp.eq(qfmt_s_exp - 127 + 16383),
                                ]
                                with m.If(qfmt_s_boxed):
                                    with m.If(qfmt_s_exp == 0xff):
                                        with m.If(qfmt_s_frac == 0):
                                            m.d.comb += qfmt_result.eq(Cat(
                                                C(0, 112), C(0x7fff, 15),
                                                fp_ex1_a[31]))
                                        with m.Else():
                                            m.d.comb += qfmt_invalid.eq(
                                                ~qfmt_s_frac[22])
                                    with m.Elif(qfmt_s_exp == 0):
                                        with m.If(qfmt_s_frac == 0):
                                            m.d.comb += qfmt_result.eq(Cat(
                                                C(0, 127), fp_ex1_a[31]))
                                        with m.Else():
                                            for bit in range(23):
                                                qfmt_s_subfrac = Cat(
                                                    C(0, 112 - bit),
                                                    qfmt_s_frac[0:bit])
                                                with m.If(qfmt_s_frac[bit]):
                                                    m.d.comb += qfmt_result.eq(Cat(
                                                        qfmt_s_subfrac,
                                                        C(16383 + bit - 149, 15),
                                                        fp_ex1_a[31]))
                                    with m.Else():
                                        m.d.comb += qfmt_result.eq(Cat(
                                            C(0, 89), qfmt_s_frac,
                                            qfmt_s_qexp, fp_ex1_a[31]))
                            with m.Else():
                                qfmt_d_boxed = Signal()
                                qfmt_d_exp = Signal(11)
                                qfmt_d_frac = Signal(52)
                                qfmt_d_qexp = Signal(15)
                                m.d.comb += [
                                    qfmt_d_boxed.eq(fp_ex1_a[64:128].all()),
                                    qfmt_d_exp.eq(fp_ex1_a[52:63]),
                                    qfmt_d_frac.eq(fp_ex1_a[0:52]),
                                    qfmt_d_qexp.eq(qfmt_d_exp - 1023 + 16383),
                                ]
                                with m.If(qfmt_d_boxed):
                                    with m.If(qfmt_d_exp == 0x7ff):
                                        with m.If(qfmt_d_frac == 0):
                                            m.d.comb += qfmt_result.eq(Cat(
                                                C(0, 112), C(0x7fff, 15),
                                                fp_ex1_a[63]))
                                        with m.Else():
                                            m.d.comb += qfmt_invalid.eq(
                                                ~qfmt_d_frac[51])
                                    with m.Elif(qfmt_d_exp == 0):
                                        with m.If(qfmt_d_frac == 0):
                                            m.d.comb += qfmt_result.eq(Cat(
                                                C(0, 127), fp_ex1_a[63]))
                                        with m.Else():
                                            for bit in range(52):
                                                qfmt_d_subfrac = Cat(
                                                    C(0, 112 - bit),
                                                    qfmt_d_frac[0:bit])
                                                with m.If(qfmt_d_frac[bit]):
                                                    m.d.comb += qfmt_result.eq(Cat(
                                                        qfmt_d_subfrac,
                                                        C(16383 + bit - 1074, 15),
                                                        fp_ex1_a[63]))
                                    with m.Else():
                                        m.d.comb += qfmt_result.eq(Cat(
                                            C(0, 60), qfmt_d_frac,
                                            qfmt_d_qexp, fp_ex1_a[63]))
                            m.d.comb += [
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(qfmt_result),
                                fp_wb_q.eq(1),
                            ]
                            with m.If(qfmt_invalid):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                        with m.Elif(self.enable_q & (IS.funct7 == 0b1100011) &
                                    (IS.rs2 <= 1)):  # FCVT.W.Q / FCVT.WU.Q
                            qtoi_exp = Signal(15)
                            qtoi_frac = Signal(112)
                            qtoi_sig = Signal(113)
                            qtoi_shift = Signal(7)
                            qtoi_trunc = Signal(34)
                            qtoi_guard = Signal()
                            qtoi_lower = Signal()
                            qtoi_discarded = Signal()
                            qtoi_rm = Signal(3)
                            qtoi_increment = Signal()
                            qtoi_rounded = Signal(34)
                            qtoi_nan = Signal()
                            qtoi_inf = Signal()
                            qtoi_nonzero = Signal()
                            qtoi_invalid = Signal()
                            qtoi_result = Signal(32)
                            m.d.comb += [
                                qtoi_exp.eq(fp_ex1_a[112:127]),
                                qtoi_frac.eq(fp_ex1_a[0:112]),
                                qtoi_sig.eq(Cat(qtoi_frac, C(1, 1))),
                                qtoi_shift.eq(0),
                                qtoi_trunc.eq(0),
                                qtoi_guard.eq(0),
                                qtoi_lower.eq(0),
                                qtoi_rm.eq(Mux(IS.funct3 == 0b111,
                                              csr_frm, IS.funct3)),
                                qtoi_nan.eq((qtoi_exp == 0x7fff) &
                                            (qtoi_frac != 0)),
                                qtoi_inf.eq((qtoi_exp == 0x7fff) &
                                            (qtoi_frac == 0)),
                                qtoi_nonzero.eq((qtoi_exp != 0) |
                                               (qtoi_frac != 0)),
                            ]
                            with m.If((qtoi_exp >= 0x3fff) &
                                      (qtoi_exp <= (0x3fff + 31))):
                                m.d.comb += [
                                    qtoi_shift.eq(112 - (qtoi_exp - 0x3fff)),
                                    qtoi_trunc.eq(qtoi_sig >> qtoi_shift),
                                    qtoi_guard.eq((qtoi_sig >>
                                                   (qtoi_shift - 1).as_unsigned())[0]),
                                    qtoi_lower.eq((qtoi_sig &
                                        ((C(1, 113) <<
                                          (qtoi_shift - 1).as_unsigned()) - 1)) != 0),
                                ]
                            with m.Elif(qtoi_exp == (0x3fff - 1)):
                                m.d.comb += [
                                    qtoi_guard.eq(qtoi_nonzero),
                                    qtoi_lower.eq(qtoi_frac != 0),
                                ]
                            with m.Elif(qtoi_exp < (0x3fff - 1)):
                                m.d.comb += qtoi_lower.eq(qtoi_nonzero)
                            m.d.comb += [
                                qtoi_discarded.eq(qtoi_guard | qtoi_lower),
                                qtoi_increment.eq(Mux(
                                    qtoi_rm == 0b000,
                                    qtoi_guard & (qtoi_lower | qtoi_trunc[0]),
                                    Mux(qtoi_rm == 0b001, 0,
                                    Mux(qtoi_rm == 0b010,
                                        fp_ex1_a[127] & qtoi_discarded,
                                    Mux(qtoi_rm == 0b011,
                                        ~fp_ex1_a[127] & qtoi_discarded,
                                    Mux(qtoi_rm == 0b100,
                                        qtoi_guard, 0)))))),
                                qtoi_rounded.eq(qtoi_trunc + qtoi_increment),
                                qtoi_invalid.eq(
                                    qtoi_nan | qtoi_inf |
                                    (qtoi_exp > (0x3fff + 31)) |
                                    Mux(IS.rs2 == 0,
                                        Mux(fp_ex1_a[127],
                                            qtoi_rounded > 0x80000000,
                                            qtoi_rounded > 0x7fffffff),
                                        (fp_ex1_a[127] &
                                         (qtoi_rounded != 0)) |
                                        (qtoi_rounded > 0xffffffff))),
                                qtoi_result.eq(Mux(
                                    qtoi_invalid,
                                    Mux(IS.rs2 == 1,
                                        Mux(qtoi_nan | ~fp_ex1_a[127],
                                            0xffffffff, 0),
                                        Mux(qtoi_nan | ~fp_ex1_a[127],
                                            0x7fffffff, 0x80000000)),
                                    Mux(fp_ex1_a[127],
                                        -qtoi_rounded[0:32],
                                        qtoi_rounded[0:32]))),
                                wb_en.eq(1),
                                wb_data.eq(qtoi_result),
                            ]
                            with m.If(qtoi_invalid):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                            with m.Elif(qtoi_discarded):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                        with m.Elif(self.enable_q & (IS.funct7 == 0b1101011) &
                                    (IS.rs2 <= 1)):  # FCVT.Q.W / FCVT.Q.WU
                            qcvt_i_sign = Signal()
                            qcvt_i_mag = Signal(32)
                            qcvt_i_result = Signal(128)
                            m.d.comb += [
                                qcvt_i_sign.eq((IS.rs2 == 0) & ex1_a[31]),
                                qcvt_i_mag.eq(Mux((IS.rs2 == 0) & ex1_a[31],
                                                 -ex1_a[0:32], ex1_a[0:32])),
                                qcvt_i_result.eq(0),
                            ]
                            for bit in range(32):
                                qcvt_i_frac = Cat(C(0, 112 - bit), qcvt_i_mag[0:bit])
                                with m.If(qcvt_i_mag[bit]):
                                    m.d.comb += qcvt_i_result.eq(Cat(
                                        qcvt_i_frac,
                                        C(16383 + bit, 15),
                                        qcvt_i_sign,
                                    ))
                            m.d.comb += [
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(qcvt_i_result),
                                fp_wb_q.eq(1),
                            ]
                        with m.Elif(self.enable_q & (IS.funct7 == 0b0010011) &
                                    (IS.funct3 <= 0b010)):  # FSGNJ.Q / FSGNJN.Q / FSGNJX.Q
                            q_fsgnj_sign = Signal()
                            q_fsgnj_word = Signal(128)
                            m.d.comb += [
                                q_fsgnj_sign.eq(Mux(
                                    IS.funct3 == 0b000,
                                    fp_ex1_b[127],
                                    Mux(
                                        IS.funct3 == 0b001,
                                        ~fp_ex1_b[127],
                                        fp_ex1_a[127] ^ fp_ex1_b[127],
                                    ),
                                )),
                                q_fsgnj_word.eq(Cat(fp_ex1_a[0:127], q_fsgnj_sign)),
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(q_fsgnj_word),
                                fp_wb_q.eq(1),
                            ]
                        with m.Elif(self.enable_fp64 & (IS.funct7 == 0b0010001)):  # FSGNJ.D / FSGNJN.D / FSGNJX.D
                            d_fsgnj_sign = Signal()
                            d_fsgnj_word = Signal(64)
                            m.d.comb += [
                                d_fsgnj_sign.eq(Mux(
                                    IS.funct3 == 0b000,
                                    fp_ex1_b[63],
                                    Mux(
                                        IS.funct3 == 0b001,
                                        ~fp_ex1_b[63],
                                        fp_ex1_a[63] ^ fp_ex1_b[63],
                                    ),
                                )),
                                d_fsgnj_word.eq(Cat(fp_ex1_a[0:63], d_fsgnj_sign)),
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(d_fsgnj_word),
                            ]
                        with m.Elif(self.enable_q & (IS.funct7 == 0b1110011) &
                                    (IS.funct3 == 0b001) &
                                    (IS.rs2 == 0)):  # FCLASS.Q
                            qclass_exp = Signal(15)
                            qclass_frac = Signal(112)
                            qclass = Signal(self.xlen)
                            m.d.comb += [
                                qclass_exp.eq(fp_ex1_a[112:127]),
                                qclass_frac.eq(fp_ex1_a[0:112]),
                                qclass.eq(0),
                            ]
                            with m.If((qclass_exp == 0x7fff) & (qclass_frac == 0)):
                                m.d.comb += qclass.eq(Mux(fp_ex1_a[127], 1 << 0, 1 << 7))
                            with m.Elif((qclass_exp == 0x7fff) & (qclass_frac != 0)):
                                m.d.comb += qclass.eq(Mux(qclass_frac[111], 1 << 9, 1 << 8))
                            with m.Elif((qclass_exp == 0) & (qclass_frac == 0)):
                                m.d.comb += qclass.eq(Mux(fp_ex1_a[127], 1 << 3, 1 << 4))
                            with m.Elif((qclass_exp == 0) & (qclass_frac != 0)):
                                m.d.comb += qclass.eq(Mux(fp_ex1_a[127], 1 << 2, 1 << 5))
                            with m.Else():
                                m.d.comb += qclass.eq(Mux(fp_ex1_a[127], 1 << 1, 1 << 6))
                            m.d.comb += [wb_en.eq(1), wb_data.eq(qclass)]
                        with m.Elif(self.enable_q & (IS.funct7 == 0b1010011) &
                                    (IS.funct3 <= 0b010)):  # FLE.Q / FLT.Q / FEQ.Q
                            qcmp_a_exp = Signal(15)
                            qcmp_b_exp = Signal(15)
                            qcmp_a_frac = Signal(112)
                            qcmp_b_frac = Signal(112)
                            qcmp_a_nan = Signal()
                            qcmp_b_nan = Signal()
                            qcmp_a_snan = Signal()
                            qcmp_b_snan = Signal()
                            qcmp_a_zero = Signal()
                            qcmp_b_zero = Signal()
                            qcmp_eq = Signal()
                            qcmp_lt = Signal()
                            qcmp_result = Signal()
                            qcmp_invalid = Signal()
                            m.d.comb += [
                                qcmp_a_exp.eq(fp_ex1_a[112:127]),
                                qcmp_b_exp.eq(fp_ex1_b[112:127]),
                                qcmp_a_frac.eq(fp_ex1_a[0:112]),
                                qcmp_b_frac.eq(fp_ex1_b[0:112]),
                                qcmp_a_nan.eq((qcmp_a_exp == 0x7fff) & (qcmp_a_frac != 0)),
                                qcmp_b_nan.eq((qcmp_b_exp == 0x7fff) & (qcmp_b_frac != 0)),
                                qcmp_a_snan.eq(qcmp_a_nan & ~qcmp_a_frac[111]),
                                qcmp_b_snan.eq(qcmp_b_nan & ~qcmp_b_frac[111]),
                                qcmp_a_zero.eq(fp_ex1_a[0:127] == 0),
                                qcmp_b_zero.eq(fp_ex1_b[0:127] == 0),
                                qcmp_eq.eq(~(qcmp_a_nan | qcmp_b_nan) &
                                           Mux(qcmp_a_zero & qcmp_b_zero, 1,
                                               fp_ex1_a == fp_ex1_b)),
                                qcmp_lt.eq(
                                    ~(qcmp_a_nan | qcmp_b_nan | qcmp_eq) &
                                    Mux(fp_ex1_a[127] != fp_ex1_b[127],
                                        fp_ex1_a[127],
                                        Mux(fp_ex1_a[127],
                                            fp_ex1_a[0:127] > fp_ex1_b[0:127],
                                            fp_ex1_a[0:127] < fp_ex1_b[0:127]))),
                                qcmp_result.eq(Mux(
                                    IS.funct3 == 0b010, qcmp_eq,
                                    Mux(IS.funct3 == 0b001, qcmp_lt,
                                        qcmp_lt | qcmp_eq))),
                                qcmp_invalid.eq(Mux(
                                    IS.funct3 == 0b010,
                                    qcmp_a_snan | qcmp_b_snan,
                                    qcmp_a_nan | qcmp_b_nan)),
                                wb_en.eq(1),
                                wb_data.eq(qcmp_result),
                            ]
                            with m.If(qcmp_invalid):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                        with m.Elif(self.enable_q & (IS.funct7 == 0b0010111) &
                                    (IS.funct3 <= 0b001)):  # FMIN.Q / FMAX.Q
                            qmm_a_exp = Signal(15)
                            qmm_b_exp = Signal(15)
                            qmm_a_frac = Signal(112)
                            qmm_b_frac = Signal(112)
                            qmm_a_nan = Signal()
                            qmm_b_nan = Signal()
                            qmm_a_snan = Signal()
                            qmm_b_snan = Signal()
                            qmm_a_zero = Signal()
                            qmm_b_zero = Signal()
                            qmm_eq = Signal()
                            qmm_a_lt_b = Signal()
                            qmm_b_lt_a = Signal()
                            qmm_min_select_a = Signal()
                            qmm_max_select_a = Signal()
                            qmm_result = Signal(128)
                            m.d.comb += [
                                qmm_a_exp.eq(fp_ex1_a[112:127]),
                                qmm_b_exp.eq(fp_ex1_b[112:127]),
                                qmm_a_frac.eq(fp_ex1_a[0:112]),
                                qmm_b_frac.eq(fp_ex1_b[0:112]),
                                qmm_a_nan.eq((qmm_a_exp == 0x7fff) & (qmm_a_frac != 0)),
                                qmm_b_nan.eq((qmm_b_exp == 0x7fff) & (qmm_b_frac != 0)),
                                qmm_a_snan.eq(qmm_a_nan & ~qmm_a_frac[111]),
                                qmm_b_snan.eq(qmm_b_nan & ~qmm_b_frac[111]),
                                qmm_a_zero.eq(fp_ex1_a[0:127] == 0),
                                qmm_b_zero.eq(fp_ex1_b[0:127] == 0),
                                qmm_eq.eq(Mux(qmm_a_zero & qmm_b_zero, 1,
                                             fp_ex1_a == fp_ex1_b)),
                                qmm_a_lt_b.eq(
                                    ~(qmm_a_nan | qmm_b_nan | qmm_eq) &
                                    Mux(fp_ex1_a[127] != fp_ex1_b[127],
                                        fp_ex1_a[127],
                                        Mux(fp_ex1_a[127],
                                            fp_ex1_a[0:127] > fp_ex1_b[0:127],
                                            fp_ex1_a[0:127] < fp_ex1_b[0:127]))),
                                qmm_b_lt_a.eq(
                                    ~(qmm_a_nan | qmm_b_nan | qmm_eq) &
                                    Mux(fp_ex1_a[127] != fp_ex1_b[127],
                                        fp_ex1_b[127],
                                        Mux(fp_ex1_b[127],
                                            fp_ex1_b[0:127] > fp_ex1_a[0:127],
                                            fp_ex1_b[0:127] < fp_ex1_a[0:127]))),
                                qmm_min_select_a.eq(Mux(
                                    qmm_a_zero & qmm_b_zero, fp_ex1_a[127],
                                    qmm_a_lt_b | qmm_eq)),
                                qmm_max_select_a.eq(Mux(
                                    qmm_a_zero & qmm_b_zero, ~fp_ex1_a[127],
                                    qmm_b_lt_a | qmm_eq)),
                                qmm_result.eq(Mux(
                                    qmm_a_nan & qmm_b_nan,
                                    C(0x7fff8000000000000000000000000000, 128),
                                    Mux(qmm_a_nan, fp_ex1_b,
                                        Mux(qmm_b_nan, fp_ex1_a,
                                            Mux(Mux(IS.funct3 == 0,
                                                    qmm_min_select_a,
                                                    qmm_max_select_a),
                                                fp_ex1_a, fp_ex1_b))))),
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(qmm_result),
                                fp_wb_q.eq(1),
                            ]
                            with m.If(qmm_a_snan | qmm_b_snan):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                        with m.Elif(self.enable_fp64 & (IS.funct7 == 0b0010101) & (
                            (IS.funct3[1] == 0) | (self.enable_zfa & (IS.funct3[1:3] == 0b01))
                        )):  # FMIN.D / FMAX.D / FMINM.D / FMAXM.D
                            dminmax_a_exp = Signal(11)
                            dminmax_b_exp = Signal(11)
                            dminmax_a_frac = Signal(52)
                            dminmax_b_frac = Signal(52)
                            dminmax_a_nan = Signal()
                            dminmax_b_nan = Signal()
                            dminmax_a_snan = Signal()
                            dminmax_b_snan = Signal()
                            dminmax_a_zero = Signal()
                            dminmax_b_zero = Signal()
                            dminmax_eq = Signal()
                            dminmax_a_lt_b = Signal()
                            dminmax_b_lt_a = Signal()
                            dmin_select_a = Signal()
                            dmax_select_a = Signal()
                            dminmax_result = Signal(64)
                            m.d.comb += [
                                dminmax_a_exp.eq(fp_ex1_a[52:63]),
                                dminmax_b_exp.eq(fp_ex1_b[52:63]),
                                dminmax_a_frac.eq(fp_ex1_a[0:52]),
                                dminmax_b_frac.eq(fp_ex1_b[0:52]),
                                dminmax_a_nan.eq((dminmax_a_exp == 0x7ff) & (dminmax_a_frac != 0)),
                                dminmax_b_nan.eq((dminmax_b_exp == 0x7ff) & (dminmax_b_frac != 0)),
                                dminmax_a_snan.eq((dminmax_a_exp == 0x7ff) & (dminmax_a_frac != 0) & ~dminmax_a_frac[51]),
                                dminmax_b_snan.eq((dminmax_b_exp == 0x7ff) & (dminmax_b_frac != 0) & ~dminmax_b_frac[51]),
                                dminmax_a_zero.eq(fp_ex1_a[0:63] == 0),
                                dminmax_b_zero.eq(fp_ex1_b[0:63] == 0),
                                dminmax_eq.eq(Mux(dminmax_a_zero & dminmax_b_zero, 1, fp_ex1_a == fp_ex1_b)),
                                dminmax_a_lt_b.eq(
                                    ~(dminmax_a_nan | dminmax_b_nan) &
                                    ~(dminmax_a_zero & dminmax_b_zero) &
                                    Mux(
                                        fp_ex1_a[63] != fp_ex1_b[63],
                                        fp_ex1_a[63] & ~fp_ex1_b[63],
                                        Mux(
                                            fp_ex1_a[63],
                                            fp_ex1_a[0:63] > fp_ex1_b[0:63],
                                            fp_ex1_a[0:63] < fp_ex1_b[0:63],
                                        ),
                                    )
                                ),
                                dminmax_b_lt_a.eq(
                                    ~(dminmax_a_nan | dminmax_b_nan) &
                                    ~(dminmax_a_zero & dminmax_b_zero) &
                                    Mux(
                                        fp_ex1_b[63] != fp_ex1_a[63],
                                        fp_ex1_b[63] & ~fp_ex1_a[63],
                                        Mux(
                                            fp_ex1_b[63],
                                            fp_ex1_b[0:63] > fp_ex1_a[0:63],
                                            fp_ex1_b[0:63] < fp_ex1_a[0:63],
                                        ),
                                    )
                                ),
                                dmin_select_a.eq(Mux(dminmax_a_zero & dminmax_b_zero, fp_ex1_a[63], dminmax_a_lt_b | dminmax_eq)),
                                dmax_select_a.eq(Mux(dminmax_a_zero & dminmax_b_zero, ~fp_ex1_a[63], dminmax_b_lt_a | dminmax_eq)),
                                dminmax_result.eq(Mux(
                                    IS.funct3[1] & (dminmax_a_nan | dminmax_b_nan),
                                    0x7ff8000000000000,
                                    Mux(
                                        dminmax_a_nan & dminmax_b_nan,
                                        0x7ff8000000000000,
                                        Mux(
                                            dminmax_a_nan,
                                            fp_ex1_b,
                                            Mux(
                                                dminmax_b_nan,
                                                fp_ex1_a,
                                                Mux(
                                                    IS.funct3[0] == 0,
                                                    Mux(dmin_select_a, fp_ex1_a, fp_ex1_b),
                                                    Mux(dmax_select_a, fp_ex1_a, fp_ex1_b),
                                                ),
                                            ),
                                        ),
                                    ),
                                )),
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(dminmax_result),
                            ]
                            with m.If(dminmax_a_snan | dminmax_b_snan):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                        with m.Elif(self.enable_fp64 & (IS.funct7 == 0b1010001) & (
                            (IS.funct3 <= 0b010) | (self.enable_zfa & ((IS.funct3 == 0b100) | (IS.funct3 == 0b101)))
                        )):  # FLE.D / FLT.D / FEQ.D / FLEQ.D / FLTQ.D
                            dcmp_a_exp = Signal(11)
                            dcmp_b_exp = Signal(11)
                            dcmp_a_frac = Signal(52)
                            dcmp_b_frac = Signal(52)
                            dcmp_a_nan = Signal()
                            dcmp_b_nan = Signal()
                            dcmp_a_snan = Signal()
                            dcmp_b_snan = Signal()
                            dcmp_a_zero = Signal()
                            dcmp_b_zero = Signal()
                            dcmp_eq = Signal()
                            dcmp_lt = Signal()
                            dcmp_result = Signal()
                            m.d.comb += [
                                dcmp_a_exp.eq(fp_ex1_a[52:63]),
                                dcmp_b_exp.eq(fp_ex1_b[52:63]),
                                dcmp_a_frac.eq(fp_ex1_a[0:52]),
                                dcmp_b_frac.eq(fp_ex1_b[0:52]),
                                dcmp_a_nan.eq((dcmp_a_exp == 0x7ff) & (dcmp_a_frac != 0)),
                                dcmp_b_nan.eq((dcmp_b_exp == 0x7ff) & (dcmp_b_frac != 0)),
                                dcmp_a_snan.eq((dcmp_a_exp == 0x7ff) & (dcmp_a_frac != 0) & ~dcmp_a_frac[51]),
                                dcmp_b_snan.eq((dcmp_b_exp == 0x7ff) & (dcmp_b_frac != 0) & ~dcmp_b_frac[51]),
                                dcmp_a_zero.eq(fp_ex1_a[0:63] == 0),
                                dcmp_b_zero.eq(fp_ex1_b[0:63] == 0),
                                dcmp_eq.eq(~(dcmp_a_nan | dcmp_b_nan) & Mux(dcmp_a_zero & dcmp_b_zero, 1, fp_ex1_a == fp_ex1_b)),
                                dcmp_lt.eq(
                                    ~(dcmp_a_nan | dcmp_b_nan) &
                                    ~(dcmp_a_zero & dcmp_b_zero) &
                                    Mux(
                                        fp_ex1_a[63] != fp_ex1_b[63],
                                        fp_ex1_a[63] & ~fp_ex1_b[63],
                                        Mux(
                                            fp_ex1_a[63],
                                            fp_ex1_a[0:63] > fp_ex1_b[0:63],
                                            fp_ex1_a[0:63] < fp_ex1_b[0:63],
                                        ),
                                    )
                                ),
                                dcmp_result.eq(Mux(
                                    IS.funct3 == 0b010,
                                    dcmp_eq,
                                    Mux((IS.funct3 == 0b001) | (IS.funct3 == 0b101), dcmp_lt, dcmp_lt | dcmp_eq),
                                )),
                                wb_en.eq(1),
                                wb_data.eq(dcmp_result),
                            ]
                            with m.If(Mux(
                                (IS.funct3 == 0b010) | IS.funct3[2],
                                dcmp_a_snan | dcmp_b_snan,
                                dcmp_a_nan | dcmp_b_nan,
                            )):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                        with m.Elif(self.enable_fp64 & (IS.funct7 == 0b0001001)):  # FMUL.D
                            dmul_a_sign = Signal()
                            dmul_b_sign = Signal()
                            dmul_sign = Signal()
                            dmul_a_exp = Signal(11)
                            dmul_b_exp = Signal(11)
                            dmul_a_frac = Signal(52)
                            dmul_b_frac = Signal(52)
                            dmul_a_nan = Signal()
                            dmul_b_nan = Signal()
                            dmul_a_snan = Signal()
                            dmul_b_snan = Signal()
                            dmul_a_inf = Signal()
                            dmul_b_inf = Signal()
                            dmul_a_zero = Signal()
                            dmul_b_zero = Signal()
                            dmul_a_mant = Signal(53)
                            dmul_b_mant = Signal(53)
                            dmul_prod = Signal(106)
                            dmul_exp_base = Signal(12)
                            dmul_exp = Signal(11)
                            dmul_frac = Signal(52)
                            dmul_result = Signal(64)
                            m.d.comb += [
                                dmul_a_sign.eq(fp_ex1_a[63]),
                                dmul_b_sign.eq(fp_ex1_b[63]),
                                dmul_sign.eq(fp_ex1_a[63] ^ fp_ex1_b[63]),
                                dmul_a_exp.eq(fp_ex1_a[52:63]),
                                dmul_b_exp.eq(fp_ex1_b[52:63]),
                                dmul_a_frac.eq(fp_ex1_a[0:52]),
                                dmul_b_frac.eq(fp_ex1_b[0:52]),
                                dmul_a_nan.eq((dmul_a_exp == 0x7ff) & (dmul_a_frac != 0)),
                                dmul_b_nan.eq((dmul_b_exp == 0x7ff) & (dmul_b_frac != 0)),
                                dmul_a_snan.eq((dmul_a_exp == 0x7ff) & (dmul_a_frac != 0) & ~dmul_a_frac[51]),
                                dmul_b_snan.eq((dmul_b_exp == 0x7ff) & (dmul_b_frac != 0) & ~dmul_b_frac[51]),
                                dmul_a_inf.eq((dmul_a_exp == 0x7ff) & (dmul_a_frac == 0)),
                                dmul_b_inf.eq((dmul_b_exp == 0x7ff) & (dmul_b_frac == 0)),
                                dmul_a_zero.eq(fp_ex1_a[0:63] == 0),
                                dmul_b_zero.eq(fp_ex1_b[0:63] == 0),
                                dmul_a_mant.eq(Cat(dmul_a_frac, Mux(dmul_a_exp == 0, 0, 1))),
                                dmul_b_mant.eq(Cat(dmul_b_frac, Mux(dmul_b_exp == 0, 0, 1))),
                                dmul_prod.eq(dmul_a_mant * dmul_b_mant),
                                dmul_exp_base.eq(dmul_a_exp + dmul_b_exp - 1023),
                                dmul_exp.eq(Mux(dmul_prod[105], dmul_exp_base + 1, dmul_exp_base)),
                                dmul_frac.eq(Mux(dmul_prod[105], dmul_prod[53:105], dmul_prod[52:104])),
                                dmul_result.eq(Cat(dmul_frac, dmul_exp, dmul_sign)),
                            ]
                            with m.If(dmul_a_nan | dmul_b_nan | ((dmul_a_zero | dmul_b_zero) & ((dmul_a_exp == 0x7ff) | (dmul_b_exp == 0x7ff)))):
                                m.d.comb += dmul_result.eq(0x7ff8000000000000)
                            with m.Elif(dmul_a_inf | dmul_b_inf):
                                m.d.comb += dmul_result.eq(Cat(C(0, 52), C(0x7ff, 11), dmul_sign))
                            with m.Elif(dmul_a_zero | dmul_b_zero):
                                m.d.comb += dmul_result.eq(Cat(C(0, 63), dmul_sign))
                            with m.If(dmul_a_snan | dmul_b_snan | (dmul_a_zero & dmul_b_inf) | (dmul_b_zero & dmul_a_inf)):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                            m.d.comb += [fp_wb_en.eq(1), fp_wb_data.eq(dmul_result)]
                        with m.Elif(self.enable_fp64 & (IS.funct7 == 0b0001101)):  # FDIV.D
                            ddiv_a_sign = Signal()
                            ddiv_b_sign = Signal()
                            ddiv_sign = Signal()
                            ddiv_a_exp = Signal(11)
                            ddiv_b_exp = Signal(11)
                            ddiv_a_frac = Signal(52)
                            ddiv_b_frac = Signal(52)
                            ddiv_a_nan = Signal()
                            ddiv_b_nan = Signal()
                            ddiv_a_snan = Signal()
                            ddiv_b_snan = Signal()
                            ddiv_a_inf = Signal()
                            ddiv_b_inf = Signal()
                            ddiv_a_zero = Signal()
                            ddiv_b_zero = Signal()
                            ddiv_a_mant = Signal(53)
                            ddiv_b_mant = Signal(53)
                            ddiv_quot = Signal(106)
                            ddiv_exp_base = Signal(12)
                            ddiv_exp = Signal(11)
                            ddiv_frac = Signal(52)
                            ddiv_result = Signal(64)
                            m.d.comb += [
                                ddiv_a_sign.eq(fp_ex1_a[63]),
                                ddiv_b_sign.eq(fp_ex1_b[63]),
                                ddiv_sign.eq(fp_ex1_a[63] ^ fp_ex1_b[63]),
                                ddiv_a_exp.eq(fp_ex1_a[52:63]),
                                ddiv_b_exp.eq(fp_ex1_b[52:63]),
                                ddiv_a_frac.eq(fp_ex1_a[0:52]),
                                ddiv_b_frac.eq(fp_ex1_b[0:52]),
                                ddiv_a_nan.eq((ddiv_a_exp == 0x7ff) & (ddiv_a_frac != 0)),
                                ddiv_b_nan.eq((ddiv_b_exp == 0x7ff) & (ddiv_b_frac != 0)),
                                ddiv_a_snan.eq((ddiv_a_exp == 0x7ff) & (ddiv_a_frac != 0) & ~ddiv_a_frac[51]),
                                ddiv_b_snan.eq((ddiv_b_exp == 0x7ff) & (ddiv_b_frac != 0) & ~ddiv_b_frac[51]),
                                ddiv_a_inf.eq((ddiv_a_exp == 0x7ff) & (ddiv_a_frac == 0)),
                                ddiv_b_inf.eq((ddiv_b_exp == 0x7ff) & (ddiv_b_frac == 0)),
                                ddiv_a_zero.eq(fp_ex1_a[0:63] == 0),
                                ddiv_b_zero.eq(fp_ex1_b[0:63] == 0),
                                ddiv_a_mant.eq(Cat(ddiv_a_frac, Mux(ddiv_a_exp == 0, 0, 1))),
                                ddiv_b_mant.eq(Cat(ddiv_b_frac, Mux(ddiv_b_exp == 0, 0, 1))),
                                ddiv_quot.eq(Mux(ddiv_b_mant == 0, 0, (ddiv_a_mant << 52) // ddiv_b_mant)),
                                ddiv_exp_base.eq(ddiv_a_exp - ddiv_b_exp + 1023),
                                ddiv_exp.eq(Mux(ddiv_quot[52], ddiv_exp_base, ddiv_exp_base - 1)),
                                ddiv_frac.eq(Mux(ddiv_quot[52], ddiv_quot[0:52], ddiv_quot[0:52] << 1)),
                                ddiv_result.eq(Cat(ddiv_frac, ddiv_exp, ddiv_sign)),
                            ]
                            with m.If(ddiv_a_nan | ddiv_b_nan | (ddiv_a_zero & ddiv_b_zero) | (ddiv_a_inf & ddiv_b_inf)):
                                m.d.comb += ddiv_result.eq(0x7ff8000000000000)
                            with m.Elif(ddiv_b_zero):
                                m.d.comb += ddiv_result.eq(Cat(C(0, 52), C(0x7ff, 11), ddiv_sign))
                            with m.Elif(ddiv_a_zero):
                                m.d.comb += ddiv_result.eq(Cat(C(0, 63), ddiv_sign))
                            with m.Elif(ddiv_a_inf):
                                m.d.comb += ddiv_result.eq(Cat(C(0, 52), C(0x7ff, 11), ddiv_sign))
                            with m.Elif(ddiv_b_inf):
                                m.d.comb += ddiv_result.eq(Cat(C(0, 63), ddiv_sign))
                            with m.If(ddiv_a_snan | ddiv_b_snan | (ddiv_a_zero & ddiv_b_zero) | (ddiv_a_inf & ddiv_b_inf)):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                            with m.Elif(~ddiv_a_nan & ~ddiv_a_inf & ~ddiv_a_zero & ddiv_b_zero):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b01000)
                            m.d.comb += [fp_wb_en.eq(1), fp_wb_data.eq(ddiv_result)]
                        with m.Elif(self.enable_fp64 & ((IS.funct7 == 0b0000001) | (IS.funct7 == 0b0000101))):  # FADD.D / FSUB.D
                            da_sign = Signal()
                            db_sign = Signal()
                            db_eff_sign = Signal()
                            da_exp = Signal(11)
                            db_exp = Signal(11)
                            da_frac = Signal(52)
                            db_frac = Signal(52)
                            da_nan = Signal()
                            db_nan = Signal()
                            da_snan = Signal()
                            db_snan = Signal()
                            da_inf = Signal()
                            db_inf = Signal()
                            dadd_invalid = Signal()
                            da_zero = Signal()
                            db_zero = Signal()
                            da_mant = Signal(53)
                            db_mant = Signal(53)
                            da_mag_ge = Signal()
                            dlarger_sign = Signal()
                            dlarger_exp = Signal(11)
                            dsmaller_exp = Signal(11)
                            dlarger_mant = Signal(53)
                            dsmaller_mant = Signal(53)
                            dexp_delta = Signal(11)
                            dshifted_small = Signal(53)
                            dsame_sign = Signal()
                            dadd_sum = Signal(54)
                            ddiff_mant = Signal(53)
                            dalign_remainder = Signal(53)
                            dalign_half = Signal(53)
                            dadd_inexact = Signal()
                            dadd_rm = Signal(3)
                            dadd_rm_valid = Signal()
                            dround_nearest = Signal()
                            dround_rmm = Signal()
                            dfinite = Signal()
                            dfinite_sign = Signal()
                            dadjust_up = Signal()
                            dadjust_down = Signal()
                            dbase_mag = Signal(63)
                            drounded_mag = Signal(63)
                            daddsub_result = Signal(64)
                            daddsub_final = Signal(64)
                            m.d.comb += [
                                da_sign.eq(fp_ex1_a[63]),
                                db_sign.eq(fp_ex1_b[63]),
                                db_eff_sign.eq(fp_ex1_b[63] ^ (IS.funct7 == 0b0000101)),
                                da_exp.eq(fp_ex1_a[52:63]),
                                db_exp.eq(fp_ex1_b[52:63]),
                                da_frac.eq(fp_ex1_a[0:52]),
                                db_frac.eq(fp_ex1_b[0:52]),
                                da_nan.eq((da_exp == 0x7ff) & (da_frac != 0)),
                                db_nan.eq((db_exp == 0x7ff) & (db_frac != 0)),
                                da_snan.eq((da_exp == 0x7ff) & (da_frac != 0) & ~da_frac[51]),
                                db_snan.eq((db_exp == 0x7ff) & (db_frac != 0) & ~db_frac[51]),
                                da_inf.eq((da_exp == 0x7ff) & (da_frac == 0)),
                                db_inf.eq((db_exp == 0x7ff) & (db_frac == 0)),
                                dadd_invalid.eq(da_snan | db_snan | (da_inf & db_inf & (da_sign != db_eff_sign))),
                                da_zero.eq(fp_ex1_a[0:63] == 0),
                                db_zero.eq(fp_ex1_b[0:63] == 0),
                                da_mant.eq(Cat(da_frac, Mux(da_exp == 0, 0, 1))),
                                db_mant.eq(Cat(db_frac, Mux(db_exp == 0, 0, 1))),
                                da_mag_ge.eq((da_exp > db_exp) | ((da_exp == db_exp) & (da_frac >= db_frac))),
                                dlarger_sign.eq(Mux(da_mag_ge, da_sign, db_eff_sign)),
                                dlarger_exp.eq(Mux(da_mag_ge, da_exp, db_exp)),
                                dsmaller_exp.eq(Mux(da_mag_ge, db_exp, da_exp)),
                                dlarger_mant.eq(Mux(da_mag_ge, da_mant, db_mant)),
                                dsmaller_mant.eq(Mux(da_mag_ge, db_mant, da_mant)),
                                dexp_delta.eq(dlarger_exp - dsmaller_exp),
                                dshifted_small.eq(Mux(dexp_delta > 52, 0, dsmaller_mant >> dexp_delta)),
                                dsame_sign.eq(da_sign == db_eff_sign),
                                dadd_sum.eq(dlarger_mant + dshifted_small),
                                ddiff_mant.eq(dlarger_mant - dshifted_small),
                                dalign_remainder.eq(Mux(
                                    dexp_delta == 0,
                                    0,
                                    Mux(dexp_delta > 52, dsmaller_mant,
                                        dsmaller_mant & ((C(1, 53) << dexp_delta) - 1)),
                                )),
                                dalign_half.eq(Mux(
                                    dexp_delta == 0,
                                    0,
                                    Mux(dexp_delta > 52, C(1, 53) << 52,
                                        C(1, 53) << (dexp_delta - 1)[0:11]),
                                )),
                                dadd_inexact.eq(dalign_remainder != 0),
                                dadd_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                dadd_rm_valid.eq(dadd_rm <= 0b100),
                                dround_nearest.eq(
                                    (dexp_delta <= 53) &
                                    ((dalign_remainder > dalign_half) |
                                     ((dalign_remainder == dalign_half) & daddsub_result[0]))
                                ),
                                dround_rmm.eq(
                                    (dexp_delta <= 53) & (dalign_remainder >= dalign_half)
                                ),
                                dfinite.eq(~da_nan & ~db_nan & ~da_inf & ~db_inf &
                                           ~(da_zero & db_zero) &
                                           (dsame_sign | (ddiff_mant != 0))),
                                dfinite_sign.eq(Mux(
                                    dsame_sign, da_sign,
                                    Mux(da_mag_ge, da_sign, db_eff_sign),
                                )),
                                daddsub_result.eq(0x7ff8000000000000),
                            ]
                            with m.If(da_nan | db_nan | (da_inf & db_inf & (da_sign != db_eff_sign))):
                                m.d.comb += daddsub_result.eq(0x7ff8000000000000)
                            with m.Elif(da_inf):
                                m.d.comb += daddsub_result.eq(fp_ex1_a)
                            with m.Elif(db_inf):
                                m.d.comb += daddsub_result.eq(Cat(C(0, 52), C(0x7ff, 11), db_eff_sign))
                            with m.Elif(da_zero & db_zero):
                                m.d.comb += daddsub_result.eq(Cat(C(0, 63), Mux(IS.funct7 == 0b0000101, da_sign & ~db_sign, da_sign & db_sign)))
                            with m.Elif(dsame_sign):
                                with m.If(dadd_sum[53]):
                                    m.d.comb += daddsub_result.eq(Cat(dadd_sum[1:53], dlarger_exp + 1, dlarger_sign))
                                with m.Else():
                                    m.d.comb += daddsub_result.eq(Cat(dadd_sum[0:52], dlarger_exp, dlarger_sign))
                            with m.Else():
                                with m.If(ddiff_mant == 0):
                                    m.d.comb += daddsub_result.eq(0)
                                with m.Else():
                                    for bit in range(53):
                                        dnorm_frac = (ddiff_mant << (52 - bit))[0:52] if bit < 52 else ddiff_mant[0:52]
                                        with m.If(ddiff_mant[bit]):
                                            m.d.comb += daddsub_result.eq(Cat(dnorm_frac, dlarger_exp - (52 - bit), dlarger_sign))
                            m.d.comb += [
                                dbase_mag.eq(daddsub_result[0:63]),
                                dadjust_up.eq(dadd_inexact & dsame_sign & Mux(
                                    dadd_rm == 0b000, dround_nearest,
                                    Mux(dadd_rm == 0b001, 0,
                                        Mux(dadd_rm == 0b010, dfinite_sign,
                                            Mux(dadd_rm == 0b011, ~dfinite_sign,
                                                dround_rmm))),
                                )),
                                dadjust_down.eq(dadd_inexact & ~dsame_sign & Mux(
                                    dadd_rm == 0b000, dround_nearest,
                                    Mux(dadd_rm == 0b001, 1,
                                        Mux(dadd_rm == 0b010, ~dfinite_sign,
                                            Mux(dadd_rm == 0b011, dfinite_sign,
                                                dround_rmm))),
                                )),
                                drounded_mag.eq(Mux(
                                    dadjust_up, dbase_mag + 1,
                                    Mux(dadjust_down, dbase_mag - 1, dbase_mag),
                                )),
                                daddsub_final.eq(Mux(
                                    dfinite,
                                    Cat(drounded_mag, dfinite_sign),
                                    daddsub_result,
                                )),
                            ]
                            with m.If(dadd_invalid):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                            with m.Elif(dadd_inexact & dfinite):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                            with m.If(dadd_rm_valid):
                                m.d.comb += [fp_wb_en.eq(1), fp_wb_data.eq(daddsub_final)]
                        with m.Elif(self.enable_fp64 & (IS.funct7 == 0b0101101) & (IS.rs2 == 0)):  # FSQRT.D
                            dsqrt_exp = Signal(11)
                            dsqrt_frac = Signal(52)
                            dsqrt_sign = Signal()
                            dsqrt_nan = Signal()
                            dsqrt_snan = Signal()
                            dsqrt_zero = Signal()
                            dsqrt_inf = Signal()
                            dsqrt_rm = Signal(3)
                            dsqrt_rm_valid = Signal()
                            dsqrt_mant = Signal(53)
                            dsqrt_unbiased = Signal(signed(13))
                            dsqrt_radicand = Signal(106)
                            dsqrt_root = Signal(54)
                            dsqrt_remainder = Signal(108)
                            dsqrt_increment = Signal()
                            dsqrt_rounded = Signal(54)
                            dsqrt_half_exp = Signal(signed(13))
                            dsqrt_biased_exp = Signal(12)
                            dsqrt_result = Signal(64)
                            m.d.comb += [
                                dsqrt_exp.eq(fp_ex1_a[52:63]),
                                dsqrt_frac.eq(fp_ex1_a[0:52]),
                                dsqrt_sign.eq(fp_ex1_a[63]),
                                dsqrt_nan.eq((dsqrt_exp == 0x7ff) & (dsqrt_frac != 0)),
                                dsqrt_snan.eq((dsqrt_exp == 0x7ff) & (dsqrt_frac != 0) & ~dsqrt_frac[51]),
                                dsqrt_zero.eq((dsqrt_exp == 0) & (dsqrt_frac == 0)),
                                dsqrt_inf.eq((dsqrt_exp == 0x7ff) & (dsqrt_frac == 0)),
                                dsqrt_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                dsqrt_rm_valid.eq(dsqrt_rm <= 0b100),
                                dsqrt_mant.eq(Cat(dsqrt_frac, C(1, 1))),
                                dsqrt_unbiased.eq(dsqrt_exp - 1023),
                                dsqrt_radicand.eq(Mux(dsqrt_unbiased[0], dsqrt_mant << 53, dsqrt_mant << 52)),
                                dsqrt_result.eq(0x7ff8000000000000),
                            ]
                            with m.If((dsqrt_exp == 0) & (dsqrt_frac != 0)):
                                m.d.comb += [dsqrt_mant.eq(0), dsqrt_unbiased.eq(-1074)]
                                for bit in range(52):
                                    with m.If(dsqrt_frac[bit]):
                                        m.d.comb += [
                                            dsqrt_mant.eq(dsqrt_frac << (52 - bit)),
                                            dsqrt_unbiased.eq(bit - 1074),
                                        ]
                            root_stages = [Signal(54, name=f"dsqrt_root_{stage}") for stage in range(54)]
                            remainder_stages = [Signal(108, name=f"dsqrt_rem_{stage}") for stage in range(54)]
                            m.d.comb += [root_stages[0].eq(0), remainder_stages[0].eq(0)]
                            for stage, pair_index in enumerate(reversed(range(53))):
                                pair = dsqrt_radicand[2 * pair_index:2 * pair_index + 2]
                                remainder_in = Signal(108, name=f"dsqrt_rem_in_{stage}")
                                root_shifted = Signal(54, name=f"dsqrt_root_shifted_{stage}")
                                trial = Signal(108, name=f"dsqrt_trial_{stage}")
                                take = Signal(name=f"dsqrt_take_{stage}")
                                m.d.comb += [
                                    remainder_in.eq(Cat(pair, remainder_stages[stage][0:106])),
                                    root_shifted.eq(Cat(C(0, 1), root_stages[stage][0:53])),
                                    trial.eq(Cat(C(1, 1), root_shifted, C(0, 53))),
                                    take.eq(remainder_in >= trial),
                                    remainder_stages[stage + 1].eq(Mux(take, remainder_in - trial, remainder_in)),
                                    root_stages[stage + 1].eq(Mux(take, root_shifted | 1, root_shifted)),
                                ]
                            m.d.comb += [
                                dsqrt_root.eq(root_stages[-1]),
                                dsqrt_remainder.eq(remainder_stages[-1]),
                                dsqrt_increment.eq(Mux(
                                    (dsqrt_rm == 0b000) | (dsqrt_rm == 0b100),
                                    dsqrt_remainder > dsqrt_root,
                                    Mux(dsqrt_rm == 0b011, dsqrt_remainder != 0, 0),
                                )),
                                dsqrt_rounded.eq(dsqrt_root + dsqrt_increment),
                                dsqrt_half_exp.eq(dsqrt_unbiased.as_signed() >> 1),
                                dsqrt_biased_exp.eq(dsqrt_half_exp + 1023 + dsqrt_rounded[53]),
                            ]
                            with m.If(dsqrt_nan):
                                m.d.comb += dsqrt_result.eq(0x7ff8000000000000)
                            with m.Elif(dsqrt_zero):
                                m.d.comb += dsqrt_result.eq(fp_ex1_a)
                            with m.Elif(dsqrt_sign):
                                m.d.comb += dsqrt_result.eq(0x7ff8000000000000)
                            with m.Elif(dsqrt_inf):
                                m.d.comb += dsqrt_result.eq(fp_ex1_a)
                            with m.Else():
                                m.d.comb += dsqrt_result.eq(Cat(
                                    Mux(dsqrt_rounded[53], C(0, 52), dsqrt_rounded[0:52]),
                                    dsqrt_biased_exp[0:11],
                                    C(0, 1),
                                ))
                            with m.If(dsqrt_rm_valid):
                                with m.If(dsqrt_snan | (dsqrt_sign & ~dsqrt_nan & ~dsqrt_zero)):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                                with m.Elif(~dsqrt_nan & ~dsqrt_inf & ~dsqrt_zero & (dsqrt_remainder != 0)):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                                m.d.comb += [fp_wb_en.eq(1), fp_wb_data.eq(dsqrt_result)]
                        with m.Elif(self.enable_fp64 & (IS.funct7 == 0b1110001) & (IS.funct3 == 0b001) & (IS.rs2 == 0)):  # FCLASS.D
                            dclass_exp = Signal(11)
                            dclass_frac = Signal(52)
                            dclass = Signal(self.xlen)
                            m.d.comb += [
                                dclass_exp.eq(fp_ex1_a[52:63]),
                                dclass_frac.eq(fp_ex1_a[0:52]),
                                dclass.eq(0),
                            ]
                            with m.If((dclass_exp == 0x7ff) & (dclass_frac == 0)):
                                m.d.comb += dclass.eq(Mux(fp_ex1_a[63], 1 << 0, 1 << 7))
                            with m.Elif((dclass_exp == 0x7ff) & (dclass_frac != 0)):
                                m.d.comb += dclass.eq(Mux(dclass_frac[51], 1 << 9, 1 << 8))
                            with m.Elif((dclass_exp == 0) & (dclass_frac == 0)):
                                m.d.comb += dclass.eq(Mux(fp_ex1_a[63], 1 << 3, 1 << 4))
                            with m.Elif((dclass_exp == 0) & (dclass_frac != 0)):
                                m.d.comb += dclass.eq(Mux(fp_ex1_a[63], 1 << 2, 1 << 5))
                            with m.Else():
                                m.d.comb += dclass.eq(Mux(fp_ex1_a[63], 1 << 1, 1 << 6))
                            m.d.comb += [wb_en.eq(1), wb_data.eq(dclass)]
                        with m.Elif(self.enable_fp64 & (IS.funct7 == 0b1101001) & ((IS.rs2 == 0) | (IS.rs2 == 1))):  # FCVT.D.W / FCVT.D.WU
                            dcvt_i_sign = Signal()
                            dcvt_i_mag = Signal(32)
                            dcvt_i_result = Signal(64)
                            m.d.comb += [
                                dcvt_i_sign.eq((IS.rs2 == 0) & ex1_a[31]),
                                dcvt_i_mag.eq(Mux((IS.rs2 == 0) & ex1_a[31], -ex1_a[0:32], ex1_a[0:32])),
                                dcvt_i_result.eq(0),
                            ]
                            with m.If(dcvt_i_mag != 0):
                                for bit in range(32):
                                    dcvt_i_frac = Cat(C(0, 52 - bit), dcvt_i_mag[0:bit]) if bit < 52 else dcvt_i_mag[bit - 52:bit]
                                    with m.If(dcvt_i_mag[bit]):
                                        m.d.comb += dcvt_i_result.eq(Cat(dcvt_i_frac, C(1023 + bit, 11), dcvt_i_sign))
                            m.d.comb += [fp_wb_en.eq(1), fp_wb_data.eq(dcvt_i_result)]
                        with m.Elif(self.enable_fp64 & (self.xlen >= 64) &
                                    (IS.funct7 == 0b1101001) &
                                    ((IS.rs2 == 2) | (IS.rs2 == 3))):  # FCVT.D.L / FCVT.D.LU
                            di64_input = Signal(64)
                            di64_sign = Signal()
                            di64_mag = Signal(64)
                            di64_zero = Signal()
                            di64_msb = Signal(6)
                            di64_rshift = Signal(6)
                            di64_lshift = Signal(6)
                            di64_retained = Signal(54)
                            di64_remainder = Signal(64)
                            di64_half = Signal(64)
                            di64_inexact = Signal()
                            di64_rm = Signal(3)
                            di64_rm_valid = Signal()
                            di64_increment = Signal()
                            di64_rounded = Signal(55)
                            di64_result = Signal(64)
                            m.d.comb += [
                                di64_input.eq(ex1_a),
                                di64_sign.eq((IS.rs2 == 2) & di64_input[63]),
                                di64_mag.eq(Mux(
                                    (IS.rs2 == 2) & di64_input[63], -di64_input, di64_input
                                )),
                                di64_zero.eq(di64_mag == 0),
                                di64_msb.eq(0),
                            ]
                            for bit in range(64):
                                with m.If(di64_mag[bit]):
                                    m.d.comb += di64_msb.eq(bit)
                            m.d.comb += [
                                di64_rshift.eq(Mux(di64_msb > 52, di64_msb - 52, 0)),
                                di64_lshift.eq(Mux(di64_msb < 52, 52 - di64_msb, 0)),
                                di64_retained.eq(Mux(
                                    di64_msb > 52,
                                    di64_mag >> di64_rshift,
                                    di64_mag << di64_lshift,
                                )),
                                di64_remainder.eq(Mux(
                                    di64_rshift != 0,
                                    di64_mag & ((C(1, 64) << di64_rshift) - 1),
                                    0,
                                )),
                                di64_half.eq(Mux(
                                    di64_rshift != 0,
                                    C(1, 64) << (di64_rshift - 1)[0:6],
                                    0,
                                )),
                                di64_inexact.eq(di64_remainder != 0),
                                di64_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                di64_rm_valid.eq(di64_rm <= 0b100),
                                di64_increment.eq(Mux(
                                    di64_rm == 0b000,
                                    (di64_remainder > di64_half) |
                                    ((di64_remainder == di64_half) & di64_retained[0]),
                                    Mux(di64_rm == 0b001, 0,
                                        Mux(di64_rm == 0b010, di64_sign & di64_inexact,
                                            Mux(di64_rm == 0b011, ~di64_sign & di64_inexact,
                                                di64_inexact & (di64_remainder >= di64_half)))),
                                )),
                                di64_rounded.eq(di64_retained + di64_increment),
                                di64_result.eq(Mux(
                                    di64_zero,
                                    0,
                                    Cat(
                                        Mux(di64_rounded[53], C(0, 52), di64_rounded[0:52]),
                                        (C(1023, 11) + di64_msb + di64_rounded[53])[0:11],
                                        di64_sign,
                                    ),
                                )),
                            ]
                            with m.If(di64_rm_valid):
                                m.d.comb += [fp_wb_en.eq(1), fp_wb_data.eq(di64_result)]
                                with m.If(di64_inexact):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                        with m.Elif(self.enable_zfa & self.enable_d & (IS.funct7 == 0b1100001) &
                                    (IS.rs2 == 8) & (IS.funct3 == 0b001)):  # FCVTMOD.W.D
                            dcvtmod_exp = Signal(11)
                            dcvtmod_frac = Signal(52)
                            dcvtmod_sign = Signal()
                            dcvtmod_special = Signal()
                            dcvtmod_zero = Signal()
                            dcvtmod_invalid = Signal()
                            dcvtmod_inexact = Signal()
                            dcvtmod_mant = Signal(53)
                            dcvtmod_rshift = Signal(6)
                            dcvtmod_lshift = Signal(11)
                            dcvtmod_right = Signal(53)
                            dcvtmod_discarded = Signal()
                            dcvtmod_mag = Signal(32)
                            dcvtmod_result = Signal(32)
                            m.d.comb += [
                                dcvtmod_exp.eq(fp_ex1_a[52:63]),
                                dcvtmod_frac.eq(fp_ex1_a[0:52]),
                                dcvtmod_sign.eq(fp_ex1_a[63]),
                                dcvtmod_special.eq(dcvtmod_exp == 0x7ff),
                                dcvtmod_zero.eq((dcvtmod_exp == 0) & (dcvtmod_frac == 0)),
                                dcvtmod_invalid.eq(
                                    dcvtmod_special |
                                    (~dcvtmod_sign & (dcvtmod_exp >= 1054)) |
                                    (dcvtmod_sign & ((dcvtmod_exp > 1054) |
                                     ((dcvtmod_exp == 1054) & (dcvtmod_frac != 0))))
                                ),
                                dcvtmod_mant.eq(Cat(dcvtmod_frac, C(1, 1))),
                                dcvtmod_rshift.eq(1075 - dcvtmod_exp),
                                dcvtmod_lshift.eq(dcvtmod_exp - 1075),
                                dcvtmod_right.eq(dcvtmod_mant >> dcvtmod_rshift),
                                dcvtmod_discarded.eq(
                                    (dcvtmod_exp < 1075) &
                                    ((dcvtmod_right << dcvtmod_rshift) != dcvtmod_mant)
                                ),
                                dcvtmod_mag.eq(0),
                                dcvtmod_result.eq(0),
                                dcvtmod_inexact.eq(
                                    ~dcvtmod_invalid & ~dcvtmod_zero &
                                    ((dcvtmod_exp < 1023) |
                                     ((dcvtmod_exp < 1075) & dcvtmod_discarded))
                                ),
                            ]
                            with m.If(~dcvtmod_special):
                                with m.If(dcvtmod_exp < 1023):
                                    m.d.comb += dcvtmod_mag.eq(0)
                                with m.Elif(dcvtmod_exp < 1075):
                                    m.d.comb += dcvtmod_mag.eq(dcvtmod_right[0:32])
                                with m.Elif(dcvtmod_lshift < 32):
                                    m.d.comb += dcvtmod_mag.eq(dcvtmod_mant[0:32] << dcvtmod_lshift)
                                m.d.comb += dcvtmod_result.eq(Mux(
                                    dcvtmod_sign,
                                    -dcvtmod_mag,
                                    dcvtmod_mag,
                                ))
                            with m.If(dcvtmod_invalid):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                            with m.Elif(dcvtmod_inexact):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                            m.d.comb += [
                                wb_en.eq(1),
                                wb_data.eq(sign_extend(dcvtmod_result, 32, self.xlen)),
                            ]
                        with m.Elif(self.enable_fp64 & (IS.funct7 == 0b1100001) & ((IS.rs2 == 0) | (IS.rs2 == 1))):  # FCVT.W.D / FCVT.WU.D
                            dcvtw_exp = Signal(11)
                            dcvtw_frac = Signal(52)
                            dcvtw_nan = Signal()
                            dcvtw_sign = Signal()
                            dcvtw_unsigned = Signal()
                            dcvtw_invalid = Signal()
                            dcvtw_mant = Signal(53)
                            dcvtw_shamt = Signal(6)
                            dcvtw_half_shamt = Signal(6)
                            dcvtw_rm = Signal(3)
                            dcvtw_trunc = Signal(33)
                            dcvtw_rounded = Signal(34)
                            dcvtw_discard_mask = Signal(53)
                            dcvtw_lower_mask = Signal(53)
                            dcvtw_inexact = Signal()
                            dcvtw_guard = Signal()
                            dcvtw_lower = Signal()
                            dcvtw_increment = Signal()
                            dcvtw_result32 = Signal(32)
                            m.d.comb += [
                                dcvtw_exp.eq(fp_ex1_a[52:63]),
                                dcvtw_frac.eq(fp_ex1_a[0:52]),
                                dcvtw_sign.eq(fp_ex1_a[63]),
                                dcvtw_unsigned.eq(IS.rs2 == 1),
                                dcvtw_nan.eq((dcvtw_exp == 0x7ff) & (dcvtw_frac != 0)),
                                dcvtw_mant.eq(Cat(dcvtw_frac, Mux(dcvtw_exp == 0, 0, 1))),
                                dcvtw_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                dcvtw_shamt.eq(0),
                                dcvtw_half_shamt.eq(0),
                                dcvtw_trunc.eq(0),
                                dcvtw_discard_mask.eq(0),
                                dcvtw_lower_mask.eq(0),
                                dcvtw_inexact.eq(0),
                                dcvtw_guard.eq(0),
                                dcvtw_lower.eq(0),
                                dcvtw_result32.eq(0),
                            ]
                            with m.If(dcvtw_exp < 1022):
                                m.d.comb += dcvtw_inexact.eq((dcvtw_exp != 0) | (dcvtw_frac != 0))
                            with m.Elif(dcvtw_exp == 1022):
                                m.d.comb += [
                                    dcvtw_inexact.eq(1),
                                    dcvtw_guard.eq(1),
                                    dcvtw_lower.eq(dcvtw_frac != 0),
                                ]
                            with m.Elif(dcvtw_exp <= 1055):
                                m.d.comb += [
                                    dcvtw_shamt.eq(1075 - dcvtw_exp),
                                    dcvtw_half_shamt.eq(dcvtw_shamt - 1),
                                    dcvtw_discard_mask.eq((C(1, 53) << dcvtw_shamt) - 1),
                                    dcvtw_lower_mask.eq((C(1, 53) << dcvtw_half_shamt) - 1),
                                    dcvtw_trunc.eq(dcvtw_mant >> dcvtw_shamt),
                                    dcvtw_inexact.eq((dcvtw_mant & dcvtw_discard_mask) != 0),
                                    dcvtw_guard.eq(dcvtw_mant.bit_select(dcvtw_half_shamt, 1)),
                                    dcvtw_lower.eq((dcvtw_mant & dcvtw_lower_mask) != 0),
                                ]
                            with m.Else():
                                m.d.comb += dcvtw_trunc.eq(0x1ffffffff)
                            m.d.comb += [
                                dcvtw_increment.eq(Mux(
                                    dcvtw_rm == 0b000,
                                    dcvtw_guard & (dcvtw_lower | dcvtw_trunc[0]),
                                    Mux(
                                        dcvtw_rm == 0b010,
                                        dcvtw_sign & dcvtw_inexact,
                                        Mux(
                                            dcvtw_rm == 0b011,
                                            ~dcvtw_sign & dcvtw_inexact,
                                            Mux(dcvtw_rm == 0b100, dcvtw_guard, 0),
                                        ),
                                    ),
                                )),
                                dcvtw_rounded.eq(dcvtw_trunc + dcvtw_increment),
                                dcvtw_invalid.eq(
                                    (dcvtw_exp == 0x7ff) |
                                    (dcvtw_unsigned & dcvtw_sign & (dcvtw_rounded != 0)) |
                                    (dcvtw_unsigned & ~dcvtw_sign & (dcvtw_rounded > 0xffffffff)) |
                                    (~dcvtw_unsigned & dcvtw_sign & (dcvtw_rounded > 0x80000000)) |
                                    (~dcvtw_unsigned & ~dcvtw_sign & (dcvtw_rounded > 0x7fffffff))
                                ),
                            ]
                            with m.If(dcvtw_invalid):
                                m.d.comb += dcvtw_result32.eq(Mux(
                                    dcvtw_unsigned,
                                    Mux(dcvtw_sign & ~dcvtw_nan, 0, 0xffffffff),
                                    Mux(dcvtw_nan | ~dcvtw_sign, 0x7fffffff, 0x80000000),
                                ))
                            with m.Else():
                                m.d.comb += dcvtw_result32.eq(Mux(dcvtw_sign, -dcvtw_rounded[0:32], dcvtw_rounded[0:32]))
                            with m.If(dcvtw_invalid):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                            with m.Elif(dcvtw_inexact):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                            m.d.comb += [wb_en.eq(1), wb_data.eq(sign_extend(dcvtw_result32, 32, self.xlen))]
                        with m.Elif(self.enable_fp64 & (self.xlen >= 64) &
                                    (IS.funct7 == 0b1100001) &
                                    ((IS.rs2 == 2) | (IS.rs2 == 3))):  # FCVT.L.D / FCVT.LU.D
                            dcvtl_exp = Signal(11)
                            dcvtl_frac = Signal(52)
                            dcvtl_nan = Signal()
                            dcvtl_sign = Signal()
                            dcvtl_unsigned = Signal()
                            dcvtl_invalid = Signal()
                            dcvtl_mant = Signal(53)
                            dcvtl_rshift = Signal(6)
                            dcvtl_lshift = Signal(4)
                            dcvtl_half_shift = Signal(6)
                            dcvtl_rm = Signal(3)
                            dcvtl_rm_valid = Signal()
                            dcvtl_trunc = Signal(65)
                            dcvtl_rounded = Signal(66)
                            dcvtl_discard_mask = Signal(53)
                            dcvtl_lower_mask = Signal(53)
                            dcvtl_inexact = Signal()
                            dcvtl_guard = Signal()
                            dcvtl_lower = Signal()
                            dcvtl_increment = Signal()
                            dcvtl_result = Signal(64)
                            m.d.comb += [
                                dcvtl_exp.eq(fp_ex1_a[52:63]),
                                dcvtl_frac.eq(fp_ex1_a[0:52]),
                                dcvtl_sign.eq(fp_ex1_a[63]),
                                dcvtl_unsigned.eq(IS.rs2 == 3),
                                dcvtl_nan.eq((dcvtl_exp == 0x7ff) & (dcvtl_frac != 0)),
                                dcvtl_mant.eq(Cat(dcvtl_frac, Mux(dcvtl_exp == 0, 0, 1))),
                                dcvtl_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                dcvtl_rm_valid.eq(dcvtl_rm <= 0b100),
                                dcvtl_rshift.eq(0),
                                dcvtl_lshift.eq(0),
                                dcvtl_half_shift.eq(0),
                                dcvtl_trunc.eq(0),
                                dcvtl_discard_mask.eq(0),
                                dcvtl_lower_mask.eq(0),
                                dcvtl_inexact.eq(0),
                                dcvtl_guard.eq(0),
                                dcvtl_lower.eq(0),
                                dcvtl_result.eq(0),
                            ]
                            with m.If(dcvtl_exp < 1022):
                                m.d.comb += dcvtl_inexact.eq((dcvtl_exp != 0) | (dcvtl_frac != 0))
                            with m.Elif(dcvtl_exp == 1022):
                                m.d.comb += [
                                    dcvtl_inexact.eq(1),
                                    dcvtl_guard.eq(1),
                                    dcvtl_lower.eq(dcvtl_frac != 0),
                                ]
                            with m.Elif(dcvtl_exp <= 1075):
                                m.d.comb += [
                                    dcvtl_rshift.eq(1075 - dcvtl_exp),
                                    dcvtl_half_shift.eq(Mux(dcvtl_rshift != 0, dcvtl_rshift - 1, 0)),
                                    dcvtl_discard_mask.eq((C(1, 53) << dcvtl_rshift) - 1),
                                    dcvtl_lower_mask.eq(Mux(
                                        dcvtl_rshift != 0,
                                        (C(1, 53) << dcvtl_half_shift) - 1,
                                        0,
                                    )),
                                    dcvtl_trunc.eq(dcvtl_mant >> dcvtl_rshift),
                                    dcvtl_inexact.eq((dcvtl_mant & dcvtl_discard_mask) != 0),
                                    dcvtl_guard.eq((dcvtl_rshift != 0) &
                                                    dcvtl_mant.bit_select(dcvtl_half_shift, 1)),
                                    dcvtl_lower.eq((dcvtl_mant & dcvtl_lower_mask) != 0),
                                ]
                            with m.Elif(dcvtl_exp <= 1086):
                                m.d.comb += [
                                    dcvtl_lshift.eq(dcvtl_exp - 1075),
                                    dcvtl_trunc.eq(dcvtl_mant << dcvtl_lshift),
                                ]
                            with m.Else():
                                m.d.comb += dcvtl_trunc.eq(C(0x1ffffffffffffffff, 65))
                            m.d.comb += [
                                dcvtl_increment.eq(Mux(
                                    dcvtl_rm == 0b000,
                                    dcvtl_guard & (dcvtl_lower | dcvtl_trunc[0]),
                                    Mux(dcvtl_rm == 0b010, dcvtl_sign & dcvtl_inexact,
                                        Mux(dcvtl_rm == 0b011, ~dcvtl_sign & dcvtl_inexact,
                                            Mux(dcvtl_rm == 0b100, dcvtl_guard, 0))),
                                )),
                                dcvtl_rounded.eq(dcvtl_trunc + dcvtl_increment),
                                dcvtl_invalid.eq(
                                    (dcvtl_exp == 0x7ff) |
                                    (dcvtl_unsigned & dcvtl_sign & (dcvtl_rounded != 0)) |
                                    (dcvtl_unsigned & ~dcvtl_sign & dcvtl_rounded[65]) |
                                    (~dcvtl_unsigned & dcvtl_sign &
                                     (dcvtl_rounded > C(0x8000000000000000, 66))) |
                                    (~dcvtl_unsigned & ~dcvtl_sign &
                                     (dcvtl_rounded > C(0x7fffffffffffffff, 66)))
                                ),
                            ]
                            with m.If(dcvtl_invalid):
                                m.d.comb += dcvtl_result.eq(Mux(
                                    dcvtl_unsigned,
                                    Mux(dcvtl_sign & ~dcvtl_nan, 0, C(0xffffffffffffffff, 64)),
                                    Mux(dcvtl_nan | ~dcvtl_sign,
                                        C(0x7fffffffffffffff, 64), C(0x8000000000000000, 64)),
                                ))
                            with m.Else():
                                m.d.comb += dcvtl_result.eq(Mux(
                                    dcvtl_sign, -dcvtl_rounded[0:64], dcvtl_rounded[0:64]
                                ))
                            with m.If(dcvtl_rm_valid):
                                m.d.comb += [wb_en.eq(1), wb_data.eq(dcvtl_result)]
                                with m.If(dcvtl_invalid):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                                with m.Elif(dcvtl_inexact):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                        with m.Elif(self.enable_zfhmin & self.enable_d & (IS.funct7 == 0b0100010) &
                                    (IS.rs2 == 1)):  # FCVT.H.D
                            dcvth_exp = Signal(11)
                            dcvth_frac = Signal(52)
                            dcvth_sign = Signal()
                            dcvth_nan = Signal()
                            dcvth_snan = Signal()
                            dcvth_inf = Signal()
                            dcvth_zero = Signal()
                            dcvth_rm = Signal(3)
                            dcvth_rm_valid = Signal()
                            dcvth_mant = Signal(53)
                            dcvth_norm_trunc = Signal(11)
                            dcvth_norm_rem = Signal(42)
                            dcvth_norm_increment = Signal()
                            dcvth_norm_rounded = Signal(12)
                            dcvth_half_exp = Signal(6)
                            dcvth_norm_target_exp = Signal(6)
                            dcvth_sub_shamt = Signal(11)
                            dcvth_sub_trunc_full = Signal(53)
                            dcvth_sub_trunc = Signal(11)
                            dcvth_sub_rem = Signal(53)
                            dcvth_sub_half = Signal(53)
                            dcvth_sub_lsb = Signal()
                            dcvth_sub_inexact = Signal()
                            dcvth_sub_increment = Signal()
                            dcvth_sub_rounded = Signal(12)
                            dcvth_overflow = Signal()
                            dcvth_inexact = Signal()
                            dcvth_tiny = Signal()
                            dcvth_result = Signal(16)
                            m.d.comb += [
                                dcvth_exp.eq(fp_ex1_a[52:63]),
                                dcvth_frac.eq(fp_ex1_a[0:52]),
                                dcvth_sign.eq(fp_ex1_a[63]),
                                dcvth_nan.eq((dcvth_exp == 0x7ff) & (dcvth_frac != 0)),
                                dcvth_snan.eq((dcvth_exp == 0x7ff) & (dcvth_frac != 0) & ~dcvth_frac[51]),
                                dcvth_inf.eq((dcvth_exp == 0x7ff) & (dcvth_frac == 0)),
                                dcvth_zero.eq((dcvth_exp == 0) & (dcvth_frac == 0)),
                                dcvth_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                dcvth_rm_valid.eq(dcvth_rm <= 0b100),
                                dcvth_mant.eq(Cat(dcvth_frac, Mux(dcvth_exp == 0, 0, 1))),
                                dcvth_norm_trunc.eq(dcvth_mant >> 42),
                                dcvth_norm_rem.eq(dcvth_mant[0:42]),
                                dcvth_norm_increment.eq(0),
                                dcvth_norm_rounded.eq(dcvth_norm_trunc + dcvth_norm_increment),
                                dcvth_half_exp.eq(dcvth_exp - 1008),
                                dcvth_norm_target_exp.eq(dcvth_half_exp + dcvth_norm_rounded[11]),
                                dcvth_sub_shamt.eq(1051 - dcvth_exp),
                                dcvth_sub_trunc_full.eq(dcvth_mant >> dcvth_sub_shamt),
                                dcvth_sub_trunc.eq(dcvth_sub_trunc_full[0:11]),
                                dcvth_sub_rem.eq(dcvth_mant - (dcvth_sub_trunc_full << dcvth_sub_shamt)),
                                dcvth_sub_half.eq(Mux(
                                    dcvth_exp >= 998,
                                    C(1, 53) << (dcvth_sub_shamt - C(1, 11)).as_unsigned(),
                                    0,
                                )),
                                dcvth_sub_lsb.eq(dcvth_sub_trunc[0]),
                                dcvth_sub_inexact.eq(~dcvth_zero & Mux(
                                    dcvth_exp >= 998,
                                    dcvth_sub_rem != 0,
                                    dcvth_mant != 0,
                                )),
                                dcvth_sub_increment.eq(0),
                                dcvth_sub_rounded.eq(dcvth_sub_trunc + dcvth_sub_increment),
                                dcvth_overflow.eq(~(dcvth_nan | dcvth_inf) & (
                                    (dcvth_exp >= 1039) |
                                    ((dcvth_exp >= 1009) & (dcvth_norm_target_exp >= 31))
                                )),
                                dcvth_inexact.eq(0),
                                dcvth_tiny.eq(0),
                                dcvth_result.eq(Cat(C(0, 15), dcvth_sign)),
                            ]
                            with m.Switch(dcvth_rm):
                                with m.Case(0b000):
                                    m.d.comb += [
                                        dcvth_norm_increment.eq(
                                            (dcvth_norm_rem > (1 << 41)) |
                                            ((dcvth_norm_rem == (1 << 41)) & dcvth_norm_trunc[0])
                                        ),
                                        dcvth_sub_increment.eq(
                                            (dcvth_exp >= 998) &
                                            ((dcvth_sub_rem > dcvth_sub_half) |
                                             ((dcvth_sub_rem == dcvth_sub_half) & dcvth_sub_lsb))
                                        ),
                                    ]
                                with m.Case(0b001):
                                    pass
                                with m.Case(0b010):
                                    m.d.comb += [
                                        dcvth_norm_increment.eq(dcvth_sign & (dcvth_norm_rem != 0)),
                                        dcvth_sub_increment.eq(dcvth_sign & dcvth_sub_inexact),
                                    ]
                                with m.Case(0b011):
                                    m.d.comb += [
                                        dcvth_norm_increment.eq(~dcvth_sign & (dcvth_norm_rem != 0)),
                                        dcvth_sub_increment.eq(~dcvth_sign & dcvth_sub_inexact),
                                    ]
                                with m.Case(0b100):
                                    m.d.comb += [
                                        dcvth_norm_increment.eq(dcvth_norm_rem >= (1 << 41)),
                                        dcvth_sub_increment.eq(
                                            (dcvth_exp >= 998) & (dcvth_sub_rem >= dcvth_sub_half)
                                        ),
                                    ]
                            with m.If(dcvth_nan):
                                m.d.comb += dcvth_result.eq(0x7e00)
                            with m.Elif(dcvth_inf):
                                m.d.comb += dcvth_result.eq(Cat(C(0, 10), C(0x1f, 5), dcvth_sign))
                            with m.Elif(dcvth_zero):
                                m.d.comb += dcvth_result.eq(Cat(C(0, 15), dcvth_sign))
                            with m.Elif(dcvth_overflow):
                                dcvth_overflow_to_inf = Signal()
                                m.d.comb += dcvth_overflow_to_inf.eq(
                                    (dcvth_rm == 0b000) | (dcvth_rm == 0b100) |
                                    ((dcvth_rm == 0b010) & dcvth_sign) |
                                    ((dcvth_rm == 0b011) & ~dcvth_sign)
                                )
                                m.d.comb += dcvth_result.eq(Mux(
                                    dcvth_overflow_to_inf,
                                    Cat(C(0, 10), C(0x1f, 5), dcvth_sign),
                                    Cat(C(0x3ff, 10), C(0x1e, 5), dcvth_sign),
                                ))
                                m.d.comb += dcvth_inexact.eq(1)
                            with m.Elif(dcvth_exp >= 1009):
                                m.d.comb += [
                                    dcvth_result.eq(Cat(
                                        Mux(dcvth_norm_rounded[11], C(0, 10), dcvth_norm_rounded[0:10]),
                                        dcvth_norm_target_exp[0:5],
                                        dcvth_sign,
                                    )),
                                    dcvth_inexact.eq(dcvth_norm_rem != 0),
                                ]
                            with m.Else():
                                m.d.comb += [
                                    dcvth_result.eq(Mux(
                                        dcvth_sub_rounded[10],
                                        Cat(C(0, 10), C(1, 5), dcvth_sign),
                                        Cat(dcvth_sub_rounded[0:10], C(0, 5), dcvth_sign),
                                    )),
                                    dcvth_inexact.eq(dcvth_sub_inexact),
                                    dcvth_tiny.eq(~dcvth_sub_rounded[10]),
                                ]
                            with m.If(dcvth_rm_valid):
                                m.d.comb += [
                                    fp_wb_en.eq(1),
                                    fp_wb_data.eq(Cat(dcvth_result, C(0xFFFFFFFFFFFF, 48))),
                                ]
                                with m.If(dcvth_snan):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                                with m.Elif(dcvth_overflow):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00101)
                                with m.Elif(dcvth_inexact & dcvth_tiny):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00011)
                                with m.Elif(dcvth_inexact):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                        with m.Elif(self.enable_zfhmin & (IS.funct7 == 0b0100010) &
                                    (IS.rs2 == 0)) :  # FCVT.H.S
                            scvth_boxed = Signal()
                            scvth_exp = Signal(8)
                            scvth_frac = Signal(23)
                            scvth_sign = Signal()
                            scvth_nan = Signal()
                            scvth_snan = Signal()
                            scvth_inf = Signal()
                            scvth_zero = Signal()
                            scvth_rm = Signal(3)
                            scvth_rm_valid = Signal()
                            scvth_mant = Signal(24)
                            scvth_norm_trunc = Signal(11)
                            scvth_norm_rem = Signal(13)
                            scvth_norm_increment = Signal()
                            scvth_norm_rounded = Signal(12)
                            scvth_half_exp = Signal(6)
                            scvth_norm_target_exp = Signal(6)
                            scvth_sub_shamt = Signal(7)
                            scvth_sub_trunc_full = Signal(24)
                            scvth_sub_trunc = Signal(11)
                            scvth_sub_rem = Signal(24)
                            scvth_sub_half = Signal(24)
                            scvth_sub_lsb = Signal()
                            scvth_sub_inexact = Signal()
                            scvth_sub_increment = Signal()
                            scvth_sub_rounded = Signal(12)
                            scvth_overflow = Signal()
                            scvth_inexact = Signal()
                            scvth_tiny = Signal()
                            scvth_result = Signal(16)
                            m.d.comb += [
                                scvth_boxed.eq(fp_ex1_a[32:64] == 0xFFFFFFFF),
                                scvth_exp.eq(Mux(scvth_boxed, fp_ex1_a[23:31], 0xff)),
                                scvth_frac.eq(Mux(scvth_boxed, fp_ex1_a[0:23], 0x400000)),
                                scvth_sign.eq(Mux(scvth_boxed, fp_ex1_a[31], 0)),
                                scvth_nan.eq((scvth_exp == 0xff) & (scvth_frac != 0)),
                                scvth_snan.eq(scvth_boxed & (scvth_exp == 0xff) &
                                              (scvth_frac != 0) & ~scvth_frac[22]),
                                scvth_inf.eq((scvth_exp == 0xff) & (scvth_frac == 0)),
                                scvth_zero.eq((scvth_exp == 0) & (scvth_frac == 0)),
                                scvth_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                scvth_rm_valid.eq(scvth_rm <= 0b100),
                                scvth_mant.eq(Cat(scvth_frac, Mux(scvth_exp == 0, 0, 1))),
                                scvth_norm_trunc.eq(scvth_mant >> 13),
                                scvth_norm_rem.eq(scvth_mant[0:13]),
                                scvth_norm_increment.eq(0),
                                scvth_norm_rounded.eq(scvth_norm_trunc + scvth_norm_increment),
                                scvth_half_exp.eq(scvth_exp - 112),
                                scvth_norm_target_exp.eq(scvth_half_exp + scvth_norm_rounded[11]),
                                scvth_sub_shamt.eq(126 - scvth_exp),
                                scvth_sub_trunc_full.eq(scvth_mant >> scvth_sub_shamt),
                                scvth_sub_trunc.eq(scvth_sub_trunc_full[0:11]),
                                scvth_sub_rem.eq(scvth_mant - (scvth_sub_trunc_full << scvth_sub_shamt)),
                                scvth_sub_half.eq(Mux(
                                    scvth_exp >= 102,
                                    C(1, 24) << (scvth_sub_shamt - C(1, 7)).as_unsigned(),
                                    0,
                                )),
                                scvth_sub_lsb.eq(scvth_sub_trunc[0]),
                                scvth_sub_inexact.eq(~scvth_zero & Mux(
                                    scvth_exp >= 102,
                                    scvth_sub_rem != 0,
                                    scvth_mant != 0,
                                )),
                                scvth_sub_increment.eq(0),
                                scvth_sub_rounded.eq(scvth_sub_trunc + scvth_sub_increment),
                                scvth_overflow.eq(~(scvth_nan | scvth_inf) & (
                                    (scvth_exp >= 143) |
                                    ((scvth_exp >= 113) & (scvth_norm_target_exp >= 31))
                                )),
                                scvth_inexact.eq(0),
                                scvth_tiny.eq(0),
                                scvth_result.eq(Cat(C(0, 15), scvth_sign)),
                            ]
                            with m.Switch(scvth_rm):
                                with m.Case(0b000):  # RNE
                                    m.d.comb += [
                                        scvth_norm_increment.eq(
                                            (scvth_norm_rem > 0x1000) |
                                            ((scvth_norm_rem == 0x1000) & scvth_norm_trunc[0])
                                        ),
                                        scvth_sub_increment.eq(
                                            (scvth_exp >= 102) &
                                            ((scvth_sub_rem > scvth_sub_half) |
                                             ((scvth_sub_rem == scvth_sub_half) & scvth_sub_lsb))
                                        ),
                                    ]
                                with m.Case(0b001):  # RTZ
                                    pass
                                with m.Case(0b010):  # RDN
                                    m.d.comb += [
                                        scvth_norm_increment.eq(scvth_sign & (scvth_norm_rem != 0)),
                                        scvth_sub_increment.eq(scvth_sign & scvth_sub_inexact),
                                    ]
                                with m.Case(0b011):  # RUP
                                    m.d.comb += [
                                        scvth_norm_increment.eq(~scvth_sign & (scvth_norm_rem != 0)),
                                        scvth_sub_increment.eq(~scvth_sign & scvth_sub_inexact),
                                    ]
                                with m.Case(0b100):  # RMM
                                    m.d.comb += [
                                        scvth_norm_increment.eq(scvth_norm_rem >= 0x1000),
                                        scvth_sub_increment.eq(
                                            (scvth_exp >= 102) & (scvth_sub_rem >= scvth_sub_half)
                                        ),
                                    ]
                            with m.If(scvth_nan):
                                m.d.comb += scvth_result.eq(0x7e00)
                            with m.Elif(scvth_inf):
                                m.d.comb += scvth_result.eq(Cat(C(0, 10), C(0x1f, 5), scvth_sign))
                            with m.Elif(scvth_zero):
                                m.d.comb += scvth_result.eq(Cat(C(0, 15), scvth_sign))
                            with m.Elif(scvth_overflow):
                                scvth_overflow_to_inf = Signal()
                                m.d.comb += scvth_overflow_to_inf.eq(
                                    (scvth_rm == 0b000) | (scvth_rm == 0b100) |
                                    ((scvth_rm == 0b010) & scvth_sign) |
                                    ((scvth_rm == 0b011) & ~scvth_sign)
                                )
                                m.d.comb += scvth_result.eq(Mux(
                                    scvth_overflow_to_inf,
                                    Cat(C(0, 10), C(0x1f, 5), scvth_sign),
                                    Cat(C(0x3ff, 10), C(0x1e, 5), scvth_sign),
                                ))
                                m.d.comb += scvth_inexact.eq(1)
                            with m.Elif(scvth_exp >= 113):
                                m.d.comb += [
                                    scvth_result.eq(Cat(
                                        Mux(scvth_norm_rounded[11], C(0, 10), scvth_norm_rounded[0:10]),
                                        scvth_norm_target_exp[0:5],
                                        scvth_sign,
                                    )),
                                    scvth_inexact.eq(scvth_norm_rem != 0),
                                ]
                            with m.Else():
                                m.d.comb += [
                                    scvth_result.eq(Mux(
                                        scvth_sub_rounded[10],
                                        Cat(C(0, 10), C(1, 5), scvth_sign),
                                        Cat(scvth_sub_rounded[0:10], C(0, 5), scvth_sign),
                                    )),
                                    scvth_inexact.eq(scvth_sub_inexact),
                                    scvth_tiny.eq(~scvth_sub_rounded[10]),
                                ]
                            with m.If(scvth_rm_valid):
                                m.d.comb += [
                                    fp_wb_en.eq(1),
                                    fp_wb_data.eq(Cat(scvth_result, C(0xFFFFFFFFFFFF, 48))),
                                ]
                                with m.If(scvth_snan):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                                with m.Elif(scvth_overflow):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00101)
                                with m.Elif(scvth_inexact & scvth_tiny):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00011)
                                with m.Elif(scvth_inexact):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                        with m.Elif(self.enable_zfhmin & (IS.funct7 == 0b0100000) &
                                    (IS.rs2 == 2)):  # FCVT.S.H
                            hcvt_boxed = Signal()
                            hcvt_exp = Signal(5)
                            hcvt_frac = Signal(10)
                            hcvt_sign = Signal()
                            hcvt_rm = Signal(3)
                            hcvt_rm_valid = Signal()
                            hcvt_nan = Signal()
                            hcvt_snan = Signal()
                            hcvt_result = Signal(32)
                            m.d.comb += [
                                hcvt_boxed.eq(fp_ex1_a[16:64] == 0xFFFFFFFFFFFF),
                                hcvt_exp.eq(Mux(hcvt_boxed, fp_ex1_a[10:15], 0x1f)),
                                hcvt_frac.eq(Mux(hcvt_boxed, fp_ex1_a[0:10], 0x200)),
                                hcvt_sign.eq(Mux(hcvt_boxed, fp_ex1_a[15], 0)),
                                hcvt_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                hcvt_rm_valid.eq(hcvt_rm <= 0b100),
                                hcvt_nan.eq((hcvt_exp == 0x1f) & (hcvt_frac != 0)),
                                hcvt_snan.eq(hcvt_boxed & (hcvt_exp == 0x1f) &
                                             (hcvt_frac != 0) & ~hcvt_frac[9]),
                                hcvt_result.eq(Cat(C(0, 23), C(0, 8), hcvt_sign)),
                            ]
                            with m.If(hcvt_nan):
                                m.d.comb += hcvt_result.eq(0x7fc00000)
                            with m.Elif(hcvt_exp == 0x1f):
                                m.d.comb += hcvt_result.eq(Cat(C(0, 23), C(0xff, 8), hcvt_sign))
                            with m.Elif(hcvt_exp == 0):
                                with m.If(hcvt_frac != 0):
                                    for bit in range(10):
                                        hcvt_sub_frac = (
                                            C(0, 23) if bit == 0 else
                                            Cat(C(0, 23 - bit), hcvt_frac[0:bit])
                                        )
                                        with m.If(hcvt_frac[bit]):
                                            m.d.comb += hcvt_result.eq(Cat(
                                                hcvt_sub_frac,
                                                C(103 + bit, 8),
                                                hcvt_sign,
                                            ))
                            with m.Else():
                                m.d.comb += hcvt_result.eq(Cat(
                                    Cat(C(0, 13), hcvt_frac),
                                    (hcvt_exp + 112)[0:8],
                                    hcvt_sign,
                                ))
                            with m.If(hcvt_rm_valid):
                                with m.If(hcvt_snan):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                                m.d.comb += [
                                    fp_wb_en.eq(1),
                                    fp_wb_data.eq(Cat(hcvt_result, C(0xFFFFFFFF, 32))),
                                ]
                        with m.Elif(self.enable_fp64 & (IS.funct7 == 0b0100000) & (IS.rs2 == 1)):  # FCVT.S.D
                            dcvts_exp = Signal(11)
                            dcvts_frac = Signal(52)
                            dcvts_sign = Signal()
                            dcvts_rm = Signal(3)
                            dcvts_rm_valid = Signal()
                            dcvts_mant = Signal(53)
                            dcvts_shamt = Signal(6)
                            dcvts_half_shamt = Signal(6)
                            dcvts_base = Signal(25)
                            dcvts_rounded = Signal(26)
                            dcvts_discard_mask = Signal(53)
                            dcvts_lower_mask = Signal(53)
                            dcvts_inexact = Signal()
                            dcvts_guard = Signal()
                            dcvts_lower = Signal()
                            dcvts_increment = Signal()
                            dcvts_target_exp = Signal(9)
                            dcvts_final_exp = Signal(9)
                            dcvts_final_frac = Signal(23)
                            dcvts_overflow = Signal()
                            dcvts_to_inf = Signal()
                            dcvts_result = Signal(32)
                            m.d.comb += [
                                dcvts_exp.eq(fp_ex1_a[52:63]),
                                dcvts_frac.eq(fp_ex1_a[0:52]),
                                dcvts_sign.eq(fp_ex1_a[63]),
                                dcvts_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                dcvts_rm_valid.eq(dcvts_rm <= 0b100),
                                dcvts_mant.eq(Cat(dcvts_frac, Mux(dcvts_exp == 0, 0, 1))),
                                dcvts_shamt.eq(0),
                                dcvts_half_shamt.eq(0),
                                dcvts_base.eq(0),
                                dcvts_discard_mask.eq(0),
                                dcvts_lower_mask.eq(0),
                                dcvts_inexact.eq(0),
                                dcvts_guard.eq(0),
                                dcvts_lower.eq(0),
                                dcvts_target_exp.eq(0),
                                dcvts_final_exp.eq(0),
                                dcvts_final_frac.eq(0),
                                dcvts_result.eq(Cat(C(0, 31), dcvts_sign)),
                            ]
                            with m.If((dcvts_exp >= 897) & (dcvts_exp != 0x7ff)):
                                m.d.comb += [
                                    dcvts_shamt.eq(29),
                                    dcvts_half_shamt.eq(28),
                                    dcvts_base.eq(dcvts_mant >> 29),
                                    dcvts_target_exp.eq(dcvts_exp - 896),
                                ]
                            with m.Elif((dcvts_exp >= 874) & (dcvts_exp < 897)):
                                m.d.comb += [
                                    dcvts_shamt.eq(926 - dcvts_exp),
                                    dcvts_half_shamt.eq(dcvts_shamt - 1),
                                    dcvts_base.eq(dcvts_mant >> dcvts_shamt),
                                ]
                            with m.Elif(dcvts_exp == 873):
                                m.d.comb += [dcvts_inexact.eq(1), dcvts_guard.eq(1), dcvts_lower.eq(dcvts_frac != 0)]
                            with m.Elif((dcvts_exp != 0) | (dcvts_frac != 0)):
                                m.d.comb += dcvts_inexact.eq(1)
                            with m.If((dcvts_exp >= 874) & (dcvts_exp != 0x7ff)):
                                m.d.comb += [
                                    dcvts_discard_mask.eq((C(1, 53) << dcvts_shamt) - 1),
                                    dcvts_lower_mask.eq((C(1, 53) << dcvts_half_shamt) - 1),
                                    dcvts_inexact.eq((dcvts_mant & dcvts_discard_mask) != 0),
                                    dcvts_guard.eq(dcvts_mant.bit_select(dcvts_half_shamt, 1)),
                                    dcvts_lower.eq((dcvts_mant & dcvts_lower_mask) != 0),
                                ]
                            m.d.comb += [
                                dcvts_increment.eq(Mux(
                                    dcvts_rm == 0b000,
                                    dcvts_guard & (dcvts_lower | dcvts_base[0]),
                                    Mux(
                                        dcvts_rm == 0b010,
                                        dcvts_sign & dcvts_inexact,
                                        Mux(
                                            dcvts_rm == 0b011,
                                            ~dcvts_sign & dcvts_inexact,
                                            Mux(dcvts_rm == 0b100, dcvts_guard, 0),
                                        ),
                                    ),
                                )),
                                dcvts_rounded.eq(dcvts_base + dcvts_increment),
                            ]
                            with m.If(dcvts_exp >= 897):
                                m.d.comb += [
                                    dcvts_final_exp.eq(Mux(dcvts_rounded[24], dcvts_target_exp + 1, dcvts_target_exp)),
                                    dcvts_final_frac.eq(Mux(dcvts_rounded[24], dcvts_rounded[1:24], dcvts_rounded[0:23])),
                                ]
                            with m.Else():
                                m.d.comb += [
                                    dcvts_final_exp.eq(Mux(dcvts_rounded[23], 1, 0)),
                                    dcvts_final_frac.eq(Mux(dcvts_rounded[23], 0, dcvts_rounded[0:23])),
                                ]
                            m.d.comb += [
                                dcvts_overflow.eq((dcvts_exp != 0x7ff) & (dcvts_final_exp >= 0xff)),
                                dcvts_to_inf.eq(
                                    (dcvts_rm == 0b000) | (dcvts_rm == 0b100) |
                                    ((dcvts_rm == 0b010) & dcvts_sign) |
                                    ((dcvts_rm == 0b011) & ~dcvts_sign)
                                ),
                            ]
                            with m.If((dcvts_exp == 0x7ff) & (dcvts_frac != 0)):
                                m.d.comb += dcvts_result.eq(0x7fc00000)
                            with m.Elif((dcvts_exp == 0x7ff) & (dcvts_frac == 0)):
                                m.d.comb += dcvts_result.eq(Cat(C(0, 23), C(0xff, 8), dcvts_sign))
                            with m.Elif(dcvts_overflow):
                                m.d.comb += dcvts_result.eq(Mux(
                                    dcvts_to_inf,
                                    Cat(C(0, 23), C(0xff, 8), dcvts_sign),
                                    Cat(C(0x7fffff, 23), C(0xfe, 8), dcvts_sign),
                                ))
                            with m.Else():
                                m.d.comb += dcvts_result.eq(Cat(dcvts_final_frac, dcvts_final_exp[0:8], dcvts_sign))
                            with m.If(dcvts_rm_valid):
                                with m.If((dcvts_exp == 0x7ff) & (dcvts_frac != 0) & ~dcvts_frac[51]):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                                with m.Elif(dcvts_exp == 0x7ff):
                                    pass
                                with m.Elif(dcvts_overflow):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00101)
                                with m.Elif(dcvts_inexact & (dcvts_final_exp == 0)):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00011)
                                with m.Elif(dcvts_inexact):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                                m.d.comb += [
                                    fp_wb_en.eq(1),
                                    fp_wb_data.eq(Cat(dcvts_result, C(0xffffffff, 32))),
                                ]
                        with m.Elif(self.enable_zfhmin & self.enable_d & (IS.funct7 == 0b0100001) &
                                    (IS.rs2 == 2)):  # FCVT.D.H
                            hcvtd_boxed = Signal()
                            hcvtd_exp = Signal(5)
                            hcvtd_frac = Signal(10)
                            hcvtd_sign = Signal()
                            hcvtd_rm = Signal(3)
                            hcvtd_rm_valid = Signal()
                            hcvtd_nan = Signal()
                            hcvtd_snan = Signal()
                            hcvtd_result = Signal(64)
                            m.d.comb += [
                                hcvtd_boxed.eq(fp_ex1_a[16:64] == 0xFFFFFFFFFFFF),
                                hcvtd_exp.eq(Mux(hcvtd_boxed, fp_ex1_a[10:15], 0x1f)),
                                hcvtd_frac.eq(Mux(hcvtd_boxed, fp_ex1_a[0:10], 0x200)),
                                hcvtd_sign.eq(Mux(hcvtd_boxed, fp_ex1_a[15], 0)),
                                hcvtd_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                hcvtd_rm_valid.eq(hcvtd_rm <= 0b100),
                                hcvtd_nan.eq((hcvtd_exp == 0x1f) & (hcvtd_frac != 0)),
                                hcvtd_snan.eq(hcvtd_boxed & (hcvtd_exp == 0x1f) &
                                              (hcvtd_frac != 0) & ~hcvtd_frac[9]),
                                hcvtd_result.eq(Cat(C(0, 52), C(0, 11), hcvtd_sign)),
                            ]
                            with m.If(hcvtd_nan):
                                m.d.comb += hcvtd_result.eq(0x7ff8000000000000)
                            with m.Elif(hcvtd_exp == 0x1f):
                                m.d.comb += hcvtd_result.eq(Cat(C(0, 52), C(0x7ff, 11), hcvtd_sign))
                            with m.Elif(hcvtd_exp == 0):
                                with m.If(hcvtd_frac != 0):
                                    for bit in range(10):
                                        hcvtd_sub_frac = (
                                            C(0, 52) if bit == 0 else
                                            Cat(C(0, 52 - bit), hcvtd_frac[0:bit])
                                        )
                                        with m.If(hcvtd_frac[bit]):
                                            m.d.comb += hcvtd_result.eq(Cat(
                                                hcvtd_sub_frac,
                                                C(999 + bit, 11),
                                                hcvtd_sign,
                                            ))
                            with m.Else():
                                m.d.comb += hcvtd_result.eq(Cat(
                                    Cat(C(0, 42), hcvtd_frac),
                                    (hcvtd_exp + 1008)[0:11],
                                    hcvtd_sign,
                                ))
                            with m.If(hcvtd_rm_valid):
                                with m.If(hcvtd_snan):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                                m.d.comb += [fp_wb_en.eq(1), fp_wb_data.eq(hcvtd_result)]
                        with m.Elif(self.enable_fp64 & (IS.funct7 == 0b0100001) & (IS.rs2 == 0)):  # FCVT.D.S
                            dcvtd_boxed = Signal()
                            dcvtd_exp = Signal(8)
                            dcvtd_frac = Signal(23)
                            dcvtd_sign = Signal()
                            dcvtd_snan = Signal()
                            dcvtd_rm = Signal(3)
                            dcvtd_rm_valid = Signal()
                            dcvtd_d_exp = Signal(11)
                            dcvtd_result = Signal(64)
                            m.d.comb += [
                                dcvtd_boxed.eq(fp_ex1_a[32:64] == 0xffffffff),
                                dcvtd_exp.eq(Mux(dcvtd_boxed, fp_ex1_a[23:31], 0xff)),
                                dcvtd_frac.eq(Mux(dcvtd_boxed, fp_ex1_a[0:23], 0x400000)),
                                dcvtd_sign.eq(Mux(dcvtd_boxed, fp_ex1_a[31], 0)),
                                dcvtd_snan.eq(dcvtd_boxed & (fp_ex1_a[23:31] == 0xff) &
                                              (fp_ex1_a[0:23] != 0) & ~fp_ex1_a[22]),
                                dcvtd_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                dcvtd_rm_valid.eq(dcvtd_rm <= 0b100),
                                dcvtd_d_exp.eq(dcvtd_exp - 127 + 1023),
                                dcvtd_result.eq(Cat(C(0, 29), dcvtd_frac, dcvtd_d_exp, dcvtd_sign)),
                            ]
                            with m.If((dcvtd_exp == 0xff) & (dcvtd_frac != 0)):
                                m.d.comb += dcvtd_result.eq(0x7ff8000000000000)
                            with m.Elif((dcvtd_exp == 0xff) & (dcvtd_frac == 0)):
                                m.d.comb += dcvtd_result.eq(Cat(C(0, 52), C(0x7ff, 11), dcvtd_sign))
                            with m.Elif((dcvtd_exp == 0) & (dcvtd_frac == 0)):
                                m.d.comb += dcvtd_result.eq(Cat(C(0, 63), dcvtd_sign))
                            with m.Elif(dcvtd_exp == 0):
                                for bit in range(23):
                                    dcvt_sub_frac = Cat(C(0, 52 - bit), dcvtd_frac[0:bit])
                                    with m.If(dcvtd_frac[bit]):
                                        m.d.comb += dcvtd_result.eq(Cat(dcvt_sub_frac, C(874 + bit, 11), dcvtd_sign))
                            with m.If(dcvtd_rm_valid):
                                with m.If(dcvtd_snan):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                                m.d.comb += [fp_wb_en.eq(1), fp_wb_data.eq(dcvtd_result)]
                        with m.Elif((IS.funct7 == 0b0101100) & (IS.rs2 == 0)):  # FSQRT.S
                            fsqrt_exp = Signal(8)
                            fsqrt_frac = Signal(23)
                            fsqrt_sign = Signal()
                            fsqrt_nan = Signal()
                            fsqrt_snan = Signal()
                            fsqrt_zero = Signal()
                            fsqrt_inf = Signal()
                            fsqrt_rm = Signal(3)
                            fsqrt_mant = Signal(24)
                            fsqrt_unbiased = Signal(signed(10))
                            fsqrt_radicand = Signal(48)
                            fsqrt_root = Signal(25)
                            fsqrt_remainder = Signal(50)
                            fsqrt_increment = Signal()
                            fsqrt_rounded = Signal(25)
                            fsqrt_half_exp = Signal(signed(10))
                            fsqrt_biased_exp = Signal(9)
                            fsqrt_result = Signal(32)
                            m.d.comb += [
                                fsqrt_exp.eq(fp_ex1_a[23:31]),
                                fsqrt_frac.eq(fp_ex1_a[0:23]),
                                fsqrt_sign.eq(fp_ex1_a[31]),
                                fsqrt_nan.eq((fsqrt_exp == 0xff) & (fsqrt_frac != 0)),
                                fsqrt_snan.eq((fsqrt_exp == 0xff) & (fsqrt_frac != 0) & ~fsqrt_frac[22]),
                                fsqrt_zero.eq((fsqrt_exp == 0) & (fsqrt_frac == 0)),
                                fsqrt_inf.eq((fsqrt_exp == 0xff) & (fsqrt_frac == 0)),
                                fsqrt_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                fsqrt_mant.eq(Cat(fsqrt_frac, C(1, 1))),
                                fsqrt_unbiased.eq(fsqrt_exp - 127),
                                fsqrt_radicand.eq(Mux(fsqrt_unbiased[0], fsqrt_mant << 24, fsqrt_mant << 23)),
                                fsqrt_result.eq(0x7fc00000),
                            ]
                            with m.If((fsqrt_exp == 0) & (fsqrt_frac != 0)):
                                m.d.comb += [fsqrt_mant.eq(0), fsqrt_unbiased.eq(-149)]
                                for bit in range(23):
                                    with m.If(fsqrt_frac[bit]):
                                        m.d.comb += [
                                            fsqrt_mant.eq(fsqrt_frac << (23 - bit)),
                                            fsqrt_unbiased.eq(bit - 149),
                                        ]
                            fsqrt_root_stages = [Signal(25, name=f"fsqrt_root_{stage}") for stage in range(25)]
                            fsqrt_remainder_stages = [Signal(50, name=f"fsqrt_rem_{stage}") for stage in range(25)]
                            m.d.comb += [fsqrt_root_stages[0].eq(0), fsqrt_remainder_stages[0].eq(0)]
                            for stage, pair_index in enumerate(reversed(range(24))):
                                pair = fsqrt_radicand[2 * pair_index:2 * pair_index + 2]
                                remainder_in = Signal(50, name=f"fsqrt_rem_in_{stage}")
                                root_shifted = Signal(25, name=f"fsqrt_root_shifted_{stage}")
                                trial = Signal(50, name=f"fsqrt_trial_{stage}")
                                take = Signal(name=f"fsqrt_take_{stage}")
                                m.d.comb += [
                                    remainder_in.eq(Cat(pair, fsqrt_remainder_stages[stage][0:48])),
                                    root_shifted.eq(Cat(C(0, 1), fsqrt_root_stages[stage][0:24])),
                                    trial.eq(Cat(C(1, 1), root_shifted, C(0, 24))),
                                    take.eq(remainder_in >= trial),
                                    fsqrt_remainder_stages[stage + 1].eq(Mux(take, remainder_in - trial, remainder_in)),
                                    fsqrt_root_stages[stage + 1].eq(Mux(take, root_shifted | 1, root_shifted)),
                                ]
                            m.d.comb += [
                                fsqrt_root.eq(fsqrt_root_stages[-1]),
                                fsqrt_remainder.eq(fsqrt_remainder_stages[-1]),
                                fsqrt_increment.eq(Mux(
                                    (fsqrt_rm == 0b000) | (fsqrt_rm == 0b100),
                                    fsqrt_remainder > fsqrt_root,
                                    Mux(fsqrt_rm == 0b011, fsqrt_remainder != 0, 0),
                                )),
                                fsqrt_rounded.eq(fsqrt_root + fsqrt_increment),
                                fsqrt_half_exp.eq(fsqrt_unbiased.as_signed() >> 1),
                                fsqrt_biased_exp.eq(fsqrt_half_exp + 127 + fsqrt_rounded[24]),
                            ]
                            with m.If(fsqrt_nan):
                                m.d.comb += fsqrt_result.eq(0x7fc00000)
                            with m.Elif(fsqrt_zero):
                                m.d.comb += fsqrt_result.eq(fp_ex1_a[0:32])
                            with m.Elif(fsqrt_sign):
                                m.d.comb += fsqrt_result.eq(0x7fc00000)
                            with m.Elif(fsqrt_inf):
                                m.d.comb += fsqrt_result.eq(fp_ex1_a[0:32])
                            with m.Else():
                                m.d.comb += fsqrt_result.eq(Cat(
                                    Mux(fsqrt_rounded[24], C(0, 23), fsqrt_rounded[0:23]),
                                    fsqrt_biased_exp[0:8],
                                    C(0, 1),
                                ))
                            with m.If(fsqrt_snan | (fsqrt_sign & ~fsqrt_nan & ~fsqrt_zero)):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                            with m.Elif(~fsqrt_nan & ~fsqrt_inf & ~fsqrt_zero & (fsqrt_remainder != 0)):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                            m.d.comb += [
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(Cat(fsqrt_result, C(0xFFFFFFFF, 32))),
                            ]
                        with m.Elif(IS.funct7 == 0b0001100):  # FDIV.S
                            fdiv_a_sign = Signal()
                            fdiv_b_sign = Signal()
                            fdiv_sign = Signal()
                            fdiv_a_exp = Signal(8)
                            fdiv_b_exp = Signal(8)
                            fdiv_a_frac = Signal(23)
                            fdiv_b_frac = Signal(23)
                            fdiv_a_nan = Signal()
                            fdiv_b_nan = Signal()
                            fdiv_a_snan = Signal()
                            fdiv_b_snan = Signal()
                            fdiv_a_inf = Signal()
                            fdiv_b_inf = Signal()
                            fdiv_a_zero = Signal()
                            fdiv_b_zero = Signal()
                            fdiv_a_mant = Signal(24)
                            fdiv_b_mant = Signal(24)
                            fdiv_quot = Signal(48)
                            fdiv_remainder = Signal(48)
                            fdiv_norm = Signal(29)
                            fdiv_mant = Signal(24)
                            fdiv_guard = Signal()
                            fdiv_lower = Signal()
                            fdiv_inexact = Signal()
                            fdiv_rm = Signal(3)
                            fdiv_increment = Signal()
                            fdiv_rounded = Signal(25)
                            fdiv_exp_base = Signal(9)
                            fdiv_exp = Signal(8)
                            fdiv_frac = Signal(23)
                            fdiv_result = Signal(32)
                            m.d.comb += [
                                fdiv_a_sign.eq(fp_ex1_a[31]),
                                fdiv_b_sign.eq(fp_ex1_b[31]),
                                fdiv_sign.eq(fp_ex1_a[31] ^ fp_ex1_b[31]),
                                fdiv_a_exp.eq(fp_ex1_a[23:31]),
                                fdiv_b_exp.eq(fp_ex1_b[23:31]),
                                fdiv_a_frac.eq(fp_ex1_a[0:23]),
                                fdiv_b_frac.eq(fp_ex1_b[0:23]),
                                fdiv_a_nan.eq((fdiv_a_exp == 0xff) & (fdiv_a_frac != 0)),
                                fdiv_b_nan.eq((fdiv_b_exp == 0xff) & (fdiv_b_frac != 0)),
                                fdiv_a_snan.eq((fdiv_a_exp == 0xff) & (fdiv_a_frac != 0) & ~fdiv_a_frac[22]),
                                fdiv_b_snan.eq((fdiv_b_exp == 0xff) & (fdiv_b_frac != 0) & ~fdiv_b_frac[22]),
                                fdiv_a_inf.eq((fdiv_a_exp == 0xff) & (fdiv_a_frac == 0)),
                                fdiv_b_inf.eq((fdiv_b_exp == 0xff) & (fdiv_b_frac == 0)),
                                fdiv_a_zero.eq(fp_ex1_a[0:31] == 0),
                                fdiv_b_zero.eq(fp_ex1_b[0:31] == 0),
                                fdiv_a_mant.eq(Cat(fdiv_a_frac, Mux(fdiv_a_exp == 0, 0, 1))),
                                fdiv_b_mant.eq(Cat(fdiv_b_frac, Mux(fdiv_b_exp == 0, 0, 1))),
                                fdiv_quot.eq(Mux(fdiv_b_mant == 0, 0, (fdiv_a_mant << 27) // fdiv_b_mant)),
                                fdiv_remainder.eq(Mux(fdiv_b_mant == 0, 0, (fdiv_a_mant << 27) % fdiv_b_mant)),
                                fdiv_norm.eq(Mux(fdiv_quot[27],
                                                 (fdiv_quot >> 1) | (fdiv_quot[0] | (fdiv_remainder != 0)),
                                                 fdiv_quot)),
                                fdiv_mant.eq(fdiv_norm[3:27]),
                                fdiv_guard.eq(fdiv_norm[2]),
                                fdiv_lower.eq((fdiv_norm[0:2] != 0) | (fdiv_remainder != 0)),
                                fdiv_inexact.eq(fdiv_guard | fdiv_lower),
                                fdiv_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                fdiv_increment.eq(
                                    Mux(fdiv_rm == 0b000, fdiv_guard & (fdiv_lower | fdiv_mant[0]),
                                    Mux(fdiv_rm == 0b001, 0,
                                    Mux(fdiv_rm == 0b010, fdiv_sign & fdiv_inexact,
                                    Mux(fdiv_rm == 0b011, ~fdiv_sign & fdiv_inexact,
                                    Mux(fdiv_rm == 0b100, fdiv_guard, 0)))))
                                ),
                                fdiv_rounded.eq(fdiv_mant + fdiv_increment),
                                fdiv_exp_base.eq(fdiv_a_exp - fdiv_b_exp + 127),
                                fdiv_exp.eq(Mux(fdiv_quot[27], fdiv_exp_base, fdiv_exp_base - 1) + fdiv_rounded[24]),
                                fdiv_frac.eq(Mux(fdiv_rounded[24], fdiv_rounded[1:24], fdiv_rounded[0:23])),
                                fdiv_result.eq(Cat(fdiv_frac, fdiv_exp, fdiv_sign)),
                            ]
                            with m.If(fdiv_a_nan | fdiv_b_nan | (fdiv_a_zero & fdiv_b_zero) | (fdiv_a_inf & fdiv_b_inf)):
                                m.d.comb += fdiv_result.eq(0x7fc00000)
                            with m.Elif(fdiv_b_zero):
                                m.d.comb += fdiv_result.eq(Cat(C(0, 23), C(0xff, 8), fdiv_sign))
                            with m.Elif(fdiv_a_zero):
                                m.d.comb += fdiv_result.eq(Cat(C(0, 31), fdiv_sign))
                            with m.Elif(fdiv_a_inf):
                                m.d.comb += fdiv_result.eq(Cat(C(0, 23), C(0xff, 8), fdiv_sign))
                            with m.Elif(fdiv_b_inf):
                                m.d.comb += fdiv_result.eq(Cat(C(0, 31), fdiv_sign))
                            with m.If(fdiv_a_snan | fdiv_b_snan | (fdiv_a_zero & fdiv_b_zero) | (fdiv_a_inf & fdiv_b_inf)):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                            with m.Elif(~fdiv_a_nan & ~fdiv_a_inf & ~fdiv_a_zero & fdiv_b_zero):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b01000)
                            with m.Elif(~fdiv_a_nan & ~fdiv_b_nan & ~fdiv_a_inf & ~fdiv_b_inf &
                                        ~fdiv_a_zero & ~fdiv_b_zero & fdiv_inexact):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                            m.d.comb += [
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(Cat(fdiv_result, C(0xFFFFFFFF, 32))),
                            ]
                        with m.Elif(IS.funct7 == 0b0001000):  # FMUL.S
                            fmul_a_sign = Signal()
                            fmul_b_sign = Signal()
                            fmul_sign = Signal()
                            fmul_a_exp = Signal(8)
                            fmul_b_exp = Signal(8)
                            fmul_a_frac = Signal(23)
                            fmul_b_frac = Signal(23)
                            fmul_a_nan = Signal()
                            fmul_b_nan = Signal()
                            fmul_a_snan = Signal()
                            fmul_b_snan = Signal()
                            fmul_a_inf = Signal()
                            fmul_b_inf = Signal()
                            fmul_a_zero = Signal()
                            fmul_b_zero = Signal()
                            fmul_a_mant = Signal(24)
                            fmul_b_mant = Signal(24)
                            fmul_prod = Signal(48)
                            fmul_mant = Signal(24)
                            fmul_guard = Signal()
                            fmul_lower = Signal()
                            fmul_inexact = Signal()
                            fmul_rm = Signal(3)
                            fmul_increment = Signal()
                            fmul_rounded = Signal(25)
                            fmul_exp_base = Signal(9)
                            fmul_exp = Signal(9)
                            fmul_frac = Signal(23)
                            fmul_overflow = Signal()
                            fmul_overflow_to_inf = Signal()
                            fmul_result = Signal(32)
                            m.d.comb += [
                                fmul_a_sign.eq(fp_ex1_a[31]),
                                fmul_b_sign.eq(fp_ex1_b[31]),
                                fmul_sign.eq(fp_ex1_a[31] ^ fp_ex1_b[31]),
                                fmul_a_exp.eq(fp_ex1_a[23:31]),
                                fmul_b_exp.eq(fp_ex1_b[23:31]),
                                fmul_a_frac.eq(fp_ex1_a[0:23]),
                                fmul_b_frac.eq(fp_ex1_b[0:23]),
                                fmul_a_nan.eq((fmul_a_exp == 0xff) & (fmul_a_frac != 0)),
                                fmul_b_nan.eq((fmul_b_exp == 0xff) & (fmul_b_frac != 0)),
                                fmul_a_snan.eq((fmul_a_exp == 0xff) & (fmul_a_frac != 0) & ~fmul_a_frac[22]),
                                fmul_b_snan.eq((fmul_b_exp == 0xff) & (fmul_b_frac != 0) & ~fmul_b_frac[22]),
                                fmul_a_inf.eq((fmul_a_exp == 0xff) & (fmul_a_frac == 0)),
                                fmul_b_inf.eq((fmul_b_exp == 0xff) & (fmul_b_frac == 0)),
                                fmul_a_zero.eq(fp_ex1_a[0:31] == 0),
                                fmul_b_zero.eq(fp_ex1_b[0:31] == 0),
                                fmul_a_mant.eq(Cat(fmul_a_frac, Mux(fmul_a_exp == 0, 0, 1))),
                                fmul_b_mant.eq(Cat(fmul_b_frac, Mux(fmul_b_exp == 0, 0, 1))),
                                fmul_prod.eq(fmul_a_mant * fmul_b_mant),
                                fmul_mant.eq(Mux(fmul_prod[47], fmul_prod[24:48], fmul_prod[23:47])),
                                fmul_guard.eq(Mux(fmul_prod[47], fmul_prod[23], fmul_prod[22])),
                                fmul_lower.eq(Mux(fmul_prod[47], fmul_prod[0:23] != 0,
                                                  fmul_prod[0:22] != 0)),
                                fmul_inexact.eq(fmul_guard | fmul_lower),
                                fmul_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                fmul_increment.eq(
                                    Mux(fmul_rm == 0b000, fmul_guard & (fmul_lower | fmul_mant[0]),
                                    Mux(fmul_rm == 0b001, 0,
                                    Mux(fmul_rm == 0b010, fmul_sign & fmul_inexact,
                                    Mux(fmul_rm == 0b011, ~fmul_sign & fmul_inexact,
                                    Mux(fmul_rm == 0b100, fmul_guard, 0)))))
                                ),
                                fmul_rounded.eq(fmul_mant + fmul_increment),
                                fmul_exp_base.eq(fmul_a_exp + fmul_b_exp - 127),
                                fmul_exp.eq(Mux(fmul_prod[47], fmul_exp_base + 1, fmul_exp_base) + fmul_rounded[24]),
                                fmul_frac.eq(Mux(fmul_rounded[24], fmul_rounded[1:24], fmul_rounded[0:23])),
                                fmul_overflow.eq(fmul_exp >= 0xff),
                                fmul_overflow_to_inf.eq(
                                    (fmul_rm == 0b000) | (fmul_rm == 0b100) |
                                    ((fmul_rm == 0b011) & ~fmul_sign) |
                                    ((fmul_rm == 0b010) & fmul_sign)),
                                fmul_result.eq(Cat(fmul_frac, fmul_exp[0:8], fmul_sign)),
                            ]
                            with m.If(fmul_a_nan | fmul_b_nan | (fmul_a_zero & fmul_b_inf) | (fmul_b_zero & fmul_a_inf)):
                                m.d.comb += fmul_result.eq(0x7fc00000)
                            with m.Elif(fmul_a_inf | fmul_b_inf):
                                m.d.comb += fmul_result.eq(Cat(C(0, 23), C(0xff, 8), fmul_sign))
                            with m.Elif(fmul_a_zero | fmul_b_zero):
                                m.d.comb += fmul_result.eq(Cat(C(0, 31), fmul_sign))
                            with m.Elif(fmul_overflow):
                                m.d.comb += fmul_result.eq(Mux(
                                    fmul_overflow_to_inf,
                                    Cat(C(0, 23), C(0xff, 8), fmul_sign),
                                    Cat(C(0x7fffff, 23), C(0xfe, 8), fmul_sign)))
                            with m.If(fmul_a_snan | fmul_b_snan | (fmul_a_zero & fmul_b_inf) | (fmul_b_zero & fmul_a_inf)):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                            with m.Elif(~fmul_a_nan & ~fmul_b_nan & ~fmul_a_inf & ~fmul_b_inf &
                                        ~fmul_a_zero & ~fmul_b_zero & fmul_overflow):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b00101)
                            with m.Elif(~fmul_a_nan & ~fmul_b_nan & ~fmul_a_inf & ~fmul_b_inf &
                                        ~fmul_a_zero & ~fmul_b_zero & fmul_inexact):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                            m.d.comb += [
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(Cat(fmul_result, C(0xFFFFFFFF, 32))),
                            ]
                        with m.Elif((IS.funct7 == 0b0000000) | (IS.funct7 == 0b0000100)):  # FADD.S / FSUB.S
                            fa_sign = Signal()
                            fb_sign = Signal()
                            fb_eff_sign = Signal()
                            fa_exp = Signal(8)
                            fb_exp = Signal(8)
                            fa_frac = Signal(23)
                            fb_frac = Signal(23)
                            fa_nan = Signal()
                            fb_nan = Signal()
                            fa_snan = Signal()
                            fb_snan = Signal()
                            fa_inf = Signal()
                            fb_inf = Signal()
                            fadd_invalid = Signal()
                            fa_mant = Signal(24)
                            fb_mant = Signal(24)
                            a_mag_ge = Signal()
                            larger_sign = Signal()
                            larger_exp = Signal(9)
                            smaller_exp = Signal(9)
                            larger_mant = Signal(24)
                            smaller_mant = Signal(24)
                            exp_delta = Signal(9)
                            align_shift = Signal(5)
                            larger_ext = Signal(28)
                            smaller_ext = Signal(28)
                            shifted_small = Signal(28)
                            align_mask = Signal(28)
                            align_sticky = Signal()
                            same_sign = Signal()
                            add_sum = Signal(29)
                            diff_mant = Signal(28)
                            leading_shift = Signal(5)
                            actual_shift = Signal(5)
                            norm_ext = Signal(28)
                            norm_exp = Signal(9)
                            round_rm = Signal(3)
                            round_inexact = Signal()
                            round_increment = Signal()
                            rounded_mant = Signal(25)
                            packed_exp = Signal(9)
                            final_exp = Signal(9)
                            final_frac = Signal(23)
                            round_overflow = Signal()
                            round_tiny = Signal()
                            overflow_to_inf = Signal()
                            finite_nonzero = Signal()
                            faddsub_result = Signal(32)
                            m.d.comb += [
                                fa_sign.eq(fp_ex1_a[31]),
                                fb_sign.eq(fp_ex1_b[31]),
                                fb_eff_sign.eq(fp_ex1_b[31] ^ (IS.funct7 == 0b0000100)),
                                fa_exp.eq(fp_ex1_a[23:31]),
                                fb_exp.eq(fp_ex1_b[23:31]),
                                fa_frac.eq(fp_ex1_a[0:23]),
                                fb_frac.eq(fp_ex1_b[0:23]),
                                fa_nan.eq((fa_exp == 0xff) & (fa_frac != 0)),
                                fb_nan.eq((fb_exp == 0xff) & (fb_frac != 0)),
                                fa_snan.eq((fa_exp == 0xff) & (fa_frac != 0) & ~fa_frac[22]),
                                fb_snan.eq((fb_exp == 0xff) & (fb_frac != 0) & ~fb_frac[22]),
                                fa_inf.eq((fa_exp == 0xff) & (fa_frac == 0)),
                                fb_inf.eq((fb_exp == 0xff) & (fb_frac == 0)),
                                fadd_invalid.eq(fa_snan | fb_snan | (fa_inf & fb_inf & (fa_sign != fb_eff_sign))),
                                fa_mant.eq(Cat(fa_frac, Mux(fa_exp == 0, 0, 1))),
                                fb_mant.eq(Cat(fb_frac, Mux(fb_exp == 0, 0, 1))),
                                a_mag_ge.eq((fa_exp > fb_exp) | ((fa_exp == fb_exp) & (fa_frac >= fb_frac))),
                                larger_sign.eq(Mux(a_mag_ge, fa_sign, fb_eff_sign)),
                                larger_exp.eq(Mux(a_mag_ge, Mux(fa_exp == 0, 1, fa_exp), Mux(fb_exp == 0, 1, fb_exp))),
                                smaller_exp.eq(Mux(a_mag_ge, Mux(fb_exp == 0, 1, fb_exp), Mux(fa_exp == 0, 1, fa_exp))),
                                larger_mant.eq(Mux(a_mag_ge, fa_mant, fb_mant)),
                                smaller_mant.eq(Mux(a_mag_ge, fb_mant, fa_mant)),
                                exp_delta.eq(larger_exp - smaller_exp),
                                align_shift.eq(Mux(exp_delta > 27, 27, exp_delta)),
                                larger_ext.eq(larger_mant << 3),
                                smaller_ext.eq(smaller_mant << 3),
                                align_mask.eq((C(1, 28) << align_shift) - 1),
                                align_sticky.eq((smaller_ext & align_mask) != 0),
                                shifted_small.eq((smaller_ext >> align_shift) | align_sticky),
                                same_sign.eq(fa_sign == fb_eff_sign),
                                add_sum.eq(larger_ext + shifted_small),
                                diff_mant.eq(larger_ext - shifted_small),
                                round_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                finite_nonzero.eq(~fa_nan & ~fb_nan & ~fa_inf & ~fb_inf &
                                                  ((fa_exp != 0) | (fa_frac != 0) |
                                                   (fb_exp != 0) | (fb_frac != 0))),
                                leading_shift.eq(0),
                                actual_shift.eq(Mux(leading_shift > (larger_exp - 1), larger_exp - 1, leading_shift)),
                                norm_ext.eq(0),
                                norm_exp.eq(larger_exp),
                                round_inexact.eq(norm_ext[0:3] != 0),
                                round_increment.eq(
                                    Mux(round_rm == 0b000,
                                        norm_ext[2] & (norm_ext[1] | norm_ext[0] | norm_ext[3]),
                                    Mux(round_rm == 0b001, 0,
                                    Mux(round_rm == 0b010, larger_sign & round_inexact,
                                    Mux(round_rm == 0b011, ~larger_sign & round_inexact,
                                    Mux(round_rm == 0b100, norm_ext[2], 0)))))
                                ),
                                rounded_mant.eq(norm_ext[3:27] + round_increment),
                                packed_exp.eq(Mux((norm_exp == 1) & ~norm_ext[26], 0, norm_exp)),
                                final_exp.eq(Mux(rounded_mant[24], packed_exp + 1,
                                                 Mux((packed_exp == 0) & rounded_mant[23], 1, packed_exp))),
                                final_frac.eq(Mux(rounded_mant[24], rounded_mant[1:24], rounded_mant[0:23])),
                                round_overflow.eq(final_exp >= 0xff),
                                round_tiny.eq((final_exp == 0) & round_inexact),
                                overflow_to_inf.eq((round_rm == 0b000) | (round_rm == 0b100) |
                                                   ((round_rm == 0b011) & ~larger_sign) |
                                                   ((round_rm == 0b010) & larger_sign)),
                                faddsub_result.eq(0x7fc00000),
                            ]
                            for bit in range(28):
                                with m.If(diff_mant[bit]):
                                    m.d.comb += leading_shift.eq(26 - bit if bit <= 26 else 0)
                            with m.If(same_sign):
                                with m.If(add_sum[27]):
                                    m.d.comb += [
                                        norm_ext.eq((add_sum >> 1) | add_sum[0]),
                                        norm_exp.eq(larger_exp + 1),
                                    ]
                                with m.Else():
                                    m.d.comb += norm_ext.eq(add_sum[0:28])
                            with m.Else():
                                m.d.comb += [
                                    norm_ext.eq(diff_mant << actual_shift),
                                    norm_exp.eq(larger_exp - actual_shift),
                                ]
                            with m.If(fa_nan | fb_nan | (fa_inf & fb_inf & (fa_sign != fb_eff_sign))):
                                m.d.comb += faddsub_result.eq(0x7fc00000)
                            with m.Elif(fa_inf):
                                m.d.comb += faddsub_result.eq(fp_ex1_a[0:32])
                            with m.Elif(fb_inf):
                                m.d.comb += faddsub_result.eq(Cat(C(0, 23), C(0xff, 8), fb_eff_sign))
                            with m.Elif(~finite_nonzero | ((~same_sign) & (diff_mant == 0))):
                                m.d.comb += faddsub_result.eq(Cat(
                                    C(0, 31),
                                    Mux((fa_exp == 0) & (fa_frac == 0) &
                                        (fb_exp == 0) & (fb_frac == 0) &
                                        (fa_sign == fb_eff_sign),
                                        fa_sign, round_rm == 0b010)))
                            with m.Elif(round_overflow):
                                with m.If(overflow_to_inf):
                                    m.d.comb += faddsub_result.eq(Cat(C(0, 23), C(0xff, 8), larger_sign))
                                with m.Else():
                                    m.d.comb += faddsub_result.eq(Cat(C(0x7fffff, 23), C(0xfe, 8), larger_sign))
                            with m.Else():
                                m.d.comb += faddsub_result.eq(Cat(final_frac, final_exp[0:8], larger_sign))
                            with m.If(fadd_invalid):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                            with m.Elif(round_overflow & finite_nonzero):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b00101)
                            with m.Elif(round_tiny & finite_nonzero):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b00011)
                            with m.Elif(round_inexact & finite_nonzero):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                            m.d.comb += [
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(Cat(faddsub_result, C(0xFFFFFFFF, 32))),
                            ]
                        with m.Elif(self.enable_zfa & (IS.funct7 == 0b0100000) &
                                    ((IS.rs2 == 4) | (IS.rs2 == 5))):  # FROUND.S / FROUNDNX.S
                            fround_exp = Signal(8)
                            fround_frac = Signal(23)
                            fround_sign = Signal()
                            fround_nan = Signal()
                            fround_snan = Signal()
                            fround_inf = Signal()
                            fround_zero = Signal()
                            fround_rm = Signal(3)
                            fround_rm_valid = Signal()
                            fround_mant = Signal(24)
                            fround_shamt = Signal(5)
                            fround_trunc = Signal(24)
                            fround_discarded = Signal(24)
                            fround_half = Signal(24)
                            fround_trunc_lsb = Signal()
                            fround_increment = Signal(25)
                            fround_rounded = Signal(25)
                            fround_inexact = Signal()
                            fround_result = Signal(32)
                            m.d.comb += [
                                fround_exp.eq(fp_ex1_a[23:31]),
                                fround_frac.eq(fp_ex1_a[0:23]),
                                fround_sign.eq(fp_ex1_a[31]),
                                fround_nan.eq((fround_exp == 0xff) & (fround_frac != 0)),
                                fround_snan.eq((fround_exp == 0xff) & (fround_frac != 0) & ~fround_frac[22]),
                                fround_inf.eq((fround_exp == 0xff) & (fround_frac == 0)),
                                fround_zero.eq((fround_exp == 0) & (fround_frac == 0)),
                                fround_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                fround_rm_valid.eq(fround_rm <= 0b100),
                                fround_mant.eq(Cat(fround_frac, C(1, 1))),
                                fround_shamt.eq(150 - fround_exp),
                                fround_trunc.eq((fround_mant >> fround_shamt) << fround_shamt),
                                fround_discarded.eq(fround_mant - fround_trunc),
                                fround_half.eq(C(1, 24) << (fround_shamt - C(1, 5)).as_unsigned()),
                                fround_trunc_lsb.eq((fround_trunc >> fround_shamt)[0]),
                                fround_increment.eq(0),
                                fround_rounded.eq(fround_trunc + fround_increment),
                                fround_inexact.eq(
                                    ~(fround_nan | fround_inf | fround_zero) &
                                    ((fround_exp < 127) |
                                     ((fround_exp < 150) & (fround_discarded != 0)))
                                ),
                                fround_result.eq(fp_ex1_a[0:32]),
                            ]
                            with m.If((fround_exp >= 127) & (fround_exp < 150)):
                                with m.Switch(fround_rm):
                                    with m.Case(0b000):  # RNE
                                        with m.If((fround_discarded > fround_half) |
                                                  ((fround_discarded == fround_half) &
                                                   fround_trunc_lsb)):
                                            m.d.comb += fround_increment.eq(C(1, 25) << fround_shamt)
                                    with m.Case(0b001):  # RTZ
                                        pass
                                    with m.Case(0b010):  # RDN
                                        with m.If(fround_sign & (fround_discarded != 0)):
                                            m.d.comb += fround_increment.eq(C(1, 25) << fround_shamt)
                                    with m.Case(0b011):  # RUP
                                        with m.If(~fround_sign & (fround_discarded != 0)):
                                            m.d.comb += fround_increment.eq(C(1, 25) << fround_shamt)
                                    with m.Case(0b100):  # RMM
                                        with m.If(fround_discarded >= fround_half):
                                            m.d.comb += fround_increment.eq(C(1, 25) << fround_shamt)
                                m.d.comb += fround_result.eq(Mux(
                                    fround_rounded[24],
                                    Cat(C(0, 23), (fround_exp + 1)[0:8], fround_sign),
                                    Cat(fround_rounded[0:23], fround_exp, fround_sign),
                                ))
                            with m.Elif((fround_exp < 127) & ~fround_zero):
                                fround_to_one = Signal()
                                m.d.comb += fround_to_one.eq(Mux(
                                    fround_rm == 0b000,
                                    (fround_exp == 126) & (fround_frac != 0),
                                    Mux(
                                        fround_rm == 0b100,
                                        fround_exp == 126,
                                        Mux(
                                            fround_rm == 0b010,
                                            fround_sign,
                                            Mux(fround_rm == 0b011, ~fround_sign, 0),
                                        ),
                                    ),
                                ))
                                m.d.comb += fround_result.eq(Mux(
                                    fround_to_one,
                                    Cat(C(0, 23), C(127, 8), fround_sign),
                                    Cat(C(0, 31), fround_sign),
                                ))
                            with m.Elif(fround_nan):
                                m.d.comb += fround_result.eq(0x7fc00000)
                            with m.If(fround_rm_valid):
                                m.d.comb += [
                                    fp_wb_en.eq(1),
                                    fp_wb_data.eq(Cat(fround_result, C(0xFFFFFFFF, 32))),
                                ]
                                with m.If(fround_snan):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                                with m.Elif((IS.rs2 == 5) & fround_inexact):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                        with m.Elif(self.enable_zfa & self.enable_zfh &
                                    (IS.funct7 == 0b0100010) &
                                    ((IS.rs2 == 4) | (IS.rs2 == 5))):  # FROUND.H / FROUNDNX.H
                            hround_raw = Signal(16)
                            hround_exp = Signal(5)
                            hround_frac = Signal(10)
                            hround_sign = Signal()
                            hround_nan = Signal()
                            hround_snan = Signal()
                            hround_inf = Signal()
                            hround_zero = Signal()
                            hround_rm = Signal(3)
                            hround_rm_valid = Signal()
                            hround_mant = Signal(11)
                            hround_shamt = Signal(5)
                            hround_trunc = Signal(11)
                            hround_discarded = Signal(11)
                            hround_half = Signal(11)
                            hround_trunc_lsb = Signal()
                            hround_increment = Signal(12)
                            hround_rounded = Signal(12)
                            hround_inexact = Signal()
                            hround_result = Signal(16)
                            m.d.comb += [
                                hround_raw.eq(Mux(
                                    fp_ex1_a[16:64] == C(0xffffffffffff, 48),
                                    fp_ex1_a[0:16], C(0x7e00, 16))),
                                hround_exp.eq(hround_raw[10:15]),
                                hround_frac.eq(hround_raw[0:10]),
                                hround_sign.eq(hround_raw[15]),
                                hround_nan.eq((hround_exp == 0x1f) & (hround_frac != 0)),
                                hround_snan.eq(hround_nan & ~hround_frac[9]),
                                hround_inf.eq((hround_exp == 0x1f) & (hround_frac == 0)),
                                hround_zero.eq((hround_exp == 0) & (hround_frac == 0)),
                                hround_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                hround_rm_valid.eq(hround_rm <= 0b100),
                                hround_mant.eq(Cat(hround_frac, C(1, 1))),
                                hround_shamt.eq(25 - hround_exp),
                                hround_trunc.eq((hround_mant >> hround_shamt) << hround_shamt),
                                hround_discarded.eq(hround_mant - hround_trunc),
                                hround_half.eq(C(1, 11) <<
                                               (hround_shamt - C(1, 5)).as_unsigned()),
                                hround_trunc_lsb.eq((hround_trunc >> hround_shamt)[0]),
                                hround_increment.eq(0),
                                hround_rounded.eq(hround_trunc + hround_increment),
                                hround_inexact.eq(
                                    ~(hround_nan | hround_inf | hround_zero) &
                                    ((hround_exp < 15) |
                                     ((hround_exp < 25) & (hround_discarded != 0)))),
                                hround_result.eq(hround_raw),
                            ]
                            with m.If((hround_exp >= 15) & (hround_exp < 25)):
                                with m.Switch(hround_rm):
                                    with m.Case(0b000):
                                        with m.If((hround_discarded > hround_half) |
                                                  ((hround_discarded == hround_half) &
                                                   hround_trunc_lsb)):
                                            m.d.comb += hround_increment.eq(
                                                C(1, 12) << hround_shamt)
                                    with m.Case(0b001):
                                        pass
                                    with m.Case(0b010):
                                        with m.If(hround_sign & (hround_discarded != 0)):
                                            m.d.comb += hround_increment.eq(
                                                C(1, 12) << hround_shamt)
                                    with m.Case(0b011):
                                        with m.If(~hround_sign & (hround_discarded != 0)):
                                            m.d.comb += hround_increment.eq(
                                                C(1, 12) << hround_shamt)
                                    with m.Case(0b100):
                                        with m.If(hround_discarded >= hround_half):
                                            m.d.comb += hround_increment.eq(
                                                C(1, 12) << hround_shamt)
                                m.d.comb += hround_result.eq(Mux(
                                    hround_rounded[11],
                                    Cat(C(0, 10), (hround_exp + 1)[0:5], hround_sign),
                                    Cat(hround_rounded[0:10], hround_exp, hround_sign)))
                            with m.Elif((hround_exp < 15) & ~hround_zero):
                                hround_to_one = Signal()
                                m.d.comb += hround_to_one.eq(Mux(
                                    hround_rm == 0b000,
                                    (hround_exp == 14) & (hround_frac != 0),
                                    Mux(hround_rm == 0b100,
                                        hround_exp == 14,
                                        Mux(hround_rm == 0b010,
                                            hround_sign,
                                            Mux(hround_rm == 0b011,
                                                ~hround_sign, 0)))))
                                m.d.comb += hround_result.eq(Mux(
                                    hround_to_one,
                                    Cat(C(0, 10), C(15, 5), hround_sign),
                                    Cat(C(0, 15), hround_sign)))
                            with m.Elif(hround_nan):
                                m.d.comb += hround_result.eq(0x7e00)
                            with m.If(hround_rm_valid):
                                m.d.comb += [
                                    fp_wb_en.eq(1),
                                    fp_wb_data.eq(Cat(hround_result,
                                                        C(0xffffffffffff, 48))),
                                ]
                                with m.If(hround_snan):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                                with m.Elif((IS.rs2 == 5) & hround_inexact):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                        with m.Elif(self.enable_zfh & (IS.funct7 == 0b0010010) & (IS.funct3 <= 0b010)):  # FSGNJ.H / FSGNJN.H / FSGNJX.H
                            hfsgnj_a = Signal(16)
                            hfsgnj_b = Signal(16)
                            hfsgnj_sign = Signal()
                            hfsgnj_word = Signal(16)
                            m.d.comb += [
                                hfsgnj_a.eq(Mux(
                                    fp_ex1_a[16:64] == C(0xffffffffffff, 48),
                                    fp_ex1_a[0:16],
                                    C(0x7e00, 16),
                                )),
                                hfsgnj_b.eq(Mux(
                                    fp_ex1_b[16:64] == C(0xffffffffffff, 48),
                                    fp_ex1_b[0:16],
                                    C(0x7e00, 16),
                                )),
                                hfsgnj_sign.eq(Mux(
                                    IS.funct3 == 0b000,
                                    hfsgnj_b[15],
                                    Mux(
                                        IS.funct3 == 0b001,
                                        ~hfsgnj_b[15],
                                        hfsgnj_a[15] ^ hfsgnj_b[15],
                                    ),
                                )),
                                hfsgnj_word.eq(Cat(hfsgnj_a[0:15], hfsgnj_sign)),
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(Cat(hfsgnj_word, C(0xffffffffffff, 48))),
                            ]
                        with m.Elif(self.enable_zfh & (IS.funct7 == 0b0010110) &
                                    ((IS.funct3 <= 0b001) |
                                     (self.enable_zfa & (IS.funct3 <= 0b011)))):  # FMIN[ M].H / FMAX[M].H
                            hminmax_a = Signal(16)
                            hminmax_b = Signal(16)
                            hminmax_a_exp = Signal(5)
                            hminmax_b_exp = Signal(5)
                            hminmax_a_frac = Signal(10)
                            hminmax_b_frac = Signal(10)
                            hminmax_a_nan = Signal()
                            hminmax_b_nan = Signal()
                            hminmax_a_snan = Signal()
                            hminmax_b_snan = Signal()
                            hminmax_a_zero = Signal()
                            hminmax_b_zero = Signal()
                            hminmax_eq = Signal()
                            hminmax_a_lt_b = Signal()
                            hminmax_result = Signal(16)
                            m.d.comb += [
                                hminmax_a.eq(Mux(
                                    fp_ex1_a[16:64] == C(0xffffffffffff, 48),
                                    fp_ex1_a[0:16],
                                    C(0x7e00, 16),
                                )),
                                hminmax_b.eq(Mux(
                                    fp_ex1_b[16:64] == C(0xffffffffffff, 48),
                                    fp_ex1_b[0:16],
                                    C(0x7e00, 16),
                                )),
                                hminmax_a_exp.eq(hminmax_a[10:15]),
                                hminmax_b_exp.eq(hminmax_b[10:15]),
                                hminmax_a_frac.eq(hminmax_a[0:10]),
                                hminmax_b_frac.eq(hminmax_b[0:10]),
                                hminmax_a_nan.eq((hminmax_a_exp == 0x1f) & (hminmax_a_frac != 0)),
                                hminmax_b_nan.eq((hminmax_b_exp == 0x1f) & (hminmax_b_frac != 0)),
                                hminmax_a_snan.eq(hminmax_a_nan & ~hminmax_a_frac[9]),
                                hminmax_b_snan.eq(hminmax_b_nan & ~hminmax_b_frac[9]),
                                hminmax_a_zero.eq((hminmax_a_exp == 0) & (hminmax_a_frac == 0)),
                                hminmax_b_zero.eq((hminmax_b_exp == 0) & (hminmax_b_frac == 0)),
                                hminmax_eq.eq((hminmax_a == hminmax_b) | (hminmax_a_zero & hminmax_b_zero)),
                                hminmax_a_lt_b.eq(~hminmax_eq & Mux(
                                    hminmax_a[15] != hminmax_b[15],
                                    hminmax_a[15],
                                    Mux(
                                        hminmax_a[15],
                                        hminmax_a[0:15] > hminmax_b[0:15],
                                        hminmax_a[0:15] < hminmax_b[0:15],
                                    ),
                                )),
                                hminmax_result.eq(Mux(
                                    IS.funct3[1] & (hminmax_a_nan | hminmax_b_nan),
                                    C(0x7e00, 16),
                                    Mux(hminmax_a_nan & hminmax_b_nan,
                                    C(0x7e00, 16),
                                    Mux(
                                        hminmax_a_nan,
                                        hminmax_b,
                                        Mux(
                                            hminmax_b_nan,
                                            hminmax_a,
                                            Mux(
                                                hminmax_a_zero & hminmax_b_zero,
                                                Cat(C(0, 15), Mux(
                                                    IS.funct3[0] == 0,
                                                    hminmax_a[15] | hminmax_b[15],
                                                    hminmax_a[15] & hminmax_b[15],
                                                )),
                                                Mux(
                                                    IS.funct3[0] == 0,
                                                    Mux(hminmax_a_lt_b, hminmax_a, hminmax_b),
                                                    Mux(hminmax_a_lt_b, hminmax_b, hminmax_a),
                                                ),
                                            ),
                                        ),
                                    )),
                                )),
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(Cat(hminmax_result, C(0xffffffffffff, 48))),
                            ]
                            with m.If(hminmax_a_snan | hminmax_b_snan):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                        with m.Elif(self.enable_zfh & (IS.funct7 == 0b0101110) & (IS.rs2 == 0)):  # FSQRT.H
                            hsqrt_raw = Signal(16)
                            hsqrt_exp = Signal(5)
                            hsqrt_frac = Signal(10)
                            hsqrt_sign = Signal()
                            hsqrt_nan = Signal()
                            hsqrt_snan = Signal()
                            hsqrt_zero = Signal()
                            hsqrt_inf = Signal()
                            hsqrt_rm = Signal(3)
                            hsqrt_rm_valid = Signal()
                            hsqrt_mant = Signal(11)
                            hsqrt_unbiased = Signal(signed(7))
                            hsqrt_radicand = Signal(22)
                            hsqrt_root = Signal(12)
                            hsqrt_remainder = Signal(24)
                            hsqrt_increment = Signal()
                            hsqrt_rounded = Signal(12)
                            hsqrt_half_exp = Signal(signed(7))
                            hsqrt_biased_exp = Signal(6)
                            hsqrt_result = Signal(16)
                            m.d.comb += [
                                hsqrt_raw.eq(Mux(fp_ex1_a[16:64] == C(0xffffffffffff, 48),
                                                 fp_ex1_a[0:16], C(0x7e00, 16))),
                                hsqrt_exp.eq(hsqrt_raw[10:15]),
                                hsqrt_frac.eq(hsqrt_raw[0:10]),
                                hsqrt_sign.eq(hsqrt_raw[15]),
                                hsqrt_nan.eq((hsqrt_exp == 0x1f) & (hsqrt_frac != 0)),
                                hsqrt_snan.eq((hsqrt_exp == 0x1f) & (hsqrt_frac != 0) &
                                               ~hsqrt_frac[9]),
                                hsqrt_zero.eq((hsqrt_exp == 0) & (hsqrt_frac == 0)),
                                hsqrt_inf.eq((hsqrt_exp == 0x1f) & (hsqrt_frac == 0)),
                                hsqrt_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                hsqrt_rm_valid.eq(hsqrt_rm <= 4),
                                hsqrt_mant.eq(Cat(hsqrt_frac, C(1, 1))),
                                hsqrt_unbiased.eq(hsqrt_exp - 15),
                                hsqrt_radicand.eq(Mux(hsqrt_unbiased[0],
                                                      hsqrt_mant << 11, hsqrt_mant << 10)),
                                hsqrt_result.eq(0x7e00),
                            ]
                            with m.If((hsqrt_exp == 0) & (hsqrt_frac != 0)):
                                m.d.comb += [hsqrt_mant.eq(0), hsqrt_unbiased.eq(-24)]
                                for bit in range(10):
                                    with m.If(hsqrt_frac[bit]):
                                        m.d.comb += [
                                            hsqrt_mant.eq(hsqrt_frac << (10 - bit)),
                                            hsqrt_unbiased.eq(bit - 24),
                                        ]
                            hsqrt_root_stages = [Signal(12, name=f"hsqrt_root_{stage}")
                                                 for stage in range(12)]
                            hsqrt_remainder_stages = [Signal(24, name=f"hsqrt_rem_{stage}")
                                                      for stage in range(12)]
                            m.d.comb += [hsqrt_root_stages[0].eq(0),
                                         hsqrt_remainder_stages[0].eq(0)]
                            for stage, pair_index in enumerate(reversed(range(11))):
                                pair = hsqrt_radicand[2 * pair_index:2 * pair_index + 2]
                                remainder_in = Signal(24, name=f"hsqrt_rem_in_{stage}")
                                root_shifted = Signal(12, name=f"hsqrt_root_shifted_{stage}")
                                trial = Signal(24, name=f"hsqrt_trial_{stage}")
                                take = Signal(name=f"hsqrt_take_{stage}")
                                m.d.comb += [
                                    remainder_in.eq(Cat(pair,
                                                        hsqrt_remainder_stages[stage][0:22])),
                                    root_shifted.eq(Cat(C(0, 1),
                                                        hsqrt_root_stages[stage][0:11])),
                                    trial.eq(Cat(C(1, 1), root_shifted, C(0, 12))),
                                    take.eq(remainder_in >= trial),
                                    hsqrt_remainder_stages[stage + 1].eq(
                                        Mux(take, remainder_in - trial, remainder_in)),
                                    hsqrt_root_stages[stage + 1].eq(
                                        Mux(take, root_shifted | 1, root_shifted)),
                                ]
                            m.d.comb += [
                                hsqrt_root.eq(hsqrt_root_stages[-1]),
                                hsqrt_remainder.eq(hsqrt_remainder_stages[-1]),
                                hsqrt_increment.eq(Mux(
                                    (hsqrt_rm == 0b000) | (hsqrt_rm == 0b100),
                                    hsqrt_remainder > hsqrt_root,
                                    Mux(hsqrt_rm == 0b011, hsqrt_remainder != 0, 0),
                                )),
                                hsqrt_rounded.eq(hsqrt_root + hsqrt_increment),
                                hsqrt_half_exp.eq(hsqrt_unbiased.as_signed() >> 1),
                                hsqrt_biased_exp.eq(hsqrt_half_exp + 15 + hsqrt_rounded[11]),
                            ]
                            with m.If(hsqrt_nan):
                                m.d.comb += hsqrt_result.eq(0x7e00)
                            with m.Elif(hsqrt_zero):
                                m.d.comb += hsqrt_result.eq(hsqrt_raw)
                            with m.Elif(hsqrt_sign):
                                m.d.comb += hsqrt_result.eq(0x7e00)
                            with m.Elif(hsqrt_inf):
                                m.d.comb += hsqrt_result.eq(hsqrt_raw)
                            with m.Else():
                                m.d.comb += hsqrt_result.eq(Cat(
                                    Mux(hsqrt_rounded[11], C(0, 10), hsqrt_rounded[0:10]),
                                    hsqrt_biased_exp[0:5], C(0, 1)))
                            with m.If(hsqrt_rm_valid):
                                m.d.comb += [
                                    fp_wb_en.eq(1),
                                    fp_wb_data.eq(Cat(hsqrt_result, C(0xffffffffffff, 48))),
                                ]
                                with m.If(hsqrt_snan |
                                          (hsqrt_sign & ~hsqrt_nan & ~hsqrt_zero)):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                                with m.Elif(~hsqrt_nan & ~hsqrt_inf & ~hsqrt_zero &
                                            (hsqrt_remainder != 0)):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                        with m.Elif(self.enable_zfh & (IS.funct7 == 0b0001110)):  # FDIV.H
                            hdiv_a = Signal(16)
                            hdiv_b = Signal(16)
                            hdiv_a_exp = Signal(5)
                            hdiv_b_exp = Signal(5)
                            hdiv_a_frac = Signal(10)
                            hdiv_b_frac = Signal(10)
                            hdiv_a_nan = Signal()
                            hdiv_b_nan = Signal()
                            hdiv_a_snan = Signal()
                            hdiv_b_snan = Signal()
                            hdiv_a_inf = Signal()
                            hdiv_b_inf = Signal()
                            hdiv_a_zero = Signal()
                            hdiv_b_zero = Signal()
                            hdiv_a_shift = Signal(5)
                            hdiv_b_shift = Signal(5)
                            hdiv_a_mag = Signal(43)
                            hdiv_b_mag = Signal(43)
                            hdiv_scaled = Signal(107)
                            hdiv_quotient = Signal(107)
                            hdiv_div_remainder = Signal(43)
                            hdiv_sign = Signal()
                            hdiv_msb = Signal(7)
                            hdiv_normal = Signal()
                            hdiv_right_shift = Signal(7)
                            hdiv_half_shift = Signal(7)
                            hdiv_retained = Signal(12)
                            hdiv_remainder = Signal(107)
                            hdiv_half = Signal(107)
                            hdiv_inexact = Signal()
                            hdiv_above_half = Signal()
                            hdiv_exact_half = Signal()
                            hdiv_rm = Signal(3)
                            hdiv_rm_valid = Signal()
                            hdiv_increment = Signal()
                            hdiv_rounded = Signal(12)
                            hdiv_exp = Signal(6)
                            hdiv_rounded_exp = Signal(6)
                            hdiv_to_inf = Signal()
                            hdiv_exact_over_max = Signal()
                            hdiv_overflow = Signal()
                            hdiv_underflow = Signal()
                            hdiv_invalid = Signal()
                            hdiv_divzero = Signal()
                            hdiv_finite_result = Signal(16)
                            hdiv_result = Signal(16)
                            m.d.comb += [
                                hdiv_a.eq(Mux(fp_ex1_a[16:64] == C(0xffffffffffff, 48),
                                             fp_ex1_a[0:16], C(0x7e00, 16))),
                                hdiv_b.eq(Mux(fp_ex1_b[16:64] == C(0xffffffffffff, 48),
                                             fp_ex1_b[0:16], C(0x7e00, 16))),
                                hdiv_a_exp.eq(hdiv_a[10:15]), hdiv_b_exp.eq(hdiv_b[10:15]),
                                hdiv_a_frac.eq(hdiv_a[0:10]), hdiv_b_frac.eq(hdiv_b[0:10]),
                                hdiv_a_nan.eq((hdiv_a_exp == 0x1f) & (hdiv_a_frac != 0)),
                                hdiv_b_nan.eq((hdiv_b_exp == 0x1f) & (hdiv_b_frac != 0)),
                                hdiv_a_snan.eq(hdiv_a_nan & ~hdiv_a_frac[9]),
                                hdiv_b_snan.eq(hdiv_b_nan & ~hdiv_b_frac[9]),
                                hdiv_a_inf.eq((hdiv_a_exp == 0x1f) & (hdiv_a_frac == 0)),
                                hdiv_b_inf.eq((hdiv_b_exp == 0x1f) & (hdiv_b_frac == 0)),
                                hdiv_a_zero.eq((hdiv_a_exp == 0) & (hdiv_a_frac == 0)),
                                hdiv_b_zero.eq((hdiv_b_exp == 0) & (hdiv_b_frac == 0)),
                                hdiv_a_shift.eq(Mux(hdiv_a_exp != 0, hdiv_a_exp - 1, 0)),
                                hdiv_b_shift.eq(Mux(hdiv_b_exp != 0, hdiv_b_exp - 1, 0)),
                                hdiv_a_mag.eq(Mux(hdiv_a_exp == 0, hdiv_a_frac,
                                                 Cat(hdiv_a_frac, C(1, 1)) << hdiv_a_shift)),
                                hdiv_b_mag.eq(Mux(hdiv_b_exp == 0, hdiv_b_frac,
                                                 Cat(hdiv_b_frac, C(1, 1)) << hdiv_b_shift)),
                                hdiv_scaled.eq(hdiv_a_mag << 64),
                                hdiv_quotient.eq(hdiv_scaled // Mux(hdiv_b_mag == 0, 1, hdiv_b_mag)),
                                hdiv_div_remainder.eq(hdiv_scaled % Mux(hdiv_b_mag == 0, 1, hdiv_b_mag)),
                                hdiv_sign.eq(hdiv_a[15] ^ hdiv_b[15]),
                                hdiv_msb.eq(0),
                            ]
                            for bit in range(107):
                                with m.If(hdiv_quotient[bit]):
                                    m.d.comb += hdiv_msb.eq(bit)
                            m.d.comb += [
                                hdiv_normal.eq(hdiv_msb >= 50),
                                hdiv_right_shift.eq(Mux(hdiv_msb >= 50, hdiv_msb - 10, 40)),
                                hdiv_half_shift.eq(hdiv_right_shift - 1),
                                hdiv_retained.eq(hdiv_quotient >> hdiv_right_shift),
                                hdiv_remainder.eq(hdiv_quotient & ((C(1, 107) << hdiv_right_shift) - 1)),
                                hdiv_half.eq(C(1, 107) << hdiv_half_shift),
                                hdiv_inexact.eq((hdiv_remainder != 0) | (hdiv_div_remainder != 0)),
                                hdiv_above_half.eq((hdiv_remainder > hdiv_half) |
                                    ((hdiv_remainder == hdiv_half) & (hdiv_div_remainder != 0))),
                                hdiv_exact_half.eq((hdiv_remainder == hdiv_half) &
                                                   (hdiv_div_remainder == 0)),
                                hdiv_rm.eq(Mux(IS.funct3 == 7, csr_frm, IS.funct3)),
                                hdiv_rm_valid.eq(hdiv_rm <= 4),
                                hdiv_increment.eq(Mux(hdiv_rm == 0,
                                    hdiv_above_half | (hdiv_exact_half & hdiv_retained[0]),
                                    Mux(hdiv_rm == 1, 0,
                                        Mux(hdiv_rm == 2, hdiv_sign & hdiv_inexact,
                                            Mux(hdiv_rm == 3, ~hdiv_sign & hdiv_inexact,
                                                hdiv_above_half | hdiv_exact_half))))),
                                hdiv_rounded.eq(hdiv_retained + hdiv_increment),
                                hdiv_exp.eq(Mux(hdiv_normal, hdiv_msb - 49, 0)),
                                hdiv_rounded_exp.eq(hdiv_exp + hdiv_rounded[11]),
                                hdiv_to_inf.eq((hdiv_rm == 0) | (hdiv_rm == 4) |
                                    ((hdiv_rm == 2) & hdiv_sign) | ((hdiv_rm == 3) & ~hdiv_sign)),
                                hdiv_exact_over_max.eq(hdiv_a_mag > (hdiv_b_mag * C(65504, 16))),
                                hdiv_overflow.eq(hdiv_normal & ((hdiv_rounded_exp >= 0x1f) |
                                    (hdiv_exact_over_max & ~hdiv_to_inf))),
                                hdiv_underflow.eq(~hdiv_normal & ~hdiv_rounded[10] & hdiv_inexact),
                                hdiv_invalid.eq(hdiv_a_snan | hdiv_b_snan |
                                    (hdiv_a_zero & hdiv_b_zero) | (hdiv_a_inf & hdiv_b_inf)),
                                hdiv_divzero.eq(~hdiv_a_zero & ~hdiv_a_inf & ~hdiv_a_nan &
                                               hdiv_b_zero & ~hdiv_b_nan),
                                hdiv_finite_result.eq(Mux(hdiv_a_zero | hdiv_b_inf,
                                    Cat(C(0, 15), hdiv_sign),
                                    Mux(hdiv_overflow,
                                        Cat(Mux(hdiv_to_inf, C(0, 10), C(0x3ff, 10)),
                                            Mux(hdiv_to_inf, C(0x1f, 5), C(0x1e, 5)), hdiv_sign),
                                        Mux(hdiv_normal,
                                            Cat(Mux(hdiv_rounded[11], hdiv_rounded[1:11], hdiv_rounded[0:10]),
                                                hdiv_rounded_exp[0:5], hdiv_sign),
                                            Cat(hdiv_rounded[0:10], Cat(hdiv_rounded[10], C(0, 4)), hdiv_sign))))),
                                hdiv_result.eq(Mux(hdiv_a_nan | hdiv_b_nan | hdiv_invalid,
                                    C(0x7e00, 16),
                                    Mux(hdiv_a_inf | hdiv_b_zero,
                                        Cat(C(0, 10), C(0x1f, 5), hdiv_sign), hdiv_finite_result))),
                            ]
                            with m.If(hdiv_rm_valid):
                                m.d.comb += [fp_wb_en.eq(1),
                                    fp_wb_data.eq(Cat(hdiv_result, C(0xffffffffffff, 48)))]
                                with m.If(hdiv_invalid):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                                with m.Elif(hdiv_divzero):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b01000)
                                with m.Elif(hdiv_overflow & ~hdiv_a_inf & ~hdiv_b_inf &
                                            ~hdiv_a_nan & ~hdiv_b_nan):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00101)
                                with m.Elif(hdiv_underflow):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00011)
                                with m.Elif(hdiv_inexact & ~hdiv_a_inf & ~hdiv_b_inf &
                                            ~hdiv_a_nan & ~hdiv_b_nan):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                        with m.Elif(self.enable_zfh & (IS.funct7 == 0b0001010)):  # FMUL.H
                            hmul_a = Signal(16)
                            hmul_b = Signal(16)
                            hmul_a_exp = Signal(5)
                            hmul_b_exp = Signal(5)
                            hmul_a_frac = Signal(10)
                            hmul_b_frac = Signal(10)
                            hmul_a_nan = Signal()
                            hmul_b_nan = Signal()
                            hmul_a_snan = Signal()
                            hmul_b_snan = Signal()
                            hmul_a_inf = Signal()
                            hmul_b_inf = Signal()
                            hmul_a_zero = Signal()
                            hmul_b_zero = Signal()
                            hmul_a_shift = Signal(5)
                            hmul_b_shift = Signal(5)
                            hmul_a_mag = Signal(43)
                            hmul_b_mag = Signal(43)
                            hmul_product = Signal(86)
                            hmul_sign = Signal()
                            hmul_msb = Signal(7)
                            hmul_normal = Signal()
                            hmul_right_shift = Signal(7)
                            hmul_half_shift = Signal(7)
                            hmul_retained = Signal(12)
                            hmul_remainder = Signal(86)
                            hmul_half = Signal(86)
                            hmul_inexact = Signal()
                            hmul_rm = Signal(3)
                            hmul_rm_valid = Signal()
                            hmul_increment = Signal()
                            hmul_rounded = Signal(12)
                            hmul_exp = Signal(6)
                            hmul_rounded_exp = Signal(6)
                            hmul_overflow = Signal()
                            hmul_underflow = Signal()
                            hmul_to_inf = Signal()
                            hmul_invalid = Signal()
                            hmul_finite_result = Signal(16)
                            hmul_result = Signal(16)
                            m.d.comb += [
                                hmul_a.eq(Mux(fp_ex1_a[16:64] == C(0xffffffffffff, 48),
                                             fp_ex1_a[0:16], C(0x7e00, 16))),
                                hmul_b.eq(Mux(fp_ex1_b[16:64] == C(0xffffffffffff, 48),
                                             fp_ex1_b[0:16], C(0x7e00, 16))),
                                hmul_a_exp.eq(hmul_a[10:15]), hmul_b_exp.eq(hmul_b[10:15]),
                                hmul_a_frac.eq(hmul_a[0:10]), hmul_b_frac.eq(hmul_b[0:10]),
                                hmul_a_nan.eq((hmul_a_exp == 0x1f) & (hmul_a_frac != 0)),
                                hmul_b_nan.eq((hmul_b_exp == 0x1f) & (hmul_b_frac != 0)),
                                hmul_a_snan.eq(hmul_a_nan & ~hmul_a_frac[9]),
                                hmul_b_snan.eq(hmul_b_nan & ~hmul_b_frac[9]),
                                hmul_a_inf.eq((hmul_a_exp == 0x1f) & (hmul_a_frac == 0)),
                                hmul_b_inf.eq((hmul_b_exp == 0x1f) & (hmul_b_frac == 0)),
                                hmul_a_zero.eq((hmul_a_exp == 0) & (hmul_a_frac == 0)),
                                hmul_b_zero.eq((hmul_b_exp == 0) & (hmul_b_frac == 0)),
                                hmul_a_shift.eq(Mux(hmul_a_exp != 0, hmul_a_exp - 1, 0)),
                                hmul_b_shift.eq(Mux(hmul_b_exp != 0, hmul_b_exp - 1, 0)),
                                hmul_a_mag.eq(Mux(hmul_a_exp == 0, hmul_a_frac,
                                                 Cat(hmul_a_frac, C(1, 1)) << hmul_a_shift)),
                                hmul_b_mag.eq(Mux(hmul_b_exp == 0, hmul_b_frac,
                                                 Cat(hmul_b_frac, C(1, 1)) << hmul_b_shift)),
                                hmul_product.eq(hmul_a_mag * hmul_b_mag),
                                hmul_sign.eq(hmul_a[15] ^ hmul_b[15]),
                                hmul_msb.eq(0),
                            ]
                            for bit in range(86):
                                with m.If(hmul_product[bit]):
                                    m.d.comb += hmul_msb.eq(bit)
                            m.d.comb += [
                                hmul_normal.eq(hmul_msb >= 34),
                                hmul_right_shift.eq(Mux(hmul_msb >= 34, hmul_msb - 10, 24)),
                                hmul_half_shift.eq(hmul_right_shift - 1),
                                hmul_retained.eq(hmul_product >> hmul_right_shift),
                                hmul_remainder.eq(hmul_product & ((C(1, 86) << hmul_right_shift) - 1)),
                                hmul_half.eq(C(1, 86) << hmul_half_shift),
                                hmul_inexact.eq(hmul_remainder != 0),
                                hmul_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                hmul_rm_valid.eq(hmul_rm <= 0b100),
                                hmul_increment.eq(Mux(
                                    hmul_rm == 0,
                                    (hmul_remainder > hmul_half) |
                                    ((hmul_remainder == hmul_half) & hmul_retained[0]),
                                    Mux(hmul_rm == 1, 0,
                                        Mux(hmul_rm == 2, hmul_sign & hmul_inexact,
                                            Mux(hmul_rm == 3, ~hmul_sign & hmul_inexact,
                                                hmul_inexact & (hmul_remainder >= hmul_half)))),
                                )),
                                hmul_rounded.eq(hmul_retained + hmul_increment),
                                hmul_exp.eq(Mux(hmul_normal, hmul_msb - 33, 0)),
                                hmul_rounded_exp.eq(hmul_exp + hmul_rounded[11]),
                                hmul_to_inf.eq((hmul_rm == 0) | (hmul_rm == 4) |
                                    ((hmul_rm == 2) & hmul_sign) | ((hmul_rm == 3) & ~hmul_sign)),
                                hmul_overflow.eq(hmul_normal & (hmul_rounded_exp >= 0x1f)),
                                hmul_underflow.eq(~hmul_normal & ~hmul_rounded[10] & hmul_inexact),
                                hmul_invalid.eq(hmul_a_snan | hmul_b_snan |
                                    (hmul_a_inf & hmul_b_zero) | (hmul_b_inf & hmul_a_zero)),
                                hmul_finite_result.eq(Mux(
                                    hmul_a_zero | hmul_b_zero,
                                    Cat(C(0, 15), hmul_sign),
                                    Mux(hmul_overflow,
                                        Cat(Mux(hmul_to_inf, C(0, 10), C(0x3ff, 10)),
                                            Mux(hmul_to_inf, C(0x1f, 5), C(0x1e, 5)), hmul_sign),
                                        Mux(hmul_normal,
                                            Cat(Mux(hmul_rounded[11], hmul_rounded[1:11], hmul_rounded[0:10]),
                                                hmul_rounded_exp[0:5], hmul_sign),
                                            Cat(hmul_rounded[0:10], Cat(hmul_rounded[10], C(0, 4)), hmul_sign))),
                                )),
                                hmul_result.eq(Mux(hmul_a_nan | hmul_b_nan | hmul_invalid,
                                    C(0x7e00, 16),
                                    Mux(hmul_a_inf | hmul_b_inf,
                                        Cat(C(0, 10), C(0x1f, 5), hmul_sign), hmul_finite_result))),
                            ]
                            with m.If(hmul_rm_valid):
                                m.d.comb += [fp_wb_en.eq(1),
                                    fp_wb_data.eq(Cat(hmul_result, C(0xffffffffffff, 48)))]
                                with m.If(hmul_invalid):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                                with m.Elif(hmul_overflow & ~hmul_a_nan & ~hmul_b_nan):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00101)
                                with m.Elif(hmul_underflow):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00011)
                                with m.Elif(hmul_inexact & ~hmul_a_nan & ~hmul_b_nan &
                                            ~hmul_a_inf & ~hmul_b_inf):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                        with m.Elif(self.enable_zfh & (
                            (IS.funct7 == 0b0000010) | (IS.funct7 == 0b0000110)
                        )):  # FADD.H / FSUB.H
                            hadd_a = Signal(16)
                            hadd_b = Signal(16)
                            hadd_a_exp = Signal(5)
                            hadd_b_exp = Signal(5)
                            hadd_a_frac = Signal(10)
                            hadd_b_frac = Signal(10)
                            hadd_a_nan = Signal()
                            hadd_b_nan = Signal()
                            hadd_a_snan = Signal()
                            hadd_b_snan = Signal()
                            hadd_a_inf = Signal()
                            hadd_b_inf = Signal()
                            hadd_a_shift = Signal(5)
                            hadd_b_shift = Signal(5)
                            hadd_a_mag = Signal(43)
                            hadd_b_mag = Signal(43)
                            hadd_b_sign = Signal()
                            hadd_same_sign = Signal()
                            hadd_sum_sign = Signal()
                            hadd_sum_mag = Signal(43)
                            hadd_zero = Signal()
                            hadd_msb = Signal(6)
                            hadd_normal = Signal()
                            hadd_right_shift = Signal(6)
                            hadd_half_shift = Signal(6)
                            hadd_retained = Signal(12)
                            hadd_remainder = Signal(43)
                            hadd_half = Signal(43)
                            hadd_inexact = Signal()
                            hadd_rm = Signal(3)
                            hadd_rm_valid = Signal()
                            hadd_increment = Signal()
                            hadd_rounded = Signal(12)
                            hadd_exp = Signal(6)
                            hadd_rounded_exp = Signal(6)
                            hadd_overflow = Signal()
                            hadd_to_inf = Signal()
                            hadd_invalid = Signal()
                            hadd_zero_sign = Signal()
                            hadd_finite_result = Signal(16)
                            hadd_result = Signal(16)
                            m.d.comb += [
                                hadd_a.eq(Mux(fp_ex1_a[16:64] == C(0xffffffffffff, 48),
                                              fp_ex1_a[0:16], C(0x7e00, 16))),
                                hadd_b.eq(Mux(fp_ex1_b[16:64] == C(0xffffffffffff, 48),
                                              fp_ex1_b[0:16], C(0x7e00, 16))),
                                hadd_a_exp.eq(hadd_a[10:15]),
                                hadd_b_exp.eq(hadd_b[10:15]),
                                hadd_a_frac.eq(hadd_a[0:10]),
                                hadd_b_frac.eq(hadd_b[0:10]),
                                hadd_a_nan.eq((hadd_a_exp == 0x1f) & (hadd_a_frac != 0)),
                                hadd_b_nan.eq((hadd_b_exp == 0x1f) & (hadd_b_frac != 0)),
                                hadd_a_snan.eq(hadd_a_nan & ~hadd_a_frac[9]),
                                hadd_b_snan.eq(hadd_b_nan & ~hadd_b_frac[9]),
                                hadd_a_inf.eq((hadd_a_exp == 0x1f) & (hadd_a_frac == 0)),
                                hadd_b_inf.eq((hadd_b_exp == 0x1f) & (hadd_b_frac == 0)),
                                hadd_a_shift.eq(Mux(hadd_a_exp != 0, hadd_a_exp - 1, 0)),
                                hadd_b_shift.eq(Mux(hadd_b_exp != 0, hadd_b_exp - 1, 0)),
                                hadd_a_mag.eq(Mux(hadd_a_exp == 0, hadd_a_frac,
                                                 Cat(hadd_a_frac, C(1, 1)) << hadd_a_shift)),
                                hadd_b_mag.eq(Mux(hadd_b_exp == 0, hadd_b_frac,
                                                 Cat(hadd_b_frac, C(1, 1)) << hadd_b_shift)),
                                hadd_b_sign.eq(hadd_b[15] ^ (IS.funct7 == 0b0000110)),
                                hadd_same_sign.eq(hadd_a[15] == hadd_b_sign),
                                hadd_sum_sign.eq(Mux(
                                    hadd_same_sign,
                                    hadd_a[15],
                                    Mux(hadd_a_mag >= hadd_b_mag, hadd_a[15], hadd_b_sign),
                                )),
                                hadd_sum_mag.eq(Mux(
                                    hadd_same_sign,
                                    hadd_a_mag + hadd_b_mag,
                                    Mux(hadd_a_mag >= hadd_b_mag,
                                        hadd_a_mag - hadd_b_mag, hadd_b_mag - hadd_a_mag),
                                )),
                                hadd_zero.eq(hadd_sum_mag == 0),
                                hadd_msb.eq(0),
                            ]
                            for bit in range(43):
                                with m.If(hadd_sum_mag[bit]):
                                    m.d.comb += hadd_msb.eq(bit)
                            m.d.comb += [
                                hadd_normal.eq(hadd_msb >= 10),
                                hadd_right_shift.eq(Mux(hadd_msb > 10, hadd_msb - 10, 0)),
                                hadd_half_shift.eq(Mux(hadd_right_shift != 0, hadd_right_shift - 1, 0)),
                                hadd_retained.eq(Mux(hadd_right_shift != 0,
                                                    hadd_sum_mag >> hadd_right_shift, hadd_sum_mag)),
                                hadd_remainder.eq(Mux(
                                    hadd_right_shift != 0,
                                    hadd_sum_mag & ((C(1, 43) << hadd_right_shift) - 1), 0,
                                )),
                                hadd_half.eq(Mux(hadd_right_shift != 0,
                                                C(1, 43) << hadd_half_shift, 0)),
                                hadd_inexact.eq(hadd_remainder != 0),
                                hadd_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                hadd_rm_valid.eq(hadd_rm <= 0b100),
                                hadd_increment.eq(Mux(
                                    hadd_rm == 0b000,
                                    (hadd_remainder > hadd_half) |
                                    ((hadd_remainder == hadd_half) & hadd_retained[0]),
                                    Mux(hadd_rm == 0b001, 0,
                                        Mux(hadd_rm == 0b010, hadd_sum_sign & hadd_inexact,
                                            Mux(hadd_rm == 0b011, ~hadd_sum_sign & hadd_inexact,
                                                hadd_inexact & (hadd_remainder >= hadd_half)))),
                                )),
                                hadd_rounded.eq(hadd_retained + hadd_increment),
                                hadd_exp.eq(Mux(hadd_normal, hadd_msb - 9, 0)),
                                hadd_rounded_exp.eq(hadd_exp + hadd_rounded[11]),
                                hadd_to_inf.eq(
                                    (hadd_rm == 0b000) | (hadd_rm == 0b100) |
                                    ((hadd_rm == 0b010) & hadd_sum_sign) |
                                    ((hadd_rm == 0b011) & ~hadd_sum_sign)
                                ),
                                hadd_overflow.eq(hadd_rounded_exp >= 0x1f),
                                hadd_invalid.eq((hadd_a_snan | hadd_b_snan) |
                                    (hadd_a_inf & hadd_b_inf & (hadd_a[15] != hadd_b_sign))),
                                hadd_zero_sign.eq(Mux(
                                    hadd_same_sign & (hadd_a_mag == 0) & (hadd_b_mag == 0),
                                    hadd_a[15],
                                    hadd_rm == 0b010,
                                )),
                                hadd_finite_result.eq(Mux(
                                    hadd_zero,
                                    Cat(C(0, 15), hadd_zero_sign),
                                    Mux(
                                        hadd_overflow,
                                        Cat(Mux(hadd_to_inf, C(0, 10), C(0x3ff, 10)),
                                            Mux(hadd_to_inf, C(0x1f, 5), C(0x1e, 5)), hadd_sum_sign),
                                        Mux(
                                            hadd_normal,
                                            Cat(Mux(hadd_rounded[11], hadd_rounded[1:11], hadd_rounded[0:10]),
                                                hadd_rounded_exp[0:5], hadd_sum_sign),
                                            Cat(hadd_sum_mag[0:10], C(0, 5), hadd_sum_sign),
                                        ),
                                    ),
                                )),
                                hadd_result.eq(Mux(
                                    hadd_a_nan | hadd_b_nan | hadd_invalid,
                                    C(0x7e00, 16),
                                    Mux(hadd_a_inf, Cat(C(0, 10), C(0x1f, 5), hadd_a[15]),
                                        Mux(hadd_b_inf, Cat(C(0, 10), C(0x1f, 5), hadd_b_sign),
                                            hadd_finite_result)),
                                )),
                            ]
                            with m.If(hadd_rm_valid):
                                m.d.comb += [fp_wb_en.eq(1),
                                    fp_wb_data.eq(Cat(hadd_result, C(0xffffffffffff, 48)))]
                                with m.If(hadd_invalid):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                                with m.Elif(hadd_overflow & ~hadd_a_inf & ~hadd_b_inf &
                                            ~hadd_a_nan & ~hadd_b_nan):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00101)
                                with m.Elif(hadd_inexact & ~hadd_a_inf & ~hadd_b_inf &
                                            ~hadd_a_nan & ~hadd_b_nan):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                        with m.Elif(self.enable_zfh & (IS.funct7 == 0b1101010) & (IS.rs2 <= 1)):  # FCVT.H.W / FCVT.H.WU
                            i2h_sign = Signal()
                            i2h_mag = Signal(32)
                            i2h_zero = Signal()
                            i2h_msb = Signal(6)
                            i2h_right_shift = Signal(6)
                            i2h_left_shift = Signal(6)
                            i2h_half_shift = Signal(6)
                            i2h_retained = Signal(12)
                            i2h_remainder = Signal(32)
                            i2h_half = Signal(32)
                            i2h_inexact = Signal()
                            i2h_rm = Signal(3)
                            i2h_rm_valid = Signal()
                            i2h_increment = Signal()
                            i2h_rounded = Signal(12)
                            i2h_biased_exp = Signal(6)
                            i2h_rounded_exp = Signal(6)
                            i2h_overflow = Signal()
                            i2h_to_inf = Signal()
                            i2h_result = Signal(16)
                            m.d.comb += [
                                i2h_sign.eq((IS.rs2 == 0) & ex1_a[31]),
                                i2h_mag.eq(Mux((IS.rs2 == 0) & ex1_a[31], -ex1_a[0:32], ex1_a[0:32])),
                                i2h_zero.eq(i2h_mag == 0),
                                i2h_msb.eq(0),
                            ]
                            for bit in range(32):
                                with m.If(i2h_mag[bit]):
                                    m.d.comb += i2h_msb.eq(bit)
                            m.d.comb += [
                                i2h_right_shift.eq(Mux(i2h_msb > 10, i2h_msb - 10, 0)),
                                i2h_left_shift.eq(Mux(i2h_msb <= 10, 10 - i2h_msb, 0)),
                                i2h_half_shift.eq(Mux(i2h_right_shift != 0, i2h_right_shift - 1, 0)),
                                i2h_retained.eq(Mux(
                                    i2h_right_shift != 0,
                                    i2h_mag >> i2h_right_shift,
                                    i2h_mag << i2h_left_shift,
                                )),
                                i2h_remainder.eq(Mux(
                                    i2h_right_shift != 0,
                                    i2h_mag & ((C(1, 32) << i2h_right_shift) - 1),
                                    0,
                                )),
                                i2h_half.eq(Mux(
                                    i2h_right_shift != 0,
                                    C(1, 32) << i2h_half_shift,
                                    0,
                                )),
                                i2h_inexact.eq(i2h_remainder != 0),
                                i2h_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                i2h_rm_valid.eq(i2h_rm <= 0b100),
                                i2h_increment.eq(Mux(
                                    i2h_rm == 0b000,
                                    (i2h_remainder > i2h_half) |
                                    ((i2h_remainder == i2h_half) & i2h_retained[0]),
                                    Mux(
                                        i2h_rm == 0b001,
                                        0,
                                        Mux(
                                            i2h_rm == 0b010,
                                            i2h_sign & i2h_inexact,
                                            Mux(
                                                i2h_rm == 0b011,
                                                ~i2h_sign & i2h_inexact,
                                                i2h_inexact & (i2h_remainder >= i2h_half),
                                            ),
                                        ),
                                    ),
                                )),
                                i2h_rounded.eq(i2h_retained + i2h_increment),
                                i2h_biased_exp.eq(15 + i2h_msb),
                                i2h_rounded_exp.eq(i2h_biased_exp + i2h_rounded[11]),
                                i2h_to_inf.eq(
                                    (i2h_rm == 0b000) | (i2h_rm == 0b100) |
                                    ((i2h_rm == 0b010) & i2h_sign) |
                                    ((i2h_rm == 0b011) & ~i2h_sign)
                                ),
                                i2h_overflow.eq(~i2h_zero & (
                                    (i2h_rounded_exp >= 0x1f) |
                                    ((i2h_mag > C(65504, 32)) & ~i2h_to_inf)
                                )),
                                i2h_result.eq(Mux(
                                    i2h_zero,
                                    0,
                                    Mux(
                                        i2h_overflow,
                                        Cat(Mux(i2h_to_inf, C(0, 10), C(0x3ff, 10)),
                                            Mux(i2h_to_inf, C(0x1f, 5), C(0x1e, 5)), i2h_sign),
                                        Cat(
                                            Mux(i2h_rounded[11], i2h_rounded[1:11], i2h_rounded[0:10]),
                                            i2h_rounded_exp[0:5],
                                            i2h_sign,
                                        ),
                                    ),
                                )),
                            ]
                            with m.If(i2h_rm_valid):
                                m.d.comb += [
                                    fp_wb_en.eq(1),
                                    fp_wb_data.eq(Cat(i2h_result, C(0xffffffffffff, 48))),
                                ]
                                with m.If(i2h_overflow):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00101)
                                with m.Elif(i2h_inexact):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                        with m.Elif(self.enable_zfh & (IS.funct7 == 0b1100010) & (IS.rs2 <= 1)):  # FCVT.W.H / FCVT.WU.H
                            h2i_value = Signal(16)
                            h2i_exp = Signal(5)
                            h2i_frac = Signal(10)
                            h2i_sign = Signal()
                            h2i_nan = Signal()
                            h2i_inf = Signal()
                            h2i_sig = Signal(11)
                            h2i_shift = Signal(6)
                            h2i_left_shift = Signal(6)
                            h2i_half_shift = Signal(6)
                            h2i_trunc = Signal(64)
                            h2i_remainder = Signal(64)
                            h2i_half = Signal(64)
                            h2i_inexact = Signal()
                            h2i_rm = Signal(3)
                            h2i_rm_valid = Signal()
                            h2i_increment = Signal()
                            h2i_rounded = Signal(64)
                            h2i_signed_overflow = Signal()
                            h2i_unsigned_overflow = Signal()
                            h2i_invalid = Signal()
                            h2i_result = Signal(32)
                            m.d.comb += [
                                h2i_value.eq(Mux(
                                    fp_ex1_a[16:64] == C(0xffffffffffff, 48),
                                    fp_ex1_a[0:16],
                                    C(0x7e00, 16),
                                )),
                                h2i_exp.eq(h2i_value[10:15]),
                                h2i_frac.eq(h2i_value[0:10]),
                                h2i_sign.eq(h2i_value[15]),
                                h2i_nan.eq((h2i_exp == 0x1f) & (h2i_frac != 0)),
                                h2i_inf.eq((h2i_exp == 0x1f) & (h2i_frac == 0)),
                                h2i_sig.eq(Mux(h2i_exp == 0, h2i_frac, Cat(h2i_frac, C(1, 1)))),
                                h2i_shift.eq(Mux(h2i_exp == 0, 24, Mux(h2i_exp < 25, 25 - h2i_exp, 0))),
                                h2i_left_shift.eq(Mux(h2i_exp >= 25, h2i_exp - 25, 0)),
                                h2i_half_shift.eq(Mux(h2i_shift != 0, h2i_shift - 1, 0)),
                                h2i_trunc.eq(Mux(
                                    h2i_shift != 0,
                                    h2i_sig >> h2i_shift,
                                    h2i_sig << h2i_left_shift,
                                )),
                                h2i_remainder.eq(Mux(
                                    h2i_shift != 0,
                                    h2i_sig & ((C(1, 64) << h2i_shift) - 1),
                                    0,
                                )),
                                h2i_half.eq(Mux(h2i_shift != 0, C(1, 64) << h2i_half_shift, 0)),
                                h2i_inexact.eq(h2i_remainder != 0),
                                h2i_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                h2i_rm_valid.eq(h2i_rm <= 0b100),
                                h2i_increment.eq(Mux(
                                    h2i_rm == 0b000,
                                    (h2i_remainder > h2i_half) |
                                    ((h2i_remainder == h2i_half) & h2i_trunc[0]),
                                    Mux(
                                        h2i_rm == 0b001,
                                        0,
                                        Mux(
                                            h2i_rm == 0b010,
                                            h2i_sign & h2i_inexact,
                                            Mux(
                                                h2i_rm == 0b011,
                                                ~h2i_sign & h2i_inexact,
                                                h2i_inexact & (h2i_remainder >= h2i_half),
                                            ),
                                        ),
                                    ),
                                )),
                                h2i_rounded.eq(h2i_trunc + h2i_increment),
                                h2i_signed_overflow.eq(Mux(
                                    h2i_sign,
                                    h2i_rounded > C(0x80000000, 64),
                                    h2i_rounded > C(0x7fffffff, 64),
                                )),
                                h2i_unsigned_overflow.eq(Mux(
                                    h2i_sign,
                                    h2i_rounded != 0,
                                    h2i_rounded > C(0xffffffff, 64),
                                )),
                                h2i_invalid.eq(h2i_nan | h2i_inf | Mux(
                                    IS.rs2 == 0,
                                    h2i_signed_overflow,
                                    h2i_unsigned_overflow,
                                )),
                                h2i_result.eq(Mux(
                                    h2i_invalid,
                                    Mux(
                                        IS.rs2 == 0,
                                        Mux(h2i_sign & ~h2i_nan, 0x80000000, 0x7fffffff),
                                        Mux(h2i_sign & ~h2i_nan, 0, 0xffffffff),
                                    ),
                                    Mux(
                                        h2i_sign,
                                        -h2i_rounded[0:32],
                                        h2i_rounded[0:32],
                                    ),
                                )),
                            ]
                            with m.If(h2i_rm_valid):
                                m.d.comb += [wb_en.eq(1), wb_data.eq(h2i_result)]
                                with m.If(h2i_invalid):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                                with m.Elif(h2i_inexact):
                                    m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                        with m.Elif(self.enable_zfh & (IS.funct7 == 0b1010010) &
                                    ((IS.funct3 <= 0b010) |
                                     (self.enable_zfa &
                                      ((IS.funct3 == 0b100) |
                                       (IS.funct3 == 0b101))))):  # FLE/FLT/FEQ/FLEQ/FLTQ.H
                            hcmp_a = Signal(16)
                            hcmp_b = Signal(16)
                            hcmp_a_nan = Signal()
                            hcmp_b_nan = Signal()
                            hcmp_a_snan = Signal()
                            hcmp_b_snan = Signal()
                            hcmp_a_zero = Signal()
                            hcmp_b_zero = Signal()
                            hcmp_eq = Signal()
                            hcmp_lt = Signal()
                            hcmp_result = Signal()
                            m.d.comb += [
                                hcmp_a.eq(Mux(
                                    fp_ex1_a[16:64] == C(0xffffffffffff, 48),
                                    fp_ex1_a[0:16],
                                    C(0x7e00, 16),
                                )),
                                hcmp_b.eq(Mux(
                                    fp_ex1_b[16:64] == C(0xffffffffffff, 48),
                                    fp_ex1_b[0:16],
                                    C(0x7e00, 16),
                                )),
                                hcmp_a_nan.eq((hcmp_a[10:15] == 0x1f) & (hcmp_a[0:10] != 0)),
                                hcmp_b_nan.eq((hcmp_b[10:15] == 0x1f) & (hcmp_b[0:10] != 0)),
                                hcmp_a_snan.eq(hcmp_a_nan & ~hcmp_a[9]),
                                hcmp_b_snan.eq(hcmp_b_nan & ~hcmp_b[9]),
                                hcmp_a_zero.eq(hcmp_a[0:15] == 0),
                                hcmp_b_zero.eq(hcmp_b[0:15] == 0),
                                hcmp_eq.eq((hcmp_a == hcmp_b) | (hcmp_a_zero & hcmp_b_zero)),
                                hcmp_lt.eq(~hcmp_eq & Mux(
                                    hcmp_a[15] != hcmp_b[15],
                                    hcmp_a[15],
                                    Mux(
                                        hcmp_a[15],
                                        hcmp_a[0:15] > hcmp_b[0:15],
                                        hcmp_a[0:15] < hcmp_b[0:15],
                                    ),
                                )),
                                hcmp_result.eq(Mux(
                                    hcmp_a_nan | hcmp_b_nan,
                                    0,
                                    Mux(
                                        IS.funct3 == 0b010,
                                        hcmp_eq,
                                        Mux((IS.funct3 == 0b001) |
                                            (IS.funct3 == 0b101),
                                            hcmp_lt, hcmp_lt | hcmp_eq),
                                    ),
                                )),
                                wb_en.eq(1),
                                wb_data.eq(hcmp_result),
                            ]
                            with m.If(Mux(
                                (IS.funct3 == 0b010) | IS.funct3[2],
                                hcmp_a_snan | hcmp_b_snan,
                                hcmp_a_nan | hcmp_b_nan,
                            )):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                        with m.Elif(self.enable_zfh & (IS.funct7 == 0b1110010) & (IS.funct3 == 0b001) & (IS.rs2 == 0)):  # FCLASS.H
                            hclass_value = Signal(16)
                            hclass_exp = Signal(5)
                            hclass_frac = Signal(10)
                            hclass = Signal(self.xlen)
                            m.d.comb += [
                                hclass_value.eq(Mux(
                                    fp_ex1_a[16:64] == C(0xffffffffffff, 48),
                                    fp_ex1_a[0:16],
                                    C(0x7e00, 16),
                                )),
                                hclass_exp.eq(hclass_value[10:15]),
                                hclass_frac.eq(hclass_value[0:10]),
                                hclass.eq(0),
                            ]
                            with m.If((hclass_exp == 0x1f) & (hclass_frac == 0)):
                                m.d.comb += hclass.eq(Mux(hclass_value[15], 1 << 0, 1 << 7))
                            with m.Elif((hclass_exp == 0x1f) & (hclass_frac != 0)):
                                m.d.comb += hclass.eq(Mux(hclass_frac[9], 1 << 9, 1 << 8))
                            with m.Elif((hclass_exp == 0) & (hclass_frac == 0)):
                                m.d.comb += hclass.eq(Mux(hclass_value[15], 1 << 3, 1 << 4))
                            with m.Elif((hclass_exp == 0) & (hclass_frac != 0)):
                                m.d.comb += hclass.eq(Mux(hclass_value[15], 1 << 2, 1 << 5))
                            with m.Else():
                                m.d.comb += hclass.eq(Mux(hclass_value[15], 1 << 1, 1 << 6))
                            m.d.comb += [wb_en.eq(1), wb_data.eq(hclass)]
                        with m.Elif(IS.funct7 == 0b0010000):  # FSGNJ.S / FSGNJN.S / FSGNJX.S
                            fsgnj_sign = Signal()
                            fsgnj_word = Signal(32)
                            m.d.comb += [
                                fsgnj_sign.eq(Mux(
                                    IS.funct3 == 0b000,
                                    fp_ex1_b[31],
                                    Mux(
                                        IS.funct3 == 0b001,
                                        ~fp_ex1_b[31],
                                        fp_ex1_a[31] ^ fp_ex1_b[31],
                                    ),
                                )),
                                fsgnj_word.eq(Cat(fp_ex1_a[0:31], fsgnj_sign)),
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(Cat(fsgnj_word, C(0xFFFFFFFF, 32))),
                            ]
                        with m.Elif(self.enable_f & (IS.funct7 == 0b1110000) & (IS.funct3 == 0b000) & (IS.rs2 == 0)):  # FMV.X.W
                            m.d.comb += [wb_en.eq(1), wb_data.eq(sign_extend(fp_ex1_a[0:32], 32, self.xlen))]
                        with m.Elif(self.enable_f & (IS.funct7 == 0b1111000) & (IS.funct3 == 0b000) & (IS.rs2 == 0)):  # FMV.W.X
                            m.d.comb += [
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(Cat(ex1_a[0:32], C(0xFFFFFFFF, 32))),
                            ]
                        with m.Elif(self.use_zfinx & (IS.funct3 == 0b000) & (IS.rs2 == 0) &
                                    ((IS.funct7 == 0b1110000) |
                                     (IS.funct7 == 0b1111000))):
                            pass
                        with m.Elif(self.enable_zfhmin & ~self.use_finx & (IS.funct7 == 0b1110010) &
                                    (IS.funct3 == 0b000) & (IS.rs2 == 0)):  # FMV.X.H
                            m.d.comb += [
                                wb_en.eq(1),
                                wb_data.eq(sign_extend(fp_ex1_a[0:16], 16, self.xlen)),
                            ]
                        with m.Elif(self.enable_zfhmin & ~self.use_finx & (IS.funct7 == 0b1111010) &
                                    (IS.funct3 == 0b000) & (IS.rs2 == 0)):  # FMV.H.X
                            m.d.comb += [
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(Cat(ex1_a[0:16], C(0xFFFFFFFFFFFF, 48))),
                            ]
                        with m.Elif(self.enable_zfa & self.enable_zfh &
                                    (IS.funct7 == 0b1111010) &
                                    (IS.funct3 == 0b000) & (IS.rs2 == 1)):  # FLI.H
                            m.d.comb += [
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(Cat(zfa_fli_h[IS.rs1],
                                                    C(0xFFFFFFFFFFFF, 48))),
                            ]
                        with m.Elif(self.enable_zfa & (IS.funct7 == 0b1111000) & (IS.funct3 == 0b000) & (IS.rs2 == 1)):  # FLI.S
                            m.d.comb += [
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(Cat(zfa_fli_s[IS.rs1], C(0xFFFFFFFF, 32))),
                            ]
                        with m.Elif((IS.funct7 == 0b1100000) & ((IS.rs2 == 0) | (IS.rs2 == 1))):  # FCVT.W.S / FCVT.WU.S
                            fcvt_exp = Signal(8)
                            fcvt_frac = Signal(23)
                            fcvt_nan = Signal()
                            fcvt_sign = Signal()
                            fcvt_unsigned = Signal()
                            fcvt_invalid = Signal()
                            fcvt_unbiased = Signal(9)
                            fcvt_mant = Signal(24)
                            fcvt_mag = Signal(33)
                            fcvt_rounded_mag = Signal(33)
                            fcvt_shamt = Signal(5)
                            fcvt_mask = Signal(24)
                            fcvt_guard = Signal()
                            fcvt_lower = Signal()
                            fcvt_inexact = Signal()
                            fcvt_increment = Signal()
                            fcvt_rm = Signal(3)
                            fcvt_result32 = Signal(32)
                            m.d.comb += [
                                fcvt_exp.eq(fp_ex1_a[23:31]),
                                fcvt_frac.eq(fp_ex1_a[0:23]),
                                fcvt_sign.eq(fp_ex1_a[31]),
                                fcvt_unsigned.eq(IS.rs2 == 1),
                                fcvt_nan.eq((fcvt_exp == 0xff) & (fcvt_frac != 0)),
                                fcvt_unbiased.eq(fcvt_exp - 127),
                                fcvt_mant.eq(Cat(fcvt_frac, Mux(fcvt_exp == 0, 0, 1))),
                                fcvt_mag.eq(0),
                                fcvt_shamt.eq(0),
                                fcvt_mask.eq(0),
                                fcvt_guard.eq(0),
                                fcvt_lower.eq(0),
                                fcvt_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                fcvt_inexact.eq(fcvt_guard | fcvt_lower),
                                fcvt_increment.eq(
                                    Mux(fcvt_rm == 0b000, fcvt_guard & (fcvt_lower | fcvt_mag[0]),
                                    Mux(fcvt_rm == 0b001, 0,
                                    Mux(fcvt_rm == 0b010, fcvt_sign & fcvt_inexact,
                                    Mux(fcvt_rm == 0b011, ~fcvt_sign & fcvt_inexact,
                                    Mux(fcvt_rm == 0b100, fcvt_guard, 0)))))
                                ),
                                fcvt_rounded_mag.eq(fcvt_mag + fcvt_increment),
                                fcvt_invalid.eq(
                                    (fcvt_exp == 0xff) |
                                    (fcvt_exp >= 159) |
                                    (fcvt_unsigned & fcvt_sign & ((fcvt_exp != 0) | (fcvt_frac != 0))) |
                                    (fcvt_unsigned & (fcvt_rounded_mag > 0xffffffff)) |
                                    (~fcvt_unsigned & ~fcvt_sign & (fcvt_rounded_mag > 0x7fffffff)) |
                                    (~fcvt_unsigned & fcvt_sign & (fcvt_rounded_mag > 0x80000000))
                                ),
                                fcvt_result32.eq(0),
                            ]
                            with m.If(fcvt_exp < 126):
                                m.d.comb += fcvt_lower.eq((fcvt_exp != 0) | (fcvt_frac != 0))
                            with m.Elif(fcvt_exp == 126):
                                m.d.comb += [fcvt_guard.eq(fcvt_mant[23]), fcvt_lower.eq(fcvt_frac != 0)]
                            with m.Elif(fcvt_unbiased < 23):
                                m.d.comb += [
                                    fcvt_shamt.eq(23 - fcvt_unbiased),
                                    fcvt_mag.eq(fcvt_mant >> fcvt_shamt),
                                    fcvt_mask.eq((C(1, 24) << fcvt_shamt) - 1),
                                    fcvt_guard.eq((fcvt_mant >> (fcvt_shamt - 1).as_unsigned())[0]),
                                    fcvt_lower.eq((fcvt_mant & (fcvt_mask >> 1)) != 0),
                                ]
                            with m.Elif(fcvt_unbiased < 32):
                                m.d.comb += [
                                    fcvt_shamt.eq(fcvt_unbiased - 23),
                                    fcvt_mag.eq(fcvt_mant << fcvt_shamt),
                                ]
                            with m.If(fcvt_invalid):
                                with m.If(fcvt_unsigned):
                                    m.d.comb += fcvt_result32.eq(Mux(fcvt_sign & ~fcvt_nan, 0, 0xffffffff))
                                with m.Else():
                                    m.d.comb += fcvt_result32.eq(Mux(fcvt_sign & ~fcvt_nan, 0x80000000, 0x7fffffff))
                            with m.Else():
                                m.d.comb += fcvt_result32.eq(Mux(fcvt_sign, -fcvt_rounded_mag, fcvt_rounded_mag))
                            with m.If(fcvt_invalid):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                            with m.Elif(fcvt_inexact):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                            m.d.comb += [wb_en.eq(1), wb_data.eq(sign_extend(fcvt_result32, 32, self.xlen))]
                        with m.Elif((IS.funct7 == 0b1101000) & ((IS.rs2 == 0) | (IS.rs2 == 1))):  # FCVT.S.W / FCVT.S.WU
                            fcvt_i_sign = Signal()
                            fcvt_i_mag = Signal(32)
                            fcvt_i_top = Signal(5)
                            fcvt_i_shift = Signal(5)
                            fcvt_i_lshift = Signal(5)
                            fcvt_i_mask = Signal(32)
                            fcvt_i_mant = Signal(24)
                            fcvt_i_guard = Signal()
                            fcvt_i_lower = Signal()
                            fcvt_i_inexact = Signal()
                            fcvt_i_increment = Signal()
                            fcvt_i_rounded = Signal(25)
                            fcvt_i_rm = Signal(3)
                            fcvt_i_exp = Signal(9)
                            fcvt_i_result = Signal(32)
                            m.d.comb += [
                                fcvt_i_sign.eq((IS.rs2 == 0) & ex1_a[31]),
                                fcvt_i_mag.eq(Mux((IS.rs2 == 0) & ex1_a[31], -ex1_a[0:32], ex1_a[0:32])),
                                fcvt_i_top.eq(0),
                                fcvt_i_shift.eq(Mux(fcvt_i_top > 23, fcvt_i_top - 23, 0)),
                                fcvt_i_lshift.eq(Mux(fcvt_i_top > 23, 0, 23 - fcvt_i_top)),
                                fcvt_i_mask.eq(Mux(fcvt_i_shift == 0, 0, (C(1, 32) << fcvt_i_shift) - 1)),
                                fcvt_i_mant.eq(Mux(fcvt_i_top > 23,
                                                   fcvt_i_mag >> fcvt_i_shift,
                                                   fcvt_i_mag << fcvt_i_lshift)),
                                fcvt_i_guard.eq(Mux(fcvt_i_shift == 0, 0,
                                                    (fcvt_i_mag >> (fcvt_i_shift - 1).as_unsigned())[0])),
                                fcvt_i_lower.eq(Mux(fcvt_i_shift <= 1, 0,
                                                    (fcvt_i_mag & (fcvt_i_mask >> 1)) != 0)),
                                fcvt_i_inexact.eq(fcvt_i_guard | fcvt_i_lower),
                                fcvt_i_rm.eq(Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)),
                                fcvt_i_increment.eq(
                                    Mux(fcvt_i_rm == 0b000,
                                        fcvt_i_guard & (fcvt_i_lower | fcvt_i_mant[0]),
                                    Mux(fcvt_i_rm == 0b001, 0,
                                    Mux(fcvt_i_rm == 0b010, fcvt_i_sign & fcvt_i_inexact,
                                    Mux(fcvt_i_rm == 0b011, ~fcvt_i_sign & fcvt_i_inexact,
                                    Mux(fcvt_i_rm == 0b100, fcvt_i_guard, 0)))))
                                ),
                                fcvt_i_rounded.eq(fcvt_i_mant + fcvt_i_increment),
                                fcvt_i_exp.eq(127 + fcvt_i_top + fcvt_i_rounded[24]),
                                fcvt_i_result.eq(0),
                            ]
                            for bit in range(32):
                                with m.If(fcvt_i_mag[bit]):
                                    m.d.comb += fcvt_i_top.eq(bit)
                            with m.If(fcvt_i_mag != 0):
                                m.d.comb += fcvt_i_result.eq(Cat(
                                    Mux(fcvt_i_rounded[24], fcvt_i_rounded[1:24], fcvt_i_rounded[0:23]),
                                    fcvt_i_exp[0:8], fcvt_i_sign))
                            with m.If(fcvt_i_inexact):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                            m.d.comb += [
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(Cat(fcvt_i_result, C(0xFFFFFFFF, 32))),
                            ]
                        with m.Elif((IS.funct7 == 0b1110000) & (IS.funct3 == 0b001) & (IS.rs2 == 0)):  # FCLASS.S
                            f_exp = Signal(8)
                            f_frac = Signal(23)
                            f_class = Signal(self.xlen)
                            m.d.comb += [
                                f_exp.eq(fp_ex1_a[23:31]),
                                f_frac.eq(fp_ex1_a[0:23]),
                                f_class.eq(0),
                            ]
                            with m.If((f_exp == 0xff) & (f_frac == 0)):
                                m.d.comb += f_class.eq(Mux(fp_ex1_a[31], 1 << 0, 1 << 7))
                            with m.Elif((f_exp == 0xff) & (f_frac != 0)):
                                m.d.comb += f_class.eq(Mux(f_frac[22], 1 << 9, 1 << 8))
                            with m.Elif((f_exp == 0) & (f_frac == 0)):
                                m.d.comb += f_class.eq(Mux(fp_ex1_a[31], 1 << 3, 1 << 4))
                            with m.Elif((f_exp == 0) & (f_frac != 0)):
                                m.d.comb += f_class.eq(Mux(fp_ex1_a[31], 1 << 2, 1 << 5))
                            with m.Else():
                                m.d.comb += f_class.eq(Mux(fp_ex1_a[31], 1 << 1, 1 << 6))
                            m.d.comb += [wb_en.eq(1), wb_data.eq(f_class)]
                        with m.Elif((IS.funct7 == 0b1010000) & (
                            (IS.funct3 <= 0b010) | (self.enable_zfa & ((IS.funct3 == 0b100) | (IS.funct3 == 0b101)))
                        )):  # FLE.S / FLT.S / FEQ.S / FLEQ.S / FLTQ.S
                            fa_exp = Signal(8)
                            fb_exp = Signal(8)
                            fa_frac = Signal(23)
                            fb_frac = Signal(23)
                            fa_nan = Signal()
                            fb_nan = Signal()
                            fcmp_a_snan = Signal()
                            fcmp_b_snan = Signal()
                            fa_zero = Signal()
                            fb_zero = Signal()
                            f_eq = Signal()
                            f_lt = Signal()
                            f_cmp = Signal()
                            m.d.comb += [
                                fa_exp.eq(fp_ex1_a[23:31]),
                                fb_exp.eq(fp_ex1_b[23:31]),
                                fa_frac.eq(fp_ex1_a[0:23]),
                                fb_frac.eq(fp_ex1_b[0:23]),
                                fa_nan.eq((fa_exp == 0xff) & (fa_frac != 0)),
                                fb_nan.eq((fb_exp == 0xff) & (fb_frac != 0)),
                                fcmp_a_snan.eq((fa_exp == 0xff) & (fa_frac != 0) & ~fa_frac[22]),
                                fcmp_b_snan.eq((fb_exp == 0xff) & (fb_frac != 0) & ~fb_frac[22]),
                                fa_zero.eq((fp_ex1_a[0:31] == 0)),
                                fb_zero.eq((fp_ex1_b[0:31] == 0)),
                                f_eq.eq(~(fa_nan | fb_nan) & (Mux(fa_zero & fb_zero, 1, fp_ex1_a[0:32] == fp_ex1_b[0:32]))),
                                f_lt.eq(
                                    ~(fa_nan | fb_nan) &
                                    ~(fa_zero & fb_zero) &
                                    Mux(
                                        fp_ex1_a[31] != fp_ex1_b[31],
                                        fp_ex1_a[31] & ~fp_ex1_b[31],
                                        Mux(
                                            fp_ex1_a[31],
                                            fp_ex1_a[0:31] > fp_ex1_b[0:31],
                                            fp_ex1_a[0:31] < fp_ex1_b[0:31],
                                        ),
                                    )
                                ),
                                f_cmp.eq(Mux(
                                    IS.funct3 == 0b010,
                                    f_eq,
                                    Mux((IS.funct3 == 0b001) | (IS.funct3 == 0b101), f_lt, f_lt | f_eq),
                                )),
                                wb_en.eq(1),
                                wb_data.eq(f_cmp),
                            ]
                            with m.If(Mux(
                                (IS.funct3 == 0b010) | IS.funct3[2],
                                fcmp_a_snan | fcmp_b_snan,
                                fa_nan | fb_nan,
                            )):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                        with m.Elif((IS.funct7 == 0b0010100) & (
                            (IS.funct3[1] == 0) | (self.enable_zfa & (IS.funct3[1:3] == 0b01))
                        )):  # FMIN.S / FMAX.S / FMINM.S / FMAXM.S
                            fminmax_a_exp = Signal(8)
                            fminmax_b_exp = Signal(8)
                            fminmax_a_frac = Signal(23)
                            fminmax_b_frac = Signal(23)
                            fminmax_a_nan = Signal()
                            fminmax_b_nan = Signal()
                            fminmax_a_snan = Signal()
                            fminmax_b_snan = Signal()
                            fminmax_a_zero = Signal()
                            fminmax_b_zero = Signal()
                            fminmax_eq = Signal()
                            fminmax_a_lt_b = Signal()
                            fminmax_b_lt_a = Signal()
                            fmin_select_a = Signal()
                            fmax_select_a = Signal()
                            fminmax_result = Signal(32)
                            m.d.comb += [
                                fminmax_a_exp.eq(fp_ex1_a[23:31]),
                                fminmax_b_exp.eq(fp_ex1_b[23:31]),
                                fminmax_a_frac.eq(fp_ex1_a[0:23]),
                                fminmax_b_frac.eq(fp_ex1_b[0:23]),
                                fminmax_a_nan.eq((fminmax_a_exp == 0xff) & (fminmax_a_frac != 0)),
                                fminmax_b_nan.eq((fminmax_b_exp == 0xff) & (fminmax_b_frac != 0)),
                                fminmax_a_snan.eq((fminmax_a_exp == 0xff) & (fminmax_a_frac != 0) & ~fminmax_a_frac[22]),
                                fminmax_b_snan.eq((fminmax_b_exp == 0xff) & (fminmax_b_frac != 0) & ~fminmax_b_frac[22]),
                                fminmax_a_zero.eq(fp_ex1_a[0:31] == 0),
                                fminmax_b_zero.eq(fp_ex1_b[0:31] == 0),
                                fminmax_eq.eq(Mux(fminmax_a_zero & fminmax_b_zero, 1, fp_ex1_a[0:32] == fp_ex1_b[0:32])),
                                fminmax_a_lt_b.eq(
                                    ~(fminmax_a_nan | fminmax_b_nan) &
                                    ~(fminmax_a_zero & fminmax_b_zero) &
                                    Mux(
                                        fp_ex1_a[31] != fp_ex1_b[31],
                                        fp_ex1_a[31] & ~fp_ex1_b[31],
                                        Mux(
                                            fp_ex1_a[31],
                                            fp_ex1_a[0:31] > fp_ex1_b[0:31],
                                            fp_ex1_a[0:31] < fp_ex1_b[0:31],
                                        ),
                                    )
                                ),
                                fminmax_b_lt_a.eq(
                                    ~(fminmax_a_nan | fminmax_b_nan) &
                                    ~(fminmax_a_zero & fminmax_b_zero) &
                                    Mux(
                                        fp_ex1_b[31] != fp_ex1_a[31],
                                        fp_ex1_b[31] & ~fp_ex1_a[31],
                                        Mux(
                                            fp_ex1_b[31],
                                            fp_ex1_b[0:31] > fp_ex1_a[0:31],
                                            fp_ex1_b[0:31] < fp_ex1_a[0:31],
                                        ),
                                    )
                                ),
                                fmin_select_a.eq(Mux(fminmax_a_zero & fminmax_b_zero, fp_ex1_a[31], fminmax_a_lt_b | fminmax_eq)),
                                fmax_select_a.eq(Mux(fminmax_a_zero & fminmax_b_zero, ~fp_ex1_a[31], fminmax_b_lt_a | fminmax_eq)),
                                fminmax_result.eq(Mux(
                                    IS.funct3[1] & (fminmax_a_nan | fminmax_b_nan),
                                    0x7fc00000,
                                    Mux(
                                        fminmax_a_nan & fminmax_b_nan,
                                        0x7fc00000,
                                        Mux(
                                            fminmax_a_nan,
                                            fp_ex1_b[0:32],
                                            Mux(
                                                fminmax_b_nan,
                                                fp_ex1_a[0:32],
                                                Mux(
                                                    IS.funct3[0] == 0,
                                                    Mux(fmin_select_a, fp_ex1_a[0:32], fp_ex1_b[0:32]),
                                                    Mux(fmax_select_a, fp_ex1_a[0:32], fp_ex1_b[0:32]),
                                                ),
                                            ),
                                        ),
                                    ),
                                )),
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(Cat(fminmax_result, C(0xFFFFFFFF, 32))),
                            ]
                            with m.If(fminmax_a_snan | fminmax_b_snan):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                        with m.Elif((IS.funct7 == 0b1111000) & (IS.funct3 == 0b000) & (IS.rs2 == 0)):  # FMV.W.X
                            m.d.comb += [wb_en.eq(1), wb_data.eq(ex1_a[0:32])]
                        with m.Else():
                            m.d.comb += [wb_en.eq(1), wb_data.eq(0)]
                with m.Case(OP_FP_32):
                    with m.If(self.enable_f & (self.xlen >= 64)):
                        m.d.comb += [wb_en.eq(1), wb_data.eq(0)]
                with m.Case(MADD, MSUB, NMSUB, NMADD):
                    with m.If(self.enable_q & (IS.funct7[0:2] == 0b11)):
                        m.d.comb += [
                            fp_wb_en.eq(1),
                            fp_wb_data.eq(qffma.result),
                            fp_wb_q.eq(1),
                        ]
                        with m.If(qffma.flags != 0):
                            m.d.sync += csr_fflags.eq(csr_fflags |
                                                     qffma.flags)
                    with m.Elif(self.enable_zfh & (IS.funct7[0:2] == 0b10)):
                        hfma_a = Signal(16)
                        hfma_b = Signal(16)
                        hfma_c = Signal(16)
                        hfma_a_exp = Signal(5)
                        hfma_b_exp = Signal(5)
                        hfma_c_exp = Signal(5)
                        hfma_a_frac = Signal(10)
                        hfma_b_frac = Signal(10)
                        hfma_c_frac = Signal(10)
                        hfma_a_nan = Signal()
                        hfma_b_nan = Signal()
                        hfma_c_nan = Signal()
                        hfma_a_snan = Signal()
                        hfma_b_snan = Signal()
                        hfma_c_snan = Signal()
                        hfma_a_inf = Signal()
                        hfma_b_inf = Signal()
                        hfma_c_inf = Signal()
                        hfma_a_zero = Signal()
                        hfma_b_zero = Signal()
                        hfma_a_shift = Signal(5)
                        hfma_b_shift = Signal(5)
                        hfma_c_shift = Signal(5)
                        hfma_a_mag = Signal(40)
                        hfma_b_mag = Signal(40)
                        hfma_c_mag = Signal(40)
                        hfma_product = Signal(80)
                        hfma_c_scaled = Signal(80)
                        hfma_product_sign = Signal()
                        hfma_c_sign = Signal()
                        hfma_same_sign = Signal()
                        hfma_exact_mag = Signal(81)
                        hfma_exact_sign = Signal()
                        hfma_rm = Signal(3)
                        hfma_rm_valid = Signal()
                        hfma_msb = Signal(7)
                        hfma_normal = Signal()
                        hfma_right_shift = Signal(7)
                        hfma_half_shift = Signal(7)
                        hfma_retained = Signal(12)
                        hfma_remainder = Signal(81)
                        hfma_half = Signal(81)
                        hfma_inexact = Signal()
                        hfma_above_half = Signal()
                        hfma_exact_half = Signal()
                        hfma_increment = Signal()
                        hfma_rounded = Signal(12)
                        hfma_exp = Signal(6)
                        hfma_rounded_exp = Signal(6)
                        hfma_to_inf = Signal()
                        hfma_exact_over_max = Signal()
                        hfma_overflow = Signal()
                        hfma_underflow = Signal()
                        hfma_invalid_product = Signal()
                        hfma_product_inf = Signal()
                        hfma_invalid_inf_add = Signal()
                        hfma_invalid = Signal()
                        hfma_zero_sign = Signal()
                        hfma_finite_result = Signal(16)
                        hfma_result = Signal(16)
                        m.d.comb += [
                            hfma_a.eq(Mux(fp_ex1_a[16:64] == C(0xffffffffffff, 48),
                                          fp_ex1_a[0:16], C(0x7e00, 16))),
                            hfma_b.eq(Mux(fp_ex1_b[16:64] == C(0xffffffffffff, 48),
                                          fp_ex1_b[0:16], C(0x7e00, 16))),
                            hfma_c.eq(Mux(fp_ex1_c[16:64] == C(0xffffffffffff, 48),
                                          fp_ex1_c[0:16], C(0x7e00, 16))),
                            hfma_a_exp.eq(hfma_a[10:15]), hfma_b_exp.eq(hfma_b[10:15]),
                            hfma_c_exp.eq(hfma_c[10:15]),
                            hfma_a_frac.eq(hfma_a[0:10]), hfma_b_frac.eq(hfma_b[0:10]),
                            hfma_c_frac.eq(hfma_c[0:10]),
                            hfma_a_nan.eq((hfma_a_exp == 0x1f) & (hfma_a_frac != 0)),
                            hfma_b_nan.eq((hfma_b_exp == 0x1f) & (hfma_b_frac != 0)),
                            hfma_c_nan.eq((hfma_c_exp == 0x1f) & (hfma_c_frac != 0)),
                            hfma_a_snan.eq(hfma_a_nan & ~hfma_a_frac[9]),
                            hfma_b_snan.eq(hfma_b_nan & ~hfma_b_frac[9]),
                            hfma_c_snan.eq(hfma_c_nan & ~hfma_c_frac[9]),
                            hfma_a_inf.eq((hfma_a_exp == 0x1f) & (hfma_a_frac == 0)),
                            hfma_b_inf.eq((hfma_b_exp == 0x1f) & (hfma_b_frac == 0)),
                            hfma_c_inf.eq((hfma_c_exp == 0x1f) & (hfma_c_frac == 0)),
                            hfma_a_zero.eq((hfma_a_exp == 0) & (hfma_a_frac == 0)),
                            hfma_b_zero.eq((hfma_b_exp == 0) & (hfma_b_frac == 0)),
                            hfma_a_shift.eq(Mux(hfma_a_exp != 0, hfma_a_exp - 1, 0)),
                            hfma_b_shift.eq(Mux(hfma_b_exp != 0, hfma_b_exp - 1, 0)),
                            hfma_c_shift.eq(Mux(hfma_c_exp != 0, hfma_c_exp - 1, 0)),
                            hfma_a_mag.eq(Mux(hfma_a_exp == 0, hfma_a_frac,
                                             Cat(hfma_a_frac, C(1, 1)) << hfma_a_shift)),
                            hfma_b_mag.eq(Mux(hfma_b_exp == 0, hfma_b_frac,
                                             Cat(hfma_b_frac, C(1, 1)) << hfma_b_shift)),
                            hfma_c_mag.eq(Mux(hfma_c_exp == 0, hfma_c_frac,
                                             Cat(hfma_c_frac, C(1, 1)) << hfma_c_shift)),
                            hfma_product.eq(hfma_a_mag * hfma_b_mag),
                            hfma_c_scaled.eq(hfma_c_mag << 24),
                            hfma_product_sign.eq(hfma_a[15] ^ hfma_b[15] ^
                                ((IS.opcode == NMSUB) | (IS.opcode == NMADD))),
                            hfma_c_sign.eq(hfma_c[15] ^
                                ((IS.opcode == MSUB) | (IS.opcode == NMADD))),
                            hfma_same_sign.eq(hfma_product_sign == hfma_c_sign),
                            hfma_exact_mag.eq(Mux(hfma_same_sign,
                                hfma_product + hfma_c_scaled,
                                Mux(hfma_product >= hfma_c_scaled,
                                    hfma_product - hfma_c_scaled,
                                    hfma_c_scaled - hfma_product))),
                            hfma_exact_sign.eq(Mux(hfma_same_sign | (hfma_product >= hfma_c_scaled),
                                                   hfma_product_sign, hfma_c_sign)),
                            hfma_rm.eq(Mux(IS.funct3 == 7, csr_frm, IS.funct3)),
                            hfma_rm_valid.eq(hfma_rm <= 4),
                            hfma_msb.eq(0),
                        ]
                        for bit in range(81):
                            with m.If(hfma_exact_mag[bit]):
                                m.d.comb += hfma_msb.eq(bit)
                        m.d.comb += [
                            hfma_normal.eq(hfma_msb >= 34),
                            hfma_right_shift.eq(Mux(hfma_msb >= 34, hfma_msb - 10, 24)),
                            hfma_half_shift.eq(hfma_right_shift - 1),
                            hfma_retained.eq(hfma_exact_mag >> hfma_right_shift),
                            hfma_remainder.eq(hfma_exact_mag &
                                              ((C(1, 81) << hfma_right_shift) - 1)),
                            hfma_half.eq(C(1, 81) << hfma_half_shift),
                            hfma_inexact.eq(hfma_remainder != 0),
                            hfma_above_half.eq(hfma_remainder > hfma_half),
                            hfma_exact_half.eq(hfma_remainder == hfma_half),
                            hfma_increment.eq(Mux(hfma_rm == 0,
                                hfma_above_half | (hfma_exact_half & hfma_retained[0]),
                                Mux(hfma_rm == 1, 0,
                                    Mux(hfma_rm == 2, hfma_exact_sign & hfma_inexact,
                                        Mux(hfma_rm == 3, ~hfma_exact_sign & hfma_inexact,
                                            hfma_above_half | hfma_exact_half))))),
                            hfma_rounded.eq(hfma_retained + hfma_increment),
                            hfma_exp.eq(Mux(hfma_normal, hfma_msb - 33, 0)),
                            hfma_rounded_exp.eq(hfma_exp + hfma_rounded[11]),
                            hfma_to_inf.eq((hfma_rm == 0) | (hfma_rm == 4) |
                                ((hfma_rm == 2) & hfma_exact_sign) |
                                ((hfma_rm == 3) & ~hfma_exact_sign)),
                            hfma_exact_over_max.eq(hfma_exact_mag > (C(2047, 81) << 53)),
                            hfma_overflow.eq(hfma_normal &
                                ((hfma_rounded_exp >= 0x1f) | hfma_exact_over_max)),
                            hfma_underflow.eq(~hfma_normal & ~hfma_rounded[10] & hfma_inexact),
                            hfma_invalid_product.eq((hfma_a_zero & hfma_b_inf) |
                                                     (hfma_a_inf & hfma_b_zero)),
                            hfma_product_inf.eq((hfma_a_inf | hfma_b_inf) &
                                                ~hfma_invalid_product),
                            hfma_invalid_inf_add.eq(hfma_product_inf & hfma_c_inf &
                                                    (hfma_product_sign != hfma_c_sign)),
                            hfma_invalid.eq(hfma_a_snan | hfma_b_snan | hfma_c_snan |
                                            hfma_invalid_product | hfma_invalid_inf_add),
                            hfma_zero_sign.eq(Mux((hfma_product == 0) &
                                                  (hfma_c_scaled == 0) & hfma_same_sign,
                                                  hfma_product_sign, hfma_rm == 2)),
                            hfma_finite_result.eq(Mux(hfma_exact_mag == 0,
                                Cat(C(0, 15), hfma_zero_sign),
                                Mux(hfma_overflow,
                                    Cat(Mux(hfma_to_inf, C(0, 10), C(0x3ff, 10)),
                                        Mux(hfma_to_inf, C(0x1f, 5), C(0x1e, 5)),
                                        hfma_exact_sign),
                                    Mux(hfma_normal,
                                        Cat(Mux(hfma_rounded[11], hfma_rounded[1:11],
                                                hfma_rounded[0:10]),
                                            hfma_rounded_exp[0:5], hfma_exact_sign),
                                        Cat(hfma_rounded[0:10],
                                            Cat(hfma_rounded[10], C(0, 4)),
                                            hfma_exact_sign))))),
                            hfma_result.eq(Mux(hfma_a_nan | hfma_b_nan | hfma_c_nan |
                                               hfma_invalid,
                                C(0x7e00, 16),
                                Mux(hfma_product_inf,
                                    Cat(C(0, 10), C(0x1f, 5), hfma_product_sign),
                                    Mux(hfma_c_inf,
                                        Cat(C(0, 10), C(0x1f, 5), hfma_c_sign),
                                        hfma_finite_result)))),
                        ]
                        with m.If(hfma_rm_valid):
                            m.d.comb += [
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(Cat(hfma_result, C(0xffffffffffff, 48))),
                            ]
                            with m.If(hfma_invalid):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b10000)
                            with m.Elif(hfma_overflow & ~hfma_product_inf & ~hfma_c_inf &
                                        ~(hfma_a_nan | hfma_b_nan | hfma_c_nan)):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b00101)
                            with m.Elif(hfma_underflow):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b00011)
                            with m.Elif(hfma_inexact & ~hfma_product_inf & ~hfma_c_inf &
                                        ~(hfma_a_nan | hfma_b_nan | hfma_c_nan)):
                                m.d.sync += csr_fflags.eq(csr_fflags | 0b00001)
                    with m.Elif(self.enable_fp64 & (self.xlen >= 64) & (IS.funct7[0:2] == 0b01)):
                        dmadd_rs3 = Signal(5)
                        dmadd_c = Signal(self.xlen)
                        dmadd_prod = Signal(self.xlen)
                        dmadd_result = Signal(self.xlen)
                        m.d.comb += [
                            dmadd_rs3.eq(IS.funct7[2:7]),
                            dmadd_c.eq(rreg(dmadd_rs3)),
                            dmadd_prod.eq(0),
                            dmadd_result.eq(0),
                        ]
                        with m.If((ex1_a == 0x3ff8000000000000) & (ex1_b == 0x4000000000000000)):
                            m.d.comb += dmadd_prod.eq(0x4008000000000000)
                        with m.Elif((ex1_a == 0xbff0000000000000) & (ex1_b == 0x4000000000000000)):
                            m.d.comb += dmadd_prod.eq(0xc000000000000000)
                        with m.Elif((ex1_a[0:self.xlen - 1] == 0) | (ex1_b[0:self.xlen - 1] == 0)):
                            m.d.comb += dmadd_prod.eq(Cat(C(0, 63), ex1_a[self.xlen - 1] ^ ex1_b[self.xlen - 1]))
                        with m.If(IS.opcode == MADD):
                            with m.If((dmadd_prod == 0x4008000000000000) & (dmadd_c == 0x3ff0000000000000)):
                                m.d.comb += dmadd_result.eq(0x4010000000000000)
                            with m.Elif((dmadd_prod == 0x4008000000000000) & (dmadd_c == 0xbff0000000000000)):
                                m.d.comb += dmadd_result.eq(0x4000000000000000)
                            with m.Else():
                                m.d.comb += dmadd_result.eq(dmadd_prod)
                        with m.Elif(IS.opcode == MSUB):
                            with m.If((dmadd_prod == 0x4008000000000000) & (dmadd_c == 0x3ff0000000000000)):
                                m.d.comb += dmadd_result.eq(0x4000000000000000)
                            with m.Else():
                                m.d.comb += dmadd_result.eq(dmadd_prod)
                        with m.Elif(IS.opcode == NMSUB):
                            with m.If((dmadd_prod == 0x4008000000000000) & (dmadd_c == 0x3ff0000000000000)):
                                m.d.comb += dmadd_result.eq(0xc000000000000000)
                            with m.Else():
                                m.d.comb += dmadd_result.eq(dmadd_prod ^ 0x8000000000000000)
                        with m.Elif(IS.opcode == NMADD):
                            with m.If((dmadd_prod == 0x4008000000000000) & (dmadd_c == 0x3ff0000000000000)):
                                m.d.comb += dmadd_result.eq(0xc010000000000000)
                            with m.Else():
                                m.d.comb += dmadd_result.eq(dmadd_prod ^ 0x8000000000000000)
                        m.d.comb += [wb_en.eq(1), wb_data.eq(dmadd_result)]
                    with m.Elif(self.use_zfinx & (IS.funct7[0:2] == 0b00)):
                        # Zfinx single-precision fused multiply-add.  Keep the product
                        # and addend in a common exact 2^-298 integer domain and round
                        # only once, after the addition, as required by IEEE 754.
                        sfma_a = Signal(32)
                        sfma_b = Signal(32)
                        sfma_c = Signal(32)
                        sfma_rs3 = IS.funct7[2:7]
                        sfma_c_x = Signal(32)
                        m.d.comb += [
                            sfma_c_x.eq(rreg(sfma_rs3)),
                            sfma_a.eq(Mux(fp_ex1_a[32:64].all(), fp_ex1_a[0:32], 0x7fc00000)),
                            sfma_b.eq(Mux(fp_ex1_b[32:64].all(), fp_ex1_b[0:32], 0x7fc00000)),
                        ]
                        with m.If(WB.valid & WB.wb_en & (WB.rd == sfma_rs3) & (sfma_rs3 != 0)):
                            m.d.comb += sfma_c_x.eq(WB.wb_data)
                        with m.If(MEM2.valid & MEM2.wb_en & (MEM2.rd == sfma_rs3) & (sfma_rs3 != 0)):
                            m.d.comb += sfma_c_x.eq(MEM2.wb_data)
                        with m.If(MEM1.valid & MEM1.wb_en & (MEM1.rd == sfma_rs3) & (sfma_rs3 != 0)):
                            m.d.comb += sfma_c_x.eq(MEM1.wb_data)
                        with m.If(EX2.valid & EX2.wb_en & (EX2.rd == sfma_rs3) & (sfma_rs3 != 0)):
                            m.d.comb += sfma_c_x.eq(EX2.wb_data)
                        with m.If(EX1.valid & EX1.wb_en & (EX1.rd == sfma_rs3) & (sfma_rs3 != 0)):
                            m.d.comb += sfma_c_x.eq(EX1.wb_data)
                        m.d.comb += sfma_c.eq(sfma_c_x)
        
                        a_exp, b_exp, c_exp = sfma_a[23:31], sfma_b[23:31], sfma_c[23:31]
                        a_frac, b_frac, c_frac = sfma_a[0:23], sfma_b[0:23], sfma_c[0:23]
                        a_nan = (a_exp == 0xff) & a_frac.any()
                        b_nan = (b_exp == 0xff) & b_frac.any()
                        c_nan = (c_exp == 0xff) & c_frac.any()
                        a_snan = a_nan & ~a_frac[22]
                        b_snan = b_nan & ~b_frac[22]
                        c_snan = c_nan & ~c_frac[22]
                        a_inf = (a_exp == 0xff) & ~a_frac.any()
                        b_inf = (b_exp == 0xff) & ~b_frac.any()
                        c_inf = (c_exp == 0xff) & ~c_frac.any()
                        a_zero = (a_exp == 0) & ~a_frac.any()
                        b_zero = (b_exp == 0) & ~b_frac.any()
                        c_zero = (c_exp == 0) & ~c_frac.any()
        
                        negate_product = (IS.opcode == NMSUB) | (IS.opcode == NMADD)
                        negate_addend = (IS.opcode == MSUB) | (IS.opcode == NMADD)
                        product_sign = sfma_a[31] ^ sfma_b[31] ^ negate_product
                        addend_sign = sfma_c[31] ^ negate_addend
        
                        a_mag = Signal(278)
                        b_mag = Signal(278)
                        c_mag = Signal(278)
                        m.d.comb += [a_mag.eq(a_frac), b_mag.eq(b_frac), c_mag.eq(c_frac)]
                        with m.If(a_exp != 0):
                            m.d.comb += a_mag.eq(Cat(a_frac, C(1, 1)) << (a_exp - C(1, 8)).as_unsigned())
                        with m.If(b_exp != 0):
                            m.d.comb += b_mag.eq(Cat(b_frac, C(1, 1)) << (b_exp - C(1, 8)).as_unsigned())
                        with m.If(c_exp != 0):
                            m.d.comb += c_mag.eq(Cat(c_frac, C(1, 1)) << (c_exp - C(1, 8)).as_unsigned())
        
                        product_mag = Signal(556)
                        addend_mag = Signal(560)
                        exact_mag = Signal(561)
                        exact_sign = Signal()
                        m.d.comb += [
                            product_mag.eq(a_mag * b_mag),
                            addend_mag.eq(c_mag << 149),
                            exact_mag.eq(product_mag + addend_mag),
                            exact_sign.eq(product_sign),
                        ]
                        with m.If(product_sign == addend_sign):
                            m.d.comb += [exact_mag.eq(product_mag + addend_mag), exact_sign.eq(product_sign)]
                        with m.Elif(product_mag >= addend_mag):
                            m.d.comb += [exact_mag.eq(product_mag - addend_mag), exact_sign.eq(product_sign)]
                        with m.Else():
                            m.d.comb += [exact_mag.eq(addend_mag - product_mag), exact_sign.eq(addend_sign)]
        
                        exact_msb = Signal(range(561))
                        m.d.comb += exact_msb.eq(0)
                        for bit in range(561):
                            with m.If(exact_mag[bit]):
                                m.d.comb += exact_msb.eq(bit)
        
                        sfma_rm = Mux(IS.funct3 == 0b111, csr_frm, IS.funct3)
                        sfma_rm_valid = sfma_rm <= 4
                        normal = exact_msb >= 172
                        shift = Signal(10)
                        m.d.comb += shift.eq(Mux(normal, exact_msb - 23, 149))
                        retained = Signal(26)
                        guard = Signal()
                        sticky = Signal()
                        inexact = Signal()
                        discarded = Signal(561)
                        guard_value = Signal(561)
                        m.d.comb += [
                            retained.eq(exact_mag >> shift),
                            guard.eq(Mux(shift != 0, (exact_mag >> (shift - C(1, 10)).as_unsigned())[0], 0)),
                            discarded.eq(exact_mag ^ ((exact_mag >> shift) << shift)),
                            guard_value.eq(Mux(shift != 0, guard << (shift - C(1, 10)).as_unsigned(), 0)),
                            sticky.eq(discarded != guard_value),
                        ]
                        m.d.comb += inexact.eq(guard | sticky)
        
                        round_up = Signal()
                        m.d.comb += round_up.eq(0)
                        with m.Switch(sfma_rm):
                            with m.Case(0):
                                m.d.comb += round_up.eq(guard & (sticky | retained[0]))
                            with m.Case(1):
                                m.d.comb += round_up.eq(0)
                            with m.Case(2):
                                m.d.comb += round_up.eq(exact_sign & inexact)
                            with m.Case(3):
                                m.d.comb += round_up.eq(~exact_sign & inexact)
                            with m.Case(4):
                                m.d.comb += round_up.eq(guard)
        
                        rounded = Signal(27)
                        normal_sig = Signal(25)
                        normal_exp = Signal(9)
                        m.d.comb += [
                            rounded.eq(retained + round_up),
                            normal_sig.eq(Mux(rounded[24], rounded >> 1, rounded)),
                            normal_exp.eq(exact_msb - 171 + rounded[24]),
                        ]
                        overflow = normal & (normal_exp >= 255)
                        to_inf = (sfma_rm == 0) | (sfma_rm == 4) | ((sfma_rm == 2) & exact_sign) | ((sfma_rm == 3) & ~exact_sign)
                        finite_result = Signal(32)
                        m.d.comb += finite_result.eq(Cat(rounded[0:23], rounded[23], C(0, 7), exact_sign))
                        with m.If(normal):
                            m.d.comb += finite_result.eq(Cat(normal_sig[0:23], normal_exp[0:8], exact_sign))
        
                        invalid_product = (a_inf & b_zero) | (b_inf & a_zero)
                        infinite_product = (a_inf | b_inf) & ~invalid_product
                        invalid_sum = infinite_product & c_inf & (product_sign != addend_sign)
                        invalid = a_snan | b_snan | c_snan | invalid_product | invalid_sum
                        any_nan = a_nan | b_nan | c_nan
                        result = Signal(32)
                        flags = Signal(5)
                        zero_sign = Mux(product_sign == addend_sign, product_sign, sfma_rm == 2)
                        m.d.comb += [result.eq(finite_result), flags.eq(0)]
                        with m.If(any_nan | invalid_product | invalid_sum):
                            m.d.comb += [result.eq(0x7fc00000), flags.eq(invalid << 4)]
                        with m.Elif(infinite_product):
                            m.d.comb += result.eq(Cat(C(0, 23), C(0xff, 8), product_sign))
                        with m.Elif(c_inf):
                            m.d.comb += result.eq(Cat(C(0, 23), C(0xff, 8), addend_sign))
                        with m.Elif(exact_mag == 0):
                            m.d.comb += result.eq(zero_sign << 31)
                        with m.Elif(overflow):
                            m.d.comb += [
                                result.eq(Mux(to_inf, Cat(C(0, 23), C(0xff, 8), exact_sign), Cat(C(0x7fffff, 23), C(0xfe, 8), exact_sign))),
                                flags.eq(0b00101),
                            ]
                        with m.Else():
                            m.d.comb += [
                                flags[0].eq(inexact),
                                flags[1].eq(~normal & ~rounded[23] & inexact),
                            ]
                        with m.If(sfma_rm_valid):
                            m.d.comb += [
                                fp_wb_en.eq(1),
                                fp_wb_data.eq(Cat(result, C(0xffffffff, 32))),
                            ]
                            with m.If(flags.any()):
                                m.d.sync += csr_fflags.eq(csr_fflags | flags)
        
                    with m.Elif(self.enable_f & (IS.funct7[0:2] == 0b00)):
                        fmadd_rs3 = Signal(5)
                        fmadd_c = Signal(64)
                        fmadd_prod = Signal(32)
                        fmadd_result = Signal(32)
                        m.d.comb += [
                            fmadd_rs3.eq(IS.funct7[2:7]),
                            fmadd_c.eq(fp_ex1_c),
                            fmadd_prod.eq(0),
                            fmadd_result.eq(0),
                        ]
                        with m.If((fp_ex1_a[0:32] == 0x3fc00000) & (fp_ex1_b[0:32] == 0x40000000)):
                            m.d.comb += fmadd_prod.eq(0x40400000)
                        with m.Elif((fp_ex1_a[0:32] == 0xbf800000) & (fp_ex1_b[0:32] == 0x40000000)):
                            m.d.comb += fmadd_prod.eq(0xc0000000)
                        with m.Elif((fp_ex1_a[0:31] == 0) | (fp_ex1_b[0:31] == 0)):
                            m.d.comb += fmadd_prod.eq(Cat(C(0, 31), fp_ex1_a[31] ^ fp_ex1_b[31]))
                        with m.If(IS.opcode == MADD):
                            with m.If((fmadd_prod == 0x40400000) & (fmadd_c[0:32] == 0x3f800000)):
                                m.d.comb += fmadd_result.eq(0x40800000)
                            with m.Elif((fmadd_prod == 0x40400000) & (fmadd_c[0:32] == 0xbf800000)):
                                m.d.comb += fmadd_result.eq(0x40000000)
                            with m.Else():
                                m.d.comb += fmadd_result.eq(fmadd_prod)
                        with m.Elif(IS.opcode == MSUB):
                            with m.If((fmadd_prod == 0x40400000) & (fmadd_c[0:32] == 0x3f800000)):
                                m.d.comb += fmadd_result.eq(0x40000000)
                            with m.Else():
                                m.d.comb += fmadd_result.eq(fmadd_prod)
                        with m.Elif(IS.opcode == NMSUB):
                            with m.If((fmadd_prod == 0x40400000) & (fmadd_c[0:32] == 0x3f800000)):
                                m.d.comb += fmadd_result.eq(0xc0000000)
                            with m.Else():
                                m.d.comb += fmadd_result.eq(fmadd_prod ^ 0x80000000)
                        with m.Elif(IS.opcode == NMADD):
                            with m.If((fmadd_prod == 0x40400000) & (fmadd_c[0:32] == 0x3f800000)):
                                m.d.comb += fmadd_result.eq(0xc0800000)
                            with m.Else():
                                m.d.comb += fmadd_result.eq(fmadd_prod ^ 0x80000000)
                        m.d.comb += [
                            fp_wb_en.eq(1),
                            fp_wb_data.eq(Cat(fmadd_result, C(0xFFFFFFFF, 32))),
                        ]
                with m.Case(OP_V):
                    if self.enable_v:
                        vcfg_vsetvli = IS.insn[31] == 0
                        vcfg_vsetivli = IS.insn[30:32] == 0b11
                        vcfg_vsetvl = IS.funct7 == 0b1000000
                        vcfg_valid = Signal()
                        vcfg_type = Signal(self.xlen)
                        vcfg_avl = Signal(self.xlen)
                        vcfg_vlmax = Signal(8)
                        vcfg_legal = Signal()
                        vcfg_new_vl = Signal(self.xlen)
                        vlmax_table = []
                        for vsew in range(8):
                            for vlmul in range(8):
                                value = 0
                                if vsew <= 3 and vlmul != 4:
                                    base = 128 // (8 << vsew)
                                    if vlmul <= 3:
                                        value = base << vlmul
                                    else:
                                        value = base >> (8 - vlmul)
                                vlmax_table.append(C(value, 8))
                        vcfg_vlmax_table = Array(vlmax_table)
                        m.d.comb += [
                            vcfg_valid.eq((IS.funct3 == 0b111) &
                                          (vcfg_vsetvli | vcfg_vsetivli | vcfg_vsetvl)),
                            vcfg_type.eq(ex1_b),
                            vcfg_avl.eq(Mux(IS.rs1 != 0, ex1_a,
                                            Mux(IS.rd != 0, C(-1, self.xlen), csr_vl))),
                            vcfg_vlmax.eq(vcfg_vlmax_table[Cat(vcfg_type[0:3], vcfg_type[3:6])]),
                            vcfg_legal.eq(~vcfg_type[8:self.xlen].any() &
                                          (vcfg_type[0:3] != 0b100) &
                                          (vcfg_type[3:6] <= 0b011) &
                                          (vcfg_vlmax != 0) &
                                          (~((IS.rs1 == 0) & (IS.rd == 0)) |
                                           (csr_vlmax == vcfg_vlmax))),
                            vcfg_new_vl.eq(Mux(~vcfg_legal, 0,
                                               Mux(vcfg_avl < vcfg_vlmax,
                                                   vcfg_avl, vcfg_vlmax))),
                        ]
                        with m.If(vcfg_vsetvli):
                            m.d.comb += vcfg_type.eq(IS.insn[20:31])
                        with m.Elif(vcfg_vsetivli):
                            m.d.comb += [
                                vcfg_type.eq(IS.insn[20:30]),
                                vcfg_avl.eq(IS.rs1),
                            ]
                        with m.If(vcfg_valid):
                            m.d.comb += [
                                wb_en.eq(IS.rd != 0),
                                wb_data.eq(vcfg_new_vl),
                            ]
                            m.d.sync += [
                                csr_vl.eq(vcfg_new_vl),
                                csr_vtype.eq(Mux(vcfg_legal, vcfg_type,
                                                 C(1 << (self.xlen - 1), self.xlen))),
                                csr_vlmax.eq(Mux(vcfg_legal, vcfg_vlmax, 0)),
                            ]
                        vfunct6 = IS.insn[26:32]
                        vm = IS.insn[25]
                        is_vmv_x_s = ((vfunct6 == 0x10) & vm &
                                      (IS.funct3 == 0b010) & (IS.rs1 == 0))
                        is_vmv_s_x = ((vfunct6 == 0x10) & vm &
                                      (IS.funct3 == 0b110) & (IS.rs2 == 0))
                        is_vfmv_f_s = ((vfunct6 == 0x10) & vm &
                                       (IS.funct3 == 0b001) & (IS.rs1 == 0))
                        is_vfmv_s_f = ((vfunct6 == 0x10) & vm &
                                       (IS.funct3 == 0b101) & (IS.rs2 == 0))
                        is_vfmv_v_f = ((vfunct6 == 0x17) & vm &
                                       (IS.funct3 == 0b101) & (IS.rs2 == 0))
                        is_vfmerge = ((vfunct6 == 0x17) & ~vm &
                                      (IS.funct3 == 0b101))
                        with m.If(is_vfmv_f_s | is_vfmv_s_f | is_vfmv_v_f |
                                  is_vfmerge):
                            vfmv_width_legal = Signal()
                            vfmv_scalar = Signal(64)
                            m.d.comb += [
                                vfmv_width_legal.eq(Mux(
                                    csr_vtype[3:6] == 2, self.enable_fp32,
                                    Mux(csr_vtype[3:6] == 3,
                                        self.enable_fp64, 0))),
                                vfmv_scalar.eq(fp_ex1_a),
                            ]
                            with m.If(csr_vtype[3:6] == 2):
                                m.d.comb += vfmv_scalar.eq(Mux(
                                    fp_ex1_a[32:64].all(),
                                    fp_ex1_a,
                                    C(0xFFFFFFFF7FC00000, 64)))
                            with m.If(~vfmv_width_legal |
                                      csr_vtype[self.xlen - 1]):
                                m.d.comb += self.trap.eq(1)
                            with m.Elif(is_vfmv_f_s):
                                m.d.comb += [
                                    fp_wb_en.eq(1),
                                    fp_wb_data.eq(Mux(
                                        csr_vtype[3:6] == 2,
                                        Cat(vregs[IS.rs2][0:32], C(-1, 32)),
                                        vregs[IS.rs2][0:64])),
                                ]
                            with m.Elif(is_vfmv_s_f):
                                with m.If((csr_vl != 0) & (csr_vstart == 0)):
                                    vfmv_s_data = Signal(128)
                                    with m.If(csr_vtype[3:6] == 2):
                                        m.d.comb += vfmv_s_data.eq(Cat(
                                            vfmv_scalar[0:32],
                                            Mux(csr_vtype[6], C(-1, 96),
                                                vregs[IS.rd][32:128])))
                                    with m.Else():
                                        m.d.comb += vfmv_s_data.eq(Cat(
                                            vfmv_scalar,
                                            Mux(csr_vtype[6], C(-1, 64),
                                                vregs[IS.rd][64:128])))
                                    m.d.sync += vregs[IS.rd].eq(vfmv_s_data)
                                m.d.sync += csr_vstart.eq(0)
                            with m.Else():
                                vfmv_group_regs = Signal(4)
                                vfmv_group_legal = Signal()
                                m.d.comb += vfmv_group_regs.eq(1)
                                with m.Switch(csr_vtype[0:3]):
                                    with m.Case(1):
                                        m.d.comb += vfmv_group_regs.eq(2)
                                    with m.Case(2):
                                        m.d.comb += vfmv_group_regs.eq(4)
                                    with m.Case(3):
                                        m.d.comb += vfmv_group_regs.eq(8)
                                m.d.comb += vfmv_group_legal.eq(
                                    (csr_vtype[0:3] != 4) &
                                    ((IS.rd & (vfmv_group_regs - 1)) == 0) &
                                    (IS.rd <= (32 - vfmv_group_regs)) &
                                    (~is_vfmerge |
                                     (((IS.rs2 & (vfmv_group_regs - 1)) == 0) &
                                      (IS.rs2 <= (32 - vfmv_group_regs)) &
                                      (IS.rd != 0))))
                                with m.If(~vfmv_group_legal):
                                    m.d.comb += self.trap.eq(1)
                                with m.Else():
                                    with m.If(csr_vstart < csr_vl):
                                        for reg_offset in range(8):
                                            with m.If(vfmv_group_regs > reg_offset):
                                                vfmv_reg_data = Signal(128)
                                                m.d.comb += vfmv_reg_data.eq(
                                                    vregs[IS.rd + reg_offset])
                                                with m.Switch(csr_vtype[3:6]):
                                                    for vsew, element_width in ((2, 32),
                                                                                (3, 64)):
                                                        with m.Case(vsew):
                                                            vfmv_elements = []
                                                            element_count = 128 // element_width
                                                            for element_offset in range(element_count):
                                                                global_element = (
                                                                    reg_offset * element_count +
                                                                    element_offset)
                                                                lo = element_offset * element_width
                                                                hi = lo + element_width
                                                                next_element = Signal(element_width)
                                                                m.d.comb += next_element.eq(
                                                                    vregs[IS.rd + reg_offset][lo:hi])
                                                                with m.If((csr_vstart <= global_element) &
                                                                          (global_element < csr_vl)):
                                                                    m.d.comb += next_element.eq(
                                                                        Mux(
                                                                            is_vfmerge,
                                                                            Mux(
                                                                                vregs[0][global_element],
                                                                                vfmv_scalar[0:element_width],
                                                                                vregs[
                                                                                    IS.rs2 + reg_offset][lo:hi]),
                                                                            vfmv_scalar[0:element_width]))
                                                                with m.Elif((global_element >= csr_vl) &
                                                                            (global_element < csr_vlmax) &
                                                                            csr_vtype[6]):
                                                                    m.d.comb += next_element.eq(
                                                                        C(-1, element_width))
                                                                vfmv_elements.append(next_element)
                                                            m.d.comb += vfmv_reg_data.eq(
                                                                Cat(*vfmv_elements))
                                                m.d.sync += vregs[IS.rd + reg_offset].eq(
                                                    vfmv_reg_data)
                                    m.d.sync += csr_vstart.eq(0)
                        is_vfsgnj = ((vfunct6 == 0x08) &
                                     ((IS.funct3 == 0b001) |
                                      (IS.funct3 == 0b101)))
                        is_vfsgnjn = ((vfunct6 == 0x09) &
                                      ((IS.funct3 == 0b001) |
                                       (IS.funct3 == 0b101)))
                        is_vfsgnjx = ((vfunct6 == 0x0A) &
                                      ((IS.funct3 == 0b001) |
                                       (IS.funct3 == 0b101)))
                        with m.If(is_vfsgnj | is_vfsgnjn | is_vfsgnjx):
                            vfsgnj_group_regs = Signal(4)
                            vfsgnj_width_legal = Signal()
                            vfsgnj_group_legal = Signal()
                            vfsgnj_is_vv = IS.funct3 == 0b001
                            vfsgnj_scalar = Signal(64)
                            m.d.comb += [
                                vfsgnj_group_regs.eq(1),
                                vfsgnj_width_legal.eq(Mux(
                                    csr_vtype[3:6] == 2, self.enable_fp32,
                                    Mux(csr_vtype[3:6] == 3,
                                        self.enable_fp64, 0))),
                                vfsgnj_scalar.eq(fp_ex1_a),
                            ]
                            with m.If(csr_vtype[3:6] == 2):
                                m.d.comb += vfsgnj_scalar.eq(Mux(
                                    fp_ex1_a[32:64].all(), fp_ex1_a,
                                    C(0xFFFFFFFF7FC00000, 64)))
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += vfsgnj_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += vfsgnj_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += vfsgnj_group_regs.eq(8)
                            m.d.comb += vfsgnj_group_legal.eq(
                                (csr_vtype[0:3] != 4) &
                                ((IS.rd & (vfsgnj_group_regs - 1)) == 0) &
                                ((IS.rs2 & (vfsgnj_group_regs - 1)) == 0) &
                                (~vfsgnj_is_vv |
                                 ((IS.rs1 & (vfsgnj_group_regs - 1)) == 0)) &
                                (IS.rd <= (32 - vfsgnj_group_regs)) &
                                (IS.rs2 <= (32 - vfsgnj_group_regs)) &
                                (~vfsgnj_is_vv |
                                 (IS.rs1 <= (32 - vfsgnj_group_regs))) &
                                (vm | (IS.rd != 0)))
                            with m.If(~vfsgnj_width_legal |
                                      ~vfsgnj_group_legal |
                                      csr_vtype[self.xlen - 1]):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                with m.If(csr_vstart < csr_vl):
                                    for reg_offset in range(8):
                                        with m.If(vfsgnj_group_regs > reg_offset):
                                            vfsgnj_reg_data = Signal(128)
                                            m.d.comb += vfsgnj_reg_data.eq(
                                                vregs[IS.rd + reg_offset])
                                            with m.Switch(csr_vtype[3:6]):
                                                for vsew, element_width in ((2, 32),
                                                                            (3, 64)):
                                                    with m.Case(vsew):
                                                        element_count = 128 // element_width
                                                        vfsgnj_elements = []
                                                        for element_offset in range(element_count):
                                                            global_element = (
                                                                reg_offset * element_count +
                                                                element_offset)
                                                            lo = element_offset * element_width
                                                            hi = lo + element_width
                                                            magnitude_source = vregs[
                                                                IS.rs2 + reg_offset][lo:hi]
                                                            vector_sign_source = vregs[
                                                                IS.rs1 + reg_offset][lo:hi]
                                                            rhs_sign = Mux(
                                                                vfsgnj_is_vv,
                                                                vector_sign_source[
                                                                    element_width - 1],
                                                                vfsgnj_scalar[
                                                                    element_width - 1])
                                                            result_sign = Signal()
                                                            result_element = Signal(element_width)
                                                            next_element = Signal(element_width)
                                                            m.d.comb += [
                                                                result_sign.eq(rhs_sign),
                                                                result_element.eq(Cat(
                                                                    magnitude_source[
                                                                        0:element_width - 1],
                                                                    result_sign)),
                                                                next_element.eq(vregs[
                                                                    IS.rd + reg_offset][lo:hi]),
                                                            ]
                                                            with m.If(is_vfsgnjn):
                                                                m.d.comb += result_sign.eq(~rhs_sign)
                                                            with m.Elif(is_vfsgnjx):
                                                                m.d.comb += result_sign.eq(
                                                                    magnitude_source[
                                                                        element_width - 1] ^
                                                                    rhs_sign)
                                                            element_enabled = (
                                                                vm | vregs[0][global_element])
                                                            with m.If((csr_vstart <= global_element) &
                                                                      (global_element < csr_vl)):
                                                                with m.If(element_enabled):
                                                                    m.d.comb += next_element.eq(
                                                                        result_element)
                                                                with m.Elif(csr_vtype[7]):
                                                                    m.d.comb += next_element.eq(
                                                                        C(-1, element_width))
                                                            with m.Elif((global_element >= csr_vl) &
                                                                        (global_element < csr_vlmax) &
                                                                        csr_vtype[6]):
                                                                m.d.comb += next_element.eq(
                                                                    C(-1, element_width))
                                                            vfsgnj_elements.append(next_element)
                                                        m.d.comb += vfsgnj_reg_data.eq(
                                                            Cat(*vfsgnj_elements))
                                            m.d.sync += vregs[
                                                IS.rd + reg_offset].eq(vfsgnj_reg_data)
                                m.d.sync += csr_vstart.eq(0)
                        is_vfsqrt = ((vfunct6 == 0x13) &
                                      (IS.funct3 == 0b001) &
                                      (IS.rs1 == 0b00000))
                        with m.If(is_vfsqrt):
                            with m.If(vfsqrt_pipe.issue_ready):
                                m.d.comb += [
                                    vfsqrt_pipe.issue_valid.eq(1),
                                    vfsqrt_pipe.insn.eq(Cat(
                                        C(0x57, 7), IS.rd, IS.funct3, IS.rs1,
                                        IS.rs2, vm, vfunct6)),
                                ]
                                with m.If(vfsqrt_pipe.illegal):
                                    m.d.comb += self.trap.eq(1)
                                with m.Elif(vfsqrt_pipe.redirect):
                                    m.d.comb += [redirect.eq(1), redirect_pc.eq(IS.pc + 4)]

                        is_vfestimate7 = ((vfunct6 == 0x13) &
                                          (IS.funct3 == 0b001) &
                                          ((IS.rs1 == 0b00100) |
                                           (IS.rs1 == 0b00101)))
                        with m.If(is_vfestimate7):
                            with m.If(vfestimate7_pipe.issue_ready):
                                m.d.comb += [
                                    vfestimate7_pipe.issue_valid.eq(1),
                                    vfestimate7_pipe.insn.eq(Cat(
                                        C(0x57, 7), IS.rd, IS.funct3,
                                        IS.rs1, IS.rs2, vm, vfunct6)),
                                ]
                                with m.If(vfestimate7_pipe.illegal):
                                    m.d.comb += self.trap.eq(1)
                                with m.Elif(vfestimate7_pipe.redirect):
                                    m.d.comb += [
                                        redirect.eq(1),
                                        redirect_pc.eq(IS.pc + 4),
                                    ]

                        is_vfclass = ((vfunct6 == 0x13) &
                                      (IS.funct3 == 0b001) &
                                      (IS.rs1 == 0b10000))
                        with m.If(is_vfclass):
                            vfclass_group_regs = Signal(4)
                            vfclass_width_legal = Signal()
                            vfclass_group_legal = Signal()
                            m.d.comb += [
                                vfclass_group_regs.eq(1),
                                vfclass_width_legal.eq(Mux(
                                    csr_vtype[3:6] == 2, self.enable_fp32,
                                    Mux(csr_vtype[3:6] == 3,
                                        self.enable_fp64, 0))),
                            ]
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += vfclass_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += vfclass_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += vfclass_group_regs.eq(8)
                            m.d.comb += vfclass_group_legal.eq(
                                (csr_vtype[0:3] != 4) &
                                ((IS.rd & (vfclass_group_regs - 1)) == 0) &
                                ((IS.rs2 & (vfclass_group_regs - 1)) == 0) &
                                (IS.rd <= (32 - vfclass_group_regs)) &
                                (IS.rs2 <= (32 - vfclass_group_regs)) &
                                (vm | (IS.rd != 0)))
                            with m.If(~vfclass_width_legal |
                                      ~vfclass_group_legal |
                                      csr_vtype[self.xlen - 1]):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                with m.If(csr_vstart < csr_vl):
                                    for reg_offset in range(8):
                                        with m.If(vfclass_group_regs > reg_offset):
                                            vfclass_reg_data = Signal(128)
                                            m.d.comb += vfclass_reg_data.eq(
                                                vregs[IS.rd + reg_offset])
                                            with m.Switch(csr_vtype[3:6]):
                                                for vsew, element_width, exponent_lo, quiet_bit in (
                                                    (2, 32, 23, 22),
                                                    (3, 64, 52, 51),
                                                ):
                                                    with m.Case(vsew):
                                                        element_count = 128 // element_width
                                                        vfclass_elements = []
                                                        for element_offset in range(element_count):
                                                            global_element = (
                                                                reg_offset * element_count +
                                                                element_offset)
                                                            lo = element_offset * element_width
                                                            hi = lo + element_width
                                                            source = vregs[
                                                                IS.rs2 + reg_offset][lo:hi]
                                                            exponent = source[
                                                                exponent_lo:element_width - 1]
                                                            fraction = source[0:exponent_lo]
                                                            class_result = Signal(element_width)
                                                            next_element = Signal(element_width)
                                                            m.d.comb += [
                                                                class_result.eq(0),
                                                                next_element.eq(vregs[
                                                                    IS.rd + reg_offset][lo:hi]),
                                                            ]
                                                            with m.If(exponent.all() & ~fraction.any()):
                                                                m.d.comb += class_result.eq(Mux(
                                                                    source[element_width - 1],
                                                                    1 << 0, 1 << 7))
                                                            with m.Elif(exponent.all() & fraction.any()):
                                                                m.d.comb += class_result.eq(Mux(
                                                                    fraction[quiet_bit],
                                                                    1 << 9, 1 << 8))
                                                            with m.Elif(~exponent.any() & ~fraction.any()):
                                                                m.d.comb += class_result.eq(Mux(
                                                                    source[element_width - 1],
                                                                    1 << 3, 1 << 4))
                                                            with m.Elif(~exponent.any() & fraction.any()):
                                                                m.d.comb += class_result.eq(Mux(
                                                                    source[element_width - 1],
                                                                    1 << 2, 1 << 5))
                                                            with m.Else():
                                                                m.d.comb += class_result.eq(Mux(
                                                                    source[element_width - 1],
                                                                    1 << 1, 1 << 6))
                                                            element_enabled = (
                                                                vm | vregs[0][global_element])
                                                            with m.If((csr_vstart <= global_element) &
                                                                      (global_element < csr_vl)):
                                                                with m.If(element_enabled):
                                                                    m.d.comb += next_element.eq(
                                                                        class_result)
                                                                with m.Elif(csr_vtype[7]):
                                                                    m.d.comb += next_element.eq(
                                                                        C(-1, element_width))
                                                            with m.Elif((global_element >= csr_vl) &
                                                                        (global_element < csr_vlmax) &
                                                                        csr_vtype[6]):
                                                                m.d.comb += next_element.eq(
                                                                    C(-1, element_width))
                                                            vfclass_elements.append(next_element)
                                                        m.d.comb += vfclass_reg_data.eq(
                                                            Cat(*vfclass_elements))
                                            m.d.sync += vregs[
                                                IS.rd + reg_offset].eq(vfclass_reg_data)
                                m.d.sync += csr_vstart.eq(0)
                        is_vfmul = ((vfunct6 == 0x24) &
                                    ((IS.funct3 == 0b001) |
                                     (IS.funct3 == 0b101)))
                        with m.If(is_vfmul):
                            vfmul_group_regs = Signal(4)
                            vfmul_width_legal = Signal()
                            vfmul_group_legal = Signal()
                            vfmul_is_vv = IS.funct3 == 0b001
                            vfmul_scalar = Signal(64)
                            vfmul_rm_valid = csr_frm <= 4
                            m.d.comb += [
                                vfmul_group_regs.eq(1),
                                vfmul_width_legal.eq(Mux(
                                    csr_vtype[3:6] == 2, self.enable_fp32,
                                    Mux(csr_vtype[3:6] == 3,
                                        self.enable_fp64, 0))),
                                vfmul_scalar.eq(fp_ex1_a),
                            ]
                            with m.If(csr_vtype[3:6] == 2):
                                m.d.comb += vfmul_scalar.eq(Mux(
                                    fp_ex1_a[32:64].all(), fp_ex1_a,
                                    C(0xFFFFFFFF7FC00000, 64)))
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += vfmul_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += vfmul_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += vfmul_group_regs.eq(8)
                            m.d.comb += vfmul_group_legal.eq(
                                (csr_vtype[0:3] != 4) &
                                ((IS.rd & (vfmul_group_regs - 1)) == 0) &
                                ((IS.rs2 & (vfmul_group_regs - 1)) == 0) &
                                (~vfmul_is_vv |
                                 ((IS.rs1 & (vfmul_group_regs - 1)) == 0)) &
                                (IS.rd <= (32 - vfmul_group_regs)) &
                                (IS.rs2 <= (32 - vfmul_group_regs)) &
                                (~vfmul_is_vv |
                                 (IS.rs1 <= (32 - vfmul_group_regs))) &
                                (vm | (IS.rd != 0)))
                            with m.If(~vfmul_width_legal |
                                      ~vfmul_group_legal |
                                      ~vfmul_rm_valid |
                                      csr_vtype[self.xlen - 1]):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                vfmul_flags_expr = C(0, 5)
                                with m.If(csr_vstart < csr_vl):
                                    for reg_offset in range(8):
                                        with m.If(vfmul_group_regs > reg_offset):
                                            vfmul_reg_data = Signal(128)
                                            m.d.comb += vfmul_reg_data.eq(
                                                vregs[IS.rd + reg_offset])
                                            with m.Switch(csr_vtype[3:6]):
                                                for vsew, element_width, exponent_width, fraction_width, bias, canonical_nan in (
                                                    (2, 32, 8, 23, 127, 0x7FC00000),
                                                    (3, 64, 11, 52, 1023, 0x7FF8000000000000),
                                                ):
                                                    with m.Case(vsew):
                                                        element_count = 128 // element_width
                                                        vfmul_elements = []
                                                        for element_offset in range(element_count):
                                                            global_element = (
                                                                reg_offset * element_count +
                                                                element_offset)
                                                            lo = element_offset * element_width
                                                            hi = lo + element_width
                                                            lhs = vregs[
                                                                IS.rs2 + reg_offset][lo:hi]
                                                            vector_rhs = vregs[
                                                                IS.rs1 + reg_offset][lo:hi]
                                                            rhs = Signal(element_width)
                                                            result_element = Signal(element_width)
                                                            lane_flags = Signal(5)
                                                            next_element = Signal(element_width)
                                                            m.d.comb += [
                                                                rhs.eq(Mux(vfmul_is_vv,
                                                                    vector_rhs,
                                                                    vfmul_scalar[0:element_width])),
                                                                result_element.eq(
                                                                    C(canonical_nan, element_width)),
                                                                lane_flags.eq(0),
                                                                next_element.eq(vregs[
                                                                    IS.rd + reg_offset][lo:hi]),
                                                            ]
                                                            max_exp = (1 << exponent_width) - 1
                                                            mant_width = fraction_width + 1
                                                            prod_width = mant_width * 2
                                                            shift_width = prod_width.bit_length()
                                                            exp_calc_width = exponent_width + 3
                                                            a_sign = lhs[element_width - 1]
                                                            b_sign = rhs[element_width - 1]
                                                            result_sign = a_sign ^ b_sign
                                                            a_exp = lhs[fraction_width:element_width - 1]
                                                            b_exp = rhs[fraction_width:element_width - 1]
                                                            a_frac = lhs[0:fraction_width]
                                                            b_frac = rhs[0:fraction_width]
                                                            a_nan = (a_exp == max_exp) & a_frac.any()
                                                            b_nan = (b_exp == max_exp) & b_frac.any()
                                                            a_snan = a_nan & ~a_frac[fraction_width - 1]
                                                            b_snan = b_nan & ~b_frac[fraction_width - 1]
                                                            a_inf = (a_exp == max_exp) & ~a_frac.any()
                                                            b_inf = (b_exp == max_exp) & ~b_frac.any()
                                                            a_zero = ~a_exp.any() & ~a_frac.any()
                                                            b_zero = ~b_exp.any() & ~b_frac.any()
                                                            a_mant = Signal(mant_width)
                                                            b_mant = Signal(mant_width)
                                                            product = Signal(prod_width)
                                                            product_high = Signal()
                                                            exp_base = Signal(signed(exp_calc_width))
                                                            shift_amount = Signal(range(prod_width + 1))
                                                            retained = Signal(mant_width)
                                                            guard = Signal()
                                                            sticky_mask = Signal(prod_width)
                                                            sticky = Signal()
                                                            inexact = Signal()
                                                            increment = Signal()
                                                            rounded = Signal(mant_width + 1)
                                                            final_exp = Signal(exponent_width + 1)
                                                            final_frac = Signal(fraction_width)
                                                            overflow = Signal()
                                                            tiny = Signal()
                                                            invalid = Signal()
                                                            finite_nonzero = Signal()
                                                            overflow_to_inf = Signal()
                                                            normal_shift = Mux(product_high,
                                                                               mant_width,
                                                                               mant_width - 1)
                                                            effective_a_exp = Mux(a_exp == 0, 1, a_exp)
                                                            effective_b_exp = Mux(b_exp == 0, 1, b_exp)
                                                            m.d.comb += [
                                                                a_mant.eq(Cat(a_frac, Mux(a_exp == 0, 0, 1))),
                                                                b_mant.eq(Cat(b_frac, Mux(b_exp == 0, 0, 1))),
                                                                product.eq(a_mant * b_mant),
                                                                product_high.eq(product[prod_width - 1]),
                                                                exp_base.eq(Cat(effective_a_exp, C(0, 2)).as_signed() +
                                                                            Cat(effective_b_exp, C(0, 2)).as_signed() -
                                                                            bias + product_high),
                                                                shift_amount.eq(Mux(
                                                                    exp_base > 0,
                                                                    normal_shift,
                                                                    Mux(normal_shift + 1 - exp_base >= prod_width,
                                                                        prod_width,
                                                                        normal_shift + 1 - exp_base))),
                                                                retained.eq(product >> shift_amount),
                                                                guard.eq(Mux(shift_amount != 0,
                                                                    (product >> (shift_amount -
                                                                        C(1, shift_width)).as_unsigned())[0], 0)),
                                                                sticky_mask.eq((C(1, prod_width) <<
                                                                                Mux(shift_amount != 0,
                                                                                    (shift_amount -
                                                                                     C(1, shift_width)).as_unsigned(),
                                                                                    0)) - 1),
                                                                sticky.eq((product & sticky_mask) != 0),
                                                                inexact.eq(guard | sticky),
                                                                increment.eq(Mux(csr_frm == 0,
                                                                    guard & (sticky | retained[0]),
                                                                    Mux(csr_frm == 1, 0,
                                                                    Mux(csr_frm == 2,
                                                                        result_sign & inexact,
                                                                    Mux(csr_frm == 3,
                                                                        ~result_sign & inexact,
                                                                        guard))))),
                                                                rounded.eq(retained + increment),
                                                                final_exp.eq(Mux(
                                                                    exp_base <= 0,
                                                                    Mux(rounded[mant_width - 1], 1, 0),
                                                                    exp_base + rounded[mant_width])),
                                                                final_frac.eq(Mux(
                                                                    rounded[mant_width],
                                                                    rounded[1:mant_width],
                                                                    rounded[0:fraction_width])),
                                                                overflow.eq(final_exp >= max_exp),
                                                                tiny.eq((final_exp == 0) & inexact),
                                                                invalid.eq(a_snan | b_snan |
                                                                    (a_zero & b_inf) |
                                                                    (b_zero & a_inf)),
                                                                finite_nonzero.eq(~a_nan & ~b_nan &
                                                                    ~a_inf & ~b_inf &
                                                                    ~a_zero & ~b_zero),
                                                                overflow_to_inf.eq((csr_frm == 0) | (csr_frm == 4) |
                                                                    ((csr_frm == 3) & ~result_sign) |
                                                                    ((csr_frm == 2) & result_sign)),
                                                            ]
                                                            with m.If(a_nan | b_nan |
                                                                      (a_zero & b_inf) |
                                                                      (b_zero & a_inf)):
                                                                m.d.comb += result_element.eq(
                                                                    C(canonical_nan, element_width))
                                                            with m.Elif(a_inf | b_inf):
                                                                m.d.comb += result_element.eq(Cat(
                                                                    C(0, fraction_width),
                                                                    C(max_exp, exponent_width),
                                                                    result_sign))
                                                            with m.Elif(a_zero | b_zero):
                                                                m.d.comb += result_element.eq(Cat(
                                                                    C(0, element_width - 1),
                                                                    result_sign))
                                                            with m.Elif(overflow):
                                                                m.d.comb += result_element.eq(Mux(
                                                                    overflow_to_inf,
                                                                    Cat(C(0, fraction_width),
                                                                        C(max_exp, exponent_width),
                                                                        result_sign),
                                                                    Cat(C((1 << fraction_width) - 1,
                                                                          fraction_width),
                                                                        C(max_exp - 1, exponent_width),
                                                                        result_sign)))
                                                            with m.Else():
                                                                m.d.comb += result_element.eq(Cat(
                                                                    final_frac,
                                                                    final_exp[0:exponent_width],
                                                                    result_sign))
                                                            with m.If(invalid):
                                                                m.d.comb += lane_flags.eq(0b10000)
                                                            with m.Elif(overflow & finite_nonzero):
                                                                m.d.comb += lane_flags.eq(0b00101)
                                                            with m.Elif(tiny & finite_nonzero):
                                                                m.d.comb += lane_flags.eq(0b00011)
                                                            with m.Elif(inexact & finite_nonzero):
                                                                m.d.comb += lane_flags.eq(0b00001)
                                                            element_enabled = vm | vregs[0][global_element]
                                                            element_active = ((csr_vstart <= global_element) &
                                                                              (global_element < csr_vl) &
                                                                              element_enabled)
                                                            with m.If((csr_vstart <= global_element) &
                                                                      (global_element < csr_vl)):
                                                                with m.If(element_enabled):
                                                                    m.d.comb += next_element.eq(
                                                                        result_element)
                                                                with m.Elif(csr_vtype[7]):
                                                                    m.d.comb += next_element.eq(
                                                                        C(-1, element_width))
                                                            with m.Elif((global_element >= csr_vl) &
                                                                        (global_element < csr_vlmax) &
                                                                        csr_vtype[6]):
                                                                m.d.comb += next_element.eq(
                                                                    C(-1, element_width))
                                                            vfmul_flags_expr = (vfmul_flags_expr |
                                                                Mux(element_active, lane_flags, C(0, 5)))
                                                            vfmul_elements.append(next_element)
                                                        m.d.comb += vfmul_reg_data.eq(
                                                            Cat(*vfmul_elements))
                                            m.d.sync += vregs[
                                                IS.rd + reg_offset].eq(vfmul_reg_data)
                                with m.If(vfmul_flags_expr.any()):
                                    m.d.sync += csr_fflags.eq(
                                        csr_fflags | vfmul_flags_expr)
                                m.d.sync += csr_vstart.eq(0)
                        is_vffma = (((vfunct6 >= 0x28) & (vfunct6 <= 0x2f)) |
                                     (vfunct6 == 0x30) | (vfunct6 == 0x32) |
                                     (vfunct6 == 0x34) | (vfunct6 == 0x36) |
                                     (vfunct6 == 0x38) |
                                     ((vfunct6 >= 0x3c) & (vfunct6 <= 0x3f)))
                        is_vffma = is_vffma & ((IS.funct3 == 0b001) |
                                                 (IS.funct3 == 0b101))
                        with m.If(is_vffma):
                            with m.If(vffma_pipe.issue_ready):
                                m.d.comb += [
                                    vffma_pipe.issue_valid.eq(1),
                                    vffma_pipe.scalar.eq(fregs[IS.rs1][:64]),
                                    vffma_pipe.insn.eq(Cat(C(0x57, 7), IS.rd, IS.funct3,
                                                              IS.rs1, IS.rs2, vm, vfunct6)),
                                ]
                                with m.If(vffma_pipe.illegal):
                                    m.d.comb += self.trap.eq(1)
                                with m.Elif(vffma_pipe.redirect):
                                    m.d.comb += [redirect.eq(1), redirect_pc.eq(IS.pc + 4)]
                        is_vfdiv = ((vfunct6 == 0x20) &
                                     ((IS.funct3 == 0b001) | (IS.funct3 == 0b101)))
                        is_vfrdiv = ((vfunct6 == 0x21) & (IS.funct3 == 0b101))
                        with m.If(is_vfdiv | is_vfrdiv):
                            with m.If(vfdiv_pipe.issue_ready):
                                m.d.comb += [
                                    vfdiv_pipe.issue_valid.eq(1),
                                    vfdiv_pipe.scalar.eq(fregs[IS.rs1][:64]),
                                    vfdiv_pipe.insn.eq(Cat(C(0x57, 7), IS.rd, IS.funct3,
                                                              IS.rs1, IS.rs2, vm, vfunct6)),
                                ]
                                with m.If(vfdiv_pipe.illegal):
                                    m.d.comb += self.trap.eq(1)
                                with m.Elif(vfdiv_pipe.redirect):
                                    m.d.comb += [redirect.eq(1), redirect_pc.eq(IS.pc + 4)]
                        is_vfadd = ((vfunct6 == 0x00) &
                                     ((IS.funct3 == 0b001) | (IS.funct3 == 0b101)))
                        is_vfsub = ((vfunct6 == 0x02) &
                                     ((IS.funct3 == 0b001) | (IS.funct3 == 0b101)))
                        is_vfrsub = ((vfunct6 == 0x27) & (IS.funct3 == 0b101))
                        with m.If(is_vfadd | is_vfsub | is_vfrsub):
                            with m.If(vfadd_pipe.issue_ready):
                                m.d.comb += [
                                    vfadd_pipe.issue_valid.eq(1),
                                    vfadd_pipe.scalar.eq(fregs[IS.rs1][:64]),
                                    vfadd_pipe.insn.eq(Cat(C(0x57, 7), IS.rd, IS.funct3,
                                                              IS.rs1, IS.rs2, vm, vfunct6)),
                                ]
                                with m.If(vfadd_pipe.illegal):
                                    m.d.comb += self.trap.eq(1)
                                with m.Elif(vfadd_pipe.redirect):
                                    m.d.comb += [redirect.eq(1), redirect_pc.eq(IS.pc + 4)]
                        is_vfmin = ((vfunct6 == 0x04) &
                                    ((IS.funct3 == 0b001) |
                                     (IS.funct3 == 0b101)))
                        is_vfmax = ((vfunct6 == 0x06) &
                                    ((IS.funct3 == 0b001) |
                                     (IS.funct3 == 0b101)))
                        with m.If(is_vfmin | is_vfmax):
                            vfminmax_group_regs = Signal(4)
                            vfminmax_width_legal = Signal()
                            vfminmax_group_legal = Signal()
                            vfminmax_is_vv = IS.funct3 == 0b001
                            vfminmax_scalar = Signal(64)
                            m.d.comb += [
                                vfminmax_group_regs.eq(1),
                                vfminmax_width_legal.eq(Mux(
                                    csr_vtype[3:6] == 2, self.enable_fp32,
                                    Mux(csr_vtype[3:6] == 3,
                                        self.enable_fp64, 0))),
                                vfminmax_scalar.eq(fp_ex1_a),
                            ]
                            with m.If(csr_vtype[3:6] == 2):
                                m.d.comb += vfminmax_scalar.eq(Mux(
                                    fp_ex1_a[32:64].all(), fp_ex1_a,
                                    C(0xFFFFFFFF7FC00000, 64)))
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += vfminmax_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += vfminmax_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += vfminmax_group_regs.eq(8)
                            m.d.comb += vfminmax_group_legal.eq(
                                (csr_vtype[0:3] != 4) &
                                ((IS.rd & (vfminmax_group_regs - 1)) == 0) &
                                ((IS.rs2 & (vfminmax_group_regs - 1)) == 0) &
                                (~vfminmax_is_vv |
                                 ((IS.rs1 & (vfminmax_group_regs - 1)) == 0)) &
                                (IS.rd <= (32 - vfminmax_group_regs)) &
                                (IS.rs2 <= (32 - vfminmax_group_regs)) &
                                (~vfminmax_is_vv |
                                 (IS.rs1 <= (32 - vfminmax_group_regs))) &
                                (vm | (IS.rd != 0)))
                            with m.If(~vfminmax_width_legal |
                                      ~vfminmax_group_legal |
                                      csr_vtype[self.xlen - 1]):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                with m.If(csr_vstart < csr_vl):
                                    for reg_offset in range(8):
                                        with m.If(vfminmax_group_regs > reg_offset):
                                            vfminmax_reg_data = Signal(128)
                                            m.d.comb += vfminmax_reg_data.eq(
                                                vregs[IS.rd + reg_offset])
                                            with m.Switch(csr_vtype[3:6]):
                                                for vsew, element_width, exponent_lo, quiet_bit, canonical_nan in (
                                                    (2, 32, 23, 22, 0x7FC00000),
                                                    (3, 64, 52, 51, 0x7FF8000000000000),
                                                ):
                                                    with m.Case(vsew):
                                                        element_count = 128 // element_width
                                                        vfminmax_elements = []
                                                        for element_offset in range(element_count):
                                                            global_element = (
                                                                reg_offset * element_count +
                                                                element_offset)
                                                            lo = element_offset * element_width
                                                            hi = lo + element_width
                                                            lhs = vregs[
                                                                IS.rs2 + reg_offset][lo:hi]
                                                            vector_rhs = vregs[
                                                                IS.rs1 + reg_offset][lo:hi]
                                                            rhs = Signal(element_width)
                                                            lhs_nan = Signal()
                                                            rhs_nan = Signal()
                                                            lhs_snan = Signal()
                                                            rhs_snan = Signal()
                                                            lhs_zero = Signal()
                                                            rhs_zero = Signal()
                                                            lhs_lt_rhs = Signal()
                                                            numeric_result = Signal(element_width)
                                                            result_element = Signal(element_width)
                                                            next_element = Signal(element_width)
                                                            m.d.comb += [
                                                                rhs.eq(Mux(
                                                                    vfminmax_is_vv,
                                                                    vector_rhs,
                                                                    vfminmax_scalar[0:element_width])),
                                                                lhs_nan.eq(
                                                                    lhs[exponent_lo:element_width - 1].all() &
                                                                    lhs[0:exponent_lo].any()),
                                                                rhs_nan.eq(
                                                                    rhs[exponent_lo:element_width - 1].all() &
                                                                    rhs[0:exponent_lo].any()),
                                                                lhs_snan.eq(lhs_nan & ~lhs[quiet_bit]),
                                                                rhs_snan.eq(rhs_nan & ~rhs[quiet_bit]),
                                                                lhs_zero.eq(lhs[0:element_width - 1] == 0),
                                                                rhs_zero.eq(rhs[0:element_width - 1] == 0),
                                                                lhs_lt_rhs.eq(Mux(
                                                                    lhs[element_width - 1] != rhs[element_width - 1],
                                                                    lhs[element_width - 1],
                                                                    Mux(lhs[element_width - 1],
                                                                        lhs[0:element_width - 1] > rhs[0:element_width - 1],
                                                                        lhs[0:element_width - 1] < rhs[0:element_width - 1]))),
                                                                numeric_result.eq(Mux(
                                                                    is_vfmin,
                                                                    Mux(lhs_lt_rhs, lhs, rhs),
                                                                    Mux(lhs_lt_rhs, rhs, lhs))),
                                                                result_element.eq(numeric_result),
                                                                next_element.eq(vregs[
                                                                    IS.rd + reg_offset][lo:hi]),
                                                            ]
                                                            with m.If(lhs_nan & rhs_nan):
                                                                m.d.comb += result_element.eq(
                                                                    C(canonical_nan, element_width))
                                                            with m.Elif(lhs_nan):
                                                                m.d.comb += result_element.eq(rhs)
                                                            with m.Elif(rhs_nan):
                                                                m.d.comb += result_element.eq(lhs)
                                                            with m.Elif(lhs_zero & rhs_zero):
                                                                m.d.comb += result_element.eq(Cat(
                                                                    C(0, element_width - 1),
                                                                    Mux(is_vfmin,
                                                                        lhs[element_width - 1] |
                                                                        rhs[element_width - 1],
                                                                        lhs[element_width - 1] &
                                                                        rhs[element_width - 1])))
                                                            element_enabled = (
                                                                vm | vregs[0][global_element])
                                                            with m.If((csr_vstart <= global_element) &
                                                                      (global_element < csr_vl)):
                                                                with m.If(element_enabled):
                                                                    m.d.comb += next_element.eq(
                                                                        result_element)
                                                                    with m.If(lhs_snan | rhs_snan):
                                                                        m.d.sync += csr_fflags.eq(
                                                                            csr_fflags | 0b10000)
                                                                with m.Elif(csr_vtype[7]):
                                                                    m.d.comb += next_element.eq(
                                                                        C(-1, element_width))
                                                            with m.Elif((global_element >= csr_vl) &
                                                                        (global_element < csr_vlmax) &
                                                                        csr_vtype[6]):
                                                                m.d.comb += next_element.eq(
                                                                    C(-1, element_width))
                                                            vfminmax_elements.append(next_element)
                                                        m.d.comb += vfminmax_reg_data.eq(
                                                            Cat(*vfminmax_elements))
                                            m.d.sync += vregs[
                                                IS.rd + reg_offset].eq(vfminmax_reg_data)
                                m.d.sync += csr_vstart.eq(0)
                        with m.If(is_vmv_x_s | is_vmv_s_x):
                            with m.If(csr_vtype[self.xlen - 1]):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                with m.If(is_vmv_x_s):
                                    vmv_x_data = Signal(self.xlen)
                                    with m.Switch(csr_vtype[3:6]):
                                        with m.Case(0):
                                            m.d.comb += vmv_x_data.eq(Cat(
                                                vregs[IS.rs2][0:8],
                                                Mux(vregs[IS.rs2][7],
                                                    C(-1, self.xlen - 8),
                                                    C(0, self.xlen - 8)),
                                            ))
                                        with m.Case(1):
                                            m.d.comb += vmv_x_data.eq(Cat(
                                                vregs[IS.rs2][0:16],
                                                Mux(vregs[IS.rs2][15],
                                                    C(-1, self.xlen - 16),
                                                    C(0, self.xlen - 16)),
                                            ))
                                        with m.Default():
                                            m.d.comb += vmv_x_data.eq(
                                                vregs[IS.rs2][0:self.xlen])
                                    m.d.comb += [
                                        wb_en.eq(IS.rd != 0),
                                        wb_data.eq(vmv_x_data),
                                    ]
                                with m.Else():
                                    with m.If((csr_vl != 0) & (csr_vstart < csr_vl)):
                                        vmv_s_data = Signal(128)
                                        with m.Switch(csr_vtype[3:6]):
                                            with m.Case(0):
                                                m.d.comb += vmv_s_data.eq(Cat(
                                                    ex1_a[0:8],
                                                    Mux(csr_vtype[6], C(-1, 120),
                                                        vregs[IS.rd][8:128]),
                                                ))
                                            with m.Case(1):
                                                m.d.comb += vmv_s_data.eq(Cat(
                                                    ex1_a[0:16],
                                                    Mux(csr_vtype[6], C(-1, 112),
                                                        vregs[IS.rd][16:128]),
                                                ))
                                            with m.Default():
                                                m.d.comb += vmv_s_data.eq(Cat(
                                                    ex1_a[0:32],
                                                    Mux(csr_vtype[6], C(-1, 96),
                                                        vregs[IS.rd][32:128]),
                                                ))
                                        m.d.sync += vregs[IS.rd].eq(vmv_s_data)
                                m.d.sync += csr_vstart.eq(0)
                        is_whole_move = ((vfunct6 == 0x27) &
                                         (IS.funct3 == 0b011))
                        with m.If(is_whole_move):
                            whole_nreg = Signal(4)
                            whole_count_valid = Signal()
                            whole_evl = Signal(self.xlen)
                            whole_start_byte = Signal(self.xlen)
                            whole_aligned = Signal()
                            m.d.comb += [whole_nreg.eq(0), whole_count_valid.eq(1)]
                            with m.Switch(IS.rs1):
                                with m.Case(0):
                                    m.d.comb += whole_nreg.eq(1)
                                with m.Case(1):
                                    m.d.comb += whole_nreg.eq(2)
                                with m.Case(3):
                                    m.d.comb += whole_nreg.eq(4)
                                with m.Case(7):
                                    m.d.comb += whole_nreg.eq(8)
                                with m.Default():
                                    m.d.comb += whole_count_valid.eq(0)
                            m.d.comb += [
                                whole_aligned.eq(
                                    ((IS.rd & (whole_nreg - 1)) == 0) &
                                    ((IS.rs2 & (whole_nreg - 1)) == 0) &
                                    (IS.rd <= (32 - whole_nreg)) &
                                    (IS.rs2 <= (32 - whole_nreg))
                                ),
                                whole_start_byte.eq(csr_vstart << csr_vtype[3:6]),
                            ]
                            with m.Switch(csr_vtype[3:6]):
                                with m.Case(0):
                                    m.d.comb += whole_evl.eq(whole_nreg << 4)
                                with m.Case(1):
                                    m.d.comb += whole_evl.eq(whole_nreg << 3)
                                with m.Case(2):
                                    m.d.comb += whole_evl.eq(whole_nreg << 2)
                                with m.Default():
                                    m.d.comb += whole_evl.eq(0)
                            with m.If(~vm | ~whole_count_valid | ~whole_aligned |
                                      csr_vtype[self.xlen - 1] | (whole_evl == 0)):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                with m.If(csr_vstart < whole_evl):
                                    for reg_offset in range(8):
                                        with m.If(whole_nreg > reg_offset):
                                            whole_bytes = []
                                            for byte_offset in range(16):
                                                byte_index = reg_offset * 16 + byte_offset
                                                whole_bytes.append(Mux(
                                                    whole_start_byte <= byte_index,
                                                    vregs[IS.rs2 + reg_offset]
                                                         [byte_offset * 8:(byte_offset + 1) * 8],
                                                    vregs[IS.rd + reg_offset]
                                                         [byte_offset * 8:(byte_offset + 1) * 8],
                                                ))
                                            m.d.sync += vregs[IS.rd + reg_offset].eq(
                                                Cat(*whole_bytes))
                                m.d.sync += csr_vstart.eq(0)
                        is_vector_move = ((vfunct6 == 0x17) & vm &
                                          ((IS.funct3 == 0b000) |
                                           (IS.funct3 == 0b100) |
                                           (IS.funct3 == 0b011)))
                        with m.If(is_vector_move):
                            move_group_regs = Signal(4)
                            move_group_aligned = Signal()
                            move_is_vv = IS.funct3 == 0b000
                            move_scalar = Signal(64)
                            if self.xlen < 64:
                                move_scalar_x = Cat(
                                    ex1_a,
                                    Mux(ex1_a[-1],
                                        C(-1, 64 - self.xlen),
                                        C(0, 64 - self.xlen)),
                                )
                            else:
                                move_scalar_x = ex1_a
                            m.d.comb += move_group_regs.eq(1)
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += move_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += move_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += move_group_regs.eq(8)
                            m.d.comb += [
                                move_group_aligned.eq(
                                    ((IS.rd & (move_group_regs - 1)) == 0) &
                                    (~move_is_vv |
                                     ((IS.rs1 & (move_group_regs - 1)) == 0)) &
                                    (IS.rd <= (32 - move_group_regs)) &
                                    (~move_is_vv | (IS.rs1 <= (32 - move_group_regs)))
                                ),
                                move_scalar.eq(Mux(
                                    IS.funct3 == 0b100,
                                    move_scalar_x,
                                    Cat(IS.rs1,
                                        Mux(IS.rs1[4], C(-1, 59), C(0, 59))),
                                )),
                            ]
                            with m.If((IS.rs2 != 0) | ~move_group_aligned |
                                      csr_vtype[self.xlen - 1]):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                with m.If(csr_vstart < csr_vl):
                                    for reg_offset in range(8):
                                        with m.If(move_group_regs > reg_offset):
                                            move_bytes = []
                                            for byte_offset in range(16):
                                                global_byte = reg_offset * 16 + byte_offset
                                                move_byte = Signal(8)
                                                old_byte = vregs[IS.rd + reg_offset][
                                                    byte_offset * 8:(byte_offset + 1) * 8]
                                                vector_byte = vregs[IS.rs1 + reg_offset][
                                                    byte_offset * 8:(byte_offset + 1) * 8]
                                                m.d.comb += move_byte.eq(old_byte)
                                                with m.Switch(csr_vtype[3:6]):
                                                    for vsew, bytes_per_element in enumerate((1, 2, 4, 8)):
                                                        element_index = global_byte // bytes_per_element
                                                        lane = global_byte % bytes_per_element
                                                        scalar_byte = move_scalar[lane * 8:(lane + 1) * 8]
                                                        with m.Case(vsew):
                                                            with m.If((csr_vstart <= element_index) &
                                                                      (element_index < csr_vl)):
                                                                m.d.comb += move_byte.eq(Mux(
                                                                    move_is_vv,
                                                                    vector_byte,
                                                                    scalar_byte,
                                                                ))
                                                            with m.Elif((element_index >= csr_vl) &
                                                                        (element_index < csr_vlmax) &
                                                                        csr_vtype[6]):
                                                                m.d.comb += move_byte.eq(0xFF)
                                                move_bytes.append(move_byte)
                                            m.d.sync += vregs[IS.rd + reg_offset].eq(
                                                Cat(*move_bytes))
                                m.d.sync += csr_vstart.eq(0)
                        is_vmerge = ((vfunct6 == 0x17) & ~vm &
                                     ((IS.funct3 == 0b000) |
                                      (IS.funct3 == 0b100) |
                                      (IS.funct3 == 0b011)))
                        with m.If(is_vmerge):
                            merge_group_regs = Signal(4)
                            merge_group_aligned = Signal()
                            merge_is_vv = IS.funct3 == 0b000
                            merge_scalar = Signal(self.xlen)
                            m.d.comb += merge_group_regs.eq(1)
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += merge_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += merge_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += merge_group_regs.eq(8)
                            m.d.comb += [
                                merge_group_aligned.eq(
                                    (IS.rd != 0) &
                                    ((IS.rd & (merge_group_regs - 1)) == 0) &
                                    ((IS.rs2 & (merge_group_regs - 1)) == 0) &
                                    (~merge_is_vv |
                                     ((IS.rs1 & (merge_group_regs - 1)) == 0)) &
                                    (IS.rd <= (32 - merge_group_regs)) &
                                    (IS.rs2 <= (32 - merge_group_regs)) &
                                    (~merge_is_vv |
                                     (IS.rs1 <= (32 - merge_group_regs)))
                                ),
                                merge_scalar.eq(Mux(
                                    IS.funct3 == 0b100,
                                    ex1_a,
                                    Cat(IS.rs1,
                                        Mux(IS.rs1[4], C(-1, self.xlen - 5),
                                            C(0, self.xlen - 5))),
                                )),
                            ]
                            with m.If(~merge_group_aligned |
                                      csr_vtype[self.xlen - 1]):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                with m.If(csr_vstart < csr_vl):
                                    for reg_offset in range(8):
                                        with m.If(merge_group_regs > reg_offset):
                                            merge_bytes = []
                                            for byte_offset in range(16):
                                                global_byte = reg_offset * 16 + byte_offset
                                                merge_byte = Signal(8)
                                                old_byte = vregs[IS.rd + reg_offset][
                                                    byte_offset * 8:(byte_offset + 1) * 8]
                                                source_byte = vregs[IS.rs2 + reg_offset][
                                                    byte_offset * 8:(byte_offset + 1) * 8]
                                                vector_byte = vregs[IS.rs1 + reg_offset][
                                                    byte_offset * 8:(byte_offset + 1) * 8]
                                                m.d.comb += merge_byte.eq(old_byte)
                                                with m.Switch(csr_vtype[3:6]):
                                                    for vsew, bytes_per_element in enumerate((1, 2, 4)):
                                                        element_index = global_byte // bytes_per_element
                                                        lane = global_byte % bytes_per_element
                                                        scalar_byte = merge_scalar[
                                                            lane * 8:(lane + 1) * 8]
                                                        with m.Case(vsew):
                                                            with m.If((csr_vstart <= element_index) &
                                                                      (element_index < csr_vl)):
                                                                m.d.comb += merge_byte.eq(Mux(
                                                                    vregs[0][element_index],
                                                                    Mux(merge_is_vv,
                                                                        vector_byte,
                                                                        scalar_byte),
                                                                    source_byte,
                                                                ))
                                                            with m.Elif((element_index >= csr_vl) &
                                                                        (element_index < csr_vlmax) &
                                                                        csr_vtype[6]):
                                                                m.d.comb += merge_byte.eq(0xFF)
                                                merge_bytes.append(merge_byte)
                                            m.d.sync += vregs[IS.rd + reg_offset].eq(
                                                Cat(*merge_bytes))
                                m.d.sync += csr_vstart.eq(0)
                        is_vadd = ((vfunct6 == 0x00) &
                                   ((IS.funct3 == 0b000) |
                                    (IS.funct3 == 0b100) |
                                    (IS.funct3 == 0b011)))
                        is_vsub = ((vfunct6 == 0x02) &
                                   ((IS.funct3 == 0b000) |
                                    (IS.funct3 == 0b100)))
                        is_vrsub = ((vfunct6 == 0x03) &
                                    ((IS.funct3 == 0b100) |
                                     (IS.funct3 == 0b011)))
                        is_vand = ((vfunct6 == 0x09) &
                                   ((IS.funct3 == 0b000) |
                                    (IS.funct3 == 0b100) |
                                    (IS.funct3 == 0b011)))
                        is_vor = ((vfunct6 == 0x0A) &
                                  ((IS.funct3 == 0b000) |
                                   (IS.funct3 == 0b100) |
                                   (IS.funct3 == 0b011)))
                        is_vxor = ((vfunct6 == 0x0B) &
                                   ((IS.funct3 == 0b000) |
                                    (IS.funct3 == 0b100) |
                                    (IS.funct3 == 0b011)))
                        is_vminu = ((vfunct6 == 0x04) &
                                    ((IS.funct3 == 0b000) |
                                     (IS.funct3 == 0b100)))
                        is_vmin = ((vfunct6 == 0x05) &
                                   ((IS.funct3 == 0b000) |
                                    (IS.funct3 == 0b100)))
                        is_vmaxu = ((vfunct6 == 0x06) &
                                    ((IS.funct3 == 0b000) |
                                     (IS.funct3 == 0b100)))
                        is_vmax = ((vfunct6 == 0x07) &
                                   ((IS.funct3 == 0b000) |
                                    (IS.funct3 == 0b100)))
                        is_vsll = ((vfunct6 == 0x25) &
                                   ((IS.funct3 == 0b000) |
                                    (IS.funct3 == 0b100) |
                                    (IS.funct3 == 0b011)))
                        is_vsrl = ((vfunct6 == 0x28) &
                                   ((IS.funct3 == 0b000) |
                                    (IS.funct3 == 0b100) |
                                    (IS.funct3 == 0b011)))
                        is_vsra = ((vfunct6 == 0x29) &
                                   ((IS.funct3 == 0b000) |
                                    (IS.funct3 == 0b100) |
                                    (IS.funct3 == 0b011)))
                        is_vssrl = ((vfunct6 == 0x2A) &
                                    ((IS.funct3 == 0b000) |
                                     (IS.funct3 == 0b100) |
                                     (IS.funct3 == 0b011)))
                        is_vssra = ((vfunct6 == 0x2B) &
                                    ((IS.funct3 == 0b000) |
                                     (IS.funct3 == 0b100) |
                                     (IS.funct3 == 0b011)))
                        is_vsaddu = ((vfunct6 == 0x20) &
                                     ((IS.funct3 == 0b000) |
                                      (IS.funct3 == 0b100) |
                                      (IS.funct3 == 0b011)))
                        is_vsadd = ((vfunct6 == 0x21) &
                                    ((IS.funct3 == 0b000) |
                                     (IS.funct3 == 0b100) |
                                     (IS.funct3 == 0b011)))
                        is_vssubu = ((vfunct6 == 0x22) &
                                     ((IS.funct3 == 0b000) |
                                      (IS.funct3 == 0b100)))
                        is_vssub = ((vfunct6 == 0x23) &
                                    ((IS.funct3 == 0b000) |
                                     (IS.funct3 == 0b100)))
                        with m.If(is_vadd | is_vsub | is_vrsub |
                                  is_vand | is_vor | is_vxor |
                                  is_vminu | is_vmin | is_vmaxu | is_vmax |
                                  is_vsll | is_vsrl | is_vsra | is_vssrl | is_vssra |
                                  is_vsaddu | is_vsadd | is_vssubu | is_vssub):
                            arith_group_regs = Signal(4)
                            arith_is_vv = IS.funct3 == 0b000
                            arith_scalar = Signal(self.xlen)
                            arith_group_aligned = Signal()
                            m.d.comb += arith_group_regs.eq(1)
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += arith_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += arith_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += arith_group_regs.eq(8)
                            m.d.comb += [
                                arith_scalar.eq(Mux(
                                    IS.funct3 == 0b100,
                                    ex1_a,
                                    Cat(IS.rs1,
                                        Mux(IS.rs1[4], C(-1, self.xlen - 5),
                                            C(0, self.xlen - 5))),
                                )),
                                arith_group_aligned.eq(
                                    ((IS.rd & (arith_group_regs - 1)) == 0) &
                                    ((IS.rs2 & (arith_group_regs - 1)) == 0) &
                                    (~arith_is_vv |
                                     ((IS.rs1 & (arith_group_regs - 1)) == 0)) &
                                    (IS.rd <= (32 - arith_group_regs)) &
                                    (IS.rs2 <= (32 - arith_group_regs)) &
                                    (~arith_is_vv |
                                     (IS.rs1 <= (32 - arith_group_regs)))
                                ),
                            ]
                            with m.If(~arith_group_aligned |
                                      csr_vtype[self.xlen - 1]):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                with m.If(csr_vstart < csr_vl):
                                    for reg_offset in range(8):
                                        with m.If(arith_group_regs > reg_offset):
                                            arith_reg_data = Signal(128)
                                            m.d.comb += arith_reg_data.eq(
                                                vregs[IS.rd + reg_offset])
                                            with m.Switch(csr_vtype[3:6]):
                                                for vsew, element_width in enumerate((8, 16, 32)):
                                                    with m.Case(vsew):
                                                        arith_elements = []
                                                        element_count = 128 // element_width
                                                        for element_offset in range(element_count):
                                                            global_element = (reg_offset * element_count +
                                                                              element_offset)
                                                            lo = element_offset * element_width
                                                            hi = lo + element_width
                                                            old_element = vregs[IS.rd + reg_offset][lo:hi]
                                                            vs2_element = vregs[IS.rs2 + reg_offset][lo:hi]
                                                            vs1_element = vregs[IS.rs1 + reg_offset][lo:hi]
                                                            scalar_element = arith_scalar[0:element_width]
                                                            operand1 = Mux(arith_is_vv,
                                                                           vs1_element,
                                                                           scalar_element)
                                                            result_element = Signal(element_width)
                                                            next_element = Signal(element_width)
                                                            saturates = Signal()
                                                            unsigned_sum = Signal(element_width + 1)
                                                            signed_sum = Signal(element_width)
                                                            signed_diff = Signal(element_width)
                                                            signed_max = C((1 << (element_width - 1)) - 1,
                                                                           element_width)
                                                            signed_min = C(1 << (element_width - 1),
                                                                           element_width)
                                                            m.d.comb += [
                                                                saturates.eq(0),
                                                                unsigned_sum.eq(
                                                                    Cat(vs2_element, C(0, 1)) +
                                                                    Cat(operand1, C(0, 1))),
                                                                signed_sum.eq(vs2_element + operand1),
                                                                signed_diff.eq(vs2_element - operand1),
                                                            ]
                                                            m.d.comb += result_element.eq(
                                                                vs2_element + operand1)
                                                            with m.If(is_vsub):
                                                                m.d.comb += result_element.eq(
                                                                    vs2_element - operand1)
                                                            with m.Elif(is_vrsub):
                                                                m.d.comb += result_element.eq(
                                                                    operand1 - vs2_element)
                                                            with m.Elif(is_vand):
                                                                m.d.comb += result_element.eq(
                                                                    vs2_element & operand1)
                                                            with m.Elif(is_vor):
                                                                m.d.comb += result_element.eq(
                                                                    vs2_element | operand1)
                                                            with m.Elif(is_vxor):
                                                                m.d.comb += result_element.eq(
                                                                    vs2_element ^ operand1)
                                                            with m.Elif(is_vminu):
                                                                m.d.comb += result_element.eq(Mux(
                                                                    vs2_element < operand1,
                                                                    vs2_element, operand1))
                                                            with m.Elif(is_vmin):
                                                                m.d.comb += result_element.eq(Mux(
                                                                    vs2_element.as_signed() <
                                                                    operand1.as_signed(),
                                                                    vs2_element, operand1))
                                                            with m.Elif(is_vmaxu):
                                                                m.d.comb += result_element.eq(Mux(
                                                                    vs2_element > operand1,
                                                                    vs2_element, operand1))
                                                            with m.Elif(is_vmax):
                                                                m.d.comb += result_element.eq(Mux(
                                                                    vs2_element.as_signed() >
                                                                    operand1.as_signed(),
                                                                    vs2_element, operand1))
                                                            with m.Elif(is_vsll):
                                                                shift_bits = {8: 3, 16: 4, 32: 5}[element_width]
                                                                m.d.comb += result_element.eq(
                                                                    vs2_element <<
                                                                    operand1[0:shift_bits])
                                                            with m.Elif(is_vsrl):
                                                                shift_bits = {8: 3, 16: 4, 32: 5}[element_width]
                                                                m.d.comb += result_element.eq(
                                                                    vs2_element >>
                                                                    operand1[0:shift_bits])
                                                            with m.Elif(is_vsra):
                                                                shift_bits = {8: 3, 16: 4, 32: 5}[element_width]
                                                                m.d.comb += result_element.eq(
                                                                    vs2_element.as_signed() >>
                                                                    operand1[0:shift_bits])
                                                            with m.Elif(is_vssrl | is_vssra):
                                                                shift_bits = {8: 3, 16: 4, 32: 5}[element_width]
                                                                rounded_shift_amount = operand1[0:shift_bits]
                                                                rounded_shifted = Signal(element_width)
                                                                rounded_discard_mask = Signal(element_width)
                                                                rounded_remainder = Signal(element_width)
                                                                rounded_half = Signal(element_width)
                                                                rounded_increment = Signal()
                                                                m.d.comb += [
                                                                    rounded_shifted.eq(Mux(
                                                                        is_vssra,
                                                                        vs2_element.as_signed() >>
                                                                        rounded_shift_amount,
                                                                        vs2_element >> rounded_shift_amount)),
                                                                    rounded_discard_mask.eq(Mux(
                                                                        rounded_shift_amount == 0,
                                                                        0,
                                                                        (C(1, element_width) <<
                                                                         rounded_shift_amount) - 1)),
                                                                    rounded_remainder.eq(
                                                                        vs2_element & rounded_discard_mask),
                                                                    rounded_half.eq(0),
                                                                    rounded_increment.eq(0),
                                                                ]
                                                                with m.If(rounded_shift_amount != 0):
                                                                    m.d.comb += rounded_half.eq(
                                                                        C(1, element_width) <<
                                                                        (rounded_shift_amount - 1).as_unsigned())
                                                                    with m.Switch(csr_vxrm):
                                                                        with m.Case(0):
                                                                            m.d.comb += rounded_increment.eq(
                                                                                (rounded_remainder &
                                                                                 rounded_half) != 0)
                                                                        with m.Case(1):
                                                                            m.d.comb += rounded_increment.eq(
                                                                                ((rounded_remainder &
                                                                                  rounded_half) != 0) &
                                                                                (((rounded_remainder &
                                                                                   (rounded_half - 1)) != 0) |
                                                                                 rounded_shifted[0]))
                                                                        with m.Case(2):
                                                                            m.d.comb += rounded_increment.eq(0)
                                                                        with m.Case(3):
                                                                            m.d.comb += rounded_increment.eq(
                                                                                ~rounded_shifted[0] &
                                                                                (rounded_remainder != 0))
                                                                m.d.comb += result_element.eq(
                                                                    rounded_shifted + rounded_increment)
                                                            with m.Elif(is_vsaddu):
                                                                m.d.comb += [
                                                                    saturates.eq(unsigned_sum[element_width]),
                                                                    result_element.eq(Mux(
                                                                        unsigned_sum[element_width],
                                                                        C(-1, element_width),
                                                                        unsigned_sum[:element_width])),
                                                                ]
                                                            with m.Elif(is_vsadd):
                                                                signed_add_overflow = (
                                                                    ~(vs2_element[element_width - 1] ^
                                                                      operand1[element_width - 1]) &
                                                                    (signed_sum[element_width - 1] ^
                                                                     vs2_element[element_width - 1]))
                                                                m.d.comb += [
                                                                    saturates.eq(signed_add_overflow),
                                                                    result_element.eq(Mux(
                                                                        signed_add_overflow,
                                                                        Mux(vs2_element[element_width - 1],
                                                                            signed_min, signed_max),
                                                                        signed_sum)),
                                                                ]
                                                            with m.Elif(is_vssubu):
                                                                m.d.comb += [
                                                                    saturates.eq(vs2_element < operand1),
                                                                    result_element.eq(Mux(
                                                                        vs2_element < operand1,
                                                                        0, vs2_element - operand1)),
                                                                ]
                                                            with m.Elif(is_vssub):
                                                                signed_sub_overflow = (
                                                                    (vs2_element[element_width - 1] ^
                                                                     operand1[element_width - 1]) &
                                                                    (signed_diff[element_width - 1] ^
                                                                     vs2_element[element_width - 1]))
                                                                m.d.comb += [
                                                                    saturates.eq(signed_sub_overflow),
                                                                    result_element.eq(Mux(
                                                                        signed_sub_overflow,
                                                                        Mux(vs2_element[element_width - 1],
                                                                            signed_min, signed_max),
                                                                        signed_diff)),
                                                                ]
                                                            m.d.comb += next_element.eq(old_element)
                                                            element_enabled = (vm |
                                                                               vregs[0][global_element])
                                                            with m.If((csr_vstart <= global_element) &
                                                                      (global_element < csr_vl)):
                                                                with m.If(element_enabled):
                                                                    m.d.comb += next_element.eq(
                                                                        result_element)
                                                                    with m.If(saturates):
                                                                        m.d.sync += csr_vxsat.eq(1)
                                                                with m.Elif(csr_vtype[7]):
                                                                    m.d.comb += next_element.eq(
                                                                        C(-1, element_width))
                                                            with m.Elif((global_element >= csr_vl) &
                                                                        (global_element < csr_vlmax) &
                                                                        csr_vtype[6]):
                                                                m.d.comb += next_element.eq(
                                                                    C(-1, element_width))
                                                            arith_elements.append(next_element)
                                                        m.d.comb += arith_reg_data.eq(
                                                            Cat(*arith_elements))
                                            m.d.sync += vregs[IS.rd + reg_offset].eq(
                                                arith_reg_data)
                                m.d.sync += csr_vstart.eq(0)
                        is_vaaddu = ((vfunct6 == 0x08) &
                                     ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vaadd = ((vfunct6 == 0x09) &
                                    ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vasubu = ((vfunct6 == 0x0A) &
                                     ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vasub = ((vfunct6 == 0x0B) &
                                    ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        with m.If(is_vaaddu | is_vaadd | is_vasubu | is_vasub):
                            avg_group_regs = Signal(4)
                            avg_is_vv = IS.funct3 == 0b010
                            avg_group_aligned = Signal()
                            m.d.comb += avg_group_regs.eq(1)
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += avg_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += avg_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += avg_group_regs.eq(8)
                            m.d.comb += avg_group_aligned.eq(
                                (csr_vtype[0:3] != 4) &
                                ((IS.rd & (avg_group_regs - 1)) == 0) &
                                ((IS.rs2 & (avg_group_regs - 1)) == 0) &
                                (~avg_is_vv | ((IS.rs1 & (avg_group_regs - 1)) == 0)) &
                                (IS.rd <= (32 - avg_group_regs)) &
                                (IS.rs2 <= (32 - avg_group_regs)) &
                                (~avg_is_vv | (IS.rs1 <= (32 - avg_group_regs))))
                            with m.If(~avg_group_aligned | csr_vtype[self.xlen - 1]):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                with m.If(csr_vstart < csr_vl):
                                    for reg_offset in range(8):
                                        with m.If(avg_group_regs > reg_offset):
                                            avg_reg_data = Signal(128)
                                            m.d.comb += avg_reg_data.eq(vregs[IS.rd + reg_offset])
                                            with m.Switch(csr_vtype[3:6]):
                                                for vsew, element_width in enumerate((8, 16, 32)):
                                                    with m.Case(vsew):
                                                        avg_elements = []
                                                        element_count = 128 // element_width
                                                        for element_offset in range(element_count):
                                                            global_element = (reg_offset * element_count +
                                                                              element_offset)
                                                            lo = element_offset * element_width
                                                            hi = lo + element_width
                                                            old_element = vregs[IS.rd + reg_offset][lo:hi]
                                                            lhs = vregs[IS.rs2 + reg_offset][lo:hi]
                                                            vector_rhs = vregs[IS.rs1 + reg_offset][lo:hi]
                                                            rhs = Mux(avg_is_vv, vector_rhs,
                                                                      ex1_a[:element_width])
                                                            avg_pre = Signal(element_width + 1)
                                                            avg_increment = Signal()
                                                            avg_shifted = Signal(element_width + 1)
                                                            avg_result = Signal(element_width)
                                                            next_element = Signal(element_width)
                                                            with m.If(is_vaaddu):
                                                                m.d.comb += avg_pre.eq(
                                                                    Cat(lhs, C(0, 1)) +
                                                                    Cat(rhs, C(0, 1)))
                                                            with m.Elif(is_vaadd):
                                                                m.d.comb += avg_pre.eq(
                                                                    Cat(lhs, lhs[element_width - 1]) +
                                                                    Cat(rhs, rhs[element_width - 1]))
                                                            with m.Elif(is_vasubu):
                                                                m.d.comb += avg_pre.eq(
                                                                    Cat(lhs, C(0, 1)) -
                                                                    Cat(rhs, C(0, 1)))
                                                            with m.Else():
                                                                m.d.comb += avg_pre.eq(
                                                                    Cat(lhs, lhs[element_width - 1]) -
                                                                    Cat(rhs, rhs[element_width - 1]))
                                                            with m.Switch(csr_vxrm):
                                                                with m.Case(0):
                                                                    m.d.comb += avg_increment.eq(avg_pre[0])
                                                                with m.Case(1):
                                                                    m.d.comb += avg_increment.eq(
                                                                        avg_pre[0] & avg_pre[1])
                                                                with m.Case(2):
                                                                    m.d.comb += avg_increment.eq(0)
                                                                with m.Case(3):
                                                                    m.d.comb += avg_increment.eq(
                                                                        avg_pre[0] & ~avg_pre[1])
                                                            m.d.comb += [
                                                                avg_shifted.eq(Mux(
                                                                    is_vaadd | is_vasub,
                                                                    avg_pre.as_signed() >> 1,
                                                                    avg_pre >> 1)),
                                                                avg_result.eq(avg_shifted[:element_width] +
                                                                              avg_increment),
                                                                next_element.eq(old_element),
                                                            ]
                                                            element_enabled = vm | vregs[0][global_element]
                                                            with m.If((csr_vstart <= global_element) &
                                                                      (global_element < csr_vl)):
                                                                with m.If(element_enabled):
                                                                    m.d.comb += next_element.eq(avg_result)
                                                                with m.Elif(csr_vtype[7]):
                                                                    m.d.comb += next_element.eq(
                                                                        C(-1, element_width))
                                                            with m.Elif((global_element >= csr_vl) &
                                                                        (global_element < csr_vlmax) &
                                                                        csr_vtype[6]):
                                                                m.d.comb += next_element.eq(
                                                                    C(-1, element_width))
                                                            avg_elements.append(next_element)
                                                        m.d.comb += avg_reg_data.eq(Cat(*avg_elements))
                                            m.d.sync += vregs[IS.rd + reg_offset].eq(avg_reg_data)
                                m.d.sync += csr_vstart.eq(0)
                        is_vredsum = ((vfunct6 == 0x00) & (IS.funct3 == 0b010))
                        is_vredand = ((vfunct6 == 0x01) & (IS.funct3 == 0b010))
                        is_vredor = ((vfunct6 == 0x02) & (IS.funct3 == 0b010))
                        is_vredxor = ((vfunct6 == 0x03) & (IS.funct3 == 0b010))
                        is_vredminu = ((vfunct6 == 0x04) & (IS.funct3 == 0b010))
                        is_vredmin = ((vfunct6 == 0x05) & (IS.funct3 == 0b010))
                        is_vredmaxu = ((vfunct6 == 0x06) & (IS.funct3 == 0b010))
                        is_vredmax = ((vfunct6 == 0x07) & (IS.funct3 == 0b010))
                        with m.If(is_vredsum | is_vredand | is_vredor | is_vredxor |
                                  is_vredminu | is_vredmin | is_vredmaxu | is_vredmax):
                            reduce_group_regs = Signal(4)
                            reduce_group_legal = Signal()
                            m.d.comb += reduce_group_regs.eq(1)
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += reduce_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += reduce_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += reduce_group_regs.eq(8)
                            m.d.comb += reduce_group_legal.eq(
                                ~csr_vtype[self.xlen - 1] &
                                (csr_vstart == 0) &
                                (csr_vtype[0:3] != 4) &
                                ((IS.rs2 & (reduce_group_regs - 1)) == 0) &
                                (IS.rs2 <= (32 - reduce_group_regs)))
                            with m.If(~reduce_group_legal):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                reduce_dest_data = Signal(128)
                                m.d.comb += reduce_dest_data.eq(vregs[IS.rd])
                                with m.Switch(csr_vtype[3:6]):
                                    for vsew, element_width in enumerate((8, 16, 32)):
                                        with m.Case(vsew):
                                            reduce_identity = Signal(element_width)
                                            m.d.comb += reduce_identity.eq(Mux(
                                                is_vredand | is_vredminu,
                                                C(-1, element_width),
                                                Mux(is_vredmin,
                                                    C((1 << (element_width - 1)) - 1,
                                                      element_width),
                                                    Mux(is_vredmax,
                                                        C(1 << (element_width - 1),
                                                          element_width),
                                                        C(0, element_width)))))

                                            def reduce_pair(left, right):
                                                return Mux(
                                                    is_vredsum, left + right,
                                                    Mux(is_vredand, left & right,
                                                        Mux(is_vredor, left | right,
                                                            Mux(is_vredxor, left ^ right,
                                                                Mux(is_vredminu,
                                                                    Mux(left < right,
                                                                        left, right),
                                                                    Mux(is_vredmin,
                                                                        Mux(left.as_signed() <
                                                                            right.as_signed(),
                                                                            left, right),
                                                                        Mux(is_vredmaxu,
                                                                            Mux(left > right,
                                                                                left, right),
                                                                            Mux(left.as_signed() >
                                                                                right.as_signed(),
                                                                                left, right))))))))

                                            reduce_terms = []
                                            elements_per_reg = 128 // element_width
                                            for reg_offset in range(8):
                                                for element_offset in range(elements_per_reg):
                                                    global_element = (reg_offset *
                                                                      elements_per_reg +
                                                                      element_offset)
                                                    lo = element_offset * element_width
                                                    hi = lo + element_width
                                                    source_element = vregs[
                                                        IS.rs2 + reg_offset][lo:hi]
                                                    element_active = (
                                                        (reduce_group_regs > reg_offset) &
                                                        (global_element < csr_vl) &
                                                        (vm | vregs[0][global_element]))
                                                    reduce_term = Signal(element_width)
                                                    m.d.comb += reduce_term.eq(Mux(
                                                        element_active,
                                                        source_element,
                                                        reduce_identity))
                                                    reduce_terms.append(reduce_term)
                                            while len(reduce_terms) > 1:
                                                next_terms = []
                                                for term in range(0, len(reduce_terms), 2):
                                                    pair_value = Signal(element_width)
                                                    if term + 1 < len(reduce_terms):
                                                        m.d.comb += pair_value.eq(reduce_pair(
                                                            reduce_terms[term],
                                                            reduce_terms[term + 1]))
                                                    else:
                                                        m.d.comb += pair_value.eq(
                                                            reduce_terms[term])
                                                    next_terms.append(pair_value)
                                                reduce_terms = next_terms
                                            reduce_result = Signal(element_width)
                                            m.d.comb += reduce_result.eq(reduce_pair(
                                                vregs[IS.rs1][0:element_width],
                                                reduce_terms[0]))
                                            reduce_elements = [reduce_result]
                                            for element_offset in range(
                                                    1, elements_per_reg):
                                                lo = element_offset * element_width
                                                hi = lo + element_width
                                                reduce_elements.append(Mux(
                                                    csr_vtype[6],
                                                    C(-1, element_width),
                                                    vregs[IS.rd][lo:hi]))
                                            m.d.comb += reduce_dest_data.eq(
                                                Cat(*reduce_elements))
                                with m.If(csr_vl != 0):
                                    m.d.sync += vregs[IS.rd].eq(
                                        reduce_dest_data)
                                m.d.sync += csr_vstart.eq(0)
                        is_vzext = ((vfunct6 == 0x12) &
                                    (IS.funct3 == 0b010) &
                                    ((IS.rs1 == 2) | (IS.rs1 == 4) |
                                     (IS.rs1 == 6)))
                        is_vsext = ((vfunct6 == 0x12) &
                                    (IS.funct3 == 0b010) &
                                    ((IS.rs1 == 3) | (IS.rs1 == 5) |
                                     (IS.rs1 == 7)))
                        with m.If(is_vzext | is_vsext):
                            vext_factor = Signal(4)
                            vext_dest_regs = Signal(4)
                            vext_source_regs = Signal(4)
                            vext_source_emul_ge1 = Signal()
                            m.d.comb += [
                                vext_factor.eq(Mux(IS.rs1[1:3] == 1, 8,
                                                 Mux(IS.rs1[1:3] == 2, 4, 2))),
                                vext_dest_regs.eq(1),
                            ]
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += vext_dest_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += vext_dest_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += vext_dest_regs.eq(8)
                            m.d.comb += [
                                vext_source_regs.eq(Mux(
                                    vext_factor == 2,
                                    Mux(vext_dest_regs > 2,
                                        vext_dest_regs >> 1, 1),
                                    Mux(vext_factor == 4,
                                        Mux(vext_dest_regs > 4,
                                            vext_dest_regs >> 2, 1),
                                        Mux(vext_dest_regs > 8,
                                            vext_dest_regs >> 3, 1)))),
                                vext_source_emul_ge1.eq(
                                    vext_dest_regs >= vext_factor),
                            ]
                            vext_width_legal = (
                                ((vext_factor == 2) & (csr_vtype[3:6] >= 1)) |
                                ((vext_factor == 4) & (csr_vtype[3:6] >= 2)) |
                                ((vext_factor == 8) & (csr_vtype[3:6] >= 3)))
                            vext_emul_legal = (
                                ((vext_factor == 2) & (csr_vtype[0:3] != 5)) |
                                ((vext_factor == 4) &
                                 ((csr_vtype[0:3] == 0) |
                                  (csr_vtype[0:3] == 1) |
                                  (csr_vtype[0:3] == 2) |
                                  (csr_vtype[0:3] == 3) |
                                  (csr_vtype[0:3] == 7))) |
                                ((vext_factor == 8) &
                                 (csr_vtype[0:3] <= 3)))
                            vext_overlap = (
                                (IS.rd < (IS.rs2 + vext_source_regs)) &
                                (IS.rs2 < (IS.rd + vext_dest_regs)))
                            vext_overlap_legal = (
                                ~vext_overlap |
                                (vext_source_emul_ge1 &
                                 (IS.rs2 == (IS.rd + vext_dest_regs -
                                             vext_source_regs))))
                            vext_group_legal = (
                                (csr_vtype[0:3] != 4) &
                                ((IS.rd & (vext_dest_regs - 1)) == 0) &
                                ((IS.rs2 & (vext_source_regs - 1)) == 0) &
                                (IS.rd <= (32 - vext_dest_regs)) &
                                (IS.rs2 <= (32 - vext_source_regs)) &
                                vext_overlap_legal &
                                (vm | (IS.rd != 0)))
                            with m.If(csr_vtype[self.xlen - 1] |
                                      ~vext_width_legal |
                                      ~vext_emul_legal |
                                      ~vext_group_legal):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                for reg_offset in range(8):
                                    with m.If(vext_dest_regs > reg_offset):
                                        vext_dest_data = Signal(128)
                                        m.d.comb += vext_dest_data.eq(
                                            vregs[IS.rd + reg_offset])
                                        with m.Switch(csr_vtype[3:6]):
                                            for vsew, dest_width in (
                                                    (1, 16), (2, 32), (3, 64)):
                                                with m.Case(vsew):
                                                    for factor in (2, 4, 8):
                                                        source_width = dest_width // factor
                                                        if source_width < 8:
                                                            continue
                                                        with m.If(vext_factor == factor):
                                                            elements = []
                                                            elements_per_dest = 128 // dest_width
                                                            elements_per_source = 128 // source_width
                                                            for element_offset in range(
                                                                    elements_per_dest):
                                                                global_element = (
                                                                    reg_offset * elements_per_dest +
                                                                    element_offset)
                                                                source_reg_offset = (
                                                                    global_element //
                                                                    elements_per_source)
                                                                source_element_offset = (
                                                                    global_element %
                                                                    elements_per_source)
                                                                source_lo = (
                                                                    source_element_offset *
                                                                    source_width)
                                                                source_hi = source_lo + source_width
                                                                source = vregs[
                                                                    IS.rs2 + source_reg_offset][
                                                                        source_lo:source_hi]
                                                                extended = Signal(dest_width)
                                                                m.d.comb += extended.eq(Mux(
                                                                    is_vsext,
                                                                    Cat(source, *([
                                                                        source[source_width - 1]] *
                                                                        (dest_width - source_width))),
                                                                    Cat(source, C(0,
                                                                        dest_width - source_width))))
                                                                dest_lo = (
                                                                    element_offset * dest_width)
                                                                dest_hi = dest_lo + dest_width
                                                                next_element = Signal(dest_width)
                                                                m.d.comb += next_element.eq(
                                                                    vregs[IS.rd + reg_offset][
                                                                        dest_lo:dest_hi])
                                                                enabled = (
                                                                    vm | vregs[0][global_element])
                                                                with m.If(
                                                                        (csr_vstart <= global_element) &
                                                                        (global_element < csr_vl)):
                                                                    with m.If(enabled):
                                                                        m.d.comb += next_element.eq(
                                                                            extended)
                                                                    with m.Elif(csr_vtype[7]):
                                                                        m.d.comb += next_element.eq(
                                                                            C(-1, dest_width))
                                                                with m.Elif(
                                                                        (global_element >= csr_vl) &
                                                                        (global_element < csr_vlmax) &
                                                                        csr_vtype[6]):
                                                                    m.d.comb += next_element.eq(
                                                                        C(-1, dest_width))
                                                                elements.append(next_element)
                                                            m.d.comb += vext_dest_data.eq(
                                                                Cat(*elements))
                                        m.d.sync += vregs[
                                            IS.rd + reg_offset].eq(vext_dest_data)
                                m.d.sync += csr_vstart.eq(0)

                        is_vfcvt = ((vfunct6 == 0x12) &
                                     (IS.funct3 == 0b001))
                        with m.If(is_vfcvt):
                            with m.If(vfcvt_pipe.issue_ready):
                                m.d.comb += [
                                    vfcvt_pipe.issue_valid.eq(1),
                                    vfcvt_pipe.insn.eq(Cat(
                                        C(0x57, 7), IS.rd, IS.funct3, IS.rs1,
                                        IS.rs2, vm, vfunct6)),
                                ]
                                with m.If(vfcvt_pipe.illegal):
                                    m.d.comb += self.trap.eq(1)
                                with m.Elif(vfcvt_pipe.redirect):
                                    m.d.comb += [
                                        redirect.eq(1),
                                        redirect_pc.eq(IS.pc + 4),
                                    ]

                        is_vmvnr = ((vfunct6 == 0x27) &
                                    (IS.funct3 == 0b011))
                        with m.If(is_vmvnr):
                            vmvnr_nregs = Signal(4)
                            m.d.comb += vmvnr_nregs.eq(0)
                            with m.Switch(IS.rs1):
                                with m.Case(0):
                                    m.d.comb += vmvnr_nregs.eq(1)
                                with m.Case(1):
                                    m.d.comb += vmvnr_nregs.eq(2)
                                with m.Case(3):
                                    m.d.comb += vmvnr_nregs.eq(4)
                                with m.Case(7):
                                    m.d.comb += vmvnr_nregs.eq(8)
                            vmvnr_legal = (
                                ~csr_vtype[self.xlen - 1] &
                                (csr_vtype[3:6] <= 3) &
                                vm & (vmvnr_nregs != 0) &
                                ((IS.rd & (vmvnr_nregs - 1)) == 0) &
                                ((IS.rs2 & (vmvnr_nregs - 1)) == 0) &
                                (IS.rd <= (32 - vmvnr_nregs)) &
                                (IS.rs2 <= (32 - vmvnr_nregs)))
                            with m.If(~vmvnr_legal):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                for reg_offset in range(8):
                                    with m.If(vmvnr_nregs > reg_offset):
                                        vmvnr_dest_data = Signal(128)
                                        m.d.comb += vmvnr_dest_data.eq(
                                            vregs[IS.rd + reg_offset])
                                        with m.Switch(csr_vtype[3:6]):
                                            for vsew, element_width in (
                                                    (0, 8), (1, 16),
                                                    (2, 32), (3, 64)):
                                                with m.Case(vsew):
                                                    elements = []
                                                    elements_per_reg = 128 // element_width
                                                    for element_offset in range(
                                                            elements_per_reg):
                                                        lo = element_offset * element_width
                                                        hi = lo + element_width
                                                        global_element = (
                                                            reg_offset * elements_per_reg +
                                                            element_offset)
                                                        elements.append(Mux(
                                                            csr_vstart <= global_element,
                                                            vregs[IS.rs2 + reg_offset][lo:hi],
                                                            vregs[IS.rd + reg_offset][lo:hi]))
                                                    m.d.comb += vmvnr_dest_data.eq(
                                                        Cat(*elements))
                                        m.d.sync += vregs[
                                            IS.rd + reg_offset].eq(vmvnr_dest_data)
                                m.d.sync += csr_vstart.eq(0)

                        is_vfredusum = ((vfunct6 == 0x01) &
                                        (IS.funct3 == 0b001))
                        is_vfredosum = ((vfunct6 == 0x03) &
                                        (IS.funct3 == 0b001))
                        with m.If(is_vfredusum | is_vfredosum):
                            vfredsum_group_regs = Signal(4)
                            vfredsum_width_legal = Signal()
                            m.d.comb += [
                                vfredsum_group_regs.eq(1),
                                vfredsum_width_legal.eq(Mux(
                                    csr_vtype[3:6] == 2, self.enable_fp32,
                                    Mux(csr_vtype[3:6] == 3,
                                        self.enable_fp64, 0))),
                            ]
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += vfredsum_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += vfredsum_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += vfredsum_group_regs.eq(8)
                            vfredsum_group_legal = (
                                ~csr_vtype[self.xlen - 1] &
                                (csr_vstart == 0) &
                                (csr_vtype[0:3] != 4) &
                                ((IS.rs2 & (vfredsum_group_regs - 1)) == 0) &
                                (IS.rs2 <= (32 - vfredsum_group_regs)) &
                                (vm | (IS.rd != 0)))
                            with m.If(~vfredsum_width_legal |
                                      ~vfredsum_group_legal |
                                      (csr_frm > 4)):
                                m.d.comb += self.trap.eq(1)
                            with m.Elif(~vfredsum_active):
                                m.d.sync += [
                                    vfredsum_active.eq(1),
                                    vfredsum_index.eq(0),
                                    vfredsum_vl.eq(csr_vl),
                                    vfredsum_vd.eq(IS.rd),
                                    vfredsum_vs2.eq(IS.rs2),
                                    vfredsum_is_f64.eq(csr_vtype[3:6] == 3),
                                    vfredsum_widen.eq(0),
                                    vfredsum_vm.eq(vm),
                                    vfredsum_vta.eq(csr_vtype[6]),
                                    vfredsum_accum.eq(Mux(
                                        csr_vtype[3:6] == 3,
                                        vregs[IS.rs1][:64],
                                        vregs[IS.rs1][:32])),
                                    vfredsum_flags.eq(0),
                                ]
                                m.d.comb += [
                                    redirect.eq(1),
                                    redirect_pc.eq(IS.pc + 4),
                                ]

                        is_vfwredusum = ((vfunct6 == 0x31) &
                                         (IS.funct3 == 0b001))
                        is_vfwredosum = ((vfunct6 == 0x33) &
                                         (IS.funct3 == 0b001))
                        with m.If(is_vfwredusum | is_vfwredosum):
                            vfwred_group_regs = Signal(4)
                            m.d.comb += vfwred_group_regs.eq(1)
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += vfwred_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += vfwred_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += vfwred_group_regs.eq(8)
                            vfwred_legal = (
                                self.enable_fp32 & self.enable_fp64 &
                                ~csr_vtype[self.xlen - 1] &
                                (csr_vtype[3:6] == 2) &
                                (csr_vstart == 0) &
                                (csr_vtype[0:3] != 4) &
                                ((IS.rs2 & (vfwred_group_regs - 1)) == 0) &
                                (IS.rs2 <= (32 - vfwred_group_regs)) &
                                (vm | (IS.rd != 0)) &
                                (csr_frm <= 4))
                            with m.If(~vfwred_legal):
                                m.d.comb += self.trap.eq(1)
                            with m.Elif(~vfredsum_active):
                                m.d.sync += [
                                    vfredsum_active.eq(1),
                                    vfredsum_index.eq(0),
                                    vfredsum_vl.eq(csr_vl),
                                    vfredsum_vd.eq(IS.rd),
                                    vfredsum_vs2.eq(IS.rs2),
                                    vfredsum_is_f64.eq(1),
                                    vfredsum_widen.eq(1),
                                    vfredsum_vm.eq(vm),
                                    vfredsum_vta.eq(csr_vtype[6]),
                                    vfredsum_accum.eq(vregs[IS.rs1][:64]),
                                    vfredsum_flags.eq(0),
                                ]
                                m.d.comb += [
                                    redirect.eq(1),
                                    redirect_pc.eq(IS.pc + 4),
                                ]

                        is_vfredmin = ((vfunct6 == 0x05) &
                                       (IS.funct3 == 0b001))
                        is_vfredmax = ((vfunct6 == 0x07) &
                                       (IS.funct3 == 0b001))
                        with m.If(is_vfredmin | is_vfredmax):
                            fpreduce_group_regs = Signal(4)
                            fpreduce_width_legal = Signal()
                            fpreduce_group_legal = Signal()
                            m.d.comb += [
                                fpreduce_group_regs.eq(1),
                                fpreduce_width_legal.eq(Mux(
                                    csr_vtype[3:6] == 2, self.enable_fp32,
                                    Mux(csr_vtype[3:6] == 3,
                                        self.enable_fp64, 0))),
                            ]
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += fpreduce_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += fpreduce_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += fpreduce_group_regs.eq(8)
                            m.d.comb += fpreduce_group_legal.eq(
                                ~csr_vtype[self.xlen - 1] &
                                (csr_vstart == 0) &
                                (csr_vtype[0:3] != 4) &
                                ((IS.rs2 & (fpreduce_group_regs - 1)) == 0) &
                                (IS.rs2 <= (32 - fpreduce_group_regs)) &
                                (vm | (IS.rd != 0)))
                            with m.If(~fpreduce_width_legal |
                                      ~fpreduce_group_legal):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                fpreduce_dest_data = Signal(128)
                                fpreduce_flags_expr = C(0, 5)
                                m.d.comb += fpreduce_dest_data.eq(vregs[IS.rd])
                                with m.Switch(csr_vtype[3:6]):
                                    for vsew, element_width, exponent_lo, quiet_bit, canonical_nan in (
                                        (2, 32, 23, 22, 0x7FC00000),
                                        (3, 64, 52, 51, 0x7FF8000000000000),
                                    ):
                                        with m.Case(vsew):
                                            def fpreduce_pair(left, right):
                                                left_nan = (left[exponent_lo:element_width - 1].all() &
                                                            left[0:exponent_lo].any())
                                                right_nan = (right[exponent_lo:element_width - 1].all() &
                                                             right[0:exponent_lo].any())
                                                left_zero = left[0:element_width - 1] == 0
                                                right_zero = right[0:element_width - 1] == 0
                                                left_lt = Mux(
                                                    left[element_width - 1] != right[element_width - 1],
                                                    left[element_width - 1],
                                                    Mux(left[element_width - 1],
                                                        left[0:element_width - 1] > right[0:element_width - 1],
                                                        left[0:element_width - 1] < right[0:element_width - 1]))
                                                numeric = Mux(
                                                    is_vfredmin,
                                                    Mux(left_lt, left, right),
                                                    Mux(left_lt, right, left))
                                                zero_result = Cat(
                                                    C(0, element_width - 1),
                                                    Mux(is_vfredmin,
                                                        left[element_width - 1] |
                                                        right[element_width - 1],
                                                        left[element_width - 1] &
                                                        right[element_width - 1]))
                                                return Mux(
                                                    left_nan & right_nan,
                                                    C(canonical_nan, element_width),
                                                    Mux(left_nan, right,
                                                        Mux(right_nan, left,
                                                            Mux(left_zero & right_zero,
                                                                zero_result, numeric))))

                                            fpreduce_values = []
                                            fpreduce_valids = []
                                            elements_per_reg = 128 // element_width
                                            for reg_offset in range(8):
                                                for element_offset in range(elements_per_reg):
                                                    global_element = (reg_offset *
                                                                      elements_per_reg +
                                                                      element_offset)
                                                    lo = element_offset * element_width
                                                    hi = lo + element_width
                                                    source = vregs[
                                                        IS.rs2 + reg_offset][lo:hi]
                                                    active = ((fpreduce_group_regs > reg_offset) &
                                                              (global_element < csr_vl) &
                                                              (vm | vregs[0][global_element]))
                                                    source_snan = (
                                                        source[exponent_lo:element_width - 1].all() &
                                                        source[0:exponent_lo].any() &
                                                        ~source[quiet_bit])
                                                    fpreduce_values.append(source)
                                                    fpreduce_valids.append(active)
                                                    fpreduce_flags_expr = (
                                                        fpreduce_flags_expr |
                                                        Mux(active & source_snan,
                                                            C(0b10000, 5), C(0, 5)))
                                            while len(fpreduce_values) > 1:
                                                next_values = []
                                                next_valids = []
                                                for term in range(0, len(fpreduce_values), 2):
                                                    pair_valid_signal = Signal()
                                                    pair_value_signal = Signal(element_width)
                                                    if term + 1 < len(fpreduce_values):
                                                        pair_valid = (fpreduce_valids[term] |
                                                                      fpreduce_valids[term + 1])
                                                        pair_value = Mux(
                                                            fpreduce_valids[term] &
                                                            fpreduce_valids[term + 1],
                                                            fpreduce_pair(
                                                                fpreduce_values[term],
                                                                fpreduce_values[term + 1]),
                                                            Mux(fpreduce_valids[term],
                                                                fpreduce_values[term],
                                                                fpreduce_values[term + 1]))
                                                    else:
                                                        pair_valid = fpreduce_valids[term]
                                                        pair_value = fpreduce_values[term]
                                                    m.d.comb += [
                                                        pair_valid_signal.eq(pair_valid),
                                                        pair_value_signal.eq(pair_value),
                                                    ]
                                                    next_values.append(pair_value_signal)
                                                    next_valids.append(pair_valid_signal)
                                                fpreduce_values = next_values
                                                fpreduce_valids = next_valids
                                            any_active = fpreduce_valids[0]
                                            initial = vregs[IS.rs1][0:element_width]
                                            initial_snan = (
                                                initial[exponent_lo:element_width - 1].all() &
                                                initial[0:exponent_lo].any() &
                                                ~initial[quiet_bit])
                                            fpreduce_result = Mux(
                                                any_active,
                                                fpreduce_pair(initial,
                                                              fpreduce_values[0]),
                                                initial)
                                            fpreduce_flags_expr = (
                                                fpreduce_flags_expr |
                                                Mux(any_active & initial_snan,
                                                    C(0b10000, 5), C(0, 5)))
                                            fpreduce_elements = [fpreduce_result]
                                            for element_offset in range(
                                                    1, elements_per_reg):
                                                lo = element_offset * element_width
                                                hi = lo + element_width
                                                fpreduce_elements.append(Mux(
                                                    csr_vtype[6],
                                                    C(-1, element_width),
                                                    vregs[IS.rd][lo:hi]))
                                            m.d.comb += fpreduce_dest_data.eq(
                                                Cat(*fpreduce_elements))
                                with m.If(csr_vl != 0):
                                    m.d.sync += vregs[IS.rd].eq(
                                        fpreduce_dest_data)
                                    with m.If(fpreduce_flags_expr.any()):
                                        m.d.sync += csr_fflags.eq(
                                            csr_fflags | fpreduce_flags_expr)
                                m.d.sync += csr_vstart.eq(0)
                        is_vwredsumu = ((vfunct6 == 0x30) &
                                        (IS.funct3 == 0b000))
                        is_vwredsum = ((vfunct6 == 0x31) &
                                       (IS.funct3 == 0b000))
                        with m.If(is_vwredsumu | is_vwredsum):
                            wreduce_group_regs = Signal(4)
                            wreduce_group_legal = Signal()
                            m.d.comb += wreduce_group_regs.eq(1)
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += wreduce_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += wreduce_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += wreduce_group_regs.eq(8)
                            m.d.comb += wreduce_group_legal.eq(
                                ~csr_vtype[self.xlen - 1] &
                                (csr_vstart == 0) &
                                (csr_vtype[0:3] != 4) &
                                ((IS.rs2 & (wreduce_group_regs - 1)) == 0) &
                                (IS.rs2 <= (32 - wreduce_group_regs)))
                            with m.If(~wreduce_group_legal):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                wreduce_dest_data = Signal(128)
                                m.d.comb += wreduce_dest_data.eq(vregs[IS.rd])
                                with m.Switch(csr_vtype[3:6]):
                                    for vsew, source_width in enumerate((8, 16, 32)):
                                        with m.Case(vsew):
                                            result_width = source_width * 2
                                            wreduce_terms = []
                                            elements_per_reg = 128 // source_width
                                            for reg_offset in range(8):
                                                for element_offset in range(elements_per_reg):
                                                    global_element = (reg_offset *
                                                                      elements_per_reg +
                                                                      element_offset)
                                                    lo = element_offset * source_width
                                                    hi = lo + source_width
                                                    source_element = vregs[
                                                        IS.rs2 + reg_offset][lo:hi]
                                                    widened_element = Signal(result_width)
                                                    m.d.comb += widened_element.eq(Mux(
                                                        is_vwredsum,
                                                        Cat(source_element,
                                                            *([source_element[
                                                                source_width - 1]] *
                                                              source_width)),
                                                        Cat(source_element,
                                                            C(0, source_width))))
                                                    element_active = (
                                                        (wreduce_group_regs > reg_offset) &
                                                        (global_element < csr_vl) &
                                                        (vm | vregs[0][global_element]))
                                                    wreduce_term = Signal(result_width)
                                                    m.d.comb += wreduce_term.eq(Mux(
                                                        element_active,
                                                        widened_element,
                                                        C(0, result_width)))
                                                    wreduce_terms.append(wreduce_term)
                                            while len(wreduce_terms) > 1:
                                                next_terms = []
                                                for term in range(0, len(wreduce_terms), 2):
                                                    pair_sum = Signal(result_width)
                                                    if term + 1 < len(wreduce_terms):
                                                        m.d.comb += pair_sum.eq(
                                                            wreduce_terms[term] +
                                                            wreduce_terms[term + 1])
                                                    else:
                                                        m.d.comb += pair_sum.eq(
                                                            wreduce_terms[term])
                                                    next_terms.append(pair_sum)
                                                wreduce_terms = next_terms
                                            wreduce_result = Signal(result_width)
                                            m.d.comb += wreduce_result.eq(
                                                vregs[IS.rs1][0:result_width] +
                                                wreduce_terms[0])
                                            result_elements = [wreduce_result]
                                            for element_offset in range(
                                                    1, 128 // result_width):
                                                lo = element_offset * result_width
                                                hi = lo + result_width
                                                result_elements.append(Mux(
                                                    csr_vtype[6],
                                                    C(-1, result_width),
                                                    vregs[IS.rd][lo:hi]))
                                            m.d.comb += wreduce_dest_data.eq(
                                                Cat(*result_elements))
                                with m.If(csr_vl != 0):
                                    m.d.sync += vregs[IS.rd].eq(
                                        wreduce_dest_data)
                                m.d.sync += csr_vstart.eq(0)
                        is_vdivu = ((vfunct6 == 0x20) &
                                    ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vdiv = ((vfunct6 == 0x21) &
                                   ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vremu = ((vfunct6 == 0x22) &
                                    ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vrem = ((vfunct6 == 0x23) &
                                   ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        with m.If(is_vdivu | is_vdiv | is_vremu | is_vrem):
                            div_group_regs = Signal(4)
                            div_is_vv = IS.funct3 == 0b010
                            div_group_aligned = Signal()
                            m.d.comb += div_group_regs.eq(1)
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += div_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += div_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += div_group_regs.eq(8)
                            m.d.comb += div_group_aligned.eq(
                                (csr_vtype[0:3] != 4) &
                                ((IS.rd & (div_group_regs - 1)) == 0) &
                                ((IS.rs2 & (div_group_regs - 1)) == 0) &
                                (~div_is_vv | ((IS.rs1 & (div_group_regs - 1)) == 0)) &
                                (IS.rd <= (32 - div_group_regs)) &
                                (IS.rs2 <= (32 - div_group_regs)) &
                                (~div_is_vv | (IS.rs1 <= (32 - div_group_regs))))
                            with m.If(~div_group_aligned | csr_vtype[self.xlen - 1]):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                with m.If(csr_vstart < csr_vl):
                                    for reg_offset in range(8):
                                        with m.If(div_group_regs > reg_offset):
                                            div_reg_data = Signal(128)
                                            m.d.comb += div_reg_data.eq(vregs[IS.rd + reg_offset])
                                            with m.Switch(csr_vtype[3:6]):
                                                for vsew, element_width in enumerate((8, 16, 32)):
                                                    with m.Case(vsew):
                                                        div_elements = []
                                                        element_count = 128 // element_width
                                                        for element_offset in range(element_count):
                                                            global_element = (reg_offset * element_count +
                                                                              element_offset)
                                                            lo = element_offset * element_width
                                                            hi = lo + element_width
                                                            old_element = vregs[IS.rd + reg_offset][lo:hi]
                                                            dividend = vregs[IS.rs2 + reg_offset][lo:hi]
                                                            vector_divisor = vregs[IS.rs1 + reg_offset][lo:hi]
                                                            divisor = Mux(div_is_vv, vector_divisor,
                                                                          ex1_a[:element_width])
                                                            safe_divisor = Mux(divisor == 0,
                                                                               C(1, element_width),
                                                                               divisor)
                                                            abs_dividend = Signal(element_width)
                                                            abs_divisor = Signal(element_width)
                                                            safe_abs_divisor = Signal(element_width)
                                                            abs_quotient = Signal(element_width)
                                                            abs_remainder = Signal(element_width)
                                                            signed_quotient = Signal(element_width)
                                                            signed_remainder = Signal(element_width)
                                                            div_result = Signal(element_width)
                                                            next_element = Signal(element_width)
                                                            signed_overflow = (
                                                                (dividend == (1 << (element_width - 1))) &
                                                                (divisor == C(-1, element_width)))
                                                            m.d.comb += [
                                                                abs_dividend.eq(Mux(
                                                                    dividend[element_width - 1],
                                                                    -dividend, dividend)),
                                                                abs_divisor.eq(Mux(
                                                                    divisor[element_width - 1],
                                                                    -divisor, divisor)),
                                                                safe_abs_divisor.eq(Mux(
                                                                    abs_divisor == 0,
                                                                    C(1, element_width), abs_divisor)),
                                                                abs_quotient.eq(
                                                                    abs_dividend // safe_abs_divisor),
                                                                abs_remainder.eq(
                                                                    abs_dividend % safe_abs_divisor),
                                                                signed_quotient.eq(Mux(
                                                                    dividend[element_width - 1] ^
                                                                    divisor[element_width - 1],
                                                                    -abs_quotient, abs_quotient)),
                                                                signed_remainder.eq(Mux(
                                                                    dividend[element_width - 1],
                                                                    -abs_remainder, abs_remainder)),
                                                                div_result.eq(0),
                                                                next_element.eq(old_element),
                                                            ]
                                                            with m.If(is_vdivu):
                                                                m.d.comb += div_result.eq(Mux(
                                                                    divisor == 0,
                                                                    C(-1, element_width),
                                                                    dividend // safe_divisor))
                                                            with m.Elif(is_vdiv):
                                                                m.d.comb += div_result.eq(Mux(
                                                                    divisor == 0,
                                                                    C(-1, element_width),
                                                                    Mux(signed_overflow,
                                                                        dividend, signed_quotient)))
                                                            with m.Elif(is_vremu):
                                                                m.d.comb += div_result.eq(Mux(
                                                                    divisor == 0,
                                                                    dividend,
                                                                    dividend % safe_divisor))
                                                            with m.Else():
                                                                m.d.comb += div_result.eq(Mux(
                                                                    divisor == 0,
                                                                    dividend,
                                                                    Mux(signed_overflow, 0,
                                                                        signed_remainder)))
                                                            element_enabled = vm | vregs[0][global_element]
                                                            with m.If((csr_vstart <= global_element) &
                                                                      (global_element < csr_vl)):
                                                                with m.If(element_enabled):
                                                                    m.d.comb += next_element.eq(div_result)
                                                                with m.Elif(csr_vtype[7]):
                                                                    m.d.comb += next_element.eq(
                                                                        C(-1, element_width))
                                                            with m.Elif((global_element >= csr_vl) &
                                                                        (global_element < csr_vlmax) &
                                                                        csr_vtype[6]):
                                                                m.d.comb += next_element.eq(
                                                                    C(-1, element_width))
                                                            div_elements.append(next_element)
                                                        m.d.comb += div_reg_data.eq(Cat(*div_elements))
                                            m.d.sync += vregs[IS.rd + reg_offset].eq(div_reg_data)
                                m.d.sync += csr_vstart.eq(0)
                        is_vsmul = ((vfunct6 == 0x27) &
                                    ((IS.funct3 == 0b000) | (IS.funct3 == 0b100)))
                        with m.If(is_vsmul):
                            smul_group_regs = Signal(4)
                            smul_is_vv = IS.funct3 == 0b000
                            smul_group_aligned = Signal()
                            m.d.comb += smul_group_regs.eq(1)
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += smul_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += smul_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += smul_group_regs.eq(8)
                            m.d.comb += smul_group_aligned.eq(
                                (csr_vtype[0:3] != 4) &
                                ((IS.rd & (smul_group_regs - 1)) == 0) &
                                ((IS.rs2 & (smul_group_regs - 1)) == 0) &
                                (~smul_is_vv | ((IS.rs1 & (smul_group_regs - 1)) == 0)) &
                                (IS.rd <= (32 - smul_group_regs)) &
                                (IS.rs2 <= (32 - smul_group_regs)) &
                                (~smul_is_vv | (IS.rs1 <= (32 - smul_group_regs))))
                            with m.If(~smul_group_aligned | csr_vtype[self.xlen - 1]):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                with m.If(csr_vstart < csr_vl):
                                    for reg_offset in range(8):
                                        with m.If(smul_group_regs > reg_offset):
                                            smul_reg_data = Signal(128)
                                            m.d.comb += smul_reg_data.eq(
                                                vregs[IS.rd + reg_offset])
                                            with m.Switch(csr_vtype[3:6]):
                                                for vsew, element_width in enumerate((8, 16, 32)):
                                                    with m.Case(vsew):
                                                        smul_elements = []
                                                        element_count = 128 // element_width
                                                        for element_offset in range(element_count):
                                                            global_element = (reg_offset * element_count +
                                                                              element_offset)
                                                            lo = element_offset * element_width
                                                            hi = lo + element_width
                                                            old_element = vregs[IS.rd + reg_offset][lo:hi]
                                                            lhs = vregs[IS.rs2 + reg_offset][lo:hi]
                                                            vector_rhs = vregs[IS.rs1 + reg_offset][lo:hi]
                                                            rhs = Mux(smul_is_vv, vector_rhs,
                                                                      ex1_a[:element_width])
                                                            lhs_abs = Signal(element_width)
                                                            rhs_abs = Signal(element_width)
                                                            magnitude_product = Signal(
                                                                2 * element_width)
                                                            signed_product = Signal(
                                                                2 * element_width)
                                                            round_increment = Signal()
                                                            scaled_product = Signal(element_width)
                                                            smul_result = Signal(element_width)
                                                            next_element = Signal(element_width)
                                                            smul_overflow = (
                                                                (lhs == (1 << (element_width - 1))) &
                                                                (rhs == (1 << (element_width - 1))))
                                                            m.d.comb += [
                                                                lhs_abs.eq(Mux(
                                                                    lhs[element_width - 1], -lhs, lhs)),
                                                                rhs_abs.eq(Mux(
                                                                    rhs[element_width - 1], -rhs, rhs)),
                                                                magnitude_product.eq(lhs_abs * rhs_abs),
                                                                signed_product.eq(Mux(
                                                                    lhs[element_width - 1] ^
                                                                    rhs[element_width - 1],
                                                                    -magnitude_product,
                                                                    magnitude_product)),
                                                                round_increment.eq(0),
                                                                scaled_product.eq(
                                                                    signed_product[
                                                                        element_width - 1:
                                                                        2 * element_width - 1]),
                                                                smul_result.eq(scaled_product +
                                                                               round_increment),
                                                                next_element.eq(old_element),
                                                            ]
                                                            with m.Switch(csr_vxrm):
                                                                with m.Case(0):
                                                                    m.d.comb += round_increment.eq(
                                                                        signed_product[
                                                                            element_width - 2])
                                                                with m.Case(1):
                                                                    m.d.comb += round_increment.eq(
                                                                        signed_product[
                                                                            element_width - 2] &
                                                                        ((signed_product[
                                                                            :element_width - 2] != 0) |
                                                                         signed_product[
                                                                             element_width - 1]))
                                                                with m.Case(2):
                                                                    m.d.comb += round_increment.eq(0)
                                                                with m.Case(3):
                                                                    m.d.comb += round_increment.eq(
                                                                        ~signed_product[
                                                                            element_width - 1] &
                                                                        (signed_product[
                                                                            :element_width - 1] != 0))
                                                            with m.If(smul_overflow):
                                                                m.d.comb += smul_result.eq(
                                                                    (1 << (element_width - 1)) - 1)
                                                            element_enabled = vm | vregs[0][global_element]
                                                            with m.If((csr_vstart <= global_element) &
                                                                      (global_element < csr_vl)):
                                                                with m.If(element_enabled):
                                                                    m.d.comb += next_element.eq(smul_result)
                                                                    with m.If(smul_overflow):
                                                                        m.d.sync += csr_vxsat.eq(1)
                                                                with m.Elif(csr_vtype[7]):
                                                                    m.d.comb += next_element.eq(
                                                                        C(-1, element_width))
                                                            with m.Elif((global_element >= csr_vl) &
                                                                        (global_element < csr_vlmax) &
                                                                        csr_vtype[6]):
                                                                m.d.comb += next_element.eq(
                                                                    C(-1, element_width))
                                                            smul_elements.append(next_element)
                                                        m.d.comb += smul_reg_data.eq(
                                                            Cat(*smul_elements))
                                            m.d.sync += vregs[IS.rd + reg_offset].eq(
                                                smul_reg_data)
                                m.d.sync += csr_vstart.eq(0)
                        is_vnsrl = ((vfunct6 == 0x2C) &
                                    ((IS.funct3 == 0b000) |
                                     (IS.funct3 == 0b100) |
                                     (IS.funct3 == 0b011)))
                        is_vnsra = ((vfunct6 == 0x2D) &
                                    ((IS.funct3 == 0b000) |
                                     (IS.funct3 == 0b100) |
                                     (IS.funct3 == 0b011)))
                        is_vnclipu = ((vfunct6 == 0x2E) &
                                     ((IS.funct3 == 0b000) |
                                      (IS.funct3 == 0b100) |
                                      (IS.funct3 == 0b011)))
                        is_vnclip = ((vfunct6 == 0x2F) &
                                    ((IS.funct3 == 0b000) |
                                     (IS.funct3 == 0b100) |
                                     (IS.funct3 == 0b011)))
                        with m.If(is_vnsrl | is_vnsra | is_vnclipu | is_vnclip):
                            nshift_dest_regs = Signal(4)
                            nshift_source_regs = Signal(4)
                            nshift_lmul_legal = Signal()
                            nshift_group_legal = Signal()
                            nshift_is_vv = IS.funct3 == 0b000
                            m.d.comb += [
                                nshift_dest_regs.eq(1),
                                nshift_source_regs.eq(1),
                                nshift_lmul_legal.eq(1),
                            ]
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(0):
                                    m.d.comb += nshift_source_regs.eq(2)
                                with m.Case(1):
                                    m.d.comb += [nshift_dest_regs.eq(2),
                                                 nshift_source_regs.eq(4)]
                                with m.Case(2):
                                    m.d.comb += [nshift_dest_regs.eq(4),
                                                 nshift_source_regs.eq(8)]
                                with m.Case(3, 4):
                                    m.d.comb += nshift_lmul_legal.eq(0)
                            nshift_vs2_no_overlap = (
                                (IS.rd + nshift_dest_regs <= IS.rs2) |
                                (IS.rs2 + nshift_source_regs <= IS.rd))
                            nshift_vs2_low_overlap = IS.rd == IS.rs2
                            nshift_vs1_no_overlap = (
                                (IS.rd + nshift_dest_regs <= IS.rs1) |
                                (IS.rs1 + nshift_dest_regs <= IS.rd))
                            nshift_vs1_exact_overlap = IS.rd == IS.rs1
                            m.d.comb += nshift_group_legal.eq(
                                nshift_lmul_legal &
                                ((IS.rd & (nshift_dest_regs - 1)) == 0) &
                                ((IS.rs2 & (nshift_source_regs - 1)) == 0) &
                                (~nshift_is_vv |
                                 ((IS.rs1 & (nshift_dest_regs - 1)) == 0)) &
                                (IS.rd <= (32 - nshift_dest_regs)) &
                                (IS.rs2 <= (32 - nshift_source_regs)) &
                                (~nshift_is_vv |
                                 (IS.rs1 <= (32 - nshift_dest_regs))) &
                                (nshift_vs2_no_overlap | nshift_vs2_low_overlap) &
                                (~nshift_is_vv | nshift_vs1_no_overlap |
                                 nshift_vs1_exact_overlap) &
                                (vm | (IS.rd != 0))
                            )
                            with m.If(~nshift_group_legal | csr_vtype[self.xlen - 1]):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                with m.If(csr_vstart < csr_vl):
                                    for dest_reg_offset in range(8):
                                        with m.If(nshift_dest_regs > dest_reg_offset):
                                            nshift_reg_data = Signal(128)
                                            m.d.comb += nshift_reg_data.eq(
                                                vregs[IS.rd + dest_reg_offset])
                                            with m.Switch(csr_vtype[3:6]):
                                                for vsew, result_width in enumerate((8, 16, 32)):
                                                    with m.Case(vsew):
                                                        source_width = result_width * 2
                                                        result_elements = 128 // result_width
                                                        source_elements = 128 // source_width
                                                        shift_bits = {8: 4, 16: 5, 32: 6}[result_width]
                                                        nshift_elements = []
                                                        for element_offset in range(result_elements):
                                                            global_element = (dest_reg_offset * result_elements +
                                                                              element_offset)
                                                            source_reg_offset = global_element // source_elements
                                                            source_element_offset = global_element % source_elements
                                                            source_lo = source_element_offset * source_width
                                                            source_hi = source_lo + source_width
                                                            result_lo = element_offset * result_width
                                                            result_hi = result_lo + result_width
                                                            wide_source = vregs[IS.rs2 + source_reg_offset][
                                                                source_lo:source_hi]
                                                            vector_amount = vregs[IS.rs1 + dest_reg_offset][
                                                                result_lo:result_hi]
                                                            shift_amount = Mux(
                                                                nshift_is_vv, vector_amount,
                                                                Mux(IS.funct3 == 0b100, ex1_a, IS.rs1))
                                                            shifted_source = Signal(source_width)
                                                            clip_remainder = Signal(source_width)
                                                            clip_half = Signal(source_width)
                                                            clip_increment = Signal()
                                                            clip_unsigned = Signal(source_width + 1)
                                                            clip_signed = Signal(signed(source_width + 1))
                                                            clip_result = Signal(result_width)
                                                            clip_saturates = Signal()
                                                            old_element = vregs[IS.rd + dest_reg_offset][
                                                                result_lo:result_hi]
                                                            next_element = Signal(result_width)
                                                            m.d.comb += [
                                                                shifted_source.eq(wide_source >>
                                                                    shift_amount[0:shift_bits]),
                                                                clip_remainder.eq(0),
                                                                clip_half.eq(0),
                                                                clip_increment.eq(0),
                                                                clip_unsigned.eq(0),
                                                                clip_signed.eq(0),
                                                                clip_result.eq(shifted_source[
                                                                    0:result_width]),
                                                                clip_saturates.eq(0),
                                                                next_element.eq(old_element),
                                                            ]
                                                            with m.If(is_vnsra | is_vnclip):
                                                                m.d.comb += shifted_source.eq(
                                                                    wide_source.as_signed() >>
                                                                    shift_amount[0:shift_bits])
                                                            with m.If(is_vnclipu | is_vnclip):
                                                                masked_amount = shift_amount[0:shift_bits]
                                                                m.d.comb += clip_remainder.eq(
                                                                    wide_source &
                                                                    ((C(1, source_width) << masked_amount) - 1))
                                                                with m.If(masked_amount != 0):
                                                                    m.d.comb += clip_half.eq(
                                                                        C(1, source_width) <<
                                                                        (masked_amount - 1).as_unsigned())
                                                                    with m.Switch(csr_vxrm):
                                                                        with m.Case(0):
                                                                            m.d.comb += clip_increment.eq(
                                                                                (clip_remainder & clip_half) != 0)
                                                                        with m.Case(1):
                                                                            m.d.comb += clip_increment.eq(
                                                                                ((clip_remainder & clip_half) != 0) &
                                                                                (((clip_remainder &
                                                                                   (clip_half - 1)) != 0) |
                                                                                 shifted_source[0]))
                                                                        with m.Case(3):
                                                                            m.d.comb += clip_increment.eq(
                                                                                (clip_remainder != 0) &
                                                                                ~shifted_source[0])
                                                                with m.If(is_vnclipu):
                                                                    m.d.comb += clip_unsigned.eq(
                                                                        Cat(shifted_source, C(0, 1)) +
                                                                        clip_increment)
                                                                    with m.If(clip_unsigned >
                                                                              C((1 << result_width) - 1,
                                                                                source_width + 1)):
                                                                        m.d.comb += [
                                                                            clip_result.eq(C(-1, result_width)),
                                                                            clip_saturates.eq(1),
                                                                        ]
                                                                    with m.Else():
                                                                        m.d.comb += clip_result.eq(
                                                                            clip_unsigned[0:result_width])
                                                                with m.Else():
                                                                    m.d.comb += clip_signed.eq(
                                                                        Cat(shifted_source,
                                                                            shifted_source[source_width - 1]) +
                                                                        clip_increment)
                                                                    with m.If(clip_signed >
                                                                              C((1 << (result_width - 1)) - 1,
                                                                                source_width + 1).as_signed()):
                                                                        m.d.comb += [
                                                                            clip_result.eq(
                                                                                C((1 << (result_width - 1)) - 1,
                                                                                  result_width)),
                                                                            clip_saturates.eq(1),
                                                                        ]
                                                                    with m.Elif(clip_signed <
                                                                                C(-(1 << (result_width - 1)),
                                                                                  source_width + 1)):
                                                                        m.d.comb += [
                                                                            clip_result.eq(
                                                                                C(1 << (result_width - 1),
                                                                                  result_width)),
                                                                            clip_saturates.eq(1),
                                                                        ]
                                                                    with m.Else():
                                                                        m.d.comb += clip_result.eq(
                                                                            clip_signed[0:result_width])
                                                            element_enabled = vm | vregs[0][global_element]
                                                            with m.If((csr_vstart <= global_element) &
                                                                      (global_element < csr_vl)):
                                                                with m.If(element_enabled):
                                                                    m.d.comb += next_element.eq(
                                                                        shifted_source[0:result_width])
                                                                    with m.If(is_vnclipu | is_vnclip):
                                                                        m.d.comb += next_element.eq(clip_result)
                                                                        with m.If(clip_saturates):
                                                                            m.d.sync += csr_vxsat.eq(1)
                                                                with m.Elif(csr_vtype[7]):
                                                                    m.d.comb += next_element.eq(
                                                                        C(-1, result_width))
                                                            with m.Elif((global_element >= csr_vl) &
                                                                        (global_element < csr_vlmax) &
                                                                        csr_vtype[6]):
                                                                m.d.comb += next_element.eq(
                                                                    C(-1, result_width))
                                                            nshift_elements.append(next_element)
                                                        m.d.comb += nshift_reg_data.eq(
                                                            Cat(*nshift_elements))
                                            m.d.sync += vregs[IS.rd + dest_reg_offset].eq(
                                                nshift_reg_data)
                                m.d.sync += csr_vstart.eq(0)
                        is_vwaddu = ((vfunct6 == 0x30) &
                                     ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vwadd = ((vfunct6 == 0x31) &
                                    ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vwsubu = ((vfunct6 == 0x32) &
                                     ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vwsub = ((vfunct6 == 0x33) &
                                    ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vwaddu_w = ((vfunct6 == 0x34) &
                                       ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vwadd_w = ((vfunct6 == 0x35) &
                                      ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vwsubu_w = ((vfunct6 == 0x36) &
                                       ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vwsub_w = ((vfunct6 == 0x37) &
                                      ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        with m.If(is_vwaddu | is_vwadd | is_vwsubu | is_vwsub |
                                  is_vwaddu_w | is_vwadd_w | is_vwsubu_w | is_vwsub_w):
                            wadd_source_regs = Signal(4)
                            wadd_dest_regs = Signal(4)
                            wadd_lmul_legal = Signal()
                            wadd_group_legal = Signal()
                            wadd_is_vv = IS.funct3 == 0b010
                            wadd_wide_source = vfunct6[2]
                            wadd_signed = is_vwadd | is_vwsub | is_vwadd_w | is_vwsub_w
                            wadd_subtract = is_vwsubu | is_vwsub | is_vwsubu_w | is_vwsub_w
                            m.d.comb += [
                                wadd_source_regs.eq(1),
                                wadd_dest_regs.eq(1),
                                wadd_lmul_legal.eq(1),
                            ]
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(0):
                                    m.d.comb += wadd_dest_regs.eq(2)
                                with m.Case(1):
                                    m.d.comb += [wadd_source_regs.eq(2),
                                                 wadd_dest_regs.eq(4)]
                                with m.Case(2):
                                    m.d.comb += [wadd_source_regs.eq(4),
                                                 wadd_dest_regs.eq(8)]
                                with m.Case(3, 4):
                                    m.d.comb += wadd_lmul_legal.eq(0)
                            wadd_vs2_narrow_no_overlap = (
                                (IS.rd + wadd_dest_regs <= IS.rs2) |
                                (IS.rs2 + wadd_source_regs <= IS.rd))
                            wadd_vs2_narrow_high_overlap = (
                                (IS.rs2 + wadd_source_regs) ==
                                (IS.rd + wadd_dest_regs))
                            wadd_vs2_wide_no_overlap = (
                                (IS.rd + wadd_dest_regs <= IS.rs2) |
                                (IS.rs2 + wadd_dest_regs <= IS.rd))
                            wadd_vs2_wide_exact_overlap = IS.rd == IS.rs2
                            wadd_vs1_no_overlap = (
                                (IS.rd + wadd_dest_regs <= IS.rs1) |
                                (IS.rs1 + wadd_source_regs <= IS.rd))
                            wadd_vs1_high_overlap = (
                                (IS.rs1 + wadd_source_regs) ==
                                (IS.rd + wadd_dest_regs))
                            m.d.comb += wadd_group_legal.eq(
                                wadd_lmul_legal &
                                ((IS.rd & (wadd_dest_regs - 1)) == 0) &
                                Mux(wadd_wide_source,
                                    ((IS.rs2 & (wadd_dest_regs - 1)) == 0) &
                                    (IS.rs2 <= (32 - wadd_dest_regs)) &
                                    (wadd_vs2_wide_no_overlap |
                                     wadd_vs2_wide_exact_overlap),
                                    ((IS.rs2 & (wadd_source_regs - 1)) == 0) &
                                    (IS.rs2 <= (32 - wadd_source_regs)) &
                                    (wadd_vs2_narrow_no_overlap |
                                     wadd_vs2_narrow_high_overlap)) &
                                (~wadd_is_vv |
                                 (((IS.rs1 & (wadd_source_regs - 1)) == 0) &
                                  (IS.rs1 <= (32 - wadd_source_regs)) &
                                  (wadd_vs1_no_overlap | wadd_vs1_high_overlap))) &
                                (IS.rd <= (32 - wadd_dest_regs)) &
                                (vm | (IS.rd != 0))
                            )
                            with m.If(~wadd_group_legal | csr_vtype[self.xlen - 1]):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                with m.If(csr_vstart < csr_vl):
                                    for dest_reg_offset in range(8):
                                        with m.If(wadd_dest_regs > dest_reg_offset):
                                            wadd_reg_data = Signal(128)
                                            m.d.comb += wadd_reg_data.eq(
                                                vregs[IS.rd + dest_reg_offset])
                                            with m.Switch(csr_vtype[3:6]):
                                                for vsew, source_width in enumerate((8, 16, 32)):
                                                    with m.Case(vsew):
                                                        result_width = source_width * 2
                                                        source_elements = 128 // source_width
                                                        result_elements = 128 // result_width
                                                        wadd_elements = []
                                                        for element_offset in range(result_elements):
                                                            global_element = (dest_reg_offset * result_elements +
                                                                              element_offset)
                                                            source_reg_offset = global_element // source_elements
                                                            source_element_offset = global_element % source_elements
                                                            source_lo = source_element_offset * source_width
                                                            source_hi = source_lo + source_width
                                                            result_lo = element_offset * result_width
                                                            result_hi = result_lo + result_width
                                                            narrow_lhs = vregs[IS.rs2 + source_reg_offset][
                                                                source_lo:source_hi]
                                                            wide_lhs = vregs[IS.rs2 + dest_reg_offset][
                                                                result_lo:result_hi]
                                                            vector_rhs = vregs[IS.rs1 + source_reg_offset][
                                                                source_lo:source_hi]
                                                            narrow_rhs = Mux(wadd_is_vv, vector_rhs,
                                                                             ex1_a[0:source_width])
                                                            lhs_unsigned = Cat(narrow_lhs, C(0, source_width))
                                                            lhs_signed = Cat(
                                                                narrow_lhs,
                                                                Mux(narrow_lhs[source_width - 1],
                                                                    C(-1, source_width), C(0, source_width)))
                                                            rhs_unsigned = Cat(narrow_rhs, C(0, source_width))
                                                            rhs_signed = Cat(
                                                                narrow_rhs,
                                                                Mux(narrow_rhs[source_width - 1],
                                                                    C(-1, source_width), C(0, source_width)))
                                                            extended_lhs = Mux(wadd_signed,
                                                                               lhs_signed, lhs_unsigned)
                                                            extended_rhs = Mux(wadd_signed,
                                                                               rhs_signed, rhs_unsigned)
                                                            operation_lhs = Mux(wadd_wide_source,
                                                                                wide_lhs, extended_lhs)
                                                            old_element = vregs[IS.rd + dest_reg_offset][
                                                                result_lo:result_hi]
                                                            wadd_result = Signal(result_width)
                                                            next_element = Signal(result_width)
                                                            m.d.comb += [
                                                                wadd_result.eq(Mux(
                                                                    wadd_subtract,
                                                                    operation_lhs - extended_rhs,
                                                                    operation_lhs + extended_rhs)),
                                                                next_element.eq(old_element),
                                                            ]
                                                            element_enabled = vm | vregs[0][global_element]
                                                            with m.If((csr_vstart <= global_element) &
                                                                      (global_element < csr_vl)):
                                                                with m.If(element_enabled):
                                                                    m.d.comb += next_element.eq(wadd_result)
                                                                with m.Elif(csr_vtype[7]):
                                                                    m.d.comb += next_element.eq(
                                                                        C(-1, result_width))
                                                            with m.Elif((global_element >= csr_vl) &
                                                                        (global_element < csr_vlmax) &
                                                                        csr_vtype[6]):
                                                                m.d.comb += next_element.eq(
                                                                    C(-1, result_width))
                                                            wadd_elements.append(next_element)
                                                        m.d.comb += wadd_reg_data.eq(Cat(*wadd_elements))
                                            m.d.sync += vregs[IS.rd + dest_reg_offset].eq(
                                                wadd_reg_data)
                                m.d.sync += csr_vstart.eq(0)
                        is_vwmulu = ((vfunct6 == 0x38) &
                                     ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vwmulsu = ((vfunct6 == 0x3A) &
                                      ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vwmul = ((vfunct6 == 0x3B) &
                                    ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        with m.If(is_vwmulu | is_vwmulsu | is_vwmul):
                            wmul_source_regs = Signal(4)
                            wmul_dest_regs = Signal(4)
                            wmul_lmul_legal = Signal()
                            wmul_is_vv = IS.funct3 == 0b010
                            wmul_group_legal = Signal()
                            m.d.comb += [
                                wmul_source_regs.eq(1),
                                wmul_dest_regs.eq(1),
                                wmul_lmul_legal.eq(1),
                            ]
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(0):
                                    m.d.comb += wmul_dest_regs.eq(2)
                                with m.Case(1):
                                    m.d.comb += [wmul_source_regs.eq(2),
                                                 wmul_dest_regs.eq(4)]
                                with m.Case(2):
                                    m.d.comb += [wmul_source_regs.eq(4),
                                                 wmul_dest_regs.eq(8)]
                                with m.Case(3, 4):
                                    m.d.comb += wmul_lmul_legal.eq(0)
                            wmul_vs2_no_overlap = ((IS.rd + wmul_dest_regs <= IS.rs2) |
                                                   (IS.rs2 + wmul_source_regs <= IS.rd))
                            wmul_vs2_high_overlap = ((IS.rs2 + wmul_source_regs) ==
                                                     (IS.rd + wmul_dest_regs))
                            wmul_vs1_no_overlap = ((IS.rd + wmul_dest_regs <= IS.rs1) |
                                                   (IS.rs1 + wmul_source_regs <= IS.rd))
                            wmul_vs1_high_overlap = ((IS.rs1 + wmul_source_regs) ==
                                                     (IS.rd + wmul_dest_regs))
                            m.d.comb += wmul_group_legal.eq(
                                wmul_lmul_legal &
                                ((IS.rd & (wmul_dest_regs - 1)) == 0) &
                                ((IS.rs2 & (wmul_source_regs - 1)) == 0) &
                                (~wmul_is_vv |
                                 ((IS.rs1 & (wmul_source_regs - 1)) == 0)) &
                                (IS.rd <= (32 - wmul_dest_regs)) &
                                (IS.rs2 <= (32 - wmul_source_regs)) &
                                (~wmul_is_vv | (IS.rs1 <= (32 - wmul_source_regs))) &
                                (wmul_vs2_no_overlap | wmul_vs2_high_overlap) &
                                (~wmul_is_vv | wmul_vs1_no_overlap |
                                 wmul_vs1_high_overlap) &
                                (vm | (IS.rd != 0))
                            )
                            with m.If(~wmul_group_legal | csr_vtype[self.xlen - 1]):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                with m.If(csr_vstart < csr_vl):
                                    for dest_reg_offset in range(8):
                                        with m.If(wmul_dest_regs > dest_reg_offset):
                                            wmul_reg_data = Signal(128)
                                            m.d.comb += wmul_reg_data.eq(
                                                vregs[IS.rd + dest_reg_offset])
                                            with m.Switch(csr_vtype[3:6]):
                                                for vsew, source_width in enumerate((8, 16, 32)):
                                                    with m.Case(vsew):
                                                        result_width = source_width * 2
                                                        source_elements = 128 // source_width
                                                        result_elements = 128 // result_width
                                                        wmul_elements = []
                                                        for element_offset in range(result_elements):
                                                            global_element = (dest_reg_offset * result_elements +
                                                                              element_offset)
                                                            source_reg_offset = global_element // source_elements
                                                            source_element_offset = global_element % source_elements
                                                            source_lo = source_element_offset * source_width
                                                            source_hi = source_lo + source_width
                                                            result_lo = element_offset * result_width
                                                            result_hi = result_lo + result_width
                                                            lhs = vregs[IS.rs2 + source_reg_offset][
                                                                source_lo:source_hi]
                                                            vector_rhs = vregs[IS.rs1 + source_reg_offset][
                                                                source_lo:source_hi]
                                                            rhs = Mux(wmul_is_vv, vector_rhs,
                                                                      ex1_a[0:source_width])
                                                            old_element = vregs[IS.rd + dest_reg_offset][
                                                                result_lo:result_hi]
                                                            lhs_mag = Signal(source_width)
                                                            rhs_mag = Signal(source_width)
                                                            unsigned_product = Signal(result_width)
                                                            signed_product = Signal(result_width)
                                                            mixed_product = Signal(result_width)
                                                            selected_product = Signal(result_width)
                                                            next_element = Signal(result_width)
                                                            m.d.comb += [
                                                                lhs_mag.eq(Mux(lhs[source_width - 1],
                                                                               (~lhs) + 1, lhs)),
                                                                rhs_mag.eq(Mux(rhs[source_width - 1],
                                                                               (~rhs) + 1, rhs)),
                                                                unsigned_product.eq(lhs * rhs),
                                                                signed_product.eq(Mux(
                                                                    lhs[source_width - 1] ^ rhs[source_width - 1],
                                                                    -(lhs_mag * rhs_mag), lhs_mag * rhs_mag)),
                                                                mixed_product.eq(Mux(
                                                                    lhs[source_width - 1],
                                                                    -(lhs_mag * rhs), lhs_mag * rhs)),
                                                                selected_product.eq(unsigned_product),
                                                                next_element.eq(old_element),
                                                            ]
                                                            with m.If(is_vwmul):
                                                                m.d.comb += selected_product.eq(signed_product)
                                                            with m.Elif(is_vwmulsu):
                                                                m.d.comb += selected_product.eq(mixed_product)
                                                            element_enabled = vm | vregs[0][global_element]
                                                            with m.If((csr_vstart <= global_element) &
                                                                      (global_element < csr_vl)):
                                                                with m.If(element_enabled):
                                                                    m.d.comb += next_element.eq(selected_product)
                                                                with m.Elif(csr_vtype[7]):
                                                                    m.d.comb += next_element.eq(
                                                                        C(-1, result_width))
                                                            with m.Elif((global_element >= csr_vl) &
                                                                        (global_element < csr_vlmax) &
                                                                        csr_vtype[6]):
                                                                m.d.comb += next_element.eq(
                                                                    C(-1, result_width))
                                                            wmul_elements.append(next_element)
                                                        m.d.comb += wmul_reg_data.eq(Cat(*wmul_elements))
                                            m.d.sync += vregs[IS.rd + dest_reg_offset].eq(
                                                wmul_reg_data)
                                m.d.sync += csr_vstart.eq(0)
                        is_vwmaccu = ((vfunct6 == 0x3C) &
                                      ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vwmacc = ((vfunct6 == 0x3D) &
                                     ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vwmaccus = ((vfunct6 == 0x3E) & (IS.funct3 == 0b110))
                        is_vwmaccsu = ((vfunct6 == 0x3F) &
                                       ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        with m.If(is_vwmaccu | is_vwmacc | is_vwmaccus | is_vwmaccsu):
                            wmacc_source_regs = Signal(4)
                            wmacc_dest_regs = Signal(4)
                            wmacc_lmul_legal = Signal()
                            wmacc_is_vv = IS.funct3 == 0b010
                            wmacc_group_legal = Signal()
                            m.d.comb += [
                                wmacc_source_regs.eq(1),
                                wmacc_dest_regs.eq(1),
                                wmacc_lmul_legal.eq(1),
                            ]
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(0):
                                    m.d.comb += wmacc_dest_regs.eq(2)
                                with m.Case(1):
                                    m.d.comb += [wmacc_source_regs.eq(2),
                                                 wmacc_dest_regs.eq(4)]
                                with m.Case(2):
                                    m.d.comb += [wmacc_source_regs.eq(4),
                                                 wmacc_dest_regs.eq(8)]
                                with m.Case(3, 4):
                                    m.d.comb += wmacc_lmul_legal.eq(0)
                            wmacc_vs2_no_overlap = (
                                (IS.rd + wmacc_dest_regs <= IS.rs2) |
                                (IS.rs2 + wmacc_source_regs <= IS.rd))
                            wmacc_vs2_high_overlap = (
                                (IS.rs2 + wmacc_source_regs) ==
                                (IS.rd + wmacc_dest_regs))
                            wmacc_vs1_no_overlap = (
                                (IS.rd + wmacc_dest_regs <= IS.rs1) |
                                (IS.rs1 + wmacc_source_regs <= IS.rd))
                            wmacc_vs1_high_overlap = (
                                (IS.rs1 + wmacc_source_regs) ==
                                (IS.rd + wmacc_dest_regs))
                            m.d.comb += wmacc_group_legal.eq(
                                wmacc_lmul_legal &
                                ((IS.rd & (wmacc_dest_regs - 1)) == 0) &
                                ((IS.rs2 & (wmacc_source_regs - 1)) == 0) &
                                (~wmacc_is_vv |
                                 ((IS.rs1 & (wmacc_source_regs - 1)) == 0)) &
                                (IS.rd <= (32 - wmacc_dest_regs)) &
                                (IS.rs2 <= (32 - wmacc_source_regs)) &
                                (~wmacc_is_vv |
                                 (IS.rs1 <= (32 - wmacc_source_regs))) &
                                (wmacc_vs2_no_overlap | wmacc_vs2_high_overlap) &
                                (~wmacc_is_vv | wmacc_vs1_no_overlap |
                                 wmacc_vs1_high_overlap) &
                                (vm | (IS.rd != 0))
                            )
                            with m.If(~wmacc_group_legal |
                                      csr_vtype[self.xlen - 1]):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                with m.If(csr_vstart < csr_vl):
                                    for dest_reg_offset in range(8):
                                        with m.If(wmacc_dest_regs > dest_reg_offset):
                                            wmacc_reg_data = Signal(128)
                                            m.d.comb += wmacc_reg_data.eq(
                                                vregs[IS.rd + dest_reg_offset])
                                            with m.Switch(csr_vtype[3:6]):
                                                for vsew, source_width in enumerate((8, 16, 32)):
                                                    with m.Case(vsew):
                                                        result_width = source_width * 2
                                                        source_elements = 128 // source_width
                                                        result_elements = 128 // result_width
                                                        wmacc_elements = []
                                                        for element_offset in range(result_elements):
                                                            global_element = (
                                                                dest_reg_offset * result_elements +
                                                                element_offset)
                                                            source_reg_offset = (
                                                                global_element // source_elements)
                                                            source_element_offset = (
                                                                global_element % source_elements)
                                                            source_lo = (
                                                                source_element_offset * source_width)
                                                            source_hi = source_lo + source_width
                                                            result_lo = element_offset * result_width
                                                            result_hi = result_lo + result_width
                                                            lhs = vregs[
                                                                IS.rs2 + source_reg_offset][
                                                                    source_lo:source_hi]
                                                            vector_rhs = vregs[
                                                                IS.rs1 + source_reg_offset][
                                                                    source_lo:source_hi]
                                                            rhs = Mux(wmacc_is_vv, vector_rhs,
                                                                      ex1_a[0:source_width])
                                                            accumulator = vregs[
                                                                IS.rd + dest_reg_offset][
                                                                    result_lo:result_hi]
                                                            lhs_mag = Signal(source_width)
                                                            rhs_mag = Signal(source_width)
                                                            unsigned_product = Signal(result_width)
                                                            signed_product = Signal(result_width)
                                                            signed_unsigned_product = Signal(result_width)
                                                            unsigned_signed_product = Signal(result_width)
                                                            selected_product = Signal(result_width)
                                                            wmacc_result = Signal(result_width)
                                                            next_element = Signal(result_width)
                                                            m.d.comb += [
                                                                lhs_mag.eq(Mux(lhs[source_width - 1],
                                                                               (~lhs) + 1, lhs)),
                                                                rhs_mag.eq(Mux(rhs[source_width - 1],
                                                                               (~rhs) + 1, rhs)),
                                                                unsigned_product.eq(lhs * rhs),
                                                                signed_product.eq(Mux(
                                                                    lhs[source_width - 1] ^
                                                                    rhs[source_width - 1],
                                                                    -(lhs_mag * rhs_mag),
                                                                    lhs_mag * rhs_mag)),
                                                                signed_unsigned_product.eq(Mux(
                                                                    lhs[source_width - 1],
                                                                    -(lhs_mag * rhs), lhs_mag * rhs)),
                                                                unsigned_signed_product.eq(Mux(
                                                                    rhs[source_width - 1],
                                                                    -(lhs * rhs_mag), lhs * rhs_mag)),
                                                                selected_product.eq(unsigned_product),
                                                                wmacc_result.eq(
                                                                    accumulator + selected_product),
                                                                next_element.eq(accumulator),
                                                            ]
                                                            with m.If(is_vwmacc):
                                                                m.d.comb += selected_product.eq(
                                                                    signed_product)
                                                            with m.Elif(is_vwmaccsu):
                                                                m.d.comb += selected_product.eq(
                                                                    signed_unsigned_product)
                                                            with m.Elif(is_vwmaccus):
                                                                m.d.comb += selected_product.eq(
                                                                    unsigned_signed_product)
                                                            element_enabled = (
                                                                vm | vregs[0][global_element])
                                                            with m.If((csr_vstart <= global_element) &
                                                                      (global_element < csr_vl)):
                                                                with m.If(element_enabled):
                                                                    m.d.comb += next_element.eq(
                                                                        wmacc_result)
                                                                with m.Elif(csr_vtype[7]):
                                                                    m.d.comb += next_element.eq(
                                                                        C(-1, result_width))
                                                            with m.Elif((global_element >= csr_vl) &
                                                                        (global_element < csr_vlmax) &
                                                                        csr_vtype[6]):
                                                                m.d.comb += next_element.eq(
                                                                    C(-1, result_width))
                                                            wmacc_elements.append(next_element)
                                                        m.d.comb += wmacc_reg_data.eq(
                                                            Cat(*wmacc_elements))
                                            m.d.sync += vregs[
                                                IS.rd + dest_reg_offset].eq(wmacc_reg_data)
                                m.d.sync += csr_vstart.eq(0)
                        is_vmulhu = ((vfunct6 == 0x24) &
                                     ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vmul = ((vfunct6 == 0x25) &
                                   ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vmulhsu = ((vfunct6 == 0x26) &
                                      ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vmulh = ((vfunct6 == 0x27) &
                                    ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        with m.If(is_vmulhu | is_vmul | is_vmulhsu | is_vmulh):
                            mul_group_regs = Signal(4)
                            mul_is_vv = IS.funct3 == 0b010
                            mul_group_aligned = Signal()
                            m.d.comb += mul_group_regs.eq(1)
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += mul_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += mul_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += mul_group_regs.eq(8)
                            m.d.comb += mul_group_aligned.eq(
                                (csr_vtype[0:3] != 4) &
                                ((IS.rd & (mul_group_regs - 1)) == 0) &
                                ((IS.rs2 & (mul_group_regs - 1)) == 0) &
                                (~mul_is_vv | ((IS.rs1 & (mul_group_regs - 1)) == 0)) &
                                (IS.rd <= (32 - mul_group_regs)) &
                                (IS.rs2 <= (32 - mul_group_regs)) &
                                (~mul_is_vv | (IS.rs1 <= (32 - mul_group_regs))))
                            with m.If(~mul_group_aligned | csr_vtype[self.xlen - 1]):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                with m.If(csr_vstart < csr_vl):
                                    for reg_offset in range(8):
                                        with m.If(mul_group_regs > reg_offset):
                                            mul_reg_data = Signal(128)
                                            m.d.comb += mul_reg_data.eq(vregs[IS.rd + reg_offset])
                                            with m.Switch(csr_vtype[3:6]):
                                                for vsew, element_width in enumerate((8, 16, 32)):
                                                    with m.Case(vsew):
                                                        mul_elements = []
                                                        element_count = 128 // element_width
                                                        for element_offset in range(element_count):
                                                            global_element = (reg_offset * element_count +
                                                                              element_offset)
                                                            lo = element_offset * element_width
                                                            hi = lo + element_width
                                                            old_element = vregs[IS.rd + reg_offset][lo:hi]
                                                            lhs = vregs[IS.rs2 + reg_offset][lo:hi]
                                                            vector_rhs = vregs[IS.rs1 + reg_offset][lo:hi]
                                                            rhs = Mux(mul_is_vv, vector_rhs,
                                                                      ex1_a[:element_width])
                                                            lhs_abs = Signal(element_width)
                                                            rhs_abs = Signal(element_width)
                                                            unsigned_product = Signal(2 * element_width)
                                                            signed_mag_product = Signal(2 * element_width)
                                                            mixed_mag_product = Signal(2 * element_width)
                                                            signed_product = Signal(2 * element_width)
                                                            mixed_product = Signal(2 * element_width)
                                                            mul_result = Signal(element_width)
                                                            next_element = Signal(element_width)
                                                            m.d.comb += [
                                                                lhs_abs.eq(Mux(
                                                                    lhs[element_width - 1], -lhs, lhs)),
                                                                rhs_abs.eq(Mux(
                                                                    rhs[element_width - 1], -rhs, rhs)),
                                                                unsigned_product.eq(lhs * rhs),
                                                                signed_mag_product.eq(lhs_abs * rhs_abs),
                                                                mixed_mag_product.eq(lhs_abs * rhs),
                                                                signed_product.eq(Mux(
                                                                    lhs[element_width - 1] ^
                                                                    rhs[element_width - 1],
                                                                    -signed_mag_product,
                                                                    signed_mag_product)),
                                                                mixed_product.eq(Mux(
                                                                    lhs[element_width - 1],
                                                                    -mixed_mag_product,
                                                                    mixed_mag_product)),
                                                                mul_result.eq(unsigned_product[:element_width]),
                                                                next_element.eq(old_element),
                                                            ]
                                                            with m.If(is_vmulhu):
                                                                m.d.comb += mul_result.eq(
                                                                    unsigned_product[element_width:])
                                                            with m.Elif(is_vmulhsu):
                                                                m.d.comb += mul_result.eq(
                                                                    mixed_product[element_width:])
                                                            with m.Elif(is_vmulh):
                                                                m.d.comb += mul_result.eq(
                                                                    signed_product[element_width:])
                                                            element_enabled = vm | vregs[0][global_element]
                                                            with m.If((csr_vstart <= global_element) &
                                                                      (global_element < csr_vl)):
                                                                with m.If(element_enabled):
                                                                    m.d.comb += next_element.eq(mul_result)
                                                                with m.Elif(csr_vtype[7]):
                                                                    m.d.comb += next_element.eq(
                                                                        C(-1, element_width))
                                                            with m.Elif((global_element >= csr_vl) &
                                                                        (global_element < csr_vlmax) &
                                                                        csr_vtype[6]):
                                                                m.d.comb += next_element.eq(
                                                                    C(-1, element_width))
                                                            mul_elements.append(next_element)
                                                        m.d.comb += mul_reg_data.eq(Cat(*mul_elements))
                                            m.d.sync += vregs[IS.rd + reg_offset].eq(mul_reg_data)
                                m.d.sync += csr_vstart.eq(0)
                        is_vmadd = ((vfunct6 == 0x29) &
                                    ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vnmsub = ((vfunct6 == 0x2B) &
                                     ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vmacc = ((vfunct6 == 0x2D) &
                                    ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        is_vnmsac = ((vfunct6 == 0x2F) &
                                     ((IS.funct3 == 0b010) | (IS.funct3 == 0b110)))
                        with m.If(is_vmadd | is_vnmsub | is_vmacc | is_vnmsac):
                            madd_group_regs = Signal(4)
                            madd_is_vv = IS.funct3 == 0b010
                            madd_group_aligned = Signal()
                            m.d.comb += madd_group_regs.eq(1)
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += madd_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += madd_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += madd_group_regs.eq(8)
                            m.d.comb += madd_group_aligned.eq(
                                (csr_vtype[0:3] != 4) &
                                ((IS.rd & (madd_group_regs - 1)) == 0) &
                                ((IS.rs2 & (madd_group_regs - 1)) == 0) &
                                (~madd_is_vv | ((IS.rs1 & (madd_group_regs - 1)) == 0)) &
                                (IS.rd <= (32 - madd_group_regs)) &
                                (IS.rs2 <= (32 - madd_group_regs)) &
                                (~madd_is_vv | (IS.rs1 <= (32 - madd_group_regs))))
                            with m.If(~madd_group_aligned | csr_vtype[self.xlen - 1]):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                with m.If(csr_vstart < csr_vl):
                                    for reg_offset in range(8):
                                        with m.If(madd_group_regs > reg_offset):
                                            madd_reg_data = Signal(128)
                                            m.d.comb += madd_reg_data.eq(
                                                vregs[IS.rd + reg_offset])
                                            with m.Switch(csr_vtype[3:6]):
                                                for vsew, element_width in enumerate((8, 16, 32)):
                                                    with m.Case(vsew):
                                                        madd_elements = []
                                                        element_count = 128 // element_width
                                                        for element_offset in range(element_count):
                                                            global_element = (reg_offset * element_count +
                                                                              element_offset)
                                                            lo = element_offset * element_width
                                                            hi = lo + element_width
                                                            old_element = vregs[IS.rd + reg_offset][lo:hi]
                                                            vs2_element = vregs[IS.rs2 + reg_offset][lo:hi]
                                                            vector_operand = vregs[IS.rs1 + reg_offset][lo:hi]
                                                            operand = Mux(madd_is_vv, vector_operand,
                                                                          ex1_a[:element_width])
                                                            multiplicand = Mux(
                                                                is_vmadd | is_vnmsub,
                                                                old_element, vs2_element)
                                                            product = Signal(2 * element_width)
                                                            madd_result = Signal(element_width)
                                                            next_element = Signal(element_width)
                                                            m.d.comb += [
                                                                product.eq(operand * multiplicand),
                                                                madd_result.eq(product[:element_width] +
                                                                               old_element),
                                                                next_element.eq(old_element),
                                                            ]
                                                            with m.If(is_vnmsac):
                                                                m.d.comb += madd_result.eq(
                                                                    old_element -
                                                                    product[:element_width])
                                                            with m.Elif(is_vmadd):
                                                                m.d.comb += madd_result.eq(
                                                                    product[:element_width] +
                                                                    vs2_element)
                                                            with m.Elif(is_vnmsub):
                                                                m.d.comb += madd_result.eq(
                                                                    vs2_element -
                                                                    product[:element_width])
                                                            element_enabled = vm | vregs[0][global_element]
                                                            with m.If((csr_vstart <= global_element) &
                                                                      (global_element < csr_vl)):
                                                                with m.If(element_enabled):
                                                                    m.d.comb += next_element.eq(madd_result)
                                                                with m.Elif(csr_vtype[7]):
                                                                    m.d.comb += next_element.eq(
                                                                        C(-1, element_width))
                                                            with m.Elif((global_element >= csr_vl) &
                                                                        (global_element < csr_vlmax) &
                                                                        csr_vtype[6]):
                                                                m.d.comb += next_element.eq(
                                                                    C(-1, element_width))
                                                            madd_elements.append(next_element)
                                                        m.d.comb += madd_reg_data.eq(
                                                            Cat(*madd_elements))
                                            m.d.sync += vregs[IS.rd + reg_offset].eq(
                                                madd_reg_data)
                                m.d.sync += csr_vstart.eq(0)
                        is_vcpop = ((vfunct6 == 0x10) & (IS.funct3 == 0b010) &
                                    (IS.rs1 == 0b10000))
                        is_vfirst = ((vfunct6 == 0x10) & (IS.funct3 == 0b010) &
                                     (IS.rs1 == 0b10001))
                        with m.If(is_vcpop | is_vfirst):
                            with m.If(csr_vtype[self.xlen - 1] | (csr_vstart != 0)):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                active_mask_bits = [
                                    vregs[IS.rs2][index] & (index < csr_vl) &
                                    (vm | vregs[0][index])
                                    for index in range(128)
                                ]
                                popcount_terms = active_mask_bits
                                while len(popcount_terms) > 1:
                                    popcount_terms = [
                                        popcount_terms[index] + popcount_terms[index + 1]
                                        if index + 1 < len(popcount_terms)
                                        else popcount_terms[index]
                                        for index in range(0, len(popcount_terms), 2)
                                    ]
                                first_nodes = [
                                    (active_mask_bits[index], C(index, self.xlen))
                                    for index in range(128)
                                ]
                                while len(first_nodes) > 1:
                                    next_nodes = []
                                    for index in range(0, len(first_nodes), 2):
                                        left_valid, left_index = first_nodes[index]
                                        right_valid, right_index = first_nodes[index + 1]
                                        next_nodes.append((
                                            left_valid | right_valid,
                                            Mux(left_valid, left_index, right_index),
                                        ))
                                    first_nodes = next_nodes
                                first_valid, first_value = first_nodes[0]
                                first_index = Mux(
                                    first_valid, first_value, C(-1, self.xlen))
                                m.d.comb += [
                                    wb_en.eq(IS.rd != 0),
                                    wb_data.eq(Mux(is_vcpop, popcount_terms[0],
                                                   first_index)),
                                ]
                                m.d.sync += csr_vstart.eq(0)
                        is_vmsbf = ((vfunct6 == 0x14) &
                                    (IS.funct3 == 0b010) & (IS.rs1 == 0b00001))
                        is_vmsof = ((vfunct6 == 0x14) &
                                    (IS.funct3 == 0b010) & (IS.rs1 == 0b00010))
                        is_vmsif = ((vfunct6 == 0x14) &
                                    (IS.funct3 == 0b010) & (IS.rs1 == 0b00011))
                        with m.If(is_vmsbf | is_vmsof | is_vmsif):
                            mask_prefix_legal = Signal()
                            m.d.comb += mask_prefix_legal.eq(
                                ~csr_vtype[self.xlen - 1] &
                                (csr_vstart == 0) &
                                (IS.rd != IS.rs2) &
                                (vm | (IS.rd != 0)))
                            with m.If(~mask_prefix_legal):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                mask_prefix_source = [
                                    vregs[IS.rs2][index] &
                                    (vm | vregs[0][index])
                                    for index in range(128)
                                ]
                                mask_prefix_bits = []
                                for index in range(128):
                                    prior_terms = mask_prefix_source[:index]
                                    while len(prior_terms) > 1:
                                        prior_terms = [
                                            prior_terms[term] | prior_terms[term + 1]
                                            if term + 1 < len(prior_terms)
                                            else prior_terms[term]
                                            for term in range(0, len(prior_terms), 2)
                                        ]
                                    found_prior = (prior_terms[0]
                                                   if prior_terms else C(0))
                                    prefix_value = Mux(
                                        is_vmsbf,
                                        ~(found_prior | mask_prefix_source[index]),
                                        Mux(is_vmsif, ~found_prior,
                                            ~found_prior & mask_prefix_source[index]))
                                    element_active = vm | vregs[0][index]
                                    mask_prefix_bits.append(Mux(
                                        index < csr_vl,
                                        Mux(element_active, prefix_value,
                                            Mux(csr_vtype[7], 1,
                                                vregs[IS.rd][index])),
                                        1))
                                m.d.sync += [
                                    vregs[IS.rd].eq(Cat(*mask_prefix_bits)),
                                    csr_vstart.eq(0),
                                ]
                        is_mask_logical = ((vfunct6 >= 0x18) &
                                           (vfunct6 <= 0x1F) &
                                           (IS.funct3 == 0b010))
                        with m.If(is_mask_logical):
                            with m.If(csr_vtype[self.xlen - 1] | ~vm):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                mask_logical_result = Signal(128)
                                with m.Switch(vfunct6):
                                    with m.Case(0x18):  # VMANDN.MM
                                        m.d.comb += mask_logical_result.eq(
                                            vregs[IS.rs2] & ~vregs[IS.rs1])
                                    with m.Case(0x19):  # VMAND.MM
                                        m.d.comb += mask_logical_result.eq(
                                            vregs[IS.rs2] & vregs[IS.rs1])
                                    with m.Case(0x1A):  # VMOR.MM
                                        m.d.comb += mask_logical_result.eq(
                                            vregs[IS.rs2] | vregs[IS.rs1])
                                    with m.Case(0x1B):  # VMXOR.MM
                                        m.d.comb += mask_logical_result.eq(
                                            vregs[IS.rs2] ^ vregs[IS.rs1])
                                    with m.Case(0x1C):  # VMORN.MM
                                        m.d.comb += mask_logical_result.eq(
                                            vregs[IS.rs2] | ~vregs[IS.rs1])
                                    with m.Case(0x1D):  # VMNAND.MM
                                        m.d.comb += mask_logical_result.eq(
                                            ~(vregs[IS.rs2] & vregs[IS.rs1]))
                                    with m.Case(0x1E):  # VMNOR.MM
                                        m.d.comb += mask_logical_result.eq(
                                            ~(vregs[IS.rs2] | vregs[IS.rs1]))
                                    with m.Case(0x1F):  # VMXNOR.MM
                                        m.d.comb += mask_logical_result.eq(
                                            ~(vregs[IS.rs2] ^ vregs[IS.rs1]))
                                mask_logical_bits = [
                                    Mux(index < csr_vstart,
                                        vregs[IS.rd][index],
                                        Mux(index < csr_vl,
                                            mask_logical_result[index], 1))
                                    for index in range(128)
                                ]
                                m.d.sync += [
                                    vregs[IS.rd].eq(Mux(
                                        csr_vstart < csr_vl,
                                        Cat(*mask_logical_bits),
                                        vregs[IS.rd])),
                                    csr_vstart.eq(0),
                                ]
                        is_viota = ((vfunct6 == 0x14) & (IS.funct3 == 0b010) &
                                    (IS.rs1 == 0b10000))
                        with m.If(is_viota):
                            iota_group_regs = Signal(4)
                            iota_group_aligned = Signal()
                            iota_source_overlap = Signal()
                            m.d.comb += iota_group_regs.eq(1)
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += iota_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += iota_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += iota_group_regs.eq(8)
                            m.d.comb += [
                                iota_source_overlap.eq(
                                    (IS.rs2 >= IS.rd) &
                                    (IS.rs2 < (IS.rd + iota_group_regs))),
                                iota_group_aligned.eq(
                                    (csr_vtype[0:3] != 4) &
                                    ((IS.rd & (iota_group_regs - 1)) == 0) &
                                    (IS.rd <= (32 - iota_group_regs)) &
                                    ~iota_source_overlap &
                                    (vm | (IS.rd != 0))),
                            ]
                            with m.If(~iota_group_aligned |
                                      csr_vtype[self.xlen - 1] |
                                      (csr_vstart != 0)):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                with m.If(csr_vl != 0):
                                    for reg_offset in range(8):
                                        with m.If(iota_group_regs > reg_offset):
                                            iota_reg_data = Signal(128)
                                            m.d.comb += iota_reg_data.eq(
                                                vregs[IS.rd + reg_offset])
                                            with m.Switch(csr_vtype[3:6]):
                                                for vsew, element_width in enumerate((8, 16, 32)):
                                                    with m.Case(vsew):
                                                        iota_elements = []
                                                        element_count = 128 // element_width
                                                        for element_offset in range(element_count):
                                                            global_element = (reg_offset * element_count +
                                                                              element_offset)
                                                            lo = element_offset * element_width
                                                            hi = lo + element_width
                                                            old_element = vregs[IS.rd + reg_offset][lo:hi]
                                                            prefix_terms = [
                                                                vregs[IS.rs2][prior] &
                                                                (vm | vregs[0][prior])
                                                                for prior in range(global_element)
                                                            ]
                                                            while len(prefix_terms) > 1:
                                                                prefix_terms = [
                                                                    prefix_terms[index] +
                                                                    prefix_terms[index + 1]
                                                                    if index + 1 < len(prefix_terms)
                                                                    else prefix_terms[index]
                                                                    for index in range(
                                                                        0, len(prefix_terms), 2)
                                                                ]
                                                            prefix_value = (prefix_terms[0]
                                                                            if prefix_terms
                                                                            else C(0, element_width))
                                                            prefix_count = Signal(element_width)
                                                            next_element = Signal(element_width)
                                                            m.d.comb += [
                                                                prefix_count.eq(prefix_value),
                                                                next_element.eq(old_element),
                                                            ]
                                                            with m.If(global_element < csr_vl):
                                                                with m.If(vm | vregs[0][global_element]):
                                                                    m.d.comb += next_element.eq(
                                                                        prefix_count)
                                                                with m.Elif(csr_vtype[7]):
                                                                    m.d.comb += next_element.eq(
                                                                        C(-1, element_width))
                                                            with m.Elif((global_element < csr_vlmax) &
                                                                        csr_vtype[6]):
                                                                m.d.comb += next_element.eq(
                                                                    C(-1, element_width))
                                                            iota_elements.append(next_element)
                                                        m.d.comb += iota_reg_data.eq(
                                                            Cat(*iota_elements))
                                            m.d.sync += vregs[IS.rd + reg_offset].eq(
                                                iota_reg_data)
                                m.d.sync += csr_vstart.eq(0)
                        is_vid = ((vfunct6 == 0x14) & (IS.funct3 == 0b010) &
                                  (IS.rs1 == 0b10001) & (IS.rs2 == 0))
                        with m.If(is_vid):
                            vid_group_regs = Signal(4)
                            vid_group_aligned = Signal()
                            m.d.comb += vid_group_regs.eq(1)
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += vid_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += vid_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += vid_group_regs.eq(8)
                            m.d.comb += vid_group_aligned.eq(
                                (csr_vtype[0:3] != 4) &
                                ((IS.rd & (vid_group_regs - 1)) == 0) &
                                (IS.rd <= (32 - vid_group_regs)) &
                                (vm | (IS.rd != 0)))
                            with m.If(~vid_group_aligned | csr_vtype[self.xlen - 1]):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                with m.If(csr_vstart < csr_vl):
                                    for reg_offset in range(8):
                                        with m.If(vid_group_regs > reg_offset):
                                            vid_reg_data = Signal(128)
                                            m.d.comb += vid_reg_data.eq(
                                                vregs[IS.rd + reg_offset])
                                            with m.Switch(csr_vtype[3:6]):
                                                for vsew, element_width in enumerate((8, 16, 32)):
                                                    with m.Case(vsew):
                                                        vid_elements = []
                                                        element_count = 128 // element_width
                                                        for element_offset in range(element_count):
                                                            global_element = (reg_offset * element_count +
                                                                              element_offset)
                                                            lo = element_offset * element_width
                                                            hi = lo + element_width
                                                            old_element = vregs[IS.rd + reg_offset][lo:hi]
                                                            next_element = Signal(element_width)
                                                            m.d.comb += next_element.eq(old_element)
                                                            element_enabled = vm | vregs[0][global_element]
                                                            with m.If((csr_vstart <= global_element) &
                                                                      (global_element < csr_vl)):
                                                                with m.If(element_enabled):
                                                                    m.d.comb += next_element.eq(
                                                                        C(global_element,
                                                                          element_width))
                                                                with m.Elif(csr_vtype[7]):
                                                                    m.d.comb += next_element.eq(
                                                                        C(-1, element_width))
                                                            with m.Elif((global_element >= csr_vl) &
                                                                        (global_element < csr_vlmax) &
                                                                        csr_vtype[6]):
                                                                m.d.comb += next_element.eq(
                                                                    C(-1, element_width))
                                                            vid_elements.append(next_element)
                                                        m.d.comb += vid_reg_data.eq(
                                                            Cat(*vid_elements))
                                            m.d.sync += vregs[IS.rd + reg_offset].eq(
                                                vid_reg_data)
                                m.d.sync += csr_vstart.eq(0)
                        is_vslide1up = ((vfunct6 == 0x0E) &
                                        (IS.funct3 == 0b110))
                        is_vslide1down = ((vfunct6 == 0x0F) &
                                          (IS.funct3 == 0b110))
                        with m.If(is_vslide1up | is_vslide1down):
                            slide1_group_regs = Signal(4)
                            slide1_group_legal = Signal()
                            slide1_groups_overlap = Signal()
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(0):
                                    m.d.comb += slide1_group_regs.eq(1)
                                with m.Case(1):
                                    m.d.comb += slide1_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += slide1_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += slide1_group_regs.eq(8)
                                with m.Default():
                                    m.d.comb += slide1_group_regs.eq(0)
                            m.d.comb += [
                                slide1_groups_overlap.eq(
                                    (IS.rd < (IS.rs2 + slide1_group_regs)) &
                                    (IS.rs2 < (IS.rd + slide1_group_regs))),
                                slide1_group_legal.eq(
                                    ~csr_vtype[self.xlen - 1] &
                                    (slide1_group_regs != 0) &
                                    ((IS.rd & (slide1_group_regs - 1)) == 0) &
                                    ((IS.rs2 & (slide1_group_regs - 1)) == 0) &
                                    (IS.rd <= (32 - slide1_group_regs)) &
                                    (IS.rs2 <= (32 - slide1_group_regs)) &
                                    (~is_vslide1up | ~slide1_groups_overlap) &
                                    (vm | (IS.rd != 0))),
                            ]
                            with m.If(~slide1_group_legal):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                slide1_source = Signal(1024)
                                m.d.comb += slide1_source.eq(
                                    Cat(*[vregs[IS.rs2 + index]
                                          for index in range(8)]))
                                with m.If(csr_vstart < csr_vl):
                                    for reg_offset in range(8):
                                        with m.If(reg_offset < slide1_group_regs):
                                            with m.Switch(csr_vtype[3:6]):
                                                for sew_code, element_width in ((0, 8),
                                                                                (1, 16),
                                                                                (2, 32)):
                                                    with m.Case(sew_code):
                                                        elements_per_reg = 128 // element_width
                                                        slide1_elements = []
                                                        for element in range(elements_per_reg):
                                                            global_element = (reg_offset *
                                                                              elements_per_reg +
                                                                              element)
                                                            old_element = vregs[
                                                                IS.rd + reg_offset
                                                            ].word_select(element,
                                                                          element_width)
                                                            source_up = slide1_source.word_select(
                                                                max(global_element - 1, 0),
                                                                element_width)
                                                            source_down = slide1_source.word_select(
                                                                min(global_element + 1, 127),
                                                                element_width)
                                                            selected_element = Signal(
                                                                element_width)
                                                            with m.If(is_vslide1up):
                                                                if global_element == 0:
                                                                    m.d.comb += selected_element.eq(
                                                                        ex1_a[:element_width])
                                                                else:
                                                                    m.d.comb += selected_element.eq(
                                                                        source_up)
                                                            with m.Else():
                                                                with m.If(global_element ==
                                                                          (csr_vl - 1)):
                                                                    m.d.comb += selected_element.eq(
                                                                        ex1_a[:element_width])
                                                                with m.Else():
                                                                    m.d.comb += selected_element.eq(
                                                                        source_down)
                                                            mask_active = (vm |
                                                                           vregs[0][global_element])
                                                            next_element = Signal(element_width)
                                                            with m.If(global_element < csr_vstart):
                                                                m.d.comb += next_element.eq(
                                                                    old_element)
                                                            with m.Elif(global_element < csr_vl):
                                                                with m.If(mask_active):
                                                                    m.d.comb += next_element.eq(
                                                                        selected_element)
                                                                with m.Else():
                                                                    m.d.comb += next_element.eq(
                                                                        Mux(csr_vtype[7],
                                                                            -1,
                                                                            old_element))
                                                            with m.Else():
                                                                m.d.comb += next_element.eq(
                                                                    Mux(csr_vtype[6],
                                                                        -1,
                                                                        old_element))
                                                            slide1_elements.append(next_element)
                                                        m.d.sync += vregs[
                                                            IS.rd + reg_offset
                                                        ].eq(Cat(*slide1_elements))
                                m.d.sync += csr_vstart.eq(0)

                        is_vfslide1up = ((vfunct6 == 0x0E) &
                                         (IS.funct3 == 0b101))
                        is_vfslide1down = ((vfunct6 == 0x0F) &
                                           (IS.funct3 == 0b101))
                        with m.If(is_vfslide1up | is_vfslide1down):
                            vfslide1_group_regs = Signal(4)
                            vfslide1_width_legal = Signal()
                            vfslide1_group_legal = Signal()
                            vfslide1_groups_overlap = Signal()
                            vfslide1_scalar = Signal(64)
                            m.d.comb += [
                                vfslide1_group_regs.eq(1),
                                vfslide1_width_legal.eq(Mux(
                                    csr_vtype[3:6] == 2, self.enable_fp32,
                                    Mux(csr_vtype[3:6] == 3,
                                        self.enable_fp64, 0))),
                                vfslide1_scalar.eq(fp_ex1_a),
                            ]
                            with m.If(csr_vtype[3:6] == 2):
                                m.d.comb += vfslide1_scalar.eq(Mux(
                                    fp_ex1_a[32:64].all(), fp_ex1_a,
                                    C(0xFFFFFFFF7FC00000, 64)))
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += vfslide1_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += vfslide1_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += vfslide1_group_regs.eq(8)
                            m.d.comb += [
                                vfslide1_groups_overlap.eq(
                                    (IS.rd < (IS.rs2 + vfslide1_group_regs)) &
                                    (IS.rs2 < (IS.rd + vfslide1_group_regs))),
                                vfslide1_group_legal.eq(
                                    (csr_vtype[0:3] != 4) &
                                    ((IS.rd & (vfslide1_group_regs - 1)) == 0) &
                                    ((IS.rs2 & (vfslide1_group_regs - 1)) == 0) &
                                    (IS.rd <= (32 - vfslide1_group_regs)) &
                                    (IS.rs2 <= (32 - vfslide1_group_regs)) &
                                    (~is_vfslide1up | ~vfslide1_groups_overlap) &
                                    (vm | (IS.rd != 0))),
                            ]
                            with m.If(~vfslide1_width_legal |
                                      ~vfslide1_group_legal |
                                      csr_vtype[self.xlen - 1]):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                vfslide1_source = Signal(1024)
                                m.d.comb += vfslide1_source.eq(Cat(*[
                                    vregs[IS.rs2 + index] for index in range(8)
                                ]))
                                with m.If(csr_vstart < csr_vl):
                                    for reg_offset in range(8):
                                        with m.If(reg_offset < vfslide1_group_regs):
                                            vfslide1_reg_data = Signal(128)
                                            m.d.comb += vfslide1_reg_data.eq(
                                                vregs[IS.rd + reg_offset])
                                            with m.Switch(csr_vtype[3:6]):
                                                for vsew, element_width in ((2, 32),
                                                                            (3, 64)):
                                                    with m.Case(vsew):
                                                        elements_per_reg = 128 // element_width
                                                        max_source_element = 1024 // element_width - 1
                                                        vfslide1_elements = []
                                                        for element_offset in range(
                                                                elements_per_reg):
                                                            global_element = (
                                                                reg_offset * elements_per_reg +
                                                                element_offset)
                                                            lo = element_offset * element_width
                                                            hi = lo + element_width
                                                            old_element = vregs[
                                                                IS.rd + reg_offset][lo:hi]
                                                            source_up = vfslide1_source.word_select(
                                                                max(global_element - 1, 0),
                                                                element_width)
                                                            source_down = vfslide1_source.word_select(
                                                                min(global_element + 1,
                                                                    max_source_element),
                                                                element_width)
                                                            selected_element = Signal(
                                                                element_width)
                                                            next_element = Signal(element_width)
                                                            m.d.comb += [
                                                                selected_element.eq(0),
                                                                next_element.eq(old_element),
                                                            ]
                                                            with m.If(is_vfslide1up):
                                                                if global_element == 0:
                                                                    m.d.comb += selected_element.eq(
                                                                        vfslide1_scalar[0:element_width])
                                                                else:
                                                                    m.d.comb += selected_element.eq(
                                                                        source_up)
                                                            with m.Else():
                                                                with m.If(global_element ==
                                                                          (csr_vl - 1)):
                                                                    m.d.comb += selected_element.eq(
                                                                        vfslide1_scalar[0:element_width])
                                                                with m.Else():
                                                                    m.d.comb += selected_element.eq(
                                                                        source_down)
                                                            element_enabled = (
                                                                vm | vregs[0][global_element])
                                                            with m.If((csr_vstart <= global_element) &
                                                                      (global_element < csr_vl)):
                                                                with m.If(element_enabled):
                                                                    m.d.comb += next_element.eq(
                                                                        selected_element)
                                                                with m.Elif(csr_vtype[7]):
                                                                    m.d.comb += next_element.eq(
                                                                        C(-1, element_width))
                                                            with m.Elif((global_element >= csr_vl) &
                                                                        (global_element < csr_vlmax) &
                                                                        csr_vtype[6]):
                                                                m.d.comb += next_element.eq(
                                                                    C(-1, element_width))
                                                            vfslide1_elements.append(next_element)
                                                        m.d.comb += vfslide1_reg_data.eq(
                                                            Cat(*vfslide1_elements))
                                            m.d.sync += vregs[
                                                IS.rd + reg_offset].eq(vfslide1_reg_data)
                                m.d.sync += csr_vstart.eq(0)

                        is_vslideup = ((vfunct6 == 0x0E) &
                                       ((IS.funct3 == 0b100) |
                                        (IS.funct3 == 0b011)))
                        is_vslidedown = ((vfunct6 == 0x0F) &
                                         ((IS.funct3 == 0b100) |
                                          (IS.funct3 == 0b011)))
                        with m.If(is_vslideup | is_vslidedown):
                            slide_group_regs = Signal(4)
                            slide_group_legal = Signal()
                            slide_groups_overlap = Signal()
                            slide_offset = Signal(self.xlen)
                            m.d.comb += slide_group_regs.eq(1)
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += slide_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += slide_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += slide_group_regs.eq(8)
                            m.d.comb += [
                                slide_offset.eq(Mux(IS.funct3 == 0b100,
                                                    ex1_a, IS.rs1)),
                                slide_groups_overlap.eq(
                                    (IS.rd < (IS.rs2 + slide_group_regs)) &
                                    (IS.rs2 < (IS.rd + slide_group_regs))),
                                slide_group_legal.eq(
                                    ~csr_vtype[self.xlen - 1] &
                                    (csr_vtype[0:3] != 4) &
                                    ((IS.rd & (slide_group_regs - 1)) == 0) &
                                    ((IS.rs2 & (slide_group_regs - 1)) == 0) &
                                    (IS.rd <= (32 - slide_group_regs)) &
                                    (IS.rs2 <= (32 - slide_group_regs)) &
                                    (~is_vslideup | ~slide_groups_overlap) &
                                    (vm | (IS.rd != 0))),
                            ]
                            with m.If(~slide_group_legal):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                slide_source_bits = Cat(*[
                                    vregs[IS.rs2 + reg_offset]
                                    for reg_offset in range(8)
                                ])
                                with m.If(csr_vstart < csr_vl):
                                    for reg_offset in range(8):
                                        with m.If(slide_group_regs > reg_offset):
                                            slide_reg_data = Signal(128)
                                            m.d.comb += slide_reg_data.eq(
                                                vregs[IS.rd + reg_offset])
                                            with m.Switch(csr_vtype[3:6]):
                                                for vsew, element_width in enumerate(
                                                        (8, 16, 32)):
                                                    with m.Case(vsew):
                                                        slide_elements = []
                                                        elements_per_reg = 128 // element_width
                                                        for element_offset in range(
                                                                elements_per_reg):
                                                            global_element = (
                                                                reg_offset * elements_per_reg +
                                                                element_offset)
                                                            lo = element_offset * element_width
                                                            hi = lo + element_width
                                                            old_element = vregs[
                                                                IS.rd + reg_offset][lo:hi]
                                                            source_index = Signal(self.xlen)
                                                            source_valid = Signal()
                                                            source_element = Signal(element_width)
                                                            next_element = Signal(element_width)
                                                            m.d.comb += [
                                                                source_index.eq(Mux(
                                                                    is_vslideup,
                                                                    Mux(global_element >= slide_offset,
                                                                        global_element - slide_offset,
                                                                        0),
                                                                    global_element + slide_offset)),
                                                                source_valid.eq(Mux(
                                                                    is_vslideup,
                                                                    global_element >= slide_offset,
                                                                    (global_element + slide_offset) <
                                                                    csr_vlmax)),
                                                                source_element.eq(Mux(
                                                                    source_valid,
                                                                    slide_source_bits.word_select(
                                                                        source_index,
                                                                        element_width),
                                                                    0)),
                                                                next_element.eq(old_element),
                                                            ]
                                                            element_enabled = (
                                                                vm | vregs[0][global_element])
                                                            with m.If(
                                                                    (csr_vstart <= global_element) &
                                                                    (global_element < csr_vl)):
                                                                with m.If(element_enabled &
                                                                          source_valid):
                                                                    m.d.comb += next_element.eq(
                                                                        source_element)
                                                                with m.Elif(element_enabled &
                                                                            is_vslidedown):
                                                                    m.d.comb += next_element.eq(0)
                                                                with m.Elif(~element_enabled &
                                                                            csr_vtype[7]):
                                                                    m.d.comb += next_element.eq(
                                                                        C(-1, element_width))
                                                            with m.Elif(
                                                                    (global_element >= csr_vl) &
                                                                    (global_element < csr_vlmax) &
                                                                    csr_vtype[6]):
                                                                m.d.comb += next_element.eq(
                                                                    C(-1, element_width))
                                                            slide_elements.append(next_element)
                                                        m.d.comb += slide_reg_data.eq(
                                                            Cat(*slide_elements))
                                            m.d.sync += vregs[
                                                IS.rd + reg_offset].eq(slide_reg_data)
                                m.d.sync += csr_vstart.eq(0)
                        is_vcompress = ((vfunct6 == 0x17) &
                                        (IS.funct3 == 0b010))
                        with m.If(is_vcompress):
                            compress_group_regs = Signal(4)
                            compress_group_legal = Signal()
                            compress_source_overlap = Signal()
                            compress_mask_overlap = Signal()
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(0):
                                    m.d.comb += compress_group_regs.eq(1)
                                with m.Case(1):
                                    m.d.comb += compress_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += compress_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += compress_group_regs.eq(8)
                                with m.Default():
                                    m.d.comb += compress_group_regs.eq(0)
                            m.d.comb += [
                                compress_source_overlap.eq(
                                    (IS.rd < (IS.rs2 + compress_group_regs)) &
                                    (IS.rs2 < (IS.rd + compress_group_regs))),
                                compress_mask_overlap.eq(
                                    (IS.rs1 >= IS.rd) &
                                    (IS.rs1 < (IS.rd + compress_group_regs))),
                                compress_group_legal.eq(
                                    ~csr_vtype[self.xlen - 1] &
                                    (compress_group_regs != 0) &
                                    ((IS.rd & (compress_group_regs - 1)) == 0) &
                                    ((IS.rs2 & (compress_group_regs - 1)) == 0) &
                                    (IS.rd <= (32 - compress_group_regs)) &
                                    (IS.rs2 <= (32 - compress_group_regs)) &
                                    ~compress_source_overlap &
                                    ~compress_mask_overlap &
                                    vm & (csr_vstart == 0)),
                            ]
                            with m.If(~compress_group_legal):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                m.d.comb += vcompress_issue.eq(1)
                                with m.If(~vcompress_active):
                                    m.d.sync += [
                                        vcompress_active.eq(1),
                                        vcompress_tail.eq(0),
                                        vcompress_vd.eq(IS.rd),
                                        vcompress_vsew.eq(csr_vtype[3:6]),
                                        vcompress_vta.eq(csr_vtype[6]),
                                        vcompress_vl.eq(csr_vl),
                                        vcompress_vlmax.eq(csr_vlmax),
                                        vcompress_source_index.eq(0),
                                        vcompress_dest_index.eq(0),
                                        vcompress_tail_index.eq(0),
                                        vcompress_source.eq(Cat(*[
                                            vregs[IS.rs2 + reg_offset]
                                            for reg_offset in range(8)
                                        ])),
                                        vcompress_mask.eq(vregs[IS.rs1]),
                                    ]
                        is_vrgatherei16 = ((vfunct6 == 0x0E) &
                                          (IS.funct3 == 0b000))
                        is_vrgather = (((vfunct6 == 0x0C) &
                                       ((IS.funct3 == 0b000) |
                                        (IS.funct3 == 0b100) |
                                        (IS.funct3 == 0b011))) |
                                      is_vrgatherei16)
                        with m.If(is_vrgather):
                            gather_group_regs = Signal(4)
                            gather_index_group_regs = Signal(4)
                            gather_vector_indices = Signal()
                            gather_group_legal = Signal()
                            gather_source_overlap = Signal()
                            gather_index_overlap = Signal()
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(0):
                                    m.d.comb += gather_group_regs.eq(1)
                                with m.Case(1):
                                    m.d.comb += gather_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += gather_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += gather_group_regs.eq(8)
                                with m.Default():
                                    m.d.comb += gather_group_regs.eq(0)
                            m.d.comb += gather_vector_indices.eq(
                                IS.funct3 == 0b000)
                            with m.If(~gather_vector_indices):
                                m.d.comb += gather_index_group_regs.eq(0)
                            with m.Elif(~is_vrgatherei16):
                                m.d.comb += gather_index_group_regs.eq(
                                    gather_group_regs)
                            with m.Else():
                                with m.Switch(csr_vtype[3:6]):
                                    with m.Case(0):
                                        with m.Switch(csr_vtype[0:3]):
                                            with m.Case(0):
                                                m.d.comb += gather_index_group_regs.eq(2)
                                            with m.Case(1):
                                                m.d.comb += gather_index_group_regs.eq(4)
                                            with m.Case(2):
                                                m.d.comb += gather_index_group_regs.eq(8)
                                            with m.Default():
                                                m.d.comb += gather_index_group_regs.eq(0)
                                    with m.Case(1):
                                        m.d.comb += gather_index_group_regs.eq(
                                            gather_group_regs)
                                    with m.Case(2):
                                        with m.Switch(csr_vtype[0:3]):
                                            with m.Case(0, 1):
                                                m.d.comb += gather_index_group_regs.eq(1)
                                            with m.Case(2):
                                                m.d.comb += gather_index_group_regs.eq(2)
                                            with m.Case(3):
                                                m.d.comb += gather_index_group_regs.eq(4)
                                            with m.Default():
                                                m.d.comb += gather_index_group_regs.eq(0)
                                    with m.Default():
                                        m.d.comb += gather_index_group_regs.eq(0)
                            m.d.comb += [
                                gather_source_overlap.eq(
                                    (IS.rd < (IS.rs2 + gather_group_regs)) &
                                    (IS.rs2 < (IS.rd + gather_group_regs))),
                                gather_index_overlap.eq(
                                    gather_vector_indices &
                                    (IS.rd < (IS.rs1 +
                                              gather_index_group_regs)) &
                                    (IS.rs1 < (IS.rd + gather_group_regs))),
                                gather_group_legal.eq(
                                    ~csr_vtype[self.xlen - 1] &
                                    (gather_group_regs != 0) &
                                    ((IS.rd & (gather_group_regs - 1)) == 0) &
                                    ((IS.rs2 & (gather_group_regs - 1)) == 0) &
                                    (IS.rd <= (32 - gather_group_regs)) &
                                    (IS.rs2 <= (32 - gather_group_regs)) &
                                    (~gather_vector_indices |
                                     ((gather_index_group_regs != 0) &
                                      ((IS.rs1 &
                                        (gather_index_group_regs - 1)) == 0) &
                                      (IS.rs1 <=
                                       (32 - gather_index_group_regs)))) &
                                    ~gather_source_overlap &
                                    ~gather_index_overlap &
                                    (vm | (IS.rd != 0))),
                            ]
                            with m.If(~gather_group_legal):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                gather_source = Cat(*[
                                    vregs[IS.rs2 + reg_offset]
                                    for reg_offset in range(8)
                                ])
                                gather_indices = Cat(*[
                                    vregs[IS.rs1 + reg_offset]
                                    for reg_offset in range(8)
                                ])
                                with m.If(csr_vstart < csr_vl):
                                    for reg_offset in range(8):
                                        with m.If(reg_offset < gather_group_regs):
                                            with m.Switch(csr_vtype[3:6]):
                                                for vsew, element_width in enumerate(
                                                        (8, 16, 32)):
                                                    with m.Case(vsew):
                                                        elements_per_reg = 128 // element_width
                                                        gather_elements = []
                                                        for element_offset in range(
                                                                elements_per_reg):
                                                            global_element = (
                                                                reg_offset * elements_per_reg +
                                                                element_offset)
                                                            old_element = vregs[
                                                                IS.rd + reg_offset
                                                            ].word_select(element_offset,
                                                                          element_width)
                                                            gather_index = Signal(self.xlen)
                                                            with m.If(is_vrgatherei16):
                                                                m.d.comb += gather_index.eq(
                                                                    gather_indices.word_select(
                                                                        global_element, 16))
                                                            with m.Elif(IS.funct3 == 0b000):
                                                                m.d.comb += gather_index.eq(
                                                                    gather_indices.word_select(
                                                                        global_element,
                                                                        element_width))
                                                            with m.Elif(IS.funct3 == 0b100):
                                                                m.d.comb += gather_index.eq(ex1_a)
                                                            with m.Else():
                                                                m.d.comb += gather_index.eq(IS.rs1)
                                                            gathered_element = Signal(
                                                                element_width)
                                                            m.d.comb += gathered_element.eq(Mux(
                                                                gather_index < csr_vlmax,
                                                                gather_source.word_select(
                                                                    gather_index,
                                                                    element_width),
                                                                0))
                                                            element_enabled = (
                                                                vm | vregs[0][global_element])
                                                            next_element = Signal(element_width)
                                                            m.d.comb += next_element.eq(old_element)
                                                            with m.If(
                                                                    (csr_vstart <= global_element) &
                                                                    (global_element < csr_vl)):
                                                                with m.If(element_enabled):
                                                                    m.d.comb += next_element.eq(
                                                                        gathered_element)
                                                                with m.Elif(csr_vtype[7]):
                                                                    m.d.comb += next_element.eq(
                                                                        C(-1, element_width))
                                                            with m.Elif(
                                                                    (global_element >= csr_vl) &
                                                                    (global_element < csr_vlmax) &
                                                                    csr_vtype[6]):
                                                                m.d.comb += next_element.eq(
                                                                    C(-1, element_width))
                                                            gather_elements.append(next_element)
                                                        m.d.sync += vregs[
                                                            IS.rd + reg_offset
                                                        ].eq(Cat(*gather_elements))
                                m.d.sync += csr_vstart.eq(0)
                        is_vmfeq = ((vfunct6 == 0x18) &
                                    ((IS.funct3 == 0b001) |
                                     (IS.funct3 == 0b101)))
                        is_vmfle = ((vfunct6 == 0x19) &
                                    ((IS.funct3 == 0b001) |
                                     (IS.funct3 == 0b101)))
                        is_vmflt = ((vfunct6 == 0x1B) &
                                    ((IS.funct3 == 0b001) |
                                     (IS.funct3 == 0b101)))
                        is_vmfne = ((vfunct6 == 0x1C) &
                                    ((IS.funct3 == 0b001) |
                                     (IS.funct3 == 0b101)))
                        is_vmfgt = ((vfunct6 == 0x1D) &
                                    (IS.funct3 == 0b101))
                        is_vmfge = ((vfunct6 == 0x1F) &
                                    (IS.funct3 == 0b101))
                        with m.If(is_vmfeq | is_vmfne | is_vmflt | is_vmfle |
                                  is_vmfgt | is_vmfge):
                            vfcmp_group_regs = Signal(4)
                            vfcmp_width_legal = Signal()
                            vfcmp_sources_legal = Signal()
                            vfcmp_dest_overlap = Signal()
                            vfcmp_is_vv = IS.funct3 == 0b001
                            vfcmp_scalar = Signal(64)
                            m.d.comb += [
                                vfcmp_group_regs.eq(1),
                                vfcmp_width_legal.eq(Mux(
                                    csr_vtype[3:6] == 2, self.enable_fp32,
                                    Mux(csr_vtype[3:6] == 3,
                                        self.enable_fp64, 0))),
                                vfcmp_scalar.eq(fp_ex1_a),
                            ]
                            with m.If(csr_vtype[3:6] == 2):
                                m.d.comb += vfcmp_scalar.eq(Mux(
                                    fp_ex1_a[32:64].all(), fp_ex1_a,
                                    C(0xFFFFFFFF7FC00000, 64)))
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += vfcmp_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += vfcmp_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += vfcmp_group_regs.eq(8)
                            m.d.comb += [
                                vfcmp_sources_legal.eq(
                                    (csr_vtype[0:3] != 4) &
                                    ((IS.rs2 & (vfcmp_group_regs - 1)) == 0) &
                                    (IS.rs2 <= (32 - vfcmp_group_regs)) &
                                    (~vfcmp_is_vv |
                                     (((IS.rs1 & (vfcmp_group_regs - 1)) == 0) &
                                      (IS.rs1 <= (32 - vfcmp_group_regs)))) &
                                    (vm | ((IS.rs2 != 0) &
                                           (~vfcmp_is_vv | (IS.rs1 != 0))))),
                                vfcmp_dest_overlap.eq(
                                    Mux((IS.rd > IS.rs2) &
                                        (IS.rd < IS.rs2 + vfcmp_group_regs),
                                        1,
                                        Mux(vfcmp_is_vv & (IS.rd > IS.rs1) &
                                            (IS.rd < IS.rs1 + vfcmp_group_regs),
                                            1, 0))),
                            ]
                            with m.If(~vfcmp_width_legal |
                                      ~vfcmp_sources_legal |
                                      vfcmp_dest_overlap |
                                      csr_vtype[self.xlen - 1]):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                with m.If(csr_vstart < csr_vl):
                                    vfcmp_mask_bits = []
                                    for mask_index in range(128):
                                        next_mask_bit = Signal()
                                        compare_bit = Signal()
                                        invalid = Signal()
                                        m.d.comb += [
                                            next_mask_bit.eq(vregs[IS.rd][mask_index]),
                                            compare_bit.eq(0),
                                            invalid.eq(0),
                                        ]
                                        with m.Switch(csr_vtype[3:6]):
                                            for vsew, element_width, exponent_lo, quiet_bit in (
                                                (2, 32, 23, 22),
                                                (3, 64, 52, 51),
                                            ):
                                                elements_per_reg = 128 // element_width
                                                max_elements = 8 * elements_per_reg
                                                with m.Case(vsew):
                                                    if mask_index < max_elements:
                                                        reg_offset = mask_index // elements_per_reg
                                                        element_offset = mask_index % elements_per_reg
                                                        lo = element_offset * element_width
                                                        hi = lo + element_width
                                                        lhs = vregs[IS.rs2 + reg_offset][lo:hi]
                                                        vector_rhs = vregs[IS.rs1 + reg_offset][lo:hi]
                                                        rhs = Signal(element_width)
                                                        lhs_nan = Signal()
                                                        rhs_nan = Signal()
                                                        lhs_snan = Signal()
                                                        rhs_snan = Signal()
                                                        lhs_zero = Signal()
                                                        rhs_zero = Signal()
                                                        equal = Signal()
                                                        less = Signal()
                                                        m.d.comb += [
                                                            rhs.eq(Mux(
                                                                vfcmp_is_vv, vector_rhs,
                                                                vfcmp_scalar[0:element_width])),
                                                            lhs_nan.eq(
                                                                lhs[exponent_lo:element_width - 1].all() &
                                                                lhs[0:exponent_lo].any()),
                                                            rhs_nan.eq(
                                                                rhs[exponent_lo:element_width - 1].all() &
                                                                rhs[0:exponent_lo].any()),
                                                            lhs_snan.eq(lhs_nan & ~lhs[quiet_bit]),
                                                            rhs_snan.eq(rhs_nan & ~rhs[quiet_bit]),
                                                            lhs_zero.eq(lhs[0:element_width - 1] == 0),
                                                            rhs_zero.eq(rhs[0:element_width - 1] == 0),
                                                            equal.eq(~(lhs_nan | rhs_nan) &
                                                                     Mux(lhs_zero & rhs_zero, 1,
                                                                         lhs == rhs)),
                                                            less.eq(~(lhs_nan | rhs_nan) &
                                                                    ~(lhs_zero & rhs_zero) &
                                                                    Mux(
                                                                        lhs[element_width - 1] !=
                                                                        rhs[element_width - 1],
                                                                        lhs[element_width - 1],
                                                                        Mux(lhs[element_width - 1],
                                                                            lhs[0:element_width - 1] >
                                                                            rhs[0:element_width - 1],
                                                                            lhs[0:element_width - 1] <
                                                                            rhs[0:element_width - 1]))),
                                                            invalid.eq(Mux(
                                                                is_vmfeq | is_vmfne,
                                                                lhs_snan | rhs_snan,
                                                                lhs_nan | rhs_nan)),
                                                        ]
                                                        with m.If(is_vmfeq):
                                                            m.d.comb += compare_bit.eq(equal)
                                                        with m.Elif(is_vmfne):
                                                            m.d.comb += compare_bit.eq(~equal)
                                                        with m.Elif(is_vmflt):
                                                            m.d.comb += compare_bit.eq(less)
                                                        with m.Elif(is_vmfle):
                                                            m.d.comb += compare_bit.eq(less | equal)
                                                        with m.Elif(is_vmfgt):
                                                            m.d.comb += compare_bit.eq(
                                                                ~(lhs_nan | rhs_nan) &
                                                                ~(lhs_zero & rhs_zero) &
                                                                ~less & ~equal)
                                                        with m.Else():
                                                            m.d.comb += compare_bit.eq(
                                                                ~(lhs_nan | rhs_nan) &
                                                                (~less | equal))
                                        with m.If((csr_vstart <= mask_index) &
                                                  (mask_index < csr_vl)):
                                            with m.If(vm | vregs[0][mask_index]):
                                                m.d.comb += next_mask_bit.eq(compare_bit)
                                                with m.If(invalid):
                                                    m.d.sync += csr_fflags.eq(
                                                        csr_fflags | 0b10000)
                                            with m.Elif(csr_vtype[7]):
                                                m.d.comb += next_mask_bit.eq(1)
                                        with m.Elif(mask_index >= csr_vl):
                                            m.d.comb += next_mask_bit.eq(1)
                                        vfcmp_mask_bits.append(next_mask_bit)
                                    m.d.sync += vregs[IS.rd].eq(Cat(*vfcmp_mask_bits))
                                m.d.sync += csr_vstart.eq(0)
                        is_vmseq = ((vfunct6 == 0x18) &
                                    ((IS.funct3 == 0b000) |
                                     (IS.funct3 == 0b100) |
                                     (IS.funct3 == 0b011)))
                        is_vmsne = ((vfunct6 == 0x19) &
                                    ((IS.funct3 == 0b000) |
                                     (IS.funct3 == 0b100) |
                                     (IS.funct3 == 0b011)))
                        is_vmsltu = ((vfunct6 == 0x1A) &
                                     ((IS.funct3 == 0b000) |
                                      (IS.funct3 == 0b100)))
                        is_vmslt = ((vfunct6 == 0x1B) &
                                    ((IS.funct3 == 0b000) |
                                     (IS.funct3 == 0b100)))
                        is_vmsleu = ((vfunct6 == 0x1C) &
                                     ((IS.funct3 == 0b000) |
                                      (IS.funct3 == 0b100) |
                                      (IS.funct3 == 0b011)))
                        is_vmsle = ((vfunct6 == 0x1D) &
                                    ((IS.funct3 == 0b000) |
                                     (IS.funct3 == 0b100) |
                                     (IS.funct3 == 0b011)))
                        is_vmsgtu = ((vfunct6 == 0x1E) &
                                     ((IS.funct3 == 0b100) |
                                      (IS.funct3 == 0b011)))
                        is_vmsgt = ((vfunct6 == 0x1F) &
                                    ((IS.funct3 == 0b100) |
                                     (IS.funct3 == 0b011)))
                        with m.If(is_vmseq | is_vmsne | is_vmsltu | is_vmslt |
                                  is_vmsleu | is_vmsle | is_vmsgtu | is_vmsgt):
                            compare_group_regs = Signal(4)
                            compare_is_vv = IS.funct3 == 0b000
                            compare_scalar = Signal(self.xlen)
                            compare_sources_valid = Signal()
                            compare_dest_overlap = Signal()
                            m.d.comb += compare_group_regs.eq(1)
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += compare_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += compare_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += compare_group_regs.eq(8)
                            m.d.comb += [
                                compare_scalar.eq(Mux(
                                    IS.funct3 == 0b100,
                                    ex1_a,
                                    Cat(IS.rs1,
                                        Mux(IS.rs1[4], C(-1, self.xlen - 5),
                                            C(0, self.xlen - 5))),
                                )),
                                compare_sources_valid.eq(
                                    ((IS.rs2 & (compare_group_regs - 1)) == 0) &
                                    (IS.rs2 <= (32 - compare_group_regs)) &
                                    Mux(compare_is_vv,
                                        ((IS.rs1 & (compare_group_regs - 1)) == 0) &
                                        (IS.rs1 <= (32 - compare_group_regs)),
                                        1) &
                                    Mux(vm, 1,
                                        (IS.rs2 != 0) &
                                        Mux(compare_is_vv, IS.rs1 != 0, 1))
                                ),
                                compare_dest_overlap.eq(
                                    Mux((IS.rd > IS.rs2) &
                                        (IS.rd < IS.rs2 + compare_group_regs),
                                        1,
                                        Mux(compare_is_vv & (IS.rd > IS.rs1) &
                                            (IS.rd < IS.rs1 + compare_group_regs),
                                            1, 0))
                                ),
                            ]
                            with m.If(~compare_sources_valid | compare_dest_overlap |
                                      csr_vtype[self.xlen - 1]):
                                m.d.comb += self.trap.eq(1)
                            with m.Else():
                                with m.If(csr_vstart < csr_vl):
                                    compare_mask_bits = []
                                    for mask_index in range(128):
                                        old_mask_bit = vregs[IS.rd][mask_index]
                                        next_mask_bit = Signal()
                                        compare_bit = Signal()
                                        m.d.comb += [
                                            next_mask_bit.eq(old_mask_bit),
                                            compare_bit.eq(0),
                                        ]
                                        with m.Switch(csr_vtype[3:6]):
                                            for vsew, element_width in enumerate((8, 16, 32)):
                                                elements_per_reg = 128 // element_width
                                                reg_offset = mask_index // elements_per_reg
                                                element_offset = mask_index % elements_per_reg
                                                lo = element_offset * element_width
                                                hi = lo + element_width
                                                with m.Case(vsew):
                                                    compare_vs2 = vregs[IS.rs2 + reg_offset][lo:hi]
                                                    compare_vs1 = vregs[IS.rs1 + reg_offset][lo:hi]
                                                    compare_operand = Mux(
                                                        compare_is_vv,
                                                        compare_vs1,
                                                        compare_scalar[0:element_width],
                                                    )
                                                    with m.If(is_vmseq):
                                                        m.d.comb += compare_bit.eq(
                                                            compare_vs2 == compare_operand)
                                                    with m.Elif(is_vmsne):
                                                        m.d.comb += compare_bit.eq(
                                                            compare_vs2 != compare_operand)
                                                    with m.Elif(is_vmsltu):
                                                        m.d.comb += compare_bit.eq(
                                                            compare_vs2 < compare_operand)
                                                    with m.Elif(is_vmslt):
                                                        m.d.comb += compare_bit.eq(
                                                            compare_vs2.as_signed() <
                                                            compare_operand.as_signed())
                                                    with m.Elif(is_vmsleu):
                                                        m.d.comb += compare_bit.eq(
                                                            compare_vs2 <= compare_operand)
                                                    with m.Elif(is_vmsle):
                                                        m.d.comb += compare_bit.eq(
                                                            compare_vs2.as_signed() <=
                                                            compare_operand.as_signed())
                                                    with m.Elif(is_vmsgtu):
                                                        m.d.comb += compare_bit.eq(
                                                            compare_vs2 > compare_operand)
                                                    with m.Elif(is_vmsgt):
                                                        m.d.comb += compare_bit.eq(
                                                            compare_vs2.as_signed() >
                                                            compare_operand.as_signed())
                                        with m.If((csr_vstart <= mask_index) &
                                                  (mask_index < csr_vl)):
                                            with m.If(vm | vregs[0][mask_index]):
                                                m.d.comb += next_mask_bit.eq(compare_bit)
                                            with m.Elif(csr_vtype[7]):
                                                m.d.comb += next_mask_bit.eq(1)
                                        with m.Elif(mask_index >= csr_vl):
                                            m.d.comb += next_mask_bit.eq(1)
                                        compare_mask_bits.append(next_mask_bit)
                                    m.d.sync += vregs[IS.rd].eq(Cat(*compare_mask_bits))
                                m.d.sync += csr_vstart.eq(0)
                        is_vadc = ((vfunct6 == 0x10) & ~vm &
                                   ((IS.funct3 == 0b000) | (IS.funct3 == 0b100) |
                                    (IS.funct3 == 0b011)))
                        is_vmadc = ((vfunct6 == 0x11) &
                                    ((IS.funct3 == 0b000) | (IS.funct3 == 0b100) |
                                     (IS.funct3 == 0b011)))
                        is_vsbc = ((vfunct6 == 0x12) & ~vm &
                                   ((IS.funct3 == 0b000) | (IS.funct3 == 0b100)))
                        is_vmsbc = ((vfunct6 == 0x13) &
                                    ((IS.funct3 == 0b000) | (IS.funct3 == 0b100)))
                        with m.If(is_vadc | is_vmadc | is_vsbc | is_vmsbc):
                            carry_group_regs = Signal(4)
                            carry_is_vv = IS.funct3 == 0b000
                            carry_is_mask = is_vmadc | is_vmsbc
                            carry_is_sub = is_vsbc | is_vmsbc
                            carry_sources_valid = Signal()
                            carry_dest_valid = Signal()
                            m.d.comb += carry_group_regs.eq(1)
                            with m.Switch(csr_vtype[0:3]):
                                with m.Case(1):
                                    m.d.comb += carry_group_regs.eq(2)
                                with m.Case(2):
                                    m.d.comb += carry_group_regs.eq(4)
                                with m.Case(3):
                                    m.d.comb += carry_group_regs.eq(8)
                            m.d.comb += [
                                carry_sources_valid.eq(
                                    (csr_vtype[0:3] != 4) &
                                    ((IS.rs2 & (carry_group_regs - 1)) == 0) &
                                    (IS.rs2 <= (32 - carry_group_regs)) &
                                    (~carry_is_vv |
                                     (((IS.rs1 & (carry_group_regs - 1)) == 0) &
                                      (IS.rs1 <= (32 - carry_group_regs)))) &
                                    (vm | ((IS.rs2 != 0) & (~carry_is_vv | (IS.rs1 != 0))))),
                                carry_dest_valid.eq(
                                    carry_is_mask |
                                    (((IS.rd & (carry_group_regs - 1)) == 0) &
                                     (IS.rd <= (32 - carry_group_regs)) &
                                     (vm | (IS.rd != 0)))),
                            ]
                            with m.If(~csr_vtype[31] & carry_sources_valid & carry_dest_valid):
                                carry_scalar = Signal(self.xlen)
                                with m.If(IS.funct3 == 0b100):
                                    m.d.comb += carry_scalar.eq(ex1_a)
                                with m.Else():
                                    m.d.comb += carry_scalar.eq(IS.rs1.as_signed())
                                with m.If(~carry_is_mask):
                                    for element_width, sew_code in ((8, 0), (16, 1), (32, 2)):
                                        elements_per_reg = 128 // element_width
                                        with m.If(csr_vtype[3:6] == sew_code):
                                            for reg_offset in range(8):
                                                with m.If(reg_offset < carry_group_regs):
                                                    carry_elements = []
                                                    for element_offset in range(elements_per_reg):
                                                        global_element = (reg_offset * elements_per_reg +
                                                                          element_offset)
                                                        lo = element_offset * element_width
                                                        hi = lo + element_width
                                                        lhs = vregs[IS.rs2 + reg_offset][lo:hi]
                                                        vector_rhs = vregs[IS.rs1 + reg_offset][lo:hi]
                                                        rhs = Signal(element_width)
                                                        cin = vregs[0][global_element]
                                                        wide_sum = Signal(element_width + 1)
                                                        result = Signal(element_width)
                                                        next_element = Signal(element_width)
                                                        m.d.comb += [
                                                            rhs.eq(Mux(carry_is_vv, vector_rhs,
                                                                       carry_scalar[:element_width])),
                                                            wide_sum.eq(Cat(lhs, C(0, 1)) +
                                                                        Cat(rhs, C(0, 1)) + cin),
                                                            result.eq(Mux(carry_is_sub,
                                                                          lhs - rhs - cin,
                                                                          wide_sum[:element_width])),
                                                            next_element.eq(
                                                                vregs[IS.rd + reg_offset][lo:hi]),
                                                        ]
                                                        with m.If((global_element >= csr_vstart) &
                                                                  (global_element < csr_vl)):
                                                            m.d.comb += next_element.eq(result)
                                                        with m.Elif((global_element >= csr_vl) &
                                                                    (global_element < csr_vlmax) &
                                                                    csr_vtype[6]):
                                                            m.d.comb += next_element.eq(
                                                                C(-1, element_width))
                                                        carry_elements.append(next_element)
                                                    m.d.sync += vregs[IS.rd + reg_offset].eq(
                                                        Cat(*carry_elements))
                                with m.Else():
                                    for element_width, sew_code in ((8, 0), (16, 1), (32, 2)):
                                        elements_per_reg = 128 // element_width
                                        max_elements = 8 * elements_per_reg
                                        with m.If(csr_vtype[3:6] == sew_code):
                                            carry_mask_bits = []
                                            for mask_index in range(128):
                                                next_mask_bit = Signal()
                                                m.d.comb += next_mask_bit.eq(vregs[IS.rd][mask_index])
                                                if mask_index < max_elements:
                                                    source_reg = mask_index // elements_per_reg
                                                    source_element = mask_index % elements_per_reg
                                                    lo = source_element * element_width
                                                    hi = lo + element_width
                                                    lhs = vregs[IS.rs2 + source_reg][lo:hi]
                                                    vector_rhs = vregs[IS.rs1 + source_reg][lo:hi]
                                                    rhs = Signal(element_width)
                                                    cin = Mux(vm, 0, vregs[0][mask_index])
                                                    wide_sum = Signal(element_width + 1)
                                                    borrow = Signal()
                                                    m.d.comb += [
                                                        rhs.eq(Mux(carry_is_vv, vector_rhs,
                                                                   carry_scalar[:element_width])),
                                                        wide_sum.eq(Cat(lhs, C(0, 1)) +
                                                                    Cat(rhs, C(0, 1)) + cin),
                                                        borrow.eq((lhs < rhs) |
                                                                  (cin & (lhs == rhs))),
                                                    ]
                                                    with m.If((csr_vstart <= mask_index) &
                                                              (mask_index < csr_vl)):
                                                        m.d.comb += next_mask_bit.eq(
                                                            Mux(carry_is_sub, borrow,
                                                                wide_sum[element_width]))
                                                    with m.Elif(mask_index >= csr_vl):
                                                        m.d.comb += next_mask_bit.eq(1)
                                                else:
                                                    m.d.comb += next_mask_bit.eq(1)
                                                carry_mask_bits.append(next_mask_bit)
                                            m.d.sync += vregs[IS.rd].eq(Cat(*carry_mask_bits))
                                m.d.sync += csr_vstart.eq(0)
                with m.Case(AMO):
                    with m.If(self.enable_a):
                        m.d.comb += mem_addr.eq(ex1_a)
                        with m.If(amo_funct5 == 0b00011):  # SC
                            m.d.comb += [
                                wb_en.eq(1),
                                wb_data.eq(Mux(amo_sc_ok, 0, 1)),
                                mem_wdata.eq(ex1_b),
                            ]
                        with m.If(amo_funct5 != 0b00011):
                            m.d.comb += wb_en.eq(1)
                with m.Case(JALR):
                    with m.If(self.enable_zcmp & IS.compressed & (IS.funct3 == 0b101) &
                              ~zcmp_push_active & ~zcmp_pop_active):
                        stack_base = Mux(
                            IS.imm[0:4] <= 7, C(16, 8),
                            Mux(IS.imm[0:4] <= 11, C(32, 8),
                                Mux(IS.imm[0:4] <= 14, C(48, 8), C(64, 8))),
                        )
                        stack_count = Mux(IS.imm[0:4] == 15, C(13, 4), IS.imm[0:4] - 3)
                        with m.If(IS.rd == 0):
                            m.d.sync += [
                                zcmp_push_active.eq(1),
                                zcmp_push_drain.eq(6),
                                zcmp_push_slot.eq(0),
                                zcmp_push_count.eq(stack_count),
                                zcmp_push_sp.eq(ex1_a),
                                zcmp_push_adj.eq(stack_base + (IS.imm[4:6] << 4)),
                            ]
                        with m.Else():
                            m.d.sync += [
                                zcmp_pop_active.eq(1),
                                zcmp_pop_drain.eq(6),
                                zcmp_pop_slot.eq(0),
                                zcmp_pop_count.eq(stack_count),
                                zcmp_pop_sp.eq(ex1_a),
                                zcmp_pop_adj.eq(stack_base + (IS.imm[4:6] << 4)),
                                zcmp_pop_ret.eq(IS.rd[1]),
                                zcmp_pop_zero.eq(IS.rd == 2),
                            ]
                        m.d.comb += [
                            redirect.eq(1),
                            redirect_pc.eq(IS.pc + 2),
                        ]
                    with m.Elif(self.enable_zcmp & IS.compressed & (IS.funct3 == 0b110)):
                        m.d.comb += [
                            wb_en.eq(1),
                            wb_data.eq(ex1_a),
                            wb2_en.eq(1),
                            wb2_rd.eq(IS.imm[5:10]),
                            wb2_data.eq(ex1_b),
                        ]
                    with m.Elif(self.enable_zcmt & IS.compressed & (IS.funct3 == 0b111)):
                        m.d.comb += [
                            wb_en.eq(IS.rd == 1),
                            wb_data.eq(IS.pc + 2),
                            redirect.eq(1),
                            redirect_pc.eq(self.imem_rdata & ~1),
                        ]
                    with m.Else():
                        m.d.comb += [
                            wb_en.eq(1),
                            wb_data.eq(jump_control.link),
                            redirect.eq(1),
                            redirect_pc.eq(jump_control.target),
                        ]
                with m.Case(SYSTEM):
                    # Architectural Zicsr state for mstatus and the standard
                    # floating-point CSR aliases (fflags/frm/fcsr).
                    with m.If(self.enable_zicsr):
                        csr_supported = Signal()
                        csr_old = Signal(self.xlen)
                        csr_zimm = Signal(self.xlen)
                        m.d.comb += [
                            csr_supported.eq(
                                (IS.imm == 0x001) | (IS.imm == 0x002) |
                                (IS.imm == 0x003) | (IS.imm == 0x300) |
                                ((self.xlen >= 64) & (IS.imm == 0x30A)) |
                                (self.enable_v & ((IS.imm == 0x008) |
                                                  (IS.imm == 0x009) |
                                                  (IS.imm == 0x00A) |
                                                  (IS.imm == 0x00F))) |
                                (self.enable_zcmt & (IS.imm == 0x017))
                            ),
                            csr_old.eq(Mux(
                                IS.imm == 0x001,
                                csr_fflags,
                                Mux(
                                    IS.imm == 0x002,
                                    csr_frm,
                                    Mux(
                                        IS.imm == 0x003,
                                        Cat(csr_fflags, csr_frm),
                                        Mux(IS.imm == 0x008, csr_vstart,
                                            Mux(IS.imm == 0x009, csr_vxsat,
                                            Mux(IS.imm == 0x00A, csr_vxrm,
                                                Mux(IS.imm == 0x00F,
                                                    Cat(csr_vxsat, csr_vxrm),
                                                    Mux(IS.imm == 0x017, csr_jvt,
                                                    Mux(IS.imm == 0x30A, csr_menvcfg,
                                                        csr_mstatus)))))),
                                    ),
                                ),
                            )),
                            csr_zimm.eq(IS.rs1),
                        ]

                        def write_selected_csr(value):
                            with m.If(IS.imm == 0x001):
                                m.d.sync += csr_fflags.eq(value[0:5])
                            with m.Elif(IS.imm == 0x002):
                                m.d.sync += csr_frm.eq(value[0:3])
                            with m.Elif(IS.imm == 0x003):
                                m.d.sync += [
                                    csr_fflags.eq(value[0:5]),
                                    csr_frm.eq(value[5:8]),
                                ]
                            with m.Elif(IS.imm == 0x008):
                                m.d.sync += csr_vstart.eq(value)
                            with m.Elif(IS.imm == 0x009):
                                m.d.sync += csr_vxsat.eq(value[0])
                            with m.Elif(IS.imm == 0x00A):
                                m.d.sync += csr_vxrm.eq(value[0:2])
                            with m.Elif(IS.imm == 0x00F):
                                m.d.sync += [
                                    csr_vxsat.eq(value[0]),
                                    csr_vxrm.eq(value[1:3]),
                                ]
                            with m.Elif(IS.imm == 0x017):
                                m.d.sync += csr_jvt.eq(value & C(0xFFFFFFC0, self.xlen))
                            with m.Elif(IS.imm == 0x30A):
                                m.d.sync += csr_menvcfg.eq(
                                    value & C(1 << 62, self.xlen))
                            with m.Else():
                                m.d.sync += csr_mstatus.eq(value)

                        with m.If(csr_supported):
                            with m.If(IS.rd != 0):
                                with m.If((IS.funct3 == 0b001) | (IS.funct3 == 0b010) | (IS.funct3 == 0b011) | (IS.funct3 == 0b101) | (IS.funct3 == 0b110) | (IS.funct3 == 0b111)):
                                    m.d.comb += [wb_en.eq(1), wb_data.eq(csr_old)]
                            with m.If(IS.funct3 == 0b001):  # CSRRW
                                write_selected_csr(ex1_a)
                            with m.If((IS.funct3 == 0b010) & (IS.rs1 != 0)):  # CSRRS
                                write_selected_csr(csr_old | ex1_a)
                            with m.If((IS.funct3 == 0b011) & (IS.rs1 != 0)):  # CSRRC
                                write_selected_csr(csr_old & ~ex1_a)
                            with m.If(IS.funct3 == 0b101):  # CSRRWI
                                write_selected_csr(csr_zimm)
                            with m.If((IS.funct3 == 0b110) & (IS.rs1 != 0)):  # CSRRSI
                                write_selected_csr(csr_old | csr_zimm)
                            with m.If((IS.funct3 == 0b111) & (IS.rs1 != 0)):  # CSRRCI
                                write_selected_csr(csr_old & ~csr_zimm)
                    with m.If((IS.funct3 == 0b000) &
                              ((IS.insn == 0x00000073) |
                               (IS.insn == 0x00100073))):
                        # ECALL and EBREAK raise the core trap indication.
                        m.d.comb += self.trap.eq(1)
                    with m.If((IS.funct3 == 0b000) & (IS.imm == FENCE_I_IMM)):
                        # Minimal FENCE.I model keeps the pipeline running.
                        pass
                    is_sinval_encoding = ((IS.funct3 == 0) &
                                          (IS.insn[25:32] == 0b0001011))
                    is_svinval_fence_encoding = ((IS.funct3 == 0) &
                                                  (IS.insn[25:32] == 0b0001100))
                    is_sinval_vma = is_sinval_encoding & (IS.rd == 0)
                    is_sfence_w_inval = (IS.insn == 0x18000073)
                    is_sfence_inval_ir = (IS.insn == 0x18100073)
                    is_svinval_instruction = (is_sinval_vma |
                                              is_sfence_w_inval |
                                              is_sfence_inval_ir)
                    is_reserved_svinval = ((is_sinval_encoding & (IS.rd != 0)) |
                                           (is_svinval_fence_encoding &
                                            ~is_sfence_w_inval &
                                            ~is_sfence_inval_ir))
                    with m.If(is_reserved_svinval):
                        m.d.comb += self.trap.eq(1)
                    with m.If(is_svinval_instruction):
                        if not self.enable_svinval:
                            m.d.comb += self.trap.eq(1)
                        else:
                            m.d.comb += [wb_en.eq(0), wb_data.eq(0)]
                            with m.If(is_sinval_vma):
                                m.d.comb += [
                                    self.svinval_valid.eq(1),
                                    self.svinval_vaddr.eq(ex1_a),
                                    self.svinval_asid.eq(ex1_b),
                                    self.svinval_vaddr_valid.eq(IS.rs1 != 0),
                                    self.svinval_asid_valid.eq(IS.rs2 != 0),
                                    self.svinval_ordered.eq(
                                        self.svinval_barrier_active),
                                ]
                                m.d.sync += self.svinval_epoch.eq(
                                    self.svinval_epoch + 1)
                                m.d.sync += self.dbg_sinval_vma_count.eq(
                                    self.dbg_sinval_vma_count + 1)
                            with m.If(is_sfence_w_inval):
                                m.d.comb += [
                                    redirect.eq(1),
                                    redirect_pc.eq(IS.pc + 4),
                                ]
                                m.d.sync += [
                                    self.svinval_barrier_active.eq(1),
                                    self.dbg_sfence_w_inval_count.eq(
                                        self.dbg_sfence_w_inval_count + 1),
                                ]
                            with m.If(is_sfence_inval_ir):
                                m.d.comb += [
                                    redirect.eq(1),
                                    redirect_pc.eq(IS.pc + 4),
                                ]
                                m.d.sync += [
                                    self.svinval_barrier_active.eq(0),
                                    self.svinval_completion_epoch.eq(
                                        self.svinval_epoch),
                                    self.dbg_sfence_inval_ir_count.eq(
                                        self.dbg_sfence_inval_ir_count + 1),
                                ]
                    # Zawrs permits immediate completion of WRS.NTO/WRS.STO.
                    with m.If(self.enable_zawrs & (IS.funct3 == 0) &
                              (IS.rd == 0) & (IS.rs1 == 0) &
                              ((IS.imm[0:12] == 0x00D) | (IS.imm[0:12] == 0x01D))):
                        m.d.comb += [wb_en.eq(0), wb_data.eq(0)]
                    # Zimop MOP.R and MOP.RR write zero to rd.
                    zimop_common = ((IS.funct3 == 0b100) & IS.funct7[6] &
                                    (IS.funct7[3:5] == 0))
                    zimop_r = ~IS.funct7[0] & (IS.rs2[2:5] == 0b111)
                    zimop_rr = IS.funct7[0]
                    with m.If(self.enable_zimop & zimop_common & (zimop_r | zimop_rr)):
                        m.d.comb += [wb_en.eq(1), wb_data.eq(0)]
                    # Zkr seed entropy CSR. Only CSRRS/CSRRC with rs1=x0 are legal reads.
                    with m.If(self.enable_zkr & (IS.imm[0:12] == 0x015)):
                        with m.If(((IS.funct3 == 0b010) | (IS.funct3 == 0b011)) &
                                  (IS.rs1 == 0)):
                            seed_value = Mux(
                                self.seed_entropy_valid,
                                C(0x80000000, 32) | self.seed_entropy,
                                C(0x40000000, 32),
                            )
                            m.d.comb += [wb_en.eq(1), wb_data.eq(seed_value)]
                        with m.Else():
                            m.d.comb += [wb_en.eq(0), wb_data.eq(0)]
                with m.Case(BRANCH):
                    with m.If(branch_condition.taken):
                        m.d.comb += [
                            redirect.eq(1),
                            redirect_pc.eq(IS.pc + IS.imm),
                        ]
                with m.Case(JAL):
                    m.d.comb += [
                        wb_en.eq(1),
                        wb_data.eq(jump_control.link),
                        redirect.eq(1),
                        redirect_pc.eq(jump_control.target),
                    ]
                with m.Case(CUSTOM0):
                    pass

        with m.If(vmem_is_insn & vmem_backend_clear & vmem_pipe.issue_ready):
            m.d.comb += [vmem_pipe.issue_valid.eq(1), vmem_launch.eq(1)]
            with m.If(vmem_pipe.illegal):
                m.d.comb += self.trap.eq(1)
            with m.Elif(vmem_pipe.redirect):
                m.d.comb += [redirect.eq(1), redirect_pc.eq(IS.pc + 4)]

        with m.If(zcmp_pop_redirect):
            m.d.comb += [
                redirect.eq(1),
                redirect_pc.eq(zcmp_pop_target),
            ]

        with m.If(~stall):
            if self.enable_a:
                with m.If(EX1.valid & (EX1.opcode == AMO)):
                    with m.If(EX1.funct7[2:7] == 0b00010):
                        m.d.sync += [lr_sc_valid.eq(1), lr_sc_addr.eq(EX1.mem_addr)]

            m.d.sync += [
                EX1.valid.eq(IS.valid & ~vmem_launch),
                EX1.pc.eq(IS.pc),
                EX1.insn.eq(IS.insn),
                EX1.opcode.eq(IS.opcode),
                EX1.rd.eq(Mux(fp_rm_illegal | finx_excluded_move, 0, IS.rd)),
                EX1.rs1.eq(IS.rs1),
                EX1.rs2.eq(IS.rs2),
                EX1.funct3.eq(IS.funct3),
                EX1.funct7.eq(IS.funct7),
                EX1.imm.eq(IS.imm),
                EX1.rs1v.eq(ex1_a),
                EX1.rs2v.eq(ex1_b),
                EX1.is_load.eq(IS.is_load),
                EX1.is_store.eq(IS.is_store),
                EX1.is_branch.eq(IS.is_branch),
                EX1.is_jal.eq(IS.is_jal),
                EX1.is_fence.eq(IS.is_fence),
                EX1.is_gc.eq(IS.is_gc),
                EX1.alu.eq(alu_out),
                EX1.mem_addr.eq(mem_addr),
                EX1.mem_wdata.eq(mem_wdata),
                EX1.fp_mem_wdata.eq(fp_mem_wdata),
                EX1.wb_en.eq(((wb_en | (fp_wb_en & ~fp_rm_illegal)) & ~finx_excluded_move)
                             if self.use_finx else wb_en),
                EX1.wb_data.eq(Mux(fp_wb_en & ~fp_rm_illegal,
                    (fp_wb_data if self.xlen >= 64 else sign_extend(fp_wb_data[0:32], 32, self.xlen)), wb_data)
                    if self.use_finx else wb_data),
                EX1.wb2_en.eq(wb2_en),
                EX1.wb2_rd.eq(wb2_rd),
                EX1.wb2_data.eq(wb2_data),
                EX1.fp_wb_en.eq(0 if self.use_finx else
                                (fp_wb_en & ~fp_rm_illegal)),
                EX1.fp_wb_data.eq(fp_wb_data),
                EX1.fp_wb_q.eq(fp_wb_q),
            ]

            # IS ← ID2 pipeline advance (inside ~stall so it works even
            # when stall_front=1, avoiding deadlock when IS.valid=0 but
            # frontend is stalled).  Guards:
            #   stall_dep_id2:         don't advance a dep-stalled instruction
            #   id2_dup_is:            prevent re-copying same ID2 into IS
            m.submodules.is_advance_ctrl = is_advance_ctrl = ISAdvanceControl()
            m.d.comb += [
                is_advance_ctrl.redirect.eq(redirect),
                is_advance_ctrl.stall_front.eq(stall_front),
                is_advance_ctrl.is_valid.eq(IS.valid),
                is_advance_ctrl.stall_dep_id2.eq(stall_dep_id2),
            ]
            with m.If(is_advance_ctrl.clear_is):
                m.d.sync += IS.valid.eq(0)
            with m.Elif(is_advance_ctrl.fill_is):
                m.d.sync += [
                    IS.valid.eq(Mux(gc_fire & (~(ID2.valid & ID2.is_gc)), 0, ID2.valid)),
                    IS.pc.eq(ID2.pc),
                    IS.insn.eq(ID2.insn),
                    IS.compressed.eq(ID2.compressed),
                    IS.opcode.eq(ID2.opcode),
                    IS.rd.eq(ID2.rd),
                    IS.rs1.eq(ID2.rs1),
                    IS.rs2.eq(ID2.rs2),
                    IS.funct3.eq(ID2.funct3),
                    IS.funct7.eq(ID2.funct7),
                    IS.imm.eq(ID2.imm),
                    IS.rs1v.eq(ID2.rs1v),
                    IS.rs2v.eq(ID2.rs2v),
                    IS.is_load.eq(ID2.is_load),
                    IS.is_store.eq(ID2.is_store),
                    IS.is_branch.eq(ID2.is_branch),
                    IS.is_jal.eq(ID2.is_jal),
                    IS.is_fence.eq(ID2.is_fence),
                    IS.is_gc.eq(ID2.is_gc),
                ]
                # When only an earlier frontend stage is held, ID2 still
                # transfers into an empty IS slot. Mark that transfer as
                # consumed so the same instruction is not replayed.
                with m.If(is_advance_ctrl.consume_id2):
                    m.d.sync += ID2.valid.eq(0)
            # Step78: prevent gc_fire/mv_reloc_fire re-fire when frontend
            # is stalled.  Matches the frontend Mux condition for gc_fire,
            # and unconditionally clears for mv_reloc_fire.
            with m.If(gc_fire & (~(ID2.valid & ID2.is_gc))):
                m.d.sync += IS.valid.eq(0)
            with m.If(mv_reloc_fire):
                m.d.sync += IS.valid.eq(0)



        with m.If(~stall):
            step(EX1, EX2)

        # ----------------------
        # MEM stages: drive DMEM
        # ----------------------
        # Step6-B/C：写屏障事件入本地队列（commit 时刻）
        # -------------------------------------------
        # 这里把“commit 时刻”定义为：store 被真正发往 DMEM 的那个 cycle。
        # 这么做的好处：
        #   - 如果本地队列满，就让 store 根本不要发出去（避免“已经写内存但事件丢了”）
        #   - stall 发生在发 DMEM 之前 => 不会出现 stall 时重复写内存的问题
        store_std = Signal()
        store_sw = Signal()
        mem_sc_fail = Signal()
        fp64_mem_busy = Signal()
        fp64_mem_is_store = Signal()
        fp64_mem_is_quad = Signal()
        fp64_mem_beat = Signal(2)
        fp64_mem_addr = Signal(32)
        fp64_mem_low = Signal(128)
        fp64_mem_store_hi = Signal(128)
        fp64_mem_retired = Signal()
        fp64_mem_retired_pc = Signal(32)
        fp64_load_mem1 = Signal()
        fp64_store_mem1 = Signal()
        int64_load_mem1 = Signal()
        int64_store_mem1 = Signal()
        fp128_load_mem1 = Signal()
        fp128_store_mem1 = Signal()
        fp_multi_mem1 = Signal()
        fp_multi_start = Signal()
        m.d.comb += [
            self.dbg_q_mem_busy.eq(fp64_mem_busy & fp64_mem_is_quad),
            self.dbg_q_mem_beat.eq(fp64_mem_beat),
        ]
        m.d.comb += [
            fp64_load_mem1.eq(self.enable_d & MEM1.valid & MEM1.is_load & (MEM1.opcode == LOAD_FP) & (MEM1.funct3 == 0b011)),
            fp64_store_mem1.eq(self.enable_d & MEM1.valid & MEM1.is_store & (MEM1.opcode == STORE_FP) & (MEM1.funct3 == 0b011)),
            int64_load_mem1.eq((self.xlen == 64) & MEM1.valid & MEM1.is_load &
                               (MEM1.opcode == LOAD) & (MEM1.funct3 == 0b011)),
            int64_store_mem1.eq((self.xlen == 64) & MEM1.valid & MEM1.is_store &
                                (MEM1.opcode == STORE) & (MEM1.funct3 == 0b011)),
            fp128_load_mem1.eq(self.enable_q & MEM1.valid & MEM1.is_load & (MEM1.opcode == LOAD_FP) & (MEM1.funct3 == 0b100)),
            fp128_store_mem1.eq(self.enable_q & MEM1.valid & MEM1.is_store & (MEM1.opcode == STORE_FP) & (MEM1.funct3 == 0b100)),
            fp_multi_mem1.eq(fp64_load_mem1 | fp64_store_mem1 |
                             int64_load_mem1 | int64_store_mem1 |
                             fp128_load_mem1 | fp128_store_mem1),
            fp_multi_start.eq(fp_multi_mem1 &
                              ~(fp64_mem_retired &
                                (fp64_mem_retired_pc == MEM1.pc))),
            q_load_forward_valid.eq(
                fp64_mem_busy & fp64_mem_is_quad & ~fp64_mem_is_store &
                (fp64_mem_beat == 3) & self.dmem_grant),
            q_load_forward_data.eq(Cat(fp64_mem_low[0:96], self.dmem_rdata)),
        ]
        amo_f5 = Signal(5)
        amo_is_lr = Signal()
        amo_is_sc = Signal()
        amo_is_64 = Signal()
        amo_sc_ok_mem = Signal()
        m.d.comb += amo_f5.eq(MEM1.funct7[2:7])
        m.d.comb += amo_is_lr.eq((MEM1.opcode == AMO) & (amo_f5 == 0b00010))
        m.d.comb += amo_is_sc.eq((MEM1.opcode == AMO) & (amo_f5 == 0b00011))
        m.d.comb += amo_is_64.eq(
            (self.xlen == 64) & MEM1.valid & (MEM1.opcode == AMO) &
            (MEM1.funct3 == 0b011)
        )
        m.d.comb += amo_sc_ok_mem.eq(lr_sc_valid & (lr_sc_addr == MEM1.mem_addr))
        m.d.comb += mem_sc_fail.eq(amo_is_sc & ~amo_sc_ok_mem)
        m.d.comb += store_std.eq(
            ((MEM1.opcode == STORE) & ((MEM1.funct3 == 0b000) | (MEM1.funct3 == 0b001) | (MEM1.funct3 == 0b010))) |
            ((MEM1.opcode == STORE_FP) & (
                (self.enable_zfhmin & ~self.use_finx & (MEM1.funct3 == 0b001)) |
                (MEM1.funct3 == 0b010) | (MEM1.funct3 == 0b011)
            ))
        )
        m.d.comb += store_sw.eq(
            MEM1.valid & MEM1.is_store & (store_std | (MEM1.opcode == AMO)) &
            ~mem_sc_fail & ~amo_is_64
        )

        amo_old32 = Signal(32)
        amo_rhs32 = Signal(32)
        amo_wdata32 = Signal(32)
        m.d.comb += [
            amo_old32.eq(self.dmem_rdata),
            amo_rhs32.eq(MEM1.rs2v[0:32]),
            amo_wdata32.eq(MEM1.mem_wdata[0:32]),
        ]
        with m.If(amo_f5 == 0b00000):      # AMOADD.W
            m.d.comb += amo_wdata32.eq(amo_old32 + amo_rhs32)
        with m.Elif(amo_f5 == 0b00001):    # AMOSWAP.W
            m.d.comb += amo_wdata32.eq(amo_rhs32)
        with m.Elif(amo_f5 == 0b00100):    # AMOXOR.W
            m.d.comb += amo_wdata32.eq(amo_old32 ^ amo_rhs32)
        with m.Elif(amo_f5 == 0b01000):    # AMOOR.W
            m.d.comb += amo_wdata32.eq(amo_old32 | amo_rhs32)
        with m.Elif(amo_f5 == 0b01100):    # AMOAND.W
            m.d.comb += amo_wdata32.eq(amo_old32 & amo_rhs32)
        with m.Elif(amo_f5 == 0b10000):    # AMOMIN.W
            m.d.comb += amo_wdata32.eq(Mux(amo_old32.as_signed() <= amo_rhs32.as_signed(), amo_old32, amo_rhs32))
        with m.Elif(amo_f5 == 0b10100):    # AMOMAX.W
            m.d.comb += amo_wdata32.eq(Mux(amo_old32.as_signed() >= amo_rhs32.as_signed(), amo_old32, amo_rhs32))
        with m.Elif(amo_f5 == 0b11000):    # AMOMINU.W
            m.d.comb += amo_wdata32.eq(Mux(amo_old32 <= amo_rhs32, amo_old32, amo_rhs32))
        with m.Elif(amo_f5 == 0b11100):    # AMOMAXU.W
            m.d.comb += amo_wdata32.eq(Mux(amo_old32 >= amo_rhs32, amo_old32, amo_rhs32))

        # AMO.D uses locked low/high 32-bit beats on the external memory port.
        amo64_busy = Signal()
        amo64_phase = Signal(2)
        amo64_old_low = Signal(32)
        amo64_old = Signal(64)
        amo64_read = Signal(64)
        amo64_new = Signal(64)
        amo64_rhs = Signal(64)
        amo64_calc = Signal(64)
        amo64_sc_fail = Signal()
        amo64_high_beat = Signal()
        amo64_terminal = Signal()
        amo64_done = Signal()
        amo64_req = Signal()
        amo64_we = Signal()
        amo64_wdata = Signal(32)
        amo64_wb_data = Signal(self.xlen)
        m.d.comb += [
            amo64_rhs.eq(MEM1.rs2v),
            amo64_read.eq(Cat(amo64_old_low, self.dmem_rdata)),
            amo64_calc.eq(amo64_rhs),
            amo64_sc_fail.eq(amo_is_64 & amo_is_sc & ~amo_sc_ok_mem),
            amo64_high_beat.eq(amo64_busy & ((amo64_phase == 1) | (amo64_phase == 3))),
            amo64_terminal.eq(
                (amo_is_lr & amo64_busy & (amo64_phase == 1)) |
                (amo_is_sc & amo64_busy & (amo64_phase == 1)) |
                (~amo_is_lr & ~amo_is_sc & amo64_busy & (amo64_phase == 3))
            ),
            amo64_done.eq(amo64_sc_fail | (amo_is_64 & amo64_terminal & self.dmem_grant)),
            amo64_req.eq(amo_is_64 & ~amo64_sc_fail),
            amo64_we.eq(amo64_req & (amo_is_sc | (amo64_busy &
                         ((amo64_phase == 2) | (amo64_phase == 3))))),
            amo64_wdata.eq(Mux(
                amo_is_sc,
                Mux(amo64_high_beat, MEM1.rs2v[32:64], MEM1.rs2v[0:32]),
                Mux(amo64_high_beat, amo64_new[32:64], amo64_new[0:32]),
            )),
            amo64_wb_data.eq(Mux(
                amo_is_sc,
                Mux(amo_sc_ok_mem, 0, 1),
                Mux(amo_is_lr, Cat(amo64_old_low, self.dmem_rdata), amo64_old),
            )),
        ]
        with m.If(amo_f5 == 0b00000):
            m.d.comb += amo64_calc.eq(amo64_read + amo64_rhs)
        with m.Elif(amo_f5 == 0b00001):
            m.d.comb += amo64_calc.eq(amo64_rhs)
        with m.Elif(amo_f5 == 0b00100):
            m.d.comb += amo64_calc.eq(amo64_read ^ amo64_rhs)
        with m.Elif(amo_f5 == 0b01000):
            m.d.comb += amo64_calc.eq(amo64_read | amo64_rhs)
        with m.Elif(amo_f5 == 0b01100):
            m.d.comb += amo64_calc.eq(amo64_read & amo64_rhs)
        with m.Elif(amo_f5 == 0b10000):
            m.d.comb += amo64_calc.eq(Mux(
                amo64_read.as_signed() <= amo64_rhs.as_signed(), amo64_read, amo64_rhs))
        with m.Elif(amo_f5 == 0b10100):
            m.d.comb += amo64_calc.eq(Mux(
                amo64_read.as_signed() >= amo64_rhs.as_signed(), amo64_read, amo64_rhs))
        with m.Elif(amo_f5 == 0b11000):
            m.d.comb += amo64_calc.eq(Mux(amo64_read <= amo64_rhs, amo64_read, amo64_rhs))
        with m.Elif(amo_f5 == 0b11100):
            m.d.comb += amo64_calc.eq(Mux(amo64_read >= amo64_rhs, amo64_read, amo64_rhs))

        with m.If(amo_is_64 & self.dmem_grant):
            with m.If(amo64_sc_fail):
                m.d.sync += [amo64_busy.eq(0), amo64_phase.eq(0)]
            with m.Elif(~amo64_busy):
                m.d.sync += [amo64_busy.eq(1), amo64_phase.eq(1)]
                with m.If(~amo_is_sc):
                    m.d.sync += amo64_old_low.eq(self.dmem_rdata)
            with m.Elif(amo64_phase == 1):
                with m.If(amo_is_lr | amo_is_sc):
                    m.d.sync += [amo64_busy.eq(0), amo64_phase.eq(0)]
                with m.Else():
                    m.d.sync += [
                        amo64_old.eq(Cat(amo64_old_low, self.dmem_rdata)),
                        amo64_new.eq(amo64_calc),
                        amo64_phase.eq(2),
                    ]
            with m.Elif(amo64_phase == 2):
                m.d.sync += amo64_phase.eq(3)
            with m.Else():
                m.d.sync += [amo64_busy.eq(0), amo64_phase.eq(0)]

        # Step15：在多核共享单端口 DMEM + RRArbiter 的模型里，
        # 如果 store/load 请求只打一个“单拍脉冲”，未被仲裁到就会丢失。
        # 解决办法：
        #   - 请求在 MEM1 保持有效，直到本核被 arbiter grant
        #   - 只有在 grant 的那个 cycle 才算“commit”（并入队写屏障事件）
        store_need = Signal()
        m.d.comb += store_need.eq(store_sw)

        # 写屏障指针过滤：
        #   - wb_ptr_filter=0：所有 store 都上报写屏障事件
        #   - wb_ptr_filter=1：仅当 wdata[31]==1（看起来像指针）才上报事件
        is_ptr_store = Signal()
        if self.wb_ptr_filter:
            m.d.comb += is_ptr_store.eq(MEM1.mem_wdata[31])
        else:
            m.d.comb += is_ptr_store.eq(1)

        store_can_issue = Signal()
        m.d.comb += store_can_issue.eq(store_need & ~stall_store)

        # 多核共享 DMEM：如果本拍没被 grant，则保持 MEM1 并重试
        stall_dmem = Signal()
        m.d.comb += stall_dmem.eq(
            MEM1.valid & (MEM1.is_load | store_can_issue) & ~amo_is_64 & ~self.dmem_grant
        )
        stall_fp64_mem = Signal()
        m.d.comb += stall_fp64_mem.eq(
            (fp_multi_start & ~fp64_mem_busy) |
            (fp64_mem_busy & fp64_mem_is_quad & (fp64_mem_beat != 3))
        )
        stall_amo64 = Signal()
        m.d.comb += stall_amo64.eq(amo_is_64 & ~amo64_done)

        # 全局 stall（后端需要保持不前推的条件）
        m.d.comb += stall.eq(stall_store | stall_dmem | stall_fp64_mem | stall_amo64 | stall_rb |
                             stall_gc_order | stall_gc_issue | zcmp_push_store |
                             zcmp_pop_load | vcompress_issue | vcompress_active)

        store_issue = Signal()
        m.d.comb += store_issue.eq(store_can_issue & self.dmem_grant)
        # (wbq write barrier enqueue moved into GCSubsystem)

        store_wdata32 = Signal(32)
        dmem_wdata = Signal(32)
        m.d.comb += store_wdata32.eq(MEM1.mem_wdata[0:32])
        with m.If((MEM1.opcode == STORE) & (MEM1.funct3 == 0b000)):
            with m.If(MEM1.mem_addr[0:2] == 0):
                m.d.comb += store_wdata32.eq(Cat(MEM1.mem_wdata[0:8], self.dmem_rdata[8:32]))
            with m.Elif(MEM1.mem_addr[0:2] == 1):
                m.d.comb += store_wdata32.eq(Cat(self.dmem_rdata[0:8], MEM1.mem_wdata[0:8], self.dmem_rdata[16:32]))
            with m.Elif(MEM1.mem_addr[0:2] == 2):
                m.d.comb += store_wdata32.eq(Cat(self.dmem_rdata[0:16], MEM1.mem_wdata[0:8], self.dmem_rdata[24:32]))
            with m.Else():
                m.d.comb += store_wdata32.eq(Cat(self.dmem_rdata[0:24], MEM1.mem_wdata[0:8]))
        with m.Elif(((MEM1.opcode == STORE) & (MEM1.funct3 == 0b001)) |
                    (self.enable_zfhmin & ~self.use_finx & (MEM1.opcode == STORE_FP) & (MEM1.funct3 == 0b001))):
            with m.If(MEM1.mem_addr[1] == 0):
                m.d.comb += store_wdata32.eq(Cat(MEM1.mem_wdata[0:16], self.dmem_rdata[16:32]))
            with m.Else():
                m.d.comb += store_wdata32.eq(Cat(self.dmem_rdata[0:16], MEM1.mem_wdata[0:16]))
        m.d.comb += dmem_wdata.eq(Mux(
            fp64_mem_busy & fp64_mem_is_store,
            fp64_mem_store_hi.word_select(fp64_mem_beat, 32),
            Mux((MEM1.opcode == AMO) & ~amo_is_sc, amo_wdata32, store_wdata32)))

        with m.If(fp64_mem_retired &
                  (~fp_multi_mem1 | (fp64_mem_retired_pc != MEM1.pc))):
            m.d.sync += fp64_mem_retired.eq(0)

        with m.If(fp_multi_start & ~fp64_mem_busy & self.dmem_grant):
            m.d.sync += [
                fp64_mem_busy.eq(1),
                fp64_mem_is_store.eq(fp64_store_mem1 | fp128_store_mem1 | int64_store_mem1),
                fp64_mem_is_quad.eq(fp128_load_mem1 | fp128_store_mem1),
                fp64_mem_beat.eq(Mux(fp128_load_mem1 | fp128_store_mem1, 0, 1)),
                fp64_mem_addr.eq(MEM1.mem_addr),
                fp64_mem_low.eq(Mux(fp128_load_mem1 | fp128_store_mem1,
                                    0, self.dmem_rdata)),
                fp64_mem_store_hi.eq(Mux(
                    int64_store_mem1, MEM1.mem_wdata,
                    Mux(fp128_store_mem1 & q_recent_valid &
                        (q_recent_rd == MEM1.rs2),
                        q_recent_data, MEM1.fp_mem_wdata))),
            ]
        with m.Elif(fp64_mem_busy & self.dmem_grant):
            with m.If(~fp64_mem_is_store):
                m.d.sync += fp64_mem_low.word_select(fp64_mem_beat, 32).eq(self.dmem_rdata)
                with m.If(fp64_mem_is_quad & (fp64_mem_beat == 3)):
                    m.d.sync += [
                        q_recent_valid.eq(1),
                        q_recent_rd.eq(MEM1.rd),
                        q_recent_data.eq(Cat(fp64_mem_low[0:96], self.dmem_rdata)),
                    ]
            with m.If((~fp64_mem_is_quad & (fp64_mem_beat == 1)) |
                      (fp64_mem_is_quad & (fp64_mem_beat == 3))):
                m.d.sync += [
                    fp64_mem_busy.eq(0),
                    fp64_mem_retired.eq(1),
                    fp64_mem_retired_pc.eq(MEM1.pc),
                ]
            with m.Else():
                m.d.sync += fp64_mem_beat.eq(fp64_mem_beat + 1)

        # DMEM：load 不受写屏障队列影响；store 仅在 store_issue 时真正写入
        m.d.comb += [
            # load：一直请求到被 grant（由 stall_dmem 保证 MEM1 保持）
            # store：无写屏障时可直接发；有写屏障时需 wbq 有空间；并在 grant 时 commit
            self.dmem_valid.eq(Mux(amo64_req, 1,
                Mux(vmem_pipe.dmem_valid, 1, Mux(
                    zcmp_push_store | zcmp_pop_load, 1,
                    (MEM1.valid & (MEM1.is_load | store_can_issue)) |
                    fp_multi_start | fp64_mem_busy,
                )))),

            self.dmem_we.eq(Mux(amo64_req, amo64_we,
                Mux(vmem_pipe.dmem_valid, vmem_pipe.dmem_we,
                    Mux(zcmp_push_store, 1, Mux(zcmp_pop_load, 0,
                    Mux(fp64_mem_busy, fp64_mem_is_store,
                        (store_issue & ~fp128_store_mem1) |
                        fp64_store_mem1 | int64_store_mem1)))))),
            self.dmem_addr.eq(Mux(amo64_req,
                                  MEM1.mem_addr + Mux(amo64_high_beat, 4, 0),
                                  Mux(vmem_pipe.dmem_valid, vmem_pipe.dmem_addr,
                                  Mux(zcmp_push_store,
                                  zcmp_push_sp - ((zcmp_push_slot + 1) << 2),
                                  Mux(zcmp_pop_load,
                                      zcmp_pop_sp + zcmp_pop_adj -
                                      Cat(C(0, 2), zcmp_pop_count - zcmp_pop_slot),
                                      Mux(fp64_mem_busy,
                                          fp64_mem_addr + (fp64_mem_beat << 2),
                                          MEM1.mem_addr)))))),
            self.dmem_wdata.eq(Mux(amo64_req, amo64_wdata,
                                   Mux(vmem_pipe.dmem_valid, vmem_pipe.dmem_wdata,
                                   Mux(zcmp_push_store,
                                   zcmp_push_regs[zcmp_push_index], dmem_wdata)))),
            self.dmem_lock.eq(amo64_req),
        ]

        with m.If(~stall):
            step(EX2, MEM1)

        # Step73：根据rb_mode提前判断该load是否需要读屏障（基于MEM1阶段）
        will_need_rb = Signal()
        if self.rb_mode == 0:
            m.d.comb += will_need_rb.eq(1)
        elif self.rb_mode == 1:
            m.d.comb += will_need_rb.eq(MEM1.mem_addr[31])
        elif self.rb_mode == 2:
            m.d.comb += will_need_rb.eq(MEM1.mem_addr[28:31] != 0)
        else:
            m.d.comb += will_need_rb.eq(1)

        with m.If(~stall):
            step(MEM1, MEM2)
            with m.If(MEM1.valid & MEM1.is_store):
                m.d.sync += [lr_sc_valid.eq(0), lr_sc_addr.eq(0)]

            with m.If(amo_is_64):
                m.d.sync += [
                    MEM2.wb_en.eq(1),
                    MEM2.wb_data.eq(amo64_wb_data),
                ]

            with m.Elif(MEM1.valid & MEM1.is_load & (~(MEM1.opcode == AMO) | amo_is_lr)):
                load_byte = Signal(8)
                m.d.comb += load_byte.eq(self.dmem_rdata[0:8])
                with m.If(~MEM1.mem_addr[1] & ~MEM1.mem_addr[0]):
                    m.d.comb += load_byte.eq(self.dmem_rdata[0:8])
                with m.Elif(~MEM1.mem_addr[1] & MEM1.mem_addr[0]):
                    m.d.comb += load_byte.eq(self.dmem_rdata[8:16])
                with m.Elif(MEM1.mem_addr[1] & ~MEM1.mem_addr[0]):
                    m.d.comb += load_byte.eq(self.dmem_rdata[16:24])
                with m.Elif(MEM1.mem_addr[1] & MEM1.mem_addr[0]):
                    m.d.comb += load_byte.eq(self.dmem_rdata[24:32])

                load_half = Signal(16)
                with m.If(~MEM1.mem_addr[1]):
                    m.d.comb += load_half.eq(self.dmem_rdata[0:16])
                with m.Elif(MEM1.mem_addr[1]):
                    m.d.comb += load_half.eq(self.dmem_rdata[16:32])

                load_word = self.dmem_rdata
                load_ext = Signal(self.xlen)
                m.d.comb += load_ext.eq(
                    Mux(
                        MEM1.funct3 == 0b000,
                        sign_extend(load_byte, 8, self.xlen),                 # LB
                        Mux(
                            MEM1.funct3 == 0b001,
                            sign_extend(load_half, 16, self.xlen),            # LH
                            Mux(
                                MEM1.funct3 == 0b100,
                                load_byte,                                    # LBU
                                Mux(
                                    MEM1.funct3 == 0b101,
                                    load_half,                                # LHU
                                    sign_extend(load_word, 32, self.xlen),    # LW
                                ),
                            ),
                        ),
                    )
                )

                fp64_load_complete = Signal()
                fp128_load_complete = Signal()
                m.d.comb += fp64_load_complete.eq(
                    (self.enable_d & (MEM1.opcode == LOAD_FP) & (MEM1.funct3 == 0b011))
                )
                m.d.comb += fp128_load_complete.eq(
                    self.enable_q & (MEM1.opcode == LOAD_FP) & (MEM1.funct3 == 0b100)
                )
                with m.If(fp128_load_complete):
                    m.d.sync += [
                        MEM2.wb_en.eq(0),
                        MEM2.fp_wb_en.eq(1),
                        MEM2.fp_wb_data.eq(Cat(fp64_mem_low[0:96], self.dmem_rdata)),
                        MEM2.fp_wb_q.eq(1),
                    ]
                with m.Elif(fp64_load_complete):
                    m.d.sync += [
                        MEM2.wb_en.eq(0),
                        MEM2.fp_wb_en.eq(1),
                        MEM2.fp_wb_data.eq(Cat(fp64_mem_low[0:32], self.dmem_rdata)),
                    ]
                with m.Elif(int64_load_mem1):
                    m.d.sync += [
                        MEM2.wb_en.eq(1),
                        MEM2.wb_data.eq(Cat(fp64_mem_low[0:32], self.dmem_rdata)),
                    ]
                with m.Elif(self.enable_zfhmin & ~self.use_finx & (MEM1.opcode == LOAD_FP) & (MEM1.funct3 == 0b001)):
                    m.d.sync += [
                        MEM2.wb_en.eq(0),
                        MEM2.fp_wb_en.eq(1),
                        MEM2.fp_wb_data.eq(Cat(load_half, C(0xFFFFFFFFFFFF, 48))),
                    ]
                with m.Elif(self.enable_f & (MEM1.opcode == LOAD_FP) & (MEM1.funct3 == 0b010)):
                    m.d.sync += [
                        MEM2.wb_en.eq(0),
                        MEM2.fp_wb_en.eq(1),
                        MEM2.fp_wb_data.eq(Cat(self.dmem_rdata, C(0xFFFFFFFF, 32))),
                    ]
                with m.Else():
                    m.d.sync += [
                        # Step8/9：LW 的返回值先进入读屏障流程，不直接写回寄存器
                        # Step73：如果不需要读屏障，直接写回
                        MEM2.wb_en.eq(1),
                        MEM2.wb_data.eq(
                            Mux(fp64_load_complete,
                                Cat(fp64_mem_low[0:32], self.dmem_rdata), load_ext),
                        ),
                    ]

            with m.Elif(self.enable_a & MEM1.valid & (MEM1.opcode == AMO) & amo_is_sc):
                # SC writes use completion status as return value (0 success, 1 fail),
                # but keep full pipeline shape consistent even when no load byte/half routing applies.
                m.d.sync += [
                    MEM2.wb_en.eq(1),
                    MEM2.wb_data.eq(Mux(amo_sc_ok_mem, 0, 1)),
                ]

            with m.Elif(self.enable_a & MEM1.valid & (MEM1.opcode == AMO) & (amo_f5 != 0b00010) & (amo_f5 != 0b00011)):
                m.d.sync += [
                    MEM2.wb_en.eq(1),
                    MEM2.wb_data.eq(self.dmem_rdata),
                ]

        # ----------------------
        # WB: writeback (including GC response)
        # ----------------------
        with m.If(~stall):
            step(MEM2, WB)

        # Step12：统一寄存器写回（WB / MV / GC / cache），避免多处动态索引写同一个 regs 导致覆盖
        # 说明：研究阶段允许'同一拍写不同寄存器'（等价于多写口 regfile）。
        for i in range(1, 32):
            wb_hit = Signal(name=f"wb_hit_c{self.core_id}_{i}")
            wb2_hit = Signal(name=f"wb2_hit_c{self.core_id}_{i}")
            mv_hit = Signal(name=f"mv_hit_c{self.core_id}_{i}")
            gc_hit = Signal(name=f"gc_hit_c{self.core_id}_{i}")
            cache_hit_i = Signal(name=f"cache_hit_c{self.core_id}_{i}")
            m.d.comb += [
                wb_hit.eq(WB.valid & WB.wb_en & (WB.rd == i)),
                wb2_hit.eq(WB.valid & WB.wb2_en & (WB.wb2_rd == i)),
                mv_hit.eq(self.mv_rsp_valid & match_found & (mv_bp_rd == i)),
                gc_hit.eq(gc_rsp_match & (self.gc_rsp_rd == i)),
                cache_hit_i.eq(cache_hit_fire & (MEM2.rd == i)),
            ]
            any_hit = Signal(name=f"rf_any_c{self.core_id}_{i}")
            m.d.comb += any_hit.eq(wb_hit | wb2_hit | mv_hit | gc_hit | cache_hit_i)
            data = Signal(self.xlen, name=f"rf_wdata_c{self.core_id}_{i}")
            m.d.comb += data.eq(Mux(cache_hit_i, cache_hit_data,
                               Mux(gc_hit, self.gc_rsp_data,
                               Mux(mv_hit, self.mv_rsp_data,
                               Mux(wb2_hit, WB.wb2_data, WB.wb_data)))))
            with m.If(any_hit):
                m.d.sync += regs[i].eq(data)

        for i in range(32):
            with m.If(WB.valid & WB.fp_wb_en & (WB.rd == i)):
                with m.If(self.enable_q & ~WB.fp_wb_q):
                    m.d.sync += fregs[i].eq(Cat(WB.fp_wb_data[0:64], C(-1, 64)))
                with m.Else():
                    m.d.sync += fregs[i].eq(WB.fp_wb_data)

        # (scoreboard pending_rd_mask update moved into GCSubsystem)

        # 调试导出
        m.d.comb += [
            self.dbg_pending_rd_mask.eq(pending_rd_mask),
            self.dbg_gc_waiting.eq(gc_fire),  # simplified
            self.dbg_gc_fire.eq(gc.dbg_gc_fire),
            self.dbg_gc_rs1.eq(gc_fwd_rs1),
            self.dbg_gc_rs2.eq(gc_fwd_rs2),
            self.dbg_stall.eq(stall),
            self.dbg_stall_gc_order.eq(stall_gc_order),
            self.dbg_stall_gc_issue.eq(stall_gc_issue),
            self.dbg_ex1_valid.eq(EX1.valid), self.dbg_ex1_rd.eq(EX1.rd),
            self.dbg_ex1_is_load.eq(EX1.is_load),
            self.dbg_mem1_valid.eq(MEM1.valid), self.dbg_mem1_rd.eq(MEM1.rd),
            self.dbg_mem1_is_load.eq(MEM1.is_load),
            self.dbg_mem2_valid.eq(MEM2.valid), self.dbg_mem2_rd.eq(MEM2.rd),
            self.dbg_mem2_is_load.eq(MEM2.is_load), self.dbg_mem2_wb_data.eq(MEM2.wb_data),
            self.dbg_id1_valid.eq(ID1.valid), self.dbg_id1_rd.eq(ID1.rd),
            self.dbg_id1_is_load.eq(0),
            self.dbg_id1_uses_int_rs1.eq(uses_rs1_id1),
            self.dbg_id1_uses_int_rs2.eq(uses_rs2_id1),
            self.dbg_id1_writes_int_rd.eq(writes_rd_id1),
            self.dbg_id2_valid.eq(ID2.valid), self.dbg_id2_rd.eq(ID2.rd),
            self.dbg_id2_is_load.eq(ID2.is_load),
            self.dbg_ex1_a.eq(EX1.rs1v),
            self.dbg_ex1_b.eq(EX1.rs2v),
            self.dbg_ex1_src_a.eq(ex1_a),
            self.dbg_ex1_src_b.eq(ex1_b),
            self.dbg_ex1_rs1.eq(EX1.rs1),
            self.dbg_ex1_rs2.eq(EX1.rs2),
            self.dbg_is_rs1.eq(IS.rs1),
            self.dbg_is_rs2.eq(IS.rs2),
            self.dbg_ex1_funct3.eq(EX1.funct3),
            self.dbg_ex1_funct7.eq(EX1.funct7),
            self.dbg_ex1_opcode.eq(EX1.opcode),
            self.dbg_reg_rdata.eq(Mux(self.dbg_reg_addr == 0, 0, regs[self.dbg_reg_addr])),
            self.dbg_is_valid.eq(IS.valid),
            self.dbg_is_is_gc.eq(IS.is_gc),
            self.dbg_stall_front.eq(stall_front),
            self.dbg_stall_dep_id1.eq(stall_dep_id1),
            self.dbg_stall_dep_id2.eq(stall_dep_id2),
        ]

        # Debug signal wiring
        m.d.comb += [
            self.dbg_ex1_valid.eq(EX1.valid), self.dbg_ex1_rd.eq(EX1.rd),
            self.dbg_ex1_is_load.eq(EX1.is_load),
            self.dbg_mem1_valid.eq(MEM1.valid), self.dbg_mem1_rd.eq(MEM1.rd),
            self.dbg_mem1_is_load.eq(MEM1.is_load),
            self.dbg_mem2_valid.eq(MEM2.valid), self.dbg_mem2_rd.eq(MEM2.rd),
            self.dbg_mem2_is_load.eq(MEM2.is_load), self.dbg_mem2_wb_data.eq(MEM2.wb_data),
            self.dbg_is_valid.eq(IS.valid), self.dbg_is_is_gc.eq(IS.is_gc),
            self.dbg_reg_rdata.eq(Mux(self.dbg_reg_addr == 0, 0, regs[self.dbg_reg_addr])),
            self.dbg_stall.eq(stall), self.dbg_stall_front.eq(stall_front),
            self.dbg_stall_dep_id1.eq(stall_dep_id1), self.dbg_stall_dep_id2.eq(stall_dep_id2),
            self.dbg_stall_gc_order.eq(stall_gc_order), self.dbg_stall_gc_issue.eq(stall_gc_issue),
            self.dbg_gc_fire.eq(gc_fire), self.dbg_gc_waiting.eq(0),
            self.dbg_gc_rs1.eq(gc_fwd_rs1), self.dbg_gc_rs2.eq(gc_fwd_rs2),
            self.dbg_pending_rd_mask.eq(pending_rd_mask),
            self.dbg_id1_valid.eq(ID1.valid), self.dbg_id1_rd.eq(ID1.rd),
            self.dbg_id1_is_load.eq(0),  # simplified
            self.dbg_id1_uses_int_rs1.eq(uses_rs1_id1),
            self.dbg_id1_uses_int_rs2.eq(uses_rs2_id1),
            self.dbg_id1_writes_int_rd.eq(writes_rd_id1),
            self.dbg_id2_valid.eq(ID2.valid), self.dbg_id2_rd.eq(ID2.rd),
            self.dbg_id2_is_load.eq(ID2.is_load),
            self.dbg_ex1_a.eq(EX1.rs1v),
            self.dbg_ex1_b.eq(EX1.rs2v),
            self.dbg_ex1_src_a.eq(ex1_a),
            self.dbg_ex1_src_b.eq(ex1_b),
            self.dbg_ex1_rs1.eq(EX1.rs1),
            self.dbg_ex1_rs2.eq(EX1.rs2),
            self.dbg_is_rs1.eq(IS.rs1),
            self.dbg_is_rs2.eq(IS.rs2),
            self.dbg_ex1_funct3.eq(EX1.funct3),
            self.dbg_ex1_funct7.eq(EX1.funct7),
            self.dbg_ex1_opcode.eq(EX1.opcode),
        ]
        return m
