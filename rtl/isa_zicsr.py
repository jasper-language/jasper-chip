from amaranth import *

from .isa_module import ISAExtension
from .isa import SYSTEM


class Zicsr(ISAExtension):
    def __init__(self, xlen=32):
        super().__init__(xlen=xlen, name="zicsr")

    def elaborate(self, platform):
        m = Module()
        XLEN = self.xlen

        is_csr = Signal()
        m.d.comb += is_csr.eq((self.opcode == SYSTEM) & (self.funct3 != 0))

        # Zicntr: free-running 64-bit cycle and instret counters
        cycle = Signal(64, name="cycle")
        instret = Signal(64, name="instret")

        m.d.sync += cycle.eq(cycle + 1)
        m.d.sync += instret.eq(instret + 1)

        # CSR read mux (address from imm[11:0])
        read_data = Signal(XLEN)
        with m.Switch(self.imm[0:12]):
            with m.Case(0xB00):  # mcycle
                with m.If(XLEN == 64):
                    m.d.comb += read_data.eq(cycle)
                with m.Else():
                    m.d.comb += read_data.eq(cycle[0:32])
            with m.Case(0xB02):  # minstret
                with m.If(XLEN == 64):
                    m.d.comb += read_data.eq(instret)
                with m.Else():
                    m.d.comb += read_data.eq(instret[0:32])
            with m.Case(0xB80):  # mcycleh (RV32)
                m.d.comb += read_data.eq(cycle[32:64])
            with m.Case(0xB82):  # minstreth (RV32)
                m.d.comb += read_data.eq(instret[32:64])
            # Zihpm: mhpmcounter3-31 read-only zero stubs
            with m.Case(*range(0xB03, 0xB20)):
                m.d.comb += read_data.eq(0)
            # Zihpm: mhpmevent3-31 read-as-zero stubs
            with m.Case(*range(0x323, 0x340)):
                m.d.comb += read_data.eq(0)
            with m.Default():
                m.d.comb += read_data.eq(0)

        m.d.comb += self.matched.eq(self.valid & is_csr)

        m.d.comb += [
            self.wb_en.eq(1),
            self.wb_data.eq(read_data),
            self.alu_out.eq(read_data),
            self.mem_addr.eq(0),
            self.mem_wdata.eq(0),
            self.redirect.eq(0),
            self.redirect_pc.eq(0),
            self.trap.eq(0),
            self.br_valid.eq(0),
            self.br_pc.eq(0),
            self.br_target.eq(0),
            self.br_taken.eq(0),
            self.br_is_branch.eq(0),
            self.br_is_jal.eq(0),
            self.br_is_jalr.eq(0),
            self.is_load.eq(0),
            self.is_store.eq(0),
            self.is_branch.eq(0),
            self.is_jal.eq(0),
            self.is_jalr.eq(0),
            self.is_fence.eq(0),
            self.is_gc.eq(0),
            self.gc_op.eq(0),
            self.gc_rd.eq(0),
            self.gc_rs1.eq(0),
            self.gc_rs2.eq(0),
            self.gc_is_reloc.eq(0),
        ]

        return m
