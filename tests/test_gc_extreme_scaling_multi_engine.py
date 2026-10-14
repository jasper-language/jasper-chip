#!/usr/bin/env python3
"""test_gc_extreme_scaling_multi_engine.py

256 核 × 512 线程 (SMT-2) × 6 GHz 极端性能分析。
涵盖多引擎 GCSweepCoProc、网关事件管道、加速器冷路径卸载。

三条并行路径：
  Path A: GC 指令      → GCSubsystem → GCMultiEngineCoProc → rsp
  Path B: 网关事件      → 事件管道 → MetadataCache → ForwardingTable → BackendMerge
  Path C: 加速器命令    → 冷路径溢出卸载 (4 引擎)
"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from amaranth import *
from amaranth.sim import Simulator
from rtl.gc_multi_engine_coproc import GCMultiEngineCoProc
from rtl.gc_sweep_coproc_pipelined import GCSweepCoProcPipelined
from rtl.gc_sweep_coproc import GCSweepCoProc
from rtl.isa import GC_NEW, GC_RELOC

FREQ_GHZ = 6.0
NCORES = 256
NTHREADS = 512
CYCLES_PER_RUN = 400


def run_multi_engine(ncores, num_engines):
    dut = GCMultiEngineCoProc(ncores=ncores, entries=max(64, ncores * 4),
                              num_engines=num_engines, fifo_depth=16, rsp_fifo_depth=8)
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
        res["accept_rate"] = total_acc / CYCLES_PER_RUN
        res["response_rate"] = total_rsp / CYCLES_PER_RUN
        res["per_core_rsp"] = [r / CYCLES_PER_RUN for r in responded]
    sim.add_testbench(proc)
    sim.run()
    res["elapsed"] = time.time() - started
    return res


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
        res["accept_rate"] = total_acc / CYCLES_PER_RUN
        res["response_rate"] = total_rsp / CYCLES_PER_RUN
        res["per_core_rsp"] = [r / CYCLES_PER_RUN for r in responded]
    sim.add_testbench(proc)
    sim.run()
    res["elapsed"] = time.time() - started
    return res


def main():
    print("=" * 80)
    print("  极端性能分析：256 核 × 512 线程 (SMT-2) × 6 GHz")
    print("  Jasper GC 系统：多引擎 GCSweepCoProc + 网关管道 + 加速器")
    print("=" * 80)

    G = FREQ_GHZ
    NC = NCORES
    NT = NTHREADS

    # ========================================
    # 1. RTL 实测
    # ========================================
    print()
    print("─" * 80)
    print("  [1] RTL 实测吞吐")
    print(f"      每配置 {CYCLES_PER_RUN} 周期，全部核持续注入 GC_NEW/RELOC")
    print()

    measured_orig = {}
    measured_me = {}

    for nc in [1, 2, 4]:
        o = run_original(nc)
        measured_orig[nc] = o
        print(f"    Orig  ncores={nc:2d}:  rsp={o['response_rate']:.4f}/cyc  core={o['response_rate']/nc:.4f}  [{o['elapsed']:.1f}s]")

    for ne in [1, 2, 4]:
        nc = min(ne * 2, 8)
        m = run_multi_engine(nc, num_engines=ne)
        measured_me[(nc, ne)] = m
        print(f"    ME(ne={ne}) ncores={nc:2d}:  rsp={m['response_rate']:.4f}/cyc  "
              f"per-engine={m['response_rate']/ne:.4f}  [{m['elapsed']:.1f}s]")
    print()

    # ========================================
    # 2. 三条并行路径天花板
    # ========================================
    print("─" * 80)
    print("  [2] 三条并行路径天花板 @ 6 GHz")
    print()

    print(f"  CPU:     {NC} 核 × 2 线程 (SMT-2) = {NT} 逻辑线程")
    print(f"  频率:    {G} GHz")
    print(f"  GC 插槽: 16/核 = {NC * 16} 总 (标准配置)")
    print()

    # Path A: GC 指令
    print("  Path A: GC 指令 (GCSubsystem → GCSweepCoProc)")
    print(f"  {'ne':<6s} {'原始':<14s} {'总吞吐@6GHz':<22s} {'每核':<18s} {'每线程':<18s} {'瓶颈?'}")
    print(f"  {'─'*6} {'─'*14} {'─'*22} {'─'*18} {'─'*18} {'─'*8}")
    for ne in [1, 2, 4, 8]:
        et = ne * 1.0
        total_s = et * G * 1e9
        pc = total_s / NC
        pt = total_s / NT
        tag = "← 瓶颈" if ne < 8 else ""
        print(f"  ne={ne:<3} {et:.0f} cmd/cyc  {total_s/1e9:.0f}B cmd/s  "
              f"{pc/1e6:.1f}M cmd/s  {pt/1e6:.1f}M cmd/s  {tag}")

    print()

    # Path B: 网关事件管道
    # 独立并行路径，不受 GC 指令影响
    print("  Path B: 网关事件管道 (事件 → MetadataCache → ForwardingTable → BackendMerge)")
    for sep in [False, True]:
        cap = 3.0 if sep else 1.0
        total_evt = cap * G * 1e9
        equiv_gc = total_evt / 10  # 假设每 GC 指令需 10 个辅助事件
        print(f"    {'Separated' if sep else 'Standard':<12s} {cap:.0f} evt/cyc  "
              f"{total_evt/1e9:.0f}B evt/s  "
              f"≈{equiv_gc/1e9:.0f}B 等效 GC cmds/s  "
              f"{total_evt/NC/1e6:.1f}M evt/s/core")

    print()

    # Path C: 加速器
    print("  Path C: 加速器冷路径卸载 (4 引擎)")
    for mode, et in [("计数", 4.0), ("内存延迟=4", 1.0)]:
        total_s = et * G * 1e9
        print(f"    {mode:<12s} {et:.1f} cmd/cyc  {total_s/1e9:.0f}B cmd/s  "
              f"{total_s/NC/1e6:.1f}M cmd/s/core")

    # ========================================
    # 3. 瓶颈分析
    # ========================================
    print()
    print("─" * 80)
    print("  [3] 瓶颈分析")
    print()

    print("""
  ┌──────────────────────────────────────────────────────────┐
  │  构架总览                                                │
  │                                                          │
  │  256 核 (512 线程 SMT-2) @ 6 GHz                         │
  │    ├─ Path A: GC 指令 → GCMultiEngineCoProc N 引擎       │
  │    │  每引擎 1.0 cmd/cyc, N 引擎 = N cmd/cyc 总          │
  │    │  GCSubsystem: 16 插槽/核 = 4096 并发                │
  │    │                                                      │
  │    ├─ Path B: 网关事件 → 事件管道 → 元数据 → 转发 → 合并 │
  │    │  标准: 1.0 evt/cyc, Separated: 3.0 evt/cyc          │
  │    │  独立路径, 不受 GC 指令吞吐影响                       │
  │    │                                                      │
  │    └─ Path C: 加速器 (冷路径溢出卸载)                     │
  │       4 引擎, 计数模式 ~1.0 cmd/cyc/引擎                 │
  │       仅在 GC 芯片 FIFO 饱和时介入                        │
  │                                                          │
  │  SMT-2: 512 线程竞争 256 个物理核 GC 提交端口            │
  │  每核最多 1 GC cmd/cyc → 系统总上限 256 cmd/cyc          │
  └──────────────────────────────────────────────────────────┘""")

    print(f"  GC 引擎瓶颈扫描 (ne 从 1→8):")
    for ne in [1, 2, 4, 8]:
        et = ne * 1.0
        total_gc = et * G * 1e9
        per_core = total_gc / NC
        cpu_limit = G * 1e9  # 1 cmd/cyc/core
        print(f"    ne={ne:2d}  {et:.0f} cmd/cyc  →  "
              f"{total_gc/1e9:6.0f}B cmd/s  →  "
              f"{per_core/1e6:6.1f}M/s/core  →  "
              f"占用核周期 {et/NC*100:.4f}%"
              f"{'  ← CPU 上限' if per_core > cpu_limit else ''}")

    print()
    print(f"  三路径对比表:")
    print(f"  {'路径':<14s} {'组件':<30s} {'吞吐/cyc':<14s} {'@6GHz':<18s} {'每核':<16s}")
    print(f"  {'─'*14} {'─'*30} {'─'*14} {'─'*18} {'─'*16}")
    print(f"  {'A':<14s} {'GCMultiEngine ne=1':<30s} {'1.0 cmd':<14s} {'6B cmd/s':<18s} {'23.4M/s':<16s}")
    print(f"  {'A':<14s} {'GCMultiEngine ne=2':<30s} {'2.0 cmd':<14s} {'12B cmd/s':<18s} {'46.9M/s':<16s}")
    print(f"  {'A':<14s} {'GCMultiEngine ne=4':<30s} {'4.0 cmd':<14s} {'24B cmd/s':<18s} {'93.8M/s':<16s}")
    print(f"  {'A':<14s} {'GCMultiEngine ne=8':<30s} {'8.0 cmd':<14s} {'48B cmd/s':<18s} {'187.5M/s':<16s}")
    print(f"  {'B':<14s} {'Gateway 标准':<30s} {'1.0 evt':<14s} {'6B evt/s':<18s} {'23.4M/s':<16s}")
    print(f"  {'B':<14s} {'Gateway Separated':<30s} {'3.0 evt':<14s} {'18B evt/s':<18s} {'70.3M/s':<16s}")
    print(f"  {'C':<14s} {'Accelerator 计数':<30s} {'4.0 cmd':<14s} {'24B cmd/s':<18s} {'93.8M/s':<16s}")
    print(f"  {'C':<14s} {'Accelerator 内存延迟4':<30s} {'1.0 cmd':<14s} {'6B cmd/s':<18s} {'23.4M/s':<16s}")

    # ========================================
    # 4. 加速器卸载深度
    # ========================================
    print()
    print("─" * 80)
    print("  [4] 加速器冷路径卸载深度")
    print()

    print(f"  加速器作为 GC 芯片 FIFO 饱和时的溢出卸载：")
    print(f"  - GC 引擎 FIFO 深度 16, 每引擎 1 cmd/cyc")
    print(f"  - 加速器 4 引擎, 并行处理溢出命令")
    print()

    for ne in [1, 2, 4, 8]:
        gc_tput = ne * G * 1e9
        acc_cap_count = 4.0 * G * 1e9
        acc_cap_mem = 1.0 * G * 1e9
        print(f"    ne={ne}:  GC={gc_tput/1e9:.0f}B/s  "
              f"Accel(计数)={acc_cap_count/1e9:.0f}B/s  "
              f"溢出比={acc_cap_count/gc_tput:.1f}×  "
              f"Accel(内存)={acc_cap_mem/1e9:.0f}B/s  "
              f"溢出比={acc_cap_mem/gc_tput:.1f}×")

    # ========================================
    # 5. 事件注入现实约束
    # ========================================
    print()
    print("─" * 80)
    print("  [5] 事件注入现实约束")
    print()

    # 参考 QPS 压力测试: 5M QPS = 0.0045 evt/cyc @ 1GHz
    qps_1g = 5_000_000  # 5M QPS @ 1GHz
    evt_per_req = 88
    qps_6g = int(qps_1g * 6)  # 5M → 30M QPS @ 6GHz
    evt_rate = qps_6g * evt_per_req / (G * 1e9)
    print(f"  参考: 5M QPS @1GHz 压力测试 ({evt_per_req} evt/req)")
    print(f"  等比例到 6GHz: {qps_6g/1e6:.0f}M QPS")
    print(f"  事件速率: {qps_6g * evt_per_req / 1e9:.0f}B evt/s = {evt_rate:.4f} evt/cyc")
    print(f"  管道容量: 1.0 evt/cyc → 利用率 {evt_rate/1.0*100:.2f}%")
    print()

    # 计算最大 QPS
    for cap in [1.0, 3.0]:
        max_evt = cap * G * 1e9
        max_qps = max_evt / evt_per_req
        print(f"  {'Separated' if cap > 1.5 else 'Standard'} 管道 ({cap:.0f} evt/cyc): "
              f"最大 {max_qps/1e6:.0f}M QPS  (事件瓶颈)")

    # ========================================
    # 6. 汇总
    # ========================================
    print()
    print("═" * 80)
    print("  [6] 最终汇总")
    print()

    print(f"  {'组件':<34s} {'原始':<14s} {'@6GHz 总':<22s} {'每核':<16s}")
    print(f"  {'─'*34} {'─'*14} {'─'*22} {'─'*16}")

    # Path B: 事件管道
    for cap, name in [(1.0, "Gateway 标准"), (3.0, "Gateway Separated")]:
        total_evt = cap * G * 1e9
        print(f"  {name:<34s} {cap:.0f} evt/cyc  {total_evt/1e9:.0f}B evt/s  "
              f"{total_evt/NC/1e6:.1f}M/s")

    # Path A: GC
    for ne in [1, 2, 4, 8]:
        et = ne * 1.0
        total_s = et * G * 1e9
        pc = total_s / NC
        tag = " ← 当前最瓶颈" if ne == 1 else ""
        tag2 = " ← 超越事件管道" if pc > 3.0 * G * 1e9 / NC and ne > 4 else ""
        print(f"  GCMultiEngine ne={ne:<2}                    "
              f"{et:.0f} cmd/cyc  {total_s/1e9:.0f}B cmd/s  "
              f"{pc/1e6:.1f}M/s{tag}{tag2}")

    # Path C: 加速器
    for mode, et in [("Accelerator 计数", 4.0), ("Accelerator 内存", 1.0)]:
        total_s = et * G * 1e9
        print(f"  {mode:<34s} {et:.1f} cmd/cyc  {total_s/1e9:.0f}B cmd/s  "
              f"{total_s/NC/1e6:.1f}M/s")

    # GCSubsystem 插槽
    print(f"  GCSubsystem 插槽                    16/核        4096 总            16 并发")

    print()
    print(f"  ─────────────────────────────────────────────────────")

    # 系统天花板
    print(f"  系统天花板:")
    print(f"    Path A (GC 指令): ne=1 → 6B cmd/s, ne=4 → 24B cmd/s")
    print(f"    Path B (网关事件): 标准 6B evt/s, Separated 18B evt/s")
    print(f"    Path C (加速器): 计数 24B cmd/s, 内存 6B cmd/s")
    print()
    print(f"  结论:")
    print(f"    1. 单引擎 GC CoProc (ne=1) 是 GC 指令路径瓶颈: 6B cmd/s")
    print(f"       → 每线程 {6e9/NT/1e6:.1f}M cmd/s, 占核周期 {1/NC*100:.4f}%")
    print(f"    2. 增引擎线性提升: ne=2 → 12B, ne=4 → 24B, ne=8 → 48B")
    print(f"    3. 事件管道与 GC 路径独立，标准管道 6B evt/s 不受 GC 影响")
    print(f"    4. 加速器冷路径卸载容量充足:")
    print(f"       - 计数模式 24B cmd/s > 任何单引擎 GC (6-48B)")
    print(f"       - 内存延迟4 模式 6B cmd/s >= ne=1, 建议配合 ne≥2")
    print(f"    5. ne=8 时 GC 吞吐 (48B cmd/s) 超过 Separated 事件管道 (18B evt/s)")
    print(f"       → 事件管道成为第二瓶颈（如果两路径共享带宽）")
    print(f"    6. SMT-2 每核 2 线程共享单个 GC 提交端口,")
    print(f"       实际 GC 指令率 ≤ 1/cyc/核, 系统上限 = 256 cmd/cyc")
    print(f"       当前 ne=1 利用率 0.39% 核周期, 远未达 CPU 上限")
    print()

    print("  Raw RTL measurement data (CYCLES={}):".format(CYCLES_PER_RUN))
    for nc in sorted(measured_orig.keys()):
        o = measured_orig[nc]
        print(f"    orig ncores={nc:2d}:  rsp={o['response_rate']:.4f}/cyc  [{o['elapsed']:.1f}s]")
    for (nc, ne) in sorted(measured_me.keys()):
        m = measured_me[(nc, ne)]
        print(f"    me   ne={ne} nc={nc:2d}:  rsp={m['response_rate']:.4f}/cyc  [{m['elapsed']:.1f}s]")

    print()
    print("=== Done ===")


if __name__ == "__main__":
    main()
