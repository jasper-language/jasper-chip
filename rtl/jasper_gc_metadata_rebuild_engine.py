# rtl/jasper_gc_metadata_rebuild_engine.py
# MRE with optional MemoryAccess integration.
from amaranth import *


class MetadataRebuildEngine(Elaboratable):
    def __init__(self, step_size=64, metadata_granule=32, object_granule=32, use_memory=False):
        self.step_size = step_size
        self.metadata_granule = metadata_granule
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
        self.out_metadata_updates = Signal(32)
        self.out_error_code = Signal(8)
        self.busy = Signal()

        # Memory interface
        self.mem_req_valid = Signal(); self.mem_req_ready = Signal()
        self.mem_req_is_write = Signal()
        self.mem_req_addr = Signal(32); self.mem_req_tag = Signal(16)
        self.mem_rsp_valid = Signal(); self.mem_rsp_ready = Signal()
        self.mem_rsp_tag = Signal(16)

    def elaborate(self, platform):
        m = Module(); SS = self.step_size; MG = self.metadata_granule

        IDLE = 0; ISSUE = 1; WAIT = 2; DONE = 3
        state = Signal(2, init=IDLE)

        rb_base = Signal(32); rb_sz = Signal(32); rb_cur = Signal(32)
        rb_cid = Signal(16); rb_ep = Signal(8); rb_dm = Signal(4)
        rb_ob = Signal(32); rb_mu = Signal(32); rb_stp = Signal(32)

        r_bs = Signal(32); r_ob = Signal(32); r_mu = Signal(32)

        m.d.comb += [self.in_ready.eq(state == IDLE), self.busy.eq(state != IDLE)]
        m.d.comb += self.mem_req_is_write.eq(0)

        # IDLE → ISSUE
        with m.If((state == IDLE) & self.in_valid & self.in_ready):
            m.d.sync += [
                state.eq(ISSUE),
                rb_base.eq(self.in_region_base), rb_sz.eq(self.in_region_size),
                rb_cur.eq(0),
                rb_cid.eq(self.in_correlation_id),
                rb_ep.eq(self.in_epoch), rb_dm.eq(self.in_merge_domain),
                rb_ob.eq(0), rb_mu.eq(0), rb_stp.eq(0),
            ]

        # ISSUE
        with m.If(state == ISSUE):
            rem = Signal(32); stp = Signal(32)
            m.d.comb += [rem.eq(rb_sz - rb_cur), stp.eq(Mux(rem > SS, SS, rem))]
            if self.use_memory:
                m.d.comb += [self.mem_req_valid.eq(1), self.mem_req_addr.eq(rb_base + rb_cur)]
                with m.If(self.mem_req_ready):
                    m.d.sync += [state.eq(WAIT), rb_stp.eq(stp)]
            else:
                m.d.sync += [rb_cur.eq(rb_cur + stp), rb_stp.eq(stp)]
                with m.If(stp > 0):
                    m.d.sync += [rb_ob.eq(rb_ob + 1), rb_mu.eq(rb_mu + (SS // MG if MG > 0 else 1))]
                with m.If(rb_cur + stp >= rb_sz):
                    m.d.sync += [
                        r_bs.eq(rb_cur + stp),
                        r_ob.eq(rb_ob + Mux(stp > 0, 1, 0)),
                        r_mu.eq(rb_mu + Mux(stp > 0, SS // MG if MG > 0 else 1, 0)),
                        state.eq(DONE),
                    ]
                with m.Else():
                    m.d.sync += state.eq(ISSUE)

        # WAIT (memory mode only)
        if self.use_memory:
            with m.If(state == WAIT):
                m.d.comb += self.mem_rsp_ready.eq(1)
                with m.If(self.mem_rsp_valid):
                    m.d.sync += rb_cur.eq(rb_cur + rb_stp)
                    with m.If(rb_stp > 0):
                        m.d.sync += [rb_ob.eq(rb_ob + 1), rb_mu.eq(rb_mu + (SS // MG if MG > 0 else 1))]
                    with m.If(rb_cur + rb_stp >= rb_sz):
                        m.d.sync += [
                            r_bs.eq(rb_cur + rb_stp),
                            r_ob.eq(rb_ob + Mux(rb_stp > 0, 1, 0)),
                            r_mu.eq(rb_mu + Mux(rb_stp > 0, SS // MG if MG > 0 else 1, 0)),
                            state.eq(DONE),
                        ]
                    with m.Else():
                        m.d.sync += state.eq(ISSUE)

        # DONE
        m.d.comb += [
            self.out_valid.eq(state == DONE), self.out_status.eq(0),
            self.out_correlation_id.eq(rb_cid),
            self.out_epoch.eq(rb_ep), self.out_merge_domain.eq(rb_dm),
            self.out_bytes_scanned.eq(r_bs), self.out_objects_scanned.eq(r_ob),
            self.out_metadata_updates.eq(r_mu), self.out_error_code.eq(0),
        ]
        with m.If((state == DONE) & self.out_ready):
            m.d.sync += state.eq(IDLE)
        return m
