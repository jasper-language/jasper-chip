# tests/test_gc_gateway_rtl.py
# RTL simulation of synthetic gateway trace: measures actual throughput vs model.
from amaranth import *
from amaranth.sim import Simulator
from rtl.gc_event_pipeline import GCEventPipelineSeparated, EVT_SCAN, EVT_SWEEP, EVT_MOVE
from rtl.gc_metadata_pipeline import MetadataCachePipelined
from rtl.gc_forwarding_table import ForwardingTableBankedPipeline
from rtl.gc_backend_merge import BackendMergeSingle
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from tools.gc_gateway_stress import WORKLOADS, compute_trace, CONFIGS, analyze_qps

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
            merge.event_valid.eq(ft.rsp_valid), ft.rsp_ready.eq(merge.event_ready),
            merge.event_addr.eq(ft.rsp_new_ptr), merge.event_tag.eq(ft.rsp_tag),
            merge.event_source.eq(ft.rsp_tag),
            P.result_valid.eq(merge.result_valid), merge.result_ready.eq(P.result_ready),
            P.result_data.eq(merge.result_data), P.result_tag.eq(merge.result_tag),
            P.busy.eq(pipe.busy | meta.busy | ft.busy),
            P.fill_valid.eq(meta.fill_valid), meta.fill_ready.eq(P.fill_ready),
        ]
        return m

def run_gateway(workload_name, config_name, target_qps, cycles=400):
    """Run a gateway workload at a target QPS for `cycles` ticks.
    Returns dict with RTL simulation results."""
    trace = compute_trace(workload_name)
    model = analyze_qps(config_name, CONFIGS[config_name], trace, target_qps)
    gc_events_per_req = trace["gc_events"]
    events_per_cycle = gc_events_per_req * target_qps / 1e9
    # RTL simulation
    dut = GCFullChain()
    sim = Simulator(dut); sim.add_clock(1e-6)
    result = {}
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 1)
        # Warmup
        for _ in range(4):
            ctx.set(dut.event_valid, 1); ctx.set(dut.event_type, EVT_SCAN)
            ctx.set(dut.event_addr, 0x1000); ctx.set(dut.event_data, 0)
            ctx.set(dut.event_tag, 0); ctx.set(dut.event_epoch, 1)
            ctx.set(dut.result_ready, 1); ctx.set(dut.fill_ready, 1)
            await ctx.tick(); ctx.set(dut.event_valid, 0); await ctx.tick()
        for _ in range(10):
            ctx.set(dut.result_ready, 1); ctx.set(dut.fill_ready, 1); await ctx.tick()
        # Stress phase
        acc = 0; rsp = 0; stall = 0; bp_cycles = 0
        evt_types = [EVT_SCAN, EVT_SWEEP, EVT_MOVE]
        interval = 1_000_000_000 // target_qps
        next_cycle = interval
        for cyc in range(cycles):
            evt = evt_types[cyc % 3]
            fire = cyc >= next_cycle
            if fire:
                ctx.set(dut.event_valid, 1); ctx.set(dut.event_type, evt)
                ctx.set(dut.event_addr, 0x1000 + (cyc % 64))
                ctx.set(dut.event_data, cyc & 0xFF)
                ctx.set(dut.event_tag, cyc & 0xFF); ctx.set(dut.event_epoch, 1)
                next_cycle += interval
            else:
                ctx.set(dut.event_valid, 0)
            ctx.set(dut.fill_ready, 1)
            er = ctx.get(dut.event_ready)
            await ctx.tick()
            if fire:
                if er: acc += 1
                else: stall += 1
            if ctx.get(dut.result_valid):
                rsp += 1
            # 50% result consumption duty cycle
            ctx.set(dut.result_ready, 1 if cyc % 2 == 0 else 0)
        ctx.set(dut.event_valid, 0)
        for _ in range(32):
            ctx.set(dut.result_ready, 1); ctx.set(dut.fill_ready, 1); await ctx.tick()
            if ctx.get(dut.result_valid): rsp += 1
            if not ctx.get(dut.busy) and not ctx.get(dut.result_valid): break
        ctx.set(dut.result_ready, 0); ctx.set(dut.fill_ready, 0)
        result["accept_rate"] = acc / cycles
        result["response_rate"] = rsp / cycles
        result["stall"] = stall
        result["events_per_cycle"] = events_per_cycle
        result["model_steady"] = model["steady"]
        result["model_bottleneck"] = model["first_bottleneck"]
    sim.add_testbench(proc); sim.run()
    return result

if __name__ == "__main__":
    print("=== Gateway RTL Simulation vs Model ===\n")
    configs = [("standard_baseline", "Standard"), ("experimental_single", "Exp Single")]
    workloads = ["gateway_normal", "gateway_heavy", "gateway_extreme"]
    qps_levels = [100_000, 500_000, 1_000_000, 2_000_000, 5_000_000]
    all_pass = True
    for cfg_key, cfg_label in configs:
        print(f"--- {cfg_label} ---")
        for wl in workloads:
            trace = compute_trace(wl)
            line = f"  {wl:20s}"
            for qps in qps_levels:
                model = analyze_qps(cfg_key, CONFIGS[cfg_key], trace, qps)
                rtl = run_gateway(wl, cfg_key, qps, cycles=300)
                match = "✅" if rtl["model_steady"] == (rtl["stall"] == 0) else "⚠️"
                gc_pct = rtl["events_per_cycle"] * 100
                if qps in [100_000, 1_000_000, 5_000_000]:
                    print(f"    {qps:>7,} QPS: RTL acc={rtl['accept_rate']:.3f}/cyc "
                          f"stall={rtl['stall']:3d} GC={gc_pct:.0f}% "
                          f"model={'✅' if rtl['model_steady'] else '❌'} {match}")
            if wl == workloads[-1]:
                print()
    print("=== Done ===")
