# rtl/gc_multi_backend_cluster.py
# Full multi-backend cluster: dispatcher → N tiles × 1L/2L → ordered merge.
from amaranth import *
from rtl.gc_backend_tile import BackendTile
from rtl.gc_fabric import HybridDispatch, OrderedGlobalMerge, SkidBuffer
from rtl.jasper_gc_config import DispatchPolicy, BackpressurePolicy


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _dispatch_fabric_code(policy):
    value = _enum_value(policy)
    mapping = {
        DispatchPolicy.NONE.value: 0,
        DispatchPolicy.CORE_AFFINITY.value: 0,
        DispatchPolicy.REGION_AFFINITY.value: 1,
        DispatchPolicy.HASH_LSB.value: 2,
        DispatchPolicy.BACKPRESSURE_AWARE.value: 3,
        DispatchPolicy.HYBRID.value: 4,
        DispatchPolicy.LOAD_AWARE.value: 4,
    }
    return mapping.get(value, 0)


class BackendDispatcher(Elaboratable):
    """Route events to N tiles by addr hash. 1 input → N tile inputs."""
    def __init__(self, tile_count=2, lane_per_tile=1):
        self.tile_count = tile_count
        self.lane_per_tile = lane_per_tile
        # Single input
        self.in_valid = Signal(); self.in_ready = Signal()
        self.in_type = Signal(2); self.in_addr = Signal(32)
        self.in_data = Signal(32); self.in_tag = Signal(8)
        self.in_epoch = Signal(8); self.in_seq = Signal(2)
        # Per-tile outputs (2 lanes each for 2L mode)
        self.out_valid = [Signal() for _ in range(tile_count * lane_per_tile)]
        self.out_ready = [Signal() for _ in range(tile_count * lane_per_tile)]
        self.out_type = [Signal(2) for _ in range(tile_count * lane_per_tile)]
        self.out_addr = [Signal(32) for _ in range(tile_count * lane_per_tile)]
        self.out_data = [Signal(32) for _ in range(tile_count * lane_per_tile)]
        self.out_tag = [Signal(8) for _ in range(tile_count * lane_per_tile)]
        self.out_epoch = [Signal(8) for _ in range(tile_count * lane_per_tile)]
        self.out_seq = [Signal(2) for _ in range(tile_count * lane_per_tile)]
        self.busy = Signal()

    def elaborate(self, platform):
        m = Module(); P = self; TC = P.tile_count; LP = P.lane_per_tile
        total_ports = TC * LP
        tc_bits = (TC - 1).bit_length() if TC > 1 else 0
        lp_bits = (LP - 1).bit_length() if LP > 1 else 0
        port_bits = tc_bits + lp_bits

        port_id = Signal(max(port_bits, 1))
        if port_bits >= 1:
            m.d.comb += port_id.eq(P.in_addr[:port_bits])

        for idx in range(total_ports):
            sel = Signal(); m.d.comb += sel.eq(port_id == idx)
            m.d.comb += [
                P.out_valid[idx].eq(P.in_valid & sel),
                P.out_type[idx].eq(P.in_type),
                P.out_addr[idx].eq(P.in_addr),
                P.out_data[idx].eq(P.in_data),
                P.out_tag[idx].eq(P.in_tag),
                P.out_epoch[idx].eq(P.in_epoch),
                P.out_seq[idx].eq(P.in_seq),
            ]

        in_rdy = Const(0)
        for idx in range(total_ports):
            in_rdy = Mux(port_id == idx, P.out_ready[idx], in_rdy)
        m.d.comb += P.in_ready.eq(in_rdy)
        m.d.comb += P.busy.eq(0)
        return m


