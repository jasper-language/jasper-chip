# tests/test_gc_multi_output.py
# Multi-Output Event Pipeline throughput scaling tests.
from amaranth import *
from amaranth.sim import Simulator
import pytest
from rtl.gc_event_pipeline import GCEventPipelineSeparated, EVT_SCAN, EVT_SWEEP, EVT_MOVE
from rtl.gc_multi_output_pipeline import MultiOutputEventPipeline


def measure_throughput(name, dut, output_ports, is_multi=False, N=500):
    """Inject N mixed events and measure total throughput across all ports."""
    sim = Simulator(dut); sim.add_clock(1e-6)
    result = {}
    async def proc(ctx):
        await ctx.tick()
        # Use epoch=0 to match warmup and avoid epoch filtering
        if hasattr(dut, 'current_epoch'):
            ctx.set(dut.current_epoch, 0)
        # Warmup
        for _ in range(4):
            ctx.set(dut.event_valid, 1); ctx.set(dut.event_type, EVT_SCAN)
            ctx.set(dut.event_addr, 0x1000); ctx.set(dut.event_data, 0)
            await ctx.tick(); ctx.set(dut.event_valid, 0); await ctx.tick()
        for _ in range(8):
            if is_multi:
                for p in range(output_ports): ctx.set(dut.rsp_ready[p], 1)
            else:
                ctx.set(dut.result_ready, 1)
            await ctx.tick()
        # Measure
        injected = 0; total_responses = 0; stall = 0
        evt_types = [EVT_SCAN, EVT_SWEEP, EVT_MOVE]
        for i in range(N):
            et = evt_types[i % 3]
            ctx.set(dut.event_valid, 1); ctx.set(dut.event_type, et)
            ctx.set(dut.event_addr, 0x1000 + (i % 64))
            ctx.set(dut.event_data, i & 0xFF)
            ctx.set(dut.event_tag, i & 0xFF)
            if hasattr(dut, 'event_epoch'): ctx.set(dut.event_epoch, 0)
            if is_multi:
                for p in range(output_ports): ctx.set(dut.rsp_ready[p], 1)
            else:
                ctx.set(dut.result_ready, 1)
            er = ctx.get(dut.event_ready)
            await ctx.tick()
            if er: injected += 1
            else: stall += 1
            if is_multi:
                for p in range(output_ports):
                    if ctx.get(dut.rsp_valid[p]): total_responses += 1
            else:
                if ctx.get(dut.result_valid): total_responses += 1
        ctx.set(dut.event_valid, 0)
        for _ in range(32):
            if is_multi:
                for p in range(output_ports): ctx.set(dut.rsp_ready[p], 1)
            else:
                ctx.set(dut.result_ready, 1)
            await ctx.tick()
            if is_multi:
                for p in range(output_ports):
                    if ctx.get(dut.rsp_valid[p]): total_responses += 1
            else:
                if ctx.get(dut.result_valid): total_responses += 1
            if not ctx.get(dut.busy): break
        result["injected"] = injected
        result["responses"] = total_responses
        result["stall"] = stall
        result["accept_rate"] = injected / N
        result["response_rate"] = total_responses / N
    sim.add_testbench(proc); sim.run()
    return result


def test_baseline_separated():
    """Standard GCEventPipelineSeparated as baseline."""
    dut = GCEventPipelineSeparated()
    r = measure_throughput("Separated(1-out)", dut, 1, is_multi=False)
    ar = r["accept_rate"]; rr = r["response_rate"]
    ok = "✅" if ar > 0.95 else "❌"
    print(f"  Separated(1-out): {r['injected']}/{500} acc ({ar:.3f}/cyc) {r['responses']} rsp ({rr:.3f}/cyc) stall={r['stall']} {ok}")
    assert ar >= 0.95


def run_multi_output_case(ports):
    """MultiOutputEventPipeline with N output ports."""
    dut = MultiOutputEventPipeline(output_ports=ports)
    r = measure_throughput(f"MultiOut({ports}-out)", dut, ports, is_multi=True)
    ar = r["accept_rate"]; rr = r["response_rate"]
    ok = "✅" if ar > 0.95 else "❌"
    print(f"  MultiOut({ports}-out):  {r['injected']}/{500} acc ({ar:.3f}/cyc) {r['responses']} rsp ({rr:.3f}/cyc) stall={r['stall']} {ok}")
    return ar >= 0.95, r


@pytest.mark.parametrize("ports", [1, 2, 3, 4])
def test_multi_output(ports):
    ok, _ = run_multi_output_case(ports)
    assert ok

if __name__ == "__main__":
    print("=== Multi-Output Throughput Scaling ===\n")

    # Baseline
    print("--- Baseline ---")
    test_baseline_separated()

    # Multi-output scaling
    print("\n--- Multi-Output Scaling ---")
    results = {}
    for ports in [1, 2, 3, 4]:
        ok, r = run_multi_output_case(ports)
        results[ports] = r

    print("\n=== Scaling Summary ===")
    base = results[1]["responses"]
    for ports, r in results.items():
        gain = r["responses"] / base if base > 0 else 0
        ar = r["accept_rate"]
        rr = r["response_rate"]
        print(f"  {ports}-output: accept={ar:.3f}/cyc resp={rr:.3f}/cyc gain={gain:.1f}× vs 1-out stall={r['stall']}")
