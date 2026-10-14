import sys
sys.path.insert(0, '.')

from amaranth import *
from amaranth.sim import *
from rtl.jasper_gc_memory_arbiter import MemoryRequestArbiter
from rtl.jasper_gc_coherent_access_adapter import CoherentAccessAdapter


class ArbiterCoherentHarness(Elaboratable):
    """Harness: MemoryRequestArbiter → CoherentAccessAdapter → CoherentAccess."""
    def __init__(self, **coherent_kwargs):
        self._ca_kwargs = coherent_kwargs
        for name in ['compact', 'mre', 'sweep', 'scan']:
            setattr(self, f'{name}_req_valid', Signal())
            setattr(self, f'{name}_req_ready', Signal())
            setattr(self, f'{name}_req_is_write', Signal())
            setattr(self, f'{name}_req_addr', Signal(32))
            setattr(self, f'{name}_req_tag', Signal(16))
            setattr(self, f'{name}_rsp_valid', Signal())
            setattr(self, f'{name}_rsp_ready', Signal())
            setattr(self, f'{name}_rsp_tag', Signal(16))
        self.dbg_rsp_error = Signal()
        self.dbg_rsp_status = Signal(3)
        self.dbg_rsp_hit = Signal()
        self.dbg_rsp_epoch = Signal(8)
        self.dbg_outstanding = Signal()
        self.dbg_out_engine = Signal(2)

    def elaborate(self, platform):
        m = Module()
        arb = MemoryRequestArbiter()
        adp = CoherentAccessAdapter(**self._ca_kwargs)
        m.submodules.arb = arb
        m.submodules.adp = adp

        # Arbiter mem_* ↔ Adapter mem_*
        m.d.comb += [
            adp.mem_req_valid.eq(arb.mem_req_valid),
            arb.mem_req_ready.eq(adp.mem_req_ready),
            adp.mem_req_is_write.eq(arb.mem_req_is_write),
            adp.mem_req_addr.eq(arb.mem_req_addr),
            adp.mem_req_tag.eq(arb.mem_req_tag),
            arb.mem_rsp_valid.eq(adp.mem_rsp_valid),
            adp.mem_rsp_ready.eq(arb.mem_rsp_ready),
            arb.mem_rsp_tag.eq(adp.mem_rsp_tag),
        ]

        # Engine ports ↔ Arbiter engine ports
        for name in ['compact', 'mre', 'sweep', 'scan']:
            m.d.comb += [
                getattr(self, f'{name}_req_ready').eq(
                    getattr(arb, f'{name}_req_ready')),
                getattr(arb, f'{name}_req_valid').eq(
                    getattr(self, f'{name}_req_valid')),
                getattr(arb, f'{name}_req_is_write').eq(
                    getattr(self, f'{name}_req_is_write')),
                getattr(arb, f'{name}_req_addr').eq(
                    getattr(self, f'{name}_req_addr')),
                getattr(arb, f'{name}_req_tag').eq(
                    getattr(self, f'{name}_req_tag')),
                getattr(self, f'{name}_rsp_valid').eq(
                    getattr(arb, f'{name}_rsp_valid')),
                getattr(arb, f'{name}_rsp_ready').eq(
                    getattr(self, f'{name}_rsp_ready')),
                getattr(self, f'{name}_rsp_tag').eq(
                    getattr(arb, f'{name}_rsp_tag')),
            ]

        # Debug passthrough
        m.d.comb += [
            self.dbg_rsp_error.eq(adp.dbg_rsp_error),
            self.dbg_rsp_status.eq(adp.dbg_rsp_status),
            self.dbg_rsp_hit.eq(adp.dbg_rsp_hit),
            self.dbg_rsp_epoch.eq(adp.dbg_rsp_epoch),
            self.dbg_outstanding.eq(arb.dbg_outstanding),
            self.dbg_out_engine.eq(arb.dbg_out_engine),
        ]
        return m


HIT_ADDR = 0x40
MISS_ADDR = 0x00


def _run(dut, fn):
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_sync_process(fn)
    sim.run()


def test_elab():
    dut = ArbiterCoherentHarness()
    assert dut is not None


