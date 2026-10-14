# rtl/gc_memory_policy.py
# GC Memory Policy: Metadata Cache + Stream Buffer + Bypass + Partition
from amaranth import *
from amaranth.lib.fifo import SyncFIFO
from dataclasses import dataclass

@dataclass
class GCMemoryPolicyParams:
    metadata_cache_enable: bool = False
    metadata_cache_size: int = 4096
    metadata_cache_ways: int = 2
    metadata_cache_line_size: int = 64
    stream_buffer_enable: bool = False
    stream_buffer_entries: int = 4
    stream_buffer_line_size: int = 64
    stream_buffer_prefetch_distance: int = 2
    dcache_bypass_enable: bool = True
    bypass_gc_scan: bool = True
    bypass_gc_sweep: bool = True
    bypass_gc_root: bool = True
    bypass_gc_object_walk: bool = True
    cache_partition_enable: bool = False
    mutator_reserved_ways: int = 6
    gc_reserved_ways: int = 2
    gc_no_fill_policy: str = "bypass"
    debug: bool = False

class GCMemoryPolicy(Elaboratable):
    """GC Memory Policy Controller — 完整 cache/stream/bypass/partition"""
    def __init__(self, params: GCMemoryPolicyParams = None):
        self.p = params or GCMemoryPolicyParams()
        # I/O
        self.access_valid = Signal()
        self.access_addr = Signal(32)
        self.access_source = Signal(4)  # 0=MUTATOR, 1=GC_SCAN, 2=GC_SWEEP, 3=GC_ROOT, 4=GC_WALK, 5+=GC_META
        self.access_is_write = Signal()
        self.access_data = Signal(32)
        self.access_ready = Signal()
        # Metadata cache hit/data
        self.metadata_cache_hit = Signal()
        self.metadata_cache_data = Signal(32)
        # Stream buffer hit/data
        self.stream_buffer_hit = Signal()
        self.stream_buffer_data = Signal(32)
        # Policy outputs
        self.bypass_dcache = Signal()
        self.reserved_mutator_ways = Signal(5)
        self.reserved_gc_ways = Signal(5)
        self.use_metadata_cache = Signal()
        self.use_stream_buffer = Signal()
        # DMEM access request (when cache misses)
        self.dmem_req_valid = Signal()
        self.dmem_req_addr = Signal(32)
        self.dmem_req_write = Signal()
        self.dmem_req_wdata = Signal(32)
        self.dmem_rsp_valid = Signal()
        self.dmem_rsp_data = Signal(32)
        # Stream buffer diagnostics (debug only)
        self.dbg_sb_valid = Signal(4)
        self.dbg_sb_tag0 = Signal(26)
        self.dbg_sb_tag1 = Signal(26)
        self.dbg_sb_wptr = Signal()
        self.dbg_sb_last_addr = Signal(26)
        self.dbg_sb_line = Signal(26)
        self.dbg_sb_seq = Signal()

        # Stats
        self.meta_cache_hits = Signal(32)
        self.meta_cache_misses = Signal(32)
        self.stream_hits = Signal(32)
        self.stream_misses = Signal(32)
        self.bypass_events = Signal(32)

    def elaborate(self, platform):
        m = Module()
        P = self.p
        line_bits = P.metadata_cache_line_size.bit_length() - 1  # 6 for 64B
        lines = P.metadata_cache_size // P.metadata_cache_line_size
        ways = P.metadata_cache_ways
        sets = lines // ways
        idx_bits = (sets - 1).bit_length() if sets > 1 else 1

        src_is_gc = self.access_source != 0
        src_is_scan = self.access_source == 1
        src_is_sweep = self.access_source == 2
        src_is_root = self.access_source == 3
        src_is_walk = self.access_source == 4
        src_is_meta = self.access_source >= 5

        # ── Bypass decision ──────────────────────────────
        m.d.comb += [
            self.bypass_dcache.eq(
                P.dcache_bypass_enable & src_is_gc & (
                    (src_is_scan & P.bypass_gc_scan) |
                    (src_is_sweep & P.bypass_gc_sweep) |
                    (src_is_root & P.bypass_gc_root) |
                    (src_is_walk & P.bypass_gc_object_walk))),
            self.reserved_mutator_ways.eq(P.mutator_reserved_ways if P.cache_partition_enable else 0),
            self.reserved_gc_ways.eq(P.gc_reserved_ways if P.cache_partition_enable else 0),
        ]

        # ── Metadata Cache (real sets×ways) ─────────────
        if P.metadata_cache_enable and sets > 0 and ways > 0:
            idx = Signal(idx_bits)
            tag = Signal(32 - line_bits - idx_bits)
            m.d.comb += [
                idx.eq(self.access_addr[line_bits:line_bits + idx_bits]),
                tag.eq(self.access_addr[line_bits + idx_bits:32]),
            ]
            mc_v = Array([Array([Signal(name=f"mc_v{w}_{s}") for s in range(sets)]) for w in range(ways)])
            mc_t = Array([Array([Signal(32 - line_bits - idx_bits, name=f"mc_t{w}_{s}") for s in range(sets)]) for w in range(ways)])
            mc_d = Array([Array([Signal(32, name=f"mc_d{w}_{s}") for s in range(sets)]) for w in range(ways)])
            mc_rr = Array([Signal(range(ways), reset=0) for _ in range(sets)])

            hit_way = Signal(range(ways))
            hit_found = Signal()
            m.d.comb += [hit_found.eq(0), hit_way.eq(0)]
            for w in range(ways):
                hit = mc_v[w][idx] & (mc_t[w][idx] == tag)
                m.d.comb += [hit_way.eq(Mux(hit & ~hit_found, w, hit_way)), hit_found.eq(hit_found | hit)]

            m.d.comb += [
                self.use_metadata_cache.eq(src_is_meta),
                self.metadata_cache_hit.eq(hit_found),
                self.metadata_cache_data.eq(Mux(hit_found, mc_d[hit_way][idx], 0)),
            ]

            # Miss fill: save missed address, fill on dmem response
            miss_tag = Signal(32 - line_bits - idx_bits)
            miss_idx = Signal(idx_bits)
            with m.If(P.metadata_cache_enable & src_is_meta & ~hit_found & self.dmem_req_valid):
                m.d.sync += [miss_tag.eq(tag), miss_idx.eq(idx)]
            with m.If(self.dmem_rsp_valid):
                rpl = mc_rr[miss_idx]
                m.d.sync += [
                    mc_v[rpl][miss_idx].eq(1),
                    mc_t[rpl][miss_idx].eq(miss_tag),
                    mc_d[rpl][miss_idx].eq(self.dmem_rsp_data),
                    mc_rr[miss_idx].eq(Mux(rpl == ways - 1, 0, rpl + 1)),
                ]

            # Write on store hit
            with m.If(self.access_valid & self.access_is_write & hit_found & P.metadata_cache_enable):
                m.d.sync += mc_d[hit_way][idx].eq(self.access_data)

            # DMEM request on miss
            m.d.comb += [
                self.dmem_req_valid.eq(self.access_valid & ~hit_found & P.metadata_cache_enable & src_is_meta),
                self.dmem_req_addr.eq(self.access_addr),
                self.dmem_req_write.eq(0),
            ]
        else:
            m.d.comb += [
                self.use_metadata_cache.eq(0),
                self.metadata_cache_hit.eq(0), self.metadata_cache_data.eq(0),
                self.dmem_req_valid.eq(0), self.dmem_req_addr.eq(0),
            ]

        use_meta = P.metadata_cache_enable & src_is_meta

        # ── Stream Buffer (sequential access detector) ──
        if P.stream_buffer_enable:
            sb_valid = Array([Signal(name=f"sb_v{i}") for i in range(P.stream_buffer_entries)])
            sb_tag = Array([Signal(32 - line_bits, name=f"sb_t{i}") for i in range(P.stream_buffer_entries)])
            sb_data = Array([Signal(32, name=f"sb_d{i}") for i in range(P.stream_buffer_entries)])
            sb_wptr = Signal(range(P.stream_buffer_entries), reset=0)
            last_addr = Signal(32 - line_bits)
            line = Signal(32 - line_bits)
            seq = Signal()
            sb_av = self.access_valid  # shorthand
            m.d.comb += [line.eq(self.access_addr >> line_bits), seq.eq(line == (last_addr + 1))]

            # Hit check (single comb block, no multiple drivers)
            sb_hit = Signal(); sb_hit_idx = Signal(range(P.stream_buffer_entries))
            sb_hit_v = Const(0); sb_hit_iv = Const(0)
            for i in range(P.stream_buffer_entries):
                h = sb_valid[i] & (line == sb_tag[i])
                sb_hit_v = sb_hit_v | h
                sb_hit_iv = Mux(h & ~sb_hit_v, Const(i), sb_hit_iv)
            m.d.comb += [sb_hit.eq(sb_hit_v), sb_hit_idx.eq(sb_hit_iv)]
            m.d.comb += [
                self.use_stream_buffer.eq(1),
                self.stream_buffer_hit.eq(sb_hit & ~src_is_meta),
                self.stream_buffer_data.eq(sb_data[sb_hit_idx]),
            ]

            # Update last_addr on every access (simplified)
            with m.If(sb_av & ~self.bypass_dcache & seq):
                m.d.sync += [
                    sb_valid[sb_wptr].eq(1),
                    sb_tag[sb_wptr].eq(line + 1),
                    sb_data[sb_wptr].eq(self.dmem_rsp_data),
                    sb_wptr.eq(Mux(sb_wptr == P.stream_buffer_entries - 1, 0, sb_wptr + 1)),
                    last_addr.eq(line),
                ]
            with m.Elif(sb_av & ~self.bypass_dcache & ~seq):
                m.d.sync += last_addr.eq(line)
        else:
            m.d.comb += [self.use_stream_buffer.eq(0), self.stream_buffer_hit.eq(0), self.stream_buffer_data.eq(0)]

        use_stream = P.stream_buffer_enable & src_is_gc & ~use_meta & ~self.bypass_dcache

        # ── DMEM access (when neither cache nor stream hit) ──
        m.d.comb += self.access_ready.eq(
            use_meta & self.metadata_cache_hit |
            use_stream & self.stream_buffer_hit |
            self.dmem_rsp_valid
        )

        # ── Stats ────────────────────────────────────────
        if self.p.debug:
            # Stream buffer diagnostics (debug only)
            if P.stream_buffer_enable:
                m.d.comb += [
                    self.dbg_sb_wptr.eq(sb_wptr),
                    self.dbg_sb_last_addr.eq(last_addr),
                    self.dbg_sb_line.eq(line),
                    self.dbg_sb_seq.eq(seq),
                ]
                for i in range(min(4, P.stream_buffer_entries)):
                    m.d.comb += self.dbg_sb_valid[i].eq(sb_valid[i])
                if P.stream_buffer_entries > 0:
                    m.d.comb += self.dbg_sb_tag0.eq(sb_tag[0])
                if P.stream_buffer_entries > 1:
                    m.d.comb += self.dbg_sb_tag1.eq(sb_tag[1])

        m.d.sync += [
            self.meta_cache_hits.eq(self.meta_cache_hits + (self.metadata_cache_hit & use_meta)),
            self.meta_cache_misses.eq(self.meta_cache_misses + (use_meta & ~self.metadata_cache_hit)),
            self.stream_hits.eq(self.stream_hits + (self.stream_buffer_hit & use_stream)),
            self.stream_misses.eq(self.stream_misses + (use_stream & ~self.stream_buffer_hit)),
            self.bypass_events.eq(self.bypass_events + self.bypass_dcache),
        ]

        return m
