from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def addi(rd, rs1, imm):
    return ((imm & 0xfff) << 20) | (rs1 << 15) | (rd << 7) | 0x13


def fld(fd, offset, is_f64=False):
    return ((offset & 0xfff) << 20) | ((3 if is_f64 else 2) << 12) | (fd << 7) | 0x07


def csrrw(rd, csr, rs1):
    return (csr << 20) | (rs1 << 15) | (1 << 12) | (rd << 7) | 0x73


def csrrs(rd, csr):
    return (csr << 20) | (2 << 12) | (rd << 7) | 0x73


def vsetivli(avl, vsew):
    return (3 << 30) | (vsew << 23) | (avl << 15) | (7 << 12) | 0x57


def vfmv_v_f(vd, fs1):
    return (0x17 << 26) | (1 << 25) | (fs1 << 15) | (5 << 12) | (vd << 7) | 0x57


def vfcvt_rtz(vd, vs2, unsigned=False, vm=1):
    operand = 6 if unsigned else 7
    return ((0x12 << 26) | (vm << 25) | (vs2 << 20) |
            (operand << 15) | (1 << 12) | (vd << 7) | 0x57)


NOP = addi(0, 0, 0)


class Bench(Elaboratable):
    def __init__(self, config):
        words = [0x3ff33333, 0xbff33333, 0x7f800000, 0x7fc00000,
                 0xbf000000, 0xbfc00000, 0, 0,
                 0x00000000, 0x43e00000, 0x00000000, 0xc3e00000]
        p = [vsetivli(1, 2)]
        cases = [(0, 2, False, 4, 20), (4, 2, False, 6, 21),
                 (8, 2, False, 8, 22), (12, 2, False, 10, 23),
                 (16, 2, True, 12, 24), (20, 2, True, 14, 25)]
        for offset, _, unsigned, vd, rd in cases:
            p += [fld(1, offset)] + [NOP] * 4
            p += [vfmv_v_f(2, 1), csrrw(0, 0x001, 0),
                  vfcvt_rtz(vd, 2, unsigned), csrrs(rd, 0x001)]
        p += [vsetivli(1, 3)]
        for offset, vd, rd in ((32, 16, 26), (40, 18, 27)):
            p += [fld(1, offset, True)] + [NOP] * 4
            p += [vfmv_v_f(2, 1), csrrw(0, 0x001, 0),
                  vfcvt_rtz(vd, 2), csrrs(rd, 0x001)]
        p += [NOP] * 24
        self.core = RV12Core(core_id=0, xlen=32, extensions=config)
        self.imem = SimpleIMem(words=len(p), init=p)
        self.dmem = SimpleDMem(words=32, init=words + [0] * 20)

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
        for _ in range(180):
            yield Tick()
        for reg in (4, 6, 8, 10, 12, 14, 16, 18):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            got[f"v{reg}"] = yield dut.core.dbg_vreg_rdata
        for reg in range(20, 28):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            got[f"x{reg}"] = yield dut.core.dbg_reg_rdata

    sim.add_sync_process(process)
    sim.run()
    return got


def test_vfcvt_rtz_float_to_integer_explicit_and_star():
    for config in ("RV32I+GC+V+D", "RV32I+GC+*"):
        got = run(config)
        assert got["v4"] & 0xffffffff == 1
        assert got["v6"] & 0xffffffff == 0xffffffff
        assert got["v8"] & 0xffffffff == 0x7fffffff
        assert got["v10"] & 0xffffffff == 0x7fffffff
        assert got["v12"] & 0xffffffff == 0
        assert got["v14"] & 0xffffffff == 0
        assert got["v16"] & ((1 << 64) - 1) == 0x7fffffffffffffff
        assert got["v18"] & ((1 << 64) - 1) == 0x8000000000000000
        assert tuple(got[f"x{i}"] for i in range(20, 28)) == (
            1, 1, 0x10, 0x10, 1, 0x10, 0x10, 0)
