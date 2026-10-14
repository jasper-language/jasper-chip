from amaranth import Elaboratable, Module, Signal


class BaseRS1UsageControl(Elaboratable):
    """Common integer rs1-use gate before extension-specific exclusions."""

    def __init__(self):
        self.valid = Signal()
        self.is_jal = Signal()
        self.is_fence = Signal()
        self.uses_rs1 = Signal()

    def elaborate(self, platform):
        m = Module()
        m.d.comb += self.uses_rs1.eq(
            self.valid & ~self.is_jal & ~self.is_fence
        )
        return m
