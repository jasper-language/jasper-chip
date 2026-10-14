from amaranth import Elaboratable, Module
from amaranth.sim import Settle, Simulator, Tick

from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core
from tests.test_isa_q_from_int import encode_fsq
from tests.test_isa_q_minmax import words128
from tests.test_isa_q_sign_injection import JAL, OP_FP, encode_flq


Q_ONE = 0x3FFF << 112
Q_TWO = 0x4000 << 112
Q_THREE = (0x4000 << 112) | (1 << 111)
Q_FOUR = 0x4001 << 112
Q_TEN = (0x4002 << 112) | (1 << 110)


def encode_q_op(funct7, rd, rs1, rs2, rm=0):
    return ((funct7 << 25) | (rs2 << 20) | (rs1 << 15) |
            (rm << 12) | (rd << 7) | OP_FP)


def encode_q_fma(opcode, rd, rs1, rs2, rs3, rm=0):
    return ((rs3 << 27) | (0b11 << 25) | (rs2 << 20) | (rs1 << 15) |
            (rm << 12) | (rd << 7) | opcode)


class QArithmeticBench(Elaboratable):
    def __init__(self, extensions):
        self.core = RV12Core(xlen=32, extensions=extensions)
        nop = 0x00000013
        program = [encode_flq(reg, 0, 0x100 + reg * 0x10)
                   for reg in range(1, 5)]
        program += [nop] * 12
        program += [
            encode_q_op(0b0000011, 10, 1, 2, 0b111),  # FADD.Q dynamic RNE
            encode_q_op(0b0000111, 11, 10, 1),        # FSUB.Q RAW
            encode_q_op(0b0001011, 12, 11, 2),        # FMUL.Q RAW
            encode_q_op(0b0001111, 13, 12, 2),        # FDIV.Q RAW
            encode_q_op(0b0101111, 14, 12, 0),        # FSQRT.Q RAW
            encode_q_fma(0x43, 15, 2, 3, 4),          # FMADD.Q
            encode_q_fma(0x47, 16, 2, 3, 4),          # FMSUB.Q
            encode_q_fma(0x4B, 17, 2, 3, 4),          # FNMSUB.Q
            encode_q_fma(0x4F, 18, 2, 3, 4),          # FNMADD.Q
            encode_q_op(0b0100000, 20, 3, 3),         # FCVT.S.Q
        ]
        program += [nop] * 12
        result_regs = list(range(10, 19)) + [20]
        program += [encode_fsq(reg, 0, 0x200 + index * 0x10)
                    for index, reg in enumerate(result_regs)]
        program += [nop] * 12
        program += [encode_q_op(0b0000011, 21, 1, 2, 0b101), JAL]

        data = [0] * 256
        for reg, value in enumerate((Q_ONE, Q_TWO, Q_THREE, Q_FOUR), 1):
            base = (0x100 + reg * 0x10) // 4
            data[base:base + 4] = words128(value)
        boxed_s_three = (((1 << 96) - 1) << 32) | 0x40400000
        self.expected = [
            Q_THREE, Q_TWO, Q_FOUR, Q_TWO, Q_TWO,
            Q_TEN, Q_TWO, (1 << 127) | Q_TWO,
            (1 << 127) | Q_TEN, boxed_s_three,
        ]
        self.imem = SimpleIMem(words=1024, init=program)
        self.dmem = SimpleDMem(words=256, init=data)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = self.core
        m.submodules.imem = self.imem
        m.submodules.dmem = self.dmem
        m.d.comb += [
            self.imem.addr.eq(self.core.imem_addr),
            self.core.imem_rdata.eq(self.imem.rdata),
            self.dmem.req_valid.eq(self.core.dmem_valid),
            self.dmem.req_we.eq(self.core.dmem_we),
            self.dmem.req_addr.eq(self.core.dmem_addr),
            self.dmem.req_wdata.eq(self.core.dmem_wdata),
            self.core.dmem_rdata.eq(self.dmem.rsp_rdata),
            self.core.dmem_grant.eq(1),
            self.core.wb_enq_ready.eq(1),
        ]
        return m


def check_config(extensions):
    dut = QArithmeticBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    writes = []
    diagnostics = {"trap_seen": 0, "fflags": 0}

    def process():
        for _ in range(760):
            yield Settle()
            diagnostics["trap_seen"] |= (yield dut.core.trap)
            diagnostics["fflags"] = (yield dut.core.dbg_fflags)
            if (yield dut.core.dmem_valid) and (yield dut.core.dmem_we):
                address = yield dut.core.dmem_addr
                if 0x200 <= address < 0x2A0:
                    writes.append((address, (yield dut.core.dmem_wdata)))
            yield Tick()

    sim.add_process(process)
    sim.run()
    expected_writes = []
    for index, value in enumerate(dut.expected):
        expected_writes.extend((0x200 + index * 0x10 + beat * 4, word)
                               for beat, word in enumerate(words128(value)))
    assert dut.core.enable_q
    assert diagnostics == {"trap_seen": 1, "fflags": 0}, diagnostics
    assert writes == expected_writes, (writes, expected_writes)


def test_q_arithmetic_explicit_extension():
    check_config("RV32I+GC+Q")


def test_q_arithmetic_star_extension():
    check_config("RV32I+GC+*")
