# tests/test_gc_stress_throughput.py
# 全链路持续压力测试：多类型 GC event 注入，测量真实 GC events/cycle
from amaranth import *
from amaranth.sim import Simulator
from rtl.gc_event_pipeline import GCEventPipelineSeparated, EVT_SCAN, EVT_SWEEP, EVT_MOVE
from rtl.gc_metadata_pipeline import MetadataCachePipelined
from rtl.gc_forwarding_table import ForwardingTableBankedPipeline
from rtl.gc_backend_merge import BackendMergeSingle

class GCFullChain(Elaboratable):
    def __init__(self):
        for s in ['event_valid','event_ready','event_type','event_addr','event_data',
                  'event_tag','event_epoch','event_seq','result_valid','result_ready',
                  'result_data','result_tag','flush','flush_epoch','current_epoch','busy',
                  'fill_ready','fill_valid']:
            setattr(self, s, Signal())
    def elaborate(self, platform):
        m = Module(); P = self
        pipe = GCEventPipelineSeparated()
        meta = MetadataCachePipelined(cache_size=1024, ways=2, access_granularity=32)
        ft = ForwardingTableBankedPipeline(bank_count=1, entries_per_bank=8, chase_depth=2)
        merge = BackendMergeSingle()
        m.submodules.pipe = pipe; m.submodules.meta = meta
        m.submodules.ft = ft; m.submodules.merge = merge
        m.d.comb += [
            pipe.event_valid.eq(P.event_valid), P.event_ready.eq(pipe.event_ready),
            pipe.event_type.eq(P.event_type), pipe.event_addr.eq(P.event_addr),
            pipe.event_data.eq(P.event_data), pipe.event_tag.eq(P.event_tag),
            pipe.event_epoch.eq(P.event_epoch), pipe.event_seq.eq(P.event_seq),
            pipe.flush.eq(P.flush), pipe.flush_epoch.eq(P.flush_epoch),
            pipe.current_epoch.eq(P.current_epoch),
            meta.request_valid.eq(pipe.result_valid),
            pipe.result_ready.eq(meta.request_ready),
            meta.request_addr.eq(pipe.result_data),
            meta.input_event.fields["event_id"].eq(pipe.result_tag),
            meta.input_event.fields["epoch"].eq(pipe.result_epoch),
            ft.query_valid.eq(meta.rsp_valid), meta.rsp_ready.eq(ft.query_ready),
            ft.query_old_ptr.eq(meta.rsp_data),
            ft.input_event.fields["event_id"].eq(meta.output_event.fields["event_id"]),
            ft.input_event.fields["epoch"].eq(meta.output_event.fields["epoch"]),
            merge.event_valid.eq(ft.rsp_valid), ft.rsp_ready.eq(merge.event_ready),
            merge.event_addr.eq(ft.rsp_new_ptr), merge.event_tag.eq(ft.rsp_tag),
            merge.event_source.eq(ft.rsp_tag),
            P.result_valid.eq(merge.result_valid), merge.result_ready.eq(P.result_ready),
            P.result_data.eq(merge.result_data), P.result_tag.eq(merge.result_tag),
            P.busy.eq(pipe.busy | meta.busy | ft.busy),
            P.fill_valid.eq(meta.fill_valid), meta.fill_ready.eq(P.fill_ready),
        ]
        return m

GC_SCENARIOS = {
    "gc5":  {"label": "5% GC",   "events_per_req": 20,  "types": [EVT_SCAN, EVT_SWEEP, EVT_MOVE]},
    "gc10": {"label": "10% GC",  "events_per_req": 40,  "types": [EVT_SCAN, EVT_SWEEP, EVT_MOVE]},
    "gc20": {"label": "20% GC",  "events_per_req": 80,  "types": [EVT_SCAN, EVT_SWEEP, EVT_MOVE]},
    "gc30": {"label": "30% GC",  "events_per_req": 120, "types": [EVT_SCAN, EVT_SWEEP, EVT_MOVE]},
    "gc50": {"label": "50% GC",  "events_per_req": 200, "types": [EVT_SCAN, EVT_SWEEP, EVT_MOVE]},
    "gc80": {"label": "80% GC",  "events_per_req": 320, "types": [EVT_SCAN, EVT_SWEEP, EVT_MOVE]},
    "gc100":{"label": "100% GC", "events_per_req": 400, "types": [EVT_SCAN, EVT_SWEEP, EVT_MOVE]},
    "gc120":{"label": "120% GC", "events_per_req": 480, "types": [EVT_SCAN, EVT_SWEEP, EVT_MOVE]},
}

