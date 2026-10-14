# rtl/jasper_gc_ip.py
# Jasper-GC unified design: top-level Elaboratable that instantiates the correct backend
from amaranth import *
from rtl.jasper_gc_config import JasperGCConfig, BackendProfile, DispatchPolicy, MergePolicy, BackpressurePolicy
from rtl.gc_backend_tile import BackendTile
from rtl.gc_backend_merge import BackendMergeSingle
from rtl.gc_event_pipeline import GCEventPipelineStandard
from rtl.gc_forwarding_table import ForwardingTableBankedPipeline
from rtl.gc_metadata_pipeline import MetadataCachePipelined
from rtl.gc_multi_backend_cluster import GCMultiBackendCluster
from rtl.gc_fabric import OrderedGlobalMerge, IdleDetect, FabricCoordinator, LoadBasedEnable


class JasperGCIP(Elaboratable):
    def __init__(self, config: JasperGCConfig):
        self.config = config
        errors = config.validate()
        if errors:
            raise ValueError(f"JasperGCConfig validation failed: {'; '.join(errors)}")

        cfg = config

        # Core-side event input (port 0)
        self.gc_event_valid = Signal()
        self.gc_event_ready = Signal()
        self.gc_event_type = Signal(4)
        self.gc_event_addr = Signal(32)
        self.gc_event_data = Signal(32)
        self.gc_event_tag = Signal(8)
        self.gc_event_epoch = Signal(8)
        self.gc_event_seq = Signal(8)
        self.gc_event_merge_domain = Signal(4)
        self.core_id = Signal(8)
        self.region_id = Signal(8)
        self.cpu_event_valid = [Signal() for _ in range(cfg.cpu_core_count)]
        self.cpu_event_ready = [Signal() for _ in range(cfg.cpu_core_count)]
        self.cpu_event_type = [Signal(4) for _ in range(cfg.cpu_core_count)]
        self.cpu_event_addr = [Signal(32) for _ in range(cfg.cpu_core_count)]
        self.cpu_event_data = [Signal(32) for _ in range(cfg.cpu_core_count)]
        self.cpu_event_tag = [Signal(8) for _ in range(cfg.cpu_core_count)]
        self.cpu_event_epoch = [Signal(8) for _ in range(cfg.cpu_core_count)]
        self.cpu_event_seq = [Signal(8) for _ in range(cfg.cpu_core_count)]
        self.cpu_region_id = [Signal(8) for _ in range(cfg.cpu_core_count)]

        # Core-side event input (port 1) — for 2L tile dual-input
        self.gc_event1_valid = Signal()
        self.gc_event1_ready = Signal()
        self.gc_event1_type = Signal(4)
        self.gc_event1_addr = Signal(32)
        self.gc_event1_data = Signal(32)
        self.gc_event1_tag = Signal(8)
        self.gc_event1_epoch = Signal(8)
        self.gc_event1_seq = Signal(8)

        # Result output
        self.gc_result_valid = Signal()
        self.gc_result_ready = Signal()
        self.gc_result_data = Signal(32)
        self.gc_result_tag = Signal(8)
        self.gc_result_epoch = Signal(8)
        self.gc_result_seq = Signal(8)
        self.gc_result_merge_domain = Signal(4)
        self.gc_result_status = Signal(4)

        # Control
        self.current_epoch = Signal(8)
        self.flush = Signal()
        self.flush_epoch = Signal(8)
        self.gc_enable = Signal()
        self.config_lock = Signal()

        # Debug / perf (optional)
        if cfg.enable_perf_counters:
            self.perf_event_count = Signal(32)
            self.perf_stall_count = Signal(32)
            self.perf_backpressure_count = Signal(32)
            self.perf_tile_active_mask = Signal(cfg.tile_count)
        else:
            self.perf_event_count = Signal()
            self.perf_stall_count = Signal()
            self.perf_backpressure_count = Signal()
            self.perf_tile_active_mask = Signal()
        if cfg.enable_debug:
            self.debug_state = Signal(32)
        else:
            self.debug_state = Signal()

        # External accelerator interface (optional placeholder)
        if cfg.enable_external_gc_interface:
            self.gc_ext = Record([
                ("cmd_valid", 1), ("cmd_ready", 1), ("cmd_type", 4),
                ("region_base", 32), ("region_size", 32), ("epoch", 8), ("merge_domain", 4),
                ("completion_valid", 1), ("completion_ready", 1), ("completion_status", 4),
            ])

    # ── Tile backend: single tile × 1 or 2 lanes ───────────────────
    def _wire_tile(self, m, lane_count=1):
        from rtl.gc_backend_tile import BackendTile

        tile = BackendTile(
            lane_count=lane_count,
            metadata_cache_size=self.config.metadata_cache_size,
            metadata_ways=self.config.metadata_ways,
            metadata_pipeline_depth=self.config.metadata_pipeline_depth,
            forwarding_entries=self.config.forwarding_entries,
            forwarding_chase_depth=self.config.forwarding_chase_depth,
        )
        m.submodules.tile = tile

        event_valid_gated = Signal()
        m.d.comb += event_valid_gated.eq(self.gc_event_valid & self.gc_enable)

        # Lane 0
        m.d.comb += [
            tile.in0_valid.eq(event_valid_gated),
            tile.in0_type.eq(self.gc_event_type[:2]),
            tile.in0_addr.eq(self.gc_event_addr),
            tile.in0_data.eq(self.gc_event_data),
            tile.in0_tag.eq(self.gc_event_tag),
            tile.in0_epoch.eq(self.gc_event_epoch),
            tile.in0_seq.eq(self.gc_event_seq[:2]),
            self.gc_event_ready.eq(tile.in0_ready),
            tile.flush.eq(self.flush),
            tile.flush_epoch.eq(self.flush_epoch),
            tile.current_epoch.eq(self.current_epoch),
            tile.fill_ready.eq(self.config.enable_forwarding),
        ]

        # Lane 1 (only for lane_count >= 2)
        if lane_count >= 2:
            ev1_valid_gated = Signal()
            m.d.comb += ev1_valid_gated.eq(self.gc_event1_valid & self.gc_enable)
            m.d.comb += [
                tile.in1_valid.eq(ev1_valid_gated),
                tile.in1_type.eq(self.gc_event1_type[:2]),
                tile.in1_addr.eq(self.gc_event1_addr),
                tile.in1_data.eq(self.gc_event1_data),
                tile.in1_tag.eq(self.gc_event1_tag),
                tile.in1_epoch.eq(self.gc_event1_epoch),
                tile.in1_seq.eq(self.gc_event1_seq[:2]),
                self.gc_event1_ready.eq(tile.in1_ready),
            ]

        # Merge tile outputs when lane_count == 2
        if lane_count == 1:
            m.d.comb += [
                self.gc_result_valid.eq(tile.out0_valid),
                tile.out0_ready.eq(self.gc_result_ready),
                self.gc_result_data.eq(tile.out0_data),
                self.gc_result_tag.eq(tile.out0_tag),
                self.gc_result_epoch.eq(tile.out0_epoch),
                self.gc_result_seq.eq(tile.out0_seq),
                self.gc_result_merge_domain.eq(tile.out0_domain),
                self.gc_result_status.eq(0),
            ]
        else:
            from rtl.gc_fabric import OrderedGlobalMerge
            tmerge = OrderedGlobalMerge(
                domain_count=self.config.merge_domain_count or 1,
                tile_count=1,
                queue_depth=self.config.ordered_merge_queue_depth,
            )
            m.submodules.tmerge = tmerge
            m.d.comb += [
                tmerge.in_valid[0][0].eq(tile.out0_valid), tile.out0_ready.eq(tmerge.in_ready[0][0]),
                tmerge.in_data[0][0].eq(tile.out0_data), tmerge.in_tag[0][0].eq(tile.out0_tag),
                tmerge.in_epoch[0][0].eq(tile.out0_epoch), tmerge.in_seq[0][0].eq(tile.out0_seq),
                tmerge.in_domain[0][0].eq(0),
                tmerge.in_valid[0][1].eq(tile.out1_valid), tile.out1_ready.eq(tmerge.in_ready[0][1]),
                tmerge.in_data[0][1].eq(tile.out1_data), tmerge.in_tag[0][1].eq(tile.out1_tag),
                tmerge.in_epoch[0][1].eq(tile.out1_epoch), tmerge.in_seq[0][1].eq(tile.out1_seq),
                tmerge.in_domain[0][1].eq(0),
                self.gc_result_valid.eq(tmerge.out_valid),
                tmerge.out_ready.eq(self.gc_result_ready),
                self.gc_result_data.eq(tmerge.out_data),
                self.gc_result_tag.eq(tmerge.out_tag),
                self.gc_result_epoch.eq(tmerge.out_epoch),
                self.gc_result_seq.eq(tmerge.out_seq),
                self.gc_result_merge_domain.eq(tmerge.out_domain),
                self.gc_result_status.eq(0),
            ]

    # ── N × 2L cluster: multiple tiles, fabric dispatch/merge ──────
    def _wire_cluster(self, m):
        cfg = self.config
        from rtl.gc_multi_backend_cluster import GCMultiBackendCluster

        if cfg.tile_count > 32:
            domain_count = min(4, cfg.tile_count // 16)
            tiles_per_domain = cfg.tile_count // domain_count
            cores_per_domain = (cfg.cpu_core_count + domain_count - 1) // domain_count
            inputs_per_domain = cores_per_domain + 1

            clusters = []
            for domain in range(domain_count):
                cluster = GCMultiBackendCluster(
                    tile_count=tiles_per_domain,
                    lane_per_tile=cfg.lane_per_tile,
                    input_count=inputs_per_domain,
                    dispatch_policy=DispatchPolicy.HASH_LSB,
                    merge_policy=cfg.merge_policy,
                    backpressure_policy=cfg.backpressure_policy,
                    ordered_merge_queue_depth=cfg.ordered_merge_queue_depth,
                    merge_domain_count=cfg.merge_domain_count,
                    metadata_cache_size=cfg.metadata_cache_size,
                    metadata_ways=cfg.metadata_ways,
                    metadata_pipeline_depth=cfg.metadata_pipeline_depth,
                    forwarding_entries=cfg.forwarding_entries,
                    forwarding_chase_depth=cfg.forwarding_chase_depth,
                )
                clusters.append(cluster)
                m.submodules[f"domain_cluster_{domain}"] = cluster
                m.d.comb += [
                    cluster.flush.eq(self.flush),
                    cluster.flush_epoch.eq(self.flush_epoch),
                    cluster.current_epoch.eq(self.current_epoch),
                    cluster.fill_ready.eq(cfg.enable_forwarding),
                ]

            event_valid_gated = Signal()
            m.d.comb += event_valid_gated.eq(self.gc_event_valid & self.gc_enable)
            m.d.comb += [
                clusters[0].in_valid.eq(event_valid_gated),
                self.gc_event_ready.eq(clusters[0].in_ready),
                clusters[0].in_type.eq(self.gc_event_type[:2]),
                clusters[0].in_addr.eq(self.gc_event_addr),
                clusters[0].in_data.eq(self.gc_event_data),
                clusters[0].in_tag.eq(self.gc_event_tag),
                clusters[0].in_epoch.eq(self.gc_event_epoch),
                clusters[0].in_seq.eq(self.gc_event_seq[:2]),
                clusters[0].core_id.eq(self.core_id),
                clusters[0].region_id.eq(self.region_id),
            ]

            for core in range(cfg.cpu_core_count):
                domain = core % domain_count
                local = (core // domain_count) + 1
                cluster = clusters[domain]
                m.d.comb += [
                    cluster.core_in_valid[local].eq(self.cpu_event_valid[core] & self.gc_enable),
                    self.cpu_event_ready[core].eq(cluster.core_in_ready[local]),
                    cluster.core_in_type[local].eq(self.cpu_event_type[core][:2]),
                    cluster.core_in_addr[local].eq(self.cpu_event_addr[core]),
                    cluster.core_in_data[local].eq(self.cpu_event_data[core]),
                    cluster.core_in_tag[local].eq(self.cpu_event_tag[core]),
                    cluster.core_in_epoch[local].eq(self.cpu_event_epoch[core]),
                    cluster.core_in_seq[local].eq(self.cpu_event_seq[core][:2]),
                    cluster.core_in_core_id[local].eq(core),
                    cluster.core_in_region_id[local].eq(self.cpu_region_id[core]),
                ]

            domain_merge = OrderedGlobalMerge(
                domain_count=cfg.merge_domain_count,
                tile_count=domain_count,
                queue_depth=cfg.ordered_merge_queue_depth,
            )
            m.submodules.domain_merge = domain_merge
            for domain, cluster in enumerate(clusters):
                m.d.comb += [
                    domain_merge.in_valid[domain][0].eq(cluster.out_valid),
                    cluster.out_ready.eq(domain_merge.in_ready[domain][0]),
                    domain_merge.in_data[domain][0].eq(cluster.out_data),
                    domain_merge.in_tag[domain][0].eq(cluster.out_tag),
                    domain_merge.in_epoch[domain][0].eq(cluster.out_epoch),
                    domain_merge.in_seq[domain][0].eq(cluster.out_seq),
                    domain_merge.in_domain[domain][0].eq(cluster.out_domain),
                    domain_merge.in_valid[domain][1].eq(0),
                ]

            m.d.comb += [
                self.gc_result_valid.eq(domain_merge.out_valid),
                domain_merge.out_ready.eq(self.gc_result_ready),
                self.gc_result_data.eq(domain_merge.out_data),
                self.gc_result_tag.eq(domain_merge.out_tag),
                self.gc_result_epoch.eq(domain_merge.out_epoch),
                self.gc_result_seq.eq(domain_merge.out_seq),
                self.gc_result_merge_domain.eq(domain_merge.out_domain),
                self.gc_result_status.eq(0),
                self.gc_event1_ready.eq(0),
            ]
            return

        cluster = GCMultiBackendCluster(
            tile_count=cfg.tile_count,
            lane_per_tile=cfg.lane_per_tile,
            input_count=cfg.cpu_core_count,
            dispatch_policy=cfg.dispatch_policy,
            merge_policy=cfg.merge_policy,
            backpressure_policy=cfg.backpressure_policy,
            ordered_merge_queue_depth=cfg.ordered_merge_queue_depth,
            merge_domain_count=cfg.merge_domain_count,
            metadata_cache_size=cfg.metadata_cache_size,
            metadata_ways=cfg.metadata_ways,
            metadata_pipeline_depth=cfg.metadata_pipeline_depth,
            forwarding_entries=cfg.forwarding_entries,
            forwarding_chase_depth=cfg.forwarding_chase_depth,
        )
        m.submodules.cluster = cluster

        event_valid_gated = Signal()
        m.d.comb += event_valid_gated.eq(self.gc_event_valid & self.gc_enable)

        core0_valid = Signal()
        m.d.comb += core0_valid.eq(event_valid_gated | self.cpu_event_valid[0])
        m.d.comb += [
            cluster.in_valid.eq(core0_valid),
            cluster.in_type.eq(self.gc_event_type[:2]),
            cluster.in_addr.eq(self.gc_event_addr),
            cluster.in_data.eq(self.gc_event_data),
            cluster.in_tag.eq(self.gc_event_tag),
            cluster.in_epoch.eq(self.gc_event_epoch),
            cluster.in_seq.eq(self.gc_event_seq[:2]),
            self.gc_event_ready.eq(cluster.in_ready),
            self.cpu_event_ready[0].eq(cluster.in_ready),
            cluster.flush.eq(self.flush),
            cluster.flush_epoch.eq(self.flush_epoch),
            cluster.current_epoch.eq(self.current_epoch),
            cluster.core_id.eq(self.core_id),
            cluster.region_id.eq(self.region_id),
        ]
        with m.If(self.cpu_event_valid[0]):
            m.d.comb += [
                cluster.in_type.eq(self.cpu_event_type[0][:2]),
                cluster.in_addr.eq(self.cpu_event_addr[0]),
                cluster.in_data.eq(self.cpu_event_data[0]),
                cluster.in_tag.eq(self.cpu_event_tag[0]),
                cluster.in_epoch.eq(self.cpu_event_epoch[0]),
                cluster.in_seq.eq(self.cpu_event_seq[0][:2]),
                cluster.core_id.eq(0),
                cluster.region_id.eq(self.cpu_region_id[0]),
            ]

        for i in range(1, cfg.cpu_core_count):
            m.d.comb += [
                cluster.core_in_valid[i].eq(self.cpu_event_valid[i] & self.gc_enable),
                self.cpu_event_ready[i].eq(cluster.core_in_ready[i]),
                cluster.core_in_type[i].eq(self.cpu_event_type[i][:2]),
                cluster.core_in_addr[i].eq(self.cpu_event_addr[i]),
                cluster.core_in_data[i].eq(self.cpu_event_data[i]),
                cluster.core_in_tag[i].eq(self.cpu_event_tag[i]),
                cluster.core_in_epoch[i].eq(self.cpu_event_epoch[i]),
                cluster.core_in_seq[i].eq(self.cpu_event_seq[i][:2]),
                cluster.core_in_core_id[i].eq(i),
                cluster.core_in_region_id[i].eq(self.cpu_region_id[i]),
            ]

        m.d.comb += cluster.fill_ready.eq(cfg.enable_forwarding)

        m.d.comb += [
            self.gc_result_valid.eq(cluster.out_valid),
            cluster.out_ready.eq(self.gc_result_ready),
            self.gc_result_data.eq(cluster.out_data),
            self.gc_result_tag.eq(cluster.out_tag),
            self.gc_result_epoch.eq(cluster.out_epoch),
            self.gc_result_seq.eq(cluster.out_seq),
            self.gc_result_merge_domain.eq(cluster.out_domain),
            self.gc_result_status.eq(0),
        ]

    def elaborate(self, platform):
        m = Module()
        cfg = self.config

        if cfg.tile_count == 1 and cfg.lane_per_tile == 1:
            self._wire_tile(m, lane_count=1)
        elif cfg.tile_count == 1 and cfg.lane_per_tile == 2:
            self._wire_tile(m, lane_count=2)
        elif cfg.tile_count > 1:
            self._wire_cluster(m)

        # Power management
        if cfg.enable_clock_gating or cfg.power_policy.value >= 1:
            idle = IdleDetect(timeout=8)
            m.submodules.idle = idle
            has_activity = Signal()
            m.d.comb += has_activity.eq(self.gc_event_valid | self.gc_result_valid | self.gc_enable)
            m.d.comb += idle.active.eq(has_activity)
            if cfg.enable_debug:
                m.d.comb += self.debug_state.eq(Mux(idle.idle, 0, 1))

        if cfg.enable_load_based_enable:
            lbe = LoadBasedEnable(
                tile_count=cfg.tile_count,
                window=8,
                threshold=cfg.metadata_cache_size // 8,
            )
            m.submodules.lbe = lbe

        return m
