from amaranth import *
from .isa_module import ISAExtension
from .isa import LOAD_FP, STORE_FP, OP_FP, MADD, MSUB, NMSUB, NMADD

class D(ISAExtension):
    """Double-precision floating-point extension (decode stub, no FPU)."""
    def __init__(self, xlen=32):
        super().__init__(xlen=xlen, name="d")
    def elaborate(self, platform):
        m = Module()
        # Match double-precision load/store (funct3=0b011)
        is_fp_load = (self.opcode == LOAD_FP) & (self.funct3 == 0b011)
        is_fp_store = (self.opcode == STORE_FP) & (self.funct3 == 0b011)
        # Match FP computational ops that are double-precision
        # In a real CPU this is determined by instruction encoding within OP_FP/MADD/etc.
        # For the stub, we exclude the ones already matched by F (single precision, funct3=010)
        # Since both F and D share the same opcode space, they must not conflict.
        # D matches funct3=011 for loads/stores. For OP_FP, the precision is
        # encoded differently, so we DO match the same OP_FP opcodes but they will
        # conflict with F if both are in the system. To avoid this:
        # - F matches LOAD_FP/STORE_FP funct3=010 + all OP_FP/MADD/etc. 
        # - D matches LOAD_FP/STORE_FP funct3=011 ONLY
        # (OP_FP operations are handled by F module only in this stub implementation)
        is_fp_op = 0  # D doesn't match any OP_FP to avoid conflict with F
        
        m.d.comb += self.matched.eq(self.valid & (is_fp_load | is_fp_store | is_fp_op))
        m.d.comb += [
            self.is_load.eq(is_fp_load),
            self.is_store.eq(is_fp_store),
            self.wb_en.eq(1),
            self.wb_data.eq(0),  # stub
            self.alu_out.eq(0),
            self.mem_addr.eq(0),
            self.mem_wdata.eq(0),
            self.redirect.eq(0), self.redirect_pc.eq(0), self.trap.eq(0),
            self.br_valid.eq(0), self.br_pc.eq(0), self.br_target.eq(0),
            self.br_taken.eq(0), self.br_is_branch.eq(0),
            self.br_is_jal.eq(0), self.br_is_jalr.eq(0),
            self.is_branch.eq(0), self.is_jal.eq(0), self.is_jalr.eq(0),
            self.is_fence.eq(0), self.is_gc.eq(0),
            self.gc_op.eq(0), self.gc_rd.eq(0),
            self.gc_rs1.eq(0), self.gc_rs2.eq(0), self.gc_is_reloc.eq(0),
        ]
        return m
