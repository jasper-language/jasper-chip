"""Executable closure for VZEXT/VSEXT VF2/VF4/VF8."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP_IMM, OP_V, SYSTEM, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core

EXTENSIONS = ("RV32I+GC+V", "RV32I+GC+*")


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


def vsetivli(avl, vsew=0, vlmul=0, vta=0, vma=0):
    vtype = ((vma & 1) << 7) | ((vta & 1) << 6) | ((vsew & 7) << 3) | (vlmul & 7)
    return ((0b11 << 30) | (vtype << 20) | ((avl & 0x1F) << 15) |
            (0b111 << 12) | (17 << 7) | OP_V)


def vmv_v_x(vd, rs1):
    return ((0x17 << 26) | (1 << 25) | ((rs1 & 0x1F) << 15) |
            (0b100 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vmv_s_x(vd, rs1):
    return ((0x10 << 26) | (1 << 25) | ((rs1 & 0x1F) << 15) |
            (0b110 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vext(vd, vs2, factor, signed=False, vm=1):
    base = {8: 2, 4: 4, 2: 6}[factor]
    simm = base + int(signed)
    return ((0x12 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            (simm << 15) | (0b010 << 12) | ((vd & 0x1F) << 7) | OP_V)


def csrrwi(csr, value):
    return ((csr & 0xFFF) << 20) | ((value & 0x1F) << 15) | (0b101 << 12) | SYSTEM


class _Bench(Elaboratable):
    def __init__(self, extensions):
        program = [
            enc_i(OP_IMM, 1, 0, 0, -128),
            enc_i(OP_IMM, 2, 0, 0, 0x55),
            enc_i(OP_IMM, 3, 0, 0, 5),
            *([nop()] * 3),
            vsetivli(16, vsew=0), vmv_v_x(2, 1),
            vsetivli(4, vsew=1), vext(4, 2, 2), vext(6, 2, 2, signed=True),
            vsetivli(4, vsew=2), vext(8, 2, 4), vext(10, 2, 4, signed=True),
            vsetivli(2, vsew=3), vext(12, 2, 8), vext(14, 2, 8, signed=True),
            vsetivli(4, vsew=2, vma=1), vmv_v_x(22, 2),
            vmv_s_x(0, 3), vext(22, 2, 4, vm=0),
            vsetivli(3, vsew=2, vta=1), vmv_v_x(24, 2),
            csrrwi(0x008, 2), vext(24, 2, 4),
            vsetivli(8, vsew=2, vlmul=1), vext(26, 2, 4),
            vsetivli(2, vsew=2), vext(4, 4, 2),
            vext(4, 4, 4, vm=0),
            vext(4, 4, 8),
            vsetivli(2, vsew=2, vlmul=5), vext(4, 2, 2),
            0x0000006F,
        ]
        self.cycles = 180
        if extensions == "RV32I+GC":
            program = [vsetivli(2, vsew=2), vext(4, 2, 4), 0x0000006F]
            self.cycles = 80
        program += [nop()] * (128 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(program), init=program)
        self.dmem = SimpleDMem(words=4, init=[0] * 4)

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
        for reg in (4, 6, 8, 10, 12, 14, 22, 24, 26, 27):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata
        result["traps"] = traps

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_integer_extension_all_factors_mask_restart_tail_groups_and_illegal(extensions):
    result = run(extensions)
    assert result[4] & ((1 << 64) - 1) == int.from_bytes(b"\x80\x00" * 4, "little")
    assert result[6] & ((1 << 64) - 1) == int.from_bytes(b"\x80\xff" * 4, "little")
    assert result[8] == int.from_bytes((0x80).to_bytes(4, "little") * 4, "little")
    assert result[10] == int.from_bytes((0xFFFFFF80).to_bytes(4, "little") * 4, "little")
    assert result[12] == int.from_bytes((0x80).to_bytes(8, "little") * 2, "little")
    assert result[14] == int.from_bytes((0xFFFFFFFFFFFFFF80).to_bytes(8, "little") * 2, "little")
    assert result[22] == int.from_bytes(
        (0x80).to_bytes(4, "little") + b"\xff" * 4 +
        (0x80).to_bytes(4, "little") + b"\xff" * 4, "little")
    assert result[24] == int.from_bytes(
        (0x55).to_bytes(4, "little") * 2 +
        (0x80).to_bytes(4, "little") + b"\xff" * 4, "little")
    expected = int.from_bytes((0x80).to_bytes(4, "little") * 4, "little")
    assert result[26] == expected
    assert result[27] == expected
    assert result["traps"] >= 4


def test_v_integer_extension_disabled_without_v():
    assert all(value == 0 for value in run("RV32I+GC").values())
