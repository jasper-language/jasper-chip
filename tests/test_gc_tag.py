# -*- coding: utf-8 -*-
"""Step6-A：tag 传递/匹配的最小可验证测试。

说明
- 当前 sweep 协处理器 FIFO 是严格顺序执行，所以不会天然出现“同一核乱序返回”。
- 但 tag 仍然非常关键：它把“请求”和“响应”绑定起来，为未来多 outstanding / 乱序返回做铺垫。

验证点
1) cmd_tag 能进入协处理器；
2) rsp_tag 会原样返回；
3) rd/data 基本字段仍保持一致。

运行：
  python -m tests.test_gc_tag
"""

from __future__ import annotations

from amaranth.sim import Simulator, Tick

from rtl.gc_sweep_coproc import GCSweepCoProc
from rtl.isa import GC_NEW


def main() -> None:
    dut = GCSweepCoProc(ncores=1)

    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def proc():
        tag = 0x5A

        # 发起一个 NEW（rd=3）请求
        yield dut.cmd_tag[0].eq(tag)
        yield dut.cmd_op[0].eq(GC_NEW)
        yield dut.cmd_rd[0].eq(3)
        yield dut.cmd_rs1[0].eq(0)
        yield dut.cmd_rs2[0].eq(0)
        yield dut.cmd_enq_valid[0].eq(1)

        # 等待 FIFO ready
        while (yield dut.cmd_enq_ready[0]) == 0:
            yield Tick()
        yield Tick()
        yield dut.cmd_enq_valid[0].eq(0)

        # 等待响应
        for _ in range(50):
            if (yield dut.rsp_valid[0]) == 1:
                rsp_tag = (yield dut.rsp_tag[0])
                rd = (yield dut.rsp_rd[0])
                data = (yield dut.rsp_data[0])
                print(f"rsp_tag=0x{rsp_tag:02x} rd={rd} data={data}")

                assert rsp_tag == tag, "rsp_tag != cmd_tag"
                assert rd == 3, "rd mismatch"

                # take 清掉响应
                yield dut.rsp_take[0].eq(1)
                yield Tick()
                yield dut.rsp_take[0].eq(0)

                print("OK: tag passthrough.")
                return

            yield Tick()

        assert False, "no response"

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
