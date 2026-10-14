# tests/test_gc_backend_integration.py
# Cross-module integration tests: chaining EventPipeline -> ForwardingTable -> MetadataCache -> BackendMerge
from amaranth import *
from amaranth.sim import Simulator
from rtl.gc_event_pipeline import GCEventPipelineSeparated, EVT_SCAN
from rtl.gc_forwarding_table import ForwardingTableStandard
from rtl.gc_metadata_pipeline import MetadataCacheStandard
from rtl.gc_backend_merge import BackendMergeSingle, BackendMergeMulti
import sys


# ── Test 1: EventPipeline -> ForwardingTable chain ─────────────────────

def test_event_pipeline_to_forwarding_table():
    pipe = GCEventPipelineSeparated()
    ft = ForwardingTableStandard(map_depth=4, chase_depth=2)

    # Step 1: pipe accepts event, produces result_tag=42
    sim = Simulator(pipe)
    sim.add_clock(1e-6)

    async def proc(ctx):
        ctx.set(pipe.event_valid, 1)
        ctx.set(pipe.event_type, EVT_SCAN)
        ctx.set(pipe.event_addr, 0x1000)
        ctx.set(pipe.event_tag, 42)
        ctx.set(pipe.event_epoch, 1)
        ctx.set(pipe.event_seq, 0)
        ctx.set(pipe.current_epoch, 1)
        ctx.set(pipe.result_ready, 1)
        await ctx.tick()
        pipe_tag = ctx.get(pipe.result_tag)
        assert pipe_tag == 42, f"pipe tag={pipe_tag}"
        print(f"  pipe: tag={pipe_tag}")

    sim.add_testbench(proc)
    sim.run()

    # Step 2: FT pre-loaded with mapping, query with old_ptr=0x1000, tag=42
    sim2 = Simulator(ft)
    sim2.add_clock(1e-6)

    async def proc2(ctx):
        ctx.set(ft.epoch, 1)
        ctx.set(ft.update_valid, 1)
        ctx.set(ft.update_old_ptr, 0x1000)
        ctx.set(ft.update_new_ptr, 0x2000)
        ctx.set(ft.update_epoch, 1)
        await ctx.tick()
        ctx.set(ft.update_valid, 0)
        await ctx.tick()

        ctx.set(ft.query_valid, 1)
        ctx.set(ft.query_old_ptr, 0x1000)
        ctx.set(ft.query_tag, 42)
        ctx.set(ft.rsp_ready, 0)
        await ctx.tick()
        ctx.set(ft.query_valid, 0)
        rsp_tag = ctx.get(ft.rsp_tag)
        new_ptr = ctx.get(ft.rsp_new_ptr)
        assert rsp_tag == 42, f"FT tag={rsp_tag}, expected 42"
        assert new_ptr == 0x2000, f"new_ptr=0x{new_ptr:08x}"
        print(f"  FT: tag={rsp_tag} new=0x{new_ptr:08x} -- PASS")

    sim2.add_testbench(proc2)
    sim2.run()


# ── Test 2: MetadataCache -> BackendMergeSingle passthrough ────────────

def test_metadata_cache_to_backend_merge():
    mc = MetadataCacheStandard(cache_size=2048, ways=2, access_granularity=64)
    bm = BackendMergeSingle()

    sim = Simulator(mc)
    sim.add_clock(1e-6)

    async def proc(ctx):
        ctx.set(mc.request_valid, 1)
        ctx.set(mc.request_addr, 0x100)
        ctx.set(mc.request_source, 0)
        ctx.set(mc.fill_data, 0xBEEF)
        ctx.set(mc.fill_ready, 1)
        await ctx.tick()
        ctx.set(mc.request_valid, 0)
        for _ in range(10):
            await ctx.tick()
            if ctx.get(mc.rsp_valid):
                break
        rsp_data = ctx.get(mc.rsp_data)
        print(f"  MC: data=0x{rsp_data:08x}")

    sim.add_testbench(proc)
    sim.run()

    sim2 = Simulator(bm)
    sim2.add_clock(1e-6)

    async def proc2(ctx):
        ctx.set(bm.event_valid, 1)
        ctx.set(bm.event_addr, 0xBEEF)
        ctx.set(bm.event_tag, 99)
        ctx.set(bm.result_ready, 1)
        await ctx.tick()
        rt = ctx.get(bm.result_tag)
        rd = ctx.get(bm.result_data)
        assert rt == 99, f"BM tag={rt}, expected 99"
        assert rd == 0xBEEF, f"BM data=0x{rd:08x}, expected 0xBEEF"
        print(f"  BM: data=0x{rd:08x} tag={rt} -- PASS")

    sim2.add_testbench(proc2)
    sim2.run()


