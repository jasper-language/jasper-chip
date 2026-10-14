# -*- coding: utf-8 -*-
"""Step59: Reloc sideband must not drop updates under prolonged backpressure.

Motivation
- Step56 added a Clean->Move reloc stream with a link FIFO + backpressure.
- Clean wrapper previously captured sweep.mv_upd pulses into a 1-slot pending reg per core.
  Under extreme backpressure (link FIFO full), additional mv_upd pulses could be *dropped*.
- Step59 converts sweep.mv_upd into a valid/ready interface and wires mv_upd_ready from Clean,
  so RELOC commits will naturally stall instead of losing forwarding-table updates.

Test
1) Disable reloc_link_enable (Move won't pop link FIFO; FIFO fills and creates backpressure).
2) Allocate 4 src handles via GC_NEW.
3) Enqueue 4 GC_RELOC commands quickly (distinct old->new pairs).
   With fifo_depth=1, total buffering capacity is 1 (link FIFO) + 1 (clean out reg) + 1 (clean pending)
   = 3 updates. The 4th RELOC must therefore stall and its response must not appear while link is disabled.
4) Re-enable reloc link and wait for all 4 responses.
5) Query MV for all 4 old handles; must map to their new handles (no lost updates).

Run:
  python -m tests.test_step59_reloc_backpressure_no_drop
"""

from __future__ import annotations

from amaranth.sim import Simulator, Tick

from rtl.gc_3chip_system import GC3ChipSystem
from rtl.isa import GC_NEW, GC_RELOC
from rtl.gc_mv_coproc import MV_QUERY


def test_step59_reloc_backpressure_no_drop():
    dut = GC3ChipSystem(ncores=1, reloc_link_depth=1, enable_scan=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def proc():
        clean = dut.clean
        move = dut.move

        # Helpers
        def enq_clean(op: int, rd: int, rs1: int, rs2: int, tag: int = 1):
            # wait ready
            for _ in range(200):
                if (yield clean.cmd_enq_ready[0]):
                    break
                yield Tick()
            else:
                assert False, "clean cmd enqueue timeout"

            yield clean.cmd_enq_valid[0].eq(1)
            yield clean.cmd_op[0].eq(op)
            yield clean.cmd_rd[0].eq(rd)
            yield clean.cmd_rs1[0].eq(rs1)
            yield clean.cmd_rs2[0].eq(rs2)
            yield clean.cmd_tag[0].eq(tag)
            yield Tick()
            yield clean.cmd_enq_valid[0].eq(0)

        def take_clean_rsp(timeout: int = 600):
            for _ in range(timeout):
                if (yield clean.rsp_valid[0]):
                    rd = (yield clean.rsp_rd[0])
                    data = (yield clean.rsp_data[0])
                    trap = (yield clean.trap[0])
                    yield clean.rsp_take[0].eq(1)
                    yield Tick()
                    yield clean.rsp_take[0].eq(0)
                    return rd, data, trap
                yield Tick()
            assert False, "clean response timeout"

        def try_take_clean_rsp():
            if (yield clean.rsp_valid[0]):
                rd = (yield clean.rsp_rd[0])
                data = (yield clean.rsp_data[0])
                trap = (yield clean.trap[0])
                yield clean.rsp_take[0].eq(1)
                yield Tick()
                yield clean.rsp_take[0].eq(0)
                return rd, data, trap
            return None

        def mv_query(val: int, tag: int = 1):
            # wait ready
            for _ in range(200):
                if (yield move.cmd_enq_ready[0]):
                    break
                yield Tick()
            else:
                assert False, "mv cmd enqueue timeout"
            yield move.cmd_enq_valid[0].eq(1)
            yield move.cmd_op[0].eq(MV_QUERY)
            yield move.cmd_rd[0].eq(1)
            yield move.cmd_rs1[0].eq(val)
            yield move.cmd_rs2[0].eq(0)
            yield move.cmd_tag[0].eq(tag)
            yield Tick()
            yield move.cmd_enq_valid[0].eq(0)

            for _ in range(300):
                if (yield move.rsp_valid[0]):
                    data = (yield move.rsp_data[0])
                    yield move.rsp_take[0].eq(1)
                    yield Tick()
                    yield move.rsp_take[0].eq(0)
                    return data
                yield Tick()
            assert False, "mv query timeout"

        # Disable link pop (backpressure)
        yield dut.reloc_link_enable.eq(0)
        yield Tick()

        # Allocate 4 source handles
        src = []
        for _ in range(4):
            yield from enq_clean(GC_NEW, 1, 0, 0, tag=1)
            rd, data, trap = (yield from take_clean_rsp())
            assert trap == 0
            src.append(data)

        # Enqueue 4 relocations quickly (distinct dst handles)
        dst = [100, 101, 102, 103]
        for old, new in zip(src, dst):
            yield from enq_clean(GC_RELOC, 0, old, new, tag=1)

        # Collect responses while link is disabled.
        # With depth=1, buffering cap is 3 updates, so 4th should stall.
        got = []
        for _ in range(300):
            r = (yield from try_take_clean_rsp())
            if r is not None:
                got.append(r)
            # stop early if we already saw 3
            if len(got) >= 3:
                break
            yield Tick()

        assert len(got) == 3, f"expected exactly 3 reloc responses while link disabled, got {len(got)}"

        # Re-enable link and wait for the last response
        yield dut.reloc_link_enable.eq(1)
        # allow draining
        for _ in range(600):
            r = (yield from try_take_clean_rsp())
            if r is not None:
                got.append(r)
                break
            yield Tick()
        assert len(got) == 4, "fourth reloc response did not arrive after link re-enabled"

        # Let Move ingest updates
        for _ in range(50):
            yield Tick()

        # Verify MV mapping for all old handles
        for old, new in zip(src, dst):
            out = (yield from mv_query(old, tag=1))
            assert out == new, f"MV_QUERY({old}) expected {new}, got {out}"

    sim.add_sync_process(proc)
    sim.run()
    print("OK: RELOC stalls under extreme backpressure without dropping MV updates.")


if __name__ == "__main__":
    test_step59_reloc_backpressure_no_drop()
    print("OK: RELOC stalls under extreme backpressure without dropping MV updates.")
