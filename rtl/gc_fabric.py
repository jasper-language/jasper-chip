# rtl/gc_fabric.py
# Multi-backend fabric: dispatch, ordered merge, skid buffer, clock gating.
from amaranth import *
from amaranth.lib.fifo import SyncFIFO


class SkidBuffer(Elaboratable):
    """Per-tile skid buffer: absorbs bursts when output is blocked.
    Depth 2: one holding, one in-flight. No data loss."""
    def __init__(self, data_width=32, tag_width=8):
        self.in_valid = Signal(); self.in_ready = Signal()
        self.in_data = Signal(data_width); self.in_tag = Signal(tag_width)
        self.in_epoch = Signal(8); self.in_seq = Signal(8)
        self.in_domain = Signal(4)
        self.out_valid = Signal(); self.out_ready = Signal()
        self.out_data = Signal(data_width); self.out_tag = Signal(tag_width)
        self.out_epoch = Signal(8); self.out_seq = Signal(8)
        self.out_domain = Signal(4)
        self.busy = Signal()

    def elaborate(self, platform):
        m = Module()
        buf_valid = Signal(); buf_data = Signal(32); buf_tag = Signal(8)
        buf_epoch = Signal(8); buf_seq = Signal(8); buf_domain = Signal(4)
        pass_valid = Signal()

        # Combinational passthrough: input -> output when buffer empty
        m.d.comb += [
            pass_valid.eq(self.in_valid & ~buf_valid),
            self.in_ready.eq(~buf_valid | (buf_valid & self.out_ready)),
            self.out_valid.eq(pass_valid | buf_valid),
            self.out_data.eq(Mux(buf_valid, buf_data, self.in_data)),
            self.out_tag.eq(Mux(buf_valid, buf_tag, self.in_tag)),
            self.out_epoch.eq(Mux(buf_valid, buf_epoch, self.in_epoch)),
            self.out_seq.eq(Mux(buf_valid, buf_seq, self.in_seq)),
            self.out_domain.eq(Mux(buf_valid, buf_domain, self.in_domain)),
            self.busy.eq(buf_valid),
        ]

        # Push to buffer: when in_valid and in_ready but output blocked
        absorb = Signal()
        m.d.comb += absorb.eq(self.in_valid & self.in_ready & ~self.out_ready)
        with m.If(absorb):
            m.d.sync += [
                buf_valid.eq(1),
                buf_data.eq(self.in_data),
                buf_tag.eq(self.in_tag),
                buf_epoch.eq(self.in_epoch),
                buf_seq.eq(self.in_seq),
                buf_domain.eq(self.in_domain),
            ]
        # Pop from buffer: when buffer valid and output accepts
        with m.Elif(buf_valid & self.out_ready):
            m.d.sync += buf_valid.eq(0)
        return m


