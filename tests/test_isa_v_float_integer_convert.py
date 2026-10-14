from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleDMem, SimpleIMem


def addi(rd, rs1, imm):
    return ((imm & 0xfff) << 20) | (rs1 << 15) | (rd << 7) | 0x13


def lui(rd, imm20):
    return (imm20 << 12) | (rd << 7) | 0x37


def csrrw(rd, csr, rs1):
    return (csr << 20) | (rs1 << 15) | (1 << 12) | (rd << 7) | 0x73


def csrrs(rd, csr):
    return (csr << 20) | (2 << 12) | (rd << 7) | 0x73


def vsetivli(avl, vsew, vta=0, vma=0):
    vtype = (vma << 7) | (vta << 6) | (vsew << 3)
    return ((0x3 << 30) | (vtype << 20) | (avl << 15) |
            (7 << 12) | 0x57)


def vmv_v_x(vd, rs1):
    return (0x17 << 26) | (1 << 25) | (rs1 << 15) | (4 << 12) | (vd << 7) | 0x57


def vmv_s_x(vd, rs1):
    return (0x10 << 26) | (1 << 25) | (rs1 << 15) | (6 << 12) | (vd << 7) | 0x57


def fld(fd, rs1, offset):
    return ((offset & 0xfff) << 20) | (rs1 << 15) | (3 << 12) | (fd << 7) | 0x07


def vfmv_v_f(vd, fs1):
    return (0x17 << 26) | (1 << 25) | (fs1 << 15) | (5 << 12) | (vd << 7) | 0x57


def vfcvt_f_x(vd, vs2, unsigned=False, vm=1):
    operand = 2 if unsigned else 3
    return (0x12 << 26) | (vm << 25) | (vs2 << 20) | (operand << 15) | (1 << 12) | (vd << 7) | 0x57


NOP = addi(0, 0, 0)


class _Bench(Elaboratable):
    def __init__(self, program, config, dmem_words):
        self.core = RV12Core(core_id=0, xlen=32, extensions=config)
        self.imem = SimpleIMem(words=len(program), init=program)
        init = list(dmem_words or [])
        self.dmem = SimpleDMem(words=32, init=init + [0] * (32 - len(init)))

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


def run(program, config, dmem_words=None, cycles=180):
    dut = _Bench(program + [NOP] * 32, config, dmem_words)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    observed = {}

    def process():
        traps = 0
        for _ in range(cycles):
            traps |= (yield dut.core.trap)
            yield Tick()
        for reg in (3, 4, 5, 6, 7, 8, 9, 12, 14, 18, 20, 24, 26, 28):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            observed[f"v{reg}"] = (yield dut.core.dbg_vreg_rdata)
        for reg in range(20, 24):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            observed[f"x{reg}"] = (yield dut.core.dbg_reg_rdata)
        observed["trap"] = traps

    sim.add_sync_process(process)
    sim.run()
    return observed


def test_vfcvt_integer_to_float_rounding_mask_tail_and_vstart():
    p = []
    p += [lui(1, 0x01000), addi(1, 1, 1), vsetivli(4, 2), vmv_v_x(2, 1)]
    for rm, vd, flag_rd in ((0, 4, 20), (3, 6, 21), (4, 8, 22)):
        p += [addi(1, 0, rm), csrrw(0, 0x002, 1),
              csrrw(0, 0x001, 0), vfcvt_f_x(vd, 2),
              csrrs(flag_rd, 0x001)]
    p += [lui(1, 0xff000), addi(1, 1, -1), vmv_v_x(10, 1)]
    p += [addi(1, 0, 2), csrrw(0, 0x002, 1), vfcvt_f_x(12, 10)]
    p += [addi(1, 0, 3), csrrw(0, 0x002, 1), vfcvt_f_x(14, 10)]
    p += [addi(1, 0, -1), vmv_v_x(16, 1)]
    p += [addi(1, 0, 1), csrrw(0, 0x002, 1), vfcvt_f_x(18, 16, True)]
    p += [addi(1, 0, 0), csrrw(0, 0x002, 1), vfcvt_f_x(20, 16, True)]
    p += [addi(1, 0, 5), vmv_v_x(22, 1), csrrw(0, 0x001, 0),
          vfcvt_f_x(24, 22), csrrs(23, 0x001)]
    p += [addi(1, 0, 5), vmv_s_x(0, 1), vsetivli(4, 2, vma=1),
          vfcvt_f_x(26, 2, vm=0)]
    p += [vsetivli(3, 2, vta=1), addi(1, 0, 2), csrrw(0, 0x008, 1),
          vfcvt_f_x(28, 2)]
    p += [addi(1, 0, 6), csrrw(0, 0x002, 1), vfcvt_f_x(30, 2)]
    p += [NOP] * 16
    got = run(p, "RV32I+GC+V")
    assert got["v4"] == int("4b800000" * 4, 16)
    assert got["v6"] == int("4b800001" * 4, 16)
    assert got["v8"] == int("4b800001" * 4, 16)
    assert got["v12"] == int("cb800001" * 4, 16)
    assert got["v14"] == int("cb800000" * 4, 16)
    assert got["v18"] == int("4f7fffff" * 4, 16)
    assert got["v20"] == int("4f800000" * 4, 16)
    assert got["v24"] == int("40a00000" * 4, 16)
    assert got["v26"] == int("ffffffff4b800000ffffffff4b800000", 16)
    assert got["v28"] == int("ffffffff4b8000000000000000000000", 16)
    assert (got["x20"], got["x21"], got["x22"], got["x23"]) == (1, 1, 1, 0)
    assert got["trap"] == 1


def test_vfcvt_64_bit_precision_and_star_configuration():
    words = [0x00000001, 0x00200000, 0xffffffff, 0xffdfffff]
    p = [fld(1, 0, 0)] + [NOP] * 6
    p += [vsetivli(1, 3), vfmv_v_f(30, 1)]
    p += [csrrw(0, 0x001, 0), vfcvt_f_x(3, 30), csrrs(20, 0x001)]
    p += [addi(1, 0, 3), csrrw(0, 0x002, 1), vfcvt_f_x(5, 30)]
    p += [fld(1, 0, 8)] + [NOP] * 6 + [vfmv_v_f(30, 1)]
    p += [addi(1, 0, 2), csrrw(0, 0x002, 1), vfcvt_f_x(7, 30)]
    p += [addi(1, 0, 3), csrrw(0, 0x002, 1), vfcvt_f_x(9, 30)]
    p += [NOP] * 16
    for config in ("RV32I+GC+V+D", "RV32I+GC+*"):
        got = run(p, config, words)
        assert got["v3"] & ((1 << 64) - 1) == 0x4340000000000000
        assert got["v5"] & ((1 << 64) - 1) == 0x4340000000000001
        assert got["v7"] & ((1 << 64) - 1) == 0xc340000000000001
        assert got["v9"] & ((1 << 64) - 1) == 0xc340000000000000
        assert got["x20"] == 1
        assert got["trap"] == 0


def test_vfcvt_rejects_reserved_rm_and_missing_fp_width():
    fp64_without_d = [vsetivli(1, 3), vfcvt_f_x(4, 2)] + [NOP] * 8
    assert run(fp64_without_d, "RV32I+F+V")["trap"] == 1
