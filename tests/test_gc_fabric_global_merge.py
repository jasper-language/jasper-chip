# tests/test_gc_fabric_global_merge.py
# Ordered global merge via subprocess.
import subprocess, sys, re

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
    "ordered_by_domain": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import OrderedGlobalMerge
m = OrderedGlobalMerge(domain_count=4, tile_count=2)
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
    "cross_domain": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import OrderedGlobalMerge
m = OrderedGlobalMerge(domain_count=4, tile_count=2)
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
    "backpressure_no_loss": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import OrderedGlobalMerge
m = OrderedGlobalMerge(domain_count=2, tile_count=1, queue_depth=4)
sim = Simulator(m); sim.add_clock(1e-6)
async def proc(ctx):
    await ctx.tick()
    ctx.set(m.out_ready, 0)
    for t in (1, 2, 3):
        ctx.set(m.in_valid[0][0], 1); ctx.set(m.in_tag[0][0], t)
        ctx.set(m.in_domain[0][0], 0)
        await ctx.tick(); ctx.set(m.in_valid[0][0], 0)
    tags = []
    for _ in range(10):
        if ctx.get(m.out_valid):
            tags.append(ctx.get(m.out_tag))
            if len(tags) >= 3: break
        ctx.set(m.out_ready, 1)
        await ctx.tick()
    print("PASS" if tags == [1, 2, 3] else f"tags={tags}")
sim.add_testbench(proc); sim.run()
""",
    # P0: Strict correctness
    "tag_set_equality": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import OrderedGlobalMerge
m = OrderedGlobalMerge(domain_count=4, tile_count=2, queue_depth=8)
sim = Simulator(m); sim.add_clock(1e-6)
async def proc(ctx):
    await ctx.tick()
    ctx.set(m.out_ready, 0)
    for d in range(4):
        for i in range(5):
            tag = d * 5 + i + 1
            ctx.set(m.in_valid[0][0], 1); ctx.set(m.in_tag[0][0], tag)
            ctx.set(m.in_domain[0][0], d)
            await ctx.tick(); ctx.set(m.in_valid[0][0], 0)
    ctx.set(m.out_ready, 1)
    drained = []
    for _ in range(50):
        if ctx.get(m.out_valid):
            drained.append(ctx.get(m.out_tag))
            if len(drained) >= 20: break
        await ctx.tick()
    ok = len(drained) == 20 and sorted(drained) == list(range(1, 21))
    print("PASS" if ok else f"len={len(drained)} drained={drained}")
sim.add_testbench(proc); sim.run()
""",
    "fifo_full_backpressure_stress": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import OrderedGlobalMerge
m = OrderedGlobalMerge(domain_count=2, tile_count=1, queue_depth=2)
sim = Simulator(m); sim.add_clock(1e-6)
async def proc(ctx):
    await ctx.tick()
    ctx.set(m.out_ready, 0)
    drained = []
    for tag in range(1, 9):
        ctx.set(m.in_valid[0][0], 1); ctx.set(m.in_tag[0][0], tag)
        ctx.set(m.in_domain[0][0], 0)
        while not ctx.get(m.in_ready[0][0]):
            if ctx.get(m.out_valid):
                drained.append(ctx.get(m.out_tag))
            ctx.set(m.out_ready, 1)
            ctx.set(m.in_valid[0][0], 0)
            await ctx.tick()
            ctx.set(m.out_ready, 0)
            ctx.set(m.in_valid[0][0], 1); ctx.set(m.in_tag[0][0], tag)
            ctx.set(m.in_domain[0][0], 0)
        await ctx.tick(); ctx.set(m.in_valid[0][0], 0)
    ctx.set(m.out_ready, 1)
    for _ in range(50):
        if ctx.get(m.out_valid):
            drained.append(ctx.get(m.out_tag))
            if len(drained) >= 8: break
        await ctx.tick()
    ok = len(drained) == 8 and drained == list(range(1, 9))
    print("PASS" if ok else f"drained={drained}")