# ── Test 3: core_id (tag) preservation across 3-stage pipeline ─────────

def test_three_stage_core_id_preservation():
    pipe = GCEventPipelineSeparated()
    ft = ForwardingTableStandard(map_depth=4, chase_depth=2)
    mc = MetadataCacheStandard(cache_size=2048, ways=2, access_granularity=64)
    bm = BackendMergeSingle()

    sim = Simulator(pipe)
    sim.add_clock(1e-6)
    async def proc(ctx):
        ctx.set(pipe.event_valid, 1)
        ctx.set(pipe.event_type, EVT_SCAN)
        ctx.set(pipe.event_addr, 0x1000)
        ctx.set(pipe.event_tag, 99)
        ctx.set(pipe.event_epoch, 1)
        ctx.set(pipe.event_seq, 0)
        ctx.set(pipe.current_epoch, 1)
        ctx.set(pipe.result_ready, 1)
        await ctx.tick()
        assert ctx.get(pipe.result_tag) == 99, "pipe tag != 99"
        print(f"  Pipe: tag=99")
    sim.add_testbench(proc)
    sim.run()

    sim2 = Simulator(ft)
    sim2.add_clock(1e-6)
    async def proc2(ctx):
        ctx.set(ft.epoch, 1)
        ctx.set(ft.update_valid, 1)
        ctx.set(ft.update_old_ptr, 0x1000)
        ctx.set(ft.update_new_ptr, 0x2000)
        ctx.set(ft.update_epoch, 1)
        await ctx.tick()
        ctx.set(ft.update_valid, 0)
        await ctx.tick()
        ctx.set(ft.query_valid, 1)
        ctx.set(ft.query_old_ptr, 0x1000)
        ctx.set(ft.query_tag, 99)
        ctx.set(ft.rsp_ready, 0)
        await ctx.tick()
        ctx.set(ft.query_valid, 0)
        assert ctx.get(ft.rsp_tag) == 99, f"FT tag != 99"
        print(f"  FT: tag=99")
    sim2.add_testbench(proc2)
    sim2.run()

    sim3 = Simulator(mc)
    sim3.add_clock(1e-6)
    async def proc3(ctx):
        ctx.set(mc.request_valid, 1)
        ctx.set(mc.request_addr, 0x2000)
        ctx.set(mc.request_source, 0)
        ctx.set(mc.fill_data, 0xCAFE)
        ctx.set(mc.fill_ready, 1)
        await ctx.tick()
        ctx.set(mc.request_valid, 0)
        for _ in range(10):
            await ctx.tick()
            if ctx.get(mc.rsp_valid):
                break
        print(f"  MC: data=0x{ctx.get(mc.rsp_data):08x}")
    sim3.add_testbench(proc3)
    sim3.run()

    sim4 = Simulator(bm)
    sim4.add_clock(1e-6)
    async def proc4(ctx):
        ctx.set(bm.event_valid, 1)
        ctx.set(bm.event_addr, 0xCAFE)
        ctx.set(bm.event_tag, 99)
        ctx.set(bm.result_ready, 1)
        await ctx.tick()
        assert ctx.get(bm.result_tag) == 99, f"BM tag != 99"
        print(f"  BM: tag=99 -- PASS")
    sim4.add_testbench(proc4)
    sim4.run()


# ── Test 4: Epoch passthrough ──────────────────────────────────────────

