"""ZICSR extension smoke test for RV32I+GC+ZICSR and RV64I+GC+ZICSR."""

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.isa import FENCE_I_IMM, LOAD, LOAD_FP, LUI, MADD, MSUB, NMADD, NMSUB, OP_FP, OP_IMM, STORE_FP, SYSTEM, enc_i, enc_r, enc_u


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


def enc_r4(opcode, rd, rm, rs1, rs2, rs3, fmt=0):
    return ((rs3 & 0x1F) << 27) | ((fmt & 0x3) << 25) | ((rs2 & 0x1F) << 20) | \
           ((rs1 & 0x1F) << 15) | ((rm & 0x7) << 12) | ((rd & 0x1F) << 7) | (opcode & 0x7F)


def enc_s_local(opcode, funct3, rs1, rs2, imm):
    imm &= 0xFFF
    return ((imm >> 5) << 25) | ((rs2 & 0x1F) << 20) | ((rs1 & 0x1F) << 15) | \
           ((funct3 & 0x7) << 12) | ((imm & 0x1F) << 7) | (opcode & 0x7F)


class _ZicsrEnabledBench(Elaboratable):
    def __init__(self, xlen):
        prog = [
            enc_i(OP_IMM, 1, 0b000, 0, 0x123),         # x1 = 0x123
            enc_i(SYSTEM, 0, 0b001, 1, 0x300),         # csrrw  x0, mstatus, x1 (x0 should stay 0)
            enc_i(SYSTEM, 0, 0b010, 0, 0x301),         # csrrs  x0, misa, x0 (x0 should stay 0)
            enc_i(SYSTEM, 0, 0b101, 7, 0x303),         # csrrwi x0, mie, 7 (x0 should stay 0)
            enc_i(SYSTEM, 0, 0b111, 2, 0x305),         # csrci  x0, stvec, 2 (x0 should stay 0)
            enc_i(SYSTEM, 2, 0b001, 1, 0x300),         # csrrw  x2, mstatus, x1
            enc_i(OP_IMM, 3, 0b000, 0, 0x234),         # x3 = 0x234
            enc_i(SYSTEM, 4, 0b010, 3, 0x301),         # csrrs  x4, misa, x3
            enc_i(OP_IMM, 5, 0b000, 0, 0x567),         # x5 = 0x567
            enc_i(SYSTEM, 5, 0b011, 5, 0x302),         # csrrc  x5, 0x302, x5
            enc_i(SYSTEM, 6, 0b101, 7, 0x303),         # csrrwi x6, 0x303, 7
            enc_i(SYSTEM, 7, 0b110, 3, 0x304),         # csrsi  x7, 0x304, 3
            enc_i(SYSTEM, 8, 0b111, 2, 0x305),         # csrci  x8, 0x305, 2
            enc_i(SYSTEM, 0, 0b000, 0, 0),             # ecall (ignored by current minimal model)
            enc_i(SYSTEM, 0, 0b000, 0, FENCE_I_IMM),  # fence.i (ignored by this minimal model)
            enc_i(OP_IMM, 9, 0b000, 0, 0x9),          # x9 = 9 (verifies control continues after ecall/ebreak)
            enc_i(SYSTEM, 0, 0b000, 0, 1),             # ebreak (ignored by current minimal model)
            enc_i(OP_IMM, 10, 0b000, 0, 0xA),         # x10 = 10
            nop(),
        ]

        IMEM_WORDS = 512
        prog = prog + [nop()] * (IMEM_WORDS - len(prog))

        self.core = RV12Core(core_id=0, xlen=xlen, extensions="RV32I+GC+ZICSR")
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


def _run_zicsr_enabled_case(xlen):
    dut = _ZicsrEnabledBench(xlen)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core

    def proc():
        for _ in range(240):
            yield Tick()

        vals = {}
        for i in range(1, 9):
            yield c.dbg_reg_addr.eq(i)
            yield Tick()
            vals[i] = yield c.dbg_reg_rdata

        yield c.dbg_reg_addr.eq(0)
        yield Tick()
        x0_val = yield c.dbg_reg_rdata

        assert vals[1] == 0x123
        assert vals[2] == 0x123
        assert vals[3] == 0x234
        assert vals[4] == 0
        assert vals[5] == 0x567
        assert vals[6] == 0
        assert vals[7] == 0
        assert vals[8] == 0
        assert x0_val == 0

        yield c.dbg_reg_addr.eq(9)
        yield Tick()
        assert (yield c.dbg_reg_rdata) == 0x9
        yield c.dbg_reg_addr.eq(10)
        yield Tick()
        assert (yield c.dbg_reg_rdata) == 0xA

    sim.add_process(proc)
    sim.run()


def test_zicsr_enabled_rv32():
    _run_zicsr_enabled_case(32)


def test_zicsr_enabled_rv64():
    _run_zicsr_enabled_case(64)


class _ZicsrDisabledBench(Elaboratable):
    def __init__(self, xlen):
        prog = [
            enc_i(OP_IMM, 1, 0b000, 0, 0x123),     # x1 = 0x123
            enc_i(SYSTEM, 2, 0b001, 1, 0x300),     # csrrw x2, mstatus, x1 (disabled => NOP)
            enc_i(OP_IMM, 2, 0b000, 0, 0x321),     # x2 = 0x321
            enc_i(OP_IMM, 3, 0b000, 0, 0x1),       # x3 = 1
            enc_i(SYSTEM, 3, 0b101, 3, 0x001),     # csrrwi x3, fflags, 3 (disabled => NOP)
            nop(),
        ]
        IMEM_WORDS = 256
        prog = prog + [nop()] * (IMEM_WORDS - len(prog))

        self.core = RV12Core(core_id=0, xlen=xlen, extensions="RV32I")
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


def _run_zicsr_disabled_case(xlen):
    dut = _ZicsrDisabledBench(xlen)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core

    def proc():
        for _ in range(160):
            yield Tick()

        yield c.dbg_reg_addr.eq(1)
        yield Tick()
        v1 = yield c.dbg_reg_rdata
        yield c.dbg_reg_addr.eq(2)
        yield Tick()
        v2 = yield c.dbg_reg_rdata
        yield c.dbg_reg_addr.eq(3)
        yield Tick()
        v3 = yield c.dbg_reg_rdata

        assert v1 == 0x123
        assert v2 == 0x321
        assert v3 == 0x1

    sim.add_process(proc)
    sim.run()


def test_zicsr_disabled_rv32():
    _run_zicsr_disabled_case(32)


def test_zicsr_disabled_rv64():
    _run_zicsr_disabled_case(64)


class _FloatingCsrAliasBench(Elaboratable):
    def __init__(self, xlen):
        prog = [
            enc_i(OP_IMM, 1, 0b000, 0, 0x0A5),    # x1 = frm=5, fflags=5
            enc_i(SYSTEM, 2, 0b001, 1, 0x003),     # csrrw  x2, fcsr, x1
            enc_i(SYSTEM, 3, 0b010, 0, 0x001),     # csrrs  x3, fflags, x0
            enc_i(SYSTEM, 4, 0b011, 3, 0x001),     # csrrc  x4, fflags, x3
            enc_i(SYSTEM, 5, 0b101, 3, 0x002),     # csrrwi x5, frm, 3
            enc_i(SYSTEM, 6, 0b110, 0x12, 0x001),  # csrrsi x6, fflags, 0x12
            enc_i(SYSTEM, 7, 0b111, 0x02, 0x003),  # csrrci x7, fcsr, 0x02
            enc_i(SYSTEM, 8, 0b010, 0, 0x001),     # csrrs  x8, fflags, x0
            enc_i(SYSTEM, 9, 0b010, 0, 0x002),     # csrrs  x9, frm, x0
            enc_i(SYSTEM, 10, 0b010, 0, 0x003),    # csrrs  x10, fcsr, x0
            nop(),
        ]
        prog += [nop()] * (256 - len(prog))

        self.core = RV12Core(core_id=0, xlen=xlen, extensions="RV32I+GC+F+ZICSR")
        self.imem = SimpleIMem(words=256, init=prog)
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


def _run_floating_csr_alias_case(xlen):
    dut = _FloatingCsrAliasBench(xlen)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(180):
            yield Tick()
        for reg in range(2, 11):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        2: 0x00,
        3: 0x05,
        4: 0x05,
        5: 0x05,
        6: 0x00,
        7: 0x72,
        8: 0x10,
        9: 0x03,
        10: 0x70,
    }


def test_floating_csr_aliases_and_all_zicsr_forms_rv32():
    _run_floating_csr_alias_case(32)


def test_floating_csr_aliases_and_all_zicsr_forms_rv64():
    _run_floating_csr_alias_case(64)


class _FloatingFlagsBench(Elaboratable):
    def __init__(self, extensions):
        prog = [
            enc_u(LUI, 1, 0x3F800),                   # +1.0f
            enc_r(OP_FP, 1, 0b000, 1, 0, 0b1111000), # FMV.W.X f1, x1
            enc_r(OP_FP, 2, 0b000, 1, 0, 0b0001100), # FDIV.S +1.0,+0.0 -> +inf, DZ
            nop(),
            enc_r(OP_FP, 2, 0b000, 2, 0, 0b1110000), # FMV.X.W x2, f2
            enc_i(SYSTEM, 3, 0b010, 0, 0x001),        # read fflags -> DZ
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),        # clear fflags
            enc_r(OP_FP, 4, 0b000, 0, 0, 0b0001100), # FDIV.S +0.0,+0.0 -> qNaN, NV
            enc_r(OP_FP, 5, 0b000, 1, 0, 0b0001100), # sticky DZ joins NV
            nop(),
            enc_r(OP_FP, 4, 0b000, 4, 0, 0b1110000), # FMV.X.W x4, f4
            enc_i(SYSTEM, 6, 0b010, 0, 0x001),        # read fflags -> NV|DZ
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),        # clear fflags
            enc_u(LUI, 7, 0x80000),                   # -0.0f
            enc_r(OP_FP, 7, 0b000, 7, 0, 0b1111000), # FMV.W.X f7, x7
            enc_r(OP_FP, 8, 0b000, 7, 0, 0b0101100), # FSQRT.S -0.0 -> -0.0, no NV
            nop(),
            enc_r(OP_FP, 8, 0b000, 8, 0, 0b1110000), # FMV.X.W x8, f8
            enc_i(SYSTEM, 9, 0b010, 0, 0x001),        # read fflags -> 0
            nop(),
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
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


