"""Executable V merge family closure."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP_IMM, OP_V, enc_i
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


def vmv_v_i(vd, imm):
    return ((0x17 << 26) | (1 << 25) | ((imm & 0x1F) << 15) |
            (0b011 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vmv_v_x(vd, rs1):
    return ((0x17 << 26) | (1 << 25) | ((rs1 & 0x1F) << 15) |
            (0b100 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vmerge(vd, vs2, operand, form):
    funct3 = {"vv": 0b000, "vx": 0b100, "vi": 0b011}[form]
    return ((0x17 << 26) | ((vs2 & 0x1F) << 20) |
            ((operand & 0x1F) << 15) | (funct3 << 12) |
            ((vd & 0x1F) << 7) | OP_V)


def csrrwi(csr, value):
    return ((csr & 0xFFF) << 20) | ((value & 0x1F) << 15) | (0b101 << 12) | 0x73


class _VMergeBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(10, 4),
            vmv_v_i(1, 1),
            enc_i(OP_IMM, 2, 0, 0, 0x22), vmv_v_x(2, 2),
            enc_i(OP_IMM, 1, 0, 0, 0x05), vmv_s_x(0, 1),
            enc_i(OP_IMM, 3, 0, 0, 0x33),
            *([nop()] * 3),
            vmerge(3, 1, 2, "vv"),
            vmerge(4, 1, 3, "vx"),
            vmerge(5, 1, -1, "vi"),
            vmv_v_i(6, 9), csrrwi(0x008, 2), vmerge(6, 1, 2, "vv"),
            vsetivli(10, 2, vta=1), vmv_v_i(7, 9), vmerge(7, 1, 2, "vv"),
            vsetivli(10, 10, vsew=1, vlmul=1),
            enc_i(OP_IMM, 4, 0, 0, 0x111), vmv_v_x(8, 4),
            enc_i(OP_IMM, 5, 0, 0, 0x222), vmv_v_x(10, 5),
            enc_i(OP_IMM, 1, 0, 0, 0x155), vmv_s_x(0, 1),
            *([nop()] * 3), vmerge(12, 8, 10, "vv"),
            0x0000006F,
        ]
        program += [nop()] * (160 - len(program))
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
    dut = _VMergeBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(700):
            yield Tick()
        for reg in (3, 4, 5, 6, 7, 12, 13):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_vmerge_forms_mask_vstart_tail_and_groups(extensions):
    result = run(extensions)
    assert result[3] & 0xFFFFFFFF == 0x01220122
    assert result[4] & 0xFFFFFFFF == 0x01330133
    assert result[5] & 0xFFFFFFFF == 0x01FF01FF
    assert result[6] & 0xFFFFFFFF == 0x01220909
    assert result[7] == int.from_bytes(b"\x22\x01" + b"\xff" * 14, "little")
    expected = b"".join((b"\x22\x02" if i % 2 == 0 else b"\x11\x01") for i in range(10))
    assert result[12] == int.from_bytes(expected[:16], "little")
    assert result[13] & 0xFFFFFFFF == int.from_bytes(expected[16:20], "little")


def test_vmerge_disabled_without_v():
    assert all(value == 0 for value in run("RV32I+GC").values())
