# rtl/gc_multi_engine_coproc.py
# N 引擎 GCSweepCoProc（N=1,2,4,8），每引擎管 entries/N 槽位 + cores/N 核。
from amaranth import *
from amaranth.lib.fifo import SyncFIFO, SyncFIFOBuffered
from .isa import GC_NEW, GC_DROP, GC_CLONE, GC_PIN, GC_UNPIN, GC_RELOC, GC_EPOCH
from math import log2


class GCPerEngine(Elaboratable):
    """单引擎实例：管理一组核的命令 FIFO + 表分片。"""
    def __init__(self, engine_id, core_base, num_cores, entries, fifo_depth=8, rsp_fifo_depth=8):
        self.engine_id = engine_id
        self.core_base = core_base  # 起始核号
        self.num_cores = num_cores
        self.entries = entries
        self.fifo_depth = fifo_depth
        self.rsp_fifo_depth = rsp_fifo_depth
        self.tag_w = 8

        # 外部接口：cmd_enq/rsp 数组，由 top 路由
        self.cmd_tag = Array(Signal(self.tag_w) for _ in range(num_cores))
        self.cmd_enq_valid = Array(Signal() for _ in range(num_cores))
        self.cmd_enq_ready = Array(Signal() for _ in range(num_cores))
        self.cmd_op = Array(Signal(3) for _ in range(num_cores))
        self.cmd_rd = Array(Signal(5) for _ in range(num_cores))
        self.cmd_rs1 = Array(Signal(32) for _ in range(num_cores))
        self.cmd_rs2 = Array(Signal(32) for _ in range(num_cores))

        self.rsp_valid = Array(Signal() for _ in range(num_cores))
        self.rsp_tag = Array(Signal(self.tag_w) for _ in range(num_cores))
        self.rsp_rd = Array(Signal(5) for _ in range(num_cores))
        self.rsp_data = Array(Signal(32) for _ in range(num_cores))
        self.rsp_take = Array(Signal() for _ in range(num_cores))
        self.trap = Array(Signal() for _ in range(num_cores))
        self.epoch_tick = Array(Signal() for _ in range(num_cores))
        self.mv_upd_valid = Array(Signal() for _ in range(num_cores))
        self.mv_upd_old = Array(Signal(32) for _ in range(num_cores))
        self.mv_upd_new = Array(Signal(32) for _ in range(num_cores))
        self.mv_upd_ready = Array(Signal(reset=1) for _ in range(num_cores))

    def elaborate(self, platform):
        m = Module(); NC = self.num_cores; N = self.entries

        # ---- Table bank ----
        rc  = Memory(width=16, depth=N, init=[0]*N)
        pin = Memory(width=1,  depth=N, init=[0]*N)
        used= Memory(width=1,  depth=N, init=[0]*N)
        m.submodules.rc_r   = rc_r   = rc.read_port(domain="comb")
        m.submodules.rc_w   = rc_w   = rc.write_port()
        m.submodules.pin_r  = pin_r  = pin.read_port(domain="comb")
        m.submodules.pin_w  = pin_w  = pin.write_port()
        m.submodules.used_r = used_r = used.read_port(domain="comb")
        m.submodules.used_w = used_w = used.write_port()
        m.d.comb += [rc_w.en.eq(0), pin_w.en.eq(0), used_w.en.eq(0)]

        # 每引擎独立 alloc_ptr（从 engine_id * entries 偏移开始）
        alloc_ptr = Signal(range(N), reset=0)

        rr_ptr = Signal(range(NC), reset=0)

        # ---- Command FIFOs ----
        fifos_list = []
        for i in range(NC):
            fifo = SyncFIFO(width=self.tag_w + 3 + 5 + 32 + 32, depth=self.fifo_depth)
            fifos_list.append(fifo)
            m.submodules[f"cmd_fifo_{i}"] = fifo
            m.d.comb += [
                fifo.w_data.eq(Cat(self.cmd_tag[i], self.cmd_op[i], self.cmd_rd[i],
                                   self.cmd_rs1[i], self.cmd_rs2[i])),
                fifo.w_en.eq(self.cmd_enq_valid[i] & fifo.w_rdy),
                self.cmd_enq_ready[i].eq(fifo.w_rdy),
            ]
        fifos = Array(fifos_list)

        # ---- Response FIFOs ----
        rsp_fifos = []
        for i in range(NC):
            rf = SyncFIFOBuffered(width=self.tag_w + 5 + 32, depth=self.rsp_fifo_depth)
            rsp_fifos.append(rf)
            m.submodules[f"rsp_fifo_{i}"] = rf
            m.d.comb += [
                self.rsp_valid[i].eq(rf.r_rdy),
                self.rsp_tag[i].eq(rf.r_data[0:self.tag_w]),
                self.rsp_rd[i].eq(rf.r_data[self.tag_w:self.tag_w+5]),
                self.rsp_data[i].eq(rf.r_data[self.tag_w+5:self.tag_w+5+32]),
                rf.r_en.eq(self.rsp_take[i] & rf.r_rdy),
            ]
        rsp_fifos_arr = Array(rsp_fifos)

        # ---- Sideband ----
        trap_fire = Signal(reset=0); trap_core = Signal(range(NC), reset=0)
        epoch_fire = Signal(reset=0); epoch_core = Signal(range(NC), reset=0)
        m.d.sync += [trap_fire.eq(0), epoch_fire.eq(0)]
        for i in range(NC):
            m.d.comb += [self.trap[i].eq(trap_fire & (trap_core == i)),
                         self.epoch_tick[i].eq(epoch_fire & (epoch_core == i))]

        mv_out_valid = Array(Signal(reset=0) for _ in range(NC))
        mv_out_old   = Array(Signal(32, reset=0) for _ in range(NC))
        mv_out_new   = Array(Signal(32, reset=0) for _ in range(NC))
        for i in range(NC):
            m.d.comb += [
                self.mv_upd_valid[i].eq(mv_out_valid[i]),
                self.mv_upd_old[i].eq(mv_out_old[i]),
                self.mv_upd_new[i].eq(mv_out_new[i]),
            ]
            with m.If(mv_out_valid[i] & self.mv_upd_ready[i]):
                m.d.sync += mv_out_valid[i].eq(0)

        # ---- RR arbiter (over this engine's cores) ----
        sel = Signal(range(NC)); have = Signal()
        sel_v = rr_ptr; have_v = Const(0)
        for k in range(NC):
            idx = rr_ptr + k
            idx = Mux(idx >= NC, idx - NC, idx)
            req = fifos[idx].r_rdy
            sel_v = Mux((~have_v) & req, idx, sel_v)
            have_v = have_v | req
        m.d.comb += [sel.eq(sel_v), have.eq(have_v)]

        # ---- Unpack ----
        tag = Signal(self.tag_w); op = Signal(3); rd = Signal(5)
        rs1 = Signal(32); rs2 = Signal(32)
        m.d.comb += [
            tag.eq(fifos[sel].r_data[0:self.tag_w]),
            op.eq(fifos[sel].r_data[self.tag_w:self.tag_w+3]),
            rd.eq(fifos[sel].r_data[self.tag_w+3:self.tag_w+3+5]),
            rs1.eq(fifos[sel].r_data[self.tag_w+8:self.tag_w+8+32]),
            rs2.eq(fifos[sel].r_data[self.tag_w+40:self.tag_w+40+32]),
        ]
        idx1 = Signal(8); idx2 = Signal(8)
        m.d.comb += [idx1.eq(rs1[0:8]), idx2.eq(rs2[0:8])]
        m.d.comb += [rc_r.addr.eq(idx1), pin_r.addr.eq(idx1), used_r.addr.eq(idx1)]

        used_ap_r = used.read_port(domain="comb")
        m.submodules.used_ap_r = used_ap_r
        m.d.comb += used_ap_r.addr.eq(alloc_ptr)

        used2_r = used.read_port(domain="comb")
        m.submodules.used2_r = used2_r
        m.d.comb += used2_r.addr.eq(idx2)

        # ---- RELOC two-step ----
        reloc_pending = Signal(reset=0); reloc_src = Signal(8, reset=0)
        with m.If(reloc_pending):
            m.d.comb += [
                used_w.en.eq(1), used_w.addr.eq(reloc_src), used_w.data.eq(0),
                rc_w.en.eq(1),   rc_w.addr.eq(reloc_src),   rc_w.data.eq(0),
                pin_w.en.eq(1),  pin_w.addr.eq(reloc_src),  pin_w.data.eq(0),
            ]
            m.d.sync += reloc_pending.eq(0)

        can_accept = Signal()
        is_reloc = Signal()
        m.d.comb += [is_reloc.eq(op == GC_RELOC)]
        m.d.comb += can_accept.eq(have & ~reloc_pending &
                                   rsp_fifos_arr[sel].w_rdy)
        m.d.comb += fifos[sel].r_en.eq(0)

        execute = Signal()
        m.d.comb += execute.eq(can_accept & ~(is_reloc & mv_out_valid[sel]))

        with m.If(execute):
            m.d.comb += fifos[sel].r_en.eq(1)
            m.d.sync += rr_ptr.eq(sel + 1)

            rsp_data_val = Signal(32)

            def raise_trap():
                m.d.sync += [trap_fire.eq(1), trap_core.eq(sel)]

            with m.Switch(op):
                with m.Case(GC_NEW):
                    with m.If(used_ap_r.data == 0):
                        m.d.comb += [
                            used_w.en.eq(1), used_w.addr.eq(alloc_ptr), used_w.data.eq(1),
                            rc_w.en.eq(1),   rc_w.addr.eq(alloc_ptr),   rc_w.data.eq(1),
                            pin_w.en.eq(1),  pin_w.addr.eq(alloc_ptr),  pin_w.data.eq(0),
                            rsp_data_val.eq(alloc_ptr),
                        ]
                        m.d.sync += [
                            alloc_ptr.eq(Mux(alloc_ptr == (N - 1), 0, alloc_ptr + 1)),
                        ]
                    with m.Else():
                        raise_trap()
                with m.Case(GC_CLONE):
                    with m.If(used_r.data):
                        with m.If(rc_r.data == 0xFFFF): raise_trap()
                        with m.Else():
                            m.d.comb += [
                                rc_w.en.eq(1), rc_w.addr.eq(idx1), rc_w.data.eq(rc_r.data + 1),
                                rsp_data_val.eq(rs1),
                            ]
                    with m.Else(): raise_trap()
                with m.Case(GC_DROP):
                    with m.If(used_r.data):
                        with m.If(pin_r.data): raise_trap()
                        with m.Elif(rc_r.data == 0): raise_trap()
                        with m.Else():
                            newrc = Signal(16)
                            m.d.comb += newrc.eq(rc_r.data - 1)
                            m.d.comb += [rc_w.en.eq(1), rc_w.addr.eq(idx1), rc_w.data.eq(newrc)]
                            with m.If(newrc == 0):
                                m.d.comb += [used_w.en.eq(1), used_w.addr.eq(idx1), used_w.data.eq(0)]
                    with m.Else(): raise_trap()
                with m.Case(GC_PIN):
                    with m.If(used_r.data):
                        m.d.comb += [pin_w.en.eq(1), pin_w.addr.eq(idx1), pin_w.data.eq(1)]
                    with m.Else(): raise_trap()
                with m.Case(GC_UNPIN):
                    with m.If(used_r.data):
                        m.d.comb += [pin_w.en.eq(1), pin_w.addr.eq(idx1), pin_w.data.eq(0)]
                        with m.If(rc_r.data == 0):
                            m.d.comb += [used_w.en.eq(1), used_w.addr.eq(idx1), used_w.data.eq(0)]
                    with m.Else(): raise_trap()
                with m.Case(GC_RELOC):
                    with m.If(used_r.data & (pin_r.data == 0) & (used2_r.data == 0)):
                        m.d.comb += [
                            used_w.en.eq(1), used_w.addr.eq(idx2), used_w.data.eq(1),
                            rc_w.en.eq(1),   rc_w.addr.eq(idx2),   rc_w.data.eq(rc_r.data),
                            pin_w.en.eq(1),  pin_w.addr.eq(idx2),  pin_w.data.eq(pin_r.data),
                        ]
                        m.d.sync += [reloc_pending.eq(1), reloc_src.eq(idx1)]
                        m.d.sync += [
                            mv_out_valid[sel].eq(1),
                            mv_out_old[sel].eq(rs1),
                            mv_out_new[sel].eq(rs2),
                        ]
                    with m.Else(): raise_trap()
                with m.Case(GC_EPOCH):
                    m.d.sync += [epoch_fire.eq(1), epoch_core.eq(sel)]
                with m.Default(): raise_trap()

            m.d.comb += [
                rsp_fifos_arr[sel].w_en.eq(rsp_fifos_arr[sel].w_rdy),
                rsp_fifos_arr[sel].w_data.eq(Cat(tag, rd, rsp_data_val)),
            ]

        with m.Elif(have & is_reloc & mv_out_valid[sel]):
            m.d.sync += rr_ptr.eq(sel + 1)

        return m