def _run_floating_flags_case(extensions):
    dut = _FloatingFlagsBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(180):
            yield Tick()
        for reg in (2, 3, 4, 6, 8, 9):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        2: 0x7F800000,
        3: 0b01000,
        4: 0x7FC00000,
        6: 0b11000,
        8: 0x80000000,
        9: 0,
    }


def test_floating_div_sqrt_flags_are_sticky_and_negative_zero_is_preserved():
    _run_floating_flags_case("RV32I+GC+F+ZICSR")
    _run_floating_flags_case("RV32I+GC+*")


class _FloatingCompareFlagsBench(Elaboratable):
    def __init__(self, extensions):
        prog = [
            enc_u(LUI, 1, 0x7FC00),                   # quiet NaN
            enc_u(LUI, 2, 0x7F800),
            enc_i(OP_IMM, 2, 0b000, 2, 1),            # signaling NaN
            enc_u(LUI, 3, 0x3F800),                   # +1.0f
            enc_r(OP_FP, 1, 0b000, 1, 0, 0b1111000), # FMV.W.X f1, x1
            enc_r(OP_FP, 2, 0b000, 2, 0, 0b1111000), # FMV.W.X f2, x2
            enc_r(OP_FP, 3, 0b000, 3, 0, 0b1111000), # FMV.W.X f3, x3
            nop(),
            enc_r(OP_FP, 4, 0b010, 1, 1, 0b1010000), # FEQ.S qNaN,qNaN -> 0, no NV
            nop(),
            enc_i(SYSTEM, 5, 0b010, 0, 0x001),        # fflags -> 0
            enc_r(OP_FP, 6, 0b000, 2, 3, 0b0010100), # FMIN.S sNaN,+1 -> +1, NV
            enc_r(OP_FP, 7, 0b001, 3, 2, 0b0010100), # FMAX.S +1,sNaN -> +1, sticky NV
            nop(),
            enc_r(OP_FP, 6, 0b000, 6, 0, 0b1110000), # FMV.X.W x6, f6
            enc_r(OP_FP, 7, 0b000, 7, 0, 0b1110000), # FMV.X.W x7, f7
            enc_i(SYSTEM, 8, 0b010, 0, 0x001),        # fflags -> NV
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),        # clear fflags
            enc_r(OP_FP, 9, 0b010, 2, 2, 0b1010000), # FEQ.S sNaN,sNaN -> 0, NV
            nop(),
            enc_i(SYSTEM, 10, 0b010, 0, 0x001),       # fflags -> NV
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),        # clear fflags
            enc_r(OP_FP, 11, 0b001, 1, 3, 0b1010000),# FLT.S qNaN,+1 -> 0, NV
            nop(),
            enc_i(SYSTEM, 12, 0b010, 0, 0x001),       # fflags -> NV
            nop(),
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(words=16)

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


def _run_floating_compare_flags_case(extensions):
    dut = _FloatingCompareFlagsBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(190):
            yield Tick()
        for reg in (4, 5, 6, 7, 8, 9, 10, 11, 12):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        4: 0, 5: 0,
        6: 0x3F800000, 7: 0x3F800000, 8: 0b10000,
        9: 0, 10: 0b10000,
        11: 0, 12: 0b10000,
    }


def test_floating_minmax_and_compare_nan_invalid_flag_rules():
    _run_floating_compare_flags_case("RV32I+GC+F+ZICSR")
    _run_floating_compare_flags_case("RV32I+GC+*")


class _FloatingMultiplyFlagsBench(Elaboratable):
    def __init__(self, extensions):
        prog = [
            enc_u(LUI, 1, 0x7FC00),                   # quiet NaN
            enc_u(LUI, 2, 0x7F800),
            enc_i(OP_IMM, 2, 0b000, 2, 1),            # signaling NaN
            enc_u(LUI, 3, 0x7F800),                   # +infinity
            enc_u(LUI, 4, 0x3F800),                   # +1.0f
            enc_r(OP_FP, 1, 0b000, 1, 0, 0b1111000), # FMV.W.X f1, x1
            enc_r(OP_FP, 2, 0b000, 2, 0, 0b1111000), # FMV.W.X f2, x2
            enc_r(OP_FP, 3, 0b000, 3, 0, 0b1111000), # FMV.W.X f3, x3
            enc_r(OP_FP, 4, 0b000, 4, 0, 0b1111000), # FMV.W.X f4, x4
            nop(),
            enc_r(OP_FP, 5, 0b000, 1, 4, 0b0001000), # FMUL.S qNaN,+1 -> qNaN, no NV
            nop(),
            enc_r(OP_FP, 5, 0b000, 5, 0, 0b1110000), # FMV.X.W x5, f5
            enc_i(SYSTEM, 6, 0b010, 0, 0x001),        # fflags -> 0
            enc_r(OP_FP, 7, 0b000, 0, 3, 0b0001000), # FMUL.S +0,+inf -> qNaN, NV
            nop(),
            enc_r(OP_FP, 7, 0b000, 7, 0, 0b1110000), # FMV.X.W x7, f7
            enc_i(SYSTEM, 8, 0b010, 0, 0x001),        # fflags -> NV
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),        # clear fflags
            enc_r(OP_FP, 9, 0b000, 2, 4, 0b0001000), # FMUL.S sNaN,+1 -> qNaN, NV
            nop(),
            enc_r(OP_FP, 9, 0b000, 9, 0, 0b1110000), # FMV.X.W x9, f9
            enc_i(SYSTEM, 10, 0b010, 0, 0x001),       # fflags -> NV
            nop(),
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(words=16)

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


def _run_floating_multiply_flags_case(extensions):
    dut = _FloatingMultiplyFlagsBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(180):
            yield Tick()
        for reg in (5, 6, 7, 8, 9, 10):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        5: 0x7FC00000, 6: 0,
        7: 0x7FC00000, 8: 0b10000,
        9: 0x7FC00000, 10: 0b10000,
    }


def test_floating_multiply_invalid_flag_rules():
    _run_floating_multiply_flags_case("RV32I+GC+F+ZICSR")
    _run_floating_multiply_flags_case("RV32I+GC+*")


class _FloatingAddFlagsBench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = [
            enc_u(LUI, 1, 0x7F800),                   # +infinity
            enc_u(LUI, 2, 0xFF800),                   # -infinity
            enc_u(LUI, 3, 0x7FC00),                   # quiet NaN
            enc_u(LUI, 4, 0x7F800),
            enc_i(OP_IMM, 4, 0b000, 4, 1),            # signaling NaN
            enc_u(LUI, 5, 0x3F800),                   # +1.0f
            enc_r(OP_FP, 1, 0b000, 1, 0, 0b1111000), # FMV.W.X f1, x1
            enc_r(OP_FP, 2, 0b000, 2, 0, 0b1111000), # FMV.W.X f2, x2
            enc_r(OP_FP, 3, 0b000, 3, 0, 0b1111000), # FMV.W.X f3, x3
            enc_r(OP_FP, 4, 0b000, 4, 0, 0b1111000), # FMV.W.X f4, x4
            enc_r(OP_FP, 5, 0b000, 5, 0, 0b1111000), # FMV.W.X f5, x5
            nop(),
            enc_r(OP_FP, 6, 0b000, 1, 2, 0b0000000), # FADD.S +inf,-inf -> qNaN, NV
            nop(),
            enc_r(OP_FP, 6, 0b000, 6, 0, 0b1110000), # FMV.X.W x6, f6
            enc_i(SYSTEM, 7, 0b010, 0, 0x001),        # fflags -> NV
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),        # clear fflags
            enc_r(OP_FP, 8, 0b000, 3, 5, 0b0000000), # FADD.S qNaN,+1 -> qNaN, no NV
            nop(),
            enc_r(OP_FP, 8, 0b000, 8, 0, 0b1110000), # FMV.X.W x8, f8
            enc_i(SYSTEM, 9, 0b010, 0, 0x001),        # fflags -> 0
            enc_r(OP_FP, 10, 0b000, 1, 1, 0b0000100),# FSUB.S +inf,+inf -> qNaN, NV
            nop(),
            enc_r(OP_FP, 10, 0b000, 10, 0, 0b1110000),# FMV.X.W x10, f10
            enc_i(SYSTEM, 11, 0b010, 0, 0x001),       # fflags -> NV
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),        # clear fflags
            enc_r(OP_FP, 12, 0b000, 4, 5, 0b0000000),# FADD.S sNaN,+1 -> qNaN, NV
            nop(),
            enc_r(OP_FP, 12, 0b000, 12, 0, 0b1110000),# FMV.X.W x12, f12
            enc_i(SYSTEM, 13, 0b010, 0, 0x001),       # fflags -> NV
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),        # clear fflags
            enc_r(OP_FP, 14, 0b000, 1, 1, 0b0000000),# FADD.S +inf,+inf -> +inf, no NV
            nop(),
            enc_r(OP_FP, 14, 0b000, 14, 0, 0b1110000),# FMV.X.W x14, f14
            enc_i(SYSTEM, 15, 0b010, 0, 0x001),       # fflags -> 0
            nop(),
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(words=16)


