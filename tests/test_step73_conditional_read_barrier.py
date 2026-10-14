# tests/test_step73_conditional_read_barrier.py
# Step73 "实际测试效果"：验证条件read barrier机制
#
# 测试三种rb_mode：
#   - mode=0：所有load都触发MV_QUERY
#   - mode=1：仅当load_addr[31]==1时触发（小地址下从不触发，直接WB写回）
#   - mode=2：仅当load_addr[30:28]!=0时触发（小地址下从不触发，直接WB写回）

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.gc_mv_coproc import GCMvCoProc
from rtl.isa import enc_i, OP_IMM, LOAD


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class TbConditionalRB(Elaboratable):
    def __init__(self, rb_mode=0):
        # 全部使用0(x0)的12位偏移，保证地址在DMEM范围内
        # lw x1, 0(x0)   => dmem[0] = 0x11111111
        # lw x2, 4(x0)   => dmem[1] = 0x22222222
        # lw x3, 8(x0)   => dmem[2] = 0x33333333
        # lw x4, 12(x0)  => dmem[3] = 0x44444444
        prog = [
            enc_i(LOAD, 1, 0b010, 0, 0),   # lw x1, 0(x0)
            enc_i(LOAD, 2, 0b010, 0, 4),   # lw x2, 4(x0)
            enc_i(LOAD, 3, 0b010, 0, 8),   # lw x3, 8(x0)
            enc_i(LOAD, 4, 0b010, 0, 12),  # lw x4, 12(x0)
            nop(), nop(), nop(), nop(),
        ] + [nop()] * (64 - 8)

        dmem_init = [0] * 64
        dmem_init[0] = 0x11111111
        dmem_init[1] = 0x22222222
        dmem_init[2] = 0x33333333
        dmem_init[3] = 0x44444444

        self.core = RV12Core(core_id=0, rb_mode=rb_mode)
        self.imem = SimpleIMem(words=64, init=prog)
        self.dmem = SimpleDMem(words=64, init=dmem_init)
        self.mv = GCMvCoProc(ncores=1)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = c = self.core
        m.submodules.imem = im = self.imem
        m.submodules.dmem = dm = self.dmem
        m.submodules.mv = mv = self.mv

        m.d.comb += [
            im.addr.eq(c.imem_addr), c.imem_rdata.eq(im.rdata),
            dm.req_valid.eq(c.dmem_valid), dm.req_we.eq(c.dmem_we),
            dm.req_addr.eq(c.dmem_addr), dm.req_wdata.eq(c.dmem_wdata),
            c.dmem_rdata.eq(dm.rsp_rdata),
            c.gc_enq_ready.eq(0), c.gc_rsp_valid.eq(0),
            c.gc_rsp_tag.eq(0), c.gc_rsp_rd.eq(0), c.gc_rsp_data.eq(0),
            c.wb_enq_ready.eq(1),
            mv.cmd_enq_valid[0].eq(c.mv_cmd_valid), c.mv_cmd_ready.eq(mv.cmd_enq_ready[0]),
            mv.cmd_tag[0].eq(c.mv_cmd_tag), mv.cmd_op[0].eq(c.mv_cmd_op),
            mv.cmd_rd[0].eq(c.mv_cmd_rd), mv.cmd_rs1[0].eq(c.mv_cmd_rs1), mv.cmd_rs2[0].eq(c.mv_cmd_rs2),
            c.mv_rsp_valid.eq(mv.rsp_valid[0]), c.mv_rsp_tag.eq(mv.rsp_tag[0]),
            c.mv_rsp_rd.eq(mv.rsp_rd[0]), c.mv_rsp_data.eq(mv.rsp_data[0]),
            mv.rsp_take[0].eq(c.mv_rsp_take),
        ]
        return m


def check_regs(c, expected):
    vals = {}
    for r in [1, 2, 3, 4]:
        yield c.dbg_reg_addr.eq(r)
        yield Tick()
        v = yield c.dbg_reg_rdata
        vals[r] = v
    print(f"  x1=0x{vals[1]:08x} x2=0x{vals[2]:08x} x3=0x{vals[3]:08x} x4=0x{vals[4]:08x}")
    for r, exp in expected.items():
        assert vals[r] == exp, f"x{r} mismatch: 0x{vals[r]:08x} != 0x{exp:08x}"

def test_rb_mode_0():
    """模式0：所有load触发RB，经MV返回正确结果"""
    print("=== rb_mode=0: all loads trigger RB ===")
    dut = TbConditionalRB(rb_mode=0)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    def proc():
        for _ in range(120):
            yield Tick()
        yield from check_regs(dut.core, {1: 0x11111111, 2: 0x22222222, 3: 0x33333333, 4: 0x44444444})
        print("  OK")
    sim.add_sync_process(proc)
    sim.run()


def test_rb_mode_1():
    """模式1：addr[31]==1才触发RB。小地址全为0，全部直接WB写回"""
    print("=== rb_mode=1: addr[31]==1 triggers RB (none for small addrs) ===")
    dut = TbConditionalRB(rb_mode=1)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    def proc():
        for _ in range(120):
            yield Tick()
        yield from check_regs(dut.core, {1: 0x11111111, 2: 0x22222222, 3: 0x33333333, 4: 0x44444444})
        print("  OK")
    sim.add_sync_process(proc)
    sim.run()


def test_rb_mode_2():
    """模式2：addr[30:28]!=0才触发RB。小地址全为0，全部直接WB写回"""
    print("=== rb_mode=2: addr[30:28]!=0 triggers RB (none for small addrs) ===")
    dut = TbConditionalRB(rb_mode=2)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    def proc():
        for _ in range(120):
            yield Tick()
        yield from check_regs(dut.core, {1: 0x11111111, 2: 0x22222222, 3: 0x33333333, 4: 0x44444444})
        print("  OK")
    sim.add_sync_process(proc)
    sim.run()


def main():
    test_rb_mode_0()
    test_rb_mode_1()
    test_rb_mode_2()
    print("\nAll conditional read barrier tests passed!")


if __name__ == "__main__":
    main()
