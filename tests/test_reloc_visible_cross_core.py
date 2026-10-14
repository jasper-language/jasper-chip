# tests/test_reloc_visible_cross_core.py
# Step50：跨核可见性（fast, no RV12Core simulation）
#
# 背景：Step49 把 MV forwarding table 从 per-core 改成 SoC 级共享。
# 关键性质：core0 的 GC_RELOC commit 更新 old->new 后，core1 的 MV_QUERY 必须能看到映射。
#
# 说明：使用 RV12Core + RRArbiter 的双核 SoC 级仿真在离线环境里过慢（Amaranth python-sim）。
# Step50 将测试收敛为“协处理器级端到端”，避免把仿真时间花在 12 级流水线与 IMEM 上。
#
# 运行：
#   python -m tests.test_reloc_visible_cross_core

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.gc_sweep_coproc import GCSweepCoProc
from rtl.gc_mv_coproc import GCMvCoProc, MV_QUERY
from rtl.isa import GC_NEW, GC_RELOC


class TbCrossCoreRelocFast(Elaboratable):
    def __init__(self):
        # Keep the design tiny so the Python-level simulator can elaborate quickly.
        # (The functional property under test doesn't require a large CAM.)
        self.sweep = GCSweepCoProc(ncores=2, entries=32, fifo_depth=2, engine_latency=0)
        self.mv    = GCMvCoProc(ncores=2, fifo_depth=2, map_depth=2, chase_depth=1)

    def elaborate(self, platform):
        m = Module()
        m.submodules.sweep = sw = self.sweep
        m.submodules.mv    = mv = self.mv

        # sweep 不接 scan/card 输入
        m.d.comb += [
            sw.card_in_valid.eq(0),
            sw.card_in_card_id.eq(0),
            sw.card_in_core_id.eq(0),
            sw.card_in_epoch.eq(0),
        ]

        # sweep reloc commit -> mv update (per-core pulse)
        for i in range(2):
            m.d.comb += [
                mv.upd_valid[i].eq(sw.mv_upd_valid[i]),
                mv.upd_old[i].eq(sw.mv_upd_old[i]),
                mv.upd_new[i].eq(sw.mv_upd_new[i]),
            ]

        return m


def main():
    dut = TbCrossCoreRelocFast()
    sw = dut.sweep
    mv = dut.mv

    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def proc():
        # init inputs
        for i in range(2):
            yield sw.cmd_enq_valid[i].eq(0)
            yield sw.cmd_tag[i].eq(0)
            yield sw.cmd_op[i].eq(0)
            yield sw.cmd_rd[i].eq(0)
            yield sw.cmd_rs1[i].eq(0)
            yield sw.cmd_rs2[i].eq(0)
            yield sw.rsp_take[i].eq(0)

            yield mv.cmd_enq_valid[i].eq(0)
            yield mv.cmd_tag[i].eq(0)
            yield mv.cmd_op[i].eq(0)
            yield mv.cmd_rd[i].eq(0)
            yield mv.cmd_rs1[i].eq(0)
            yield mv.cmd_rs2[i].eq(0)
            yield mv.rsp_take[i].eq(0)

        # Give the design a couple of cycles to settle internal FIFO resets.
        yield Tick()
        yield Tick()

        # ------------------------------
        # core0: enqueue GC_NEW
        # ------------------------------
        assert (yield sw.cmd_enq_ready[0]) == 1
        yield sw.cmd_tag[0].eq(1)
        yield sw.cmd_op[0].eq(GC_NEW)
        yield sw.cmd_rd[0].eq(1)
        yield sw.cmd_rs1[0].eq(0)
        yield sw.cmd_rs2[0].eq(0)
        yield sw.cmd_enq_valid[0].eq(1)
        yield Tick()  # enqueue
        yield sw.cmd_enq_valid[0].eq(0)

        # Wait for response (engine_latency=0 => a couple cycles)
        for _ in range(10):
            if (yield sw.rsp_valid[0]):
                break
            yield Tick()
        assert (yield sw.rsp_valid[0]) == 1, "GC_NEW rsp did not arrive"
        old_handle = (yield sw.rsp_data[0])
        trap = (yield sw.trap[0])
        assert trap == 0
        assert old_handle != 0
        # take
        yield sw.rsp_take[0].eq(1)
        yield Tick()
        yield sw.rsp_take[0].eq(0)

        # ------------------------------
        # core0: enqueue GC_RELOC(old->10)
        # ------------------------------
        assert (yield sw.cmd_enq_ready[0]) == 1
        yield sw.cmd_tag[0].eq(2)
        yield sw.cmd_op[0].eq(GC_RELOC)
        yield sw.cmd_rd[0].eq(0)
        yield sw.cmd_rs1[0].eq(old_handle)
        yield sw.cmd_rs2[0].eq(10)
        yield sw.cmd_enq_valid[0].eq(1)
        yield Tick()  # enqueue
        yield sw.cmd_enq_valid[0].eq(0)

        for _ in range(12):
            if (yield sw.rsp_valid[0]):
                break
            yield Tick()
        assert (yield sw.rsp_valid[0]) == 1, "GC_RELOC rsp did not arrive"
        trap2 = (yield sw.trap[0])
        assert trap2 == 0
        # take
        yield sw.rsp_take[0].eq(1)
        yield Tick()
        yield sw.rsp_take[0].eq(0)

        # Allow mv_upd sideband to be consumed and committed in MV table.
        for _ in range(4):
            yield Tick()

        # ------------------------------
        # core1: enqueue MV_QUERY(old) => 10
        # ------------------------------
        assert (yield mv.cmd_enq_ready[1]) == 1
        yield mv.cmd_tag[1].eq(0)  # delay=tag[1:0]=0, fastest
        yield mv.cmd_op[1].eq(MV_QUERY)
        yield mv.cmd_rd[1].eq(3)
        yield mv.cmd_rs1[1].eq(old_handle)
        yield mv.cmd_rs2[1].eq(0)
        yield mv.cmd_enq_valid[1].eq(1)
        yield Tick()
        yield mv.cmd_enq_valid[1].eq(0)

        # Wait for MV response (can be ooo but tag=0 => minimal delay)
        for _ in range(30):
            if (yield mv.rsp_valid[1]):
                break
            yield Tick()
        assert (yield mv.rsp_valid[1]) == 1, "MV_QUERY rsp did not arrive"
        rd = (yield mv.rsp_rd[1])
        data = (yield mv.rsp_data[1])
        trap3 = (yield mv.trap[1])
        assert trap3 == 0
        assert rd == 3

        print(f"old_handle={old_handle} mv_query(core1)->{data}")
        assert data == 10, "cross-core: mapping inserted by core0 RELOC must be visible to core1"
        print("OK: relocation mapping visible cross-core via shared MV table")

        yield mv.rsp_take[1].eq(1)
        yield Tick()
        yield mv.rsp_take[1].eq(0)

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