def _run_floating_add_flags_case(extensions):
    dut = _FloatingAddFlagsBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(190):
            yield Tick()
        for reg in range(6, 16):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        6: 0x7FC00000, 7: 0b10000,
        8: 0x7FC00000, 9: 0,
        10: 0x7FC00000, 11: 0b10000,
        12: 0x7FC00000, 13: 0b10000,
        14: 0x7F800000, 15: 0,
    }


def test_floating_add_sub_invalid_and_infinity_rules():
    _run_floating_add_flags_case("RV32I+GC+F+ZICSR")
    _run_floating_add_flags_case("RV32I+GC+*")


class _FloatingConvertFlagsBench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = [
            enc_u(LUI, 1, 0x7FC00),                   # quiet NaN
            enc_u(LUI, 2, 0x7F800),                   # +infinity
            enc_u(LUI, 3, 0xC0000),                   # -2.0f
            enc_u(LUI, 4, 0xCF000),                   # -2^31, valid signed boundary
            enc_u(LUI, 5, 0x4F000),                   # +2^31, signed overflow
            enc_r(OP_FP, 1, 0b000, 1, 0, 0b1111000), # FMV.W.X f1, x1
            enc_r(OP_FP, 2, 0b000, 2, 0, 0b1111000), # FMV.W.X f2, x2
            enc_r(OP_FP, 3, 0b000, 3, 0, 0b1111000), # FMV.W.X f3, x3
            enc_r(OP_FP, 4, 0b000, 4, 0, 0b1111000), # FMV.W.X f4, x4
            enc_r(OP_FP, 5, 0b000, 5, 0, 0b1111000), # FMV.W.X f5, x5
            nop(),
            enc_r(OP_FP, 6, 0b001, 1, 0, 0b1100000), # FCVT.W.S qNaN -> INT_MAX, NV
            nop(),
            enc_i(SYSTEM, 7, 0b010, 0, 0x001),        # fflags -> NV
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),        # clear fflags
            enc_r(OP_FP, 8, 0b001, 2, 1, 0b1100000), # FCVT.WU.S +inf -> UINT_MAX, NV
            nop(),
            enc_i(SYSTEM, 9, 0b010, 0, 0x001),        # fflags -> NV
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),        # clear fflags
            enc_r(OP_FP, 10, 0b001, 3, 1, 0b1100000),# FCVT.WU.S -2 -> 0, NV
            nop(),
            enc_i(SYSTEM, 11, 0b010, 0, 0x001),       # fflags -> NV
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),        # clear fflags
            enc_r(OP_FP, 12, 0b001, 4, 0, 0b1100000),# FCVT.W.S -2^31 -> INT_MIN, valid
            nop(),
            enc_i(SYSTEM, 13, 0b010, 0, 0x001),       # fflags -> 0
            enc_r(OP_FP, 14, 0b001, 5, 0, 0b1100000),# FCVT.W.S +2^31 -> INT_MAX, NV
            nop(),
            enc_i(SYSTEM, 15, 0b010, 0, 0x001),       # fflags -> NV
            nop(),
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(words=16)


def _run_floating_convert_flags_case(extensions):
    dut = _FloatingConvertFlagsBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(190):
            yield Tick()
        for reg in range(6, 16):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        6: 0x7FFFFFFF, 7: 0b10000,
        8: 0xFFFFFFFF, 9: 0b10000,
        10: 0, 11: 0b10000,
        12: 0x80000000, 13: 0,
        14: 0x7FFFFFFF, 15: 0b10000,
    }


def test_floating_to_integer_invalid_and_boundary_rules():
    _run_floating_convert_flags_case("RV32I+GC+F+ZICSR")
    _run_floating_convert_flags_case("RV32I+GC+*")


class _IndependentFloatingRegisterBench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = [
            enc_u(LUI, 1, 0x3F800),                    # x1 = +1.0f bits
            enc_r(OP_FP, 2, 0b000, 1, 0, 0b1111000), # FMV.W.X f2, x1
            enc_i(OP_IMM, 1, 0b000, 0, 7),            # x1 = 7
            enc_r(OP_FP, 3, 0b000, 2, 0, 0b1110000), # FMV.X.W x3, f2
            enc_r(OP_FP, 0, 0b000, 1, 0, 0b1111000), # FMV.W.X f0, x1
            enc_r(OP_FP, 4, 0b000, 0, 0, 0b1110000), # FMV.X.W x4, f0
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(words=16)


def _run_independent_floating_register_case(extensions):
    dut = _IndependentFloatingRegisterBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(100):
            yield Tick()
        for reg in (1, 2, 3, 4):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[f"x{reg}"] = yield dut.core.dbg_reg_rdata
        for reg in (0, 2):
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            results[f"f{reg}"] = yield dut.core.dbg_freg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        "x1": 7,
        "x2": 0,
        "x3": 0x3F800000,
        "x4": 7,
        "f0": 0xFFFFFFFF00000007,
        "f2": 0xFFFFFFFF3F800000,
    }


def test_independent_floating_register_file_and_fmv_nan_boxing():
    _run_independent_floating_register_case("RV32I+GC+F+ZICSR")
    _run_independent_floating_register_case("RV32I+GC+*")


class _FloatingSignInjectionRegisterBench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = [
            enc_u(LUI, 1, 0x3FC00),                    # x1 = +1.5f bits
            enc_r(OP_FP, 1, 0b000, 1, 0, 0b1111000), # FMV.W.X f1, x1
            enc_u(LUI, 2, 0x80000),                    # x2 = -0.0f bits
            enc_r(OP_FP, 2, 0b000, 2, 0, 0b1111000), # FMV.W.X f2, x2
            nop(),
            enc_r(OP_FP, 3, 0b000, 1, 2, 0b0010000), # FSGNJ.S f3, f1, f2
            enc_r(OP_FP, 4, 0b001, 1, 2, 0b0010000), # FSGNJN.S f4, f1, f2
            enc_r(OP_FP, 5, 0b010, 1, 2, 0b0010000), # FSGNJX.S f5, f1, f2
            nop(),
            enc_r(OP_FP, 3, 0b000, 3, 0, 0b1110000), # FMV.X.W x3, f3
            enc_r(OP_FP, 4, 0b000, 4, 0, 0b1110000), # FMV.X.W x4, f4
            enc_r(OP_FP, 5, 0b000, 5, 0, 0b1110000), # FMV.X.W x5, f5
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(words=16)


def _run_floating_sign_injection_register_case(extensions):
    dut = _FloatingSignInjectionRegisterBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(120):
            yield Tick()
        for reg in (3, 4, 5):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[f"x{reg}"] = yield dut.core.dbg_reg_rdata
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            results[f"f{reg}"] = yield dut.core.dbg_freg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        "x3": 0xBFC00000,
        "x4": 0x3FC00000,
        "x5": 0xBFC00000,
        "f3": 0xFFFFFFFFBFC00000,
        "f4": 0xFFFFFFFF3FC00000,
        "f5": 0xFFFFFFFFBFC00000,
    }


def test_floating_sign_injection_uses_independent_register_file():
    _run_floating_sign_injection_register_case("RV32I+GC+F+ZICSR")
    _run_floating_sign_injection_register_case("RV32I+GC+*")


class _FloatingCompareClassRegisterBench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = [
            enc_u(LUI, 1, 0x7FC00),                    # qNaN
            enc_r(OP_FP, 1, 0b000, 1, 0, 0b1111000), # FMV.W.X f1, x1
            enc_u(LUI, 2, 0x7F800),
            enc_i(OP_IMM, 2, 0b000, 2, 1),            # sNaN
            enc_r(OP_FP, 2, 0b000, 2, 0, 0b1111000), # FMV.W.X f2, x2
            enc_u(LUI, 3, 0x80000),
            enc_i(OP_IMM, 3, 0b000, 3, 1),            # negative subnormal
            enc_r(OP_FP, 3, 0b000, 3, 0, 0b1111000), # FMV.W.X f3, x3
            nop(),
            enc_r(OP_FP, 5, 0b001, 1, 0, 0b1110000), # FCLASS.S x5, f1
            enc_r(OP_FP, 6, 0b001, 2, 0, 0b1110000), # FCLASS.S x6, f2
            enc_r(OP_FP, 7, 0b001, 3, 0, 0b1110000), # FCLASS.S x7, f3
            enc_r(OP_FP, 8, 0b010, 1, 1, 0b1010000), # FEQ.S x8, f1, f1
            enc_i(SYSTEM, 9, 0b010, 0, 0x001),        # qNaN FEQ leaves NV clear
            enc_r(OP_FP, 10, 0b010, 2, 2, 0b1010000),# FEQ.S x10, f2, f2
            enc_i(SYSTEM, 11, 0b010, 0, 0x001),       # sNaN FEQ sets NV
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),        # clear fflags
            enc_r(OP_FP, 12, 0b001, 1, 3, 0b1010000),# FLT.S qNaN,f3 sets NV
            enc_i(SYSTEM, 13, 0b010, 0, 0x001),
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),        # clear fflags
            enc_r(OP_FP, 14, 0b000, 3, 3, 0b1010000),# FLE.S f3,f3 -> true
            enc_i(SYSTEM, 15, 0b010, 0, 0x001),
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(words=16)


def _run_floating_compare_class_register_case(extensions):
    dut = _FloatingCompareClassRegisterBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(180):
            yield Tick()
        for reg in range(5, 16):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        5: 1 << 9,
        6: 1 << 8,
        7: 1 << 2,
        8: 0,
        9: 0,
        10: 0,
        11: 0b10000,
        12: 0,
        13: 0b10000,
        14: 1,
        15: 0,
    }


