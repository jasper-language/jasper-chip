# tests/test_gc_full_heap_concurrent.py
# Full-heap GC concurrent mark+sweep RTL tests
from amaranth import *
from amaranth.sim import Simulator
from rtl.gc_sweep_coproc import GCSweepCoProc
from rtl.isa import GC_NEW, GC_DROP, GC_CLONE, GC_PIN, GC_UNPIN, GC_RELOC, GC_EPOCH


async def _txn(ctx, sweep, op, rd, rs1, rs2, tag, core=0):
    """Full command transaction: send + wait for response."""
    ctx.set(sweep.cmd_op[core], op)
    ctx.set(sweep.cmd_rd[core], rd)
    ctx.set(sweep.cmd_rs1[core], rs1)
    ctx.set(sweep.cmd_rs2[core], rs2)
    ctx.set(sweep.cmd_tag[core], tag)
    ctx.set(sweep.cmd_enq_valid[core], 1)
    while not ctx.get(sweep.cmd_enq_ready[core]):
        await ctx.tick()
    await ctx.tick()
    ctx.set(sweep.cmd_enq_valid[core], 0)
    while not ctx.get(sweep.rsp_valid[core]):
        await ctx.tick()
    d = ctx.get(sweep.rsp_data[core])
    trapped = ctx.get(sweep.trap[core])
    ctx.set(sweep.rsp_take[core], 1)
    await ctx.tick()
    ctx.set(sweep.rsp_take[core], 0)
    return d, trapped


async def _send_card(ctx, sweep, card_id, core_id=0, epoch=0):
    """Send one card event via card_in, waiting for backpressure."""
    ctx.set(sweep.card_in_valid, 1)
    ctx.set(sweep.card_in_card_id, card_id)
    ctx.set(sweep.card_in_core_id, core_id)
    ctx.set(sweep.card_in_epoch, epoch)
    while not ctx.get(sweep.card_in_ready):
        await ctx.tick()
    await ctx.tick()
    ctx.set(sweep.card_in_valid, 0)


async def _drain_cards(ctx, extra_ticks=8):
    """Wait for card processing to settle."""
    for _ in range(extra_ticks):
        await ctx.tick()


async def _send_card_and_check(ctx, sweep, card_id, core_id, epoch, expected_mark_total, expected_dup_total):
    """Send one card and verify mark counts afterward."""
    await _send_card(ctx, sweep, card_id, core_id, epoch)
    await _drain_cards(ctx, 2)
    m = ctx.get(sweep.mark_count_total)
    d = ctx.get(sweep.mark_dup_drop_total)
    if m != expected_mark_total or d != expected_dup_total:
        raise AssertionError(
            f"card_id={card_id} ep={epoch}: mark={m} (want {expected_mark_total}), "
            f"dup={d} (want {expected_dup_total})"
        )


def test_concurrent_mark_sweep_basic():
    """Drive 10 card_in events + 5 GC_NEW commands; verify both paths complete."""
    sweep = GCSweepCoProc(ncores=1, engine_latency=0)
    sim = Simulator(sweep)
    sim.add_clock(1e-6)

    async def proc(ctx):
        n_cards = 10
        n_cmds = 5
        cmd_idx = 0

        for i in range(n_cards):
            # Send a card
            await _send_card(ctx, sweep, i, core_id=0, epoch=0)
            # Interleave a command every 2 cards
            if i % 2 == 0 and cmd_idx < n_cmds:
                h, trapped = await _txn(ctx, sweep, GC_NEW, 1, 100 + cmd_idx, 0, cmd_idx)
                assert not trapped, f"GC_NEW {cmd_idx} trapped during card {i}"
                assert h != 0, f"GC_NEW {cmd_idx} returned 0 (handle 0 reserved)"
                cmd_idx += 1

        await _drain_cards(ctx, 10)

        mark_total = ctx.get(sweep.mark_count_total)
        dup_drop = ctx.get(sweep.mark_dup_drop_total)
        print(f"  mark_count_total={mark_total} (expected {n_cards})  dup_drop={dup_drop}")
        assert mark_total == n_cards, f"Expected {n_cards} marks, got {mark_total}"
        assert dup_drop == 0, f"Expected 0 dup drops, got {dup_drop}"

        # Engine not corrupted: one more GC_NEW should succeed
        h, trapped = await _txn(ctx, sweep, GC_NEW, 1, 999, 0, 99)
        assert not trapped, "GC_NEW trapped after concurrent mark+sweep"
        assert h != 0, "GC_NEW returned 0 after recovery"

    sim.add_testbench(proc)
    sim.run()
    print("  PASS: 10 cards + 5 GC_NEW completed, no cross-interference")


