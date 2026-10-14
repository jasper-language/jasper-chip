from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick, Settle

from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core
from tests.test_isa_q_minmax import words128
from tests.test_isa_q_sign_injection import encode_flq, OP_FP, JAL
from tests.test_isa_q_from_int import encode_fsq


def encode_fcvt_q_fp(rd, rs1, source_format, rm):
    return ((0b0100011 << 25) | (source_format << 20) | (rs1 << 15) |
            (rm << 12) | (rd << 7) | OP_FP)


class QFromFPBench(Elaboratable):
    def __init__(self, extensions):
        self.core = RV12Core(xlen=32, extensions=extensions)
        nop = 0x00000013
        program = [encode_flq(reg, 0, 0x100 + reg * 0x10)
                   for reg in range(1, 6)]
        program += [nop] * 12
        program += [
            encode_fcvt_q_fp(10, 1, 0, 0b000), # boxed S +1.5
            encode_fcvt_q_fp(11, 2, 0, 0b001), # boxed S sNaN
            encode_fcvt_q_fp(12, 3, 0, 0b010), # unboxed S -> canonical NaN
            encode_fcvt_q_fp(13, 4, 1, 0b011), # boxed D negative min subnormal
            encode_fcvt_q_fp(14, 5, 1, 0b100), # boxed D +infinity
            encode_fcvt_q_fp(15, 1, 0, 0b111), # dynamic frm, exact
        ]
        program += [nop] * 12
        program += [encode_fsq(reg, 0, 0x200 + (reg - 10) * 0x10)
                    for reg in range(10, 16)]
        program += [nop] * 12
        program.append(encode_fcvt_q_fp(16, 1, 2, 0b000)) # reserved source
        program.append(JAL)

        boxed_s_one_half = ((1 << 96) - 1) << 32
        boxed_s_one_half |= (0x3f800000 | (1 << 22))
        boxed_s_snan = (((1 << 96) - 1) << 32) | 0x7f800001
        unboxed_s_one = 0x3f800000
        boxed_d_neg_min_sub = (((1 << 64) - 1) << 64) | (1 << 63) | 1
        boxed_d_pos_inf = (((1 << 64) - 1) << 64) | (0x7ff << 52)
        sources = [boxed_s_one_half, boxed_s_snan, unboxed_s_one,
                   boxed_d_neg_min_sub, boxed_d_pos_inf]
        data = [0] * 256
        for index, value in enumerate(sources, start=1):
            base = (0x100 + index * 0x10) // 4
            data[base:base + 4] = words128(value)

        q_one_half = (0x3fff << 112) | (1 << 111)
        q_nan = (0x7fff << 112) | (1 << 111)
        q_neg_d_min_sub = (1 << 127) | ((16383 - 1074) << 112)
        q_pos_inf = 0x7fff << 112
        self.expected = [q_one_half, q_nan, q_nan, q_neg_d_min_sub,
                         q_pos_inf, q_one_half]
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
    dut = QFromFPBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    writes = []
    diagnostics = {"trap_seen": 0, "fflags": 0}

    def process():
        for _ in range(400):
            yield Settle()
            diagnostics["trap_seen"] |= (yield dut.core.trap)
            diagnostics["fflags"] = (yield dut.core.dbg_fflags)
            if (yield dut.core.dmem_valid) and (yield dut.core.dmem_we):
                address = yield dut.core.dmem_addr
                if 0x200 <= address < 0x260:
                    writes.append((address, (yield dut.core.dmem_wdata)))
            yield Tick()

    sim.add_process(process)
    sim.run()
    expected_writes = []
    for index, value in enumerate(dut.expected):
        expected_writes.extend((0x200 + index * 0x10 + beat * 4, word)
                               for beat, word in enumerate(words128(value)))
    assert dut.core.enable_q and dut.core.enable_d
    assert diagnostics["trap_seen"] == 1, diagnostics
    assert diagnostics["fflags"] == 0b10000, diagnostics
    assert writes == expected_writes, diagnostics


def test_q_from_fp_explicit_extension():
    check_config("RV32I+GC+Q+D")


def test_q_from_fp_star_extension():
    check_config("RV32I+GC+*")
