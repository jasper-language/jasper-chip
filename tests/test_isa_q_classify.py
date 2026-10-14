from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick, Settle

from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core
from tests.test_isa_q_minmax import words128
from tests.test_isa_q_sign_injection import encode_flq, OP_FP, JAL


STORE = 0b0100011


def encode_fclass_q(rd, rs1):
    return ((0b1110011 << 25) | (rs1 << 15) | (0b001 << 12) |
            (rd << 7) | OP_FP)


def encode_sw(rs2, rs1, imm):
    immediate = imm & 0xfff
    return (((immediate >> 5) << 25) | (rs2 << 20) | (rs1 << 15) |
            (0b010 << 12) | ((immediate & 0x1f) << 7) | STORE)


class QClassifyBench(Elaboratable):
    def __init__(self, extensions):
        self.core = RV12Core(xlen=32, extensions=extensions)
        nop = 0x00000013
        program = [encode_flq(reg, 0, 0x100 + reg * 0x10)
                   for reg in range(1, 11)]
        program += [nop] * 12
        program += [encode_fclass_q(9 + reg, reg) for reg in range(1, 11)]
        program += [nop] * 12
        program += [encode_sw(10 + index, 0, 0x240 + index * 4)
                    for index in range(10)]
        program.append(JAL)

        sign = 1 << 127
        inf = 0x7fff << 112
        one = 0x3fff << 112
        sources = [
            sign | inf,       # negative infinity
            sign | one,       # negative normal
            sign | 1,         # negative subnormal
            sign,             # negative zero
            0,                # positive zero
            1,                # positive subnormal
            one,              # positive normal
            inf,              # positive infinity
            inf | 1,          # signaling NaN
            inf | (1 << 111), # quiet NaN
        ]
        data = [0] * 256
        for index, value in enumerate(sources, start=1):
            base = (0x100 + index * 0x10) // 4
            data[base:base + 4] = words128(value)

        self.expected = [1 << index for index in range(10)]
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
    dut = QClassifyBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    writes = []
    diagnostics = {"trap": 0, "fflags": 0}

    def process():
        for _ in range(420):
            yield Settle()
            diagnostics["trap"] = (yield dut.core.trap)
            diagnostics["fflags"] = (yield dut.core.dbg_fflags)
            if (yield dut.core.dmem_valid) and (yield dut.core.dmem_we):
                address = yield dut.core.dmem_addr
                if 0x240 <= address < 0x268:
                    writes.append((address, (yield dut.core.dmem_wdata)))
            yield Tick()

    sim.add_process(process)
    sim.run()
    assert dut.core.enable_q
    assert diagnostics["trap"] == 0, diagnostics
    assert diagnostics["fflags"] == 0, diagnostics
    assert writes == [(0x240 + index * 4, value)
                      for index, value in enumerate(dut.expected)], diagnostics


def test_q_classify_explicit_extension():
    check_config("RV32I+GC+Q")


def test_q_classify_star_extension():
    check_config("RV32I+GC+*")
