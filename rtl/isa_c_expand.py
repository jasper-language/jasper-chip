from amaranth import *
from amaranth.hdl import *

from .isa import OP_IMM, OP, LOAD, STORE, LOAD_FP, STORE_FP, BRANCH, JAL, JALR, LUI, SYSTEM


class CExpander(Elaboratable):
    def __init__(self, xlen=32, enable_zcmop=False, enable_zcmt=False, enable_zcmp=False):
        self.xlen = xlen
        self.enable_zcmop = bool(enable_zcmop)
        self.enable_zcmt = bool(enable_zcmt)
        self.enable_zcmp = bool(enable_zcmp)
        self.valid = Signal()
        self.insn16 = Signal(16)
        self.insn32 = Signal(32)
        self.is_compressed = Signal()
        self.illegal = Signal()

    def elaborate(self, platform):
        m = Module()
        m.domains += ClockDomain('sync')

        i16 = self.insn16
        op = i16[0:2]
        funct3 = i16[13:16]

        cOP   = C(OP, 7)
        cOP_IMM = C(OP_IMM, 7)
        cLOAD = C(LOAD, 7)
        cSTORE = C(STORE, 7)
        cLOAD_FP = C(LOAD_FP, 7)
        cSTORE_FP = C(STORE_FP, 7)
        cBRANCH = C(BRANCH, 7)
        cJAL  = C(JAL, 7)
        cJALR = C(JALR, 7)
        cLUI  = C(LUI, 7)
        cSYSTEM = C(SYSTEM, 7)

        rd0  = i16[7:12]
        rs1  = i16[7:10]
        rs2  = i16[2:7]
        rd8  = Signal(5)
        rs18 = Signal(5)
        rs28 = Signal(5)

        m.d.comb += self.is_compressed.eq(op != 0b11)
        m.d.comb += [
            self.insn32.eq(0),
            self.illegal.eq(0),
            rd8.eq(C(8, 5) + i16[2:5]),
            rs18.eq(C(8, 5) + i16[7:10]),
            rs28.eq(C(8, 5) + i16[2:5]),
        ]

        with m.If(~self.valid | (op == 0b11)):
            m.d.comb += self.insn32.eq(Cat(i16, C(0, 16)))
        with m.Elif(op == 0b00):
            with m.Switch(funct3):
                with m.Case(0b000):
                    nzuimm_12 = Signal(12)
                    m.d.comb += nzuimm_12.eq(Cat(C(0, 2), i16[5:6], i16[6:7], i16[11:13], i16[7:11]))
                    m.d.comb += self.insn32.eq(Cat(cOP_IMM, rd8, C(0, 3), C(2, 5), nzuimm_12))
                    with m.If(nzuimm_12 == 0):
                        m.d.comb += self.illegal.eq(1)
                with m.Case(0b001):
                    fld_imm = Cat(C(0, 3), i16[10:13], i16[5:7], C(0, 4))
                    m.d.comb += self.insn32.eq(Cat(cLOAD_FP, rd8, C(0b011, 3), rs18, fld_imm))
                with m.Case(0b010):
                    lw_imm = Signal(12)
                    m.d.comb += lw_imm.eq(Cat(C(0, 2), i16[10:11], i16[11:12], i16[5:6], i16[12:13], i16[6:7], C(0, 5)))
                    m.d.comb += self.insn32.eq(Cat(cLOAD, rd8, C(2, 3), rs18, lw_imm))
                with m.Case(0b100):
                    with m.Switch(i16[10:12]):
                        with m.Case(0b00):
                            lb_imm = Cat(i16[6], i16[5], C(0, 10))
                            m.d.comb += self.insn32.eq(Cat(cLOAD, rd8, C(0b100, 3), rs18, lb_imm))
                        with m.Case(0b01):
                            lh_imm = Cat(C(0, 1), i16[5], C(0, 10))
                            m.d.comb += self.insn32.eq(Cat(cLOAD, rd8, Mux(i16[6], C(0b001, 3), C(0b101, 3)), rs18, lh_imm))
                        with m.Case(0b10):
                            sb_imm = Cat(i16[6], i16[5], C(0, 10))
                            m.d.comb += self.insn32.eq(Cat(cSTORE, sb_imm[:5], C(0b000, 3), rs18, rs28, sb_imm[5:]))
                        with m.Case(0b11):
                            sh_imm = Cat(C(0, 1), i16[5], C(0, 10))
                            m.d.comb += self.insn32.eq(Cat(cSTORE, sh_imm[:5], C(0b001, 3), rs18, rs28, sh_imm[5:]))
                with m.Case(0b011):
                    with m.If(self.xlen == 32):
                        flw_imm = Cat(C(0, 2), i16[6], i16[10:13], i16[5], C(0, 5))
                        m.d.comb += self.insn32.eq(Cat(cLOAD_FP, rd8, C(0b010, 3), rs18, flw_imm))
                    with m.Else():
                        m.d.comb += self.illegal.eq(1)
                with m.Case(0b101):
                    fsd_imm = Cat(C(0, 3), i16[10:13], i16[5:7], C(0, 4))
                    m.d.comb += self.insn32.eq(Cat(cSTORE_FP, fsd_imm[:5], C(0b011, 3), rs18, rs28, fsd_imm[5:]))
                with m.Case(0b110):
                    sw_imm = Signal(12)
                    m.d.comb += sw_imm.eq(Cat(C(0, 2), i16[10:11], i16[11:12], i16[5:6], i16[12:13], i16[6:7], C(0, 5)))
                    m.d.comb += self.insn32.eq(Cat(cSTORE, sw_imm[0:5], C(2, 3), rs18, rs28, sw_imm[5:12]))
                with m.Case(0b111):
                    with m.If(self.xlen == 32):
                        fsw_imm = Cat(C(0, 2), i16[6], i16[10:13], i16[5], C(0, 5))
                        m.d.comb += self.insn32.eq(Cat(cSTORE_FP, fsw_imm[:5], C(0b010, 3), rs18, rs28, fsw_imm[5:]))
                    with m.Else():
                        m.d.comb += self.illegal.eq(1)
                with m.Default():
                    m.d.comb += self.illegal.eq(1)
        with m.Elif(op == 0b01):
            with m.Switch(funct3):
                with m.Case(0b000):
                    ci_imm = Signal(12)
                    m.d.comb += ci_imm.eq(Cat(i16[2:7], i16[12], Cat(*[i16[12]] * 6)))
                    m.d.comb += self.insn32.eq(Cat(cOP_IMM, rd0, C(0, 3), rd0, ci_imm))
                with m.Case(0b001):
                    with m.If(self.xlen == 32):
                        cj_off = Signal(21)
                        m.d.comb += cj_off.eq(Cat(C(0, 1), i16[3:6], i16[11:12], i16[2:3], i16[7:8], i16[6:7], i16[9:11], i16[8:9], i16[12:13], Cat(*([i16[12]] * 9))))
                        m.d.comb += self.insn32.eq(Cat(cJAL, C(1, 5), cj_off[12:20], cj_off[11:12], cj_off[1:11], cj_off[20:21]))
                    with m.Else():
                        ciw_imm = Signal(12)
                        m.d.comb += ciw_imm.eq(Cat(i16[2:7], i16[12], Cat(*[i16[12]] * 6)))
                        m.d.comb += self.insn32.eq(Cat(C(27, 7), rd0, C(0, 3), rd0, ciw_imm))
                with m.Case(0b010):
                    li_imm = Signal(12)
                    m.d.comb += li_imm.eq(Cat(i16[2:7], i16[12], Cat(*[i16[12]] * 6)))
                    m.d.comb += self.insn32.eq(Cat(cOP_IMM, rd0, C(0, 3), C(0, 5), li_imm))
                with m.Case(0b011):
                    # Zcmop occupies the reserved C.LUI rd, 0 encodings for odd rd <= 15.
                    is_zcmop = self.enable_zcmop & ~i16[12] & (i16[2:7] == 0) & \
                        i16[7] & ~i16[11]
                    with m.If(is_zcmop):
                        m.d.comb += self.insn32.eq(0x00000013)  # Expand to NOP.
                    with m.Else():
                        with m.If(rd0 == 0b00010):
                            csp_imm = Signal(12)
                            m.d.comb += csp_imm.eq(Cat(C(0, 4), i16[6:7], i16[2:3], i16[5:6], i16[3:5], i16[12:13], Cat(*([i16[12]] * 2))))
                            m.d.comb += self.insn32.eq(Cat(cOP_IMM, C(2, 5), C(0, 3), C(2, 5), csp_imm))
                            with m.If(csp_imm == 0):
                                m.d.comb += self.illegal.eq(1)
                        with m.Else():
                            lui_imm = Signal(12)
                            m.d.comb += lui_imm.eq(Cat(i16[2:7], i16[12], Cat(*[i16[12]] * 6)))
                            m.d.comb += self.insn32.eq(Cat(cLUI, rd0, lui_imm, Cat(*[i16[12]] * 8)))
                            with m.If((lui_imm == 0) | (rd0 == 0)):
                                m.d.comb += self.illegal.eq(1)
                with m.Case(0b100):
                    funct2 = i16[10:12]
                    with m.Switch(funct2):
                        with m.Case(0b00):
                            m.d.comb += self.insn32.eq(Cat(cOP_IMM, rs18, C(5, 3), rs18, i16[2:7], C(0, 7)))
                        with m.Case(0b01):
                            m.d.comb += self.insn32.eq(Cat(cOP_IMM, rs18, C(5, 3), rs18, i16[2:7], C(0, 7)))
                            m.d.comb += self.insn32[30].eq(1)
                        with m.Case(0b10):
                            m.d.comb += self.insn32.eq(Cat(cOP_IMM, rs18, C(7, 3), rs18, Cat(i16[2:7], i16[12], Cat(*[i16[12]] * 6))))
                        with m.Case(0b11):
                            funct2 = i16[5:7]
                            with m.Switch(funct2):
                                with m.Case(0b00):
                                    with m.If(self.xlen == 64):
                                        m.d.comb += self.insn32.eq(Cat(cOP, rs18, C(0, 3), rs18, rs28, C(32, 7)))
                                    with m.Else():
                                        m.d.comb += self.insn32.eq(Cat(cOP, rs18, C(0, 3), rs18, rs28, C(0, 7)))
                                        m.d.comb += self.insn32[30].eq(1)
                                with m.Case(0b01):
                                    m.d.comb += self.insn32.eq(Cat(cOP, rs18, C(4, 3), rs18, rs28, C(0, 7)))
                                with m.Case(0b10):
                                    with m.If(i16[12]):
                                        m.d.comb += self.insn32.eq(Cat(cOP, rs18, C(0, 3), rs18, rs28, C(0b0000001, 7)))
                                    with m.Else():
                                        m.d.comb += self.insn32.eq(Cat(cOP, rs18, C(6, 3), rs18, rs28, C(0, 7)))
                                with m.Case(0b11):
                                    with m.If(i16[12]):
                                        with m.Switch(i16[5:7]):
                                            with m.Case(0b10):
                                                m.d.comb += self.insn32.eq(Cat(cOP, rs18, C(0, 3), rs18, rs28, C(0b0000001, 7)))
                                            with m.Case(0b11):
                                                with m.Switch(i16[2:5]):
                                                    with m.Case(0b000):
                                                        m.d.comb += self.insn32.eq(Cat(cOP_IMM, rs18, C(0b111, 3), rs18, C(0x0FF, 12)))
                                                    with m.Case(0b001):
                                                        m.d.comb += self.insn32.eq(Cat(cOP_IMM, rs18, C(0b001, 3), rs18, C(0x604, 12)))
                                                    with m.Case(0b010):
                                                        m.d.comb += self.insn32.eq(Cat(cOP, rs18, C(0b100, 3), rs18, C(0, 5), C(0b0000100, 7)))
                                                    with m.Case(0b011):
                                                        m.d.comb += self.insn32.eq(Cat(cOP_IMM, rs18, C(0b001, 3), rs18, C(0x605, 12)))
                                                    with m.Case(0b101):
                                                        m.d.comb += self.insn32.eq(Cat(cOP_IMM, rs18, C(0b100, 3), rs18, C(0xFFF, 12)))
                                                    with m.Default():
                                                        m.d.comb += self.illegal.eq(1)
                                            with m.Default():
                                                m.d.comb += self.illegal.eq(1)
                                    with m.Else():
                                        m.d.comb += self.insn32.eq(Cat(cOP, rs18, C(7, 3), rs18, rs28, C(0, 7)))
                with m.Case(0b101):
                    cj_off = Signal(21)
                    m.d.comb += cj_off.eq(Cat(C(0, 1), i16[3:6], i16[11:12], i16[2:3], i16[7:8], i16[6:7], i16[9:11], i16[8:9], i16[12:13], Cat(*([i16[12]] * 9))))
                    m.d.comb += self.insn32.eq(Cat(cJAL, C(0, 5), cj_off[12:20], cj_off[11:12], cj_off[1:11], cj_off[20:21]))
                with m.Case(0b110):
                    cb_off = Signal(13)
                    m.d.comb += cb_off.eq(Cat(C(0, 1), i16[3:5], i16[10:12], i16[2:3], i16[5:7], i16[12:13], Cat(*([i16[12]] * 4))))
                    m.d.comb += self.insn32.eq(Cat(cBRANCH, cb_off[11:12], cb_off[1:5], C(0, 3), rs18, C(0, 5), cb_off[5:11], cb_off[12:13]))
                with m.Case(0b111):
                    cb_off = Signal(13)
                    m.d.comb += cb_off.eq(Cat(C(0, 1), i16[3:5], i16[10:12], i16[2:3], i16[5:7], i16[12:13], Cat(*([i16[12]] * 4))))
                    m.d.comb += self.insn32.eq(Cat(cBRANCH, cb_off[11:12], cb_off[1:5], C(1, 3), rs18, C(0, 5), cb_off[5:11], cb_off[12:13]))
        with m.Else():
            with m.Switch(funct3):
                with m.Case(0b000):
                    m.d.comb += self.insn32.eq(Cat(cOP_IMM, rd0, C(1, 3), rd0, i16[2:7], C(0, 7)))
                    with m.If(i16[12]):
                        m.d.comb += self.illegal.eq(1)
                with m.Case(0b001):
                    fldsp_imm = Cat(C(0, 3), i16[5:7], i16[12], i16[2:5], C(0, 3))
                    m.d.comb += self.insn32.eq(Cat(cLOAD_FP, rd0, C(0b011, 3), C(2, 5), fldsp_imm))
                with m.Case(0b010):
                    lwsp_imm = Signal(12)
                    m.d.comb += lwsp_imm.eq(Cat(C(0, 2), i16[2:3], i16[5:6], i16[6:7], i16[12:13], i16[4:5], i16[3:4], C(0, 4)))
                    m.d.comb += self.insn32.eq(Cat(cLOAD, rd0, C(2, 3), C(2, 5), lwsp_imm))
                with m.Case(0b011):
                    with m.If(self.xlen == 32):
                        flwsp_imm = Cat(C(0, 2), i16[4:7], i16[12], i16[2:4], C(0, 4))
                        m.d.comb += self.insn32.eq(Cat(cLOAD_FP, rd0, C(0b010, 3), C(2, 5), flwsp_imm))
                    with m.Else():
                        m.d.comb += self.illegal.eq(1)
                with m.Case(0b100):
                    with m.If(i16[12] == 0):
                        with m.If(i16[2:7] == 0):
                            with m.If(rd0 == 0):
                                m.d.comb += self.illegal.eq(1)
                            with m.Else():
                                m.d.comb += self.insn32.eq(Cat(cJALR, C(0, 5), C(0, 3), rd0, C(0, 20)))
                        with m.Else():
                            m.d.comb += self.insn32.eq(Cat(cOP, rd0, C(0, 3), C(0, 5), rs2, C(0, 7)))
                    with m.Else():
                        with m.If(i16[2:7] == 0):
                            with m.If(rd0 == 0):
                                m.d.comb += self.insn32.eq(Cat(cSYSTEM, C(0, 5), C(0, 3), C(0, 5), C(0, 12)))
                                m.d.comb += self.insn32[20].eq(1)
                            with m.Else():
                                m.d.comb += self.insn32.eq(Cat(cJALR, C(1, 5), C(0, 3), rd0, C(0, 20)))
                        with m.Else():
                            m.d.comb += self.insn32.eq(Cat(cOP, rd0, C(0, 3), rd0, rs2, C(0, 7)))
                with m.Case(0b110):
                    swsp_imm = Signal(12)
                    m.d.comb += swsp_imm.eq(Cat(C(0, 2), i16[9:13], i16[7:9], C(0, 4)))
                    m.d.comb += self.insn32.eq(Cat(cSTORE, swsp_imm[0:5], C(2, 3), C(2, 5), i16[2:7], swsp_imm[5:12]))
                with m.Case(0b101):
                    # Zcmt CMJT format: funct6=101000, index=insn[9:2].
                    # A reserved JALR funct3 carries the table operation through
                    # the ordinary pipeline without introducing register sources.
                    with m.If(self.enable_zcmp & (i16[11:13] == 0b11) & ~i16[8]):
                        stack_rlist = i16[4:8]
                        stack_imm = Cat(stack_rlist, i16[2:4], C(0, 6))
                        stack_kind = Cat(i16[9:11], C(0, 3))
                        m.d.comb += self.insn32.eq(Cat(
                            cJALR, stack_kind, C(0b101, 3), C(2, 5), stack_imm
                        ))
                        with m.If(stack_rlist < 4):
                            m.d.comb += [
                                self.insn32.eq(0x00000013),
                                self.illegal.eq(1),
                            ]
                    with m.Elif(self.enable_zcmp & (i16[10:13] == 0b011) &
                              ((i16[5:7] == 0b01) | (i16[5:7] == 0b11))):
                        sregs = Array(C(reg, 5) for reg in (8, 9, 18, 19, 20, 21, 22, 23))
                        zcmp_r1 = sregs[i16[7:10]]
                        zcmp_r2 = sregs[i16[2:5]]
                        zcmp_to_a = i16[5:7] == 0b11
                        zcmp_rd1 = Mux(zcmp_to_a, C(10, 5), zcmp_r1)
                        zcmp_rs1 = Mux(zcmp_to_a, zcmp_r1, C(10, 5))
                        zcmp_rs2 = Mux(zcmp_to_a, zcmp_r2, C(11, 5))
                        zcmp_rd2 = Mux(zcmp_to_a, C(11, 5), zcmp_r2)
                        zcmp_imm = Cat(zcmp_rs2, zcmp_rd2, zcmp_to_a, C(0, 1))
                        m.d.comb += self.insn32.eq(Cat(
                            cJALR, zcmp_rd1, C(0b110, 3), zcmp_rs1, zcmp_imm
                        ))
                        with m.If(~zcmp_to_a & (i16[7:10] == i16[2:5])):
                            m.d.comb += [
                                self.insn32.eq(0x00000013),
                                self.illegal.eq(1),
                            ]
                    with m.Elif(self.enable_zcmt & (i16[10:13] == 0b000)):
                        cmjt_rd = Mux(i16[2:10] < 32, C(0, 5), C(1, 5))
                        cmjt_imm = Cat(i16[2:10], C(0, 4))
                        m.d.comb += self.insn32.eq(Cat(
                            cJALR, cmjt_rd, C(0b111, 3), C(0, 5), cmjt_imm
                        ))
                    with m.Else():
                        fsdsp_imm = Cat(C(0, 3), i16[10:13], i16[7:10], C(0, 3))
                        m.d.comb += self.insn32.eq(Cat(cSTORE_FP, fsdsp_imm[:5], C(0b011, 3), C(2, 5), i16[2:7], fsdsp_imm[5:]))
                with m.Case(0b111):
                    with m.If(self.xlen == 32):
                        fswsp_imm = Cat(C(0, 2), i16[9:13], i16[7:9], C(0, 4))
                        m.d.comb += self.insn32.eq(Cat(cSTORE_FP, fswsp_imm[:5], C(0b010, 3), C(2, 5), i16[2:7], fswsp_imm[5:]))
                    with m.Else():
                        m.d.comb += self.illegal.eq(1)
                with m.Default():
                    m.d.comb += self.illegal.eq(1)

        return m
