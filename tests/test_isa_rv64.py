"""RV64 W-suffix instruction verification."""

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.isa import (
    enc_i, enc_r, enc_u,
    OP_IMM, OP, LUI,
    OP_IMM_32, OP_32,
)

XLEN = 64

def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)

# ── W-suffix instruction encoders (manual — isa_rv32i doesn't handle them) ──

def enc_addiw(rd, rs1, imm):
    return enc_i(OP_IMM_32, rd, 0b000, rs1, imm)

def enc_addw(rd, rs1, rs2):
    return enc_r(OP_32, rd, 0b000, rs1, rs2, 0b0000000)

def enc_subw(rd, rs1, rs2):
    return enc_r(OP_32, rd, 0b000, rs1, rs2, 0b0100000)

def enc_slliw(rd, rs1, shamt):
    return enc_i(OP_IMM_32, rd, 0b001, rs1, shamt & 0x1f)

def enc_srliw(rd, rs1, shamt):
    return enc_i(OP_IMM_32, rd, 0b101, rs1, shamt & 0x1f)

def enc_sraiw(rd, rs1, shamt):
    return enc_i(OP_IMM_32, rd, 0b101, rs1, 0x40 | (shamt & 0x1f))

def enc_sllw(rd, rs1, rs2):
    return enc_r(OP_32, rd, 0b001, rs1, rs2, 0b0000000)

def enc_srlw(rd, rs1, rs2):
    return enc_r(OP_32, rd, 0b101, rs1, rs2, 0b0000000)

def enc_sraw(rd, rs1, rs2):
    return enc_r(OP_32, rd, 0b101, rs1, rs2, 0b0100000)


def build_program():
    """
    Instruction sequence (PC = idx*4):

    idx  label   instr                               effect (RV64 intent)
    ──── ──────  ─────────────────────────────────── ─────────────────────────
    0            LUI   x1, 0x80000                   x1 = 0xFFFF_FFFF_8000_0000
    1            ADDI  x1, x1, -1                    x1 = 0xFFFF_FFFF_7FFF_FFFF
    2            ADDIW x2, x1, 0                     x2 = SE32(0x7FFFFFFF) = 0x7FFF_FFFF
    3            ADDI  x3, x0, -1                    x3 = 0xFFFF_FFFF_FFFF_FFFF
    4            ADDIW x4, x3, 0                     x4 = SE32(0xFFFFFFFF) = 0xFFFF_FFFF_FFFF_FFFF
    5            ADDW  x5, x3, x1                    x5 = SE32(-1 + 0x7FFFFFFF) = SE32(0x7FFFFFFE) = 0x7FFF_FFFE
    6            SUBW  x6, x3, x1                    x6 = SE32(-1 - 0x7FFFFFFF) = SE32(0x80000000) = 0xFFFF_FFFF_8000_0000
    7            ADDI  x7, x0, 0x5                   x7 = 5
    8            SLLIW x8, x7, 3                     x8 = SE32(5 << 3) = 40
    9            SRLIW x9, x7, 1                     x9 = SE32(5 >> 1) = 2
    10           SRAIW x10, x7, 1                    x10 = SE32(5 >> 1) = 2
    11           SLLW  x11, x7, x7                   x11 = SE32(5 << 5) = SE32(160) = 160
    12           SRLW  x12, x7, x7                   x12 = SE32(5 >> 5) = 0
    13           SRAW  x13, x7, x7                   x13 = SE32(5 >> 5) = 0
    14           ADDI  x14, x0, 0x7FF                x14 = 0x7FF (done marker)
    """
    return [
        enc_u(LUI, 1, 0x80000),                          # 0
        enc_i(OP_IMM, 1, 0b000, 1, -1 & 0xfff),          # 1  ADDI x1,x1,-1
        enc_addiw(2, 1, 0),                                # 2
        enc_i(OP_IMM, 3, 0b000, 0, -1 & 0xfff),          # 3  ADDI x3,x0,-1
        enc_addiw(4, 3, 0),                                # 4
        enc_addw(5, 3, 1),                                 # 5
        enc_subw(6, 3, 1),                                 # 6
        enc_i(OP_IMM, 7, 0b000, 0, 5),                   # 7  ADDI x7,x0,5
        enc_slliw(8, 7, 3),                                # 8
        enc_srliw(9, 7, 1),                                # 9
        enc_sraiw(10, 7, 1),                               # 10
        enc_sllw(11, 7, 7),                                # 11
        enc_srlw(12, 7, 7),                                # 12
        enc_sraw(13, 7, 7),                                # 13
        enc_i(OP_IMM, 14, 0b000, 0, 0x7ff),               # 14  done marker
    ]


