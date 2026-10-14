from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def addi(rd, rs1, imm):
    return ((imm & 0xfff) << 20) | (rs1 << 15) | (rd << 7) | 0x13


def lui(rd, imm20):
    return (imm20 << 12) | (rd << 7) | 0x37


def csrrw(csr, rs1):
    return (csr << 20) | (rs1 << 15) | (1 << 12) | 0x73


def csrrs(rd, csr):
    return (csr << 20) | (2 << 12) | (rd << 7) | 0x73


def vsetivli(avl, vlmul=0, vta=0, vma=0, rd=0):
    vtype = (vma << 7) | (vta << 6) | (2 << 3) | vlmul
    return ((3 << 30) | (vtype << 20) | (avl << 15) |
            (7 << 12) | (rd << 7) | 0x57)


def vmv_v_x(vd, rs1):
    return (0x17 << 26) | (1 << 25) | (rs1 << 15) | (4 << 12) | (vd << 7) | 0x57


def vmv_s_x(vd, rs1):
    return (0x10 << 26) | (1 << 25) | (rs1 << 15) | (6 << 12) | (vd << 7) | 0x57


def vfwcvt_f_x(vd, vs2, unsigned=False, vm=1):
    operand = 0x0A if unsigned else 0x0B
    return ((0x12 << 26) | (vm << 25) | (vs2 << 20) |
            (operand << 15) | (1 << 12) | (vd << 7) | 0x57)


NOP = addi(0, 0, 0)


class Bench(Elaboratable):
    def __init__(self, config):
        p = [csrrw(0x001, 0), lui(1, 0x01000), addi(1, 1, 1),
             vsetivli(4), vmv_v_x(2, 1),
             vmv_v_x(25, 1), vfwcvt_f_x(24, 25),
             vfwcvt_f_x(4, 2)]
        p += [addi(1, 0, -1), vmv_v_x(6, 1), vfwcvt_f_x(8, 6),
              vfwcvt_f_x(12, 6, True)]
        p += [addi(1, 0, 5), vmv_s_x(0, 1), vsetivli(4, vma=1),
              vfwcvt_f_x(16, 2, vm=0)]
        p += [vsetivli(3, vta=1), addi(1, 0, 2), csrrw(0x008, 1),
              vfwcvt_f_x(20, 2)]
        p += [csrrs(20, 0x001)]
        p += [addi(1, 0, 6), csrrw(0x002, 1), vfwcvt_f_x(24, 2)]
        p += [NOP] * 24 + [0x0000006F]
        self.core = RV12Core(core_id=0, xlen=32, extensions=config)
        self.imem = SimpleIMem(words=len(p), init=p)
        self.dmem = SimpleDMem(words=8, init=[0] * 8)

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
        for _ in range(180):
            traps |= (yield dut.core.trap)
            yield Tick()
        for reg in (4, 5, 8, 9, 12, 13, 16, 17, 20, 21, 24, 25):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            got[reg] = yield dut.core.dbg_vreg_rdata
        yield dut.core.dbg_reg_addr.eq(20)
        yield Tick()
        got["fflags"] = yield dut.core.dbg_reg_rdata
        got["trap"] = traps

    sim.add_sync_process(process)
    sim.run()
    return got


def test_vfwcvt_integer_to_float_explicit_and_star():
    for config in ("RV32I+GC+V+D", "RV32I+GC+*"):
        g = run(config)
        exact = 0x4170000010000000
        assert g[4] == (exact << 64) | exact
        assert g[5] == (exact << 64) | exact
        assert g[8] == int("bff0000000000000" * 2, 16)
        assert g[12] == int("41efffffffe00000" * 2, 16)
        assert g[16] == int("ffffffffffffffff4170000010000000" * 1, 16)
        assert g[17] == int("ffffffffffffffff4170000010000000" * 1, 16)
        assert g[20] == 0
        assert g[21] == (0xffffffffffffffff << 64) | exact
        assert g[24] == (exact << 64) | exact
        assert g[25] == (exact << 64) | exact
        assert g["fflags"] == 0
        assert g["trap"] == 1
