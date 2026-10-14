from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick
import pytest

from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def lui(rd, upper20):
    return (upper20 << 12) | (rd << 7) | 0x37


def slli(rd, rs1, shamt):
    return (shamt << 20) | (rs1 << 15) | (1 << 12) | (rd << 7) | 0x13


def addi(rd, rs1, immediate):
    return ((immediate & 0xFFF) << 20) | (rs1 << 15) | (rd << 7) | 0x13


def load_double_bits(rd, upper32):
    return [lui(rd, upper32 >> 12), addi(rd, rd, upper32 & 0xFFF), slli(rd, rd, 32)]


def op_fp(rd, rs1, rs2, funct7, funct3=0):
    return (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | 0x53


NOP = addi(0, 0, 0)


def run(extensions, program, registers):
    words = 128
    program += [NOP] * (words - len(program))

    class Bench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=64, extensions=extensions)
            self.imem = SimpleIMem(words=words, init=program)
            self.dmem = SimpleDMem(words=16)

        def elaborate(self, platform):
            m = Module()
            m.submodules.core = c = self.core
            m.submodules.imem = im = self.imem
            m.submodules.dmem = dm = self.dmem
            m.d.comb += [
                im.addr.eq(c.imem_addr), c.imem_rdata.eq(im.rdata),
                dm.req_valid.eq(c.dmem_valid), dm.req_we.eq(c.dmem_we),
                dm.req_addr.eq(c.dmem_addr), dm.req_wdata.eq(c.dmem_wdata),
                c.dmem_rdata.eq(dm.rsp_rdata), c.gc_enq_ready.eq(0),
                c.gc_rsp_valid.eq(0), c.gc_rsp_tag.eq(0), c.gc_rsp_rd.eq(0),
                c.gc_rsp_data.eq(0), c.wb_enq_ready.eq(1), c.mv_cmd_ready.eq(1),
                c.mv_rsp_valid.eq(0), c.mv_rsp_tag.eq(0), c.mv_rsp_rd.eq(0),
                c.mv_rsp_data.eq(0),
            ]
            return m

    dut = Bench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(800):
            yield Tick()
        for register in registers:
            yield dut.core.dbg_reg_addr.eq(register)
            yield Tick()
            result[register] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return tuple(result[register] for register in registers)


EXTENSIONS = ["RV64I+GC+ZDINX", "RV64I+GC+*+ZDINX"]


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zdinx_rv64_sign_injection_and_minmax(extensions):
    program = []
    program += load_double_bits(1, 0x3FF80000)  # +1.5
    program += load_double_bits(2, 0xC0000000)  # -2.0
    program += [
        op_fp(10, 1, 2, 0b0010001, 0),
        op_fp(11, 1, 2, 0b0010001, 1),
        op_fp(12, 1, 2, 0b0010001, 2),
        op_fp(13, 1, 2, 0b0010101, 0),
        op_fp(14, 1, 2, 0b0010101, 1),
        NOP, NOP, NOP, NOP,
    ]
    assert run(extensions, program, (10, 11, 12, 13, 14)) == (
        0xBFF8000000000000,
        0x3FF8000000000000,
        0xBFF8000000000000,
        0xC000000000000000,
        0x3FF8000000000000,
    )


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zdinx_rv64_compare_and_classify(extensions):
    program = []
    program += load_double_bits(1, 0x3FF80000)
    program += load_double_bits(2, 0xC0000000)
    program += [
        op_fp(10, 1, 1, 0b1010001, 2),
        op_fp(11, 1, 2, 0b1010001, 1),
        op_fp(12, 2, 1, 0b1010001, 0),
        op_fp(13, 2, 0, 0b1110001, 1),
        NOP, NOP, NOP, NOP,
    ]
    assert run(extensions, program, (10, 11, 12, 13)) == (1, 0, 1, 1 << 1)
