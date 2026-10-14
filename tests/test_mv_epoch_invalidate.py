# tests/test_mv_epoch_invalidate.py
# Step52: MV epoch support. When epoch advances, old forwarding entries must not match.
#
# Scenario:
#   1) Write mapping old=1 -> 10 via MV_RELOC (cmd path)
#   2) MV_QUERY(1) should return 10
#   3) Pulse mv.epoch_advance (toggles epoch bit)
#   4) MV_QUERY(1) should now return 1 (stale mapping filtered)
#   5) Write mapping old=1 -> 20 via sideband update (commit path)
#   6) MV_QUERY(1) should return 20

from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.gc_mv_coproc import GCMvCoProc, MV_RELOC, MV_QUERY


class TbMvEpoch(Elaboratable):
    def __init__(self):
        self.mv = GCMvCoProc(ncores=2, fifo_depth=4, map_depth=4, chase_depth=1)

    def elaborate(self, platform):
        m = Module()
        m.submodules.mv = self.mv
        return m


def main():
    tb = TbMvEpoch()
    sim = Simulator(tb)
    sim.add_clock(1e-6)

    mv = tb.mv

    def drive_cmd(core, tag, op, rd, rs1, rs2):
        def _gen():
            while True:
                if (yield mv.cmd_enq_ready[core]):
                    break
                yield Tick()
            yield mv.cmd_tag[core].eq(tag)
            yield mv.cmd_op[core].eq(op)
            yield mv.cmd_rd[core].eq(rd)
            yield mv.cmd_rs1[core].eq(rs1)
            yield mv.cmd_rs2[core].eq(rs2)
            yield mv.cmd_enq_valid[core].eq(1)
            yield Tick()
            yield mv.cmd_enq_valid[core].eq(0)
        return _gen

    def wait_rsp(core):
        # Keep rsp slot free; return (tag, rd, data) when a response appears.
        def _gen():
            while True:
                if (yield mv.rsp_valid[core]):
                    tag = (yield mv.rsp_tag[core])
                    rd  = (yield mv.rsp_rd[core])
                    data= (yield mv.rsp_data[core])
                    yield mv.rsp_take[core].eq(1)
                    yield Tick()
                    yield mv.rsp_take[core].eq(0)
                    return tag, rd, data
                yield Tick()
        return _gen

    def proc():
        # Step0: ensure epoch_advance low
        yield mv.epoch_advance.eq(0)
        yield Tick()

        # 1) cmd-path write: 1->10
        yield from drive_cmd(0, 1, MV_RELOC, 0, 1, 10)()
        # wait for rsp (MV_RELOC returns 0)
        tag, rd, data = (yield from wait_rsp(0)())
        assert data == 0

        # 2) query: expect 10
        yield from drive_cmd(1, 2, MV_QUERY, 1, 1, 0)()
        tag, rd, data = (yield from wait_rsp(1)())
        assert data == 10, f"expected 10 before epoch, got {data}"

        # 3) epoch advance pulse
        yield mv.epoch_advance.eq(1)
        yield Tick()
        yield mv.epoch_advance.eq(0)
        yield Tick()

        # 4) query again: expect stale filtered => 1
        yield from drive_cmd(1, 3, MV_QUERY, 1, 1, 0)()
        tag, rd, data = (yield from wait_rsp(1)())
        assert data == 1, f"expected 1 after epoch, got {data}"

        # 5) sideband update: core0 provides upd 1->20 (commit)
        # Tag with current epoch (=1 after advance) so the mapping is visible.
        yield mv.upd_old[0].eq(1)
        yield mv.upd_new[0].eq(20)
        yield mv.upd_epoch[0].eq(1)
        yield mv.upd_valid[0].eq(1)
        yield Tick()
        yield mv.upd_valid[0].eq(0)

        # allow drain
        for _ in range(4):
            yield Tick()

        # 6) query: expect 20
        yield from drive_cmd(1, 4, MV_QUERY, 1, 1, 0)()
        tag, rd, data = (yield from wait_rsp(1)())
        assert data == 20, f"expected 20 after new mapping, got {data}"

        print("OK: mv epoch invalidates stale forwarding entries.")

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
