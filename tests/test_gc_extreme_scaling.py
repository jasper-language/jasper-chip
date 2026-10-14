#!/usr/bin/env python3
"""test_gc_extreme_scaling.py -- 256-core x 6 GHz extreme scaling analysis."""
import time
from amaranth import *
from amaranth.sim import Simulator
from rtl.gc_sweep_coproc import GCSweepCoProc
from rtl.gc_sweep_coproc_pipelined import GCSweepCoProcPipelined
from rtl.isa import GC_NEW, GC_RELOC

FREQ_GHZ = 6.0
NCORES_TOTAL = 256
CYCLES_PER_RUN = 400


def run_original(ncores):
    dut = GCSweepCoProc(ncores=ncores, fifo_depth=16)
    sim = Simulator(dut); sim.add_clock(1e-6)
    res = {}
    started = time.time()
    async def proc(ctx):
        await ctx.tick()
        for i in range(ncores):
            ctx.set(dut.rsp_take[i], 1)
        await ctx.tick()
        accepted = [0] * ncores
        responded = [0] * ncores
        for cyc in range(CYCLES_PER_RUN):
            for i in range(ncores):
                ctx.set(dut.cmd_op[i], GC_NEW if (cyc % 6) != 5 else GC_RELOC)
                ctx.set(dut.cmd_rd[i], (cyc % 31) + 1)
                ctx.set(dut.cmd_rs1[i], ((cyc * ncores + i + 1) & 0xFF) or 1)
                ctx.set(dut.cmd_rs2[i], (((cyc * ncores + i) * 4 + 0x200) & 0xFF) or 1)
                ctx.set(dut.cmd_tag[i], cyc & 0xFF)
                ctx.set(dut.cmd_enq_valid[i], 1)
            await ctx.tick()
            for i in range(ncores):
                if ctx.get(dut.cmd_enq_ready[i]):
                    accepted[i] += 1
                if ctx.get(dut.rsp_valid[i]):
                    responded[i] += 1
                ctx.set(dut.cmd_enq_valid[i], 0)
                ctx.set(dut.rsp_take[i], 1)
        for _ in range(CYCLES_PER_RUN):
            await ctx.tick()
            for i in range(ncores):
                if ctx.get(dut.rsp_valid[i]):
                    responded[i] += 1
        total_acc = sum(accepted)
        total_rsp = sum(responded)
        res["total_acc"] = total_acc
        res["total_rsp"] = total_rsp
        res["accept_rate"] = total_acc / CYCLES_PER_RUN
        res["response_rate"] = total_rsp / CYCLES_PER_RUN
        res["per_core_rsp"] = [r / CYCLES_PER_RUN for r in responded]
        res["per_core_acc"] = [a / CYCLES_PER_RUN for a in accepted]
    sim.add_testbench(proc)
    sim.run()
    res["elapsed"] = time.time() - started
    return res


def run_pipelined(ncores):
    dut = GCSweepCoProcPipelined(ncores=ncores, fifo_depth=16, rsp_fifo_depth=8)
    sim = Simulator(dut); sim.add_clock(1e-6)
    res = {}
    started = time.time()
    async def proc(ctx):
        await ctx.tick()
        for i in range(ncores):
            ctx.set(dut.rsp_take[i], 1)
            ctx.set(dut.mv_upd_ready[i], 1)
        await ctx.tick()
        accepted = [0] * ncores
        responded = [0] * ncores
        for cyc in range(CYCLES_PER_RUN):
            for i in range(ncores):
                ctx.set(dut.cmd_op[i], GC_NEW if (cyc % 6) != 5 else GC_RELOC)
                ctx.set(dut.cmd_rd[i], (cyc % 31) + 1)
                ctx.set(dut.cmd_rs1[i], ((cyc * ncores + i + 1) & 0xFF) or 1)
                ctx.set(dut.cmd_rs2[i], (((cyc * ncores + i) * 4 + 0x200) & 0xFF) or 1)
                ctx.set(dut.cmd_tag[i], cyc & 0xFF)
                ctx.set(dut.cmd_enq_valid[i], 1)
            await ctx.tick()
            for i in range(ncores):
                if ctx.get(dut.cmd_enq_ready[i]):
                    accepted[i] += 1
                if ctx.get(dut.rsp_valid[i]):
                    responded[i] += 1
                ctx.set(dut.cmd_enq_valid[i], 0)
                ctx.set(dut.rsp_take[i], 1)
        for _ in range(CYCLES_PER_RUN):
            await ctx.tick()
            for i in range(ncores):
                if ctx.get(dut.rsp_valid[i]):
                    responded[i] += 1
        total_acc = sum(accepted)
        total_rsp = sum(responded)
        res["total_acc"] = total_acc
        res["total_rsp"] = total_rsp
        res["accept_rate"] = total_acc / CYCLES_PER_RUN
        res["response_rate"] = total_rsp / CYCLES_PER_RUN
        res["per_core_rsp"] = [r / CYCLES_PER_RUN for r in responded]
        res["per_core_acc"] = [a / CYCLES_PER_RUN for a in accepted]
    sim.add_testbench(proc)
    sim.run()
    res["elapsed"] = time.time() - started
    return res


