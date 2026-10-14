"""Executable closure for VMV1R/2R/4R/8R.V whole-register moves."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import LOAD_FP, OP_IMM, OP_V, SYSTEM, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core

EXTENSIONS = ("RV32I+GC+V", "RV32I+GC+*")


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


def vsetivli(avl, vsew=2):
    vtype = (vsew & 7) << 3
    return ((0b11 << 30) | (vtype << 20) | ((avl & 0x1F) << 15) |
            (0b111 << 12) | (17 << 7) | OP_V)


def vfmv_v_f(vd, fs1):
    return ((0x17 << 26) | (1 << 25) | ((fs1 & 0x1F) << 15) |
            (0b101 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vmvnr(vd, vs2, nregs, vm=1, simm=None):
    encoded_simm = nregs - 1 if simm is None else simm
    return ((0x27 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((encoded_simm & 0x1F) << 15) | (0b011 << 12) |
            ((vd & 0x1F) << 7) | OP_V)


def csrrwi(csr, value):
    return ((csr & 0xFFF) << 20) | ((value & 0x1F) << 15) | (0b101 << 12) | SYSTEM


class _Bench(Elaboratable):
    def __init__(self, extensions):
        loads = []
        for freg, offset in ((1, 0), (2, 4), (3, 8), (4, 12)):
            loads += [enc_i(LOAD_FP, freg, 0b010, 0, offset), *([nop()] * 4)]
        program = loads + [
            vsetivli(4),
            vfmv_v_f(2, 1), vmvnr(3, 2, 1),
            vfmv_v_f(4, 1), vfmv_v_f(5, 2), vmvnr(6, 4, 2),
            vfmv_v_f(8, 1), vfmv_v_f(9, 2),
            vfmv_v_f(10, 3), vfmv_v_f(11, 4), vmvnr(12, 8, 4),
            vfmv_v_f(16, 1), vfmv_v_f(17, 2),
            vfmv_v_f(18, 3), vfmv_v_f(19, 4),
            vfmv_v_f(20, 1), vfmv_v_f(21, 2),
            vfmv_v_f(22, 3), vfmv_v_f(23, 4), vmvnr(24, 16, 8),
            vfmv_v_f(2, 1), vfmv_v_f(3, 2),
            csrrwi(0x008, 2), vmvnr(3, 2, 1),
            vfmv_v_f(28, 4), csrrwi(0x008, 4), vmvnr(28, 2, 1),
            csrrwi(0x008, 0),
            vfmv_v_f(29, 2), vfmv_v_f(30, 2), vfmv_v_f(31, 2),
            vsetivli(4, vsew=0), csrrwi(0x008, 15), vmvnr(29, 2, 1),
            vsetivli(4, vsew=1), csrrwi(0x008, 7), vmvnr(30, 2, 1),
            vsetivli(2, vsew=3),
            csrrwi(0x008, 1), vmvnr(31, 2, 1),
            vmvnr(5, 4, 2),
            vmvnr(4, 4, 2, vm=0),
            vmvnr(4, 4, 1, simm=2),
            0x0000006F,
        ]
        self.cycles = 180
        if extensions == "RV32I+GC":
            program = [vsetivli(4), vmvnr(4, 2, 1), 0x0000006F]
            self.cycles = 80
        program += [nop()] * (128 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(program), init=program)
        self.dmem = SimpleDMem(words=4, init=[
            0x11111111, 0x22222222, 0x33333333, 0x44444444,
        ])

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
    dut = _Bench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        traps = 0
        for _ in range(dut.cycles):
            traps += (yield dut.core.trap)
            yield Tick()
        for reg in tuple(range(3, 16)) + tuple(range(24, 32)):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata
        result["traps"] = traps

    sim.add_process(process)
    sim.run()
    return result


def repeated(word):
    return int.from_bytes(word.to_bytes(4, "little") * 4, "little")


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_vmvnr_all_group_sizes_restart_overlap_and_reserved_encodings(extensions):
    result = run(extensions)
    values = [repeated(0x11111111), repeated(0x22222222),
              repeated(0x33333333), repeated(0x44444444)]
    assert result[3] == int.from_bytes(
        (0x22222222).to_bytes(4, "little") * 2 +
        (0x11111111).to_bytes(4, "little") * 2, "little")
    assert result[6] == values[0]
    assert result[7] == values[1]
    assert [result[reg] for reg in range(12, 16)] == values
    assert [result[reg] for reg in range(24, 28)] == values
    assert result[28] == values[3]
    assert result[29] == int.from_bytes(b"\x22" * 15 + b"\x11", "little")
    assert result[30] == int.from_bytes(b"\x22" * 14 + b"\x11" * 2, "little")
    assert result[31] == int.from_bytes(b"\x22" * 8 + b"\x11" * 8, "little")
    assert result["traps"] >= 3


def test_vmvnr_disabled_without_v():
    assert all(value == 0 for value in run("RV32I+GC").values())
