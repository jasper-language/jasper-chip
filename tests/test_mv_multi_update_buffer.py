"""tests/test_mv_multi_update_buffer.py

Step51 的“实际测试效果”：验证 GCMvCoProc 对 **同拍多路 sideband 更新** 的鲁棒性：
- 同一拍 core0/core1 同时 upd_valid，MV 必须最终都能看到两个映射（不丢 update）
- 查表保持 Step48 的 latest-wins 搜索策略（不在此测试覆盖）

运行：
  python -m tests.test_mv_multi_update_buffer
"""

from amaranth.sim import Simulator, Tick

from rtl.gc_mv_coproc import GCMvCoProc, MV_QUERY


def main():
    mv = GCMvCoProc(ncores=2, map_depth=4, fifo_depth=2, chase_depth=1)

    sim = Simulator(mv)
    sim.add_clock(1e-6)

    def send_query(core: int, tag: int, key: int):
        # enqueue one MV_QUERY
        assert (yield mv.cmd_enq_ready[core]) == 1
        yield mv.cmd_tag[core].eq(tag)
        yield mv.cmd_op[core].eq(MV_QUERY)
        yield mv.cmd_rd[core].eq(1)  # dummy
        yield mv.cmd_rs1[core].eq(key)
        yield mv.cmd_rs2[core].eq(0)
        yield mv.cmd_enq_valid[core].eq(1)
        yield Tick()
        yield mv.cmd_enq_valid[core].eq(0)

    def take_rsp(core: int):
        # wait for response and take it
        for _ in range(50):
            if (yield mv.rsp_valid[core]) == 1:
                tag = (yield mv.rsp_tag[core])
                data = (yield mv.rsp_data[core])
                yield mv.rsp_take[core].eq(1)
                yield Tick()
                yield mv.rsp_take[core].eq(0)
                return tag, data
            yield Tick()
        raise AssertionError(f"timeout waiting rsp on core{core}")

    def proc():
        # ------------------------------
        # Same-cycle dual sideband updates
        # ------------------------------
        yield mv.upd_old[0].eq(1)
        yield mv.upd_new[0].eq(10)
        yield mv.upd_old[1].eq(2)
        yield mv.upd_new[1].eq(20)
        yield mv.upd_valid[0].eq(1)
        yield mv.upd_valid[1].eq(1)
        yield Tick()
        yield mv.upd_valid[0].eq(0)
        yield mv.upd_valid[1].eq(0)

        # Allow drain to commit both updates (at most 1 per cycle)
        for _ in range(4):
            yield Tick()

        # Query both keys from both cores (shared map)
        yield from send_query(0, 0x11, 1)
        yield from send_query(1, 0x22, 2)
        t0, d0 = yield from take_rsp(0)
        t1, d1 = yield from take_rsp(1)

        assert t0 == 0x11 and d0 == 10, (t0, d0)
        assert t1 == 0x22 and d1 == 20, (t1, d1)

        # Cross-check: core0 queries key=2 -> 20
        yield from send_query(0, 0x33, 2)
        t2, d2 = yield from take_rsp(0)
        assert t2 == 0x33 and d2 == 20, (t2, d2)

        # Overflow should be zero in this scenario.
        assert (yield mv.dbg_upd_overflow) == 0

        print("OK: dual sideband updates captured and visible across cores.")

    sim.add_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
