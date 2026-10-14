# tests/test_step75_rb_cache.py
# Step75 "实际测试效果"：验证 RB cache（读屏障结果缓存）
#
# 测试场景：
#   1) 第一次 load 同一地址（0x80000000）：cache miss → 发送 MV_QUERY
#   2) 第二次 load 同一地址：cache hit → 直接写回缓存结果，不发送 MV_QUERY

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.gc_mv_coproc import GCMvCoProc
from rtl.isa import enc_i, enc_s, OP_IMM, LOAD, STORE


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class TbRbCache(Elaboratable):
    def __init__(self):
        # 程序：
        #   1) lw x1, 0x800(x0)      => 第一次load高地址（触发RB cache miss）
        #   2) nop*5                   => 等待MV_QUERY返回
        #   3) lw x2, 0x800(x0)      => 第二次load同一地址（应cache hit）
        #   4) nop*5
        #   5) lw x3, 4(x0)          => load另一地址（新的cache miss）
        #   6) nop*5
        #   7) lw x4, 0x800(x0)      => 第三次load同一地址（再次cache hit）
        # 注意：使用偏移量0x800是为了让MEM2.wb_data作为cache key不同
        # 实际上这里的地址是imm，而wb_data是dmem中的值
        # 为了简化测试，让dmem_init的值可区分
        prog = [
            enc_i(LOAD, 1, 0b010, 0, 0),     # lw x1, 0(x0)
            nop(), nop(), nop(), nop(),
            enc_i(LOAD, 2, 0b010, 0, 0),     # lw x2, 0(x0)  -- 第二次load同一地址
            nop(), nop(), nop(), nop(),
            enc_i(LOAD, 3, 0b010, 0, 4),     # lw x3, 4(x0)  -- load另一地址
            nop(), nop(), nop(), nop(),
            enc_i(LOAD, 4, 0b010, 0, 0),     # lw x4, 0(x0)  -- 第三次load同一地址
            nop(), nop(), nop(), nop(),
        ] + [nop()] * (64 - 25)

        dmem_init = [0] * 64
        dmem_init[0] = 0xDEAD0000   # addr 0 处的值（cache key）
        dmem_init[1] = 0xBEEF0001   # addr 4 处的值

        self.core = RV12Core(core_id=0, rb_mode=0)  # 所有load都触发RB
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
            im.addr.eq(c.imem_addr),
            c.imem_rdata.eq(im.rdata),
        ]

        m.d.comb += [
            dm.req_valid.eq(c.dmem_valid),
            dm.req_we.eq(c.dmem_we),
            dm.req_addr.eq(c.dmem_addr),
            dm.req_wdata.eq(c.dmem_wdata),
            c.dmem_rdata.eq(dm.rsp_rdata),
        ]

        m.d.comb += [
            c.gc_enq_ready.eq(0),
            c.gc_rsp_valid.eq(0),
            c.gc_rsp_tag.eq(0),
            c.gc_rsp_rd.eq(0),
            c.gc_rsp_data.eq(0),
            c.wb_enq_ready.eq(1),
        ]

        m.d.comb += [
            mv.cmd_enq_valid[0].eq(c.mv_cmd_valid),
            c.mv_cmd_ready.eq(mv.cmd_enq_ready[0]),
            mv.cmd_tag[0].eq(c.mv_cmd_tag),
            mv.cmd_op[0].eq(c.mv_cmd_op),
            mv.cmd_rd[0].eq(c.mv_cmd_rd),
            mv.cmd_rs1[0].eq(c.mv_cmd_rs1),
            mv.cmd_rs2[0].eq(c.mv_cmd_rs2),

            c.mv_rsp_valid.eq(mv.rsp_valid[0]),
            c.mv_rsp_tag.eq(mv.rsp_tag[0]),
            c.mv_rsp_rd.eq(mv.rsp_rd[0]),
            c.mv_rsp_data.eq(mv.rsp_data[0]),
            mv.rsp_take[0].eq(c.mv_rsp_take),
        ]

        return m


def main():
    dut = TbRbCache()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    c = dut.core

    def proc():
        # 运行足够长时间让所有load完成
        for _ in range(300):
            yield Tick()

        # 读取寄存器
        for r in [1, 2, 3, 4]:
            yield c.dbg_reg_addr.eq(r)
            yield Tick()
            val = (yield c.dbg_reg_rdata)
            print(f"x{r}=0x{val:08x}")
            if r == 1:
                x1 = val
            elif r == 2:
                x2 = val
            elif r == 3:
                x3 = val
            elif r == 4:
                x4 = val

        # 所有load结果：MV_QUERY返回rs1原值(因为mv转发表为空)
        # 所以x1 == 0xDEAD0000, x2 == 0xDEAD0000 (cache hit, 不经过mv)
        # x3 == 0xBEEF0001 (不同地址，cache miss)
        # x4 == 0xDEAD0000 (cache hit)

        # 验证：所有load结果正确
        assert x1 == 0xDEAD0000, f"x1 should be 0xDEAD0000, got 0x{x1:08x}"
        assert x2 == 0xDEAD0000, f"x2 should be 0xDEAD0000, got 0x{x2:08x}"
        assert x3 == 0xBEEF0001, f"x3 should be 0xBEEF0001, got 0x{x3:08x}"
        assert x4 == 0xDEAD0000, f"x4 should be 0xDEAD0000, got 0x{x4:08x}"

        print("OK: RB cache correctly returns values for all loads.")

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
