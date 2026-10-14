"""Executable V load/store addressing-mode closure."""

import pytest
from amaranth import Elaboratable, Module

from rtl.isa import OP_IMM, OP_V, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core
from sim.v_batch import run_v_program


LOAD_FP = 0x07
STORE_FP = 0x27


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


def addi(rd, imm):
    return enc_i(OP_IMM, rd, 0, 0, imm)


def vsetivli(avl, vsew=0, vlmul=0):
    vtype = ((vsew & 7) << 3) | (vlmul & 7)
    return ((0b11 << 30) | (vtype << 20) | ((avl & 0x1F) << 15) |
            (0b111 << 12) | (17 << 7) | OP_V)


def vmem(opcode, vd_vs3, rs1, width=0, rs2_lumop=0, mop=0, vm=1,
         nf=0, mew=0):
    return (((nf & 7) << 29) | ((mew & 1) << 28) | ((mop & 3) << 26) |
            ((vm & 1) << 25) | ((rs2_lumop & 0x1F) << 20) |
            ((rs1 & 0x1F) << 15) | ((width & 7) << 12) |
            ((vd_vs3 & 0x1F) << 7) | opcode)


def words_from_bytes(data):
    padded = bytes(data) + b"\x00" * ((-len(data)) & 3)
    return [int.from_bytes(padded[i:i + 4], "little")
            for i in range(0, len(padded), 4)]


class _Bench(Elaboratable):
    def __init__(self, extensions, fof=False):
        if fof:
            program = [
                addi(1, 1), addi(4, 32), vsetivli(4),
                vmem(LOAD_FP, 12, 1, rs2_lumop=0b10000),
                vmem(LOAD_FP, 13, 4),
                0x0000006F,
            ]
        else:
            program = [
                addi(1, 1), addi(2, 2), addi(3, 64), addi(4, 32), addi(5, 48),
                vsetivli(4),
                vmem(LOAD_FP, 1, 1),
                vmem(LOAD_FP, 2, 1, rs2_lumop=2, mop=2),
                vmem(LOAD_FP, 3, 4),
                vmem(LOAD_FP, 4, 1, rs2_lumop=3, mop=1),
                vmem(LOAD_FP, 6, 1, nf=1),
                vmem(LOAD_FP, 8, 1, rs2_lumop=0b01000),
                vmem(STORE_FP, 1, 3),
                vmem(LOAD_FP, 10, 3),
                vsetivli(8),
                vmem(LOAD_FP, 0, 5, rs2_lumop=0b01011),
                0x0000006F,
            ]
        program += [nop()] * (128 - len(program))

        memory = bytearray((i * 3 + 1) & 0xFF for i in range(128))
        memory[32:36] = bytes((0, 2, 5, 7))
        memory[48] = 0b10100101

        self.memory = bytes(memory)
        self.fof = fof
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(program), init=program)
        self.dmem = SimpleDMem(words=32, init=words_from_bytes(memory))

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = c = self.core
        m.submodules.imem = im = self.imem
        m.submodules.dmem = dm = self.dmem
        m.d.comb += [
            im.addr.eq(c.imem_addr), c.imem_rdata.eq(im.rdata),
            dm.req_valid.eq(c.dmem_valid), dm.req_we.eq(c.dmem_we),
            dm.req_addr.eq(c.dmem_addr), dm.req_wdata.eq(c.dmem_wdata),
            c.dmem_rdata.eq(dm.rsp_rdata),
            c.dmem_error.eq(c.dmem_valid & (c.dmem_addr == 3)
                            if self.fof else 0),
            c.gc_enq_ready.eq(1), c.gc_rsp_valid.eq(0), c.gc_rsp_tag.eq(0),
            c.gc_rsp_rd.eq(0), c.gc_rsp_data.eq(0), c.wb_enq_ready.eq(1),
            c.mv_cmd_ready.eq(1), c.mv_rsp_valid.eq(0), c.mv_rsp_tag.eq(0),
            c.mv_rsp_rd.eq(0), c.mv_rsp_data.eq(0),
        ]
        return m


def run(extensions, fof=False):
    dut = _Bench(extensions, fof=fof)
    result = run_v_program(
        extensions, dut.imem.init, dut.dmem.init, 400,
        vregs=(0, 1, 2, 3, 4, 6, 7, 8, 10, 12, 13),
        fault_addr=3 if fof else None, trace_dmem=True, control_from=368,
        v_units=(),
    )
    return dut.memory, result


@pytest.mark.parametrize("extensions", ("RV32I+V", "RV32I+GC+V", "RV32I+GC+*"))
def test_v_memory_unit_strided_indexed_segment_whole_mask_and_store(extensions):
    memory, result = run(extensions)

    def packed(values):
        values = bytes(values)
        return int.from_bytes(values + b"\x00" * (16 - len(values)), "little")

    expected = {
        1: packed(memory[1:5]),
        2: packed(memory[i] for i in (1, 3, 5, 7)),
        3: packed((0, 2, 5, 7)),
        4: packed(memory[1 + i] for i in (0, 2, 5, 7)),
        6: packed(memory[i] for i in (1, 3, 5, 7)),
        7: packed(memory[i] for i in (2, 4, 6, 8)),
        8: int.from_bytes(memory[1:17], "little"),
        10: packed(memory[1:5]),
        0: 0b10100101,
    }
    observed = {reg: result[reg] if reg != 0 else result[reg] & 0xFF
                for reg in expected}
    assert observed == expected, {
        "observed": observed,
        "expected": expected,
        "traps": result["traps"],
        "trace": result["trace"],
        "control_trace": result["control_trace"],
    }


def test_v_memory_disabled_without_v():
    _, result = run("RV32I+GC")
    assert all(result[reg] == 0 for reg in (0, 1, 2, 3, 4, 6, 7, 8, 10))


@pytest.mark.parametrize("extensions", ("RV32I+V", "RV32I+GC+V", "RV32I+GC+*"))
def test_vleff_suppresses_later_fault_and_reduces_vl(extensions):
    memory, result = run(extensions, fof=True)
    assert result[12] == int.from_bytes(memory[1:3] + b"\x00" * 14, "little")
    assert result[13] == int.from_bytes(memory[32:34] + b"\x00" * 14, "little")
    assert result["traps"] == 0
    assert result["trace"][:5] == [(0, 1), (0, 2), (0, 3), (0, 32), (0, 33)]
