"""Encoded execution closure for the V floating divide pipeline."""

import struct

from amaranth.sim import Settle, Simulator, Tick

from rtl.vfdiv_pipeline import VFDivPipeline


def f32(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def f64(value):
    return struct.unpack("<Q", struct.pack("<d", value))[0]


def encoding(funct6, funct3=0b001, vd=8, vs2=16, operand=24, vm=True):
    return ((funct6 << 26) | (int(vm) << 25) | (vs2 << 20) |
            (operand << 15) | (funct3 << 12) | (vd << 7) | 0x57)


def test_vfdiv_pipeline_vv_vf_reverse_f64_mask_tail_and_flags():
    cases = [
        ("vv", encoding(0x20), 2 << 3, f32(6), f32(2), 0, f32(3), 0),
        ("vf", encoding(0x20, funct3=0b101), 2 << 3,
         f32(6), 0, 0xffffffff40000000, f32(3), 0),
        ("reverse", encoding(0x21, funct3=0b101), 2 << 3,
         f32(6), 0, 0xffffffff40000000, f32(1 / 3), 1),
        ("f64", encoding(0x20), 3 << 3, f64(6), f64(2), 0, f64(3), 0),
        ("dz", encoding(0x20), 2 << 3, f32(1), f32(0), 0,
         0x7f800000, 0b01000),
    ]
    for name, insn, vtype, src2, src1, scalar, expected, flags in cases:
        dut = VFDivPipeline()
        sim = Simulator(dut)
        sim.add_clock(1e-6)
        observed = {"write": None, "flags": 0, "done": 0}

        def process():
            yield dut.vregs[16].eq(src2)
            yield dut.vregs[24].eq(src1)
            yield dut.scalar.eq(scalar)
            yield dut.insn.eq(insn)
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

    dut = VFDivPipeline()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    writes = []

    def masked_tail():
        yield dut.vregs[0].eq(0)
        yield dut.vregs[16].eq(f32(6))
        yield dut.vregs[24].eq(f32(2))
        yield dut.insn.eq(encoding(0x20, vm=False))
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
