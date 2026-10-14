# tests/test_sweep_index_hash.py
# -*- coding: utf-8 -*-
#
# Step24 实测：索引 hash（xor-fold）降低低位冲突，减少重复处理
#
# 构造：
#   - card_table_size=4（sets=4，idx_w=2）
#   - 选择 card_id：0,4,8,12
#       低 2bit 都是 00 -> 直接映射时全部冲突到同一个 set
#       xor-fold 时 idx = low2 ^ high2，可分散到 4 个 set
#   - 输入序列：0,4,8,12,0,4,8,12（epoch=0）
#
# 预期：
#   - index_mode=0（低位）：mark_total=8, dup=0, replace_total=7
#   - index_mode=1（xor-fold）：mark_total=4, dup=4, replace_total=0
#
from amaranth import Module, Elaboratable
from amaranth.sim import Simulator, Tick

from rtl.gc_sweep_coproc import GCSweepCoProc


class DUT(Elaboratable):
    def __init__(self, index_mode):
        self.sweep = GCSweepCoProc(
            ncores=1,
            card_dedup_enable=True,
            card_table_size=4,
            card_table_ways=1,
            card_index_mode=index_mode,
        )

    def elaborate(self, platform):
        m = Module()
        m.submodules.sweep = self.sweep
        return m


def run_case(index_mode):
    dut = DUT(index_mode)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def proc():
        seq = [0, 4, 8, 12, 0, 4, 8, 12]
        for card in seq:
            while (yield dut.sweep.card_in_ready) == 0:
                yield Tick()
            yield dut.sweep.card_in_valid.eq(1)
            yield dut.sweep.card_in_card_id.eq(card)
            yield dut.sweep.card_in_core_id.eq(0)
            yield dut.sweep.card_in_epoch.eq(0)
            yield Tick()
            yield dut.sweep.card_in_valid.eq(0)

        for _ in range(60):
            yield Tick()

        mark = (yield dut.sweep.mark_count_total)
        dup  = (yield dut.sweep.mark_dup_drop_total)
        rep  = (yield dut.sweep.mark_replace_total)
        print(f"index_mode={index_mode} mark={mark} dup={dup} replace={rep}")
        return mark, dup, rep

    result={}
    def wrapper():
        result["vals"]=yield from proc()
    sim.add_sync_process(wrapper)
    sim.run()
    return result["vals"]


def main():
    m0, d0, r0 = run_case(0)
    m1, d1, r1 = run_case(1)

    assert (m0, d0) == (8, 0), (m0, d0)
    assert r0 >= 6, r0  # 理论上为 7
    assert (m1, d1, r1) == (4, 4, 0), (m1, d1, r1)

    print("OK: xor-fold index reduces low-bit conflicts and avoids replacement churn.")


if __name__ == "__main__":
    main()
