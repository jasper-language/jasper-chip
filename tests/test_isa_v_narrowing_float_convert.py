from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def addi(rd, rs1, imm):
    return ((imm & 0xFFF) << 20) | (rs1 << 15) | (rd << 7) | 0x13


def fld(fd, offset):
    return ((offset & 0xFFF) << 20) | (3 << 12) | (fd << 7) | 0x07


def csrrw(csr, rs1):
    return (csr << 20) | (rs1 << 15) | (1 << 12) | 0x73


def csrrs(rd, csr):
    return (csr << 20) | (2 << 12) | (rd << 7) | 0x73


def vsetivli(avl, vsew, vlmul=0, vta=0, vma=0):
    vtype = (vma << 7) | (vta << 6) | (vsew << 3) | vlmul
    return ((3 << 30) | (vtype << 20) | (avl << 15) |
            (7 << 12) | 0x57)


def vfmv_v_f(vd, fs1):
    return ((0x17 << 26) | (1 << 25) | (fs1 << 15) |
            (5 << 12) | (vd << 7) | 0x57)


def vmv_s_x(vd, rs1):
    return ((0x10 << 26) | (1 << 25) | (rs1 << 15) |
            (6 << 12) | (vd << 7) | 0x57)


def vfncvt_f_f(vd, vs2, rod=False, vm=1):
    return ((0x12 << 26) | (vm << 25) | (vs2 << 20) |
            ((0x15 if rod else 0x14) << 15) | (1 << 12) |
            (vd << 7) | 0x57)


NOP = addi(0, 0, 0)
JAL_ZERO = 0x0000006F


def repeat32(value):
    return sum(value << (32 * lane) for lane in range(4))


class Bench(Elaboratable):
    def __init__(self, extensions):
        p = [csrrw(0x001, 0), fld(1, 0)] + [NOP] * 4
        p += [vsetivli(4, 3, 1), vfmv_v_f(2, 1), vsetivli(4, 2)]
        for rm, vd in enumerate(range(4, 9)):
            p += [addi(1, 0, rm), csrrw(0x002, 1), vfncvt_f_f(vd, 2)]
        p += [vfncvt_f_f(9, 2, rod=True), csrrs(20, 0x001)]
        p += [fld(1, 8)] + [NOP] * 4
        p += [vsetivli(4, 3, 1), vfmv_v_f(10, 1), vsetivli(4, 2),
              vfncvt_f_f(12, 10), vfncvt_f_f(13, 10, rod=True),
              csrrs(21, 0x001)]
        p += [csrrw(0x001, 0), fld(1, 16)] + [NOP] * 4
        p += [vsetivli(4, 3, 1), vfmv_v_f(14, 1), vsetivli(4, 2),
              vfncvt_f_f(16, 14), csrrs(22, 0x001)]
        p += [csrrw(0x001, 0), fld(1, 24)] + [NOP] * 4
        p += [vsetivli(4, 3, 1), vfmv_v_f(18, 1), vsetivli(4, 2),
              vfncvt_f_f(20, 18), csrrs(23, 0x001)]
        p += [fld(1, 32)] + [NOP] * 4
        p += [vsetivli(4, 3, 1), vfmv_v_f(22, 1), vsetivli(4, 2),
              addi(1, 0, 5), vmv_s_x(0, 1), vsetivli(4, 2, vma=1),
              vfncvt_f_f(24, 22, vm=0),
              vsetivli(3, 2, vta=1), addi(1, 0, 2), csrrw(0x008, 1),
              vfncvt_f_f(25, 22),
              vsetivli(4, 2), addi(1, 0, 6), csrrw(0x002, 1),
              vfncvt_f_f(26, 22, rod=True),
              vfncvt_f_f(22, 22, rod=True)]
        p += [NOP] * 24 + [JAL_ZERO]

        values = [0x3FF0000010000000, 0x0000000000000001,
                  0x7FF0000000000001, 0x7FF8000000000001,
                  0x3FF8000000000000]
        data = []
        for bits in values:
            data += [bits & 0xFFFFFFFF, bits >> 32]
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(p), init=p)
        self.dmem = SimpleDMem(words=16, init=data + [0] * 6)

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


def run(extensions):
    dut = Bench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    got = {}

    def process():
        traps = 0
        for _ in range(420):
            traps |= (yield dut.core.trap)
            yield Tick()
        for reg in (4, 5, 6, 7, 8, 9, 12, 13, 16, 20, 22, 24, 25, 26):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            got[reg] = yield dut.core.dbg_vreg_rdata
        for reg in (20, 21, 22, 23):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            got[f"x{reg}"] = yield dut.core.dbg_reg_rdata
        got["trap"] = traps

    sim.add_sync_process(process)
    sim.run()
    return got


def test_vfncvt_float_ieee_round_odd_mask_restart_overlap_and_star():
    for extensions in ("RV32I+GC+V+D", "RV32I+GC+*"):
        g = run(extensions)
        for reg, value in zip(range(4, 9),
                              (0x3F800000, 0x3F800000, 0x3F800000,
                               0x3F800001, 0x3F800001)):
            assert g[reg] == repeat32(value)
        assert g[9] == repeat32(0x3F800001)
        assert g[12] == 0
        assert g[13] == repeat32(1)
        assert g[16] == repeat32(0x7FC00000)
        assert g[20] == repeat32(0x7FC00000)
        assert g["x20"] == 0x01
        assert g["x21"] == 0x03
        assert g["x22"] == 0x10
        assert g["x23"] == 0
        assert g[24] == sum(value << (32 * lane) for lane, value in
                            enumerate((0x3FC00000, 0xFFFFFFFF,
                                       0x3FC00000, 0xFFFFFFFF)))
        assert g[25] == sum(value << (32 * lane) for lane, value in
                            enumerate((0, 0, 0x3FC00000, 0xFFFFFFFF)))
        assert g[26] == repeat32(0x3FC00000)
        assert g[22] == repeat32(0x3FC00000)
        assert g["trap"] == 0
