# tests/test_gc_vs_gateway.py
# Three-pathway overflow capacity: GC chip vs Accelerator vs Gateway Event Pipeline
from amaranth import *
from amaranth.sim import Simulator
from rtl.gc_chip_clean import GCCleanChipTop
from rtl.isa import GC_NEW
from rtl.jasper_gc_accelerator_config import JasperGCAcceleratorConfig, AcceleratorProfile
from rtl.jasper_gc_accelerator_ip import JasperGCAcceleratorIP
from rtl.gc_event_pipeline import GCEventPipelineSeparated, EVT_SCAN, EVT_SWEEP, EVT_MOVE
from rtl.gc_metadata_pipeline import MetadataCachePipelined
from rtl.gc_forwarding_table import ForwardingTableBankedPipeline
from rtl.gc_backend_merge import BackendMergeSingle


class GCFullChain(Elaboratable):
    def __init__(self):
        for s in ['event_valid','event_ready','event_type','event_addr','event_data',
                  'event_tag','event_epoch','event_seq','result_valid','result_ready',
                  'result_data','result_tag','flush','flush_epoch','current_epoch','busy',
                  'fill_ready','fill_valid']:
            setattr(self, s, Signal())
    def elaborate(self, platform):
        m = Module(); P = self
        pipe = GCEventPipelineSeparated()
        meta = MetadataCachePipelined(cache_size=1024, ways=2, access_granularity=32)
        ft = ForwardingTableBankedPipeline(bank_count=1, entries_per_bank=8, chase_depth=2)
        merge = BackendMergeSingle()
        m.submodules.pipe = pipe; m.submodules.meta = meta
        m.submodules.ft = ft; m.submodules.merge = merge
        m.d.comb += [
            pipe.event_valid.eq(P.event_valid), P.event_ready.eq(pipe.event_ready),
            pipe.event_type.eq(P.event_type), pipe.event_addr.eq(P.event_addr),
            pipe.event_data.eq(P.event_data), pipe.event_tag.eq(P.event_tag),
            pipe.event_epoch.eq(P.event_epoch), pipe.event_seq.eq(P.event_seq),
            pipe.flush.eq(P.flush), pipe.flush_epoch.eq(P.flush_epoch),
            pipe.current_epoch.eq(P.current_epoch),
            meta.request_valid.eq(pipe.result_valid),
            pipe.result_ready.eq(meta.request_ready),
            meta.request_addr.eq(pipe.result_data),
            meta.input_event.fields["event_id"].eq(pipe.result_tag),
            meta.input_event.fields["epoch"].eq(pipe.result_epoch),
            ft.query_valid.eq(meta.rsp_valid), meta.rsp_ready.eq(ft.query_ready),
            ft.query_old_ptr.eq(meta.rsp_data),
            ft.input_event.fields["event_id"].eq(meta.output_event.fields["event_id"]),
            merge.event_valid.eq(ft.rsp_valid), ft.rsp_ready.eq(merge.event_ready),
            merge.event_addr.eq(ft.rsp_new_ptr), merge.event_tag.eq(ft.rsp_tag),
            merge.event_source.eq(ft.rsp_tag),
            P.result_valid.eq(merge.result_valid), merge.result_ready.eq(P.result_ready),
            P.result_data.eq(merge.result_data), P.result_tag.eq(merge.result_tag),
            P.busy.eq(pipe.busy | meta.busy | ft.busy),
            P.fill_valid.eq(meta.fill_valid), meta.fill_ready.eq(P.fill_ready),
        ]
        return m


def test_gc_chip_ceiling():
    """GC chip max sustained throughput."""
    chip = GCCleanChipTop(ncores=1, engine_latency=0)
    sim = Simulator(chip); sim.add_clock(1e-6)
    N = 50
    total_cyc = 0
    async def proc(ctx):
        nonlocal total_cyc
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
    sim.add_testbench(proc); sim.run()
    return N / total_cyc if total_cyc else 0


