from amaranth import C, Elaboratable, Module, Mux, Signal


class PendingScoreboardUpdate(Elaboratable):
    """Build scoreboard set/clear masks with same-cycle clear priority."""

    def __init__(self, set_ports=2, clear_ports=4):
        self.set_valid = [Signal(name=f"set_valid_{i}")
                          for i in range(set_ports)]
        self.set_rd = [Signal(5, name=f"set_rd_{i}")
                       for i in range(set_ports)]
        self.clear_valid = [Signal(name=f"clear_valid_{i}")
                            for i in range(clear_ports)]
        self.clear_rd = [Signal(5, name=f"clear_rd_{i}")
                         for i in range(clear_ports)]
        self.current_mask = Signal(32)
        self.set_mask = Signal(32)
        self.clear_mask = Signal(32)
        self.next_mask = Signal(32)

    @staticmethod
    def _combine(valids, registers):
        combined = C(0, 32)
        for valid, register in zip(valids, registers):
            combined = combined | Mux(valid, C(1, 32) << register, C(0, 32))
        return combined

    def elaborate(self, platform):
        m = Module()
        set_mask = self._combine(self.set_valid, self.set_rd)
        clear_mask = self._combine(self.clear_valid, self.clear_rd)
        m.d.comb += [
            self.set_mask.eq(set_mask),
            self.clear_mask.eq(clear_mask),
            self.next_mask.eq((self.current_mask | set_mask) & ~clear_mask),
        ]
        return m