class OrderedMerge(Elaboratable):
    """Merge N tile outputs into 1 ordered stream using commit queue."""
    def __init__(self, input_count=2, queue_depth=16):
        self.input_count = input_count
        self.queue_depth = queue_depth
        self.in_valid = [Signal() for _ in range(input_count)]
        self.in_ready = [Signal() for _ in range(input_count)]
        self.in_data = [Signal(32) for _ in range(input_count)]
        self.in_tag = [Signal(8) for _ in range(input_count)]
        self.in_epoch = [Signal(8) for _ in range(input_count)]
        self.in_seq = [Signal(2) for _ in range(input_count)]
        self.in_domain = [Signal(4) for _ in range(input_count)]
        self.out_valid = Signal(); self.out_ready = Signal()
        self.out_data = Signal(32); self.out_tag = Signal(8)
        self.out_epoch = Signal(8); self.out_seq = Signal(2)
        self.out_domain = Signal(4)
        self.busy = Signal()

    def elaborate(self, platform):
        m = Module(); P = self; IC = P.input_count; QD = P.queue_depth

        # Commit queue
        q_data = Array([Signal(32) for _ in range(QD)])
        q_tag = Array([Signal(8) for _ in range(QD)])
        q_epoch = Array([Signal(8) for _ in range(QD)])
        q_seq = Array([Signal(2) for _ in range(QD)])
        q_domain = Array([Signal(4) for _ in range(QD)])
        q_valid = Array([Signal() for _ in range(QD)])
        q_head = Signal(range(QD), reset=0)
        q_tail = Signal(range(QD), reset=0)
        q_count = Signal(range(QD + 1), reset=0)
        q_full = Signal(); q_empty = Signal()
        m.d.comb += [q_full.eq(q_count == QD), q_empty.eq(q_count == 0)]

        # Round-robin-with-skip push selector
        # Scan from rr_start, pick first valid & ~q_full input, skip inactive
        rr_start = Signal(range(IC), reset=0)
        # Build Mux tree for each possible rr_start value
        rr_cases = []
        for sv in range(IC):
            case_sel = Const(0); case_found = Const(0)
            for off in range(IC):
                idx = (sv + off) % IC
                active = P.in_valid[idx] & ~q_full
                case_sel = Mux(~case_found & active, idx, case_sel)
                case_found = case_found | active
            rr_cases.append((case_sel, case_found))

        push_sel = Signal(range(IC))
        any_active = Signal()
        push_sel_expr = Const(0); push_found_expr = Const(0)
        for sv in range(IC):
            push_sel_expr = Mux(rr_start == sv, rr_cases[sv][0], push_sel_expr)
            push_found_expr = Mux(rr_start == sv, rr_cases[sv][1], push_found_expr)
        m.d.comb += [
            push_sel.eq(push_sel_expr),
            any_active.eq(push_found_expr),
        ]

        # Generate per-input push signals and in_ready
        push_signals = []
        for i in range(IC):
            push = Signal()
            m.d.comb += push.eq(P.in_valid[i] & ~q_full & (push_sel == i))
            m.d.comb += P.in_ready[i].eq(push)
            push_signals.append(push)

        any_push = Signal()
        m.d.comb += any_push.eq(any_active & ~q_full)

        # Push data
        for i in range(IC):
            with m.If(push_signals[i]):
                m.d.sync += [
                    q_data[q_tail].eq(P.in_data[i]),
                    q_tag[q_tail].eq(P.in_tag[i]),
                    q_epoch[q_tail].eq(P.in_epoch[i]),
                    q_seq[q_tail].eq(P.in_seq[i]),
                    q_domain[q_tail].eq(P.in_domain[i]),
                    q_valid[q_tail].eq(1),
                    q_tail.eq(Mux(q_tail == QD - 1, 0, q_tail + 1)),
                ]

        # Advance rr_start on successful push
        with m.If(any_push):
            m.d.sync += rr_start.eq(Mux(push_sel == IC - 1, 0, push_sel + 1))

        # Pop
        def fifo_read(arr, hd):
            v = Const(0)
            for i in range(QD):
                v = Mux(hd == i, arr[i], v)
            return v

        head_valid = Signal(); m.d.comb += head_valid.eq(q_valid[q_head])
        m.d.comb += [
            P.out_valid.eq(~q_empty & head_valid),
            P.out_data.eq(Mux(head_valid, q_data[q_head], 0)),
            P.out_tag.eq(Mux(head_valid, q_tag[q_head], 0)),
            P.out_epoch.eq(Mux(head_valid, q_epoch[q_head], 0)),
            P.out_seq.eq(Mux(head_valid, q_seq[q_head], 0)),
            P.out_domain.eq(Mux(head_valid, q_domain[q_head], 0)),
        ]
        pop = Signal(); m.d.comb += pop.eq(P.out_valid & P.out_ready)
        with m.If(pop):
            m.d.sync += [q_valid[q_head].eq(0), q_head.eq(Mux(q_head == QD - 1, 0, q_head + 1))]

        with m.If(any_push & ~pop): m.d.sync += q_count.eq(q_count + 1)
        with m.If(pop & ~any_push): m.d.sync += q_count.eq(q_count - 1)

        m.d.comb += P.busy.eq(~q_empty)
        return m


