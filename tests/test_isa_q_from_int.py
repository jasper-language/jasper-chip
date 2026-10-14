from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick, Settle

from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core
from tests.test_isa_q_minmax import words128
from tests.test_isa_q_sign_injection import OP_FP, JAL


LOAD = 0b0000011
STORE_FP = 0b0100111


def encode_lw(rd, rs1, imm):
    return (((imm & 0xfff) << 20) | (rs1 << 15) | (0b010 << 12) |
            (rd << 7) | LOAD)


def encode_fcvt_q_w(rd, rs1, unsigned, rm):
    return ((0b1101011 << 25) | (unsigned << 20) | (rs1 << 15) |
            (rm << 12) | (rd << 7) | OP_FP)


def encode_fsq(rs2, rs1, imm):
    immediate = imm & 0xfff
    return (((immediate >> 5) << 25) | (rs2 << 20) | (rs1 << 15) |
            (0b100 << 12) | ((immediate & 0x1f) << 7) | STORE_FP)


class QFromIntBench(Elaboratable):
    def __init__(self, extensions):
        self.core = RV12Core(xlen=32, extensions=extensions)
        nop = 0x00000013
        program = [encode_lw(reg, 0, 0x100 + (reg - 1) * 4)
                   for reg in range(1, 5)]
        program += [nop] * 12
        program += [
            encode_fcvt_q_w(1, 1, 0, 0b000),  # -1, RNE
            encode_fcvt_q_w(2, 2, 0, 0b001),  # INT32_MIN, RTZ
            encode_fcvt_q_w(3, 3, 1, 0b010),  # UINT32_MAX, RDN
            encode_fcvt_q_w(4, 4, 0, 0b011),  # +1, RUP
            encode_fcvt_q_w(5, 3, 1, 0b100),  # UINT32_MAX, RMM
            encode_fcvt_q_w(6, 3, 1, 0b111),  # UINT32_MAX, dynamic RNE
            encode_fcvt_q_w(7, 0, 0, 0b000),  # zero
        ]
        program += [nop] * 12
        program += [encode_fsq(reg, 0, 0x200 + (reg - 1) * 0x10)
                    for reg in range(1, 8)]
        program += [nop] * 12
        program.append(encode_fcvt_q_w(8, 4, 0, 0b101))  # reserved rm
        program.append(JAL)

        data = [0] * 256
        data[0x100 // 4:0x110 // 4] = [0xffffffff, 0x80000000,
                                       0xffffffff, 1]
        sign = 1 << 127
        q_one = 0x3fff << 112
        q_int_min = sign | ((0x3fff + 31) << 112)
        q_uint_max = ((0x3fff + 31) << 112) | (0x7fffffff << 81)
        self.expected = [sign | q_one, q_int_min, q_uint_max, q_one,
                         q_uint_max, q_uint_max, 0]
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
    dut = QFromIntBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    writes = []
    diagnostics = {"trap_seen": 0, "fflags": 0}

    def process():
        for _ in range(420):
            yield Settle()
            diagnostics["trap_seen"] |= (yield dut.core.trap)
            diagnostics["fflags"] = (yield dut.core.dbg_fflags)
            if (yield dut.core.dmem_valid) and (yield dut.core.dmem_we):
                address = yield dut.core.dmem_addr
                if 0x200 <= address < 0x270:
                    writes.append((address, (yield dut.core.dmem_wdata)))
            yield Tick()

    sim.add_process(process)
    sim.run()
    expected_writes = []
    for index, value in enumerate(dut.expected):
        expected_writes.extend((0x200 + index * 0x10 + beat * 4, word)
                               for beat, word in enumerate(words128(value)))
    assert dut.core.enable_q
    assert diagnostics["trap_seen"] == 1, diagnostics
    assert diagnostics["fflags"] == 0, diagnostics
    assert writes == expected_writes, diagnostics


def test_q_from_int_explicit_extension():
    check_config("RV32I+GC+Q")


def test_q_from_int_star_extension():
    check_config("RV32I+GC+*")
