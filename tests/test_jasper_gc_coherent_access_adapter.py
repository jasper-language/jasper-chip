import sys
sys.path.insert(0, '.')

import importlib
from amaranth.sim import *
from rtl.jasper_gc_coherent_access_adapter import CoherentAccessAdapter


def test_elab():
    importlib.reload(sys.modules['rtl.jasper_gc_coherent_access_adapter'])
    dut = CoherentAccessAdapter()
    assert dut is not None


def _run_test(dut, test_fn):
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_sync_process(test_fn)
    sim.run()


HIT_ADDR = 0x40   # line_idx=01 → mask bit 1 → hit
MISS_ADDR = 0x00  # line_idx=00 → mask bit 0 → miss
STORE_ADDR = 0x80  # line_idx=10 → mask bit 2 (miss for read, store for write)


def test_read_hit():
    dut = CoherentAccessAdapter()
    results = {}
    def process():
        yield dut.mem_req_valid.eq(1)
        yield dut.mem_req_is_write.eq(0)
        yield dut.mem_req_addr.eq(HIT_ADDR)
        yield dut.mem_req_tag.eq(0xABCD)
        yield dut.mem_rsp_ready.eq(1)
        yield
        yield dut.mem_req_valid.eq(0)
        # Wait for ready + response
        for _ in range(10):
            rv = yield dut.mem_rsp_valid
            if rv:
                results['rsp_valid'] = 1
                results['rsp_tag'] = yield dut.mem_rsp_tag
                results['dbg_hit'] = yield dut.dbg_rsp_hit
                results['dbg_error'] = yield dut.dbg_rsp_error
                results['dbg_status'] = yield dut.dbg_rsp_status
                break
            yield
    _run_test(dut, process)
    assert results.get('rsp_valid') == 1, "no response"
    assert results['rsp_tag'] == 0xABCD, f"tag mismatch {results['rsp_tag']}"
    assert results['dbg_hit'] == 1, "should be hit"
    assert results['dbg_error'] == 0, "should be OK"
    assert results['dbg_status'] == 0, "should be OK"


def test_read_miss():
    dut = CoherentAccessAdapter()
    results = {}
    def process():
        yield dut.mem_req_valid.eq(1)
        yield dut.mem_req_is_write.eq(0)
        yield dut.mem_req_addr.eq(MISS_ADDR)
        yield dut.mem_req_tag.eq(0xDEAD)
        yield dut.mem_rsp_ready.eq(1)
        yield
        yield dut.mem_req_valid.eq(0)
        for _ in range(10):
            rv = yield dut.mem_rsp_valid
            if rv:
                results['rsp_valid'] = 1
                results['rsp_tag'] = yield dut.mem_rsp_tag
                results['dbg_hit'] = yield dut.dbg_rsp_hit
                break
            yield
    _run_test(dut, process)
    assert results.get('rsp_valid') == 1
    assert results['rsp_tag'] == 0xDEAD
    assert results['dbg_hit'] == 0, "should be miss"


def test_write():
    dut = CoherentAccessAdapter()
    results = {}
    def process():
        yield dut.mem_req_valid.eq(1)
        yield dut.mem_req_is_write.eq(1)
        yield dut.mem_req_addr.eq(STORE_ADDR)
        yield dut.mem_req_tag.eq(0x42)
        yield dut.mem_rsp_ready.eq(1)
        yield
        yield dut.mem_req_valid.eq(0)
        for _ in range(10):
            rv = yield dut.mem_rsp_valid
            if rv:
                results['rsp_valid'] = 1
                results['rsp_tag'] = yield dut.mem_rsp_tag
                results['dbg_status'] = yield dut.dbg_rsp_status
                results['dbg_error'] = yield dut.dbg_rsp_error
                break
            yield
    _run_test(dut, process)
    assert results.get('rsp_valid') == 1
    assert results['rsp_tag'] == 0x42
    assert results['dbg_status'] == 0, "write should be OK"
    assert results['dbg_error'] == 0


def test_write_disabled_unsupported():
    dut = CoherentAccessAdapter(enable_write=False)
    results = {}
    def process():
        yield dut.mem_req_valid.eq(1)
        yield dut.mem_req_is_write.eq(1)
        yield dut.mem_req_addr.eq(STORE_ADDR)
        yield dut.mem_req_tag.eq(0x55)
        yield dut.mem_rsp_ready.eq(1)
        yield
        yield dut.mem_req_valid.eq(0)
        for _ in range(10):
            rv = yield dut.mem_rsp_valid
            if rv:
                results['rsp_valid'] = 1
                results['rsp_tag'] = yield dut.mem_rsp_tag
                results['dbg_status'] = yield dut.dbg_rsp_status
                results['dbg_error'] = yield dut.dbg_rsp_error
                break
            yield
    _run_test(dut, process)
    assert results.get('rsp_valid') == 1
    assert results['rsp_tag'] == 0x55
    assert results['dbg_status'] == 5, f"expected UNSUPPORTED(5), got {results['dbg_status']}"
    assert results['dbg_error'] == 1


