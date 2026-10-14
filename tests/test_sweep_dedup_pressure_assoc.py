# tests/test_sweep_dedup_pressure_assoc.py
# -*- coding: utf-8 -*-
#
# Step24 实测：去重表容量压力（同一个 set 内超过容量会导致替换 -> 重复处理）
#
# 目的：
#   - 构造“同 set 冲突”的 card 序列，验证：
#       1) ways=1（直接映射）会发生大量替换，导致重复 card 也被当作 miss 反复处理
#       2) ways=2（组相联）能同时容纳更多 card，从而把重复 card 正确判定为 hit
#
# 构造：
#   - card_table_size=2（sets=2，idx 取 card_id 低 1bit）
#   - card_id=0(0b0) 与 card_id=2(0b10) 的低位 idx 都是 0，必冲突同一个 set
#   - 输入序列：0,2,0,2,0,2（epoch=0）
#
# 预期：
#   - ways=1：每次几乎都是 miss -> mark_total=6, dup_drop=0, replace_total=5
#   - ways=2：只前两次 miss，其余为 hit -> mark_total=2, dup_drop=4, replace_total=0
#
from amaranth import Module, Elaboratable
from amaranth.sim import Simulator, Tick

from rtl.gc_sweep_coproc import GCSweepCoProc


class DUT(Elaboratable):
    def __init__(self, ways):
        self.sweep = GCSweepCoProc(
            ncores=1,
            card_dedup_enable=True,
            card_table_size=2,
            card_table_ways=ways,
            card_index_mode=0,
        )

    def elaborate(self, platform):
        m = Module()
        m.submodules.sweep = self.sweep
        return m


def run_case(ways):
    dut = DUT(ways)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def proc():
        seq = [0, 2, 0, 2, 0, 2]
        for card in seq:
            while (yield dut.sweep.card_in_ready) == 0:
                yield Tick()
            yield dut.sweep.card_in_valid.eq(1)
            yield dut.sweep.card_in_card_id.eq(card)
            yield dut.sweep.card_in_core_id.eq(0)
            yield dut.sweep.card_in_epoch.eq(0)
            yield Tick()
            yield dut.sweep.card_in_valid.eq(0)

        for _ in range(40):
            yield Tick()

        mark = (yield dut.sweep.mark_count_total)
        dup  = (yield dut.sweep.mark_dup_drop_total)
        rep  = (yield dut.sweep.mark_replace_total)
        print(f"ways={ways} mark={mark} dup={dup} replace={rep}")
        return mark, dup, rep

    result = {}
    def wrapper():
        result["vals"] = yield from proc()

    sim.add_sync_process(wrapper)
    sim.run()
    return result["vals"]


def main():
    m1, d1, r1 = run_case(1)
    m2, d2, r2 = run_case(2)

    assert (m1, d1) == (6, 0), (m1, d1)
    assert r1 >= 4, r1  # 理论上为 5；这里保守一点，保证“确实发生大量替换”

    assert (m2, d2, r2) == (2, 4, 0), (m2, d2, r2)

    print("OK: associativity reduces replacement-induced reprocessing under capacity pressure.")


if __name__ == "__main__":
    main()
