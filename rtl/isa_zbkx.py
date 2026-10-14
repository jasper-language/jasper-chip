from amaranth import *

from .isa_module import ISAExtension
from .isa import OP


class Zbkx(ISAExtension):
    def __init__(self, xlen=32):
        super().__init__(xlen=xlen, name="zbkx")

    def elaborate(self, platform):
        m = Module()
        XLEN = self.xlen
        NUM_BYTES = XLEN // 8
        NUM_NIBBLES = XLEN // 4

        is_xperm8 = (self.opcode == OP) & (self.funct7 == 0b0010100) & (self.funct3 == 0b100)
        is_xperm4 = (self.opcode == OP) & (self.funct7 == 0b0010100) & (self.funct3 == 0b010)

        m.d.comb += [
            self.matched.eq(self.valid & (is_xperm8 | is_xperm4)),
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

        result = Signal(XLEN)
        m.d.comb += result.eq(0)

        # xperm8: rs2 supplies indexes into the byte table in rs1.
        with m.If(is_xperm8 & self.valid):
            for i in range(NUM_BYTES):
                lo = i * 8
                hi = lo + 8
                sel = Signal(3)
                m.d.comb += sel.eq(self.ex1_b[lo:lo + 3])
                rd_byte = Signal(8)
                with m.Switch(sel):
                    for j in range(8):
                        with m.Case(j):
                            if j < NUM_BYTES:
                                b_lo = j * 8
                                m.d.comb += rd_byte.eq(self.ex1_a[b_lo:b_lo + 8])
                            else:
                                m.d.comb += rd_byte.eq(0)
                m.d.comb += result[lo:hi].eq(rd_byte)

        # xperm4: rs2 supplies indexes into the nibble table in rs1.
        with m.Elif(is_xperm4 & self.valid):
            for i in range(NUM_NIBBLES):
                lo = i * 4
                hi = lo + 4
                sel = Signal(4)
                m.d.comb += sel.eq(self.ex1_b[lo:lo + 4])
                rd_nibble = Signal(4)
                with m.Switch(sel):
                    for j in range(16):
                        with m.Case(j):
                            if j < NUM_NIBBLES:
                                n_lo = j * 4
                                m.d.comb += rd_nibble.eq(self.ex1_a[n_lo:n_lo + 4])
                            else:
                                m.d.comb += rd_nibble.eq(0)
                m.d.comb += result[lo:hi].eq(rd_nibble)

        m.d.comb += [
            self.wb_en.eq(self.matched),
            self.wb_data.eq(result),
            self.alu_out.eq(result),
        ]

        return m
