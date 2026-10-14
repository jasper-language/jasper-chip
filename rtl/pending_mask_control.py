from amaranth import C, Elaboratable, Module, Mux, Signal


class PendingMaskControl(Elaboratable):
    """Apply same-cycle completion clears to the integer pending mask."""

    def __init__(self, clear_ports=3):
        self.clear_ports = clear_ports
        self.pending_mask = Signal(32)
        self.clear_valid = [Signal(name=f"clear_valid_{i}")
                            for i in range(clear_ports)]
        self.clear_rd = [Signal(5, name=f"clear_rd_{i}")
                         for i in range(clear_ports)]
        self.clear_mask = Signal(32)
        self.visible_mask = Signal(32)

    def elaborate(self, platform):
        m = Module()
        clear_terms = [
            Mux(valid, C(1, 32) << rd, C(0, 32))
            for valid, rd in zip(self.clear_valid, self.clear_rd)
        ]
        combined = C(0, 32)
        for term in clear_terms:
            combined = combined | term
        m.d.comb += [
            self.clear_mask.eq(combined),
            self.visible_mask.eq(self.pending_mask & ~combined),
        ]
        return m
