from amaranth import *

ACCEL_VERSION_VALUE = 0x20250601


class AcceleratorRegs(Elaboratable):
    def __init__(self, config):
        self._config = config

        self.bus_addr = Signal(12)
        self.bus_wdata = Signal(32)
        self.bus_wstrb = Signal(4)
        self.bus_valid = Signal()
        self.bus_ready = Signal()
        self.bus_is_write = Signal()
        self.bus_rdata = Signal(32)
        self.bus_rvalid = Signal()

        self.status_busy = Signal()
        self.status_error = Signal()
        self.status_relocation_active = Signal()
        self.scan_done = Signal()
        self.perf_cycle = Signal(32)
        self.perf_scan_obj = Signal(32)
        self.perf_moved_obj = Signal(32)
        self.perf_errors = Signal(32)

        self.control_start = Signal()
        self.control_reset = Signal()
        self.control_enable_coherent = Signal()
        self.heap_base = Signal(32)
        self.heap_size = Signal(32)
        self.region_size = Signal(32)

    @staticmethod
    def _merge(old, new, wstrb):
        return Cat(
            Mux(wstrb[0], new.word_select(0, 8), old.word_select(0, 8)),
            Mux(wstrb[1], new.word_select(1, 8), old.word_select(1, 8)),
            Mux(wstrb[2], new.word_select(2, 8), old.word_select(2, 8)),
            Mux(wstrb[3], new.word_select(3, 8), old.word_select(3, 8)),
        )

    def elaborate(self, platform):
        m = Module()

        control = Signal(3)
        heap_base = Signal(32)
        heap_size = Signal(32)
        region_size = Signal(32)

        raddr = Signal(10)
        rvalid = Signal()

        m.d.comb += self.bus_ready.eq(self.bus_valid)

        with m.If(self.bus_valid & self.bus_is_write):
            with m.Switch(self.bus_addr >> 2):
                with m.Case(2):
                    m.d.sync += control.eq(self.bus_wdata[:3])
                with m.Case(8):
                    m.d.sync += heap_base.eq(self._merge(heap_base, self.bus_wdata, self.bus_wstrb))
                with m.Case(9):
                    m.d.sync += heap_size.eq(self._merge(heap_size, self.bus_wdata, self.bus_wstrb))
                with m.Case(10):
                    m.d.sync += region_size.eq(self._merge(region_size, self.bus_wdata, self.bus_wstrb))

        with m.If(self.bus_valid & ~self.bus_is_write):
            m.d.sync += [
                raddr.eq(self.bus_addr >> 2),
                rvalid.eq(1),
            ]
        with m.Else():
            m.d.sync += rvalid.eq(0)

        m.d.comb += self.bus_rvalid.eq(rvalid)

        status_val = Cat(self.status_busy, self.status_error, self.status_relocation_active)

        with m.Switch(raddr):
            with m.Case(0):
                m.d.comb += self.bus_rdata.eq(ACCEL_VERSION_VALUE)
            with m.Case(1):
                m.d.comb += self.bus_rdata.eq(status_val)
            with m.Case(2):
                m.d.comb += self.bus_rdata.eq(control)
            with m.Case(3):
                m.d.comb += self.bus_rdata.eq(self.scan_done)
            with m.Case(8):
                m.d.comb += self.bus_rdata.eq(heap_base)
            with m.Case(9):
                m.d.comb += self.bus_rdata.eq(heap_size)
            with m.Case(10):
                m.d.comb += self.bus_rdata.eq(region_size)
            with m.Case(12):
                m.d.comb += self.bus_rdata.eq(self.perf_cycle)
            with m.Case(13):
                m.d.comb += self.bus_rdata.eq(self.perf_scan_obj)
            with m.Case(14):
                m.d.comb += self.bus_rdata.eq(self.perf_moved_obj)
            with m.Case(15):
                m.d.comb += self.bus_rdata.eq(self.perf_errors)
            with m.Default():
                m.d.comb += self.bus_rdata.eq(0)

        m.d.comb += [
            self.control_start.eq(control[0]),
            self.control_reset.eq(control[1]),
            self.control_enable_coherent.eq(control[2]),
            self.heap_base.eq(heap_base),
            self.heap_size.eq(heap_size),
            self.region_size.eq(region_size),
        ]

        return m
