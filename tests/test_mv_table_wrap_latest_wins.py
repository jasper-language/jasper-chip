# tests/test_mv_table_wrap_latest_wins.py
# Step48：验证 forwarding table 的查询在 ring wrap 后仍返回“最新写入”的映射。
#
# 背景：map_ptr 是 ring buffer 的写指针。如果同一个 old key 被多次写入且发生 wrap，
# 如果 lookup 只是“物理 index 最后命中 wins”，会错误地返回旧映射。
#
# 本测试用 MV_RELOC（命令路径写表）构造：
#   map_depth=4
#   写入 old=1 -> new=100,101,102,103,104 (共 5 次，发生 wrap)
# 期望：MV_QUERY(1) 返回 104（最新），而不是 103。

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.gc_mv_coproc import GCMvCoProc, MV_RELOC, MV_QUERY


class TbMvWrap(Elaboratable):
    def __init__(self):
        # small depth to force wrap quickly
        self.mv = GCMvCoProc(ncores=1, fifo_depth=8, map_depth=4, chase_depth=1)

    def elaborate(self, platform):
        m = Module()
        m.submodules.mv = self.mv

        # Tie-off sweep sideband (not used in this unit test).
        m.d.comb += [
            self.mv.upd_valid[0].eq(0),
            self.mv.upd_old[0].eq(0),
            self.mv.upd_new[0].eq(0),
        ]
        return m


def main():
    tb = TbMvWrap()
    sim = Simulator(tb)
    sim.add_clock(1e-6)

    mv = tb.mv

    def drive_cmd(tag, op, rd, rs1, rs2):
        # one-cycle enqueue handshake
        def _gen():
            while True:
                rdy = (yield mv.cmd_enq_ready[0])
                if rdy:
                    break
                yield Tick()
            yield mv.cmd_tag[0].eq(tag)
            yield mv.cmd_op[0].eq(op)
            yield mv.cmd_rd[0].eq(rd)
            yield mv.cmd_rs1[0].eq(rs1)
            yield mv.cmd_rs2[0].eq(rs2)
            yield mv.cmd_enq_valid[0].eq(1)
            yield Tick()
            yield mv.cmd_enq_valid[0].eq(0)
        return _gen

    def proc():
        # helper: always take responses to keep rsp slot free
        def maybe_take():
            if (yield mv.rsp_valid[0]):
                yield mv.rsp_take[0].eq(1)
            else:
                yield mv.rsp_take[0].eq(0)

        # write 5 mappings for the same key (forces wrap at depth=4)
        new_values = [100, 101, 102, 103, 104]
        tag = 1
        for nv in new_values:
            # enqueue MV_RELOC old=1,new=nv
            gen = drive_cmd(tag, MV_RELOC, 0, 1, nv)
            yield from gen()

            # run a few cycles so the engine can dequeue/write and produce rsp
            for _ in range(6):
                yield from maybe_take()
                yield Tick()
            tag += 1

        # now query old=1
        gen = drive_cmd(tag, MV_QUERY, 1, 1, 0)
        yield from gen()

        # wait for rsp
        got = None
        for _ in range(80):
            if (yield mv.rsp_valid[0]):
                got = (yield mv.rsp_data[0])
                # take it
                yield mv.rsp_take[0].eq(1)
                yield Tick()
                yield mv.rsp_take[0].eq(0)
                break
            yield Tick()

        print(f"MV_QUERY(1) -> {got}")
        assert got == 104, "MV lookup must return newest mapping after ring wrap"
        print("OK: MV forwarding table returns newest mapping after wrap (latest-wins).")

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
