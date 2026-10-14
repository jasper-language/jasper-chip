from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def addi(rd, rs1, imm):
    return ((imm & 0xfff) << 20) | (rs1 << 15) | (rd << 7) | 0x13


def load_fp(fd, offset):
    return ((offset & 0xfff) << 20) | (2 << 12) | (fd << 7) | 0x07


def csrrw(csr, rs1):
    return (csr << 20) | (rs1 << 15) | (1 << 12) | 0x73


def csrrs(rd, csr):
    return (csr << 20) | (2 << 12) | (rd << 7) | 0x73


def vsetivli(avl, vta=0, vma=0):
    vtype = (vma << 7) | (vta << 6) | (2 << 3)
    return ((3 << 30) | (vtype << 20) | (avl << 15) |
            (7 << 12) | 0x57)


def vfmv_v_f(vd, fs1):
    return (0x17 << 26) | (1 << 25) | (fs1 << 15) | (5 << 12) | (vd << 7) | 0x57


def vmv_s_x(vd, rs1):
    return (0x10 << 26) | (1 << 25) | (rs1 << 15) | (6 << 12) | (vd << 7) | 0x57


def vfwcvt_x_f(vd, vs2, unsigned=False, fixed_rtz=False, vm=1):
    operand = (0x0E if unsigned else 0x0F) if fixed_rtz else (
        0x08 if unsigned else 0x09)
    return ((0x12 << 26) | (vm << 25) | (vs2 << 20) |
            (operand << 15) | (1 << 12) | (vd << 7) | 0x57)


NOP = addi(0, 0, 0)
JAL_ZERO = 0x0000006F


class Bench(Elaboratable):
    def __init__(self, config):
        p = [csrrw(0x001, 0), load_fp(1, 0)] + [NOP] * 4
        p += [vsetivli(4), vfmv_v_f(2, 1)]
        for rm, vd in enumerate((4, 6, 8, 10, 12)):
            p += [addi(1, 0, rm), csrrw(0x002, 1), vfwcvt_x_f(vd, 2)]
        p += [load_fp(1, 4)] + [NOP] * 4 + [vfmv_v_f(14, 1)]
        p += [vfwcvt_x_f(16, 14, fixed_rtz=True)]
        p += [vfwcvt_x_f(18, 14, unsigned=True), csrrs(20, 0x001)]
        p += [addi(1, 0, 5), vmv_s_x(0, 1), vsetivli(4, vma=1),
              vfwcvt_x_f(20, 2, vm=0)]
        p += [vsetivli(3, vta=1), addi(1, 0, 2), csrrw(0x008, 1),
              vfwcvt_x_f(22, 2, fixed_rtz=True)]
        p += [vsetivli(4), vfmv_v_f(25, 1),
              vfwcvt_x_f(24, 25, fixed_rtz=True)]
        p += [addi(1, 0, 6), csrrw(0x002, 1),
              vfwcvt_x_f(28, 2), vfwcvt_x_f(30, 2, fixed_rtz=True)]
        p += [NOP] * 24 + [JAL_ZERO]
        self.core = RV12Core(core_id=0, xlen=32, extensions=config)
        self.imem = SimpleIMem(words=len(p), init=p)
        self.dmem = SimpleDMem(words=8, init=[0x3FC00000, 0xBFC00000] + [0] * 6)

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


def run(config):
    dut = Bench(config)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    got = {}

    def process():
        traps = 0
        for _ in range(240):
            traps |= (yield dut.core.trap)
            yield Tick()
        for reg in (4, 6, 8, 10, 12, 16, 18, 20, 21, 22, 23, 24, 25, 28, 30):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            got[reg] = yield dut.core.dbg_vreg_rdata
        yield dut.core.dbg_reg_addr.eq(20)
        yield Tick()
        got["flags"] = yield dut.core.dbg_reg_rdata
        got["trap"] = traps

    sim.add_sync_process(process)
    sim.run()
    return got


def test_vfwcvt_float_to_integer_explicit_and_star():
    for config in ("RV32I+GC+V+D", "RV32I+GC+*"):
        g = run(config)
        expected = (2, 1, 1, 2, 2)
        assert tuple(g[r] & ((1 << 64) - 1) for r in (4, 6, 8, 10, 12)) == expected
        assert g[16] & ((1 << 64) - 1) == 0xFFFFFFFFFFFFFFFF
        assert g[18] == 0
        assert g["flags"] == 0x11
        assert g[20] == ((1 << 128) - (1 << 64)) | 2
        assert g[21] == ((1 << 128) - (1 << 64)) | 2
        assert g[22] == 0
        assert g[23] == (0xFFFFFFFFFFFFFFFF << 64) | 1
        assert g[24] == (0xFFFFFFFFFFFFFFFF << 64) | 0xFFFFFFFFFFFFFFFF
        assert g[25] == (0xFFFFFFFFFFFFFFFF << 64) | 0xFFFFFFFFFFFFFFFF
        assert g[28] == 0
        assert g[30] & ((1 << 64) - 1) == 1
        assert g["trap"] == 1
