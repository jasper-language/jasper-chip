# rtl/jasper_gc_accelerator_queue.py
# P0: CommandQueue + CompletionQueue — valid/ready FIFOs with backpressure.
from amaranth import *
from rtl.jasper_gc_accelerator_config import CmdType, CompletionStatus


class CommandQueue(Elaboratable):
    """N-deep command FIFO with valid/ready handshake.
    Stores: type, correlation_id, epoch, merge_domain, region_base,
    region_size, priority, flags.
    When burst_enable=False (default, v0.1-compatible), rising-edge
    detection on cmd_valid prevents duplicate pushes from a held-valid
    pulse.  When burst_enable=True, the queue accepts one command per
    cycle that cmd_valid & ~full (continuous burst with backpressure)."""
    def __init__(self, depth=8, burst_enable=False):
        self.depth = depth
        self.burst_enable = burst_enable
        self.cmd_valid = Signal(); self.cmd_ready = Signal()
        self.cmd_valid_d = Signal()
        self.cmd_type = Signal(4); self.cmd_correlation_id = Signal(16)
        self.cmd_epoch = Signal(8); self.cmd_merge_domain = Signal(4)
        self.cmd_region_base = Signal(32); self.cmd_region_size = Signal(32)
        self.cmd_priority = Signal(2); self.cmd_flags = Signal(8)

        # Output to scheduler
        self.out_valid = Signal(); self.out_ready = Signal()
        self.out_type = Signal(4); self.out_correlation_id = Signal(16)
        self.out_epoch = Signal(8); self.out_merge_domain = Signal(4)
        self.out_region_base = Signal(32); self.out_region_size = Signal(32)
        self.out_priority = Signal(2); self.out_flags = Signal(8)

        self.busy = Signal(); self.full = Signal(); self.count = Signal(range(depth + 1))

    def elaborate(self, platform):
        m = Module(); D = self.depth
        # FIFO storage
        q_type = Array([Signal(4) for _ in range(D)])
        q_cid = Array([Signal(16) for _ in range(D)])
        q_epoch = Array([Signal(8) for _ in range(D)])
        q_domain = Array([Signal(4) for _ in range(D)])
        q_base = Array([Signal(32) for _ in range(D)])
        q_size = Array([Signal(32) for _ in range(D)])
        q_prio = Array([Signal(2) for _ in range(D)])
        q_flags = Array([Signal(8) for _ in range(D)])
        q_valid = Array([Signal() for _ in range(D)])

        head = Signal(range(D), reset=0); tail = Signal(range(D), reset=0)
        cnt = Signal(range(D + 1), reset=0)

        m.d.comb += [
            self.full.eq(cnt == D), self.count.eq(cnt),
            self.cmd_ready.eq(~self.full),
            self.busy.eq(cnt != 0),
        ]

        m.d.sync += self.cmd_valid_d.eq(self.cmd_valid)

        push = Signal()
        if self.burst_enable:
            m.d.comb += push.eq(self.cmd_valid & ~self.full)
        else:
            m.d.comb += push.eq(self.cmd_valid & ~self.cmd_valid_d & ~self.full)

        pop = Signal()
        m.d.comb += pop.eq(self.out_valid & self.out_ready)

        # Write to tail on push
        with m.If(push):
            m.d.sync += [
                q_type[tail].eq(self.cmd_type),
                q_cid[tail].eq(self.cmd_correlation_id),
                q_epoch[tail].eq(self.cmd_epoch),
                q_domain[tail].eq(self.cmd_merge_domain),
                q_base[tail].eq(self.cmd_region_base),
                q_size[tail].eq(self.cmd_region_size),
                q_prio[tail].eq(self.cmd_priority),
                q_flags[tail].eq(self.cmd_flags),
                q_valid[tail].eq(1),
                tail.eq(Mux(tail == D - 1, 0, tail + 1)),
            ]

        # Read from head (combinational)
        m.d.comb += [
            self.out_valid.eq(cnt != 0),
            self.out_type.eq(q_type[head]),
            self.out_correlation_id.eq(q_cid[head]),
            self.out_epoch.eq(q_epoch[head]),
            self.out_merge_domain.eq(q_domain[head]),
            self.out_region_base.eq(q_base[head]),
            self.out_region_size.eq(q_size[head]),
            self.out_priority.eq(q_prio[head]),
            self.out_flags.eq(q_flags[head]),
        ]

        # Invalid head slot on pop
        with m.If(pop):
            m.d.sync += [
                q_valid[head].eq(0),
                head.eq(Mux(head == D - 1, 0, head + 1)),
            ]

        with m.If(push & ~pop):
            m.d.sync += cnt.eq(cnt + 1)
        with m.Elif(pop & ~push):
            m.d.sync += cnt.eq(cnt - 1)

        return m


