"""Encoded execution closure for the V floating square-root pipeline."""

from amaranth.sim import Settle, Simulator, Tick

from rtl.vfsqrt_pipeline import VFSqrtPipeline


def encoding(vd=8, vs2=16, vm=True):
    return ((0x13 << 26) | (int(vm) << 25) | (vs2 << 20) |
            (0b001 << 12) | (vd << 7) | 0x57)


def test_vfsqrt_pipeline_f32_f64_mask_tail_and_flags():
    cases = [
        ("f32", 2 << 3, 0x40800000, 0x40000000, 0),
        ("f64", 3 << 3, 0x4022000000000000, 0x4008000000000000, 0),
        ("negative", 2 << 3, 0xbf800000, 0x7fc00000, 0b10000),
        ("inexact", 2 << 3, 0x40000000, 0x3fb504f3, 0b00001),
    ]
    for name, vtype, operand, expected, flags in cases:
        dut = VFSqrtPipeline()
        sim = Simulator(dut)
        sim.add_clock(1e-6)
        observed = {"write": None, "flags": 0, "done": 0}

        def process():
            yield dut.vregs[16].eq(operand)
            yield dut.insn.eq(encoding())
            yield dut.vtype.eq(vtype)
            yield dut.vl.eq(1)
            yield dut.vlmax.eq(1)
            yield dut.issue_valid.eq(1)
            yield Tick()
            yield dut.issue_valid.eq(0)
            for _ in range(80):
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
        assert observed["done"], name
        assert observed["write"] == expected, name
        assert observed["flags"] == flags, name

    dut = VFSqrtPipeline()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    writes = []

    def masked_tail():
        yield dut.vregs[0].eq(0)
        yield dut.vregs[16].eq(0x40800000)
        yield dut.insn.eq(encoding(vm=False))
        yield dut.vtype.eq((2 << 3) | (1 << 6) | (1 << 7))
        yield dut.vl.eq(1)
        yield dut.vlmax.eq(2)
        yield dut.issue_valid.eq(1)
        yield Tick()
        yield dut.issue_valid.eq(0)
        for _ in range(8):
            yield Settle()
            if (yield dut.write_valid):
                writes.append(((yield dut.write_lane), (yield dut.write_data)))
            if (yield dut.done):
                break
            yield Tick()

    sim.add_process(masked_tail)
    sim.run()
    assert writes == [(0, 0xffffffffffffffff), (1, 0xffffffffffffffff)]