def test_scan_request():
    dut = ArbiterCoherentHarness()
    def process():
        yield dut.scan_rsp_ready.eq(1)
        yield dut.scan_req_valid.eq(1)
        yield dut.scan_req_is_write.eq(0)
        yield dut.scan_req_addr.eq(HIT_ADDR)
        yield dut.scan_req_tag.eq(0x1001)
        yield
        yield dut.scan_req_valid.eq(0)
        for _ in range(10):
            rv = yield dut.scan_rsp_valid
            if rv:
                t = yield dut.scan_rsp_tag
                assert t == 0x1001, f"scan tag mismatch: {t:#x}"
                return
            yield
        assert False, "scan response timeout"
    _run(dut, process)


def test_sweep_request():
    dut = ArbiterCoherentHarness()
    def process():
        yield dut.sweep_rsp_ready.eq(1)
        yield dut.sweep_req_valid.eq(1)
        yield dut.sweep_req_is_write.eq(0)
        yield dut.sweep_req_addr.eq(MISS_ADDR)
        yield dut.sweep_req_tag.eq(0x2002)
        yield
        yield dut.sweep_req_valid.eq(0)
        for _ in range(10):
            rv = yield dut.sweep_rsp_valid
            if rv:
                t = yield dut.sweep_rsp_tag
                assert t == 0x2002, f"sweep tag mismatch: {t:#x}"
                return
            yield
        assert False, "sweep response timeout"
    _run(dut, process)


def test_mre_request():
    dut = ArbiterCoherentHarness()
    def process():
        yield dut.mre_rsp_ready.eq(1)
        yield dut.mre_req_valid.eq(1)
        yield dut.mre_req_is_write.eq(0)
        yield dut.mre_req_addr.eq(HIT_ADDR)
        yield dut.mre_req_tag.eq(0x3003)
        yield
        yield dut.mre_req_valid.eq(0)
        for _ in range(10):
            rv = yield dut.mre_rsp_valid
            if rv:
                t = yield dut.mre_rsp_tag
                assert t == 0x3003, f"mre tag mismatch: {t:#x}"
                return
            yield
        assert False, "mre response timeout"
    _run(dut, process)


def test_compact_request():
    dut = ArbiterCoherentHarness()
    def process():
        yield dut.compact_rsp_ready.eq(1)
        yield dut.compact_req_valid.eq(1)
        yield dut.compact_req_is_write.eq(0)
        yield dut.compact_req_addr.eq(HIT_ADDR)
        yield dut.compact_req_tag.eq(0x4004)
        yield
        yield dut.compact_req_valid.eq(0)
        for _ in range(10):
            rv = yield dut.compact_rsp_valid
            if rv:
                t = yield dut.compact_rsp_tag
                assert t == 0x4004, f"compact tag mismatch: {t:#x}"
                return
            yield
        assert False, "compact response timeout"
    _run(dut, process)


def test_priority_compact_over_all():
    dut = ArbiterCoherentHarness()
    chosen = []
    def process():
        yield dut.compact_rsp_ready.eq(1)
        yield dut.mre_rsp_ready.eq(1)
        yield dut.sweep_rsp_ready.eq(1)
        yield dut.scan_rsp_ready.eq(1)
        yield dut.compact_req_valid.eq(1)
        yield dut.compact_req_addr.eq(HIT_ADDR)
        yield dut.compact_req_tag.eq(0xAA)
        yield dut.mre_req_valid.eq(1)
        yield dut.mre_req_addr.eq(HIT_ADDR)
        yield dut.mre_req_tag.eq(0xBB)
        yield dut.sweep_req_valid.eq(1)
        yield dut.sweep_req_addr.eq(HIT_ADDR)
        yield dut.sweep_req_tag.eq(0xCC)
        yield dut.scan_req_valid.eq(1)
        yield dut.scan_req_addr.eq(HIT_ADDR)
        yield dut.scan_req_tag.eq(0xDD)
        yield
        for _ in range(10):
            cv = yield dut.compact_rsp_valid
            if cv:
                chosen.append('compact')
                break
            mv = yield dut.mre_rsp_valid
            if mv:
                chosen.append('mre')
                break
            sw = yield dut.sweep_rsp_valid
            if sw:
                chosen.append('sweep')
                break
            sc = yield dut.scan_rsp_valid
            if sc:
                chosen.append('scan')
                break
            yield
    _run(dut, process)
    assert 'compact' in chosen, f"compact should win, got {chosen}"