def test_floating_compare_and_classify_use_independent_register_file():
    _run_floating_compare_class_register_case("RV32I+GC+F+ZICSR")
    _run_floating_compare_class_register_case("RV32I+GC+*")


class _IntegerToFloatingRegisterBench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = [
            enc_i(OP_IMM, 1, 0b000, 0, 2),            # x1 = 2
            enc_i(OP_IMM, 2, 0b000, 0, -2),           # x2 = -2
            enc_u(LUI, 3, 0x80000),                   # x3 = 2^31 unsigned
            enc_r(OP_FP, 4, 0b001, 1, 0, 0b1101000), # FCVT.S.W f4, x1
            enc_r(OP_FP, 5, 0b001, 2, 0, 0b1101000), # FCVT.S.W f5, x2
            enc_r(OP_FP, 6, 0b001, 3, 1, 0b1101000), # FCVT.S.WU f6, x3
            nop(),
            enc_r(OP_FP, 4, 0b000, 4, 0, 0b1110000), # FMV.X.W x4, f4
            enc_r(OP_FP, 5, 0b000, 5, 0, 0b1110000), # FMV.X.W x5, f5
            enc_r(OP_FP, 6, 0b000, 6, 0, 0b1110000), # FMV.X.W x6, f6
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(words=16)


def _run_integer_to_floating_register_case(extensions):
    dut = _IntegerToFloatingRegisterBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(120):
            yield Tick()
        for reg in (4, 5, 6):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[f"x{reg}"] = yield dut.core.dbg_reg_rdata
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            results[f"f{reg}"] = yield dut.core.dbg_freg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        "x4": 0x40000000,
        "x5": 0xC0000000,
        "x6": 0x4F000000,
        "f4": 0xFFFFFFFF40000000,
        "f5": 0xFFFFFFFFC0000000,
        "f6": 0xFFFFFFFF4F000000,
    }


def test_integer_to_floating_conversion_writes_independent_register_file():
    _run_integer_to_floating_register_case("RV32I+GC+F+ZICSR")
    _run_integer_to_floating_register_case("RV32I+GC+*")


class _FloatingFmaRegisterBench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = [
            enc_u(LUI, 1, 0x3FC00),                   # +1.5f
            enc_u(LUI, 2, 0x40000),                   # +2.0f
            enc_u(LUI, 3, 0x3F800),                   # +1.0f
            enc_r(OP_FP, 1, 0b000, 1, 0, 0b1111000),# FMV.W.X f1, x1
            enc_r(OP_FP, 2, 0b000, 2, 0, 0b1111000),# FMV.W.X f2, x2
            enc_r(OP_FP, 3, 0b000, 3, 0, 0b1111000),# FMV.W.X f3, x3
            nop(),
            enc_r4(MADD, 4, 0, 1, 2, 3),             # FMADD.S  f4,f1,f2,f3 = +4
            enc_r4(MSUB, 5, 0, 1, 2, 3),             # FMSUB.S  f5,f1,f2,f3 = +2
            enc_r4(NMSUB, 6, 0, 1, 2, 3),            # FNMSUB.S f6,f1,f2,f3 = -2
            enc_r4(NMADD, 7, 0, 1, 2, 3),            # FNMADD.S f7,f1,f2,f3 = -4
            nop(),
            enc_r(OP_FP, 4, 0b000, 4, 0, 0b1110000),# FMV.X.W x4, f4
            enc_r(OP_FP, 5, 0b000, 5, 0, 0b1110000),# FMV.X.W x5, f5
            enc_r(OP_FP, 6, 0b000, 6, 0, 0b1110000),# FMV.X.W x6, f6
            enc_r(OP_FP, 7, 0b000, 7, 0, 0b1110000),# FMV.X.W x7, f7
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(words=16)


def _run_floating_fma_register_case(extensions):
    dut = _FloatingFmaRegisterBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(150):
            yield Tick()
        for reg in (4, 5, 6, 7):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        4: 0x40800000,
        5: 0x40000000,
        6: 0xC0000000,
        7: 0xC0800000,
    }


def test_floating_fma_family_uses_three_independent_fpr_sources():
    _run_floating_fma_register_case("RV32I+GC+F+ZICSR")
    _run_floating_fma_register_case("RV32I+GC+*")


class _FloatingWordMemoryRegisterBench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = [
            enc_u(LUI, 2, 0x3FC00),                    # x2 = +1.5f bits
            enc_r(OP_FP, 2, 0b000, 2, 0, 0b1111000), # FMV.W.X f2, x2
            nop(),
            enc_s_local(STORE_FP, 0b010, 0, 2, 0),    # FSW f2, 0(x0)
            nop(),
            enc_i(LOAD_FP, 3, 0b010, 0, 0),           # FLW f3, 0(x0)
            nop(), nop(), nop(), nop(),
            enc_r(OP_FP, 3, 0b000, 3, 0, 0b1110000), # FMV.X.W x3, f3
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(words=16)


def _run_floating_word_memory_register_case(extensions):
    dut = _FloatingWordMemoryRegisterBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(140):
            yield Tick()
        for reg in (2, 3):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[f"x{reg}"] = yield dut.core.dbg_reg_rdata
        yield dut.core.dbg_freg_addr.eq(3)
        yield Tick()
        results["f3"] = yield dut.core.dbg_freg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        "x2": 0x3FC00000,
        "x3": 0x3FC00000,
        "f3": 0xFFFFFFFF3FC00000,
    }


def test_floating_word_load_store_use_independent_register_file():
    _run_floating_word_memory_register_case("RV32I+GC+F+ZICSR")
    _run_floating_word_memory_register_case("RV32I+GC+*")


class _FloatingDoubleMemoryRv32Bench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = [
            enc_i(LOAD_FP, 1, 0b011, 0, 0),           # FLD f1, 0(x0)
            nop(), nop(), nop(), nop(),
            enc_s_local(STORE_FP, 0b011, 0, 1, 8),    # FSD f1, 8(x0)
            nop(), nop(), nop(), nop(),
            enc_i(LOAD, 2, 0b010, 0, 8),              # LW x2, 8(x0)
            enc_i(LOAD, 3, 0b010, 0, 12),             # LW x3, 12(x0)
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(words=16, init=[0x89ABCDEF, 0x01234567] + [0] * 14)


def _run_floating_double_memory_rv32_case(extensions):
    dut = _FloatingDoubleMemoryRv32Bench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(220):
            yield Tick()
        for reg in (1, 2, 3):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[f"x{reg}"] = yield dut.core.dbg_reg_rdata
        yield dut.core.dbg_freg_addr.eq(1)
        yield Tick()
        results["f1"] = yield dut.core.dbg_freg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        "x1": 0,
        "x2": 0x89ABCDEF,
        "x3": 0x01234567,
        "f1": 0x0123456789ABCDEF,
    }


def test_floating_double_load_store_execute_on_rv32():
    _run_floating_double_memory_rv32_case("RV32I+GC+D+ZICSR")
    _run_floating_double_memory_rv32_case("RV32I+GC+*")


class _FloatingDoubleSignInjectionRv32Bench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = [
            enc_i(LOAD_FP, 1, 0b011, 0, 0),           # FLD f1, 0(x0): +1.5
            enc_i(LOAD_FP, 2, 0b011, 0, 8),           # FLD f2, 8(x0): -0.0
            nop(), nop(), nop(), nop(),
            enc_r(OP_FP, 3, 0b000, 1, 2, 0b0010001), # FSGNJ.D f3, f1, f2
            enc_r(OP_FP, 4, 0b001, 1, 2, 0b0010001), # FSGNJN.D f4, f1, f2
            enc_r(OP_FP, 5, 0b010, 1, 2, 0b0010001), # FSGNJX.D f5, f1, f2
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(
            words=16,
            init=[0x00000000, 0x3FF80000, 0x00000000, 0x80000000] + [0] * 12,
        )


def _run_floating_double_sign_injection_rv32_case(extensions):
    dut = _FloatingDoubleSignInjectionRv32Bench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(180):
            yield Tick()
        for reg in (3, 4, 5):
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            results[reg] = yield dut.core.dbg_freg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        3: 0xBFF8000000000000,
        4: 0x3FF8000000000000,
        5: 0xBFF8000000000000,
    }


def test_floating_double_sign_injection_executes_on_rv32():
    _run_floating_double_sign_injection_rv32_case("RV32I+GC+D+ZICSR")
    _run_floating_double_sign_injection_rv32_case("RV32I+GC+*")


class _FloatingDoubleCompareClassRv32Bench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = [
            enc_i(LOAD_FP, 1, 0b011, 0, 0),           # qNaN
            nop(), nop(), nop(), nop(),
            enc_i(LOAD_FP, 2, 0b011, 0, 8),           # sNaN
            nop(), nop(), nop(), nop(),
            enc_i(LOAD_FP, 3, 0b011, 0, 16),          # negative subnormal
            nop(), nop(), nop(), nop(),
            enc_r(OP_FP, 5, 0b001, 1, 0, 0b1110001), # FCLASS.D x5, f1
            enc_r(OP_FP, 6, 0b001, 2, 0, 0b1110001), # FCLASS.D x6, f2
            enc_r(OP_FP, 7, 0b001, 3, 0, 0b1110001), # FCLASS.D x7, f3
            enc_r(OP_FP, 8, 0b010, 1, 1, 0b1010001), # FEQ.D x8, f1, f1
            enc_i(SYSTEM, 9, 0b010, 0, 0x001),
            enc_r(OP_FP, 10, 0b010, 2, 2, 0b1010001),# FEQ.D x10, f2, f2
            enc_i(SYSTEM, 11, 0b010, 0, 0x001),
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            enc_r(OP_FP, 12, 0b001, 1, 3, 0b1010001),# FLT.D x12, f1, f3
            enc_i(SYSTEM, 13, 0b010, 0, 0x001),
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            enc_r(OP_FP, 14, 0b000, 3, 3, 0b1010001),# FLE.D x14, f3, f3
            enc_i(SYSTEM, 15, 0b010, 0, 0x001),
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(
            words=16,
            init=[
                0x00000000, 0x7FF80000,
                0x00000001, 0x7FF00000,
                0x00000001, 0x80000000,
            ] + [0] * 10,
        )


def _run_floating_double_compare_class_rv32_case(extensions):
    dut = _FloatingDoubleCompareClassRv32Bench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(260):
            yield Tick()
        for reg in range(5, 16):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[reg] = yield dut.core.dbg_reg_rdata
        for reg in (1, 2, 3):
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            results[f"f{reg}"] = yield dut.core.dbg_freg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        5: 1 << 9,
        6: 1 << 8,
        7: 1 << 2,
        8: 0,
        9: 0,
        10: 0,
        11: 0b10000,
        12: 0,
        13: 0b10000,
        14: 1,
        15: 0,
        "f1": 0x7FF8000000000000,
        "f2": 0x7FF0000000000001,
        "f3": 0x8000000000000001,
    }