class CompletionQueue(Elaboratable):
    """N-deep completion FIFO with valid/ready handshake.
    Stores: status, correlation_id, epoch, merge_domain, stats."""
    def __init__(self, depth=8):
        self.depth = depth
        # Input from engines/scheduler
        self.in_valid = Signal(); self.in_ready = Signal()
        self.in_status = Signal(3); self.in_correlation_id = Signal(16)
        self.in_epoch = Signal(8); self.in_merge_domain = Signal(4)
        self.in_bytes_scanned = Signal(32)
        self.in_objects_scanned = Signal(32)
        self.in_live_objects = Signal(32); self.in_dead_objects = Signal(32)
        self.in_objects_moved = Signal(32); self.in_bytes_moved = Signal(32)
        self.in_metadata_updates = Signal(32)
        self.in_error_code = Signal(8)

        # Output to Core
        self.out_valid = Signal(); self.out_ready = Signal()
        self.out_status = Signal(3); self.out_correlation_id = Signal(16)
        self.out_epoch = Signal(8); self.out_merge_domain = Signal(4)
        self.out_bytes_scanned = Signal(32)
        self.out_objects_scanned = Signal(32)
        self.out_live_objects = Signal(32); self.out_dead_objects = Signal(32)
        self.out_objects_moved = Signal(32); self.out_bytes_moved = Signal(32)
        self.out_metadata_updates = Signal(32)
        self.out_error_code = Signal(8)

        self.busy = Signal(); self.full = Signal(); self.count = Signal(range(depth + 1))

    def elaborate(self, platform):
        m = Module(); D = self.depth
        Q = 11  # number of stored fields

        Arrays = {}
        for name, width in [
            ("status", 3), ("cid", 16), ("epoch", 8), ("domain", 4),
            ("b_scanned", 32), ("o_scanned", 32), ("live", 32), ("dead", 32),
            ("moved", 32), ("b_moved", 32), ("meta_upd", 32), ("err", 8),
        ]:
            Arrays[name] = Array([Signal(width) for _ in range(D)])

        q_valid = Array([Signal() for _ in range(D)])
        head = Signal(range(D), reset=0); tail = Signal(range(D), reset=0)
        cnt = Signal(range(D + 1), reset=0)

        m.d.comb += [
            self.full.eq(cnt == D), self.count.eq(cnt),
            self.in_ready.eq(~self.full),
        ]

        push = Signal()
        m.d.comb += push.eq(self.in_valid & ~self.full)
        pop = Signal()
        m.d.comb += pop.eq(self.out_valid & self.out_ready)

        with m.If(push):
            m.d.sync += [
                Arrays["status"][tail].eq(self.in_status),
                Arrays["cid"][tail].eq(self.in_correlation_id),
                Arrays["epoch"][tail].eq(self.in_epoch),
                Arrays["domain"][tail].eq(self.in_merge_domain),
                Arrays["b_scanned"][tail].eq(self.in_bytes_scanned),
                Arrays["o_scanned"][tail].eq(self.in_objects_scanned),
                Arrays["live"][tail].eq(self.in_live_objects),
                Arrays["dead"][tail].eq(self.in_dead_objects),
                Arrays["moved"][tail].eq(self.in_objects_moved),
                Arrays["b_moved"][tail].eq(self.in_bytes_moved),
                Arrays["meta_upd"][tail].eq(self.in_metadata_updates),
                Arrays["err"][tail].eq(self.in_error_code),
                q_valid[tail].eq(1),
                tail.eq(Mux(tail == D - 1, 0, tail + 1)),
            ]

        m.d.comb += [
            self.out_valid.eq(cnt != 0),
            self.out_status.eq(Arrays["status"][head]),
            self.out_correlation_id.eq(Arrays["cid"][head]),
            self.out_epoch.eq(Arrays["epoch"][head]),
            self.out_merge_domain.eq(Arrays["domain"][head]),
            self.out_bytes_scanned.eq(Arrays["b_scanned"][head]),
            self.out_objects_scanned.eq(Arrays["o_scanned"][head]),
            self.out_live_objects.eq(Arrays["live"][head]),
            self.out_dead_objects.eq(Arrays["dead"][head]),
            self.out_objects_moved.eq(Arrays["moved"][head]),
            self.out_bytes_moved.eq(Arrays["b_moved"][head]),
            self.out_metadata_updates.eq(Arrays["meta_upd"][head]),
            self.out_error_code.eq(Arrays["err"][head]),
            self.busy.eq(cnt != 0),
        ]

        with m.If(pop):
            m.d.sync += [
                q_valid[head].eq(0),
                head.eq(Mux(head == D - 1, 0, head + 1)),
            ]

        with m.If(push & ~pop):
            m.d.sync += cnt.eq(cnt + 1)
        with m.Elif(pop & ~push):
            m.d.sync += cnt.eq(cnt - 1)

        return m