def test_priority_mre_over_sweep_scan():
    dut = ArbiterCoherentHarness()
    chosen = []
    def process():
        yield dut.compact_rsp_ready.eq(1)
        yield dut.mre_rsp_ready.eq(1)
        yield dut.sweep_rsp_ready.eq(1)
        yield dut.scan_rsp_ready.eq(1)
        yield dut.compact_req_valid.eq(0)
        yield dut.mre_req_valid.eq(1)
        yield dut.mre_req_addr.eq(HIT_ADDR)
        yield dut.mre_req_tag.eq(0xEE)
        yield dut.sweep_req_valid.eq(1)
        yield dut.sweep_req_addr.eq(HIT_ADDR)
        yield dut.sweep_req_tag.eq(0xFF)
        yield dut.scan_req_valid.eq(1)
        yield dut.scan_req_addr.eq(HIT_ADDR)
        yield dut.scan_req_tag.eq(0x100)
        yield
        for _ in range(10):
            mv = yield dut.mre_rsp_valid
            if mv:
                chosen.append('mre')
                break
            sw = yield dut.sweep_rsp_valid
            if sw:
                chosen.append('sweep')
                break
            sc = yield dut.scan_rsp_valid
            if sc:
                chosen.append('scan')
                break
            yield
    _run(dut, process)
    assert 'mre' in chosen, f"mre should win, got {chosen}"


def test_priority_sweep_over_scan():
    dut = ArbiterCoherentHarness()
    chosen = []
    def process():
        yield dut.compact_rsp_ready.eq(1)
        yield dut.mre_rsp_ready.eq(1)
        yield dut.sweep_rsp_ready.eq(1)
        yield dut.scan_rsp_ready.eq(1)
        yield dut.compact_req_valid.eq(0)
        yield dut.mre_req_valid.eq(0)
        yield dut.sweep_req_valid.eq(1)
        yield dut.sweep_req_addr.eq(HIT_ADDR)
        yield dut.sweep_req_tag.eq(0x111)
        yield dut.scan_req_valid.eq(1)
        yield dut.scan_req_addr.eq(HIT_ADDR)
        yield dut.scan_req_tag.eq(0x222)
        yield
        for _ in range(10):
            sw = yield dut.sweep_rsp_valid
            if sw:
                chosen.append('sweep')
                break
            sc = yield dut.scan_rsp_valid
            if sc:
                chosen.append('scan')
                break
            yield
    _run(dut, process)
    assert 'sweep' in chosen, f"sweep should win, got {chosen}"


def test_response_route_not_overwritten():
    dut = ArbiterCoherentHarness(miss_latency=8, hit_latency=3)
    def process():
        yield dut.compact_rsp_ready.eq(1)
        yield dut.mre_rsp_ready.eq(1)
        yield dut.sweep_rsp_ready.eq(1)
        yield dut.scan_rsp_ready.eq(1)
        yield dut.compact_req_valid.eq(1)
        yield dut.compact_req_addr.eq(MISS_ADDR)
        yield dut.compact_req_tag.eq(0x7777)
        yield
        yield dut.compact_req_valid.eq(0)
        # While compact is in flight, fire mre (should be rejected, route preserved)
        for _ in range(2):
            yield
        yield dut.mre_req_valid.eq(1)
        yield dut.mre_req_addr.eq(HIT_ADDR)
        yield dut.mre_req_tag.eq(0x8888)
        yield
        mr = yield dut.mre_req_ready
        assert mr == 0, f"mre_req_ready={mr} (should be 0, outstanding=1)"
        yield dut.mre_req_valid.eq(0)
        # Compact response should route correctly
        for _ in range(15):
            cv = yield dut.compact_rsp_valid
            if cv:
                t = yield dut.compact_rsp_tag
                assert t == 0x7777, f"compact tag: {t:#x}"
                break
            yield
        else:
            assert False, "compact response timeout"
        yield
        # Now send mre (outstanding=0, should be accepted)
        yield dut.mre_req_valid.eq(1)
        yield dut.mre_req_addr.eq(HIT_ADDR)
        yield dut.mre_req_tag.eq(0x8888)
        yield
        mr2 = yield dut.mre_req_ready
        assert mr2 == 1, f"mre_req_ready={mr2} (should be 1, outstanding=0)"
        yield dut.mre_req_valid.eq(0)
        for _ in range(15):
            mv = yield dut.mre_rsp_valid
            if mv:
                t = yield dut.mre_rsp_tag
                assert t == 0x8888, f"mre tag: {t:#x}"
                return
            yield
        assert False, "mre response timeout"
    _run(dut, process)