class OrderedGlobalMerge(Elaboratable):
    """Ordered global merge with per-domain queues.

    Each merge_domain has its own FIFO (depth 8).
    Tiles push results to domain FIFOs.
    Merge pops from domain FIFOs in round-robin order starting from rr_start.
    Same domain: FIFO preserves order.
    Cross domain: independent, no ordering constraint.
    """
    def __init__(self, domain_count=4, tile_count=2, queue_depth=8, input_domain_map=None):
        self.domain_count = domain_count
        self.tile_count = tile_count
        self.queue_depth = queue_depth
        self.input_domain_map = input_domain_map
        # Tile inputs: tile_count x 2 outputs each
        self.in_valid = [[Signal() for _ in range(2)] for _ in range(tile_count)]
        self.in_ready = [[Signal() for _ in range(2)] for _ in range(tile_count)]
        self.in_data = [[Signal(32) for _ in range(2)] for _ in range(tile_count)]
        self.in_tag = [[Signal(8) for _ in range(2)] for _ in range(tile_count)]
        self.in_epoch = [[Signal(8) for _ in range(2)] for _ in range(tile_count)]
        self.in_seq = [[Signal(8) for _ in range(2)] for _ in range(tile_count)]
        self.in_domain = [[Signal(4) for _ in range(2)] for _ in range(tile_count)]
        # Single output
        self.out_valid = Signal(); self.out_ready = Signal()
        self.out_data = Signal(32); self.out_tag = Signal(8)
        self.out_epoch = Signal(8); self.out_seq = Signal(8)
        self.out_domain = Signal(4)
        self.busy = Signal()

    def elaborate(self, platform):
        m = Module(); P = self; DC = P.domain_count; TC = P.tile_count; QD = P.queue_depth

        payload_width = 32 + 8 + 8 + 8
        fifos = []
        for d in range(DC):
            fifo = SyncFIFO(width=payload_width, depth=QD)
            fifos.append(fifo)
            m.submodules[f"domain_fifo_{d}"] = fifo

        ready_exprs = [[Const(0) for _ in range(2)] for _ in range(TC)]

        # Each domain accepts at most one matching input per cycle. Cluster users can provide a
        # static tile->domain map; that avoids large dynamic compare trees for 8+ tile profiles.
        for d in range(DC):
            selected = Const(0)
            selected_data = Const(0, 32)
            selected_tag = Const(0, 8)
            selected_epoch = Const(0, 8)
            selected_seq = Const(0, 8)
            found = Const(0)
            for t in range(TC):
                if P.input_domain_map is not None and P.input_domain_map[t] != d:
                    continue
                for p in range(2):
                    if P.input_domain_map is None:
                        match = P.in_valid[t][p] & (P.in_domain[t][p] == d) & ~found
                    else:
                        match = P.in_valid[t][p] & ~found
                    selected = selected | match
                    selected_data = Mux(match, P.in_data[t][p], selected_data)
                    selected_tag = Mux(match, P.in_tag[t][p], selected_tag)
                    selected_epoch = Mux(match, P.in_epoch[t][p], selected_epoch)
                    selected_seq = Mux(match, P.in_seq[t][p], selected_seq)
                    ready_exprs[t][p] = ready_exprs[t][p] | (match & fifos[d].w_rdy)
                    found = found | match

            m.d.comb += [
                fifos[d].w_en.eq(selected & fifos[d].w_rdy),
                fifos[d].w_data.eq(Cat(selected_data, selected_tag, selected_epoch, selected_seq)),
            ]

        for t in range(TC):
            for p in range(2):
                m.d.comb += P.in_ready[t][p].eq(ready_exprs[t][p])

        rr_start = Signal(range(DC), reset=0)

        # Build round-robin Mux tree over domains. FIFO storage is inside SyncFIFOBuffered, so
        # elaboration cost scales with domain/tile count rather than queue depth.
        rr_cases = []
        for sv in range(DC):
            rr_sel_data = Const(0); rr_sel_tag = Const(0)
            rr_sel_epoch = Const(0); rr_sel_seq = Const(0)
            rr_sel_domain = Const(0); rr_prev_found = Const(0)
            for offset in range(DC):
                d = (sv + offset) % DC
                ok = fifos[d].r_rdy
                fifo_data = fifos[d].r_data
                d_data = fifo_data[:32]
                d_tag = fifo_data[32:40]
                d_epoch = fifo_data[40:48]
                d_seq = fifo_data[48:56]
                rr_sel_data = Mux(ok & ~rr_prev_found, d_data, rr_sel_data)
                rr_sel_tag = Mux(ok & ~rr_prev_found, d_tag, rr_sel_tag)
                rr_sel_epoch = Mux(ok & ~rr_prev_found, d_epoch, rr_sel_epoch)
                rr_sel_seq = Mux(ok & ~rr_prev_found, d_seq, rr_sel_seq)
                rr_sel_domain = Mux(ok & ~rr_prev_found, d, rr_sel_domain)
                rr_prev_found = rr_prev_found | ok
            rr_cases.append((rr_sel_data, rr_sel_tag, rr_sel_epoch, rr_sel_seq, rr_sel_domain, rr_prev_found))

        sel_data_expr = Const(0); sel_tag_expr = Const(0)
        sel_epoch_expr = Const(0); sel_seq_expr = Const(0)
        sel_domain_expr = Const(0); prev_found_expr = Const(0)
        for sv in range(DC):
            c = rr_cases[sv]
            match_sv = rr_start == sv
            sel_data_expr = Mux(match_sv, c[0], sel_data_expr)
            sel_tag_expr = Mux(match_sv, c[1], sel_tag_expr)
            sel_epoch_expr = Mux(match_sv, c[2], sel_epoch_expr)
            sel_seq_expr = Mux(match_sv, c[3], sel_seq_expr)
            sel_domain_expr = Mux(match_sv, c[4], sel_domain_expr)
            prev_found_expr = Mux(match_sv, c[5], prev_found_expr)

        sel_domain = Signal(4)
        m.d.comb += [
            P.out_valid.eq(prev_found_expr),
            P.out_data.eq(sel_data_expr),
            P.out_tag.eq(sel_tag_expr),
            P.out_epoch.eq(sel_epoch_expr),
            P.out_seq.eq(sel_seq_expr),
            sel_domain.eq(sel_domain_expr),
            P.out_domain.eq(sel_domain),
        ]
        pop = Signal()
        m.d.comb += pop.eq(P.out_valid & P.out_ready)

        # Pop from the selected domain
        for d in range(DC):
            is_sel = Signal(); m.d.comb += is_sel.eq(sel_domain == d)
            m.d.comb += fifos[d].r_en.eq(pop & is_sel)

        # Update rr_start on pop
        with m.If(pop):
            m.d.sync += rr_start.eq(Mux(sel_domain == DC - 1, 0, sel_domain + 1))

        busy_expr = Const(0)
        for d in range(DC):
            busy_expr = busy_expr | fifos[d].r_rdy
        m.d.comb += P.busy.eq(busy_expr)
        return m


