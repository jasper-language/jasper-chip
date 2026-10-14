# tests/test_gc_pipelined_combined.py
# Combined throughput analysis: pipelined GCSweepCoProc + multi-backend + accelerator.
from amaranth import *
from amaranth.sim import Simulator
from rtl.gc_sweep_coproc_pipelined import GCSweepCoProcPipelined
from rtl.gc_multi_backend_cluster import GCMultiBackendCluster
from rtl.jasper_gc_accelerator_ip import JasperGCAcceleratorIP
from rtl.jasper_gc_accelerator_config import JasperGCAcceleratorConfig, AcceleratorProfile
from rtl.isa import GC_NEW

# ── Pipelined GCSweepCoProc ──────────────────────────────────────
def run_pipelined_gc(cycles=200):
    """Measure pipelined GCSweepCoProc sustained throughput (burst mode)."""
    dut = GCSweepCoProcPipelined(ncores=1, fifo_depth=8, rsp_fifo_depth=8)
    sim = Simulator(dut); sim.add_clock(1e-6)
    result = {}
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.rsp_take[0], 1)
        ctx.set(dut.mv_upd_ready[0], 1)
        await ctx.tick()
        accepted = 0; responses = 0
        for i in range(cycles):
            ctx.set(dut.cmd_op[0], GC_NEW)
            ctx.set(dut.cmd_rd[0], (i % 31) + 1)
            ctx.set(dut.cmd_rs1[0], ((i * 4 + 0x100) & 0xFF) or 1)
            ctx.set(dut.cmd_tag[0], i & 0xFF)
            ctx.set(dut.cmd_enq_valid[0], 1)
            rv = ctx.get(dut.rsp_valid[0])
            if rv:
                responses += 1
                ctx.set(dut.rsp_take[0], 1)
            await ctx.tick()
            if ctx.get(dut.cmd_enq_ready[0]): accepted += 1
            ctx.set(dut.cmd_enq_valid[0], 0)
        ctx.set(dut.cmd_enq_valid[0], 0)
        for _ in range(cycles):
            rv = ctx.get(dut.rsp_valid[0])
            if rv:
                responses += 1
                ctx.set(dut.rsp_take[0], 1)
            await ctx.tick()
            if not rv:
                ctx.set(dut.rsp_take[0], 1)
        result["rate"] = accepted / cycles
        result["accepted"] = accepted
        result["responses"] = responses
    sim.add_testbench(proc); sim.run()
    return result

# ── Multi-backend interface ──────────────────────────────────────
MB_TYPES = [("1L×1", 1, 1), ("2L×1", 1, 2), ("1L×2", 2, 1), ("2L×2", 2, 2)]

def run_multi_backend(tile_count, lane_per_tile, cycles=400):
    """Measure multi-backend event acceptance rate."""
    dut = GCMultiBackendCluster(
        tile_count=tile_count, lane_per_tile=lane_per_tile,
        metadata_cache_size=256, metadata_ways=2)
    sim = Simulator(dut); sim.add_clock(1e-6)
    result = {}
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 0); ctx.set(dut.fill_ready, 1)
        total_lanes = tile_count * lane_per_tile
        for p in range(total_lanes):
            ctx.set(dut.out_ready, 1)
        # Warmup
        for _ in range(8):
            ctx.set(dut.in_valid, 1); ctx.set(dut.in_addr, 0x1000)
            ctx.set(dut.in_type, 0); ctx.set(dut.fill_ready, 1)
            await ctx.tick(); ctx.set(dut.in_valid, 0); await ctx.tick()
            for _ in range(4):
                ctx.set(dut.out_ready, 1); await ctx.tick()
        # Flush warmup responses
        for _ in range(16):
            ctx.set(dut.out_ready, 1); await ctx.tick()
            if not ctx.get(dut.busy): break
        # Stress: fire events as fast as accepted
        accepted = 0; outputs = 0
        addrs = [0x1000 + (i * 0x40) for i in range(32)]
        for i in range(cycles):
            a = addrs[i % len(addrs)]
            ctx.set(dut.in_valid, 1); ctx.set(dut.in_addr, a)
            ctx.set(dut.in_type, i % 3); ctx.set(dut.in_tag, i & 0xFF)
            ctx.set(dut.in_epoch, 0)
            ctx.set(dut.out_ready, 1); ctx.set(dut.fill_ready, 1)
            await ctx.tick()
            if ctx.get(dut.in_ready): accepted += 1
            if ctx.get(dut.out_valid): outputs += 1
        ctx.set(dut.in_valid, 0)
        for _ in range(32):
            ctx.set(dut.out_ready, 1); await ctx.tick()
            if ctx.get(dut.out_valid): outputs += 1
            if not ctx.get(dut.busy) and not ctx.get(dut.out_valid): break
        result["rate"] = accepted / cycles
        result["accepted"] = accepted
        result["outputs"] = outputs
    sim.add_testbench(proc); sim.run()
    return result