def test_single_outstanding_blocks_all():
    dut = ArbiterCoherentHarness(hit_latency=10)
    def process():
        yield dut.compact_rsp_ready.eq(1)
        yield dut.scan_rsp_ready.eq(1)
        yield dut.compact_req_valid.eq(1)
        yield dut.compact_req_addr.eq(HIT_ADDR)
        yield dut.compact_req_tag.eq(1)
        yield
        # Cycle 1: compact req valid, check ready = 1 (accepted)
        cr = yield dut.compact_req_ready
        assert cr == 1, f"compact_req_ready={cr} (should be 1 at cycle 1)"
        yield dut.compact_req_valid.eq(0)
        yield
        # Cycle 2: compact deasserted, outstanding=1 now
        o2 = yield dut.dbg_outstanding
        assert o2 == 1, f"outstanding={o2} (should be 1 after accept)"
        yield dut.scan_req_valid.eq(1)
        yield dut.scan_req_addr.eq(HIT_ADDR)
        yield dut.scan_req_tag.eq(2)
        yield
        # Cycle 3: scan req valid, but outstanding=1 blocks it
        sr = yield dut.scan_req_ready
        assert sr == 0, f"scan_req_ready={sr} (should be 0, outstanding=1)"
        yield dut.scan_req_valid.eq(0)
        yield
    _run(dut, process)


def test_response_backpressure_hold():
    dut = ArbiterCoherentHarness(miss_latency=5)
    def process():
        yield dut.compact_rsp_ready.eq(0)
        yield dut.compact_req_valid.eq(1)
        yield dut.compact_req_addr.eq(MISS_ADDR)
        yield dut.compact_req_tag.eq(0x3333)
        yield
        yield dut.compact_req_valid.eq(0)
        for i in range(20):
            cv = yield dut.compact_rsp_valid
            if cv:
                t = yield dut.compact_rsp_tag
                assert t == 0x3333, f"initial tag: {t:#x}"
                yield
                t2 = yield dut.compact_rsp_tag
                assert t2 == 0x3333, f"t+1 tag: {t2:#x}"
                yield
                t3 = yield dut.compact_rsp_tag
                assert t3 == 0x3333, f"t+2 tag: {t3:#x}"
                yield dut.compact_rsp_ready.eq(1)
                yield
                t4 = yield dut.compact_rsp_tag
                assert t4 == 0x3333, f"t+3 (ready=1) tag: {t4:#x}"
                return
            yield
        assert False, "response timeout"
    _run(dut, process)


def test_no_loss():
    dut = ArbiterCoherentHarness(hit_latency=2)
    def process():
        # Sequence 4 requests through single-outstanding arbiter: send, wait, send, wait...
        for tag, eng in [(0x11, 'compact'), (0x22, 'mre'), (0x33, 'sweep'), (0x44, 'scan')]:
            yield getattr(dut, f'{eng}_rsp_ready').eq(1)
            yield getattr(dut, f'{eng}_req_valid').eq(1)
            yield getattr(dut, f'{eng}_req_is_write').eq(0)
            yield getattr(dut, f'{eng}_req_addr').eq(HIT_ADDR)
            yield getattr(dut, f'{eng}_req_tag').eq(tag)
            yield
            yield getattr(dut, f'{eng}_req_valid').eq(0)
            # Wait for response
            for _ in range(10):
                rv = yield getattr(dut, f'{eng}_rsp_valid')
                if rv:
                    t = yield getattr(dut, f'{eng}_rsp_tag')
                    assert t == tag, f"{eng} tag: {t:#x} != {tag:#x}"
                    break
                yield
            else:
                assert False, f"{eng} response timeout"
            yield
    _run(dut, process)