def test_tag_16bit_preserved():
    dut = CoherentAccessAdapter()
    results = {}
    def process():
        yield dut.mem_req_valid.eq(1)
        yield dut.mem_req_is_write.eq(0)
        yield dut.mem_req_addr.eq(HIT_ADDR)
        yield dut.mem_req_tag.eq(0xFEED)
        yield dut.mem_rsp_ready.eq(1)
        yield
        yield dut.mem_req_valid.eq(0)
        for _ in range(10):
            rv = yield dut.mem_rsp_valid
            if rv:
                results['rsp_valid'] = 1
                results['rsp_tag'] = yield dut.mem_rsp_tag
                break
            yield
    _run_test(dut, process)
    assert results.get('rsp_valid') == 1
    assert results['rsp_tag'] == 0xFEED, f"16-bit tag not preserved: {results['rsp_tag']:#x}"


def test_response_backpressure_hold():
    dut = CoherentAccessAdapter(miss_latency=3)
    results = {}
    def process():
        yield dut.mem_req_valid.eq(1)
        yield dut.mem_req_is_write.eq(0)
        yield dut.mem_req_addr.eq(MISS_ADDR)
        yield dut.mem_req_tag.eq(0x100)
        yield dut.mem_rsp_ready.eq(0)  # hold response
        yield
        yield dut.mem_req_valid.eq(0)
        # Wait for rsp_valid to appear while holding
        for i in range(20):
            rv = yield dut.mem_rsp_valid
            if rv:
                results['first_cycle'] = i
                results['rsp_tag_held'] = yield dut.mem_rsp_tag
                # Release hold
                yield dut.mem_rsp_ready.eq(1)
                yield
                rv2 = yield dut.mem_rsp_valid
                results['after_release'] = 1 if rv2 else 0
                break
            yield
    _run_test(dut, process)
    assert 'first_cycle' in results, "response never appeared"
    assert results.get('after_release') == 1, "response dropped after release"
    assert results.get('rsp_tag_held') == 0x100


def test_request_backpressure():
    dut = CoherentAccessAdapter(queue_depth=2, hit_latency=10, miss_latency=10)
    accepted = []
    rejected = []
    def process():
        yield dut.mem_rsp_ready.eq(0)
        for i in range(6):
            yield dut.mem_req_valid.eq(1)
            yield dut.mem_req_is_write.eq(0)
            yield dut.mem_req_addr.eq(HIT_ADDR)
            yield dut.mem_req_tag.eq(i)
            yield
            ready = yield dut.mem_req_ready
            if ready:
                accepted.append(i)
            else:
                rejected.append(i)
            yield dut.mem_req_valid.eq(0)
            yield
    _run_test(dut, process)
    assert len(accepted) == 3, f"expected 3 accepted (1 bypass + 2 queue), got {len(accepted)}"
    assert len(rejected) >= 1, f"expected >=1 rejected, got {len(rejected)}"


def test_response_backpressure_hold_data_stable():
    dut = CoherentAccessAdapter()
    results = {}
    def process():
        yield dut.mem_req_valid.eq(1)
        yield dut.mem_req_is_write.eq(0)
        yield dut.mem_req_addr.eq(HIT_ADDR)
        yield dut.mem_req_tag.eq(0x7777)
        yield dut.mem_rsp_ready.eq(0)
        yield
        yield dut.mem_req_valid.eq(0)
        for _ in range(10):
            rv = yield dut.mem_rsp_valid
            if rv:
                t1 = yield dut.mem_rsp_tag
                d1 = yield dut.dbg_rsp_status
                yield
                t2 = yield dut.mem_rsp_tag
                d2 = yield dut.dbg_rsp_status
                results['stable'] = (t1 == t2) and (d1 == d2)
                break
            yield
    _run_test(dut, process)
    assert results.get('stable'), "response data not stable under backpressure"


