from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick, Settle

from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core
from tests.test_isa_q_sign_injection import encode_flq, encode_fsq, OP_FP, JAL


def encode_minmax_q(rd, rs1, rs2, is_max=False):
    return ((0b0010111 << 25) | (rs2 << 20) | (rs1 << 15) |
            (int(is_max) << 12) | (rd << 7) | OP_FP)


def words128(value):
    return [(value >> shift) & 0xffffffff for shift in (0, 32, 64, 96)]


class QMinMaxBench(Elaboratable):
    def __init__(self, extensions):
        self.core = RV12Core(xlen=32, extensions=extensions)
        nop = 0x00000013
        program = []
        for reg in range(1, 9):
            program.append(encode_flq(reg, 0, 0x0f0 + reg * 0x10))
        program += [nop] * 12
        program += [
            encode_minmax_q(10, 1, 2, False),
            encode_minmax_q(11, 1, 2, True),
            encode_minmax_q(12, 3, 4, False),
            encode_minmax_q(13, 5, 6, True),
            encode_minmax_q(14, 7, 8, False),
            encode_minmax_q(15, 7, 8, True),
        ]
        program += [nop] * 12
        for index, reg in enumerate(range(10, 16)):
            program.append(encode_fsq(reg, 0, 0x200 + index * 0x10))
        program.append(JAL)

        negative_zero = 1 << 127
        positive_zero = 0
        signaling_nan = (0x7fff << 112) | 0x12345
        positive_one = 0x3fff << 112
        quiet_nan_a = (0x7fff << 112) | (1 << 111) | 0x111
        quiet_nan_b = (0x7fff << 112) | (1 << 111) | 0x222
        negative_two = (1 << 127) | (0x4000 << 112)
        positive_one_b = positive_one
        sources = [negative_zero, positive_zero, signaling_nan, positive_one,
                   quiet_nan_a, quiet_nan_b, negative_two, positive_one_b]
        data = [0] * 256
        for index, value in enumerate(sources):
            base = (0x100 + index * 0x10) // 4
            data[base:base + 4] = words128(value)

        canonical_nan = (0x7fff << 112) | (1 << 111)
        self.expected_values = [negative_zero, positive_zero, positive_one,
                                canonical_nan, negative_two, positive_one]
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
        ]
        return m


def run_config(extensions):
    dut = QMinMaxBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    writes = []
    diagnostics = {"trap": 0, "fflags": 0}

    def process():
        for _ in range(360):
            yield Settle()
            diagnostics["trap"] = (yield dut.core.trap)
            diagnostics["fflags"] = (yield dut.core.dbg_fflags)
            if (yield dut.core.dmem_valid) and (yield dut.core.dmem_we):
                address = yield dut.core.dmem_addr
                if 0x200 <= address < 0x260:
                    writes.append((address, (yield dut.core.dmem_wdata)))
            yield Tick()

    sim.add_process(process)
    sim.run()
    return dut, writes, diagnostics


def expected_writes(dut):
    result = []
    for index, value in enumerate(dut.expected_values):
        result.extend((0x200 + index * 0x10 + beat * 4, word)
                      for beat, word in enumerate(words128(value)))
    return result


def check_config(extensions):
    dut, writes, diagnostics = run_config(extensions)
    assert dut.core.enable_q
    assert diagnostics["trap"] == 0, diagnostics
    assert diagnostics["fflags"] == 0b10000, diagnostics
    assert writes == expected_writes(dut), diagnostics


def test_q_minmax_explicit_extension():
    check_config("RV32I+GC+Q")


def test_q_minmax_star_extension():
    check_config("RV32I+GC+*")
