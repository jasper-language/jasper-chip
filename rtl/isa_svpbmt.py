from amaranth import *

from .isa_module import ISAExtension


class Svpbmt(ISAExtension):
    def __init__(self, xlen=32):
        super().__init__(xlen=xlen, name="svpbmt")
        self.pte = Signal(64)
        self.leaf = Signal()
        self.pbmte = Signal()
        self.pbmt = Signal(2)
        self.page_fault = Signal()
        self.pma = Signal()
        self.noncacheable = Signal()
        self.io = Signal()

    def elaborate(self, platform):
        m = Module()

        # Svpbmt changes page-table entry (PTE) format to support page-based
        # memory types.  No new instructions are defined.
        pbmt = self.pte[61:63]
        m.d.comb += [
            self.pbmt.eq(pbmt),
            self.page_fault.eq((pbmt == 0b11) |
                               ((pbmt != 0) & (~self.leaf | ~self.pbmte))),
            self.pma.eq((pbmt == 0b00) & self.leaf),
            self.noncacheable.eq((pbmt == 0b01) & self.leaf & self.pbmte),
            self.io.eq((pbmt == 0b10) & self.leaf & self.pbmte),
        ]
        m.d.comb += [
            self.matched.eq(0),
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

        return m