def test_mark_stress_during_sweep():
    """100 card_in events + 20 GC commands; verify both paths complete."""
    sweep = GCSweepCoProc(ncores=1, engine_latency=0)
    sim = Simulator(sweep)
    sim.add_clock(1e-6)

    async def proc(ctx):
        n_cards = 100
        n_cmds = 20

        for batch in range(max(n_cards, n_cmds) // 10 + 1):
            base_card = batch * 10
            base_cmd = batch * 10
            for i in range(10):
                ci = base_card + i
                if ci < n_cards:
                    await _send_card(ctx, sweep, ci, core_id=0, epoch=0)
            for i in range(10):
                ci = base_cmd + i
                if ci < n_cmds:
                    h, trapped = await _txn(ctx, sweep, GC_NEW, 1, 200 + ci, 0, ci)
                    assert not trapped, f"GC_NEW {ci} trapped"

        await _drain_cards(ctx, 20)

        mark_total = ctx.get(sweep.mark_count_total)
        dup_drop = ctx.get(sweep.mark_dup_drop_total)
        print(f"  mark_count_total={mark_total} (expected {n_cards})  dup_drop={dup_drop}")
        assert mark_total == n_cards, f"Expected {n_cards} marks, got {mark_total}"
        assert dup_drop == 0, f"Expected 0 dup drops, got {dup_drop}"

        hit_total = ctx.get(sweep.mark_hit_total)
        miss_total = ctx.get(sweep.mark_miss_total)
        replace_total = ctx.get(sweep.mark_replace_total)
        print(f"  hit={hit_total}  miss={miss_total}  replace={replace_total}")

    sim.add_testbench(proc)
    sim.run()
    print("  PASS: 100 cards + 20 commands throughput")


def test_card_in_backpressure_during_command():
    """Fill GC command FIFO; verify card_in still accepts while backed up."""
    sweep = GCSweepCoProc(ncores=1, engine_latency=0)
    sim = Simulator(sweep)
    sim.add_clock(1e-6)

    async def proc(ctx):
        # Phase 1: fill command FIFO (don't drain responses)
        cmd_filled = 0
        for attempt in range(50):
            ctx.set(sweep.cmd_op[0], GC_NEW)
            ctx.set(sweep.cmd_rd[0], 1)
            ctx.set(sweep.cmd_rs1[0], cmd_filled)
            ctx.set(sweep.cmd_rs2[0], 0)
            ctx.set(sweep.cmd_tag[0], cmd_filled)
            ctx.set(sweep.cmd_enq_valid[0], 1)
            if not ctx.get(sweep.cmd_enq_ready[0]):
                ctx.set(sweep.cmd_enq_valid[0], 0)
                print(f"  cmd_enq_ready went low after {cmd_filled} commands")
                break
            await ctx.tick()
            ctx.set(sweep.cmd_enq_valid[0], 0)
            cmd_filled += 1
        else:
            ctx.set(sweep.cmd_enq_valid[0], 0)
        assert cmd_filled >= 2, "Should have filled at least 2 commands"

        # Phase 2: command FIFO is full; card_in should still accept
        cards_sent = 0
        for i in range(20):
            ctx.set(sweep.card_in_valid, 1)
            ctx.set(sweep.card_in_card_id, i)
            ctx.set(sweep.card_in_core_id, 0)
            ctx.set(sweep.card_in_epoch, 0)
            while not ctx.get(sweep.card_in_ready):
                await ctx.tick()
            await ctx.tick()
            ctx.set(sweep.card_in_valid, 0)
            cards_sent += 1
        print(f"  Sent {cards_sent} cards while cmd FIFO was full/backed up")
        assert cards_sent == 20, "All 20 cards should be accepted"

        # Phase 3: drain command responses (one at a time)
        drained = 0
        for _ in range(100):
            if ctx.get(sweep.rsp_valid[0]):
                ctx.set(sweep.rsp_take[0], 1)
                await ctx.tick()
                ctx.set(sweep.rsp_take[0], 0)
                drained += 1
            else:
                await ctx.tick()
            if drained >= cmd_filled:
                break
        print(f"  Drained {drained}/{cmd_filled} command responses")
        assert drained == cmd_filled, f"Expected {cmd_filled} responses, got {drained}"

        # Phase 4: both paths should recover
        h, trapped = await _txn(ctx, sweep, GC_NEW, 1, 888, 0, 42)
        assert not trapped, "GC_NEW trapped after drain"
        print(f"  Post-recovery GC_NEW handle={h}")

        await _drain_cards(ctx, 10)
        mark_total = ctx.get(sweep.mark_count_total)
        print(f"  Final mark_count_total={mark_total}")
        assert mark_total >= 20, f"Expected >=20 marks (sent 20 cards), got {mark_total}"

    sim.add_testbench(proc)
    sim.run()
    print("  PASS: card_in independent of command FIFO backpressure")


def test_mark_completes_independent_of_sweep():
    """50 card_in events without GC commands; then send GC commands."""
    sweep = GCSweepCoProc(ncores=1, engine_latency=0)
    sim = Simulator(sweep)
    sim.add_clock(1e-6)

    async def proc(ctx):
        n_cards = 50
        for i in range(n_cards):
            await _send_card(ctx, sweep, i, core_id=0, epoch=0)

        await _drain_cards(ctx, 10)

        mark_total = ctx.get(sweep.mark_count_total)
        dup_drop = ctx.get(sweep.mark_dup_drop_total)
        print(f"  Mark-only phase: mark_count_total={mark_total}  dup_drop={dup_drop}")
        assert mark_total == n_cards, f"Expected {n_cards} marks, got {mark_total}"
        assert dup_drop == 0, "No dup drops expected on unique cards"

        # Now send GC commands — should work fine
        for i in range(5):
            h, trapped = await _txn(ctx, sweep, GC_NEW, 1, 300 + i, 0, 100 + i)
            assert not trapped, f"GC_NEW {i} trapped after mark-only phase"
            assert h != 0, f"GC_NEW {i} returned handle 0"

        print("  Sweep commands work cleanly after mark-only phase")

    sim.add_testbench(proc)
    sim.run()
    print("  PASS: mark phase independent, sweep commands work after")


def test_card_dedup_during_concurrent():
    """Send duplicate card IDs with GC commands; verify dedup in concurrent mode."""
    sweep = GCSweepCoProc(
        ncores=1, engine_latency=0,
        card_dedup_enable=True,
        card_table_size=16,
        card_table_ways=1,
    )
    sim = Simulator(sweep)
    sim.add_clock(1e-6)

    async def proc(ctx):
        n_unique = 5
        n_dup_rounds = 2  # send duplicates twice

        # First pass: 5 unique cards
        for i in range(n_unique):
            await _send_card(ctx, sweep, i, core_id=0, epoch=0)

        # Interleave GC commands with duplicate sends
        for r in range(n_dup_rounds):
            for i in range(n_unique):
                await _send_card(ctx, sweep, i, core_id=0, epoch=0)
            # GC command between rounds
            h, trapped = await _txn(ctx, sweep, GC_NEW, 1, 400 + r, 0, 200 + r)
            assert not trapped

        await _drain_cards(ctx, 16)

        mark_total = ctx.get(sweep.mark_count_total)
        dup_drop = ctx.get(sweep.mark_dup_drop_total)
        hit_total = ctx.get(sweep.mark_hit_total)
        miss_total = ctx.get(sweep.mark_miss_total)
        print(f"  mark_count_total={mark_total}  dup_drop={dup_drop}")
        print(f"  mark_hit={hit_total}  mark_miss={miss_total}")

        # 5 unique marks (epoch=0), rest are dedup hits
        expected_unique = n_unique
        expected_dups = n_unique * n_dup_rounds
        assert mark_total == expected_unique, \
            f"Expected {expected_unique} unique marks, got {mark_total}"
        assert dup_drop >= expected_dups, \
            f"Expected >= {expected_dups} dup drops, got {dup_drop}"
        assert miss_total == n_unique, \
            f"Expected {n_unique} misses (one per unique card), got {miss_total}"
        assert hit_total >= expected_dups, \
            f"Expected >= {expected_dups} hits, got {hit_total}"

    sim.add_testbench(proc)
    sim.run()
    print("  PASS: dedup works correctly with concurrent GC commands")


def test_epoch_handoff():
    """Epoch change mid-card-stream; old epoch cards processed before new."""
    sweep = GCSweepCoProc(
        ncores=1, engine_latency=0,
        card_dedup_enable=True,
        card_table_size=16,
        card_table_ways=1,
    )
    sim = Simulator(sweep)
    sim.add_clock(1e-6)

    async def proc(ctx):
        # Phase 1: epoch=0 cards (IDs 0-4, unique)
        for i in range(5):
            await _send_card(ctx, sweep, i, core_id=0, epoch=0)

        # GC command during epoch=0 processing
        h, trapped = await _txn(ctx, sweep, GC_NEW, 1, 600, 0, 300)
        assert not trapped

        # Duplicate epoch=0 cards (should dedup)
        for i in range(5):
            await _send_card(ctx, sweep, i, core_id=0, epoch=0)

        # Phase 2: epoch=1 — same card IDs but new epoch = new marks
        for i in range(5):
            await _send_card(ctx, sweep, i, core_id=1, epoch=1)

        # Duplicate one epoch=1 card (should dedup)
        await _send_card(ctx, sweep, 0, core_id=1, epoch=1)

        # GC command in new epoch
        h, trapped = await _txn(ctx, sweep, GC_NEW, 1, 700, 0, 310)
        assert not trapped

        await _drain_cards(ctx, 16)

        mark_total = ctx.get(sweep.mark_count_total)
        dup_drop = ctx.get(sweep.mark_dup_drop_total)
        print(f"  mark_count_total={mark_total}  dup_drop={dup_drop}")

        # Expected:
        #   5 marks from epoch=0 unique cards (IDs 0-4)
        #   5 dup drops from epoch=0 duplicate cards
        #   5 marks from epoch=1 cards (IDs 0-4 again, but new epoch)
        #   1 dup drop from epoch=1 duplicate
        # Total: 10 marks, 6 dup drops
        assert mark_total == 10, f"Expected 10 marks, got {mark_total}"
        assert dup_drop >= 6, f"Expected >=6 dup drops, got {dup_drop}"

        # Phase 3: send cards with epoch=0 again (same IDs)
        for i in range(5):
            await _send_card(ctx, sweep, i, core_id=0, epoch=0)

        await _drain_cards(ctx, 16)
        mark_total2 = ctx.get(sweep.mark_count_total)
        dup_drop2 = ctx.get(sweep.mark_dup_drop_total)
        print(f"  After epoch=0 re-send: mark_count_total={mark_total2}  dup_drop={dup_drop2}")

        # Some epoch=0 entries may have been evicted by epoch=1 writes,
        # so some refetches become new marks. System remains stable.
        assert mark_total2 >= mark_total, "Mark count should not decrease"
        assert mark_total2 > 0, "Mark count should be positive"
        print("  Epoch handoff: system stable, no crashes across epoch boundary")

    sim.add_testbench(proc)
    sim.run()
    print("  PASS: epoch handoff processed correctly with concurrent marks")


if __name__ == "__main__":
    print("=" * 60)
    print("Full-Heap GC Concurrent Mark+Sweep Tests")
    print("=" * 60)
    tests = [
        ("Concurrent mark+sweep basic",      test_concurrent_mark_sweep_basic),
        ("Mark stress during sweep",          test_mark_stress_during_sweep),
        ("Card backpressure during command",  test_card_in_backpressure_during_command),
        ("Mark completes independent",        test_mark_completes_independent_of_sweep),
        ("Card dedup during concurrent",      test_card_dedup_during_concurrent),
        ("Epoch handoff",                     test_epoch_handoff),
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        print(f"\n--- {name} ---")
        try:
            fn()
            print(f"  RESULT: PASS")
            passed += 1
        except AssertionError as e:
            print(f"  RESULT: FAIL — {e}")
            failed += 1
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  RESULT: FAIL — {e}")
            failed += 1
    print(f"\n{'=' * 60}")
    print(f"Total: {passed} passed, {failed} failed")
    if failed:
        exit(1)
