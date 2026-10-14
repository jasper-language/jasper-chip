from amaranth import Elaboratable, Module, Signal


class DependencyStallControl(Elaboratable):
    """Combine integer and floating dependency hazards into a stage stall."""

    def __init__(self):
        self.rs1_hazard = Signal()
        self.rs2_hazard = Signal()
        self.waw_hazard = Signal()
        self.include_waw = Signal()
        self.suppress_integer = Signal()
        self.fp_store_hazard = Signal()
        self.stall = Signal()

    def elaborate(self, platform):
        m = Module()
        integer_hazard = Signal()
        m.d.comb += [
            integer_hazard.eq(
                self.rs1_hazard | self.rs2_hazard |
                (self.include_waw & self.waw_hazard)
            ),
            self.stall.eq(
                (integer_hazard & ~self.suppress_integer) |
                self.fp_store_hazard
            ),
        ]
        return m
