from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def addi(rd, rs1, imm):
    return ((imm & 0xfff) << 20) | (rs1 << 15) | (rd << 7) | 0x13


def load_fp(fd, offset, is_f64=False):
    return ((offset & 0xfff) << 20) | ((3 if is_f64 else 2) << 12) | (fd << 7) | 0x07


def csrrw(csr, rs1):
    return (csr << 20) | (rs1 << 15) | (1 << 12) | 0x73


def vsetivli(vsew):
    return (3 << 30) | (vsew << 23) | (1 << 15) | (7 << 12) | 0x57


def vfmv_v_f(vd, fs1):
    return (0x17 << 26) | (1 << 25) | (fs1 << 15) | (5 << 12) | (vd << 7) | 0x57


def vfcvt(vd, vs2, unsigned=False, fixed_rtz=False):
    operand = (6 if unsigned else 7) if fixed_rtz else (0 if unsigned else 1)
    return ((0x12 << 26) | (1 << 25) | (vs2 << 20) |
            (operand << 15) | (1 << 12) | (vd << 7) | 0x57)


NOP = addi(0, 0, 0)


class Bench(Elaboratable):
    def __init__(self, config):
        p = [load_fp(1, 0)] + [NOP] * 4
        p += [vsetivli(2), vfmv_v_f(2, 1)]
        for rm, vd in enumerate((4, 6, 8, 10, 12)):
            p += [addi(1, 0, rm), csrrw(0x002, 1), vfcvt(vd, 2)]
        p += [load_fp(1, 4)] + [NOP] * 4 + [vfmv_v_f(14, 1)]
        for rm, vd in ((0, 16), (2, 18), (3, 20)):
            p += [addi(1, 0, rm), csrrw(0x002, 1), vfcvt(vd, 14)]
        p += [addi(1, 0, 0), csrrw(0x002, 1), vfcvt(22, 2, True)]
        p += [load_fp(1, 8, True)] + [NOP] * 4
        p += [vsetivli(3), vfmv_v_f(24, 1)]
        p += [vfcvt(26, 24), addi(1, 0, 1), csrrw(0x002, 1),
              vfcvt(28, 24)]
        p += [addi(1, 0, 6), csrrw(0x002, 1),
              vfcvt(30, 24, fixed_rtz=True), vfcvt(2, 24)]
        p += [NOP] * 20
        self.core = RV12Core(core_id=0, xlen=32, extensions=config)
        self.imem = SimpleIMem(words=len(p), init=p)
        self.dmem = SimpleDMem(words=16, init=[
            0x3fc00000, 0xbfc00000, 0x00000000, 0x3ff80000,
        ] + [0] * 12)

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
        for _ in range(170):
            traps |= (yield dut.core.trap)
            yield Tick()
        for reg in (4, 6, 8, 10, 12, 16, 18, 20, 22, 26, 28, 30):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            got[reg] = yield dut.core.dbg_vreg_rdata
        got["trap"] = traps

    sim.add_sync_process(process)
    sim.run()
    return got


def test_vfcvt_dynamic_rounding_explicit_and_star():
    for config in ("RV32I+GC+V+D", "RV32I+GC+*"):
        g = run(config)
        assert tuple(g[r] & 0xffffffff for r in (4, 6, 8, 10, 12)) == (2, 1, 1, 2, 2)
        assert tuple(g[r] & 0xffffffff for r in (16, 18, 20)) == (
            0xfffffffe, 0xfffffffe, 0xffffffff)
        assert g[22] & 0xffffffff == 2
        assert g[26] & ((1 << 64) - 1) == 2
        assert g[28] & ((1 << 64) - 1) == 1
        assert g[30] & ((1 << 64) - 1) == 1
        assert g["trap"] == 1
