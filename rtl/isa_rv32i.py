from amaranth import *

from .isa_module import ISAExtension
from .isa import OP_IMM, OP, LOAD, STORE, BRANCH, JAL, JALR, MISC_MEM, LUI, AUIPC, SYSTEM


class RV32I(ISAExtension):
    def __init__(self, xlen=32):
        super().__init__(xlen=xlen, name="rv32i")
        self._xlen = xlen

    def elaborate(self, platform):
        m = Module()
        XLEN = self._xlen

        rv32i_opcodes = Signal()
        m.d.comb += rv32i_opcodes.eq(
            (self.opcode == OP_IMM) | (self.opcode == OP) |
            (self.opcode == LOAD)   | (self.opcode == STORE) |
            (self.opcode == BRANCH) | (self.opcode == JAL) |
            (self.opcode == JALR)   | (self.opcode == MISC_MEM) |
            (self.opcode == LUI)    | (self.opcode == AUIPC) |
            (self.opcode == SYSTEM))

        m.d.comb += self.matched.eq(
            self.valid & rv32i_opcodes &
            ~((self.opcode == OP) & (self.funct7 == 0b0000001)) &
            ~((self.opcode == SYSTEM) & (self.funct3 != 0)) &
            ~((self.opcode == OP) & (self.funct7 == 0b0000101)) &
            ~((self.opcode == OP) & (self.funct7 == 0b0010000)) &
            ~((self.opcode == OP) & (self.funct7 == 0b0100100)) &
            ~((self.opcode == OP) & (self.funct7 == 0b0110000)) &
            ~((self.opcode == OP) & (self.funct7 == 0b0000111)) &
            ~((self.opcode == OP) & (self.funct7 == 0b0010101)) &
            ~((self.opcode == OP) & (self.funct7 == 0b0110101)))

        m.d.comb += [
            self.wb_en.eq(0),
            self.wb_data.eq(0),
            self.alu_out.eq(0),
            self.mem_addr.eq(0),
            self.mem_wdata.eq(self.ex1_b),
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
            self.is_load.eq(self.opcode == LOAD),
            self.is_store.eq(self.opcode == STORE),
            self.is_branch.eq(self.opcode == BRANCH),
            self.is_jal.eq(self.opcode == JAL),
            self.is_jalr.eq(self.opcode == JALR),
            self.is_fence.eq(self.opcode == MISC_MEM),
            self.is_gc.eq(0),
            self.gc_op.eq(0),
            self.gc_rd.eq(0),
            self.gc_rs1.eq(0),
            self.gc_rs2.eq(0),
            self.gc_is_reloc.eq(0),
        ]

        with m.Switch(self.opcode):
            with m.Case(OP_IMM):
                with m.If(self.funct3 == 0b000):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.ex1_a + self.imm),
                    ]
                with m.Elif(self.funct3 == 0b001):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.ex1_a << self.imm[0:5]),
                    ]
                with m.Elif(self.funct3 == 0b010):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.ex1_a.as_signed() < self.imm.as_signed()),
                    ]
                with m.Elif(self.funct3 == 0b011):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.ex1_a.as_unsigned() < self.imm.as_unsigned()),
                    ]
                with m.Elif(self.funct3 == 0b100):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.ex1_a ^ self.imm),
                    ]
                with m.Elif(self.funct3 == 0b101):
                    with m.If(self.funct7[5] == 0):
                        m.d.comb += [
                            self.wb_en.eq(1),
                            self.wb_data.eq(self.ex1_a >> self.imm[0:5]),
                        ]
                    with m.Else():
                        m.d.comb += [
                            self.wb_en.eq(1),
                            self.wb_data.eq(self.ex1_a.as_signed() >> self.imm[0:5]),
                        ]
                with m.Elif(self.funct3 == 0b110):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.ex1_a | self.imm),
                    ]
                with m.Elif(self.funct3 == 0b111):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.ex1_a & self.imm),
                    ]
            with m.Case(OP):
                with m.If((self.funct3 == 0b000) & (self.funct7 == 0b0000000)):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.ex1_a + self.ex1_b),
                    ]
                with m.Elif((self.funct3 == 0b000) & (self.funct7 == 0b0100000)):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.ex1_a - self.ex1_b),
                    ]
                with m.Elif((self.funct3 == 0b001) & (self.funct7 == 0b0000000)):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.ex1_a << self.ex1_b[0:5]),
                    ]
                with m.Elif((self.funct3 == 0b010) & (self.funct7 == 0b0000000)):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.ex1_a.as_signed() < self.ex1_b.as_signed()),
                    ]
                with m.Elif((self.funct3 == 0b011) & (self.funct7 == 0b0000000)):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.ex1_a.as_unsigned() < self.ex1_b.as_unsigned()),
                    ]
                with m.Elif((self.funct3 == 0b100) & (self.funct7 == 0b0000000)):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.ex1_a ^ self.ex1_b),
                    ]
                with m.Elif((self.funct3 == 0b101) & (self.funct7 == 0b0000000)):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.ex1_a >> self.ex1_b[0:5]),
                    ]
                with m.Elif((self.funct3 == 0b101) & (self.funct7 == 0b0100000)):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.ex1_a.as_signed() >> self.ex1_b[0:5]),
                    ]
                with m.Elif((self.funct3 == 0b110) & (self.funct7 == 0b0000000)):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.ex1_a | self.ex1_b),
                    ]
                with m.Elif((self.funct3 == 0b111) & (self.funct7 == 0b0000000)):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.ex1_a & self.ex1_b),
                    ]
                with m.Elif((XLEN == 64) & (self.funct3 == 0b000) & (self.funct7 == 0b0000000)):
                    pass
            with m.Case(LOAD):
                m.d.comb += [
                    self.mem_addr.eq(self.ex1_a + self.imm),
                ]
            with m.Case(STORE):
                m.d.comb += [
                    self.mem_addr.eq(self.ex1_a + self.imm),
                ]
            with m.Case(BRANCH):
                m.d.comb += [self.br_valid.eq(1)]
                br_eq = Signal()
                m.d.comb += br_eq.eq(self.ex1_a == self.ex1_b)
                br_lt_s = Signal()
                br_lt_u = Signal()
                m.d.comb += [
                    br_lt_s.eq(self.ex1_a.as_signed() < self.ex1_b.as_signed()),
                    br_lt_u.eq(self.ex1_a.as_unsigned() < self.ex1_b.as_unsigned()),
                ]
                with m.If(self.funct3 == 0b000):
                    m.d.comb += [
                        self.br_taken.eq(br_eq),
                        self.br_is_branch.eq(1),
                        self.br_pc.eq(self.pc),
                        self.br_target.eq(self.pc + self.imm),
                    ]
                with m.Elif(self.funct3 == 0b001):
                    m.d.comb += [
                        self.br_taken.eq(~br_eq),
                        self.br_is_branch.eq(1),
                        self.br_pc.eq(self.pc),
                        self.br_target.eq(self.pc + self.imm),
                    ]
                with m.Elif(self.funct3 == 0b100):
                    m.d.comb += [
                        self.br_taken.eq(br_lt_s),
                        self.br_is_branch.eq(1),
                        self.br_pc.eq(self.pc),
                        self.br_target.eq(self.pc + self.imm),
                    ]
                with m.Elif(self.funct3 == 0b101):
                    m.d.comb += [
                        self.br_taken.eq(~br_lt_s),
                        self.br_is_branch.eq(1),
                        self.br_pc.eq(self.pc),
                        self.br_target.eq(self.pc + self.imm),
                    ]
                with m.Elif(self.funct3 == 0b110):
                    m.d.comb += [
                        self.br_taken.eq(br_lt_u),
                        self.br_is_branch.eq(1),
                        self.br_pc.eq(self.pc),
                        self.br_target.eq(self.pc + self.imm),
                    ]
                with m.Elif(self.funct3 == 0b111):
                    m.d.comb += [
                        self.br_taken.eq(~br_lt_u),
                        self.br_is_branch.eq(1),
                        self.br_pc.eq(self.pc),
                        self.br_target.eq(self.pc + self.imm),
                    ]
                with m.If(self.br_taken):
                    m.d.comb += [
                        self.redirect.eq(1),
                        self.redirect_pc.eq(self.pc + self.imm),
                    ]
                with m.Elif(self.bp_mispredict):
                    m.d.comb += [
                        self.redirect.eq(1),
                        self.redirect_pc.eq(self.pc + 4),
                    ]
            with m.Case(JAL):
                m.d.comb += [
                    self.br_valid.eq(1),
                    self.br_taken.eq(1),
                    self.br_is_jal.eq(1),
                    self.br_pc.eq(self.pc),
                    self.br_target.eq(self.pc + self.imm),
                    self.redirect.eq(1),
                    self.redirect_pc.eq(self.pc + self.imm),
                    self.wb_en.eq(1),
                    self.wb_data.eq(self.pc + 4),
                ]
            with m.Case(JALR):
                with m.If(self.funct3 == 0b000):
                    jalr_target = Signal(XLEN)
                    m.d.comb += jalr_target.eq((self.ex1_a + self.imm) & ~1)
                    m.d.comb += [
                        self.br_valid.eq(1),
                        self.br_taken.eq(1),
                        self.br_is_jalr.eq(1),
                        self.br_pc.eq(self.pc),
                        self.br_target.eq(jalr_target),
                        self.redirect.eq(1),
                        self.redirect_pc.eq(jalr_target),
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.pc + 4),
                    ]
            with m.Case(LUI):
                m.d.comb += [
                    self.wb_en.eq(1),
                    self.wb_data.eq(self.imm),
                ]
            with m.Case(AUIPC):
                m.d.comb += [
                    self.wb_en.eq(1),
                    self.wb_data.eq(self.pc + self.imm),
                ]
            with m.Case(MISC_MEM):
                pass
            with m.Case(SYSTEM):
                with m.If(self.funct3 == 0b000):
                    m.d.comb += [self.trap.eq(1)]

        return m