class HybridDispatch(Elaboratable):
    """Dispatch: core_affinity + region_affinity + backpressure_aware + hybrid.

    Select tile by core_id, region_id, hash, backpressure-aware, or hybrid.
    """
    def __init__(self, tile_count=2, lane_per_tile=2, fixed_policy=None):
        self.tile_count = tile_count
        self.lane_per_tile = lane_per_tile
        self.fixed_policy = fixed_policy
        self.in_valid = Signal(); self.in_ready = Signal()
        self.in_core_id = Signal(8); self.in_region_id = Signal(8)
        self.in_addr = Signal(32)
        self.tile_ready = [Signal() for _ in range(tile_count * lane_per_tile)]
        self.tile_valid = [Signal() for _ in range(tile_count * lane_per_tile)]
        self.tile_addr = [Signal(32) for _ in range(tile_count * lane_per_tile)]
        self.dispatch_policy = Signal(3)  # 0=core, 1=region, 2=hash, 3=backpressure, 4=hybrid
        self.busy = Signal()

    def elaborate(self, platform):
        m = Module(); P = self; TC = P.tile_count; LP = P.lane_per_tile
        total_ports = TC * LP
        tc_bits = (TC - 1).bit_length() if TC > 1 else 0
        lp_bits = (LP - 1).bit_length() if LP > 1 else 0

        # Core affinity: tile = core_id % TC
        core_tile = Signal(tc_bits if tc_bits >= 1 else 1)
        if tc_bits >= 1:
            m.d.comb += core_tile.eq(P.in_core_id[:tc_bits])

        # Region affinity: tile = region_id % TC
        region_tile = Signal(tc_bits if tc_bits >= 1 else 1)
        if tc_bits >= 1:
            m.d.comb += region_tile.eq(P.in_region_id[:tc_bits])

        # Hash: tile = addr % TC
        hash_tile = Signal(tc_bits if tc_bits >= 1 else 1)
        if tc_bits >= 1:
            m.d.comb += hash_tile.eq(P.in_addr[:tc_bits])

        # Backpressure-aware (policy 3): iterate tiles from hash_tile, pick first ready.
        # Omit this logic for fixed static policies; otherwise tile_ready can become part of
        # selected_tile and create a ready->data combinational cycle in large fabrics.
        bp_sel_expr = Const(0)
        needs_ready_policy = self.fixed_policy is None or self.fixed_policy >= 3
        if tc_bits >= 1 and needs_ready_policy:
            bp_hash_cases = []
            for hv in range(TC):
                case_mux = Const(0)
                case_found = Const(0)
                for off in range(TC):
                    t_idx = (hv + off) % TC
                    r = P.tile_ready[t_idx * LP]
                    case_mux = Mux(~case_found & r, t_idx, case_mux)
                    case_found = case_found | r
                case_mux = Mux(case_found, case_mux, hv)
                bp_hash_cases.append(case_mux)
            for hv in range(TC):
                bp_sel_expr = Mux(hash_tile == hv, bp_hash_cases[hv], bp_sel_expr)

        # Hybrid (policy 4): try core_tile first, fallback to first ready tile
        hybrid_sel_expr = Const(0)
        if tc_bits >= 1 and needs_ready_policy:
            hybrid_cases = []
            for hv in range(TC):
                h_core_ready = P.tile_ready[hv * LP]
                h_fallback = Const(0)
                h_found = Const(0)
                for off in range(TC):
                    t_idx = (hv + off) % TC
                    r = P.tile_ready[t_idx * LP]
                    h_fallback = Mux(~h_found & r, t_idx, h_fallback)
                    h_found = h_found | r
                h_sel = Mux(h_core_ready, hv, h_fallback)
                hybrid_cases.append(h_sel)
            for hv in range(TC):
                hybrid_sel_expr = Mux(core_tile == hv, hybrid_cases[hv], hybrid_sel_expr)

        # Select tile based on policy
        selected_tile = Signal(tc_bits if tc_bits >= 1 else 1)
        if self.fixed_policy == 0:
            m.d.comb += selected_tile.eq(core_tile)
        elif self.fixed_policy == 1:
            m.d.comb += selected_tile.eq(region_tile)
        elif self.fixed_policy == 2:
            m.d.comb += selected_tile.eq(hash_tile)
        elif self.fixed_policy == 3:
            m.d.comb += selected_tile.eq(bp_sel_expr)
        elif self.fixed_policy == 4:
            m.d.comb += selected_tile.eq(hybrid_sel_expr)
        else:
            m.d.comb += selected_tile.eq(
                Mux(P.dispatch_policy == 0, core_tile,
                Mux(P.dispatch_policy == 1, region_tile,
                Mux(P.dispatch_policy == 2, hash_tile,
                Mux(P.dispatch_policy == 3, bp_sel_expr,
                Mux(P.dispatch_policy == 4, hybrid_sel_expr, 0))))))

        # Select lane within tile
        lane_in = Signal(lp_bits if lp_bits >= 1 else 1)
        if lp_bits >= 1:
            m.d.comb += lane_in.eq(P.in_addr[tc_bits:tc_bits + lp_bits])

        # Route to selected tile/lane
        in_rdy = Const(0)
        for i in range(TC):
            for lp in range(LP):
                sel = Signal()
                m.d.comb += sel.eq(selected_tile == i)
                if LP >= 2:
                    lane_sel = Signal()
                    m.d.comb += lane_sel.eq(lane_in == lp)
                    m.d.comb += P.tile_valid[i*2+lp].eq(P.in_valid & sel & lane_sel)
                    in_rdy = in_rdy | (sel & lane_sel & P.tile_ready[i*2+lp])
                else:
                    m.d.comb += P.tile_valid[i*LP+lp].eq(P.in_valid & sel)
                    in_rdy = in_rdy | (sel & P.tile_ready[i*LP+lp])
                m.d.comb += P.tile_addr[i*LP+lp].eq(P.in_addr)
        m.d.comb += P.in_ready.eq(in_rdy)
        m.d.comb += P.busy.eq(0)
        # Dummy sync for clock domain
        dummy = Signal(); m.d.sync += dummy.eq(dummy)
        return m


