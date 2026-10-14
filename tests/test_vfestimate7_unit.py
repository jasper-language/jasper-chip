from amaranth.sim import Settle, Simulator

from rtl.vfestimate7_unit import VFEstimate7Unit


def test_vfestimate7_tables_special_values_rounding_and_flags():
    dut = VFEstimate7Unit()
    sim = Simulator(dut)
    cases = (
        # Operation, width, rm, input, result, flags.
        (1, 0, 0, 0x00718abc, 0x5f080000, 0),
        (1, 0, 0, 0x7f765432, 0x1f820000, 0),
        (0, 0, 0, 0x00718abc, 0x7e900000, 0),
        (0, 0, 0, 0x7f765432, 0x00214000, 0),
        (1, 0, 0, 0x00000000, 0x7f800000, 0x08),
        (1, 0, 0, 0x80000000, 0xff800000, 0x08),
        (1, 0, 0, 0xbf800000, 0x7fc00000, 0x10),
        (1, 0, 0, 0x7f800000, 0x00000000, 0),
        (1, 0, 0, 0xff800000, 0x7fc00000, 0x10),
        (0, 0, 0, 0x7f800000, 0x00000000, 0),
        (0, 0, 0, 0xff800000, 0x80000000, 0),
        (0, 0, 0, 0x7fc00001, 0x7fc00000, 0),
        (0, 0, 0, 0x7f800001, 0x7fc00000, 0x10),
        (0, 0, 3, 0x00000001, 0x7f800000, 0x05),
        (0, 0, 2, 0x00000001, 0x7f7fffff, 0x05),
        (1, 1, 0, 0x3ff0000000000000, 0x3fefe00000000000, 0),
        (0, 1, 0, 0x3ff0000000000000, 0x3fefe00000000000, 0),
    )

    def process():
        for op, is_f64, rm, value, result, flags in cases:
            yield dut.reciprocal_sqrt.eq(op)
            yield dut.is_f64.eq(is_f64)
            yield dut.rm.eq(rm)
            yield dut.value.eq(value)
            yield Settle()
            mask = (1 << (64 if is_f64 else 32)) - 1
            assert (yield dut.result) & mask == result
            assert (yield dut.flags) == flags

    sim.add_process(process)
    sim.run()
