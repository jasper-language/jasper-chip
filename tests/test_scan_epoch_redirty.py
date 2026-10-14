# tests/test_scan_epoch_redirty.py
#
# Step19 实测：epoch / generation 切换后，同一张 card 在新 epoch 应该允许再次入队。
#
# 场景：
#   - consume_every=0：scan 不消费（避免“消费清除集合”影响结论）
#   - dedup_enable=True：开启去重
#   - 连续 3 次写入同一卡：
#       1) 第一次：uniq_enq +1
#       2) 第二次：dup_drop +1（命中去重）
#       3) epoch_advance 翻转 epoch 后第三次：uniq_enq +1（新 epoch 重新入队）
#
from amaranth.sim import Simulator, Tick

from rtl.gc_scan_coproc import GCScanCoProc


def main():
    dut = GCScanCoProc(
        ncores=1,
        fifo_depth=4,
        consume_every=0,   # 不消费
        batch_size=1,
        dedup_enable=True,
        cardset_size=4,
    )

    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def proc():
        # 0) 初始 epoch=0
        assert (yield dut.epoch) == 0

        # 1) 第一次写入 card=1,obj=4 -> 期望 uniq_enq=1
        yield dut.wb_valid[0].eq(1)
        yield dut.wb_addr[0].eq(1)
        yield dut.wb_data[0].eq(4)
        yield Tick()

        # 2) 第二次写入同一卡 -> 期望 dup_drop=1
        yield dut.wb_addr[0].eq(1)
        yield dut.wb_data[0].eq(4)
        yield Tick()

        # 3) 关 wb_valid
        yield dut.wb_valid[0].eq(0)
        yield Tick()

        # 4) 翻转 epoch（拉高 1 拍）
        yield dut.epoch_advance.eq(1)
        yield Tick()
        yield dut.epoch_advance.eq(0)
        yield Tick()

        # 5) 第三次写入同一卡（新 epoch）-> 应该重新入队 uniq_enq=2
        yield dut.wb_valid[0].eq(1)
        yield dut.wb_addr[0].eq(1)
        yield dut.wb_data[0].eq(4)
        yield Tick()
        yield dut.wb_valid[0].eq(0)
        yield Tick()

        in_cnt = (yield dut.in_count[0])
        uniq = (yield dut.uniq_enq[0])
        dup = (yield dut.dup_drop[0])
        ep = (yield dut.epoch)
        print(f"epoch={ep} in={in_cnt} uniq={uniq} dup={dup}")

        assert ep == 1, "epoch should have toggled to 1"
        assert in_cnt == 3, f"expected in_count=3 got {in_cnt}"
        assert uniq == 2, f"expected uniq_enq=2 got {uniq}"
        assert dup == 1, f"expected dup_drop=1 got {dup}"

    sim.add_sync_process(proc)
    sim.run()
    print("OK: epoch redirty allows same card to re-enqueue in new epoch.")


if __name__ == "__main__":
    main()
