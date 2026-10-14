"""Executable V widening add/subtract family closure."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP_IMM, OP_V, SYSTEM, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


EXTENSIONS = ("RV32I+GC+V", "RV32I+GC+*")


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


def vsetivli(rd, avl, vsew=0, vlmul=0, vta=0):
    vtype = ((vta & 1) << 6) | ((vsew & 7) << 3) | (vlmul & 7)
    return ((0b11 << 30) | (vtype << 20) | ((avl & 0x1F) << 15) |
            (0b111 << 12) | ((rd & 0x1F) << 7) | OP_V)


def vmv_s_x(vd, rs1):
    return ((0x10 << 26) | (1 << 25) | ((rs1 & 0x1F) << 15) |
            (0b110 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vmv_v_x(vd, rs1):
    return ((0x17 << 26) | (1 << 25) | ((rs1 & 0x1F) << 15) |
            (0b100 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vwop(funct6, funct3, vd, vs2, operand, vm=1):
    return ((funct6 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((operand & 0x1F) << 15) | (funct3 << 12) | ((vd & 0x1F) << 7) | OP_V)


def csrrwi(csr, value):
    return ((csr & 0xFFF) << 20) | ((value & 0x1F) << 15) | (0b101 << 12) | SYSTEM


class _VWideningAddSubBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(17, 4),
            enc_i(OP_IMM, 1, 0, 0, 250), vmv_v_x(1, 1),
            enc_i(OP_IMM, 2, 0, 0, 10), vmv_v_x(2, 2),
            *([nop()] * 3),
            vwop(0x30, 0b010, 4, 1, 2), vwop(0x31, 0b010, 6, 1, 2),
            vwop(0x32, 0b010, 8, 1, 2), vwop(0x33, 0b010, 10, 1, 2),
            enc_i(OP_IMM, 3, 0, 0, 10), *([nop()] * 3),
            vwop(0x30, 0b110, 12, 1, 3), vwop(0x31, 0b110, 12, 1, 3),
            vwop(0x32, 0b110, 12, 1, 3),
            enc_i(OP_IMM, 4, 0, 0, 5), vmv_s_x(0, 4), *([nop()] * 3),
            vwop(0x33, 0b110, 12, 1, 3, vm=0),
            vwop(0x30, 0b010, 14, 1, 2), *([nop()] * 3),
            vwop(0x34, 0b010, 16, 14, 2), vwop(0x35, 0b010, 18, 14, 2),
            vwop(0x36, 0b010, 20, 14, 2),
            csrrwi(0x008, 2), vwop(0x37, 0b010, 22, 14, 2),
            vwop(0x34, 0b110, 24, 14, 3), vwop(0x35, 0b110, 26, 14, 3),
            vwop(0x36, 0b110, 28, 14, 3),
            vsetivli(17, 2, vta=1), vwop(0x37, 0b110, 30, 14, 3),
            vsetivli(17, 10, vsew=1, vlmul=1),
            enc_i(OP_IMM, 1, 0, 0, -300), vmv_v_x(4, 1),
            enc_i(OP_IMM, 2, 0, 0, 200), vmv_v_x(6, 2),
            *([nop()] * 3), vwop(0x31, 0b010, 24, 4, 6),
            0x0000006F,
        ]
        program += [nop()] * (224 - len(program))
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
    dut = _VWideningAddSubBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(1300):
            yield Tick()
        for reg in (4, 6, 8, 10, 12, 16, 18, 20, 22, 28, 30, 31, 24, 25, 26):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_widening_add_sub_all_forms_mask_vstart_tail_and_groups(extensions):
    result = run(extensions)
    assert result[8] & ((1 << 64) - 1) == int.from_bytes(b"\xf0\x00" * 4, "little")
    assert result[10] & ((1 << 64) - 1) == int.from_bytes(b"\xf0\xff" * 4, "little")
    assert result[12] & ((1 << 64) - 1) == int.from_bytes(
        b"\xf0\xff\xf0\x00\xf0\xff\xf0\x00", "little")
    assert result[16] & ((1 << 64) - 1) == int.from_bytes(b"\x0e\x01" * 4, "little")
    assert result[18] & ((1 << 64) - 1) == int.from_bytes(b"\x0e\x01" * 4, "little")
    assert result[20] & ((1 << 64) - 1) == int.from_bytes(b"\xfa\x00" * 4, "little")
    assert result[22] & ((1 << 64) - 1) == int.from_bytes(b"\x00\x00" * 2 + b"\xfa\x00" * 2, "little")
    assert result[28] & ((1 << 64) - 1) == int.from_bytes(b"\xfa\x00" * 4, "little")
    assert result[30] == int.from_bytes(b"\xfa\x00" * 2 + b"\xff" * 12, "little")
    assert result[31] == (1 << 128) - 1
    product = (-100) & 0xFFFFFFFF
    expected = b"".join(product.to_bytes(4, "little") for _ in range(10))
    assert result[24] == int.from_bytes(expected[:16], "little")
    assert result[25] == int.from_bytes(expected[16:32], "little")
    assert result[26] & ((1 << 64) - 1) == int.from_bytes(expected[32:40], "little")


def test_v_widening_add_sub_disabled_without_v():
    assert all(value == 0 for value in run("RV32I+GC").values())
