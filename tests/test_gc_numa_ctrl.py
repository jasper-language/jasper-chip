# tests/test_gc_numa_ctrl.py — NUMA GC Controller 单元测试
from amaranth import *
from amaranth.sim import Simulator, Tick
from rtl.gc_numa_ctrl import GCNumaCtrlDisabled, GCNumaCtrlEnabled, create_numa_ctrl
import sys

PHASE_ROOTS    = 1
PHASE_HEAP     = 2
PHASE_MARK     = 3
PHASE_SWEEP    = 4
PHASE_RELOCATE = 5
PHASE_COMPLETE = 6

def test_disabled_elaborate():
    m = Module()
    nc = GCNumaCtrlDisabled(n_numa_nodes=1, local_node_id=0)
    m.submodules.nc = nc
    from amaranth.back import rtlil
    o = rtlil.convert(m, ports=[])
    print(f"  disabled elaboration: {len(o)} chars — PASS")
    return True

def test_disabled_single_cycle():
    nc = GCNumaCtrlDisabled(n_numa_nodes=1, local_node_id=0)
    sim = Simulator(nc); sim.add_clock(1e-6)
    def proc():
        yield nc.start_cycle.eq(1)
        yield Tick(); yield Tick()  # schedule→apply: cycle active, phase=ROOTS
        yield nc.start_cycle.eq(0)

        yield nc.rs_done.eq(1); yield Tick(); yield Tick(); yield nc.rs_done.eq(0)  # →HEAP
        yield nc.hw_done.eq(1); yield Tick(); yield Tick(); yield nc.hw_done.eq(0)  # →MARK
        yield nc.scan_done.eq(1); yield Tick(); yield Tick(); yield nc.scan_done.eq(0)  # →SWEEP
        yield nc.sweep_done.eq(1); yield Tick(); yield Tick(); yield nc.sweep_done.eq(0)  # →RELOCATE
        yield nc.mv_done.eq(1); yield nc.mv_relocs.eq(42); yield Tick(); yield Tick()  # →COMPLETE
        yield Tick()  # idle transition: cycle_active→0, epoch→1, cycle_count→1
        yield nc.mv_done.eq(0)

        active = (yield nc.cycle_active)
        phase = (yield nc.phase)
        epoch = (yield nc.epoch)
        epoch_adv = (yield nc.epoch_advance)
        cycle_cnt = (yield nc.cycle_count)
        total_relocs = (yield nc.total_relocs)
        gc_complete = (yield nc.global_cycle_complete)
        print(f"  after cycle: active={active} phase={phase} epoch={epoch} adv={epoch_adv} cycle={cycle_cnt} relocs={total_relocs} gc={gc_complete}")
        assert active == 0, f"expected cycle_active=0, got {active}"
        assert epoch == 1, f"expected epoch=1, got {epoch}"
        assert epoch_adv == 1, f"expected epoch_advance=1, got {epoch_adv}"
        assert gc_complete == 1, f"expected global_cycle_complete=1, got {gc_complete}"
        assert total_relocs == 42, f"expected relocs=42, got {total_relocs}"
        assert cycle_cnt == 1, f"expected cycle_count=1, got {cycle_cnt}"

        # Next cycle: epoch_advance goes low (combinational after phase leaves COMPLETE)
        yield nc.start_cycle.eq(1); yield Tick(); yield Tick(); yield nc.start_cycle.eq(0)
        epoch_adv2 = (yield nc.epoch_advance)
        print(f"  next cycle start: epoch_advance={epoch_adv2}")
        assert epoch_adv2 == 0, f"expected epoch_advance=0, got {epoch_adv2}"

        print(f"  → PASS")
    sim.add_process(proc); sim.run()
    return True

def test_disabled_two_cycles():
    nc = GCNumaCtrlDisabled(n_numa_nodes=1, local_node_id=0)
    sim = Simulator(nc); sim.add_clock(1e-6)
    def proc():
        for cyc in range(2):
            yield nc.start_cycle.eq(1)
            yield Tick(); yield Tick()
            yield nc.start_cycle.eq(0)
            for ds in [nc.rs_done, nc.hw_done, nc.scan_done, nc.sweep_done, nc.mv_done]:
                yield ds.eq(1)
                yield Tick(); yield Tick()
                yield ds.eq(0)
            yield Tick()  # idle transition
        epoch_final = (yield nc.epoch)
        cycle_cnt_final = (yield nc.cycle_count)
        print(f"  two cycles: epoch={epoch_final} count={cycle_cnt_final}")
        assert epoch_final == 2, f"epoch={epoch_final}"
        assert cycle_cnt_final == 2, f"cycle_count={cycle_cnt_final}"
        print(f"  → PASS")
    sim.add_process(proc); sim.run()
    return True

def test_enabled_elaborate():
    m = Module()
    nc = GCNumaCtrlEnabled(n_numa_nodes=4, local_node_id=0)
    m.submodules.nc = nc
    from amaranth.back import rtlil
    o = rtlil.convert(m, ports=[])
    print(f"  enabled elaboration: {len(o)} chars — PASS")
    return True