def test_floating_double_compare_and_classify_execute_on_rv32():
    _run_floating_double_compare_class_rv32_case("RV32I+GC+D+ZICSR")
    _run_floating_double_compare_class_rv32_case("RV32I+GC+*")


class _FloatingDoubleMinMaxRv32Bench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = []
        for reg, offset in enumerate(range(0, 32, 8), start=1):
            prog += [enc_i(LOAD_FP, reg, 0b011, 0, offset), nop(), nop(), nop(), nop()]
        prog += [
            enc_r(OP_FP, 5, 0b000, 0, 4, 0b0010001),  # FSGNJ.D +0,-2 -> -0
            nop(), nop(), nop(), nop(),
            enc_r(OP_FP, 10, 0b000, 1, 3, 0b0010101), # FMIN.D qNaN,+1.5 -> +1.5
            enc_r(OP_FP, 11, 0b001, 2, 3, 0b0010101), # FMAX.D sNaN,+1.5 -> +1.5, NV
            enc_i(SYSTEM, 5, 0b010, 0, 0x001),         # fflags -> NV
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),         # clear fflags
            enc_r(OP_FP, 12, 0b000, 1, 2, 0b0010101), # FMIN.D qNaN,sNaN -> canonical qNaN, NV
            enc_r(OP_FP, 13, 0b000, 0, 5, 0b0010101), # FMIN.D +0,-0 -> -0
            enc_r(OP_FP, 14, 0b001, 0, 5, 0b0010101), # FMAX.D +0,-0 -> +0
            enc_r(OP_FP, 15, 0b000, 3, 4, 0b0010101), # FMIN.D +1.5,-2 -> -2
            enc_r(OP_FP, 16, 0b001, 3, 4, 0b0010101), # FMAX.D +1.5,-2 -> +1.5
            enc_i(SYSTEM, 6, 0b010, 0, 0x001),         # fflags -> NV
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(
            words=16,
            init=[
                0x00000000, 0x7FF80000, # qNaN
                0x00000001, 0x7FF00000, # sNaN
                0x00000000, 0x3FF80000, # +1.5
                0x00000000, 0xC0000000, # -2.0
            ] + [0] * 8,
        )


def _run_floating_double_minmax_rv32_case(extensions):
    dut = _FloatingDoubleMinMaxRv32Bench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(220):
            yield Tick()
        for reg in (5, 6):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[reg] = yield dut.core.dbg_reg_rdata
        for reg in range(10, 17):
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            results[f"f{reg}"] = yield dut.core.dbg_freg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        5: 0b10000,
        6: 0b10000,
        "f10": 0x3FF8000000000000,
        "f11": 0x3FF8000000000000,
        "f12": 0x7FF8000000000000,
        "f13": 0x8000000000000000,
        "f14": 0x0000000000000000,
        "f15": 0xC000000000000000,
        "f16": 0x3FF8000000000000,
    }


def test_floating_double_minmax_executes_on_rv32():
    _run_floating_double_minmax_rv32_case("RV32I+GC+D+ZICSR")
    _run_floating_double_minmax_rv32_case("RV32I+GC+*")


class _FloatingDoubleConsecutiveLoadsRv32Bench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = [enc_i(LOAD_FP, reg, 0b011, 0, (reg - 1) * 8) for reg in range(1, 7)]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(
            words=16,
            init=[
                0x22222222, 0x11111111,
                0x44444444, 0x33333333,
                0x66666666, 0x55555555,
                0x88888888, 0x77777777,
                0xAAAAAAAA, 0x99999999,
                0xCCCCCCCC, 0xBBBBBBBB,
            ] + [0] * 4,
        )


def _run_floating_double_consecutive_loads_rv32_case(extensions):
    dut = _FloatingDoubleConsecutiveLoadsRv32Bench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(180):
            yield Tick()
        for reg in range(1, 7):
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            results[reg] = yield dut.core.dbg_freg_rdata
        results["pending"] = yield dut.core.dbg_pending_rd_mask
        results["stall"] = yield dut.core.dbg_stall

    sim.add_process(proc)
    sim.run()
    assert results == {
        1: 0x1111111122222222,
        2: 0x3333333344444444,
        3: 0x5555555566666666,
        4: 0x7777777788888888,
        5: 0x99999999AAAAAAAA,
        6: 0xBBBBBBBBCCCCCCCC,
        "pending": 0,
        "stall": 0,
    }


def test_floating_double_consecutive_loads_execute_on_rv32():
    _run_floating_double_consecutive_loads_rv32_case("RV32I+GC+D+ZICSR")
    _run_floating_double_consecutive_loads_rv32_case("RV32I+GC+*")


class _FloatingDoubleMultiplyRv32Bench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = [enc_i(LOAD_FP, reg, 0b011, 0, (reg - 1) * 8) for reg in range(1, 6)]
        prog += [nop(), nop(), nop(), nop()]
        prog += [
            enc_r(OP_FP, 10, 0b000, 1, 2, 0b0001001), # FMUL.D +1.5,-2 -> -3
            enc_r(OP_FP, 11, 0b000, 3, 1, 0b0001001), # FMUL.D qNaN,+1.5 -> qNaN
            enc_i(SYSTEM, 5, 0b010, 0, 0x001),         # fflags -> 0
            enc_r(OP_FP, 12, 0b000, 4, 1, 0b0001001), # FMUL.D sNaN,+1.5 -> qNaN, NV
            enc_i(SYSTEM, 6, 0b010, 0, 0x001),         # fflags -> NV
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),         # clear fflags
            enc_r(OP_FP, 13, 0b000, 0, 5, 0b0001001), # FMUL.D +0,+inf -> qNaN, NV
            enc_i(SYSTEM, 7, 0b010, 0, 0x001),         # fflags -> NV
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),         # clear fflags
            enc_r(OP_FP, 14, 0b000, 5, 2, 0b0001001), # FMUL.D +inf,-2 -> -inf
            enc_r(OP_FP, 15, 0b000, 2, 0, 0b0001001), # FMUL.D -2,+0 -> -0
            enc_i(SYSTEM, 8, 0b010, 0, 0x001),         # fflags -> 0
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(
            words=16,
            init=[
                0x00000000, 0x3FF80000, # +1.5
                0x00000000, 0xC0000000, # -2.0
                0x00000000, 0x7FF80000, # qNaN
                0x00000001, 0x7FF00000, # sNaN
                0x00000000, 0x7FF00000, # +infinity
            ] + [0] * 6,
        )


def _run_floating_double_multiply_rv32_case(extensions):
    dut = _FloatingDoubleMultiplyRv32Bench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(220):
            yield Tick()
        for reg in range(5, 9):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[reg] = yield dut.core.dbg_reg_rdata
        for reg in range(10, 16):
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            results[f"f{reg}"] = yield dut.core.dbg_freg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        5: 0,
        6: 0b10000,
        7: 0b10000,
        8: 0,
        "f10": 0xC008000000000000,
        "f11": 0x7FF8000000000000,
        "f12": 0x7FF8000000000000,
        "f13": 0x7FF8000000000000,
        "f14": 0xFFF0000000000000,
        "f15": 0x8000000000000000,
    }


def test_floating_double_multiply_executes_on_rv32():
    _run_floating_double_multiply_rv32_case("RV32I+GC+D+ZICSR")
    _run_floating_double_multiply_rv32_case("RV32I+GC+*")


