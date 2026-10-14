from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick, Settle

from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core
from tests.test_isa_q_minmax import words128
from tests.test_isa_q_sign_injection import encode_flq, OP_FP, JAL


STORE = 0b0100011


def encode_fcvt_w_q(rd, rs1, unsigned, rm):
    return ((0b1100011 << 25) | (unsigned << 20) | (rs1 << 15) |
            (rm << 12) | (rd << 7) | OP_FP)


def encode_sw(rs2, rs1, imm):
    immediate = imm & 0xfff
    return (((immediate >> 5) << 25) | (rs2 << 20) | (rs1 << 15) |
            (0b010 << 12) | ((immediate & 0x1f) << 7) | STORE)


class QToIntBench(Elaboratable):
    def __init__(self, extensions):
        self.core = RV12Core(xlen=32, extensions=extensions)
        nop = 0x00000013
        program = [encode_flq(reg, 0, 0x100 + reg * 0x10)
                   for reg in range(1, 9)]
        program += [nop] * 12
        program += [
            encode_fcvt_w_q(10, 1, 0, 0b000), # +1.5 RNE -> 2
            encode_fcvt_w_q(11, 1, 0, 0b001), # +1.5 RTZ -> 1
            encode_fcvt_w_q(12, 2, 0, 0b010), # -1.5 RDN -> -2
            encode_fcvt_w_q(13, 2, 0, 0b011), # -1.5 RUP -> -1
            encode_fcvt_w_q(14, 3, 0, 0b100), # +0.5 RMM -> 1
            encode_fcvt_w_q(15, 4, 0, 0b111), # -0.5 dynamic RNE -> 0
            encode_fcvt_w_q(16, 5, 0, 0b000), # +2^31 signed overflow
            encode_fcvt_w_q(17, 6, 0, 0b000), # qNaN signed saturation
            encode_fcvt_w_q(18, 7, 1, 0b001), # -0.25 unsigned RTZ -> 0
            encode_fcvt_w_q(19, 7, 1, 0b010), # -0.25 unsigned RDN invalid
            encode_fcvt_w_q(20, 8, 1, 0b000), # UINT32_MAX exact
        ]
        program += [nop] * 12
        program += [encode_sw(reg, 0, 0x240 + (reg - 10) * 4)
                    for reg in range(10, 21)]
        program += [nop] * 12
        program.append(encode_fcvt_w_q(21, 1, 2, 0b000)) # reserved rs2
        program.append(JAL)

        sign = 1 << 127
        q_one_half = (0x3fff << 112) | (1 << 111)
        q_half = (0x3ffe << 112)
        q_quarter = (0x3ffd << 112)
        q_two31 = (0x3fff + 31) << 112
        q_nan = (0x7fff << 112) | (1 << 111)
        q_uint_max = ((0x3fff + 31) << 112) | (0x7fffffff << 81)
        sources = [q_one_half, sign | q_one_half, q_half, sign | q_half,
                   q_two31, q_nan, sign | q_quarter, q_uint_max]
        data = [0] * 256
        for index, value in enumerate(sources, start=1):
            base = (0x100 + index * 0x10) // 4
            data[base:base + 4] = words128(value)

        self.expected = [2, 1, 0xfffffffe, 0xffffffff, 1, 0,
                         0x7fffffff, 0x7fffffff, 0, 0, 0xffffffff]
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
    dut = QToIntBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    writes = []
    diagnostics = {"trap_seen": 0, "fflags": 0}

    def process():
        for _ in range(440):
            yield Settle()
            diagnostics["trap_seen"] |= (yield dut.core.trap)
            diagnostics["fflags"] = (yield dut.core.dbg_fflags)
            if (yield dut.core.dmem_valid) and (yield dut.core.dmem_we):
                address = yield dut.core.dmem_addr
                if 0x240 <= address < 0x26c:
                    writes.append((address, (yield dut.core.dmem_wdata)))
            yield Tick()

    sim.add_process(process)
    sim.run()
    assert dut.core.enable_q
    assert diagnostics["trap_seen"] == 1, diagnostics
    assert diagnostics["fflags"] == 0b10001, diagnostics
    assert writes == [(0x240 + index * 4, value)
                      for index, value in enumerate(dut.expected)], diagnostics


def test_q_to_int_explicit_extension():
    check_config("RV32I+GC+Q")


def test_q_to_int_star_extension():
    check_config("RV32I+GC+*")
