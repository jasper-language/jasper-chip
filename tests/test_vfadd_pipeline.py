"""Encoded execution closure for V floating add/subtract."""

from amaranth.sim import Settle, Simulator, Tick

from rtl.vfadd_pipeline import VFAddPipeline


def encoding(funct6, funct3=0b001, vd=8, vs2=16, operand=24, vm=True):
    return ((funct6 << 26) | (int(vm) << 25) | (vs2 << 20) |
            (operand << 15) | (funct3 << 12) | (vd << 7) | 0x57)


def test_vfadd_pipeline_add_sub_reverse_f64_mask_tail_and_flags():
    cases = [
        ("add", encoding(0x00), 2 << 3, 0x3f800000, 0x40000000,
         0, 0x40400000, 0),
        ("sub", encoding(0x02), 2 << 3, 0x40c00000, 0x40000000,
         0, 0x40800000, 0),
        ("reverse", encoding(0x27, funct3=0b101), 2 << 3,
         0x40c00000, 0, 0xffffffff41200000, 0x40800000, 0),
        ("f64", encoding(0x00), 3 << 3, 0x3ff0000000000000,
         0x4000000000000000, 0, 0x4008000000000000, 0),
        ("invalid", encoding(0x00), 2 << 3, 0x7f800000,
         0xff800000, 0, 0x7fc00000, 0b10000),
    ]
    for name, insn, vtype, src2, src1, scalar, expected, flags in cases:
        dut = VFAddPipeline()
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

    dut = VFAddPipeline()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    writes = []

    def masked_tail():
        yield dut.vregs[0].eq(0)
        yield dut.insn.eq(encoding(0x00, vm=False))
        yield dut.vtype.eq((2 << 3) | (1 << 6) | (1 << 7))
        yield dut.vl.eq(1)
        yield dut.vlmax.eq(2)
        yield dut.issue_valid.eq(1)
        yield Tick()
        yield dut.issue_valid.eq(0)
        for _ in range(6):
            yield Settle()
            if (yield dut.write_valid):
                writes.append(((yield dut.write_lane), (yield dut.write_data)))
            if (yield dut.done):
                break
            yield Tick()

    sim.add_process(masked_tail)
    sim.run()
    assert writes == [(0, 0xffffffffffffffff), (1, 0xffffffffffffffff)]