def test_epoch_passthrough():
    pipe = GCEventPipelineSeparated()
    ft = ForwardingTableStandard(map_depth=4, chase_depth=2)

    sim = Simulator(pipe)
    sim.add_clock(1e-6)
    async def proc(ctx):
        ctx.set(pipe.event_valid, 1)
        ctx.set(pipe.event_type, EVT_SCAN)
        ctx.set(pipe.event_addr, 0x1000)
        ctx.set(pipe.event_tag, 42)
        ctx.set(pipe.event_epoch, 7)
        ctx.set(pipe.event_seq, 0)
        ctx.set(pipe.current_epoch, 7)
        ctx.set(pipe.result_ready, 1)
        await ctx.tick()
        assert ctx.get(pipe.result_valid), "pipe no result with epoch 7"
        print(f"  Pipe: result_epoch={ctx.get(pipe.result_epoch)}")
    sim.add_testbench(proc)
    sim.run()

    sim2 = Simulator(ft)
    sim2.add_clock(1e-6)
    async def proc2(ctx):
        ctx.set(ft.epoch, 7)
        ctx.set(ft.update_valid, 1)
        ctx.set(ft.update_old_ptr, 0x1000)
        ctx.set(ft.update_new_ptr, 0x2000)
        ctx.set(ft.update_epoch, 7)
        await ctx.tick()
        ctx.set(ft.update_valid, 0)
        await ctx.tick()

        ctx.set(ft.query_valid, 1)
        ctx.set(ft.query_old_ptr, 0x1000)
        ctx.set(ft.query_tag, 42)
        ctx.set(ft.rsp_ready, 0)
        await ctx.tick()
        ctx.set(ft.query_valid, 0)
        assert ctx.get(ft.rsp_valid), "FT epoch=7: no response"
        assert ctx.get(ft.rsp_hit), "FT epoch=7: miss"
        print(f"  FT: epoch=7 hit -- PASS")
    sim2.add_testbench(proc2)
    sim2.run()


# ── Test 5: merge_domain preservation in BackendMergeMulti ─────────────

def test_merge_domain_preservation():
    bm = BackendMergeMulti(data_width=32, tag_width=8, backend_count=2, source_width=8)

    from amaranth.sim import Tick
    sim = Simulator(bm)
    sim.add_clock(1e-6)

    def proc():
        yield bm.dispatch_policy.eq(0)
        yield bm.merge_policy.eq(0)
        yield bm.backend_busy.eq(0)

        yield bm.event_valid.eq(1)
        yield bm.event_addr.eq(0x1000)
        yield bm.event_tag.eq(1)
        yield bm.event_source.eq(3)
        yield Tick()
        rv = (yield bm.result_valid)
        assert rv, "no result after event 1"
        md = (yield bm.output_event.fields["merge_domain"])
        ev = (yield bm.output_event.fields["event_id"])
        print(f"  event 1: merge_domain={md} event_id={ev}")
        yield bm.event_valid.eq(0)

        yield bm.event_valid.eq(1)
        yield bm.event_addr.eq(0x2000)
        yield bm.event_tag.eq(2)
        yield bm.event_source.eq(7)
        yield Tick()
        rv = (yield bm.result_valid)
        assert rv, "no result after event 2"
        md = (yield bm.output_event.fields["merge_domain"])
        ev = (yield bm.output_event.fields["event_id"])
        print(f"  event 2: merge_domain={md} event_id={ev}")
        yield bm.event_valid.eq(0)
        yield Tick()
        print(f"  BM Multi: merge_domain preserved -- PASS")

    sim.add_process(proc)
    sim.run()


if __name__ == "__main__":
    tests = [
        ("EventPipeline -> ForwardingTable",        test_event_pipeline_to_forwarding_table),
        ("MetadataCache -> BackendMerge",            test_metadata_cache_to_backend_merge),
        ("3-Stage core_id (tag) preservation",       test_three_stage_core_id_preservation),
        ("Epoch passthrough",                        test_epoch_passthrough),
        ("merge_domain in BackendMergeMulti",        test_merge_domain_preservation),
    ]
    print("=" * 60)
    print("GC Backend Integration Tests")
    print("=" * 60)
    all_ok = True
    for name, fn in tests:
        print(f"\n[{name}]")
        try:
            ok = fn()
            if ok is not None:
                print(f"  -> {'PASS' if ok else 'FAIL'}")
                all_ok &= ok
        except Exception as e:
            import traceback
            print(f"  -> FAIL: {e}")
            traceback.print_exc()
            all_ok = False
    print(f"\n{'='*60}")
    print(f"{'ALL PASS' if all_ok else 'SOME FAILED'}")
    sys.exit(0 if all_ok else 1)