class LoadBasedEnable(Elaboratable):
    """Monitors per-tile backpressure, enables tiles based on load.
    When load < threshold, reduces active tile count for power saving.
    """
    def __init__(self, tile_count=2, window=8, threshold=3):
        self.tile_ready = [Signal() for _ in range(tile_count)]
        self.tile_active = [Signal() for _ in range(tile_count)]
        self.tile_load = [Signal(range(window+1)) for _ in range(tile_count)]
        self.window = window; self.threshold = threshold
        self.use_external_load = Signal()  # 0 = use counter, 1 = use external qdepth
        self.tile_queue_depth = [Signal(range(9)) for _ in range(tile_count)]  # 0..8

    def elaborate(self, platform):
        m = Module()
        for t in range(len(self.tile_ready)):
            cnt = Signal(range(self.window + 1), reset=0)
            with m.If(~self.tile_ready[t]):
                with m.If(cnt < self.window):
                    m.d.sync += cnt.eq(cnt + 1)
            with m.Else():
                with m.If(cnt > 0):
                    m.d.sync += cnt.eq(cnt - 1)
            load_src = Signal(range(self.window + 1))
            m.d.comb += load_src.eq(
                Mux(self.use_external_load,
                    Mux(self.tile_queue_depth[t] > self.window, self.window, self.tile_queue_depth[t]),
                    cnt))
            m.d.comb += [
                self.tile_load[t].eq(load_src),
                self.tile_active[t].eq(load_src < self.threshold),
            ]
        return m


