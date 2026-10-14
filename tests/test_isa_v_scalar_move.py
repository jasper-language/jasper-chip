"""Executable V scalar/element-zero move closure."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP_IMM, OP_V, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


EXTENSIONS = ("RV32I+GC+V", "RV32I+GC+*")


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


def vsetivli(rd, avl, vsew=0, vta=0, vlmul=0):
    vtypei = ((vta & 1) << 6) | ((vsew & 7) << 3) | (vlmul & 7)
    return ((0b11 << 30) | (vtypei << 20) | ((avl & 0x1F) << 15) |
            (0b111 << 12) | ((rd & 0x1F) << 7) | OP_V)


def vmv_s_x(vd, rs1, vm=1):
    return ((0x10 << 26) | ((vm & 1) << 25) | ((rs1 & 0x1F) << 15) |
            (0b110 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vmv_x_s(rd, vs2, vm=1):
    return ((0x10 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            (0b010 << 12) | ((rd & 0x1F) << 7) | OP_V)


def vmvr_v(vd, vs2, nreg, vm=1):
    count_encoding = nreg - 1
    return ((0x27 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((count_encoding & 0x1F) << 15) | (0b011 << 12) |
            ((vd & 0x1F) << 7) | OP_V)


def vmv_v_v(vd, vs1, vs2=0, vm=1):
    return ((0x17 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((vs1 & 0x1F) << 15) | (0b000 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vmv_v_x(vd, rs1, vs2=0, vm=1):
    return ((0x17 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((rs1 & 0x1F) << 15) | (0b100 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vmv_v_i(vd, imm, vs2=0, vm=1):
    return ((0x17 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((imm & 0x1F) << 15) | (0b011 << 12) | ((vd & 0x1F) << 7) | OP_V)


class _VScalarMoveBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(10, 4, vsew=0, vta=0),
            enc_i(OP_IMM, 1, 0, 0, -128),
            vmv_s_x(1, 1),
            *([nop()] * 3),
            vmv_x_s(5, 1),
            vsetivli(10, 4, vsew=0, vta=1),
            enc_i(OP_IMM, 2, 0, 0, 0x55),
            vmv_s_x(2, 2),
            *([nop()] * 3),
            vsetivli(10, 0, vsew=0, vta=0),
            enc_i(OP_IMM, 3, 0, 0, 0x22),
            vmv_s_x(1, 3),
            vmv_x_s(6, 1),
            vmv_s_x(3, 3, vm=0),
            vmv_x_s(7, 3, vm=0),
            0x0000006F,
        ]
        program += [nop()] * (96 - len(program))
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


def run_program(extensions):
    dut = _VScalarMoveBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(420):
            yield Tick()
        for reg in (5, 6, 7):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield dut.core.dbg_reg_rdata
        for reg in (1, 2, 3):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[f"v{reg}"] = yield dut.core.dbg_vreg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_scalar_element_zero_moves_explicit_and_wildcard(extensions):
    result = run_program(extensions)
    assert result["x5"] == 0xFFFFFF80
    assert result["x6"] == 0xFFFFFF80
    assert result["x7"] == 0
    assert result["v1"] == 0x80
    assert result["v2"] == ((1 << 128) - 1) ^ 0xAA
    assert result["v3"] == 0


def test_v_scalar_moves_are_disabled_without_v():
    result = run_program("RV32I+GC")
    assert result["x5"] == 0
    assert result["x6"] == 0
    assert result["v1"] == 0
    assert result["v2"] == 0


class _VWholeMoveBench(Elaboratable):
    def __init__(self, extensions):
        program = [vsetivli(10, 4, vsew=2, vta=0)]
        for offset in range(8):
            program += [
                enc_i(OP_IMM, 1, 0, 0, offset + 1),
                vmv_s_x(16 + offset, 1),
            ]
        program += [
            *([nop()] * 3),
            vmvr_v(1, 16, 1),
            vmvr_v(2, 16, 2),
            vmvr_v(4, 16, 4),
            vmvr_v(24, 16, 8),
            vmvr_v(9, 16, 2),
            vmvr_v(10, 16, 3),
            vmvr_v(11, 16, 1, vm=0),
            0x0000006F,
        ]
        program += [nop()] * (128 - len(program))
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


def run_whole_move(extensions):
    dut = _VWholeMoveBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(520):
            yield Tick()
        for reg in tuple(range(1, 12)) + tuple(range(24, 32)):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_whole_register_move_groups_and_legality(extensions):
    result = run_whole_move(extensions)
    assert result[1] == 1
    assert [result[reg] for reg in (2, 3)] == [1, 2]
    assert [result[reg] for reg in range(4, 8)] == [1, 2, 3, 4]
    assert [result[reg] for reg in range(24, 32)] == list(range(1, 9))
    assert result[9] == 0
    assert result[10] == 0
    assert result[11] == 0


def test_v_whole_register_moves_are_disabled_without_v():
    result = run_whole_move("RV32I+GC")
    assert all(value == 0 for value in result.values())


class _VVectorMoveBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(10, 31, vsew=0, vta=0, vlmul=1),
            vmv_v_i(8, -1),
            *([nop()] * 3),
            vmv_v_v(12, 8),
            vsetivli(10, 5, vsew=1, vta=0, vlmul=1),
            enc_i(OP_IMM, 1, 0, 0, 0x123),
            vmv_v_x(16, 1),
            vsetivli(10, 2, vsew=2, vta=0, vlmul=7),
            vmv_v_i(20, -1),
            vsetivli(10, 1, vsew=2, vta=1, vlmul=0),
            vmv_v_i(21, 7),
            vmv_v_i(23, 3, vs2=1),
            0x0000006F,
        ]
        program += [nop()] * (128 - len(program))
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


def run_vector_move(extensions):
    dut = _VVectorMoveBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(560):
            yield Tick()
        for reg in (8, 9, 12, 13, 16, 17, 20, 21, 23):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_vector_moves_lmul_sew_tail_and_legality(extensions):
    result = run_vector_move(extensions)
    assert result[8] == (1 << 128) - 1
    assert result[9] == (1 << 120) - 1
    assert result[12] == (1 << 128) - 1
    assert result[13] == (1 << 120) - 1
    assert result[16] == int.from_bytes(b"\x23\x01" * 5 + b"\x00" * 6, "little")
    assert result[17] == 0
    assert result[20] == (1 << 64) - 1
    assert result[21] == (((1 << 128) - 1) ^ 0xFFFFFFFF) | 7
    assert result[23] == 0


def test_v_vector_moves_are_disabled_without_v():
    result = run_vector_move("RV32I+GC")
    assert all(value == 0 for value in result.values())
