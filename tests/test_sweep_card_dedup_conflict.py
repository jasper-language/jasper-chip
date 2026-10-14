# tests/test_sweep_card_dedup_conflict.py
# -*- coding: utf-8 -*-
#
# Step23 实测：sweep 去重表的“冲突/覆盖”问题
#
# 目的：验证 Step23 的 set-associative 去重表能避免直接映射冲突导致的重复处理。
#
# 构造：
#   - card_table_size=2（sets=2，index 取 card_id 低 1bit）
#   - 选择 card_id=1(0b01) 与 card_id=3(0b11)，两者 idx 都是 1，会发生冲突。
#   - 输入序列：1,3,1,3（同 epoch=0）
#
# 期望：
#   - ways=2 时，同一个 set 能同时容纳两个 card（1 和 3）
#   - 因此 mark_total=2，dup_drop=2

from amaranth import Module, Elaboratable
from amaranth.sim import Simulator, Tick

from rtl.gc_sweep_coproc import GCSweepCoProc


class DUT(Elaboratable):
    def __init__(self):
        # 关键：sets 很小 + ways=2，用于验证冲突不会导致去重失效
        self.sweep = GCSweepCoProc(
            ncores=1,
            card_dedup_enable=True,
            card_table_size=2,
            card_table_ways=2,
        )

    def elaborate(self, platform):
        m = Module()
        m.submodules.sweep = self.sweep
        return m


def main():
    dut = DUT()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def proc():
        # 输入序列：1,3,1,3（epoch=0，core=0）
        seq = [1, 3, 1, 3]
        for card in seq:
            while (yield dut.sweep.card_in_ready) == 0:
                yield Tick()
            yield dut.sweep.card_in_valid.eq(1)
            yield dut.sweep.card_in_card_id.eq(card)
            yield dut.sweep.card_in_core_id.eq(0)
            yield dut.sweep.card_in_epoch.eq(0)
            yield Tick()
            yield dut.sweep.card_in_valid.eq(0)

        # 留出若干拍让内部消费完成
        for _ in range(30):
            yield Tick()

        mark = int((yield dut.sweep.mark_count_total))
        dup = int((yield dut.sweep.mark_dup_drop_total))
        assert mark == 2 and dup == 2, f"conflict dedup failed: mark={mark} dup={dup}"

    sim.add_sync_process(proc)
    sim.run()
    print("OK: sweep set-associative dedup survives index conflicts (mark=2 dup=2).")


if __name__ == "__main__":
    main()