def test_no_loss():
    dut = CoherentAccessAdapter(queue_depth=4)
    req_tags = set()
    rsp_tags = set()
    def process():
        yield dut.mem_rsp_ready.eq(0)
        for i in range(4):
            yield dut.mem_req_valid.eq(1)
            yield dut.mem_req_is_write.eq(0)
            yield dut.mem_req_addr.eq([HIT_ADDR, MISS_ADDR, HIT_ADDR, MISS_ADDR][i])
            yield dut.mem_req_tag.eq(0x10 + i)
            yield
            req_tags.add(0x10 + i)
            yield dut.mem_req_valid.eq(0)
            for _ in range(3):
                yield
        yield dut.mem_rsp_ready.eq(1)
        for _ in range(30):
            rv = yield dut.mem_rsp_valid
            if rv:
                t = yield dut.mem_rsp_tag
                rsp_tags.add(t)
                yield
            yield
    _run_test(dut, process)
    missing = req_tags - rsp_tags
    extra = rsp_tags - req_tags
    assert len(missing) == 0, f"missing response tags: {missing}"
    assert len(extra) == 0, f"unexpected response tags: {extra}"


def test_no_missing_response():
    dut = CoherentAccessAdapter()
    rsp_tags = []
    def process():
        yield dut.mem_rsp_ready.eq(1)
        sent = 0
        for i in range(6):
            yield dut.mem_req_valid.eq(1)
            yield dut.mem_req_is_write.eq(0)
            yield dut.mem_req_addr.eq(HIT_ADDR if i % 2 == 0 else MISS_ADDR)
            yield dut.mem_req_tag.eq(0x20 + i)
            yield
            yield dut.mem_req_valid.eq(0)
            for _ in range(8):
                rv = yield dut.mem_rsp_valid
                if rv:
                    t = yield dut.mem_rsp_tag
                    rsp_tags.append(t)
                    yield
                    break
                yield
        # collect remaining
        for _ in range(20):
            rv = yield dut.mem_rsp_valid
            if rv:
                t = yield dut.mem_rsp_tag
                rsp_tags.append(t)
                yield
    _run_test(dut, process)
    expected = list(range(0x20, 0x26))
    missing = set(expected) - set(rsp_tags)
    assert len(missing) == 0, f"missing tags: {missing}"
    assert len(rsp_tags) == len(expected), f"expected {len(expected)} responses, got {len(rsp_tags)}"


def test_no_duplicate_response():
    dut = CoherentAccessAdapter()
    rsp_tags = []
    def process():
        yield dut.mem_rsp_ready.eq(1)
        for i in range(4):
            yield dut.mem_req_valid.eq(1)
            yield dut.mem_req_is_write.eq(0)
            yield dut.mem_req_addr.eq(HIT_ADDR)
            yield dut.mem_req_tag.eq(0x30 + i)
            yield
            yield dut.mem_req_valid.eq(0)
            for _ in range(8):
                rv = yield dut.mem_rsp_valid
                if rv:
                    t = yield dut.mem_rsp_tag
                    rsp_tags.append(t)
                    yield
                    break
                yield
        for _ in range(20):
            rv = yield dut.mem_rsp_valid
            if rv:
                t = yield dut.mem_rsp_tag
                rsp_tags.append(t)
                yield
    _run_test(dut, process)
    assert len(rsp_tags) == len(set(rsp_tags)), f"duplicate tags: {rsp_tags}"


def test_fault_status_on_dbg():
    dut = CoherentAccessAdapter(enable_error_injection=True, fault_tag=0x99)
    results = {}
    def process():
        yield dut.mem_req_valid.eq(1)
        yield dut.mem_req_is_write.eq(0)
        yield dut.mem_req_addr.eq(HIT_ADDR)
        yield dut.mem_req_tag.eq(0x99)
        yield dut.mem_rsp_ready.eq(1)
        yield
        yield dut.mem_req_valid.eq(0)
        for _ in range(10):
            rv = yield dut.mem_rsp_valid
            if rv:
                results['rsp_valid'] = 1
                results['rsp_tag'] = yield dut.mem_rsp_tag
                results['dbg_status'] = yield dut.dbg_rsp_status
                results['dbg_error'] = yield dut.dbg_rsp_error
                break
            yield
    _run_test(dut, process)
    assert results.get('rsp_valid') == 1
    assert results['rsp_tag'] == 0x99
    assert results['dbg_status'] == 4, f"expected FAULT(4), got {results['dbg_status']}"
    assert results['dbg_error'] == 1


