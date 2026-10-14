from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def addi(rd, rs1, imm):
    return ((imm & 0xFFF) << 20) | (rs1 << 15) | (rd << 7) | 0x13


def vsetivli(avl, vta=0):
    vtype = (vta << 6) | (3 << 3) | 1
    return ((3 << 30) | (vtype << 20) | (avl << 15) |
            (7 << 12) | 0x57)


def vmv_v_v(vd, vs1, vs2=0):
    return ((0x17 << 26) | (1 << 25) | (vs2 << 20) |
            (vs1 << 15) | (vd << 7) | 0x57)


def vmv_v_x(vd, rs1, vs2=0):
    return ((0x17 << 26) | (1 << 25) | (vs2 << 20) |
            (rs1 << 15) | (4 << 12) | (vd << 7) | 0x57)


def vmv_v_i(vd, imm, vs2=0):
    return ((0x17 << 26) | (1 << 25) | (vs2 << 20) |
            ((imm & 0x1F) << 15) | (3 << 12) | (vd << 7) | 0x57)


def csrrw(csr, rs1):
    return (csr << 20) | (rs1 << 15) | (1 << 12) | 0x73


NOP = addi(0, 0, 0)
JAL_ZERO = 0x0000006F
ONES64 = (1 << 64) - 1


class Bench(Elaboratable):
    def __init__(self, extensions):
        p = [
            vsetivli(4),
            addi(1, 0, -1), vmv_v_x(8, 1),
            addi(1, 0, 0x123), vmv_v_x(10, 1),
            vmv_v_i(12, -2),
            vmv_v_v(14, 10),
            addi(2, 0, 2), csrrw(0x008, 2),
            addi(1, 0, 7), vmv_v_x(16, 1),
            vsetivli(3, vta=1), vmv_v_i(18, 1),
            vsetivli(4), vmv_v_i(21, 3),
        ]
        p += [NOP] * 16 + [JAL_ZERO]
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
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


def run(extensions):
    dut = Bench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    got = {}

    def process():
        traps = 0
        for _ in range(220):
            traps |= (yield dut.core.trap)
            yield Tick()
        for reg in range(8, 22):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            got[reg] = yield dut.core.dbg_vreg_rdata
        got["trap"] = traps

    sim.add_sync_process(process)
    sim.run()
    return got


def test_v_integer_scalar_moves_e64_lmul_restart_tail_and_legality():
    for extensions in ("RV32I+GC+V", "RV32I+GC+*"):
        g = run(extensions)
        assert g[8] == g[9] == (1 << 128) - 1
        pair_123 = (0x123 << 64) | 0x123
        assert g[10] == g[11] == pair_123
        pair_neg2 = ((ONES64 - 1) << 64) | (ONES64 - 1)
        assert g[12] == g[13] == pair_neg2
        assert g[14] == g[15] == pair_123
        assert g[16] == 0
        assert g[17] == (7 << 64) | 7
        assert g[18] == (1 << 64) | 1
        assert g[19] == (ONES64 << 64) | 1
        assert g[20] == g[21] == 0
        assert g["trap"] == 1
