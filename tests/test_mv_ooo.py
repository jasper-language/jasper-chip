"""tests/test_mv_ooo.py

Step7 的“实际测试效果”：验证 GCMvCoProc **确实可能乱序返回**。

设计意图：
  - 让协处理器在同一核缓存 2 条 pending，并让 delay 由 tag[1:0] 决定。
  - 这样我们可以构造：先发 tag=0x03（delay=3），再发 tag=0x00（delay=0）。
  - 预期：第二条响应先回来 -> 乱序成立。

这不是为了“性能”，而是为了逼迫 CPU 侧必须用 tag 做匹配。
"""

from amaranth.sim import Simulator, Tick

from rtl.gc_mv_coproc import GCMvCoProc, MV_QUERY


def main():
    dut = GCMvCoProc(ncores=1, fifo_depth=4)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def proc():
        # 发送第 1 条（delay=3）
        yield dut.cmd_tag[0].eq(0x03)
        yield dut.cmd_op[0].eq(MV_QUERY)
        yield dut.cmd_rd[0].eq(1)
        yield dut.cmd_rs1[0].eq(0xAAAA0001)
        yield dut.cmd_rs2[0].eq(0)
        yield dut.cmd_enq_valid[0].eq(1)
        # 等 ready
        while (yield dut.cmd_enq_ready[0]) == 0:
            yield Tick()
        yield Tick()
        yield dut.cmd_enq_valid[0].eq(0)

        # 发送第 2 条（delay=0）
        yield dut.cmd_tag[0].eq(0x00)
        yield dut.cmd_op[0].eq(MV_QUERY)
        yield dut.cmd_rd[0].eq(2)
        yield dut.cmd_rs1[0].eq(0xBBBB0002)
        yield dut.cmd_rs2[0].eq(0)
        yield dut.cmd_enq_valid[0].eq(1)
        while (yield dut.cmd_enq_ready[0]) == 0:
            yield Tick()
        yield Tick()
        yield dut.cmd_enq_valid[0].eq(0)

        got = []
        # 等待两次响应
        for _ in range(30):
            if (yield dut.rsp_valid[0]) == 1:
                tag = (yield dut.rsp_tag[0])
                rd  = (yield dut.rsp_rd[0])
                data = (yield dut.rsp_data[0])
                got.append(tag)
                print(f"rsp: tag=0x{tag:02x} rd={rd} data=0x{data:08x}")
                # take
                yield dut.rsp_take[0].eq(1)
                yield Tick()
                yield dut.rsp_take[0].eq(0)
                if len(got) == 2:
                    break
            yield Tick()

        assert len(got) == 2, f"only got {len(got)} responses"
        assert got[0] == 0x00 and got[1] == 0x03, f"not out-of-order as expected: {got}"
        print("OK: out-of-order response observed (tag 0x00 before 0x03).")

    sim.add_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