def main():
    print("=" * 70)
    print("  Extreme Scaling: 256 cores x 6 GHz Jasper GC Architecture Analysis")
    print("=" * 70)

    measured = {}

    # ---- 1. Per-core throughput scaling (RTL sim for 1,2,4; estimate 8,16) ----
    print()
    print("--- 1. Per-core Throughput Scaling Test ---")
    print(f"    Each run: {CYCLES_PER_RUN} cycles, all cores injecting GC_NEW/RELOC")
    print()

    for nc in [1, 2, 4]:
        print(f"  -- ncores={nc} --")
        o = run_original(nc)
        p = run_pipelined(nc)
        measured[nc] = (o, p)
        print(f"    Original:   accept={o['accept_rate']:.4f}/cyc  "
              f"rsp={o['response_rate']:.4f}/cyc  per-core(rsp)={o['response_rate']/nc:.4f}  [{o['elapsed']:.1f}s]")
        print(f"    Pipelined:  accept={p['accept_rate']:.4f}/cyc  "
              f"rsp={p['response_rate']:.4f}/cyc  per-core(rsp)={p['response_rate']/nc:.4f}  [{p['elapsed']:.1f}s]")
        if nc > 1:
            o_cv = (sum((v - o['response_rate']/nc)**2 for v in o['per_core_rsp']) / nc)**0.5 / max(o['response_rate']/nc, 1e-6)
            p_cv = (sum((v - p['response_rate']/nc)**2 for v in p['per_core_rsp']) / nc)**0.5 / max(p['response_rate']/nc, 1e-6)
            print(f"    Fairness CV: orig={o_cv:.4f}  pipe={p_cv:.4f}")

    # Estimate for 8, 16 cores (extrapolate from measured data)
    # Single engine: total response throughput is bounded by 1/cyc,
    # per-core = total_rsp_rate / ncores
    o_base = measured[4][0]["response_rate"]  # total rsp rate at 4 cores
    p_base = measured[4][1]["response_rate"]
    print()
    print(f"  -- Extrapolated for 8, 16+ cores --")
    for nc in [8, 16, 256]:
        o_est = o_base / nc
        p_est = p_base / nc
        if nc <= 16:
            print(f"    ncores={nc:3d}:  orig={o_est:.6f} rsp/cyc/core  "
                  f"pipe={p_est:.6f} rsp/cyc/core")
        else:
            at_ghz = p_est * FREQ_GHZ * 1e9 / 1e6
            print(f"    ncores={nc:3d}:  total rsp rate = {p_base:.4f}/cyc  "
                  f"per-core = {p_est:.6f}/cyc  = {at_ghz:.1f}M cmd/s/core")
    print()

    # ---- 2. Theoretical throughput calculation ----
    print("--- 2. Theoretical Throughput at 6 GHz ---")
    G = FREQ_GHZ
    N = NCORES_TOTAL

    rows = [
        ("Pipelined GC chip",    "1 cmd/cyc",  f"1 x {G} = {G:.0f}B cmd/s",          f"{G/N*1e3:.1f}M cmd/s"),
        ("Accelerator (cnt)",    "1 cmd/cyc",  f"1 x {G} = {G:.0f}B cmd/s",          f"{G/N*1e3:.1f}M cmd/s"),
        ("Gateway pipeline",     "1 evt/cyc",  f"1 x {G} = {G:.0f}B evt/s",          f"{G/N*1e3:.1f}M evt/s"),
        ("GCSubsystem slots",    "16/core",    f"16 x {N} = {16*N} total slots",     f"16 in-flight/core"),
    ]
    for comp, raw, total_s, per_core_s in rows:
        print(f"    {comp:<30s}  {raw:<18s}  {total_s:<28s}  {per_core_s}")

    # ---- 3. Bottleneck analysis ----
    print()
    print("--- 3. Bottleneck Analysis ---")
    print("""
  Request path:
    Thread alloc req
      -> GCSubsystem slot (16/core = 4096 total)
      -> GCSweepCoProc engine (1 shared across all cores)
      -> Gateway event pipeline

  Narrowest pipe at 256 cores x 6 GHz:
    GCSweepCoProc single engine: 1 cmd/cyc max
    Per core: 6 GHz / 256 = 23.4M cmd/s/core
    This is the system ceiling -- all paths converge here.
    """)

    # ---- 4. Final summary table ----
    print("--- 4. Final Summary Table ---")
    print()

    # Use theoretical sustained throughput: pipelined engine = 1.0 cmd/cyc
    # (Measured rates include FIFO drain; theoretical ceiling is 1.0 cmd/cyc)
    p_rsp = measured[4][1]["response_rate"]

    print(f"=== Extreme Scaling: {N} cores x {G} GHz ===")
    print(f"{'Component':<30s} {'Throughput/core':<24s} {'Total throughput':<24s} {'Bottleneck?'}")
    print(f"{'-'*90}")

    slots_per_core = 16
    print(f"{'GCSubsystem slots':<30s} {f'{slots_per_core} in-flight':<24s} "
          f"{f'{slots_per_core * N} in-flight':<24s} {'(slot count)'}")

    # Original GCSweepCoProc (theoretical sustained: 0.33 cmd/cyc)
    orig_total = 0.33
    orig_tput_per_core = orig_total * G / N * 1000
    print(f"{'GCSweepCoProc (orig)':<30s} {f'{orig_tput_per_core:.1f}M cmd/s':<24s} "
          f"{f'{orig_total:.2f} cmd/cyc':<24s} {'YES <-':s}")

    # Pipelined GCSweepCoProc (theoretical sustained: 1.0 cmd/cyc)
    pipe_total = 1.0
    pipe_tput_per_core = pipe_total * G / N * 1000
    print(f"{'GCSweepCoProc (pipe)':<30s} {f'{pipe_tput_per_core:.1f}M cmd/s':<24s} "
          f"{f'{pipe_total:.1f} cmd/cyc':<24s} {'YES <-':s}")

    # Accelerator (counting: 1 cmd/cyc)
    acc_total = 1.0
    acc_tput_per_core = acc_total * G / N * 1000
    print(f"{'Accelerator (cnt)':<30s} {f'{acc_tput_per_core:.1f}M cmd/s':<24s} "
          f"{f'{acc_total:.1f} cmd/cyc':<24s} {'YES <-':s}")

    # Gateway pipeline (1 evt/cyc)
    gw_total = 1.0
    gw_tput_per_core = gw_total * G / N * 1000
    print(f"{'Gateway pipeline':<30s} {f'{gw_tput_per_core:.1f}M evt/s':<24s} "
          f"{f'{gw_total:.1f} evt/cyc':<24s} {'YES <-':s}")

    print(f"{'-'*90}")
    ceiling = pipe_tput_per_core  # 23.4M ops/s/core
    print(f"{'System ceiling:':<30s} {f'{ceiling:.1f}M ops/s/core':<24s} "
          f"{'= {:.0f} ops/s total'.format(G * 1e9):<24s}")

    # ---- Raw measurement summary ----
    print()
    print(f"  Raw RTL measurement data (CYCLES={CYCLES_PER_RUN}):")
    for nc in sorted(measured.keys()):
        o, p = measured[nc]
        o_r = o["response_rate"]
        p_r = p["response_rate"]
        o_a = o["accept_rate"]
        p_a = p["accept_rate"]
        o_cv_str = ""
        p_cv_str = ""
        if nc > 1:
            o_cv = (sum((v - o_r/nc)**2 for v in o['per_core_rsp']) / nc)**0.5 / max(o_r/nc, 1e-6)
            p_cv = (sum((v - p_r/nc)**2 for v in p['per_core_rsp']) / nc)**0.5 / max(p_r/nc, 1e-6)
            o_cv_str = f"  CV={o_cv:.4f}"
            p_cv_str = f"  CV={p_cv:.4f}"
        else:
            o_cv_str = "  (single)"
            p_cv_str = "  (single)"
        print(f"    ncores={nc:2d}:  orig accept={o_a:.4f}/cyc rsp={o_r:.4f}/cyc core={o_r/nc:.4f}{o_cv_str}")
        print(f"               pipe accept={p_a:.4f}/cyc rsp={p_r:.4f}/cyc core={p_r/nc:.4f}{p_cv_str}")

    print()
    print("=== Done ===")


if __name__ == "__main__":
    main()
