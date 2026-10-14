from amaranth import *

from .isa_module import ISAExtension


class Svnapot(ISAExtension):
    def __init__(self, xlen=32):
        super().__init__(xlen=xlen, name="svnapot")
        self.pte = Signal(64)
        self.vpn = Signal(44)
        self.leaf = Signal()
        self.level = Signal(3)
        self.napot_valid = Signal()
        self.page_fault = Signal()
        self.translated_ppn = Signal(44)
        self.region_base = Signal(56)
        self.page_size = Signal(17)

    def elaborate(self, platform):
        m = Module()

        # Svnapot changes page-table entry (PTE) format to support NAPOT
        # superpages.  No new instructions are defined.
        ppn = self.pte[10:54]
        napot = self.pte[63]
        # Version 1.0 standardizes only a 64 KiB region at level zero.
        # All other N=1 encodings, including use at an upper page-table
        # level, are reserved and raise a page fault.
        valid_64k = self.leaf & (self.level == 0) & (ppn[0:4] == 0b1000)
        m.d.comb += [
            self.napot_valid.eq(napot & valid_64k),
            self.page_fault.eq(napot & ~valid_64k),
            self.translated_ppn.eq(ppn),
            self.region_base.eq(Cat(C(0, 12), ppn)),
            self.page_size.eq(4096),
        ]
        with m.If(napot & valid_64k):
            m.d.comb += [
                self.translated_ppn.eq(Cat(self.vpn[0:4], ppn[4:44])),
                self.region_base.eq(Cat(C(0, 16), ppn[4:44])),
                self.page_size.eq(65536),
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