class GCMultiEngineCoProc(Elaboratable):
    """N 引擎 GC 协处理器（N=1,2,4,8，2 的等幂次）。
    每核接口与 GCSweepCoProc 兼容。
    """
    def __init__(self, ncores=4, entries=256, num_engines=1, fifo_depth=8, rsp_fifo_depth=8):
        if num_engines not in (1, 2, 4, 8):
            raise ValueError(f"num_engines must be 1/2/4/8, got {num_engines}")
        if ncores % num_engines != 0:
            raise ValueError(f"ncores ({ncores}) must be divisible by num_engines ({num_engines})")
        if entries % num_engines != 0:
            raise ValueError(f"entries ({entries}) must be divisible by num_engines ({num_engines})")

        self.ncores = ncores
        self.entries = entries
        self.num_engines = num_engines
        self.fifo_depth = fifo_depth
        self.rsp_fifo_depth = rsp_fifo_depth
        self.tag_w = 8
        self.engine_bits = int(log2(num_engines)) if num_engines > 1 else 0

        # 外壳接口（与 GCSweepCoProc 一致）
        self.cmd_tag       = Array(Signal(self.tag_w, name=f"cmd{i}_tag") for i in range(ncores))
        self.cmd_enq_valid = Array(Signal(name=f"cmd{i}_valid") for i in range(ncores))
        self.cmd_enq_ready = Array(Signal(name=f"cmd{i}_ready") for i in range(ncores))
        self.cmd_op        = Array(Signal(3, name=f"cmd{i}_op") for i in range(ncores))
        self.cmd_rd        = Array(Signal(5, name=f"cmd{i}_rd") for i in range(ncores))
        self.cmd_rs1       = Array(Signal(32, name=f"cmd{i}_rs1") for i in range(ncores))
        self.cmd_rs2       = Array(Signal(32, name=f"cmd{i}_rs2") for i in range(ncores))
        self.rsp_valid     = Array(Signal(name=f"rsp{i}_valid") for i in range(ncores))
        self.rsp_tag       = Array(Signal(self.tag_w, name=f"rsp{i}_tag") for i in range(ncores))
        self.rsp_rd        = Array(Signal(5, name=f"rsp{i}_rd") for i in range(ncores))
        self.rsp_data      = Array(Signal(32, name=f"rsp{i}_data") for i in range(ncores))
        self.rsp_take      = Array(Signal(name=f"rsp{i}_take") for i in range(ncores))
        self.trap          = Array(Signal(name=f"trap{i}") for i in range(ncores))
        self.epoch_tick    = Array(Signal(name=f"epoch{i}_tick") for i in range(ncores))
        self.mv_upd_valid  = Array(Signal(name=f"mvupd{i}_valid") for i in range(ncores))
        self.mv_upd_old    = Array(Signal(32, name=f"mvupd{i}_old") for i in range(ncores))
        self.mv_upd_new    = Array(Signal(32, name=f"mvupd{i}_new") for i in range(ncores))
        self.mv_upd_ready  = Array(Signal(reset=1, name=f"mvupd{i}_ready") for i in range(ncores))

    def elaborate(self, platform):
        m = Module(); NE = self.num_engines; NC = self.ncores
        CPE = NC // NE     # cores per engine
        EPE = self.entries // NE  # entries per engine

        engines = []
        for eid in range(NE):
            core_base = eid * CPE
            eng = GCPerEngine(
                engine_id=eid, core_base=core_base, num_cores=CPE,
                entries=EPE, fifo_depth=self.fifo_depth,
                rsp_fifo_depth=self.rsp_fifo_depth)
            engines.append(eng)
            m.submodules[f"engine_{eid}"] = eng

            # 路由：engine[eid] 的 core_local = core_global - core_base
            for local_i in range(CPE):
                global_i = core_base + local_i
                m.d.comb += [
                    eng.cmd_tag[local_i].eq(self.cmd_tag[global_i]),
                    eng.cmd_enq_valid[local_i].eq(self.cmd_enq_valid[global_i]),
                    self.cmd_enq_ready[global_i].eq(eng.cmd_enq_ready[local_i]),
                    eng.cmd_op[local_i].eq(self.cmd_op[global_i]),
                    eng.cmd_rd[local_i].eq(self.cmd_rd[global_i]),
                    eng.cmd_rs1[local_i].eq(self.cmd_rs1[global_i]),
                    eng.cmd_rs2[local_i].eq(self.cmd_rs2[global_i]),
                    self.rsp_valid[global_i].eq(eng.rsp_valid[local_i]),
                    self.rsp_tag[global_i].eq(eng.rsp_tag[local_i]),
                    self.rsp_rd[global_i].eq(eng.rsp_rd[local_i]),
                    self.rsp_data[global_i].eq(eng.rsp_data[local_i]),
                    eng.rsp_take[local_i].eq(self.rsp_take[global_i]),
                    self.trap[global_i].eq(eng.trap[local_i]),
                    self.epoch_tick[global_i].eq(eng.epoch_tick[local_i]),
                    self.mv_upd_valid[global_i].eq(eng.mv_upd_valid[local_i]),
                    self.mv_upd_old[global_i].eq(eng.mv_upd_old[local_i]),
                    self.mv_upd_new[global_i].eq(eng.mv_upd_new[local_i]),
                    eng.mv_upd_ready[local_i].eq(self.mv_upd_ready[global_i]),
                ]

        return m