# ── Accelerator interface ─────────────────────────────────────────
def run_accelerator(config, enable_memory, mem_lat, cycles=400):
    """Measure accelerator command acceptance rate."""
    dut = JasperGCAcceleratorIP(
        config=config, enable_memory=enable_memory,
        mem_read_latency=mem_lat, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    result = {}
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        await ctx.tick()
        sent = 0; completed = 0
        bases = [0x00000000, 0x10000000, 0x20000000, 0x30000000]
        for i in range(cycles):
            typ = i % 4
            ctx.set(dut.iface.cmd_type, typ)
            ctx.set(dut.iface.cmd_correlation_id, i)
            ctx.set(dut.iface.cmd_epoch, 1)
            ctx.set(dut.iface.cmd_region_base, bases[typ])
            ctx.set(dut.iface.cmd_region_size, 64)
            ctx.set(dut.iface.cmd_valid, 1)
            await ctx.tick()
            if ctx.get(dut.iface.cmd_ready):
                sent += 1
            ctx.set(dut.iface.cmd_valid, 0)
            if ctx.get(dut.iface.comp_valid):
                ctx.set(dut.iface.comp_ready, 1)
                completed += 1
                await ctx.tick()
                ctx.set(dut.iface.comp_ready, 1)
            else:
                ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.cmd_valid, 0)
        for _ in range(cycles):
            ctx.set(dut.iface.comp_ready, 1); await ctx.tick()
            if ctx.get(dut.iface.comp_valid):
                completed += 1
        rate = sent / cycles if cycles else 0
        result["send_rate"] = rate
        result["comp_rate"] = completed / cycles if cycles else 0
        result["sent"] = sent
        result["completed"] = completed
    sim.add_testbench(proc); sim.run()
    return result


if __name__ == "__main__":
    ORIGINAL_GC_RATE = 0.3333  # from earlier benchmarks (lat=0)

    # ── Measure pipelined GC ──
    pipelined = run_pipelined_gc(cycles=200)
    PIPELINED_GC_RATE = pipelined["rate"]

    # ── Measure multi-backend (best case: 2L×2) ──
    mb_label, mb_tc, mb_lp = ("2L×2", 2, 2)
    mb_r = run_multi_backend(mb_tc, mb_lp)
    MB_RATE = mb_r["rate"]

    # ── Measure accelerator ──
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_STANDARD)
    acc_count = run_accelerator(cfg, enable_memory=False, mem_lat=0)
    ACC_COUNT_RATE = acc_count["send_rate"]
    acc_mem4 = run_accelerator(cfg, enable_memory=True, mem_lat=4)
    ACC_MEM4_RATE = acc_mem4["send_rate"]

    # ── Print table ──
    print("=== Full System Throughput Ceiling ===")
    print(f"{'Pathway':39s} {'Sustained cmd/evt/cyc':>22s}")
    print(f"{'─'*61}")
    print(f"{'Original GCSweepCoProc (lat=0)':39s} {ORIGINAL_GC_RATE:>22.4f}")
    print(f"{'Pipelined GCSweepCoProc':39s} {PIPELINED_GC_RATE:>22.4f}")
    print(f"{'Multi-backend ' + mb_label:39s} {MB_RATE:>22.4f}")
    print(f"{'Accelerator (counting, burst)':39s} {ACC_COUNT_RATE:>22.4f}")
    print(f"{'Accelerator (with memory lat=4)':39s} {ACC_MEM4_RATE:>22.4f}")
    print(f"{'─'*61}")
    print(f"{'Combinations:':39s}")
    print(f"{'  GC original + MB + Acc(counting)':39s} {ORIGINAL_GC_RATE + MB_RATE + ACC_COUNT_RATE:>22.4f}")
    print(f"{'  GC pipelined + MB + Acc(counting)':39s} {PIPELINED_GC_RATE + MB_RATE + ACC_COUNT_RATE:>22.4f}")
    print(f"{'  GC pipelined + MB + Acc(mem4)':39s} {PIPELINED_GC_RATE + MB_RATE + ACC_MEM4_RATE:>22.4f}")
    print(f"{'  GC pipelined alone':39s} {PIPELINED_GC_RATE:>22.4f}  (vs {ORIGINAL_GC_RATE:.4f} original)")
    print("=== Done ===")
