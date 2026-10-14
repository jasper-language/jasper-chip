"""Encoded execution and overlap closure for all V conversion classes."""

from amaranth.sim import Settle, Simulator, Tick

from rtl.vfcvt_pipeline import VFCvtPipeline


def encoding(subop, vd=8, vs2=16, vm=True):
    return ((0x12 << 26) | (int(vm) << 25) | (vs2 << 20) |
            (subop << 15) | (0b001 << 12) | (vd << 7) | 0x57)


def run_case(subop, source, expected, vtype=2 << 3, vd=8, vs2=16,
             frm=0, flags=0):
    dut = VFCvtPipeline()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    observed = {"write": None, "flags": 0, "done": 0}

    def process():
        yield dut.vregs[vs2].eq(source)
        yield dut.insn.eq(encoding(subop, vd=vd, vs2=vs2))
        yield dut.vtype.eq(vtype)
        yield dut.vl.eq(1)
        yield dut.vlmax.eq(1)
        yield dut.frm.eq(frm)
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
    assert observed["done"]
    assert observed["write"] == expected
    assert observed["flags"] == flags


def test_vfcvt_pipeline_same_widen_narrow_rtz_rod_and_flags():
    run_case(0x02, 1, 0x3f800000)
    run_case(0x00, 0x3fc00000, 2, flags=1)
    run_case(0x06, 0x3fc00000, 1, frm=7, flags=1)
    run_case(0x0a, 2, 0x4000000000000000)
    run_case(0x08, 0x3fc00000, 2, flags=1)
    run_case(0x0c, 0x3f800000, 0x3ff0000000000000)
    run_case(0x12, 0x0000000001000001, 0x4b800000, flags=1)
    run_case(0x10, 0x3ff8000000000000, 2, flags=1)
    run_case(0x14, 0x3ff0000010000000, 0x3f800000, flags=1)
    run_case(0x15, 0x3ff0000010000000, 0x3f800001, frm=7, flags=1)


def test_vfcvt_pipeline_snapshot_preserves_high_and_low_overlap():
    dut = VFCvtPipeline()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    registers = {8: 0, 9: (1 | (2 << 32) | (3 << 64) | (4 << 96))}
    writes = []

    def process():
        yield dut.vregs[8].eq(registers[8])
        yield dut.vregs[9].eq(registers[9])
        yield dut.insn.eq(encoding(0x0a, vd=8, vs2=9))
        yield dut.vtype.eq(2 << 3)
        yield dut.vl.eq(4)
        yield dut.vlmax.eq(4)
        yield dut.issue_valid.eq(1)
        yield Tick()
        yield dut.issue_valid.eq(0)
        for _ in range(10):
            yield Settle()
            valid = yield dut.write_valid
            reg = yield dut.write_reg
            lane = yield dut.write_lane
            data = yield dut.write_data
            done = yield dut.done
            yield Tick()
            if valid:
                mask = ((1 << 64) - 1) << (lane * 64)
                registers[reg] = ((registers.get(reg, 0) & ~mask) |
                                  (data << (lane * 64)))
                yield dut.vregs[reg].eq(registers[reg])
                writes.append(data)
            if done:
                break

    sim.add_process(process)
    sim.run()
    assert writes == [0x3ff0000000000000, 0x4000000000000000,
                      0x4008000000000000, 0x4010000000000000]