class _FloatingDoubleDivideRv32Bench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = [enc_i(LOAD_FP, reg, 0b011, 0, (reg - 1) * 8) for reg in range(1, 6)]
        prog += [nop(), nop(), nop(), nop()]
        prog += [
            enc_r(OP_FP, 10, 0b000, 1, 2, 0b0001101), # FDIV.D +6,-2 -> -3
            enc_r(OP_FP, 11, 0b000, 3, 1, 0b0001101), # FDIV.D qNaN,+6 -> qNaN
            enc_i(SYSTEM, 5, 0b010, 0, 0x001),         # fflags -> 0
            enc_r(OP_FP, 12, 0b000, 4, 1, 0b0001101), # FDIV.D sNaN,+6 -> qNaN, NV
            enc_i(SYSTEM, 6, 0b010, 0, 0x001),         # fflags -> NV
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            enc_r(OP_FP, 13, 0b000, 1, 0, 0b0001101), # FDIV.D +6,+0 -> +inf, DZ
            enc_i(SYSTEM, 7, 0b010, 0, 0x001),
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            enc_r(OP_FP, 14, 0b000, 0, 0, 0b0001101), # FDIV.D +0,+0 -> qNaN, NV
            enc_i(SYSTEM, 8, 0b010, 0, 0x001),
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            enc_r(OP_FP, 15, 0b000, 5, 5, 0b0001101), # FDIV.D +inf,+inf -> qNaN, NV
            enc_i(SYSTEM, 9, 0b010, 0, 0x001),
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            enc_r(OP_FP, 16, 0b000, 0, 2, 0b0001101), # FDIV.D +0,-2 -> -0
            enc_r(OP_FP, 17, 0b000, 1, 5, 0b0001101), # FDIV.D +6,+inf -> +0
            enc_r(OP_FP, 18, 0b000, 5, 2, 0b0001101), # FDIV.D +inf,-2 -> -inf
            enc_i(SYSTEM, 19, 0b010, 0, 0x001),        # fflags -> 0
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(
            words=16,
            init=[
                0x00000000, 0x40180000, # +6.0
                0x00000000, 0xC0000000, # -2.0
                0x00000000, 0x7FF80000, # qNaN
                0x00000001, 0x7FF00000, # sNaN
                0x00000000, 0x7FF00000, # +infinity
            ] + [0] * 6,
        )


def _run_floating_double_divide_rv32_case(extensions):
    dut = _FloatingDoubleDivideRv32Bench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(240):
            yield Tick()
        for reg in (5, 6, 7, 8, 9, 19):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[reg] = yield dut.core.dbg_reg_rdata
        for reg in range(10, 19):
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            results[f"f{reg}"] = yield dut.core.dbg_freg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        5: 0,
        6: 0b10000,
        7: 0b01000,
        8: 0b10000,
        9: 0b10000,
        19: 0,
        "f10": 0xC008000000000000,
        "f11": 0x7FF8000000000000,
        "f12": 0x7FF8000000000000,
        "f13": 0x7FF0000000000000,
        "f14": 0x7FF8000000000000,
        "f15": 0x7FF8000000000000,
        "f16": 0x8000000000000000,
        "f17": 0x0000000000000000,
        "f18": 0xFFF0000000000000,
    }


def test_floating_double_divide_executes_on_rv32():
    _run_floating_double_divide_rv32_case("RV32I+GC+D+ZICSR")
    _run_floating_double_divide_rv32_case("RV32I+GC+*")


class _FloatingDoubleAddSubRv32Bench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = [enc_i(LOAD_FP, reg, 0b011, 0, (reg - 1) * 8) for reg in range(1, 8)]
        prog += [nop(), nop(), nop(), nop()]
        prog += [
            enc_r(OP_FP, 10, 0b000, 1, 2, 0b0000001), # FADD.D +1.5,+2.25 -> +3.75
            enc_r(OP_FP, 11, 0b000, 2, 1, 0b0000101), # FSUB.D +2.25,+1.5 -> +0.75
            enc_r(OP_FP, 12, 0b000, 1, 3, 0b0000001), # FADD.D +1.5,-1.5 -> +0
            enc_r(OP_FP, 13, 0b000, 1, 3, 0b0000101), # FSUB.D +1.5,-1.5 -> +3
            enc_r(OP_FP, 14, 0b000, 4, 1, 0b0000001), # FADD.D qNaN,+1.5 -> qNaN
            enc_i(SYSTEM, 5, 0b010, 0, 0x001),
            enc_r(OP_FP, 15, 0b000, 5, 1, 0b0000001), # FADD.D sNaN,+1.5 -> qNaN, NV
            enc_i(SYSTEM, 6, 0b010, 0, 0x001),
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            enc_r(OP_FP, 16, 0b000, 6, 7, 0b0000001), # FADD.D +inf,-inf -> qNaN, NV
            enc_i(SYSTEM, 7, 0b010, 0, 0x001),
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            enc_r(OP_FP, 17, 0b000, 6, 6, 0b0000101), # FSUB.D +inf,+inf -> qNaN, NV
            enc_i(SYSTEM, 8, 0b010, 0, 0x001),
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            enc_r(OP_FP, 18, 0b000, 6, 7, 0b0000101), # FSUB.D +inf,-inf -> +inf
            enc_i(SYSTEM, 9, 0b010, 0, 0x001),
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(
            words=16,
            init=[
                0x00000000, 0x3FF80000, # +1.5
                0x00000000, 0x40020000, # +2.25
                0x00000000, 0xBFF80000, # -1.5
                0x00000000, 0x7FF80000, # qNaN
                0x00000001, 0x7FF00000, # sNaN
                0x00000000, 0x7FF00000, # +infinity
                0x00000000, 0xFFF00000, # -infinity
            ] + [0] * 2,
        )


def _run_floating_double_addsub_rv32_case(extensions):
    dut = _FloatingDoubleAddSubRv32Bench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(260):
            yield Tick()
        for reg in range(5, 10):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[reg] = yield dut.core.dbg_reg_rdata
        for reg in range(10, 19):
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            results[f"f{reg}"] = yield dut.core.dbg_freg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        5: 0,
        6: 0b10000,
        7: 0b10000,
        8: 0b10000,
        9: 0,
        "f10": 0x400E000000000000,
        "f11": 0x3FE8000000000000,
        "f12": 0x0000000000000000,
        "f13": 0x4008000000000000,
        "f14": 0x7FF8000000000000,
        "f15": 0x7FF8000000000000,
        "f16": 0x7FF8000000000000,
        "f17": 0x7FF8000000000000,
        "f18": 0x7FF0000000000000,
    }


def test_floating_double_add_sub_execute_on_rv32():
    _run_floating_double_addsub_rv32_case("RV32I+GC+D+ZICSR")
    _run_floating_double_addsub_rv32_case("RV32I+GC+*")


class _FloatingDoubleFromWordRv32Bench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = [
            enc_i(OP_IMM, 2, 0b000, 0, -1),           # x2 = -1
            enc_u(LUI, 3, 0x80000),                   # x3 = INT32_MIN
            enc_u(LUI, 4, 0x80000),
            enc_i(OP_IMM, 4, 0b000, 4, -1),           # x4 = INT32_MAX
            enc_i(OP_IMM, 5, 0b000, 0, -1),           # x5 = UINT32_MAX
            nop(), nop(), nop(), nop(),
            enc_r(OP_FP, 10, 0b000, 0, 0, 0b1101001), # FCVT.D.W f10, x0
            enc_r(OP_FP, 11, 0b000, 2, 0, 0b1101001), # FCVT.D.W f11, x2
            enc_r(OP_FP, 12, 0b000, 3, 0, 0b1101001), # FCVT.D.W f12, x3
            enc_r(OP_FP, 13, 0b000, 4, 0, 0b1101001), # FCVT.D.W f13, x4
            enc_r(OP_FP, 14, 0b000, 5, 1, 0b1101001), # FCVT.D.WU f14, x5
            enc_r(OP_FP, 15, 0b000, 3, 1, 0b1101001), # FCVT.D.WU f15, x3
            enc_i(SYSTEM, 6, 0b010, 0, 0x001),         # exact conversions: no flags
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(words=16)


def _run_floating_double_from_word_rv32_case(extensions):
    dut = _FloatingDoubleFromWordRv32Bench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(180):
            yield Tick()
        yield dut.core.dbg_reg_addr.eq(6)
        yield Tick()
        results[6] = yield dut.core.dbg_reg_rdata
        for reg in range(10, 16):
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            results[f"f{reg}"] = yield dut.core.dbg_freg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        6: 0,
        "f10": 0x0000000000000000,
        "f11": 0xBFF0000000000000,
        "f12": 0xC1E0000000000000,
        "f13": 0x41DFFFFFFFC00000,
        "f14": 0x41EFFFFFFFE00000,
        "f15": 0x41E0000000000000,
    }


def test_floating_double_from_word_executes_on_rv32():
    _run_floating_double_from_word_rv32_case("RV32I+GC+D+ZICSR")
    _run_floating_double_from_word_rv32_case("RV32I+GC+*")


class _FloatingDoubleFromSingleRv32Bench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = [enc_i(LOAD_FP, reg, 0b010, 0, (reg - 1) * 4) for reg in range(1, 8)]
        prog += [nop(), nop(), nop(), nop()]
        prog += [
            enc_r(OP_FP, 10, 0b000, 1, 0, 0b0100001), # FCVT.D.S +1.5
            enc_r(OP_FP, 11, 0b000, 2, 0, 0b0100001), # FCVT.D.S -0
            enc_r(OP_FP, 12, 0b000, 3, 0, 0b0100001), # smallest subnormal
            enc_r(OP_FP, 13, 0b000, 4, 0, 0b0100001), # exact 2^-127
            enc_r(OP_FP, 14, 0b000, 5, 0, 0b0100001), # +infinity
            enc_r(OP_FP, 15, 0b000, 6, 0, 0b0100001), # qNaN
            enc_i(SYSTEM, 5, 0b010, 0, 0x001),         # qNaN does not raise NV
            enc_r(OP_FP, 16, 0b000, 7, 0, 0b0100001), # sNaN -> canonical qNaN, NV
            enc_i(SYSTEM, 6, 0b010, 0, 0x001),
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(
            words=16,
            init=[
                0x3FC00000, # +1.5
                0x80000000, # -0
                0x00000001, # smallest positive subnormal
                0x00400000, # 2^-127
                0x7F800000, # +infinity
                0x7FC00000, # qNaN
                0x7F800001, # sNaN
            ] + [0] * 9,
        )


def _run_floating_double_from_single_rv32_case(extensions):
    dut = _FloatingDoubleFromSingleRv32Bench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(220):
            yield Tick()
        for reg in (5, 6):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[reg] = yield dut.core.dbg_reg_rdata
        for reg in range(10, 17):
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            results[f"f{reg}"] = yield dut.core.dbg_freg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        5: 0,
        6: 0b10000,
        "f10": 0x3FF8000000000000,
        "f11": 0x8000000000000000,
        "f12": 0x36A0000000000000,
        "f13": 0x3800000000000000,
        "f14": 0x7FF0000000000000,
        "f15": 0x7FF8000000000000,
        "f16": 0x7FF8000000000000,
    }


