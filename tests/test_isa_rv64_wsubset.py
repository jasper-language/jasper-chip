"""Minimal smoke test for RV64 W-suffix instruction decode/execute."""

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.isa import OP_IMM_32, OP_32, OP_IMM, OP, LUI, AUIPC, enc_i, enc_r


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


def enc_addiw(rd, rs1, imm):
    return enc_i(OP_IMM_32, rd, 0b000, rs1, imm)


def enc_slliw(rd, rs1, shamt):
    return enc_i(OP_IMM_32, rd, 0b001, rs1, shamt & 0x1f)


def enc_srliw(rd, rs1, shamt):
    return enc_i(OP_IMM_32, rd, 0b101, rs1, shamt & 0x1f)


def enc_sraiw(rd, rs1, shamt):
    return enc_i(OP_IMM_32, rd, 0b101, rs1, 0x400 | (shamt & 0x1f))


def enc_addw(rd, rs1, rs2):
    return enc_r(OP_32, rd, 0b000, rs1, rs2, 0b0000000)


def enc_subw(rd, rs1, rs2):
    return enc_r(OP_32, rd, 0b000, rs1, rs2, 0b0100000)


def enc_sllw(rd, rs1, rs2):
    return enc_r(OP_32, rd, 0b001, rs1, rs2, 0b0000000)


def enc_srlw(rd, rs1, rs2):
    return enc_r(OP_32, rd, 0b101, rs1, rs2, 0b0000000)


def enc_sraw(rd, rs1, rs2):
    return enc_r(OP_32, rd, 0b101, rs1, rs2, 0b0100000)


class TbRv64WSubset(Elaboratable):
    def __init__(self):
        prog = [
            enc_i(OP_IMM, 1, 0b000, 0, 7),   # x1 = 7
            enc_i(OP_IMM, 2, 0b000, 0, 3),   # x2 = 3
            enc_addiw(3, 1, 0),               # x3 = signext32(7)
            enc_subw(4, 1, 2),                # x4 = 4
            enc_slliw(5, 1, 1),               # x5 = 14
            enc_srliw(6, 1, 1),               # x6 = 3
            enc_sraiw(7, 1, 1),               # x7 = 3
            enc_addw(8, 1, 2),                # x8 = 10
            enc_sllw(9, 1, 2),                # x9 = 56 (shift by rs2=3 => low5=3)
            enc_srlw(10, 1, 2),               # x10 = 0 (shift by rs2=3)
            enc_sraw(11, 1, 2),               # x11 = 0
            enc_sllw(12, 1, 1),               # x12 = 896 (shift by 7)
        ]
        IMEM_WORDS = 128
        prog = prog + [nop()] * (IMEM_WORDS - len(prog))

        self.core = RV12Core(core_id=0, xlen=64)
        self.imem = SimpleIMem(words=IMEM_WORDS, init=prog)
        self.dmem = SimpleDMem(words=16)

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
            c.gc_enq_ready.eq(1),
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


def test_rv64_wsubset():
    dut = TbRv64WSubset()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core

    def proc():
        # Wait enough cycles for all instructions to retire.
        for _ in range(260):
            yield Tick()

        regs = {}
        for i in range(13):
            yield c.dbg_reg_addr.eq(i)
            yield Tick()
            regs[i] = (yield c.dbg_reg_rdata)

        expect = {
            1: 7,
            2: 3,
            3: 7,
            4: 4,
            5: 14,
            6: 3,
            7: 3,
            8: 10,
            9: 56,
            10: 0,
            11: 0,
            12: 896,
        }
        for idx, value in expect.items():
            assert regs[idx] == value

    sim.add_process(proc)
    sim.run()


if __name__ == '__main__':
    test_rv64_wsubset()