class GCMultiBackendCluster(Elaboratable):
    """Complete multi-backend cluster: dispatcher → N tiles → ordered merge.

    Parameters:
        tile_count (int): number of backend tiles (power of two)
        lane_per_tile (int): lanes per tile (1 or 2)
    """
    def __init__(self, tile_count=2, lane_per_tile=1, input_count=1,
                 dispatch_policy=0, merge_policy=0,
                 backpressure_policy=0, ordered_merge_queue_depth=8, merge_domain_count=4,
                 metadata_cache_size=1024, metadata_ways=2, metadata_access_granularity=32,
                 metadata_pipeline_depth=8,
                 forwarding_entries=64, forwarding_chase_depth=4,
                 entries_per_bank=2):
        self.tile_count = tile_count
        self.lane_per_tile = lane_per_tile
        self.input_count = input_count
        self.dispatch_policy = _dispatch_fabric_code(dispatch_policy)
        self.merge_policy = _enum_value(merge_policy)
        self.backpressure_policy = _enum_value(backpressure_policy)
        self.ordered_merge_queue_depth = ordered_merge_queue_depth
        self.merge_domain_count = merge_domain_count
        self.metadata_cache_size = metadata_cache_size
        self.metadata_ways = metadata_ways
        self.metadata_access_granularity = metadata_access_granularity
        self.metadata_pipeline_depth = metadata_pipeline_depth
        self.forwarding_entries = forwarding_entries
        self.forwarding_chase_depth = forwarding_chase_depth
        self.entries_per_bank = entries_per_bank
        total_lanes = tile_count * lane_per_tile

        self.in_valid = Signal(); self.in_ready = Signal()
        self.in_type = Signal(2); self.in_addr = Signal(32)
        self.in_data = Signal(32); self.in_tag = Signal(8)
        self.in_epoch = Signal(8); self.in_seq = Signal(2)
        self.core_id = Signal(8)
        self.region_id = Signal(8)

        self.core_in_valid = [Signal() for _ in range(input_count)]
        self.core_in_ready = [Signal() for _ in range(input_count)]
        self.core_in_type = [Signal(2) for _ in range(input_count)]
        self.core_in_addr = [Signal(32) for _ in range(input_count)]
        self.core_in_data = [Signal(32) for _ in range(input_count)]
        self.core_in_tag = [Signal(8) for _ in range(input_count)]
        self.core_in_epoch = [Signal(8) for _ in range(input_count)]
        self.core_in_seq = [Signal(2) for _ in range(input_count)]
        self.core_in_core_id = [Signal(8) for _ in range(input_count)]
        self.core_in_region_id = [Signal(8) for _ in range(input_count)]
        self.flush = Signal(); self.flush_epoch = Signal(8)
        self.current_epoch = Signal(8)

        self.out_valid = Signal(); self.out_ready = Signal()
        self.out_data = Signal(32); self.out_tag = Signal(8)
        self.out_epoch = Signal(8); self.out_seq = Signal(2)
        self.out_domain = Signal(4)
        self.busy = Signal()
        self.fill_ready = Signal(); self.fill_valid = Signal()
        self.fill_addr = Signal(32); self.fill_data = Signal(32)

    def elaborate(self, platform):
        m = Module(); P = self; TC = P.tile_count; LP = P.lane_per_tile; IC = P.input_count
        total_lanes = TC * LP

        m.d.comb += [
            P.core_in_valid[0].eq(P.in_valid),
            P.in_ready.eq(P.core_in_ready[0]),
            P.core_in_type[0].eq(P.in_type),
            P.core_in_addr[0].eq(P.in_addr),
            P.core_in_data[0].eq(P.in_data),
            P.core_in_tag[0].eq(P.in_tag),
            P.core_in_epoch[0].eq(P.in_epoch),
            P.core_in_seq[0].eq(P.in_seq),
            P.core_in_core_id[0].eq(P.core_id),
            P.core_in_region_id[0].eq(P.region_id),
        ]

        # Hierarchical ingress: large CPU-core counts are first collapsed into
        # small ingress groups, then dispatched to backend lanes. This keeps the
        # frontend fabric from generating one full tile dispatcher per CPU core.
        ingress_group_size = 2 if IC > 64 else 16
        use_ingress_groups = IC > 64
        src_valid = []
        src_type = []
        src_addr = []
        src_data = []
        src_tag = []
        src_epoch = []
        src_seq = []
        src_core_id = []
        src_region_id = []
        src_ready = []
        if use_ingress_groups:
            for base in range(0, IC, ingress_group_size):
                group_sources = range(base, min(base + ingress_group_size, IC))
                g_valid = Signal()
                g_type = Signal(2)
                g_addr = Signal(32)
                g_data = Signal(32)
                g_tag = Signal(8)
                g_epoch = Signal(8)
                g_seq = Signal(2)
                g_core_id = Signal(8)
                g_region_id = Signal(8)
                g_ready = Signal()
                downstream_ready = Signal()
                g_valid_r = Signal()
                g_type_r = Signal(2)
                g_addr_r = Signal(32)
                g_data_r = Signal(32)
                g_tag_r = Signal(8)
                g_epoch_r = Signal(8)
                g_seq_r = Signal(2)
                g_core_id_r = Signal(8)
                g_region_id_r = Signal(8)
                taken = Const(0)
                valid_expr = Const(0)
                type_expr = Const(0, 2)
                addr_expr = Const(0, 32)
                data_expr = Const(0, 32)
                tag_expr = Const(0, 8)
                epoch_expr = Const(0, 8)
                seq_expr = Const(0, 2)
                core_expr = Const(0, 8)
                region_expr = Const(0, 8)
                for core in group_sources:
                    grant = Signal()
                    m.d.comb += grant.eq(P.core_in_valid[core] & ~taken)
                    taken = taken | P.core_in_valid[core]
                    valid_expr = valid_expr | grant
                    type_expr = Mux(grant, P.core_in_type[core], type_expr)
                    addr_expr = Mux(grant, P.core_in_addr[core], addr_expr)
                    data_expr = Mux(grant, P.core_in_data[core], data_expr)
                    tag_expr = Mux(grant, P.core_in_tag[core], tag_expr)
                    epoch_expr = Mux(grant, P.core_in_epoch[core], epoch_expr)
                    seq_expr = Mux(grant, P.core_in_seq[core], seq_expr)
                    core_expr = Mux(grant, P.core_in_core_id[core], core_expr)
                    region_expr = Mux(grant, P.core_in_region_id[core], region_expr)
                    m.d.comb += P.core_in_ready[core].eq(grant & g_ready)
                m.d.comb += [
                    g_ready.eq(~g_valid_r | downstream_ready),
                    g_valid.eq(g_valid_r),
                    g_type.eq(g_type_r),
                    g_addr.eq(g_addr_r),
                    g_data.eq(g_data_r),
                    g_tag.eq(g_tag_r),
                    g_epoch.eq(g_epoch_r),
                    g_seq.eq(g_seq_r),
                    g_core_id.eq(g_core_id_r),
                    g_region_id.eq(g_region_id_r),
                ]
                with m.If(g_ready):
                    m.d.sync += [
                        g_valid_r.eq(valid_expr),
                        g_type_r.eq(type_expr),
                        g_addr_r.eq(addr_expr),
                        g_data_r.eq(data_expr),
                        g_tag_r.eq(tag_expr),
                        g_epoch_r.eq(epoch_expr),
                        g_seq_r.eq(seq_expr),
                        g_core_id_r.eq(core_expr),
                        g_region_id_r.eq(region_expr),
                    ]
                src_valid.append(g_valid)
                src_type.append(g_type)
                src_addr.append(g_addr)
                src_data.append(g_data)
                src_tag.append(g_tag)
                src_epoch.append(g_epoch)
                src_seq.append(g_seq)
                src_core_id.append(g_core_id)
                src_region_id.append(g_region_id)
                src_ready.append(downstream_ready)
        else:
            src_valid = P.core_in_valid
            src_type = P.core_in_type
            src_addr = P.core_in_addr
            src_data = P.core_in_data
            src_tag = P.core_in_tag
            src_epoch = P.core_in_epoch
            src_seq = P.core_in_seq
            src_core_id = P.core_in_core_id
            src_region_id = P.core_in_region_id
            src_ready = P.core_in_ready

        source_count = len(src_valid)

        # Dispatcher (HybridDispatch for multi-tile)
        dispatchers = []
        for src in range(source_count):
            disp = HybridDispatch(
                tile_count=TC,
                lane_per_tile=LP,
                fixed_policy=self.dispatch_policy,
            )
            dispatchers.append(disp)
            m.submodules[f"disp_{src}"] = disp
            m.d.comb += [
                disp.dispatch_policy.eq(self.dispatch_policy),
                disp.in_valid.eq(src_valid[src]),
                disp.in_core_id.eq(src_core_id[src]),
                disp.in_region_id.eq(src_region_id[src]),
                disp.in_addr.eq(src_addr[src]),
            ]
            m.d.comb += src_ready[src].eq(disp.in_ready)

        # Tiles
        tiles = [BackendTile(
            lane_count=LP,
            metadata_cache_size=self.metadata_cache_size,
            metadata_ways=self.metadata_ways,
            metadata_access_granularity=self.metadata_access_granularity,
            metadata_pipeline_depth=self.metadata_pipeline_depth,
            forwarding_entries=self.forwarding_entries,
            forwarding_chase_depth=self.forwarding_chase_depth,
            entries_per_bank=self.entries_per_bank,
        ) for _ in range(TC)]
        for i, t in enumerate(tiles):
            m.submodules[f"tile_{i}"] = t

        hierarchical_merge = TC > 16
        if hierarchical_merge:
            merge_group_size = 8
            merge_group_count = (TC + merge_group_size - 1) // merge_group_size
            local_merges = []
            for group in range(merge_group_count):
                base_tile = group * merge_group_size
                local_tile_count = min(merge_group_size, TC - base_tile)
                local_merge = OrderedGlobalMerge(
                    domain_count=self.merge_domain_count,
                    tile_count=local_tile_count,
                    queue_depth=self.ordered_merge_queue_depth,
                    input_domain_map=[
                        (base_tile + i) % self.merge_domain_count
                        for i in range(local_tile_count)
                    ],
                )
                local_merges.append(local_merge)
                m.submodules[f"local_merge_{group}"] = local_merge

            global_merge = OrderedGlobalMerge(
                domain_count=self.merge_domain_count,
                tile_count=merge_group_count,
                queue_depth=self.ordered_merge_queue_depth,
            )
            m.submodules.global_merge = global_merge
        else:
            # Global merge (tile lane outputs -> single stream). Each BackendTile already exposes
            # per-lane outputs, so an extra per-tile merge layer only inflates small profiles.
            global_merge = OrderedGlobalMerge(
                domain_count=self.merge_domain_count,
                tile_count=TC,
                queue_depth=self.ordered_merge_queue_depth,
                input_domain_map=[i % self.merge_domain_count for i in range(TC)],
            )
            m.submodules.global_merge = global_merge

        port_valid = [Signal() for _ in range(total_lanes)]
        port_type = [Signal(2) for _ in range(total_lanes)]
        port_addr = [Signal(32) for _ in range(total_lanes)]
        port_data = [Signal(32) for _ in range(total_lanes)]
        port_tag = [Signal(8) for _ in range(total_lanes)]
        port_epoch = [Signal(8) for _ in range(total_lanes)]
        port_seq = [Signal(2) for _ in range(total_lanes)]
        port_ready = [Signal() for _ in range(total_lanes)]

        if IC == 1:
            src = 0
            for p in range(total_lanes):
                m.d.comb += [
                    dispatchers[src].tile_ready[p].eq(port_ready[p]),
                    port_valid[p].eq(dispatchers[src].tile_valid[p]),
                    port_type[p].eq(P.core_in_type[src]),
                    port_addr[p].eq(P.core_in_addr[src]),
                    port_data[p].eq(P.core_in_data[src]),
                    port_tag[p].eq(P.core_in_tag[src]),
                    port_epoch[p].eq(P.core_in_epoch[src]),
                    port_seq[p].eq(P.core_in_seq[src]),
                ]
        else:
            group_size = 16
            for p in range(total_lanes):
                group_valids = []
                group_types = []
                group_addrs = []
                group_datas = []
                group_tags = []
                group_epochs = []
                group_seqs = []
                for base in range(0, source_count, group_size):
                    group_sources = range(base, min(base + group_size, source_count))
                    taken = Const(0)
                    valid_expr = Const(0)
                    type_expr = Const(0, 2)
                    addr_expr = Const(0, 32)
                    data_expr = Const(0, 32)
                    tag_expr = Const(0, 8)
                    epoch_expr = Const(0, 8)
                    seq_expr = Const(0, 2)
                    for src in group_sources:
                        grant = Signal()
                        m.d.comb += grant.eq(dispatchers[src].tile_valid[p] & ~taken)
                        taken = taken | dispatchers[src].tile_valid[p]
                        # Dispatchers need lane ready visibility for policy decisions, and it must
                        # not be gated by per-source grant for hybrid/backpressure policies.
                        m.d.comb += dispatchers[src].tile_ready[p].eq(port_ready[p])
                        valid_expr = valid_expr | grant
                        type_expr = Mux(grant, src_type[src], type_expr)
                        addr_expr = Mux(grant, src_addr[src], addr_expr)
                        data_expr = Mux(grant, src_data[src], data_expr)
                        tag_expr = Mux(grant, src_tag[src], tag_expr)
                        epoch_expr = Mux(grant, src_epoch[src], epoch_expr)
                        seq_expr = Mux(grant, src_seq[src], seq_expr)

                    g_valid = Signal()
                    g_type = Signal(2)
                    g_addr = Signal(32)
                    g_data = Signal(32)
                    g_tag = Signal(8)
                    g_epoch = Signal(8)
                    g_seq = Signal(2)
                    m.d.comb += [
                        g_valid.eq(valid_expr),
                        g_type.eq(type_expr),
                        g_addr.eq(addr_expr),
                        g_data.eq(data_expr),
                        g_tag.eq(tag_expr),
                        g_epoch.eq(epoch_expr),
                        g_seq.eq(seq_expr),
                    ]
                    group_valids.append(g_valid)
                    group_types.append(g_type)
                    group_addrs.append(g_addr)
                    group_datas.append(g_data)
                    group_tags.append(g_tag)
                    group_epochs.append(g_epoch)
                    group_seqs.append(g_seq)

                valid_expr = Const(0)
                type_expr = Const(0, 2)
                addr_expr = Const(0, 32)
                data_expr = Const(0, 32)
                tag_expr = Const(0, 8)
                epoch_expr = Const(0, 8)
                seq_expr = Const(0, 2)
                group_taken = Const(0)
                for g, g_valid in enumerate(group_valids):
                    group_grant = Signal()
                    m.d.comb += group_grant.eq(g_valid & ~group_taken)
                    group_taken = group_taken | g_valid
                    valid_expr = valid_expr | group_grant
                    type_expr = Mux(group_grant, group_types[g], type_expr)
                    addr_expr = Mux(group_grant, group_addrs[g], addr_expr)
                    data_expr = Mux(group_grant, group_datas[g], data_expr)
                    tag_expr = Mux(group_grant, group_tags[g], tag_expr)
                    epoch_expr = Mux(group_grant, group_epochs[g], epoch_expr)
                    seq_expr = Mux(group_grant, group_seqs[g], seq_expr)
                m.d.comb += [
                    port_valid[p].eq(valid_expr),
                    port_type[p].eq(type_expr),
                    port_addr[p].eq(addr_expr),
                    port_data[p].eq(data_expr),
                    port_tag[p].eq(tag_expr),
                    port_epoch[p].eq(epoch_expr),
                    port_seq[p].eq(seq_expr),
                ]

        for i in range(TC):
            t = tiles[i]
            for lp in range(LP):
                src_idx = i * LP + lp
                lane_ready = t.in0_ready if lp == 0 else t.in1_ready
                m.d.comb += [
                    (t.in0_valid if lp == 0 else t.in1_valid).eq(port_valid[src_idx]),
                    port_ready[src_idx].eq(lane_ready),
                    (t.in0_type if lp == 0 else t.in1_type).eq(port_type[src_idx]),
                    (t.in0_addr if lp == 0 else t.in1_addr).eq(port_addr[src_idx]),
                    (t.in0_data if lp == 0 else t.in1_data).eq(port_data[src_idx]),
                    (t.in0_tag if lp == 0 else t.in1_tag).eq(port_tag[src_idx]),
                    (t.in0_epoch if lp == 0 else t.in1_epoch).eq(port_epoch[src_idx]),
                    (t.in0_seq if lp == 0 else t.in1_seq).eq(port_seq[src_idx]),
                ]
            m.d.comb += [
                t.flush.eq(P.flush), t.flush_epoch.eq(P.flush_epoch),
                t.current_epoch.eq(P.current_epoch),
                t.fill_ready.eq(P.fill_ready), t.fill_data.eq(P.fill_data),
            ]

        # Tile outputs -> merge fabric
        if hierarchical_merge:
            for group, local_merge in enumerate(local_merges):
                base_tile = group * merge_group_size
                local_tile_count = min(merge_group_size, TC - base_tile)
                for local_i in range(local_tile_count):
                    tile_i = base_tile + local_i
                    for lp in range(LP):
                        t_out_valid = tiles[tile_i].out0_valid if lp == 0 else tiles[tile_i].out1_valid
                        t_out_ready = tiles[tile_i].out0_ready if lp == 0 else tiles[tile_i].out1_ready
                        t_out_data = tiles[tile_i].out0_data if lp == 0 else tiles[tile_i].out1_data
                        t_out_tag = tiles[tile_i].out0_tag if lp == 0 else tiles[tile_i].out1_tag
                        t_out_epoch = tiles[tile_i].out0_epoch if lp == 0 else tiles[tile_i].out1_epoch
                        t_out_seq = tiles[tile_i].out0_seq if lp == 0 else tiles[tile_i].out1_seq
                        m.d.comb += [
                            local_merge.in_valid[local_i][lp].eq(t_out_valid),
                            t_out_ready.eq(local_merge.in_ready[local_i][lp]),
                            local_merge.in_data[local_i][lp].eq(t_out_data),
                            local_merge.in_tag[local_i][lp].eq(t_out_tag),
                            local_merge.in_epoch[local_i][lp].eq(t_out_epoch),
                            local_merge.in_seq[local_i][lp].eq(t_out_seq),
                            local_merge.in_domain[local_i][lp].eq(tile_i % self.merge_domain_count),
                        ]
                    for lp in range(LP, 2):
                        m.d.comb += local_merge.in_valid[local_i][lp].eq(0)

                m.d.comb += [
                    global_merge.in_valid[group][0].eq(local_merge.out_valid),
                    local_merge.out_ready.eq(global_merge.in_ready[group][0]),
                    global_merge.in_data[group][0].eq(local_merge.out_data),
                    global_merge.in_tag[group][0].eq(local_merge.out_tag),
                    global_merge.in_epoch[group][0].eq(local_merge.out_epoch),
                    global_merge.in_seq[group][0].eq(local_merge.out_seq),
                    global_merge.in_domain[group][0].eq(local_merge.out_domain),
                    global_merge.in_valid[group][1].eq(0),
                ]
        else:
            for i in range(TC):
                for lp in range(LP):
                    t_out_valid = tiles[i].out0_valid if lp == 0 else tiles[i].out1_valid
                    t_out_ready = tiles[i].out0_ready if lp == 0 else tiles[i].out1_ready
                    t_out_data = tiles[i].out0_data if lp == 0 else tiles[i].out1_data
                    t_out_tag = tiles[i].out0_tag if lp == 0 else tiles[i].out1_tag
                    t_out_epoch = tiles[i].out0_epoch if lp == 0 else tiles[i].out1_epoch
                    t_out_seq = tiles[i].out0_seq if lp == 0 else tiles[i].out1_seq
                    m.d.comb += [
                        global_merge.in_valid[i][lp].eq(t_out_valid),
                        t_out_ready.eq(global_merge.in_ready[i][lp]),
                        global_merge.in_data[i][lp].eq(t_out_data),
                        global_merge.in_tag[i][lp].eq(t_out_tag),
                        global_merge.in_epoch[i][lp].eq(t_out_epoch),
                        global_merge.in_seq[i][lp].eq(t_out_seq),
                        global_merge.in_domain[i][lp].eq(i % self.merge_domain_count),
                    ]
                for lp in range(LP, 2):
                    m.d.comb += global_merge.in_valid[i][lp].eq(0)

        # Global merge → output
        m.d.comb += [
            P.out_valid.eq(global_merge.out_valid),
            global_merge.out_ready.eq(P.out_ready),
            P.out_data.eq(global_merge.out_data),
            P.out_tag.eq(global_merge.out_tag),
            P.out_epoch.eq(global_merge.out_epoch),
            P.out_seq.eq(global_merge.out_seq[:2]),
            P.out_domain.eq(global_merge.out_domain),
            P.busy.eq(sum(t.busy for t in tiles) > 0),
        ]

        # Fill: OR across all tiles
        fill_v = Const(0); fill_a = Const(0)
        for t in tiles:
            fill_v = fill_v | t.fill_valid
            fill_a = Mux(t.fill_valid, t.fill_addr, fill_a)
        m.d.comb += [P.fill_valid.eq(fill_v), P.fill_addr.eq(fill_a)]
        return m
