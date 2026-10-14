from amaranth import Elaboratable, Module, Signal


class PendingRegisterHazard(Elaboratable):
    """Integer RAW/WAW checks against the architectural pending mask."""

    def __init__(self):
        self.uses_rs1 = Signal()
        self.uses_rs2 = Signal()
        self.writes_rd = Signal()
        self.rs1 = Signal(5)
        self.rs2 = Signal(5)
        self.rd = Signal(5)
        self.pending_mask = Signal(32)
        self.rs1_hazard = Signal()
        self.rs2_hazard = Signal()
        self.waw_hazard = Signal()
        self.any_hazard = Signal()

    def elaborate(self, platform):
        m = Module()
        m.d.comb += [
            self.rs1_hazard.eq(
                self.uses_rs1 & (self.rs1 != 0) &
                self.pending_mask.bit_select(self.rs1, 1)
            ),
            self.rs2_hazard.eq(
                self.uses_rs2 & (self.rs2 != 0) &
                self.pending_mask.bit_select(self.rs2, 1)
            ),
            self.waw_hazard.eq(
                self.writes_rd & self.pending_mask.bit_select(self.rd, 1)
            ),
        ]
        m.d.comb += self.any_hazard.eq(
            self.rs1_hazard | self.rs2_hazard | self.waw_hazard
        )
        return m