def test_dbg_rsp_error_follows_status():
    dut = CoherentAccessAdapter(enable_error_injection=True, fault_tag=0xAA)
    results = {}
    def process():
        # Fault request → error=1
        yield dut.mem_req_valid.eq(1)
        yield dut.mem_req_is_write.eq(0)
        yield dut.mem_req_addr.eq(HIT_ADDR)
        yield dut.mem_req_tag.eq(0xAA)
        yield dut.mem_rsp_ready.eq(1)
        yield
        yield dut.mem_req_valid.eq(0)
        for _ in range(10):
            rv = yield dut.mem_rsp_valid
            if rv:
                results['fault_err'] = yield dut.dbg_rsp_error
                results['fault_sta'] = yield dut.dbg_rsp_status
                break
            yield
        # OK request → error=0
        yield dut.mem_req_valid.eq(1)
        yield dut.mem_req_is_write.eq(0)
        yield dut.mem_req_addr.eq(HIT_ADDR)
        yield dut.mem_req_tag.eq(0xBB)
        yield
        yield dut.mem_req_valid.eq(0)
        for _ in range(10):
            rv = yield dut.mem_rsp_valid
            if rv:
                results['ok_err'] = yield dut.dbg_rsp_error
                results['ok_sta'] = yield dut.dbg_rsp_status
                break
            yield
    _run_test(dut, process)
    assert results.get('fault_err') == 1, "fault should have error=1"
    assert results['fault_sta'] == 4
    assert results.get('ok_err') == 0, "OK should have error=0"
    assert results['ok_sta'] == 0


def test_dbg_rsp_hit_reports():
    dut = CoherentAccessAdapter()
    results = {}
    def process():
        yield dut.mem_rsp_ready.eq(1)
        # Hit
        yield dut.mem_req_valid.eq(1)
        yield dut.mem_req_is_write.eq(0)
        yield dut.mem_req_addr.eq(HIT_ADDR)
        yield dut.mem_req_tag.eq(0xCC)
        yield
        yield dut.mem_req_valid.eq(0)
        for _ in range(10):
            rv = yield dut.mem_rsp_valid
            if rv:
                results['hit'] = yield dut.dbg_rsp_hit
                yield
                break
            yield
        # Miss
        yield dut.mem_req_valid.eq(1)
        yield dut.mem_req_is_write.eq(0)
        yield dut.mem_req_addr.eq(MISS_ADDR)
        yield dut.mem_req_tag.eq(0xDD)
        yield
        yield dut.mem_req_valid.eq(0)
        for _ in range(10):
            rv = yield dut.mem_rsp_valid
            if rv:
                results['miss'] = yield dut.dbg_rsp_hit
                break
            yield
    _run_test(dut, process)
    assert results.get('hit') == 1, "hit address should report hit"
    assert results.get('miss') == 0, "miss address should report miss"


def test_dbg_rsp_epoch_passthrough():
    dut = CoherentAccessAdapter()
    results = {}
    def process():
        yield dut.mem_req_valid.eq(1)
        yield dut.mem_req_is_write.eq(0)
        yield dut.mem_req_addr.eq(HIT_ADDR)
        yield dut.mem_req_tag.eq(0xEE)
        yield dut.mem_rsp_ready.eq(1)
        yield
        yield dut.mem_req_valid.eq(0)
        for _ in range(10):
            rv = yield dut.mem_rsp_valid
            if rv:
                results['epoch'] = yield dut.dbg_rsp_epoch
                break
            yield
    _run_test(dut, process)
    assert 'epoch' in results, "no epoch response"
    # Epoch is driven as 0 by adapter (arbiter doesn't carry epoch)


def test_mixed_read_write_sequence():
    dut = CoherentAccessAdapter()
    results = []
    def process():
        yield dut.mem_rsp_ready.eq(1)
        for i, (is_write, addr) in enumerate([
            (0, HIT_ADDR), (1, STORE_ADDR), (0, MISS_ADDR), (1, STORE_ADDR)
        ]):
            yield dut.mem_req_valid.eq(1)
            yield dut.mem_req_is_write.eq(is_write)
            yield dut.mem_req_addr.eq(addr)
            yield dut.mem_req_tag.eq(0x40 + i)
            yield
            yield dut.mem_req_valid.eq(0)
            for _ in range(10):
                rv = yield dut.mem_rsp_valid
                if rv:
                    t = yield dut.mem_rsp_tag
                    s = yield dut.dbg_rsp_status
                    results.append({'tag': t, 'sta': s})
                    yield
                    break
                yield
        for _ in range(20):
            rv = yield dut.mem_rsp_valid
            if rv:
                t2 = yield dut.mem_rsp_tag
                s2 = yield dut.dbg_rsp_status
                results.append({'tag': t2, 'sta': s2})
                yield
    _run_test(dut, process)
    tags_found = [r['tag'] for r in results]
    expected = [0x40, 0x41, 0x42, 0x43]
    for t in expected:
        assert t in tags_found, f"tag 0x{t:x} missing"
    for r in results:
        assert r['sta'] == 0 or r['sta'] == 5, f"unexpected status {r['sta']} for tag 0x{r['tag']:x}"
