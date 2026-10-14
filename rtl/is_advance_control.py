from amaranth import Elaboratable, Module, Signal


class ISAdvanceControl(Elaboratable):
    """Ready/valid control for the ID2 to IS pipeline transfer."""

    def __init__(self):
        self.redirect = Signal()
        self.stall_front = Signal()
        self.is_valid = Signal()
        self.stall_dep_id2 = Signal()

        self.clear_is = Signal()
        self.fill_is = Signal()
        self.consume_id2 = Signal()

    def elaborate(self, platform):
        m = Module()
        m.d.comb += [
            self.clear_is.eq(
                self.redirect |
                (self.stall_front & self.is_valid) |
                self.stall_dep_id2
            ),
            self.fill_is.eq(
                ~self.redirect &
                ~(self.stall_front & self.is_valid) &
                ~self.stall_dep_id2
            ),
            self.consume_id2.eq(
                self.stall_front & ~self.is_valid &
                ~self.redirect & ~self.stall_dep_id2
            ),
        ]
        return m
