from amaranth.sim import Simulator, Settle

from rtl.vfwcvt_float_unit import VFWidenFloatUnit


def test_vfwcvt_f32_to_f64_special_values_and_flags():
    dut = VFWidenFloatUnit()
    sim = Simulator(dut)

    cases = (
        (0x00000000, 0x0000000000000000, 0x00),
        (0x3f800000, 0x3ff0000000000000, 0x00),
        (0xc0200000, 0xc004000000000000, 0x00),
        (0x00000001, 0x36a0000000000000, 0x00),
        (0x7f800000, 0x7ff0000000000000, 0x00),
        (0x7fc00001, 0x7ff8000000000000, 0x00),
        (0x7f800001, 0x7ff8000000000000, 0x10),
    )

    def process():
        for value, result, flags in cases:
            yield dut.value.eq(value)
            yield Settle()
            assert (yield dut.result) == result
            assert (yield dut.flags) == flags

    sim.add_process(process)
    sim.run()
