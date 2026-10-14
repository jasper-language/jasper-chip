"""Deep binary64 IEEE coverage for the V floating multiply family."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import LOAD_FP, OP_IMM, OP_V, SYSTEM, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


EXTENSIONS = ("RV32I+GC+V", "RV32I+GC+*")


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


def vsetivli(avl, vsew=3):
    vtype = (vsew & 7) << 3
    return ((0b11 << 30) | (vtype << 20) | ((avl & 0x1F) << 15) |
            (0b111 << 12) | (17 << 7) | OP_V)


def vfmv_v_f(vd, fs1):
    return ((0x17 << 26) | (1 << 25) | ((fs1 & 0x1F) << 15) |
            (0b101 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vfmul_vv(vd, vs2, vs1):
    return ((0x24 << 26) | (1 << 25) | ((vs2 & 0x1F) << 20) |
            ((vs1 & 0x1F) << 15) | (0b001 << 12) |
            ((vd & 0x1F) << 7) | OP_V)


def csrrwi(csr, value):
    return (((csr & 0xFFF) << 20) | ((value & 0x1F) << 15) |
            (0b101 << 12) | SYSTEM)


def csrrs(rd, csr):
    return (((csr & 0xFFF) << 20) | (0b010 << 12) |
            ((rd & 0x1F) << 7) | SYSTEM)


class _Bench(Elaboratable):
    def __init__(self, extensions, batch):
        values = [
            0x3FF0000000000000,  # 1.0
            0x7FF0000000001234,  # sNaN
            0x7FF8000000001234,  # qNaN
            0x0000000000000000,  # +0
            0x7FF0000000000000,  # +inf
            0x8000000000000000,  # -0
            0x4008000000000000,  # 3.0
            0x7FEFFFFFFFFFFFFF,  # maximum finite
            0x4000000000000000,  # 2.0
            0x0000000000000001,  # minimum subnormal
            0x3FE0000000000000,  # 0.5
            0x8000000000000001,  # negative minimum subnormal
        ]
        words = []
        for value in values:
            words += [value & 0xFFFFFFFF, value >> 32]

        cases = [
            # vd, flag rd, lhs index, rhs index, rm
            (4, 20, 1, 0, 0),
            (5, 21, 2, 0, 0),
            (6, 22, 3, 4, 0),
            (7, 23, 5, 6, 0),
            (8, 24, 7, 8, 0),
            (9, 25, 7, 8, 1),
            (10, 26, 9, 10, 0),
            (11, 27, 9, 10, 3),
            (12, 28, 11, 10, 2),
            (13, 29, 11, 10, 3),
        ]
        cases = cases[batch * 2:(batch + 1) * 2]
        program = [vsetivli(2)]
        for vd, rd, lhs, rhs, rm in cases:
            program += [
                enc_i(LOAD_FP, 1, 0b011, 0, lhs * 8), *([nop()] * 4),
                enc_i(LOAD_FP, 2, 0b011, 0, rhs * 8), *([nop()] * 4),
                vfmv_v_f(1, 1), vfmv_v_f(2, 2),
                csrrwi(0x002, rm), csrrwi(0x001, 0),
                vfmul_vv(vd, 1, 2), csrrs(rd, 0x001),
            ]
        program += [0x0000006F]
        program += [nop()] * (40 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(program), init=program)
        self.dmem = SimpleDMem(words=32, init=words + [0] * (32 - len(words)))

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


def run(extensions, batch):
    dut = _Bench(extensions, batch)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(140):
            yield Tick()
        for reg in range(4, 14):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[f"v{reg}"] = yield dut.core.dbg_vreg_rdata
        for reg in range(20, 30):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
@pytest.mark.parametrize("batch", range(5))
def test_v_float_multiply_f64_special_overflow_underflow_and_rounding(extensions, batch):
    got = run(extensions, batch)
    expected = [
        (0x7FF8000000000000, 0x10),
        (0x7FF8000000000000, 0x00),
        (0x7FF8000000000000, 0x10),
        (0x8000000000000000, 0x00),
        (0x7FF0000000000000, 0x05),
        (0x7FEFFFFFFFFFFFFF, 0x05),
        (0x0000000000000000, 0x03),
        (0x0000000000000001, 0x03),
        (0x8000000000000001, 0x03),
        (0x8000000000000000, 0x03),
    ]
    start = batch * 2
    for index, (value, flags) in enumerate(expected[start:start + 2], start=start):
        vector = int.from_bytes(value.to_bytes(8, "little") * 2, "little")
        assert got[f"v{index + 4}"] == vector
        assert got[f"x{index + 20}"] == flags
