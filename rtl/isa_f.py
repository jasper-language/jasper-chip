from amaranth import *
from .isa_module import ISAExtension
from .isa import LOAD_FP, STORE_FP, MADD, MSUB, NMSUB, NMADD, OP_FP


class F(ISAExtension):
    """Single-precision floating-point extension (decode stub, no FPU)."""
    def __init__(self, xlen=32):
        super().__init__(xlen=xlen, name="f")

    def elaborate(self, platform):
        m = Module()

        is_fp_load  = (self.opcode == LOAD_FP) & (self.funct3 == 0b010)
        is_fp_store = (self.opcode == STORE_FP) & (self.funct3 == 0b010)
        is_fp_op = (self.opcode == OP_FP) | (self.opcode == MADD) | \
                   (self.opcode == MSUB) | (self.opcode == NMSUB) | \
                   (self.opcode == NMADD)

        mem_addr = self.ex1_a + self.imm

        m.d.comb += self.matched.eq(self.valid & (is_fp_load | is_fp_store | is_fp_op))

        m.d.comb += [
            self.is_load.eq(is_fp_load),
            self.is_store.eq(is_fp_store),
            self.wb_en.eq(is_fp_load | is_fp_op),
            self.wb_data.eq(0),
            self.alu_out.eq(0),
            self.mem_addr.eq(mem_addr),
            self.mem_wdata.eq(self.ex1_b),
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
