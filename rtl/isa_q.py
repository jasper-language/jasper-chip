from amaranth import *
from .isa_module import ISAExtension
from .isa import LOAD_FP, STORE_FP


class Q(ISAExtension):
    """Quad-precision floating-point extension (decode stub, no FPU).

    Q extension uses LOAD_FP/STORE_FP with funct3=0b100 for quad-precision
    loads and stores. Computational ops (OP_FP/MADD/etc.) are not matched
    to avoid conflict with F and D in this stub implementation.
    """
    def __init__(self, xlen=32):
        super().__init__(xlen=xlen, name="q")

    def elaborate(self, platform):
        m = Module()

        is_fp_load = (self.opcode == LOAD_FP) & (self.funct3 == 0b100)
        is_fp_store = (self.opcode == STORE_FP) & (self.funct3 == 0b100)

        m.d.comb += self.matched.eq(self.valid & (is_fp_load | is_fp_store))

        m.d.comb += [
            self.is_load.eq(is_fp_load),
            self.is_store.eq(is_fp_store),
            self.wb_en.eq(1),
            self.wb_data.eq(0),
            self.alu_out.eq(0),
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
