from amaranth import *

from .isa_module import ISAExtension
from .isa import OP, OP_IMM


class Zbkb(ISAExtension):
    def __init__(self, xlen=32):
        super().__init__(xlen=xlen, name="zbkb")

    def elaborate(self, platform):
        m = Module()

        is_pack = (self.opcode == OP) & (self.funct7 == 0b0000100) & (self.funct3 == 0b100)
        is_packh = (self.opcode == OP) & (self.funct7 == 0b0000100) & (self.funct3 == 0b111)
        is_brev8 = (self.opcode == OP_IMM) & (self.imm[0:12] == 0x687) & (self.funct3 == 0b101)
        is_zip = (self.xlen == 32) & (self.opcode == OP_IMM) & (self.imm[0:12] == 0x08F) & (self.funct3 == 0b001)
        is_unzip = (self.xlen == 32) & (self.opcode == OP_IMM) & (self.imm[0:12] == 0x08F) & (self.funct3 == 0b101)
        m.d.comb += [
            self.matched.eq(self.valid & (is_pack | is_packh | is_brev8 | is_zip | is_unzip)),
            self.wb_en.eq(0),
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

        with m.If(self.matched):
            m.d.comb += self.wb_en.eq(1)
            with m.If(is_pack):
                half = self.xlen // 2
                m.d.comb += self.wb_data.eq(Cat(self.ex1_a[0:half], self.ex1_b[0:half]))
            with m.Elif(is_packh):
                m.d.comb += self.wb_data.eq(Cat(
                    self.ex1_a[0:8], self.ex1_b[0:8], C(0, self.xlen - 16)
                ))
            with m.Elif(is_brev8):
                parts = []
                for byte in range(self.xlen // 8):
                    base = byte * 8
                    parts.append(Cat(*[
                        self.ex1_a[base + 7 - bit] for bit in range(8)
                    ]))
                m.d.comb += self.wb_data.eq(Cat(*parts))
            with m.Elif(is_zip):
                bits = []
                for bit in range(16):
                    bits.extend((self.ex1_a[bit], self.ex1_a[bit + 16]))
                m.d.comb += self.wb_data.eq(Cat(*bits))
            with m.Else():
                bits = [self.ex1_a[2 * bit] for bit in range(16)]
                bits += [self.ex1_a[2 * bit + 1] for bit in range(16)]
                m.d.comb += self.wb_data.eq(Cat(*bits))

        m.d.comb += self.alu_out.eq(self.wb_data)

        return m
