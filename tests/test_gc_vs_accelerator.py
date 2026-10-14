# tests/test_gc_vs_accelerator.py
# Overflow analysis: GC chip saturated → accelerator as cold-path offload
from amaranth import *
from amaranth.sim import Simulator
from rtl.gc_chip_clean import GCCleanChipTop
from rtl.isa import GC_NEW
from rtl.jasper_gc_accelerator_config import JasperGCAcceleratorConfig, AcceleratorProfile
from rtl.jasper_gc_accelerator_ip import JasperGCAcceleratorIP


# ═══════════════════════════════════════════════════════════════════════
# Part 1: GC chip — what's its ceiling?
# ═══════════════════════════════════════════════════════════════════════

def test_gc_chip_ceiling():
    """GC chip max sustained throughput at various latencies."""
    print("  [GC chip] Max sustained throughput (serial, 1 engine):")
    for lat in [0, 2, 4, 8]:
        chip = GCCleanChipTop(ncores=1, engine_latency=lat)
        sim = Simulator(chip); sim.add_clock(1e-6)
        N = 50
        async def proc(ctx):
            total_cyc = 0
            for i in range(N):
                ctx.set(chip.cmd_op[0], GC_NEW)
                ctx.set(chip.cmd_rd[0], 1)
                ctx.set(chip.cmd_rs1[0], i)
                ctx.set(chip.cmd_rs2[0], 0)
                ctx.set(chip.cmd_tag[0], i)
                ctx.set(chip.cmd_enq_valid[0], 1)
                while not ctx.get(chip.cmd_enq_ready[0]):
                    await ctx.tick(); total_cyc += 1
                await ctx.tick(); total_cyc += 1
                ctx.set(chip.cmd_enq_valid[0], 0)
                while not ctx.get(chip.rsp_valid[0]):
                    await ctx.tick(); total_cyc += 1
                ctx.set(chip.rsp_take[0], 1)
                await ctx.tick(); total_cyc += 1
                ctx.set(chip.rsp_take[0], 0)
            print(f"    lat={lat}: {N}/{total_cyc} cyc  = {N/total_cyc:.4f} cmds/cyc  (cap={N/total_cyc:.4f})")
        sim.add_testbench(proc); sim.run()


# ═══════════════════════════════════════════════════════════════════════
# Part 2: Accelerator — what's its ceiling?
# ═══════════════════════════════════════════════════════════════════════

def test_acc_ceiling():
    """Accelerator: max throughput with all 4 engines + burst + multi-outstanding."""
    print("  [Accelerator] Burst throughput (4 engines, multi-outstanding):")
    for outp in [1, 2, 4, 8]:
        cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_STANDARD)
        cfg.max_outstanding_commands = outp
        cfg.command_queue_depth = 16
        cfg.completion_queue_depth = 16
        # Counting only (no memory) — pure pipeline throughput
        dut = JasperGCAcceleratorIP(cfg, enable_memory=False, burst_enable=True)
        sim = Simulator(dut); sim.add_clock(1e-6)
        N = 40
        async def proc(ctx):
            ctx.set(dut.iface.comp_ready, 1)
            ctx.set(dut.iface.current_epoch, 1)
            await ctx.tick()
            # Burst: fire commands back-to-back, track completions
            sent = 0; completed = 0; total_cyc = 0
            ctx.set(dut.iface.cmd_valid, 0)
            await ctx.tick()
            for i in range(N):
                typ = [0, 1, 2, 3][i % 4]
                base = [0x00000000, 0x10000000, 0x20000000, 0x30000000][typ]
                ctx.set(dut.iface.cmd_type, typ)
                ctx.set(dut.iface.cmd_correlation_id, i)
                ctx.set(dut.iface.cmd_epoch, 1)
                ctx.set(dut.iface.cmd_region_base, base)
                ctx.set(dut.iface.cmd_region_size, 64)
                ctx.set(dut.iface.cmd_valid, 1)
                await ctx.tick(); total_cyc += 1
                if ctx.get(dut.iface.comp_valid):
                    completed += 1
                sent += 1
                ctx.set(dut.iface.cmd_valid, 0)
            # Drain
            for _ in range(N * 4):
                await ctx.tick(); total_cyc += 1
                if ctx.get(dut.iface.comp_valid):
                    completed += 1
                if completed >= sent:
                    break
            print(f"    out={outp}: sent={sent} completed={completed} cyc={total_cyc}  = {sent/total_cyc:.4f} cmds/cyc")
        sim.add_testbench(proc); sim.run()


# ═══════════════════════════════════════════════════════════════════════
# Part 3: Overflow simulation — GC chip saturated, acc picks up
# ═══════════════════════════════════════════════════════════════════════

