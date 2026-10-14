from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick, Settle

from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


LOAD_FP = 0b0000111
STORE_FP = 0b0100111
OP_FP = 0b1010011
JAL = 0b1101111


def encode_flq(rd, rs1, imm):
    return ((imm & 0xfff) << 20) | (rs1 << 15) | (0b100 << 12) | (rd << 7) | LOAD_FP


def encode_fsq(rs2, rs1, imm):
    immediate = imm & 0xfff
    return (((immediate >> 5) << 25) | (rs2 << 20) | (rs1 << 15) |
            (0b100 << 12) | ((immediate & 0x1f) << 7) | STORE_FP)


def encode_fsgnj_q(rd, rs1, rs2, funct3):
    return ((0b0010011 << 25) | (rs2 << 20) | (rs1 << 15) |
            (funct3 << 12) | (rd << 7) | OP_FP)


class QSignInjectionBench(Elaboratable):
    def __init__(self, extensions):
        self.core = RV12Core(xlen=32, extensions=extensions)
        nops = [0x00000013] * 10
        program = [
            encode_flq(1, 0, 0x100),
            encode_flq(2, 0, 0x110),
            *nops,
            encode_fsgnj_q(3, 1, 2, 0b000),
            encode_fsgnj_q(4, 1, 2, 0b001),
            encode_fsgnj_q(5, 1, 2, 0b010),
            *nops,
            encode_fsq(3, 0, 0x140),
            encode_fsq(4, 0, 0x150),
            encode_fsq(5, 0, 0x160),
            JAL,
        ]
        source_a = [0x89ABCDEF, 0x01234567, 0x00000001, 0xFFFF8000]
        source_b = [0, 0, 0, 0x3FFF0000]
        data = [0] * 256
        data[0x100 // 4:0x110 // 4] = source_a
        data[0x110 // 4:0x120 // 4] = source_b
        self.source_a = source_a
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
    dut = QSignInjectionBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    writes = []
    diagnostics = {"trap": 0, "is_insn": 0, "q_busy": 0, "q_beat": 0}

    def process():
        for _ in range(180):
            yield Settle()
            diagnostics.update({
                "trap": (yield dut.core.trap),
                "is_insn": (yield dut.core.dbg_is_insn),
                "q_busy": (yield dut.core.dbg_q_mem_busy),
                "q_beat": (yield dut.core.dbg_q_mem_beat),
            })
            if (yield dut.core.dmem_valid) and (yield dut.core.dmem_we):
                address = yield dut.core.dmem_addr
                writes.append((address, (yield dut.core.dmem_wdata)))
            yield Tick()

    sim.add_process(process)
    sim.run()
    return dut, writes, diagnostics


def expected_writes(dut):
    magnitude = list(dut.source_a)
    magnitude[3] &= 0x7fffffff
    positive = magnitude
    negative = list(magnitude)
    negative[3] |= 0x80000000
    words = positive + negative + negative
    return [(0x140 + (index // 4) * 0x10 + (index % 4) * 4, word)
            for index, word in enumerate(words)]


def test_q_sign_injection_explicit_extension():
    dut, writes, diagnostics = run_config("RV32I+GC+Q")
    assert dut.core.enable_q
    assert writes == expected_writes(dut), diagnostics


def test_q_sign_injection_star_extension():
    dut, writes, diagnostics = run_config("RV32I+GC+*")
    assert dut.core.enable_q
    assert writes == expected_writes(dut), diagnostics
