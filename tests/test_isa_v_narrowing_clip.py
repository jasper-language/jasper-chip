"""Executable V fixed-point narrowing clip family closure."""

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


def vmv_v_i(vd, imm):
    return ((0x17 << 26) | (1 << 25) | ((imm & 0x1F) << 15) |
            (0b011 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vmv_v_x(vd, rs1):
    return ((0x17 << 26) | (1 << 25) | ((rs1 & 0x1F) << 15) |
            (0b100 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vnclip(funct6, funct3, vd, vs2, operand, vm=1):
    return ((funct6 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((operand & 0x1F) << 15) | (funct3 << 12) | ((vd & 0x1F) << 7) | OP_V)


def csrrwi(csr, value):
    return ((csr & 0xFFF) << 20) | ((value & 0x1F) << 15) | (0b101 << 12) | SYSTEM


def csrrs(rd, csr):
    return ((csr & 0xFFF) << 20) | (0b010 << 12) | ((rd & 0x1F) << 7) | SYSTEM


class _VNarrowingClipBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(17, 4, vsew=1),
            enc_i(OP_IMM, 1, 0, 0, 3), vmv_v_x(4, 1),
            enc_i(OP_IMM, 1, 0, 0, 5), vmv_v_x(6, 1),
            enc_i(OP_IMM, 1, 0, 0, 510), vmv_v_x(8, 1),
            enc_i(OP_IMM, 1, 0, 0, 256), vmv_v_x(10, 1),
            enc_i(OP_IMM, 1, 0, 0, -257), vmv_v_x(12, 1),
            vsetivli(17, 4), vmv_v_i(1, 1),
            enc_i(OP_IMM, 2, 0, 0, 1), *([nop()] * 3),
            csrrwi(0x00A, 0), vnclip(0x2E, 0b000, 14, 4, 1),
            csrrwi(0x00A, 1), vnclip(0x2E, 0b000, 15, 4, 1),
            csrrwi(0x00A, 2), vnclip(0x2E, 0b100, 16, 4, 2),
            csrrwi(0x00A, 3), vnclip(0x2E, 0b011, 17, 6, 1),
            csrrwi(0x009, 0), vnclip(0x2E, 0b011, 18, 8, 0), csrrs(20, 0x009),
            csrrwi(0x009, 0), csrrwi(0x00A, 2),
            vnclip(0x2F, 0b011, 19, 10, 1), csrrs(21, 0x009),
            csrrwi(0x009, 0), csrrwi(0x00A, 0),
            vnclip(0x2F, 0b011, 20, 12, 1), csrrs(22, 0x009),
            csrrwi(0x009, 0), csrrwi(0x00A, 2),
            vnclip(0x2F, 0b011, 21, 12, 1), csrrs(23, 0x009),
            csrrwi(0x009, 0), enc_i(OP_IMM, 3, 0, 0, 0), vmv_s_x(0, 3),
            vmv_v_i(22, 7), vnclip(0x2E, 0b011, 22, 8, 0, vm=0), csrrs(24, 0x009),
            vmv_v_i(23, 7), csrrwi(0x008, 2), vnclip(0x2E, 0b011, 23, 4, 1),
            vsetivli(17, 2, vta=1), vnclip(0x2E, 0b011, 24, 4, 1),
            vsetivli(17, 10, vsew=2, vlmul=2),
            enc_i(OP_IMM, 1, 0, 0, -300), vmv_v_x(8, 1),
            vsetivli(17, 10, vsew=1, vlmul=1),
            enc_i(OP_IMM, 2, 0, 0, 4), *([nop()] * 3),
            vnclip(0x2F, 0b100, 28, 8, 2),
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
    dut = _VNarrowingClipBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(1450):
            yield Tick()
        for reg in (14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 28):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[f"v{reg}"] = yield dut.core.dbg_vreg_rdata
        for reg in (20, 21, 22, 23, 24):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_narrowing_clip_rounding_saturation_mask_restart_tail_and_groups(extensions):
    result = run(extensions)
    assert result["v14"] & 0xFFFFFFFF == 0x02020202
    assert result["v15"] & 0xFFFFFFFF == 0x02020202
    assert result["v16"] & 0xFFFFFFFF == 0x01010101
    assert result["v17"] & 0xFFFFFFFF == 0x03030303
    assert result["v18"] & 0xFFFFFFFF == 0xFFFFFFFF
    assert result["v19"] & 0xFFFFFFFF == 0x7F7F7F7F
    assert result["v20"] & 0xFFFFFFFF == 0x80808080
    assert result["v21"] & 0xFFFFFFFF == 0x80808080
    assert (result["x20"], result["x21"], result["x22"], result["x23"]) == (1, 1, 0, 1)
    assert result["v22"] & 0xFFFFFFFF == 0x07070707
    assert result["x24"] == 0
    assert result["v23"] & 0xFFFFFFFF == 0x01010707
    assert result["v24"] == int.from_bytes(b"\x01\x01" + b"\xff" * 14, "little")
    assert result["v28"] == int.from_bytes(b"\xed\xff" * 8, "little")


def test_v_narrowing_clip_disabled_without_v():
    assert all(value == 0 for value in run("RV32I+GC").values())
