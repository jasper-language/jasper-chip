from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick, Settle

from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core
from tests.test_isa_q_minmax import words128
from tests.test_isa_q_sign_injection import encode_flq, OP_FP, JAL
from tests.test_isa_q_from_int import encode_fsq


def encode_fcvt_d_q(rd, rs1, rm):
    return ((0b0100001 << 25) | (3 << 20) | (rs1 << 15) |
            (rm << 12) | (rd << 7) | OP_FP)


class QToDBench(Elaboratable):
    def __init__(self, extensions):
        self.core = RV12Core(xlen=32, extensions=extensions)
        nop = 0x00000013
        program = [encode_flq(reg, 0, 0x100 + reg * 0x10)
                   for reg in range(1, 7)]
        program += [nop] * 12
        program += [
            encode_fcvt_d_q(10, 1, 0b000), # exact +1.5
            encode_fcvt_d_q(11, 2, 0b000), # half ULP RNE -> even
            encode_fcvt_d_q(12, 2, 0b011), # half ULP RUP -> next
            encode_fcvt_d_q(13, 3, 0b001), # sNaN canonical + NV
            encode_fcvt_d_q(14, 4, 0b000), # positive overflow -> infinity
            encode_fcvt_d_q(15, 5, 0b100), # half min-subnormal RMM -> min-sub
            encode_fcvt_d_q(16, 6, 0b011), # negative overflow RUP -> max finite
            encode_fcvt_d_q(17, 2, 0b010), # half ULP RDN -> even
            encode_fcvt_d_q(18, 1, 0b111), # dynamic RNE exact
        ]
        program += [nop] * 12
        program += [encode_fsq(reg, 0, 0x200 + (reg - 10) * 0x10)
                    for reg in range(10, 19)]
        program += [nop] * 12
        program.append(encode_fcvt_d_q(19, 1, 0b101)) # reserved rm
        program.append(JAL)

        sign = 1 << 127
        q_one_half = (0x3fff << 112) | (1 << 111)
        q_half_ulp = (0x3fff << 112) | (1 << 59)
        q_snan = (0x7fff << 112) | 1
        q_max = (0x7ffe << 112) | ((1 << 112) - 1)
        q_half_min_d_sub = (15308 << 112)
        sources = [q_one_half, q_half_ulp, q_snan, q_max,
                   q_half_min_d_sub, sign | q_max]
        data = [0] * 256
        for index, value in enumerate(sources, start=1):
            base = (0x100 + index * 0x10) // 4
            data[base:base + 4] = words128(value)

        boxed = (1 << 128) - (1 << 64)
        self.expected = [
            boxed | 0x3ff8000000000000,
            boxed | 0x3ff0000000000000,
            boxed | 0x3ff0000000000001,
            boxed | 0x7ff8000000000000,
            boxed | 0x7ff0000000000000,
            boxed | 0x0000000000000001,
            boxed | 0xffefffffffffffff,
            boxed | 0x3ff0000000000000,
            boxed | 0x3ff8000000000000,
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
    dut = QToDBench(extensions)
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
                if 0x200 <= address < 0x290:
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
    assert diagnostics["fflags"] == 0b10111, diagnostics
    assert writes == expected_writes, diagnostics


def test_q_to_d_explicit_extension():
    check_config("RV32I+GC+Q+D")


def test_q_to_d_star_extension():
    check_config("RV32I+GC+*")
