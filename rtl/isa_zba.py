from amaranth import *
from .isa_module import ISAExtension
from .isa import OP, OP_32

class Zba(ISAExtension):
    def __init__(self, xlen=32):
        super().__init__(xlen=xlen, name="zba")
    def elaborate(self, platform):
        m = Module()
        XLEN = self.xlen

        # Match conditions
        is_rv32_shxadd = (self.opcode == OP) & (self.funct7 == 0b0010000) & \
                         ((self.funct3 == 0b010) | (self.funct3 == 0b100) | (self.funct3 == 0b110))
        is_add_uw = (XLEN == 64) & (self.opcode == OP_32) & (self.funct7 == 0b0000100) & (self.funct3 == 0b000)
        is_rv64_shxadd_uw = (XLEN == 64) & (self.opcode == OP_32) & (self.funct7 == 0b0010000) & \
                            ((self.funct3 == 0b010) | (self.funct3 == 0b100) | (self.funct3 == 0b110))

        m.d.comb += self.matched.eq(self.valid & (is_rv32_shxadd | is_add_uw | is_rv64_shxadd_uw))

        # Select shift amount based on funct3
        shift = Signal(6)
        with m.Switch(self.funct3):
            with m.Case(0b010): m.d.comb += shift.eq(1)
            with m.Case(0b100): m.d.comb += shift.eq(2)
            with m.Case(0b110): m.d.comb += shift.eq(3)
            with m.Default():   m.d.comb += shift.eq(0)

        # Zba shifts rs1 and adds rs2. The .UW forms zero-extend rs1 first.
        op_a = Signal(XLEN)
        with m.If(is_add_uw | is_rv64_shxadd_uw):
            m.d.comb += op_a.eq(self.ex1_a[0:32])
        with m.Else():
            m.d.comb += op_a.eq(self.ex1_a)

        shifted = Signal(XLEN)
        m.d.comb += shifted.eq(op_a << shift)

        m.d.comb += [
            self.alu_out.eq(self.ex1_b + shifted),
            self.wb_en.eq(1),
            self.wb_data.eq(self.alu_out),
            self.mem_addr.eq(0), self.mem_wdata.eq(0),
            self.redirect.eq(0), self.redirect_pc.eq(0), self.trap.eq(0),
            self.br_valid.eq(0), self.br_pc.eq(0), self.br_target.eq(0),
            self.br_taken.eq(0), self.br_is_branch.eq(0),
            self.br_is_jal.eq(0), self.br_is_jalr.eq(0),
            self.is_load.eq(0), self.is_store.eq(0), self.is_branch.eq(0),
            self.is_jal.eq(0), self.is_jalr.eq(0), self.is_fence.eq(0),
            self.is_gc.eq(0),
            self.gc_op.eq(0), self.gc_rd.eq(0),
            self.gc_rs1.eq(0), self.gc_rs2.eq(0), self.gc_is_reloc.eq(0),
        ]
        return m
