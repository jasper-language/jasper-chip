import pytest
from amaranth.sim import Settle, Simulator

from rtl.fp_store_hazard_control import FPStoreHazardControl


@pytest.mark.parametrize("enabled", [
    {1}, {2}, {1, 2}, {1, 2, 3}, {1, 2, 3, 4},
])
def test_fp_store_hazard_widths_and_all_pipeline_slots(enabled):
    dut = FPStoreHazardControl(
        slots=7,
        enable_h=1 in enabled,
        enable_f=2 in enabled,
        enable_d=3 in enabled,
        enable_q=4 in enabled,
    )
    sim = Simulator(dut)

    def proc():
        yield dut.store_valid.eq(1)
        yield dut.store_rs2.eq(9)
        for slot in range(dut.slots):
            for index in range(dut.slots):
                yield dut.load_valid[index].eq(index == slot)
                yield dut.load_rd[index].eq(9)
            for width in range(1, 5):
                yield dut.store_funct3.eq(width)
                yield dut.load_funct3[slot].eq(width)
                yield Settle()
                assert bool((yield dut.hazard)) == (width in enabled)

            yield dut.store_funct3.eq(next(iter(enabled)))
            yield dut.load_funct3[slot].eq(next(iter(enabled)))
            yield dut.load_rd[slot].eq(8)
            yield Settle()
            assert not (yield dut.hazard)

        yield dut.store_valid.eq(0)
        yield dut.load_rd[0].eq(9)
        yield Settle()
        assert not (yield dut.hazard)

    sim.add_process(proc)
    sim.run()


def test_fp_store_hazard_is_disabled_for_finx_register_mode():
    dut = FPStoreHazardControl(
        slots=2, enable_h=True, enable_f=True,
        enable_d=True, enable_q=True, use_finx=True)
    sim = Simulator(dut)

    def proc():
        yield dut.store_valid.eq(1)
        yield dut.store_rs2.eq(3)
        yield dut.load_valid[0].eq(1)
        yield dut.load_rd[0].eq(3)
        for width in range(1, 5):
            yield dut.store_funct3.eq(width)
            yield dut.load_funct3[0].eq(width)
            yield Settle()
            assert not (yield dut.hazard)

    sim.add_process(proc)
    sim.run()