def test_no_missing_response():
    dut = ArbiterCoherentHarness(hit_latency=2, miss_latency=5)
    def process():
        for i in range(6):
            eng = ['compact', 'mre', 'sweep', 'scan', 'compact', 'mre'][i]
            tag = 0x50 + i
            addr = HIT_ADDR if i < 3 else HIT_ADDR  # all hits for determinism
            yield getattr(dut, f'{eng}_rsp_ready').eq(1)
            yield getattr(dut, f'{eng}_req_valid').eq(1)
            yield getattr(dut, f'{eng}_req_addr').eq(addr)
            yield getattr(dut, f'{eng}_req_tag').eq(tag)
            yield
            yield getattr(dut, f'{eng}_req_valid').eq(0)
            # Wait for response
            for _ in range(10):
                rv = yield getattr(dut, f'{eng}_rsp_valid')
                if rv:
                    t = yield getattr(dut, f'{eng}_rsp_tag')
                    assert t == tag, f"{eng}#{i} tag: {t:#x} != {tag:#x}"
                    break
                yield
            else:
                assert False, f"{eng}#{i} response timeout"
            yield
    _run(dut, process)


def test_no_duplicate_response():
    dut = ArbiterCoherentHarness(queue_depth=4)
    rsp_tags = []
    def process():
        yield dut.compact_rsp_ready.eq(0)
        yield dut.mre_rsp_ready.eq(0)
        yield dut.sweep_rsp_ready.eq(0)
        yield dut.scan_rsp_ready.eq(0)
        for i in range(4):
            eng = ['compact', 'mre', 'sweep', 'scan'][i]
            yield getattr(dut, f'{eng}_req_valid').eq(1)
            yield getattr(dut, f'{eng}_req_addr').eq(HIT_ADDR)
            yield getattr(dut, f'{eng}_req_tag').eq(0x60 + i)
            yield
            yield getattr(dut, f'{eng}_req_valid').eq(0)
            for _ in range(3):
                yield
        yield dut.compact_rsp_ready.eq(1)
        yield dut.mre_rsp_ready.eq(1)
        yield dut.sweep_rsp_ready.eq(1)
        yield dut.scan_rsp_ready.eq(1)
        for _ in range(30):
            for eng in ['compact', 'mre', 'sweep', 'scan']:
                rv = yield getattr(dut, f'{eng}_rsp_valid')
                if rv:
                    t = yield getattr(dut, f'{eng}_rsp_tag')
                    rsp_tags.append(t)
                    yield
            yield
    _run(dut, process)
    assert len(rsp_tags) == len(set(rsp_tags)), f"duplicates: {rsp_tags}"


def test_dbg_rsp_hit_visible():
    dut = ArbiterCoherentHarness()
    def process():
        yield dut.compact_rsp_ready.eq(1)
        yield dut.compact_req_valid.eq(1)
        yield dut.compact_req_addr.eq(HIT_ADDR)
        yield dut.compact_req_tag.eq(0x99)
        yield
        yield dut.compact_req_valid.eq(0)
        for _ in range(10):
            cv = yield dut.compact_rsp_valid
            if cv:
                h1 = yield dut.dbg_rsp_hit
                assert h1 == 1, f"first (HIT_ADDR) hit={h1}"
                break
            yield
        else:
            assert False, "first response timeout"
        yield
        yield dut.compact_req_valid.eq(1)
        yield dut.compact_req_addr.eq(MISS_ADDR)
        yield dut.compact_req_tag.eq(0x100)
        yield
        yield dut.compact_req_valid.eq(0)
        for _ in range(10):
            cv = yield dut.compact_rsp_valid
            if cv:
                h2 = yield dut.dbg_rsp_hit
                assert h2 == 0, f"second (MISS_ADDR) hit={h2}"
                return
            yield
        assert False, "second response timeout"
    _run(dut, process)