def test_gateway_pipeline_ceiling():
    """Gateway event pipeline: max event acceptance rate (valid=1 every cycle)."""
    dut = GCFullChain()
    sim = Simulator(dut); sim.add_clock(1e-6)
    CYCLES = 400
    accepted = 0
    async def proc(ctx):
        nonlocal accepted
        ctx.set(dut.current_epoch, 1)
        ctx.set(dut.result_ready, 1)
        ctx.set(dut.fill_ready, 1)
        ctx.set(dut.flush, 0)
        await ctx.tick()
        evt_types = [EVT_SCAN, EVT_SWEEP, EVT_MOVE]
        for cyc in range(CYCLES):
            ctx.set(dut.event_valid, 1)
            ctx.set(dut.event_type, evt_types[cyc % 3])
            ctx.set(dut.event_addr, 0x1000 + (cyc % 64))
            ctx.set(dut.event_data, cyc & 0xFF)
            ctx.set(dut.event_tag, cyc & 0xFF)
            ctx.set(dut.event_epoch, 1)
            ctx.set(dut.event_seq, cyc & 0xFF)
            er = ctx.get(dut.event_ready)
            await ctx.tick()
            if er:
                accepted += 1
        ctx.set(dut.event_valid, 0)
        # drain
        for _ in range(64):
            await ctx.tick()
            if not ctx.get(dut.busy) and not ctx.get(dut.result_valid):
                break
    sim.add_testbench(proc); sim.run()
    return accepted / CYCLES


def test_acc_ceiling():
    """Accelerator max throughput (4 engines, burst)."""
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_STANDARD)
    cfg.max_outstanding_commands = 4
    cfg.command_queue_depth = 16
    cfg.completion_queue_depth = 16
    dut = JasperGCAcceleratorIP(cfg, enable_memory=False, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    N = 40
    total_cyc = 0
    async def proc(ctx):
        nonlocal total_cyc
        ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        await ctx.tick()
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
            ctx.set(dut.iface.cmd_valid, 0)
        for _ in range(N * 4):
            await ctx.tick(); total_cyc += 1
    sim.add_testbench(proc); sim.run()
    return N / total_cyc if total_cyc else 0


def test_acc_mem_ceiling(mem_lat=0):
    """Accelerator with memory latency."""
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_STANDARD)
    cfg.max_outstanding_commands = 4
    cfg.command_queue_depth = 16
    cfg.completion_queue_depth = 16
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True, mem_read_latency=mem_lat, burst_enable=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    N = 32
    total_cyc = 0
    async def proc(ctx):
        nonlocal total_cyc
        ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        await ctx.tick()
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
            ctx.set(dut.iface.cmd_valid, 0)
        for _ in range(N * 8):
            await ctx.tick(); total_cyc += 1
    sim.add_testbench(proc); sim.run()
    return N / total_cyc if total_cyc else 0


if __name__ == "__main__":
    print("=== Three-Pathway Overflow Capacity ===\n")

    gc_bw = test_gc_chip_ceiling()
    gw_bw = test_gateway_pipeline_ceiling()
    acc_bw = test_acc_ceiling()

    print(f"{'Pathway':45s} {'Max throughput (cmds/evts/cyc)':>30s}")
    print("─" * 75)
    print(f"{'GC chip (cmd_enq→rsp)':45s} {gc_bw:>8.4f}  (@lat=0)")
    print(f"{'Accelerator (4 engines)':45s} {acc_bw:>8.4f}  (counting peak)")
    print(f"{'Gateway Event Pipeline':45s} {gw_bw:>8.4f}  (events/cyc)")
    print()

    # Combined analysis
    print("  Combined capacity:")
    print(f"    GC + Acc = {gc_bw + acc_bw:.4f} cmds/cyc")
    print(f"    GC + Gateway = {gc_bw + gw_bw:.4f} cmds+evts/cyc")
    print(f"    GC + Acc + Gateway = {gc_bw + acc_bw + gw_bw:.4f} cmds+evts/cyc")
    print()

    # Accelerator with memory
    print("  Accelerator with memory latency:")
    for ml in [0, 4, 8]:
        bw = test_acc_mem_ceiling(ml)
        print(f"    mem_lat={ml}: {bw:.4f} cmds/cyc")
    print()

    # Combined with memory
    print("  Combined (GC lat=0 + Acc with memory):")
    for ml in [0, 4, 8]:
        acc_mem = test_acc_mem_ceiling(ml)
        print(f"    mem_lat={ml}: GC={gc_bw:.4f} + Acc={acc_mem:.4f} + Gateway={gw_bw:.4f} = {gc_bw + acc_mem + gw_bw:.4f}")
    print("=== Done ===")
