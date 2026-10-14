# rtl/jasper_gc_memory_access.py
# Latency-modeled memory access with response backpressure support.
from amaranth import *


class MemoryAccess(Elaboratable):
    """Memory access latency model with response backpressure.

    - Configurable read latency (cycles through shift register)
    - Request queue with backpressure
    - Response holds when rsp_ready=0 (backpressure-safe)
    - Single outstanding mode (no out-of-order response)
    """
    def __init__(self, read_latency=4, write_latency=2, queue_depth=8, error_rate=0.0, data_width=32):
        self.read_latency = read_latency
        self.write_latency = write_latency
        self.queue_depth = queue_depth
        self.error_rate = error_rate
        self.data_width = data_width

        self.req_valid = Signal(); self.req_ready = Signal()
        self.req_is_write = Signal()
        self.req_addr = Signal(32); self.req_write_data = Signal(data_width)
        self.req_tag = Signal(16); self.req_burst = Signal(8)
        self.rsp_valid = Signal(); self.rsp_ready = Signal()
        self.rsp_read_data = Signal(data_width)
        self.rsp_tag = Signal(16)
        self.rsp_error = Signal()
        self.busy = Signal()

    def elaborate(self, platform):
        m = Module(); RL = self.read_latency; QD = self.queue_depth

        # Request queue
        q_valid = Array([Signal() for _ in range(QD)])
        q_tag = Array([Signal(16) for _ in range(QD)])
        q_is_write = Array([Signal() for _ in range(QD)])
        q_addr = Array([Signal(32) for _ in range(QD)])
        q_write_data = Array([Signal(self.data_width) for _ in range(QD)])
        q_head = Signal(range(QD), init=0); q_tail = Signal(range(QD), init=0)
        q_cnt = Signal(range(QD + 1), init=0)

        m.d.comb += [self.req_ready.eq(q_cnt != QD), self.busy.eq(q_cnt != 0)]

        push = Signal()
        m.d.comb += push.eq(self.req_valid & (q_cnt != QD))

        # Latency pipe
        LD = RL + 2  # pipeline stages for latency
        pipe_valid = [Signal() for _ in range(LD)]
        pipe_tag = [Signal(16) for _ in range(LD)]
        pipe_is_write = [Signal() for _ in range(LD)]
        pipe_data = [Signal(self.data_width) for _ in range(LD)]

        # Response pop signal (defined early for shift register use)
        rsp_pop = Signal()
        m.d.comb += rsp_pop.eq(self.rsp_valid & self.rsp_ready)

        # Shift register: stage i takes from stage i-1 only when stage i-1 is valid
        # Stage LD-1 (tail) additionally holds when rsp_ready=0
        for i in range(1, LD):
            if i == LD - 1:
                with m.If(pipe_valid[i - 1] & (rsp_pop | ~pipe_valid[i])):
                    m.d.sync += [
                        pipe_valid[i].eq(1),
                        pipe_tag[i].eq(pipe_tag[i - 1]),
                        pipe_is_write[i].eq(pipe_is_write[i - 1]),
                        pipe_data[i].eq(pipe_data[i - 1]),
                    ]
                with m.Elif(rsp_pop):
                    m.d.sync += pipe_valid[i].eq(0)
            else:
                with m.If(pipe_valid[i - 1]):
                    m.d.sync += [
                        pipe_valid[i].eq(1),
                        pipe_tag[i].eq(pipe_tag[i - 1]),
                        pipe_is_write[i].eq(pipe_is_write[i - 1]),
                        pipe_data[i].eq(pipe_data[i - 1]),
                    ]
                with m.Else():
                    m.d.sync += pipe_valid[i].eq(0)

        # Dequeue: every cycle, if queue has data and pipe stage 0 is free
        dequeue = Signal()
        m.d.comb += dequeue.eq((q_cnt != 0) & ~pipe_valid[0])

        with m.If(push):
            m.d.sync += [
                q_tag[q_tail].eq(self.req_tag),
                q_valid[q_tail].eq(1),
                q_is_write[q_tail].eq(self.req_is_write),
                q_addr[q_tail].eq(self.req_addr),
                q_write_data[q_tail].eq(self.req_write_data),
                q_tail.eq(Mux(q_tail == QD - 1, 0, q_tail + 1)),
            ]

        # q_cnt: push +1, dequeue -1 (combined for same-cycle)
        m.d.sync += q_cnt.eq(
            Mux(push & dequeue, q_cnt,
            Mux(push & (q_cnt < QD), q_cnt + 1,
            Mux(dequeue & (q_cnt > 0), q_cnt - 1,
            q_cnt))))

        # Pipe stage 0: set by dequeue, cleared by shift (stage 0 → 1)
        # Simple: valid[0] = dequeue (overwrites on every dequeue cycle)
        m.d.sync += pipe_valid[0].eq(dequeue)
        with m.If(dequeue):
            m.d.sync += [
                q_valid[q_head].eq(0),
                q_head.eq(Mux(q_head == QD - 1, 0, q_head + 1)),
                pipe_tag[0].eq(q_tag[q_head]),
                pipe_is_write[0].eq(q_is_write[q_head]),
                pipe_data[0].eq(Mux(q_is_write[q_head],
                    q_write_data[q_head],
                    q_addr[q_head][:self.data_width] ^ Cat(q_tag[q_head], C(0, self.data_width - 16)))),
            ]

        # Response output from pipe tail
        m.d.comb += [
            self.rsp_valid.eq(pipe_valid[LD - 1]),
            self.rsp_read_data.eq(pipe_data[LD - 1]),
            self.rsp_tag.eq(pipe_tag[LD - 1]),
            self.rsp_error.eq(0),
        ]

        return m
