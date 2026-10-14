"""Executable V widening integer multiply family closure."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP_IMM, OP_V, SYSTEM, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


EXTENSIONS = ("RV32I+GC+V", "RV32I+GC+*")


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


def vsetivli(rd, avl, vsew=0, vlmul=0, vta=0, vma=0):
    vtype = ((vma & 1) << 7) | ((vta & 1) << 6) | ((vsew & 7) << 3) | (vlmul & 7)
    return ((0b11 << 30) | (vtype << 20) | ((avl & 0x1F) << 15) |
            (0b111 << 12) | ((rd & 0x1F) << 7) | OP_V)


def vmv_s_x(vd, rs1):
    return ((0x10 << 26) | (1 << 25) | ((rs1 & 0x1F) << 15) |
            (0b110 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vmv_v_i(vd, imm):
    return ((0x17 << 26) | (1 << 25) | ((imm & 0x1F) << 15) |
            (0b011 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vmv_v_x(vd, rs1):
    return ((0x17 << 26) | (1 << 25) | ((rs1 & 0x1F) << 15) |
            (0b100 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vwmul(funct6, funct3, vd, vs2, operand, vm=1):
    return ((funct6 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((operand & 0x1F) << 15) | (funct3 << 12) | ((vd & 0x1F) << 7) | OP_V)


def csrrwi(csr, value):
    return ((csr & 0xFFF) << 20) | ((value & 0x1F) << 15) | (0b101 << 12) | SYSTEM


class _VWideningMultiplyBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(17, 4), vmv_v_i(1, -7), vmv_v_i(2, 9),
            *([nop()] * 3),
            vwmul(0x3B, 0b010, 4, 1, 2),
            vwmul(0x38, 0b010, 6, 1, 2),
            vwmul(0x3A, 0b010, 8, 1, 2),
            enc_i(OP_IMM, 3, 0, 0, 3), *([nop()] * 3),
            vwmul(0x3B, 0b110, 10, 1, 3),
            enc_i(OP_IMM, 1, 0, 0, 5), vmv_s_x(0, 1),
            vsetivli(17, 8), vmv_v_i(12, 7), vsetivli(17, 4),
            *([nop()] * 3), vwmul(0x3B, 0b010, 12, 1, 2, vm=0),
            vmv_v_i(14, 7), csrrwi(0x008, 2), vwmul(0x3B, 0b010, 14, 1, 2),
            vsetivli(17, 2, vta=1), vmv_v_i(16, 7),
            vwmul(0x3B, 0b010, 16, 1, 2),
            vsetivli(17, 10, vsew=1, vlmul=1),
            enc_i(OP_IMM, 1, 0, 0, -300), vmv_v_x(20, 1),
            enc_i(OP_IMM, 2, 0, 0, 200), vmv_v_x(22, 2),
            *([nop()] * 3), vwmul(0x3B, 0b010, 24, 20, 22),
            0x0000006F,
        ]
        program += [nop()] * (192 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(program), init=program)
        self.dmem = SimpleDMem(words=16, init=[0] * 16)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = c = self.core
        m.submodules.imem = im = self.imem
        m.submodules.dmem = dm = self.dmem
        m.d.comb += [
            im.addr.eq(c.imem_addr), c.imem_rdata.eq(im.rdata),
            dm.req_valid.eq(c.dmem_valid), dm.req_we.eq(c.dmem_we),
            dm.req_addr.eq(c.dmem_addr), dm.req_wdata.eq(c.dmem_wdata),
            c.dmem_rdata.eq(dm.rsp_rdata), c.gc_enq_ready.eq(1),
            c.gc_rsp_valid.eq(0), c.gc_rsp_tag.eq(0), c.gc_rsp_rd.eq(0),
            c.gc_rsp_data.eq(0), c.wb_enq_ready.eq(1), c.mv_cmd_ready.eq(1),
            c.mv_rsp_valid.eq(0), c.mv_rsp_tag.eq(0), c.mv_rsp_rd.eq(0),
            c.mv_rsp_data.eq(0),
        ]
        return m


def run(extensions):
    dut = _VWideningMultiplyBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(1100):
            yield Tick()
        for reg in (4, 6, 8, 10, 12, 14, 16, 17, 24, 25, 26):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_widening_multiply_signed_mask_vstart_tail_and_groups(extensions):
    result = run(extensions)
    assert result[4] & ((1 << 64) - 1) == int.from_bytes(b"\xc1\xff" * 4, "little")
    assert result[6] & ((1 << 64) - 1) == int.from_bytes(b"\xc1\x08" * 4, "little")
    assert result[8] & ((1 << 64) - 1) == int.from_bytes(b"\xc1\xff" * 4, "little")
    assert result[10] & ((1 << 64) - 1) == int.from_bytes(b"\xeb\xff" * 4, "little")
    assert result[12] & ((1 << 64) - 1) == int.from_bytes(
        b"\xc1\xff\x07\x07\xc1\xff\x07\x07", "little")
    assert result[14] & ((1 << 64) - 1) == int.from_bytes(
        b"\x07\x07\x07\x07\xc1\xff\xc1\xff", "little")
    assert result[16] == int.from_bytes(b"\xc1\xff" * 2 + b"\xff" * 12, "little")
    assert result[17] == (1 << 128) - 1
    product = (-60000) & 0xFFFFFFFF
    expected = b"".join(product.to_bytes(4, "little") for _ in range(10))
    assert result[24] == int.from_bytes(expected[:16], "little")
    assert result[25] == int.from_bytes(expected[16:32], "little")
    assert result[26] & ((1 << 64) - 1) == int.from_bytes(expected[32:40], "little")


def test_v_widening_multiply_disabled_without_v():
    assert all(value == 0 for value in run("RV32I+GC").values())
