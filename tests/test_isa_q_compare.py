from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick, Settle

from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core
from tests.test_isa_q_minmax import words128
from tests.test_isa_q_sign_injection import encode_flq, OP_FP, JAL


STORE = 0b0100011


def encode_compare_q(rd, rs1, rs2, funct3):
    return ((0b1010011 << 25) | (rs2 << 20) | (rs1 << 15) |
            (funct3 << 12) | (rd << 7) | OP_FP)


def encode_sw(rs2, rs1, imm):
    immediate = imm & 0xfff
    return (((immediate >> 5) << 25) | (rs2 << 20) | (rs1 << 15) |
            (0b010 << 12) | ((immediate & 0x1f) << 7) | STORE)


class QCompareBench(Elaboratable):
    def __init__(self, extensions):
        self.core = RV12Core(xlen=32, extensions=extensions)
        nop = 0x00000013
        program = [encode_flq(reg, 0, 0x0f0 + reg * 0x10)
                   for reg in range(1, 7)]
        program += [nop] * 12
        program += [
            encode_compare_q(10, 1, 2, 0b010),  # FEQ.Q -0,+0
            encode_compare_q(11, 3, 4, 0b001),  # FLT.Q -2,+1
            encode_compare_q(12, 4, 3, 0b000),  # FLE.Q +1,-2
            encode_compare_q(13, 5, 4, 0b010),  # FEQ.Q qNaN,+1
            encode_compare_q(14, 5, 4, 0b001),  # FLT.Q qNaN,+1
            encode_compare_q(15, 6, 4, 0b010),  # FEQ.Q sNaN,+1
        ]
        program += [nop] * 12
        program += [encode_sw(reg, 0, 0x200 + (reg - 10) * 4)
                    for reg in range(10, 16)]
        program.append(JAL)

        negative_zero = 1 << 127
        positive_zero = 0
        negative_two = (1 << 127) | (0x4000 << 112)
        positive_one = 0x3fff << 112
        quiet_nan = (0x7fff << 112) | (1 << 111) | 0x55
        signaling_nan = (0x7fff << 112) | 0x66
        sources = [negative_zero, positive_zero, negative_two, positive_one,
                   quiet_nan, signaling_nan]
        data = [0] * 256
        for index, value in enumerate(sources):
            base = (0x100 + index * 0x10) // 4
            data[base:base + 4] = words128(value)

        self.expected = [1, 1, 0, 0, 0, 0]
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


def run_config(extensions):
    dut = QCompareBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    writes = []
    diagnostics = {"trap": 0, "fflags": 0}

    def process():
        for _ in range(260):
            yield Settle()
            diagnostics["trap"] = (yield dut.core.trap)
            diagnostics["fflags"] = (yield dut.core.dbg_fflags)
            if (yield dut.core.dmem_valid) and (yield dut.core.dmem_we):
                address = yield dut.core.dmem_addr
                if 0x200 <= address < 0x218:
                    writes.append((address, (yield dut.core.dmem_wdata)))
            yield Tick()

    sim.add_process(process)
    sim.run()
    return dut, writes, diagnostics


def check_config(extensions):
    dut, writes, diagnostics = run_config(extensions)
    assert dut.core.enable_q
    assert diagnostics["trap"] == 0, diagnostics
    assert diagnostics["fflags"] == 0b10000, diagnostics
    assert writes == [(0x200 + index * 4, value)
                      for index, value in enumerate(dut.expected)], diagnostics


def test_q_compare_explicit_extension():
    check_config("RV32I+GC+Q")


def test_q_compare_star_extension():
    check_config("RV32I+GC+*")