class ClockGate(Elaboratable):
    """Behavioral clock gate: passthrough when enable=1, hold when enable=0."""
    def __init__(self):
        self.enable = Signal(); self.data_in = Signal(32)
        self.data_out = Signal(32)

    def elaborate(self, platform):
        m = Module()
        with m.If(self.enable):
            m.d.sync += self.data_out.eq(self.data_in)
        return m


class IdleDetect(Elaboratable):
    """Clock gating idle detection: asserts idle when no activity for N cycles."""
    def __init__(self, timeout=4):
        self.active = Signal()  # pulsed on any activity
        self.idle = Signal()    # asserted after timeout cycles of inactivity
        self.timeout = timeout

    def elaborate(self, platform):
        m = Module()
        cnt = Signal(range(self.timeout + 1), reset=self.timeout)
        with m.If(self.active):
            m.d.sync += cnt.eq(0)
        with m.Elif(cnt < self.timeout):
            m.d.sync += cnt.eq(cnt + 1)
        m.d.comb += self.idle.eq(cnt >= self.timeout)
        return m


class FabricCoordinator(Elaboratable):
    """Coordinates IdleDetect -> ClockGate per tile.
    IdleDetect.idle drives ClockGate.enable inverted:
    idle=0 (active) -> enable=1, idle=1 (idle) -> enable=0.
    """
    def __init__(self, tile_count=2):
        self.tile_active = [Signal() for _ in range(tile_count)]
        self.tile_idle = [Signal() for _ in range(tile_count)]
        self.clock_enable = [Signal() for _ in range(tile_count)]

    def elaborate(self, platform):
        m = Module()
        for t in range(len(self.tile_active)):
            m.d.comb += self.clock_enable[t].eq(self.tile_active[t] | ~self.tile_idle[t])
        return m
