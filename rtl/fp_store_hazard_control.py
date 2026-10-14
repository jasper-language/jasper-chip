from amaranth import Const, Elaboratable, Module, Signal


class FPStoreHazardControl(Elaboratable):
    """Detect an enabled FP load feeding an FP store source register."""

    def __init__(self, *, slots, enable_h=False, enable_f=False,
                 enable_d=False, enable_q=False, use_finx=False):
        self.slots = slots
        self.enable_h = enable_h and not use_finx
        self.enable_f = enable_f and not use_finx
        self.enable_d = enable_d and not use_finx
        self.enable_q = enable_q and not use_finx

        self.store_valid = Signal()
        self.store_funct3 = Signal(3)
        self.store_rs2 = Signal(5)
        self.load_valid = [Signal(name=f"load_valid_{i}") for i in range(slots)]
        self.load_funct3 = [Signal(3, name=f"load_funct3_{i}") for i in range(slots)]
        self.load_rd = [Signal(5, name=f"load_rd_{i}") for i in range(slots)]
        self.hazard = Signal()

    def _width_enabled(self, funct3):
        return (
            (Const(self.enable_h) & (funct3 == 0b001)) |
            (Const(self.enable_f) & (funct3 == 0b010)) |
            (Const(self.enable_d) & (funct3 == 0b011)) |
            (Const(self.enable_q) & (funct3 == 0b100))
        )

    def elaborate(self, platform):
        m = Module()
        pending = Const(0)
        for valid, funct3, rd in zip(
                self.load_valid, self.load_funct3, self.load_rd):
            pending = pending | (
                valid & self._width_enabled(funct3) & (rd == self.store_rs2))
        m.d.comb += self.hazard.eq(
            self.store_valid & self._width_enabled(self.store_funct3) & pending)
        return m
