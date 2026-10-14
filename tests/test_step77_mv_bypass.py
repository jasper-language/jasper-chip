# tests/test_step77_mv_bypass.py
# Step77：MV 响应 / RB Cache 命中旁路
#
# 验证依赖指令不需要额外 stall 就能拿到 MV/RB 转发数据：
#   1) GC_MV_RELOC 建立映射 100→200
#   2) load dmem[0]（值=100）→ RB→MV_QUERY(100)→200（cache miss）
#   3) 紧接着的 addi 依赖 load 结果 → 验证 x4=x3+0=200（bypass 或 scoreboard+regfile）
#   4) 第二次 load 同一地址 → RB cache HIT
#   5) 再次验证依赖指令 x6=x5+0=200（cache bypass 或 scoreboard+regfile）

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.gc_mv_coproc import GCMvCoProc
from rtl.isa import enc_i, enc_s, OP_IMM, LOAD, STORE, enc_gc_mv_reloc


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class TbMvBypass(Elaboratable):
    def __init__(self):
        # 程序：
        #   x1=100 (old), x2=200 (new)
        #   GC_MV_RELOC x1,x2 → map 100→200
        #   sw x1, 0(x0) → dmem[0]=100
        #   lw x3, 0(x0) → RB miss → MV_QUERY → x3=200
        #   addi x4,x3,0 → dependent on x3 → x4=200 (测试旁路)
        #   lw x5, 0(x0) → RB cache HIT → x5=200
        #   addi x6,x5,0 → dependent on x5 (cache hit) → x6=200
        prog = [
            enc_i(OP_IMM, 1, 0b000, 0, 100),   # x1 = 100
            enc_i(OP_IMM, 2, 0b000, 0, 200),   # x2 = 200
            enc_gc_mv_reloc(rs1_old=1, rs2_new=2, rd=7),
            nop(), nop(), nop(),
            enc_s(STORE, 0b010, 0, 1, 0),       # sw x1, 0(x0)
            # cache miss + dependent
            enc_i(LOAD, 3, 0b010, 0, 0),        # lw x3, 0(x0) → RB miss → x3=200
            enc_i(OP_IMM, 4, 0b000, 3, 0),      # addi x4, x3, 0 → 测试旁路
            # cache hit + dependent
            enc_i(LOAD, 5, 0b010, 0, 0),        # lw x5, 0(x0) → RB cache HIT → x5=200
            enc_i(OP_IMM, 6, 0b000, 5, 0),      # addi x6, x5, 0 → 测试cache旁路
            nop(), nop(), nop(), nop(),
            nop(), nop(), nop(), nop(),
            nop(), nop(), nop(), nop(),
        ] + [nop()] * (64 - 24)

        dmem_init = [0] * 64

        self.core = RV12Core(core_id=0, rb_mode=0)
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
    dut = TbMvBypass()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    c = dut.core

    def proc():
        for cycle in range(300):
            yield Tick()
            mv_cmd = (yield c.mv_cmd_valid)
            mv_rsp_v = (yield c.mv_rsp_valid)
            mv_rsp_d = (yield c.mv_rsp_data)
            mv_rsp_rd = (yield c.mv_rsp_rd)
            mv_rsp_take_v = (yield c.mv_rsp_take)
            rb_fire_v = (yield c.dbg_rb_fire)
            rb_need_v = (yield c.dbg_rb_need_load)
            stall_v = (yield c.dbg_stall)
            stall_front_v = (yield c.dbg_stall_front)
            stall_dep_id2_v = (yield c.dbg_stall_dep_id2)
            pending_v = (yield c.dbg_pending_rd_mask)
            gc_fire_v = (yield c.dbg_gc_fire)
            is_valid_v = (yield c.dbg_is_valid)
            mem2_is_load = (yield c.dbg_mem2_is_load)
            mem2_rd = (yield c.dbg_mem2_rd)
            mem2_valid = (yield c.dbg_mem2_valid)
            id2_valid = (yield c.dbg_id2_valid)
            id2_is_load = (yield c.dbg_id2_is_load)
            id2_rd = (yield c.dbg_id2_rd)
            ex1_valid = (yield c.dbg_ex1_valid)
            ex1_is_load = (yield c.dbg_ex1_is_load)
            ex1_rd = (yield c.dbg_ex1_rd)
            mem1_valid = (yield c.dbg_mem1_valid)
            mem1_is_load = (yield c.dbg_mem1_is_load)
            mem1_rd = (yield c.dbg_mem1_rd)
            id1_valid = (yield c.dbg_id1_valid)
            id1_is_load = (yield c.dbg_id1_is_load)
            id1_rd = (yield c.dbg_id1_rd)
            if cycle < 45:
                print(f"c{cycle:3d}: pend={pending_v:08b} sf={stall_front_v} sdep={stall_dep_id2_v} id1:v={id1_valid} Ld={id1_is_load} rd={id1_rd}  id2:v={id2_valid} Ld={id2_is_load} rd={id2_rd}  ISv={is_valid_v}  ex1:v={ex1_valid} Ld={ex1_is_load} rd={ex1_rd}  mem1:v={mem1_valid} Ld={mem1_is_load} rd={mem1_rd}  mem2:v={mem2_valid} Ld={mem2_is_load} rd={mem2_rd}")

        # 读取寄存器
        for rd in range(1, 7):
            yield c.dbg_reg_addr.eq(rd)
            yield Tick()
            v = (yield c.dbg_reg_rdata)
            print(f"  x{rd}={v}")

        # 验证
        yield c.dbg_reg_addr.eq(1)
        yield Tick()
        x1 = (yield c.dbg_reg_rdata)
        yield c.dbg_reg_addr.eq(2)
        yield Tick()
        x2 = (yield c.dbg_reg_rdata)
        yield c.dbg_reg_addr.eq(3)
        yield Tick()
        x3 = (yield c.dbg_reg_rdata)
        yield c.dbg_reg_addr.eq(4)
        yield Tick()
        x4 = (yield c.dbg_reg_rdata)
        yield c.dbg_reg_addr.eq(5)
        yield Tick()
        x5 = (yield c.dbg_reg_rdata)
        yield c.dbg_reg_addr.eq(6)
        yield Tick()
        x6 = (yield c.dbg_reg_rdata)

        assert x1 == 100, f"x1 should be 100, got {x1}"
        assert x2 == 200, f"x2 should be 200, got {x2}"
        assert x3 == 200, f"x3 (load RB) should be 200, got {x3}"
        assert x4 == 200, f"x4 (dependent on MV response) should be 200, got {x4}"
        assert x5 == 200, f"x5 (RB cache hit) should be 200, got {x5}"
        assert x6 == 200, f"x6 (dependent on cache hit) should be 200, got {x6}"

        print("OK: MV response / RB cache bypass works correctly.")

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
