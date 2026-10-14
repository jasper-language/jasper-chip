"""A extension smoke test for RV32I+GC+A and RV64I+GC+A and A-disabled behavior."""

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.isa import OP_IMM, AMO, enc_i, enc_r, LUI, enc_u


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


def enc_amo(opcd, rd, rs1, rs2, funct5, aq=0, rl=0, funct3=0b010):
    funct7 = ((funct5 & 0x1F) << 2) | ((aq & 1) << 1) | (rl & 1)
    return enc_r(opcd, rd, funct3, rs1, rs2, funct7)


def enc_lr(rd, rs1):
    return enc_amo(AMO, rd, rs1, 0, 0b00010, funct3=0b010)


def enc_sc(rd, rs1, rs2):
    return enc_amo(AMO, rd, rs1, rs2, 0b00011, funct3=0b010)


def enc_amoswap(rd, rs1, rs2):
    return enc_amo(AMO, rd, rs1, rs2, 0b00000, funct3=0b010)


def enc_li(rd, imm32):
    upper = (imm32 >> 12) & 0xFFFFF
    lower = imm32 & 0xFFF
    sign_lower = lower
    if sign_lower & (1 << 11):
        upper = (upper + 1) & 0xFFFFF
        sign_lower = lower - (1 << 12)
    return [
        enc_u(LUI, rd, upper),
        enc_i(OP_IMM, rd, 0b000, rd, sign_lower),
    ]


class _AExtBench(Elaboratable):
    def __init__(self, xlen):
        prog = [
            *enc_li(1, 0x11111111),                    # x1 = 0x11111111
            enc_lr(2, 0),                               # x2 = dmem[0]
            enc_amoswap(3, 0, 1),                      # x3 = old[0], dmem[0] = x1
            *enc_li(4, 0x12345678),                    # x4 = 0x12345678
            enc_sc(5, 0, 4),                           # x5 = SC status, dmem[0] = x4
            *enc_li(6, 0x22222222),                    # x6 = 0x22222222
            enc_amo(AMO, 6, 0, 6, 0b00010),           # LR.W x6,0(x0) => should load 0x12345678
            nop(),
        ]
        IMEM_WORDS = 128
        prog = prog + [nop()] * (IMEM_WORDS - len(prog))

        self.core = RV12Core(core_id=0, xlen=xlen, extensions="RV32I+GC+A")
        self.imem = SimpleIMem(words=IMEM_WORDS, init=prog)
        self.dmem = SimpleDMem(words=16, init=[0x0F0F0F0F])

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


def _run_a_ext_case(xlen):
    dut = _AExtBench(xlen)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core

    def proc():
        for _ in range(260):
            yield Tick()

        vals = {}
        for i in (1, 2, 3, 4, 5, 6):
            yield c.dbg_reg_addr.eq(i)
            yield Tick()
            vals[i] = yield c.dbg_reg_rdata

        assert vals[1] == 0x11111111
        assert vals[2] == 0x0F0F0F0F
        assert vals[3] == 0x0F0F0F0F
        assert vals[4] == 0x12345678
        assert vals[5] == 0
        assert vals[6] == 0x12345678

    sim.add_process(proc)
    sim.run()


def test_isa_a_ext_rv32():
    _run_a_ext_case(32)


def test_isa_a_ext_rv64():
    _run_a_ext_case(64)


class _ADisabledBench(Elaboratable):
    def __init__(self, xlen):
        prog = [
            *enc_li(1, 0x11111111),
            enc_lr(2, 0),
            *enc_li(2, 0x22222222),
            nop(),
        ]
        IMEM_WORDS = 64
        prog = prog + [nop()] * (IMEM_WORDS - len(prog))

        self.core = RV12Core(core_id=0, xlen=xlen)
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


def _run_a_disabled_case(xlen):
    dut = _ADisabledBench(xlen)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core

    def proc():
        for _ in range(140):
            yield Tick()

        vals = {}
        for i in (1, 2):
            yield c.dbg_reg_addr.eq(i)
            yield Tick()
            vals[i] = yield c.dbg_reg_rdata

        assert vals[1] == 0x11111111
        assert vals[2] == 0x22222222

    sim.add_process(proc)
    sim.run()


def test_isa_a_ext_disabled_rv32():
    _run_a_disabled_case(32)


def test_isa_a_ext_disabled_rv64():
    _run_a_disabled_case(64)


def _run_a_amo_ops_case(xlen):
    # Prepare a sequence to validate amoswap/amoadd/amoxor/amoor/amoand/amin/max.
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0x00000009),    # x1 = 9
        enc_i(OP_IMM, 2, 0b000, 0, 0x0000000F),    # x2 = 15
        enc_amo(AMO, 3, 0, 1, 0b00000, funct3=0b010),  # AMOSWAP x3, x0, x1 => old=0,new=9
        enc_amo(AMO, 4, 0, 2, 0b00001, funct3=0b010),  # AMOADD x4, x0, x2 => old=9,new=24
        enc_amo(AMO, 5, 0, 1, 0b00100, funct3=0b010),  # AMOXOR x5, x0, x1 => old=24,new=17
        enc_amo(AMO, 6, 0, 2, 0b01000, funct3=0b010),  # AMOOR  x6, x0, x2 => old=17,new=31
        enc_amo(AMO, 7, 0, 2, 0b01100, funct3=0b010),  # AMOAND x7, x0, x2 => old=31,new=15
        enc_amo(AMO, 8, 0, 1, 0b10000, funct3=0b010),  # AMOMIN x8, x0, x1 => old=15,new=9
        enc_amo(AMO, 9, 0, 2, 0b10100, funct3=0b010),  # AMOMAX x9, x0, x2 => old=9,new=15
        enc_amo(AMO, 10, 0, 2, 0b11000, funct3=0b010), # AMOMINU x10, x0, x2 => old=15,new=15
        enc_amo(AMO, 11, 0, 1, 0b11100, funct3=0b010), # AMOMAXU x11, x0, x1 => old=15,new=15
        nop(),
    ]
    IMEM_WORDS = 160
    prog = prog + [nop()] * (IMEM_WORDS - len(prog))

    class _Bench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions="RV32I+GC+A")
            self.imem = SimpleIMem(words=IMEM_WORDS, init=prog)
            self.dmem = SimpleDMem(words=16, init=[0])

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

    dut = _Bench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core

    def proc():
        for _ in range(360):
            yield Tick()

        vals = {}
        for i in range(3, 12):
            yield c.dbg_reg_addr.eq(i)
            yield Tick()
            vals[i] = yield c.dbg_reg_rdata

        assert vals[3] == 0
        assert vals[4] == 9
        assert vals[5] == 24
        assert vals[6] == 17
        assert vals[7] == 31
        assert vals[8] == 15
        assert vals[9] == 9
        assert vals[10] == 9
        assert vals[11] == 9

    sim.add_process(proc)
    sim.run()


def test_isa_a_ext_amo_ops_rv32():
    _run_a_amo_ops_case(32)


def test_isa_a_ext_amo_ops_rv64():
    _run_a_amo_ops_case(64)