def test_floating_double_from_single_executes_on_rv32():
    _run_floating_double_from_single_rv32_case("RV32I+GC+D+ZICSR")
    _run_floating_double_from_single_rv32_case("RV32I+GC+*")


class _FloatingWordFromDoubleRv32Bench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = [enc_i(LOAD_FP, reg, 0b011, 0, (reg - 1) * 8) for reg in range(1, 8)]
        prog += [nop(), nop(), nop(), nop()]
        prog += [
            enc_r(OP_FP, 10, 0b000, 1, 0, 0b1100001), # RNE +2.5 -> 2
            enc_r(OP_FP, 11, 0b000, 2, 0, 0b1100001), # RNE -2.5 -> -2
            enc_r(OP_FP, 12, 0b100, 1, 0, 0b1100001), # RMM +2.5 -> 3
            enc_r(OP_FP, 13, 0b100, 2, 0, 0b1100001), # RMM -2.5 -> -3
            enc_r(OP_FP, 14, 0b001, 1, 0, 0b1100001), # RTZ +2.5 -> 2
            enc_r(OP_FP, 15, 0b001, 2, 0, 0b1100001), # RTZ -2.5 -> -2
            enc_r(OP_FP, 16, 0b010, 1, 0, 0b1100001), # RDN +2.5 -> 2
            enc_r(OP_FP, 17, 0b010, 2, 0, 0b1100001), # RDN -2.5 -> -3
            enc_r(OP_FP, 18, 0b011, 1, 0, 0b1100001), # RUP +2.5 -> 3
            enc_r(OP_FP, 19, 0b011, 2, 0, 0b1100001), # RUP -2.5 -> -2
            enc_i(SYSTEM, 20, 0b010, 0, 0x001),        # NX
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            enc_r(OP_FP, 21, 0b001, 3, 0, 0b1100001), # qNaN -> INT_MAX, NV
            enc_r(OP_FP, 22, 0b001, 4, 0, 0b1100001), # +inf -> INT_MAX
            enc_r(OP_FP, 23, 0b001, 5, 0, 0b1100001), # -inf -> INT_MIN
            enc_r(OP_FP, 24, 0b001, 5, 1, 0b1100001), # -inf -> UINT_MIN
            enc_r(OP_FP, 25, 0b001, 6, 1, 0b1100001), # 2^32 -> UINT_MAX
            enc_i(SYSTEM, 26, 0b010, 0, 0x001),        # NV only
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            enc_r(OP_FP, 27, 0b011, 7, 1, 0b1100001), # RUP -0.5 -> 0 unsigned
            enc_i(SYSTEM, 28, 0b010, 0, 0x001),        # NX, not NV
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(
            words=16,
            init=[
                0x00000000, 0x40040000, # +2.5
                0x00000000, 0xC0040000, # -2.5
                0x00000000, 0x7FF80000, # qNaN
                0x00000000, 0x7FF00000, # +infinity
                0x00000000, 0xFFF00000, # -infinity
                0x00000000, 0x41F00000, # 2^32
                0x00000000, 0xBFE00000, # -0.5
            ] + [0] * 2,
        )


def _run_floating_word_from_double_rv32_case(extensions):
    dut = _FloatingWordFromDoubleRv32Bench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(280):
            yield Tick()
        for reg in range(10, 29):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        10: 2, 11: 0xfffffffe,
        12: 3, 13: 0xfffffffd,
        14: 2, 15: 0xfffffffe,
        16: 2, 17: 0xfffffffd,
        18: 3, 19: 0xfffffffe,
        20: 0b00001,
        21: 0x7fffffff,
        22: 0x7fffffff,
        23: 0x80000000,
        24: 0,
        25: 0xffffffff,
        26: 0b10000,
        27: 0,
        28: 0b00001,
    }


def test_floating_word_from_double_executes_on_rv32():
    _run_floating_word_from_double_rv32_case("RV32I+GC+D+ZICSR")
    _run_floating_word_from_double_rv32_case("RV32I+GC+*")


class _FloatingSingleFromDoubleRv32Bench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = [enc_i(LOAD_FP, reg, 0b011, 0, (reg - 1) * 8) for reg in range(1, 8)]
        prog += [nop(), nop(), nop(), nop()]
        prog += [
            enc_r(OP_FP, 10, 0b000, 1, 1, 0b0100000), # RNE tie -> +1.0f
            enc_r(OP_FP, 11, 0b100, 1, 1, 0b0100000), # RMM tie -> next +float
            enc_r(OP_FP, 12, 0b011, 2, 1, 0b0100000), # RUP negative tie -> -1.0f
            enc_r(OP_FP, 13, 0b010, 2, 1, 0b0100000), # RDN negative tie -> next -float
            nop(), nop(), nop(), nop(),
            enc_i(SYSTEM, 22, 0b010, 0, 0x001),        # NX
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            nop(),
            enc_r(OP_FP, 14, 0b000, 3, 1, 0b0100000), # exact minimum subnormal
            nop(), nop(), nop(), nop(),
            enc_i(SYSTEM, 23, 0b010, 0, 0x001),        # exact: no flags
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            nop(),
            enc_r(OP_FP, 15, 0b000, 4, 1, 0b0100000), # half min-sub RNE -> zero, UF|NX
            nop(), nop(), nop(), nop(),
            enc_i(SYSTEM, 24, 0b010, 0, 0x001),
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            nop(),
            enc_r(OP_FP, 16, 0b100, 4, 1, 0b0100000), # half min-sub RMM -> min-sub
            nop(), nop(), nop(), nop(),
            enc_i(SYSTEM, 25, 0b010, 0, 0x001),
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            nop(),
            enc_r(OP_FP, 17, 0b000, 5, 1, 0b0100000), # 2^128 RNE -> +inf, OF|NX
            enc_r(OP_FP, 18, 0b001, 5, 1, 0b0100000), # 2^128 RTZ -> max finite
            nop(), nop(), nop(), nop(),
            enc_i(SYSTEM, 26, 0b010, 0, 0x001),
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            nop(),
            enc_r(OP_FP, 19, 0b000, 6, 1, 0b0100000), # qNaN -> canonical
            nop(), nop(), nop(), nop(),
            enc_i(SYSTEM, 27, 0b010, 0, 0x001),
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            nop(),
            enc_r(OP_FP, 21, 0b000, 7, 1, 0b0100000), # sNaN -> canonical, NV
            nop(), nop(), nop(), nop(),
            enc_i(SYSTEM, 28, 0b010, 0, 0x001),
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(
            words=16,
            init=[
                0x10000000, 0x3FF00000, # +1 + 2^-24, halfway
                0x10000000, 0xBFF00000, # -1 - 2^-24, halfway
                0x00000000, 0x36A00000, # 2^-149, exact min single subnormal
                0x00000000, 0x36900000, # 2^-150, half min-sub
                0x00000000, 0x47F00000, # 2^128, finite single overflow
                0x00000000, 0x7FF80000, # qNaN
                0x00000001, 0x7FF00000, # sNaN
            ] + [0] * 2,
        )


def _run_floating_single_from_double_rv32_case(extensions):
    dut = _FloatingSingleFromDoubleRv32Bench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(300):
            yield Tick()
        for reg in range(22, 29):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[reg] = yield dut.core.dbg_reg_rdata
        for reg in range(10, 22):
            if reg in (20,):
                continue
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            results[f"f{reg}"] = yield dut.core.dbg_freg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        22: 0b00001,
        23: 0,
        24: 0b00011,
        25: 0b00011,
        26: 0b00101,
        27: 0,
        28: 0b10000,
        "f10": 0xffffffff3f800000,
        "f11": 0xffffffff3f800001,
        "f12": 0xffffffffbf800000,
        "f13": 0xffffffffbf800001,
        "f14": 0xffffffff00000001,
        "f15": 0xffffffff00000000,
        "f16": 0xffffffff00000001,
        "f17": 0xffffffff7f800000,
        "f18": 0xffffffff7f7fffff,
        "f19": 0xffffffff7fc00000,
        "f21": 0xffffffff7fc00000,
    }


def test_floating_single_from_double_executes_on_rv32():
    _run_floating_single_from_double_rv32_case("RV32I+GC+D+ZICSR")
    _run_floating_single_from_double_rv32_case("RV32I+GC+*")


