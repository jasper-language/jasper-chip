# -*- coding: utf-8 -*-
"""Step58: Reloc stream must not resurrect stale MV mappings across epoch.

Why:
- Step56/57 introduced a Clean->Move reloc stream with FIFO + backpressure.
- Step55 validated that epoch_advance invalidates MV mappings.
- But if a reloc update is still in-flight (stuck in the link FIFO) when epoch advances,
  delivering it later MUST NOT recreate the mapping in the new epoch.

Scenario:
1) Issue a GC_RELOC on Clean while reloc_link_enable=0 (Move will not pop; update stays in link FIFO).
2) Pulse epoch_advance (Move toggles epoch; old mappings must be invalid).
3) Re-enable reloc link (stale update delivered after epoch flip).
4) Query MV: must MISS and return rs1 (old), not the relocated new.

Note:
- Avoid wrapping the DUT in an extra top-level Elaboratable here; some amaranth versions can spend a long
  time in elaboration transforms when Simulator() is given a wrapper module. Passing the DUT directly keeps
  this test fast and deterministic.

Run:
  python -m tests.test_step58_reloc_epoch_tag_drop
"""

from amaranth.sim import Simulator, Tick

from rtl.gc_3chip_system import GC3ChipSystem
from rtl.isa import GC_NEW, GC_RELOC
from rtl.gc_mv_coproc import MV_QUERY


def test_step58_reloc_epoch_tag_drop():
    dut = GC3ChipSystem(ncores=1, enable_scan=False, reloc_link_depth=4)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def proc():
        clean = dut.clean
        move  = dut.move

        def enq_clean(op, rd=0, rs1=0, rs2=0, tag=0x10):
            for _ in range(200):
                if (yield clean.cmd_enq_ready[0]):
                    break
                yield Tick()
            else:
                assert False, "clean cmd ready timeout"
            yield clean.cmd_enq_valid[0].eq(1)
            yield clean.cmd_op[0].eq(op)
            yield clean.cmd_rd[0].eq(rd)
            yield clean.cmd_rs1[0].eq(rs1)
            yield clean.cmd_rs2[0].eq(rs2)
            yield clean.cmd_tag[0].eq(tag)
            yield Tick()
            yield clean.cmd_enq_valid[0].eq(0)

        def take_clean_rsp():
            for _ in range(400):
                if (yield clean.rsp_valid[0]):
                    rd = (yield clean.rsp_rd[0])
                    data = (yield clean.rsp_data[0])
                    yield clean.rsp_take[0].eq(1)
                    yield Tick()
                    yield clean.rsp_take[0].eq(0)
                    return rd, data
                yield Tick()
            assert False, "clean rsp timeout"

        def enq_move(op, rd=0, rs1=0, rs2=0, tag=0x20):
            for _ in range(200):
                if (yield move.cmd_enq_ready[0]):
                    break
                yield Tick()
            else:
                assert False, "move cmd ready timeout"
            yield move.cmd_enq_valid[0].eq(1)
            yield move.cmd_op[0].eq(op)
            yield move.cmd_rd[0].eq(rd)
            yield move.cmd_rs1[0].eq(rs1)
            yield move.cmd_rs2[0].eq(rs2)
            yield move.cmd_tag[0].eq(tag)
            yield Tick()
            yield move.cmd_enq_valid[0].eq(0)

        def take_move_rsp():
            for _ in range(500):
                if (yield move.rsp_valid[0]):
                    data = (yield move.rsp_data[0])
                    yield move.rsp_take[0].eq(1)
                    yield Tick()
                    yield move.rsp_take[0].eq(0)
                    return data
                yield Tick()
            assert False, "move rsp timeout"

        # Initial conditions
        yield dut.epoch_advance.eq(0)
        yield dut.reloc_link_enable.eq(0)  # block pop so update stays in FIFO
        yield Tick()

        # Allocate a handle (h)
        yield from enq_clean(GC_NEW, rd=1, rs1=0, rs2=0, tag=0x11)
        rd, h = yield from take_clean_rsp()
        assert rd == 1
        assert h != 0

        # Commit relocation h -> 0x1000 while link pop is blocked
        yield from enq_clean(GC_RELOC, rd=0, rs1=h, rs2=0x1000, tag=0x12)
        _rd0, _ = yield from take_clean_rsp()

        # Advance epoch while reloc still in FIFO (Move toggles to epoch=1)
        yield dut.epoch_advance.eq(1)
        yield Tick()
        yield dut.epoch_advance.eq(0)
        yield Tick()

        # Re-enable reloc link: stale update (epoch=0) will be delivered now
        yield dut.reloc_link_enable.eq(1)
        for _ in range(10):
            yield Tick()

        # Query for h: must MISS in new epoch and return h itself
        yield from enq_move(MV_QUERY, rd=2, rs1=h, rs2=0, tag=0x21)
        got = yield from take_move_rsp()
        assert got == h, f"expected MV miss after epoch, got mapping to {got:#x}"

    sim.add_sync_process(proc)
    sim.run()

    print("OK: stale reloc updates delivered after epoch do not resurrect MV mapping.")


def main():
    test_step58_reloc_epoch_tag_drop()


if __name__ == "__main__":
    main()
