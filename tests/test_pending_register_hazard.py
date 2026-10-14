from amaranth.sim import Settle, Simulator

from rtl.pending_register_hazard import PendingRegisterHazard


def test_all_register_indices_and_pending_mask_boundaries():
    dut = PendingRegisterHazard()
    sim = Simulator(dut)
    all_pending = (1 << 32) - 1

    def proc():
        for register in range(32):
            yield dut.rs1.eq(register)
            yield dut.rs2.eq(register)
            yield dut.rd.eq(register)
            masks = (0, 1 << register, all_pending ^ (1 << register), all_pending)
            for pending_mask in masks:
                yield dut.pending_mask.eq(pending_mask)
                pending = bool(pending_mask & (1 << register))
                for uses in (0, 1):
                    yield dut.uses_rs1.eq(uses)
                    yield dut.uses_rs2.eq(uses)
                    yield dut.writes_rd.eq(uses)
                    yield Settle()
                    source_expected = bool(uses and register != 0 and pending)
                    waw_expected = bool(uses and pending)
                    assert bool((yield dut.rs1_hazard)) == source_expected
                    assert bool((yield dut.rs2_hazard)) == source_expected
                    assert bool((yield dut.waw_hazard)) == waw_expected
                    assert bool((yield dut.any_hazard)) == (
                        source_expected or waw_expected
                    )

    sim.add_process(proc)
    sim.run()


def test_all_enable_combinations_and_independent_register_matches():
    dut = PendingRegisterHazard()
    sim = Simulator(dut)

    def proc():
        yield dut.rs1.eq(3)
        yield dut.rs2.eq(7)
        yield dut.rd.eq(11)
        for pending_mask in (0, 1 << 3, 1 << 7, 1 << 11,
                             (1 << 3) | (1 << 7) | (1 << 11)):
            yield dut.pending_mask.eq(pending_mask)
            for uses_rs1 in (0, 1):
                yield dut.uses_rs1.eq(uses_rs1)
                for uses_rs2 in (0, 1):
                    yield dut.uses_rs2.eq(uses_rs2)
                    for writes_rd in (0, 1):
                        yield dut.writes_rd.eq(writes_rd)
                        yield Settle()
                        rs1 = bool(uses_rs1 and pending_mask & (1 << 3))
                        rs2 = bool(uses_rs2 and pending_mask & (1 << 7))
                        waw = bool(writes_rd and pending_mask & (1 << 11))
                        assert bool((yield dut.rs1_hazard)) == rs1
                        assert bool((yield dut.rs2_hazard)) == rs2
                        assert bool((yield dut.waw_hazard)) == waw
                        assert bool((yield dut.any_hazard)) == (rs1 or rs2 or waw)

    sim.add_process(proc)
    sim.run()
