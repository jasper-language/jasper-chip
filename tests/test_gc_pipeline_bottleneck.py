#!/usr/bin/env python3
"""Pipeline bottleneck profiler — tests each GCFullChain stage individually."""
import sys
from amaranth import *
from amaranth.sim import Simulator

from rtl.gc_event_pipeline import (
    GCEventPipelineSeparated,
    EVT_SCAN, EVT_SWEEP, EVT_MOVE
)
from rtl.gc_metadata_pipeline import MetadataCachePipelined
from rtl.gc_forwarding_table import ForwardingTableBankedPipeline
from rtl.gc_backend_merge import BackendMergeSingle


def bench_event_pipeline():
    """Measure GCEventPipelineSeparated acceptance & production rates."""
    dut = GCEventPipelineSeparated()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    res = {}

    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 1)
        ctx.set(dut.event_epoch, 1)
        ctx.set(dut.flush, 0)

        N = 1000
        accepted = 0
        produced = 0

        for i in range(N):
            ctx.set(dut.event_valid, 1)
            ctx.set(dut.event_type,
                    [EVT_SCAN, EVT_SWEEP, EVT_MOVE][i % 3])
            ctx.set(dut.event_addr, i * 4)
            ctx.set(dut.event_data, i)
            ctx.set(dut.event_tag, i & 0xFF)
            ctx.set(dut.event_seq, i & 3)
            ctx.set(dut.result_ready, 1)
            await ctx.tick()

            if ctx.get(dut.event_ready):
                accepted += 1
            if ctx.get(dut.result_valid):
                produced += 1

        ctx.set(dut.event_valid, 0)
        drain = 0
        for _ in range(200):
            ctx.set(dut.result_ready, 1)
            await ctx.tick()
            drain += 1
            if ctx.get(dut.result_valid):
                produced += 1
            elif not ctx.get(dut.busy):
                break

        res['accepted'] = accepted
        res['produced'] = produced
        res['cycles'] = N + drain

    sim.add_testbench(proc)
    sim.run()
    return res['accepted'], res['produced'], res['cycles']


def bench_metadata_cache():
    """Measure MetadataCachePipelined acceptance & production rates."""
    dut = MetadataCachePipelined(
        cache_size=2048, ways=2, access_granularity=64
    )
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    res = {}

    async def proc(ctx):
        await ctx.tick()
        N = 1000
        accepted = 0
        produced = 0

        # Always ready to accept fill responses and consume results
        ctx.set(dut.fill_data, 0xDEAD)
        ctx.set(dut.fill_ready, 1)
        ctx.set(dut.rsp_ready, 1)

        for i in range(N):
            ctx.set(dut.request_valid, 1)
            ctx.set(dut.request_addr, (i % 32) * 256)
            ctx.set(dut.request_source, 1)
            await ctx.tick()

            if ctx.get(dut.request_ready):
                accepted += 1
            if ctx.get(dut.rsp_valid):
                produced += 1

        ctx.set(dut.request_valid, 0)
        drain = 0
        for _ in range(200):
            await ctx.tick()
            drain += 1
            if ctx.get(dut.rsp_valid):
                produced += 1
            elif not ctx.get(dut.busy):
                break

        res['accepted'] = accepted
        res['produced'] = produced
        res['cycles'] = N + drain

    sim.add_testbench(proc)
    sim.run()
    return res['accepted'], res['produced'], res['cycles']


def bench_forwarding_table():
    """Measure ForwardingTableBankedPipeline acceptance & production rates."""
    dut = ForwardingTableBankedPipeline(
        bank_count=1, entries_per_bank=8, chase_depth=2
    )
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    res = {}

    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.epoch, 1)

        # Populate all entries so queries find matches
        for i in range(8):
            ctx.set(dut.update_valid, 1)
            ctx.set(dut.update_old_ptr, i * 0x1000)
            ctx.set(dut.update_new_ptr, i * 0x1000 + 0x2000)
            ctx.set(dut.update_epoch, 1)
            await ctx.tick()
            if not ctx.get(dut.update_ready):
                await ctx.tick()
        ctx.set(dut.update_valid, 0)
        await ctx.tick()

        N = 1000
        accepted = 0
        produced = 0

        for i in range(N):
            ctx.set(dut.query_valid, 1)
            ctx.set(dut.query_old_ptr, (i % 8) * 0x1000)
            ctx.set(dut.query_tag, i & 0xFF)
            ctx.set(dut.rsp_ready, 1)
            await ctx.tick()

            if ctx.get(dut.query_ready):
                accepted += 1
            if ctx.get(dut.rsp_valid):
                produced += 1

        ctx.set(dut.query_valid, 0)
        drain = 0
        for _ in range(200):
            ctx.set(dut.rsp_ready, 1)
            await ctx.tick()
            drain += 1
            if ctx.get(dut.rsp_valid):
                produced += 1
            elif not ctx.get(dut.busy):
                break

        res['accepted'] = accepted
        res['produced'] = produced
        res['cycles'] = N + drain

    sim.add_testbench(proc)
    sim.run()
    return res['accepted'], res['produced'], res['cycles']


def bench_backend_merge():
    """Measure BackendMergeSingle acceptance & production rates."""
    dut = BackendMergeSingle(data_width=32, tag_width=8, backend_count=1)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    res = {}

    async def proc(ctx):
        await ctx.tick()
        N = 1000
        accepted = 0
        produced = 0

        for i in range(N):
            ctx.set(dut.event_valid, 1)
            ctx.set(dut.event_addr, i * 4)
            ctx.set(dut.event_tag, i & 0xFF)
            ctx.set(dut.event_source, 1)
            ctx.set(dut.result_ready, 1)
            await ctx.tick()

            if ctx.get(dut.event_ready):
                accepted += 1
            if ctx.get(dut.result_valid):
                produced += 1

        ctx.set(dut.event_valid, 0)
        drain = 0
        for _ in range(200):
            ctx.set(dut.result_ready, 1)
            await ctx.tick()
            drain += 1
            if ctx.get(dut.result_valid):
                produced += 1
            elif not ctx.get(dut.backend_busy):
                break

        res['accepted'] = accepted
        res['produced'] = produced
        res['cycles'] = N + drain

    sim.add_testbench(proc)
    sim.run()
    return res['accepted'], res['produced'], res['cycles']


def main():
    print("=== Pipeline Stage Throughput ===")
    print(f"{'Stage':<35s} {'Inputs/cyc':<12s} {'Outputs/cyc':<12s}  Limiting?")
    print("-" * 73)

    benchmarks = [
        ("GCEventPipelineSeparated", bench_event_pipeline),
        ("MetadataCachePipelined",   bench_metadata_cache),
        ("ForwardingTableBankedPipeline", bench_forwarding_table),
        ("BackendMergeSingle",       bench_backend_merge),
    ]

    results = []
    for name, bench_fn in benchmarks:
        accepted, produced, cycles = bench_fn()
        in_rate = accepted / cycles
        out_rate = produced / cycles
        results.append((name, in_rate, out_rate, cycles))

    min_in_rate = min(r[1] for r in results)
    bottleneck = [r[0] for r in results if r[1] <= min_in_rate + 0.0001][0]

    for name, in_rate, out_rate, cycles in results:
        limiting = "YES" if name == bottleneck else "NO"
        print(f"{name:<35s} {in_rate:<12.4f} {out_rate:<12.4f}  {limiting}")

    print("-" * 73)
    print(f"Chain bottleneck: {bottleneck}")


if __name__ == "__main__":
    main()
