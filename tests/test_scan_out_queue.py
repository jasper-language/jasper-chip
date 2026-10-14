# tests/test_scan_out_queue.py
# -*- coding: utf-8 -*-
#
# Step20 实测：scan 协处理器新增 out_q（card stream 输出）。
#
# 场景：2 核各注入 1 条写屏障事件，scan 引擎消费后应输出两条记录：
#   (core_id, card_id, epoch)
# epoch 初始为 0。

from amaranth.sim import Simulator, Tick

from rtl.gc_scan_coproc import GCScanCoProc


def main():
    dut = GCScanCoProc(
        ncores=2,
        fifo_depth=4,
        consume_every=1,
        batch_size=1,
        dedup_enable=False,
        out_depth=4,
    )

    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def proc():
        # out_ready 默认 reset=1，这里显式保持为 1
        yield dut.out_ready.eq(1)

        # cycle 1：同时向两核注入事件（card_id 直接写入 wb_addr）
        yield dut.wb_valid[0].eq(1)
        yield dut.wb_valid[1].eq(1)
        yield dut.wb_addr[0].eq(1)
        yield dut.wb_addr[1].eq(3)
        yield dut.wb_data[0].eq(111)
        yield dut.wb_data[1].eq(222)
        yield Tick()

        # 拉低 valid
        yield dut.wb_valid[0].eq(0)
        yield dut.wb_valid[1].eq(0)

        # 采集 out 记录
        got = []
        for _ in range(20):
            if (yield dut.out_valid):
                got.append(
                    (
                        int((yield dut.out_core_id)),
                        int((yield dut.out_card_id)),
                        int((yield dut.out_epoch)),
                    )
                )
            yield Tick()

        print("out_records:", got)

        # 必须至少拿到两条
        assert len(got) >= 2, "expected at least 2 out records"

        # out_q 的顺序取决于 rr_ptr；我们只验证集合包含两条正确记录
        want = {(0, 1, 0), (1, 3, 0)}
        assert want.issubset(set(got)), f"missing expected records {want}"

    sim.add_sync_process(proc)
    sim.run()
    print("OK: scan out_q emits (core_id, card_id, epoch) for consumed events.")


if __name__ == "__main__":
    main()