class _FloatingDoubleSqrtRv32Bench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = [enc_i(LOAD_FP, reg, 0b011, 0, (reg - 1) * 8) for reg in range(1, 10)]
        prog += [nop(), nop(), nop(), nop()]
        prog += [
            enc_r(OP_FP, 10, 0b000, 1, 0, 0b0101101), # sqrt(4) = 2 exact
            enc_r(OP_FP, 11, 0b000, 2, 0, 0b0101101), # sqrt(2), RNE
            enc_r(OP_FP, 12, 0b010, 2, 0, 0b0101101), # sqrt(2), RDN
            nop(), nop(), nop(), nop(),
            enc_i(SYSTEM, 20, 0b010, 0, 0x001),       # NX
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            nop(),
            enc_r(OP_FP, 13, 0b000, 3, 0, 0b0101101), # sqrt(min-sub) = 2^-537
            enc_r(OP_FP, 14, 0b000, 4, 0, 0b0101101), # sqrt(9) = 3
            enc_r(OP_FP, 15, 0b000, 5, 0, 0b0101101), # sqrt(-0) = -0
            enc_r(OP_FP, 16, 0b000, 6, 0, 0b0101101), # sqrt(+inf) = +inf
            nop(), nop(), nop(), nop(),
            enc_i(SYSTEM, 25, 0b010, 0, 0x001),       # exact: no flags
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            nop(),
            enc_r(OP_FP, 17, 0b000, 7, 0, 0b0101101), # negative finite -> qNaN, NV
            nop(), nop(), nop(), nop(),
            enc_i(SYSTEM, 26, 0b010, 0, 0x001),
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            nop(),
            enc_r(OP_FP, 18, 0b000, 8, 0, 0b0101101), # qNaN -> qNaN, no flags
            nop(), nop(), nop(), nop(),
            enc_i(SYSTEM, 27, 0b010, 0, 0x001),
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            nop(),
            enc_r(OP_FP, 19, 0b000, 9, 0, 0b0101101), # sNaN -> qNaN, NV
            nop(), nop(), nop(), nop(),
            enc_i(SYSTEM, 28, 0b010, 0, 0x001),
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            nop(),
            enc_r(OP_FP, 21, 0b000, 2, 0, 0b0101101), # final isolated inexact check
            nop(), nop(), nop(), nop(),
            enc_i(SYSTEM, 20, 0b010, 0, 0x001),
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(
            words=32,
            init=[
                0x00000000, 0x40100000, # +4
                0x00000000, 0x40000000, # +2
                0x00000001, 0x00000000, # minimum subnormal
                0x00000000, 0x40220000, # +9
                0x00000000, 0x80000000, # -0
                0x00000000, 0x7ff00000, # +infinity
                0x00000000, 0xc0100000, # -4
                0x00000000, 0x7ff80000, # qNaN
                0x00000001, 0x7ff00000, # sNaN
            ] + [0] * 14,
        )


def _run_floating_double_sqrt_rv32_case(extensions):
    dut = _FloatingDoubleSqrtRv32Bench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(360):
            yield Tick()
        for reg in (20, 25, 26, 27, 28):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[reg] = yield dut.core.dbg_reg_rdata
        for reg in range(10, 20):
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            results[f"f{reg}"] = yield dut.core.dbg_freg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        20: 0b00001,
        25: 0,
        26: 0b10000,
        27: 0,
        28: 0b10000,
        "f10": 0x4000000000000000,
        "f11": 0x3ff6a09e667f3bcd,
        "f12": 0x3ff6a09e667f3bcc,
        "f13": 0x1e60000000000000,
        "f14": 0x4008000000000000,
        "f15": 0x8000000000000000,
        "f16": 0x7ff0000000000000,
        "f17": 0x7ff8000000000000,
        "f18": 0x7ff8000000000000,
        "f19": 0x7ff8000000000000,
    }


def test_floating_double_sqrt_executes_on_rv32():
    _run_floating_double_sqrt_rv32_case("RV32I+GC+D+ZICSR")
    _run_floating_double_sqrt_rv32_case("RV32I+GC+*")


class _FloatingSingleSqrtRv32Bench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = [enc_i(LOAD_FP, reg, 0b010, 0, (reg - 1) * 4) for reg in range(1, 10)]
        prog += [nop(), nop(), nop(), nop()]
        prog += [
            enc_r(OP_FP, 10, 0b000, 1, 0, 0b0101100), # sqrt(4) = 2 exact
            enc_r(OP_FP, 11, 0b000, 2, 0, 0b0101100), # sqrt(2), RNE
            enc_r(OP_FP, 12, 0b011, 2, 0, 0b0101100), # sqrt(2), RUP
            enc_r(OP_FP, 13, 0b000, 3, 0, 0b0101100), # sqrt(2^-148) = 2^-74
            enc_r(OP_FP, 14, 0b000, 4, 0, 0b0101100), # sqrt(9) = 3
            enc_r(OP_FP, 15, 0b000, 5, 0, 0b0101100), # sqrt(-0) = -0
            enc_r(OP_FP, 16, 0b000, 6, 0, 0b0101100), # sqrt(+inf) = +inf
            nop(), nop(), nop(), nop(),
            enc_i(SYSTEM, 25, 0b010, 0, 0x001),       # NX from sqrt(2)
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            nop(),
            enc_r(OP_FP, 17, 0b000, 7, 0, 0b0101100), # negative finite -> qNaN, NV
            nop(), nop(), nop(), nop(),
            enc_i(SYSTEM, 26, 0b010, 0, 0x001),
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            nop(),
            enc_r(OP_FP, 18, 0b000, 8, 0, 0b0101100), # qNaN -> qNaN, no flags
            nop(), nop(), nop(), nop(),
            enc_i(SYSTEM, 27, 0b010, 0, 0x001),
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            nop(),
            enc_r(OP_FP, 19, 0b000, 9, 0, 0b0101100), # sNaN -> qNaN, NV
            nop(), nop(), nop(), nop(),
            enc_i(SYSTEM, 28, 0b010, 0, 0x001),
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            nop(),
            enc_r(OP_FP, 21, 0b000, 2, 0, 0b0101100), # final isolated NX check
            nop(), nop(), nop(), nop(),
            enc_i(SYSTEM, 20, 0b010, 0, 0x001),
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(
            words=16,
            init=[
                0x40800000, # +4
                0x40000000, # +2
                0x00000002, # 2^-148, subnormal
                0x41100000, # +9
                0x80000000, # -0
                0x7f800000, # +infinity
                0xc0800000, # -4
                0x7fc00000, # qNaN
                0x7f800001, # sNaN
            ] + [0] * 7,
        )


def _run_floating_single_sqrt_rv32_case(extensions):
    dut = _FloatingSingleSqrtRv32Bench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        for _ in range(340):
            yield Tick()
        for reg in (20, 25, 26, 27, 28):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[reg] = yield dut.core.dbg_reg_rdata
        for reg in range(10, 20):
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            results[f"f{reg}"] = yield dut.core.dbg_freg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        20: 0b00001,
        25: 0b00001,
        26: 0b10000,
        27: 0,
        28: 0b10000,
        "f10": 0xffffffff40000000,
        "f11": 0xffffffff3fb504f3,
        "f12": 0xffffffff3fb504f4,
        "f13": 0xffffffff1a800000,
        "f14": 0xffffffff40400000,
        "f15": 0xffffffff80000000,
        "f16": 0xffffffff7f800000,
        "f17": 0xffffffff7fc00000,
        "f18": 0xffffffff7fc00000,
        "f19": 0xffffffff7fc00000,
    }


def test_floating_single_sqrt_executes_on_rv32():
    _run_floating_single_sqrt_rv32_case("RV32I+GC+F+ZICSR")
    _run_floating_single_sqrt_rv32_case("RV32I+GC+*")


class _FloatingIntegerScoreboardIsolationBench(_FloatingMultiplyFlagsBench):
    def __init__(self, extensions):
        prog = [
            nop(), nop(), nop(), nop(),
            enc_i(LOAD_FP, 5, 0b010, 0, 0),            # FLW f5 while x5 is pending
            nop(), nop(), nop(), nop(),
            enc_r(OP_FP, 10, 0b000, 5, 5, 0b0000000), # FADD.S f10,f5,f5
        ]
        prog += [nop()] * (256 - len(prog))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(words=16, init=[0x3fc00000] + [0] * 15)

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
            c.gc_rsp_data.eq(0), c.wb_enq_ready.eq(1), c.mv_cmd_ready.eq(0),
            c.mv_rsp_valid.eq(0), c.mv_rsp_tag.eq(0), c.mv_rsp_rd.eq(0),
            c.mv_rsp_data.eq(0),
        ]
        return m


def _run_floating_integer_scoreboard_isolation_case(extensions):
    dut = _FloatingIntegerScoreboardIsolationBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def proc():
        results["pending_seen"] = False
        results["flw_classified"] = False
        results["fadd_classified"] = False
        yield dut.core.dbg_freg_addr.eq(10)
        yield dut.core.rb_inj_rd.eq(5)
        yield dut.core.rb_inj_value.eq(0x12345678)
        yield dut.core.rb_inj_valid.eq(1)
        while not (yield dut.core.rb_inj_ready):
            yield Tick()
        yield Tick()
        for _ in range(180):
            yield Tick()
            pending = yield dut.core.dbg_pending_rd_mask
            if pending & (1 << 5):
                results["pending_seen"] = True
            if (yield dut.core.dbg_id1_valid):
                rd = yield dut.core.dbg_id1_rd
                uses_rs1 = yield dut.core.dbg_id1_uses_int_rs1
                uses_rs2 = yield dut.core.dbg_id1_uses_int_rs2
                writes_rd = yield dut.core.dbg_id1_writes_int_rd
                if rd == 5:
                    results["flw_classified"] = (uses_rs1 == 1 and uses_rs2 == 0 and writes_rd == 0)
                if rd == 10:
                    results["fadd_classified"] = (uses_rs1 == 0 and uses_rs2 == 0 and writes_rd == 0)
        yield dut.core.rb_inj_valid.eq(0)
        yield dut.core.dbg_freg_addr.eq(5)
        yield Tick()
        results["f5"] = yield dut.core.dbg_freg_rdata
        yield dut.core.dbg_freg_addr.eq(10)
        yield Tick()
        results["f10"] = yield dut.core.dbg_freg_rdata
        yield dut.core.dbg_reg_addr.eq(5)
        yield Tick()
        results["x5"] = yield dut.core.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    assert results == {
        "f5": 0xffffffff3fc00000,
        "f10": 0xffffffff40400000,
        "x5": 0,
        "pending_seen": True,
        "flw_classified": True,
        "fadd_classified": True,
    }


def test_floating_and_integer_scoreboards_are_isolated():
    _run_floating_integer_scoreboard_isolation_case("RV32I+GC+F+ZICSR")
    _run_floating_integer_scoreboard_isolation_case("RV32I+GC+*")