sim.add_testbench(proc); sim.run()
""",
    "multi_tile_multi_domain_concurrent": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import OrderedGlobalMerge
m = OrderedGlobalMerge(domain_count=4, tile_count=2)
sim = Simulator(m); sim.add_clock(1e-6)
async def proc(ctx):
    await ctx.tick()
    ctx.set(m.out_ready, 0)
    for i in range(5):
        ctx.set(m.in_valid[0][0], 1); ctx.set(m.in_tag[0][0], 10 + i)
        ctx.set(m.in_domain[0][0], 0)
        ctx.set(m.in_valid[1][0], 1); ctx.set(m.in_tag[1][0], 20 + i)
        ctx.set(m.in_domain[1][0], 1)
        await ctx.tick(); ctx.set(m.in_valid[0][0], 0); ctx.set(m.in_valid[1][0], 0)
    ctx.set(m.out_ready, 1)
    drained = []
    for _ in range(50):
        if ctx.get(m.out_valid):
            drained.append((ctx.get(m.out_tag), ctx.get(m.out_domain)))
            if len(drained) >= 10: break
        await ctx.tick()
    domains = set(d for _, d in drained)
    ok = len(domains) == 2 and len(drained) == 10
    print("PASS" if ok else f"domains={domains} len={len(drained)}")
sim.add_testbench(proc); sim.run()
""",
    "epoch_ordering": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import OrderedGlobalMerge
m = OrderedGlobalMerge(domain_count=2, tile_count=1)
sim = Simulator(m); sim.add_clock(1e-6)
async def proc(ctx):
    await ctx.tick()
    ctx.set(m.out_ready, 0)
    for tag in (1, 2, 3):
        ctx.set(m.in_valid[0][0], 1); ctx.set(m.in_tag[0][0], tag)
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
    "q_cnt_push_pop_same_cycle": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import OrderedGlobalMerge
m = OrderedGlobalMerge(domain_count=1, tile_count=1, queue_depth=4)
sim = Simulator(m); sim.add_clock(1e-6)
async def proc(ctx):
    await ctx.tick()
    tags = []
    for i in range(1, 5):
        if ctx.get(m.out_valid):
            tags.append(ctx.get(m.out_tag))
        ctx.set(m.in_valid[0][0], 1); ctx.set(m.in_tag[0][0], i)
        ctx.set(m.in_domain[0][0], 0); ctx.set(m.out_ready, 1)
        await ctx.tick(); ctx.set(m.in_valid[0][0], 0)
    for _ in range(8):
        if ctx.get(m.out_valid):
            tags.append(ctx.get(m.out_tag))
        await ctx.tick()
    ok = tags == [1,2,3,4]
    print("PASS" if ok else f"tags={tags}")
sim.add_testbench(proc); sim.run()
""",
    "q_empty_correctness": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import OrderedGlobalMerge
m = OrderedGlobalMerge(domain_count=1, tile_count=1)
sim = Simulator(m); sim.add_clock(1e-6)
async def proc(ctx):
    await ctx.tick()
    assert ctx.get(m.out_valid) == 0, "empty start"
    ctx.set(m.in_valid[0][0], 1); ctx.set(m.in_tag[0][0], 1)
    ctx.set(m.in_domain[0][0], 0); ctx.set(m.out_ready, 0)
    await ctx.tick(); ctx.set(m.in_valid[0][0], 0)
    assert ctx.get(m.out_valid) == 1, "valid after push"
    ctx.set(m.out_ready, 1)
    await ctx.tick()
    assert ctx.get(m.out_valid) == 0, "empty after drain"
    print("PASS")
sim.add_testbench(proc); sim.run()
""",
    "busy_correctness": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import OrderedGlobalMerge
m = OrderedGlobalMerge(domain_count=1, tile_count=1)
sim = Simulator(m); sim.add_clock(1e-6)
async def proc(ctx):
    await ctx.tick()
    assert ctx.get(m.busy) == 0, "not busy at start"
    ctx.set(m.in_valid[0][0], 1); ctx.set(m.in_tag[0][0], 1)
    ctx.set(m.in_domain[0][0], 0); ctx.set(m.out_ready, 0)
    await ctx.tick(); ctx.set(m.in_valid[0][0], 0)
    assert ctx.get(m.busy) == 1, "busy after push"
    ctx.set(m.out_ready, 1)
    await ctx.tick()
    assert ctx.get(m.busy) == 0, "not busy after drain"
    print("PASS")