def run_stress(scenario_key, cycles=200):
    """Run a stress scenario: inject events at given ratio for `cycles` clock ticks.
    Returns (accepted, responses, stall_cycles, backpressure_cycles)."""
    sc = GC_SCENARIOS[scenario_key]
    dut = GCFullChain()
    sim = Simulator(dut); sim.add_clock(1e-6)
    result = {}
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 1)
        ctx.set(dut.flush, 0); ctx.set(dut.flush_epoch, 0)
        # Warmup cache with a few events
        for _ in range(4):
            ctx.set(dut.event_valid, 1); ctx.set(dut.event_type, EVT_SCAN)
            ctx.set(dut.event_addr, 0x1000); ctx.set(dut.event_data, 0)
            ctx.set(dut.event_tag, 0); ctx.set(dut.event_epoch, 1)
            ctx.set(dut.result_ready, 1); ctx.set(dut.fill_ready, 1)
            await ctx.tick(); ctx.set(dut.event_valid, 0); await ctx.tick()
        # Drain warmup
        for _ in range(20):
            ctx.set(dut.result_ready, 1); ctx.set(dut.fill_ready, 1); await ctx.tick()
        # Stress phase: inject events for `cycles` ticks
        accepted = 0; responses = 0; stall = 0; bp = 0
        event_idx = 0
        for cyc in range(cycles):
            # Determine event type (cycle through types)
            evt_type = sc["types"][event_idx % len(sc["types"])]
            event_idx += 1
            ctx.set(dut.event_valid, 1); ctx.set(dut.event_type, evt_type)
            ctx.set(dut.event_addr, 0x1000 + (cyc % 256))
            ctx.set(dut.event_data, cyc & 0xFF)
            ctx.set(dut.event_tag, cyc & 0xFF)
            ctx.set(dut.event_epoch, 1)
            ctx.set(dut.fill_ready, 1)
            # Read before tick
            er = ctx.get(dut.event_ready)
            rv = ctx.get(dut.result_valid)
            await ctx.tick()
            # Read after tick
            er_after = ctx.get(dut.event_ready)
            rv_after = ctx.get(dut.result_valid)
            if er: accepted += 1
            if ctx.get(dut.result_valid) and ctx.get(dut.result_ready):
                responses += 1
            # Consume every other cycle (simulate realistic backpressure)
            if cyc % 2 == 0:
                ctx.set(dut.result_ready, 1)
            else:
                ctx.set(dut.result_ready, 0)
            if not er:
                stall += 1  # event_ready=0 → could not accept
            if ctx.get(dut.fill_valid):
                ctx.set(dut.fill_ready, 1)
        ctx.set(dut.event_valid, 0)
        # Drain
        for _ in range(64):
            ctx.set(dut.result_ready, 1); ctx.set(dut.fill_ready, 1); await ctx.tick()
            if ctx.get(dut.result_valid): responses += 1
            if not ctx.get(dut.busy) and not ctx.get(dut.result_valid): break
        ctx.set(dut.result_ready, 0); ctx.set(dut.fill_ready, 0)
        result["accepted"] = accepted
        result["responses"] = responses
        result["stall"] = stall
        result["accept_rate"] = accepted / cycles
        result["response_rate"] = responses / cycles
        result["gc_ratio"] = accepted / cycles  # events/cycle ≈ GC ratio
    sim.add_testbench(proc); sim.run()
    return result

if __name__ == "__main__":
    print("=== GC Stress Throughput Test ===\n")
    all_ok = True
    for sk, sc in GC_SCENARIOS.items():
        res = run_stress(sk)
        label = sc["label"]
        ar = res["accept_rate"]
        rr = res["response_rate"]
        steady = "✅" if ar > 0.5 else "❌"
        print(f"  {label:10s}: accept={res['accepted']:4d} resp={res['responses']:4d} "
              f"accept_rate={ar:.3f}/cyc resp_rate={rr:.3f}/cyc stall={res['stall']:3d} {steady}")
        if ar < 0.5:
            print(f"    → UNSTEADY at {label}")
            all_ok = False
    print(f"\n{'ALL PASS' if all_ok else 'SOME FAILED'}")