def test_overflow_breakdown():
    """At what CPU demand does the GC chip saturate? Can acc pick up the rest?"""
    print("  [Overflow analysis] CPU demand → GC chip max → acc picks up remainder:")

    # GC chip throughput at various latencies (from test_gc_chip_ceiling above)
    gc_capacity = {0: 0.3333, 2: 0.1667, 4: 0.1250, 8: 0.0833}

    # Accelerator throughput (4 engines, no memory, out=4)
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_STANDARD)
    cfg.max_outstanding_commands = 4
    cfg.command_queue_depth = 16
    cfg.completion_queue_depth = 16
    dut = JasperGCAcceleratorIP(cfg, enable_memory=False, burst_enable=True)
    sim_acc = Simulator(dut); sim_acc.add_clock(1e-6)
    acc_capacity = None
    async def acc_proc(ctx):
        nonlocal acc_capacity
        ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        await ctx.tick()
        N = 40
        sent = 0; total_cyc = 0
        for i in range(N):
            typ = i % 4
            base = [0x00000000, 0x10000000, 0x20000000, 0x30000000][typ]
            ctx.set(dut.iface.cmd_type, typ)
            ctx.set(dut.iface.cmd_correlation_id, i)
            ctx.set(dut.iface.cmd_epoch, 1)
            ctx.set(dut.iface.cmd_region_base, base)
            ctx.set(dut.iface.cmd_region_size, 64)
            ctx.set(dut.iface.cmd_valid, 1)
            await ctx.tick(); total_cyc += 1
            sent += 1
            ctx.set(dut.iface.cmd_valid, 0)
        for _ in range(N * 4):
            await ctx.tick(); total_cyc += 1
            if ctx.get(dut.iface.comp_valid):
                pass
        acc_capacity = sent / total_cyc if total_cyc else 0
    sim_acc.add_testbench(acc_proc); sim_acc.run()

    # Accelerator with memory latency=4
    cfg_mem = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_STANDARD)
    cfg_mem.max_outstanding_commands = 4
    cfg_mem.command_queue_depth = 16
    cfg_mem.completion_queue_depth = 16
    for mem_lat, label in [(0, "mem0"), (4, "mem4"), (8, "mem8")]:
        dut_m = JasperGCAcceleratorIP(cfg_mem, enable_memory=True, mem_read_latency=mem_lat, burst_enable=True)
        sim_m = Simulator(dut_m); sim_m.add_clock(1e-6)
        cap_m = [None]
        async def proc_m(ctx):
            ctx.set(dut_m.iface.comp_ready, 1)
            ctx.set(dut_m.iface.current_epoch, 1)
            await ctx.tick()
            N = 32
            sent = 0; total_cyc = 0
            for i in range(N):
                typ = i % 4
                base = [0x00000000, 0x10000000, 0x20000000, 0x30000000][typ]
                ctx.set(dut_m.iface.cmd_type, typ)
                ctx.set(dut_m.iface.cmd_correlation_id, i)
                ctx.set(dut_m.iface.cmd_epoch, 1)
                ctx.set(dut_m.iface.cmd_region_base, base)
                ctx.set(dut_m.iface.cmd_region_size, 64)
                ctx.set(dut_m.iface.cmd_valid, 1)
                await ctx.tick(); total_cyc += 1
                sent += 1
                ctx.set(dut_m.iface.cmd_valid, 0)
            for _ in range(N * 8):
                await ctx.tick(); total_cyc += 1
                if ctx.get(dut_m.iface.comp_valid):
                    pass
            cap_m[0] = sent / total_cyc if total_cyc else 0
        sim_m.add_testbench(proc_m); sim_m.run()

        for lat, gc_bw in gc_capacity.items():
            gc_max = gc_bw
            combined = gc_max + cap_m[0]
            headroom = combined / gc_max - 1 if gc_max > 0 else 0
            print(f"    lat={lat}: GC={gc_max:.4f} + Acc({label})={cap_m[0]:.4f} = {combined:.4f}  headroom={headroom:.0%}")


# ═══════════════════════════════════════════════════════════════════════
# Part 4: Can the combined system handle worst-case CPU demand?
# ═══════════════════════════════════════════════════════════════════════

def test_saturation_ramp():
    """Ramp CPU demand until combined system saturates."""
    print("  [Saturation ramp] Finding the breaking point:")

    gc_capacity = {0: 0.3333, 2: 0.1667, 4: 0.1250, 8: 0.0833}

    for mem_lat, mem_label in [(0, "mem0"), (4, "mem4")]:
        cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_STANDARD)
        cfg.max_outstanding_commands = 4
        cfg.command_queue_depth = 16
        cfg.completion_queue_depth = 16
        dut = JasperGCAcceleratorIP(cfg, enable_memory=True, mem_read_latency=mem_lat, burst_enable=True)
        sim = Simulator(dut); sim.add_clock(1e-6)
        acc_bw = [None]
        async def proc(ctx):
            ctx.set(dut.iface.comp_ready, 1)
            ctx.set(dut.iface.current_epoch, 1)
            await ctx.tick()
            N = 32; sent = 0; total = 0
            for i in range(N):
                typ = i % 4
                base = [0x00000000, 0x10000000, 0x20000000, 0x30000000][typ]
                ctx.set(dut.iface.cmd_type, typ)
                ctx.set(dut.iface.cmd_correlation_id, i)
                ctx.set(dut.iface.cmd_epoch, 1)
                ctx.set(dut.iface.cmd_region_base, base)
                ctx.set(dut.iface.cmd_region_size, 64)
                ctx.set(dut.iface.cmd_valid, 1)
                await ctx.tick(); total += 1; sent += 1
                ctx.set(dut.iface.cmd_valid, 0)
            for _ in range(N * 8):
                await ctx.tick(); total += 1
            acc_bw[0] = sent / total if total else 0
        sim.add_testbench(proc); sim.run()

        for gc_lat, gc_bw in gc_capacity.items():
            combined = gc_bw + acc_bw[0]
            print(f"    GC(lat={gc_lat})={gc_bw:.4f} + Acc({mem_label})={acc_bw[0]:.4f} = {combined:.4f}")
            print(f"      → CPU demand > {combined:.4f} cmd/cyc saturates both paths")
            if gc_lat == 0:
                cpu_max_nomem = gc_bw
            if gc_lat == 4:
                cpu_max_mem4 = gc_bw


if __name__ == "__main__":
    print("=" * 60)
    print("GC Chip + Accelerator — Overflow Capacity Analysis")
    print("=" * 60)
    print()
    test_gc_chip_ceiling()
    print()
    test_acc_ceiling()
    print()
    test_overflow_breakdown()
    print()
    test_saturation_ramp()
