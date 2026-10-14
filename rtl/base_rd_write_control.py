from amaranth import Elaboratable, Module, Signal

from .isa import AMO, AUIPC, JALR, LUI, OP, OP_32, OP_IMM, OP_IMM_32


class BaseRDWriteControl(Elaboratable):
    """Base integer opcode contribution to architectural rd writeback."""

    def __init__(self):
        self.opcode = Signal(7)
        self.integer_load = Signal()
        self.is_jal = Signal()
        self.enable_a = Signal()
        self.writes_rd = Signal()

    def elaborate(self, platform):
        m = Module()
        m.d.comb += self.writes_rd.eq(
            (self.opcode == OP_IMM) | (self.opcode == OP_IMM_32) |
            (self.opcode == OP) | (self.opcode == OP_32) |
            (self.opcode == LUI) | (self.opcode == AUIPC) |
            (self.opcode == JALR) | self.integer_load | self.is_jal |
            (self.enable_a & (self.opcode == AMO))
        )
        return m
