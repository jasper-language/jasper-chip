"""Runtime smoke test for RV32I+GC+* on RV32/64."""

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.isa import AUIPC, BRANCH, JAL, JALR, LUI, LOAD, LOAD_FP, STORE_FP, STORE, OP, OP_32, OP_FP, OP_FP_32, OP_IMM, FENCE_I_IMM, ZICOND_F7, SYSTEM, AMO, MADD, MSUB, NMSUB, NMADD, enc_b, enc_fence, enc_i, enc_jal, enc_r, enc_u, enc_rw, enc_s


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


def enc_mul(rd, rs1, rs2):
    return enc_r(OP, rd, 0b000, rs1, rs2, 0b0000001)


def enc_div(rd, rs1, rs2):
    return enc_r(OP, rd, 0b100, rs1, rs2, 0b0000001)


def enc_divw(rd, rs1, rs2, funct3):
    return enc_rw(rd, funct3, rs1, rs2, 0b0000001)


def enc_amoswap(rd, rs1, rs2):
    return enc_r(AMO, rd, 0b010, rs1, rs2, 0b00001 << 2)


def enc_amo(rd, rs1, rs2, amofn, funct3=0b010):
    return enc_r(AMO, rd, funct3, rs1, rs2, amofn << 2)


def enc_amo_aqrl(rd, rs1, rs2, amofn, aqrl=0, funct3=0b010):
    return enc_r(AMO, rd, funct3, rs1, rs2, (amofn << 2) | aqrl)


class _Bench(Elaboratable):
    def __init__(self, extensions, xlen):
        # Word0 carries C.NOP (pc=0) and C.LI x6, 21 (pc=2).
        # Word1 carries C.ADDI x6, -5 (pc=4) and C.NOP (pc=6).
        # Word2 carries C.LUI x7, 1 (pc=8) and C.SLLI x7, 1 (pc=10).
        # Word3 carries C.LI x8, 24 (pc=12) and C.SRLI x8, 1 (pc=14).
        # Word4 carries C.LI x9, -16 (pc=16) and C.SRAI x9, 1 (pc=18).
        # Word5 carries C.LI x10, -9 (pc=20) and C.ANDI x10, 7 (pc=22).
        # Word6 carries C.LI x11, 30 (pc=24) and C.SUB x11, x10 (pc=26).
        # Word7 carries C.LI x12, 10 (pc=28) and C.XOR x12, x10 (pc=30).
        # Word8 carries C.LI x13, 8 (pc=32) and C.OR x13, x10 (pc=34).
        # Word9 carries C.LI x14, 11 (pc=36) and C.AND x14, x10 (pc=38).
        # Word10 carries C.LI x15, 4 (pc=40) and C.ADD x15, x10 (pc=42).
        # Word11 carries C.MV x16, x10 (pc=44) and C.NOP (pc=46).
        # Word12 carries C.ADDI16SP sp, 16 (pc=48) and C.NOP (pc=50).
        c_nop = 0x0001
        c_li_x6_21 = 0x4355
        c_addi_x6_m5 = 0x136d
        c_lui_x7_1 = 0x6385
        c_slli_x7_1 = 0x0386
        c_li_x8_24 = 0x4461
        c_srli_x8_1 = 0x8005
        c_li_x9_m16 = 0x54c1
        c_srai_x9_1 = 0x8485
        c_li_x10_m9 = 0x555d
        c_andi_x10_7 = 0x891d
        c_li_x11_30 = 0x45f9
        c_sub_x11_x10 = 0x8d89
        c_li_x12_10 = 0x4629
        c_xor_x12_x10 = 0x8e29
        c_li_x13_8 = 0x46a1
        c_or_x13_x10 = 0x9ec9
        c_li_x14_11 = 0x472d
        c_and_x14_x10 = 0x8f69
        c_li_x15_4 = 0x4791
        c_add_x15_x10 = 0x97aa
        c_mv_x16_x10 = 0x882a
        c_addi16sp_16 = 0x6141
        word0 = c_nop | (c_li_x6_21 << 16)
        word1 = c_addi_x6_m5 | (c_nop << 16)
        word2 = c_lui_x7_1 | (c_slli_x7_1 << 16)
        word3 = c_li_x8_24 | (c_srli_x8_1 << 16)
        word4 = c_li_x9_m16 | (c_srai_x9_1 << 16)
        word5 = c_li_x10_m9 | (c_andi_x10_7 << 16)
        word6 = c_li_x11_30 | (c_sub_x11_x10 << 16)
        word7 = c_li_x12_10 | (c_xor_x12_x10 << 16)
        word8 = c_li_x13_8 | (c_or_x13_x10 << 16)
        word9 = c_li_x14_11 | (c_and_x14_x10 << 16)
        word10 = c_li_x15_4 | (c_add_x15_x10 << 16)
        word11 = c_mv_x16_x10 | (c_nop << 16)
        word12 = c_addi16sp_16 | (c_nop << 16)

        prog = [
            word0,
            word1,
            word2,
            word3,
            word4,
            word5,
            word6,
            word7,
            word8,
            word9,
            word10,
            word11,
            word12,
            enc_i(OP_IMM, 1, 0b000, 0, 3),
            enc_i(OP_IMM, 18, 0b000, 0, 4),
            enc_mul(3, 1, 18),
            enc_i(OP_IMM, 5, 0b000, 0, 2),
            nop(),
        ]

        imem_words = 128
        prog = prog + [nop()] * (imem_words - len(prog))

        self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
        self.imem = SimpleIMem(words=imem_words, init=prog)
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


def _run_case(extensions, xlen, read_x2=False, read_x7=False, read_x8=False, read_x9=False, read_x10=False, read_x11=False, read_x12=False, read_x13=False, read_x14=False, read_x15=False, read_x16=False):
    dut = _Bench(extensions=extensions, xlen=xlen)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core

    def proc():
        for _ in range(220):
            yield Tick()

        yield c.dbg_reg_addr.eq(3)
        yield Tick()
        v3 = yield c.dbg_reg_rdata

        yield c.dbg_reg_addr.eq(5)
        yield Tick()
        v5 = yield c.dbg_reg_rdata

        yield c.dbg_reg_addr.eq(6)
        yield Tick()
        v6 = yield c.dbg_reg_rdata

        if read_x2:
            yield c.dbg_reg_addr.eq(2)
            yield Tick()
            results["v2"] = yield c.dbg_reg_rdata

        if read_x7:
            yield c.dbg_reg_addr.eq(7)
            yield Tick()
            results["v7"] = yield c.dbg_reg_rdata

        if read_x8:
            yield c.dbg_reg_addr.eq(8)
            yield Tick()
            results["v8"] = yield c.dbg_reg_rdata

        if read_x9:
            yield c.dbg_reg_addr.eq(9)
            yield Tick()
            results["v9"] = yield c.dbg_reg_rdata

        if read_x10:
            yield c.dbg_reg_addr.eq(10)
            yield Tick()
            results["v10"] = yield c.dbg_reg_rdata

        if read_x11:
            yield c.dbg_reg_addr.eq(11)
            yield Tick()
            results["v11"] = yield c.dbg_reg_rdata

        if read_x12:
            yield c.dbg_reg_addr.eq(12)
            yield Tick()
            results["v12"] = yield c.dbg_reg_rdata

        if read_x13:
            yield c.dbg_reg_addr.eq(13)
            yield Tick()
            results["v13"] = yield c.dbg_reg_rdata

        if read_x14:
            yield c.dbg_reg_addr.eq(14)
            yield Tick()
            results["v14"] = yield c.dbg_reg_rdata

        if read_x15:
            yield c.dbg_reg_addr.eq(15)
            yield Tick()
            results["v15"] = yield c.dbg_reg_rdata

        if read_x16:
            yield c.dbg_reg_addr.eq(16)
            yield Tick()
            results["v16"] = yield c.dbg_reg_rdata

        if isinstance(extensions, str):
            ext_iter = extensions.split('+')
        else:
            ext_iter = list(extensions)

        ext_set = {str(part).strip().upper() for part in ext_iter if str(part).strip()}
        if ('M' in ext_set) or ('*' in ext_set):
            assert v3 == 12
        results["v5"] = v5
        results["v6"] = v6

    results = {}
    sim.add_process(proc)
    sim.run()
    if read_x7 and read_x8 and read_x9 and read_x10 and read_x11 and read_x12 and read_x13 and read_x14 and read_x15 and read_x16:
        return results["v5"], results["v6"], results["v7"], results["v8"], results["v9"], results["v10"], results["v11"], results["v12"], results["v13"], results["v14"], results["v15"], results["v16"]
    if read_x2:
        return results["v5"], results["v6"], results["v2"]
    if read_x7 and read_x8 and read_x9 and read_x10 and read_x11 and read_x12 and read_x13 and read_x14 and read_x15:
        return results["v5"], results["v6"], results["v7"], results["v8"], results["v9"], results["v10"], results["v11"], results["v12"], results["v13"], results["v14"], results["v15"]
    if read_x7 and read_x8 and read_x9 and read_x10 and read_x11 and read_x12 and read_x13 and read_x14:
        return results["v5"], results["v6"], results["v7"], results["v8"], results["v9"], results["v10"], results["v11"], results["v12"], results["v13"], results["v14"]
    if read_x7 and read_x8 and read_x9 and read_x10 and read_x11 and read_x12 and read_x13:
        return results["v5"], results["v6"], results["v7"], results["v8"], results["v9"], results["v10"], results["v11"], results["v12"], results["v13"]
    if read_x7 and read_x8 and read_x9 and read_x10 and read_x11 and read_x12:
        return results["v5"], results["v6"], results["v7"], results["v8"], results["v9"], results["v10"], results["v11"], results["v12"]
    if read_x7 and read_x8 and read_x9 and read_x10 and read_x11:
        return results["v5"], results["v6"], results["v7"], results["v8"], results["v9"], results["v10"], results["v11"]
    if read_x7 and read_x8 and read_x9 and read_x10:
        return results["v5"], results["v6"], results["v7"], results["v8"], results["v9"], results["v10"]
    if read_x7 and read_x8 and read_x9:
        return results["v5"], results["v6"], results["v7"], results["v8"], results["v9"]
    if read_x7 and read_x8:
        return results["v5"], results["v6"], results["v7"], results["v8"]
    if read_x7:
        return results["v5"], results["v6"], results["v7"]
    if read_x8:
        return results["v5"], results["v6"], results["v8"]
    if read_x9:
        return results["v5"], results["v6"], results["v9"]
    if read_x10:
        return results["v5"], results["v6"], results["v10"]
    if read_x11:
        return results["v5"], results["v6"], results["v11"]
    if read_x12:
        return results["v5"], results["v6"], results["v12"]
    if read_x13:
        return results["v5"], results["v6"], results["v13"]
    if read_x14:
        return results["v5"], results["v6"], results["v14"]
    if read_x15:
        return results["v5"], results["v6"], results["v15"]
    if read_x16:
        return results["v5"], results["v6"], results["v16"]
    return results["v5"], results["v6"]


def _run_base_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 1),   # x1 = 1
        enc_i(OP_IMM, 2, 0b000, 0, 2),   # x2 = 2
        enc_i(OP_IMM, 4, 0b000, 0, 4),   # x4 = 4
        enc_r(OP, 3, 0b000, 1, 2, 0b0000000),  # x3 = x1 + x2 = 3
        enc_i(OP_IMM, 5, 0b000, 4, 18),  # x5 = 22
        enc_i(OP_IMM, 3, 0b000, 3, -3 & 0xFFF),  # x3 = 0
        enc_i(OP_IMM, 3, 0b000, 1, 5),  # x3 = 6
        nop(),
    ]

    imem_words = 128
    prog = prog + [nop()] * (imem_words - len(prog))

    class _BaseBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _BaseBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core

    results = {}

    def proc():
        for _ in range(180):
            yield Tick()

        yield c.dbg_reg_addr.eq(3)
        yield Tick()
        results["x3"] = yield c.dbg_reg_rdata

        yield c.dbg_reg_addr.eq(5)
        yield Tick()
        results["x5"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return results["x3"], results["x5"]


def _run_c_addi4spn_case(extensions, xlen=32):
    c_addi4spn_x8_sp_16 = 0x0800
    c_nop = 0x0001
    word0 = c_addi4spn_x8_sp_16 | (c_nop << 16)

    prog = [word0]
    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _CAddi4spnBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _CAddi4spnBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    results = {}

    def proc():
        for _ in range(80):
            yield Tick()
        yield c.dbg_reg_addr.eq(8)
        yield Tick()
        results["x8"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return results["x8"]


def _run_c_lw_case(extensions, xlen=32):
    c_addi4spn_x8_sp_16 = 0x0800
    c_lw_x9_0_x8 = 0x4004
    c_nop = 0x0001
    word0 = c_addi4spn_x8_sp_16 | (c_lw_x9_0_x8 << 16)

    prog = [word0]
    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))
    dmem_init = [0, 0, 0, 0, 0x13579BDF] + [0] * 11

    class _CLwBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
            self.dmem = SimpleDMem(words=16, init=dmem_init)

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

    dut = _CLwBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    results = {}

    def proc():
        for _ in range(100):
            yield Tick()
        yield c.dbg_reg_addr.eq(9)
        yield Tick()
        results["x9"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return results["x9"]


def _run_c_sw_case(extensions, xlen=32):
    c_addi4spn_x8_sp_16 = 0x0800
    c_sw_x9_0_x8 = 0xc004
    c_lw_x10_0_x8 = 0x4008
    c_nop = 0x0001
    word0 = enc_i(OP_IMM, 9, 0b000, 0, 21)
    word1 = c_addi4spn_x8_sp_16 | (c_nop << 16)
    word2 = c_nop | (c_nop << 16)
    word3 = c_sw_x9_0_x8 | (c_nop << 16)
    word4 = c_nop | (c_nop << 16)
    word5 = c_lw_x10_0_x8 | (c_nop << 16)

    prog = [word0, word1, word2, word3, word4, word5]
    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _CSwBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _CSwBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    results = {}

    def proc():
        for _ in range(150):
            yield Tick()
        yield c.dbg_reg_addr.eq(10)
        yield Tick()
        results["x10"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return results["x10"]


def _run_c_lwsp_case(extensions, xlen=32):
    c_lwsp_x5_0_sp = 0x4282
    c_nop = 0x0001
    word0 = c_lwsp_x5_0_sp | (c_nop << 16)

    prog = [word0]
    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))
    dmem_init = [0x2468ACE0] + [0] * 15

    class _CLwspBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
            self.dmem = SimpleDMem(words=16, init=dmem_init)

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

    dut = _CLwspBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    results = {}

    def proc():
        for _ in range(100):
            yield Tick()
        yield c.dbg_reg_addr.eq(5)
        yield Tick()
        results["x5"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return results["x5"]


def _run_c_swsp_case(extensions, xlen=32):
    c_li_x5_21 = 0x42d5
    c_swsp_x5_0_sp = 0xc016
    c_lwsp_x6_0_sp = 0x4302
    c_nop = 0x0001
    word0 = c_li_x5_21 | (c_nop << 16)
    word1 = c_nop | (c_nop << 16)
    word2 = c_swsp_x5_0_sp | (c_nop << 16)
    word3 = c_nop | (c_nop << 16)
    word4 = c_lwsp_x6_0_sp | (c_nop << 16)

    prog = [word0, word1, word2, word3, word4]
    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _CSwspBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _CSwspBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    results = {}

    def proc():
        for _ in range(130):
            yield Tick()
        yield c.dbg_reg_addr.eq(6)
        yield Tick()
        results["x6"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return results["x6"]


def _run_c_ebreak_case(extensions, xlen=32):
    c_ebreak = 0x9002
    c_nop = 0x0001
    word0 = c_ebreak | (c_nop << 16)

    prog = [word0]
    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _CEbreakBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _CEbreakBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {"trap_seen": False}

    def proc():
        for _ in range(80):
            if (yield c.trap):
                result["trap_seen"] = True
            yield Tick()

    sim.add_process(proc)
    sim.run()
    return result["trap_seen"]


def _run_c_j_case(extensions, xlen=32):
    c_j_plus_4 = 0xa201
    c_ebreak = 0x9002
    c_li_x5_9 = 0x42a5
    c_nop = 0x0001
    word0 = c_j_plus_4 | (c_ebreak << 16)
    word1 = c_li_x5_9 | (c_nop << 16)

    prog = [word0, word1]
    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _CJBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _CJBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    results = {"trap_seen": False}

    def proc():
        for _ in range(120):
            if (yield c.trap):
                results["trap_seen"] = True
            yield Tick()

        yield c.dbg_reg_addr.eq(5)
        yield Tick()
        results["x5"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return results["x5"], results["trap_seen"]


def _run_c_jal_case(extensions, xlen=32):
    c_jal_plus_4 = 0x2201
    c_ebreak = 0x9002
    c_li_x5_9 = 0x42a5
    c_nop = 0x0001
    word0 = c_jal_plus_4 | (c_ebreak << 16)
    word1 = c_li_x5_9 | (c_nop << 16)

    prog = [word0, word1]
    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _CJalBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _CJalBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    results = {"trap_seen": False}

    def proc():
        for _ in range(44):
            if (yield c.trap):
                results["trap_seen"] = True
            yield Tick()

        yield c.dbg_reg_addr.eq(1)
        yield Tick()
        results["x1"] = yield c.dbg_reg_rdata
        yield c.dbg_reg_addr.eq(5)
        yield Tick()
        results["x5"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return results["x1"], results["x5"], results["trap_seen"]


def _run_c_jr_case(extensions, xlen=32):
    c_li_x5_6 = 0x4299
    c_jr_x5 = 0x8282
    c_ebreak = 0x9002
    c_li_x6_9 = 0x4325
    c_nop = 0x0001
    word0 = c_li_x5_6 | (c_jr_x5 << 16)
    word1 = c_ebreak | (c_li_x6_9 << 16)
    word2 = c_nop | (c_nop << 16)

    prog = [word0, word1, word2]
    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _CJrBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _CJrBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    results = {"trap_seen": False}

    def proc():
        for _ in range(72):
            if (yield c.trap):
                results["trap_seen"] = True
            yield Tick()

        yield c.dbg_reg_addr.eq(6)
        yield Tick()
        results["x6"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return results["x6"], results["trap_seen"]


def _run_c_jalr_case(extensions, xlen=32):
    c_jalr_x5 = 0x9282
    c_ebreak = 0x9002
    c_li_x6_9 = 0x4325
    c_nop = 0x0001
    word0 = enc_i(OP_IMM, 5, 0b000, 0, 32)
    word1 = c_nop | (c_nop << 16)
    word2 = c_nop | (c_nop << 16)
    word3 = c_nop | (c_nop << 16)
    word4 = c_nop | (c_nop << 16)
    word5 = c_jalr_x5 | (c_ebreak << 16)
    word6 = c_nop | (c_nop << 16)
    word7 = c_nop | (c_nop << 16)
    word8 = c_li_x6_9 | (c_nop << 16)

    prog = [word0, word1, word2, word3, word4, word5, word6, word7, word8]
    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _CJalrBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _CJalrBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    results = {"trap_seen": False}

    def proc():
        for _ in range(44):
            if (yield c.trap):
                results["trap_seen"] = True
            yield Tick()

        yield c.dbg_reg_addr.eq(1)
        yield Tick()
        results["x1"] = yield c.dbg_reg_rdata

        yield c.dbg_reg_addr.eq(6)
        yield Tick()
        results["x6"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return results["x1"], results["x6"], results["trap_seen"]


def _run_c_bnez_case(extensions, xlen=32):
    c_li_x8_1 = 0x4405
    c_bnez_x8_plus_4 = 0xe401
    c_ebreak = 0x9002
    c_li_x5_9 = 0x42a5
    c_nop = 0x0001
    word0 = c_li_x8_1 | (c_bnez_x8_plus_4 << 16)
    word1 = c_ebreak | (c_li_x5_9 << 16)

    prog = [word0, word1]
    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _CBnezBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _CBnezBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    results = {"trap_seen": False}

    def proc():
        for _ in range(120):
            if (yield c.trap):
                results["trap_seen"] = True
            yield Tick()

        yield c.dbg_reg_addr.eq(5)
        yield Tick()
        results["x5"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return results["x5"], results["trap_seen"]


def _run_c_beqz_case(extensions, xlen=32):
    c_beqz_x8_plus_4 = 0xc401
    c_ebreak = 0x9002
    c_li_x5_9 = 0x42a5
    c_nop = 0x0001
    word0 = c_beqz_x8_plus_4 | (c_ebreak << 16)
    word1 = c_li_x5_9 | (c_nop << 16)

    prog = [word0, word1]
    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _CBeqzBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _CBeqzBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    results = {"trap_seen": False}

    def proc():
        for _ in range(120):
            if (yield c.trap):
                results["trap_seen"] = True
            yield Tick()

        yield c.dbg_reg_addr.eq(5)
        yield Tick()
        results["x5"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return results["x5"], results["trap_seen"]


def _run_m_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 6),            # x1 = 6
        enc_i(OP_IMM, 2, 0b000, 0, -2 & 0xFFF),   # x2 = -2
        enc_mul(3, 1, 2),                         # x3 = -12
        enc_i(OP_IMM, 4, 0b000, 0, 4),            # x4 = 4
        enc_div(5, 1, 4),                         # x5 = 1
        nop(),
    ]
    imem_words = 128
    prog = prog + [nop()] * (imem_words - len(prog))

    class _MCaseBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _MCaseBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    results = {}

    def proc():
        for _ in range(180):
            yield Tick()
        yield c.dbg_reg_addr.eq(3)
        yield Tick()
        results["x3"] = yield c.dbg_reg_rdata
        yield c.dbg_reg_addr.eq(5)
        yield Tick()
        results["x5"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return results["x3"], results["x5"]


def _run_rv32m_standard_matrix_case(extensions):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, -16 & 0xFFF),  # x1 = -16 / 0xfffffff0
        enc_i(OP_IMM, 2, 0b000, 0, 7),            # x2 = 7
        enc_r(OP, 3, 0b000, 1, 2, 0b0000001),     # MUL
        enc_r(OP, 4, 0b001, 1, 2, 0b0000001),     # MULH
        enc_r(OP, 5, 0b010, 1, 2, 0b0000001),     # MULHSU
        enc_r(OP, 6, 0b011, 1, 2, 0b0000001),     # MULHU
        enc_r(OP, 7, 0b100, 1, 2, 0b0000001),     # DIV
        enc_r(OP, 8, 0b101, 1, 2, 0b0000001),     # DIVU
        enc_r(OP, 9, 0b110, 1, 2, 0b0000001),     # REM
        enc_r(OP, 10, 0b111, 1, 2, 0b0000001),    # REMU
        enc_r(OP, 11, 0b100, 1, 0, 0b0000001),    # DIV by zero
        enc_r(OP, 12, 0b101, 1, 0, 0b0000001),    # DIVU by zero
        enc_r(OP, 13, 0b110, 1, 0, 0b0000001),    # REM by zero
        enc_r(OP, 14, 0b111, 1, 0, 0b0000001),    # REMU by zero
        nop(),
    ]
    imem_words = 256
    prog = prog + [nop()] * (imem_words - len(prog))

    class _RV32MMatrixBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _RV32MMatrixBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    results = {}

    def proc():
        for _ in range(260):
            yield Tick()
        for reg in range(3, 15):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            results[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return results


def _run_mw_case(extensions, xlen=64):
    prog = [
        enc_u(LUI, 1, 0x12345),                    # x1 = 0x12345_000
        enc_i(OP_IMM, 1, 0b000, 1, 0x678),        # x1 = 0x12345678
        enc_i(OP_IMM, 2, 0b000, 0, 0x00000002),   # x2 = 2
        enc_i(OP_IMM, 4, 0b000, 0, 0x11111111),   # x4 sentinel
        enc_i(OP_IMM, 5, 0b000, 0, 0x22222222),   # x5 sentinel
        enc_i(OP_IMM, 6, 0b000, 0, 0x33333333),   # x6 sentinel
        enc_divw(4, 1, 2, 0b100),                  # DIVW x4, x1, x2
        enc_divw(5, 1, 2, 0b110),                  # REMW x5, x1, x2
        enc_r(OP_32, 6, 0b000, 1, 2, 0b0000001),  # MULW x6, x1, x2
        nop(),
    ]

    imem_words = 512
    prog = prog + [nop()] * (imem_words - len(prog))

    class _MWordBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _MWordBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(180):
            yield Tick()
        yield c.dbg_reg_addr.eq(4)
        yield Tick()
        result["x4"] = yield c.dbg_reg_rdata
        yield c.dbg_reg_addr.eq(5)
        yield Tick()
        result["x5"] = yield c.dbg_reg_rdata
        yield c.dbg_reg_addr.eq(6)
        yield Tick()
        result["x6"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x4"], result["x5"], result["x6"]


def _run_mw_edge_case(extensions, xlen=64):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 10),      # x1 = 10
        enc_i(OP_IMM, 2, 0b000, 0, 0),       # x2 = 0
        enc_divw(4, 1, 2, 0b100),            # DIVW x4, x1, 0
        enc_divw(5, 1, 2, 0b110),            # REMW x5, x1, 0
        enc_divw(6, 0, 0, 0b101),            # DIVUW x6, x0, x0 (x0 always 0)
        enc_i(OP_IMM, 1, 0b000, 0, -1 & 0xfff),
        enc_i(OP_IMM, 2, 0b000, 0, -1 & 0xfff),
        enc_divw(3, 1, 2, 0b100),            # DIVW x3, -1, -1
    ]

    imem_words = 512
    prog = prog + [nop()] * (imem_words - len(prog))

    class _MWordEdgeBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _MWordEdgeBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(200):
            yield Tick()
        for reg in (3, 4, 5, 6):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"], result["x6"]


def _run_zicsr_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 3, 0b000, 0, 0x123),   # x3 = 0x123
        enc_i(SYSTEM, 3, 0b001, 2, 0x300),    # csrrw x3, mstatus, x2
        nop(),
    ]

    imem_words = 512
    prog = prog + [nop()] * (imem_words - len(prog))

    class _ZicsrBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _ZicsrBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core

    result = {}

    def proc():
        for _ in range(180):
            yield Tick()
        yield c.dbg_reg_addr.eq(3)
        yield Tick()
        result["x3"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"]


def _run_zicsr_full_case(extensions, xlen):
    prog = [
        enc_i(SYSTEM, 0, 0b101, 0, 0x300),    # csrrwi x0, mstatus, 0
        enc_i(OP_IMM, 2, 0b000, 0, 5),        # x2 = 5
        enc_i(SYSTEM, 3, 0b001, 2, 0x300),    # csrrw  x3, mstatus, x2
        enc_i(SYSTEM, 4, 0b010, 2, 0x300),    # csrrs  x4, mstatus, x2
        enc_i(SYSTEM, 5, 0b011, 2, 0x300),    # csrrc  x5, mstatus, x2
        enc_i(SYSTEM, 6, 0b101, 1, 0x300),    # csrrwi x6, mstatus, 1
        enc_i(SYSTEM, 7, 0b110, 2, 0x300),    # csrrsi x7, mstatus, 2
        enc_i(SYSTEM, 8, 0b111, 1, 0x300),    # csrrci x8, mstatus, 1
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _ZicsrFullBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _ZicsrFullBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(220):
            yield Tick()
        for reg in (3, 4, 5, 6, 7, 8):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return tuple(result[f"x{reg}"] for reg in (3, 4, 5, 6, 7, 8))


def test_rv32i_standard_zicsr_all_csr_read_write_forms_execute_mstatus_state():
    expected = (0, 5, 5, 0, 1, 3)
    assert _run_zicsr_full_case("RV32I+GC+ZICSR", 32) == expected
    assert _run_zicsr_full_case("RV32I+GC+*", 32) == expected


def test_star_extensions_work_on_rv32_and_rv64():
    v5, v6 = _run_case("RV32I+GC+*", 32)
    assert v5 == 2
    assert v6 == 21

    v5_64, v6_64 = _run_case("RV64I+GC+*", 64)
    assert v5_64 == 2
    assert v6_64 == 21


def test_star_extensions_include_compressed_vs_rv32i_gc_only():
    _, v6_with_star = _run_case("RV32I+GC+*", 32)
    _, v6_without_star = _run_case("RV32I+GC", 32)
    assert v6_with_star == 21
    assert v6_without_star == 0


def test_star_extensions_include_standard_set_across_xlen_aliases():
    _, v6_rv32_star = _run_case("RV32I+GC+*", 32)
    _, v6_rv64_star = _run_case("RV64I+GC+*", 64)
    assert v6_rv32_star == 16
    assert v6_rv64_star == 16


def test_rv32c_standard_c_nop_c_li_and_c_addi_expand_and_execute():
    v5_base, v6_base = _run_case("RV32I+GC+C", 32)
    v5_star, v6_star = _run_case("RV32I+GC+*", 32)

    assert v5_base == 2
    assert v6_base == 16
    assert (v5_star, v6_star) == (v5_base, v6_base)


def test_rv32c_standard_c_addi4spn_expands_and_executes():
    x8_base = _run_c_addi4spn_case("RV32I+GC", 32)
    x8_star = _run_c_addi4spn_case("RV32I+GC+*", 32)

    assert x8_base == 16
    assert x8_star == x8_base


def test_rv32c_standard_c_lw_expands_and_executes():
    x9_base = _run_c_lw_case("RV32I+GC", 32)
    x9_star = _run_c_lw_case("RV32I+GC+*", 32)

    assert x9_base == 0x13579BDF
    assert x9_star == x9_base


def test_rv32c_standard_c_sw_expands_and_executes():
    x10_base = _run_c_sw_case("RV32I+GC", 32)
    x10_star = _run_c_sw_case("RV32I+GC+*", 32)

    assert x10_base == 21
    assert x10_star == x10_base


def test_rv32c_standard_c_lwsp_expands_and_executes():
    x5_base = _run_c_lwsp_case("RV32I+GC", 32)
    x5_star = _run_c_lwsp_case("RV32I+GC+*", 32)

    assert x5_base == 0x2468ACE0
    assert x5_star == x5_base


def test_rv32c_standard_c_swsp_expands_and_executes():
    x6_base = _run_c_swsp_case("RV32I+GC", 32)
    x6_star = _run_c_swsp_case("RV32I+GC+*", 32)

    assert x6_base == 21
    assert x6_star == x6_base


def test_rv32c_standard_c_ebreak_expands_and_traps():
    trap_base = _run_c_ebreak_case("RV32I+GC", 32)
    trap_star = _run_c_ebreak_case("RV32I+GC+*", 32)

    assert trap_base
    assert trap_star


def test_rv32c_standard_c_j_expands_and_executes():
    x5_base, trap_base = _run_c_j_case("RV32I+GC", 32)
    x5_star, trap_star = _run_c_j_case("RV32I+GC+*", 32)

    assert x5_base == 9
    assert x5_star == x5_base
    assert not trap_base
    assert not trap_star


def test_rv32c_standard_c_jal_expands_and_executes():
    x1_base, x5_base, trap_base = _run_c_jal_case("RV32I+GC", 32)
    x1_star, x5_star, trap_star = _run_c_jal_case("RV32I+GC+*", 32)

    assert x1_base == 2
    assert x5_base == 9
    assert (x1_star, x5_star) == (x1_base, x5_base)
    assert not trap_base
    assert not trap_star


def test_rv32c_standard_c_jr_expands_and_executes():
    x6_base, trap_base = _run_c_jr_case("RV32I+GC", 32)
    x6_star, trap_star = _run_c_jr_case("RV32I+GC+*", 32)

    assert x6_base == 9
    assert x6_star == x6_base
    assert not trap_base
    assert not trap_star


def test_rv32c_standard_c_jalr_expands_and_executes():
    x1_base, x6_base, trap_base = _run_c_jalr_case("RV32I+GC", 32)
    x1_star, x6_star, trap_star = _run_c_jalr_case("RV32I+GC+*", 32)

    assert x1_base == 22
    assert x6_base == 9
    assert (x1_star, x6_star) == (x1_base, x6_base)
    assert not trap_base
    assert not trap_star


def test_rv32c_standard_c_bnez_expands_and_executes():
    x5_base, trap_base = _run_c_bnez_case("RV32I+GC", 32)
    x5_star, trap_star = _run_c_bnez_case("RV32I+GC+*", 32)

    assert x5_base == 9
    assert x5_star == x5_base
    assert not trap_base
    assert not trap_star


def test_rv32c_standard_c_beqz_expands_and_executes():
    x5_base, trap_base = _run_c_beqz_case("RV32I+GC", 32)
    x5_star, trap_star = _run_c_beqz_case("RV32I+GC+*", 32)

    assert x5_base == 9
    assert x5_star == x5_base
    assert not trap_base
    assert not trap_star


def test_rv32c_standard_c_lui_and_c_slli_expand_and_execute():
    _, _, v7_base = _run_case("RV32I+GC", 32, read_x7=True)
    _, _, v7_star = _run_case("RV32I+GC+*", 32, read_x7=True)

    assert v7_base == 0x2000
    assert v7_star == v7_base


def test_rv32c_standard_c_srli_expands_and_executes():
    _, _, v8_base = _run_case("RV32I+GC", 32, read_x8=True)
    _, _, v8_star = _run_case("RV32I+GC+*", 32, read_x8=True)

    assert v8_base == 12
    assert v8_star == v8_base


def test_rv32c_standard_c_srai_expands_and_executes():
    _, _, v9_base = _run_case("RV32I+GC", 32, read_x9=True)
    _, _, v9_star = _run_case("RV32I+GC+*", 32, read_x9=True)

    assert v9_base == 0xFFFFFFF8
    assert v9_star == v9_base


def test_rv32c_standard_c_andi_expands_and_executes():
    _, _, v10_base = _run_case("RV32I+GC", 32, read_x10=True)
    _, _, v10_star = _run_case("RV32I+GC+*", 32, read_x10=True)

    assert v10_base == 7
    assert v10_star == v10_base


def test_rv32c_standard_c_sub_expands_and_executes():
    _, _, v11_base = _run_case("RV32I+GC", 32, read_x11=True)
    _, _, v11_star = _run_case("RV32I+GC+*", 32, read_x11=True)

    assert v11_base == 23
    assert v11_star == v11_base


def test_rv32c_standard_c_xor_expands_and_executes():
    _, _, v12_base = _run_case("RV32I+GC", 32, read_x12=True)
    _, _, v12_star = _run_case("RV32I+GC+*", 32, read_x12=True)

    assert v12_base == 13
    assert v12_star == v12_base


def test_rv32c_standard_c_or_expands_and_executes():
    _, _, v13_base = _run_case("RV32I+GC", 32, read_x13=True)
    _, _, v13_star = _run_case("RV32I+GC+*", 32, read_x13=True)

    assert v13_base == 15
    assert v13_star == v13_base


def test_rv32c_standard_c_and_expands_and_executes():
    _, _, v14_base = _run_case("RV32I+GC", 32, read_x14=True)
    _, _, v14_star = _run_case("RV32I+GC+*", 32, read_x14=True)

    assert v14_base == 3
    assert v14_star == v14_base


def test_rv32c_standard_c_add_expands_and_executes():
    _, _, v15_base = _run_case("RV32I+GC", 32, read_x15=True)
    _, _, v15_star = _run_case("RV32I+GC+*", 32, read_x15=True)

    assert v15_base == 11
    assert v15_star == v15_base


def test_rv32c_standard_c_mv_expands_and_executes():
    _, _, v16_base = _run_case("RV32I+GC", 32, read_x16=True)
    _, _, v16_star = _run_case("RV32I+GC+*", 32, read_x16=True)

    assert v16_base == 7
    assert v16_star == v16_base


def test_rv32c_standard_c_addi16sp_expands_and_executes():
    _, _, v2_base = _run_case("RV32I+GC", 32, read_x2=True)
    _, _, v2_star = _run_case("RV32I+GC+*", 32, read_x2=True)

    assert v2_base == 32
    assert v2_star == v2_base


def test_star_and_base_noisy_parser_aliasing_matches_for_rv32i_gc():
    noisy_32 = "  rv32i + gc + ??? + M + m + A + a + B + b + C + F + f + D + d + ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + "
    noisy_64 = "  rv64i + gc + ??? + M + m + A + a + B + b + C + F + f + D + d + ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + "

    assert _run_base_case("RV32I+GC", 32) == _run_base_case(noisy_32, 32)
    assert _run_base_case("RV64I+GC", 64) == _run_base_case(noisy_64, 64)


def test_extension_spec_iterable_input_matches_string_normalization_for_standard_sets():
    iterable_32 = ["rv32i", "gc", "m", "a", "zba", "zifencei", "zicsr", "zicond", "b", "*", "unknown.ext"]
    iterable_64 = ["rv64i", "gc", "m", "a", "zbs", "zifencei", "zicsr", "zicond", "b", "*", "junk"]

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(iterable_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(iterable_64, 64)


def test_baseline_rv32i_gc_and_rv64i_gc_execute_stable():
    v3, v5 = _run_base_case("RV32I+GC", 32)
    assert v3 == 6
    assert v5 == 22

    v3_64, v5_64 = _run_base_case("RV64I+GC", 64)
    assert v3_64 == 6
    assert v5_64 == 22


def test_explicit_m_extension_executes_on_rv32_and_rv64():
    v3, v5 = _run_m_case("RV32I+GC+M", 32)
    assert v3 == 0xFFFFFFF4 & 0xFFFFFFFF
    assert v5 == 1

    v3_64, v5_64 = _run_m_case("RV64I+GC+M", 64)
    assert v3_64 == -12 & ((1 << 64) - 1)
    assert v5_64 == 1


def test_rv32m_standard_all_multiply_divide_remainder_forms_execute():
    expected = {
        "x3": 0xFFFFFF90,  # MUL low half of -16 * 7
        "x4": 0xFFFFFFFF,  # MULH signed high half
        "x5": 0xFFFFFFFF,  # MULHSU signed/unsigned high half
        "x6": 0x00000006,  # MULHU unsigned high half
        "x7": 0xFFFFFFFE,  # DIV truncates -16 / 7 toward zero
        "x8": 0x24924922,  # DIVU 0xfffffff0 / 7
        "x9": 0xFFFFFFFE,  # REM keeps dividend sign: -16 % 7 -> -2
        "x10": 0x00000002, # REMU 0xfffffff0 % 7
        "x11": 0xFFFFFFFF, # DIV by zero
        "x12": 0xFFFFFFFF, # DIVU by zero
        "x13": 0xFFFFFFF0, # REM by zero returns dividend
        "x14": 0xFFFFFFF0, # REMU by zero returns dividend
    }
    assert _run_rv32m_standard_matrix_case("RV32I+GC+M") == expected
    assert _run_rv32m_standard_matrix_case("RV32I+GC+*") == expected


def test_explicit_a_extension_executes_amoswap_on_rv32_and_rv64():
    assert _run_amo_star_case("RV32I+GC+A", 32) == 1
    assert _run_amo_star_case("RV64I+GC+A", 64) == 1


def test_rv32a_standard_all_lr_sc_and_amo_word_forms_execute_with_aq_rl():
    amo_cases = [
        (0b00001, 0b00, 3, 5, (5, 3)),      # AMOSWAP.W
        (0b00000, 0b01, 3, 5, (5, 8)),      # AMOADD.W rl
        (0b00100, 0b10, 3, 5, (5, 6)),      # AMOXOR.W aq
        (0b01100, 0b11, 3, 5, (5, 1)),      # AMOAND.W aq+rl
        (0b01000, 0b00, 3, 5, (5, 7)),      # AMOOR.W
        (0b10000, 0b01, 7, 0x80, (0x80, 7)),   # AMOMIN.W signed
        (0b10100, 0b10, 7, 0x80, (0x80, 0x80)), # AMOMAX.W signed
        (0b11000, 0b11, 7, 0x80, (0x80, 7)),    # AMOMINU.W unsigned
        (0b11100, 0b00, 7, 0x80, (0x80, 0x80)), # AMOMAXU.W unsigned
    ]
    for amofn, aqrl, src_imm, init_mem, expected in amo_cases:
        assert _run_amo_op_case("RV32I+GC+A", 32, amofn, src_imm, init_mem, aqrl=aqrl) == expected
        assert _run_amo_op_case("RV32I+GC+*", 32, amofn, src_imm, init_mem, aqrl=aqrl) == expected
    assert _run_lr_sc_case("RV32I+GC+A", 32, 0b010, aqrl=0b11) == (0x12345678, 0, 0xA5)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010, aqrl=0b11) == (0x12345678, 0, 0xA5)


def test_star_preserves_lr_sc_runtime_behavior_for_rv32_and_rv64():
    x2_32, x4_32, x5_32 = _run_lr_sc_case("RV32I+GC+*", 32, 0b010)
    x2_32_base, x4_32_base, x5_32_base = _run_lr_sc_case("RV32I+GC+A", 32, 0b010)
    assert (x2_32, x4_32, x5_32) == (x2_32_base, x4_32_base, x5_32_base)

    x2_64, x4_64, x5_64 = _run_lr_sc_case("RV64I+GC+*", 64, 0b011)
    x2_64_base, x4_64_base, x5_64_base = _run_lr_sc_case("RV64I+GC+A", 64, 0b011)
    assert (x2_64, x4_64, x5_64) == (x2_64_base, x4_64_base, x5_64_base)


def _run_amo_ops_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0),     # x1 = base address
        enc_i(OP_IMM, 2, 0b000, 0, 0x03),  # x2 = 3
        enc_i(OP_IMM, 3, 0b000, 0, 0x0F),  # x3 = 15
        enc_i(OP_IMM, 4, 0b000, 0, 0xF0),  # x4 = 240
        enc_amo(5, 1, 2, 0b00000),         # AMOADD x5, 3 from mem(0)
        enc_amo(6, 1, 3, 0b00100),         # AMOXOR x6, 15 from mem(0)
        enc_amo(7, 1, 4, 0b01100),         # AMOAND x7, 240 from mem(0)
        nop(),
    ]
    imem_words = 512
    prog = prog + [nop()] * (imem_words - len(prog))

    class _AmoOpsBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
            self.dmem = SimpleDMem(words=16, init=[0x00000005])

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

    dut = _AmoOpsBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(240):
            yield Tick()
        for reg in (5, 6, 7):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x5"], result["x6"], result["x7"]


def _run_amo_op_case(extensions, xlen, amofn, src_imm, init_mem, funct3=0b010, aqrl=0):
    if funct3 == 0b011:
        src_bytes = [(src_imm >> shift) & 0xFF for shift in range(56, -1, -8)]
        load_src = [enc_i(OP_IMM, 2, 0b000, 0, src_bytes[0])]
        for byte in src_bytes[1:]:
            load_src.extend([
                enc_i(OP_IMM, 2, 0b001, 2, 8),
                enc_i(OP_IMM, 2, 0b110, 2, byte),
            ])
        init_words = [init_mem & 0xFFFFFFFF, (init_mem >> 32) & 0xFFFFFFFF]
    else:
        load_src = [enc_i(OP_IMM, 2, 0b000, 0, src_imm)]
        init_words = [init_mem]

    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0),     # x1 = base address
        *load_src,
        enc_amo_aqrl(5, 1, 2, amofn, aqrl=aqrl, funct3=funct3),  # AMO rd, rs2, (rs1)
        enc_i(LOAD, 6, funct3, 1, 0),       # x6 = post-amo memory value
        nop(),
    ]

    imem_words = 512
    prog = prog + [nop()] * (imem_words - len(prog))

    class _AmoOpBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
            self.dmem = SimpleDMem(words=16, init=init_words)

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

    dut = _AmoOpBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(220):
            yield Tick()
        for reg in (5, 6):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x5"], result["x6"]


def _run_amo_op_aqrl_case(extensions, amofn, aqrl, src_imm, init_mem):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0),
        enc_i(OP_IMM, 2, 0b000, 0, src_imm),
        enc_amo_aqrl(5, 1, 2, amofn, aqrl=aqrl),
        enc_i(LOAD, 6, 0b010, 1, 0),
        nop(),
    ]
    imem_words = 128
    prog = prog + [nop()] * (imem_words - len(prog))

    class _AmoAqrlBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
            self.dmem = SimpleDMem(words=16, init=[init_mem])

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

    dut = _AmoAqrlBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(220):
            yield Tick()
        for reg in (5, 6):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x5"], result["x6"]


def _run_lr_sc_aqrl_case(extensions):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0),
        enc_amo_aqrl(2, 1, 0, 0b00010, aqrl=0b11),
        enc_i(OP_IMM, 3, 0b000, 0, 0xA5),
        enc_amo_aqrl(4, 1, 3, 0b00011, aqrl=0b11),
        enc_i(LOAD, 5, 0b010, 1, 0),
        nop(),
    ]
    imem_words = 128
    prog = prog + [nop()] * (imem_words - len(prog))

    class _LrScAqrlBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
            self.dmem = SimpleDMem(words=16, init=[0x12345678])

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

    dut = _LrScAqrlBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(240):
            yield Tick()
        for reg in (2, 4, 5):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x2"], result["x4"], result["x5"]


def _run_rv32a_standard_matrix_case(extensions):
    amo_cases = [
        (0b00001, 0, 3, 5, 0x00000003),  # AMOSWAP.W
        (0b00000, 1, 3, 5, 0x00000008),  # AMOADD.W
        (0b00100, 2, 3, 5, 0x00000006),  # AMOXOR.W
        (0b01100, 3, 3, 5, 0x00000001),  # AMOAND.W
        (0b01000, 0, 3, 5, 0x00000007),  # AMOOR.W
        (0b10000, 1, 7, 0x80, 0x00000007),  # AMOMIN.W signed
        (0b10100, 2, 7, 0x80, 0x00000080),  # AMOMAX.W signed
        (0b11000, 3, 7, 0x80, 0x00000007),  # AMOMINU.W unsigned
        (0b11100, 0, 7, 0x80, 0x00000080),  # AMOMAXU.W unsigned
    ]
    prog = []
    old_regs = []
    post_regs = []
    for idx, (amofn, aqrl, src, init, _expected_post) in enumerate(amo_cases):
        addr = idx * 4
        old_reg = 3 + idx
        post_reg = 12 + idx
        old_regs.append(old_reg)
        post_regs.append(post_reg)
        prog.extend([
            enc_i(OP_IMM, 1, 0b000, 0, addr),
            enc_i(OP_IMM, 2, 0b000, 0, src),
            nop(),
            enc_amo_aqrl(old_reg, 1, 2, amofn, aqrl=aqrl),
            nop(),
            nop(),
            nop(),
            enc_i(LOAD, post_reg, 0b010, 1, 0),
            nop(),
        ])
    prog.extend([
        enc_i(OP_IMM, 1, 0b000, 0, 36),
        nop(),
        enc_amo_aqrl(21, 1, 0, 0b00010, aqrl=0b11),  # LR.W aq+rl
        enc_i(OP_IMM, 2, 0b000, 0, 0x5A),
        nop(),
        enc_amo_aqrl(22, 1, 2, 0b00011, aqrl=0b11),  # SC.W aq+rl
        nop(),
        nop(),
        nop(),
        enc_i(LOAD, 23, 0b010, 1, 0),
        nop(),
    ])
    imem_words = 256
    prog = prog + [nop()] * (imem_words - len(prog))
    init_mem = [case[3] for case in amo_cases] + [0x00000044]

    class _RV32AMatrixBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
            self.dmem = SimpleDMem(words=16, init=init_mem)

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

    dut = _RV32AMatrixBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    results = {}

    def proc():
        for _ in range(520):
            yield Tick()
        for reg in old_regs + post_regs + [21, 22, 23]:
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            results[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return results


def _run_lr_sc_case(extensions, xlen, funct3, aqrl=0):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0),         # x1 = base address
        enc_amo_aqrl(2, 1, 0, 0b00010, aqrl=aqrl, funct3=funct3),  # LR
        enc_i(OP_IMM, 3, 0b000, 0, 0xA5),      # x3 = 0xA5
        enc_amo_aqrl(4, 1, 3, 0b00011, aqrl=aqrl, funct3=funct3),  # SC
        enc_i(LOAD, 5, funct3, 1, 0),          # x5 = memory after SC
        nop(),
    ]

    imem_words = 512
    prog = prog + [nop()] * (imem_words - len(prog))

    init_mem = 0x12345678 if xlen == 32 else 0x123456789ABCDEF0
    init_words = ([init_mem] if xlen == 32 else
                  [init_mem & 0xFFFFFFFF, (init_mem >> 32) & 0xFFFFFFFF])

    class _LrScBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
            self.dmem = SimpleDMem(words=16, init=init_words)

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

    dut = _LrScBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(220):
            yield Tick()
        for reg in (2, 4, 5):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x2"], result["x4"], result["x5"]


def test_explicit_a_extension_executes_amo_ops_on_rv32_and_rv64():
    x5_32, x6_32, x7_32 = _run_amo_ops_case("RV32I+GC+A", 32)
    assert x5_32 == 5
    assert x6_32 == 8
    assert x7_32 == 7

    x5_64, x6_64, x7_64 = _run_amo_ops_case("RV64I+GC+A", 64)
    assert x5_64 == 5
    assert x6_64 == 8
    assert x7_64 == 7


def test_explicit_a_extension_executes_more_amo_ops_on_rv32_and_rv64():
    x5_or_32, x6_or_32 = _run_amo_op_case("RV32I+GC+A", 32, 0b01000, 0xF0, 0x5A)
    assert x5_or_32 == 0x5A
    assert x6_or_32 == 0xFA

    x5_max_32, x6_max_32 = _run_amo_op_case("RV32I+GC+A", 32, 0b10100, 0x7F, 0x5A)
    assert x5_max_32 == 0x5A
    assert x6_max_32 == 0x7F

    x5_maxu_64, x6_maxu_64 = _run_amo_op_case("RV64I+GC+A", 64, 0b11100, 0xFFFFFFFFFFFFFFFF, 0x12345678)
    assert x5_maxu_64 == 0x12345678
    assert x6_maxu_64 == 0xFFFFFFFFFFFFFFFF


def test_explicit_a_extension_executes_min_ops_on_rv32_and_rv64():
    x5_min_32, x6_min_32 = _run_amo_op_case("RV32I+GC+A", 32, 0b10000, 0x7F, 0x80)
    assert x5_min_32 == 0x80
    assert x6_min_32 == 0x7F

    x5_minu_32, x6_minu_32 = _run_amo_op_case("RV32I+GC+A", 32, 0b11000, 0x7F, 0x80)
    assert x5_minu_32 == 0x80
    assert x6_minu_32 == 0x7F

    x5_min_64, x6_min_64 = _run_amo_op_case("RV64I+GC+A", 64, 0b10000, 0x7FFFFFFFFFFFFFFF, 0x8000000000000000, funct3=0b011)
    assert x5_min_64 == 0x8000000000000000
    assert x6_min_64 == 0x8000000000000000

    x5_minu_64, x6_minu_64 = _run_amo_op_case("RV64I+GC+A", 64, 0b11000, 0xFFFFFFFFFFFFFFFF, 0x7FFFFFFFFFFFFFFF, funct3=0b011)
    assert x5_minu_64 == 0x7FFFFFFFFFFFFFFF
    assert x6_minu_64 == 0x7FFFFFFFFFFFFFFF


def test_explicit_a_extension_executes_lr_sc_on_rv32_and_rv64():
    x2_32, x4_32, x5_32 = _run_lr_sc_case("RV32I+GC+A", 32, 0b010)
    assert x2_32 == 0x12345678
    assert x4_32 == 0
    assert x5_32 == 0x000000A5

    x2_64, x4_64, x5_64 = _run_lr_sc_case("RV64I+GC+A", 64, 0b011)
    assert x2_64 == 0x123456789ABCDEF0
    assert x4_64 == 0
    assert x5_64 == 0x00000000000000A5


def test_explicit_a_extension_executes_all_amo_d_ops_on_rv64():
    cases = [
        (0b00000, 2, 1, 3),
        (0b00001, 9, 5, 9),
        (0b00100, 0x5A, 0xF0, 0xAA),
        (0b01000, 0x5A, 0xF0, 0xFA),
        (0b01100, 0x5A, 0xF0, 0x50),
        (0b10000, 0x7FFFFFFFFFFFFFFF, 0x8000000000000000,
         0x8000000000000000),
        (0b10100, 0x7FFFFFFFFFFFFFFF, 0x8000000000000000,
         0x7FFFFFFFFFFFFFFF),
        (0b11000, 0xFFFFFFFFFFFFFFFF, 0x7FFFFFFFFFFFFFFF,
         0x7FFFFFFFFFFFFFFF),
        (0b11100, 0xFFFFFFFFFFFFFFFF, 0x7FFFFFFFFFFFFFFF,
         0xFFFFFFFFFFFFFFFF),
    ]
    for amofn, source, initial, expected in cases:
        old, post = _run_amo_op_case(
            "RV64I+GC+A", 64, amofn, source, initial, funct3=0b011)
        assert old == initial
        assert post == expected


def test_explicit_m_word_ops_execute_on_rv64():
    # MULW/DIVW/REMW are RV64 W-suffix M extension ops.
    x4, x5, x6 = _run_mw_case("RV64I+GC+M")
    assert x4 == 0x12345678 // 2
    assert x5 == 0
    assert x6 == (0x12345678 * 2) & ((1 << 64) - 1)

    x4_no_m, x5_no_m, x6_no_m = _run_mw_case("RV64I+GC")
    assert x4_no_m == 0x111
    assert x5_no_m == 0x222
    assert x6_no_m == 0x333


def test_star_superset_preserves_rv64_word_m_extension_variants():
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case("RV64I+GC+M", 64)
    assert _run_mw_case("RV64I+GC+M", 64) == _run_mw_case("  rv64i + gc + ??? + M + B + B + ", 64)

    assert _run_mw_edge_case("RV64I+GC+*", 64) == _run_mw_edge_case("RV64I+GC+M", 64)
    assert _run_mw_edge_case("RV64I+GC+M", 64) == _run_mw_edge_case("  rv64i + gc + ??? + m + M + C + ", 64)


def test_star_superset_preserves_fp_and_double_runtime_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + F + D + M + B + C + ZICSR + zifencei + A + "
    noisy_64 = "  rv64i + gc + ??? + d + f + m + a + ZICSR + ZIFENCEI + B + C + "

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case("  rv32i + gc + ??? + D + f + F + M + A + ", 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case("  rv64i + gc + ??? + d + A + M + F + ", 64)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)


def test_zicsr_runtime_stability_for_star_full_noisy_standard_spec_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + zicsr + zifencei + zicond + m + a + B + C + F + D + "
    noisy_64 = "  rv64i + gc + ??? + ZICSR + ZIFENCEI + ZICOND + A + M + B + C + F + D + "

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)
def test_explicit_m_word_div_edge_cases_execute_on_rv64():
    x3, x4, x5, x6 = _run_mw_edge_case("RV64I+GC+M")
    neg1_64 = ((1 << 64) - 1)
    assert x4 == neg1_64      # DIVW x4 = 10 / 0 -> -1
    assert x5 == 10           # REMW x5 = 10
    assert x6 == neg1_64      # DIVUW x6 = 0 / 0 -> -1
    assert x3 == 1            # (-1) / (-1) = 1


def test_explicit_m_a_zicsr_bundle_executes_on_rv32_and_rv64():
    x3, x4, x5 = _run_extension_combo_case("RV32I+GC+M+A+ZICSR", 32)
    assert x3 == 0xFFFFFFF4 & 0xFFFFFFFF
    assert x4 == 1
    assert x5 == 0

    x3_64, x4_64, x5_64 = _run_extension_combo_case("RV64I+GC+M+A+ZICSR", 64)
    assert x3_64 == -12 & ((1 << 64) - 1)
    assert x4_64 == 1
    assert x5_64 == 0


def test_star_superset_matches_extension_combo_bundle_on_rv32_and_rv64():
    noisy_32 = "  rv32i + gc + ??? + zicsr + a + m + B + b + "
    noisy_64 = "  rv64i + gc + ??? + M + A + ZICSR + ZBA + B + b + "

    explicit_32 = "RV32I+GC+M+A+ZICSR"
    explicit_64 = "RV64I+GC+M+A+ZICSR"
    star_32 = "RV32I+GC+*"
    star_64 = "RV64I+GC+*"

    assert _run_extension_combo_case(star_32, 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case(star_64, 64) == _run_extension_combo_case(noisy_64, 64)
    assert _run_extension_combo_case(star_32, 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case(star_64, 64) == _run_extension_combo_case(explicit_64, 64)


def test_star_matches_explicit_full_standard_combo_bundle_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + A + B + D + F + C + M + ZICOND + zifencei + zicsr + ??? + "
    noisy_64 = "  rv64i + gc + c + b + a + d + f + M + zicond + ZICSR + ZIFENCEI + ??? + "

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)


def test_star_matches_explicit_standard_full_bundle_executes_same_values_for_bundle_vs_star_on_rv32_and_rv64():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    star_32 = "RV32I+GC+*"
    star_64 = "RV64I+GC+*"

    noisy_explicit_32 = "  rv32i + gc + zicsr + zifencei + zicond + M + A + B + C + F + D + ??? + "
    noisy_explicit_64 = "  rv64i + gc + ??? + ZICSR + ZIFENCEI + ZICOND + m + a + b + c + f + d + "

    rv32_star = _run_extension_combo_case(star_32, 32)
    rv32_explicit = _run_extension_combo_case(explicit_32, 32)
    rv64_star = _run_extension_combo_case(star_64, 64)
    rv64_explicit = _run_extension_combo_case(explicit_64, 64)
    rv32_noisy = _run_extension_combo_case(noisy_explicit_32, 32)
    rv64_noisy = _run_extension_combo_case(noisy_explicit_64, 64)

    assert rv32_star == rv32_explicit
    assert rv64_star == rv64_explicit
    assert rv32_star == rv32_noisy
    assert rv64_star == rv64_noisy


def test_star_matches_explicit_standard_full_bundle_on_rv64_with_alias_noise():
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_64 = "  rv64i + gc + ??? + zicond + zifencei + zicsr + m + a + b + c + f + d + "

    star_64 = "RV64I+GC+*"
    star_alias_64 = "  RV64I + GC + * + ??? + "
    explicit_64 = "  RV64I + GC + M + A + B + C + F + D + ZICSR + ZIFENCEI + ZICOND "

    rv64_star = _run_extension_combo_case(star_64, 64)
    rv64_star_alias = _run_extension_combo_case(star_alias_64, 64)
    rv64_full = _run_extension_combo_case(full_64, 64)
    rv64_explicit = _run_extension_combo_case(explicit_64, 64)
    rv64_noisy = _run_extension_combo_case(noisy_64, 64)

    assert rv64_star == rv64_star_alias
    assert rv64_star == rv64_full
    assert rv64_star == rv64_explicit
    assert rv64_star == rv64_noisy


def test_star_alias_and_duplicate_tokens_stable_on_rv64_combo_runtime():
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_star_64 = "  rv64i + gc + * + ??? + M + m + A + a + B + b + C + F + D + zicsr + zifencei + zicond + "
    noisy_explicit_64 = "  RV64I + GC + ZICOND + ZIFENCEI + ZICSR + M + A + B + C + F + D + ??? + "

    rv64_star = _run_extension_combo_case("RV64I+GC+*", 64)
    rv64_star_noisy = _run_extension_combo_case(noisy_star_64, 64)
    rv64_explicit = _run_extension_combo_case(explicit_64, 64)
    rv64_explicit_noisy = _run_extension_combo_case(noisy_explicit_64, 64)

    assert rv64_star == rv64_star_noisy
    assert rv64_star == rv64_explicit
    assert rv64_star == rv64_explicit_noisy


def test_star_matches_explicit_standard_full_bundle_on_rv32_alias_and_duplicates_runtime():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + zifencei + zicsr + zicond + m + m + A + a + b + c + f + d + "
    noisy_star_32 = "  RV32I + GC + * + ??? + A + a + M + m + B + C + D + F + ZICOND + ZIFENCEI + ZICSR "

    star_32 = "RV32I+GC+*"
    explicit_32 = "  RV32I + GC + M + A + B + C + F + D + ZICSR + ZIFENCEI + ZICOND "

    rv32_star = _run_extension_combo_case(star_32, 32)
    rv32_star_noisy = _run_extension_combo_case(noisy_star_32, 32)
    rv32_full = _run_extension_combo_case(full_32, 32)
    rv32_explicit = _run_extension_combo_case(explicit_32, 32)
    rv32_noisy = _run_extension_combo_case(noisy_32, 32)

    assert rv32_star == rv32_star_noisy
    assert rv32_star == rv32_full
    assert rv32_star == rv32_explicit
    assert rv32_star == rv32_noisy


def test_explicit_zicsr_extension_executes_on_rv32_and_rv64():
    assert _run_zicsr_case("RV32I+GC+ZICSR", 32) == 0
    assert _run_zicsr_case("RV64I+GC+ZICSR", 64) == 0

    assert _run_zicsr_case("RV32I", 32) == 0x123
    assert _run_zicsr_case("RV64I", 64) == 0x123


def _run_amo_star_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 2, 0b000, 0, 1),
        enc_amoswap(1, 0, 2),
        nop(),
    ]
    imem_words = 512
    prog = prog + [nop()] * (imem_words - len(prog))

    class _AmoBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
            self.dmem = SimpleDMem(words=16, init=[0x00000001])

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

    dut = _AmoBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core

    result = {}

    def proc():
        for _ in range(160):
            yield Tick()

        yield c.dbg_reg_addr.eq(1)
        yield Tick()
        result["x1"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x1"]


def _run_extension_combo_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 6),          # x1 = 6
        enc_i(OP_IMM, 2, 0b000, 0, -2 & 0xFFF), # x2 = -2
        enc_mul(3, 1, 2),                        # x3 = -12
        enc_amoswap(4, 0, 0),                    # x4 = old dmem[0] (requires A)
        enc_i(OP_IMM, 5, 0b000, 0, 0xB),        # x5 = 0xB
        enc_i(SYSTEM, 5, 0b001, 5, 0x300),      # csrrw x5, mstatus, x5 (requires ZICSR)
        nop(),
    ]
    # Keep the 220-cycle observation window from wrapping the program and
    # executing the non-idempotent AMO sequence a second time.
    imem_words = 512
    prog = prog + [nop()] * (imem_words - len(prog))

    class _ExtComboBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
            self.dmem = SimpleDMem(words=16, init=[1])

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

    dut = _ExtComboBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    results = {}

    def proc():
        for _ in range(220):
            yield Tick()
        yield c.dbg_reg_addr.eq(3)
        yield Tick()
        results["x3"] = yield c.dbg_reg_rdata
        yield c.dbg_reg_addr.eq(4)
        yield Tick()
        results["x4"] = yield c.dbg_reg_rdata
        yield c.dbg_reg_addr.eq(5)
        yield Tick()
        results["x5"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return results["x3"], results["x4"], results["x5"]


def _run_fp_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 4),      # x1 = 4 (addr base)
        enc_i(OP_IMM, 2, 0b000, 0, 7),      # x2 = 7
        enc_i(OP_IMM, 3, 0b000, 0, 9),      # x3 = 9 baseline value
        enc_r(OP_FP, 3, 0b000, 1, 2, 0x00), # FADD.S/D placeholder -> writeback stub zero when F enabled
        enc_i(LOAD_FP, 4, 0b010, 1, 0),      # FLW x4, 0(x1) (through LOAD_FP if enabled)
        enc_i(STORE_FP, 0, 0b010, 1, 4),    # FSW x4, 0(x1) (through STORE_FP if enabled)
        nop(),
    ]

    imem_words = 128
    prog = prog + [nop()] * (imem_words - len(prog))

    class _FpBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
            self.dmem = SimpleDMem(words=16, init=[0x11111111])

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

    dut = _FpBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(220):
            yield Tick()
        yield c.dbg_reg_addr.eq(3)
        yield Tick()
        result["x3"] = yield c.dbg_reg_rdata
        yield c.dbg_reg_addr.eq(4)
        yield Tick()
        result["x4"] = yield c.dbg_reg_rdata
        yield c.dbg_reg_addr.eq(1)
        yield Tick()
        result["x1"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x1"]


def _run_d_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0),      # x1 = 0
        enc_i(OP_IMM, 2, 0b000, 0, 0x77),   # x2 starts non-zero to distinguish no-op from D execution
        enc_i(LOAD_FP, 2, 0b011, 1, 0),     # FLD f2,0(x1); integer x2 must be preserved
        enc_i(OP_IMM, 3, 0b000, 2, 0x55),
        nop(),
    ]

    imem_words = 96
    prog = prog + [nop()] * (imem_words - len(prog))
    class _DCase(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
            self.dmem = SimpleDMem(words=16, init=[0x22222222])

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

    dut = _DCase()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(180):
            yield Tick()
        yield c.dbg_reg_addr.eq(2)
        yield Tick()
        result["x2"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x2"]
    sim.run()
    return result["x2"]


def _run_fp_width_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0),      # x1 = 0
        enc_i(OP_IMM, 2, 0b000, 0, 0x77),   # x2 = 0x77 baseline
        enc_i(OP_IMM, 4, 0b000, 0, 0x55),   # x4 = 0x55 baseline
        enc_i(LOAD_FP, 2, 0b011, 1, 0),     # FLD x2,0(x1) only with D
        enc_i(LOAD_FP, 4, 0b010, 1, 0),     # FLW x4,0(x1) only with F
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))
    class _FPWidthBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
            self.dmem = SimpleDMem(words=16, init=[0x11111111, 0x22222222])

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

    dut = _FPWidthBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(180):
            yield Tick()
        yield c.dbg_reg_addr.eq(2)
        yield Tick()
        result["x2"] = yield c.dbg_reg_rdata
        yield c.dbg_reg_addr.eq(4)
        yield Tick()
        result["x4"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x2"], result["x4"]


def _run_fp_store_width_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0),      # x1 = 0
        enc_i(LOAD_FP, 2, 0b010, 1, 0),     # FLW f2,0(x1) only with F
        enc_s(STORE_FP, 0b010, 1, 2, 4),    # FSW f2,4(x1) only with F
        enc_i(LOAD, 3, 0b010, 1, 4),        # x3 observes the FSW payload
        enc_i(LOAD_FP, 2, 0b011, 1, 16),    # FLD f2,16(x1) only with D
        enc_s(STORE_FP, 0b011, 1, 2, 8),    # FSD f2,8(x1) only with D
        enc_i(LOAD, 4, 0b010, 1, 8),        # x4 observes the low FSD word
        nop(),
    ]

    imem_words = 256
    prog = prog + [nop()] * (imem_words - len(prog))
    class _FPWidthStoreBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
            self.dmem = SimpleDMem(words=16, init=[
                0x11111111, 0x22222222, 0x33333333, 0x44444444,
                0x11111111, 0x22222222,
            ])

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

    dut = _FPWidthStoreBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {"dependency_cycles": [], "writes": []}

    def proc():
        for cycle in range(220):
            if ((yield c.dbg_stall_dep_id1) or
                    (yield c.dbg_stall_dep_id2)):
                result["dependency_cycles"].append(cycle)
            if (yield c.dmem_valid) and (yield c.dmem_we):
                result["writes"].append((
                    cycle,
                    (yield c.dmem_addr),
                    (yield c.dmem_wdata),
                ))
            yield Tick()
        yield c.dbg_reg_addr.eq(3)
        yield Tick()
        result["x3"] = yield c.dbg_reg_rdata
        yield c.dbg_reg_addr.eq(4)
        yield Tick()
        result["x4"] = yield c.dbg_reg_rdata
        yield c.dbg_freg_addr.eq(2)
        yield Tick()
        result["f2"] = yield c.dbg_freg_rdata

    sim.add_process(proc)
    sim.run()
    if dut.core.enable_d:
        assert result["f2"] == 0x2222222211111111
        assert result["dependency_cycles"]
        assert any(addr == 8 and data == 0x11111111
                   for _, addr, data in result["writes"]), result
    elif dut.core.enable_f:
        assert result["f2"] == 0xFFFFFFFF11111111
        assert result["dependency_cycles"]
        assert any(addr == 4 and data == 0x11111111
                   for _, addr, data in result["writes"]), result
        assert result["x3"] == 0x11111111, result
    return result["x3"], result["x4"]


def _run_b_case(extensions, xlen, funct3=0b111):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0x123),
        enc_i(OP_IMM, 2, 0b000, 0, 0x0F),
        enc_i(OP_IMM, 3, 0b000, 0, 0x55),
        enc_r(OP, 3, funct3, 1, 2, 0b0100000),
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _BCase(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _BCase()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(180):
            yield Tick()
        yield c.dbg_reg_addr.eq(3)
        yield Tick()
        result["x3"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"]


def _run_zbb_count_case(extensions, xlen=32):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0x10),
        enc_r(OP, 3, 0b001, 1, 0b00000, 0b0110000),  # CLZ
        enc_r(OP, 4, 0b001, 1, 0b00001, 0b0110000),  # CTZ
        enc_r(OP, 5, 0b001, 1, 0b00010, 0b0110000),  # CPOP
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _ZbbCountCase(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _ZbbCountCase()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(180):
            yield Tick()
        for reg in (3, 4, 5):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"]


def _run_zbb_minmax_case(extensions, xlen=32):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, -3),
        enc_i(OP_IMM, 2, 0b000, 0, 5),
        enc_r(OP, 3, 0b100, 1, 2, 0b0000101),  # MIN
        enc_r(OP, 4, 0b101, 1, 2, 0b0000101),  # MINU
        enc_r(OP, 5, 0b110, 1, 2, 0b0000101),  # MAX
        enc_r(OP, 6, 0b111, 1, 2, 0b0000101),  # MAXU
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _ZbbMinMaxCase(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _ZbbMinMaxCase()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(220):
            yield Tick()
        for reg in (3, 4, 5, 6):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"], result["x6"]


def _run_zbb_extend_case(extensions, xlen=32):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0xF),
        enc_i(OP_IMM, 1, 0b001, 1, 12),
        enc_i(OP_IMM, 1, 0b110, 1, 0x80),
        enc_r(OP, 3, 0b100, 1, 0b00100, 0b0110000),  # SEXT.B
        enc_r(OP, 4, 0b100, 1, 0b00101, 0b0110000),  # SEXT.H
        enc_r(OP, 5, 0b100, 1, 0b00110, 0b0110000),  # ZEXT.H
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _ZbbExtendCase(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _ZbbExtendCase()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(220):
            yield Tick()
        for reg in (3, 4, 5):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"]


def _run_zbb_byte_case(extensions, xlen=32):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0x01),
        enc_i(OP_IMM, 1, 0b001, 1, 20),
        enc_i(OP_IMM, 1, 0b110, 1, 0x20),
        enc_i(OP_IMM, 1, 0b001, 1, 8),
        enc_i(OP_IMM, 1, 0b110, 1, 0x03),
        enc_r(OP, 3, 0b111, 1, 0, 0b0010101),       # ORC.B
        enc_r(OP, 4, 0b101, 1, 0b00111, 0b0110101), # REV8
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _ZbbByteCase(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _ZbbByteCase()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(240):
            yield Tick()
        for reg in (3, 4):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"]


def _run_zbb_rotate_case(extensions, xlen=32):
    prog = [
        enc_u(LUI, 1, 0x12345),
        enc_i(OP_IMM, 1, 0b000, 1, 0x678),                  # x1 = 0x12345678
        enc_i(OP_IMM, 8, 0b000, 0, 8),                      # x8 = 8
        enc_r(OP, 3, 0b001, 1, 8, 0b0110000),               # ROL
        enc_r(OP, 4, 0b101, 1, 8, 0b0110000),               # ROR
        enc_i(OP_IMM, 5, 0b101, 1, (0b0110000 << 5) | 4),   # RORI
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _ZbbRotateCase(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _ZbbRotateCase()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(240):
            yield Tick()
        for reg in (3, 4, 5):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"]


def test_zbb_standard_rotate_execute_on_rv32_b_and_star():
    expected = (0x34567812, 0x78123456, 0x81234567)
    assert _run_zbb_rotate_case(["B"]) == expected
    assert _run_zbb_rotate_case(["*"]) == expected


def _run_control_flow_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 1),        # x1 = 1
        enc_i(OP_IMM, 2, 0b000, 0, 2),        # x2 = 2
        enc_jal(0, 8),                         # jump over ins 2 -> execute ins 3
        enc_i(OP_IMM, 3, 0b000, 0, 0x55),     # skipped
        enc_b(BRANCH, 0b000, 1, 1, 12),       # beq x1, x1, ins+3
        enc_i(OP_IMM, 4, 0b000, 0, 0x44),     # skipped by branch
        enc_i(OP_IMM, 5, 0b000, 0, 0x55),     # skipped by branch
        enc_i(OP_IMM, 6, 0b000, 0, 0x66),     # branch target + next
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _ControlFlowBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _ControlFlowBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(180):
            yield Tick()
        for reg in (1, 3, 4, 5, 6):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x1"], result["x3"], result["x4"], result["x5"], result["x6"]


def _run_branch_condition_case(extensions, xlen, funct3, lhs, rhs):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, lhs),       # x1 = lhs
        enc_i(OP_IMM, 2, 0b000, 0, rhs),       # x2 = rhs
        enc_b(BRANCH, funct3, 1, 2, 12),       # taken target at pc 20
        enc_i(OP_IMM, 3, 0b000, 0, 0x11),      # not-taken marker
        enc_jal(0, 8),                         # skip taken marker
        enc_i(OP_IMM, 3, 0b000, 0, 0x22),      # taken marker
        enc_jal(0, 0),                         # hold final state stable
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _BranchConditionBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _BranchConditionBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(220):
            yield Tick()
        yield c.dbg_reg_addr.eq(3)
        yield Tick()
        result["x3"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"]


def _assert_branch_condition_pair(extensions, funct3, taken_operands, not_taken_operands):
    assert _run_branch_condition_case(extensions, 32, funct3, *taken_operands) == 0x22
    assert _run_branch_condition_case(extensions, 32, funct3, *not_taken_operands) == 0x11


def test_rv32i_standard_branch_conditions_execute_taken_and_not_taken():
    branch_cases = [
        (0b000, (7, 7), (7, 8)),       # BEQ
        (0b001, (7, 8), (7, 7)),       # BNE
        (0b100, (-1, 1), (1, -1)),     # BLT signed
        (0b101, (1, -1), (-1, 1)),     # BGE signed
        (0b110, (1, -1), (-1, 1)),     # BLTU unsigned
        (0b111, (-1, 1), (1, -1)),     # BGEU unsigned
    ]
    for funct3, taken_operands, not_taken_operands in branch_cases:
        _assert_branch_condition_pair("RV32I+GC", funct3, taken_operands, not_taken_operands)
        _assert_branch_condition_pair("RV32I+GC+*", funct3, taken_operands, not_taken_operands)


def _run_zicond_case(extensions, xlen, funct3=0b000, rs2=0x0F):
    # Historical callers use 000/001 as operation selectors.  Emit the
    # ratified encodings while preserving those callers' mnemonic selectors:
    # 000 selected CZERO.EQZ, while 001 selected CZERO.NEZ.
    standard_funct3 = {0b000: 0b101, 0b001: 0b111}.get(funct3, funct3)
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0x55),
        enc_i(OP_IMM, 2, 0b000, 0, rs2),
        enc_r(OP, 3, standard_funct3, 1, 2, ZICOND_F7),
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _ZicondBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _ZicondBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(160):
            yield Tick()
        yield c.dbg_reg_addr.eq(3)
        yield Tick()
        result["x3"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"]


def _run_multi_extension_mix_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0),         # x1 = 0
        enc_i(OP_IMM, 2, 0b000, 0, 0x123),     # x2 = 0x123
        enc_i(SYSTEM, 3, 0b001, 2, 0x300),     # x3 = csrrw x3, mstatus, x2
        enc_i(OP_IMM, 4, 0b000, 0, 0x55),      # x4 = 0x55
        enc_amo(5, 1, 4, 0b00001),             # x5 = old[0], mem[0] = x4
        enc_i(LOAD, 6, 0b010, 1, 0),          # x6 = mem[0]
        enc_i(SYSTEM, 0, 0b000, 0, FENCE_I_IMM),
        enc_r(OP, 7, 0b000, 4, 0, ZICOND_F7),  # x7 = czero.eqz x4, x0 => 0
        nop(),
    ]

    imem_words = 512
    prog = prog + [nop()] * (imem_words - len(prog))

    class _MixBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _MixBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(260):
            yield Tick()
        for reg in (3, 5, 6, 7):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x5"], result["x6"], result["x7"]


def _run_fp32_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 4),      # x1 = 4
        enc_i(OP_IMM, 2, 0b000, 0, 7),      # x2 = 7 baseline
        enc_r(OP_FP_32, 2, 0b000, 1, 1, 0x00),
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _Fp32Bench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _Fp32Bench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(140):
            yield Tick()
        yield c.dbg_reg_addr.eq(2)
        yield Tick()
        result["x2"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x2"]


def test_star_enables_a_extension_for_amo():
    # AMOSWAP in star-set should behave as atomic swap and read old value 1 from dmem[0]
    assert _run_amo_star_case("RV32I+GC+*", 64) == 1


def test_non_star_without_a_keeps_amo_as_noop():
    # Without A extension, AMOSWAP should be not executed and keep x1 at default 0
    assert _run_amo_star_case("RV32I+GC", 32) == 0


def test_star_set_amo_noise_invariance_on_rv32_and_rv64():
    noisy_32 = "  rv32i + gc + ??? + ZBA + ZBB + B + C + F + D + A + ZICOND + ZICSR + ZIFENCEI + unknown.ext + "
    noisy_64 = "  rv64i + gc + ??? + ZBA + zba + B + C + F + D + A + zicond + zifencei + zicsr + unknown.ext + "

    assert _run_amo_star_case("RV32I+GC+*", 32) == _run_amo_star_case(noisy_32, 32)
    assert _run_amo_star_case("RV64I+GC+*", 64) == _run_amo_star_case(noisy_64, 64)


def test_star_alias_parser_handles_duplicate_and_dense_tokens_on_rv64():
    # Parser robustness: duplicates, lower/upper mix, dense separators, and whitespace noise
    # should not alter the runtime behavior of the full standard-star set.
    assert _run_case("RV64I+GC+*", 64) == _run_case("  rv64i+GC+*+*+???+  +b+ a +A+ZB*+", 64)


def test_rv32_baseline_parser_noise_matches_clean_rv32i_gc_baseline():
    # RV32I+GC baseline should ignore duplicate/empty/unknown tokens and still execute stable.
    noisy_32 = "  rv32i + gc + ??? + b + B + C + ? + unknown.token + "
    assert _run_base_case("RV32I+GC", 32) == _run_base_case(noisy_32, 32)


def _run_zicsr_star_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 3, 0b000, 0, 0x123),   # x3 = 0x123
        enc_i(SYSTEM, 3, 0b001, 2, 0x300),    # csrrw x3, mstatus, x2
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _ZicsrBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _ZicsrBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core

    result = {}

    def proc():
        for _ in range(180):
            yield Tick()
        yield c.dbg_reg_addr.eq(3)
        yield Tick()
        result["x3"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"]


def test_star_enables_zicsr_system_writeback_zero():
    assert _run_zicsr_star_case("RV32I+GC+*", 32) == 0


def test_non_star_without_zicsr_keeps_register():
    assert _run_zicsr_star_case("RV32I", 32) == 0x123


def _run_fence_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 1),
        enc_fence(),                           # FENCE
        enc_i(OP_IMM, 2, 0b000, 0, 2),
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _FenceBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _FenceBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(180):
            yield Tick()
        for reg in (1, 2):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x1"], result["x2"]


def test_rv32i_standard_fence_executes_as_ordering_barrier():
    assert _run_fence_case("RV32I+GC", 32) == (1, 2)
    assert _run_fence_case("RV32I+GC+*", 32) == (1, 2)


def _run_system_trap_case(extensions, xlen, imm):
    prog = [
        enc_i(SYSTEM, 0, 0b000, 0, imm),      # ECALL imm=0 / EBREAK imm=1
        enc_jal(0, 0),                         # hold final state stable
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _SystemTrapBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _SystemTrapBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {"trap_seen": False}

    def proc():
        for _ in range(120):
            if (yield c.trap):
                result["trap_seen"] = True
            yield Tick()

    sim.add_process(proc)
    sim.run()
    return result["trap_seen"]


def test_rv32i_standard_ecall_and_ebreak_raise_trap():
    for imm in (0, 1):
        assert _run_system_trap_case("RV32I+GC", 32, imm)
        assert _run_system_trap_case("RV32I+GC+*", 32, imm)


def _run_zifencei_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 1),
        enc_i(SYSTEM, 0, 0b000, 0, FENCE_I_IMM),  # FENCE.I
        enc_i(OP_IMM, 2, 0b000, 0, 2),
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _ZifenceiBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _ZifenceiBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core

    result = {}

    def proc():
        for _ in range(180):
            yield Tick()
        yield c.dbg_reg_addr.eq(1)
        yield Tick()
        result["x1"] = yield c.dbg_reg_rdata
        yield c.dbg_reg_addr.eq(2)
        yield Tick()
        result["x2"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x1"], result["x2"]


def test_explicit_zifencei_extensions_execute_on_rv32_and_rv64():
    assert _run_zifencei_case("RV32I+GC+ZIFENCEI", 32) == (1, 2)
    assert _run_zifencei_case("RV64I+GC+ZIFENCEI", 64) == (1, 2)

    assert _run_zifencei_case("RV32I+GC", 32) == (1, 2)
    assert _run_zifencei_case("RV64I+GC", 64) == (1, 2)


def test_star_set_includes_zifencei_standard_behavior():
    assert _run_zifencei_case("RV32I+GC+*", 32) == (1, 2)
    assert _run_zifencei_case("RV64I+GC+*", 64) == (1, 2)


def test_star_set_includes_zicsr_zicond_zifencei_under_noise_rv32():
    noisy_star = "  RV32I + GC + * + ??? + ZBA + zba + zbb + zbh + ZBK + zifencei + zicond + ZICSR + UNKNOWN + "
    noisy_explicit = "  rv32i + gc + ??? + m + a + B + C + F + D + ZICSR + zifencei + zicond + zba + zbb + "

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_star, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_explicit, 32)


def test_star_fullset_control_mix_stability_under_32_and_64_alias_noise():
    noisy_star_32 = "  rv32i + gc + ??? + M + m + A + a + B + b + C + F + f + D + d + ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + "
    noisy_star_64 = "  rv64i + gc + ??? + M + m + A + a + B + b + C + F + f + D + d + ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + "

    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(noisy_star_32, 32)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(noisy_star_64, 64)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_star_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_star_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_star_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_star_64, 64)


def test_star_includes_fullset_runtime_parity_with_noisy_alias_on_rv32_rv64():
    noisy_star_rv32 = " rv32i + GC + * + ??? + m + A + m + ZICSR + zicsr + ZICOND + zifencei + zifencei + unknown "
    noisy_explicit_rv32 = "RV32I + gc + M + A + ZICSR + ZICOND + ZIFENCEI + ??? + m + zifencei "

    noisy_star_rv64 = " rv64i+ gc +*+ zifencei + ZICOND + ZICSR + a + m + ??? + gc + ZIFENCEI "
    noisy_explicit_rv64 = "RV64I + GC + M + A + ZICSR + ZICOND + ZIFENCEI + ZICOND + M "

    rv32_star_x3, rv32_star_x5, rv32_star_x6, rv32_star_x7 = _run_multi_extension_mix_case(noisy_star_rv32, 32)
    rv32_exp_x3, rv32_exp_x5, rv32_exp_x6, rv32_exp_x7 = _run_multi_extension_mix_case(noisy_explicit_rv32, 32)
    rv64_star_x3, rv64_star_x5, rv64_star_x6, rv64_star_x7 = _run_multi_extension_mix_case(noisy_star_rv64, 64)
    rv64_exp_x3, rv64_exp_x5, rv64_exp_x6, rv64_exp_x7 = _run_multi_extension_mix_case(noisy_explicit_rv64, 64)

    assert (rv32_star_x3, rv32_star_x5, rv32_star_x6, rv32_star_x7) == (rv32_exp_x3, rv32_exp_x5, rv32_exp_x6, rv32_exp_x7)
    assert (rv64_star_x3, rv64_star_x5, rv64_star_x6, rv64_star_x7) == (rv64_exp_x3, rv64_exp_x5, rv64_exp_x6, rv64_exp_x7)


def test_zicsr_and_zifencei_extensions_execute_on_rv32_and_rv64():
    assert _run_zifencei_case("RV32I+GC+ZICSR+ZIFENCEI", 32) == (1, 2)
    assert _run_zifencei_case("RV64I+GC+ZICSR+ZIFENCEI", 64) == (1, 2)


def test_zicond_and_zifencei_extensions_execute_on_rv32_and_rv64():
    assert _run_zifencei_case("RV32I+GC+ZICOND+ZIFENCEI", 32) == (1, 2)
    assert _run_zifencei_case("RV64I+GC+ZICOND+ZIFENCEI", 64) == (1, 2)


def test_multi_extension_mix_runtime_executes_on_rv32_and_rv64():
    x3_32, x5_32, x6_32, x7_32 = _run_multi_extension_mix_case("RV32I+GC+M+A+ZICSR+ZICOND+ZIFENCEI", 32)
    assert x3_32 == 0
    assert x5_32 == 0
    assert x6_32 == 0x55
    assert x7_32 == 0

    x3_64, x5_64, x6_64, x7_64 = _run_multi_extension_mix_case("RV64I+GC+M+A+ZICSR+ZICOND+ZIFENCEI", 64)
    mask = (1 << 64) - 1
    assert x3_64 == 0
    assert x5_64 == 0
    assert x6_64 == 0x55 & mask
    assert x7_64 == 0


def test_explicit_f_and_d_extension_combo_executes_on_rv32_and_rv64():
    x3_32, x4_32, x1_32 = _run_fp_case("RV32I+GC+F+D", 32)
    assert x3_32 == 9
    assert x4_32 == 0
    assert x1_32 == 4
    assert _run_d_case("RV32I+GC+F+D", 32) == 0x77

    x3_64, x4_64, x1_64 = _run_fp_case("RV64I+GC+F+D", 64)
    assert x3_64 == 9
    assert x4_64 == 0
    assert x1_64 == 4
    assert _run_d_case("RV64I+GC+F+D", 64) == 0x77


def test_noisy_extension_syntax_keeps_multi_extension_mix_execution_consistent():
    noisy_32 = "  rv32i + gc + ??? + zifencei + b + a + ZICSR + zicond + m + ZBA + B + "
    noisy_64 = "  rv64i + gc + ??? + a + m + zicond + zicsr + zifencei + zBH + B + "
    full_32 = "RV32I+GC+M+A+ZICSR+ZICOND+ZIFENCEI"
    full_64 = "RV64I+GC+M+A+ZICSR+ZICOND+ZIFENCEI"

    x3_32, x5_32, x6_32, x7_32 = _run_multi_extension_mix_case(noisy_32, 32)
    x3_32_full, x5_32_full, x6_32_full, x7_32_full = _run_multi_extension_mix_case(full_32, 32)
    assert (x3_32, x5_32, x6_32, x7_32) == (x3_32_full, x5_32_full, x6_32_full, x7_32_full)

    x3_64, x5_64, x6_64, x7_64 = _run_multi_extension_mix_case(noisy_64, 64)
    x3_64_full, x5_64_full, x6_64_full, x7_64_full = _run_multi_extension_mix_case(full_64, 64)
    assert (x3_64, x5_64, x6_64, x7_64) == (x3_64_full, x5_64_full, x6_64_full, x7_64_full)


def test_zicsr_zicond_zifencei_extensions_execute_on_rv32_and_rv64():
    assert _run_zifencei_case("RV32I+GC+ZICSR+ZICOND+ZIFENCEI", 32) == (1, 2)
    assert _run_zifencei_case("RV64I+GC+ZICSR+ZICOND+ZIFENCEI", 64) == (1, 2)


def test_explicit_f_extension_has_distinct_runtime_behavior_rv32_and_rv64():
    x3_no_f, x4_no_f, _ = _run_fp_case("RV32I+GC", 32)
    assert x3_no_f == 9
    assert x4_no_f == 0

    x3_with_f, x4_with_f, _ = _run_fp_case("RV32I+GC+F", 32)
    assert x3_with_f == 0
    assert x4_with_f == 0

    x3_with_f64, x4_with_f64, _ = _run_fp_case("RV64I+GC+F", 64)
    assert x3_with_f64 == 0
    assert x4_with_f64 == 0


def test_explicit_d_extension_fp_loads_execute_on_rv32_and_rv64():
    x2_no_d = _run_d_case("RV32I+GC", 32)
    assert x2_no_d == 0x77
    x2_with_d = _run_d_case("RV32I+GC+D", 32)
    assert x2_with_d == 0x77
    x2_with_d64 = _run_d_case("RV64I+GC+D", 64)
    assert x2_with_d64 == 0x77


def test_explicit_f_width_gates_fp_loads_on_rv32_and_rv64():
    x2_f32, x4_f32 = _run_fp_width_case("RV32I+GC+F", 32)
    assert x2_f32 == 0x77
    assert x4_f32 == 0x55

    x2_f64, x4_f64 = _run_fp_width_case("RV64I+GC+F", 64)
    assert x2_f64 == 0x77
    assert x4_f64 == 0x55

    x2_d32, x4_d32 = _run_fp_width_case("RV32I+GC+D", 32)
    assert x2_d32 == 0x77
    assert x4_d32 == 0x55

    x2_d64, x4_d64 = _run_fp_width_case("RV64I+GC+D", 64)
    assert x2_d64 == 0x77
    assert x4_d64 == 0x55


def test_explicit_f_width_gates_fp_stores_on_rv32_and_rv64():
    x3_f32, x4_f32 = _run_fp_store_width_case("RV32I+GC+F", 32)
    assert x3_f32 == 0x11111111
    assert x4_f32 == 0x33333333

    x3_f64, x4_f64 = _run_fp_store_width_case("RV64I+GC+F", 64)
    assert x3_f64 == 0x11111111
    assert x4_f64 == 0x33333333

    x3_d32, x4_d32 = _run_fp_store_width_case("RV32I+GC+D", 32)
    assert x3_d32 == 0x11111111
    assert x4_d32 == 0x11111111

    x3_d64, x4_d64 = _run_fp_store_width_case("RV64I+GC+D", 64)
    assert x3_d64 == 0x11111111
    assert x4_d64 == 0x11111111


def _run_flw_fsw_case(extensions, xlen=32):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0),       # x1 = 0 (base)
        enc_u(LUI, 2, 0x12345),
        enc_i(OP_IMM, 2, 0b000, 2, 0x678),   # x2 = 0x12345678 payload
        enc_i(LOAD_FP, 3, 0b010, 1, 0),      # FLW x3, 0(x1)
        enc_s(STORE_FP, 0b010, 1, 2, 4),     # FSW x2, 4(x1)
        enc_i(LOAD, 4, 0b010, 1, 4),         # LW x4, 4(x1) observes FSW
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _FlwFswBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
            self.dmem = SimpleDMem(words=16, init=[0xA5A5C3C3, 0])

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

    dut = _FlwFswBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(220):
            yield Tick()
        for reg in (3, 4):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"]


def test_rv32f_standard_flw_fsw_execute_on_rv32_f_and_star():
    assert _run_flw_fsw_case("RV32I+GC+F", 32) == (0xA5A5C3C3, 0x12345678)
    assert _run_flw_fsw_case("RV32I+GC+*", 32) == (0xA5A5C3C3, 0x12345678)


def _run_faddsub_case(extensions, xlen=32):
    prog = [
        enc_u(LUI, 1, 0x3F800),                  # +1.0f
        enc_u(LUI, 2, 0x40000),                  # +2.0f
        enc_u(LUI, 6, 0xBF800),                  # -1.0f
        enc_r(OP_FP, 3, 0b000, 1, 2, 0b0000000), # FADD.S +1,+2 -> +3
        enc_r(OP_FP, 4, 0b000, 2, 1, 0b0000100), # FSUB.S +2,+1 -> +1
        enc_r(OP_FP, 5, 0b000, 6, 2, 0b0000000), # FADD.S -1,+2 -> +1
        enc_r(OP_FP, 7, 0b000, 1, 1, 0b0000100), # FSUB.S +1,+1 -> +0
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _FaddSubBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _FaddSubBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(240):
            yield Tick()
        for reg in (3, 4, 5, 7):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"], result["x7"]


def test_rv32f_standard_add_sub_execute_on_rv32_f_and_star():
    expected = (0x40400000, 0x3F800000, 0x3F800000, 0x00000000)
    assert _run_faddsub_case("RV32I+GC+F", 32) == expected
    assert _run_faddsub_case("RV32I+GC+*", 32) == expected


def _run_fmul_case(extensions, xlen=32):
    prog = [
        enc_u(LUI, 1, 0x3F800),                  # +1.0f
        enc_u(LUI, 2, 0x40000),                  # +2.0f
        enc_u(LUI, 6, 0xBF800),                  # -1.0f
        enc_u(LUI, 8, 0x3FC00),                  # +1.5f
        enc_r(OP_FP, 3, 0b000, 8, 2, 0b0001000), # FMUL.S +1.5,+2 -> +3
        enc_r(OP_FP, 4, 0b000, 6, 2, 0b0001000), # FMUL.S -1,+2 -> -2
        enc_r(OP_FP, 5, 0b000, 0, 2, 0b0001000), # FMUL.S +0,+2 -> +0
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _FmulBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _FmulBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(240):
            yield Tick()
        for reg in (3, 4, 5):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"]


def test_rv32f_standard_mul_execute_on_rv32_f_and_star():
    expected = (0x40400000, 0xC0000000, 0x00000000)
    assert _run_fmul_case("RV32I+GC+F", 32) == expected
    assert _run_fmul_case("RV32I+GC+*", 32) == expected


def enc_r4(opcode, rd, rm, rs1, rs2, rs3, funct2=0):
    return ((rs3 & 0x1f) << 27) | ((funct2 & 0x3) << 25) | ((rs2 & 0x1f) << 20) | \
        ((rs1 & 0x1f) << 15) | ((rm & 0x7) << 12) | ((rd & 0x1f) << 7) | (opcode & 0x7f)


def _run_fused_fma_case(extensions, xlen=32):
    prog = [
        enc_u(LUI, 1, 0x3F800),                  # +1.0f
        enc_u(LUI, 2, 0x40000),                  # +2.0f
        enc_u(LUI, 8, 0x3FC00),                  # +1.5f
        enc_r4(MADD, 3, 0b000, 8, 2, 1),         # FMADD.S 1.5*2+1 -> +4
        enc_r4(MSUB, 4, 0b000, 8, 2, 1),         # FMSUB.S 1.5*2-1 -> +2
        enc_r4(NMSUB, 5, 0b000, 8, 2, 1),        # FNMSUB.S -(1.5*2)+1 -> -2
        enc_r4(NMADD, 6, 0b000, 8, 2, 1),        # FNMADD.S -(1.5*2)-1 -> -4
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _FusedFmaBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _FusedFmaBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(280):
            yield Tick()
        for reg in (3, 4, 5, 6):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"], result["x6"]


def test_rv32f_standard_fused_madd_family_execute_on_rv32_f_and_star():
    expected = (0x40800000, 0x40000000, 0xC0000000, 0xC0800000)
    assert _run_fused_fma_case("RV32I+GC+F", 32) == expected
    assert _run_fused_fma_case("RV32I+GC+*", 32) == expected


def _run_fdiv_case(extensions, xlen=32):
    prog = [
        enc_u(LUI, 1, 0x40400),                  # +3.0f
        enc_u(LUI, 2, 0x3FC00),                  # +1.5f
        enc_u(LUI, 6, 0xC0000),                  # -2.0f
        enc_u(LUI, 8, 0x3F800),                  # +1.0f
        enc_r(OP_FP, 3, 0b000, 1, 2, 0b0001100), # FDIV.S +3,+1.5 -> +2
        enc_r(OP_FP, 4, 0b000, 6, 8, 0b0001100), # FDIV.S -2,+1 -> -2
        enc_r(OP_FP, 5, 0b000, 0, 1, 0b0001100), # FDIV.S +0,+3 -> +0
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _FdivBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _FdivBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(260):
            yield Tick()
        for reg in (3, 4, 5):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"]


def test_rv32f_standard_div_execute_on_rv32_f_and_star():
    expected = (0x40000000, 0xC0000000, 0x00000000)
    assert _run_fdiv_case("RV32I+GC+F", 32) == expected
    assert _run_fdiv_case("RV32I+GC+*", 32) == expected


def _run_fsqrt_case(extensions, xlen=32):
    prog = [
        enc_u(LUI, 1, 0x3F800),                  # +1.0f
        enc_u(LUI, 2, 0x40800),                  # +4.0f
        enc_u(LUI, 6, 0x41100),                  # +9.0f
        enc_r(OP_FP, 3, 0b000, 0, 0, 0b0101100), # FSQRT.S +0 -> +0
        enc_r(OP_FP, 4, 0b000, 1, 0, 0b0101100), # FSQRT.S +1 -> +1
        enc_r(OP_FP, 5, 0b000, 2, 0, 0b0101100), # FSQRT.S +4 -> +2
        enc_r(OP_FP, 7, 0b000, 6, 0, 0b0101100), # FSQRT.S +9 -> +3
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _FsqrtBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _FsqrtBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(260):
            yield Tick()
        for reg in (3, 4, 5, 7):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"], result["x7"]


def test_rv32f_standard_sqrt_execute_on_rv32_f_and_star():
    expected = (0x00000000, 0x3F800000, 0x40000000, 0x40400000)
    assert _run_fsqrt_case("RV32I+GC+F", 32) == expected
    assert _run_fsqrt_case("RV32I+GC+*", 32) == expected


def _run_fcvt_w_case(extensions, xlen=32):
    prog = [
        enc_u(LUI, 1, 0x40400),                  # +3.0f
        enc_u(LUI, 2, 0xC0000),                  # -2.0f
        enc_u(LUI, 6, 0x40000),                  # +2.0f
        enc_r(OP_FP, 3, 0b001, 1, 0, 0b1100000), # FCVT.W.S +3.0 -> 3
        enc_r(OP_FP, 4, 0b001, 2, 0, 0b1100000), # FCVT.W.S -2.0 -> -2
        enc_r(OP_FP, 5, 0b001, 6, 1, 0b1100000), # FCVT.WU.S +2.0 -> 2
        enc_r(OP_FP, 7, 0b001, 0, 1, 0b1100000), # FCVT.WU.S +0.0 -> 0
        enc_r(OP_FP, 8, 0b001, 2, 1, 0b1100000), # FCVT.WU.S -2.0 -> 0 saturation
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _FcvtWBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _FcvtWBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(260):
            yield Tick()
        for reg in (3, 4, 5, 7, 8):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"], result["x7"], result["x8"]


def test_rv32f_standard_fcvt_w_execute_on_rv32_f_and_star():
    expected = (3, 0xfffffffe, 2, 0, 0)
    assert _run_fcvt_w_case("RV32I+GC+F", 32) == expected
    assert _run_fcvt_w_case("RV32I+GC+*", 32) == expected


def _run_fcvt_s_case(extensions, xlen=32):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 3),             # x1 = +3
        enc_i(OP_IMM, 2, 0b000, 0, -2),            # x2 = -2
        enc_i(OP_IMM, 6, 0b000, 0, 2),             # x6 = +2
        enc_r(OP_FP, 3, 0b000, 1, 0, 0b1101000),   # FCVT.S.W +3 -> +3.0f
        enc_r(OP_FP, 4, 0b000, 2, 0, 0b1101000),   # FCVT.S.W -2 -> -2.0f
        enc_r(OP_FP, 5, 0b000, 6, 1, 0b1101000),   # FCVT.S.WU +2 -> +2.0f
        enc_r(OP_FP, 7, 0b000, 0, 1, 0b1101000),   # FCVT.S.WU +0 -> +0.0f
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _FcvtSBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _FcvtSBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(260):
            yield Tick()
        for reg in (3, 4, 5, 7):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"], result["x7"]


def test_rv32f_standard_fcvt_s_execute_on_rv32_f_and_star():
    expected = (0x40400000, 0xC0000000, 0x40000000, 0x00000000)
    assert _run_fcvt_s_case("RV32I+GC+F", 32) == expected
    assert _run_fcvt_s_case("RV32I+GC+*", 32) == expected


def _run_fsgnj_case(extensions, xlen=32):
    prog = [
        enc_u(LUI, 1, 0x3F800),
        enc_i(OP_IMM, 1, 0b000, 1, 1),        # x1 = 0x3f800001
        enc_u(LUI, 2, 0xBF000),
        enc_i(OP_IMM, 2, 0b000, 2, 2),        # x2 = 0xbf000002
        enc_r(OP_FP, 3, 0b000, 1, 2, 0b0010000),  # FSGNJ.S
        enc_r(OP_FP, 4, 0b001, 1, 2, 0b0010000),  # FSGNJN.S
        enc_r(OP_FP, 5, 0b010, 1, 2, 0b0010000),  # FSGNJX.S
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _FsgnjBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _FsgnjBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(220):
            yield Tick()
        for reg in (3, 4, 5):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"]


def test_rv32f_standard_fsgnj_sign_injection_execute_on_rv32_f_and_star():
    expected = (0xBF800001, 0x3F800001, 0xBF800001)
    assert _run_fsgnj_case("RV32I+GC+F", 32) == expected
    assert _run_fsgnj_case("RV32I+GC+*", 32) == expected


def _run_d_fsgnj_case(extensions, xlen=64):
    prog = [
        enc_u(LUI, 1, 0x3FF00),
        enc_i(OP_IMM, 1, 0b001, 1, 32),           # x1 = 0x3ff0000000000000
        enc_i(OP_IMM, 1, 0b000, 1, 1),            # x1 = 0x3ff0000000000001
        enc_u(LUI, 2, 0xBFF00),
        enc_i(OP_IMM, 2, 0b001, 2, 32),           # x2 = 0xbff0000000000000
        enc_i(OP_IMM, 2, 0b000, 2, 2),            # x2 = 0xbff0000000000002
        enc_r(OP_FP, 3, 0b000, 1, 2, 0b0010001),  # FSGNJ.D
        enc_r(OP_FP, 4, 0b001, 1, 2, 0b0010001),  # FSGNJN.D
        enc_r(OP_FP, 5, 0b010, 1, 2, 0b0010001),  # FSGNJX.D
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _DFsgnjBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _DFsgnjBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(260):
            yield Tick()
        for reg in (3, 4, 5):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"]


def test_rv32d_standard_fsgnj_sign_injection_execute_on_rv64_d_and_star():
    expected = (0xBFF0000000000001, 0x3FF0000000000001, 0xBFF0000000000001)
    assert _run_d_fsgnj_case("RV64I+GC+D", 64) == expected
    assert _run_d_fsgnj_case("RV64I+GC+*", 64) == expected


def _run_d_fld_fsd_case(extensions, xlen=64):
    prog = [
        enc_i(LOAD_FP, 3, 0b011, 0, 0),      # FLD x3, 0(x0) -> +3.0d
        nop(),
        nop(),
        enc_s(STORE_FP, 0b011, 0, 3, 8),    # FSD x3, 8(x0)
        nop(),
        nop(),
        enc_i(LOAD_FP, 4, 0b011, 0, 8),      # FLD x4, 8(x0)
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))
    dmem_init = [0x00000000, 0x40080000, 0x00000000, 0x00000000] + [0] * 12

    class _DFldFsdBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
            self.dmem = SimpleDMem(words=16, init=dmem_init)

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

    dut = _DFldFsdBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(260):
            yield Tick()
        for reg in (3, 4):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"]


def test_rv32d_standard_fld_fsd_execute_on_rv64_d_and_star():
    expected = (0x4008000000000000, 0x4008000000000000)
    assert _run_d_fld_fsd_case("RV64I+GC+D", 64) == expected
    assert _run_d_fld_fsd_case("RV64I+GC+*", 64) == expected


def _run_d_minmax_case(extensions, xlen=64):
    prog = [
        enc_u(LUI, 1, 0x3FF00),
        enc_i(OP_IMM, 1, 0b001, 1, 32),           # +1.0d
        enc_u(LUI, 2, 0x40000),
        enc_i(OP_IMM, 2, 0b001, 2, 32),           # +2.0d
        enc_u(LUI, 6, 0xBFF00),
        enc_i(OP_IMM, 6, 0b001, 6, 32),           # -1.0d
        enc_u(LUI, 7, 0x80000),
        enc_i(OP_IMM, 7, 0b001, 7, 32),           # -0.0d
        enc_u(LUI, 8, 0x7FF80),
        enc_i(OP_IMM, 8, 0b001, 8, 32),           # qNaN
        enc_r(OP_FP, 3, 0b000, 1, 2, 0b0010101),  # FMIN.D +1,+2 -> +1
        enc_r(OP_FP, 4, 0b001, 6, 1, 0b0010101),  # FMAX.D -1,+1 -> +1
        enc_r(OP_FP, 5, 0b000, 0, 7, 0b0010101),  # FMIN.D +0,-0 -> -0
        enc_r(OP_FP, 9, 0b001, 8, 2, 0b0010101),  # FMAX.D NaN,+2 -> +2
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _DMinmaxBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _DMinmaxBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(300):
            yield Tick()
        for reg in (3, 4, 5, 9):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"], result["x9"]


def test_rv32d_standard_min_max_execute_on_rv64_d_and_star():
    expected = (0x3FF0000000000000, 0x3FF0000000000000, 0x8000000000000000, 0x4000000000000000)
    assert _run_d_minmax_case("RV64I+GC+D", 64) == expected
    assert _run_d_minmax_case("RV64I+GC+*", 64) == expected


def _run_d_compare_case(extensions, xlen=64):
    prog = [
        enc_u(LUI, 1, 0x3FF00),
        enc_i(OP_IMM, 1, 0b001, 1, 32),           # +1.0d
        enc_u(LUI, 2, 0x40000),
        enc_i(OP_IMM, 2, 0b001, 2, 32),           # +2.0d
        enc_u(LUI, 6, 0xBFF00),
        enc_i(OP_IMM, 6, 0b001, 6, 32),           # -1.0d
        enc_u(LUI, 7, 0x7FF80),
        enc_i(OP_IMM, 7, 0b001, 7, 32),           # qNaN
        enc_r(OP_FP, 3, 0b010, 1, 1, 0b1010001),  # FEQ.D +1,+1 -> 1
        enc_r(OP_FP, 4, 0b001, 1, 2, 0b1010001),  # FLT.D +1,+2 -> 1
        enc_r(OP_FP, 5, 0b000, 6, 1, 0b1010001),  # FLE.D -1,+1 -> 1
        enc_r(OP_FP, 8, 0b010, 7, 7, 0b1010001),  # FEQ.D NaN,NaN -> 0
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _DCompareBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _DCompareBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(300):
            yield Tick()
        for reg in (3, 4, 5, 8):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"], result["x8"]


def test_rv32d_standard_compare_execute_on_rv64_d_and_star():
    expected = (1, 1, 1, 0)
    assert _run_d_compare_case("RV64I+GC+D", 64) == expected
    assert _run_d_compare_case("RV64I+GC+*", 64) == expected


def _run_d_mul_case(extensions, xlen=64):
    prog = [
        enc_u(LUI, 1, 0x3FF80),
        enc_i(OP_IMM, 1, 0b001, 1, 32),           # +1.5d
        enc_u(LUI, 2, 0xC0000),
        enc_i(OP_IMM, 2, 0b001, 2, 32),           # -2.0d
        enc_i(OP_IMM, 6, 0b000, 0, 0),            # +0.0d
        enc_u(LUI, 7, 0x7FF80),
        enc_i(OP_IMM, 7, 0b001, 7, 32),           # qNaN
        enc_r(OP_FP, 3, 0b000, 1, 2, 0b0001001),  # FMUL.D +1.5,-2.0 -> -3.0
        enc_r(OP_FP, 4, 0b000, 1, 6, 0b0001001),  # FMUL.D +1.5,+0.0 -> +0.0
        enc_r(OP_FP, 5, 0b000, 7, 1, 0b0001001),  # FMUL.D NaN,+1.5 -> qNaN
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _DMulBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _DMulBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(280):
            yield Tick()
        for reg in (3, 4, 5):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"]


def test_rv32d_standard_mul_execute_on_rv64_d_and_star():
    expected = (0xC008000000000000, 0x0000000000000000, 0x7FF8000000000000)
    assert _run_d_mul_case("RV64I+GC+D", 64) == expected
    assert _run_d_mul_case("RV64I+GC+*", 64) == expected


def _run_d_div_case(extensions, xlen=64):
    prog = [
        enc_u(LUI, 1, 0x40180),
        enc_i(OP_IMM, 1, 0b001, 1, 32),           # +6.0d
        enc_u(LUI, 2, 0x40000),
        enc_i(OP_IMM, 2, 0b001, 2, 32),           # +2.0d
        enc_u(LUI, 6, 0x3FF80),
        enc_i(OP_IMM, 6, 0b001, 6, 32),           # +1.5d
        enc_i(OP_IMM, 7, 0b000, 0, 0),            # +0.0d
        enc_r(OP_FP, 3, 0b000, 1, 2, 0b0001101),  # FDIV.D +6.0,+2.0 -> +3.0
        enc_r(OP_FP, 4, 0b000, 6, 7, 0b0001101),  # FDIV.D +1.5,+0.0 -> +inf
        enc_r(OP_FP, 5, 0b000, 7, 7, 0b0001101),  # FDIV.D +0.0,+0.0 -> qNaN
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _DDivBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _DDivBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(280):
            yield Tick()
        for reg in (3, 4, 5):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"]


def test_rv32d_standard_div_execute_on_rv64_d_and_star():
    expected = (0x4008000000000000, 0x7FF0000000000000, 0x7FF8000000000000)
    assert _run_d_div_case("RV64I+GC+D", 64) == expected
    assert _run_d_div_case("RV64I+GC+*", 64) == expected


def _run_d_fused_fma_case(extensions, xlen=64):
    prog = [
        enc_u(LUI, 1, 0x3FF00),
        enc_i(OP_IMM, 1, 0b001, 1, 32),             # +1.0d
        enc_u(LUI, 2, 0x40000),
        enc_i(OP_IMM, 2, 0b001, 2, 32),             # +2.0d
        enc_u(LUI, 8, 0x3FF80),
        enc_i(OP_IMM, 8, 0b001, 8, 32),             # +1.5d
        nop(),
        nop(),
        nop(),
        enc_r4(MADD, 3, 0b000, 8, 2, 1, funct2=1),  # FMADD.D 1.5*2+1 -> +4
        enc_r4(MSUB, 4, 0b000, 8, 2, 1, funct2=1),  # FMSUB.D 1.5*2-1 -> +2
        enc_r4(NMSUB, 5, 0b000, 8, 2, 1, funct2=1), # FNMSUB.D -(1.5*2)+1 -> -2
        enc_r4(NMADD, 6, 0b000, 8, 2, 1, funct2=1), # FNMADD.D -(1.5*2)-1 -> -4
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _DFusedFmaBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _DFusedFmaBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(320):
            yield Tick()
        for reg in (3, 4, 5, 6):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"], result["x6"]


def test_rv32d_standard_fused_madd_family_execute_on_rv64_d_and_star():
    expected = (0x4010000000000000, 0x4000000000000000, 0xC000000000000000, 0xC010000000000000)
    assert _run_d_fused_fma_case("RV64I+GC+D", 64) == expected
    assert _run_d_fused_fma_case("RV64I+GC+*", 64) == expected


def _run_d_add_sub_case(extensions, xlen=64):
    prog = [
        enc_u(LUI, 1, 0x3FF80),
        enc_i(OP_IMM, 1, 0b001, 1, 32),           # +1.5d
        enc_u(LUI, 2, 0x40000),
        enc_i(OP_IMM, 2, 0b001, 2, 32),           # +2.0d
        enc_u(LUI, 7, 0x7FF80),
        enc_i(OP_IMM, 7, 0b001, 7, 32),           # qNaN
        enc_r(OP_FP, 3, 0b000, 1, 2, 0b0000001),  # FADD.D +1.5,+2.0 -> +3.5
        enc_r(OP_FP, 4, 0b000, 2, 1, 0b0000101),  # FSUB.D +2.0,+1.5 -> +0.5
        enc_r(OP_FP, 5, 0b000, 7, 1, 0b0000001),  # FADD.D NaN,+1.5 -> qNaN
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _DAddSubBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _DAddSubBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(280):
            yield Tick()
        for reg in (3, 4, 5):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"]


def test_rv32d_standard_add_sub_execute_on_rv64_d_and_star():
    expected = (0x400C000000000000, 0x3FE0000000000000, 0x7FF8000000000000)
    assert _run_d_add_sub_case("RV64I+GC+D", 64) == expected
    assert _run_d_add_sub_case("RV64I+GC+*", 64) == expected


def _run_d_sqrt_case(extensions, xlen=64):
    prog = [
        enc_u(LUI, 1, 0x40100),
        enc_i(OP_IMM, 1, 0b001, 1, 32),           # +4.0d
        enc_u(LUI, 2, 0x40220),
        enc_i(OP_IMM, 2, 0b001, 2, 32),           # +9.0d
        enc_u(LUI, 6, 0xBFF00),
        enc_i(OP_IMM, 6, 0b001, 6, 32),           # -1.0d
        enc_r(OP_FP, 3, 0b000, 1, 0, 0b0101101),  # FSQRT.D +4.0 -> +2.0
        enc_r(OP_FP, 4, 0b000, 2, 0, 0b0101101),  # FSQRT.D +9.0 -> +3.0
        enc_r(OP_FP, 5, 0b000, 6, 0, 0b0101101),  # FSQRT.D -1.0 -> qNaN
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _DSqrtBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _DSqrtBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(280):
            yield Tick()
        for reg in (3, 4, 5):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"]


def test_rv32d_standard_sqrt_execute_on_rv64_d_and_star():
    expected = (0x4000000000000000, 0x4008000000000000, 0x7FF8000000000000)
    assert _run_d_sqrt_case("RV64I+GC+D", 64) == expected
    assert _run_d_sqrt_case("RV64I+GC+*", 64) == expected


def _run_d_fclass_case(extensions, xlen=64):
    prog = [
        enc_u(LUI, 1, 0xBFF00),
        enc_i(OP_IMM, 1, 0b001, 1, 32),           # -1.0d
        enc_u(LUI, 2, 0x3FF00),
        enc_i(OP_IMM, 2, 0b001, 2, 32),           # +1.0d
        enc_i(OP_IMM, 6, 0b000, 0, 0),            # +0.0d
        enc_u(LUI, 7, 0x7FF80),
        enc_i(OP_IMM, 7, 0b001, 7, 32),           # quiet NaN
        enc_r(OP_FP, 3, 0b001, 1, 0, 0b1110001),  # FCLASS.D negative normal
        enc_r(OP_FP, 4, 0b001, 2, 0, 0b1110001),  # FCLASS.D positive normal
        enc_r(OP_FP, 5, 0b001, 6, 0, 0b1110001),  # FCLASS.D positive zero
        enc_r(OP_FP, 8, 0b001, 7, 0, 0b1110001),  # FCLASS.D quiet NaN
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _DFclassBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _DFclassBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(300):
            yield Tick()
        for reg in (3, 4, 5, 8):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"], result["x8"]


def test_rv32d_standard_fclass_execute_on_rv64_d_and_star():
    expected = (1 << 1, 1 << 6, 1 << 4, 1 << 9)
    assert _run_d_fclass_case("RV64I+GC+D", 64) == expected
    assert _run_d_fclass_case("RV64I+GC+*", 64) == expected


def _run_d_fcvt_from_word_case(extensions, xlen=64):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, -2 & 0xFFF),   # x1 = -2
        enc_i(OP_IMM, 2, 0b000, 0, 3),            # x2 = 3
        enc_r(OP_FP, 3, 0b000, 1, 0, 0b1101001),  # FCVT.D.W -2 -> -2.0d
        enc_r(OP_FP, 4, 0b000, 2, 1, 0b1101001),  # FCVT.D.WU 3 -> +3.0d
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _DFcvtFromWordBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _DFcvtFromWordBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(220):
            yield Tick()
        for reg in (3, 4):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"]


def test_rv32d_standard_fcvt_d_from_word_execute_on_rv64_d_and_star():
    expected = (0xC000000000000000, 0x4008000000000000)
    assert _run_d_fcvt_from_word_case("RV64I+GC+D", 64) == expected
    assert _run_d_fcvt_from_word_case("RV64I+GC+*", 64) == expected


def _run_d_fcvt_to_word_case(extensions, xlen=64):
    prog = [
        enc_u(LUI, 1, 0xC0000),
        enc_i(OP_IMM, 1, 0b001, 1, 32),           # -2.0d
        enc_u(LUI, 2, 0x40080),
        enc_i(OP_IMM, 2, 0b001, 2, 32),           # +3.0d
        enc_r(OP_FP, 3, 0b000, 1, 0, 0b1100001),  # FCVT.W.D -2.0d -> -2
        enc_r(OP_FP, 4, 0b000, 2, 1, 0b1100001),  # FCVT.WU.D +3.0d -> 3
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _DFcvtToWordBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _DFcvtToWordBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(220):
            yield Tick()
        for reg in (3, 4):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"]


def test_rv32d_standard_fcvt_word_from_d_execute_on_rv64_d_and_star():
    expected = (0xFFFFFFFFFFFFFFFE, 3)
    assert _run_d_fcvt_to_word_case("RV64I+GC+D", 64) == expected
    assert _run_d_fcvt_to_word_case("RV64I+GC+*", 64) == expected


def _run_d_fcvt_single_double_case(extensions, xlen=64):
    prog = [
        enc_u(LUI, 1, 0x3FC00),                   # +1.5f
        enc_u(LUI, 2, 0x3FF80),
        enc_i(OP_IMM, 2, 0b001, 2, 32),           # +1.5d
        enc_r(OP_FP, 3, 0b000, 1, 0, 0b0100001),  # FCVT.D.S +1.5f -> +1.5d
        enc_r(OP_FP, 4, 0b000, 2, 1, 0b0100000),  # FCVT.S.D +1.5d -> +1.5f
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _DFcvtSingleDoubleBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _DFcvtSingleDoubleBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(220):
            yield Tick()
        for reg in (3, 4):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"]


def test_rv32d_standard_fcvt_single_double_execute_on_rv64_d_and_star():
    expected = (0x3FF8000000000000, 0x3FC00000)
    assert _run_d_fcvt_single_double_case("RV64I+GC+D", 64) == expected
    assert _run_d_fcvt_single_double_case("RV64I+GC+*", 64) == expected


def _run_fmv_case(extensions, xlen=32):
    prog = [
        enc_u(LUI, 1, 0x80000),
        enc_i(OP_IMM, 1, 0b000, 1, 0x123),       # x1 = 0x80000123
        enc_u(LUI, 2, 0x12345),
        enc_i(OP_IMM, 2, 0b000, 2, 0x678),       # x2 = 0x12345678
        enc_r(OP_FP, 3, 0b000, 1, 0, 0b1110000), # FMV.X.W
        enc_r(OP_FP, 4, 0b000, 2, 0, 0b1111000), # FMV.W.X
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _FmvBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _FmvBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(220):
            yield Tick()
        for reg in (3, 4):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"]


def test_rv32f_standard_fmv_bit_moves_execute_on_rv32_f_and_star():
    expected = (0x80000123, 0x12345678)
    assert _run_fmv_case("RV32I+GC+F", 32) == expected
    assert _run_fmv_case("RV32I+GC+*", 32) == expected


def _run_fclass_case(extensions, xlen=32):
    prog = [
        enc_u(LUI, 1, 0xBF800),                  # -1.0f
        enc_u(LUI, 2, 0x3F800),                  # +1.0f
        enc_i(OP_IMM, 6, 0b000, 0, 0),           # +0.0f
        enc_u(LUI, 7, 0x7FC00),                  # quiet NaN
        enc_r(OP_FP, 3, 0b001, 1, 0, 0b1110000), # FCLASS.S negative normal
        enc_r(OP_FP, 4, 0b001, 2, 0, 0b1110000), # FCLASS.S positive normal
        enc_r(OP_FP, 5, 0b001, 6, 0, 0b1110000), # FCLASS.S positive zero
        enc_r(OP_FP, 8, 0b001, 7, 0, 0b1110000), # FCLASS.S quiet NaN
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _FclassBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _FclassBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(240):
            yield Tick()
        for reg in (3, 4, 5, 8):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"], result["x8"]


def test_rv32f_standard_fclass_execute_on_rv32_f_and_star():
    expected = (1 << 1, 1 << 6, 1 << 4, 1 << 9)
    assert _run_fclass_case("RV32I+GC+F", 32) == expected
    assert _run_fclass_case("RV32I+GC+*", 32) == expected


def _run_fcmp_case(extensions, xlen=32):
    prog = [
        enc_u(LUI, 1, 0x3F800),                  # +1.0f
        enc_u(LUI, 2, 0x40000),                  # +2.0f
        enc_u(LUI, 6, 0xBF800),                  # -1.0f
        enc_u(LUI, 7, 0x7FC00),                  # quiet NaN
        enc_r(OP_FP, 3, 0b010, 1, 1, 0b1010000), # FEQ.S
        enc_r(OP_FP, 4, 0b001, 1, 2, 0b1010000), # FLT.S
        enc_r(OP_FP, 5, 0b000, 6, 1, 0b1010000), # FLE.S
        enc_r(OP_FP, 8, 0b010, 7, 7, 0b1010000), # FEQ.S NaN false
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _FcmpBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _FcmpBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(240):
            yield Tick()
        for reg in (3, 4, 5, 8):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"], result["x8"]


def test_rv32f_standard_compare_execute_on_rv32_f_and_star():
    expected = (1, 1, 1, 0)
    assert _run_fcmp_case("RV32I+GC+F", 32) == expected
    assert _run_fcmp_case("RV32I+GC+*", 32) == expected


def _run_fminmax_case(extensions, xlen=32):
    prog = [
        enc_u(LUI, 1, 0x3F800),                  # +1.0f
        enc_u(LUI, 2, 0x40000),                  # +2.0f
        enc_u(LUI, 6, 0xBF800),                  # -1.0f
        enc_u(LUI, 7, 0x80000),                  # -0.0f
        enc_u(LUI, 8, 0x7FC00),                  # quiet NaN
        enc_r(OP_FP, 3, 0b000, 1, 2, 0b0010100), # FMIN.S +1,+2 -> +1
        enc_r(OP_FP, 4, 0b001, 6, 1, 0b0010100), # FMAX.S -1,+1 -> +1
        enc_r(OP_FP, 5, 0b000, 0, 7, 0b0010100), # FMIN.S +0,-0 -> -0
        enc_r(OP_FP, 9, 0b001, 8, 2, 0b0010100), # FMAX.S NaN,+2 -> +2
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _FminmaxBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _FminmaxBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(240):
            yield Tick()
        for reg in (3, 4, 5, 9):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"], result["x9"]


def test_rv32f_standard_min_max_execute_on_rv32_f_and_star():
    expected = (0x3F800000, 0x3F800000, 0x80000000, 0x40000000)
    assert _run_fminmax_case("RV32I+GC+F", 32) == expected
    assert _run_fminmax_case("RV32I+GC+*", 32) == expected


def test_explicit_b_extension_enables_andn():
    x3_without_b = _run_b_case("RV32I+GC", 32)
    x3_with_b = _run_b_case("RV32I+GC+B", 32)
    assert x3_without_b == 0x55
    assert x3_with_b == (0x123 & (~0x0F & ((1 << 32) - 1)))

    x3_with_b64 = _run_b_case("RV64I+GC+B", 64)
    assert x3_with_b64 == (0x123 & (~0x0F & ((1 << 64) - 1)))


def test_explicit_b_extension_enables_orn():
    x3_without_b = _run_b_case("RV32I+GC", 32, funct3=0b110)
    x3_with_b = _run_b_case("RV32I+GC+B", 32, funct3=0b110)
    assert x3_without_b == 0x55
    assert x3_with_b == (0x123 | (~0x0F & ((1 << 32) - 1)))

    x3_with_b64 = _run_b_case("RV64I+GC+B", 64, funct3=0b110)
    assert x3_with_b64 == (0x123 | (~0x0F & ((1 << 64) - 1)))


def test_explicit_b_extension_enables_xnor():
    x3_without_b = _run_b_case("RV32I+GC", 32, funct3=0b100)
    x3_with_b = _run_b_case("RV32I+GC+B", 32, funct3=0b100)
    assert x3_without_b == 0x55
    assert x3_with_b == (~(0x123 ^ 0x0F) & ((1 << 32) - 1))

    x3_with_b64 = _run_b_case("RV64I+GC+B", 64, funct3=0b100)
    assert x3_with_b64 == (~(0x123 ^ 0x0F) & ((1 << 64) - 1))


def test_star_set_includes_b_and_executes_b_instructions():
    x3_star_32 = _run_b_case("RV32I+GC+*", 32, funct3=0b110)
    x3_star_64 = _run_b_case("RV64I+GC+*", 64, funct3=0b110)
    expected32 = 0x123 | (~0x0F & ((1 << 32) - 1))
    expected64 = 0x123 | (~0x0F & ((1 << 64) - 1))
    assert x3_star_32 == expected32
    assert x3_star_64 == expected64

    x3_star_32_andn = _run_b_case("RV32I+GC+*", 32, funct3=0b111)
    x3_star_64_andn = _run_b_case("RV64I+GC+*", 64, funct3=0b111)
    assert x3_star_32_andn == (0x123 & (~0x0F & ((1 << 32) - 1)))
    assert x3_star_64_andn == (0x123 & (~0x0F & ((1 << 64) - 1)))

    x3_star_32_xnor = _run_b_case("RV32I+GC+*", 32, funct3=0b100)
    x3_star_64_xnor = _run_b_case("RV64I+GC+*", 64, funct3=0b100)
    expected32_xnor = (~(0x123 ^ 0x0F) & ((1 << 32) - 1))
    expected64_xnor = (~(0x123 ^ 0x0F) & ((1 << 64) - 1))
    assert x3_star_32_xnor == expected32_xnor
    assert x3_star_64_xnor == expected64_xnor


def test_zbb_standard_clz_ctz_cpop_execute_on_rv32_b_and_star():
    expected = (27, 4, 1)
    assert _run_zbb_count_case("RV32I+GC+B", 32) == expected
    assert _run_zbb_count_case("RV32I+GC+ZBB", 32) == expected
    assert _run_zbb_count_case("RV32I+GC+*", 32) == expected


def test_zbb_standard_min_max_execute_on_rv32_b_and_star():
    expected = (0xFFFFFFFD, 5, 5, 0xFFFFFFFD)
    assert _run_zbb_minmax_case("RV32I+GC+B", 32) == expected
    assert _run_zbb_minmax_case("RV32I+GC+ZBB", 32) == expected
    assert _run_zbb_minmax_case("RV32I+GC+*", 32) == expected


def test_zbb_standard_sign_zero_extend_execute_on_rv32_b_and_star():
    expected = (0xFFFFFF80, 0xFFFFF080, 0x0000F080)
    assert _run_zbb_extend_case("RV32I+GC+B", 32) == expected
    assert _run_zbb_extend_case("RV32I+GC+ZBB", 32) == expected
    assert _run_zbb_extend_case("RV32I+GC+*", 32) == expected


def test_zbb_standard_orcb_rev8_execute_on_rv32_b_and_star():
    expected = (0xFF00FFFF, 0x03200010)
    assert _run_zbb_byte_case("RV32I+GC+B", 32) == expected
    assert _run_zbb_byte_case("RV32I+GC+ZBB", 32) == expected
    assert _run_zbb_byte_case("RV32I+GC+*", 32) == expected


def test_star_set_includes_zicond_extension_behavior():
    x3_star = _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0)
    assert x3_star == 0x55
    x3_star_64 = _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0)
    assert x3_star_64 == 0x55

    x3_star_nez = _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0)
    assert x3_star_nez == 0
    x3_star_nez2 = _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F)
    assert x3_star_nez2 == 0x55

    x3_star_64_nez = _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0)
    assert x3_star_64_nez == 0
    x3_star_64_nez2 = _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F)
    assert x3_star_64_nez2 == 0x55


def test_star_set_control_flow_instructions_are_not_perturbed_by_noisy_parser_on_rv32():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + GC + * + ??? + B + ZBA + UNKNOWN + m + a + M + C + F + D + zicond + ZICOND + zicsr + ZIFENCEI + ZBA + zifencei + "

    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(noisy_32, 32)


def test_star_set_control_flow_parser_noise_invariance_on_rv32_and_rv64():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + GC + * + ??? + B + ZBA + UNKNOWN + m + a + M + C + F + D + zicond + ZICOND + zicsr + ZIFENCEI + ZBA + zifencei + "
    noisy_64 = "  rv64i + GC + * + ??? + B + ZBA + UNKNOWN + m + a + M + C + F + D + zicond + ZICOND + zicsr + ZIFENCEI + ZBA + zifencei + "

    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(noisy_32, 32)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(explicit_64, 64)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(noisy_64, 64)

def test_star_set_jalr_parser_noise_invariance_on_rv32_and_rv64():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + GC + * + ??? + ZICOND + ZICSR + C + B + M + ZIFENCEI + A + F + D + unknown.token + "
    noisy_64 = "  rv64i + GC + * + ??? + ZICOND + ZICSR + C + B + M + ZIFENCEI + A + F + D + unknown.token + "

    assert _run_jalr_case("RV32I+GC+*", 32) == _run_jalr_case(explicit_32, 32)
    assert _run_jalr_case("RV32I+GC+*", 32) == _run_jalr_case(noisy_32, 32)

    assert _run_jalr_case("RV64I+GC+*", 64) == _run_jalr_case(explicit_64, 64)
    assert _run_jalr_case("RV64I+GC+*", 64) == _run_jalr_case(noisy_64, 64)


def test_star_fullset_runtime_parser_noise_is_stable_across_core_function_families():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + * + zba + ZBA + zbb + ??? + m + M + a + A + b + B + c + C + d + D + f + F + zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + unknown_token + "
    noisy_64 = "  rv64i + gc + * + zba + zbb + ??? + m + M + a + A + b + B + c + C + d + D + f + F + zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + unknown_token + "

    assert _run_case(explicit_32, 32) == _run_case(noisy_32, 32)
    assert _run_case(explicit_64, 64) == _run_case(noisy_64, 64)

    assert _run_base_case(explicit_32, 32) == _run_base_case(noisy_32, 32)
    assert _run_base_case(explicit_64, 64) == _run_base_case(noisy_64, 64)

    assert _run_extension_combo_case(explicit_32, 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case(explicit_64, 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_m_case(explicit_32, 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case(explicit_64, 64) == _run_m_case(noisy_64, 64)

    assert _run_mw_case(explicit_64, 64) == _run_mw_case(noisy_64, 64)
    assert _run_mw_edge_case(explicit_64, 64) == _run_mw_edge_case(noisy_64, 64)

    assert _run_control_flow_case(explicit_32, 32) == _run_control_flow_case(noisy_32, 32)
    assert _run_control_flow_case(explicit_64, 64) == _run_control_flow_case(noisy_64, 64)

    assert _run_jalr_case(explicit_32, 32) == _run_jalr_case(noisy_32, 32)
    assert _run_jalr_case(explicit_64, 64) == _run_jalr_case(noisy_64, 64)

    assert _run_u_type_case(explicit_32, 32) == _run_u_type_case(noisy_32, 32)
    assert _run_u_type_case(explicit_64, 64) == _run_u_type_case(noisy_64, 64)

    assert _run_fp_case(explicit_32, 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case(explicit_64, 64) == _run_fp_case(noisy_64, 64)
    assert _run_fp32_case(explicit_32, 32) == _run_fp32_case(noisy_32, 32)

    assert _run_d_case(explicit_32, 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case(explicit_64, 64) == _run_d_case(noisy_64, 64)

    assert _run_fp_width_case(explicit_32, 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case(explicit_64, 64) == _run_fp_width_case(noisy_64, 64)
    assert _run_fp_store_width_case(explicit_32, 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case(explicit_64, 64) == _run_fp_store_width_case(noisy_64, 64)

    assert _run_b_case(explicit_32, 32, funct3=0b111) == _run_b_case(noisy_32, 32, funct3=0b111)
    assert _run_b_case(explicit_64, 64, funct3=0b111) == _run_b_case(noisy_64, 64, funct3=0b111)

    assert _run_amo_op_case(explicit_32, 32, amofn=0, src_imm=0, init_mem=0x12345678) == _run_amo_op_case(noisy_32, 32, amofn=0, src_imm=0, init_mem=0x12345678)
    assert _run_amo_op_case(explicit_64, 64, amofn=0, src_imm=0, init_mem=0x123456789ABCDEF0) == _run_amo_op_case(noisy_64, 64, amofn=0, src_imm=0, init_mem=0x123456789ABCDEF0)

    assert _run_lr_sc_case(explicit_32, 32, funct3=0b010) == _run_lr_sc_case(noisy_32, 32, funct3=0b010)
    assert _run_lr_sc_case(explicit_64, 64, funct3=0b011) == _run_lr_sc_case(noisy_64, 64, funct3=0b011)

    assert _run_zicsr_case(explicit_32, 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case(explicit_64, 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zifencei_case(explicit_32, 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case(explicit_64, 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicond_case(explicit_32, 32, funct3=0b000, rs2=0) == _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case(explicit_64, 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0x0F)

    assert _run_multi_extension_mix_case(explicit_32, 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case(explicit_64, 64) == _run_multi_extension_mix_case(noisy_64, 64)



def test_star_fullset_control_memory_path_parity_on_rv32_and_rv64_with_noisy_parser_inputs():
    """RV32I+GC+* and RV64I+GC+* should keep control/memory/jal paths stable with noisy parser input."""

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i ",
        "+",
        "gc",
        "+",
        "???",
        "M",
        "A",
        "B",
        "C",
        "F",
        "D",
        "junk",
        "zicsr",
        "ZICSR",
        "zifencei",
        "ZIFENCEI",
        "zicond",
        "ZICOND",
        "",
        "*",
    )
    noisy_64 = (
        "  rv64i ",
        "+",
        "GC",
        "+",
        "???",
        "M",
        "A",
        "B",
        "C",
        "F",
        "D",
        "junk",
        "zicsr",
        "ZICSR",
        "zifencei",
        "ZIFENCEI",
        "zicond",
        "ZICOND",
        "",
        "*",
    )

    def noisy_generator_32():
        yield " rv32i "
        yield "+"
        yield "gc"
        yield "+"
        yield "M"
        yield "A"
        yield "B"
        yield "C"
        yield "F"
        yield "D"
        yield "ZICSR"
        yield "ZIFENCEI"
        yield "ZICOND"
        yield None

    def noisy_generator_64():
        yield " rv64i "
        yield "+"
        yield "GC"
        yield "+"
        yield "M"
        yield "A"
        yield "B"
        yield "C"
        yield "F"
        yield "D"
        yield "ZICSR"
        yield "ZIFENCEI"
        yield "ZICOND"
        yield None

    assert _run_jalr_case("RV32I+GC+*", 32) == _run_jalr_case(explicit_32, 32)
    assert _run_jalr_case("RV32I+GC+*", 32) == _run_jalr_case(noisy_32, 32)
    assert _run_jalr_case("RV32I+GC+*", 32) == _run_jalr_case(noisy_generator_32(), 32)

    assert _run_u_type_case("RV32I+GC+*", 32) == _run_u_type_case(explicit_32, 32)
    assert _run_u_type_case("RV32I+GC+*", 32) == _run_u_type_case(noisy_32, 32)
    assert _run_u_type_case("RV64I+GC+*", 64) == _run_u_type_case(explicit_64, 64)
    assert _run_u_type_case("RV64I+GC+*", 64) == _run_u_type_case(noisy_64, 64)
    assert _run_u_type_case("RV64I+GC+*", 64) == _run_u_type_case(noisy_generator_64(), 64)

    assert _run_load_case("RV32I+GC+*", 32) == _run_load_case(explicit_32, 32)
    assert _run_load_case("RV32I+GC+*", 32) == _run_load_case(noisy_32, 32)
    assert _run_load_case("RV64I+GC+*", 64) == _run_load_case(explicit_64, 64)
    assert _run_load_case("RV64I+GC+*", 64) == _run_load_case(noisy_64, 64)

    assert _run_store_case("RV32I+GC+*", 32) == _run_store_case(explicit_32, 32)
    assert _run_store_case("RV32I+GC+*", 32) == _run_store_case(noisy_32, 32)
    assert _run_store_case("RV64I+GC+*", 64) == _run_store_case(explicit_64, 64)
    assert _run_store_case("RV64I+GC+*", 64) == _run_store_case(noisy_64, 64)

    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(noisy_32, 32)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(explicit_64, 64)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(noisy_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(explicit_32, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(explicit_64, 64)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)


def test_star_fullset_sys_contract_parity_with_noisy_parser_inputs_rv32_and_rv64():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i",
        "+",
        "gc",
        "+",
        "M",
        "A",
        "B",
        "C",
        "F",
        "D",
        "zicsr",
        "zifencei",
        "zicond",
        "junk",
        "",
    )
    noisy_64 = (
        "rv64i",
        "+",
        "GC",
        "+",
        "M",
        "A",
        "B",
        "C",
        "F",
        "D",
        "ZICSR",
        "ZIFENCEI",
        "ZICOND",
        "junk",
        "",
    )

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(explicit_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(explicit_64, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0x00) == _run_zicond_case(explicit_32, 32, funct3=0b000, rs2=0x00)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0x00) == _run_zicond_case(explicit_64, 64, funct3=0b000, rs2=0x00)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0x0F)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(explicit_32, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(explicit_64, 64)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(explicit_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(explicit_64, 64)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)


def test_star_fullset_fp_width_and_store_width_contract_with_noisy_parser_inputs():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i ",
        "+",
        "GC",
        "+",
        "M",
        "A",
        "B",
        "junk",
        "",
        "C",
        "F",
        "D",
        "ZICSR",
        "zifencei",
        "ZICOND",
        "*",
    )
    noisy_64 = (
        "  rv64i ",
        "+",
        "gc",
        "+",
        "M",
        "A",
        "B",
        "junk",
        "",
        "C",
        "F",
        "D",
        "ZICSR",
        "ZIFENCEI",
        "ZICOND",
        "*",
    )

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(explicit_32, 32)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(explicit_64, 64)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(explicit_32, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(explicit_64, 64)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)


def test_star_fullset_fp32_and_branch_noisy_parser_stability_on_rv32_and_rv64():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "RV32I",
        "+",
        "GC",
        "+",
        "M",
        "A",
        "B",
        "C",
        "F",
        "D",
        "junk",
        "",
        "ZICSR",
        "ZIFENCEI",
        "ZICOND",
    )
    noisy_64 = (
        "RV64I",
        "+",
        "gc",
        "+",
        "M",
        "A",
        "B",
        "C",
        "F",
        "D",
        "junk",
        "",
        "ZICSR",
        "ZIFENCEI",
        "ZICOND",
    )

    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(explicit_32, 32)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(noisy_32, 32)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(explicit_64, 64)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(noisy_64, 64)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(explicit_32, 32, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(noisy_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(explicit_64, 64, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(noisy_64, 64, funct3=0b111)

def _run_jalr_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 2, 0b000, 0, 0x18),    # x2 = 24 (target word 6)
        enc_i(JALR, 5, 0b000, 2, 0),        # JALR x5, 0(x2), x5 = return addr
        enc_i(OP_IMM, 4, 0b000, 0, 0x77),    # executed after return
        nop(),
        nop(),
        nop(),
        enc_i(OP_IMM, 6, 0b000, 0, 0x66),    # callee writes x6
        enc_i(JALR, 0, 0b000, 5, 0),        # return to x5
        nop(),
    ]

    imem_words = 32
    prog = prog + [nop()] * (imem_words - len(prog))

    class _JalrBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _JalrBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(240):
            yield Tick()

        for reg in (4, 5, 6):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x4"], result["x5"], result["x6"]


def _run_jal_case(extensions, xlen):
    prog = [
        enc_jal(5, 12),                         # x5 = pc + 4, jump to target at pc 12
        enc_i(OP_IMM, 3, 0b000, 0, 0x33),       # skipped by JAL
        enc_i(OP_IMM, 4, 0b000, 0, 0x44),       # skipped by JAL
        enc_i(OP_IMM, 6, 0b000, 0, 0x66),       # target
        enc_jal(0, 0),                          # hold target state stable
    ]

    imem_words = 32
    prog = prog + [nop()] * (imem_words - len(prog))

    class _JalBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _JalBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(160):
            yield Tick()
        for reg in (3, 4, 5, 6):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"], result["x6"]


def test_rv32i_standard_jal_writes_link_and_redirects():
    assert _run_jal_case("RV32I+GC", 32) == (0, 0, 4, 0x66)
    assert _run_jal_case("RV32I+GC+*", 32) == (0, 0, 4, 0x66)



def _run_u_type_case(extensions, xlen):
    prog = [
        enc_u(LUI, 1, 0x12345),    # x1 = 0x12345000
        enc_i(OP_IMM, 2, 0b000, 0, 4),  # x2 = 4
        enc_u(AUIPC, 3, 0x1),      # x3 = pc(8)+0x1000 = 0x1008 on first three-instruction window
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _UTypeBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _UTypeBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(140):
            yield Tick()
        for reg in (1, 2, 3):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x1"], result["x2"], result["x3"]


def _run_auipc_dependency_case(extensions, xlen):
    prog = [
        enc_u(AUIPC, 3, 0x1),              # x3 = pc(0)+0x1000
        enc_i(OP_IMM, 4, 0b000, 3, 7),     # x4 = x3 + 7, adjacent AUIPC dependency
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _AuipcDependencyBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _AuipcDependencyBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(120):
            yield Tick()
        for reg in (3, 4):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"]


def _run_lui_dependency_case(extensions, xlen):
    prog = [
        enc_u(LUI, 3, 0x12345),             # x3 = 0x12345000
        enc_i(OP_IMM, 4, 0b000, 3, 0x123),  # x4 = x3 + 0x123, adjacent LUI dependency
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _LuiDependencyBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _LuiDependencyBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(120):
            yield Tick()
        for reg in (3, 4):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"]


def test_rv32i_standard_lui_dependency_executes_without_scoreboard_hole():
    assert _run_lui_dependency_case("RV32I+GC", 32) == (0x12345000, 0x12345123)
    assert _run_lui_dependency_case("RV32I+GC+*", 32) == (0x12345000, 0x12345123)


def _run_add_sub_reg_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 7),              # x1 = 7
        enc_i(OP_IMM, 2, 0b000, 0, 11),             # x2 = 11
        nop(),
        nop(),
        enc_r(OP, 3, 0b000, 1, 2, 0b0000000),       # add x3, x1, x2 = 18
        enc_r(OP, 4, 0b000, 2, 1, 0b0100000),       # sub x4, x2, x1 = 4
        enc_r(OP, 5, 0b000, 1, 2, 0b0100000),       # sub x5, x1, x2 = -4
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _AddSubRegBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _AddSubRegBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(150):
            yield Tick()
        for reg in (3, 4, 5):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"]


def test_rv32i_standard_add_sub_registers_execute_add_and_sub():
    assert _run_add_sub_reg_case("RV32I+GC", 32) == (18, 4, 0xFFFF_FFFC)
    assert _run_add_sub_reg_case("RV32I+GC+*", 32) == (18, 4, 0xFFFF_FFFC)


def _run_x0_invariance_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 0, 0b000, 0, 7),              # addi x0, x0, 7
        enc_i(OP_IMM, 1, 0b000, 0, 3),              # x1 = 3
        enc_i(OP_IMM, 2, 0b000, 0, 4),              # x2 = 4
        nop(),
        nop(),
        enc_r(OP, 0, 0b000, 1, 2, 0b0000000),       # add x0, x1, x2
        enc_i(LOAD, 0, 0b010, 0, 0),                # lw x0, 0(x0)
        enc_jal(0, 8),                              # jal x0, target
        enc_i(OP_IMM, 3, 0b000, 0, 0x33),           # skipped by JAL
        enc_i(OP_IMM, 4, 0b000, 0, 0x44),           # target
        enc_jal(0, 0),                              # hold final state stable
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _X0InvarianceBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
            self.dmem = SimpleDMem(words=16, init=[0xFFFF_FFFF] + [0] * 15)

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

    dut = _X0InvarianceBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(220):
            yield Tick()
        for reg in (0, 3, 4):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x0"], result["x3"], result["x4"]


def test_rv32i_standard_x0_remains_zero_across_writeback_paths():
    assert _run_x0_invariance_case("RV32I+GC", 32) == (0, 0, 0x44)
    assert _run_x0_invariance_case("RV32I+GC+*", 32) == (0, 0, 0x44)


def _run_shift_imm_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, -8),       # x1 = 0xfffffff8
        nop(),
        nop(),
        enc_i(OP_IMM, 2, 0b101, 1, 1),        # srli x2, x1, 1 = 0x7ffffffc
        enc_i(OP_IMM, 3, 0b101, 1, 0x401),    # srai x3, x1, 1 = 0xfffffffc
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _ShiftImmBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _ShiftImmBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(140):
            yield Tick()
        for reg in (2, 3):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x2"], result["x3"]


def test_rv32i_standard_shift_immediates_distinguish_srli_and_srai():
    assert _run_shift_imm_case("RV32I+GC", 32) == (0x7FFFFFFC, 0xFFFFFFFC)
    assert _run_shift_imm_case("RV32I+GC+*", 32) == (0x7FFFFFFC, 0xFFFFFFFC)


def _run_shift_reg_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, -8),             # x1 = 0xfffffff8
        enc_i(OP_IMM, 2, 0b000, 0, 1),              # x2 = 1
        nop(),
        nop(),
        enc_r(OP, 3, 0b001, 1, 2, 0b0000000),       # sll x3, x1, x2 = 0xfffffff0
        enc_r(OP, 4, 0b101, 1, 2, 0b0000000),       # srl x4, x1, x2 = 0x7ffffffc
        enc_r(OP, 5, 0b101, 1, 2, 0b0100000),       # sra x5, x1, x2 = 0xfffffffc
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _ShiftRegBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _ShiftRegBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(150):
            yield Tick()
        for reg in (3, 4, 5):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"]


def test_rv32i_standard_shift_registers_execute_sll_srl_sra():
    assert _run_shift_reg_case("RV32I+GC", 32) == (0xFFFF_FFF0, 0x7FFF_FFFC, 0xFFFF_FFFC)
    assert _run_shift_reg_case("RV32I+GC+*", 32) == (0xFFFF_FFF0, 0x7FFF_FFFC, 0xFFFF_FFFC)


def _run_logic_imm_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0x0F0),   # x1 = 0x0f0
        nop(),
        nop(),
        enc_i(OP_IMM, 2, 0b100, 1, 0x0FF),   # xori x2, x1, 0x0ff = 0x00f
        enc_i(OP_IMM, 3, 0b110, 1, 0x00F),   # ori  x3, x1, 0x00f = 0x0ff
        enc_i(OP_IMM, 4, 0b111, 1, 0x033),   # andi x4, x1, 0x033 = 0x030
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _LogicImmBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _LogicImmBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(140):
            yield Tick()
        for reg in (2, 3, 4):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x2"], result["x3"], result["x4"]


def test_rv32i_standard_logic_immediates_execute_xori_ori_andi():
    assert _run_logic_imm_case("RV32I+GC", 32) == (0x00F, 0x0FF, 0x030)
    assert _run_logic_imm_case("RV32I+GC+*", 32) == (0x00F, 0x0FF, 0x030)


def _run_logic_reg_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0x0F0),          # x1 = 0x000000f0
        enc_i(OP_IMM, 2, 0b000, 0, -0x0F1),         # x2 = 0xffffff0f
        nop(),
        nop(),
        enc_r(OP, 3, 0b100, 1, 2, 0b0000000),       # xor x3, x1, x2 = 0xffffffff
        enc_r(OP, 4, 0b110, 1, 2, 0b0000000),       # or  x4, x1, x2 = 0xffffffff
        enc_r(OP, 5, 0b111, 1, 2, 0b0000000),       # and x5, x1, x2 = 0x00000000
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _LogicRegBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _LogicRegBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(150):
            yield Tick()
        for reg in (3, 4, 5):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"]


def test_rv32i_standard_logic_registers_execute_xor_or_and():
    assert _run_logic_reg_case("RV32I+GC", 32) == (0xFFFF_FFFF, 0xFFFF_FFFF, 0)
    assert _run_logic_reg_case("RV32I+GC+*", 32) == (0xFFFF_FFFF, 0xFFFF_FFFF, 0)


def _run_set_less_than_imm_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, -1),      # x1 = -1 / 0xffffffff
        enc_i(OP_IMM, 4, 0b000, 0, 1),       # x4 = 1
        nop(),
        nop(),
        enc_i(OP_IMM, 2, 0b010, 1, 1),       # slti  x2, x1, 1  = 1 (-1 < 1)
        enc_i(OP_IMM, 3, 0b011, 1, 1),       # sltiu x3, x1, 1  = 0 (0xffffffff < 1)
        enc_i(OP_IMM, 5, 0b011, 4, -1),      # sltiu x5, x4, -1 = 1 (1 < 0xffffffff)
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _SetLessThanImmBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _SetLessThanImmBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(150):
            yield Tick()
        for reg in (2, 3, 5):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x2"], result["x3"], result["x5"]


def test_rv32i_standard_set_less_than_immediates_distinguish_signed_unsigned():
    assert _run_set_less_than_imm_case("RV32I+GC", 32) == (1, 0, 1)
    assert _run_set_less_than_imm_case("RV32I+GC+*", 32) == (1, 0, 1)


def _run_set_less_than_reg_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, -1),             # x1 = -1 / 0xffffffff
        enc_i(OP_IMM, 2, 0b000, 0, 1),              # x2 = 1
        nop(),
        nop(),
        enc_r(OP, 3, 0b010, 1, 2, 0b0000000),       # slt  x3, x1, x2 = 1 (-1 < 1)
        enc_r(OP, 4, 0b011, 1, 2, 0b0000000),       # sltu x4, x1, x2 = 0 (0xffffffff < 1)
        enc_r(OP, 5, 0b011, 2, 1, 0b0000000),       # sltu x5, x2, x1 = 1 (1 < 0xffffffff)
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _SetLessThanRegBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _SetLessThanRegBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(150):
            yield Tick()
        for reg in (3, 4, 5):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"], result["x4"], result["x5"]


def test_rv32i_standard_set_less_than_registers_distinguish_signed_unsigned():
    assert _run_set_less_than_reg_case("RV32I+GC", 32) == (1, 0, 1)
    assert _run_set_less_than_reg_case("RV32I+GC+*", 32) == (1, 0, 1)


def test_rv32i_standard_auipc_dependency_executes_without_scoreboard_hole():
    assert _run_auipc_dependency_case("RV32I+GC", 32) == (0x1100, 0x1107)
    assert _run_auipc_dependency_case("RV32I+GC+*", 32) == (0x1100, 0x1107)


def _run_jalr_dependency_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0x214),  # x1 = target pc
        enc_i(JALR, 5, 0b000, 1, 0),        # x5 = return pc, jump to x1
        enc_i(OP_IMM, 6, 0b000, 0, 1),      # skipped by JALR
        enc_i(OP_IMM, 6, 0b000, 0, 2),      # skipped by JALR
        nop(),                              # skipped by JALR
        enc_i(OP_IMM, 6, 0b000, 5, 3),      # x6 = x5 + 3, adjacent target-side dependency
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _JalrDependencyBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
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

    dut = _JalrDependencyBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(160):
            yield Tick()
        for reg in (5, 6):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return bool(result["x5"]), result["x6"] - result["x5"]


def test_rv32i_standard_jalr_dependency_executes_without_scoreboard_hole():
    assert _run_jalr_dependency_case("RV32I+GC", 32) == (True, 3)
    assert _run_jalr_dependency_case("RV32I+GC+*", 32) == (True, 3)


def _run_load_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0),
        enc_i(LOAD, 3, 0b010, 1, 0),
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _LoadCaseBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
            self.dmem = SimpleDMem(words=16, init=[0x5A5A5A5A])

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

    dut = _LoadCaseBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(180):
            yield Tick()
        yield c.dbg_reg_addr.eq(3)
        yield Tick()
        result["x3"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x3"]


def _run_store_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0),       # x1 = 0
        enc_i(OP_IMM, 2, 0b000, 0, 0x11),    # x2 = 0x11
        enc_s(STORE, 0b000, 1, 2, 0),        # sb x2, 0(x1)
        enc_i(OP_IMM, 2, 0b000, 0, 0x22),    # x2 = 0x22
        enc_s(STORE, 0b000, 1, 2, 1),        # sb x2, 1(x1)
        enc_i(OP_IMM, 2, 0b000, 0, 0x33),    # x2 = 0x33
        enc_s(STORE, 0b000, 1, 2, 2),        # sb x2, 2(x1)
        enc_i(OP_IMM, 2, 0b000, 0, 0x44),    # x2 = 0x44
        enc_s(STORE, 0b000, 1, 2, 3),        # sb x2, 3(x1)
        enc_i(LOAD, 3, 0b010, 1, 0),         # x3 = 0x44332211
        enc_i(OP_IMM, 7, 0b000, 0, 0x5A6),   # x7 = 0x05A6
        enc_s(STORE, 0b001, 1, 7, 4),        # sh x7, 4(x1)
        enc_i(OP_IMM, 7, 0b000, 0, 0x7BC),   # x7 = 0x07BC
        enc_s(STORE, 0b001, 1, 7, 6),        # sh x7, 6(x1)
        enc_i(LOAD, 4, 0b010, 1, 4),         # x4 = 0x07BC05A6
        enc_i(OP_IMM, 10, 0b000, 0, 0x123),  # x10 = 0x123
        enc_s(STORE, 0b010, 1, 10, 8),       # sw x10, 8(x1)
        enc_i(LOAD, 5, 0b010, 1, 8),         # x5 = 0x00000123
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _StoreCaseBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions, rb_mode=1)
            self.imem = SimpleIMem(words=imem_words, init=prog)
            self.dmem = SimpleDMem(words=16, init=[0x0, 0x0, 0x0, 0x0])

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

    dut = _StoreCaseBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(180):
            yield Tick()
        for reg in (3, 4, 5):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return (
        result["x3"],
        result["x4"],
        result["x5"],
    )


def test_rv32i_standard_store_widths_execute_byte_halfword_and_word_lanes():
    expected = (
        0x44332211,
        0x07BC05A6,
        0x00000123,
    )

    assert _run_store_case("RV32I+GC", 32) == expected
    assert _run_store_case("RV32I+GC+*", 32) == expected


def _run_load_width_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0),        # x1 = base address 0
        nop(),
        nop(),
        enc_i(LOAD, 6, 0b010, 1, 0),          # lw  x6, 0(x1) = 0x800180ff
        nop(),
        enc_i(LOAD, 2, 0b000, 1, 0),          # lb  x2, 0(x1) = sign_extend(0xff)
        nop(),
        enc_i(LOAD, 3, 0b100, 1, 0),          # lbu x3, 0(x1) = zero_extend(0xff)
        nop(),
        enc_i(LOAD, 4, 0b001, 1, 0),          # lh  x4, 0(x1) = sign_extend(0x80ff)
        nop(),
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _LoadWidthBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
            self.dmem = SimpleDMem(words=16, init=[0x8001_80FF] + [0] * 15)

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

    dut = _LoadWidthBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(180):
            yield Tick()
        for reg in (2, 3, 4, 6):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x2"], result["x3"], result["x4"], result["x6"]


def test_rv32i_standard_load_signed_widths_and_unsigned_byte_execute():
    expected = (
        0xFFFF_FFFF,
        0x0000_00FF,
        0xFFFF_80FF,
        0x8001_80FF,
    )

    assert _run_load_width_case("RV32I+GC", 32) == expected
    assert _run_load_width_case("RV32I+GC+*", 32) == expected


def _run_lhu_case(extensions, xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 0),        # x1 = base address 0
        nop(),
        nop(),
        enc_i(LOAD, 2, 0b101, 1, 0),          # lhu x2, 0(x1) = zero_extend(0x80ff)
        enc_i(LOAD, 3, 0b101, 1, 2),          # lhu x3, 2(x1) = zero_extend(0x8001)
        nop(),
    ]

    imem_words = 64
    prog = prog + [nop()] * (imem_words - len(prog))

    class _LhuBench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=extensions)
            self.imem = SimpleIMem(words=imem_words, init=prog)
            self.dmem = SimpleDMem(words=16, init=[0x8001_80FF] + [0] * 15)

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

    dut = _LhuBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core
    result = {}

    def proc():
        for _ in range(180):
            yield Tick()
        for reg in (2, 3):
            yield c.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield c.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result["x2"], result["x3"]


def test_rv32i_standard_lhu_zero_extends_low_and_high_halfwords():
    assert _run_lhu_case("RV32I+GC", 32) == (0x0000_80FF, 0x0000_8001)
    assert _run_lhu_case("RV32I+GC+*", 32) == (0x0000_80FF, 0x0000_8001)


def test_star_set_u_type_parser_noise_invariance_on_rv32():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + GC + * + ??? + ZICOND + ZICSR + C + B + M + ZIFENCEI + A + F + D + unknown.token + "

    assert _run_u_type_case("RV32I+GC+*", 32) == _run_u_type_case(explicit_32, 32)
    assert _run_u_type_case("RV32I+GC+*", 32) == _run_u_type_case(noisy_32, 32)


def test_star_set_u_type_parser_noise_invariance_on_rv32_and_rv64():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + GC + * + ??? + ZICOND + ZICSR + C + B + M + ZIFENCEI + A + F + D + unknown.token + "
    noisy_64 = "  rv64i + GC + * + ??? + ZICOND + ZICSR + C + B + M + ZIFENCEI + A + F + D + unknown.token + "

    assert _run_u_type_case("RV32I+GC+*", 32) == _run_u_type_case(explicit_32, 32)
    assert _run_u_type_case("RV32I+GC+*", 32) == _run_u_type_case(noisy_32, 32)
    assert _run_u_type_case("RV64I+GC+*", 64) == _run_u_type_case(explicit_64, 64)
    assert _run_u_type_case("RV64I+GC+*", 64) == _run_u_type_case(noisy_64, 64)


def test_star_set_b_parser_noise_invariance_on_rv32_and_rv64():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + GC + * + ??? + ZICOND + ZICSR + C + M + ZIFENCEI + A + F + D + ZBA + ZBKB + B + unknown.token + "
    noisy_64 = "  rv64i + GC + * + ??? + ZICOND + ZICSR + C + M + ZIFENCEI + A + F + D + ZBA + ZBKB + B + unknown.token + "

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(explicit_32, 32, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(explicit_64, 64, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_64, 64, funct3=0b110)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(explicit_32, 32, funct3=0b100)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(noisy_32, 32, funct3=0b100)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b100) == _run_b_case(explicit_64, 64, funct3=0b100)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b100) == _run_b_case(noisy_64, 64, funct3=0b100)


def test_zicond_and_zicsr_extensions_execute_on_rv32_and_rv64():
    x3_32 = _run_zicond_case("RV32I+GC+ZICSR+ZICOND", 32, funct3=0b001, rs2=0x0F)
    assert x3_32 == 0

    x3_64 = _run_zicond_case("RV64I+GC+ZICSR+ZICOND", 64, funct3=0b001, rs2=0)
    assert x3_64 == 0x55


def test_zba_alias_maps_to_b_extension_runtime_behavior():
    x3 = _run_b_case("RV32I+GC+ZBA", 32, funct3=0b110)
    expected32 = 0x123 | (~0x0F & ((1 << 32) - 1))
    assert x3 == expected32
    x3_64 = _run_b_case("RV64I+GC+ZBA", 64, funct3=0b110)
    expected64 = 0x123 | (~0x0F & ((1 << 64) - 1))
    assert x3_64 == expected64


def test_zbkb_generic_alias_maps_to_b_extension_runtime_behavior():
    x3 = _run_b_case("RV32I+GC+ZBKB", 32, funct3=0b100)
    expected32 = (~(0x123 ^ 0x0F) & ((1 << 32) - 1))
    assert x3 == expected32
    x3_64 = _run_b_case("RV64I+GC+ZBKB", 64, funct3=0b100)
    expected64 = (~(0x123 ^ 0x0F) & ((1 << 64) - 1))
    assert x3_64 == expected64


def test_zbb_and_zbs_aliases_map_to_b_runtime_behavior():
    x3_zbb_32 = _run_b_case("RV32I+GC+ZBB", 32, funct3=0b110)
    x3_zbb_64 = _run_b_case("RV64I+GC+ZBB", 64, funct3=0b110)
    expected32 = 0x123 | (~0x0F & ((1 << 32) - 1))
    expected64 = 0x123 | (~0x0F & ((1 << 64) - 1))
    assert x3_zbb_32 == expected32
    assert x3_zbb_64 == expected64

    x3_zbs_32 = _run_b_case("RV32I+GC+ZBS", 32, funct3=0b111)
    x3_zbs_64 = _run_b_case("RV64I+GC+ZBS", 64, funct3=0b111)
    assert x3_zbs_32 == (0x123 & (~0x0F & ((1 << 32) - 1)))
    assert x3_zbs_64 == (0x123 & (~0x0F & ((1 << 64) - 1)))


def test_zbk_and_zbh_aliases_map_to_b_runtime_behavior():
    x3_zbk_32 = _run_b_case("RV32I+GC+ZBK", 32, funct3=0b100)
    x3_zbk_64 = _run_b_case("RV64I+GC+ZBK", 64, funct3=0b100)
    expected32 = (~(0x123 ^ 0x0F) & ((1 << 32) - 1))
    expected64 = (~(0x123 ^ 0x0F) & ((1 << 64) - 1))
    assert x3_zbk_32 == expected32
    assert x3_zbk_64 == expected64

    x3_zbh_32 = _run_b_case("RV32I+GC+ZBH", 32, funct3=0b110)
    x3_zbh_64 = _run_b_case("RV64I+GC+ZBH", 64, funct3=0b110)
    expected32_orn = 0x123 | (~0x0F & ((1 << 32) - 1))
    expected64_orn = 0x123 | (~0x0F & ((1 << 64) - 1))
    assert x3_zbh_32 == expected32_orn
    assert x3_zbh_64 == expected64_orn


def test_zbe_zbf_zbm_aliases_map_to_b_runtime_behavior():
    x3_zbe_32 = _run_b_case("RV32I+GC+ZBE", 32, funct3=0b100)
    x3_zbe_64 = _run_b_case("RV64I+GC+ZBE", 64, funct3=0b100)
    expected32_xnor = (~(0x123 ^ 0x0F) & ((1 << 32) - 1))
    expected64_xnor = (~(0x123 ^ 0x0F) & ((1 << 64) - 1))
    assert x3_zbe_32 == expected32_xnor
    assert x3_zbe_64 == expected64_xnor

    x3_zbf_32 = _run_b_case("RV32I+GC+ZBF", 32, funct3=0b111)
    x3_zbf_64 = _run_b_case("RV64I+GC+ZBF", 64, funct3=0b111)
    assert x3_zbf_32 == (0x123 & (~0x0F & ((1 << 32) - 1)))
    assert x3_zbf_64 == (0x123 & (~0x0F & ((1 << 64) - 1)))

    x3_zbm_32 = _run_b_case("RV32I+GC+ZBM", 32, funct3=0b110)
    x3_zbm_64 = _run_b_case("RV64I+GC+ZBM", 64, funct3=0b110)
    expected32_orn = 0x123 | (~0x0F & ((1 << 32) - 1))
    expected64_orn = 0x123 | (~0x0F & ((1 << 64) - 1))
    assert x3_zbm_32 == expected32_orn
    assert x3_zbm_64 == expected64_orn


def test_zbc_alias_maps_to_b_extension_runtime_behavior():
    """ZBC should be accepted on top of GC as a B-compatible bit-manipulation subset."""

    x3_zbc_32_andn = _run_b_case("RV32I+GC+ZBC", 32, funct3=0b111)
    x3_zbc_64_andn = _run_b_case("RV64I+GC+ZBC", 64, funct3=0b111)
    expected32_andn = (0x123 & (~0x0F & ((1 << 32) - 1)))
    expected64_andn = (0x123 & (~0x0F & ((1 << 64) - 1)))
    assert x3_zbc_32_andn == expected32_andn
    assert x3_zbc_64_andn == expected64_andn

    x3_zbc_32_xnor = _run_b_case("RV32I+GC+ZBC", 32, funct3=0b100)
    x3_zbc_64_xnor = _run_b_case("RV64I+GC+ZBC", 64, funct3=0b100)
    expected32_xnor = (~(0x123 ^ 0x0F) & ((1 << 32) - 1))
    expected64_xnor = (~(0x123 ^ 0x0F) & ((1 << 64) - 1))
    assert x3_zbc_32_xnor == expected32_xnor
    assert x3_zbc_64_xnor == expected64_xnor


def test_more_zb_aliases_map_to_b_runtime_behavior():
    expected32_andn = (0x123 & (~0x0F & ((1 << 32) - 1)))
    expected64_andn = (0x123 & (~0x0F & ((1 << 64) - 1)))
    expected32_xnor = (~(0x123 ^ 0x0F) & ((1 << 32) - 1))
    expected64_xnor = (~(0x123 ^ 0x0F) & ((1 << 64) - 1))
    expected32_orn = 0x123 | (~0x0F & ((1 << 32) - 1))
    expected64_orn = 0x123 | (~0x0F & ((1 << 64) - 1))

    # aliases mapped to B should keep same runtime behavior as explicit B
    for alias in ("ZBG", "ZBL", "ZBN", "ZBP", "ZBR", "ZBT", "ZBU", "ZBV", "ZBX", "ZBZ", "ZBI"):
        x3_xnor_32 = _run_b_case(f"RV32I+GC+{alias}", 32, funct3=0b100)
        x3_xnor_64 = _run_b_case(f"RV64I+GC+{alias}", 64, funct3=0b100)
        assert x3_xnor_32 == expected32_xnor
        assert x3_xnor_64 == expected64_xnor

        x3_andn_32 = _run_b_case(f"RV32I+GC+{alias}", 32, funct3=0b111)
        x3_andn_64 = _run_b_case(f"RV64I+GC+{alias}", 64, funct3=0b111)
        assert x3_andn_32 == expected32_andn
        assert x3_andn_64 == expected64_andn

        x3_orn_32 = _run_b_case(f"RV32I+GC+{alias}", 32, funct3=0b110)
        x3_orn_64 = _run_b_case(f"RV64I+GC+{alias}", 64, funct3=0b110)
        assert x3_orn_32 == expected32_orn
        assert x3_orn_64 == expected64_orn


def test_noisy_star_extension_specification_executes_standard_set_on_both_xlen():
    expected32_32 = _run_zifencei_case("RV32I+GC+ZICSR+ZIFENCEI", 32)
    expected32_noisy = _run_zifencei_case("  rv32i + gc + ??? + ZICSR + ZIFENCEI + ZICOND + B + b + ZBA + zbkb + B +  ", 32)
    assert expected32_noisy == expected32_32

    expected64_64 = _run_zifencei_case("RV64I+GC+ZICSR+ZIFENCEI", 64)
    expected64_noisy = _run_zifencei_case("  rv64i + gc + ??? + ZICSR + ZIFENCEI + ZICOND + B + b + ZBA + zbkb + B +  ", 64)
    assert expected64_noisy == expected64_64


def test_noisy_extension_specification_executes_m_and_a_runtime_on_rv32_and_rv64():
    expected_m32 = _run_m_case("RV32I+GC+M", 32)
    noisy_m32 = _run_m_case("  rv32i + gc + ??? + m + B + ZBB + ZBK + M +  ", 32)
    assert noisy_m32 == expected_m32

    expected_a64 = _run_amo_ops_case("RV64I+GC+A", 64)
    noisy_a64 = _run_amo_ops_case("  rv64i + gc + ??? + a + B + ZBH + A + ZBK + A +  ", 64)
    assert noisy_a64 == expected_a64


def test_noisy_extension_specification_executes_zicond_runtime_on_rv32_and_rv64():
    expected_zicond_32 = _run_zicond_case("RV32I+GC+ZICOND", 32, funct3=0b001, rs2=0)
    noisy_zicond_32 = _run_zicond_case("  rv32i + gc + ??? + ZICOND + b + ZBA + a + ZBH + B +  ", 32, funct3=0b001, rs2=0)
    assert noisy_zicond_32 == expected_zicond_32

    expected_zicond_64 = _run_zicond_case("RV64I+GC+ZICOND", 64, funct3=0b001, rs2=0)
    noisy_zicond_64 = _run_zicond_case("  rv64i + gc + ??? + ZICOND + b + ZBA + a + ZBH + B +  ", 64, funct3=0b001, rs2=0)
    assert noisy_zicond_64 == expected_zicond_64


def test_star_includes_full_standard_set_even_with_unknown_tokens_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + B + ZBA + ZBH + XFOO + A + m + zicsr + zifencei + C + F + D + ZICOND + M + "
    noisy_64 = "  rv64i + gc + ??? + C + F + ZBH + ZBA + UNKNOWN + m + A + zicsr + zifencei + B + D + ZICOND + "

    rv32_star = _run_extension_combo_case("RV32I+GC+*", 32)
    rv32_noisy = _run_extension_combo_case(noisy_32, 32)
    rv32_full = _run_extension_combo_case(full_32, 32)
    assert rv32_star == rv32_full
    assert rv32_star == rv32_noisy

    rv64_star = _run_extension_combo_case("RV64I+GC+*", 64)
    rv64_noisy = _run_extension_combo_case(noisy_64, 64)
    rv64_full = _run_extension_combo_case(full_64, 64)
    assert rv64_star == rv64_full
    assert rv64_star == rv64_noisy


def test_star_fullset_consistency_for_rv32_with_duplicate_unknown_and_alias_noise():
    explicit = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_noisy = "  rv32i + gc + ??? + m + A + B + C + F + D + ZICSR + ZIFENCEI + ZICOND + zbh + zbk + "
    noisy_star = "  RV32I + GC + * + M + A + B + B + zba + zbb + zbs + ZBK + ZBH + unknown.ext + ZICSR + zifencei + zicond + "

    rv32_star = _run_extension_combo_case("RV32I+GC+*", 32)
    rv32_noisy = _run_extension_combo_case(noisy_star, 32)
    rv32_explicit = _run_extension_combo_case(explicit, 32)
    rv32_explicit_noisy = _run_extension_combo_case(explicit_noisy, 32)

    assert rv32_star == rv32_explicit
    assert rv32_star == rv32_noisy
    assert rv32_star == rv32_explicit_noisy


def test_star_not_add_nonstandard_behavior_for_rv32_base_path():
    base_32 = "RV32I+GC"
    noisy_base_32 = "  rv32i + gc + ??? + ZICOND + ZIFENCEI + ZBA + ZBB + "
    alias_base_32 = "  RV32I + GC + "

    base_no_star = _run_extension_combo_case(base_32, 32)
    noisy_base = _run_extension_combo_case(noisy_base_32, 32)
    alias_base = _run_extension_combo_case(alias_base_32, 32)
    star_32 = _run_extension_combo_case("RV32I+GC+*", 32)

    assert base_no_star == noisy_base
    assert base_no_star == alias_base
    assert star_32 != base_no_star


def test_star_not_add_nonstandard_behavior_for_rv64_base_path():
    base_64 = "RV64I+GC"
    noisy_base_64 = "  rv64i + gc + ??? + zicond + zifencei + zbak + zbs + ZBA + "
    alias_base_64 = "  RV64I + GC + "

    base_no_star = _run_extension_combo_case(base_64, 64)
    noisy_base = _run_extension_combo_case(noisy_base_64, 64)
    alias_base = _run_extension_combo_case(alias_base_64, 64)
    star_64 = _run_extension_combo_case("RV64I+GC+*", 64)

    assert base_no_star == noisy_base
    assert base_no_star == alias_base
    assert star_64 != base_no_star


def test_star_fullset_aligns_with_explicit_m_a_zicsr_set_for_rv32_under_noise():
    explicit_ma_zicsr = "RV32I+GC+M+A+ZICSR"
    noisy_explicit_ma = "  rv32i + gc + ??? + M + A + ZICSR + B + ZBA + m + a + ZBH + "
    noisy_star = "  RV32I + GC + * + UNKNOWN + ZICSR + B + M + m + ZBA + ZBB + A + a + "

    explicit_result = _run_extension_combo_case(explicit_ma_zicsr, 32)
    noisy_explicit_result = _run_extension_combo_case(noisy_explicit_ma, 32)
    star_result = _run_extension_combo_case(noisy_star, 32)

    assert noisy_explicit_result == explicit_result
    assert star_result == explicit_result


def test_star_fullset_aligns_with_explicit_m_a_zicsr_set_for_rv64_under_noise():
    explicit_ma_zicsr = "RV64I+GC+M+A+ZICSR"
    noisy_explicit_ma = "  rv64i + gc + ??? + a + M + zicsr + ZBA + b + ZBH + m + ZICOND + "
    noisy_star = "  RV64I + GC + * + ??? + ZICSR + M + m + ZBA + ZBB + A + a + B + C + "

    explicit_result = _run_extension_combo_case(explicit_ma_zicsr, 64)
    noisy_explicit_result = _run_extension_combo_case(noisy_explicit_ma, 64)
    star_result = _run_extension_combo_case(noisy_star, 64)

    assert noisy_explicit_result == explicit_result
    assert star_result == explicit_result


def test_star_rv32_fullset_matches_explicit_bundle_under_noisy_aliases():
    explicit_full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_explicit_32 = "  rv32i + gc + ??? + zicsr + A + a + zicond + ZICSR + B + b + M + m + C + F + f + D + d + ZIFENCEI + ZBA + "
    noisy_star_32 = "  RV32I + GC + * + ??? + zicond + zifencei + ZICSR + ZBA + ZBB + M + m + A + a + B + C + F + f + D + d + "

    star_32 = "RV32I+GC+*"

    assert _run_extension_combo_case(star_32, 32) == _run_extension_combo_case(explicit_full_32, 32)
    assert _run_extension_combo_case(star_32, 32) == _run_extension_combo_case(noisy_explicit_32, 32)
    assert _run_extension_combo_case(star_32, 32) == _run_extension_combo_case(noisy_star_32, 32)

    assert _run_fp_case(star_32, 32) == _run_fp_case(explicit_full_32, 32)
    assert _run_fp_case(star_32, 32) == _run_fp_case(noisy_explicit_32, 32)
    assert _run_fp_case(star_32, 32) == _run_fp_case(noisy_star_32, 32)

    assert _run_d_case(star_32, 32) == _run_d_case(explicit_full_32, 32)
    assert _run_d_case(star_32, 32) == _run_d_case(noisy_explicit_32, 32)
    assert _run_d_case(star_32, 32) == _run_d_case(noisy_star_32, 32)


def test_star_rv32_fullset_mix_runtime_matches_explicit_bundle_under_noisy_aliases():
    explicit_full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + A + a + m + B + C + F + D + ZIFENCEI + zifencei + ZICOND + zicond + ZICSR + unknown.ext + ZBA + "
    noisy_star_32 = "  RV32I + GC + * + ??? + ZICSR + zicsr + ZICOND + zicond + ZIFENCEI + zifencei + ZBB + ZBH + ZBK + M + A + B + C + F + D + "

    mix_explicit = _run_multi_extension_mix_case(explicit_full_32, 32)
    mix_noisy = _run_multi_extension_mix_case(noisy_32, 32)
    mix_star = _run_multi_extension_mix_case(noisy_star_32, 32)

    assert mix_explicit == mix_noisy
    assert mix_explicit == mix_star


def test_explicit_zicond_extension_enables_czero_eqz():
    x3_no_zicond = _run_zicond_case("RV32I+GC", 32, funct3=0b000, rs2=0)
    assert x3_no_zicond == 0

    x3_with_zicond = _run_zicond_case("RV32I+GC+ZICOND", 32, funct3=0b000, rs2=0)
    assert x3_with_zicond == 0x55

    x3_no_zicond_64 = _run_zicond_case("RV64I+GC", 64, funct3=0b000, rs2=0)
    assert x3_no_zicond_64 == 0

    x3_with_zicond_64 = _run_zicond_case("RV64I+GC+ZICOND", 64, funct3=0b000, rs2=0)
    assert x3_with_zicond_64 == 0x55


def test_explicit_zicond_extension_enables_czero_nez():
    x3_with_zicond_nez = _run_zicond_case("RV32I+GC+ZICOND", 32, funct3=0b001, rs2=0x0F)
    assert x3_with_zicond_nez == 0
    x3_with_zicond_nez2 = _run_zicond_case("RV32I+GC+ZICOND", 32, funct3=0b001, rs2=0)
    assert x3_with_zicond_nez2 == 0x55

    x3_with_zicond_nez_64 = _run_zicond_case("RV64I+GC+ZICOND", 64, funct3=0b001, rs2=0x0F)
    assert x3_with_zicond_nez_64 == 0
    x3_with_zicond_nez2_64 = _run_zicond_case("RV64I+GC+ZICOND", 64, funct3=0b001, rs2=0)
    assert x3_with_zicond_nez2_64 == 0x55


def test_redundant_and_unknown_extensions_do_not_block_b_runtime_behavior():
    expected32 = 0x123 | (~0x0F & ((1 << 32) - 1))
    x3 = _run_b_case("RV32I+GC+B+B+ZBA+ZBKB+ZZZZ", 32, funct3=0b110)
    assert x3 == expected32

    expected64 = 0x123 | (~0x0F & ((1 << 64) - 1))
    x3_64 = _run_b_case("RV64I+GC+B+B+ZBA+ZBKB+ZZZZ", 64, funct3=0b110)
    assert x3_64 == expected64


def test_robust_extension_specification_syntax_still_executes_b_when_tolerated():
    expected32 = 0x123 | (~0x0F & ((1 << 32) - 1))
    x3 = _run_b_case("  rv32i + gc + zbkb + zBka + ??? + B + b + ", 32, funct3=0b110)
    assert x3 == expected32

    expected64 = 0x123 | (~0x0F & ((1 << 64) - 1))
    x3_64 = _run_b_case("  rv64i + gc + zbkb + zBka + ??? + B + b + ", 64, funct3=0b110)
    assert x3_64 == expected64


def test_op_fp_32_writes_only_on_64bit_f():
    assert _run_fp32_case("RV32I+GC", 32) == 7
    assert _run_fp32_case("RV32I+GC+F", 32) == 7
    assert _run_fp32_case("RV64I+GC+F", 64) == 0


def test_explicit_c_extension_enabled_works_with_rv32i_gc_star_like_program():
    _, v6_base = _run_case("RV32I+GC", 32)
    _, v6_with_c = _run_case("RV32I+GC+C", 32)
    _, v6_star = _run_case("RV32I+GC+*", 32)

    assert v6_base == 0
    assert v6_with_c == 21
    assert v6_with_c == v6_star


def test_explicit_c_extension_enabled_works_with_rv64i_gc_star_like_program():
    _, v6_base = _run_case("RV64I+GC", 64)
    _, v6_with_c = _run_case("RV64I+GC+C", 64)
    _, v6_star = _run_case("RV64I+GC+*", 64)

    assert v6_base == 0
    assert v6_with_c == 21
    assert v6_with_c == v6_star


def test_star_superset_matches_explicit_standard_extensions_on_rv32_and_rv64():
    # RV32I baseline + each explicit std extension should match the +* superset behavior.
    v3_base_32, v5_base_32 = _run_base_case("RV32I+GC", 32)
    v3_star_32, v5_star_32 = _run_base_case("RV32I+GC+*", 32)
    assert v3_star_32 == v3_base_32
    assert v5_star_32 == v5_base_32

    x3_m_32, x5_m_32 = _run_m_case("RV32I+GC+M", 32)
    x3_star_m_32, x5_star_m_32 = _run_m_case("RV32I+GC+*", 32)
    assert (x3_m_32, x5_m_32) == (x3_star_m_32, x5_star_m_32)

    assert _run_amo_ops_case("RV32I+GC+A", 32) == _run_amo_ops_case("RV32I+GC+*", 32)
    assert _run_b_case("RV32I+GC+B", 32, funct3=0b110) == _run_b_case("RV32I+GC+*", 32, funct3=0b110)
    assert _run_zicsr_case("RV32I+GC+ZICSR", 32) == _run_zicsr_case("RV32I+GC+*", 32)
    assert _run_zifencei_case("RV32I+GC+ZIFENCEI", 32) == _run_zifencei_case("RV32I+GC+*", 32)
    assert _run_zicond_case("RV32I+GC+ZICOND", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        "RV32I+GC+*", 32, funct3=0b001, rs2=0x0F
    )

    x3_fp_32, x4_fp_32, _ = _run_fp_case("RV32I+GC+F", 32)
    x3_fp_star_32, x4_fp_star_32, _ = _run_fp_case("RV32I+GC+*", 32)
    assert (x3_fp_32, x4_fp_32) == (x3_fp_star_32, x4_fp_star_32)

    x3_d_32 = _run_d_case("RV32I+GC+D", 32)
    x3_d_32_star = _run_d_case("RV32I+GC+*", 32)
    assert x3_d_32 == x3_d_32_star

    _, v6_base_64 = _run_base_case("RV64I+GC", 64)
    _, v6_star_64 = _run_base_case("RV64I+GC+*", 64)
    assert v6_star_64 == v6_base_64

    x3_m_64, x5_m_64 = _run_m_case("RV64I+GC+M", 64)
    x3_star_m_64, x5_star_m_64 = _run_m_case("RV64I+GC+*", 64)
    assert (x3_m_64, x5_m_64) == (x3_star_m_64, x5_star_m_64)

    assert _run_amo_ops_case("RV64I+GC+A", 64) == _run_amo_ops_case("RV64I+GC+*", 64)
    assert _run_b_case("RV64I+GC+B", 64, funct3=0b110) == _run_b_case("RV64I+GC+*", 64, funct3=0b110)
    assert _run_zicsr_case("RV64I+GC+ZICSR", 64) == _run_zicsr_case("RV64I+GC+*", 64)
    assert _run_zifencei_case("RV64I+GC+ZIFENCEI", 64) == _run_zifencei_case("RV64I+GC+*", 64)
    assert _run_zicond_case("RV64I+GC+ZICOND", 64, funct3=0b001, rs2=0) == _run_zicond_case(
        "RV64I+GC+*", 64, funct3=0b001, rs2=0
    )

    x3_fp_64, x4_fp_64, _ = _run_fp_case("RV64I+GC+F", 64)
    x3_fp_star_64, x4_fp_star_64, _ = _run_fp_case("RV64I+GC+*", 64)
    assert (x3_fp_64, x4_fp_64) == (x3_fp_star_64, x4_fp_star_64)

    x3_d_64 = _run_d_case("RV64I+GC+D", 64)
    x3_d_64_star = _run_d_case("RV64I+GC+*", 64)
    assert x3_d_64 == x3_d_64_star


def test_star_equals_explicit_full_standard_set_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(full_64, 64, funct3=0b110)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        full_32, 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0) == _run_zicond_case(
        full_64, 64, funct3=0b001, rs2=0
    )

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32, ) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64, ) == _run_fp_case(full_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)


def test_star_equals_explicit_full_standard_set_fp_width_cases_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    x2_f32, x4_f32 = _run_fp_width_case("RV32I+GC+*", 32)
    x2_f32_full, x4_f32_full = _run_fp_width_case(full_32, 32)
    assert (x2_f32, x4_f32) == (x2_f32_full, x4_f32_full)

    x2_f64, x4_f64 = _run_fp_width_case("RV64I+GC+*", 64)
    x2_f64_full, x4_f64_full = _run_fp_width_case(full_64, 64)
    assert (x2_f64, x4_f64) == (x2_f64_full, x4_f64_full)

    x3_f32, x4_f32 = _run_fp_store_width_case("RV32I+GC+*", 32)
    x3_f32_full, x4_f32_full = _run_fp_store_width_case(full_32, 32)
    assert (x3_f32, x4_f32) == (x3_f32_full, x4_f32_full)

    x3_f64, x4_f64 = _run_fp_store_width_case("RV64I+GC+*", 64)
    x3_f64_full, x4_f64_full = _run_fp_store_width_case(full_64, 64)
    assert (x3_f64, x4_f64) == (x3_f64_full, x4_f64_full)


def test_order_noisy_specification_does_not_change_star_standard_execution_behavior():
    noisy_32 = "  rv32i + gc + ??? + B + a + m + d + zicond + c + f + zifencei + zicsr +  "
    noisy_64 = "  rv64i + gc + ??? + ZIFENCEI + ZICSR + D + A + M + C + F + ZICOND + B + "
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(full_64, 64, funct3=0b110)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(full_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0) == _run_zicond_case(full_64, 64, funct3=0b001, rs2=0)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)


def test_star_and_noisy_full_standard_set_are_idempotent_on_rv32_and_rv64():
    noisy_32 = (
        "  rv32i + gc + ??? + M + M + A + b + B + C + c + F + "
        "f + D + ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + ZICOND + zicond + ZIFENCEI + zifencei + "
        "ZICSR + zicsr + D + F + F + A + a + M + m + B + b + C + c + "
    )
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)


def test_star_matches_noisy_canonicalization_included_compression_on_rv32_and_rv64():
    noisy_32 = "  rv32i + gc + ??? + ZBA + b + C + zBka + M + A + "
    noisy_64 = "  rv64i + gc + ??? + c + B + M + a + zifencei + ZICOND + "

    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_case("RV32I+GC+C", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+C", 64) == _run_case(noisy_64, 64)


def test_star_superset_preserves_amo_ops_equivalence_on_32_and_64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + A + M + ZICSR + zicsr + B + "
    noisy_64 = "  rv64i + gc + ??? + a + m + zifencei + zicsr + B + "

    amo_tests_32 = [
        (0b00001, 0x03, 0x0F, 0b010),
        (0b00100, 0x0F, 0xF0, 0b010),
        (0b01100, 0x0F, 0xF0, 0b010),
        (0b00000, 0x2A, 0x10, 0b010),
    ]
    amo_tests_64 = [
        (0b00001, 0x03, 0x0F, 0b011),
        (0b00100, 0x0F, 0xF0, 0b011),
        (0b01100, 0x0F, 0xF0, 0b011),
        (0b00000, 0x2A, 0x10, 0b011),
    ]

    for amofn, src_imm, init_mem, funct3 in amo_tests_32:
        rv32_star = _run_amo_op_case("RV32I+GC+*", 32, amofn, src_imm, init_mem, funct3=funct3)
        rv32_full = _run_amo_op_case(full_32, 32, amofn, src_imm, init_mem, funct3=funct3)
        rv32_noisy = _run_amo_op_case(noisy_32, 32, amofn, src_imm, init_mem, funct3=funct3)
        assert rv32_star == rv32_full == rv32_noisy

    for amofn, src_imm, init_mem, funct3 in amo_tests_64:
        rv64_star = _run_amo_op_case("RV64I+GC+*", 64, amofn, src_imm, init_mem, funct3=funct3)
        rv64_full = _run_amo_op_case(full_64, 64, amofn, src_imm, init_mem, funct3=funct3)
        rv64_noisy = _run_amo_op_case(noisy_64, 64, amofn, src_imm, init_mem, funct3=funct3)
        assert rv64_star == rv64_full == rv64_noisy


def test_star_superset_matches_zicond_variants_on_rv32_and_rv64():
    noisy_32 = "  rv32i + gc + ??? + ZICOND + b + M + A + B + "
    noisy_64 = "  rv64i + gc + ??? + zicond + C + A + M + ZICSR + "

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(
        "RV32I+GC+ZICOND", 32, funct3=0b000, rs2=0
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(
        "RV64I+GC+ZICOND", 64, funct3=0b000, rs2=0
    )

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        "RV32I+GC+ZICOND", 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        "RV64I+GC+ZICOND", 64, funct3=0b001, rs2=0x0F
    )

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0x0F) == _run_zicond_case(
        noisy_32, 32, funct3=0b000, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0x0F) == _run_zicond_case(
        noisy_64, 64, funct3=0b000, rs2=0x0F
    )


def test_star_orderless_noisy_standard_set_remains_rv32_and_rv64_equivalent():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    noisy_32 = (
        "  rv32i + gc + ??? + zifencei + M + zbk + A + zicsr + C + "
        "zbb + F + D + zcond + zba + B + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + c + zifencei + a + zba + b + m + zcsr + "
        "f + D + ZICOND + ZICSR + B + "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)


def test_star_noisy_specification_executes_standard_set_runtime_behaviors():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + zicond + ZZ_UNKNOWN + B + f + "
        "A + m + d + zifencei + zicsr + C + c + M + ZBA + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + ZIFENCEI + zbh + ZBB + D + A + "
        "ZICOND + m + b + ZICSR + F + C + zbkb + c + "
    )

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(full_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(full_64, 64, funct3=0b111)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0) == _run_zicond_case(
        noisy_32, 32, funct3=0b001, rs2=0
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0) == _run_zicond_case(
        noisy_64, 64, funct3=0b001, rs2=0
    )


def test_base_program_noisy_parser_stability_for_rv32_and_rv64():
    noisy_32 = (
        "  rv32i + gc + ??? + ZBA + m + a + ZICSR + c + F + D + "
        "ZIFENCEI + B + ZICOND + ZBA + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + zifencei + zicond + m + A + zicsr + B + "
        "D + F + C + c + ZBHB + "
    )
    baseline_32 = "  rv32i + gc + ??? + C + "
    baseline_64 = "  rv64i + gc + ??? + c + "

    assert _run_base_case("RV32I+GC", 32) == _run_base_case(noisy_32, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_base_case("RV64I+GC", 64) == _run_base_case(noisy_64, 64)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(noisy_64, 64)

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(baseline_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(baseline_64, 64)

    x2_f32_star, x4_f32_star = _run_fp_width_case("RV32I+GC+*", 32)
    x2_f32_noisy, x4_f32_noisy = _run_fp_width_case(noisy_32, 32)
    assert (x2_f32_star, x4_f32_star) == (x2_f32_noisy, x4_f32_noisy)

    x2_f64_star, x4_f64_star = _run_fp_width_case("RV64I+GC+*", 64)
    x2_f64_noisy, x4_f64_noisy = _run_fp_width_case(noisy_64, 64)
    assert (x2_f64_star, x4_f64_star) == (x2_f64_noisy, x4_f64_noisy)

    x3_f32_star, x4_f32_star = _run_fp_store_width_case("RV32I+GC+*", 32)
    x3_f32_noisy, x4_f32_noisy = _run_fp_store_width_case(noisy_32, 32)
    assert (x3_f32_star, x4_f32_star) == (x3_f32_noisy, x4_f32_noisy)

    x3_f64_star, x4_f64_star = _run_fp_store_width_case("RV64I+GC+*", 64)
    x3_f64_noisy, x4_f64_noisy = _run_fp_store_width_case(noisy_64, 64)
    assert (x3_f64_star, x4_f64_star) == (x3_f64_noisy, x4_f64_noisy)


def test_star_includes_compressed_extension_runtime_stability_under_noisy_rv32_and_rv64():
    noisy_32 = "  rv32i + gc + ??? + ZICSR + M + A + ZIFENCEI + ZICOND + B + "
    noisy_64 = "  rv64i + gc + ??? + C + M + A + ZICSR + ZIFENCEI + zicond + B + "

    assert _run_case("RV32I+GC+C", 32) == _run_case("RV32I+GC+*", 32)
    assert _run_case("RV64I+GC+C", 64) == _run_case("RV64I+GC+*", 64)

    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_case("RV32I+GC", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC", 64) != _run_case(noisy_64, 64)


def test_noisy_alias_and_duplicates_stabilize_standard_extension_runtime_on_32_and_64():
    full_32 = "RV32I+GC+M+A+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + M + M + a + zifencei + ZICOND + ZZ + "
        "ZICSR + b + B + A + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + a + A + ZIFENCEI + ZICOND + M + m + "
        "zicsr + ZBA + B + ZBKB + "
    )

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(full_32, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        full_64, 64, funct3=0b001, rs2=0x0F
    )


def test_star_extension_combo_noisy_stability_against_explicit_m_a_zicsr_32_and_64():
    full_32 = "RV32I+GC+M+A+ZICSR"
    full_64 = "RV64I+GC+M+A+ZICSR"
    noisy_32 = (
        "  rv32i + gc + ??? + M + ZZ_UNKNOWN + a + zicsr + A + m + "
        "C + B + ZBA + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + a + M + M + zicond + ZICSR + c + A + "
        "B + zbh + "
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)

    assert _run_extension_combo_case("RV32I+GC", 32) != _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC", 64) != _run_extension_combo_case(noisy_64, 64)


def test_star_d_extension_noisy_stability_for_fp_width_and_d_loads_on_rv32_and_rv64():
    noisy_32 = (
        "  rv32i + gc + ??? + ZICSR + D + F + zifencei + zz + "
        "M + A + B + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + d + F + ZICOND + zicsr + m + a + "
        "b + zifencei + C + "
    )

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case("RV32I+GC+F+D", 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case("RV64I+GC+F+D", 64)

    assert _run_d_case("RV32I+GC", 32) != _run_d_case("RV32I+GC+*", 32)
    assert _run_d_case("RV64I+GC", 64) != _run_d_case("RV64I+GC+*", 64)

    x2_d_width_32_star, x4_d_width_32_star = _run_fp_width_case("RV32I+GC+*", 32)
    x2_d_width_32_noisy, x4_d_width_32_noisy = _run_fp_width_case(noisy_32, 32)
    assert (x2_d_width_32_star, x4_d_width_32_star) == (x2_d_width_32_noisy, x4_d_width_32_noisy)
    assert (x2_d_width_32_star, x4_d_width_32_star) == (0x77, 0x55)

    x2_d_width_64_star, x4_d_width_64_star = _run_fp_width_case("RV64I+GC+*", 64)
    x2_d_width_64_noisy, x4_d_width_64_noisy = _run_fp_width_case(noisy_64, 64)
    assert (x2_d_width_64_star, x4_d_width_64_star) == (x2_d_width_64_noisy, x4_d_width_64_noisy)
    assert (x2_d_width_64_star, x4_d_width_64_star) == (0x77, 0x55)


def test_star_ifencei_and_zicsr_combo_noisy_stability_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + ZIFENCEI + zifencei + M + A + "
        "ZZ_UNKNOWN + zicsr + ZICOND + B + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + A + M + zifencei + ZICOND + ZICSR + "
        "b + ZZ + c + "
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)

    assert _run_extension_combo_case("RV32I+GC", 32) != _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC", 64) != _run_extension_combo_case(noisy_64, 64)


def test_star_zicond_noisy_stability_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+ZICOND"
    full_64 = "RV64I+GC+M+A+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + ZICOND + zicond + ZBA + M + A + "
        "B + b + ZIFENCEI + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + zcond + ZICOND + A + a + m + M + B + "
        "ZBA + zifencei + "
    )

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(noisy_64, 64, funct3=0b000, rs2=0)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case("RV32I+GC+ZICOND", 32, funct3=0b000, rs2=0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case("RV64I+GC+ZICOND", 64, funct3=0b000, rs2=0)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case("RV32I+GC+ZICOND", 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case("RV64I+GC+ZICOND", 64, funct3=0b001, rs2=0x0F)

    assert _run_zicond_case("RV32I+GC", 32, funct3=0b000, rs2=0xF) != _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0xF)
    assert _run_zicond_case("RV64I+GC", 64, funct3=0b001, rs2=0x0) != _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0)


def test_star_cross_extension_noisy_stability_for_rv32_and_rv64_core_bundle():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + F + D + zicsr + zifencei + B + "
        "ZBA + zbkb + ZBS + zba + m + a + C + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + c + zba + f + D + M + A + ZBA + "
        "zbh + ZICSR + ZICOND + ZIFENCEI + b + "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(noisy_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(noisy_64, 64, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(noisy_32, 32, funct3=0b100)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b100) == _run_b_case(noisy_64, 64, funct3=0b100)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_64, 64, funct3=0b110)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)


def test_star_multi_extension_mix_noisy_stability_and_noise_invariance_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+F+D+B+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+F+D+B+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + A + M + ZICOND + B + b + F + D + "
        "zicsr + zifencei + ZBA + C + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + M + m + a + ZIFENCEI + zicond + "
        "F + D + B + c + ZBA + ZICSR + "
    )

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)

    assert _run_multi_extension_mix_case("RV32I+GC", 32) != _run_multi_extension_mix_case("RV32I+GC+*", 32)
    assert _run_multi_extension_mix_case("RV64I+GC", 64) != _run_multi_extension_mix_case("RV64I+GC+*", 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)


def test_star_amo_lr_sc_is_noisy_stable_against_explicit_a_on_rv32_and_rv64():
    noisy_32 = (
        "  rv32i + gc + ??? + A + A + M + B + ZBA + ZBS + "
        "c + zifencei + ZICSR + zicond + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + a + zz + A + B + M + ZICOND + "
        "c + ZIFENCEI + zifencei + "
    )

    x2_32_star, x4_32_star, x5_32_star = _run_lr_sc_case("RV32I+GC+*", 32, 0b010)
    x2_32_a, x4_32_a, x5_32_a = _run_lr_sc_case("RV32I+GC+A", 32, 0b010)
    x2_32_noisy, x4_32_noisy, x5_32_noisy = _run_lr_sc_case(noisy_32, 32, 0b010)
    assert (x2_32_star, x4_32_star, x5_32_star) == (x2_32_a, x4_32_a, x5_32_a)
    assert (x2_32_star, x4_32_star, x5_32_star) == (x2_32_noisy, x4_32_noisy, x5_32_noisy)
    assert _run_lr_sc_case("RV32I+GC", 32, 0b010) != (x2_32_star, x4_32_star, x5_32_star)

    x2_64_star, x4_64_star, x5_64_star = _run_lr_sc_case("RV64I+GC+*", 64, 0b011)
    x2_64_a, x4_64_a, x5_64_a = _run_lr_sc_case("RV64I+GC+A", 64, 0b011)
    x2_64_noisy, x4_64_noisy, x5_64_noisy = _run_lr_sc_case(noisy_64, 64, 0b011)
    assert (x2_64_star, x4_64_star, x5_64_star) == (x2_64_a, x4_64_a, x5_64_a)
    assert (x2_64_star, x4_64_star, x5_64_star) == (x2_64_noisy, x4_64_noisy, x5_64_noisy)
    assert _run_lr_sc_case("RV64I+GC", 64, 0b011) != (x2_64_star, x4_64_star, x5_64_star)

    x5_32_star_amo, x6_32_star_amo = _run_amo_op_case("RV32I+GC+*", 32, 0b00001, 0x2A, 0x55, funct3=0b010)
    x5_32_a_amo, x6_32_a_amo = _run_amo_op_case("RV32I+GC+A", 32, 0b00001, 0x2A, 0x55, funct3=0b010)
    x5_32_noisy_amo, x6_32_noisy_amo = _run_amo_op_case(noisy_32, 32, 0b00001, 0x2A, 0x55, funct3=0b010)
    assert (x5_32_star_amo, x6_32_star_amo) == (x5_32_a_amo, x6_32_a_amo)
    assert (x5_32_star_amo, x6_32_star_amo) == (x5_32_noisy_amo, x6_32_noisy_amo)

    x5_64_star_amo, x6_64_star_amo = _run_amo_op_case("RV64I+GC+*", 64, 0b00001, 0x2A, 0x55, funct3=0b011)
    x5_64_a_amo, x6_64_a_amo = _run_amo_op_case("RV64I+GC+A", 64, 0b00001, 0x2A, 0x55, funct3=0b011)
    x5_64_noisy_amo, x6_64_noisy_amo = _run_amo_op_case(noisy_64, 64, 0b00001, 0x2A, 0x55, funct3=0b011)
    assert (x5_64_star_amo, x6_64_star_amo) == (x5_64_a_amo, x6_64_a_amo)
    assert (x5_64_star_amo, x6_64_star_amo) == (x5_64_noisy_amo, x6_64_noisy_amo)


def test_star_and_noisy_parser_stability_for_base_and_wildcard_on_rv32_and_rv64():
    noisy_32 = (
        "  rv32i + gc + ??? + ZBA + zba + B + B + "
        "C + c + M + A + ZICSR + ZICOND + ZIFENCEI + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + zbh + ZBH + b + "
        "c + C + m + A + ZICSR + zicsr + ZICOND + ZIFENCEI + "
    )
    baseline_noisy_32 = "  rv32i + gc + ??? + C + "
    baseline_noisy_64 = "  rv64i + gc + ??? + C + "

    base_32 = _run_base_case("RV32I+GC", 32)
    base_32_noisy = _run_base_case(baseline_noisy_32, 32)
    base_64 = _run_base_case("RV64I+GC", 64)
    base_64_noisy = _run_base_case(baseline_noisy_64, 64)
    assert base_32 == base_32_noisy
    assert base_64 == base_64_noisy

    assert _run_base_case("RV32I+GC+*", 32) == base_32
    assert _run_base_case("RV64I+GC+*", 64) == base_64

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0) == _run_zicond_case(
        noisy_32, 32, funct3=0b001, rs2=0
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0) == _run_zicond_case(
        noisy_64, 64, funct3=0b001, rs2=0
    )


def test_star_superset_matches_full_standard_set_zifencei_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case("  rv32i + gc + ??? + zifencei + zicsr + m + a + B + C + ", 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case("  rv64i + gc + ??? + ZIFENCEI + ZICSR + A + B + C + ", 64)


def test_star_matches_full_noisy_extension_suite_for_combo_and_sys_paths():
    explicit_32 = "RV32I+GC+M+A+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + ZICSR + ZIFENCEI + ZICOND + m + a + B + C + "
    noisy_64 = "  rv64i + gc + ??? + zicsr + zifencei + zicond + A + M + B + C + "

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(explicit_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(explicit_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(explicit_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)


def test_star_explicit_fullset_and_noisy_fullset_equivalence_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + F + D + B + M + A + C + "
        "zifencei + zicsr + zicond + B + M + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + c + m + a + f + d + B + "
        "ZICSR + ZICOND + ZIFENCEI + F + M + "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)


def test_star_fullset_zifencei_zicsr_zicond_interaction_noisy_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+F+D+B+C+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+F+D+B+C+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + ZIFENCEI + ZICSR + ZICOND + m + a + "
        "b + c + F + D + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + zifencei + zicsr + zicond + m + a + "
        "B + C + F + D + "
    )

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(full_32, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(full_64, 64, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(noisy_64, 64, funct3=0b000, rs2=0)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)


def test_star_standard_fullset_and_noisy_equivalence_across_m_a_b_paths_on_32_and_64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + A + m + B + b + ZBA + ZBB + "
        "f + F + d + D + ZICSR + zifencei + ZICOND + C + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + a + M + B + b + ZBH + ZBA + "
        "F + f + D + d + ZICSR + ZIFENCEI + ZICOND + C + "
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(full_64, 64, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_64, 64, funct3=0b110)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)


def test_star_fullset_and_noisy_fp32_fp64_width_store_load_paths_on_32_and_64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + C + F + D + ZICSR + ZIFENCEI + ZICOND + "
        "M + A + B + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + c + f + d + ZICSR + ZIFENCEI + ZICOND + "
        "M + A + B + "
    )

    x2_f32_star, x4_f32_star = _run_fp_width_case("RV32I+GC+*", 32)
    x2_f32_full, x4_f32_full = _run_fp_width_case(full_32, 32)
    x2_f32_noisy, x4_f32_noisy = _run_fp_width_case(noisy_32, 32)
    assert (x2_f32_star, x4_f32_star) == (x2_f32_full, x4_f32_full) == (x2_f32_noisy, x4_f32_noisy)

    x2_f64_star, x4_f64_star = _run_fp_width_case("RV64I+GC+*", 64)
    x2_f64_full, x4_f64_full = _run_fp_width_case(full_64, 64)
    x2_f64_noisy, x4_f64_noisy = _run_fp_width_case(noisy_64, 64)
    assert (x2_f64_star, x4_f64_star) == (x2_f64_full, x4_f64_full) == (x2_f64_noisy, x4_f64_noisy)

    x3_32_star, x4_32_star = _run_fp_store_width_case("RV32I+GC+*", 32)
    x3_32_full, x4_32_full = _run_fp_store_width_case(full_32, 32)
    x3_32_noisy, x4_32_noisy = _run_fp_store_width_case(noisy_32, 32)
    assert (x3_32_star, x4_32_star) == (x3_32_full, x4_32_full) == (x3_32_noisy, x4_32_noisy)

    x3_64_star, x4_64_star = _run_fp_store_width_case("RV64I+GC+*", 64)
    x3_64_full, x4_64_full = _run_fp_store_width_case(full_64, 64)
    x3_64_noisy, x4_64_noisy = _run_fp_store_width_case(noisy_64, 64)
    assert (x3_64_star, x4_64_star) == (x3_64_full, x4_64_full) == (x3_64_noisy, x4_64_noisy)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)


def test_star_noisy_parser_stability_against_full_and_base_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+F+D+B+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+F+D+B+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + ZBA + ZBB + zba + ZBKB + "
        "M + A + F + D + B + C + ZICSR + ZICOND + ZIFENCEI + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + ZBA + ZBH + zbh + F + D + "
        "M + A + B + C + ZICSR + ZICOND + ZIFENCEI + "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case("RV32I+GC", 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case("RV64I+GC", 64)

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)


def test_star_noisy_extension_behavior_differs_from_base_only_when_enabled():
    noisy_32 = "  rv32i + gc + ??? + m + a + zicsr + zifencei + zicond + B + F + D + C + "
    noisy_64 = "  rv64i + gc + ??? + M + A + ZICSR + ZIFENCEI + ZICOND + B + F + D + C + "

    base_32 = _run_base_case("RV32I+GC", 32)
    star_32 = _run_base_case("RV32I+GC+*", 32)
    noisy_base_32 = _run_base_case(noisy_32, 32)
    assert base_32 == noisy_base_32 == star_32

    base_64 = _run_base_case("RV64I+GC", 64)
    star_64 = _run_base_case("RV64I+GC+*", 64)
    noisy_base_64 = _run_base_case(noisy_64, 64)
    assert base_64 == noisy_base_64 == star_64

    assert _run_zifencei_case("RV32I+GC", 32) != _run_zifencei_case("RV32I+GC+*", 32)
    assert _run_zifencei_case("RV64I+GC", 64) != _run_zifencei_case("RV64I+GC+*", 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC", 32) != _run_zicsr_case("RV32I+GC+*", 32)
    assert _run_zicsr_case("RV64I+GC", 64) != _run_zicsr_case("RV64I+GC+*", 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC", 32) != _run_extension_combo_case("RV32I+GC+*", 32)
    assert _run_extension_combo_case("RV64I+GC", 64) != _run_extension_combo_case("RV64I+GC+*", 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC", 32, funct3=0b001, rs2=0) != _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0)
    assert _run_zicond_case("RV64I+GC", 64, funct3=0b000, rs2=0x0F) != _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0x0F)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0) == _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0x0F) == _run_zicond_case(noisy_64, 64, funct3=0b000, rs2=0x0F)


def test_star_matches_explicit_standard_m_a_zicsr_zifencei_zicond_set_on_32_and_64():
    explicit_32 = "RV32I+GC+M+A+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+ZICSR+ZIFENCEI+ZICOND"

    assert _run_case("RV32I+GC+*", 32) == _run_case(explicit_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(explicit_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(explicit_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(explicit_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(explicit_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(explicit_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(explicit_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(explicit_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(explicit_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        explicit_32, 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(
        explicit_64, 64, funct3=0b000, rs2=0
    )


def test_star_respects_b_alias_noisy_bundle_without_affecting_base_on_rv32_and_rv64():
    noisy_32 = (
        "  rv32i + gc + ??? + zba + zbb + zbkb + zbk + zbh + zbs + "
        "zbf + zbe + zbm + zbga + zicond + zicsr + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + ZBKB + zbb + zba + zbk + zbh + zbs + "
        "zbm + zbe + zbf + zicond + zicsr + "
    )

    assert _run_b_case("RV32I+GC", 32, funct3=0b110) != _run_b_case("RV32I+GC+*", 32, funct3=0b110)
    assert _run_b_case("RV64I+GC", 64, funct3=0b110) != _run_b_case("RV64I+GC+*", 64, funct3=0b110)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_64, 64, funct3=0b110)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case("RV32I+GC+B", 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case("RV64I+GC+B", 64, funct3=0b111)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case("RV32I+GC+ZBA+ZBB+ZBK+ZBH+ZBS", 32, funct3=0b100)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b100) == _run_b_case("RV64I+GC+ZBA+ZBB+ZBK+ZBH+ZBS", 64, funct3=0b100)


def test_star_zicond_and_zicsr_combo_noisy_stability_for_czero_on_rv32_and_rv64():
    full_32 = "RV32I+GC+ZICSR+ZICOND+M+A"
    full_64 = "RV64I+GC+ZICSR+ZICOND+M+A"
    noisy_32 = (
        "  rv32i + gc + ??? + zicsr + ZICOND + m + a + "
        "B + C + F + D + zifencei + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + ZICOND + zicsr + A + M + "
        "B + C + F + D + ZIFENCEI + "
    )

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(full_32, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(full_64, 64, funct3=0b001, rs2=0x0F)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0x0F) == _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

def test_star_full_standard_parity_for_rv32_and_rv64_full_suite_with_noisy_inputs():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + b + B + F + f + D + d + zicond + ZICOND + "
        "zifencei + zIFENCEI + zicsr + ZICSR + m + M + a + A + c + C + "
        "ZBA + zbk + zbe + zbs + zbf + zbm + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + C + c + ZICSR + zicsr + M + a + A + B + b + "
        "F + f + D + d + zifencei + ZIFENCEI + ZICOND + zicond + "
        "ZBA + ZBB + ZBH + ZBK + ZBKB + "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(full_64, 64, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_64, 64, funct3=0b110)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        full_32, 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(
        full_64, 64, funct3=0b000, rs2=0
    )
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        noisy_32, 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(
        noisy_64, 64, funct3=0b000, rs2=0
    )
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

def test_star_fullset_parity_and_activation_on_rv32_and_rv64_for_standard_suite():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + m + a + b + B + C + f + F + d + D + "
        "zifencei + zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + M + A + B + C + F + D + "
        "zifencei + zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + "
        "b + "
    )

    assert _run_base_case("RV32I+GC", 32) == _run_base_case("RV32I+GC+*", 32)
    assert _run_base_case("RV64I+GC", 64) == _run_base_case("RV64I+GC+*", 64)

    assert _run_case("RV32I+GC+*", 32) == _run_case(explicit_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(explicit_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(explicit_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(explicit_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(explicit_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(explicit_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(explicit_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(explicit_64, 64, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_64, 64, funct3=0b110)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(explicit_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(explicit_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(explicit_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(explicit_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(explicit_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(explicit_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(explicit_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(explicit_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(explicit_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(explicit_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(explicit_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(explicit_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0x0F) == _run_zicond_case(
        explicit_32, 32, funct3=0b000, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0) == _run_zicond_case(
        explicit_64, 64, funct3=0b001, rs2=0
    )
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0x0F) == _run_zicond_case(
        noisy_32, 32, funct3=0b000, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0) == _run_zicond_case(
        noisy_64, 64, funct3=0b001, rs2=0
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(explicit_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

def test_star_fullset_equivalence_for_fp32_noisy_parsing_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + f + F + d + D + zifencei + zIFENCEI + "
        "zifencei + ZICSR + zicsr + zicond + ZICOND + M + m + A + a + "
        "C + c + b + B + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + ZIFENCEI + zifencei + ZICSR + zicsr + "
        "ZICOND + zicond + m + M + a + A + F + f + D + d + B + b + "
        "C + c + "
    )

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case("RV32I+GC", 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case("RV64I+GC", 64)

    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(full_32, 32)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(full_64, 64)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(noisy_32, 32)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(noisy_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0) == _run_zicond_case(
        full_32, 32, funct3=0b001, rs2=0
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0x0F) == _run_zicond_case(
        full_64, 64, funct3=0b000, rs2=0x0F
    )
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0) == _run_zicond_case(
        noisy_32, 32, funct3=0b001, rs2=0
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0x0F) == _run_zicond_case(
        noisy_64, 64, funct3=0b000, rs2=0x0F
    )

def test_star_equivalence_fullset_noisy_for_core_mix_paths_on_rv32_and_rv64():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + m + M + a + A + zifencei + ZIFENCEI + "
        "zicsr + ZICSR + zicond + ZICOND + F + f + D + d + B + b + C + c + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + M + A + ZICOND + zicond + F + f + D + d + "
        "ZICSR + zicsr + ZIFENCEI + zifencei + B + b + C + c + "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(explicit_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(explicit_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(explicit_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(explicit_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(explicit_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(explicit_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(explicit_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case("RV32I+GC+A", 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case("RV64I+GC+A", 64, 0b011)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(noisy_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(noisy_64, 64, 0b011)

    assert _run_amo_op_case("RV32I+GC+*", 32, 0b00001, 0x2A, 0x55, funct3=0b010) == _run_amo_op_case(
        noisy_32, 32, 0b00001, 0x2A, 0x55, funct3=0b010
    )
    assert _run_amo_op_case("RV64I+GC+*", 64, 0b00001, 0x2A, 0x55, funct3=0b011) == _run_amo_op_case(
        noisy_64, 64, 0b00001, 0x2A, 0x55, funct3=0b011
    )

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(explicit_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(explicit_64, 64, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_64, 64, funct3=0b110)

def test_star_full_extension_suite_equivalence_with_noisy_redundant_specs_on_rv32_and_rv64():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + M + M + A + A + f + F + d + D + "
        "B + b + C + c + zicond + ZICOND + zicsr + ZICSR + "
        "ZIFENCEI + zifencei + ZBA + zba + ZBB + zbb + ZBK + zbk + "
        "UNKNOWN_32 + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + m + a + F + f + D + d + B + b + C + c + "
        "ZICSR + zicsr + ZICOND + zicond + ZIFENCEI + zifencei + "
        "ZBA + ZBB + ZBK + ZBKB + UNKNOWN_64 + "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(explicit_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(explicit_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(explicit_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(explicit_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(explicit_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(explicit_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(explicit_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(explicit_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(explicit_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(explicit_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(explicit_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(explicit_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(explicit_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0xF) == _run_zicond_case(
        explicit_32, 32, funct3=0b001, rs2=0xF
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(
        explicit_64, 64, funct3=0b000, rs2=0
    )
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0xF) == _run_zicond_case(
        noisy_32, 32, funct3=0b001, rs2=0xF
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(
        noisy_64, 64, funct3=0b000, rs2=0
    )

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(explicit_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(explicit_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(explicit_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(explicit_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

def test_star_full_standard_suite_parser_noise_invariance_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + m + A + b + B + C + F + D + zifencei + "
        "ZICSR + zicsr + zicond + ZICOND + f + d + c + M + ZBA + ZBB + "
        "ZBK + ZBH + UNKNOWN_X + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + M + a + B + b + C + c + F + f + D + d + "
        "ZICOND + zicond + ZICSR + zicsr + ZIFENCEI + zifencei + "+
        "ZBA + ZBB + ZBK + ZBF + UNKNOWN_Y + "
    )

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case("RV32I+GC", 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case("RV64I+GC", 64)

    assert _run_case("RV32I+GC+*", 32) == _run_case("RV32I+GC+*", 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case("RV64I+GC+*", 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_amo_op_case("RV32I+GC+*", 32, 0b00001, 0xA5, 0x3F, funct3=0b010) == _run_amo_op_case(
        noisy_32, 32, 0b00001, 0xA5, 0x3F, funct3=0b010
    )
    assert _run_amo_op_case("RV64I+GC+*", 64, 0b00001, 0xA5, 0x3F, funct3=0b011) == _run_amo_op_case(
        noisy_64, 64, 0b00001, 0xA5, 0x3F, funct3=0b011
    )

    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case("RV32I+GC+A", 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case("RV64I+GC+A", 64, 0b011)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(noisy_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(noisy_64, 64, 0b011)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(full_64, 64, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_64, 64, funct3=0b110)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0) == _run_zicond_case(
        full_32, 32, funct3=0b001, rs2=0
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0x0F) == _run_zicond_case(
        full_64, 64, funct3=0b000, rs2=0x0F
    )
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0) == _run_zicond_case(
        noisy_32, 32, funct3=0b001, rs2=0
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0x0F) == _run_zicond_case(
        noisy_64, 64, funct3=0b000, rs2=0x0F
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

def test_star_standard_fullset_and_noisy_parser_equivalence_for_amo_bsys_fp_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + M + m + A + a + F + f + D + d + "
        "B + b + C + c + ZBA + zba + ZBB + zbb + ZBK + zbk + "
        "ZBH + zbh + ZBS + zbs + ZICSR + zicsr + ZIFENCEI + zifencei + "
        "ZICOND + zicond + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + a + m + A + M + f + F + D + d + "
        "b + B + C + c + ZBA + ZBB + ZBH + ZBK + zicond + ZICOND + "
        "zicsr + ZICSR + zifencei + ZIFENCEI + "
    )

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(full_64, 64, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_64, 64, funct3=0b110)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0) == _run_zicond_case(
        full_32, 32, funct3=0b001, rs2=0
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0) == _run_zicond_case(
        full_64, 64, funct3=0b001, rs2=0
    )
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0) == _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0)

def test_star_fullset_noisy_stability_for_sys_and_fp_paths_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + f + F + d + D + zifencei + zicond + "
        "ZICOND + zicsr + ZICSR + C + c + B + b + M + A + "
        "zz_unknown + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + F + f + D + d + ZIFENCEI + zifencei + "
        "ZICOND + zicond + ZICSR + zicsr + M + A + B + b + "
        "C + c + zz_unknown2 + "
    )

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case("RV32I+GC", 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case("RV64I+GC", 64)

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

def test_star_fullset_system_amo_lr_sc_fp_width_equivalence_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + A + a + M + m + ZICSR + zicsr + ZIFENCEI + zifencei + "
        "ZICOND + zicond + B + b + C + c + F + f + D + d + ZZ + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + a + A + m + M + zicsr + ZICSR + zifencei + ZIFENCEI + "
        "zicond + ZICOND + b + B + C + c + F + f + D + d + ZZ + "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_amo_op_case("RV32I+GC+*", 32, 0b00001, 0x7F, 0x99, funct3=0b010) == _run_amo_op_case(
        noisy_32, 32, 0b00001, 0x7F, 0x99, funct3=0b010
    )
    assert _run_amo_op_case("RV64I+GC+*", 64, 0b00001, 0x7F, 0x99, funct3=0b011) == _run_amo_op_case(
        noisy_64, 64, 0b00001, 0x7F, 0x99, funct3=0b011
    )

    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case("RV32I+GC+A", 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case("RV64I+GC+A", 64, 0b011)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(noisy_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(noisy_64, 64, 0b011)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

def test_star_amo_b_fp_d_system_suite_parity_on_rv32_and_rv64_for_noisy_fullset():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + M + A + B + F + D + ZICOND + ZICSR + ZIFENCEI + "
        "C + b + f + d + zicond + zifencei + zicsr + m + a + c + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + m + a + b + f + d + ZICOND + zicond + ZICSR + zicsr + "
        "ZIFENCEI + zifencei + C + B + F + D + "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(full_64, 64, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_64, 64, funct3=0b110)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

def test_star_fullset_and_parser_noise_noop_guard_paths_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + M + a + b + C + F + D + ZICSR + zicsr + "
        "ZIFENCEI + zifencei + ZICOND + zicond + m + A + B + f + d + "
        "zba + ZBA + ZBB + zbb + ZBK + zBH + ZBF + ZZ_UNKNOWN + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + M + A + b + B + F + f + D + d + zifencei + "
        "ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + ZBA + ZBB + "
        "ZBH + zbh + ZBK + ZBF + ZICOND + ZZ_UNKNOWN2 + "
    )

    assert _run_case("RV32I+GC", 32) == _run_case("RV32I+GC+*", 32)
    assert _run_case("RV64I+GC", 64) == _run_case("RV64I+GC+*", 64)

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_amo_op_case("RV32I+GC+*", 32, 0b01000, 0x3F, 0xAA, funct3=0b010) == _run_amo_op_case(
        noisy_32, 32, 0b01000, 0x3F, 0xAA, funct3=0b010
    )
    assert _run_amo_op_case("RV64I+GC+*", 64, 0b01000, 0x3F, 0xAA, funct3=0b011) == _run_amo_op_case(
        noisy_64, 64, 0b01000, 0x3F, 0xAA, funct3=0b011
    )

    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case("RV32I+GC+A", 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case("RV64I+GC+A", 64, 0b011)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(noisy_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(noisy_64, 64, 0b011)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(full_64, 64, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_64, 64, funct3=0b110)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        full_32, 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(
        full_64, 64, funct3=0b000, rs2=0
    )
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        noisy_32, 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(
        noisy_64, 64, funct3=0b000, rs2=0
    )

def test_star_fullset_noisy_mix_equivalence_includes_fp_and_system_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + ZBA + ZBB + zba + zbb + ZBH + zbk + ZBF + f + F + d + D + "
        "ZICOND + zicond + ZICSR + zicsr + ZIFENCEI + zifencei + M + A + B + b + C + c + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + zba + ZBA + zbb + ZBB + zbh + ZBH + ZBK + ZBF + "
        "F + f + D + d + zicond + ZICOND + zicsr + ZICSR + ZIFENCEI + zifencei + m + A + c + C + "+
        "B + b + "
    )

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case("RV32I+GC", 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case("RV64I+GC", 64)

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case("RV32I+GC+A", 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case("RV64I+GC+A", 64, 0b011)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(noisy_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(noisy_64, 64, 0b011)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(full_32, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        full_64, 64, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        noisy_64, 64, funct3=0b001, rs2=0x0F
    )

def test_star_standard_suite_equivalence_bundle_for_fp_amo_zicond_and_sys_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + m + M + a + A + b + B + f + F + d + D + "
        "C + c + zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + "
        "zicond + ZICOND + zicsr + ZICSR + zifencei + ZIFENCEI "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case("RV32I+GC+A", 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case("RV64I+GC+A", 64, 0b011)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(noisy_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(noisy_64, 64, 0b011)

    assert _run_amo_op_case("RV32I+GC+*", 32, 0b00001, 0x2A, 0x55, funct3=0b010) == _run_amo_op_case(
        noisy_32, 32, 0b00001, 0x2A, 0x55, funct3=0b010
    )
    assert _run_amo_op_case("RV64I+GC+*", 64, 0b00001, 0x2A, 0x55, funct3=0b011) == _run_amo_op_case(
        noisy_64, 64, 0b00001, 0x2A, 0x55, funct3=0b011
    )

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(full_64, 64, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_64, 64, funct3=0b110)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(
        full_32, 32, funct3=0b000, rs2=0
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        full_64, 64, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        noisy_64, 64, funct3=0b001, rs2=0x0F
    )

def test_star_extension_bundle_mw_cases_cover_rv32_and_rv64_with_full_noisy_parity():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + b + B + f + F + d + D + c + C + zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond"
    )

    assert _run_mw_case("RV32I+GC+*", 32) == _run_mw_case(full_32, 32)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(full_64, 64)
    assert _run_mw_case("RV32I+GC+*", 32) == _run_mw_case(noisy_32, 32)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(noisy_64, 64)

    assert _run_mw_edge_case("RV32I+GC+*", 32) == _run_mw_edge_case(full_32, 32)
    assert _run_mw_edge_case("RV64I+GC+*", 64) == _run_mw_edge_case(full_64, 64)
    assert _run_mw_edge_case("RV32I+GC+*", 32) == _run_mw_edge_case(noisy_32, 32)
    assert _run_mw_edge_case("RV64I+GC+*", 64) == _run_mw_edge_case(noisy_64, 64)

def test_star_extension_star_features_parity_including_zicsr_and_amo_star_for_rv32_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + m + M + a + A + b + B + f + F + d + D + c + C + "+
        "zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND"
    )
    noisy_64 = (
        "  rv64i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + "+
        "ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond"
    )

    assert _run_zicsr_star_case("RV32I+GC+*", 32) == _run_zicsr_star_case(full_32, 32)
    assert _run_zicsr_star_case("RV64I+GC+*", 64) == _run_zicsr_star_case(full_64, 64)
    assert _run_zicsr_star_case("RV32I+GC+*", 32) == _run_zicsr_star_case(noisy_32, 32)
    assert _run_zicsr_star_case("RV64I+GC+*", 64) == _run_zicsr_star_case(noisy_64, 64)

    assert _run_zicsr_star_case("RV32I+GC+*", 32) == _run_zicsr_star_case("RV32I+GC", 32)
    assert _run_zicsr_star_case("RV64I+GC+*", 64) == _run_zicsr_star_case("RV64I+GC", 64)

    assert _run_amo_star_case("RV32I+GC+*", 32) == _run_amo_star_case(full_32, 32)
    assert _run_amo_star_case("RV64I+GC+*", 64) == _run_amo_star_case(full_64, 64)
    assert _run_amo_star_case("RV32I+GC+*", 32) == _run_amo_star_case(noisy_32, 32)
    assert _run_amo_star_case("RV64I+GC+*", 64) == _run_amo_star_case(noisy_64, 64)

def test_star_fp32_case_parity_includes_rv32_and_rv64_and_noisy_variants():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + b + B + f + F + d + D + c + C + "+
        "zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + "+
        "zicond + ZICOND + zicsr + ZICSR + zifencei + ZIFENCEI"
    )

    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(full_32, 32)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(full_64, 64)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(noisy_32, 32)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(noisy_64, 64)

def test_star_system_instruction_mix_parity_for_standard_set_and_noisy_for_rv32_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + "+
        "ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond"
    )
    noisy_64 = (
        "rv64i + gc + ??? + m + M + a + A + b + B + c + C + f + F + d + D + "+
        "zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND"
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

def test_star_system_barrier_and_csrs_parity_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + b + B + C + c + f + F + d + D + "+
        "zifencei + ZIFENCEI + zicond + ZICOND + zicsr + ZICSR"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + c + C + F + f + D + d + "+
        "ZIFENCEI + zifencei + ZICSR + zicsr + ZICOND + zicond"
    )

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

def test_star_control_flow_and_base_parity_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + b + B + C + c + f + F + D + d + "+
        "ZICOND + zicond + ZICSR + zicsr + zifencei + ZIFENCEI"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + c + C + F + f + D + d + "+
        "ZICOND + zicond + zicsr + ZICSR + ZIFENCEI + zifencei"
    )

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(full_64, 64, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(noisy_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(noisy_64, 64, funct3=0b111)

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(full_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(full_64, 64)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(noisy_64, 64)

def test_star_zicond_conditional_variants_parity_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + "+
        "ZICSR + zicsr + ZIFENCEI + zifencei + zicond + ZICOND"
    )
    noisy_64 = (
        "rv64i + gc + ??? + m + M + A + a + b + B + c + C + d + D + f + F + "+
        "ZICSR + zicsr + ZICOND + zicond + ZIFENCEI + zifencei"
    )

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(full_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x00) == _run_zicond_case(full_64, 64, funct3=0b001, rs2=0x00)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0x00) == _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0x00)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x1A) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0x1A)

    assert _run_zicond_case("RV32I+GC+ZICOND", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(full_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+ZICOND", 64, funct3=0b000, rs2=0x00) == _run_zicond_case(full_64, 64, funct3=0b000, rs2=0x00)

def test_star_extension_combo_stability_for_zicond_zicsr_mixed_with_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + b + B + c + C + f + F + d + D + "
        "zifencei + ZIFENCEI + ZICSR + zicsr + zicond + ZICOND"
    )
    noisy_64 = (
        "rv64i + gc + ??? + m + M + A + a + B + b + C + c + F + f + D + d + "
        "ZICOND + zicond + ZICSR + zicsr + ZIFENCEI + zifencei"
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case("RV32I+GC+ZICOND+ZICSR", 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case("RV64I+GC+ZICOND+ZICSR", 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case("RV32I+GC+ZICOND+ZICSR", 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case("RV64I+GC+ZICOND+ZICSR", 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

def test_star_lr_sc_amo_parity_for_full_noisy_and_explicit_star_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + b + B + C + c + F + f + D + d + "+
        "zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + "+
        "ZIFENCEI + zifencei + ZICOND + zicond + ZICSR + zicsr"
    )

    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case(full_32, 32, funct3=0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b011) == _run_lr_sc_case(full_64, 64, funct3=0b011)
    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case(noisy_32, 32, funct3=0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b011) == _run_lr_sc_case(noisy_64, 64, funct3=0b011)

    assert _run_amo_op_case("RV32I+GC+*", 32, 0b00010, 0x2A, 0x55, funct3=0b010) == _run_amo_op_case(
        full_32, 32, 0b00010, 0x2A, 0x55, funct3=0b010
    )
    assert _run_amo_op_case("RV64I+GC+*", 64, 0b00010, 0x2A, 0x55, funct3=0b011) == _run_amo_op_case(
        full_64, 64, 0b00010, 0x2A, 0x55, funct3=0b011
    )
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

def test_star_fp_width_store_parity_for_rv32_and_rv64_full_noisy():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + M + m + A + a + b + B + c + C + F + f + D + d + "+
        "ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond"
    )
    noisy_64 = (
        "rv64i + gc + ??? + m + M + a + A + B + b + C + c + f + F + d + D + "+
        "zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND"
    )

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case("RV32I+GC+F", 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case("RV64I+GC+F", 64)

def test_star_double_precision_parity_for_rv32_and_rv64_full_noisy_and_explicit_d():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + b + B + c + C + d + D + f + F + "+
        "ZICOND + zicond + ZIFENCEI + zifencei + ZICSR + zicsr"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + "+
        "zicond + ZICOND + zifencei + ZIFENCEI + zicsr + ZICSR"
    )

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case("RV32I+GC+D", 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case("RV64I+GC+D", 64)

def test_star_multi_mul_logic_parity_for_rv32_and_rv64_full_noisy_and_explicit_m_b():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + a + A + b + B + c + C + d + D + f + F + m + M + "+
        "ZICOND + zicond + ZICSR + zicsr + ZIFENCEI + zifencei"
    )
    noisy_64 = (
        "rv64i + gc + ??? + A + a + B + b + C + c + D + d + F + f + M + m + "+
        "zicond + ZICOND + zicsr + ZICSR + zifencei + ZIFENCEI"
    )

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

    assert _run_case("RV32I+GC+*", 32) == _run_case("RV32I+GC+M", 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case("RV64I+GC+M", 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case("RV32I+GC+B", 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case("RV64I+GC+B", 64)

def test_star_atomic_compressed_conditional_parity_for_rv32_and_rv64_full_noisy_and_explicit_a_c_zicond():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + b + B + c + C + d + D + f + F + "+
        "zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + "+
        "zifencei + ZIFENCEI + ZICSR + zicsr + zicond + ZICOND"
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case("RV32I+GC+A+C+ZICOND", 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case("RV64I+GC+A+C+ZICOND", 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case("RV32I+GC+A+ZICOND", 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case("RV64I+GC+A+ZICOND", 64)

def test_star_fp_conditional_pack_parity_for_rv32_and_rv64_full_noisy_and_explicit_fd_zicond():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + b + B + c + C + d + D + f + F + "+
        "zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + D + d + F + f + "+
        "ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond"
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case("RV32I+GC+F+D", 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case("RV64I+GC+F+D", 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case("RV32I+GC+F", 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case("RV64I+GC+F", 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case("RV32I+GC+D", 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case("RV64I+GC+D", 64)

def test_star_system_cross_case_parity_for_rv32_and_rv64_full_noisy():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + b + B + C + c + f + F + d + D + "+
        "zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + b + B + C + c + F + f + D + d + "+
        "ZIFENCEI + zifencei + ZICSR + zicsr + ZICOND + zicond"
    )

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case("RV32I+GC+ZIFENCEI", 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case("RV64I+GC+ZIFENCEI", 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case("RV32I+GC+ZICSR", 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case("RV64I+GC+ZICSR", 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

def test_star_b_conditional_mix_parity_for_rv32_and_rv64_full_noisy_and_explicit_b_cond():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + b + B + c + C + d + D + f + F + "+
        "zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + "+
        "zifencei + ZIFENCEI + zicsr + ZICSR + ZICOND + zicond"
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case("RV32I+GC+B+ZICOND", 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case("RV64I+GC+B+ZICOND", 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case("RV32I+GC+B+ZICOND", 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case("RV64I+GC+B+ZICOND", 64)

def test_star_system_combo_parity_for_rv32_and_rv64_full_noisy_and_explicit_sys_pack():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + b + B + c + C + d + D + f + F + "+
        "zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + "+
        "ZICOND + zicond + ZICSR + zicsr + zifencei + ZIFENCEI"
    )

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(
        "RV32I+GC+ZICSR+ZIFENCEI+ZICOND", 32
    )
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(
        "RV64I+GC+ZICSR+ZIFENCEI+ZICOND", 64
    )
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(
        "RV32I+GC+ZICSR+ZIFENCEI+ZICOND", 32
    )
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(
        "RV64I+GC+ZICSR+ZIFENCEI+ZICOND", 64
    )
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

def test_star_base_suite_parity_for_explicit_and_noisy_full_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + b + B + c + C + d + D + f + F + "+
        "zicond + ZICOND + ZICSR + zicsr + zifencei + ZIFENCEI"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + "+
        "ZICOND + zicond + ZICSR + zicsr + ZIFENCEI + zifencei"
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case("RV32I", 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case("RV64I", 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(full_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(full_64, 64)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(noisy_64, 64)

def test_star_fp_d_and_system_combo_parity_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + b + B + c + C + f + F + d + D + "+
        "zicsr + ZICSR + ZIFENCEI + zifencei + zicond + ZICOND"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + "+
        "ZICOND + zicond + ZICSR + zicsr + ZIFENCEI + zifencei"
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case("RV32I+GC+F+D+ZIFENCEI", 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case("RV64I+GC+F+D+ZIFENCEI", 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case("RV32I+GC+F+D+ZIFENCEI+ZICOND", 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case("RV64I+GC+F+D+ZIFENCEI+ZICOND", 64)

def test_star_compressed_extension_parity_for_rv32_and_rv64_full_noisy_and_explicit_c():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + b + B + d + D + f + F + c + C + "+
        "ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + "+
        "zicsr + ZICSR + zifencei + ZIFENCEI + ZICOND + zicond"
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case("RV32I+GC+C", 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case("RV64I+GC+C", 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case("RV32I+GC+C", 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case("RV64I+GC+C", 64)

def test_star_atomic_pack_parity_for_rv32_and_rv64_full_noisy_and_explicit_am():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + b + B + c + C + d + D + f + F + a + A + "+
        "ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + B + b + C + c + D + d + F + f + A + a + "+
        "zicsr + ZICSR + ZIFENCEI + zifencei + ZICOND + zicond"
    )

    assert _run_amo_star_case("RV32I+GC+*", 32) == _run_amo_star_case("RV32I+GC+A", 32)
    assert _run_amo_star_case("RV64I+GC+*", 64) == _run_amo_star_case("RV64I+GC+A", 64)
    assert _run_amo_star_case("RV32I+GC+*", 32) == _run_amo_star_case(full_32, 32)
    assert _run_amo_star_case("RV64I+GC+*", 64) == _run_amo_star_case(full_64, 64)
    assert _run_amo_star_case("RV32I+GC+*", 32) == _run_amo_star_case(noisy_32, 32)
    assert _run_amo_star_case("RV64I+GC+*", 64) == _run_amo_star_case(noisy_64, 64)

    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case("RV32I+GC+A", 32, funct3=0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b011) == _run_lr_sc_case("RV64I+GC+A", 64, funct3=0b011)

def test_star_branch_pack_parity_for_rv32_and_rv64_full_noisy_and_explicit_b():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + c + C + d + D + f + F + B + b + "+
        "ZICSR + zicsr + zifencei + ZIFENCEI + zicond + ZICOND"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + "+
        "ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond"
    )

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case("RV32I+GC+B", 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case("RV64I+GC+B", 64, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(full_64, 64, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(noisy_32, 32, funct3=0b100)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b101) == _run_b_case(noisy_64, 64, funct3=0b101)

def test_star_zicond_zicsr_dual_pack_parity_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + b + B + c + C + d + D + f + F + "+
        "zifencei + ZIFENCEI + ZICOND + zicond + zicsr + ZICSR"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + "+
        "ZIFENCEI + zifencei + zicond + ZICOND + zicsr + ZICSR"
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case("RV32I+GC+ZICOND+ZICSR", 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case("RV64I+GC+ZICOND+ZICSR", 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

def test_star_sys_pack_cross_parity_for_rv32_and_rv64_full_noisy_and_explicit_system():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + b + B + c + C + d + D + f + F + "+
        "zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + "+
        "ZIFENCEI + zifencei + zicsr + ZICSR + zicond + ZICOND"
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case("RV32I+GC+ZICSR+ZIFENCEI", 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case("RV64I+GC+ZICSR+ZIFENCEI", 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case("RV32I+GC+ZICSR+ZIFENCEI", 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case("RV64I+GC+ZICSR+ZIFENCEI", 64)

def test_star_mul_pack_parity_for_rv32_and_rv64_full_noisy_and_explicit_m():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + b + B + a + A + c + C + d + D + f + F + M + m + "+
        "ZICSR + zicsr + zifencei + ZIFENCEI + zicond + ZICOND"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + D + d + F + f + "+
        "zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND"
    )

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case("RV32I+GC+M", 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case("RV64I+GC+M", 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

def test_star_combo_pack_parity_for_rv32_and_rv64_full_noisy_and_explicit_mbf():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + a + A + c + C + d + D + m + M + f + F + "+
        "zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + b + B"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + "+
        "zicond + ZICOND + ZICSR + zicsr + ZIFENCEI + zifencei"
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case("RV32I+GC+M+B+F", 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case("RV64I+GC+M+B+F", 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

def test_star_acb_combo_parity_for_rv32_and_rv64_full_noisy_and_explicit_acb():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + d + D + f + F + zicsr + ZICSR + zifencei + ZIFENCEI + "
        "zicond + ZICOND + a + A + b + B + c + C"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + D + d + F + f + ZICSR + zicsr + ZIFENCEI + zifencei + "
        "ZICOND + zicond + A + a + B + b + C + c"
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case("RV32I+GC+A+B+C", 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case("RV64I+GC+A+B+C", 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

def test_star_fd_combo_parity_for_rv32_and_rv64_full_noisy_and_explicit():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + A + a + B + b + C + c + zicsr + ZICSR + "
        "zifencei + ZIFENCEI + zicond + ZICOND + F + f + d + D"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + ZICSR + zicsr + "
        "ZIFENCEI + zifencei + ZICOND + zicond + F + f + D + d"
    )

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case("RV32I+GC+F+D", 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case("RV64I+GC+F+D", 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case("RV32I+GC+F", 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case("RV64I+GC+F", 64)

def test_star_system_combo_all_stars_parity_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + A + a + B + b + C + c + F + f + D + d + "
        "ZICOND + zicond + ZICSR + zicsr + ZIFENCEI + zifencei"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + a + A + B + b + C + c + F + f + D + d + "
        "zicond + ZICOND + zicsr + ZICSR + zifencei + ZIFENCEI"
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case("RV32I+GC+M+A+B+C+F+D+ZICOND+ZICSR+ZIFENCEI", 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case("RV64I+GC+M+A+B+C+F+D+ZICOND+ZICSR+ZIFENCEI", 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

def test_star_atomic_logic_conditional_parity_for_rv32_and_rv64_full_noisy_and_explicit_abczicond():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + f + F + d + D + zicsr + ZICSR + "
        "zifencei + ZIFENCEI + zicond + ZICOND + a + A + b + B + c + C"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + F + f + D + d + ZICSR + zicsr + "
        "ZIFENCEI + zifencei + ZICOND + zicond + A + a + B + b + C + c"
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case("RV32I+GC+A+B+C+ZICOND", 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case("RV64I+GC+A+B+C+ZICOND", 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

def test_star_mab_and_zicond_combo_parity_for_rv32_and_rv64_full_noisy():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + c + C + d + D + f + F + zicsr + ZICSR + "+
        "zifencei + ZIFENCEI + zicond + ZICOND + a + A + b + B"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + C + c + D + d + F + f + zicsr + ZICSR + "+
        "ZIFENCEI + zifencei + ZICOND + zicond + A + a + B + b"
    )

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case("RV32I+GC+M+A+B+ZICOND", 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case("RV64I+GC+M+A+B+ZICOND", 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

def test_star_c_sys_pack_parity_for_rv32_and_rv64_full_noisy_and_explicit():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + A + a + B + b + d + D + F + f + "+
        "zifencei + ZIFENCEI + zicond + ZICOND + zicsr + ZICSR + C + c"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + D + d + "+
        "ZICOND + zicond + zicsr + ZICSR + ZIFENCEI + zifencei + F + f"
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case("RV32I+GC+C+ZICSR+ZIFENCEI", 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case("RV64I+GC+C+ZICSR+ZIFENCEI", 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

def test_star_all_system_combo_parity_for_rv32_and_rv64_full_noisy():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + A + a + B + b + C + c + f + F + d + D + "+
        "zicond + ZICOND + zicsr + ZICSR + zifencei + ZIFENCEI"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + "+
        "ZICOND + zicond + ZICSR + zicsr + ZIFENCEI + zifencei"
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case("RV32I+GC+ZICOND+ZICSR+ZIFENCEI", 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case("RV64I+GC+ZICOND+ZICSR+ZIFENCEI", 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

def test_star_all_system_mix_parity_for_rv32_and_rv64_full_noisy():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + A + a + B + b + C + c + f + F + d + D + "+
        "zifencei + ZIFENCEI + zicond + ZICOND + zicsr + ZICSR"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + "+
        "ZICOND + zicond + ZICSR + zicsr + zifencei + ZIFENCEI"
    )

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case("RV32I+GC+ZICOND+ZICSR+ZIFENCEI", 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case("RV64I+GC+ZICOND+ZICSR+ZIFENCEI", 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

def test_star_ma_combo_parity_for_rv32_and_rv64_full_noisy_and_explicit_ma():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + B + b + C + c + d + D + f + F + "+
        "zicond + ZICOND + zicsr + ZICSR + zifencei + ZIFENCEI + A + a"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + B + b + C + c + D + d + F + f + "+
        "ZICOND + zicond + ZICSR + zicsr + ZIFENCEI + zifencei + A + a"
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case("RV32I+GC+M+A", 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case("RV64I+GC+M+A", 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

def test_star_zicond_base_parity_for_rv32_and_rv64_full_noisy_and_explicit():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + A + a + B + b + C + c + f + F + D + d + "+
        "zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + b + B + C + c + D + d + F + f + "+
        "ZICOND + zicond + ZICSR + zicsr + ZIFENCEI + zifencei"
    )

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case("RV32I+GC+ZICOND", 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case("RV64I+GC+ZICOND", 64)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(full_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(full_64, 64)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(noisy_64, 64)


def test_star_atomic_memory_pack_parity_for_rv32_and_rv64_with_am_explicit_noisy_full():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + b + B + c + C + d + D + f + F + "
        "zicond + ZICOND + ZICSR + zicsr + zifencei + ZIFENCEI"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + D + d + F + f + "
        "ZICOND + zicond + ZICSR + zicsr + ZIFENCEI + zifencei"
    )

    assert _run_mw_case("RV32I+GC+*", 32) == _run_mw_case("RV32I+GC+M+A", 32)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case("RV64I+GC+M+A", 64)
    assert _run_mw_case("RV32I+GC+*", 32) == _run_mw_case(full_32, 32)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(full_64, 64)
    assert _run_mw_case("RV32I+GC+*", 32) == _run_mw_case(noisy_32, 32)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(noisy_64, 64)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case("RV32I+GC+A", 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case("RV64I+GC+A", 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

def test_star_ab_combo_parity_for_rv32_and_rv64_full_noisy_and_explicit_ab():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + c + C + d + D + f + F + "+
        "zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + b + B"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + a + A + B + b + C + c + D + d + F + f + "+
        "ZICOND + zicond + zicsr + ZICSR + ZIFENCEI + zifencei"
    )

    assert _run_mw_case("RV32I+GC+*", 32) == _run_mw_case("RV32I+GC+A+B", 32)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case("RV64I+GC+A+B", 64)
    assert _run_mw_case("RV32I+GC+*", 32) == _run_mw_case(full_32, 32)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(full_64, 64)
    assert _run_mw_case("RV32I+GC+*", 32) == _run_mw_case(noisy_32, 32)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(noisy_64, 64)

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case("RV32I+GC+A+B", 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case("RV64I+GC+A+B", 64)

def test_star_c_zicond_mix_parity_for_rv32_and_rv64_full_noisy_and_explicit():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + b + B + d + D + F + f + "+
        "zifencei + ZIFENCEI + zicsr + ZICSR + C + c + zicond + ZICOND"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + D + d + F + f + "+
        "ZICOND + zicond + zicsr + ZICSR + zifencei + ZIFENCEI"
    )

    assert _run_mw_case("RV32I+GC+*", 32) == _run_mw_case("RV32I+GC+C+ZICOND", 32)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case("RV64I+GC+C+ZICOND", 64)
    assert _run_mw_case("RV32I+GC+*", 32) == _run_mw_case(full_32, 32)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(full_64, 64)
    assert _run_mw_case("RV32I+GC+*", 32) == _run_mw_case(noisy_32, 32)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(noisy_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case("RV32I+GC+C", 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case("RV64I+GC+C", 64)

def test_star_mw_edge_and_amo_star_parity_for_rv32_and_rv64_full_noisy_and_explicit_mb():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + c + C + d + D + f + F + "+
        "zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + b + B"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + a + A + B + b + C + c + D + d + F + f + "+
        "ZICOND + zicond + ZICSR + zicsr + ZIFENCEI + zifencei"
    )

    assert _run_mw_edge_case("RV32I+GC+*", 32) == _run_mw_edge_case("RV32I+GC+M+B", 32)
    assert _run_mw_edge_case("RV64I+GC+*", 64) == _run_mw_edge_case("RV64I+GC+M+B", 64)
    assert _run_mw_edge_case("RV32I+GC+*", 32) == _run_mw_edge_case(full_32, 32)
    assert _run_mw_edge_case("RV64I+GC+*", 64) == _run_mw_edge_case(full_64, 64)
    assert _run_mw_edge_case("RV32I+GC+*", 32) == _run_mw_edge_case(noisy_32, 32)
    assert _run_mw_edge_case("RV64I+GC+*", 64) == _run_mw_edge_case(noisy_64, 64)

    assert _run_amo_star_case("RV32I+GC+*", 32) == _run_amo_star_case("RV32I+GC+M+B", 32)
    assert _run_amo_star_case("RV64I+GC+*", 64) == _run_amo_star_case("RV64I+GC+M+B", 64)
    assert _run_amo_star_case("RV32I+GC+*", 32) == _run_amo_star_case(full_32, 32)
    assert _run_amo_star_case("RV64I+GC+*", 64) == _run_amo_star_case(full_64, 64)
    assert _run_amo_star_case("RV32I+GC+*", 32) == _run_amo_star_case(noisy_32, 32)
    assert _run_amo_star_case("RV64I+GC+*", 64) == _run_amo_star_case(noisy_64, 64)

def test_star_c_f_system_combo_parity_for_rv32_and_rv64_full_noisy_and_explicit():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + b + B + d + D + "+
        "zifencei + ZIFENCEI + zicond + ZICOND + zicsr + ZICSR + C + c + F + f"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + D + d + "+
        "ZICOND + zicond + zicsr + ZICSR + ZIFENCEI + zifencei + C + c + F + f"
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case("RV32I+GC+C+F+ZICOND+ZICSR+ZIFENCEI", 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case("RV64I+GC+C+F+ZICOND+ZICSR+ZIFENCEI", 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case("RV32I+GC+C+F+ZICOND+ZICSR+ZIFENCEI", 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case("RV64I+GC+C+F+ZICOND+ZICSR+ZIFENCEI", 64)

def test_star_d_system_combo_parity_for_rv32_and_rv64_full_noisy_and_explicit():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + b + B + c + C + f + F + "+
        "zifencei + ZIFENCEI + zicond + ZICOND + zicsr + ZICSR + D + d"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + B + b + C + c + F + f + "+
        "ZICOND + zicond + ZICSR + zicsr + ZIFENCEI + zifencei + D + d"
    )

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case("RV32I+GC+D+ZICSR+ZIFENCEI+ZICOND", 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case("RV64I+GC+D+ZICSR+ZIFENCEI+ZICOND", 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case("RV32I+GC+D+ZICSR+ZIFENCEI+ZICOND", 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case("RV64I+GC+D+ZICSR+ZIFENCEI+ZICOND", 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

def test_star_ac_system_pack_parity_for_rv32_and_rv64_full_noisy_and_explicit():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + b + B + d + D + f + F + c + C + "+
        "zicond + ZICOND + zicsr + ZICSR + zifencei + ZIFENCEI + a + A"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + B + b + D + d + F + f + C + c + "+
        "ZICOND + zicond + ZICSR + zicsr + ZIFENCEI + zifencei + a + A"
    )

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case("RV32I+GC+A+C+ZICOND+ZICSR+ZIFENCEI", 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case("RV64I+GC+A+C+ZICOND+ZICSR+ZIFENCEI", 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case("RV32I+GC+A+C+ZICOND+ZICSR+ZIFENCEI", 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case("RV64I+GC+A+C+ZICOND+ZICSR+ZIFENCEI", 64)

def test_star_mf_system_combo_parity_for_rv32_and_rv64_full_noisy_and_explicit():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + b + B + a + A + c + C + d + D + "+
        "zifencei + ZIFENCEI + zicond + ZICOND + zicsr + ZICSR + M + m + F + f"
    )
    noisy_64 = (
        "rv64i + gc + ??? + B + b + A + a + C + c + D + d + "+
        "ZICOND + zicond + ZICSR + zicsr + ZIFENCEI + zifencei + M + m + F + f"
    )

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case("RV32I+GC+M+F", 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case("RV64I+GC+M+F", 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case("RV32I+GC+M+F+ZICOND+ZICSR+ZIFENCEI", 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case("RV64I+GC+M+F+ZICOND+ZICSR+ZIFENCEI", 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

def test_star_bc_sys_combo_parity_for_rv32_and_rv64_full_noisy_and_explicit():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + d + D + f + F + c + C + "+
        "zicond + ZICOND + zifencei + ZIFENCEI + B + b + zicsr + ZICSR"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + D + d + F + f + c + C + "+
        "ZICOND + zicond + ZIFENCEI + zifencei + B + b + ZICSR + zicsr"
    )

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case("RV32I+GC+B+C+ZICSR", 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case("RV64I+GC+B+C+ZICSR", 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case("RV32I+GC+B+C+ZICSR", 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case("RV64I+GC+B+C+ZICSR", 64)

def test_star_a_zicond_combo_parity_for_rv32_and_rv64_full_noisy_and_explicit():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + b + B + c + C + d + D + f + F + "+
        "zifencei + ZIFENCEI + ZICOND + zicond + zicsr + ZICSR + a + A"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + B + b + C + c + D + d + F + f + "+
        "ZIFENCEI + zifencei + ZICOND + zicond + ZICSR + zicsr + a + A"
    )

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case("RV32I+GC+A+ZICOND", 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case("RV64I+GC+A+ZICOND", 64, funct3=0b001, rs2=0x0F)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case("RV32I+GC+A+ZICOND+ZICSR", 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case("RV64I+GC+A+ZICOND+ZICSR", 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case("RV32I+GC+A+ZICOND+ZICSR", 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case("RV64I+GC+A+ZICOND+ZICSR", 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

def test_star_bf_ifence_parity_for_rv32_and_rv64_full_noisy_and_explicit():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + c + C + d + D + zicond + ZICOND + zicsr + ZICSR + "+
        "F + f + B + b + zifencei + ZIFENCEI"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + A + a + C + c + D + d + ZICOND + zicond + ZICSR + zicsr + "+
        "F + f + B + b + ZIFENCEI + zifencei"
    )

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case("RV32I+GC+B+F+ZIFENCEI", 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case("RV64I+GC+B+F+ZIFENCEI", 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case("RV32I+GC+B+F+ZIFENCEI", 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case("RV64I+GC+B+F+ZIFENCEI", 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

def test_star_fd_system_width_pack_parity_for_rv32_and_rv64_full_noisy_and_explicit():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + b + B + c + C + ZICSR + zicsr + ZIFENCEI + zifencei + "+
        "zicond + ZICOND + F + f + D + d"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + a + A + B + b + C + c + zicsr + ZICSR + zifencei + ZIFENCEI + "+
        "ZICOND + zicond + F + f + D + d"
    )

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case("RV32I+GC+F+D+ZICOND+ZICSR+ZIFENCEI", 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case("RV64I+GC+F+D+ZICOND+ZICSR+ZIFENCEI", 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case("RV32I+GC+F+D+ZICOND+ZICSR+ZIFENCEI", 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case("RV64I+GC+F+D+ZICOND+ZICSR+ZIFENCEI", 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case("RV32I+GC+F+D+ZICOND+ZICSR+ZIFENCEI", 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case("RV64I+GC+F+D+ZICOND+ZICSR+ZIFENCEI", 64)

def test_star_mbc_pack_parity_for_rv32_and_rv64_full_noisy_and_explicit():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + a + A + d + D + f + F + zicsr + ZICSR + "+
        "zifencei + ZIFENCEI + zicond + ZICOND + B + b + c + C"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + a + A + D + d + F + f + ZICSR + zicsr + "+
        "ZIFENCEI + zifencei + ZICOND + zicond + B + b + C + c"
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case("RV32I+GC+M+B+C", 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case("RV64I+GC+M+B+C", 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case("RV32I+GC+M+B+C", 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case("RV64I+GC+M+B+C", 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)

def test_star_a_zicsr_zifencei_pack_parity_for_rv32_and_rv64_full_noisy_and_explicit():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i + gc + ??? + m + M + b + B + c + C + d + D + f + F + "+
        "zicond + ZICOND + A + a + zicsr + ZICSR + zifencei + ZIFENCEI"
    )
    noisy_64 = (
        "rv64i + gc + ??? + M + m + B + b + C + c + D + d + F + f + "+
        "ZICOND + zicond + A + a + ZICSR + zicsr + ZIFENCEI + zifencei"
    )

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case("RV32I+GC+A+ZICSR+ZIFENCEI", 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case("RV64I+GC+A+ZICSR+ZIFENCEI", 64)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(full_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(full_64, 64)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case("RV32I+GC+A+ZICSR+ZIFENCEI", 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case("RV64I+GC+A+ZICSR+ZIFENCEI", 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case("RV32I+GC+A+ZICSR+ZIFENCEI", 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case("RV64I+GC+A+ZICSR+ZIFENCEI", 64)

def test_star_matches_full_standard_set_with_unknown_noise_tokens_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + M + m + A + zba + b + C + ZBA + F + D + d + ZICSR + ZIFENCEI + ZICOND + ZICOND + ZXYZ + ZZZ_BAD + "
    noisy_64 = "  rv64i + gc + ??? + zifencei + m + M + zicsr + A + a + B + b + C + c + ZICOND + F + D + FOO_UNKNOWN + "

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

def test_star_matches_full_standard_set_for_rv32_including_critical_runtime_points():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(full_32, 32, funct3=0b000, rs2=0)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)

def test_star_matches_standard_set_for_rv32_b_aliases_and_mixed_extensions():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(full_32, 32, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(full_32, 32, funct3=0b100)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)

def test_star_full_set_and_noisy_standard_spec_equivalent_on_rv32_paths():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + zba + ZBB + zbkb + m + a + zifencei + C + "
        "f + D + zicond + zicsr + B + zzzz + "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        full_32, 32, funct3=0b001, rs2=0x0F
    )

def test_star_and_noisy_spec_keep_fp32_behavior_on_rv32():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + f + d + F + ZBA + b + M + A + ZICOND + "+
        "ZICSR + zifencei + C + zxxxx + "
    )

    assert _run_fp32_case("RV32I+GC", 32) == _run_fp32_case(full_32, 32)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(full_32, 32)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(noisy_32, 32)

def test_rv32_parser_robustness_for_star_still_matches_base_and_full_standard_behavior():
    noisy_32 = (
        "  rv32i + gc + ??? + M + m + A + a + B + b + C + c + F + D + f + d + "
        "ZICSR + zifencei + ZIFENCEI + ZICOND + ZZZ + zbad + "
    )

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_base_case("RV32I+GC", 32) == _run_base_case(noisy_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case("RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND", 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case("RV32I+GC+M", 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case("RV32I+GC+A", 32)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case("RV32I+GC+B", 32, funct3=0b110)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case("RV32I+GC+ZICSR", 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case("RV32I+GC+ZIFENCEI", 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        "RV32I+GC+ZICOND", 32, funct3=0b001, rs2=0x0F
    )

def test_star_and_noisy_runtime_equivalence_for_rv32_mixed_full_extensions():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + ZIFENCEI + ZICSR + ZICOND + ZBH + ZBA + "
        "B + b + A + a + M + m + C + F + f + D + d + zzzz + "
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(full_32, 32, funct3=0b000, rs2=0)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)

def test_star_standard_equivalence_with_noisy_full_spec_on_rv32():
    noisy_32 = (
        "  rv32i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + "
        "ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + ZZZ_BAD + "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(noisy_32, 32, funct3=0b111)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        noisy_32, 32, funct3=0b001, rs2=0x0F
    )

def test_star_coverage_against_noisy_standard_spec_with_duplicates_on_rv32():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + m + M + a + A + b + B + c + C + f + F + d + D + "
        "zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND + ZUNK + "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(full_32, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(noisy_32, 32, funct3=0b100)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0) == _run_zicond_case(
        full_32, 32, funct3=0b001, rs2=0
    )

def test_rv32_star_orderless_noisy_tokens_still_match_full_standard_set():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_permute_32 = (
        "  rv32i + gc + ??? + ZICSR + B + zifencei + A + M + F + d + ZICOND + "
        "c + b + zba + ZBK + zzzz + "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_permute_32, 32)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_permute_32, 32)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_permute_32, 32)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_permute_32, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_permute_32, 32)

def test_star_canonical_bop_equivalence_on_rv32_full_set():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    b_aliases_noisy = "  rv32i + gc + ??? + ZBB + ZBS + ZBK + ZBE + ZBF + ZBM + ZBA + zba + b + B + ZBKB + "

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(full_32, 32, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(full_32, 32, funct3=0b100)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(b_aliases_noisy, 32, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(b_aliases_noisy, 32, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(b_aliases_noisy, 32, funct3=0b100)

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(b_aliases_noisy, 32)

def test_star_fp_d_csr_fencei_zicond_equivalence_on_rv32():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_mix_32 = (
        "  rv32i + gc + ??? + ZIFENCEI + F + f + D + d + M + A + ZICSR + zicsr + "+
        "ZICOND + zicond + B + b + C + c + unknown + "
    )

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_mix_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_mix_32, 32)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_mix_32, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_mix_32, 32)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0) == _run_zicond_case(
        full_32, 32, funct3=0b001, rs2=0
    )
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_mix_32, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0x0F) == _run_zicond_case(
        noisy_mix_32, 32, funct3=0b000, rs2=0x0F
    )

def test_star_atomic_mixed_extensions_equivalence_on_rv32_full_vs_noisy():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + m + A + B + C + F + D + a + f + d + zicond + "
        "ZICSR + zifencei + zzz + zba + b + "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(noisy_32, 32, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(full_32, 32, funct3=0b100)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        full_32, 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)

def test_star_idempotent_parser_with_noisy_tokens_on_rv32_mixed_standard_set():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + M + m + A + a + B + b + C + c + F + f + "
        "D + d + ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + "
        "ZBKB + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + ZBZ + ZBI + "+
        "ZUNKNOW + "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        noisy_32, 32, funct3=0b001, rs2=0x0F
    )

def test_rv32_star_parity_across_base_mabf_d_csr_fencei_zicond_in_noisy_specs():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + C + c + M + m + A + a + B + b + ZBA + ZBH + "
        "ZBB + F + f + D + d + ZICSR + zifencei + ZIFENCEI + ZICOND + zicond + "
        "XXX + "
    )

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(full_32, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(full_32, 32, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(noisy_32, 32, funct3=0b100)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0x0F) == _run_zicond_case(
        noisy_32, 32, funct3=0b000, rs2=0x0F
    )

def test_rv32_star_full_set_stability_for_multi_combo_and_noisy_aliases():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + ZBA + ZBK + zba + zbkb + ZBB + ZBS + A + a + B + b + C + c + M + m + F + f + D + d + ZICSR + zifencei + ZICOND + zicond + "

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)

def test_rv32_star_full_noisy_combination_equivalence_for_base_m_amo_b_extensions():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + B + b + A + a + M + m + C + c + F + f + D + d + "
        "ZICSR + zifencei + ZIFENCEI + zicsr + ZICOND + zicond + GARBAGE + "
    )

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(full_32, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0x0F) == _run_zicond_case(
        full_32, 32, funct3=0b000, rs2=0x0F
    )

def test_rv32_star_b_variants_and_multi_paths_match_full_set_with_noise():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + ZBKB + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
        "ZBH + ZBA + B + b + A + a + M + m + C + c + F + f + D + d + "
        "ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + "
    )

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case("RV32I+GC+B", 32, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case("RV32I+GC+B", 32, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case("RV32I+GC+B", 32, funct3=0b100)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(full_32, 32, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(noisy_32, 32, funct3=0b100)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)

def test_rv32_star_csr_fencei_zicond_with_fp_d_b_m_a_noisy_spec_parity():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + ZICOND + zicond + ZIFENCEI + zifencei + ZICSR + zicsr + "
        "D + d + F + f + B + b + M + m + A + a + C + c + random + "
    )

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        full_32, 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)

def test_rv32_star_fp32_path_matches_full_and_noisy_standard_specs():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + F + f + D + d + M + m + A + a + B + b + C + c + "
        "ZICSR + zifencei + ZIFENCEI + ZICOND + zicond + EXTRA + "
    )

    assert _run_fp32_case("RV32I+GC", 32) == _run_fp32_case(full_32, 32)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(full_32, 32)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(noisy_32, 32)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)

def test_rv32_star_case_m_amo_b_combo_parity_with_full_noisy_standard_set():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + c + C + m + M + A + a + A + b + B + zba + ZBA + "
        "F + f + D + d + ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + ZZ + "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(noisy_32, 32, funct3=0b100)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0) == _run_zicond_case(
        noisy_32, 32, funct3=0b001, rs2=0
    )

def test_rv32_star_fp_d_zicsr_zifencei_zicond_full_noisy_parity():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + F + f + D + d + ZICSR + zicsr + ZIFENCEI + zifencei + "
        "ZICOND + zicond + M + m + A + a + B + b + C + c + X_UNKNOWN + "
    )

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(
        full_32, 32, funct3=0b000, rs2=0
    )
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0) == _run_zicond_case(
        noisy_32, 32, funct3=0b001, rs2=0
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)

def test_rv32_star_noisy_full_set_equivalence_for_core_and_system_mix():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + "
        "ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + NOISE + "
    )

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(full_32, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(full_32, 32, funct3=0b111)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0x0F) == _run_zicond_case(
        noisy_32, 32, funct3=0b000, rs2=0x0F
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)

def test_rv32_star_fp_d_and_system_mix_stability_for_full_vs_noisy_spec():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + C + c + F + f + D + d + M + m + A + a + B + b + "
        "ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + ZZZZ + "
    )

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        full_32, 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(
        noisy_32, 32, funct3=0b000, rs2=0
    )

def test_rv32_star_multi_extension_stack_matches_full_set_for_core_system_noisy_spec():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + M + m + A + a + B + b + C + c + F + f + D + d + "
        "ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + UNKNOWN + "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0) == _run_zicond_case(
        noisy_32, 32, funct3=0b001, rs2=0
    )
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)

def test_rv32_star_standard_set_resilience_with_b_variants_and_system_ext_mix():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + b + B + zba + ZBA + zbkb + ZBB + M + m + A + a + F + f + "
        "D + d + C + c + ZICSR + zicsr + ZICOND + zicond + ZIFENCEI + zifencei + GARBAGE + "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(full_32, 32)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(noisy_32, 32, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(
        noisy_32, 32, funct3=0b000, rs2=0
    )

def test_rv32_star_system_extensions_and_fp_d_fullstack_equivalence_with_noisy_standard_spec():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + ZIFENCEI + zifencei + ZICSR + zicsr + ZICOND + zicond + "
        "F + f + D + d + M + m + A + a + B + b + C + c + NOISE + "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        full_32, 32, funct3=0b001, rs2=0x0F
    )

def test_rv32_star_full_and_noisy_spec_mix_stability_for_multi_extension_stack():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + B + b + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + "
        "M + m + A + a + C + c + F + f + D + d + ZICSR + zifencei + ZIFENCEI + "
        "ZICOND + zicond + UNKNOWN + "
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        full_32, 32, funct3=0b001, rs2=0x0F
    )

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(full_32, 32, funct3=0b100)


def test_rv64_star_full_and_noisy_spec_mix_stability_for_standard_extension_stack():
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_64 = (
        "  rv64i + gc + ??? + M + m + A + a + C + c + F + f + D + d + "
        "ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + UNKNOWN + "
    )

    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)
    assert _run_case("RV64I+GC+*", 64) == _run_case(" rv64i + GC + * ", 64)

    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(noisy_64, 64, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(full_64, 64, funct3=0b110)

    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        full_64, 64, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(
        noisy_64, 64, funct3=0b000, rs2=0
    )


def test_rv32_star_profile_matches_full_set_and_noisy_variants_for_all_core_cases():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  RV32I + gc + ??? + m + A + b + ZBKB + B + c + F + d + D + "
        "M + ZICSR + zicond + ZICOND + zifencei + ZIFENCEI + UNKNOWN + "
    )

    # Base program behavior must remain identical for pure +* and explicit full set / noisy specs.
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(full_32, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)

    # Explicit-extension feature checks.
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(full_32, 32, 0b010)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(noisy_32, 32, 0b010)

    # Bit-manipulation aliases should be accepted and equivalent under +*.
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(noisy_32, 32, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(noisy_32, 32, funct3=0b100)

    # FP/D and system extensions.
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)

    # System extension helpers.
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        noisy_32, 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(
        full_32, 32, funct3=0b000, rs2=0
    )

    # Cross-check mixed-extension stack and parser-tolerant noisy specs.
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)


def test_rv64_star_profile_matches_full_set_and_noisy_variants_for_all_core_cases():
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_64 = (
        "  rv64i + gc + ??? + ZBA + zba + ZBB + ZICOND + zicond + B + b + "
        "M + m + A + a + C + c + F + f + D + d + ZICSR + zicsr + "
        "ZIFENCEI + zifencei +  ZBK + zbk + UNKNOWN + "
    )

    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(full_64, 64)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(noisy_64, 64)
    assert _run_case("RV64I+GC+*", 64) == _run_case(" rv64i + GC + * ", 64)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(full_64, 64)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(noisy_64, 64)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(full_64, 64, 0b011)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(noisy_64, 64, 0b011)

    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(full_64, 64, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_64, 64, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b100) == _run_b_case(full_64, 64, funct3=0b100)

    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        full_64, 64, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(
        noisy_64, 64, funct3=0b000, rs2=0
    )

    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)


def test_rv32_and_rv64_star_profiles_align_on_explicit_full_set_and_noisy_variants():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  RV32I + gc + ??? + M + A + B + C + F + D + ZICSR + zicsr + "
        "ZIFENCEI + zifencei + ZICOND + zicond + N0ISE + "
    )
    noisy_64 = (
        "  rv64i + GC + ??? + m + a + b + c + f + d + ZICSR + zicsr + "
        "ZIFENCEI + zifencei + ZICOND + zicond +  ?? + "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(noisy_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(noisy_64, 64, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(full_64, 64, funct3=0b110)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(full_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(full_64, 64, 0b011)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(full_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        noisy_32, 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(
        full_64, 64, funct3=0b000, rs2=0
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)


def test_parser_robustness_for_star_profile_with_redundant_noisy_standard_tokens():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + + + + m + A + M + b + ZBA + zba + B + C + C + f + F + "
        "d + D + d + zifencei + ZIFENCEI + ZICSR + zicsr + zicond + ZICOND + N0ISE + "
        "??? + garbage + gc + M + "
    )
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_64 = (
        "  RV64I + gc + m + M + a + A + B + b + ZBB + zbb + C + c + F + f + D + d + "
        "ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + ??? + UNKNOWN + "
    )

    # Parser robustness and dedup behavior.
    assert _run_case("RV32I+GC+*", 32) == _run_case("  RV32I + GC + *  ", 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case("  RV64I + gc + *  ", 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(full_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(full_64, 64)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(noisy_64, 64)

    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(full_32, 32)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(noisy_32, 32)

    # Cross extension feature checks under parser-noise stress.
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(noisy_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(noisy_64, 64, 0b011)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(noisy_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(noisy_64, 64, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_64, 64, funct3=0b110)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        noisy_32, 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(
        noisy_64, 64, funct3=0b000, rs2=0
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)


def test_star_profile_standard_set_full_coverage_on_explicit_and_alias_order_variants():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "gc + RV32I + ZBA + ZBK + ZBE + ZBF + ZBM + B + b + M + m + A + a + "
        "C + c + F + f + D + d + ZICSR + zicsr + ZIFENCEI + zifencei + "
        "ZICOND + zicond + ??? + NOP + * + "
    )
    noisy_64 = (
        " GC + rv64i + zifencei + ZIFENCEI + ZICSR + zicsr + ZICOND + zicond + "
        "B + b + M + A + C + F + D + f + d + a + m + ZBB + zbb + ZBS + zbs + "
        "+++ + ??? + garbage + "
    )

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(full_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(full_64, 64)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(noisy_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(noisy_32, 32, funct3=0b100)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b100) == _run_b_case(noisy_64, 64, funct3=0b100)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(full_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(full_64, 64, funct3=0b111)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(noisy_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(noisy_64, 64, 0b011)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        noisy_32, 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(
        full_64, 64, funct3=0b000, rs2=0
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)


def test_star_profile_explicit_matrix_full_vs_noisy_stability():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " RV32I + GC + m + A + b + ZBA + zba + B + C + c + F + f + D + d + "
        "ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + "
        " ??? + garbage + "
    )
    noisy_64 = (
        " rv64i + gc + M + a + B + b + C + c + F + f + D + d + ZICSR + zicsr + "
        "ZIFENCEI + zifencei + ZICOND + zicond + "
        " ??? + UNKNOWN + "
    )

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case("RV32I+GC", 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case("RV64I+GC", 64)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(noisy_64, 64)

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case("RV32I+GC+M", 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case("RV64I+GC+M", 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case("RV32I+GC+F", 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case("RV64I+GC+F", 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case("RV32I+GC+D", 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case("RV64I+GC+D", 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case("RV32I+GC", 32)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(noisy_32, 32)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case("RV32I+GC+B", 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case("RV64I+GC+B", 64, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(noisy_32, 32, funct3=0b100)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b100) == _run_b_case(noisy_64, 64, funct3=0b100)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case("RV32I+GC+A", 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case("RV64I+GC+A", 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case("RV32I+GC+A", 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case("RV64I+GC+A", 64, 0b011)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case("RV64I+GC+M", 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case("RV32I+GC+ZICSR", 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case("RV64I+GC+ZICSR", 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case("RV32I+GC+ZIFENCEI", 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case("RV64I+GC+ZIFENCEI", 64)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        "RV32I+GC+ZICOND", 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(
        noisy_64, 64, funct3=0b000, rs2=0
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)


def test_star_profile_parser_priority_with_reordered_and_repeated_standard_aliases():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    ordered_32 = "RV32I + GC + ZICOND + zicond + ZICSR + ZIFENCEI + D + d + F + f + C + c + B + b + A + a + M + m"
    repeated_32 = "rv32i + gc + M + m + M + a + A + B + B + b + zba + ZBKB + zicond + zicond + C + c + D + d + F + F + zifencei + zifencei + ZICSR + zicsr + ???"

    ordered_64 = "rv64i + GC + zicond + ZICOND + zicsr + ZICSR + zifencei + ZIFENCEI + d + D + c + C + b + B + a + A + m + M"
    repeated_64 = "RV64I + gc + D + d + M + m + M + A + b + B + ZBB + ZBS + F + f + C + c + zifencei + ZIFENCEI + zicond + ZICOND + ??? + garbage"

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(full_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(full_64, 64)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(ordered_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(ordered_64, 64)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(repeated_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(repeated_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(ordered_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(ordered_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(repeated_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(repeated_64, 64)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(ordered_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(ordered_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(repeated_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(repeated_64, 64)

    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(ordered_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(ordered_64, 64, 0b011)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(repeated_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(repeated_64, 64, 0b011)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(ordered_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(ordered_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(repeated_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(repeated_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(ordered_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(ordered_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(repeated_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(repeated_64, 64)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(ordered_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(ordered_64, 64, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(repeated_32, 32, funct3=0b100)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b100) == _run_b_case(repeated_64, 64, funct3=0b100)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(ordered_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(ordered_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(repeated_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(repeated_64, 64)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        ordered_32, 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(
        ordered_64, 64, funct3=0b000, rs2=0
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(repeated_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(repeated_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(ordered_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(ordered_64, 64)


def test_star_profile_extensional_gap_fill_with_aliases_and_unknown_tokens():
    explicit_full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    alias_gap_32 = (
        " RV32I + gc + zba + ZBKB + zbe + ZBE + zbf + ZBF + zbm + ZBM + "
        "zbb + ZBB + zbs + ZBS + C + B + F + D + A + M + "
        "ZIFENCEI + ZICSR + ZICOND + ??? + RND + "
    )
    alias_gap_64 = (
        " rv64i + GC + M + A + B + C + F + D + zifencei + ZIFENCEI + "
        "zicsr + ZICSR + zicond + ZICOND + ZBA + ZBK + ZBF + zbs + "
        "ZBS + ??? + ??? + NOP + "
    )

    noise_gap_32 = (
        " RV32I + GC + M + A + B + C + F + D + ZICSR + zicsr + "
        "ZIFENCEI + zifencei + ZICOND + zicond + ### + ! + "
    )
    noise_gap_64 = (
        " rv64i + GC + m + a + b + c + f + d + zicsr + ZICSR + "
        "zifencei + ZIFENCEI + zicond + ZICOND + ... + junk + "
    )

    # Base equivalence with explicit full-set definitions.
    assert _run_case("RV32I+GC+*", 32) == _run_case(explicit_full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(explicit_full_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noise_gap_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noise_gap_64, 64)

    # M/A/atomic coverage.
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(alias_gap_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(alias_gap_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(alias_gap_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(alias_gap_64, 64)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(alias_gap_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(alias_gap_64, 64, 0b011)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(alias_gap_64, 64)

    # Bitmanipulation alias acceptance.
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(alias_gap_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(alias_gap_64, 64, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(alias_gap_32, 32, funct3=0b100)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b100) == _run_b_case(alias_gap_64, 64, funct3=0b100)

    # FP/D/system.
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(alias_gap_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(alias_gap_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(alias_gap_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(alias_gap_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(alias_gap_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(alias_gap_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(alias_gap_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(alias_gap_64, 64)

    # Explicit and noisy system extension specs.
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case("RV32I+GC+ZICSR", 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case("RV64I+GC+ZICSR", 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case("RV32I+GC+ZIFENCEI", 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case("RV64I+GC+ZIFENCEI", 64)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        "RV32I+GC+ZICOND", 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(
        "RV64I+GC+ZICOND", 64, funct3=0b000, rs2=0
    )

    # Parser-priority and dedupe check.
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noise_gap_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noise_gap_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(alias_gap_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(alias_gap_64, 64)

    # Base comparison across baseline without extension letters in spec variants.
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case("RV32I+GC", 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case("RV64I+GC", 64)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(" rv32i + gc + + + ", 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(" rv64i + GC + + + ", 64)


def test_rv32_gc_star_fullset_and_alias_matrix_for_uncovered_extension_features():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_only_32 = (
        "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    )
    noisy_32 = (
        " rv32i + gc + M + A + B + C + F + D + ZICSR + zicsr + ZIFENCEI + zifencei + "
        "ZICOND + zicond + ZBA + zba + ZBB + zbb + ZBS + zbs + ZBK + zbk + "
        "?? + N0ISE + "
    )
    parser_shift_32 = (
        "  GC + RV32I + + + + + A + a + M + m + C + B + b + F + f + D + d + "
        "ZICSR + zifencei + ZIFENCEI + zicond + ZICOND + "
        "RANDOM + "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(explicit_only_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(parser_shift_32, 32)

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(full_32, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(parser_shift_32, 32)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(parser_shift_32, 32)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)

    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(full_32, 32, 0b010)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(parser_shift_32, 32, 0b010)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(noisy_32, 32, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(parser_shift_32, 32, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(noisy_32, 32, funct3=0b100)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(parser_shift_32, 32)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(explicit_only_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(parser_shift_32, 32)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(parser_shift_32, 32)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case("RV32I+GC+ZICSR", 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case("RV32I+GC+ZIFENCEI", 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(parser_shift_32, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        "RV32I+GC+ZICOND", 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0x0F) == _run_zicond_case(
        noisy_32, 32, funct3=0b000, rs2=0x0F
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(parser_shift_32, 32)


def test_rv64_gc_star_fullset_and_alias_matrix_for_uncovered_extension_features():
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_only_64 = (
        "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    )
    noisy_64 = (
        " rv64i + gc + M + A + B + C + F + D + ZICSR + zicsr + ZIFENCEI + zifencei + "
        "ZICOND + zicond + ZBA + zba + ZBB + zbb + ZBS + zbs + ZBK + zbk + "
        "?? + N0ISE + "
    )
    parser_shift_64 = (
        "  GC + RV64I + + + + + a + A + M + m + C + B + b + F + f + D + d + "
        "ZICSR + zifencei + ZIFENCEI + zicond + ZICOND + "
        "RANDOM + "
    )

    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV64I+GC+*", 64) == _run_case(explicit_only_64, 64)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)
    assert _run_case("RV64I+GC+*", 64) == _run_case(parser_shift_64, 64)

    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(full_64, 64)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(parser_shift_64, 64)

    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(parser_shift_64, 64)

    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(full_64, 64, 0b011)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(parser_shift_64, 64, 0b011)

    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(full_64, 64)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(parser_shift_64, 64)

    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(noisy_64, 64, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(parser_shift_64, 64, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b100) == _run_b_case(noisy_64, 64, funct3=0b100)

    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(parser_shift_64, 64)

    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(explicit_only_64, 64)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(parser_shift_64, 64)

    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(parser_shift_64, 64)

    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case("RV64I+GC+ZICSR", 64)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case("RV64I+GC+ZIFENCEI", 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(parser_shift_64, 64)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        "RV64I+GC+ZICOND", 64, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0x0F) == _run_zicond_case(
        noisy_64, 64, funct3=0b000, rs2=0x0F
    )

    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(parser_shift_64, 64)


def test_rv32_gc_star_gap_fill_instructional_paths_with_noisy_aliases():
    base = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy = (
        " rv32i + gc + + + M + m + A + a + B + b + ZBA + zba + C + c + F + f + "
        "D + d + ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + "
        "??? + random_token + "
    )
    reordered = (
        " gc + RV32I + zicond + ZICOND + zifencei + ZIFENCEI + ZICSR + zicsr + "
        "m + M + a + A + B + b + C + c + F + f + D + d + ??? + NOP + "
    )

    # Core + parser behavior.
    assert _run_case("RV32I+GC+*", 32) == _run_case(base, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(reordered, 32)

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(base, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(reordered, 32)

    # Baseline extension families.
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(base, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(reordered, 32)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(base, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy, 32)

    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(base, 32, 0b010)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(reordered, 32, 0b010)

    # Bit manipulation alias acceptance and deterministic behavior checks.
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(base, 32, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy, 32, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(reordered, 32, funct3=0b100)

    # FP/D and scalar width checks.
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(base, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(reordered, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(base, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy, 32)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(reordered, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(base, 32)

    # FP32 behavior with baseline spec and noisy alias forms.
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case("RV32I+GC", 32)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(noisy, 32)

    # System extension paths.
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(base, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(base, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(reordered, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        base, 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0x0F) == _run_zicond_case(
        noisy, 32, funct3=0b000, rs2=0x0F
    )

    # Combined extension runners should remain stable under alias-noise permutations.
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(base, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(reordered, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(base, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy, 32)


def test_rv64_gc_star_gap_fill_instructional_paths_with_noisy_aliases():
    base = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy = (
        " RV64I + gc + M + m + A + a + B + b + ZBA + zba + C + c + F + f + "
        "D + d + ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + "
        "??? + random_token + "
    )
    reordered = (
        " GC + RV64I + zicond + ZICOND + zifencei + ZIFENCEI + ZICSR + zicsr + "
        "m + M + a + A + B + b + C + c + F + f + D + d + ??? + NOP + "
    )

    assert _run_case("RV64I+GC+*", 64) == _run_case(base, 64)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy, 64)
    assert _run_case("RV64I+GC+*", 64) == _run_case(reordered, 64)

    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(base, 64)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(noisy, 64)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(reordered, 64)

    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(base, 64)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy, 64)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(reordered, 64)

    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(base, 64)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy, 64)

    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(base, 64, 0b011)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(reordered, 64, 0b011)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(base, 64)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(reordered, 64)

    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(base, 64, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy, 64, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b100) == _run_b_case(reordered, 64, funct3=0b100)

    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(base, 64)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy, 64)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(reordered, 64)

    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(base, 64)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy, 64)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(reordered, 64)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(base, 64)

    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(base, 64)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(base, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(reordered, 64)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        base, 64, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0x0F) == _run_zicond_case(
        noisy, 64, funct3=0b000, rs2=0x0F
    )

    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(base, 64)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy, 64)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(reordered, 64)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(base, 64)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy, 64)


def test_rv32_rv64_star_base_and_system_stability_against_noisy_full_specs():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " RV32I + gc + ??? + M + A + B + C + F + D + ZICSR + zicsr + "
        "ZIFENCEI + zifencei + ZICOND + zicond + N0ISE + "
    )
    noisy_64 = (
        " rv64i + GC + ??? + m + a + b + c + f + d + ZICSR + zicsr + "
        "zifencei + ZIFENCEI + zicond + ZICOND + UNKNOWN + "
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(noisy_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(full_32, 32, 0b010)
    assert _run_lr_sc_case("RV32I+GC+*", 32) == _run_lr_sc_case(noisy_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(full_64, 64, 0b011)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(noisy_64, 64, 0b011)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        noisy_32, 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0x0F) == _run_zicond_case(
        noisy_64, 64, funct3=0b000, rs2=0x0F
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

def test_star_fullset_and_noisy_rv32_rv64_system_bundle_invariant_with_aliases():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + GC + ??? + m + a + b + c + f + d +"
        " zicsr + zifencei + zicond + b + A + M + unknown + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + M + A + B + C + F + D +"
        " zicsr + zifencei + zicond + zicsr + duplicate + "
    )

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(full_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0xFF) == _run_zicond_case(full_64, 64, funct3=0b001, rs2=0xFF)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0xFF) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0xFF)

def test_star_fullset_core_and_system_mixed_paths_with_noisy_stability_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + GC + ??? + M + A + B + C + F + D + zicsr + zifencei + zicond + "
        "MISC + B + a + UNKNOWN + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + m + a + b + c + f + d + zicsr + zifencei + zicond +"
        " noise + A + B + junk + "
    )

    assert _run_b_case("RV32I+GC+*", 32) == _run_b_case(full_32, 32)
    assert _run_b_case("RV64I+GC+*", 64) == _run_b_case(full_64, 64)
    assert _run_b_case("RV32I+GC+*", 32) == _run_b_case(noisy_32, 32)
    assert _run_b_case("RV64I+GC+*", 64) == _run_b_case(noisy_64, 64)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

def test_star_standard_fullset_and_noisy_stability_for_fp_width_and_zicond_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = " RV32I + gc + ??? + M + A + B + C + F + D + ZICSR + zifencei + zicond + unknown + B + A + "
    noisy_64 = " rv64i + GC + ??? + m + a + b + c + f + d + zicsr + zifencei + zicond + duplicate + M + A + "

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0x0F) == _run_zicond_case(full_32, 32, funct3=0b000, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0xFF) == _run_zicond_case(full_64, 64, funct3=0b000, rs2=0xFF)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0xF0) == _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0xF0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x7F) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0x7F)

def test_star_fullset_and_noisy_equivalence_for_m_a_b_zicsr_zifencei_zicond_paths_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + M + A + B + C + F + D + M + A + zicond + zifencei + zicsr + unknown + b "
    noisy_64 = "  rv64i + gc + ??? + m + a + b + c + f + d + zicond + zifencei + zicsr + unknown + "

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(full_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(full_64, 64)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(noisy_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

def test_star_fullset_and_noisy_parity_for_lr_sc_system_and_branch_like_mix_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + GC + ??? + M + A + B + C + F + D + zicsr + zifencei + zicond + noisy + EXTRA + "
    noisy_64 = "  rv64i + gc + ??? + m + a + b + c + f + d + ZICSR + zifencei + zicond + GARBAGE + "

    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(full_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(full_64, 64, 0b011)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(noisy_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(noisy_64, 64, 0b011)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)

def test_star_fullset_fp32_amo_star_and_zicsr_bundle_stability_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + C + F + D + zicsr + zifencei + zicond + "
        "unknown + noise + A + M + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + c + f + d + zicsr + zifencei + zicond + "
        "junk + M + A + duplicate + "
    )

    assert _run_amo_star_case("RV32I+GC+*", 32) == _run_amo_star_case(full_32, 32)
    assert _run_amo_star_case("RV64I+GC+*", 64) == _run_amo_star_case(full_64, 64)
    assert _run_amo_star_case("RV32I+GC+*", 32) == _run_amo_star_case(noisy_32, 32)
    assert _run_amo_star_case("RV64I+GC+*", 64) == _run_amo_star_case(noisy_64, 64)

    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(full_32, 32)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(full_64, 64)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(noisy_32, 32)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(noisy_64, 64)

    assert _run_zicsr_star_case("RV32I+GC+*", 32) == _run_zicsr_star_case(full_32, 32)
    assert _run_zicsr_star_case("RV64I+GC+*", 64) == _run_zicsr_star_case(full_64, 64)
    assert _run_zicsr_star_case("RV32I+GC+*", 32) == _run_zicsr_star_case(noisy_32, 32)
    assert _run_zicsr_star_case("RV64I+GC+*", 64) == _run_zicsr_star_case(noisy_64, 64)

def test_star_fullset_and_noisy_mword_and_edge_equivalence_for_system_mixed_bundle_on_rv64():
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + c + f + d + zicsr + zifencei + zicond + "
        "B + M + M + duplicate + UNKNOWN + "
    )

    # baseline mword integer/div semantics under star profile
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(full_64, 64)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(noisy_64, 64)

    # mword edge behavior under star profile
    assert _run_mw_edge_case("RV64I+GC+*", 64) == _run_mw_edge_case(full_64, 64)
    assert _run_mw_edge_case("RV64I+GC+*", 64) == _run_mw_edge_case(noisy_64, 64)

    # compare against explicit RV64I+GC+M baseline in the same edge/path class
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case("RV64I+GC+M", 64)
    assert _run_mw_edge_case("RV64I+GC+*", 64) == _run_mw_edge_case("RV64I+GC+M", 64)

    # ensure mixed bundle remains stable with noisy system-like input
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

def test_star_fullset_and_noisy_fp32_bundle_stability_for_rv32_only():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + C + F + D + zifencei + zicsr + zicond + "
        "extra + A + M + B + UNKNOWN + "
    )

    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(full_32, 32)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(noisy_32, 32)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case("RV32I+GC+M", 32)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case("RV32I+GC", 32)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)

def test_star_fullset_and_noisy_b_system_stability_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + C + F + D + ZICSR + ZIFENCEI + ZICOND + "
        "noise + B + duplicate + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + c + f + d + zicsr + zifencei + zicond + "
        "extra + B + junk + "
    )

    assert _run_b_case("RV32I+GC+*", 32) == _run_b_case(full_32, 32)
    assert _run_b_case("RV64I+GC+*", 64) == _run_b_case(full_64, 64)
    assert _run_b_case("RV32I+GC+*", 32) == _run_b_case(noisy_32, 32)
    assert _run_b_case("RV64I+GC+*", 64) == _run_b_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(full_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0xFF) == _run_zicond_case(full_64, 64, funct3=0b001, rs2=0xFF)

def test_star_fullset_and_noisy_zicsr_zicond_stability_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + C + F + D + zifencei + zicond + zicsr + "
        "n0ise + EXTRA + M + A + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + c + f + d + zifencei + zicond + zicsr + "
        "junk + m + a + "
    )

    assert _run_zicsr_star_case("RV32I+GC+*", 32) == _run_zicsr_star_case(full_32, 32)
    assert _run_zicsr_star_case("RV64I+GC+*", 64) == _run_zicsr_star_case(full_64, 64)
    assert _run_zicsr_star_case("RV32I+GC+*", 32) == _run_zicsr_star_case(noisy_32, 32)
    assert _run_zicsr_star_case("RV64I+GC+*", 64) == _run_zicsr_star_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(full_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0xFF) == _run_zicond_case(full_64, 64, funct3=0b000, rs2=0xFF)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0x55) == _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0x55)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0xAA) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0xAA)

def test_star_fullset_and_noisy_mixed_system_mix_stability_for_rv64_only():
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_64 = (
        " rv64i + gc + ??? + M + A + B + C + F + D + ZICSR + zifencei + zicond + "
        "n0ise + duplicate + junk + "
    )

    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(full_64, 64, 0b011)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(noisy_64, 64, 0b011)

    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

def test_star_fullset_and_noisy_fp_store_system_bundle_stability_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + C + F + D + zifencei + zicond + zicsr + "
        "noise + A + M + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + c + f + d + zifencei + zicond + zicsr + "
        "junk + b + a + "
    )

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

def test_star_fullset_and_noisy_mixed_system_branch_stability_for_rv32():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + C + F + D + zicsr + zifencei + zicond + "
        "n0ise + A + M + "
    )

    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(full_32, 32, 0b010)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(noisy_32, 32, 0b010)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(full_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0xF0) == _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0xF0)

    assert _run_b_case("RV32I+GC+*", 32) == _run_b_case(full_32, 32)
    assert _run_b_case("RV32I+GC+*", 32) == _run_b_case(noisy_32, 32)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)

def test_star_fullset_noisy_parity_for_mw_and_fp_cases_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + C + F + D + zicsr + zifencei + zicond + "
        "noise + b + a + A + M + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + c + f + d + zicsr + zifencei + zicond + "
        "junk + M + A + "
    )

    assert _run_mw_case("RV32I+GC+*", 32) == _run_mw_case(full_32, 32)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(full_64, 64)
    assert _run_mw_case("RV32I+GC+*", 32) == _run_mw_case(noisy_32, 32)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(noisy_64, 64)

    assert _run_mw_edge_case("RV32I+GC+*", 32) == _run_mw_edge_case(full_32, 32)
    assert _run_mw_edge_case("RV64I+GC+*", 64) == _run_mw_edge_case(full_64, 64)
    assert _run_mw_edge_case("RV32I+GC+*", 32) == _run_mw_edge_case(noisy_32, 32)
    assert _run_mw_edge_case("RV64I+GC+*", 64) == _run_mw_edge_case(noisy_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

def test_star_fullset_and_noisy_fp_width_and_zicond_bundle_stability_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + C + F + D + zicsr + zifencei + zicond + "
        "N0ISE + zifencei + M + A + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + c + f + d + zicsr + zifencei + zicond + "
        "noisy + A + M + "
    )

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(full_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0xF0) == _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0xF0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0xAA) == _run_zicond_case(full_64, 64, funct3=0b001, rs2=0xAA)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0x55) == _run_zicond_case(noisy_64, 64, funct3=0b000, rs2=0x55)


def test_star_bundle_equivalence_for_m_a_zba_aliased_noisy_inputs_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+ZBA+B+ZICSR+ZIFENCEI+ZICOND+F+D"
    full_64 = "RV64I+GC+M+A+ZBA+B+ZICSR+ZIFENCEI+ZICOND+F+D"
    noisy_32 = (
        " rv32i + gc + ??? + zba + zbh + a + b + m + M + f + D + d + zicond + "
        "garbage + A + M + C + c + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + ZBH + ZBA + B + A + M + ZICOND + zicond + zifencei + "
        "ZICSR + F + d + D + junk + A + M + "
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(full_64, 64, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_64, 64, funct3=0b110)


def test_star_vs_full_and_noisy_stability_on_rv32_gc_plus_a_system():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + C + F + D + zicond + zifencei + zicsr + "
        "noise + M + A + zba + ZBA + C + c + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + c + f + d + zicond + zifencei + zicsr + "
        "junk + M + A + ZBA + zba + "
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(full_32, 32)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(full_64, 64)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(noisy_32, 32)


def test_star_bundle_explicit_plus_noisy_stability_for_rv32_plus_a_zicond():
    full_32 = "RV32I+GC+M+A+ZBA+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + A + M + B + ZBA + ZICOND + C + F + D + zicond + "
        "zicsr + zifencei + noise + m + a + "
    )
    full_64 = "RV64I+GC+M+A+ZBA+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + ZBA + zba + ZICOND + c + F + D + zifencei + "
        "ZICSR + junk + M + A + "
    )

    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(full_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(full_64, 64, 0b011)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(noisy_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(noisy_64, 64, 0b011)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(full_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0xAA) == _run_zicond_case(full_64, 64, funct3=0b001, rs2=0xAA)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0xAA) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0xAA)


def test_star_and_noisy_bundle_stability_for_rv32_fp32_system_and_extension_mix():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + F + D + M + A + B + C + zifencei + zicsr + zicond + "
        "junk + M + A + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + f + d + m + a + b + c + ZICOND + zifencei + ZICSR + "
        "noise + M + A + "
    )

    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(full_32, 32)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(full_64, 64)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(noisy_32, 32)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)


def test_star_set_stability_for_rv32_mixed_arith_and_double_precision_noisy_inputs():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + m + a + b + c + f + d + zifencei + zicsr + zicond + "
        "garbage + M + A + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + M + A + B + C + F + D + ZICSR + ZIFENCEI + ZICOND + "
        "junk + m + a + "
    )

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)


def test_star_fullset_noisy_bundle_stability_for_rv32_width_and_mix_cases():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + C + F + D + ZICOND + zifencei + zicsr + "
        "junk + b + m + a + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + B + c + f + d + zicond + zifencei + zicsr + "
        "noise + A + M + "
    )

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)


def test_star_set_stability_for_rv32_amo_system_and_fp32_noisy_inputs():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + C + F + D + zifencei + zicsr + zicond + "
        "noise + A + M + b + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + c + f + d + zifencei + zicsr + zicond + "
        "junk + A + M + "
    )

    assert _run_amo_star_case("RV32I+GC+*", 32) == _run_amo_star_case(full_32, 32)
    assert _run_amo_star_case("RV64I+GC+*", 64) == _run_amo_star_case(full_64, 64)
    assert _run_amo_star_case("RV32I+GC+*", 32) == _run_amo_star_case(noisy_32, 32)
    assert _run_amo_star_case("RV64I+GC+*", 64) == _run_amo_star_case(noisy_64, 64)

    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(full_32, 32)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(full_64, 64)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(noisy_32, 32)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)


def test_star_bundle_stability_for_rv32_base_and_noisy_b_with_zicond_system_mix():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
        "F + D + zifencei + zicsr + zicond + junk + m + a + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "f + d + ZICOND + ZICSR + ZIFENCEI + noise + M + A + "
    )

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(full_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0xAA) == _run_zicond_case(full_64, 64, funct3=0b001, rs2=0xAA)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0xAA) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0xAA)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(full_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(full_64, 64, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(noisy_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(noisy_64, 64, funct3=0b111)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)


def test_star_fullset_and_noisy_bundle_stability_for_lr_sc_system_mix_on_rv32():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
        "F + D + ZICOND + zifencei + zicsr + noise + m + a + b + "
    )
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
        "f + d + ZICOND + zifencei + zicsr + junk + M + A + "
    )

    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(full_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(full_64, 64, 0b011)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(noisy_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(noisy_64, 64, 0b011)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0xF0) == _run_zicond_case(full_32, 32, funct3=0b000, rs2=0xF0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0x55) == _run_zicond_case(full_64, 64, funct3=0b000, rs2=0x55)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0xF0) == _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0xF0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0x55) == _run_zicond_case(noisy_64, 64, funct3=0b000, rs2=0x55)


def test_star_vs_noisy_bundle_stability_for_rv32_system_fp_and_mix():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + m + a + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "f + d + zicond + zifencei + zicsr + noise + A + M + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + M + A + B + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
        "F + D + ZICOND + ZIFENCEI + ZICSR + junk + m + a + "
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)


def test_star_set_stability_for_a_zicond_and_system_mix_on_rv32():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
        "F + D + zicond + zifencei + zicsr + noise + A + M + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "f + d + ZICOND + ZICSR + ZIFENCEI + junk + A + M + "
    )

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0xF0) == _run_zicond_case(full_32, 32, funct3=0b000, rs2=0xF0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0x55) == _run_zicond_case(full_64, 64, funct3=0b000, rs2=0x55)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0xF0) == _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0xF0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0x55) == _run_zicond_case(noisy_64, 64, funct3=0b000, rs2=0x55)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)


def test_star_set_stability_for_rv32_width_mix_and_b_alias_noisy_inputs():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
        "F + D + ZICOND + ZIFENCEI + ZICSR + noise + m + a + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "f + d + zicond + zifencei + zicsr + junk + M + A + "
    )

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(full_64, 64, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_64, 64, funct3=0b110)


def test_star_bundle_stability_for_lr_sc_d_and_system_noisy_mix_on_rv32():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
        "F + D + zifencei + zicsr + zicond + noise + m + a + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "f + d + ZIFENCEI + ZICSR + ZICOND + junk + M + A + "
    )

    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(full_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(full_64, 64, 0b011)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(noisy_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(noisy_64, 64, 0b011)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)


def test_star_fullset_and_noisy_parser_equivalence_for_explicit_system_arith_bundle_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + M + A + B + C + F + D + zifencei + zicsr + zicond + noise + junk + "
    noisy_64 = "  rv64i + gc + ??? + m + a + b + c + f + d + zifencei + zicsr + zicond + extra + "

    assert _run_amo_star_case("RV32I+GC+*", 32) == _run_amo_star_case(full_32, 32)
    assert _run_amo_star_case("RV64I+GC+*", 64) == _run_amo_star_case(full_64, 64)
    assert _run_amo_star_case("RV32I+GC+*", 32) == _run_amo_star_case(noisy_32, 32)
    assert _run_amo_star_case("RV64I+GC+*", 64) == _run_amo_star_case(noisy_64, 64)
    assert _run_amo_star_case("RV32I+GC+M+A", 32) == _run_amo_star_case("RV32I+GC+*", 32)
    assert _run_amo_star_case("RV64I+GC+M+A", 64) == _run_amo_star_case("RV64I+GC+*", 64)


def test_star_bundle_stability_for_parser_aliases_without_wildcard_noise_on_system_fp_mix():
    base_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI"
    base_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI"
    noisy_32 = (
        " rv32i + gc + ??? + m + a + b + c + f + d + zicsr + zifencei + "
        "ZICOND + zcnd + alias + M + A + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + M + A + B + C + F + D + ZICSR + ZIFENCEI + "
        "ZICOND + zc + no-op + "
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(base_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(base_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(base_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(base_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(base_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(base_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)


def test_star_bundle_stability_for_b_instruction_paths_with_alias_noise_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + m + a + B + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
        "f + d + zifencei + zicsr + zicond + noise + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + M + A + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "F + D + ZIFENCEI + ZICSR + ZICOND + junk + "
    )

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b001) == _run_b_case(full_32, 32, funct3=0b001)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b001) == _run_b_case(full_64, 64, funct3=0b001)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b001) == _run_b_case(noisy_32, 32, funct3=0b001)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b001) == _run_b_case(noisy_64, 64, funct3=0b001)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b010) == _run_b_case("RV32I+GC+M+A+B+ZBA+ZBB", 32, funct3=0b010)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b010) == _run_b_case("RV64I+GC+M+A+B+ZBA+ZBB", 64, funct3=0b010)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case("RV32I+GC+M+A+B", 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case("RV64I+GC+M+A+B", 64, funct3=0b111)



def test_star_fullset_and_noisy_system_arith_fp32_gate_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + m + a + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "f + d + zifencei + zicsr + zicond + noise + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + M + A + B + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
        "F + D + ZIFENCEI + ZICSR + ZICOND + junk + "
    )

    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(full_32, 32)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(full_64, 64)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(noisy_32, 32)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(noisy_64, 64)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

def test_star_fullset_and_noisy_system_mix_stability_for_rv32_and_rv64_core_bundle():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + M + A + a + B + b + ZBA + zba + ZBB + zbb + "
        "ZBK + zBK + ZBE + zbe + ZBF + zbf + ZBM + zbm + ZBH + zbh + "
        "F + D + zifencei + zicsr + zicond + unknown + garbage + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "f + d + zifencei + zicsr + zicond + unknown + junk + "
        "A + M + B + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

def test_star_fullset_system_fp_mix_stability_for_rv32_rv64_noisy_aliases():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + m + a + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "f + d + zifencei + zicsr + zicond + junk + noise + M + A + B + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + M + A + B + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
        "F + D + ZIFENCEI + ZICSR + ZICOND + junk + extra + m + a + b + "
    )

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)


def test_star_fullset_system_and_atomic_mix_stability_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + m + a + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "f + d + zifencei + zicsr + zicond + noise + M + A + B + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + M + A + B + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
        "F + D + ZIFENCEI + ZICSR + ZICOND + garbage + m + a + b + "
    )

    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(full_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(full_64, 64, 0b011)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(noisy_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(noisy_64, 64, 0b011)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

def test_star_fullset_and_noisy_fp_system_mix_matches_explicit_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
        "F + D + ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + junk + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "f + d + zicsr + zicond + zifencei + zifencei + ZICSR + ZIFENCEI + "
    )

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0x77) == _run_zicond_case(full_32, 32, funct3=0b000, rs2=0x77)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0x22) == _run_zicond_case(full_64, 64, funct3=0b000, rs2=0x22)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x33) == _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0x33)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x44) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0x44)

def test_star_fullset_noisy_stability_for_mw_and_system_bundle_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
        "F + D + ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + noise + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "f + d + zifencei + zicsr + zicond + garbage + "
    )

    assert _run_mw_case("RV32I+GC+*", 32) == _run_mw_case(full_32, 32)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(full_64, 64)
    assert _run_mw_case("RV32I+GC+*", 32) == _run_mw_case(noisy_32, 32)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

def test_star_fullset_and_noisy_system_bundle_stability_for_rv32_and_rv64_core_paths():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
        "F + D + zicond + ZICSR + zifencei + ZIFENCEI + unknown + junk + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "f + d + ZIFENCEI + zifencei + ZICOND + ZICSR + noise + "
    )

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0xF0) == _run_zicond_case(full_32, 32, funct3=0b000, rs2=0xF0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(full_64, 64, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0xF0) == _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0xF0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0x0F)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

def test_star_fullset_and_noisy_b_sys_bundle_stability_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
        "F + D + zicond + zicsr + ZICSR + zifencei + ZIFENCEI + noise + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "f + d + ZIFENCEI + zifencei + ZICOND + ZICSR + zicsr + junk + "
    )

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(full_64, 64, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_64, 64, funct3=0b110)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case("RV32I+GC+M+A+B", 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case("RV64I+GC+M+A+B", 64, funct3=0b111)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

def test_star_fullset_and_noisy_core_bundle_parity_for_multi_mix_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + M + A + a + B + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "F + D + zicond + zicsr + ZICSR + zifencei + ZIFENCEI + noise + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "f + d + ZICOND + zifencei + ZICSR + ZIFENCEI + junk + "
    )

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

def test_star_fullset_and_noisy_zicond_b_sys_parity_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
        "F + D + zicond + ZICOND + zicsr + ZICSR + zifencei + ZIFENCEI + noise + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "f + d + ZICOND + zifencei + zicsr + ZICSR + ZIFENCEI + junk + "
    )

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0xAA) == _run_zicond_case(full_32, 32, funct3=0b000, rs2=0xAA)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x55) == _run_zicond_case(full_64, 64, funct3=0b001, rs2=0x55)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0xAA) == _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0xAA)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x55) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0x55)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b001) == _run_b_case(full_32, 32, funct3=0b001)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b001) == _run_b_case(full_64, 64, funct3=0b001)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b001) == _run_b_case(noisy_32, 32, funct3=0b001)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b001) == _run_b_case(noisy_64, 64, funct3=0b001)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)


def test_star_fullset_and_noisy_mix_fp_system_parity_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + m + a + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "f + d + zicond + zicsr + ZICSR + zifencei + ZIFENCEI + noise + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + M + A + B + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
        "f + d + ZICOND + zifencei + zicsr + ZICSR + ZIFENCEI + junk + "
    )

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

def test_star_fullset_and_noisy_orderless_core_system_mix_stability_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + B + b + ZBA + zba + zbb + ZBB + zbk + ZBK + zbe + ZBF + zbm + ZBM + zbh + ZBH + "
        "f + F + d + D + A + a + M + m + zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND + noise + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + A + a + M + B + b + zba + zbb + ZBA + ZBB + zbk + ZBK + zbe + ZBF + zbm + zbh + zBH + "
        "f + d + D + ZICSR + zicsr + ZIFENCEI + zifencei + zicond + ZICOND + junk + "
    )

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)


def test_star_fullset_and_noisy_fp_store_system_parity_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + m + a + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "F + D + zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + noise + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + M + A + B + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
        "f + d + zifencei + zicsr + zicond + ZICOND + ZICSR + garbage + "
    )

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0xAA) == _run_zicond_case(full_32, 32, funct3=0b000, rs2=0xAA)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x55) == _run_zicond_case(full_64, 64, funct3=0b001, rs2=0x55)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0xAA) == _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0xAA)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x55) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0x55)

def test_star_fullset_and_noisy_combo_mix_parity_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + m + a + ZBA + ZBB + ZBK + ZBE + zbe + ZBF + zbf + zbm + zbh + "
        "F + D + zicond + zicsr + ZICSR + zifencei + ZIFENCEI + noise + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + M + A + B + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "f + d + ZICOND + ZICSR + zicsr + zifencei + ZIFENCEI + junk + "
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

def test_star_fullset_and_noisy_atomic_fp_system_parity_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "f + d + zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + noise + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "f + d + ZIFENCEI + zifencei + zicsr + zicond + ZICOND + ZICSR + junk + "
    )

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_mw_case("RV32I+GC+*", 32) == _run_mw_case(full_32, 32)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(full_64, 64)
    assert _run_mw_case("RV32I+GC+*", 32) == _run_mw_case(noisy_32, 32)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(noisy_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

def test_star_fullset_and_noisy_b_fp_system_bundle_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "F + D + ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + noise + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "f + d + zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND + junk + "
    )

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(full_32, 32, funct3=0b100)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b100) == _run_b_case(full_64, 64, funct3=0b100)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(noisy_32, 32, funct3=0b100)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b100) == _run_b_case(noisy_64, 64, funct3=0b100)

    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(full_32, 32)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(full_64, 64)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(noisy_32, 32)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

def test_star_fullset_and_noisy_fp32_zicond_bundle_stability_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "F + D + ZICSR + zicsr + ZICOND + zicond + zifencei + ZIFENCEI + noise + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "f + d + zicond + ZICOND + zifencei + ZIFENCEI + zicsr + ZICSR + junk + "
    )

    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(full_32, 32)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(full_64, 64)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(noisy_32, 32)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0xA5) == _run_zicond_case(full_32, 32, funct3=0b000, rs2=0xA5)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x5A) == _run_zicond_case(full_64, 64, funct3=0b001, rs2=0x5A)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0xA5) == _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0xA5)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x5A) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0x5A)

def test_star_fullset_and_noisy_m_sys_bundle_stability_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + m + a + B + zba + zbb + ZBA + ZBB + zbk + ZBK + zbe + zbf + zbm + zbh + "
        "f + d + zicond + ZICOND + zifencei + ZIFENCEI + zicsr + ZICSR + noise + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + M + A + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "F + D + zifencei + ZIFENCEI + zicond + ZICOND + zicsr + ZICSR + junk + "
    )

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

def test_star_fullset_and_noisy_fp_width_bundle_stability_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + M + A + B + zba + zbb + ZBA + ZBB + zbk + ZBK + zbe + zbf + zbm + zbh + "
        "f + d + zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + noise + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + m + a + b + zba + zbb + zbk + zbe + zbf + zbm + zbh + "
        "F + D + ZIFENCEI + zifencei + zicsr + ZICSR + zicond + ZICOND + junk + "
    )

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

def test_star_fullset_and_noisy_mw_amo_mix_bundle_stability_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i + gc + ??? + m + a + b + ZBA + ZBB + zbk + zbe + zbf + zbm + zbh + "
        "f + d + zifencei + ZIFENCEI + zicond + ZICOND + ZICSR + zicsr + noise + "
    )
    noisy_64 = (
        " rv64i + gc + ??? + M + A + B + zba + zbb + ZBK + zbk + ZBE + zbe + ZBF + zbf + ZBM + zbm + "
        "F + D + zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + junk + "
    )

    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(full_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(full_64, 64, 0b011)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(noisy_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(noisy_64, 64, 0b011)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)


def test_star_fullset_and_noisy_fp32_bundle_stability_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + M + A + B + F + D + ZICSR + zifencei + zicond + ZBA + ZBE + zbk + zbf + zbm + zbh +"
    noisy_64 = "  rv64i + gc + ??? + f + m + a + d + zicsr + ZIFENCEI + zicond + zba + zbb + zbk + zbh +"

    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(full_32, 32)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(full_64, 64)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(noisy_32, 32)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(noisy_64, 64)


def test_star_fullset_and_noisy_b_zicond_bundle_stability_for_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + M + m + A + a + B + C + ZBA + zbb + zbk + zbf +"
        " zbm + zbh + ZICSR + ZIFENCEI + ZICOND + zicond + ZBC + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + M + A + B + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
        "f + d + zifencei + ZICSR + ZICOND + zicond + ZICOND + "
    )

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(full_64, 64, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_64, 64, funct3=0b110)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(full_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(full_64, 64, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(noisy_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(noisy_64, 64, funct3=0b111)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0x0F) == _run_zicond_case(full_32, 32, funct3=0b000, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0x0F) == _run_zicond_case(full_64, 64, funct3=0b000, rs2=0x0F)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0x0F) == _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0x0F) == _run_zicond_case(noisy_64, 64, funct3=0b000, rs2=0x0F)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0) == _run_zicond_case(full_32, 32, funct3=0b001, rs2=0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0) == _run_zicond_case(full_64, 64, funct3=0b001, rs2=0)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0) == _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0)


def test_star_and_noisy_standard_fullset_equivalence_on_rv32_with_b_zicond_m_a_combo():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + M + a + ZBA + zbk + ZBF + ZBH + zbe + zbm + ZBB + B + "
        "C + F + D + zifencei + ZIFENCEI + zicsr + ZICSR + ZICOND + zicond + "
    )

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(full_32, 32, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(noisy_32, 32, funct3=0b111)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(full_32, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(full_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0x0F)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)


def test_rv32_star_standard_fullset_noisy_consistency_for_explicit_suite():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + M + a + A + M + B + zba + ZBA + zbb + ZBB + zbk + ZBK + zbe + zbf + zbm + zbh + "
        "F + D + zifencei + ZIFENCEI + zicsr + ZICSR + ZICOND + zicond + noise +"
    )

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(full_32, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(full_32, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0) == _run_zicond_case(full_32, 32, funct3=0b001, rs2=0)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0) == _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(full_32, 32, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(noisy_32, 32, funct3=0b111)


def test_star_matches_explicit_and_noisy_fullset_suite_on_rv32_with_rv64_sanity():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + C + M + A + B + zba + ZBA + zbb + ZBB + zbk + ZBK + zbe + ZBE + zbf +"
        " ZBF + zbm + ZBM + zbh + ZBH + F + D + ZIFENCEI + zifencei + ZICSR + zicsr + ZICOND + zicond "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + M + A + C + B + zba + ZBA + ZBB + zbk + ZBK + zbe + zbf + zbm + ZBM + zbh +"
        " F + D + ZIFENCEI + zifencei + ZICSR + zicsr + ZICOND + zicond"
    )

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)


def test_star_superset_stability_for_uncovered_mix_suite_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+ZBA+ZBB+ZBK+ZBE+ZBF+ZBM+ZBH+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i + gc + ??? + A + M + B + C + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
        "ZIFENCEI + zifencei + ZICSR + zicsr + ZICOND + zicond + "
    )
    noisy_64 = (
        "  rv64i + gc + ??? + M + A + B + ZBA + ZBB + ZBK + ZBE + ZBF + ZBM + ZBH + "
        "ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + "
    )

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(full_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(full_64, 64, 0b011)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(noisy_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(noisy_64, 64, 0b011)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0x0F) == _run_zicond_case(full_32, 32, funct3=0b000, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0x0F) == _run_zicond_case(full_64, 64, funct3=0b000, rs2=0x0F)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0x0F) == _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0x0F) == _run_zicond_case(noisy_64, 64, funct3=0b000, rs2=0x0F)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0) == _run_zicond_case(full_32, 32, funct3=0b001, rs2=0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0) == _run_zicond_case(full_64, 64, funct3=0b001, rs2=0)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0) == _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0)

def test_star_and_explicit_full_std_set_are_stable_on_mixed_parser_noise_rv32_and_rv64():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    star_32 = "RV32I+GC+*"
    star_64 = "RV64I+GC+*"
    noisy_32 = "  rv32i + gc + ??? + ZBA + m + C + A + b + F + D + ZICSR + zifencei + zicond + ZBB +"
    noisy_64 = "  rv64i + gc + ??? + c + B + a + M + m + zifencei + ZICSR + d + zicond + ZBH +"

    assert _run_case(star_32, 32) == _run_case(explicit_32, 32)
    assert _run_case(star_64, 64) == _run_case(explicit_64, 64)
    assert _run_case(star_32, 32) == _run_case(noisy_32, 32)
    assert _run_case(star_64, 64) == _run_case(noisy_64, 64)

    assert _run_m_case(star_32, 32) == _run_m_case(explicit_32, 32)
    assert _run_m_case(star_64, 64) == _run_m_case(explicit_64, 64)
    assert _run_amo_ops_case(star_32, 32) == _run_amo_ops_case(explicit_32, 32)
    assert _run_amo_ops_case(star_64, 64) == _run_amo_ops_case(explicit_64, 64)

    assert _run_extension_combo_case(star_32, 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case(star_64, 64) == _run_extension_combo_case(explicit_64, 64)
    assert _run_extension_combo_case(star_32, 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case(star_64, 64) == _run_extension_combo_case(noisy_64, 64)

def test_star_runtime_matches_explicit_full_with_noisy_forms_on_rv32_and_rv64():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + ZBA + C + A + M + b + zifencei + zicond + ZZ_UNKNOWN + D + F + ZICSR +"
    noisy_64 = "  rv64i + gc + ??? + d + f + A + m + zicond + zifencei + zicsr + c + B + zba + ZBB +"

    assert _run_case("RV32I+GC+*", 32) == _run_case(explicit_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(explicit_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(explicit_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(explicit_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(explicit_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(explicit_64, 64)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(explicit_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(explicit_64, 64, funct3=0b111)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(explicit_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(explicit_64, 64)

def test_star_fullset_noisy_stability_for_control_extensions_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + zifencei + ZICOND + zicsr + B + m + A + ZBA +"
    noisy_64 = "  rv64i + gc + ??? + ZICSR + zifencei + zicond + a + m + B + zba + C +"

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(full_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0) == _run_zicond_case(full_64, 64, funct3=0b001, rs2=0)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0)

def test_star_fp_d_fullset_noisy_stability_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + ZBA + F + d + ZBB + ZICOND + ZICSR + zifencei + A + B + M + C +"
    noisy_64 = "  rv64i + gc + ??? + d + f + ZBH + zifencei + zicond + zicsr + M + a + B + C +"

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

def test_star_m_a_b_fullset_noisy_composition_stability_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + ZBA + ZBB + M + B + A + zifencei + m + ZICSR + F + D + c + ZICOND +"
    noisy_64 = "  rv64i + gc + ??? + a + M + B + zba + zicsr + zifencei + zicond + C + d + f +"

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

    assert _run_mw_case("RV64I+GC+*") == _run_mw_case(full_64)
    assert _run_mw_case("RV64I+GC+*") == _run_mw_case(noisy_64)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(full_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(full_64, 64, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(noisy_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(noisy_64, 64, funct3=0b111)

def test_star_combo_with_system_and_conditional_ops_stable_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + ZICSR + M + A + B + zifencei + zicond + F + D + C +"
    noisy_64 = "  rv64i + gc + ??? + zicond + zifencei + zicsr + a + b + m + c + d + f +"

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        full_32, 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0) == _run_zicond_case(
        full_64, 64, funct3=0b001, rs2=0
    )
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        noisy_32, 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0) == _run_zicond_case(
        noisy_64, 64, funct3=0b001, rs2=0
    )

def test_star_core_base_and_controls_noisy_equivalence_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + ZIFENCEI + ZICSR + M + C + ZICOND + A + B +"
    noisy_64 = "  rv64i + gc + ??? + zifencei + zicsr + m + c + zicond + a + b +"

    assert _run_base_case("RV32I+GC", 32) == _run_base_case(full_32, 32)
    assert _run_base_case("RV64I+GC", 64) == _run_base_case(full_64, 64)

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(full_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(full_64, 64)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(noisy_64, 64)

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

def test_star_lr_sc_and_b_m_mix_noisy_fullset_stability_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + M + ZBA + A + B + ZBB + ZICOND + ZICSR + zifencei +"
    noisy_64 = "  rv64i + gc + ??? + m + B + zba + a + zifencei + zicsr + zicond + c +"

    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(full_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(full_64, 64, 0b011)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(noisy_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(noisy_64, 64, 0b011)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(full_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(full_64, 64, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(noisy_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(noisy_64, 64, funct3=0b111)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

def test_star_control_fp_mix_stability_against_full_and_noisy_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + F + D + ZBA + ZICOND + ZIFENCEI + ZICSR + M + B + A +"
    noisy_64 = "  rv64i + gc + ??? + d + zifencei + zicsr + m + a + b + f + c + zicond +"

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

def test_star_b_system_conditional_noisy_fullset_stability_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + ZBA + ZBB + zifencei + zicond + zicsr + M + A + B +"
    noisy_64 = "  rv64i + gc + ??? + zicond + zifencei + zicsr + m + a + b + c + ZBA +"

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(full_64, 64, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_64, 64, funct3=0b110)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0x0F) == _run_zicond_case(
        full_32, 32, funct3=0b000, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x00) == _run_zicond_case(
        full_64, 64, funct3=0b001, rs2=0x00
    )
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0x0F) == _run_zicond_case(
        noisy_32, 32, funct3=0b000, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x00) == _run_zicond_case(
        noisy_64, 64, funct3=0b001, rs2=0x00
    )

def test_star_atomic_bitops_fp_mix_noisy_fullset_stability_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + A + B + M + F + D + ZBA + ZBB + zifencei + zicond + zicsr +"
    noisy_64 = "  rv64i + gc + ??? + a + b + m + d + f + zifencei + zicsr + zicond + c +"

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(full_32, 32, funct3=0b100)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b100) == _run_b_case(full_64, 64, funct3=0b100)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b100) == _run_b_case(noisy_32, 32, funct3=0b100)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b100) == _run_b_case(noisy_64, 64, funct3=0b100)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

def test_star_parser_robustness_for_full_std_control_bitops_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + ZICSR + ZIFENCEI + ZICOND + zBA + zz_bad + M + B + A + F + D +"
    noisy_64 = "  rv64i + gc + ??? + zifencei + zicsr + zicond + zbh + m + a + b + d + f +"

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(full_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(full_64, 64, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_64, 64, funct3=0b110)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

def test_star_lr_sc_atomic_math_control_noisy_fullset_stability_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + M + A + B + zicond + zifencei + zicsr + F + D + C +"
    noisy_64 = "  rv64i + gc + ??? + a + m + b + zifencei + zicsr + zicond + f + d +"

    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(full_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(full_64, 64, 0b011)
    assert _run_lr_sc_case("RV32I+GC+*", 32, 0b010) == _run_lr_sc_case(noisy_32, 32, 0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, 0b011) == _run_lr_sc_case(noisy_64, 64, 0b011)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

def test_star_bitops_control_fullset_noisy_equivalence_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + B + ZBA + M + A + ZICSR + ZIFENCEI + ZICOND + F + D +"
    noisy_64 = "  rv64i + gc + ??? + zba + b + m + a + zicsr + zifencei + zicond + d + f +"

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(full_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(full_64, 64, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(noisy_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(noisy_64, 64, funct3=0b111)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        full_32, 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0) == _run_zicond_case(
        full_64, 64, funct3=0b001, rs2=0
    )
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(
        noisy_32, 32, funct3=0b001, rs2=0x0F
    )
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0) == _run_zicond_case(
        noisy_64, 64, funct3=0b001, rs2=0
    )

def test_star_fullset_control_combo_consistency_noisy_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + ZICSR + ZIFENCEI + ZICOND + A + M + B + F + D + C +"
    noisy_64 = "  rv64i + gc + ??? + zicsr + zifencei + zicond + a + m + b + d + f + c +"

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

def test_star_word_and_fp_width_fullset_noisy_stability_on_rv64_and_rv32():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + F + D + M + B + A + zifencei + zicond + zicsr + C +"
    noisy_64 = "  rv64i + gc + ??? + c + f + d + m + a + b + zifencei + zicsr + zicond +"

    assert _run_mw_case("RV64I+GC+*") == _run_mw_case(full_64)
    assert _run_mw_case("RV64I+GC+*") == _run_mw_case(noisy_64)
    assert _run_mw_edge_case("RV64I+GC+*") == _run_mw_edge_case(full_64)
    assert _run_mw_edge_case("RV64I+GC+*") == _run_mw_edge_case(noisy_64)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

def test_star_equivalent_to_full_standard_config_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + + + m + a + b + c + f + d + zicsr + zifencei + zicond + ???  "
    noisy_64 = "  rv64i + gc + + + M + A + B + C + F + D + ZICSR + ZIFENCEI + ZICOND + ???  "

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_m_case(full_32, 32) == _run_m_case("RV32I+GC+*", 32)
    assert _run_m_case(full_64, 64) == _run_m_case("RV64I+GC+*", 64)

    assert _run_fp_case(full_32, 32) == _run_fp_case("RV32I+GC+*", 32)
    assert _run_fp_case(full_64, 64) == _run_fp_case("RV64I+GC+*", 64)

def test_star_token_normalization_and_noise_tolerance_on_rv32_and_rv64():
    noisy_star_32 = "  RV32I + GC + * + + m + m + gC + ??? + "
    noisy_star_64 = "  RV64I + GC + * + A + a + ZICSR + zicsr + ??? + C + c + "
    noisy_base_32 = "rv32i + gc + + + +"
    noisy_base_64 = "rv64i + gc + + + +"

    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_star_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_star_64, 64)
    assert _run_case("RV32I+GC", 32) == _run_case(noisy_base_32, 32)
    assert _run_case("RV64I+GC", 64) == _run_case(noisy_base_64, 64)

def test_star_parser_ignores_unknown_extension_tokens_when_still_matching_full_set():
    noisy_with_unknown_32 = "  rv32i + gc + * + ZZZ_UNKNOWN + zba + ??? + "
    noisy_with_unknown_64 = "  rv64i + gc + * + ZZZ_UNKNOWN + zba + ??? + "

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_with_unknown_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_with_unknown_64, 64)

def test_star_set_stable_with_noisy_b_aliases_on_rv32_and_rv64():
    noisy_32 = "  rv32i + gc + ??? + zba + zbs + zbb + zbk + zbh + B + "
    noisy_64 = "  rv64i + gc + ??? + ZBB + ZBH + ZBA + ZBK + ZBS + b + "

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_64, 64, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(noisy_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(noisy_64, 64, funct3=0b111)

def test_star_control_extensions_stable_with_mixed_noisy_fullset_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + F + d + zifencei + zicond + zicsr + B + M + C + A + "
    noisy_64 = "  rv64i + gc + ??? + zba + f + zifencei + zicond + zicsr + b + M + c + A + "

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

def test_star_control_combo_stability_with_noisy_aliases_on_both_xlen():
    full_32 = "RV32I+GC+M+A+ZICSR+ZIFENCEI+ZICOND+B+C+F+D"
    full_64 = "RV64I+GC+M+A+ZICSR+ZIFENCEI+ZICOND+B+C+F+D"
    noisy_32 = "  rv32i + gc + ??? + + + M + A + zicsr + zifencei + zicond + ZBA + ZBB + B + C + f + d + "
    noisy_64 = "  rv64i + gc + ??? + M + a + zicond + zifencei + zicsr + zbh + ZBK + B + C + f + d + "

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)


def test_star_full_set_rv64_behavior_stability_for_runtime_mix_noisy_aliases():
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_64 = "  rv64i + gc + ??? + zba + zbb + ZBH + zifencei + ZICOND + ZICSR + M + A + C + F + D + "

    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(full_64, 64, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0x0F)

    assert _run_amo_ops_case("RV64I+GC+*", 64, amofn=0, src_imm=0) == _run_amo_ops_case(full_64, 64, amofn=0, src_imm=0)


def test_star_full_standard_set_end_to_end_stability_with_noisy_control_aliases_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + ZBA + zifencei + ZICSR + zicond + M + A + F + D + C + B + "
    noisy_64 = "  rv64i + gc + ??? + zbb + zba + zifencei + ZIFENCEI + zicsr + M + A + C + F + D + B + "

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(full_32, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(full_64, 64, funct3=0b000, rs2=0)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0x0F)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)


def test_star_standard_full_set_with_multi_mix_and_noisy_aliases_execute_consistently_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + ZBA + zbb + M + A + zicond + zifencei + ZICSR + B + C + F + D + "
    noisy_64 = "  rv64i + gc + ??? + zbh + zbk + M + A + ZICOND + ZICSR + ZIFENCEI + b + C + F + D + "

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(full_32, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(full_64, 64, funct3=0b000, rs2=0)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)


def test_star_fullset_core_controls_and_atomics_behave_stably_with_noisy_aliases_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + ZBH + zifencei + zicond + zicsr + B + M + A + C + F + D + "
    noisy_64 = "  rv64i + gc + ??? + zba + zbb + zifencei + ZICOND + zicond + zicsr + m + a + c + f + d + B + "

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)

    assert _run_amo_ops_case("RV32I+GC+*", 32, amofn=0, src_imm=0) == _run_amo_ops_case(full_32, 32, amofn=0, src_imm=0)
    assert _run_amo_ops_case("RV64I+GC+*", 64, amofn=0, src_imm=0) == _run_amo_ops_case(full_64, 64, amofn=0, src_imm=0)
    assert _run_amo_ops_case("RV32I+GC+*", 32, amofn=0, src_imm=0) == _run_amo_ops_case(noisy_32, 32, amofn=0, src_imm=0)
    assert _run_amo_ops_case("RV64I+GC+*", 64, amofn=0, src_imm=0) == _run_amo_ops_case(noisy_64, 64, amofn=0, src_imm=0)

    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case(full_32, 32, funct3=0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b010) == _run_lr_sc_case(full_64, 64, funct3=0b010)
    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case(noisy_32, 32, funct3=0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b010) == _run_lr_sc_case(noisy_64, 64, funct3=0b010)


def test_star_core_system_bundle_and_control_paths_remain_stable_on_rv64_noisy_spec():
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_64 = "  rv64i + gc + ??? + zba + zbb + ZBH + m + a + b + c + f + d + zifencei + zicsr + zicond + junk + "

    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(explicit_64, 64)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(explicit_64, 64)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(explicit_64, 64)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(explicit_64, 64)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(explicit_64, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(explicit_64, 64)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(explicit_64, 64, funct3=0b000, rs2=0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(explicit_64, 64, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(noisy_64, 64, funct3=0b000, rs2=0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0x0F)


def test_star_and_explicit_full_standard_mix_stability_for_base_and_fp32_controls():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + zba + M + A + B + C + F + D + zifencei + ZICOND + zicsr + "
    noisy_64 = "  rv64i + gc + ??? + ZBB + zbh + m + a + b + c + f + d + ZIFENCEI + zicond + ZICSR + "

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(explicit_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(explicit_64, 64)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(noisy_64, 64)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(explicit_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(explicit_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(explicit_32, 32)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(explicit_64, 64)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(noisy_32, 32)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(noisy_64, 64)


def test_star_and_explicit_full_standard_core_paths_on_rv32_remain_stable():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + zba + zbb + ZBH + m + a + b + c + f + d + zicsr + zifencei + zicond + "

    assert _run_case("RV32I+GC+*", 32) == _run_case(explicit_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)

    assert _run_mw_case("RV32I+GC+*", 32) == _run_mw_case(explicit_32, 32)
    assert _run_mw_case("RV32I+GC+*", 32) == _run_mw_case(noisy_32, 32)

    assert _run_mw_edge_case("RV32I+GC+*", 32) == _run_mw_edge_case(explicit_32, 32)
    assert _run_mw_edge_case("RV32I+GC+*", 32) == _run_mw_edge_case(noisy_32, 32)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(explicit_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(explicit_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0x0F)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(explicit_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)


def test_star_equivalence_with_noisy_fullset_for_rv32_runtime_mix():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + zba + zbb + m + a + A + B + C + f + F + D + zicond + zifencei + zicsr + m "

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(explicit_32, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(explicit_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(explicit_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0x0F)


def test_star_preserves_multi_extension_mix_on_rv32_and_rv64_with_noisy_tokens():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + M + m + A + a + B + b + C + F + D + ZIFENCEI + ZICSR + ZICOND + junk + "
    noisy_64 = "  rv64i + gc + ??? + ZICOND + zifencei + zicsr + m + a + b + c + f + d + M + A + junk + "

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(explicit_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(explicit_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)


def test_star_fullset_noisy_aliases_match_explicit_suite_on_rv32_and_rv64_runtime_mix():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_star_32 = "  RV32I + GC + * + ??? + m + M + A + a + C + c + B + b + f + D + d + ZBA + zbb + ZICSR + zifencei + junk_token_32 + "
    noisy_star_64 = "  rv64i + gc + ??? + * + zba + ZBA + B + C + a + M + zifencei + ZICOND + zicond + ZICSR + ZBH + zbh + unknown.token + "
    noisy_explicit_32 = "  rv32i + gc + ??? + zifencei + ZIFENCEI + M + A + B + C + f + F + D + ZICSR + m + a + d + ZBA + zbb + "
    noisy_explicit_64 = "  rv64i + gc + ??? + zba + zbb + m + A + B + C + F + D + zifencei + ZIFENCEI + zicond + ZICOND + zicsr + "

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(explicit_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_star_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_star_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_explicit_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_explicit_64, 64)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_star_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_star_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_star_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_star_64, 64)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0) == _run_zicond_case(noisy_star_32, 32, funct3=0b001, rs2=0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(noisy_star_64, 64, funct3=0b000, rs2=0)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_star_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_star_64, 64)


def test_star_fullset_rv64_noisy_parser_noise_and_duplication_stability():
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_star_64 = "  RV64I + GC + * + * + ??? + M + m + a + A + B + b + C + c + F + f + D + d + ZICOND + zicond + ZIFENCEI + zifencei + ZICSR + zicsr + junk_64 + "
    noisy_explicit_64 = "  rv64i + gc + ??? + zifencei + ZIFENCEI + zicond + ZICOND + zicsr + ZICSR + m + a + M + b + B + c + C + d + D + f + F + "

    assert _run_case("RV64I+GC+*", 64) == _run_case(explicit_64, 64)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_star_64, 64)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_explicit_64, 64)

    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(explicit_64, 64)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_star_64, 64)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_explicit_64, 64)

    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(explicit_64, 64)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_star_64, 64)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_explicit_64, 64)

    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(explicit_64, 64)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_star_64, 64)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_explicit_64, 64)

    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(explicit_64, 64)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(noisy_star_64, 64)
    assert _run_mw_edge_case("RV64I+GC+*", 64) == _run_mw_edge_case(explicit_64, 64)
    assert _run_mw_edge_case("RV64I+GC+*", 64) == _run_mw_edge_case(noisy_star_64, 64)

    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(explicit_64, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_star_64, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_explicit_64, 64)

    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(explicit_64, 64)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_star_64, 64)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_explicit_64, 64)

    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(explicit_64, 64, funct3=0b000, rs2=0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(explicit_64, 64, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(noisy_star_64, 64, funct3=0b000, rs2=0)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_star_64, 64, funct3=0b001, rs2=0x0F)


def test_star_fullset_rv32_noisy_parser_tolerance_for_alias_duplicates_and_unknowns():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_star_32 = "  RV32I + GC + * + * + ??? + zba + zbb + zba + M + m + A + a + B + b + C + c + F + f + D + d + ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + UNKNOWN_32 + "
    noisy_explicit_32 = "  rv32i + gc + ??? + zifencei + ZIFENCEI + zicond + ZICOND + zicsr + ZICSR + m + a + M + b + B + c + C + d + D + f + F + "

    assert _run_case("RV32I+GC+*", 32) == _run_case(explicit_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_star_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_explicit_32, 32)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_star_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_explicit_32, 32)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(explicit_32, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_star_32, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_explicit_32, 32)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(explicit_32, 32)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_star_32, 32)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_explicit_32, 32)

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(explicit_32, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_star_32, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_explicit_32, 32)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(explicit_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_star_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_explicit_32, 32)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(explicit_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_star_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_explicit_32, 32)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(explicit_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_star_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_explicit_32, 32)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(explicit_32, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(explicit_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b000, rs2=0) == _run_zicond_case(noisy_star_32, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_star_32, 32, funct3=0b001, rs2=0x0F)


def test_star_fullset_rv32_control_and_atomics_noisy_stability_with_aliases():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_star_32 = "  rv32i + GC + * + ??? + M + m + A + a + B + b + C + c + F + f + D + d + ZIFENCEI + zifencei + ZICSR + zicsr + ZICOND + zicond + unknown_token + "

    assert _run_case("RV32I+GC+*", 32) == _run_case(explicit_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_star_32, 32)

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(explicit_32, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_star_32, 32)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_star_32, 32)

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(explicit_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_star_32, 32)

    assert _run_amo_ops_case("RV32I+GC+*", 32, amofn=0, src_imm=0) == _run_amo_ops_case(explicit_32, 32, amofn=0, src_imm=0)
    assert _run_amo_ops_case("RV32I+GC+*", 32, amofn=1, src_imm=1) == _run_amo_ops_case(noisy_star_32, 32, amofn=1, src_imm=1)

    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case(explicit_32, 32, funct3=0b010)
    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case(noisy_star_32, 32, funct3=0b010)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(explicit_32, 32, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(noisy_star_32, 32, funct3=0b111)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(explicit_32, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_star_32, 32)

    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_star_64 = "  rv64i + GC + * + ??? + M + m + A + a + B + b + C + c + F + f + D + d + ZIFENCEI + zifencei + ZICSR + zicsr + ZICOND + zicond + unknown_token + "

    assert _run_case("RV64I+GC+*", 64) == _run_case(explicit_64, 64)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_star_64, 64)

    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(explicit_64, 64)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(noisy_star_64, 64)

    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(explicit_64, 64)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_star_64, 64)

    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(explicit_64, 64)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_star_64, 64)

    assert _run_amo_ops_case("RV64I+GC+*", 64, amofn=0, src_imm=0) == _run_amo_ops_case(explicit_64, 64, amofn=0, src_imm=0)
    assert _run_amo_ops_case("RV64I+GC+*", 64, amofn=1, src_imm=1) == _run_amo_ops_case(noisy_star_64, 64, amofn=1, src_imm=1)

    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b011) == _run_lr_sc_case(explicit_64, 64, funct3=0b011)
    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b011) == _run_lr_sc_case(noisy_star_64, 64, funct3=0b011)

    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(explicit_64, 64, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(noisy_star_64, 64, funct3=0b111)

    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(explicit_64, 64)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_star_64, 64)

def test_standard_fullset_alias_and_noise_contract_stable_for_rv32i_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + zifencei + zicond + zicsr + m + A + a + b + B + d + D + f + F + c + C + "

    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_64 = "  rv64i + gc + ??? + ZICOND + ZICSR + ZIFENCEI + ZBA + ZBB + M + A + B + C + D + F + c + a + m + zifencei + zicond + zicsr + "

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

def test_star_fullset_runtime_contract_stable_for_rv32_and_rv64_with_noisy_aliases():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  RV32I  + gc + * + m + A + b + B + c + C + d + D + F + f + ZIFENCEI + zifencei + zicsr + ZICSR + zicond + ZICOND + zba + ??? + "
    noisy_64 = "  rv64i + GC + * + ??? + A + a + B + b + C + c + D + d + F + f + M + m + ZICOND + zicond + ZIFENCEI + zicsr + ZICSR + ZBA + zbb + "

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(full_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(full_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)

def test_star_fullset_runtime_control_extensions_match_explicit_full_set_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + * + ??? + m + A + zifencei + ZICSR + zicond + b + B + C + c + D + d + f + F + zba + zbb + "
    noisy_64 = "  rv64i + GC + * + junk + M + a + A + zifencei + zicsr + zicond + B + b + C + c + D + d + F + f + "

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(full_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0x0F)

    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(full_64, 64, funct3=0b000, rs2=0)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b000, rs2=0) == _run_zicond_case(noisy_64, 64, funct3=0b000, rs2=0)

def test_star_fullset_runtime_branch_and_atomics_match_explicit_suite_on_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + * + ??? + b + B + m + a + zba + zbb + junk + C + c + d + D + F + f + ZICOND + zicond + ZIFENCEI + zifencei + ZICSR + zicsr + "
    noisy_64 = "  rv64i + GC + * + ??? + M + A + B + b + C + c + d + D + F + f + zicond + ZICOND + zifencei + ZIFENCEI + zicsr + ZICSR + unknown + zba + zbh + "

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(full_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(full_64, 64)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(noisy_64, 64)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(full_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(full_64, 64, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(noisy_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(noisy_64, 64, funct3=0b111)

    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case(full_32, 32, funct3=0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b011) == _run_lr_sc_case(full_64, 64, funct3=0b011)
    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case(noisy_32, 32, funct3=0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b011) == _run_lr_sc_case(noisy_64, 64, funct3=0b011)

def test_star_fullset_runtime_control_fp_width_contract_stable_for_rv32i_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + * + ??? + C + c + F + f + M + m + zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND + B + b + D + d + unknown_32 + "
    noisy_64 = "  rv64i + GC + * + ??? + M + m + A + a + B + b + C + c + D + d + F + f + ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + junk + "

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(full_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(full_64, 64)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(full_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(full_64, 64)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(noisy_32, 32)
    assert _run_fp_store_width_case("RV64I+GC+*", 64) == _run_fp_store_width_case(noisy_64, 64)

    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(full_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(full_64, 64)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)

def test_star_fullset_runtime_iterable_input_matches_explicit_full_set_rv32_and_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "RV32I+gc+*+zba+zbb+???+zifencei+zicsr+zicond+junk"
    noisy_64 = "rv64i+GC+*+zba+zbh+???+zbb+zifencei+zicsr+zicond+unknown"

    assert _run_case("RV32I+GC+*", 32) == _run_case(full_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(full_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)


def test_star_fullset_runtime_duplicate_tokens_and_invalids_stable_for_rv32_and_rv64():
    canonical_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    canonical_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    duplicate_noisy_32 = " rv32i + gc + m + M + a + a + b + c + C + m + f + F + zicsr + zifencei + zicond + zba + junk + "
    duplicate_noisy_64 = "  RV64I + GC + M + m + A + b + B + C + c + c + d + f + F + ZIFENCEI + zifencei + UNKNOWN + ZICSR + zicsr + zicond + ZICOND "

    assert _run_case("RV32I+GC+*", 32) == _run_case(canonical_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(canonical_64, 64)
    assert _run_case(canonical_32, 32) == _run_case(duplicate_noisy_32, 32)
    assert _run_case(canonical_64, 64) == _run_case(duplicate_noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(canonical_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(canonical_64, 64)
    assert _run_extension_combo_case(canonical_32, 32) == _run_extension_combo_case(duplicate_noisy_32, 32)
    assert _run_extension_combo_case(canonical_64, 64) == _run_extension_combo_case(duplicate_noisy_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(canonical_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(canonical_64, 64)
    assert _run_fp_case(canonical_32, 32) == _run_fp_case(duplicate_noisy_32, 32)
    assert _run_fp_case(canonical_64, 64) == _run_fp_case(duplicate_noisy_64, 64)


def test_star_fullset_runtime_whitespace_and_separator_noise_stable_for_rv32_and_rv64():
    canonical_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    canonical_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    spaced_32 = "  rv32i + gc + + + m + A + a + B + b + c + C + d + D + f + F + zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND + "
    spaced_64 = "  rv64i + gc + m + M + a + b + B + c + C + d + D + f + F + zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND "

    assert _run_case("RV32I+GC+*", 32) == _run_case(canonical_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(canonical_64, 64)
    assert _run_case(canonical_32, 32) == _run_case(spaced_32, 32)
    assert _run_case(canonical_64, 64) == _run_case(spaced_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(canonical_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(canonical_64, 64)
    assert _run_extension_combo_case(canonical_32, 32) == _run_extension_combo_case(spaced_32, 32)
    assert _run_extension_combo_case(canonical_64, 64) == _run_extension_combo_case(spaced_64, 64)

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(canonical_32, 32)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(canonical_64, 64)
    assert _run_fp_case(canonical_32, 32) == _run_fp_case(spaced_32, 32)
    assert _run_fp_case(canonical_64, 64) == _run_fp_case(spaced_64, 64)


def test_star_fullset_runtime_amo_form_stability_with_noisy_parser_rv32i_and_rv64i():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + * + ??? + m + M + a + A + b + B + c + C + d + D + f + F + zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + zba + zbb + "
    noisy_64 = "  rv64i + gc + * + ??? + m + A + B + C + D + F + zifencei + zicsr + zicond + zba + zbb + ZBA + ZBB + "

    for amofn in (0b00001, 0b00011, 0b01001):
        for src_imm in (3, 0):
            assert _run_amo_op_case(explicit_32, 32, amofn=amofn, src_imm=src_imm, init_mem=0x12345678) == \
                _run_amo_op_case(noisy_32, 32, amofn=amofn, src_imm=src_imm, init_mem=0x12345678)
            assert _run_amo_op_case(explicit_64, 64, amofn=amofn, src_imm=src_imm, init_mem=0x123456789ABCDEF0) == \
                _run_amo_op_case(noisy_64, 64, amofn=amofn, src_imm=src_imm, init_mem=0x123456789ABCDEF0)


def test_star_fullset_system_extensions_contract_stable_on_rv32_and_rv64():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + * + zba + zbb + ??? + m + A + b + B + c + C + d + D + f + F + zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + "
    noisy_64 = "  rv64i + gc + * + zba + zbh + zbb + ??? + m + a + b + B + c + C + d + D + f + F + zicond + ZICOND + zifencei + ZIFENCEI + zicsr + ZICSR + "

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x11) == _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0x11)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x11) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0x11)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b010, rs2=0x11) == _run_zicond_case(noisy_32, 32, funct3=0b010, rs2=0x11)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b010, rs2=0x11) == _run_zicond_case(noisy_64, 64, funct3=0b010, rs2=0x11)


def test_star_fullset_and_noisy_multi_extension_mix_is_stable_on_rv32_and_rv64():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "\n  rv32i + gc + * + m + M + a + A + b + B + c + C + d + D + f + F + zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND + zba + junk + \t"
    noisy_64 = "\n\trv64i + gc + * + m + a + A + b + B + c + C + d + D + f + F + zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND + zbh + ? ? ? + unknown"
    reordered_32 = "RV32I+GC+ZICSR+ZICOND+ZIFENCEI+M+A+B+C+F+D+*+gc+gc"
    reordered_64 = "RV64I+GC+ZICOND+ZIFENCEI+ZICSR+M+A+B+C+F+D+*+GC+GC"

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(explicit_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(explicit_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(reordered_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(reordered_64, 64)

def test_star_fullset_stability_across_noisy_aliasing_and_mixed_case_for_rv32i_rv64i():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + * + m + m + A + a + B + b + C + c + D + d + F + f + zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND + " + \
                "zba + zbb + zba + junk + "
    noisy_64 = "  rv64i + gc + * + m + M + A + a + B + b + C + c + D + d + f + F + zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + " + \
                "ZBA + ZBB + ??? + zext + "
    reordered_32 = " RV32I + * + gc + M + A + m + B + b + C + c + D + d + F + F + ZIFENCEI + zifencei + ZICSR + zicsr + ZICOND + zicond + "
    reordered_64 = " RV64I + gc + * + M + A + a + B + b + C + c + D + d + F + f + zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + "
    assert _run_case("RV32I+GC+*", 32) == _run_case(explicit_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(explicit_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(reordered_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(reordered_64, 64)

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(explicit_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_amo_op_case(explicit_32, 32, amofn=0b00001, src_imm=2, init_mem=0x0BADF00D) == \
        _run_amo_op_case(noisy_32, 32, amofn=0b00001, src_imm=2, init_mem=0x0BADF00D)
    assert _run_amo_op_case(explicit_64, 64, amofn=0b00011, src_imm=0, init_mem=0x123456789ABCDEF0) == \
        _run_amo_op_case(noisy_64, 64, amofn=0b00011, src_imm=0, init_mem=0x123456789ABCDEF0)

    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case(explicit_32, 32, funct3=0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b011) == _run_lr_sc_case(explicit_64, 64, funct3=0b011)
    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case(reordered_32, 32, funct3=0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b011) == _run_lr_sc_case(reordered_64, 64, funct3=0b011)

    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy_32, 32)
    assert _run_fp_width_case("RV64I+GC+*", 64) == _run_fp_width_case(noisy_64, 64)

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x33) == _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0x33)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x33) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0x33)

def test_star_fullset_parser_and_exec_stability_for_rv32i_gc_vs_star_and_noisy_input():
    explicit = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy = "  rv32i + gc + * + m + M + a + A + b + B + c + C + d + D + f + F + zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + " \
            "+ zba + zbb + ??? + junk + "
    reordered = " RV32I + * + gc + M + A + b + B + C + c + D + d + m + F + f + ZICSR + zicsr + ZICOND + zicond + ZIFENCEI + zifencei + "

    assert _run_case("RV32I+GC", 32) == _run_case(explicit, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(explicit, 32)
    assert _run_case("RV32I+GC", 32) == _run_case(noisy, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(reordered, 32)

    assert _run_base_case("RV32I+GC", 32) == _run_base_case(explicit, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(explicit, 32)
    assert _run_base_case("RV32I+GC", 32) == _run_base_case(noisy, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(reordered, 32)

    assert _run_extension_combo_case("RV32I+GC", 32) == _run_extension_combo_case(explicit, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(explicit, 32)
    assert _run_extension_combo_case("RV32I+GC", 32) == _run_extension_combo_case(noisy, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(reordered, 32)

    assert _run_multi_extension_mix_case("RV32I+GC", 32) == _run_multi_extension_mix_case(explicit, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(explicit, 32)
    assert _run_multi_extension_mix_case("RV32I+GC", 32) == _run_multi_extension_mix_case(noisy, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(reordered, 32)

    assert _run_amo_ops_case("RV32I+GC", 32) == _run_amo_ops_case(explicit, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(explicit, 32)
    assert _run_amo_ops_case("RV32I+GC", 32) == _run_amo_ops_case(noisy, 32)

    assert _run_m_case("RV32I+GC", 32) == _run_m_case(explicit, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(explicit, 32)

    assert _run_control_flow_case("RV32I+GC", 32) == _run_control_flow_case(explicit, 32)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(explicit, 32)
    assert _run_control_flow_case("RV32I+GC", 32) == _run_control_flow_case(reordered, 32)

    assert _run_u_type_case("RV32I+GC", 32) == _run_u_type_case(explicit, 32)
    assert _run_u_type_case("RV32I+GC+*", 32) == _run_u_type_case(explicit, 32)
    assert _run_u_type_case("RV32I+GC", 32) == _run_u_type_case(noisy, 32)

    assert _run_jalr_case("RV32I+GC", 32) == _run_jalr_case(explicit, 32)
    assert _run_jalr_case("RV32I+GC+*", 32) == _run_jalr_case(explicit, 32)
    assert _run_jalr_case("RV32I+GC", 32) == _run_jalr_case(reordered, 32)

def test_star_fullset_runtime_control_flow_and_fp32_stability_on_rv32i_gc_and_star():
    explicit = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy = "  rv32i + gc + * + m + M + a + A + b + B + c + C + d + D + F + f + zicond + ZICOND + zifencei + ZIFENCEI + zicsr + ZICSR + zba + ??? + junk + "
    reordered = "RV32I+*+gc+M+A+B+C+D+F+ZICSR+ZIFENCEI+ZICOND+m+a+b+c+d+f+"

    assert _run_case("RV32I+GC", 32) == _run_case(explicit, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(explicit, 32)
    assert _run_case("RV32I+GC", 32) == _run_case(noisy, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(reordered, 32)

    assert _run_base_case("RV32I+GC", 32) == _run_base_case(explicit, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(explicit, 32)
    assert _run_base_case("RV32I+GC", 32) == _run_base_case(noisy, 32)

    assert _run_extension_combo_case("RV32I+GC", 32) == _run_extension_combo_case(explicit, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(explicit, 32)
    assert _run_extension_combo_case("RV32I+GC", 32) == _run_extension_combo_case(reordered, 32)

    assert _run_b_case("RV32I+GC", 32) == _run_b_case(explicit, 32, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32) == _run_b_case(explicit, 32, funct3=0b110)
    assert _run_b_case("RV32I+GC", 32) == _run_b_case(noisy, 32, funct3=0b110)
    assert _run_b_case("RV32I+GC", 32) == _run_b_case(reordered, 32, funct3=0b111)

    assert _run_jalr_case("RV32I+GC", 32) == _run_jalr_case(explicit, 32)
    assert _run_jalr_case("RV32I+GC+*", 32) == _run_jalr_case(explicit, 32)
    assert _run_jalr_case("RV32I+GC", 32) == _run_jalr_case(noisy, 32)

    assert _run_fp32_case("RV32I+GC", 32) == _run_fp32_case(explicit, 32)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(explicit, 32)
    assert _run_fp32_case("RV32I+GC", 32) == _run_fp32_case(noisy, 32)

    assert _run_fp_store_width_case("RV32I+GC", 32) == _run_fp_store_width_case(explicit, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(explicit, 32)
    assert _run_fp_store_width_case("RV32I+GC", 32) == _run_fp_store_width_case(reordered, 32)

    assert _run_zifencei_case("RV32I+GC", 32) == _run_zifencei_case(explicit, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(explicit, 32)
    assert _run_zifencei_case("RV32I+GC", 32) == _run_zifencei_case(noisy, 32)

def test_star_fullset_runtime_d_and_system_paths_stable_for_rv32i_gc_and_star_forms():
    explicit = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy = "  rv32i + gc + * + m + M + a + A + b + B + c + C + d + D + f + F + zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND + ??? + ZBA + ZBB + garbage + "
    reordered = " RV32I + * + GC + m + a + A + B + b + C + c + D + d + F + f + ZICSR + zicsr + ZIFENCEI + zifencei + ZICOND + zicond + "

    assert _run_case("RV32I+GC", 32) == _run_case(explicit, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(explicit, 32)
    assert _run_case("RV32I+GC", 32) == _run_case(noisy, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(reordered, 32)

    assert _run_fp_case("RV32I+GC", 32) == _run_fp_case(explicit, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(explicit, 32)
    assert _run_fp_case("RV32I+GC", 32) == _run_fp_case(reordered, 32)

    assert _run_d_case("RV32I+GC", 32) == _run_d_case(explicit, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(explicit, 32)
    assert _run_d_case("RV32I+GC", 32) == _run_d_case(noisy, 32)

    assert _run_fp_width_case("RV32I+GC", 32) == _run_fp_width_case(explicit, 32)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(explicit, 32)
    assert _run_fp_width_case("RV32I+GC", 32) == _run_fp_width_case(reordered, 32)

    assert _run_zicsr_case("RV32I+GC", 32) == _run_zicsr_case(explicit, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(explicit, 32)
    assert _run_zicsr_case("RV32I+GC", 32) == _run_zicsr_case(noisy, 32)

    assert _run_zifencei_case("RV32I+GC", 32) == _run_zifencei_case(explicit, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(explicit, 32)
    assert _run_zifencei_case("RV32I+GC", 32) == _run_zifencei_case(reordered, 32)

    assert _run_zicond_case("RV32I+GC", 32, funct3=0b000, rs2=0x0F) == _run_zicond_case(explicit, 32, funct3=0b000, rs2=0x0F)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x11) == _run_zicond_case(explicit, 32, funct3=0b001, rs2=0x11)
    assert _run_zicond_case("RV32I+GC", 32, funct3=0b010, rs2=0x13) == _run_zicond_case(noisy, 32, funct3=0b010, rs2=0x13)

    assert _run_amo_op_case(explicit, 32, amofn=0b00010, src_imm=1, init_mem=0x55AA55AA) == \
        _run_amo_op_case(noisy, 32, amofn=0b00010, src_imm=1, init_mem=0x55AA55AA)
    assert _run_amo_op_case(explicit, 32, amofn=0b01011, src_imm=2, init_mem=0x12345678) == \
        _run_amo_op_case(reordered, 32, amofn=0b01011, src_imm=2, init_mem=0x12345678)

    assert _run_lr_sc_case("RV32I+GC", 32, funct3=0b010) == _run_lr_sc_case(explicit, 32, funct3=0b010)
    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case(explicit, 32, funct3=0b010)
    assert _run_lr_sc_case("RV32I+GC", 32, funct3=0b010) == _run_lr_sc_case(noisy, 32, funct3=0b010)

def test_star_fullset_runtime_rv32i_core_and_star_stability_for_multi_category_mix():
    explicit = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy = "  rv32i + gc + * + m + M + a + A + b + B + c + C + d + D + f + F + zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND + zba + zbb + ??? + junk + "
    messy = " RV32I + + + gc + M + m + A + a + B + b + C + c + D + d + F + f + ZICOND + zicond + ZIFENCEI + zifencei + ZICSR + zicsr + unknown "

    assert _run_case("RV32I+GC", 32) == _run_case(explicit, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(explicit, 32)
    assert _run_case("RV32I+GC", 32) == _run_case(noisy, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(messy, 32)

    assert _run_base_case("RV32I+GC", 32) == _run_base_case(explicit, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(explicit, 32)
    assert _run_base_case("RV32I+GC", 32) == _run_base_case(noisy, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(messy, 32)

    assert _run_extension_combo_case("RV32I+GC", 32) == _run_extension_combo_case(explicit, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(explicit, 32)
    assert _run_extension_combo_case("RV32I+GC", 32) == _run_extension_combo_case(noisy, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(messy, 32)

    assert _run_multi_extension_mix_case("RV32I+GC", 32) == _run_multi_extension_mix_case(explicit, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(explicit, 32)
    assert _run_multi_extension_mix_case("RV32I+GC", 32) == _run_multi_extension_mix_case(noisy, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(messy, 32)

    assert _run_m_case("RV32I+GC", 32) == _run_m_case(explicit, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(explicit, 32)

    assert _run_b_case("RV32I+GC", 32) == _run_b_case(explicit, 32, funct3=0b100)
    assert _run_b_case("RV32I+GC+*", 32) == _run_b_case(explicit, 32, funct3=0b101)
    assert _run_b_case("RV32I+GC", 32) == _run_b_case(noisy, 32, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32) == _run_b_case(messy, 32, funct3=0b111)

    assert _run_jalr_case("RV32I+GC", 32) == _run_jalr_case(explicit, 32)
    assert _run_jalr_case("RV32I+GC+*", 32) == _run_jalr_case(explicit, 32)
    assert _run_jalr_case("RV32I+GC", 32) == _run_jalr_case(noisy, 32)
    assert _run_jalr_case("RV32I+GC+*", 32) == _run_jalr_case(messy, 32)

    assert _run_control_flow_case("RV32I+GC", 32) == _run_control_flow_case(explicit, 32)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(explicit, 32)
    assert _run_control_flow_case("RV32I+GC", 32) == _run_control_flow_case(noisy, 32)

def test_star_fullset_runtime_cross_xlen_stability_for_control_flow_and_system_mix():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + * + m + M + a + A + b + B + c + C + d + D + f + F + zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND + ??? + garbage + "
    noisy_64 = "  rv64i + gc + * + m + M + a + A + b + B + c + C + d + D + f + F + zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND + zba + zbb + ??? + junk + "
    messy_32 = " RV32I + + + gc + M + m + A + a + B + b + C + c + D + d + F + f + ZICOND + zicond + ZIFENCEI + zifencei + ZICSR + zicsr + unknown "
    messy_64 = " RV64I + + + gc + M + m + A + a + B + b + C + c + D + d + F + f + ZICOND + zicond + ZIFENCEI + zifencei + ZICSR + zicsr + unknown + "

    assert _run_control_flow_case("RV32I+GC", 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case("RV32I+GC", 32) == _run_control_flow_case(noisy_32, 32)
    assert _run_control_flow_case("RV64I+GC", 64) == _run_control_flow_case(explicit_64, 64)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(explicit_64, 64)
    assert _run_control_flow_case("RV64I+GC", 64) == _run_control_flow_case(noisy_64, 64)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(messy_32, 32)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(messy_64, 64)

    assert _run_zifencei_case("RV32I+GC", 32) == _run_zifencei_case(explicit_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(explicit_32, 32)
    assert _run_zifencei_case("RV64I+GC", 64) == _run_zifencei_case(explicit_64, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(explicit_64, 64)

    assert _run_multi_extension_mix_case("RV32I+GC", 32) == _run_multi_extension_mix_case(explicit_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(explicit_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC", 64) == _run_multi_extension_mix_case(explicit_64, 64)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(explicit_64, 64)


def test_star_fullset_runtime_rv64_control_and_aux_paths_stable():
    explicit = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy = "  rv64i + gc + * + m + M + a + A + b + B + c + C + d + D + f + F + zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND + ??? + random.ext + "
    messy = " RV64I + + + gc + M + m + A + a + B + b + C + c + D + d + F + f + ZICOND + zicond + ZIFENCEI + zifencei + ZICSR + zicsr + ??? + "

    assert _run_case("RV64I+GC", 64) == _run_case(explicit, 64)
    assert _run_case("RV64I+GC+*", 64) == _run_case(explicit, 64)
    assert _run_case("RV64I+GC", 64) == _run_case(noisy, 64)
    assert _run_case("RV64I+GC+*", 64) == _run_case(messy, 64)

    assert _run_jalr_case("RV64I+GC", 64) == _run_jalr_case(explicit, 64)
    assert _run_jalr_case("RV64I+GC+*", 64) == _run_jalr_case(explicit, 64)
    assert _run_jalr_case("RV64I+GC", 64) == _run_jalr_case(noisy, 64)
    assert _run_jalr_case("RV64I+GC+*", 64) == _run_jalr_case(messy, 64)

    assert _run_b_case("RV64I+GC", 64, funct3=0b100) == _run_b_case(explicit, 64, funct3=0b100)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b101) == _run_b_case(explicit, 64, funct3=0b101)
    assert _run_b_case("RV64I+GC", 64, funct3=0b110) == _run_b_case(noisy, 64, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(messy, 64, funct3=0b111)

    assert _run_zifencei_case("RV64I+GC", 64) == _run_zifencei_case(explicit, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(explicit, 64)
    assert _run_zifencei_case("RV64I+GC", 64) == _run_zifencei_case(messy, 64)

    assert _run_zicsr_case("RV64I+GC", 64) == _run_zicsr_case(explicit, 64)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(explicit, 64)
    assert _run_zicsr_case("RV64I+GC", 64) == _run_zicsr_case(noisy, 64)

    assert _run_zicond_case("RV64I+GC", 64, funct3=0b000, rs2=0x0F) == _run_zicond_case(explicit, 64, funct3=0b000, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x11) == _run_zicond_case(explicit, 64, funct3=0b001, rs2=0x11)
    assert _run_zicond_case("RV64I+GC", 64, funct3=0b010, rs2=0x13) == _run_zicond_case(noisy, 64, funct3=0b010, rs2=0x13)

    assert _run_amo_op_case(explicit, 64, amofn=0b00010, src_imm=1, init_mem=0x55AA55AA) == \
        _run_amo_op_case(noisy, 64, amofn=0b00010, src_imm=1, init_mem=0x55AA55AA)
    assert _run_amo_op_case(explicit, 64, amofn=0b01011, src_imm=2, init_mem=0x12345678) == \
        _run_amo_op_case(messy, 64, amofn=0b01011, src_imm=2, init_mem=0x12345678)

    assert _run_lr_sc_case("RV64I+GC", 64, funct3=0b011) == _run_lr_sc_case(explicit, 64, funct3=0b011)
    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b011) == _run_lr_sc_case(explicit, 64, funct3=0b011)
    assert _run_lr_sc_case("RV64I+GC", 64, funct3=0b011) == _run_lr_sc_case(messy, 64, funct3=0b011)

def test_star_runtime_cross_width_mix_guard_for_jalr_b_zicond_lr_sc_and_system():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + * + m + a + B + C + zifencei + ZICOND + zicsr + ZICOND + garbage + "
    noisy_64 = "  rv64i + gc + * + m + a + b + c + f + d + zifencei + ZICOND + zicsr + bad.ext + "

    assert _run_jalr_case("RV32I+GC", 32) == _run_jalr_case(full_32, 32)
    assert _run_jalr_case("RV32I+GC+*", 32) == _run_jalr_case(full_32, 32)
    assert _run_jalr_case("RV32I+GC", 32) == _run_jalr_case(noisy_32, 32)

    assert _run_jalr_case("RV64I+GC", 64) == _run_jalr_case(full_64, 64)
    assert _run_jalr_case("RV64I+GC+*", 64) == _run_jalr_case(full_64, 64)
    assert _run_jalr_case("RV64I+GC+*", 64) == _run_jalr_case(noisy_64, 64)

    assert _run_b_case("RV32I+GC", 32, funct3=0b111) == _run_b_case(full_32, 32, funct3=0b111)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b101) == _run_b_case(full_32, 32, funct3=0b101)
    assert _run_b_case("RV32I+GC", 64, funct3=0b110) == _run_b_case(full_64, 64, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b010) == _run_b_case(full_64, 64, funct3=0b010)

    assert _run_zicond_case("RV32I+GC", 32, funct3=0b001, rs2=0x20) == _run_zicond_case(full_32, 32, funct3=0b001, rs2=0x20)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b010, rs2=0x02) == _run_zicond_case(full_32, 32, funct3=0b010, rs2=0x02)
    assert _run_zicond_case("RV64I+GC", 64, funct3=0b011, rs2=0x03) == _run_zicond_case(full_64, 64, funct3=0b011, rs2=0x03)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b100, rs2=0x04) == _run_zicond_case(noisy_64, 64, funct3=0b100, rs2=0x04)

    assert _run_lr_sc_case("RV32I+GC", 32, funct3=0b010) == _run_lr_sc_case(full_32, 32, funct3=0b010)
    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case(noisy_32, 32, funct3=0b010)
    assert _run_lr_sc_case("RV64I+GC", 64, funct3=0b011) == _run_lr_sc_case(full_64, 64, funct3=0b011)
    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b011) == _run_lr_sc_case(noisy_64, 64, funct3=0b011)

    assert _run_zifencei_case("RV32I+GC", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)

def test_star_fullset_invariant_across_rv32i_gc_parser_forms_with_runtime_mix():
    explicit = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    dense = "rv32i+gc+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy = "  rv32i + gc + * + m + a + B + b + C + c + D + d + F + f + zicond + ZICOND + zicsr + ZICSR + zifencei + ZIFENCEI + ??? + junk + "
    reordered = "RV32I + GC + C + B + A + M + F + D + ZICOND + zifencei + zicsr"

    assert _run_case("RV32I+GC", 32) == _run_case(explicit, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(explicit, 32)
    assert _run_case("RV32I+GC", 32) == _run_case(dense, 32)
    assert _run_case("RV32I+GC", 32) == _run_case(noisy, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(reordered, 32)

    assert _run_base_case("RV32I+GC", 32) == _run_base_case(explicit, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(explicit, 32)
    assert _run_base_case("RV32I+GC", 32) == _run_base_case(dense, 32)
    assert _run_base_case("RV32I+GC", 32) == _run_base_case(noisy, 32)

    assert _run_extension_combo_case("RV32I+GC", 32) == _run_extension_combo_case(explicit, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(explicit, 32)
    assert _run_extension_combo_case("RV32I+GC", 32) == _run_extension_combo_case(noisy, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(reordered, 32)

    assert _run_multi_extension_mix_case("RV32I+GC", 32) == _run_multi_extension_mix_case(explicit, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(explicit, 32)
    assert _run_multi_extension_mix_case("RV32I+GC", 32) == _run_multi_extension_mix_case(dense, 32)

    assert _run_m_case("RV32I+GC", 32) == _run_m_case(explicit, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(explicit, 32)
    assert _run_m_case("RV32I+GC", 32) == _run_m_case(noisy, 32)

    assert _run_fp_case("RV32I+GC", 32) == _run_fp_case(explicit, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(explicit, 32)
    assert _run_fp_case("RV32I+GC", 32) == _run_fp_case(noisy, 32)

def test_star_fullset_invariant_across_rv64i_gc_parser_forms_with_runtime_mix():
    explicit = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    dense = "rv64i+gc+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy = "  rv64i + gc + * + m + a + B + b + C + c + D + d + F + f + zicond + ZICOND + zicsr + ZICSR + zifencei + ZIFENCEI + ??? + garbage + "
    reordered = " RV64I + GC + C + B + A + M + F + D + ZICOND + zifencei + zicsr"

    assert _run_case("RV64I+GC", 64) == _run_case(explicit, 64)
    assert _run_case("RV64I+GC+*", 64) == _run_case(explicit, 64)
    assert _run_case("RV64I+GC", 64) == _run_case(dense, 64)
    assert _run_case("RV64I+GC", 64) == _run_case(noisy, 64)
    assert _run_case("RV64I+GC+*", 64) == _run_case(reordered, 64)

    assert _run_base_case("RV64I+GC", 64) == _run_base_case(explicit, 64)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(explicit, 64)
    assert _run_base_case("RV64I+GC", 64) == _run_base_case(noisy, 64)

    assert _run_extension_combo_case("RV64I+GC", 64) == _run_extension_combo_case(explicit, 64)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(explicit, 64)
    assert _run_extension_combo_case("RV64I+GC", 64) == _run_extension_combo_case(reordered, 64)

    assert _run_multi_extension_mix_case("RV64I+GC", 64) == _run_multi_extension_mix_case(explicit, 64)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(explicit, 64)
    assert _run_multi_extension_mix_case("RV64I+GC", 64) == _run_multi_extension_mix_case(noisy, 64)

    assert _run_control_flow_case("RV64I+GC", 64) == _run_control_flow_case(explicit, 64)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(explicit, 64)
    assert _run_control_flow_case("RV64I+GC", 64) == _run_control_flow_case(noisy, 64)

    assert _run_b_case("RV64I+GC", 64, funct3=0b110) == _run_b_case(explicit, 64, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(explicit, 64, funct3=0b111)
    assert _run_b_case("RV64I+GC", 64, funct3=0b101) == _run_b_case(reordered, 64, funct3=0b101)

    assert _run_zifencei_case("RV64I+GC", 64) == _run_zifencei_case(explicit, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(explicit, 64)
    assert _run_zifencei_case("RV64I+GC", 64) == _run_zifencei_case(noisy, 64)

    assert _run_zicond_case("RV64I+GC", 64, funct3=0b000, rs2=0x0F) == _run_zicond_case(explicit, 64, funct3=0b000, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x11) == _run_zicond_case(explicit, 64, funct3=0b001, rs2=0x11)

    assert _run_lr_sc_case("RV64I+GC", 64, funct3=0b011) == _run_lr_sc_case(explicit, 64, funct3=0b011)
    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b011) == _run_lr_sc_case(explicit, 64, funct3=0b011)
    assert _run_lr_sc_case("RV64I+GC", 64, funct3=0b011) == _run_lr_sc_case(noisy, 64, funct3=0b011)

def test_star_rv32_runtime_fp_a_m_zicsr_zifencei_stability_mix():
    explicit = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy = "  rv32i + gc + * + m + a + B + b + C + c + D + d + F + f + zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND + ??? + junk + "
    reordered = "RV32I + GC + D + C + B + A + M + F + zicsr + zifencei + zicond"

    assert _run_fp_case("RV32I+GC", 32) == _run_fp_case(explicit, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(explicit, 32)
    assert _run_fp_case("RV32I+GC", 32) == _run_fp_case(noisy, 32)

    assert _run_d_case("RV32I+GC", 32) == _run_d_case(explicit, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(explicit, 32)
    assert _run_d_case(explicit, 32) == _run_d_case(starred, 32)

    assert _run_fp_width_case("RV32I+GC", 32) == _run_fp_width_case(explicit, 32)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(explicit, 32)
    assert _run_fp_width_case("RV32I+GC", 32) == _run_fp_width_case(noisy, 32)

    assert _run_fp_store_width_case("RV32I+GC", 32) == _run_fp_store_width_case(explicit, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(explicit, 32)
    assert _run_fp_store_width_case("RV32I+GC", 32) == _run_fp_store_width_case(noisy, 32)

    assert _run_amo_star_case("RV32I+GC", 32) == _run_amo_star_case(explicit, 32)
    assert _run_amo_star_case("RV32I+GC+*", 32) == _run_amo_star_case(explicit, 32)
    assert _run_amo_star_case("RV32I+GC", 32) == _run_amo_star_case(reordered, 32)

    assert _run_amo_op_case("RV32I+GC", 32, amofn=0b00010, src_imm=3, init_mem=0x12345678) == \
        _run_amo_op_case(explicit, 32, amofn=0b00010, src_imm=3, init_mem=0x12345678)
    assert _run_amo_op_case("RV32I+GC+*", 32, amofn=0b00010, src_imm=3, init_mem=0x12345678) == \
        _run_amo_op_case(noisy, 32, amofn=0b00010, src_imm=3, init_mem=0x12345678)

    assert _run_lr_sc_case("RV32I+GC", 32, funct3=0b010) == _run_lr_sc_case(explicit, 32, funct3=0b010)
    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case(explicit, 32, funct3=0b010)
    assert _run_lr_sc_case("RV32I+GC", 32, funct3=0b010) == _run_lr_sc_case(noisy, 32, funct3=0b010)

    assert _run_zicsr_case("RV32I+GC", 32) == _run_zicsr_case(explicit, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(explicit, 32)
    assert _run_zicsr_case("RV32I+GC", 32) == _run_zicsr_case(reordered, 32)

    assert _run_zifencei_case("RV32I+GC", 32) == _run_zifencei_case(explicit, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(explicit, 32)
    assert _run_zifencei_case("RV32I+GC", 32) == _run_zifencei_case(noisy, 32)

def test_star_fullset_stability_with_compressed_alias_inputs_and_runtime_mix():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    compact_32 = "RV32I+GC+M+A+B+C+*"
    compact_64 = "RV64I+GC+M+A+B+C+*"
    mixed = "  rv32i + gc + * + m + a + b + C + zifencei + ZICOND + zicsr + ??? + gc + ZICSR + d + f + "
    noisy_64 = "  rv64i + gc + * + m + a + b + C + zifencei + zifencei + ZICOND + zicsr + gc + garbage + d + f + "

    assert _run_case("RV32I+GC", 32) == _run_case(explicit_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(compact_32, 32)
    assert _run_case("RV32I+GC", 32) == _run_case(mixed, 32)

    assert _run_case("RV64I+GC", 64) == _run_case(explicit_64, 64)
    assert _run_case("RV64I+GC+*", 64) == _run_case(compact_64, 64)
    assert _run_case("RV64I+GC", 64) == _run_case(noisy_64, 64)

    assert _run_control_flow_case("RV32I+GC", 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(compact_32, 32)
    assert _run_control_flow_case("RV64I+GC", 64) == _run_control_flow_case(explicit_64, 64)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(compact_64, 64)

    assert _run_jalr_case("RV32I+GC", 32) == _run_jalr_case(explicit_32, 32)
    assert _run_jalr_case("RV32I+GC+*", 32) == _run_jalr_case(compact_32, 32)
    assert _run_jalr_case("RV64I+GC", 64) == _run_jalr_case(explicit_64, 64)
    assert _run_jalr_case("RV64I+GC+*", 64) == _run_jalr_case(compact_64, 64)

    assert _run_b_case("RV32I+GC", 32, funct3=0b110) == _run_b_case(explicit_32, 32, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(compact_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC", 64, funct3=0b111) == _run_b_case(explicit_64, 64, funct3=0b111)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(compact_64, 64, funct3=0b111)

    assert _run_extension_combo_case("RV32I+GC", 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(compact_32, 32)
    assert _run_extension_combo_case("RV64I+GC", 64) == _run_extension_combo_case(explicit_64, 64)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(compact_64, 64)

    assert _run_amo_star_case("RV32I+GC", 32) == _run_amo_star_case(compact_32, 32)
    assert _run_amo_star_case("RV64I+GC", 64) == _run_amo_star_case(compact_64, 64)
    assert _run_zifencei_case("RV32I+GC", 32) == _run_zifencei_case(compact_32, 32)
    assert _run_zifencei_case("RV64I+GC", 64) == _run_zifencei_case(compact_64, 64)
    assert _run_zicsr_case("RV32I+GC", 32) == _run_zicsr_case(compact_32, 32)
    assert _run_zicsr_case("RV64I+GC", 64) == _run_zicsr_case(compact_64, 64)

def test_star_fullset_cross_width_runtime_for_jalr_b_zicond_lr_sc_amo_paths():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + * + m + M + a + A + b + B + c + C + d + D + f + F + zifencei + ZICOND + zicsr + unknown + "
    noisy_64 = "  rv64i + gc + * + m + M + a + A + b + B + c + C + d + D + f + F + zifencei + ZICOND + zicsr + ??? + junk "

    assert _run_case("RV32I+GC", 32) == _run_case(explicit_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(explicit_32, 32)
    assert _run_case("RV32I+GC", 32) == _run_case(noisy_32, 32)

    assert _run_case("RV64I+GC", 64) == _run_case(explicit_64, 64)
    assert _run_case("RV64I+GC+*", 64) == _run_case(explicit_64, 64)
    assert _run_case("RV64I+GC", 64) == _run_case(noisy_64, 64)

    assert _run_jalr_case("RV32I+GC", 32) == _run_jalr_case(explicit_32, 32)
    assert _run_jalr_case("RV32I+GC+*", 32) == _run_jalr_case(noisy_32, 32)
    assert _run_jalr_case("RV64I+GC", 64) == _run_jalr_case(explicit_64, 64)
    assert _run_jalr_case("RV64I+GC+*", 64) == _run_jalr_case(noisy_64, 64)

    assert _run_b_case("RV32I+GC", 32, funct3=0b110) == _run_b_case(explicit_32, 32, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(noisy_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC", 64, funct3=0b101) == _run_b_case(explicit_64, 64, funct3=0b101)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b001) == _run_b_case(noisy_64, 64, funct3=0b001)

    assert _run_zicond_case("RV32I+GC", 32, funct3=0b000, rs2=0x0F) == _run_zicond_case(explicit_32, 32, funct3=0b000, rs2=0x0F)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x11) == _run_zicond_case(explicit_32, 32, funct3=0b001, rs2=0x11)
    assert _run_zicond_case("RV64I+GC", 64, funct3=0b010, rs2=0x12) == _run_zicond_case(explicit_64, 64, funct3=0b010, rs2=0x12)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b011, rs2=0x13) == _run_zicond_case(noisy_64, 64, funct3=0b011, rs2=0x13)

    assert _run_lr_sc_case("RV32I+GC", 32, funct3=0b010) == _run_lr_sc_case(explicit_32, 32, funct3=0b010)
    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case(noisy_32, 32, funct3=0b010)
    assert _run_lr_sc_case("RV64I+GC", 64, funct3=0b011) == _run_lr_sc_case(explicit_64, 64, funct3=0b011)
    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b011) == _run_lr_sc_case(noisy_64, 64, funct3=0b011)

    assert _run_amo_op_case("RV32I+GC", 32, amofn=0b00010, src_imm=3, init_mem=0x55AA55AA) == \
        _run_amo_op_case(noisy_32, 32, amofn=0b00010, src_imm=3, init_mem=0x55AA55AA)
    assert _run_amo_op_case("RV64I+GC", 64, amofn=0b01011, src_imm=2, init_mem=0x12345678) == \
        _run_amo_op_case(noisy_64, 64, amofn=0b01011, src_imm=2, init_mem=0x12345678)

def test_star_fullset_runtime_guard_for_mixed_control_atomics_and_sys_under_reordered_parser_forms():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    reordered_32 = "RV32I + GC + B + A + C + M + F + D + ZIFENCEI + ZICSR + ZICOND"
    reordered_64 = "RV64I + GC + A + C + B + M + D + F + ZICSR + ZICOND + ZIFENCEI"
    noisy_32 = "  rv32i + gc + ??? + m + a + B + b + C + c + D + d + F + f + zicond + ZICOND + zicsr + ZICSR + zifencei + ZIFENCEI + garbage + "
    noisy_64 = "  rv64i + gc + ??? + m + A + b + B + c + C + d + f + F + zicsr + ZICSR + ZICOND + zicond + zifencei + ZIFENCEI + junk + "

    assert _run_m_case("RV32I+GC", 32) == _run_m_case(full_32, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(reordered_32, 32)
    assert _run_m_case("RV32I+GC", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC", 64) == _run_m_case(full_64, 64)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(reordered_64, 64)
    assert _run_m_case("RV64I+GC", 64) == _run_m_case(noisy_64, 64)

    assert _run_amo_ops_case("RV32I+GC", 32) == _run_amo_ops_case(full_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_amo_ops_case("RV64I+GC", 64) == _run_amo_ops_case(full_64, 64)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC", 64) == _run_extension_combo_case(noisy_64, 64)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(reordered_64, 64)

def test_star_fullset_parser_mix_stability_for_fp32_and_system_combo_rv32_and_rv64():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    reordered_32 = "RV32I + GC + ZICOND + F + D + M + A + B + C + ZICSR + ZIFENCEI"
    reordered_64 = "RV64I + GC + F + D + B + A + M + C + ZICOND + ZICSR + ZIFENCEI"
    noisy_32 = "  rv32i + gc + * + m + a + b + C + f + d + zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + ??? + garbage + "
    noisy_64 = "  rv64i + gc + * + m + A + B + C + F + D + zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + ??? + garbage + "

    assert _run_fp32_case("RV32I+GC", 32) == _run_fp32_case(explicit_32, 32)
    assert _run_fp32_case("RV32I+GC+*", 32) == _run_fp32_case(reordered_32, 32)
    assert _run_fp32_case("RV32I+GC", 32) == _run_fp32_case(noisy_32, 32)
    assert _run_fp32_case("RV64I+GC", 64) == _run_fp32_case(explicit_64, 64)
    assert _run_fp32_case("RV64I+GC+*", 64) == _run_fp32_case(reordered_64, 64)
    assert _run_fp32_case("RV64I+GC", 64) == _run_fp32_case(noisy_64, 64)

    assert _run_zicsr_star_case("RV32I+GC+ZICSR", 32) == _run_zicsr_star_case(noisy_32, 32)
    assert _run_zicsr_star_case("RV32I+GC+*", 32) == _run_zicsr_star_case(explicit_32, 32)
    assert _run_zicsr_star_case("RV32I+GC+ZICSR", 64) == _run_zicsr_star_case(noisy_64, 64)
    assert _run_zicsr_star_case("RV64I+GC+*", 64) == _run_zicsr_star_case(explicit_64, 64)

    assert _run_u_type_case("RV32I+GC", 32) == _run_u_type_case(explicit_32, 32)
    assert _run_u_type_case("RV32I+GC+*", 32) == _run_u_type_case(noisy_32, 32)
    assert _run_u_type_case("RV64I+GC", 64) == _run_u_type_case(explicit_64, 64)
    assert _run_u_type_case("RV64I+GC+*", 64) == _run_u_type_case(reordered_64, 64)

def test_star_fullset_runtime_edge_mix_stability_for_mw_fp_zicsr_and_zicond_rv32_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    compact_32 = "rv32i + gc + * + M + A + C + F + D"
    compact_64 = "rv64i + gc + * + M + A + C + F + D"
    noisy_32 = "  rv32i + gc + ??? + m + a + b + c + C + d + D + f + F + zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND + x + y + "
    noisy_64 = "  rv64i + gc + ??? + m + A + B + c + C + D + f + F + zicsr + ZICSR + ZICOND + zicond + zifencei + ZIFENCEI + junk + "

    assert _run_case("RV32I+GC", 32) == _run_case(full_32, 32)
    assert _run_case("RV32I+GC+*", 32) == _run_case(compact_32, 32)
    assert _run_case("RV32I+GC", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC", 64) == _run_case(full_64, 64)
    assert _run_case("RV64I+GC+*", 64) == _run_case(compact_64, 64)
    assert _run_case("RV64I+GC", 64) == _run_case(noisy_64, 64)

    assert _run_fp_case("RV32I+GC", 32) == _run_fp_case(full_32, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(compact_32, 32)
    assert _run_fp_case("RV64I+GC", 64) == _run_fp_case(full_64, 64)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(compact_64, 64)

    assert _run_d_case("RV32I+GC", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV64I+GC", 64) == _run_d_case(noisy_64, 64)

    assert _run_mw_case("RV32I+GC", 32) == _run_mw_case(compact_32, 32)
    assert _run_mw_case("RV64I+GC", 64) == _run_mw_case(compact_64, 64)
    assert _run_mw_edge_case("RV32I+GC+*", 32) == _run_mw_edge_case(full_32, 32)
    assert _run_mw_edge_case("RV64I+GC+*", 64) == _run_mw_edge_case(full_64, 64)

    assert _run_zicsr_star_case("RV32I+GC", 32) == _run_zicsr_star_case(noisy_32, 32)
    assert _run_zicsr_star_case("RV64I+GC", 64) == _run_zicsr_star_case(noisy_64, 64)
    assert _run_zicsr_star_case("RV32I+GC+*", 32) == _run_zicsr_star_case(full_32, 32)
    assert _run_zicsr_star_case("RV64I+GC+*", 64) == _run_zicsr_star_case(full_64, 64)

    assert _run_zifencei_case("RV32I+GC", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC", 64) == _run_zifencei_case(noisy_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(full_64, 64)

def test_star_fullset_runtime_stability_for_multi_extension_mix_with_star_parser_noise_rv32_rv64():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + * + m + a + b + c + C + d + D + F + f + zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + ??? + x + "
    noisy_64 = "  rv64i + gc + * + m + A + B + C + d + f + F + zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + ??? + y + "

    assert _run_multi_extension_mix_case("RV32I+GC", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC", 64) == _run_multi_extension_mix_case(full_64, 64)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)

    assert _run_extension_combo_case("RV32I+GC", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC", 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_amo_star_case("RV32I+GC", 32) == _run_amo_star_case(full_32, 32)
    assert _run_amo_star_case("RV32I+GC+*", 32) == _run_amo_star_case(full_32, 32)
    assert _run_amo_star_case("RV64I+GC", 64) == _run_amo_star_case(full_64, 64)
    assert _run_amo_star_case("RV64I+GC+*", 64) == _run_amo_star_case(full_64, 64)

    assert _run_zicond_case("RV32I+GC", 32, funct3=0b101, rs2=0x21) == _run_zicond_case(noisy_32, 32, funct3=0b101, rs2=0x21)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b110, rs2=0x22) == _run_zicond_case(full_32, 32, funct3=0b110, rs2=0x22)
    assert _run_zicond_case("RV64I+GC", 64, funct3=0b011, rs2=0x09) == _run_zicond_case(noisy_64, 64, funct3=0b011, rs2=0x09)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x10) == _run_zicond_case(full_64, 64, funct3=0b001, rs2=0x10)

    assert _run_control_flow_case("RV32I+GC", 32) == _run_control_flow_case(noisy_32, 32)
    assert _run_control_flow_case("RV64I+GC", 64) == _run_control_flow_case(noisy_64, 64)
    assert _run_jalr_case("RV64I+GC+*", 64) == _run_jalr_case(full_64, 64)


def test_star_fullset_branch_matrix_matches_runtime_bundle_for_rv32_and_rv64():
    explicit_32 = "RV32I+GC+M+A+B+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + * + zicsr + zifencei + zicond + m + a + c + f + d + b + ??? + "
    noisy_64 = "  rv64i + gc + * + ZICSR + ZIFENCEI + ZICOND + M + A + C + F + D + B + ??? + "

    for funct3 in (0b000, 0b001, 0b100, 0b101, 0b110, 0b111):
        rv32_expected = _run_b_case(explicit_32, 32, funct3=funct3)
        rv64_expected = _run_b_case(explicit_64, 64, funct3=funct3)

        assert _run_b_case("RV32I+GC", 32, funct3=funct3) == rv32_expected
        assert _run_b_case("RV32I+GC+*", 32, funct3=funct3) == rv32_expected
        assert _run_b_case(noisy_32, 32, funct3=funct3) == rv32_expected

        assert _run_b_case("RV64I+GC", 64, funct3=funct3) == rv64_expected
        assert _run_b_case("RV64I+GC+*", 64, funct3=funct3) == rv64_expected
        assert _run_b_case(noisy_64, 64, funct3=funct3) == rv64_expected


def test_star_runtime_stability_across_system_and_jump_alias_variants_rv32_rv64():
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    mixed_32 = "  rv32i + gc + * + zicsr + zifencei + zicond + m + a + b + c + d + f + ??? + "
    mixed_64 = "  rv64i + gc + * + zicsr + ZICSR + zifencei + ZIFENCEI + zicond + m + a + b + c + d + f + ??? + "
    verbose_32 = "RV32I+GC+M+A+B+f+d+zicond+zicsr+zifencei+ZICOND+ZICSR+ZIFENCEI+"
    verbose_64 = "RV64I+GC+M+A+B+f+d+zicond+zicsr+zifencei+ZICOND+ZICSR+ZIFENCEI+"

    assert _run_jalr_case("RV32I+GC", 32) == _run_jalr_case(explicit_32, 32)
    assert _run_jalr_case("RV32I+GC+*", 32) == _run_jalr_case(mixed_32, 32)
    assert _run_jalr_case("RV32I+GC", 32) == _run_jalr_case(verbose_32, 32)

    assert _run_control_flow_case("RV32I+GC", 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(mixed_32, 32)
    assert _run_control_flow_case("RV32I+GC", 32) == _run_control_flow_case(verbose_32, 32)

    assert _run_zifencei_case("RV32I+GC", 32) == _run_zifencei_case(explicit_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(mixed_32, 32)
    assert _run_zifencei_case("RV32I+GC", 32) == _run_zifencei_case(verbose_32, 32)

    assert _run_zicsr_case("RV32I+GC", 32) == _run_zicsr_case(explicit_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(mixed_32, 32)
    assert _run_zicsr_case("RV32I+GC", 32) == _run_zicsr_case(verbose_32, 32)

    assert _run_zicond_case("RV32I+GC", 32, funct3=0b000, rs2=0x15) == _run_zicond_case(explicit_32, 32, funct3=0b000, rs2=0x15)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x16) == _run_zicond_case(mixed_32, 32, funct3=0b001, rs2=0x16)
    assert _run_zicond_case("RV32I+GC", 32, funct3=0b011, rs2=0x17) == _run_zicond_case(verbose_32, 32, funct3=0b011, rs2=0x17)

    assert _run_jalr_case("RV64I+GC", 64) == _run_jalr_case(explicit_64, 64)
    assert _run_jalr_case("RV64I+GC+*", 64) == _run_jalr_case(mixed_64, 64)
    assert _run_jalr_case("RV64I+GC", 64) == _run_jalr_case(verbose_64, 64)

    assert _run_control_flow_case("RV64I+GC", 64) == _run_control_flow_case(explicit_64, 64)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(mixed_64, 64)
    assert _run_control_flow_case("RV64I+GC", 64) == _run_control_flow_case(verbose_64, 64)

    assert _run_zifencei_case("RV64I+GC", 64) == _run_zifencei_case(explicit_64, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(mixed_64, 64)
    assert _run_zifencei_case("RV64I+GC", 64) == _run_zifencei_case(verbose_64, 64)

    assert _run_zicsr_case("RV64I+GC", 64) == _run_zicsr_case(explicit_64, 64)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(mixed_64, 64)
    assert _run_zicsr_case("RV64I+GC", 64) == _run_zicsr_case(verbose_64, 64)

    assert _run_zicond_case("RV64I+GC", 64, funct3=0b010, rs2=0x21) == _run_zicond_case(explicit_64, 64, funct3=0b010, rs2=0x21)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b011, rs2=0x22) == _run_zicond_case(mixed_64, 64, funct3=0b011, rs2=0x22)
    assert _run_zicond_case("RV64I+GC", 64, funct3=0b001, rs2=0x23) == _run_zicond_case(verbose_64, 64, funct3=0b001, rs2=0x23)


def test_star_runtime_guarded_mix_for_control_system_and_atomic_alias_forms():
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + * + m + a + b + c + d + f + zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + ??? + "
    noisy_64 = "  rv64i + gc + * + m + a + b + c + d + f + zifencei + ZIFENCEI + zicsr + ZICSR + zicond + ZICOND + ??? + "
    reordered_32 = "RV32I + GC + ZICOND + ZIFENCEI + ZICSR + M + A + B + C + F + D"
    reordered_64 = "RV64I + GC + D + F + C + B + A + M + ZICOND + ZICSR + ZIFENCEI"

    # Baseline and star alias parsing should not change core control-flow + system behavior.
    assert _run_control_flow_case("RV32I+GC", 32) == _run_control_flow_case(full_32, 32)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(noisy_32, 32)
    assert _run_control_flow_case("RV32I+GC", 32) == _run_control_flow_case(reordered_32, 32)

    assert _run_control_flow_case("RV64I+GC", 64) == _run_control_flow_case(full_64, 64)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(noisy_64, 64)
    assert _run_control_flow_case("RV64I+GC", 64) == _run_control_flow_case(reordered_64, 64)

    # JALR and ZICSR paths should be parser-stable too.
    assert _run_jalr_case("RV32I+GC", 32) == _run_jalr_case(full_32, 32)
    assert _run_jalr_case("RV32I+GC+*", 32) == _run_jalr_case(noisy_32, 32)
    assert _run_jalr_case("RV32I+GC", 32) == _run_jalr_case(reordered_32, 32)

    assert _run_jalr_case("RV64I+GC", 64) == _run_jalr_case(full_64, 64)
    assert _run_jalr_case("RV64I+GC+*", 64) == _run_jalr_case(noisy_64, 64)
    assert _run_jalr_case("RV64I+GC", 64) == _run_jalr_case(reordered_64, 64)

    assert _run_zicsr_case("RV32I+GC", 32) == _run_zicsr_case(full_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV32I+GC", 32) == _run_zicsr_case(reordered_32, 32)

    assert _run_zicsr_case("RV64I+GC", 64) == _run_zicsr_case(full_64, 64)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)
    assert _run_zicsr_case("RV64I+GC", 64) == _run_zicsr_case(reordered_64, 64)

    # Fence and condition instructions should remain stable with equivalent parser forms.
    assert _run_zifencei_case("RV32I+GC", 32) == _run_zifencei_case(full_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV32I+GC", 32) == _run_zifencei_case(reordered_32, 32)

    assert _run_zifencei_case("RV64I+GC", 64) == _run_zifencei_case(full_64, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)
    assert _run_zifencei_case("RV64I+GC", 64) == _run_zifencei_case(reordered_64, 64)

    # Atomic and branch condition checks ensure RV32/RV64 consistency under star/noise/reorder.
    assert _run_amo_op_case("RV32I+GC", 32, amofn=0b00001, src_imm=5, init_mem=0x10) == \
        _run_amo_op_case(full_32, 32, amofn=0b00001, src_imm=5, init_mem=0x10)
    assert _run_amo_op_case("RV32I+GC+*", 32, amofn=0b00101, src_imm=0x20, init_mem=0x30) == \
        _run_amo_op_case(noisy_32, 32, amofn=0b00101, src_imm=0x20, init_mem=0x30)
    assert _run_amo_op_case("RV32I+GC", 32, amofn=0b00001, src_imm=3, init_mem=0x44) == \
        _run_amo_op_case(reordered_32, 32, amofn=0b00001, src_imm=3, init_mem=0x44)

    assert _run_amo_op_case("RV64I+GC", 64, amofn=0b00001, src_imm=0x10, init_mem=0xFF, funct3=0b011) == \
        _run_amo_op_case(full_64, 64, amofn=0b00001, src_imm=0x10, init_mem=0xFF, funct3=0b011)
    assert _run_amo_op_case("RV64I+GC+*", 64, amofn=0b00101, src_imm=0x20, init_mem=0xF0F0, funct3=0b011) == \
        _run_amo_op_case(noisy_64, 64, amofn=0b00101, src_imm=0x20, init_mem=0xF0F0, funct3=0b011)
    assert _run_amo_op_case("RV64I+GC", 64, amofn=0b01010, src_imm=0x33, init_mem=0xA5, funct3=0b011) == \
        _run_amo_op_case(reordered_64, 64, amofn=0b01010, src_imm=0x33, init_mem=0xA5, funct3=0b011)


def test_star_runtime_guarded_base_m_a_b_mix_for_rv32_and_rv64():
    explicit_32 = "RV32I+GC+M+A+B+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + * + m + a + b + zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND + ??? + "
    noisy_64 = "  rv64i + gc + * + m + a + b + zicsr + ZICSR + zifencei + ZIFENCEI + zicond + ZICOND + ??? + "
    reordered_32 = "RV32I + GC + ZICOND + ZIFENCEI + ZICSR + M + A + B"
    reordered_64 = "RV64I + GC + B + A + M + ZICOND + ZICSR + ZIFENCEI"

    assert _run_base_case("RV32I+GC", 32) == _run_base_case(explicit_32, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_base_case("RV32I+GC", 32) == _run_base_case(reordered_32, 32)
    assert _run_base_case("RV64I+GC", 64) == _run_base_case(explicit_64, 64)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(noisy_64, 64)
    assert _run_base_case("RV64I+GC", 64) == _run_base_case(reordered_64, 64)

    assert _run_m_case("RV32I+GC", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(explicit_32, 32)
    assert _run_m_case("RV32I+GC", 32) == _run_m_case(reordered_32, 32)

    assert _run_m_case("RV64I+GC", 64) == _run_m_case(noisy_64, 64)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(explicit_64, 64)
    assert _run_m_case("RV64I+GC", 64) == _run_m_case(reordered_64, 64)

    assert _run_b_case("RV32I+GC", 32, funct3=0b110) == _run_b_case(explicit_32, 32, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b111) == _run_b_case(noisy_32, 32, funct3=0b111)
    assert _run_b_case("RV64I+GC", 64, funct3=0b000) == _run_b_case(explicit_64, 64, funct3=0b000)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b001) == _run_b_case(reordered_64, 64, funct3=0b001)


def test_star_runtime_guarded_fp_and_system_paths_for_rv32():
    explicit = "RV32I+GC+M+A+B+F+D+ZICSR+ZIFENCEI+ZICOND"
    starred = "RV32I+GC+*"
    noisy = "  rv32i + gc + * + m + a + b + f + d + zicond + zifencei + ZIFENCEI + zicsr + ZICSR + ??? + "
    reordered = "RV32I + GC + ZICOND + ZIFENCEI + ZICSR + M + A + B + F + D"

    assert _run_fp32_case("RV32I+GC", 32) == _run_fp32_case(explicit, 32)
    assert _run_fp32_case(starred, 32) == _run_fp32_case(noisy, 32)
    assert _run_fp32_case("RV32I+GC", 32) == _run_fp32_case(reordered, 32)

    assert _run_fp_case(explicit, 32) == _run_fp_case(starred, 32)
    assert _run_fp_case(explicit, 32) == _run_fp_case(noisy, 32)

    assert _run_d_case(explicit, 32) == _run_d_case(starred, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy, 32)

    assert _run_fp_width_case("RV32I+GC", 32) == _run_fp_width_case(explicit, 32)
    assert _run_fp_width_case("RV32I+GC+*", 32) == _run_fp_width_case(noisy, 32)

    assert _run_fp_store_width_case("RV32I+GC", 32) == _run_fp_store_width_case(reordered, 32)
    assert _run_fp_store_width_case("RV32I+GC+*", 32) == _run_fp_store_width_case(explicit, 32)

    assert _run_zicsr_star_case(starred, 32) == _run_zicsr_star_case(noisy, 32)
    assert _run_zifencei_case("RV32I+GC", 32) == _run_zifencei_case(noisy, 32)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(reordered, 32)


def test_star_runtime_guarded_fp_and_system_paths_for_rv64():
    explicit = "RV64I+GC+M+A+B+F+D+ZICSR+ZIFENCEI+ZICOND"
    starred = "RV64I+GC+*"
    noisy = "  rv64i + gc + * + m + a + b + f + d + zicond + zifencei + ZIFENCEI + zicsr + ZICSR + ??? + "
    reordered = "RV64I + GC + ZICOND + ZIFENCEI + ZICSR + M + A + B + F + D"

    assert _run_fp_case(starred, 64) == _run_fp_case(noisy, 64)
    assert _run_fp_case(explicit, 64) == _run_fp_case(reordered, 64)
    assert _run_fp_case(explicit, 64) == _run_fp_case(starred, 64)

    assert _run_d_case(explicit, 64) == _run_d_case(starred, 64)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy, 64)

    assert _run_fp_width_case("RV64I+GC", 64) == _run_fp_width_case(starred, 64)
    assert _run_fp_width_case(starred, 64) == _run_fp_width_case(noisy, 64)

    assert _run_fp_store_width_case("RV64I+GC", 64) == _run_fp_store_width_case(starred, 64)
    assert _run_fp_store_width_case(starred, 64) == _run_fp_store_width_case(noisy, 64)

    assert _run_zicsr_star_case(starred, 64) == _run_zicsr_star_case(noisy, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy, 64)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(reordered, 64)


def test_star_runtime_guarded_parser_noise_for_rv64():
    explicit = "RV64I+GC+M+A+B+F+D+ZICSR+ZIFENCEI+ZICOND"
    starred = "RV64I+GC+*"
    noisy = "  rv64i + gc + * + ??? + m + A + B + F + D + zifencei + ZICOND + zicsr + "

    assert _run_fp_case(starred, 64) == _run_fp_case(noisy, 64)
    assert _run_fp_case(explicit, 64) == _run_fp_case("  rv64I + GC + zicond + zifencei + zicsr + m + a + b + f + d ", 64)

    assert _run_d_case(explicit, 64) == _run_d_case(noisy, 64)
    assert _run_d_case(starred, 64) == _run_d_case("RV64I + GC + M + A + B + F + D + ZICSR + ZICOND + ZIFENCEI", 64)

    assert _run_zicsr_star_case(starred, 64) == _run_zicsr_star_case(noisy, 64)
    assert _run_zifencei_case("RV64I+GC", 64) == _run_zifencei_case(noisy, 64)
    assert _run_control_flow_case(starred, 64) == _run_control_flow_case("RV64I + GC + ZICOND + ZIFENCEI + ZICSR + M + A + B + F + D", 64)
    assert _run_fp_width_case(starred, 64) == _run_fp_width_case(noisy, 64)
    assert _run_fp_store_width_case("RV64I+GC", 64) == _run_fp_store_width_case(noisy, 64)


def test_star_runtime_guarded_fp32_case_for_rv64():
    explicit = "RV64I+GC+M+A+B+F+D+ZICSR+ZIFENCEI+ZICOND"
    starred = "RV64I+GC+*"
    noisy = " rv64i + gc + * + m + a + b + f + d + ZICSR + zicsr + zifencei + zicond "
    reordered = "RV64I + GC + ZICOND + ZIFENCEI + ZICSR + M + A + B + F + D"

    assert _run_fp32_case(starred, 64) == _run_fp32_case(noisy, 64)
    assert _run_fp32_case(explicit, 64) == _run_fp32_case(reordered, 64)
    assert _run_fp32_case(explicit, 64) == _run_fp32_case("RV64I+GC+F", 64)


def test_star_runtime_guarded_m_word_and_branch_paths_for_rv64():
    explicit = "RV64I+GC+M+A+B+F+D+ZICSR+ZIFENCEI+ZICOND"
    starred = "RV64I+GC+*"
    noisy = "  rv64i + gc + * + m + a + b + d + zicond + ZIFENCEI + zicsr + "
    reordered = "RV64I + GC + ZICOND + ZIFENCEI + ZICSR + M + A + B + F + D"

    assert _run_m_case(starred, 64) == _run_m_case(explicit, 64)
    assert _run_m_case(starred, 64) == _run_m_case(noisy, 64)
    assert _run_m_case("RV64I+GC+M", 64) == _run_m_case(reordered, 64)

    assert _run_mw_case("RV64I+GC+M", 64) == _run_mw_case(starred, 64)
    assert _run_mw_case("RV64I+GC+*", 64) == _run_mw_case(noisy, 64)
    assert _run_mw_edge_case("RV64I+GC+M", 64) == _run_mw_edge_case(starred, 64)

    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(explicit, 64, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b111) == _run_b_case(noisy, 64, funct3=0b111)


def test_star_runtime_guarded_control_aliases_for_rv32():
    explicit = "RV32I+GC+M+A+B+F+D+ZICSR+ZIFENCEI+ZICOND"
    starred = "RV32I+GC+*"
    noisy = "  rv32i + gc + * + m + a + b + f + d + zicond + ZIFENCEI + zicsr + ZICSR + ??? + "
    reordered = "RV32I + GC + ZICOND + ZIFENCEI + ZICSR + M + A + B + F + D"

    assert _run_control_flow_case(starred, 32) == _run_control_flow_case(noisy, 32)
    assert _run_control_flow_case(explicit, 32) == _run_control_flow_case(reordered, 32)

    assert _run_b_case(starred, 32, funct3=0b110) == _run_b_case(explicit, 32, funct3=0b110)
    assert _run_b_case(starred, 32, funct3=0b111) == _run_b_case(noisy, 32, funct3=0b111)

    assert _run_zifencei_case(starred, 32) == _run_zifencei_case(noisy, 32)
    assert _run_zicsr_star_case(starred, 32) == _run_zicsr_star_case(explicit, 32)


def test_star_runtime_guarded_control_aliases_for_rv64():
    explicit = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    starred = "RV64I+GC+*"
    noisy = " rv64i + gc + * + m + a + b + c + f + d + zicond + ZIFENCEI + zicsr + ??? + "
    reordered = "RV64I + GC + ZICSR + ZIFENCEI + ZICOND + M + A + B + C + F + D"

    assert _run_control_flow_case(starred, 64) == _run_control_flow_case(noisy, 64)
    assert _run_control_flow_case(starred, 64) == _run_control_flow_case(reordered, 64)
    assert _run_control_flow_case(explicit, 64) == _run_control_flow_case("RV64I + GC + M + A + B + C + F + D + ZICSR + ZICOND + ZIFENCEI", 64)

    assert _run_jalr_case(starred, 64) == _run_jalr_case(explicit, 64)
    assert _run_jalr_case(starred, 64) == _run_jalr_case(noisy, 64)
    assert _run_jalr_case(starred, 64) == _run_jalr_case(reordered, 64)

    assert _run_b_case(starred, 64, funct3=0b000) == _run_b_case(explicit, 64, funct3=0b000)
    assert _run_b_case(starred, 64, funct3=0b001) == _run_b_case(noisy, 64, funct3=0b001)
    assert _run_b_case(starred, 64, funct3=0b101) == _run_b_case(reordered, 64, funct3=0b101)

    assert _run_zifencei_case(starred, 64) == _run_zifencei_case(noisy, 64)
    assert _run_zifencei_case(starred, 64) == _run_zifencei_case(explicit, 64)
    assert _run_zicsr_star_case(starred, 64) == _run_zicsr_star_case(explicit, 64)
    assert _run_zicsr_star_case(starred, 64) == _run_zicsr_star_case(noisy, 64)


def test_star_runtime_guarded_u_type_and_sys_paths_for_rv64():
    explicit = "RV64I+GC+M+A+B+F+D+ZICSR+ZIFENCEI+ZICOND"
    starred = "RV64I+GC+*"
    noisy = " rv64i + gc + * + m + a + b + f + d + zicsr + zifencei + zicond + ??? + "
    reordered = "RV64I + GC + ZICOND + ZIFENCEI + ZICSR + M + A + B + F + D"

    assert _run_u_type_case(starred, 64) == _run_u_type_case(explicit, 64)
    assert _run_u_type_case(starred, 64) == _run_u_type_case(noisy, 64)
    assert _run_u_type_case(starred, 64) == _run_u_type_case(reordered, 64)

    assert _run_control_flow_case(starred, 64) == _run_control_flow_case(explicit, 64)
    assert _run_jalr_case(starred, 64) == _run_jalr_case(explicit, 64)
    assert _run_jalr_case(starred, 64) == _run_jalr_case(noisy, 64)
    assert _run_jalr_case(starred, 64) == _run_jalr_case(reordered, 64)

    assert _run_zifencei_case(starred, 64) == _run_zifencei_case(explicit, 64)
    assert _run_zifencei_case(starred, 64) == _run_zifencei_case(noisy, 64)
    assert _run_zicsr_star_case(starred, 64) == _run_zicsr_star_case(explicit, 64)


def test_star_runtime_guarded_u_type_and_control_system_paths_for_rv32():
    explicit = "RV32I+GC+M+A+B+F+D+ZICSR+ZIFENCEI+ZICOND"
    starred = "RV32I+GC+*"
    noisy = " rv32i + gc + * + m + a + b + f + d + zicsr + zifencei + zicond + ??? + "
    reordered = "RV32I + GC + ZICOND + ZIFENCEI + ZICSR + M + A + B + F + D"

    assert _run_u_type_case(starred, 32) == _run_u_type_case(explicit, 32)
    assert _run_u_type_case(starred, 32) == _run_u_type_case(noisy, 32)
    assert _run_u_type_case(starred, 32) == _run_u_type_case(reordered, 32)

    assert _run_control_flow_case(starred, 32) == _run_control_flow_case(explicit, 32)
    assert _run_control_flow_case(starred, 32) == _run_control_flow_case(noisy, 32)
    assert _run_control_flow_case(starred, 32) == _run_control_flow_case(reordered, 32)

    assert _run_jalr_case(starred, 32) == _run_jalr_case(explicit, 32)
    assert _run_jalr_case(starred, 32) == _run_jalr_case(noisy, 32)
    assert _run_jalr_case(starred, 32) == _run_jalr_case(reordered, 32)

    assert _run_zifencei_case(starred, 32) == _run_zifencei_case(explicit, 32)
    assert _run_zifencei_case(starred, 32) == _run_zifencei_case(noisy, 32)
    assert _run_zicsr_star_case(starred, 32) == _run_zicsr_star_case(explicit, 32)
    assert _run_zicsr_star_case(starred, 32) == _run_zicsr_star_case(noisy, 32)


def test_star_runtime_star_iterable_parser_invariance_for_rv32_and_rv64():
    """Iterator-based extension specs should behave like canonical star specs."""
    explicit_iterable_32 = [
        "rv32i",
        "gc",
        "m",
        "a",
        "b",
        "c",
        "f",
        "d",
        "ZICOND",
        "ZICSR",
        "ZIFENCEI",
        "???",
        "unknown.token",
    ]
    explicit_iterable_64 = [
        "rv64i",
        "gc",
        "m",
        "a",
        "b",
        "c",
        "f",
        "d",
        "zicond",
        "zicsr",
        "zifencei",
        "",
        None,
    ]

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(explicit_iterable_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(explicit_iterable_64, 64)

    reordered_32 = [
        "  rv32i + gc + * + ",
        "?",
        "zifencei",
        "zicsr",
        "zicond",
        "f",
        "d",
        "c",
        "b",
        "a",
        "m",
    ]
    reordered_64 = [
        "zifencei",
        "zicsr",
        "zicond",
        "f",
        "d",
        "c",
        "b",
        "a",
        "m",
        "rv64i + gc + *",
    ]

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(reordered_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(reordered_64, 64)

def test_star_runtime_star_iterable_parser_normalization_for_repeated_tokens_and_whitespace_rv32_rv64():
    """Iterable extension specs with duplicated and whitespace-padded tokens should be normalized."""
    dup_like_32 = tuple(
        ["rv32i", " rv32i ", "GC", "gc", "*", "m", "m", " a ", "A", "b", "c", "f", "d", "zicsr", "ZICSR", "zifencei", "  ", "zifencei"]
    )
    dup_like_64 = tuple(
        ["rv64i", " RV64I ", "gc", "gC", "*", "M", "m", " a ", "A", "b", "c", "f", "d", "zicond", "ZICOND", "zicond", "zifencei", "zicsr", "   "]
    )

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICOND+ZICSR+ZIFENCEI"

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(dup_like_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(dup_like_64, 64)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(explicit_64, 64)

def test_star_runtime_star_iterable_generator_paths_for_rv32_and_rv64():
    """Generator-based extension inputs should normalize to canonical star runtime profiles."""

    def _gen_32():
        for token in [
            "", " \t", "rv32i", "GC", "*", "m", "a", "a", " b ", "C", "f", "d", "zicond", "ZICOND", "zicsr", "ZIFENCEI", None, "unknown.ext",
        ]:
            yield token

    def _gen_64():
        for token in (
            "RV64I", "gc", "*", "M", "m", "a", "b", "B", "c", "f", "d", "zicond", "ZICSR", "ZICSR", "zifencei", "  ", "???"
        ):
            yield token

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(_gen_32(), 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(_gen_64(), 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(["rv32i", "gc", "*", "m", "a", "b", "c", "f", "d", "ZIFENCEI", "ZICSR", "ZICOND"], 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(("RV64I", "GC", "*", "M", "A", "B", "C", "D", "F", "ZICOND", "ZICSR", "ZIFENCEI"), 64)

def test_star_runtime_star_alias_equivalence_for_mixed_explicit_paths_rv32_rv64():
    """Mixed explicit + star aliases with punctuation noise should normalize to canonical profile."""

    starred_32 = "RV32I+GC+*"
    starred_64 = "RV64I+GC+*"
    noisy_32 = [
        "  rv32i ",
        "+",
        "gc",
        "gC",
        "*",
        ",",
        "m",
        "a",
        "b",
        "c",
        "f",
        "d",
        "zicond",
        "zifencei",
        "zicsr",
        "",
        "???",
    ]
    noisy_64 = [
        "RV64I",
        "gc",
        "*",
        "m",
        "a",
        "b",
        "c",
        "f",
        "d",
        "zicond",
        "zifencei",
        "zicsr",
        " ",
        None,
        "???",
    ]
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICOND+ZIFENCEI+ZICSR"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICOND+ZIFENCEI+ZICSR"

    assert _run_extension_combo_case(starred_32, 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case(starred_64, 64) == _run_extension_combo_case(noisy_64, 64)
    assert _run_extension_combo_case(starred_32, 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case(starred_64, 64) == _run_extension_combo_case(explicit_64, 64)

def test_star_runtime_star_iterable_mixed_type_tokens_for_rv32_and_rv64():
    """Iterable extension tokens can include unexpected non-string entries and still normalize consistently."""

    assert _run_extension_combo_case(
        "RV32I+GC+*",
        32,
    ) == _run_extension_combo_case(
        [
            " rv32i ",
            "GC",
            "*",
            None,
            7,
            "m",
            "a",
            "b",
            "c",
            "f",
            "d",
            "zicond",
            "zicsr",
            "zifencei",
        ],
        32,
    )

    assert _run_extension_combo_case(
        "RV64I+GC+*",
        64,
    ) == _run_extension_combo_case(
        (
            "RV64I",
            " gc ",
            "*",
            0,
            "m",
            "a",
            "b",
            "c",
            "f",
            "d",
            "zicond",
            "zicsr",
            "zifencei",
            "",
        ),
        64,
    )

def test_star_runtime_star_case_vs_explicit_control_system_atomic_rv32():
    """RV32I+GC baseline should equal explicit standard extensions used by this mix."""
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(
        "RV32I+GC+M+A+ZICSR+ZIFENCEI+ZICOND",
        32,
    )


def test_star_runtime_star_case_vs_explicit_control_system_atomic_rv64():
    """RV64I+GC baseline should equal explicit standard extensions used by this mix."""
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(
        "RV64I+GC+M+A+ZICSR+ZIFENCEI+ZICOND",
        64,
    )

def test_star_runtime_star_crossset_control_system_atomic_paths_rv32():
    """Cross-check RV32I+GC case-insensitive iterable parsing for control/system/atomic sequence."""
    assert _run_extension_combo_case(
        ["rv32i", " gc ", "*", "m", "A", "zicond", "zifencei", "zicsr"],
        32,
    ) == _run_extension_combo_case("RV32I+GC+M+A+ZICSR+ZIFENCEI+ZICOND", 32)

def test_star_runtime_star_crossset_control_system_atomic_paths_rv64():
    """Cross-check RV64I+GC case-insensitive iterable parsing for control/system/atomic sequence."""
    assert _run_extension_combo_case(
        ["RV64I", "GC", "*", "M", "a", "ZICOND", "ZIFENCEI", "ZICSR"],
        64,
    ) == _run_extension_combo_case("RV64I+GC+M+A+ZICSR+ZIFENCEI+ZICOND", 64)


def test_star_runtime_star_noisy_equivalent_iterables_rv32_and_rv64():
    """Noisy equivalent token streams should normalize to the same executable profile."""
    noisy_32_a = (
        " ",
        "rv32i",
        None,
        "gc",
        "m",
        "a",
        "B",
        "c",
        "f",
        "d",
        "zicond",
        "zifencei",
        "zicsr",
        "*",
    )
    noisy_32_b = (
        "  RV32I  ",
        "*",
        "GC",
        "m",
        "ZICOND",
        "zifencei",
        "zicsr",
        "a",
        "C",
        "d",
        "f",
        "b",
        None,
    )

    assert _run_extension_combo_case(noisy_32_a, 32) == _run_extension_combo_case(noisy_32_b, 32)

    noisy_64_a = [
        "RV64I",
        "gc",
        "*",
        "m",
        "A",
        "b",
        "c",
        "f",
        "d",
        "zifencei",
        "zicsr",
        "zicond",
        42,
        "",
    ]
    noisy_64_b = [
        "   rv64i ",
        "*",
        "GC",
        "a",
        "b",
        "c",
        "d",
        "f",
        "zifencei",
        "zicsr",
        "zicond",
        None,
        "m",
    ]

    assert _run_extension_combo_case(noisy_64_a, 64) == _run_extension_combo_case(noisy_64_b, 64)


def test_star_runtime_star_parser_robustness_across_rv32_and_rv64_noisy_paths():
    """Parser should ignore delimiter/noise while preserving semantic equivalence."""
    noise_32 = [
        "\t",
        "RV32I",
        "+",
        ",",
        "gc",
        "*",
        "m",
        "a",
        "b",
        "c",
        "f",
        "d",
        "zicond",
        "zifencei",
        "zicsr",
        "",
        "   ",
        None,
        "???",
    ]
    noise_32_alt = [
        "rv32i",
        "gc",
        "*",
        "a",
        "m",
        "B",
        "C",
        "D",
        "F",
        "ZICSR",
        "zifencei",
        "ZICOND",
        0,
        "-",
    ]

    assert _run_extension_combo_case(noise_32, 32) == _run_extension_combo_case(noise_32_alt, 32)

    noise_64 = [
        "rv64i",
        "gc",
        "*",
        "M",
        "A",
        "B",
        "C",
        "D",
        "F",
        "zifencei",
        "zicsr",
        "zicond",
        ",",
        " ",
        None,
    ]
    noise_64_alt = (
        "RV64I",
        " GC ",
        "*",
        "m",
        "a",
        "b",
        "c",
        "f",
        "d",
        "ZICOND",
        "ZIFENCEI",
        "ZICSR",
        "???",
    )

    assert _run_extension_combo_case(noise_64, 64) == _run_extension_combo_case(noise_64_alt, 64)


def test_star_runtime_star_set_and_tuple_path_equivalence_rv32_rv64():
    """Set/tuple extension paths should still resolve to the same executable profile."""
    set_like_32 = {
        "rv32i",
        "gc",
        "*",
        "m",
        "a",
        "b",
        "c",
        "d",
        "f",
        "zicond",
        "zifencei",
        "zicsr",
        None,
        "",
        "???",
    }
    tuple_like_32 = (
        "RV32I",
        "GC",
        "*",
        "A",
        "B",
        "C",
        "D",
        "F",
        "M",
        "ZICOND",
        "ZICSR",
        "ZIFENCEI",
        99,
        " ",
    )

    assert _run_extension_combo_case(set_like_32, 32) == _run_extension_combo_case(tuple_like_32, 32)

    set_like_64 = {
        "rv64i",
        "gc",
        "*",
        "m",
        "a",
        "b",
        "c",
        "d",
        "f",
        "zicond",
        "zifencei",
        "zicsr",
        None,
        "???",
    }
    tuple_like_64 = (
        "RV64I",
        " gc ",
        "*",
        "M",
        "A",
        "B",
        "C",
        "D",
        "F",
        "ZICOND",
        "ZICSR",
        "ZIFENCEI",
        12,
        " ",
    )

    assert _run_extension_combo_case(set_like_64, 64) == _run_extension_combo_case(tuple_like_64, 64)


def test_star_runtime_star_explicit_and_structured_repetition_paths_rv32_rv64():
    """Explicit and structured repeated/ noisy forms should converge to the same profile."""
    explicit_32 = "RV32I+GC+M+A+ZICSR+ZIFENCEI+ZICOND"
    structured_32 = [
        "rv32i",
        "gc",
        "gc",
        "*",
        "m",
        "a",
        "A",
        "zicond",
        "zicond",
        "zifencei",
        "zicsr",
        None,
        ",",
        "",
    ]

    assert _run_extension_combo_case(explicit_32, 32) == _run_extension_combo_case(structured_32, 32)

    explicit_64 = "RV64I+GC+M+A+ZICSR+ZIFENCEI+ZICOND"
    structured_64 = (
        " RV64I ",
        "GC",
        "*",
        "m",
        "m",
        "a",
        "b",
        "c",
        "d",
        "f",
        "zicond",
        "zifencei",
        "zicsr",
        "???",
    )

    assert _run_extension_combo_case(explicit_64, 64) == _run_extension_combo_case(structured_64, 64)


def test_star_runtime_star_intersection_of_noisy_collections_rv32_rv64():
    """Intersected noisy collections should still normalize to the same active profile."""
    noisy_a_32 = {
        "rv32i",
        "gc",
        "*",
        "m",
        "A",
        "b",
        "c",
        "f",
        "d",
        "zicond",
        "zifencei",
    }
    noisy_b_32 = [
        "RV32I",
        "GC",
        "m",
        "a",
        "B",
        "C",
        "D",
        "F",
        "zicsr",
        "ZICSR",
        " zifencei ",
        100,
        "   ",
    ]

    assert _run_extension_combo_case(noisy_a_32, 32) == _run_extension_combo_case(noisy_b_32, 32)

    noisy_a_64 = {
        "rv64i",
        "gc",
        "*",
        "m",
        "A",
        "b",
        "c",
        "f",
        "d",
        "zicond",
        "zicsr",
        "zifencei",
    }
    noisy_b_64 = [
        " RV64I ",
        "GC",
        "*",
        "m",
        "a",
        "B",
        "C",
        "D",
        "F",
        "zicsr",
        "zifencei",
        "ZICOND",
        None,
        "???",
    ]

    assert _run_extension_combo_case(noisy_a_64, 64) == _run_extension_combo_case(noisy_b_64, 64)


def test_star_runtime_star_control_flow_equivalence_rv32_and_rv64():
    """Control-flow behavior should be identical between base and star profiles for RV32I/RV64I."""
    base_32 = "RV32I+GC"
    star_32 = "RV32I+GC+*"
    assert _run_control_flow_case(base_32, 32) == _run_control_flow_case(star_32, 32)

    base_64 = "RV64I+GC"
    star_64 = "RV64I+GC+*"
    assert _run_control_flow_case(base_64, 64) == _run_control_flow_case(star_64, 64)


def test_star_extension_standard_addons_do_not_change_control_path_semantics():
    """Adding explicit standard addons should not alter control-flow behavior under star mode."""
    full_32 = "RV32I+GC+M+A+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+ZICSR+ZIFENCEI+ZICOND"

    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(full_32, 32)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(full_64, 64)


def test_star_runtime_uses_full_standard_system_and_atomic_path_set_on_rv32_and_rv64():
    """Multi-extension mix execution should remain identical with explicit standard bundle or star."""
    full_32 = "RV32I+GC+M+A+ZICSR+ZICOND+ZIFENCEI"
    full_64 = "RV64I+GC+M+A+ZICSR+ZICOND+ZIFENCEI"

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(full_64, 64)


def test_star_runtime_parser_noise_noops_and_redundancy_do_not_change_full_set_on_rv32_and_rv64():
    """Noisy or redundant star inputs should normalize to the same full-standard execution profile."""
    noisy_32 = [
        " rv32i ",
        "gc",
        "*",
        "m",
        "m",
        "a",
        "a",
        "zifencei",
        "ZIFENCEI",
        "zicsr",
        "zicond",
        "????",
        "",
        None,
    ]
    noisy_64 = (
        " RV64I ",
        "gc",
        "*",
        "M",
        "a",
        "A",
        "ZICSR",
        "zifencei",
        "zicond",
        "zicond",
        123,
    )

    full_32 = "RV32I+GC+M+A+ZICSR+ZICOND+ZIFENCEI"
    full_64 = "RV64I+GC+M+A+ZICSR+ZICOND+ZIFENCEI"

    assert _run_multi_extension_mix_case(noisy_32, 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case(noisy_64, 64) == _run_multi_extension_mix_case(full_64, 64)


def test_star_runtime_explicit_and_star_full_set_execute_identically_for_system_atomic_and_control_mix_rv32_rv64():
    """Star profile and explicit full standard profile must stay execution-identical on RV32/RV64."""
    explicit_32 = "RV32I+GC+M+A+ZICSR+ZICOND+ZIFENCEI"
    explicit_64 = "RV64I+GC+M+A+ZICSR+ZICOND+ZIFENCEI"

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(explicit_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(explicit_64, 64)


def test_star_and_explicit_full_set_noisy_parser_inputs_equivalent_with_redundancy_rv32_and_rv64():
    """Redundant/noisy tokenization of full standard set should not change runtime semantics."""
    noisy_32 = [
        "rv32i",
        " gc ",
        "*",
        "M",
        "A",
        "b",
        "B",
        "c",
        "d",
        "f",
        "ZICSR",
        "zifencei",
        "zicond",
        "",
        None,
        "m",
    ]
    noisy_64 = (
        " RV64I ",
        "gc",
        "*",
        "A",
        "a",
        "M",
        "ZICOND",
        "zicond",
        "zifencei",
        "ZICSR",
        "",
        "???",
    )

    full_32 = "RV32I+GC+M+A+ZICSR+ZICOND+ZIFENCEI"
    full_64 = "RV64I+GC+M+A+ZICSR+ZICOND+ZIFENCEI"

    assert _run_multi_extension_mix_case(noisy_32, 32) == _run_multi_extension_mix_case(full_32, 32)
    assert _run_multi_extension_mix_case(noisy_64, 64) == _run_multi_extension_mix_case(full_64, 64)


def test_star_fullset_iterable_and_string_variants_preserve_mix_results_rv32_and_rv64():
    """Iterable/noisy parser forms and canonical star form should execute the same mix program."""
    noisy_32 = [
        "RV32I",
        "gc",
        "*",
        "m",
        "a",
        "b",
        "c",
        "d",
        "f",
        "zicond",
        "zicsr",
        "zifencei",
        "",
        None,
    ]
    noisy_64 = (
        " RV64I ",
        "gc",
        "*",
        "m",
        "a",
        "b",
        "c",
        "d",
        "f",
        "zicond",
        "zicsr",
        "zifencei",
        "  ",
        "???",
    )

    assert _run_multi_extension_mix_case(noisy_32, 32) == _run_multi_extension_mix_case(
        "RV32I+GC+M+A+ZICSR+ZICOND+ZIFENCEI",
        32,
    )
    assert _run_multi_extension_mix_case(noisy_64, 64) == _run_multi_extension_mix_case(
        "RV64I+GC+M+A+ZICSR+ZICOND+ZIFENCEI",
        64,
    )


def test_star_fullset_unknown_or_empty_tokens_remain_noop_for_control_and_mix_paths_rv32_rv64():
    """Unknown/empty parser tokens must be treated as no-op and preserve star full-set semantics."""
    explicit_32 = "RV32I+GC+M+A+ZICSR+ZICOND+ZIFENCEI"
    explicit_64 = "RV64I+GC+M+A+ZICSR+ZICOND+ZIFENCEI"

    noisy_32 = {
        "RV32I",
        "GC",
        "*",
        "m",
        "a",
        "zicsr",
        "zifencei",
        "zicond",
        "",
        None,
        "???",
    }
    noisy_64 = [
        " RV64I ",
        "gc",
        "*",
        "m",
        "A",
        "zicond",
        "zifencei",
        "zicsr",
        "",
        0,
        "\t\t",
    ]

    assert _run_control_flow_case(noisy_32, 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case(noisy_64, 64) == _run_control_flow_case(explicit_64, 64)
    assert _run_multi_extension_mix_case(noisy_32, 32) == _run_multi_extension_mix_case(explicit_32, 32)
    assert _run_multi_extension_mix_case(noisy_64, 64) == _run_multi_extension_mix_case(explicit_64, 64)


def test_star_noisy_extension_combo_remains_equivalent_to_explicit_full_set_rv32_rv64():
    """Noisy extension-combo specs should keep RV32I/RV64I parity with explicit standard profiles."""
    noisy_32 = [
        " RV32I ",
        "gc",
        "*",
        "M",
        "A",
        "a",
        "m",
        "zicond",
        "ZICSR",
        "zifencei",
        "",
        None,
        "x",
    ]
    noisy_64 = (
        "RV64I",
        " gc ",
        "*",
        "m",
        "a",
        "ZICOND",
        "zicsr",
        "zifencei",
        "",
        "??",
    )

    explicit_32 = "RV32I+GC+M+A+ZICSR+ZICOND+ZIFENCEI"
    explicit_64 = "RV64I+GC+M+A+ZICSR+ZICOND+ZIFENCEI"

    assert _run_extension_combo_case(noisy_32, 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case(noisy_64, 64) == _run_extension_combo_case(explicit_64, 64)


def test_star_fullset_noisy_control_system_mix_parity_for_explicit_star_variants_rv32_rv64():
    """Noisy star-like specifications should remain parity-equivalent on mixed control/system cases."""
    noisy_32 = (
        "RV32I",
        "GC",
        "*",
        "m",
        "a",
        "ZIFENCEI",
        "zifencei",
        "zicond",
        "ZICSR",
        "",
        "bad-token",
        None,
    )
    noisy_64 = [
        " RV64I ",
        "gc",
        "*",
        "M",
        "A",
        "zicond",
        "zicsr",
        "zifencei",
        "",
        0,
    ]

    explicit_32 = "RV32I+GC+M+A+ZICSR+ZICOND+ZIFENCEI"
    explicit_64 = "RV64I+GC+M+A+ZICSR+ZICOND+ZIFENCEI"

    assert _run_control_flow_case(noisy_32, 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case(noisy_64, 64) == _run_control_flow_case(explicit_64, 64)
    assert _run_multi_extension_mix_case(noisy_32, 32) == _run_multi_extension_mix_case(explicit_32, 32)
    assert _run_multi_extension_mix_case(noisy_64, 64) == _run_multi_extension_mix_case(explicit_64, 64)


def test_star_noisy_iterable_fullset_system_parity_for_control_and_system_rv32_rv64():
    """Iterable noisy extension specs should keep system/control outcomes stable versus explicit star-full-set."""
    noisy_32 = [
        "rv32i",
        "GC",
        "*",
        "m",
        "M",
        "a",
        "A",
        "b",
        "B",
        "zba",
        "ZBK",
        "zifencei",
        "ZIFENCEI",
        "zicond",
        "ZICOND",
        "zicsr",
        "ZICSR",
        "unknown-token",
        "",
    ]
    noisy_64 = (
        "RV64I",
        " gc ",
        "*",
        "M",
        "m",
        "A",
        "a",
        "f",
        "F",
        "zifencei",
        "zifencei",
        "zicsr",
        "ZICSR",
        "zicond",
        "",
        None,
    )

    explicit_32 = "RV32I+GC+M+A+ZICSR+ZICOND+ZIFENCEI"
    explicit_64 = "RV64I+GC+M+A+ZICSR+ZICOND+ZIFENCEI"

    assert _run_control_flow_case(noisy_32, 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case(noisy_64, 64) == _run_control_flow_case(explicit_64, 64)
    assert _run_zifencei_case(noisy_32, 32) == _run_zifencei_case(explicit_32, 32)
    assert _run_zifencei_case(noisy_64, 64) == _run_zifencei_case(explicit_64, 64)
    assert _run_zicsr_case(noisy_32, 32) == _run_zicsr_case(explicit_32, 32)
    assert _run_zicsr_case(noisy_64, 64) == _run_zicsr_case(explicit_64, 64)
    assert _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0) == _run_zicond_case(explicit_32, 32, funct3=0b001, rs2=0)
    assert _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0) == _run_zicond_case(explicit_64, 64, funct3=0b001, rs2=0)


def test_star_noisy_iterable_full_standard_set_parity_for_rv32_rv64_runtime_pack():
    """Noisy iterable specs should keep full-standard runtime results stable versus explicit full-set specs."""
    noisy_32 = [
        "rv32i",
        " gc ",
        "*",
        "M",
        "a",
        "b",
        "C",
        "f",
        "D",
        "zifencei",
        "ZIFENCEI",
        "zicsr",
        "ZICSR",
        "zicond",
        "ZICOND",
        "unknown",
        "",
    ]
    noisy_64 = [
        " RV64I ",
        "GC",
        "*",
        "m",
        "A",
        "B",
        "c",
        "F",
        "d",
        "ZIFENCEI",
        "zifencei",
        "ZICSR",
        "zicsr",
        "ZICOND",
        "zicond",
        None,
    ]

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZIFENCEI+ZICSR+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZIFENCEI+ZICSR+ZICOND"

    assert _run_base_case(noisy_32, 32) == _run_base_case(explicit_32, 32)
    assert _run_base_case(noisy_64, 64) == _run_base_case(explicit_64, 64)
    assert _run_fp_case(noisy_32, 32) == _run_fp_case(explicit_32, 32)
    assert _run_fp_case(noisy_64, 64) == _run_fp_case(explicit_64, 64)
    assert _run_d_case(noisy_32, 32) == _run_d_case(explicit_32, 32)
    assert _run_d_case(noisy_64, 64) == _run_d_case(explicit_64, 64)
    assert _run_multi_extension_mix_case(noisy_32, 32) == _run_multi_extension_mix_case(explicit_32, 32)
    assert _run_multi_extension_mix_case(noisy_64, 64) == _run_multi_extension_mix_case(explicit_64, 64)
    assert _run_control_flow_case(noisy_32, 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case(noisy_64, 64) == _run_control_flow_case(explicit_64, 64)
    assert _run_extension_combo_case(noisy_32, 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case(noisy_64, 64) == _run_extension_combo_case(explicit_64, 64)


def test_star_noisy_iterable_full_star_parity_for_b_alias_bundle_rv32_rv64():
    """Noisy iterable star specs with B aliases should remain parity-equivalent to explicit B-fullset."""
    noisy_32 = [
        "rv32i",
        " GC ",
        "*",
        "m",
        "a",
        "ZBA",
        "zbb",
        "ZBH",
        "zbk",
        "ZBKB",
        "zbs",
        "ZBE",
        "zbf",
        "zbm",
        "zicond",
        "zifencei",
        "ZICSR",
        "  ",
    ]
    noisy_64 = [
        "RV64I",
        "GC",
        "*",
        "A",
        "M",
        "zba",
        "zbb",
        "zbh",
        "ZBK",
        "zbkb",
        "zbs",
        "zbe",
        "zbf",
        "ZBM",
        "ZICSR",
        "zifencei",
        "ZICOND",
        None,
    ]

    explicit_32 = "RV32I+GC+M+A+B+ZICOND+ZIFENCEI+ZICSR"
    explicit_64 = "RV64I+GC+M+A+B+ZICOND+ZIFENCEI+ZICSR"

    assert _run_b_case(noisy_32, 32, funct3=0b110) == _run_b_case(explicit_32, 32, funct3=0b110)
    assert _run_b_case(noisy_64, 64, funct3=0b110) == _run_b_case(explicit_64, 64, funct3=0b110)
    assert _run_extension_combo_case(noisy_32, 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case(noisy_64, 64) == _run_extension_combo_case(explicit_64, 64)


def test_star_noisy_iterable_fullset_control_mix_stability_rv32_rv64_with_b_alias_noise():
    """Full-set noisy iterable specs should keep control/system/multi behavior stable."""
    noisy_32 = [
        "rv32i",
        "GC",
        "*",
        "zifencei",
        "zifencei",
        "zicsr",
        "zicond",
        "ZICSR",
        "ZIFENCEI",
        "ZICOND",
        "ZBA",
        "ZBB",
        "ZBK",
        "ZBH",
        "zbs",
        "zbe",
        "zbf",
        "zbm",
        "M",
        "A",
        "B",
        "",
    ]
    noisy_64 = (
        "RV64I",
        "gc",
        "*",
        "a",
        "m",
        "zicond",
        "zicsr",
        "zifencei",
        "ZICOND",
        "ZICSR",
        "ZIFENCEI",
        "ZBA",
        "ZBB",
        "ZBH",
        "zbk",
        "zbs",
        "ZBE",
        "ZBF",
        "zbm",
        "B",
    )

    explicit_32 = "RV32I+GC+M+A+B+ZICOND+ZIFENCEI+ZICSR"
    explicit_64 = "RV64I+GC+M+A+B+ZICOND+ZIFENCEI+ZICSR"

    assert _run_control_flow_case(noisy_32, 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case(noisy_64, 64) == _run_control_flow_case(explicit_64, 64)
    assert _run_multi_extension_mix_case(noisy_32, 32) == _run_multi_extension_mix_case(explicit_32, 32)
    assert _run_multi_extension_mix_case(noisy_64, 64) == _run_multi_extension_mix_case(explicit_64, 64)
    assert _run_extension_combo_case(noisy_32, 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case(noisy_64, 64) == _run_extension_combo_case(explicit_64, 64)
    assert _run_base_case(noisy_32, 32) == _run_base_case(explicit_32, 32)
    assert _run_base_case(noisy_64, 64) == _run_base_case(explicit_64, 64)


def test_star_noisy_iterable_full_standard_pack_runtime_parity_for_rv32_rv64():
    """Noisy iterable star-like specs should match explicit full standard pack runtime behavior."""
    noisy_32 = (
        "  rv32i + GC + * + ZBA + ZBB + ZBH + ZBK + ZBS + ZBE + ZBF + ZBM "
        "+ M + A + ZICSR + ZIFENCEI + ZICOND + unknown + "
        "+ m + a + B + F + D + C + "
    )
    noisy_64 = (
        "RV64I + gc + * + zba + zbb + zbh + ZBK + zbs + zbe + zbf + zbm "
        "+ m + A + zicsr + zifencei + zicond + ??? + "
        "+ M + B + C + F + D +"
    )

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZIFENCEI+ZICSR+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZIFENCEI+ZICSR+ZICOND"

    assert _run_fp_case(noisy_32, 32) == _run_fp_case(explicit_32, 32)
    assert _run_fp_case(noisy_64, 64) == _run_fp_case(explicit_64, 64)
    assert _run_d_case(noisy_32, 32) == _run_d_case(explicit_32, 32)
    assert _run_d_case(noisy_64, 64) == _run_d_case(explicit_64, 64)
    assert _run_zifencei_case(noisy_32, 32) == _run_zifencei_case(explicit_32, 32)
    assert _run_zifencei_case(noisy_64, 64) == _run_zifencei_case(explicit_64, 64)
    assert _run_zicsr_case(noisy_32, 32) == _run_zicsr_case(explicit_32, 32)
    assert _run_zicsr_case(noisy_64, 64) == _run_zicsr_case(explicit_64, 64)
    assert _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0) == _run_zicond_case(explicit_32, 32, funct3=0b001, rs2=0)
    assert _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0) == _run_zicond_case(explicit_64, 64, funct3=0b001, rs2=0)


def test_star_noisy_iterable_fullset_control_system_fp_mix_stability_for_rv32_rv64():
    """Noisy iterable full-set specs should keep mixed runtime outcomes aligned with explicit full specs."""
    noisy_32 = "  rv32i + gc + * + M + A + B + C + F + D + ZIFENCEI + ZICSR + ZICOND + zba + zbb + zbk + zbh + zbs + zbe + zbf + zbm + ??? + unknown.token + "
    noisy_64 = "  rv64i + gc + * + A + M + B + C + F + D + ZICOND + ZICSR + ZIFENCEI + ZBA + ZBB + ZBH + ZBK + ZBKB + ZBS + ZBE + ZBF + ZBM + bad_token + "

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZIFENCEI+ZICSR+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZIFENCEI+ZICSR+ZICOND"

    assert _run_base_case(noisy_32, 32) == _run_base_case(explicit_32, 32)
    assert _run_base_case(noisy_64, 64) == _run_base_case(explicit_64, 64)
    assert _run_control_flow_case(noisy_32, 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case(noisy_64, 64) == _run_control_flow_case(explicit_64, 64)
    assert _run_multi_extension_mix_case(noisy_32, 32) == _run_multi_extension_mix_case(explicit_32, 32)
    assert _run_multi_extension_mix_case(noisy_64, 64) == _run_multi_extension_mix_case(explicit_64, 64)
    assert _run_extension_combo_case(noisy_32, 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case(noisy_64, 64) == _run_extension_combo_case(explicit_64, 64)



def test_star_noisy_iterable_b_alias_bundle_matches_runtime_pack_rv32_rv64():
    """B-extension aliases/noise should be stable for RV32I and RV64I star/full-set mixes."""
    noisy_32 = [
        "rv32i",
        "GC",
        "*",
        "zifencei",
        "ZICSR",
        "zicond",
        "ZBA",
        "zbb",
        "ZBK",
        "zbh",
        "zbs",
        "zbe",
        "zbf",
        "zbm",
        "B",
        "A",
        "M",
        "??",
    ]
    noisy_64 = "  rv64i + gc + * + zba + zbb + zbh + zbk + zbs + zbe + zbf + zbm + m + a + B + ZICSR + ZICOND + ZIFENCEI + ??? + "

    explicit_32 = "RV32I+GC+M+A+B+ZICOND+ZIFENCEI+ZICSR"
    explicit_64 = "RV64I+GC+M+A+B+ZICOND+ZIFENCEI+ZICSR"

    assert _run_b_case(noisy_32, 32, funct3=0b110) == _run_b_case(explicit_32, 32, funct3=0b110)
    assert _run_b_case(noisy_64, 64, funct3=0b110) == _run_b_case(explicit_64, 64, funct3=0b110)
    assert _run_b_case(noisy_32, 32, funct3=0b000) == _run_b_case(explicit_32, 32, funct3=0b000)
    assert _run_b_case(noisy_64, 64, funct3=0b000) == _run_b_case(explicit_64, 64, funct3=0b000)
    assert _run_extension_combo_case(noisy_32, 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case(noisy_64, 64) == _run_extension_combo_case(explicit_64, 64)
    assert _run_multi_extension_mix_case(noisy_32, 32) == _run_multi_extension_mix_case(explicit_32, 32)
    assert _run_multi_extension_mix_case(noisy_64, 64) == _run_multi_extension_mix_case(explicit_64, 64)


def test_star_fullset_profile_matches_runtime_pack_stability_on_rv32_and_rv64():
    """Noisy star/full-set profiles should not perturb baseline+runtime mixed behavior."""
    noisy_32 = "  rv32i + gc + * + M + m + A + a + ZBA + zbb + ZBK + zbh + ZBS + zbs + B + b + C + c + f + D + zicsr + zifencei + zicond + ??? + junk + "
    noisy_64 = "  rv64i + gc + * + zba + zbb + m + A + B + C + zifencei + ZICOND + ZICSR + D + F + junk + ??? + "

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZIFENCEI+ZICSR+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZIFENCEI+ZICSR+ZICOND"

    assert _run_case(noisy_32, 32) == _run_case(explicit_32, 32)
    assert _run_case(noisy_64, 64) == _run_case(explicit_64, 64)
    assert _run_base_case(noisy_32, 32) == _run_base_case(explicit_32, 32)
    assert _run_base_case(noisy_64, 64) == _run_base_case(explicit_64, 64)
    assert _run_control_flow_case(noisy_32, 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case(noisy_64, 64) == _run_control_flow_case(explicit_64, 64)
    assert _run_multi_extension_mix_case(noisy_32, 32) == _run_multi_extension_mix_case(explicit_32, 32)
    assert _run_multi_extension_mix_case(noisy_64, 64) == _run_multi_extension_mix_case(explicit_64, 64)


def test_star_fullset_system_alias_noise_stability_rv32_and_rv64():
    """System-control noisy star/full-set aliases should keep behavior stable for 32/64."""
    noisy_32 = "  rv32i + gc + * + M + m + A + B + C + F + D + ZICSR + ZIFENCEI + ZICOND + zba + zbs + zbb + zbf + zbe + zbm + ??? + junk + "
    noisy_64 = "  rv64i + gc + * + m + A + B + C + F + D + zicsr + zifencei + zicond + zba + zbh + ??? + garbage + "

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    assert _run_base_case(noisy_32, 32) == _run_base_case(explicit_32, 32)
    assert _run_base_case(noisy_64, 64) == _run_base_case(explicit_64, 64)
    assert _run_control_flow_case(noisy_32, 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case(noisy_64, 64) == _run_control_flow_case(explicit_64, 64)
    assert _run_extension_combo_case(noisy_32, 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case(noisy_64, 64) == _run_extension_combo_case(explicit_64, 64)
    assert _run_zifencei_case(noisy_32, 32) == _run_zifencei_case(explicit_32, 32)
    assert _run_zifencei_case(noisy_64, 64) == _run_zifencei_case(explicit_64, 64)
    assert _run_zicsr_case(noisy_32, 32) == _run_zicsr_case(explicit_32, 32)
    assert _run_zicsr_case(noisy_64, 64) == _run_zicsr_case(explicit_64, 64)
    assert _run_zicond_case(noisy_32, 32, funct3=0b001, rs2=0) == _run_zicond_case(explicit_32, 32, funct3=0b001, rs2=0)
    assert _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0) == _run_zicond_case(explicit_64, 64, funct3=0b001, rs2=0)


def test_star_fullset_extended_mix_stability_with_unknown_tokens_rv32_rv64():
    """Unknown or duplicate tokens around star/full-set should keep runtime mix behavior stable."""
    noisy_32 = [
        "rv32i",
        "GC",
        "*",
        "M",
        "A",
        "B",
        "C",
        "F",
        "D",
        "ZICSR",
        "ZIFENCEI",
        "ZICOND",
        "??",
        "junk",
        "???",
        "m",
        "a",
        "b",
    ]
    noisy_64 = "  rv64i + gc + * + ZBA + zbb + zbh + zbe + zbm + m + A + B + C + F + D + zicsr + zifencei + zicond + extra + ??? + "

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    assert _run_multi_extension_mix_case(noisy_32, 32) == _run_multi_extension_mix_case(explicit_32, 32)
    assert _run_multi_extension_mix_case(noisy_64, 64) == _run_multi_extension_mix_case(explicit_64, 64)
    assert _run_extension_combo_case(noisy_32, 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case(noisy_64, 64) == _run_extension_combo_case(explicit_64, 64)
    assert _run_control_flow_case(noisy_32, 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case(noisy_64, 64) == _run_control_flow_case(explicit_64, 64)


def test_star_fullset_runtime_pack_stability_for_controls_and_literals_rv32_rv64():
    """Noisy star/full-set control and immediate-format aliases should stay stable."""
    noisy_32 = [
        "rv32i",
        "GC",
        "*",
        "M",
        "A",
        "C",
        "F",
        "ZICSR",
        "ZIFENCEI",
        "ZICOND",
        "B",
        "a",
        "??",
        "b",
    ]
    noisy_64 = "  rv64i + gc + * + A + M + C + F + D + zicsr + zifencei + zicond + zba + zbb + ??? + junk + "

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    assert _run_control_flow_case(noisy_32, 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case(noisy_64, 64) == _run_control_flow_case(explicit_64, 64)
    assert _run_u_type_case(noisy_32, 32) == _run_u_type_case(explicit_32, 32)
    assert _run_u_type_case(noisy_64, 64) == _run_u_type_case(explicit_64, 64)
    assert _run_jalr_case(noisy_32, 32) == _run_jalr_case(explicit_32, 32)
    assert _run_jalr_case(noisy_64, 64) == _run_jalr_case(explicit_64, 64)
    assert _run_fp32_case(noisy_32, 32) == _run_fp32_case(explicit_32, 32)
    assert _run_fp32_case(noisy_64, 64) == _run_fp32_case(explicit_64, 64)


def test_star_fullset_runtime_pack_stability_for_system_tokens_and_mix_variants_rv32_rv64():
    """Noisy RV32I/RV64I star/full-set specs should keep runtime mixed behavior stable."""
    noisy_32 = (
        "  rv32i + gc + * + M + m + A + a + C + B + F + D "
        "+ ZICOND + zifencei + zicsr + ??? + unknown + B + b + "
    )
    noisy_64 = (
        "  rv64i + gc + * + A + M + B + C + D + F "
        "+ zicond + zifencei + zicsr + ??? + random + "
    )

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    assert _run_base_case(noisy_32, 32) == _run_base_case(explicit_32, 32)
    assert _run_base_case(noisy_64, 64) == _run_base_case(explicit_64, 64)
    assert _run_extension_combo_case(noisy_32, 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case(noisy_64, 64) == _run_extension_combo_case(explicit_64, 64)
    assert _run_zifencei_case(noisy_32, 32) == _run_zifencei_case(explicit_32, 32)
    assert _run_zifencei_case(noisy_64, 64) == _run_zifencei_case(explicit_64, 64)
    assert _run_zicsr_case(noisy_32, 32) == _run_zicsr_case(explicit_32, 32)
    assert _run_zicsr_case(noisy_64, 64) == _run_zicsr_case(explicit_64, 64)
    assert _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0) == _run_zicond_case(explicit_32, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0) == _run_zicond_case(explicit_64, 64, funct3=0b001, rs2=0)
    assert _run_multi_extension_mix_case(noisy_32, 32) == _run_multi_extension_mix_case(explicit_32, 32)
    assert _run_multi_extension_mix_case(noisy_64, 64) == _run_multi_extension_mix_case(explicit_64, 64)


def test_star_fullset_runtime_pack_covers_all_standard_categories_rv32_rv64():
    """All RV32I/RV64I standard-category execution paths stay aligned between star/full-set and explicit specs."""
    noisy_32 = [
        "  rv32i ",
        "Gc",
        "*",
        "M",
        "A",
        "B",
        "C",
        "F",
        "D",
        "ZICSR",
        "ZIFENCEI",
        "ZICOND",
        "??",
        "junk",
    ]
    noisy_64 = (
        " rv64i+gc+*+m+a+b+c+d+f+zicsr+zifencei+zicond+zba+zbb+???+noise "
    )

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    assert _run_base_case(noisy_32, 32) == _run_base_case(explicit_32, 32)
    assert _run_base_case(noisy_64, 64) == _run_base_case(explicit_64, 64)
    assert _run_extension_combo_case(noisy_32, 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case(noisy_64, 64) == _run_extension_combo_case(explicit_64, 64)
    assert _run_control_flow_case(noisy_32, 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case(noisy_64, 64) == _run_control_flow_case(explicit_64, 64)
    assert _run_b_case(noisy_32, 32, funct3=0b111) == _run_b_case(explicit_32, 32, funct3=0b111)
    assert _run_b_case(noisy_64, 64, funct3=0b111) == _run_b_case(explicit_64, 64, funct3=0b111)
    assert _run_fp_case(noisy_32, 32) == _run_fp_case(explicit_32, 32)
    assert _run_fp_case(noisy_64, 64) == _run_fp_case(explicit_64, 64)
    assert _run_d_case(noisy_32, 32) == _run_d_case(explicit_32, 32)
    assert _run_d_case(noisy_64, 64) == _run_d_case(explicit_64, 64)
    assert _run_zicsr_case(noisy_32, 32) == _run_zicsr_case(explicit_32, 32)
    assert _run_zicsr_case(noisy_64, 64) == _run_zicsr_case(explicit_64, 64)
    assert _run_zifencei_case(noisy_32, 32) == _run_zifencei_case(explicit_32, 32)
    assert _run_zifencei_case(noisy_64, 64) == _run_zifencei_case(explicit_64, 64)
    assert _run_multi_extension_mix_case(noisy_32, 32) == _run_multi_extension_mix_case(explicit_32, 32)
    assert _run_multi_extension_mix_case(noisy_64, 64) == _run_multi_extension_mix_case(explicit_64, 64)
    assert _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0) == _run_zicond_case(explicit_32, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0) == _run_zicond_case(explicit_64, 64, funct3=0b001, rs2=0)


def test_star_fullset_runtime_iterable_parser_input_stability_rv32_rv64():
    """Iterable parser variants for RV32I/RV64I should resolve to the same full-set runtime profile."""
    star_32 = "RV32I+GC+*"
    star_64 = "RV64I+GC+*"
    noisy_32_iter = [
        "rv32i",
        " gc ",
        "*",
        "m",
        "A",
        "B",
        "C",
        "F",
        "D",
        "zicsr",
        "zifencei",
        "zicond",
        "??",
        "",
    ]
    noisy_64_iter = (
        "  rv64i + gc + * + M + A + B + C + F + D "
        "+ ZICSR + ZIFENCEI + ZICOND + zba + zbb + ??? + trailing+"
    )

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    assert _run_base_case(star_32, 32) == _run_base_case(noisy_32_iter, 32)
    assert _run_base_case(star_64, 64) == _run_base_case(noisy_64_iter, 64)
    assert _run_extension_combo_case(star_32, 32) == _run_extension_combo_case(noisy_32_iter, 32)
    assert _run_extension_combo_case(star_64, 64) == _run_extension_combo_case(noisy_64_iter, 64)
    assert _run_control_flow_case(star_32, 32) == _run_control_flow_case(noisy_32_iter, 32)
    assert _run_control_flow_case(star_64, 64) == _run_control_flow_case(noisy_64_iter, 64)
    assert _run_multi_extension_mix_case(star_32, 32) == _run_multi_extension_mix_case(noisy_32_iter, 32)
    assert _run_multi_extension_mix_case(star_64, 64) == _run_multi_extension_mix_case(noisy_64_iter, 64)
    assert _run_zicond_case(star_32, 32, funct3=0b000, rs2=0) == _run_zicond_case(explicit_32, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case(star_64, 64, funct3=0b001, rs2=0) == _run_zicond_case(explicit_64, 64, funct3=0b001, rs2=0)
    assert _run_zicsr_case(star_32, 32) == _run_zicsr_case(explicit_32, 32)
    assert _run_zicsr_case(star_64, 64) == _run_zicsr_case(explicit_64, 64)
    assert _run_zifencei_case(star_32, 32) == _run_zifencei_case(explicit_32, 32)
    assert _run_zifencei_case(star_64, 64) == _run_zifencei_case(explicit_64, 64)


def test_star_fullset_parser_input_collections_map_to_same_runtime_32_and_64():
    """Set/tuple/list parser inputs should all map to the same full-set runtime profile."""
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_32_star = "RV32I+GC+*"
    explicit_64_star = "RV64I+GC+*"

    iterable_32 = ("rv32i", "gc", "*", "M", "A", "B", "C", "F", "D", "ZICSR", "ZIFENCEI", "ZICOND", "??", "junk", "m", "a")
    iterable_64 = {"rv64i", "gc", "*", "a", "m", "b", "c", "f", "d", "zicsr", "zifencei", "zicond", "zba", "zbb", "???", ""}
    noisy_32_list = [
        "RV32I", "Gc", "*", "m", "A", "", " ", "b", "B", "C", "F", "D",
        "zicsr", "zifencei", "zicond", "junk", "??"
    ]
    noisy_64_list = [
        "rv64i", "gc", "*", "A", "M", "B", "C", "D", "F", "ZICSR", "ZIFENCEI", "ZICOND",
        "???", "noise", "", " "
    ]

    assert _run_extension_combo_case(explicit_32_star, 32) == _run_extension_combo_case(iterable_32, 32)
    assert _run_extension_combo_case(explicit_64_star, 64) == _run_extension_combo_case(iterable_64, 64)
    assert _run_extension_combo_case(explicit_32_star, 32) == _run_extension_combo_case(noisy_32_list, 32)
    assert _run_extension_combo_case(explicit_64_star, 64) == _run_extension_combo_case(noisy_64_list, 64)
    assert _run_multi_extension_mix_case(explicit_32_star, 32) == _run_multi_extension_mix_case(explicit_32, 32)
    assert _run_multi_extension_mix_case(explicit_64_star, 64) == _run_multi_extension_mix_case(explicit_64, 64)
    assert _run_control_flow_case(explicit_32_star, 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case(explicit_64_star, 64) == _run_control_flow_case(explicit_64, 64)
    assert _run_zicond_case(explicit_32_star, 32, funct3=0b000, rs2=0) == _run_zicond_case(iterable_32, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case(explicit_64_star, 64, funct3=0b001, rs2=0) == _run_zicond_case(iterable_64, 64, funct3=0b001, rs2=0)


def test_star_fullset_parser_noise_normalization_preserves_legacy_base_fp_d_csr_paths_rv32_rv64():
    """Noisy parser forms should still match canonical full-set runtime behavior for legacy categories."""
    star_32 = "RV32I+GC+*"
    star_64 = "RV64I+GC+*"
    canonical_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    canonical_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    canonical_mix_noise_32 = (
        "  RV32I + gC + * + M + M + A + b + C + F + D + F + ZICSR + ZIFENCEI + ZICOND + unknown + "
    )
    canonical_mix_noise_64 = (
        "RV64I+GC+*+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND+zba+zbb+Zicond+garbage"
    )
    iterable_32 = ["rv32i", "", " ", "gc", "*", "M", "m", "A", "a", "b", "C", "c", "F", "f", "D", "d", "zifencei", "ZIFENCEI", "zicsr", "ZICSR", "zicond", "ZICOND", "??", " "]
    iterable_64 = ("rv64i", "gc", "*", "zicsr", "zifencei", "zicond", "M", "m", "A", "a", "B", "b", "C", "c", "D", "d", "F", "f", "ZBA")

    assert _run_base_case(star_32, 32) == _run_base_case(iterable_32, 32)
    assert _run_base_case(star_64, 64) == _run_base_case(iterable_64, 64)
    assert _run_fp_case(star_32, 32) == _run_fp_case(canonical_mix_noise_32, 32)
    assert _run_fp_case(star_64, 64) == _run_fp_case(canonical_mix_noise_64, 64)
    assert _run_d_case(star_32, 32) == _run_d_case(canonical_mix_noise_32, 32)
    assert _run_d_case(star_64, 64) == _run_d_case(canonical_mix_noise_64, 64)
    assert _run_zicsr_case(star_32, 32) == _run_zicsr_case(canonical_32, 32)
    assert _run_zicsr_case(star_64, 64) == _run_zicsr_case(canonical_64, 64)
    assert _run_zifencei_case(star_32, 32) == _run_zifencei_case(canonical_32, 32)
    assert _run_zifencei_case(star_64, 64) == _run_zifencei_case(canonical_64, 64)
    assert _run_control_flow_case(star_32, 32) == _run_control_flow_case(iterable_32, 32)
    assert _run_control_flow_case(star_64, 64) == _run_control_flow_case(iterable_64, 64)
    assert _run_multi_extension_mix_case(star_32, 32) == _run_multi_extension_mix_case(canonical_mix_noise_32, 32)
    assert _run_multi_extension_mix_case(star_64, 64) == _run_multi_extension_mix_case(canonical_mix_noise_64, 64)
    assert _run_zicond_case(star_32, 32, funct3=0b000, rs2=0) == _run_zicond_case(iterable_32, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case(star_64, 64, funct3=0b001, rs2=0) == _run_zicond_case(iterable_64, 64, funct3=0b001, rs2=0)


def test_star_fullset_system_atomic_bmix_parser_variants_map_to_same_runtime_rv32_rv64():
    """System, atomic and B mix parser variants should be identical under RV32I+GC+* profile."""
    star_32 = "RV32I+GC+*"
    star_64 = "RV64I+GC+*"
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    parser_noise_32 = (
        "rv32i", "gc", "*", " m ", "a", "A", "b", "B", "c", "C", "zicsr", "zifencei", "zicond", "zba", "zbb", "zbc", "zbs", "", " ", "??"
    )
    parser_noise_64 = [
        "RV64I", "GC", "*", "M", "m", "A", "a", "B", "C", "F", "D", "ZICSR", "ZIFENCEI", "ZICOND", "garbage", "  ", "zicond", "zba"
    ]
    parser_noise_32_set = {"rv32i", "gc", "*", "m", "a", "b", "c", "f", "d", "zicsr", "zifencei", "zicond", "junk", "zba", "zbb", "ZBS"}
    parser_noise_64_set = {"rv64i", "gc", "*", "M", "A", "B", "C", "F", "D", "ZICSR", "ZIFENCEI", "ZICOND", "ZBA", "zbb", "???"}

    assert _run_amo_star_case(star_32, 32) == _run_amo_star_case(parser_noise_32, 32)
    assert _run_amo_star_case(star_64, 64) == _run_amo_star_case(parser_noise_64, 64)
    assert _run_amo_star_case(star_32, 32) == _run_amo_star_case(parser_noise_32_set, 32)
    assert _run_amo_star_case(star_64, 64) == _run_amo_star_case(parser_noise_64_set, 64)
    assert _run_amo_ops_case(star_32, 32) == _run_amo_ops_case(explicit_32, 32)
    assert _run_amo_ops_case(star_64, 64) == _run_amo_ops_case(explicit_64, 64)
    assert _run_b_case(star_32, 32) == _run_b_case(parser_noise_32, 32)
    assert _run_b_case(star_64, 64) == _run_b_case(parser_noise_64, 64)
    assert _run_multi_extension_mix_case(star_32, 32) == _run_multi_extension_mix_case(parser_noise_32_set, 32)
    assert _run_multi_extension_mix_case(star_64, 64) == _run_multi_extension_mix_case(parser_noise_64_set, 64)
    assert _run_zifencei_case(star_32, 32) == _run_zifencei_case(parser_noise_32, 32)
    assert _run_zifencei_case(star_64, 64) == _run_zifencei_case(parser_noise_64, 64)


def test_star_fullset_order_alias_and_separator_noise_is_equivalent_for_fp_and_misc_paths():
    """Permutation, alias case, and separator noise should not alter full-set runtime behavior."""
    star_32 = "RV32I+GC+*"
    star_64 = "RV64I+GC+*"

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    parser_32 = (
        "RV32I + gc + * + m + C + B + A + F + D + ZIFENCEI + ZICSR + zicond + zba + zbb + "
        "??"
    )
    parser_64 = "rv64i+GC+*+A+A+M+B+F+D+C+ZICOND+ZICSR+ZIFENCEI+zbc+zbe+zbs"
    parser_32_collection = {"rv32i", "gc", "*", "a", "m", "b", "c", "f", "d", "zifencei", "zicsr", "zicond", "zba", "zbb"}
    parser_64_collection = ["rv64i", "gc", "*", "M", "A", "B", "C", "F", "D", "ZIFENCEI", "ZICSR", "ZICOND", "zba", "zbb", "ZBS", "", " "]

    assert _run_extension_combo_case(star_32, 32) == _run_extension_combo_case(parser_32, 32)
    assert _run_extension_combo_case(star_64, 64) == _run_extension_combo_case(parser_64, 64)
    assert _run_extension_combo_case(star_32, 32) == _run_extension_combo_case(parser_32_collection, 32)
    assert _run_extension_combo_case(star_64, 64) == _run_extension_combo_case(parser_64_collection, 64)
    assert _run_base_case(star_32, 32) == _run_base_case(parser_32_collection, 32)
    assert _run_base_case(star_64, 64) == _run_base_case(parser_64_collection, 64)
    assert _run_fp_case(star_32, 32) == _run_fp_case(explicit_32, 32)
    assert _run_fp_case(star_64, 64) == _run_fp_case(explicit_64, 64)
    assert _run_fp_width_case(star_32, 32) == _run_fp_width_case(explicit_32, 32)
    assert _run_fp_width_case(star_64, 64) == _run_fp_width_case(explicit_64, 64)
    assert _run_fp_store_width_case(star_32, 32) == _run_fp_store_width_case(explicit_32, 32)
    assert _run_fp_store_width_case(star_64, 64) == _run_fp_store_width_case(explicit_64, 64)
    assert _run_control_flow_case(star_32, 32) == _run_control_flow_case(parser_32, 32)
    assert _run_control_flow_case(star_64, 64) == _run_control_flow_case(parser_64, 64)
    assert _run_zicond_case(star_32, 32, funct3=0b000, rs2=0) == _run_zicond_case(parser_32_collection, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case(star_64, 64, funct3=0b001, rs2=0) == _run_zicond_case(parser_64_collection, 64, funct3=0b001, rs2=0)
    assert _run_zicsr_case(star_32, 32) == _run_zicsr_case(parser_32_collection, 32)
    assert _run_zicsr_case(star_64, 64) == _run_zicsr_case(parser_64_collection, 64)
    assert _run_zifencei_case(star_32, 32) == _run_zifencei_case(parser_32, 32)
    assert _run_zifencei_case(star_64, 64) == _run_zifencei_case(parser_64, 64)


def test_star_fullset_control_jump_misc_paths_stable_for_noisy_parser_inputs_rv32_rv64():
    """Noisy parser inputs should preserve control-flow, jumps, and atomic-memory behavior."""
    star_32 = "RV32I+GC+*"
    star_64 = "RV64I+GC+*"

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    noisy_32 = (
        "RV32I", "GC", "*", " ", "", "m", "A", "a", "B", "b", "C", "c", "F", "f", "D", "d",
        "zicsr", "zifencei", "zicond", "junk", "ZBA", "ZBB", "???"
    )
    noisy_32_str = (
        " rv32i + gc + * +  m + A + B + C + F + D + ZICSR + ZIFENCEI + zicond + ?? + zba + ZBB "
    )
    noisy_64 = {
        "rv64i", "gc", "*", "M", "A", "B", "C", "F", "D", "ZICSR", "ZIFENCEI", "ZICOND", "zba", "ZICOND", "garbage"
    }

    assert _run_extension_combo_case(star_32, 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case(star_64, 64) == _run_extension_combo_case(noisy_64, 64)
    assert _run_extension_combo_case(star_32, 32) == _run_extension_combo_case(noisy_32_str, 32)
    assert _run_extension_combo_case(star_64, 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_control_flow_case(star_32, 32) == _run_control_flow_case(noisy_32, 32)
    assert _run_control_flow_case(star_64, 64) == _run_control_flow_case(noisy_64, 64)
    assert _run_jalr_case(star_32, 32) == _run_jalr_case(noisy_32_str, 32)
    assert _run_jalr_case(star_64, 64) == _run_jalr_case(noisy_64, 64)
    assert _run_u_type_case(star_32, 32) == _run_u_type_case(noisy_32, 32)
    assert _run_u_type_case(star_64, 64) == _run_u_type_case(noisy_64, 64)

    assert _run_base_case(star_32, 32) == _run_base_case(explicit_32, 32)
    assert _run_base_case(star_64, 64) == _run_base_case(explicit_64, 64)
    assert _run_mw_case(star_64, 64) == _run_mw_case(explicit_64, 64)
    assert _run_lr_sc_case(star_64, 64, funct3=0b011) == _run_lr_sc_case(explicit_64, 64, funct3=0b011)
    assert _run_amo_ops_case(star_32, 32) == _run_amo_ops_case(explicit_32, 32)
    assert _run_amo_ops_case(star_64, 64) == _run_amo_ops_case(explicit_64, 64)
    assert _run_amo_star_case(star_32, 32) == _run_amo_star_case(noisy_32_str, 32)
    assert _run_amo_star_case(star_64, 64) == _run_amo_star_case(noisy_64, 64)

    assert _run_zicsr_case(star_32, 32) == _run_zicsr_case(noisy_32_str, 32)
    assert _run_zicsr_case(star_64, 64) == _run_zicsr_case(noisy_64, 64)
    assert _run_zifencei_case(star_32, 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case(star_64, 64) == _run_zifencei_case(noisy_64, 64)
    assert _run_zicond_case(star_32, 32, funct3=0b000, rs2=0) == _run_zicond_case(noisy_32, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case(star_64, 64, funct3=0b001, rs2=0) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0)


def test_star_fullset_end_to_end_runtime_equivalence_for_all_core_paths():
    """Star profile must remain identical to explicit full profile across core instruction families."""
    star_32 = "RV32I+GC+*"
    star_64 = "RV64I+GC+*"
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    noisy_32 = (
        "RV32I", "gc", "*", " ", "m", "A", "a", "B", "C", "f", "F", "d", "D",
        "zicsr", "zifencei", "zicond", "ZBA", "ZBB", "junk", "??"
    )
    noisy_64 = [
        "rv64i", "gc", "*", "M", "A", "B", "C", "F", "D", "ZICSR", "ZIFENCEI",
        "ZICOND", "zba", "zbb", "garbage", "zbc"
    ]

    assert _run_extension_combo_case(star_32, 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case(star_64, 64) == _run_extension_combo_case(explicit_64, 64)
    assert _run_extension_combo_case(star_32, 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case(star_64, 64) == _run_extension_combo_case(noisy_64, 64)

    assert _run_base_case(star_32, 32) == _run_base_case(explicit_32, 32)
    assert _run_base_case(star_64, 64) == _run_base_case(explicit_64, 64)
    assert _run_fp_case(star_32, 32) == _run_fp_case(explicit_32, 32)
    assert _run_fp_case(star_64, 64) == _run_fp_case(explicit_64, 64)
    assert _run_control_flow_case(star_32, 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case(star_64, 64) == _run_control_flow_case(explicit_64, 64)
    assert _run_jalr_case(star_32, 32) == _run_jalr_case(explicit_32, 32)
    assert _run_jalr_case(star_64, 64) == _run_jalr_case(explicit_64, 64)
    assert _run_u_type_case(star_32, 32) == _run_u_type_case(explicit_32, 32)
    assert _run_u_type_case(star_64, 64) == _run_u_type_case(explicit_64, 64)

    assert _run_amo_ops_case(star_32, 32) == _run_amo_ops_case(explicit_32, 32)
    assert _run_amo_ops_case(star_64, 64) == _run_amo_ops_case(explicit_64, 64)
    assert _run_mw_case(star_64, 64) == _run_mw_case(explicit_64, 64)
    assert _run_lr_sc_case(star_64, 64, funct3=0b011) == _run_lr_sc_case(explicit_64, 64, funct3=0b011)
    assert _run_zicsr_case(star_32, 32) == _run_zicsr_case(explicit_32, 32)
    assert _run_zicsr_case(star_64, 64) == _run_zicsr_case(explicit_64, 64)
    assert _run_zifencei_case(star_32, 32) == _run_zifencei_case(explicit_32, 32)
    assert _run_zifencei_case(star_64, 64) == _run_zifencei_case(explicit_64, 64)
    assert _run_fp_width_case(star_32, 32) == _run_fp_width_case(explicit_32, 32)
    assert _run_fp_width_case(star_64, 64) == _run_fp_width_case(explicit_64, 64)
    assert _run_fp_store_width_case(star_32, 32) == _run_fp_store_width_case(explicit_32, 32)
    assert _run_fp_store_width_case(star_64, 64) == _run_fp_store_width_case(explicit_64, 64)


def test_star_fullset_profile_matches_explicit_and_noisy_for_full_instruction_matrix_rv32_rv64():
    """Verify full instruction matrix parity for star profile with parser noise variants."""
    star_32 = "RV32I+GC+*"
    star_64 = "RV64I+GC+*"
    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    noisy_32_str = " rv32i + gc + * + m + a + b + c + f + d + zicsr + zifencei + zicond + zba + zbb + zbc "
    noisy_64_iter = (
        "RV64I", "GC", "*", "M", "A", "B", "C", "F", "D",
        "ZICSR", "ZIFENCEI", "ZICOND", "ZBA", "ZBB", "ZBS", ""
    )
    noisy_32_iter = (
        "RV32I", "GC", "*", "M", "A", "B", "C", "F", "D",
        "ZICSR", "ZIFENCEI", "ZICOND", "ZBA", "ZBB", "ZBH", ""
    )
    noisy_64_str = "RV64I + gc + * + m + a + b + c + f + d + zicsr + zifencei + zicond + zba + zbb"
    noisy_32_set = {"rv32i", "gc", "*", "m", "a", "b", "c", "f", "d", "zicsr", "zifencei", "zicond", "zba", "zbb"}
    noisy_64_set = {"rv64i", "gc", "*", "M", "A", "B", "C", "F", "D", "ZICSR", "ZIFENCEI", "ZICOND", "ZBA", "ZBB"}

    assert _run_extension_combo_case(star_32, 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case(star_64, 64) == _run_extension_combo_case(explicit_64, 64)
    assert _run_extension_combo_case(star_32, 32) == _run_extension_combo_case(noisy_32_str, 32)
    assert _run_extension_combo_case(star_64, 64) == _run_extension_combo_case(noisy_64_iter, 64)
    assert _run_extension_combo_case(star_32, 32) == _run_extension_combo_case(noisy_32_set, 32)
    assert _run_extension_combo_case(star_64, 64) == _run_extension_combo_case(noisy_64_set, 64)

    assert _run_case(star_32, 32) == _run_case(noisy_32_iter, 32)
    assert _run_case(star_64, 64) == _run_case(noisy_64_iter, 64)

    assert _run_base_case(star_32, 32) == _run_base_case(explicit_32, 32)
    assert _run_base_case(star_64, 64) == _run_base_case(explicit_64, 64)
    assert _run_m_case(star_32, 32) == _run_m_case(explicit_32, 32)
    assert _run_m_case(star_64, 64) == _run_m_case(explicit_64, 64)
    assert _run_u_type_case(star_32, 32) == _run_u_type_case(explicit_32, 32)
    assert _run_u_type_case(star_64, 64) == _run_u_type_case(explicit_64, 64)
    assert _run_control_flow_case(star_32, 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case(star_64, 64) == _run_control_flow_case(explicit_64, 64)
    assert _run_jalr_case(star_32, 32) == _run_jalr_case(explicit_32, 32)
    assert _run_jalr_case(star_64, 64) == _run_jalr_case(explicit_64, 64)
    assert _run_control_flow_case(star_32, 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case(star_64, 64) == _run_control_flow_case(explicit_64, 64)

    assert _run_amo_ops_case(star_32, 32) == _run_amo_ops_case(explicit_32, 32)
    assert _run_amo_ops_case(star_64, 64) == _run_amo_ops_case(explicit_64, 64)
    assert _run_amo_star_case(star_32, 32) == _run_amo_star_case(noisy_32_set, 32)
    assert _run_amo_star_case(star_64, 64) == _run_amo_star_case(noisy_64_set, 64)

    assert _run_mw_case(star_32, 32) == _run_mw_case(explicit_32, 32)
    assert _run_mw_case(star_64, 64) == _run_mw_case(explicit_64, 64)
    assert _run_lr_sc_case(star_64, 64, funct3=0b011) == _run_lr_sc_case(explicit_64, 64, funct3=0b011)

    assert _run_fp_case(star_32, 32) == _run_fp_case(explicit_32, 32)
    assert _run_fp_case(star_64, 64) == _run_fp_case(explicit_64, 64)
    assert _run_fp_width_case(star_32, 32) == _run_fp_width_case(explicit_32, 32)
    assert _run_fp_width_case(star_64, 64) == _run_fp_width_case(explicit_64, 64)
    assert _run_fp_store_width_case(star_32, 32) == _run_fp_store_width_case(explicit_32, 32)
    assert _run_fp_store_width_case(star_64, 64) == _run_fp_store_width_case(explicit_64, 64)
    assert _run_case(star_32, 32) == _run_case(explicit_32, 32)
    assert _run_case(star_64, 64) == _run_case(explicit_64, 64)
    assert _run_case(star_32, 32) == _run_case(noisy_32_str, 32)
    assert _run_case(star_64, 64) == _run_case(noisy_64_str, 64)
    assert _run_d_case(star_32, 32) == _run_d_case(explicit_32, 32)
    assert _run_d_case(star_64, 64) == _run_d_case(explicit_64, 64)
    assert _run_d_case(star_32, 32) == _run_d_case(noisy_32_set, 32)
    assert _run_d_case(star_64, 64) == _run_d_case(noisy_64_set, 64)

    assert _run_zicsr_case(star_32, 32) == _run_zicsr_case(explicit_32, 32)
    assert _run_zicsr_case(star_64, 64) == _run_zicsr_case(explicit_64, 64)
    assert _run_zicond_case(star_32, 32, funct3=0b000, rs2=0) == _run_zicond_case(explicit_32, 32, funct3=0b000, rs2=0)
    assert _run_zicond_case(star_64, 64, funct3=0b001, rs2=0) == _run_zicond_case(explicit_64, 64, funct3=0b001, rs2=0)
    assert _run_zifencei_case(star_32, 32) == _run_zifencei_case(explicit_32, 32)
    assert _run_zifencei_case(star_64, 64) == _run_zifencei_case(explicit_64, 64)


def test_star_fullset_control_and_noisy_iterables_are_stable_on_rv32_and_rv64():
    """Control flow path should remain stable across star/noisy iterable extension inputs."""
    star_32 = "RV32I+GC+*"
    star_64 = "RV64I+GC+*"
    full_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    full_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"

    noisy_iter_32 = [
        " rv32i ",
        "gc",
        "*",
        "M",
        "A",
        "C",
        "B",
        "F",
        "D",
        "zifencei",
        "zicond",
        "zicsr",
        "",
        "???",
        "M",
    ]
    noisy_iter_64 = (
        "RV64I",
        "GC",
        "*",
        "m",
        "a",
        "c",
        "b",
        "f",
        "d",
        "ZICOND",
        "ZICSR",
        "ZIFENCEI",
        None,
        "",
    )

    assert _run_control_flow_case(star_32, 32) == _run_control_flow_case(full_32, 32)
    assert _run_control_flow_case(star_64, 64) == _run_control_flow_case(full_64, 64)
    assert _run_control_flow_case(star_32, 32) == _run_control_flow_case(noisy_iter_32, 32)
    assert _run_control_flow_case(star_64, 64) == _run_control_flow_case(noisy_iter_64, 64)

def test_star_run_case_iterable_and_str_parser_equivalence_for_rv32_and_rv64_fullset():
    """`_run_case` should accept iterable extension input and match canonical star string."""
    star_32_iter = ["rv32i", "gc", "*", "m", "a", "b", "c", "f", "d", "zicsr", "zifencei", "zicond", "zba", "zbb"]
    star_64_iter = ["rv64i", "gc", "*", "m", "a", "b", "c", "f", "d", "zicsr", "zifencei", "zicond", "zba", "zbb"]

    star_32 = "RV32I+GC+*"
    star_64 = "RV64I+GC+*"

    assert _run_case(star_32, 32) == _run_case(star_32_iter, 32)
    assert _run_case(star_64, 64) == _run_case(star_64_iter, 64)


def test_star_parser_iterable_generator_mixed_tokens_are_noop_for_unknown_rv32_and_rv64():
    """Mixed token types in iterable parser inputs should behave like noisy canonical specs."""

    star_32 = "RV32I+GC+*"
    star_64 = "RV64I+GC+*"

    def noisy_tokens_32():
        yield " rv32i "
        yield "gc"
        yield "*"
        yield None
        yield "M"
        yield ""
        yield "   "
        yield 123
        yield "zifencei"
        yield "ZICSR"
        yield "zicond"
        yield "ZICOND"

    def noisy_tokens_64():
        yield " RV64I "
        yield "GC"
        yield "*"
        yield "a"
        yield 456
        yield ""
        yield "zicsr"
        yield "zifencei"
        yield None

    assert _run_case(star_32, 32) == _run_case(noisy_tokens_32(), 32)
    assert _run_case(star_64, 64) == _run_case(noisy_tokens_64(), 64)
    assert _run_control_flow_case(star_32, 32) == _run_control_flow_case(noisy_tokens_32(), 32)
    assert _run_control_flow_case(star_64, 64) == _run_control_flow_case(noisy_tokens_64(), 64)


def test_star_parser_generator_tokens_stable_for_extension_combo_and_system_mix_on_rv64():
    """Generator-based noisy tokens should preserve RV64 star/fullset equivalence for combo/mix paths."""

    star_64 = "RV64I+GC+*"
    explicit_64 = "RV64I+GC+M+A+ZICSR+ZIFENCEI+ZICOND"

    def noisy_tokens():
        yield " RV64I "
        yield "gc"
        yield "*"
        yield "m"
        yield "a"
        yield "b"
        yield "c"
        yield "f"
        yield "d"
        yield "zifencei"
        yield "ZICOND"
        yield None
        yield ""
        yield 0

    assert _run_extension_combo_case(star_64, 64) == _run_extension_combo_case(explicit_64, 64)
    assert _run_extension_combo_case(star_64, 64) == _run_extension_combo_case(noisy_tokens(), 64)
    assert _run_multi_extension_mix_case(star_64, 64) == _run_multi_extension_mix_case(explicit_64, 64)
    assert _run_multi_extension_mix_case(star_64, 64) == _run_multi_extension_mix_case(noisy_tokens(), 64)
    assert _run_lr_sc_case(star_64, 64, funct3=0b011) == _run_lr_sc_case(explicit_64, 64, funct3=0b011)
    assert _run_lr_sc_case(star_64, 64, funct3=0b011) == _run_lr_sc_case(noisy_tokens(), 64, funct3=0b011)


def test_star_parser_duplicate_alias_tokens_stable_for_rv32_and_rv64_runtime_paths():
    """Duplicate/alias/noisy token streams should preserve star behavior on both XLENs."""

    star_32 = "RV32I+GC+*"
    star_64 = "RV64I+GC+*"

    def noisy_tokens_32():
        yield "  rv32i "
        yield "gc"
        yield "GC"
        yield "*"
        yield "*"
        yield "m"
        yield "A"
        yield "a"
        yield "ZICSR"
        yield "zifencei"
        yield "ZIFENCEI"
        yield "zicond"
        yield " "
        yield None

    def noisy_tokens_64():
        yield "  RV64I "
        yield "gc"
        yield "*"
        yield "A"
        yield "a"
        yield "zicsr"
        yield "ZIFENCEI"
        yield "M"
        yield "m"
        yield "zicond"
        yield "b"
        yield ""

    assert _run_case(star_32, 32) == _run_case(noisy_tokens_32(), 32)
    assert _run_case(star_64, 64) == _run_case(noisy_tokens_64(), 64)
    assert _run_control_flow_case(star_32, 32) == _run_control_flow_case(noisy_tokens_32(), 32)
    assert _run_control_flow_case(star_64, 64) == _run_control_flow_case(noisy_tokens_64(), 64)
    assert _run_extension_combo_case(star_32, 32) == _run_extension_combo_case(noisy_tokens_32(), 32)
    assert _run_extension_combo_case(star_64, 64) == _run_extension_combo_case(noisy_tokens_64(), 64)


def test_star_parser_whitespace_and_alias_normalization_stays_deterministic_rv32_rv64():
    """Different token casing/spacing/duplicates must not change parser/runtime output."""

    noisy_32 = "  rV32i + GC + * + ??? + gc + * + m + A + zifencei + M +  "
    noisy_64 = "  rv64I + gC + * + ??? + * + zicsr + zifencei + ZICOND + a +"

    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_64, 64)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(noisy_32, 32)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(noisy_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)


def test_star_parser_mixed_noise_paths_are_equivalent_between_string_and_generator_for_rv32_and_rv64():
    """String and generator noise forms for star should yield identical behavior for runtime paths."""

    noisy_string_32 = "  rv32i + gc + * + m + A + zicsr + zifencei + zicond + ??? + "
    noisy_string_64 = "  rv64i + gc + * + m + A + zifencei + zicsr + ZICOND + ??? + "

    def noisy_generator_32():
        yield " rv32i "
        yield "GC"
        yield "*"
        yield "*"
        yield "m"
        yield "A"
        yield "zicsr"
        yield "zifencei"
        yield "ZICOND"
        yield None

    def noisy_generator_64():
        yield " rv64i "
        yield "gc"
        yield "*"
        yield "zifencei"
        yield "ZICSR"
        yield "m"
        yield "a"
        yield ""

    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_string_32, 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_string_64, 64)
    assert _run_case("RV32I+GC+*", 32) == _run_case(noisy_generator_32(), 32)
    assert _run_case("RV64I+GC+*", 64) == _run_case(noisy_generator_64(), 64)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(noisy_generator_32(), 32)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(noisy_generator_64(), 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_generator_32(), 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_generator_64(), 64)


def test_star_parser_string_vs_generator_noise_equivalence_for_mix_and_lr_sc_rv32_rv64():
    """Star parser equivalence across string and generator noise for mix and LR/SC paths."""

    noisy_string_32 = "  rv32i + gc + * + ??? + m + a + zifencei + zicsr + zicond +  "
    noisy_string_64 = "  rv64i + gc + * + ??? + m + a + ZICSR + ZIFENCEI + zicond +  "

    def noisy_generator_32():
        yield "rv32i"
        yield "+"
        yield "GC"
        yield "*"
        yield "*"
        yield "M"
        yield "A"
        yield "a"
        yield "zicsr"
        yield "ZIFENCEI"
        yield "zicond"
        yield "ZB" 

    def noisy_generator_64():
        yield "rv64i"
        yield "+"
        yield "gc"
        yield "*"
        yield "m"
        yield "a"
        yield "zifencei"
        yield "ZICOND"
        yield "zicsr"
        yield None

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_string_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_string_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_generator_32(), 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_generator_64(), 64)
    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case(noisy_generator_32(), 32, funct3=0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b011) == _run_lr_sc_case(noisy_generator_64(), 64, funct3=0b011)


def test_star_parser_noisy_iterables_match_explicit_and_star_for_jalr_u_paths_rv32_rv64():
    """Noisy/duplicate extension token streams should not affect `jalr` and `u`-type behavior."""

    star_32 = "RV32I+GC+*"
    star_64 = "RV64I+GC+*"
    explicit_32 = "RV32I+GC+M+A+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+F+D+ZICSR+ZIFENCEI+ZICOND"

    noisy_tokens_32 = [
        "",
        "  ",
        "RV32I",
        "+",
        "GC",
        "+",
        "*",
        " ",
        "m",
        "M",
        "zicsr",
        "ZICSR",
        "f",
        "D",
        "zicond",
        "ZICOND",
        "zifencei",
        "",
    ]

    noisy_tokens_64 = [
        "  RV64I  ",
        "+",
        "gc",
        "+",
        "*",
        "a",
        "A",
        "d",
        "f",
        "m",
        "ZIFENCEI",
        "zicsr",
        "ZICOND",
        "",
    ]

    assert _run_jalr_case(star_32, 32) == _run_jalr_case(explicit_32, 32)
    assert _run_jalr_case(star_64, 64) == _run_jalr_case(explicit_64, 64)
    assert _run_jalr_case(star_32, 32) == _run_jalr_case(noisy_tokens_32, 32)
    assert _run_jalr_case(star_64, 64) == _run_jalr_case(noisy_tokens_64, 64)
    assert _run_u_type_case(star_32, 32) == _run_u_type_case(explicit_32, 32)
    assert _run_u_type_case(star_64, 64) == _run_u_type_case(explicit_64, 64)
    assert _run_u_type_case(star_32, 32) == _run_u_type_case(noisy_tokens_32, 32)
    assert _run_u_type_case(star_64, 64) == _run_u_type_case(noisy_tokens_64, 64)


def test_star_parser_noisy_and_standalone_iterables_preserve_b_path_for_rv32_64():
    """Ensure `b`-path execution is stable when star parser receives noisy/iterator inputs."""

    star_32 = "RV32I+GC+*"
    star_64 = "RV64I+GC+*"
    explicit_32 = "RV32I+GC+M+A+ZBA+ZBB+ZBK+ZBS+ZBC"
    explicit_64 = "RV64I+GC+M+A+ZBA+ZBB+ZBK+ZBS+ZBC"

    noisy_string_32 = "  rv32i + gc + m + a + zbA + zbb + zbk + zbc + zbs + * + ??? + "
    noisy_string_64 = "  rv64i + gc + m + a + zbb + zba + zbk + zbc + zbs + * + ZICSR + "

    def noisy_generator_32():
        yield " RV32I "
        yield "+"
        yield "gC"
        yield "+"
        yield "*"
        yield "M"
        yield "A"
        yield "zba"
        yield "ZBA"
        yield "zbk"
        yield "ZBS"
        yield "ZBC"
        yield ""

    def noisy_generator_64():
        yield "rv64i"
        yield "+"
        yield "gc"
        yield "+"
        yield "*"
        yield "m"
        yield "a"
        yield "zbb"
        yield "ZBB"
        yield "zba"
        yield "ZBK"
        yield "ZBS"
        yield "ZBC"
        yield None

    assert _run_b_case(star_32, 32, funct3=0b111) == _run_b_case(explicit_32, 32, funct3=0b111)
    assert _run_b_case(star_64, 64, funct3=0b111) == _run_b_case(explicit_64, 64, funct3=0b111)
    assert _run_b_case(star_32, 32, funct3=0b110) == _run_b_case(explicit_32, 32, funct3=0b110)
    assert _run_b_case(star_64, 64, funct3=0b110) == _run_b_case(explicit_64, 64, funct3=0b110)
    assert _run_b_case(star_32, 32, funct3=0b100) == _run_b_case(explicit_32, 32, funct3=0b100)
    assert _run_b_case(star_64, 64, funct3=0b100) == _run_b_case(explicit_64, 64, funct3=0b100)

    assert _run_b_case(star_32, 32, funct3=0b111) == _run_b_case(noisy_string_32, 32, funct3=0b111)
    assert _run_b_case(star_64, 64, funct3=0b111) == _run_b_case(noisy_string_64, 64, funct3=0b111)
    assert _run_b_case(star_32, 32, funct3=0b110) == _run_b_case(noisy_string_32, 32, funct3=0b110)
    assert _run_b_case(star_64, 64, funct3=0b110) == _run_b_case(noisy_string_64, 64, funct3=0b110)

    assert _run_b_case(star_32, 32, funct3=0b111) == _run_b_case(noisy_generator_32(), 32, funct3=0b111)
    assert _run_b_case(star_64, 64, funct3=0b111) == _run_b_case(noisy_generator_64(), 64, funct3=0b111)
    assert _run_b_case(star_32, 32, funct3=0b110) == _run_b_case(noisy_generator_32(), 32, funct3=0b110)
    assert _run_b_case(star_64, 64, funct3=0b110) == _run_b_case(noisy_generator_64(), 64, funct3=0b110)
    assert _run_b_case(star_32, 32, funct3=0b100) == _run_b_case(noisy_generator_32(), 32, funct3=0b100)
    assert _run_b_case(star_64, 64, funct3=0b100) == _run_b_case(noisy_generator_64(), 64, funct3=0b100)


def test_star_parser_control_and_system_paths_stable_under_noise_for_rv32_rv64():
    """ZICOND/ZICSR/ZIFENCEI behaviors should be parser-noise invariant in star profile."""

    explicit_32 = "RV32I+GC+M+A+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_string_32 = "  rv32i + gc + * + ??? + m + a + f + d + zicsr + zifencei + zicond +  "
    noisy_string_64 = "  rv64i + gc + * + ??? + m + a + f + d + ZIFENCEI + ZICSR + ZICOND + "

    def noisy_generator_32():
        yield "rv32i"
        yield "+"
        yield "GC"
        yield "+"
        yield "*"
        yield "M"
        yield "a"
        yield "f"
        yield "D"
        yield "zicond"
        yield "ZICSR"
        yield "zifencei"
        yield ""

    def noisy_generator_64():
        yield "rv64i"
        yield "+"
        yield "gc"
        yield "+"
        yield "*"
        yield "m"
        yield "A"
        yield "d"
        yield "F"
        yield "zicsr"
        yield "zifencei"
        yield "ZICOND"
        yield None

    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(explicit_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(explicit_64, 64, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_string_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_string_64, 64, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_generator_32(), 32, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_generator_64(), 64, funct3=0b001, rs2=0x0F)

    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(explicit_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(explicit_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_string_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_string_64, 64)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_generator_32(), 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_generator_64(), 64)

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(explicit_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(explicit_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_string_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_string_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_generator_32(), 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_generator_64(), 64)


def test_star_parser_varied_iterable_inputs_preserve_multi_extension_and_system_execution():
    tuple_32 = ("rv32i", "gc", "", "+", "m", "a", "f", "d", "M", "A", "ZICOND", "zifencei", "zicsr", " ", "junk")
    tuple_64 = ("rv64i", "gc", "M", "", "A", "F", "D", "zicond", "ZIFENCEI", "ZICSR", "??", "*")

    def generator_32():
        for token in ("rv32i", "+", "gc", "M", "A", "f", "d", "zicond", "zifencei", "ZICSR", "", None):
            yield token

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(tuple_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(tuple_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(generator_32(), 32)
    assert _run_zicond_case("RV32I+GC+*", 32, funct3=0b001, rs2=0x0F) == _run_zicond_case(tuple_32, 32, funct3=0b001, rs2=0x0F)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(tuple_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(tuple_64, 64)


def test_star_set_preserves_control_and_system_mixes_under_tuple_generator_noise():
    explicit_32 = ("RV32I", "GC", "M", "A", "B", "C", "F", "D", "ZICSR", "ZIFENCEI", "ZICOND")
    explicit_64 = ("RV64I", "GC", "M", "A", "B", "C", "F", "D", "ZICSR", "ZIFENCEI", "ZICOND")
    noisy_32 = (" rv32i ", "+", "", "gc", "???", "m", "a", "b", " ", "zifencei", "zicsr", "zicond", None, "junk")
    noisy_64 = (" rv64i ", "+", "", "gc", "???", "m", "a", "b", " ", "zifencei", "zicsr", "zicond", "", "junk")

    def generator_64():
        yield "rv64i"
        yield "+"
        yield "gc"
        yield "+"
        yield "*"
        yield "M"
        yield "A"
        yield "B"
        yield "C"
        yield "F"
        yield "D"
        yield "ZICOND"
        yield "ZICSR"
        yield "ZIFENCEI"
        yield ""

    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(explicit_64, 64)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(noisy_32, 32)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(generator_64(), 64)
    assert _run_jalr_case("RV64I+GC+*", 64) == _run_jalr_case(generator_64(), 64)


def test_star_set_system_control_roundtrip_with_iterable_variants_rv32_rv64():
    cfg_tuple_32 = ("rv32i", "gc", "M", "A", "F", "D", "ZICSR", "ZIFENCEI", "ZICOND")
    cfg_tuple_64 = ("rv64i", "gc", "m", "a", "f", "d", "zicsr", "zifencei", "zicond")
    cfg_star_noisy_32 = ("rv32i", "+", "GC", "+", "*", "???", "", "m", "a", "zicsr", "zifencei", "zicond", "junk")
    cfg_star_noisy_64 = ("rv64i", "+", "GC", "+", "*", "???", "", "m", "a", "zicsr", "zifencei", "zicond", "")

    def cfg_generator():
        yield "rv32i"
        yield "+"
        yield "gc"
        yield "+"
        yield "*"
        yield "M"
        yield "a"
        yield "F"
        yield "d"
        yield "ZICOND"
        yield "ZICSR"
        yield "ZIFENCEI"
        yield None

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(cfg_tuple_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(cfg_tuple_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(cfg_star_noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(cfg_star_noisy_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(cfg_generator(), 32)
    assert _run_zicond_case("RV64I+GC+*", 64, rs2=0x0F) == _run_zicond_case(cfg_tuple_64, 64, rs2=0x0F)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(cfg_star_noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(cfg_star_noisy_64, 64)


def test_star_set_preserves_base_profile_parser_noise_on_rv32_rv64():
    base_32 = ("rv32i", "gc")
    base_64 = ("rv64i", "gc")
    noisy_base_32 = ("  rv32i ", "+", "gc", "junk", "", "???", "alias", "base")
    noisy_base_64 = ("  rv64i ", "+", "gc", "junk", "", "???", "alias", "base")

    def noisy_generator_64():
        yield "rv64i"
        yield "+"
        yield "gc"
        yield ""
        yield "junk"
        yield None

    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(base_32, 32)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(base_64, 64)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(noisy_base_32, 32)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(noisy_base_64, 64)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(noisy_generator_64(), 64)

    assert _run_jalr_case("RV32I+GC+*", 32) == _run_jalr_case(base_32, 32)
    assert _run_jalr_case("RV64I+GC+*", 64) == _run_jalr_case(base_64, 64)
    assert _run_jalr_case("RV32I+GC+*", 32) == _run_jalr_case(noisy_base_32, 32)
    assert _run_jalr_case("RV64I+GC+*", 64) == _run_jalr_case(noisy_generator_64(), 64)

def test_star_set_preserves_arith_and_control_on_rv32_and_rv64_with_mixed_noise_inputs():
    """RV32I+GC+* should treat mixed iterable/string noise as equivalent baseline."""

    base_32 = ("rv32i", "gc")
    base_64 = ("rv64i", "gc")
    noisy_32 = ("  RV32I ", "+", "gc", "junk", "", "???", "m", "A", "*", "zicond", "invalid")
    noisy_64 = ("  RV64I ", "+", "gc", "junk", "", "???", "m", "a", "*", "zifencei", "invalid")

    def noise_generator_32():
        yield " RV32I "
        yield "+"
        yield "gc"
        yield "*"
        yield "m"
        yield "a"
        yield "ZICSR"
        yield "ZIFENCEI"
        yield "ZICOND"
        yield "junk"
        yield ""
        yield None

    def noise_generator_64():
        yield " rv64i "
        yield "+"
        yield "GC"
        yield "+"
        yield "*"
        yield "M"
        yield "A"
        yield "zicsr"
        yield "zifencei"
        yield "zicond"
        yield None

    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(base_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(base_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noise_generator_32(), 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noise_generator_64(), 64)

    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(noisy_32, 32)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(noisy_64, 64)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(noise_generator_32(), 32)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(noise_generator_64(), 64)

    assert _run_jalr_case("RV32I+GC+*", 32) == _run_jalr_case(noisy_32, 32)
    assert _run_jalr_case("RV64I+GC+*", 64) == _run_jalr_case(noisy_64, 64)
    assert _run_jalr_case("RV32I+GC+*", 32) == _run_jalr_case(noise_generator_32(), 32)
    assert _run_jalr_case("RV64I+GC+*", 64) == _run_jalr_case(noise_generator_64(), 64)


def test_star_set_base_parser_tuple_generator_noise_parity_for_rv32_and_rv64():
    """Ensure RV32I+GC+* is parser-noise stable for tuple/generator inputs."""

    base_32 = ("rv32i", "gc")
    base_64 = ("rv64i", "gc")
    noisy_tuple_32 = ("  RV32I ", "+", "gc", "", "*", "junk", "???", "alias", "base")
    noisy_tuple_64 = ("  RV64I ", "+", "gc", "", "*", "junk", "???", "alias", "base")

    def noisy_generator_32():
        yield " rv32i "
        yield "+"
        yield "GC"
        yield "+"
        yield "*"
        yield "m"
        yield "A"
        yield ""
        yield None

    def noisy_generator_64():
        yield " rv64i "
        yield "+"
        yield "gc"
        yield "+"
        yield "*"
        yield "M"
        yield "A"
        yield ""
        yield None

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(base_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(base_64, 64)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_tuple_32, 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(noisy_tuple_64, 64)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_generator_32(), 32)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(noisy_generator_64(), 64)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_tuple_32, 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_tuple_64, 64, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_generator_32(), 32, funct3=0b110)
    assert _run_b_case("RV64I+GC+*", 64, funct3=0b110) == _run_b_case(noisy_generator_64(), 64, funct3=0b110)

    assert _run_u_type_case("RV32I+GC+*", 32) == _run_u_type_case(noisy_tuple_32, 32)
    assert _run_u_type_case("RV64I+GC+*", 64) == _run_u_type_case(noisy_tuple_64, 64)
    assert _run_u_type_case("RV32I+GC+*", 32) == _run_u_type_case(noisy_generator_32(), 32)
    assert _run_u_type_case("RV64I+GC+*", 64) == _run_u_type_case(noisy_generator_64(), 64)

def test_star_set_base_arith_load_branch_parity_on_rv32_with_noisy_inputs():
    """RV32I+GC+* should keep base/mixed instruction behavior under noisy parser inputs."""

    explicit = ("rv32i", "gc")
    explicit_b = ("rv32i", "gc", "b")
    noisy_tuple = ("  RV32I ", "+", "gc", "*", "junk", "", "???", "alias")
    noisy_tuple_b = ("  RV32I ", "+", "gc", "*", "B", "junk", "", "???", "alias")

    def noisy_generator():
        yield " rv32i "
        yield "+"
        yield "GC"
        yield "+"
        yield "*"
        yield "M"
        yield "A"
        yield ""
        yield None

    def noisy_generator_b():
        yield " rv32i "
        yield "+"
        yield "GC"
        yield "+"
        yield "*"
        yield "B"
        yield "M"
        yield "A"
        yield ""
        yield None

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(explicit, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_tuple, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_generator(), 32)

    assert _run_u_type_case("RV32I+GC+*", 32) == _run_u_type_case(explicit, 32)
    assert _run_u_type_case("RV32I+GC+*", 32) == _run_u_type_case(noisy_tuple, 32)
    assert _run_u_type_case("RV32I+GC+*", 32) == _run_u_type_case(noisy_generator(), 32)

    assert _run_load_case("RV32I+GC+*", 32) == _run_load_case(explicit, 32)
    assert _run_load_case("RV32I+GC+*", 32) == _run_load_case(noisy_tuple, 32)
    assert _run_load_case("RV32I+GC+*", 32) == _run_load_case(noisy_generator(), 32)

    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(explicit_b, 32, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_tuple_b, 32, funct3=0b110)
    assert _run_b_case("RV32I+GC+*", 32, funct3=0b110) == _run_b_case(noisy_generator_b(), 32, funct3=0b110)


def test_star_set_load_parser_noise_invariance_on_rv64():
    """RV64I+GC+* should keep load behavior stable under noisy parser inputs."""

    explicit_64 = ("rv64i", "gc")
    noisy_tuple_64 = ("  RV64I ", "+", "gc", "*", "junk", "", "???", "alias")

    def noisy_generator_64():
        yield " rv64i "
        yield "+"
        yield "GC"
        yield "+"
        yield "*"
        yield "M"
        yield "A"
        yield ""
        yield None

    assert _run_load_case("RV64I+GC+*", 64) == _run_load_case(explicit_64, 64)
    assert _run_load_case("RV64I+GC+*", 64) == _run_load_case(noisy_tuple_64, 64)
    assert _run_load_case("RV64I+GC+*", 64) == _run_load_case(noisy_generator_64(), 64)


def test_star_set_load_fullset_parity_with_explicit_standard_extensions_on_rv32_and_rv64():
    """RV32/64 star set should match explicit standard parser baseline on load path."""

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + D + F + C + B + ZIFENCEI + A + M + ZICSR + ZICOND + junk + "
    noisy_64 = "  rv64i + gc + ??? + D + F + C + B + ZIFENCEI + A + M + ZICSR + ZICOND + junk + "

    assert _run_load_case("RV32I+GC+*", 32) == _run_load_case(explicit_32, 32)
    assert _run_load_case("RV64I+GC+*", 64) == _run_load_case(explicit_64, 64)
    assert _run_load_case("RV32I+GC+*", 32) == _run_load_case(noisy_32, 32)
    assert _run_load_case("RV64I+GC+*", 64) == _run_load_case(noisy_64, 64)


def test_star_set_store_parser_noise_invariance_on_rv32_and_rv64():
    """RV32/64 star set should keep store behavior stable under noisy parser inputs."""

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + D + F + C + B + ZIFENCEI + A + M + ZICSR + ZICOND + junk + "
    noisy_64 = "  rv64i + gc + ??? + D + F + C + B + ZIFENCEI + A + M + ZICSR + ZICOND + junk + "

    assert _run_store_case("RV32I+GC+*", 32) == _run_store_case(explicit_32, 32)
    assert _run_store_case("RV64I+GC+*", 64) == _run_store_case(explicit_64, 64)
    assert _run_store_case("RV32I+GC+*", 32) == _run_store_case(noisy_32, 32)
    assert _run_store_case("RV64I+GC+*", 64) == _run_store_case(noisy_64, 64)


def test_star_set_amo_parser_noise_invariance_on_rv32():
    """RV32 star set should keep AMO behavior stable under noisy parser inputs."""

    explicit = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_tuple = ("  RV32I ", "+", "gc", "+", "?", "M", "A", "*", "junk", "", "", None)
    noisy_generator = ("  rv32i + gc + ??? + M + A + C + F + D + ZICSR + ZICOND + ZIFENCEI + B + unknown ")

    assert _run_amo_op_case("RV32I+GC+*", 32, amofn=0, src_imm=0, init_mem=0x12345678) == _run_amo_op_case(explicit, 32, amofn=0, src_imm=0, init_mem=0x12345678)
    assert _run_amo_op_case("RV32I+GC+*", 32, amofn=0, src_imm=0, init_mem=0x12345678) == _run_amo_op_case(noisy_tuple, 32, amofn=0, src_imm=0, init_mem=0x12345678)
    assert _run_amo_op_case("RV32I+GC+*", 32, amofn=0, src_imm=0, init_mem=0x12345678) == _run_amo_op_case(noisy_generator, 32, amofn=0, src_imm=0, init_mem=0x12345678)


def test_star_set_lr_sc_parser_noise_invariance_on_rv32():
    """RV32 star set should keep LR/SC behavior stable under noisy parser inputs."""

    explicit = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_tuple = ("  RV32I ", "+", "gc", "+", "???", "M", "A", "*", "junk", "", "alias", None)
    noisy_generator = (" rv32i + gc + ??? + ZBA + M + A + C + D + ZICOND + zicond + ZIFENCEI + unknown + ")

    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case(explicit, 32, funct3=0b010)
    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case(noisy_tuple, 32, funct3=0b010)
    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case(noisy_generator, 32, funct3=0b010)


def test_star_set_amo_parser_noise_invariance_on_rv64():
    """RV64 star set should keep AMO behavior stable under noisy parser inputs."""

    explicit = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_tuple = ("  RV64I ", "+", "gc", "+", "???", "B", "M", "A", "*", "junk", "", None)
    noisy_generator = ("  rv64i + gc + ??? + M + A + C + F + D + ZICOND + zicond + ZIFENCEI + unknown + ")

    assert _run_amo_op_case("RV64I+GC+*", 64, amofn=0, src_imm=0, init_mem=0x123456789ABCDEF0) == _run_amo_op_case(explicit, 64, amofn=0, src_imm=0, init_mem=0x123456789ABCDEF0)
    assert _run_amo_op_case("RV64I+GC+*", 64, amofn=0, src_imm=0, init_mem=0x123456789ABCDEF0) == _run_amo_op_case(noisy_tuple, 64, amofn=0, src_imm=0, init_mem=0x123456789ABCDEF0)
    assert _run_amo_op_case("RV64I+GC+*", 64, amofn=0, src_imm=0, init_mem=0x123456789ABCDEF0) == _run_amo_op_case(noisy_generator, 64, amofn=0, src_imm=0, init_mem=0x123456789ABCDEF0)


def test_star_set_zifencei_parser_noise_invariance_on_rv32_and_rv64():
    """RV32/64 star set should keep zifencei behavior stable under noisy parser inputs."""

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = "  rv32i + gc + ??? + ZBA + zbb + M + C + D + zifencei + ZIFENCEI + zicsr + ZICSR + ZICOND + unknown + "
    noisy_64 = "  rv64i + gc + ??? + ZBA + zbb + M + C + D + zifencei + ZIFENCEI + zicsr + ZICSR + ZICOND + unknown + "

    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(explicit_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(explicit_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)


def test_star_set_multi_extension_mix_stability_on_rv32_and_rv64():
    """RV32/64 star set should match explicit and noisy mixed-extension inputs for multi-path execution."""

    explicit_32 = ("RV32I", "GC", "M", "A", "B", "C", "F", "D", "ZICSR", "ZIFENCEI", "ZICOND")
    explicit_64 = ("RV64I", "GC", "M", "A", "B", "C", "F", "D", "ZICSR", "ZIFENCEI", "ZICOND")
    noisy_32 = ("  rv32i ", "+", "gc", "???", "", "d", "f", "b", "zba", "zicond", "junk", "*", "a", "m")
    noisy_64 = ("  rv64i ", "+", "gc", "???", "", "d", "f", "b", "zba", "zicond", "junk", "*", "a", "m")

    def noisy_generator_64():
        yield "  rv64i "
        yield "+"
        yield "GC"
        yield "+"
        yield "M"
        yield "A"
        yield "B"
        yield "C"
        yield "F"
        yield "D"
        yield "ZICSR"
        yield "ZIFENCEI"
        yield "ZICOND"
        yield "junk"
        yield ""
        yield None

    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(explicit_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(explicit_64, 64)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_generator_64(), 64)
    assert _run_jalr_case("RV32I+GC+*", 32) == _run_jalr_case(explicit_32, 32)
    assert _run_jalr_case("RV64I+GC+*", 64) == _run_jalr_case(explicit_64, 64)


def test_star_set_rv32_control_system_mix_parity_under_duplicates_and_alias_noise():
    """RV32I+GC+* should keep control/system behavior stable with noisy duplicate tokens."""

    explicit_32 = ("RV32I", "GC", "M", "A", "B", "C", "F", "D", "ZICSR", "ZIFENCEI", "ZICOND")
    noisy_32 = (
        " rv32i ",
        "+",
        "gc",
        "",
        "GC",
        "???",
        "M",
        "A",
        "m",
        "a",
        "B",
        "b",
        "ZICOND",
        "zicond",
        "junk",
        "ZICSR",
        "zicsr",
        "ZIFENCEI",
        "zifencei",
        "*",
        "???",
    )

    def noisy_generator_32():
        yield " RV32I "
        yield "+"
        yield "gc"
        yield ""
        yield "M"
        yield "A"
        yield "m"
        yield "B"
        yield "b"
        yield "zifencei"
        yield "ZICOND"
        yield "ZICSR"
        yield "???"
        yield "junk"
        yield None

    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(noisy_32, 32)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(noisy_generator_32(), 32)
    assert _run_jalr_case("RV32I+GC+*", 32) == _run_jalr_case(explicit_32, 32)
    assert _run_jalr_case("RV32I+GC+*", 32) == _run_jalr_case(noisy_32, 32)
    assert _run_jalr_case("RV32I+GC+*", 32) == _run_jalr_case(noisy_generator_32(), 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(explicit_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_generator_32(), 32)
def test_star_set_rv64_control_system_mix_parity_under_duplicates_and_alias_noise():
    """RV64I+GC+* should keep control/system behavior stable with noisy duplicate tokens."""

    explicit_64 = ("RV64I", "GC", "M", "A", "B", "C", "F", "D", "ZICSR", "ZIFENCEI", "ZICOND")
    noisy_64 = (
        " rv64i ",
        "+",
        "GC",
        "",
        "GC",
        "???",
        "M",
        "A",
        "m",
        "a",
        "B",
        "b",
        "ZICOND",
        "zicond",
        "junk",
        "ZICSR",
        "zicsr",
        "ZIFENCEI",
        "zifencei",
        "*",
        "???",
    )

    def noisy_generator_64():
        yield " RV64I "
        yield "+"
        yield "gc"
        yield ""
        yield "M"
        yield "A"
        yield "m"
        yield "B"
        yield "b"
        yield "zifencei"
        yield "ZICOND"
        yield "ZICSR"
        yield "???"
        yield "junk"
        yield None

    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(explicit_64, 64)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(noisy_64, 64)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(noisy_generator_64(), 64)
    assert _run_jalr_case("RV64I+GC+*", 64) == _run_jalr_case(explicit_64, 64)
    assert _run_jalr_case("RV64I+GC+*", 64) == _run_jalr_case(noisy_64, 64)
    assert _run_jalr_case("RV64I+GC+*", 64) == _run_jalr_case(noisy_generator_64(), 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(explicit_64, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_generator_64(), 64)
def test_star_set_fp_d_parser_noise_invariance_on_rv64():
    """RV64I+GC+* fp/d path should keep stable under noisy parser inputs."""

    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_tuple = ("  RV64I ", "+", "gc", "", "???", "F", "f", "D", "d", "M", "A", "zicond", "junk", "ZICSR", "zifencei", "*", "ZIFENCEI", "zicsr", None)

    def noisy_generator_64():
        yield " rv64i "
        yield "+"
        yield "GC"
        yield "+"
        yield "F"
        yield "f"
        yield "D"
        yield "d"
        yield "M"
        yield "A"
        yield "ZICOND"
        yield "junk"
        yield None

    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(explicit_64, 64)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_tuple, 64)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_generator_64(), 64)

    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(explicit_64, 64)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_tuple, 64)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_generator_64(), 64)
def test_star_set_zicond_parser_noise_invariance_on_rv32_and_rv64():
    """RV32/64 star sets should keep zicond behavior stable under noisy parser inputs."""

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  RV32I ",
        "+",
        "GC",
        "???",
        "",
        "M",
        "A",
        "B",
        "C",
        "F",
        "D",
        "zifencei",
        "ZICOND",
        "zicond",
        "junk",
        "ZICSR",
        "*",
    )
    noisy_64 = (
        "  RV64I ",
        "+",
        "gc",
        "",
        "???",
        "C",
        "M",
        "A",
        "B",
        "D",
        "F",
        "zicond",
        "ZIFENCEI",
        "ZICOND",
        "junk",
        "ZICSR",
        "*",
    )

    def noisy_generator_32():
        yield " rv32i "
        yield "+"
        yield "GC"
        yield "M"
        yield "A"
        yield "B"
        yield "C"
        yield "F"
        yield "D"
        yield "ZICOND"
        yield "ZICSR"
        yield "ZIFENCEI"
        yield "???"
        yield "junk"
        yield None

    def noisy_generator_64():
        yield " rv64i "
        yield "+"
        yield "gc"
        yield "M"
        yield "A"
        yield "B"
        yield "C"
        yield "F"
        yield "D"
        yield "zicond"
        yield "ZICSR"
        yield "ZIFENCEI"
        yield None

    assert _run_zicond_case("RV32I+GC+*", 32) == _run_zicond_case(explicit_32, 32)
    assert _run_zicond_case("RV64I+GC+*", 64) == _run_zicond_case(explicit_64, 64)
    assert _run_zicond_case("RV32I+GC+*", 32) == _run_zicond_case(noisy_32, 32)
    assert _run_zicond_case("RV64I+GC+*", 64) == _run_zicond_case(noisy_64, 64)
    assert _run_zicond_case("RV32I+GC+*", 32) == _run_zicond_case(noisy_generator_32(), 32)
    assert _run_zicond_case("RV64I+GC+*", 64) == _run_zicond_case(noisy_generator_64(), 64)


def test_star_set_load_store_noise_invariance_on_rv32_and_rv64():
    """Load/store helper behavior should stay stable under star/noisy extension parsing."""

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  RV32I ",
        "+",
        "gc",
        "",
        "M",
        "A",
        "B",
        "C",
        "M",
        "junk",
        "F",
        "D",
        "ZICOND",
        "zifencei",
        "ZICSR",
        "*",
        "???",
    )
    noisy_64 = (
        "  RV64I ",
        "+",
        "GC",
        "",
        "A",
        "M",
        "junk",
        "C",
        "F",
        "D",
        "b",
        "zifencei",
        "zicond",
        "ZICSR",
        "*",
        "???",
    )

    def noisy_generator_32():
        yield " rv32i "
        yield "+"
        yield "GC"
        yield "+"
        yield "M"
        yield "A"
        yield "F"
        yield "D"
        yield "ZICOND"
        yield "junk"
        yield None

    def noisy_generator_64():
        yield " rv64i "
        yield "+"
        yield "gc"
        yield "+"
        yield "A"
        yield "M"
        yield "C"
        yield "F"
        yield "D"
        yield "ZICSR"
        yield "ZIFENCEI"
        yield None

    assert _run_load_case("RV32I+GC+*", 32) == _run_load_case(explicit_32, 32)
    assert _run_load_case("RV64I+GC+*", 64) == _run_load_case(explicit_64, 64)
    assert _run_load_case("RV32I+GC+*", 32) == _run_load_case(noisy_32, 32)
    assert _run_load_case("RV64I+GC+*", 64) == _run_load_case(noisy_64, 64)
    assert _run_load_case("RV32I+GC+*", 32) == _run_load_case(noisy_generator_32(), 32)
    assert _run_load_case("RV64I+GC+*", 64) == _run_load_case(noisy_generator_64(), 64)

    assert _run_store_case("RV32I+GC+*", 32) == _run_store_case(explicit_32, 32)
    assert _run_store_case("RV64I+GC+*", 64) == _run_store_case(explicit_64, 64)
    assert _run_store_case("RV32I+GC+*", 32) == _run_store_case(noisy_32, 32)
    assert _run_store_case("RV64I+GC+*", 64) == _run_store_case(noisy_64, 64)
    assert _run_store_case("RV32I+GC+*", 32) == _run_store_case(noisy_generator_32(), 32)
    assert _run_store_case("RV64I+GC+*", 64) == _run_store_case(noisy_generator_64(), 64)


def test_star_set_amo_op_noise_invariance_on_rv32_and_rv64():
    """AMO helper behavior should stay stable under star/noisy extension parsing."""

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  RV32I ",
        "+",
        "gc",
        "",
        "M",
        "A",
        "junk",
        "B",
        "C",
        "F",
        "D",
        "ZICOND",
        "ZIFENCEI",
        "ZICSR",
        "???",
    )
    noisy_64 = (
        "  RV64I ",
        "+",
        "gc",
        "",
        "m",
        "a",
        "junk",
        "B",
        "C",
        "F",
        "D",
        "zicond",
        "zifencei",
        "zicsr",
        "*",
        "???",
    )

    def noisy_generator_32():
        yield " rv32i "
        yield "+"
        yield "GC"
        yield "M"
        yield "A"
        yield "B"
        yield "C"
        yield "F"
        yield "D"
        yield "junk"
        yield None

    def noisy_generator_64():
        yield " rv64i "
        yield "+"
        yield "gc"
        yield "M"
        yield "A"
        yield "B"
        yield "C"
        yield "F"
        yield "D"
        yield "ZICSR"
        yield "ZIFENCEI"
        yield None

    assert _run_amo_op_case("RV32I+GC+*", 32, amofn=0b00000, src_imm=0, init_mem=0x1234) == _run_amo_op_case(explicit_32, 32, amofn=0b00000, src_imm=0, init_mem=0x1234)
    assert _run_amo_op_case("RV64I+GC+*", 64, amofn=0b00000, src_imm=0, init_mem=0x1234) == _run_amo_op_case(explicit_64, 64, amofn=0b00000, src_imm=0, init_mem=0x1234)
    assert _run_amo_op_case("RV32I+GC+*", 32, amofn=0b00000, src_imm=0, init_mem=0x1234) == _run_amo_op_case(noisy_32, 32, amofn=0b00000, src_imm=0, init_mem=0x1234)
    assert _run_amo_op_case("RV64I+GC+*", 64, amofn=0b00000, src_imm=0, init_mem=0x1234) == _run_amo_op_case(noisy_64, 64, amofn=0b00000, src_imm=0, init_mem=0x1234)
    assert _run_amo_op_case("RV32I+GC+*", 32, amofn=0b00000, src_imm=0, init_mem=0x1234) == _run_amo_op_case(noisy_generator_32(), 32, amofn=0b00000, src_imm=0, init_mem=0x1234)
    assert _run_amo_op_case("RV64I+GC+*", 64, amofn=0b00000, src_imm=0, init_mem=0x1234) == _run_amo_op_case(noisy_generator_64(), 64, amofn=0b00000, src_imm=0, init_mem=0x1234)

    assert _run_amo_op_case("RV32I+GC+*", 32, amofn=0b10000, src_imm=0x7F, init_mem=0x80, funct3=0b010) == _run_amo_op_case(explicit_32, 32, amofn=0b10000, src_imm=0x7F, init_mem=0x80, funct3=0b010)
    assert _run_amo_op_case("RV64I+GC+*", 64, amofn=0b10000, src_imm=0x7FFFFFFF, init_mem=0x80, funct3=0b011) == _run_amo_op_case(explicit_64, 64, amofn=0b10000, src_imm=0x7FFFFFFF, init_mem=0x80, funct3=0b011)
    assert _run_amo_op_case("RV32I+GC+*", 32, amofn=0b10000, src_imm=0x7F, init_mem=0x80, funct3=0b010) == _run_amo_op_case(noisy_32, 32, amofn=0b10000, src_imm=0x7F, init_mem=0x80, funct3=0b010)
    assert _run_amo_op_case("RV64I+GC+*", 64, amofn=0b10000, src_imm=0x7FFFFFFF, init_mem=0x80, funct3=0b011) == _run_amo_op_case(noisy_64, 64, amofn=0b10000, src_imm=0x7FFFFFFF, init_mem=0x80, funct3=0b011)
    assert _run_amo_op_case("RV32I+GC+*", 32, amofn=0b10000, src_imm=0x7F, init_mem=0x80, funct3=0b010) == _run_amo_op_case(noisy_generator_32(), 32, amofn=0b10000, src_imm=0x7F, init_mem=0x80, funct3=0b010)
    assert _run_amo_op_case("RV64I+GC+*", 64, amofn=0b10000, src_imm=0x7FFFFFFF, init_mem=0x80, funct3=0b011) == _run_amo_op_case(noisy_generator_64(), 64, amofn=0b10000, src_imm=0x7FFFFFFF, init_mem=0x80, funct3=0b011)


def test_star_set_mixed_mul_div_path_stability_under_noisy_parser_rv32_and_rv64():
    """Integer mul/div helper behavior should remain stable with noisy parser inputs."""

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  RV32I ",
        "+",
        "gc",
        "",
        "M",
        "A",
        "junk",
        "B",
        "C",
        "f",
        "d",
        "ZICOND",
        "zifencei",
        "ZICSR",
        "???",
    )
    noisy_64 = (
        "  RV64I ",
        "+",
        "GC",
        "",
        "m",
        "a",
        "junk",
        "B",
        "C",
        "f",
        "d",
        "zicond",
        "zifencei",
        "zicsr",
        "*",
        "???",
    )

    def noisy_generator_32():
        yield " rv32i "
        yield "+"
        yield "GC"
        yield "M"
        yield "A"
        yield "B"
        yield "junk"
        yield None

    def noisy_generator_64():
        yield " rv64i "
        yield "+"
        yield "gc"
        yield "M"
        yield "A"
        yield "B"
        yield "C"
        yield "junk"
        yield None

    assert _run_m_case("RV32I+GC+M", 32) == _run_m_case("RV32I+GC+*", 32)
    assert _run_m_case("RV64I+GC+M", 64) == _run_m_case("RV64I+GC+*", 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(explicit_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(explicit_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_32, 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_64, 64)
    assert _run_m_case("RV32I+GC+*", 32) == _run_m_case(noisy_generator_32(), 32)
    assert _run_m_case("RV64I+GC+*", 64) == _run_m_case(noisy_generator_64(), 64)


def test_star_set_lr_sc_stability_under_noisy_parser_inputs_rv32_and_rv64():
    """LR/SC helper behavior should remain stable for star/noisy extension parsing."""

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  RV32I ",
        "+",
        "gc",
        "",
        "M",
        "A",
        "junk",
        "B",
        "C",
        "F",
        "D",
        "ZICOND",
        "zifencei",
        "ZICSR",
        "???",
    )
    noisy_64 = (
        "  RV64I ",
        "+",
        "GC",
        "",
        "m",
        "a",
        "junk",
        "C",
        "B",
        "F",
        "D",
        "zicond",
        "zifencei",
        "zicsr",
        "*",
        "???",
    )

    def noisy_generator_32():
        yield " rv32i "
        yield "+"
        yield "gc"
        yield "M"
        yield "A"
        yield "B"
        yield "C"
        yield "junk"
        yield None

    def noisy_generator_64():
        yield " rv64i "
        yield "+"
        yield "gc"
        yield "M"
        yield "A"
        yield "B"
        yield "C"
        yield "junk"
        yield None

    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case(explicit_32, 32, funct3=0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b010) == _run_lr_sc_case(explicit_64, 64, funct3=0b010)
    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b011) == _run_lr_sc_case(explicit_32, 32, funct3=0b011)
    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b011) == _run_lr_sc_case(explicit_64, 64, funct3=0b011)
    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case(noisy_32, 32, funct3=0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b010) == _run_lr_sc_case(noisy_64, 64, funct3=0b010)
    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b011) == _run_lr_sc_case(noisy_32, 32, funct3=0b011)
    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b011) == _run_lr_sc_case(noisy_64, 64, funct3=0b011)
    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case(noisy_generator_32(), 32, funct3=0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b010) == _run_lr_sc_case(noisy_generator_64(), 64, funct3=0b010)
    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b011) == _run_lr_sc_case(noisy_generator_32(), 32, funct3=0b011)
    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b011) == _run_lr_sc_case(noisy_generator_64(), 64, funct3=0b011)


def test_star_set_parser_noise_redundancy_stability_for_control_and_combo_paths():
    """Noisy parser noise should not perturb RV32/64 star-set control/combo behavior."""

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  RV32I ",
        "+",
        "gc",
        "",
        "M",
        "A",
        "junk",
        "B",
        "B",
        "C",
        "F",
        "D",
        "ZICOND",
        "zifencei",
        "ZICSR",
        "???",
        "+",
    )
    noisy_64 = (
        "  RV64I ",
        "+",
        "GC",
        "",
        "m",
        "a",
        "junk",
        "C",
        "B",
        "F",
        "D",
        "ZICOND",
        "zifencei",
        "zicsr",
        "???",
        "*",
    )

    def noisy_generator_32():
        yield " rv32i "
        yield "+"
        yield "gc"
        yield "M"
        yield "A"
        yield "junk"
        yield "B"
        yield "B"
        yield "F"
        yield "D"
        yield "ZICSR"
        yield None

    def noisy_generator_64():
        yield " rv64i "
        yield "+"
        yield "gc"
        yield "M"
        yield "A"
        yield "junk"
        yield "C"
        yield "zicsr"
        yield "zifencei"
        yield "ZICOND"
        yield None

    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(explicit_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_64, 64)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(noisy_32, 32)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(noisy_64, 64)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(noisy_generator_32(), 32)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(noisy_generator_64(), 64)


def test_star_set_system_and_atomic_contract_parity_rv32_rv64_with_tuple_generator_noise():
    """RV64 and RV32 star profiles should keep system/atomic behavior stable for noisy parser inputs."""

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "rv32i",
        "+",
        "GC",
        "",
        "M",
        "A",
        "junk",
        "B",
        "C",
        "F",
        "zifencei",
        "ZICSR",
        "ZICOND",
        "???",
    )
    noisy_64 = (
        "RV64I",
        "+",
        "gc",
        "",
        "m",
        "a",
        "junk",
        "c",
        "b",
        "d",
        "ZICSR",
        "ZIFENCEI",
        "zicond",
        "???",
    )

    def noisy_generator_32():
        yield "  rv32i  "
        yield "+"
        yield "GC"
        yield "M"
        yield "A"
        yield "junk"
        yield "B"
        yield "C"
        yield "ZICSR"
        yield "ZIFENCEI"
        yield None

    def noisy_generator_64():
        yield "  rv64i  "
        yield "+"
        yield "gc"
        yield "M"
        yield "A"
        yield "junk"
        yield "F"
        yield "ZICSR"
        yield "ZIFENCEI"
        yield None

    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(explicit_32, 32)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(explicit_64, 64)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(noisy_32, 32)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(noisy_64, 64)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_generator_32(), 32)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_generator_64(), 64)
    assert _run_lr_sc_case("RV32I+GC+*", 32, funct3=0b010) == _run_lr_sc_case(noisy_32, 32, funct3=0b010)
    assert _run_lr_sc_case("RV64I+GC+*", 64, funct3=0b011) == _run_lr_sc_case(noisy_64, 64, funct3=0b011)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_64, 64)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_64, 64)


def test_star_set_fp_and_d_parser_noise_stability_on_rv64_with_control_checks():
    """RV64 star profile should remain stable for FP/D helpers under noisy parser inputs."""

    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_64 = (
        " rv64i ",
        "+",
        "gc",
        "",
        "f",
        "d",
        "M",
        "junk",
        "A",
        "B",
        "C",
        "ZICOND",
        "zifencei",
        "ZICSR",
        "???",
        "*",
    )

    def noisy_generator_64():
        yield "RV64I"
        yield "+"
        yield "GC"
        yield "M"
        yield "A"
        yield "junk"
        yield "B"
        yield "C"
        yield "F"
        yield "D"
        yield "ZICSR"
        yield None

    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(explicit_64, 64)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_64, 64)
    assert _run_fp_case("RV64I+GC+*", 64) == _run_fp_case(noisy_generator_64(), 64)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(explicit_64, 64)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_64, 64)
    assert _run_d_case("RV64I+GC+*", 64) == _run_d_case(noisy_generator_64(), 64)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(explicit_64, 64, funct3=0b001, rs2=0x0F)
    assert _run_zicond_case("RV64I+GC+*", 64, funct3=0b001, rs2=0x0F) == _run_zicond_case(noisy_64, 64, funct3=0b001, rs2=0x0F)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(noisy_64, 64)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_generator_64(), 64)


def test_star_set_fp_and_d_parser_noise_stability_on_rv32_with_mix_and_junk():
    """RV32 star profile should remain stable for FP/D helpers under mixed noisy parser inputs."""

    explicit_32 = (
        "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    )
    noisy_32 = (
        "rv32i",
        "+",
        "GC",
        "",
        "f",
        "d",
        "M",
        "ZICSR",
        "junk",
        "A",
        "B",
        "C",
        "zifencei",
        "ZICOND",
        "???",
        "*",
    )

    def noisy_generator_32():
        yield "RV32I"
        yield "+"
        yield "gc"
        yield "M"
        yield "A"
        yield "junk"
        yield "B"
        yield "C"
        yield "F"
        yield "D"
        yield "ZICSR"
        yield None

    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(explicit_32, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_32, 32)
    assert _run_fp_case("RV32I+GC+*", 32) == _run_fp_case(noisy_generator_32(), 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(explicit_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_32, 32)
    assert _run_d_case("RV32I+GC+*", 32) == _run_d_case(noisy_generator_32(), 32)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(noisy_32, 32)


def test_star_plus_gc32_parser_noise_preserves_fullset_core_mix():
    """RV32I+GC+* parser noise inputs should preserve core-path behavior on mixed workloads."""

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i ",
        "+",
        "gc",
        "",
        "M",
        "junk",
        "A",
        "B",
        "B",
        "C",
        "F",
        "D",
        "ZICSR",
        "zifencei",
        "ZICOND",
        "???",
        "RV32I",
    )

    def noisy_generator_32():
        yield "RV32I"
        yield "+"
        yield "GC"
        yield "M"
        yield "A"
        yield "B"
        yield "junk"
        yield "C"
        yield "F"
        yield "D"
        yield "ZICSR"
        yield "ZIFENCEI"
        yield "ZICOND"
        yield None

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(explicit_32, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_generator_32(), 32)
    assert _run_load_case("RV32I+GC+*", 32) == _run_load_case(noisy_32, 32)
    assert _run_load_case("RV32I+GC+*", 32) == _run_load_case(noisy_generator_32(), 32)
    assert _run_store_case("RV32I+GC+*", 32) == _run_store_case(noisy_32, 32)
    assert _run_store_case("RV32I+GC+*", 32) == _run_store_case(noisy_generator_32(), 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(explicit_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_generator_32(), 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(explicit_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_32, 32)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(noisy_generator_32(), 32)


def test_star_core_profile_parser_noise_equivalence_rv32_rv64_across_mix_paths():
    """RV32I+GC+* and RV64I+GC+* should be parser-noise equivalent on core-mix workloads."""

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i ",
        "+",
        "gc",
        "",
        "M",
        "junk",
        "A",
        "B",
        "B",
        "C",
        "F",
        "D",
        "ZICSR",
        "zifencei",
        "ZICOND",
        "???",
        "RV32I",
    )
    noisy_64 = (
        " RV64I ",
        "+",
        "Gc",
        "",
        "m",
        "junk",
        "a",
        "b",
        "c",
        "d",
        "f",
        "ZIFENCEI",
        "zicsr",
        "ZICOND",
        "???",
    )

    def noisy_generator_32():
        yield " RV32I "
        yield "+"
        yield "GC"
        yield "M"
        yield "A"
        yield "junk"
        yield "B"
        yield "C"
        yield "F"
        yield "D"
        yield "ZICSR"
        yield "ZIFENCEI"
        yield "ZICOND"
        yield None

    def noisy_generator_64():
        yield "RV64I"
        yield "+"
        yield "gc"
        yield "M"
        yield "A"
        yield "junk"
        yield "B"
        yield "C"
        yield "D"
        yield "F"
        yield "ZICSR"
        yield "ZIFENCEI"
        yield "ZICOND"
        yield None

    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_32, 32)
    assert _run_base_case("RV32I+GC+*", 32) == _run_base_case(noisy_generator_32(), 32)
    assert _run_load_case("RV32I+GC+*", 32) == _run_load_case(noisy_32, 32)
    assert _run_load_case("RV32I+GC+*", 32) == _run_load_case(noisy_generator_32(), 32)
    assert _run_store_case("RV32I+GC+*", 32) == _run_store_case(noisy_32, 32)
    assert _run_store_case("RV32I+GC+*", 32) == _run_store_case(noisy_generator_32(), 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(explicit_32, 32)
    assert _run_amo_ops_case("RV32I+GC+*", 32) == _run_amo_ops_case(noisy_32, 32)
    assert _run_zicsr_case("RV32I+GC+*", 32) == _run_zicsr_case(noisy_generator_32(), 32)
    assert _run_zifencei_case("RV32I+GC+*", 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_control_flow_case("RV32I+GC+*", 32) == _run_control_flow_case(noisy_generator_32(), 32)
    assert _run_multi_extension_mix_case("RV32I+GC+*", 32) == _run_multi_extension_mix_case(noisy_32, 32)
    assert _run_extension_combo_case("RV32I+GC+*", 32) == _run_extension_combo_case(noisy_generator_32(), 32)

    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(noisy_64, 64)
    assert _run_base_case("RV64I+GC+*", 64) == _run_base_case(noisy_generator_64(), 64)
    assert _run_load_case("RV64I+GC+*", 64) == _run_load_case(noisy_64, 64)
    assert _run_load_case("RV64I+GC+*", 64) == _run_load_case(noisy_generator_64(), 64)
    assert _run_store_case("RV64I+GC+*", 64) == _run_store_case(noisy_64, 64)
    assert _run_store_case("RV64I+GC+*", 64) == _run_store_case(noisy_generator_64(), 64)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(explicit_64, 64)
    assert _run_amo_ops_case("RV64I+GC+*", 64) == _run_amo_ops_case(noisy_64, 64)
    assert _run_zicsr_case("RV64I+GC+*", 64) == _run_zicsr_case(noisy_generator_64(), 64)
    assert _run_zifencei_case("RV64I+GC+*", 64) == _run_zifencei_case(noisy_generator_64(), 64)
    assert _run_control_flow_case("RV64I+GC+*", 64) == _run_control_flow_case(noisy_generator_64(), 64)
    assert _run_multi_extension_mix_case("RV64I+GC+*", 64) == _run_multi_extension_mix_case(noisy_64, 64)
    assert _run_extension_combo_case("RV64I+GC+*", 64) == _run_extension_combo_case(noisy_generator_64(), 64)


def test_star_core_profile_parser_order_and_duplicate_noise_stability_rv32_rv64():
    """RV32I+GC+* and RV64I+GC+* should ignore ordering/duplication noise in parser inputs."""

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    reorder_32 = (
        "rv32i",
        "+",
        "ZICOND",
        "F",
        "B",
        "A",
        "junk",
        "M",
        "C",
        "D",
        "ZICSR",
        "B",
        "gc",
        "ZIFENCEI",
        "A",
        "+",
        "C",
        "",
    )
    reorder_64 = (
        "RV64I",
        "+",
        "zicond",
        "f",
        "b",
        "a",
        "junk",
        "gc",
        "c",
        "d",
        "zicsr",
        "b",
        "m",
        "zifencei",
        "a",
        "+",
        "c",
        "",
    )

    def duplicate_generator_32():
        yield " RV32I "
        yield "+"
        yield "GC"
        yield "M"
        yield "M"
        yield "A"
        yield "A"
        yield "B"
        yield "C"
        yield "C"
        yield "F"
        yield "D"
        yield "D"
        yield "B"
        yield "ZICSR"
        yield "ZIFENCEI"
        yield "ZIFENCEI"
        yield "ZICOND"
        yield "???"
        yield None

    def duplicate_generator_64():
        yield "RV64I"
        yield "+"
        yield "gc"
        yield "m"
        yield "a"
        yield "B"
        yield "b"
        yield "C"
        yield "d"
        yield "f"
        yield "F"
        yield "M"
        yield "ZICSR"
        yield "zicsr"
        yield "ZIFENCEI"
        yield "ZICOND"
        yield "???"
        yield " "
        yield None

    assert _run_base_case(explicit_32, 32) == _run_base_case(reorder_32, 32)
    assert _run_base_case(explicit_32, 32) == _run_base_case(duplicate_generator_32(), 32)
    assert _run_amo_ops_case(explicit_32, 32) == _run_amo_ops_case(reorder_32, 32)
    assert _run_amo_ops_case(explicit_32, 32) == _run_amo_ops_case(duplicate_generator_32(), 32)
    assert _run_multi_extension_mix_case(explicit_32, 32) == _run_multi_extension_mix_case(reorder_32, 32)
    assert _run_multi_extension_mix_case(explicit_32, 32) == _run_multi_extension_mix_case(duplicate_generator_32(), 32)

    assert _run_base_case(explicit_64, 64) == _run_base_case(reorder_64, 64)
    assert _run_base_case(explicit_64, 64) == _run_base_case(duplicate_generator_64(), 64)
    assert _run_amo_ops_case(explicit_64, 64) == _run_amo_ops_case(reorder_64, 64)
    assert _run_amo_ops_case(explicit_64, 64) == _run_amo_ops_case(duplicate_generator_64(), 64)
    assert _run_multi_extension_mix_case(explicit_64, 64) == _run_multi_extension_mix_case(reorder_64, 64)
    assert _run_multi_extension_mix_case(explicit_64, 64) == _run_multi_extension_mix_case(duplicate_generator_64(), 64)


def test_star_core_profile_parser_separators_and_case_noise_stability_rv32_rv64():
    """RV32I+GC+* and RV64I+GC+* should tolerate noisy separators and casing in parser tokens."""

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        "  rv32i  ",
        "+",
        "G",
        "C",
        ",",
        "m",
        "a",
        " ",
        "b",
        "c",
        "d",
        "f",
        "zicsr",
        "",
        "zifencei",
        "zicond",
        "???",
        "+",
    )
    noisy_64 = (
        "RV64I",
        "::",
        "g",
        "c",
        ",",
        "M",
        "A",
        "B",
        "C",
        "D",
        "F",
        "ZICOND",
        "ZIFENCEI",
        "ZICSR",
        " ",
        "??",
        "",
    )

    def noisy_generator_32():
        yield "RV32I"
        yield "+"
        yield "GC"
        yield "M"
        yield ","
        yield "A"
        yield "b"
        yield "junk"
        yield "C"
        yield "d"
        yield "F"
        yield "f"
        yield "D"
        yield "ZIFENCEI"
        yield "ZICSR"
        yield "ZICOND"
        yield " ??? "
        yield None

    def noisy_generator_64():
        yield " RV64I "
        yield "+"
        yield "gc"
        yield "m"
        yield "+"
        yield "A"
        yield "B"
        yield "c"
        yield "D"
        yield "f"
        yield "ZICSR"
        yield "ZIFENCEI"
        yield "ZICOND"
        yield ""
        yield "junk"
        yield None

    assert _run_base_case(explicit_32, 32) == _run_base_case(noisy_32, 32)
    assert _run_base_case(explicit_32, 32) == _run_base_case(noisy_generator_32(), 32)
    assert _run_control_flow_case(explicit_32, 32) == _run_control_flow_case(noisy_32, 32)
    assert _run_control_flow_case(explicit_32, 32) == _run_control_flow_case(noisy_generator_32(), 32)
    assert _run_zicsr_case(explicit_32, 32) == _run_zicsr_case(noisy_32, 32)
    assert _run_zifencei_case(explicit_32, 32) == _run_zifencei_case(noisy_32, 32)
    assert _run_zicond_case(explicit_32, 32) == _run_zicond_case(noisy_generator_32(), 32)

    assert _run_base_case(explicit_64, 64) == _run_base_case(noisy_64, 64)
    assert _run_base_case(explicit_64, 64) == _run_base_case(noisy_generator_64(), 64)
    assert _run_control_flow_case(explicit_64, 64) == _run_control_flow_case(noisy_64, 64)
    assert _run_control_flow_case(explicit_64, 64) == _run_control_flow_case(noisy_generator_64(), 64)
    assert _run_zicsr_case(explicit_64, 64) == _run_zicsr_case(noisy_64, 64)
    assert _run_zifencei_case(explicit_64, 64) == _run_zifencei_case(noisy_generator_64(), 64)
    assert _run_zicond_case(explicit_64, 64) == _run_zicond_case(noisy_generator_64(), 64)


def test_star_core_profile_parser_fullset_category_parity_rv32_rv64():
    """RV32I+GC+* and RV64I+GC+* noisy variants should preserve full category behavior."""

    explicit_32 = "RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    explicit_64 = "RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    noisy_32 = (
        " rv32i ",
        "+",
        "gc",
        "",
        "M",
        "junk",
        "A",
        "B",
        "C",
        "F",
        "D",
        "ZICSR",
        "ZIFENCEI",
        "ZICOND",
        "???",
    )
    noisy_64 = (
        " RV64I ",
        "+",
        "GC",
        "junk",
        "M",
        "A",
        "B",
        "C",
        "F",
        "D",
        "ZIFENCEI",
        "ZICSR",
        "ZICOND",
        "junk2",
    )

    def noisy_generator_32():
        yield "rv32i"
        yield "+"
        yield "gc"
        yield "M"
        yield "A"
        yield "B"
        yield "C"
        yield "junk"
        yield "F"
        yield "D"
        yield "ZICSR"
        yield "zifencei"
        yield "zicond"
        yield "???"
        yield None

    def noisy_generator_64():
        yield "RV64I"
        yield "+"
        yield "GC"
        yield "M"
        yield "A"
        yield "B"
        yield "C"
        yield "F"
        yield "D"
        yield "ZICSR"
        yield "ZIFENCEI"
        yield "ZICOND"
        yield None

    for helper in (
        _run_load_case,
        _run_store_case,
        _run_fp_case,
        _run_amo_ops_case,
        _run_multi_extension_mix_case,
        _run_control_flow_case,
        _run_zicsr_case,
        _run_zifencei_case,
        _run_zicond_case,
        _run_base_case,
    ):
        assert helper(explicit_32, 32) == helper(noisy_32, 32)
        assert helper(explicit_32, 32) == helper(noisy_generator_32(), 32)
        assert helper(explicit_64, 64) == helper(noisy_64, 64)
        assert helper(explicit_64, 64) == helper(noisy_generator_64(), 64)


def test_star_core_profile_parser_gc_vs_star_variants_rv32i_and_rv64i():
    """RV32I+GC profile should remain stable against noisy parser variants and star/no-star forms."""

    gc_32 = "RV32I+GC"
    star_32 = "RV32I+GC+*"
    gc_64 = "RV64I+GC"
    star_64 = "RV64I+GC+*"

    noisy_gc_32 = (
        "rv32i",
        "+",
        "gc",
        "M",
        "A",
        "B",
        "C",
        "junk",
        "D",
        "F",
        "ZICSR",
        "ZIFENCEI",
        "ZICOND",
        "???",
    )
    noisy_gc_64 = (
        "RV64I",
        "+",
        "GC",
        "A",
        "B",
        "M",
        "C",
        "junk",
        "D",
        "F",
        "zifencei",
        "zicsr",
        "zicond",
        "",
    )

    def noisy_generator_gc_32():
        yield " RV32I "
        yield "+"
        yield "gC"
        yield "M"
        yield "A"
        yield "junk"
        yield "B"
        yield "C"
        yield "D"
        yield "F"
        yield "ZICSR"
        yield "ZIFENCEI"
        yield "ZICOND"
        yield None

    def noisy_generator_gc_64():
        yield " RV64I "
        yield "+"
        yield "Gc"
        yield "M"
        yield "A"
        yield "B"
        yield "C"
        yield "D"
        yield "F"
        yield "junk"
        yield "ZIFENCEI"
        yield None

    noisy_star_32 = ("RV32I", "+", "GC", "+", "*", "???", "", "M", "A", "B", "C", "D", "F", "ZICSR", "ZIFENCEI", "ZICOND")
    noisy_star_64 = ("RV64I", "+", "GC", "+", "*", "???", "", "M", "A", "B", "C", "D", "F", "ZICSR", "ZIFENCEI", "ZICOND")

    # RV32I+GC should be stable against noisy parser forms and star-form expansion.
    assert _run_base_case(gc_32, 32) == _run_base_case(noisy_gc_32, 32)
    assert _run_base_case(gc_32, 32) == _run_base_case(noisy_generator_gc_32(), 32)
    assert _run_base_case(star_32, 32) == _run_base_case(noisy_star_32, 32)
    assert _run_base_case(star_32, 32) == _run_base_case(gc_32, 32)
    assert _run_extension_combo_case(star_32, 32) == _run_extension_combo_case(noisy_star_32, 32)
    assert _run_multi_extension_mix_case(star_32, 32) == _run_multi_extension_mix_case(noisy_star_32, 32)
    assert _run_control_flow_case(star_32, 32) == _run_control_flow_case(gc_32, 32)

    # RV64I+GC should be stable against noisy parser forms and star-form expansion.
    assert _run_base_case(gc_64, 64) == _run_base_case(noisy_gc_64, 64)
    assert _run_base_case(gc_64, 64) == _run_base_case(noisy_generator_gc_64(), 64)
    assert _run_base_case(star_64, 64) == _run_base_case(gc_64, 64)
    assert _run_base_case(star_64, 64) == _run_base_case(noisy_star_64, 64)
    assert _run_extension_combo_case(star_64, 64) == _run_extension_combo_case(noisy_star_64, 64)
    assert _run_multi_extension_mix_case(star_64, 64) == _run_multi_extension_mix_case(noisy_star_64, 64)
    assert _run_control_flow_case(star_64, 64) == _run_control_flow_case(gc_64, 64)


def test_star_profile_parser_tolerates_redundant_noisy_tokens_rv32i_and_rv64i():
    """RV32I+GC+* should normalize noisy redundant tokens consistently on parser input."""

    star_32 = "RV32I+GC+*"
    star_64 = "RV64I+GC+*"

    noisy_star_32 = (
        "",
        "RV32I",
        "+",
        "gc",
        "+",
        "*",
        "m",
        "M",
        "a",
        "A",
        "b",
        "B",
        "c",
        "C",
        "",
        "f",
        "F",
        "zicsr",
        "ZICSR",
        "zifencei",
        "ZIFENCEI",
        "zicond",
        "ZICOND",
        "???",
        "",
    )

    noisy_star_64 = (
        "RV64I",
        " ",
        "+",
        "GC",
        "+",
        "*",
        "M",
        "m",
        "A",
        "a",
        "B",
        "b",
        "C",
        "c",
        "f",
        "F",
        "d",
        "D",
        "zicsr",
        "ZICSR",
        "zifencei",
        "ZIFENCEI",
        "zicond",
        "ZICOND",
        "?",
        "???",
        "",
    )

    assert _run_extension_combo_case(star_32, 32) == _run_extension_combo_case(noisy_star_32, 32)
    assert _run_extension_combo_case(star_64, 64) == _run_extension_combo_case(noisy_star_64, 64)
    assert _run_base_case(star_32, 32) == _run_base_case(noisy_star_32, 32)
    assert _run_base_case(star_64, 64) == _run_base_case(noisy_star_64, 64)
    assert _run_control_flow_case(star_32, 32) == _run_control_flow_case(noisy_star_32, 32)
    assert _run_control_flow_case(star_64, 64) == _run_control_flow_case(noisy_star_64, 64)
    assert _run_multi_extension_mix_case(star_32, 32) == _run_multi_extension_mix_case(noisy_star_32, 32)
    assert _run_multi_extension_mix_case(star_64, 64) == _run_multi_extension_mix_case(noisy_star_64, 64)
