"""Zkr entropy-source CSR execution."""

from amaranth import Module, Mux, Signal

from .isa import SYSTEM
from .isa_module import ISAExtension

SEED_CSR = 0x015
SEED_OPST_WAIT = 0b01
SEED_OPST_ES16 = 0b10


class Zkr(ISAExtension):
    """Implement the seed CSR using an explicit external entropy handshake."""

    def __init__(self, xlen=32):
        if xlen != 32:
            raise ValueError("This Zkr seed unit currently targets RV32")
        super().__init__(xlen=xlen, name="zkr")
        self.entropy = Signal(16)
        self.entropy_valid = Signal()

    def elaborate(self, platform):
        m = Module()
        m.d.comb += [
            self.matched.eq(0), self.wb_en.eq(0), self.wb_data.eq(0), self.alu_out.eq(0),
            self.mem_addr.eq(0), self.mem_wdata.eq(0), self.redirect.eq(0), self.redirect_pc.eq(0),
            self.trap.eq(0), self.br_valid.eq(0), self.br_pc.eq(0), self.br_target.eq(0),
            self.br_taken.eq(0), self.br_is_branch.eq(0), self.br_is_jal.eq(0),
            self.br_is_jalr.eq(0), self.is_load.eq(0), self.is_store.eq(0),
            self.is_branch.eq(0), self.is_jal.eq(0), self.is_jalr.eq(0), self.is_fence.eq(0),
            self.is_gc.eq(0), self.gc_op.eq(0), self.gc_rd.eq(0), self.gc_rs1.eq(0),
            self.gc_rs2.eq(0), self.gc_is_reloc.eq(0),
        ]
        is_seed = self.valid & (self.opcode == SYSTEM) & (self.imm[0:12] == SEED_CSR)
        legal_read = ((self.funct3 == 0b010) | (self.funct3 == 0b011)) & (self.rs1 == 0)
        result = Mux(
            self.entropy_valid,
            (SEED_OPST_ES16 << 30) | self.entropy,
            SEED_OPST_WAIT << 30,
        )
        m.d.comb += self.matched.eq(is_seed)
        with m.If(is_seed & legal_read):
            m.d.comb += [self.wb_en.eq(1), self.wb_data.eq(result), self.alu_out.eq(result)]
        with m.Elif(is_seed):
            m.d.comb += self.trap.eq(1)
        return m