def _run_through_phases(proc, nc):
    """Helper: yield through all phases to reach PHASE_COMPLETE."""
    yield nc.start_cycle.eq(1)
    yield Tick(); yield Tick()
    yield nc.start_cycle.eq(0)
    for ds in [nc.rs_done, nc.hw_done, nc.scan_done, nc.sweep_done, nc.mv_done]:
        yield ds.eq(1)
        yield Tick(); yield Tick()
        yield ds.eq(0)

def test_enabled_coordination():
    nc = GCNumaCtrlEnabled(n_numa_nodes=4, local_node_id=0)
    sim = Simulator(nc); sim.add_clock(1e-6)
    def proc():
        yield from _run_through_phases(proc, nc)
        phase = (yield nc.phase)
        assert phase == PHASE_COMPLETE, f"expected PHASE_COMPLETE, got {phase}"
        print(f"  after local done: phase={phase}")

        gc = (yield nc.global_cycle_complete)
        assert gc == 0, f"expected global_cycle_complete=0, got {gc}"

        yield nc.per_node_cycle_done.eq(0b1111)
        yield Tick(); yield Tick()
        yield nc.per_node_cycle_done.eq(0)

        gc2 = (yield nc.global_cycle_complete)
        active2 = (yield nc.cycle_active)
        print(f"  all done: global_complete={gc2} active={active2}")
        assert gc2 == 1
        assert active2 == 0
        print(f"  → PASS")
    sim.add_process(proc); sim.run()
    return True

def test_enabled_epoch_advance():
    nc = GCNumaCtrlEnabled(n_numa_nodes=4, local_node_id=0)
    sim = Simulator(nc); sim.add_clock(1e-6)
    def proc():
        yield from _run_through_phases(proc, nc)
        yield nc.per_node_cycle_done.eq(0b1111)
        yield Tick(); yield Tick()
        yield nc.per_node_cycle_done.eq(0)
        epoch = (yield nc.epoch)
        ea = (yield nc.epoch_advance)
        print(f"  epoch={epoch} epoch_advance={ea}")
        assert epoch == 1
        assert ea == 1
        print(f"  → PASS")
    sim.add_process(proc); sim.run()
    return True

def test_enabled_global_cycle_waits_all_nodes():
    nc = GCNumaCtrlEnabled(n_numa_nodes=4, local_node_id=0)
    sim = Simulator(nc); sim.add_clock(1e-6)
    def proc():
        yield from _run_through_phases(proc, nc)
        phase = (yield nc.phase)
        active = (yield nc.cycle_active)
        print(f"  after local done: phase={phase} active={active}")
        assert phase == PHASE_COMPLETE
        assert active == 1

        yield nc.per_node_cycle_done.eq(0b0010)
        yield Tick(); yield Tick()
        active2 = (yield nc.cycle_active)
        assert active2 == 1, "cycle still active (1/3 remote done)"

        yield nc.per_node_cycle_done.eq(0b1111)
        yield Tick(); yield Tick()
        active3 = (yield nc.cycle_active)
        print(f"  all remote done: active={active3}")
        assert active3 == 0
        print(f"  → PASS")
    sim.add_process(proc); sim.run()
    return True

def test_factory():
    disabled = create_numa_ctrl("disabled", n_numa_nodes=1, local_node_id=0)
    assert isinstance(disabled, GCNumaCtrlDisabled), f"expected GCNumaCtrlDisabled, got {type(disabled)}"
    enabled = create_numa_ctrl("enabled", n_numa_nodes=4, local_node_id=0)
    assert isinstance(enabled, GCNumaCtrlEnabled), f"expected GCNumaCtrlEnabled, got {type(enabled)}"
    print(f"  factory: disabled={type(disabled).__name__} enabled={type(enabled).__name__} — PASS")
    return True

if __name__ == "__main__":
    tests = [
        ("Disabled Elaborate",            test_disabled_elaborate),
        ("Disabled Single Cycle",         test_disabled_single_cycle),
        ("Disabled Two Cycles",           test_disabled_two_cycles),
        ("Enabled Elaborate",             test_enabled_elaborate),
        ("Enabled Coordination",          test_enabled_coordination),
        ("Enabled Epoch Advance",         test_enabled_epoch_advance),
        ("Enabled Wait All Nodes",        test_enabled_global_cycle_waits_all_nodes),
        ("Factory",                       test_factory),
    ]
    print("=" * 60)
    print("GC NUMA Ctrl 单元测试")
    print("=" * 60)
    all_ok = True
    for name, fn in tests:
        print(f"\n[{name}]")
        try:
            ok = fn()
            if ok is not None:
                print(f"  → {'PASS' if ok else 'FAIL'}")
                all_ok &= ok
        except Exception as e:
            import traceback
            print(f"  → FAIL: {e}")
            traceback.print_exc()
            all_ok = False
    print(f"\n{'='*60}")
    print(f"{'ALL PASS' if all_ok else 'SOME FAILED'}")
    sys.exit(0 if all_ok else 1)
