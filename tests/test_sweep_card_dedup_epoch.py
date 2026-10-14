# tests/test_sweep_card_dedup_epoch.py
# -*- coding: utf-8 -*-
#
# Step22 实测：sweep 侧 card 去重 + epoch 语义
#
# 场景：
#   - scan 去重关闭（让重复 card 也能输出），同一卡连续写 4 次（epoch=0）
#   - sweep 去重开启：应只“标记”1 次，dup_drop=3
#   - 然后推进 scan epoch（epoch_advance 脉冲）
#   - 再写同一卡 1 次（epoch=1）
#   - sweep 应把它当作“新一轮 GC 的脏卡”，mark_total 变 2（dup_drop 不再增加）
#
# 该测试不依赖 CPU 程序执行，只验证：
#   write-barrier events -> scan out_q -> sweep dedup-by-(card,epoch)

from amaranth import Module, Elaboratable
from amaranth.sim import Simulator, Tick

from rtl.gc_scan_coproc import GCScanCoProc
from rtl.gc_sweep_coproc import GCSweepCoProc


class DUT(Elaboratable):
    def __init__(self):
        self.scan = GCScanCoProc(
            ncores=1,
            fifo_depth=4,
            consume_every=1,
            batch_size=1,
            dedup_enable=False,    # 关键：关闭 scan 去重，让重复 card 输出到 sweep
            cardset_size=4,
        )
        self.sweep = GCSweepCoProc(
            ncores=1,
            card_dedup_enable=True,
            card_table_size=16,
        )

    def elaborate(self, platform):
        m = Module()
        m.submodules.scan = self.scan
        m.submodules.sweep = self.sweep

        # scan out_q -> sweep card_in
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
        # 初始：epoch=0
        assert int((yield dut.scan.epoch)) == 0

        # 连续 4 拍：同一卡（card_id=5）写 4 次
        for _ in range(4):
            yield dut.scan.wb_valid[0].eq(1)
            yield dut.scan.wb_addr[0].eq(5)   # 这里 wb_addr 语义就是 card_id
            yield dut.scan.wb_data[0].eq(123) # obj_id（无所谓）
            yield Tick()
        yield dut.scan.wb_valid[0].eq(0)

        # 等待处理
        for _ in range(30):
            yield Tick()

        mark1 = int((yield dut.sweep.mark_count_total))
        dup1  = int((yield dut.sweep.mark_dup_drop_total))
        assert mark1 == 1 and dup1 == 3, f"epoch0 dedup failed: mark={mark1} dup={dup1}"

        # 推进 epoch：脉冲 1 拍
        yield dut.scan.epoch_advance.eq(1)
        yield Tick()
        yield dut.scan.epoch_advance.eq(0)
        yield Tick()
        assert int((yield dut.scan.epoch)) == 1, "epoch did not advance"

        # 再写同一卡 1 次（epoch=1）
        yield dut.scan.wb_valid[0].eq(1)
        yield dut.scan.wb_addr[0].eq(5)
        yield dut.scan.wb_data[0].eq(456)
        yield Tick()
        yield dut.scan.wb_valid[0].eq(0)

        for _ in range(30):
            yield Tick()

        mark2 = int((yield dut.sweep.mark_count_total))
        dup2  = int((yield dut.sweep.mark_dup_drop_total))
        assert mark2 == 2 and dup2 == 3, f"epoch1 behavior wrong: mark={mark2} dup={dup2}"

    sim.add_sync_process(proc)
    sim.run()
    print("OK: sweep dedup works within epoch and resets across epochs.")


if __name__ == "__main__":
    main()
