# tests/test_scan_to_sweep_pipeline.py
# -*- coding: utf-8 -*-
#
# Step21 实测：把 scan 的 out_q（card stream）接到 sweep，形成最小“跨协处理器闭环”。
#
# 场景：2 核注入写屏障事件，其中 core0 对同一卡重复写 3 次（应被 scan 去重），
#       core1 写 1 次。期望 sweep 侧最终只“标记”到 2 条 card 记录。
#
# 这个测试不依赖 CPU 程序执行，只验证：
#   write-barrier events -> scan consume -> out_q -> sweep consume/计数

from amaranth import Module, Elaboratable
from amaranth.sim import Simulator, Tick

from rtl.gc_scan_coproc import GCScanCoProc
from rtl.gc_sweep_coproc import GCSweepCoProc


class DUT(Elaboratable):
    def __init__(self):
        self.scan = GCScanCoProc(
            ncores=2,
            fifo_depth=4,
            consume_every=1,
            batch_size=1,
            dedup_enable=True,
            cardset_size=8,
            out_depth=8,
        )
        self.sweep = GCSweepCoProc(ncores=2)

    def elaborate(self, platform):
        m = Module()
        m.submodules.scan = self.scan
        m.submodules.sweep = self.sweep

        # scan out -> sweep in
        m.d.comb += [
            self.sweep.card_in_valid.eq(self.scan.out_valid),
            self.scan.out_ready.eq(self.sweep.card_in_ready),
            self.sweep.card_in_card_id.eq(self.scan.out_card_id),
            self.sweep.card_in_core_id.eq(self.scan.out_core_id),
            self.sweep.card_in_epoch.eq(self.scan.out_epoch),
        ]

        return m


def main():
    dut = DUT()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def proc():
        # cycle 1：core0 写 card=5（应入队） + core1 写 card=7（应入队）
        yield dut.scan.wb_valid[0].eq(1)
        yield dut.scan.wb_addr[0].eq(5)
        yield dut.scan.wb_data[0].eq(111)
        yield dut.scan.wb_valid[1].eq(1)
        yield dut.scan.wb_addr[1].eq(7)
        yield dut.scan.wb_data[1].eq(222)
        yield Tick()

        # cycle 2：core0 重复写同一卡（应被去重丢弃，dup_drop++）
        yield dut.scan.wb_valid[1].eq(0)
        yield dut.scan.wb_valid[0].eq(1)
        yield dut.scan.wb_addr[0].eq(5)
        yield Tick()

        # cycle 3：再重复一次
        yield dut.scan.wb_valid[0].eq(1)
        yield dut.scan.wb_addr[0].eq(5)
        yield Tick()

        # 拉低 valid
        yield dut.scan.wb_valid[0].eq(0)
        yield dut.scan.wb_valid[1].eq(0)

        # 等待 scan 消费并输出到 sweep
        for _ in range(30):
            yield Tick()

        total = int((yield dut.sweep.mark_count_total))
        c0 = int((yield dut.sweep.mark_count_core[0]))
        c1 = int((yield dut.sweep.mark_count_core[1]))

        print("mark_total=", total, "core0=", c0, "core1=", c1)
        print("last:", int((yield dut.sweep.last_core_id)), int((yield dut.sweep.last_card_id)), int((yield dut.sweep.last_epoch)))

        # 期望：只标记 2 个 card（core0 的 card=5 1次；core1 的 card=7 1次）
        assert total == 2, f"expected mark_total=2, got {total}"
        assert c0 == 1 and c1 == 1, f"per-core counts wrong: c0={c0} c1={c1}"

        # 去重统计也应符合：core0 uniq=1 dup>=2
        uniq0 = int((yield dut.scan.uniq_enq[0]))
        dup0 = int((yield dut.scan.dup_drop[0]))
        assert uniq0 == 1 and dup0 >= 2, f"dedup stats unexpected: uniq0={uniq0} dup0={dup0}"

    sim.add_sync_process(proc)
    sim.run()
    print("OK: scan out_q -> sweep pipeline works; dedup reduces cards; sweep marks cards.")


if __name__ == "__main__":
    main()