class TbIsaRv64(Elaboratable):
    def __init__(self):
        IMEM_WORDS = 1024
        prog = build_program()
        prog = prog + [nop()] * (IMEM_WORDS - len(prog))

        self.core = RV12Core(core_id=0, xlen=XLEN)
        self.imem = SimpleIMem(words=IMEM_WORDS, init=prog)
        self.dmem = SimpleDMem(words=64)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = c = self.core
        m.submodules.imem = im = self.imem
        m.submodules.dmem = dm = self.dmem

        m.d.comb += [
            im.addr.eq(c.imem_addr),
            c.imem_rdata.eq(im.rdata),
            dm.req_valid.eq(c.dmem_valid),
            dm.req_we.eq(c.dmem_we),
            dm.req_addr.eq(c.dmem_addr),
            dm.req_wdata.eq(c.dmem_wdata),
            c.dmem_rdata.eq(dm.rsp_rdata),
            c.gc_enq_ready.eq(0),
            c.gc_rsp_valid.eq(0),
            c.gc_rsp_tag.eq(0),
            c.gc_rsp_rd.eq(0),
            c.gc_rsp_data.eq(0),
            c.wb_enq_ready.eq(1),
            c.mv_cmd_ready.eq(1),
            c.mv_rsp_valid.eq(0),
            c.mv_rsp_tag.eq(0),
            c.mv_rsp_rd.eq(0),
            c.mv_rsp_data.eq(0),
        ]
        return m


def check_reg(regs, name, idx, expected, errors):
    v = regs.get(f"x{idx}", None)
    if v is None:
        errors.append(f"x{idx} not read")
    elif v != expected:
        errors.append(f"x{idx}=0x{v:016x} expected 0x{expected:016x}")


def main():
    import sys

    dut = TbIsaRv64()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core

    def proc():
        # Run enough cycles for all instructions to retire
        for _ in range(300):
            yield Tick()

        regs = {}
        for i in range(32):
            yield c.dbg_reg_addr.eq(i)
            yield Tick()
            regs[f"x{i}"] = (yield c.dbg_reg_rdata)

        for i in range(15):
            print(f"x{i:2d} = 0x{regs[f'x{i}']:016x}")

        print(f"x14 = 0x{regs['x14']:x} (done marker, expected 0x7ff)")

        errs = []

        # RV64-W suffix expectations after full RV64 XLEN + W-suffix writeback support.
        check_reg(regs, "x1",  1, 0xFFFFFFFF7FFFFFFF, errs)
        check_reg(regs, "x2",  2, 0x000000007FFFFFFF, errs)
        check_reg(regs, "x3",  3, 0xFFFFFFFFFFFFFFFF, errs)
        check_reg(regs, "x4",  4, 0xFFFFFFFFFFFFFFFF, errs)
        check_reg(regs, "x5",  5, 0x000000007FFFFFFE, errs)
        check_reg(regs, "x6",  6, 0xFFFFFFFF80000000, errs)
        check_reg(regs, "x7",  7, 0x0000000000000005, errs)
        check_reg(regs, "x8",  8, 0x0000000000000028, errs)
        check_reg(regs, "x9",  9, 0x0000000000000002, errs)
        check_reg(regs, "x10", 10, 0x0000000000000002, errs)
        check_reg(regs, "x11", 11, 0x00000000000000A0, errs)
        check_reg(regs, "x12", 12, 0x0000000000000000, errs)
        check_reg(regs, "x13", 13, 0x0000000000000000, errs)
        check_reg(regs, "x14", 14, 0x00000000000007FF, errs)

        if errs:
            for e in errs:
                print(f"FAIL: {e}")
        else:
            print("\nOK: all register checks passed (baseline — see docstring for caveats).")

        # Only assert if x14 (done marker) was reached — checks ran
        assert regs["x14"] == 0x7FF, f"Done marker x14=0x{regs['x14']:x} != 0x7ff — program may not have finished"
        assert not errs, "\n".join(errs)

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
