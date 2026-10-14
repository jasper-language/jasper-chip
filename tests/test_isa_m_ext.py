"""Standard M extension smoke test for RV32I+GC+M and RV64I+GC+M."""

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.isa import OP, OP_IMM, OP_32, LUI, enc_u, enc_i, enc_r


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


def enc_mul(rd, rs1, rs2):
    return enc_r(OP, rd, 0b000, rs1, rs2, 0b0000001)


def enc_mulh(rd, rs1, rs2):
    return enc_r(OP, rd, 0b001, rs1, rs2, 0b0000001)


def enc_mulhsu(rd, rs1, rs2):
    return enc_r(OP, rd, 0b010, rs1, rs2, 0b0000001)


def enc_mulhu(rd, rs1, rs2):
    return enc_r(OP, rd, 0b011, rs1, rs2, 0b0000001)


def enc_div(rd, rs1, rs2):
    return enc_r(OP, rd, 0b100, rs1, rs2, 0b0000001)


def enc_divu(rd, rs1, rs2):
    return enc_r(OP, rd, 0b101, rs1, rs2, 0b0000001)


def enc_rem(rd, rs1, rs2):
    return enc_r(OP, rd, 0b110, rs1, rs2, 0b0000001)


def enc_remu(rd, rs1, rs2):
    return enc_r(OP, rd, 0b111, rs1, rs2, 0b0000001)


def enc_divw(rd, rs1, rs2):
    return enc_r(OP_32, rd, 0b100, rs1, rs2, 0b0000001)


class _MExtBench(Elaboratable):
    def __init__(self, xlen):
        prog = [
            enc_u(LUI, 1, 16),                          # x1 = 65536
            enc_u(LUI, 2, 16),                          # x2 = 65536
            enc_i(OP_IMM, 3, 0b000, 0, 0xFFFFFFFF),   # x3 = 0xFFFFFFFF
            enc_i(OP_IMM, 4, 0b000, 0, 3),            # x4 = 3
            enc_mul(5, 1, 2),                          # x5 = x1*x2 = 0x100000000
            enc_mulh(6, 1, 2),                         # x6 = high(x1*x2) = 1
            enc_mulhsu(7, 3, 4),                       # x7 = high(-1*3) = 0xFFFFFFFF
            enc_mulhu(8, 3, 3),                        # x8 = high(0xFFFFFFFF*0xFFFFFFFF) = 0xFFFFFFFE
            enc_div(9, 3, 4),                          # x9 = -1 / 3 = -1 (trunc toward zero)
            enc_rem(10, 3, 4),                         # x10 = -1 % 3 = -1? (RV remainder keeps sign)
            enc_divu(11, 3, 4),                        # x11 = unsigned(-1)/3
            enc_remu(12, 3, 4),                        # x12 = unsigned(-1)%3
            enc_divu(13, 1, 0),                       # x13 = 65536 / 0 (DIVU by zero)
            enc_remu(14, 1, 0),                       # x14 = 65536 % 0 (REMU by zero)
            enc_rem(15, 3, 0),                        # x15 = -1 % 0 (REM by zero)
        ]
        if xlen >= 64:
            prog += [
                enc_u(LUI, 16, 0x80000),              # x16 = 0xFFFFFFFF80000000
                enc_i(OP_IMM, 17, 0b000, 0, 0xFFFFFFFF),  # x17 = -1
                enc_divw(18, 16, 17),                  # x18 = DIVW x16, x17 -> 0xFFFFFFFF80000000
            ]
            prog += [
                enc_div(19, 16, 17),                   # x19 = DIV x16, x17 -> 0xFFFFFFFF80000000 (overflow rule)
                enc_rem(20, 16, 17),                   # x20 = REM x16, x17 -> 0
            ]
        IMEM_WORDS = 160
        prog = prog + [nop()] * (IMEM_WORDS - len(prog))

        self.core = RV12Core(core_id=0, xlen=xlen, extensions="RV32I+GC+M")
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


def _run_m_ext_case(xlen):
    dut = _MExtBench(xlen)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core

    def proc():
        for _ in range(260):
            yield Tick()

        vals = {}
        for i in range(1, 21):
            yield c.dbg_reg_addr.eq(i)
            yield Tick()
            vals[i] = yield c.dbg_reg_rdata

        if xlen >= 64:
            assert vals[5] == (1 << 32)  # MUL writes full xlen lower bits; MUL(65536,65536)=2^32
        else:
            assert vals[5] == 0
        if xlen >= 64:
            assert vals[6] == 0
            assert vals[7] == 0xFFFFFFFFFFFFFFFF
            assert vals[8] == 0xFFFFFFFFFFFFFFFE
        else:
            assert vals[6] == 1
            assert vals[7] == 0xFFFFFFFF
            assert vals[8] == 0xFFFFFFFE
        assert vals[9] == 0xFFFFFFFF
        assert vals[10] == 0xFFFFFFFF
        assert vals[11] == 0x55555555
        assert vals[12] == 0x00000002
        assert vals[13] == (0xFFFFFFFFFFFFFFFF if xlen >= 64 else 0xFFFFFFFF)
        assert vals[14] == (0x00010000 if xlen >= 64 else 0x00010000)
        assert vals[15] == 0xFFFFFFFF
        if xlen >= 64:
            assert vals[18] == 0xFFFFFFFF80000000
            assert vals[19] == 0xFFFFFFFF80000000
            assert vals[20] == 0

    sim.add_process(proc)
    sim.run()


def test_isa_m_ext_rv32():
    _run_m_ext_case(32)


def test_isa_m_ext_rv64():
    _run_m_ext_case(64)