sim.add_testbench(proc); sim.run()
""",
    "multi_domain_push_pop_same_cycle": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import OrderedGlobalMerge
m = OrderedGlobalMerge(domain_count=2, tile_count=1)
sim = Simulator(m); sim.add_clock(1e-6)
async def proc(ctx):
    await ctx.tick()
    ctx.set(m.out_ready, 0)
    for d in range(2):
        ctx.set(m.in_valid[0][0], 1); ctx.set(m.in_tag[0][0], d*10+1)
        ctx.set(m.in_domain[0][0], d)
        await ctx.tick(); ctx.set(m.in_valid[0][0], 0)
    tags = []
    ctx.set(m.out_ready, 1)
    for i in range(2):
        if ctx.get(m.out_valid):
            tags.append((ctx.get(m.out_tag), ctx.get(m.out_domain)))
        ctx.set(m.in_valid[0][0], 1); ctx.set(m.in_tag[0][0], 100+i)
        ctx.set(m.in_domain[0][0], 0)
        await ctx.tick(); ctx.set(m.in_valid[0][0], 0)
    if ctx.get(m.out_valid):
        tags.append((ctx.get(m.out_tag), ctx.get(m.out_domain)))
        await ctx.tick()
    ok = len(tags) == 3
    print("PASS" if ok else f"tags={tags}")
sim.add_testbench(proc); sim.run()
""",
    "queue_depth_16": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import OrderedGlobalMerge
m = OrderedGlobalMerge(domain_count=1, tile_count=1, queue_depth=16)
sim = Simulator(m); sim.add_clock(1e-6)
async def proc(ctx):
    await ctx.tick()
    ctx.set(m.out_ready, 1)
    drained = []
    for i in range(1, 21):
        if ctx.get(m.out_valid):
            drained.append(ctx.get(m.out_tag))
        ctx.set(m.in_valid[0][0], 1); ctx.set(m.in_tag[0][0], i)
        ctx.set(m.in_domain[0][0], 0)
        await ctx.tick(); ctx.set(m.in_valid[0][0], 0)
    for _ in range(60):
        if ctx.get(m.out_valid):
            drained.append(ctx.get(m.out_tag))
            if len(drained) >= 20: break
        await ctx.tick()
    ok = len(drained) == 20 and sorted(drained) == list(range(1,21))
    print("PASS" if ok else f"drained={drained}")
sim.add_testbench(proc); sim.run()
""",
    "queue_depth_32": """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_fabric import OrderedGlobalMerge
m = OrderedGlobalMerge(domain_count=1, tile_count=1, queue_depth=32)
sim = Simulator(m); sim.add_clock(1e-6)
async def proc(ctx):
    await ctx.tick()
    ctx.set(m.out_ready, 1)
    drained = []
    for i in range(1, 41):
        if ctx.get(m.out_valid):
            drained.append(ctx.get(m.out_tag))
        ctx.set(m.in_valid[0][0], 1); ctx.set(m.in_tag[0][0], i)
        ctx.set(m.in_domain[0][0], 0)
        await ctx.tick(); ctx.set(m.in_valid[0][0], 0)
    for _ in range(120):
        if ctx.get(m.out_valid):
            drained.append(ctx.get(m.out_tag))
            if len(drained) >= 40: break
        await ctx.tick()
    ok = len(drained) == 40 and sorted(drained) == list(range(1,41))
    print("PASS" if ok else f"drained={drained}")
sim.add_testbench(proc); sim.run()
""",
}
if __name__ == "__main__":
    passed = 0
    for n in ["ordered_by_domain", "cross_domain", "backpressure_no_loss",
              "tag_set_equality", "fifo_full_backpressure_stress",
              "multi_tile_multi_domain_concurrent", "epoch_ordering",
              "q_cnt_push_pop_same_cycle", "q_empty_correctness",
              "busy_correctness", "multi_domain_push_pop_same_cycle",
              "queue_depth_16", "queue_depth_32"]:
        if _run(n, TESTS[n]): passed += 1
    print(f"\nResults: {passed}/{len(TESTS)} passed")
    if passed != len(TESTS): exit(1)
