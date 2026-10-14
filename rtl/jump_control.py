from amaranth import C, Elaboratable, Module, Mux, Signal


class JumpControl(Elaboratable):
    """RISC-V JAL/JALR link and target address calculation."""

    def __init__(self, xlen):
        self.xlen = xlen
        self.pc = Signal(xlen)
        self.base = Signal(xlen)
        self.imm = Signal(xlen)
        self.compressed = Signal()
        self.jalr = Signal()
        self.link = Signal(xlen)
        self.target = Signal(xlen)

    def elaborate(self, platform):
        m = Module()
        m.d.comb += [
            self.link.eq(
                self.pc + Mux(self.compressed, C(2, self.xlen), C(4, self.xlen))
            ),
            self.target.eq(Mux(
                self.jalr,
                (self.base + self.imm) & C(-2, self.xlen),
                self.pc + self.imm,
            )),
        ]
        return m
