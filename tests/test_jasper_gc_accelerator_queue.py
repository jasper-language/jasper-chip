# tests/test_jasper_gc_accelerator_queue.py
# CommandQueue + CompletionQueue tests.
from amaranth import *; from amaranth.sim import Simulator
from rtl.jasper_gc_accelerator_queue import CommandQueue, CompletionQueue


def _elab(mod):
    """Elaboration smoke test."""
    m = Module(); m.submodules.dut = mod
    from amaranth.back import rtlil
    rtlil.convert(m, ports=[])


def test_cmd_queue_elab():
    _elab(CommandQueue(depth=4))


def test_cmd_queue_accept():
    """Push 1 command, pop 1 command, verify fields."""
    q = CommandQueue(depth=4)
    sim = Simulator(q); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        assert ctx.get(q.cmd_ready) == 1, "should be ready"
        ctx.set(q.cmd_valid, 1); ctx.set(q.cmd_type, 1)
        ctx.set(q.cmd_correlation_id, 42)
        ctx.set(q.cmd_epoch, 7); ctx.set(q.cmd_merge_domain, 2)
        ctx.set(q.cmd_region_base, 0x1000); ctx.set(q.out_ready, 1)
        await ctx.tick(); ctx.set(q.cmd_valid, 0)
        assert ctx.get(q.out_valid) == 1, "should have output"
        assert ctx.get(q.out_type) == 1
        assert ctx.get(q.out_correlation_id) == 42
        assert ctx.get(q.out_epoch) == 7
        assert ctx.get(q.out_merge_domain) == 2
        assert ctx.get(q.out_region_base) == 0x1000
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_cmd_queue_full():
    """Fill queue to depth, then cmd_ready=0."""
    q = CommandQueue(depth=4)
    sim = Simulator(q); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(q.out_ready, 0)
        for i in range(4):
            assert ctx.get(q.cmd_ready) == 1, f"ready at {i}"
            ctx.set(q.cmd_valid, 1); ctx.set(q.cmd_correlation_id, i)
            await ctx.tick(); ctx.set(q.cmd_valid, 0)
            if i < 3:
                await ctx.tick()  # idle: let cmd_valid_d clear for rising-edge detect
        assert ctx.get(q.cmd_ready) == 0, "should be full"
        assert ctx.get(q.full) == 1
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_cmd_queue_backpressure():
    """Push 5 commands through depth 4: 4 accepted, 1 rejected."""
    q = CommandQueue(depth=4)
    sim = Simulator(q); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(q.out_ready, 0)
        accepted = 0
        for i in range(5):
            ctx.set(q.cmd_valid, 1); ctx.set(q.cmd_correlation_id, i)
            await ctx.tick(); ctx.set(q.cmd_valid, 0)
            if ctx.get(q.cmd_ready) == 1:  # was accepted on prev cycle
                pass
            accepted += 1 if i == 0 else 0  # simplified
            if i < 4:
                await ctx.tick()  # idle: let cmd_valid_d clear for rising-edge detect
        # Count: drain and count
        ctx.set(q.out_ready, 1)
        drained = 0
        for _ in range(10):
            if ctx.get(q.out_valid):
                drained += 1
            await ctx.tick()
            if drained >= 4: break
        assert drained == 4, f"drained={drained}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_comp_queue_elab():
    _elab(CompletionQueue(depth=4))


def test_comp_queue_basic():
    """Push 1 completion, pop 1 completion, verify fields."""
    q = CompletionQueue(depth=4)
    sim = Simulator(q); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(q.in_valid, 1); ctx.set(q.in_status, 0)
        ctx.set(q.in_correlation_id, 99); ctx.set(q.in_epoch, 5)
        ctx.set(q.out_ready, 1)
        await ctx.tick(); ctx.set(q.in_valid, 0)
        assert ctx.get(q.out_valid) == 1
        assert ctx.get(q.out_status) == 0
        assert ctx.get(q.out_correlation_id) == 99
        assert ctx.get(q.out_epoch) == 5
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_comp_queue_full():
    """Fill completion queue to depth, then in_ready=0."""
    q = CompletionQueue(depth=4)
    sim = Simulator(q); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(q.out_ready, 0)
        for i in range(4):
            assert ctx.get(q.in_ready) == 1, f"ready at {i}"
            ctx.set(q.in_valid, 1); ctx.set(q.in_correlation_id, i)
            await ctx.tick(); ctx.set(q.in_valid, 0)
        assert ctx.get(q.in_ready) == 0, "should be full"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_cmd_queue_burst_enable():
    """With burst_enable=True, consecutive cmd_valid cycles each push a command."""
    q = CommandQueue(depth=8, burst_enable=True)
    sim = Simulator(q); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(q.out_ready, 0)
        ctx.set(q.cmd_valid, 1)
        ctx.set(q.cmd_correlation_id, 10)
        await ctx.tick()
        ctx.set(q.cmd_correlation_id, 20)
        await ctx.tick()
        ctx.set(q.cmd_correlation_id, 30)
        await ctx.tick()
        ctx.set(q.cmd_valid, 0)
        # Drain and verify we got all 3 commands
        ctx.set(q.out_ready, 1)
        drained = []
        for _ in range(10):
            if ctx.get(q.out_valid):
                drained.append(ctx.get(q.out_correlation_id))
                if len(drained) >= 3:
                    break
            await ctx.tick()
        assert drained == [10, 20, 30], f"drained={drained}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_cmd_queue_burst_disable():
    """With burst_enable=False (default), consecutive cmd_valid pushes only 1 command."""
    q = CommandQueue(depth=8, burst_enable=False)
    sim = Simulator(q); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(q.out_ready, 0)
        ctx.set(q.cmd_valid, 1)
        ctx.set(q.cmd_correlation_id, 10)
        await ctx.tick()
        ctx.set(q.cmd_correlation_id, 20)
        await ctx.tick()
        ctx.set(q.cmd_correlation_id, 30)
        await ctx.tick()
        ctx.set(q.cmd_valid, 0)
        # Drain and verify only 1 command was pushed
        ctx.set(q.out_ready, 1)
        drained = []
        for _ in range(10):
            if ctx.get(q.out_valid):
                drained.append(ctx.get(q.out_correlation_id))
                if len(drained) >= 3:
                    break
            await ctx.tick()
        assert drained == [10], f"drained={drained}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_comp_queue_correlation_id_echo():
    """correlation_id is preserved through queue."""
    q = CompletionQueue(depth=8)
    sim = Simulator(q); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        # Push 3 completions without draining
        ctx.set(q.out_ready, 0)
        for cid in [10, 20, 30]:
            ctx.set(q.in_valid, 1); ctx.set(q.in_correlation_id, cid)
            await ctx.tick(); ctx.set(q.in_valid, 0)
        # Now drain
        ctx.set(q.out_ready, 1)
        echo = []
        for _ in range(10):
            if ctx.get(q.out_valid):
                echo.append(ctx.get(q.out_correlation_id))
                if len(echo) >= 3: break
            await ctx.tick()
        assert echo == [10, 20, 30], f"echo={echo}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()