def test_dbg_rsp_status_fault():
    dut = ArbiterCoherentHarness(enable_error_injection=True, fault_tag=0xFA)
    def process():
        yield dut.compact_rsp_ready.eq(1)
        yield dut.compact_req_valid.eq(1)
        yield dut.compact_req_addr.eq(HIT_ADDR)
        yield dut.compact_req_tag.eq(0xFA)
        yield
        yield dut.compact_req_valid.eq(0)
        for _ in range(10):
            cv = yield dut.compact_rsp_valid
            if cv:
                s = yield dut.dbg_rsp_status
                assert s == 4, f"expected FAULT(4), got {s}"
                return
            yield
        assert False, "response timeout"
    _run(dut, process)


def test_dbg_rsp_status_unsupported():
    dut = ArbiterCoherentHarness(enable_write=False)
    def process():
        yield dut.scan_rsp_ready.eq(1)
        yield dut.scan_req_valid.eq(1)
        yield dut.scan_req_is_write.eq(1)
        yield dut.scan_req_addr.eq(HIT_ADDR)
        yield dut.scan_req_tag.eq(0x55)
        yield
        yield dut.scan_req_valid.eq(0)
        for _ in range(10):
            sv = yield dut.scan_rsp_valid
            if sv:
                s = yield dut.dbg_rsp_status
                assert s == 5, f"expected UNSUPPORTED(5), got {s}"
                return
            yield
        assert False, "response timeout"
    _run(dut, process)


def test_dbg_rsp_error_follows_status():
    dut = ArbiterCoherentHarness(enable_error_injection=True, fault_tag=0xBB)
    errors = []
    def process():
        yield dut.compact_rsp_ready.eq(1)
        yield dut.compact_req_valid.eq(1)
        yield dut.compact_req_addr.eq(HIT_ADDR)
        yield dut.compact_req_tag.eq(0xBB)
        yield
        yield dut.compact_req_valid.eq(0)
        for _ in range(10):
            cv = yield dut.compact_rsp_valid
            if cv:
                e = yield dut.dbg_rsp_error
                s = yield dut.dbg_rsp_status
                errors.append(('fault', e, s))
                break
            yield
        yield dut.compact_req_valid.eq(1)
        yield dut.compact_req_addr.eq(HIT_ADDR)
        yield dut.compact_req_tag.eq(0xCC)
        yield
        yield dut.compact_req_valid.eq(0)
        for _ in range(10):
            cv = yield dut.compact_rsp_valid
            if cv:
                e2 = yield dut.dbg_rsp_error
                s2 = yield dut.dbg_rsp_status
                errors.append(('ok', e2, s2))
                break
            yield
    _run(dut, process)
    assert len(errors) == 2
    name1, err1, sta1 = errors[0]
    assert sta1 == 4, f"first should be FAULT(4), got {sta1}"
    assert err1 == 1, f"FAULT should have error=1, got {err1}"
    name2, err2, sta2 = errors[1]
    assert sta2 == 0, f"second should be OK(0), got {sta2}"
    assert err2 == 0, f"OK should have error=0, got {err2}"


def test_16bit_tag_preserved():
    dut = ArbiterCoherentHarness()
    def process():
        yield dut.sweep_rsp_ready.eq(1)
        yield dut.sweep_req_valid.eq(1)
        yield dut.sweep_req_addr.eq(HIT_ADDR)
        yield dut.sweep_req_tag.eq(0xABCD)
        yield
        yield dut.sweep_req_valid.eq(0)
        for _ in range(10):
            sv = yield dut.sweep_rsp_valid
            if sv:
                t = yield dut.sweep_rsp_tag
                assert t == 0xABCD, f"16-bit tag: {t:#x}"
                return
            yield
        assert False, "response timeout"
    _run(dut, process)


def test_adapter_does_not_change_single_outstanding():
    dut = ArbiterCoherentHarness(hit_latency=10)
    def process():
        yield dut.compact_rsp_ready.eq(1)
        yield dut.scan_rsp_ready.eq(1)
        yield dut.compact_req_valid.eq(1)
        yield dut.compact_req_addr.eq(HIT_ADDR)
        yield dut.compact_req_tag.eq(0xDD)
        yield
        yield dut.compact_req_valid.eq(0)
        yield
        o = yield dut.dbg_outstanding
        assert o == 1, f"expected outstanding=1 after accept, got {o}"
        yield
    _run(dut, process)
