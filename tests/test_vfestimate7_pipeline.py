"""Encoded execution closure for V 7-bit floating estimates."""

from amaranth.sim import Settle, Simulator, Tick

from rtl.vfestimate7_pipeline import VFEstimate7Pipeline


def encoding(rs1, vd=8, vs2=16, vm=True):
    return ((0x13 << 26) | (int(vm) << 25) | (vs2 << 20) |
            (rs1 << 15) | (0b001 << 12) | (vd << 7) | 0x57)


def test_vfestimate7_pipeline_examples_mask_tail_and_flags():
    cases = (
        (4, 0x00718abc, 0x5f080000, 0, 0),
        (5, 0x7f765432, 0x00214000, 0, 0),
        (4, 0xbf800000, 0x7fc00000, 0x10, 0),
        (5, 0x00000001, 0x7f800000, 0x05, 3),
    )
    for rs1, operand, expected, flags, frm in cases:
        dut = VFEstimate7Pipeline()
        sim = Simulator(dut)
        sim.add_clock(1e-6)
        observed = {"write": None, "flags": 0, "done": 0}

        def process():
            yield dut.vregs[16].eq(operand)
            yield dut.insn.eq(encoding(rs1))
            yield dut.vtype.eq(2 << 3)
            yield dut.vl.eq(1)
            yield dut.vlmax.eq(1)
            yield dut.frm.eq(frm)
            yield dut.issue_valid.eq(1)
            yield Tick()
            yield dut.issue_valid.eq(0)
            for _ in range(8):
                yield Settle()
                if (yield dut.write_valid):
                    observed["write"] = yield dut.write_data
                if (yield dut.fflags_write_valid):
                    observed["flags"] = yield dut.fflags_write_value
                if (yield dut.done):
                    observed["done"] = 1
                    break
                yield Tick()

        sim.add_process(process)
        sim.run()
        assert observed == {"write": expected, "flags": flags, "done": 1}

    dut = VFEstimate7Pipeline()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    writes = []

    def masked_tail():
        yield dut.vregs[0].eq(0)
        yield dut.vregs[16].eq(0x3f800000)
        yield dut.insn.eq(encoding(4, vm=False))
        yield dut.vtype.eq((2 << 3) | (1 << 6) | (1 << 7))
        yield dut.vl.eq(1)
        yield dut.vlmax.eq(2)
        yield dut.issue_valid.eq(1)
        yield Tick()
        yield dut.issue_valid.eq(0)
        for _ in range(8):
            yield Settle()
            if (yield dut.write_valid):
                writes.append(((yield dut.write_lane),
                               (yield dut.write_data)))
            if (yield dut.done):
                break
            yield Tick()

    sim.add_process(masked_tail)
    sim.run()
    assert writes == [(0, 0xffffffffffffffff),
                      (1, 0xffffffffffffffff)]
