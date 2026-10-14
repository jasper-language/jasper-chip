"""Encoded execution closure for the V floating fused pipeline."""

import struct

from amaranth.sim import Settle, Simulator, Tick

from rtl.vffma_pipeline import VFFMAPipeline


def bits(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def bits64(value):
    return struct.unpack("<Q", struct.pack("<d", value))[0]


def encoding(funct6, vd=8, vs2=16, vs1=24, vm=True):
    return ((funct6 << 26) | (int(vm) << 25) | (vs2 << 20) |
            (vs1 << 15) | (0b001 << 12) | (vd << 7) | 0x57)


def test_vffma_pipeline_encoded_fma_mask_tail_flags_and_illegal():
    dut = VFFMAPipeline()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    values = [bits(2.0), bits(3.0), bits(4.0), bits(5.0)]
    addends = [bits(1.0)] * 4
    destination = [bits(10.0)] * 4
    register = sum(value << (32 * lane)
                   for lane, value in enumerate(destination))
    result = {"redirect": 0, "illegal": 0, "done": 0}

    def process():
        nonlocal register
        yield dut.vregs[0].eq(0b0101)
        yield dut.vregs[24].eq(sum(value << (32 * lane)
                                   for lane, value in enumerate(values)))
        yield dut.vregs[16].eq(sum(value << (32 * lane)
                                   for lane, value in enumerate(addends)))
        yield dut.vregs[8].eq(register)
        yield dut.insn.eq(encoding(0x28, vm=False))
        yield dut.vtype.eq((2 << 3) | (1 << 6) | (1 << 7))
        yield dut.vl.eq(3)
        yield dut.vlmax.eq(4)
        yield dut.issue_valid.eq(1)
        yield Settle()
        result["redirect"] = yield dut.redirect
        yield Tick()
        yield dut.issue_valid.eq(0)
        for _ in range(12):
            yield Settle()
            valid = yield dut.write_valid
            lane = yield dut.write_lane
            data = yield dut.write_data
            done = yield dut.done
            yield Tick()
            if valid:
                mask = 0xffffffff << (32 * lane)
                register = (register & ~mask) | ((data & 0xffffffff) <<
                                                  (32 * lane))
                yield dut.vregs[8].eq(register)
            if done:
                result["done"] = 1
                break
        yield dut.insn.eq(encoding(0x38))
        yield dut.vtype.eq(3 << 3)
        yield dut.issue_valid.eq(1)
        yield Settle()
        result["illegal"] = yield dut.illegal

    sim.add_process(process)
    sim.run()
    lanes = [(register >> (32 * lane)) & 0xffffffff for lane in range(4)]
    assert result == {"redirect": 1, "illegal": 1, "done": 1}
    assert lanes == [bits(21.0), 0xffffffff, bits(41.0), 0xffffffff]


def test_vffma_pipeline_f64_widening_families_and_fflags():
    cases = [
        ("f64", 0x28, 3 << 3, bits64(2.0), bits64(3.0),
         bits64(10.0), bits64(23.0), 0),
        ("vfwmul", 0x38, 2 << 3, bits(2.0), bits(3.0),
         bits64(10.0), bits64(6.0), 0),
        ("vfwfma", 0x3c, 2 << 3, bits(2.0), bits(3.0),
         bits64(10.0), bits64(16.0), 0),
        ("vfwadd", 0x30, 2 << 3, bits(2.0), bits(3.0),
         bits64(10.0), bits64(5.0), 0),
        ("vfwadd_wide", 0x34, 2 << 3, bits(2.0), bits64(3.0),
         bits64(10.0), bits64(5.0), 0),
        ("invalid", 0x28, 2 << 3, bits(0.0), bits(1.0),
         0x7f800000, 0x7fc00000, 0b10000),
    ]
    for name, funct6, vtype, src1, src2, initial, expected, flags in cases:
        dut = VFFMAPipeline()
        sim = Simulator(dut)
        sim.add_clock(1e-6)
        observed = {"write": None, "flags": 0, "done": 0}

        def process():
            yield dut.vregs[24].eq(src1)
            yield dut.vregs[16].eq(src2)
            yield dut.vregs[8].eq(initial)
            yield dut.insn.eq(encoding(funct6))
            yield dut.vtype.eq(vtype)
            yield dut.vl.eq(1)
            yield dut.vlmax.eq(1)
            yield dut.issue_valid.eq(1)
            yield Tick()
            yield dut.issue_valid.eq(0)
            for _ in range(6):
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
