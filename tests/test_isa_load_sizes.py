"""Load-size extension smoke test for RV32I+GC/ RV64I+GC (lb/lh/lbU/lhU/lw)."""

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.isa import OP_IMM, LOAD, enc_i


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


def enc_lb(rd, rs1, imm):
    return enc_i(LOAD, rd, 0b000, rs1, imm)


def enc_lh(rd, rs1, imm):
    return enc_i(LOAD, rd, 0b001, rs1, imm)


def enc_lw(rd, rs1, imm):
    return enc_i(LOAD, rd, 0b010, rs1, imm)


def enc_lbu(rd, rs1, imm):
    return enc_i(LOAD, rd, 0b100, rs1, imm)


def enc_lhu(rd, rs1, imm):
    return enc_i(LOAD, rd, 0b101, rs1, imm)


class _LoadSizeBench(Elaboratable):
    def __init__(self, xlen):
        prog = [
            enc_lb(1, 0, 0),      # x1 = dmem[0] byte 0x80 -> sign-extended
            enc_lbu(2, 0, 0),     # x2 = dmem[0] byte 0x80 -> zero-extended
            enc_lh(3, 0, 2),      # x3 = dmem[2:4] = 0x01FE
            enc_lhu(4, 0, 2),     # x4 = dmem[2:4] = 0x01FE
            enc_lw(5, 0, 0),      # x5 = dmem[0] word = 0x01FE7F80
            enc_lb(6, 0, 1),      # x6 = byte lane 1, positive 0x7F
            enc_lb(7, 0, 2),      # x7 = byte lane 2, negative 0xFE
            enc_lbu(8, 0, 3),     # x8 = byte lane 3, zero-extended 0x01
            enc_lh(9, 0, 0),      # x9 = half lane 0, positive 0x7F80
            enc_lhu(10, 0, 0),    # x10 = half lane 0, zero-extended 0x7F80
            nop(),
            nop(),
        ]
        IMEM_WORDS = 64
        prog = prog + [nop()] * (IMEM_WORDS - len(prog))

        # little-endian: byte0=0x80, byte1=0x7F, byte2=0xFE, byte3=0x01
        self.core = RV12Core(core_id=0, xlen=xlen, rb_mode=2)
        self.imem = SimpleIMem(words=IMEM_WORDS, init=prog)
        self.dmem = SimpleDMem(words=16, init=[0x01FE7F80, 0])

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


def _run_load_size_case(xlen):
    dut = _LoadSizeBench(xlen)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core

    def proc():
        for _ in range(180):
            yield Tick()

        vals = {}
        for i in range(11):
            yield c.dbg_reg_addr.eq(i)
            yield Tick()
            vals[i] = yield c.dbg_reg_rdata

        mask = (1 << xlen) - 1
        if xlen == 32:
            assert vals[1] == 0xFFFFFF80
        else:
            assert vals[1] == 0xFFFFFFFFFFFFFF80
        assert vals[2] == 0x00000080
        assert vals[3] == 0x000001FE
        assert vals[4] == 0x000001FE
        assert vals[5] == 0x01FE7F80
        assert vals[6] == 0x0000007F
        assert vals[7] == (mask - 1)
        assert vals[8] == 0x00000001
        assert vals[9] == 0x00007F80
        assert vals[10] == 0x00007F80

    sim.add_process(proc)
    sim.run()


def test_isa_load_sizes_rv32():
    _run_load_size_case(32)


def test_isa_load_sizes_rv64():
    _run_load_size_case(64)
