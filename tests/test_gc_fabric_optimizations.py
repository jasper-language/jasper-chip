# tests/test_gc_fabric_optimizations.py
# Fabric optimization tests via subprocess.
import subprocess, sys

def _run(name, code):
    r = subprocess.run([sys.executable, "-c", code],
                       capture_output=True, text=True, timeout=30)
    for line in r.stdout.strip().split("\n"):
        if line: print("  " + line)
    if "PASS" in r.stdout:
        print(f"  {name}: PASS")
        return True
    else:
        print(f"  {name}: FAIL ({r.stderr[:100]})")
        return False

TESTS = {
    "skid_buffer_basic": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import SkidBuffer
sb = SkidBuffer()
sim = Simulator(sb); sim.add_clock(1e-6)
async def proc(ctx):
    await ctx.tick()
    ctx.set(sb.in_valid, 1); ctx.set(sb.in_data, 42)
    ctx.set(sb.out_ready, 0)
    await ctx.tick()
    assert ctx.get(sb.in_ready) == 0, f"in_ready={ctx.get(sb.in_ready)} (skid)"
    ctx.set(sb.out_ready, 1)
    await ctx.tick()
    assert ctx.get(sb.out_valid) == 1
    assert ctx.get(sb.out_data) == 42
    print("PASS")
sim.add_testbench(proc); sim.run()
""",
    "skid_backpressure": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import SkidBuffer
sb = SkidBuffer()
sim = Simulator(sb); sim.add_clock(1e-6)
async def proc(ctx):
    await ctx.tick()
    ctx.set(sb.in_valid, 1); ctx.set(sb.in_data, 99)
    ctx.set(sb.out_ready, 1)
    await ctx.tick()
    assert ctx.get(sb.out_valid) == 1
    print("PASS")
sim.add_testbench(proc); sim.run()
""",
    "ordered_merge_basic": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import OrderedGlobalMerge
m = OrderedGlobalMerge(domain_count=2, tile_count=1, queue_depth=4)
sim = Simulator(m); sim.add_clock(1e-6)
async def proc(ctx):
    await ctx.tick()
    ctx.set(m.out_ready, 0)
    for s in (1, 2, 3):
        ctx.set(m.in_valid[0][0], 1); ctx.set(m.in_tag[0][0], s)
        ctx.set(m.in_domain[0][0], 0)
        await ctx.tick(); ctx.set(m.in_valid[0][0], 0)
    ctx.set(m.out_ready, 1)
    seqs = []
    for _ in range(10):
        if ctx.get(m.out_valid):
            seqs.append(ctx.get(m.out_tag))
            if len(seqs) >= 3: break
        await ctx.tick()
    print("PASS" if seqs == [1, 2, 3] else f"seqs={seqs}")
sim.add_testbench(proc); sim.run()
""",
    "ordered_merge_parallel": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import OrderedGlobalMerge
m = OrderedGlobalMerge(domain_count=2, tile_count=2)
sim = Simulator(m); sim.add_clock(1e-6)
async def proc(ctx):
    await ctx.tick()
    ctx.set(m.out_ready, 1)
    ctx.set(m.in_valid[0][0], 1); ctx.set(m.in_tag[0][0], 10)
    ctx.set(m.in_domain[0][0], 0)
    ctx.set(m.in_valid[1][0], 1); ctx.set(m.in_tag[1][0], 20)
    ctx.set(m.in_domain[1][0], 1)
    await ctx.tick()
    ctx.set(m.in_valid[0][0], 0); ctx.set(m.in_valid[1][0], 0)
    domains = set()
    for _ in range(10):
        if ctx.get(m.out_valid):
            domains.add(ctx.get(m.out_domain))
        await ctx.tick()
    print("PASS" if len(domains) == 2 else f"domains={len(domains)}")
sim.add_testbench(proc); sim.run()
""",
    "idle_timeout2": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import IdleDetect
id = IdleDetect(timeout=2); sim = Simulator(id); sim.add_clock(1e-6)
async def proc(ctx):
    ctx.set(id.active, 1)  # pulse before first tick to reset cnt=0
    await ctx.tick()
    ctx.set(id.active, 1)
    await ctx.tick()
    ctx.set(id.active, 0)  # stop activity
    await ctx.tick()        # 1st idle cycle
    assert ctx.get(id.idle) == 0, "too early"
    await ctx.tick()        # 2nd idle cycle (timeout=2)
    assert ctx.get(id.idle) == 1, f"idle={ctx.get(id.idle)}"
    print("PASS")
sim.add_testbench(proc); sim.run()
""",
    # P0: Skid metadata preservation
    "skid_metadata_preservation": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import SkidBuffer
sb = SkidBuffer()
sim = Simulator(sb); sim.add_clock(1e-6)
async def proc(ctx):
    await ctx.tick()
    ctx.set(sb.in_valid, 1); ctx.set(sb.in_data, 99)
    ctx.set(sb.in_tag, 99); ctx.set(sb.in_epoch, 7)
    ctx.set(sb.in_seq, 42); ctx.set(sb.in_domain, 2)
    ctx.set(sb.out_ready, 0)
    await ctx.tick()
    assert ctx.get(sb.in_ready) == 0, "skid full"
    ctx.set(sb.out_ready, 1)
    await ctx.tick()
    assert ctx.get(sb.out_valid) == 1, "out_valid"
    assert ctx.get(sb.out_tag) == 99, f"tag={ctx.get(sb.out_tag)}"
    assert ctx.get(sb.out_epoch) == 7, f"epoch={ctx.get(sb.out_epoch)}"
    assert ctx.get(sb.out_seq) == 42, f"seq={ctx.get(sb.out_seq)}"
    assert ctx.get(sb.out_domain) == 2, f"domain={ctx.get(sb.out_domain)}"
    print("PASS")
sim.add_testbench(proc); sim.run()
""",
    "skid_back_to_back": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import SkidBuffer
sb = SkidBuffer()
sim = Simulator(sb); sim.add_clock(1e-6)
async def proc(ctx):
    await ctx.tick()
    ctx.set(sb.out_ready, 1)
    seen = []
    for tag in range(1, 11):
        ctx.set(sb.in_valid, 1); ctx.set(sb.in_tag, tag)
        if ctx.get(sb.out_valid):
            seen.append(ctx.get(sb.out_tag))
        await ctx.tick()
        ctx.set(sb.in_valid, 0)
    for _ in range(10):
        if ctx.get(sb.out_valid):
            seen.append(ctx.get(sb.out_tag))
        await ctx.tick()
    print("PASS" if len(seen) == 10 else f"seen={seen}")
sim.add_testbench(proc); sim.run()
""",
    # P3: Power tests
    "clockgate_hold": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import ClockGate
cg = ClockGate(); sim = Simulator(cg); sim.add_clock(1e-6)
async def proc(ctx):
    await ctx.tick()
    ctx.set(cg.enable, 0); ctx.set(cg.data_in, 42)
    await ctx.tick()
    assert ctx.get(cg.data_out) == 0, f"held=0: {ctx.get(cg.data_out)}"
    ctx.set(cg.data_in, 99)
    await ctx.tick()
    assert ctx.get(cg.data_out) == 0, f"held=0 (still): {ctx.get(cg.data_out)}"
    print("PASS")
sim.add_testbench(proc); sim.run()
""",
    "clockgate_passthrough": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import ClockGate
cg = ClockGate(); sim = Simulator(cg); sim.add_clock(1e-6)
async def proc(ctx):
    await ctx.tick()
    ctx.set(cg.enable, 1); ctx.set(cg.data_in, 42)
    await ctx.tick()
    assert ctx.get(cg.data_out) == 42, f"pass: {ctx.get(cg.data_out)}"
    ctx.set(cg.data_in, 99)
    await ctx.tick()
    assert ctx.get(cg.data_out) == 99, f"pass2: {ctx.get(cg.data_out)}"
    print("PASS")
sim.add_testbench(proc); sim.run()
""",
    "idle_to_gate_enable": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import IdleDetect, FabricCoordinator
m = Module()
m.submodules.id = IdleDetect(timeout=2)
m.submodules.fc = FabricCoordinator(tile_count=1)
id = m.submodules.id; fc = m.submodules.fc
m.d.comb += fc.tile_idle[0].eq(id.idle)
sim = Simulator(m); sim.add_clock(1e-6)
async def proc(ctx):
    await ctx.tick()
    ctx.set(id.active, 1); ctx.set(fc.tile_active[0], 1)
    await ctx.tick(); ctx.set(id.active, 0)
    await ctx.tick(); await ctx.tick()
    assert ctx.get(fc.clock_enable[0]) == 1, f"active clk={ctx.get(fc.clock_enable[0])}"
    ctx.set(fc.tile_active[0], 0)
    await ctx.tick(); await ctx.tick()
    clk = ctx.get(fc.clock_enable[0])
    print("PASS" if clk == 0 else f"idle clk={clk}")
sim.add_testbench(proc); sim.run()
""",
    "load_rising_falling": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import LoadBasedEnable
lbe = LoadBasedEnable(tile_count=1, window=8, threshold=4)
sim = Simulator(lbe); sim.add_clock(1e-6)
async def proc(ctx):
    ctx.set(lbe.tile_ready[0], 1)
    await ctx.tick()
    assert ctx.get(lbe.tile_load[0]) == 0, f"init load={ctx.get(lbe.tile_load[0])}"
    assert ctx.get(lbe.tile_active[0]) == 1, "init active"
    ctx.set(lbe.tile_ready[0], 0)
    for i in range(1, 6):
        await ctx.tick()
    assert ctx.get(lbe.tile_load[0]) >= 4, f"rise load={ctx.get(lbe.tile_load[0])}"
    assert ctx.get(lbe.tile_active[0]) == 0, f"rise active={ctx.get(lbe.tile_active[0])}"
    ctx.set(lbe.tile_ready[0], 1)
    for i in range(1, 8):
        await ctx.tick()
    assert ctx.get(lbe.tile_load[0]) < 4, f"fall load={ctx.get(lbe.tile_load[0])}"
    assert ctx.get(lbe.tile_active[0]) == 1, f"fall active={ctx.get(lbe.tile_active[0])}"
    print("PASS")
sim.add_testbench(proc); sim.run()
""",
    "load_threshold_hysteresis": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import LoadBasedEnable
lbe = LoadBasedEnable(tile_count=1, window=8, threshold=3)
sim = Simulator(lbe); sim.add_clock(1e-6)
async def proc(ctx):
    ctx.set(lbe.tile_ready[0], 1)
    await ctx.tick()
    ctx.set(lbe.tile_ready[0], 0)
    await ctx.tick(); assert ctx.get(lbe.tile_active[0]) == 1, f"1:{ctx.get(lbe.tile_active[0])}"
    await ctx.tick(); assert ctx.get(lbe.tile_active[0]) == 1, f"2:{ctx.get(lbe.tile_active[0])}"
    await ctx.tick(); assert ctx.get(lbe.tile_active[0]) == 0, f"3:{ctx.get(lbe.tile_active[0])}"
    ctx.set(lbe.tile_ready[0], 1)
    await ctx.tick(); assert ctx.get(lbe.tile_active[0]) == 1, f"dec2:{ctx.get(lbe.tile_active[0])}"
    await ctx.tick(); assert ctx.get(lbe.tile_active[0]) == 1, f"dec1:{ctx.get(lbe.tile_active[0])}"
    print("PASS")
sim.add_testbench(proc); sim.run()
""",
    "load_external_qdepth": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import LoadBasedEnable
lbe = LoadBasedEnable(tile_count=1, window=8, threshold=4)
sim = Simulator(lbe); sim.add_clock(1e-6)
async def proc(ctx):
    await ctx.tick()
    ctx.set(lbe.use_external_load, 1)
    ctx.set(lbe.tile_queue_depth[0], 0); await ctx.tick()
    assert ctx.get(lbe.tile_load[0]) == 0, f"ext 0 -> load={ctx.get(lbe.tile_load[0])}"
    assert ctx.get(lbe.tile_active[0]) == 1, "ext 0 -> active"
    ctx.set(lbe.tile_queue_depth[0], 5); await ctx.tick()
    assert ctx.get(lbe.tile_load[0]) == 5, f"ext 5 -> load={ctx.get(lbe.tile_load[0])}"
    assert ctx.get(lbe.tile_active[0]) == 0, f"ext 5 -> active={ctx.get(lbe.tile_active[0])}"
    print("PASS")
sim.add_testbench(proc); sim.run()
""",
    "load_based_enable": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import LoadBasedEnable
lbe = LoadBasedEnable(tile_count=2, window=4, threshold=2)
sim = Simulator(lbe); sim.add_clock(1e-6)
async def proc(ctx):
    ctx.set(lbe.tile_ready[0], 1)
    await ctx.tick()
    assert ctx.get(lbe.tile_active[0]) == 1, "init active"
    ctx.set(lbe.tile_ready[0], 0)  # backpressure: load increases
    await ctx.tick()
    assert ctx.get(lbe.tile_active[0]) == 1, "cnt=1 < thr=2"
    await ctx.tick()
    assert ctx.get(lbe.tile_active[0]) == 0, "cnt=2 >= thr=2 -> inactive"
    ctx.set(lbe.tile_ready[0], 1)  # no backpressure: load decreases
    await ctx.tick()
    assert ctx.get(lbe.tile_active[0]) == 1, "cnt=1 < thr=2 -> active"
    print("PASS")
sim.add_testbench(proc); sim.run()
""",
    "idle_timeout4": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import IdleDetect
id = IdleDetect(timeout=4); sim = Simulator(id); sim.add_clock(1e-6)
async def proc(ctx):
    ctx.set(id.active, 1)
    await ctx.tick()
    ctx.set(id.active, 0)
    await ctx.tick(); assert ctx.get(id.idle) == 0, "t1"
    await ctx.tick(); assert ctx.get(id.idle) == 0, "t2"
    await ctx.tick(); assert ctx.get(id.idle) == 0, "t3"
    await ctx.tick(); assert ctx.get(id.idle) == 1, f"t4 idle={ctx.get(id.idle)}"
    print("PASS")
sim.add_testbench(proc); sim.run()
""",
}
if __name__ == "__main__":
    passed = 0
    for n in TESTS:
        if _run(n, TESTS[n]): passed += 1
    print(f"\nResults: {passed}/{len(TESTS)} passed")
    if passed != len(TESTS): exit(1)
