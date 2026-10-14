# rtl/gc_coproc.py
from amaranth import *
from amaranth.lib.fifo import SyncFIFO
from .isa import GC_NEW, GC_DROP, GC_CLONE, GC_PIN, GC_UNPIN, GC_RELOC


class GCCoProc(Elaboratable):
    def __init__(self, ncores=4, entries=256, fifo_depth=8):
        self.ncores = ncores
        self.entries = entries
        self.fifo_depth = fifo_depth

        # Use Array so we can index with Signals
        self.cmd_enq_valid = Array(Signal(name=f"cmd{i}_valid") for i in range(ncores))
        self.cmd_enq_ready = Array(Signal(name=f"cmd{i}_ready") for i in range(ncores))
        self.cmd_op        = Array(Signal(3,  name=f"cmd{i}_op")   for i in range(ncores))
        self.cmd_rd        = Array(Signal(5,  name=f"cmd{i}_rd")   for i in range(ncores))
        self.cmd_rs1       = Array(Signal(32, name=f"cmd{i}_rs1")  for i in range(ncores))
        self.cmd_rs2       = Array(Signal(32, name=f"cmd{i}_rs2")  for i in range(ncores))

        self.rsp_valid     = Array(Signal(name=f"rsp{i}_valid") for i in range(ncores))
        self.rsp_rd        = Array(Signal(5,  name=f"rsp{i}_rd") for i in range(ncores))
        self.rsp_data      = Array(Signal(32, name=f"rsp{i}_data") for i in range(ncores))
        self.rsp_take      = Array(Signal(name=f"rsp{i}_take") for i in range(ncores))

        self.trap          = Array(Signal(name=f"trap{i}") for i in range(ncores))

    def elaborate(self, platform):
        m = Module()
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
            fifo = SyncFIFO(width=3 + 5 + 32 + 32, depth=self.fifo_depth)
            fifos_list.append(fifo)
            m.submodules[f"cmd_fifo{i}"] = fifo

            m.d.comb += [
                fifo.w_en.eq(self.cmd_enq_valid[i]),
                fifo.w_data.eq(Cat(self.cmd_op[i], self.cmd_rd[i], self.cmd_rs1[i], self.cmd_rs2[i])),
                self.cmd_enq_ready[i].eq(fifo.w_rdy),
            ]
        fifos = Array(fifos_list)
        # Default: do not pop any FIFO. (SyncFIFO pops only when r_en=1 at clock edge)
        for i in range(self.ncores):
            m.d.comb += fifos[i].r_en.eq(0)


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

        # clear every cycle
        m.d.sync += trap_fire.eq(0)

        # comb decode to per-core trap outputs (ONLY comb drive of self.trap)
        for i in range(self.ncores):
            m.d.comb += self.trap[i].eq(trap_fire & (trap_core == i))

        # ---- Select FIFO round-robin
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
        op  = Signal(3)
        rd  = Signal(5)
        rs1 = Signal(32)
        rs2 = Signal(32)
        m.d.comb += [
            op.eq(fifos[sel].r_data[0:3]),
            rd.eq(fifos[sel].r_data[3:8]),
            rs1.eq(fifos[sel].r_data[8:40]),
            rs2.eq(fifos[sel].r_data[40:72]),
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
        with m.If(can_accept & ~reloc_pending):
            # Pop selected core's FIFO (consume the command) when we actually execute it.
            for i in range(self.ncores):
                with m.If(sel == i):
                    m.d.comb += fifos[i].r_en.eq(1)

            m.d.sync += rr_ptr.eq(sel + 1)

            # default response
            m.d.sync += [
                self.rsp_valid[sel].eq(1),
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
                        m.d.comb += [
                            rc_w.en.eq(1), rc_w.addr.eq(idx1), rc_w.data.eq(rc_r.data + 1),
                        ]
                        m.d.sync += self.rsp_data[sel].eq(rs1)
                    with m.Else():
                        raise_trap()

                with m.Case(GC_DROP):
                    # Model semantics:
                    #   - if unused => trap
                    #   - if pinned => trap (cannot drop a pinned object)
                    #   - if rc==0  => trap (inconsistent state)
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
                    with m.Else():
                        raise_trap()

                with m.Default():
                    raise_trap()

        return m
