"""Executable Zcmt table-jump closure for RV32."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP_IMM, SYSTEM, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


EXTENSIONS = (
    "RV32I+GC+ZCMT",
    "RV32I+GC+*+ZCMT",
)

C_NOP = 0x0001


def cmjt(index):
    return (0b101000 << 10) | ((index & 0xFF) << 2) | 0b10


class _ZcmtBench(Elaboratable):
    def __init__(self, extensions, index, target, target_rd, target_value):
        words = [enc_i(OP_IMM, 0, 0, 0, 0)] * 128
        words[0] = enc_i(OP_IMM, 5, 0, 0, 0x13F)
        words[1] = enc_i(SYSTEM, 6, 0b001, 5, 0x017)  # write jvt, read reset value
        words[2] = enc_i(SYSTEM, 7, 0b010, 0, 0x017)  # read WARL-aligned jvt
        words[3] = cmjt(index) | (C_NOP << 16)
        words[target >> 2] = enc_i(OP_IMM, target_rd, 0, 0, target_value)
        words[(target >> 2) + 1] = 0x0000006F  # JAL x0, 0
        words[(0x100 + index * 4) >> 2] = target | 1  # bit zero must be cleared

        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(words), init=words)
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


def run_case(extensions, index, target, target_rd, target_value):
    dut = _ZcmtBench(extensions, index, target, target_rd, target_value)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    regs = {}

    def process():
        for _ in range(180):
            yield Tick()
        for reg in (1, 6, 7, target_rd):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            regs[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return regs


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zcmt_cm_jt_reads_aligned_jvt_entry_and_clears_target_bit_zero(extensions):
    regs = run_case(extensions, index=0, target=0x20, target_rd=10, target_value=42)
    assert regs[6] == 0
    assert regs[7] == 0x100
    assert regs[10] == 42
    assert regs[1] == 0


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zcmt_cm_jalt_links_pc_plus_two_and_jumps_via_high_index(extensions):
    regs = run_case(extensions, index=32, target=0x30, target_rd=11, target_value=77)
    assert regs[7] == 0x100
    assert regs[11] == 77
    assert regs[1] == 0x0E
