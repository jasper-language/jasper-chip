# rtl/jasper_gc_sweep_engine.py
# SweepEngine with optional MemoryAccess integration.
from amaranth import *


class SweepEngine(Elaboratable):
    """SweepEngine with optional MemoryAccess.
    use_memory=True: each step issues mem read, waits for response.
    use_memory=False: counting mode (original behavior).
    """
    def __init__(self, step_size=64, dead_ratio=0.3, object_granule=32, use_memory=False):
        self.step_size = step_size
        self.dead_ratio = dead_ratio
        self.object_granule = object_granule
        self.use_memory = use_memory

        self.in_valid = Signal(); self.in_ready = Signal()
        self.in_correlation_id = Signal(16)
        self.in_epoch = Signal(8); self.in_merge_domain = Signal(4)
        self.in_region_base = Signal(32); self.in_region_size = Signal(32)
        self.out_valid = Signal(); self.out_ready = Signal()
        self.out_status = Signal(3)
        self.out_correlation_id = Signal(16)
        self.out_epoch = Signal(8); self.out_merge_domain = Signal(4)
        self.out_bytes_scanned = Signal(32)
        self.out_objects_scanned = Signal(32)
        self.out_live_objects = Signal(32)
        self.out_dead_objects = Signal(32)
        self.out_bytes_moved = Signal(32)
        self.out_objects_moved = Signal(32)
        self.out_metadata_updates = Signal(32)
        self.out_error_code = Signal(8)
        self.busy = Signal()

        # Memory access interface
        self.mem_req_valid = Signal(); self.mem_req_ready = Signal()
        self.mem_req_is_write = Signal()
        self.mem_req_addr = Signal(32); self.mem_req_tag = Signal(16)
        self.mem_rsp_valid = Signal(); self.mem_rsp_ready = Signal()
        self.mem_rsp_tag = Signal(16)

    def elaborate(self, platform):
        m = Module(); SS = self.step_size; GR = self.object_granule
        add_d = 1 if self.dead_ratio > 0.5 else 0

        IDLE = 0; SWP_ISSUE = 1; SWP_WAIT = 2; DONE = 3
        state = Signal(2, init=IDLE)

        sw_base = Signal(32); sw_sz = Signal(32); sw_cur = Signal(32)
        sw_cid = Signal(16); sw_ep = Signal(8); sw_dm = Signal(4)
        sw_ob = Signal(32); sw_dd = Signal(32); sw_mu = Signal(32)
        sw_stp = Signal(32)

        r_bs = Signal(32); r_ob = Signal(32); r_dd = Signal(32)
        r_mu = Signal(32); r_rc = Signal(32)

        m.d.comb += [self.in_ready.eq(state == IDLE), self.busy.eq(state != IDLE)]
        m.d.comb += self.mem_req_is_write.eq(0)

        # IDLE → SWP_ISSUE
        with m.If((state == IDLE) & self.in_valid & self.in_ready):
            m.d.sync += [
                state.eq(SWP_ISSUE),
                sw_base.eq(self.in_region_base), sw_sz.eq(self.in_region_size),
                sw_cur.eq(0),
                sw_cid.eq(self.in_correlation_id),
                sw_ep.eq(self.in_epoch), sw_dm.eq(self.in_merge_domain),
                sw_ob.eq(0), sw_dd.eq(0), sw_mu.eq(0), sw_stp.eq(0),
            ]

        # SWP_ISSUE
        with m.If(state == SWP_ISSUE):
            rem = Signal(32); stp = Signal(32)
            m.d.comb += [rem.eq(sw_sz - sw_cur), stp.eq(Mux(rem > SS, SS, rem))]
            if self.use_memory:
                m.d.comb += [
                    self.mem_req_valid.eq(1),
                    self.mem_req_addr.eq(sw_base + sw_cur),
                ]
                with m.If(self.mem_req_ready):
                    m.d.sync += [state.eq(SWP_WAIT), sw_stp.eq(stp)]
            else:
                m.d.sync += [sw_cur.eq(sw_cur + stp), sw_stp.eq(stp)]
                with m.If(stp > 0):
                    m.d.sync += [sw_ob.eq(sw_ob + 1), sw_dd.eq(sw_dd + add_d), sw_mu.eq(sw_mu + 1)]
                with m.If(sw_cur + stp >= sw_sz):
                    m.d.sync += [
                        r_bs.eq(sw_cur + stp), r_ob.eq(sw_ob + Mux(stp > 0, 1, 0)),
                        r_dd.eq(sw_dd + Mux(stp > 0, add_d, 0)),
                        r_mu.eq(sw_mu + Mux(stp > 0, 1, 0)),
                        r_rc.eq((sw_dd + Mux(stp > 0, add_d, 0)) * GR),
                        state.eq(DONE),
                    ]
                with m.Else():
                    m.d.sync += state.eq(SWP_ISSUE)

        # SWP_WAIT (memory mode only)
        if self.use_memory:
            with m.If(state == SWP_WAIT):
                m.d.comb += self.mem_rsp_ready.eq(1)
                with m.If(self.mem_rsp_valid):
                    m.d.sync += sw_cur.eq(sw_cur + sw_stp)
                    with m.If(sw_stp > 0):
                        m.d.sync += [sw_ob.eq(sw_ob + 1), sw_dd.eq(sw_dd + add_d), sw_mu.eq(sw_mu + 1)]
                    with m.If(sw_cur + sw_stp >= sw_sz):
                        m.d.sync += [
                            r_bs.eq(sw_cur + sw_stp), r_ob.eq(sw_ob + Mux(sw_stp > 0, 1, 0)),
                            r_dd.eq(sw_dd + Mux(sw_stp > 0, add_d, 0)),
                            r_mu.eq(sw_mu + Mux(sw_stp > 0, 1, 0)),
                            r_rc.eq((sw_dd + Mux(sw_stp > 0, add_d, 0)) * GR),
                            state.eq(DONE),
                        ]
                    with m.Else():
                        m.d.sync += state.eq(SWP_ISSUE)

        # DONE
        m.d.comb += [
            self.out_valid.eq(state == DONE), self.out_status.eq(0),
            self.out_correlation_id.eq(sw_cid),
            self.out_epoch.eq(sw_ep), self.out_merge_domain.eq(sw_dm),
            self.out_bytes_scanned.eq(r_bs), self.out_objects_scanned.eq(r_ob),
            self.out_live_objects.eq(r_ob - r_dd), self.out_dead_objects.eq(r_dd),
            self.out_bytes_moved.eq(r_rc), self.out_objects_moved.eq(r_dd),
            self.out_metadata_updates.eq(r_mu), self.out_error_code.eq(0),
        ]
        with m.If((state == DONE) & self.out_ready):
            m.d.sync += state.eq(IDLE)
        return m
