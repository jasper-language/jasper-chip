# tests/test_reloc_updates_mv_map.py
# Step47 “实际测试效果”：验证 sweep 的 GC_RELOC 成功提交后，会通过 sideband
# 更新 mv forwarding table，使随后 load->MV_QUERY 的读屏障能够把旧 handle
# 改写为新 handle。
#
# 程序：
#   1) GC_NEW x1          => x1 = 1 (handle)
#   2) addi x2, x0, 10    => x2 = 10 (未分配槽，作为 dst)
#   3) GC_RELOC x1, x2    => move 1 -> 10，并触发 mv_upd(old=1,new=10)
#   4) sw x1, 0(x0)       => 写入旧 handle 1
#   5) lw x3, 0(x0)       => 读回 1，但读屏障应查询 mv 并写回 10

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.gc_sweep_coproc import GCSweepCoProc
from rtl.gc_mv_coproc import GCMvCoProc
from rtl.isa import enc_i, enc_s, OP_IMM, LOAD, STORE, enc_gc_new, enc_gc_reloc


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class TbRelocMap(Elaboratable):
    def __init__(self):
        prog = [
            enc_gc_new(rd=1),
            enc_i(OP_IMM, 2, 0b000, 0, 10),
            enc_gc_reloc(rs1_old=1, rs2_new=2),
            nop(), nop(), nop(), nop(),
            enc_s(STORE, 0b010, 0, 1, 0),   # sw x1, 0(x0)
            enc_i(LOAD, 3, 0b010, 0, 0),    # lw x3, 0(x0)
            nop(), nop(), nop(), nop(),
        ]
        # Pad to IMEM depth
        prog = prog + [nop()] * (128 - len(prog))

        dmem_init = [0] * 64
        self.core = RV12Core(core_id=0)
        self.imem = SimpleIMem(words=128, init=prog)
        self.dmem = SimpleDMem(words=64, init=dmem_init)
        self.sweep = GCSweepCoProc(ncores=1)
        self.mv = GCMvCoProc(ncores=1)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = c = self.core
        m.submodules.imem = im = self.imem
        m.submodules.dmem = dm = self.dmem
        m.submodules.sweep = sw = self.sweep
        m.submodules.mv = mv = self.mv

        # IMEM
        m.d.comb += [
            im.addr.eq(c.imem_addr),
            c.imem_rdata.eq(im.rdata),
        ]

        # DMEM
        m.d.comb += [
            dm.req_valid.eq(c.dmem_valid),
            dm.req_we.eq(c.dmem_we),
            dm.req_addr.eq(c.dmem_addr),
            dm.req_wdata.eq(c.dmem_wdata),
            c.dmem_rdata.eq(dm.rsp_rdata),
        ]

        # 写屏障：不接 scan，直接让 core 认为 downstream 永远 ready
        m.d.comb += c.wb_enq_ready.eq(1)

        # sweep 不接 scan out（本测试只需要 GC 指令）
        m.d.comb += [
            sw.card_in_valid.eq(0),
            sw.card_in_card_id.eq(0),
            sw.card_in_core_id.eq(0),
            sw.card_in_epoch.eq(0),
        ]

        # core <-> sweep
        m.d.comb += [
            sw.cmd_enq_valid[0].eq(c.gc_enq_valid),
            c.gc_enq_ready.eq(sw.cmd_enq_ready[0]),
            sw.cmd_tag[0].eq(c.gc_tag),
            sw.cmd_op[0].eq(c.gc_op),
            sw.cmd_rd[0].eq(c.gc_rd),
            sw.cmd_rs1[0].eq(c.gc_rs1),
            sw.cmd_rs2[0].eq(c.gc_rs2),

            c.gc_rsp_valid.eq(sw.rsp_valid[0]),
            c.gc_rsp_tag.eq(sw.rsp_tag[0]),
            c.gc_rsp_rd.eq(sw.rsp_rd[0]),
            c.gc_rsp_data.eq(sw.rsp_data[0]),
            sw.rsp_take[0].eq(c.gc_rsp_take),
        ]

        # core <-> mv (read barrier)
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

        # Step47: sweep reloc commit -> mv forwarding table update
        m.d.comb += [
            mv.upd_valid[0].eq(sw.mv_upd_valid[0]),
            mv.upd_old[0].eq(sw.mv_upd_old[0]),
            mv.upd_new[0].eq(sw.mv_upd_new[0]),
        ]

        return m


def main():
    dut = TbRelocMap()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    c = dut.core

    def proc():
        # 运行一段时间（包含：GC_NEW、GC_RELOC、store、load、mv 响应）
        for _ in range(200):
            yield Tick()

        # 读取 x1/x3
        yield c.dbg_reg_addr.eq(1)
        yield Tick()
        x1 = (yield c.dbg_reg_rdata)

        yield c.dbg_reg_addr.eq(3)
        yield Tick()
        x3 = (yield c.dbg_reg_rdata)

        print(f"x1={x1} x3={x3}")
        assert x1 != 0, "GC_NEW should allocate a non-zero handle in the model"
        assert x3 == 10, "read barrier should rewrite old handle 1 -> new handle 10"
        print("OK: GC_RELOC commit updated mv forwarding table; LW read barrier rewrote handle.")

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
