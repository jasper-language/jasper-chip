# rtl/gc_heap_region.py
# Heap Region Partition: 将堆划分为 N 个区域, 每个区域分配给一个 backend
from amaranth import *

class HeapRegionFlat(Elaboratable):
    """Flat 实现: 单个区域, 所有地址送往 backend 0.

    与当前单 backend 行为一致.
    """
    def __init__(self, addr_width=32, region_id_width=1, n_backends=1):
        self.addr_width = addr_width
        self.region_id_width = region_id_width
        self.n_backends = n_backends

        self.access_valid = Signal()
        self.access_ready = Signal()
        self.access_addr = Signal(addr_width)
        self.access_source = Signal(8)

        self.region_id = Signal(region_id_width)
        self.per_region_busy = Signal(n_backends)
        self.backend_dispatch = Signal(range(max(n_backends, 1)))

    def elaborate(self, platform):
        m = Module()
        m.d.comb += [
            self.access_ready.eq(~self.per_region_busy[0] if self.n_backends > 0 else 1),
            self.region_id.eq(0),
            self.backend_dispatch.eq(0),
        ]
        return m


class HeapRegionPartitioned(Elaboratable):
    """Partitioned 实现: N 个区域, 地址 hash → region_id, 分发到对应 backend.

    region_id = hash(addr) >> shift, 其中 shift 控制区域粒度.
    """
    def __init__(self, addr_width=32, region_id_width=2, n_regions=4,
                 hash_shift=0, n_backends=4):
        self.addr_width = addr_width
        self.region_id_width = region_id_width
        self.n_regions = n_regions
        self.hash_shift = hash_shift
        self.n_backends = n_backends

        self.access_valid = Signal()
        self.access_ready = Signal()
        self.access_addr = Signal(addr_width)
        self.access_source = Signal(8)

        self.region_id = Signal(region_id_width)
        self.per_region_busy = Signal(n_regions)
        self.backend_dispatch = Signal(range(max(n_backends, 1)))

    def elaborate(self, platform):
        m = Module()
        n = self.n_regions
        shift = self.hash_shift

        addr_hash = Signal(self.addr_width)
        m.d.comb += addr_hash.eq(self.access_addr ^ (self.access_addr >> 4))

        region = Signal(self.region_id_width)
        m.d.comb += region.eq(addr_hash >> shift)

        busy_bits = Signal(n)
        for i in range(n):
            m.d.comb += busy_bits[i].eq(self.per_region_busy[i])

        any_busy = Signal()
        m.d.comb += any_busy.eq(busy_bits.any())

        m.d.comb += [
            self.access_ready.eq(~any_busy),
            self.region_id.eq(region),
            self.backend_dispatch.eq(region),
        ]
        return m


def create_heap_region(impl: str, **kwargs):
    if impl == "flat":
        return HeapRegionFlat(**kwargs)
    elif impl == "partitioned":
        return HeapRegionPartitioned(**kwargs)
    else:
        raise ValueError(f"Unknown heap_region_impl: {impl}")
