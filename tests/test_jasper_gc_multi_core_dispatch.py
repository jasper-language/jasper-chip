import sys; sys.path.insert(0, '.')
from amaranth import *
from amaranth.sim import *
from rtl.jasper_gc_multi_core_dispatch import MultiCoreDispatch
from rtl.jasper_gc_accelerator_config import JasperGCAcceleratorConfig


def _run(dut, fn):
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_sync_process(fn)
    sim.run()


def test_elab_d2():
    cfg = JasperGCAcceleratorConfig(profile='standard')
    dut = MultiCoreDispatch(cfg, num_cores=2)
    assert dut is not None


def test_elab_d4():
    cfg = JasperGCAcceleratorConfig(profile='standard')
    dut = MultiCoreDispatch(cfg, num_cores=4)
    assert dut is not None


def test_round_robin_2core():
    cfg = JasperGCAcceleratorConfig(profile='standard')
    dut = MultiCoreDispatch(cfg, num_cores=2)
    dispatched = []
    def process():
        for cid in [1, 2, 3]:
            yield dut.core0_cmd_ready.eq(1)
            yield dut.core1_cmd_ready.eq(1)
            yield dut.cmd_valid.eq(1)
            yield dut.cmd_correlation_id.eq(cid)
            yield
            yield dut.cmd_valid.eq(0)
            for _ in range(10):
                for i in range(2):
                    cv = yield getattr(dut, f'core{i}_cmd_valid')
                    if cv:
                        dispatched.append(i)
                        yield
                        break
                else:
                    yield
                    continue
                break
    _run(dut, process)
    assert len(dispatched) == 3, f"expected 3, got {dispatched}"
    assert 0 in dispatched, "core0 not used"
    assert 1 in dispatched, "core1 not used"


def test_round_robin_4core():
    cfg = JasperGCAcceleratorConfig(profile='standard')
    dut = MultiCoreDispatch(cfg, num_cores=4)
    dispatched = []
    def process():
        for i in range(4):
            yield getattr(dut, f'core{i}_cmd_ready').eq(1)
        for cid in range(6):
            yield dut.cmd_valid.eq(1)
            yield dut.cmd_correlation_id.eq(cid)
            yield
            yield dut.cmd_valid.eq(0)
            for _ in range(10):
                for i in range(4):
                    cv = yield getattr(dut, f'core{i}_cmd_valid')
                    if cv:
                        dispatched.append(i)
                        yield
                        break
                else:
                    yield
                    continue
                break
    _run(dut, process)
    assert len(dispatched) == 6, f"expected 6, got {dispatched}"
    for i in range(4):
        assert i in dispatched, f"core{i} not used"


def test_backpressure_no_core_ready():
    cfg = JasperGCAcceleratorConfig(profile='standard')
    dut = MultiCoreDispatch(cfg, num_cores=2)
    def process():
        yield dut.core0_cmd_ready.eq(0)
        yield dut.core1_cmd_ready.eq(0)
        yield
        yield dut.cmd_valid.eq(1)
        yield
        cr = yield dut.cmd_ready
        yield dut.cmd_valid.eq(0)
        assert cr == 0, f"cmd_ready={cr} (should be 0, no core ready)"
    _run(dut, process)


def test_completion_mux():
    cfg = JasperGCAcceleratorConfig(profile='standard')
    dut = MultiCoreDispatch(cfg, num_cores=2)
    comps = []
    def process():
        yield dut.comp_ready.eq(1)
        yield
        for i in range(2):
            yield getattr(dut, f'core{i}_comp_valid').eq(1)
            yield getattr(dut, f'core{i}_comp_correlation_id').eq(0x50 + i)
            yield
            cv = yield dut.comp_valid
            if cv:
                cid = yield dut.comp_correlation_id
                comps.append((i, cid))
            yield getattr(dut, f'core{i}_comp_valid').eq(0)
            yield
    _run(dut, process)
    assert len(comps) == 2, f"expected 2, got {comps}"
    assert (0, 0x50) in comps
    assert (1, 0x51) in comps


def test_cmd_ready_only_when_valid():
    cfg = JasperGCAcceleratorConfig(profile='standard')
    dut = MultiCoreDispatch(cfg, num_cores=2)
    def process():
        yield dut.core0_cmd_ready.eq(1)
        yield dut.core1_cmd_ready.eq(1)
        yield
        cr = yield dut.cmd_ready
        assert cr == 0, f"cmd_ready={cr} (should be 0, cmd_valid=0)"
        yield dut.cmd_valid.eq(1)
        yield
        cr2 = yield dut.cmd_ready
        assert cr2 == 1, f"cmd_ready={cr2} (should be 1, valid+ready)"
        yield dut.cmd_valid.eq(0)
    _run(dut, process)
