# rtl/gc_config.py
# Jasper-GC 分层配置对象

from dataclasses import dataclass, field
from typing import Optional

# ── 前台 Barrier 参数 ──────────────────────────────────────────
@dataclass
class GCFrontendConfig:
    gc_slots: int = 16
    rb_cache_ways: int = 4
    rb_slots: int = 4
    wb_depth: int = 4
    mv_depth: int = 4
    wb_ptr_filter: int = 0
    wb_card_shift: int = 6
    wb_obj_shift: int = 4
    rb_mode: int = 0
    wb_combine_depth: int = 0
    gc_slots_bank_impl: str = "standard"
    gc_slots_bank_count: int = 1

# ── 根扫描参数 ────────────────────────────────────────────────
@dataclass
class GCRootScanConfig:
    root_fifo_depth: int = 8
    root_scan_width: int = 1
    root_table_entries: int = 256

# ── 堆遍历参数 ────────────────────────────────────────────────
@dataclass
class GCHeapWalkConfig:
    heap_walk_slots: int = 8
    object_scan_width: int = 2
    trace_fifo_depth: int = 8
    mark_queue_depth: int = 32
    layout_cache_entries: int = 16
    max_fields_per_object: int = 16

# ── 标记/清扫参数 ─────────────────────────────────────────────
@dataclass
class GCMarkSweepConfig:
    card_table_size: int = 16
    card_table_ways: int = 2
    card_index_mode: int = 0
    sweep_batch_size: int = 4
    sweep_entries: int = 256
    sweep_fifo_depth: int = 8
    engine_latency: int = 0

# ── Move/Forwarding 参数 ─────────────────────────────────────
@dataclass
class GCMoveConfig:
    forward_table_entries: int = 64
    forward_table_ways: int = 4
    forward_chase_limit: int = 4
    reloc_fifo_depth: int = 8
    move_update_fifo_depth: int = 8


# ── 多 backend / bank 配置 (默认全部=1) ────────────────────────
@dataclass
class GCBackendConfig:
    scan_backend_count: int = 1
    sweep_backend_count: int = 1
    move_backend_count: int = 1
    heap_walk_backend_count: int = 1
    metadata_bank_count: int = 1
    forwarding_bank_count: int = 1
    slots_bank_count: int = 1
    forwarding_table_impl: str = "standard"
    metadata_pipeline_impl: str = "standard"
    slots_impl: str = "standard"
    forwarding_pipeline_stages: int = 3
    forwarding_dispatch_policy: str = "round_robin"
    forwarding_merge_policy: str = "ordered"
    backend_dispatch_policy: str = "round_robin"
    backend_merge_policy: str = "none"

# ── GC Cycle 参数 ────────────────────────────────────────────
@dataclass
class GCCycleConfig:
    enable_compact: bool = True
    enable_reloc: bool = True
    enable_incremental: bool = False
    max_steps: int = 1000
    safepoint_timeout: int = 100


# ── GC 内存策略参数 ───────────────────────────────────────────

# ── GC 拓扑/多核边界配置 ───────────────────────────────────────
@dataclass
class GCTopologyConfig:
    '''GC 模块拓扑/归属配置

    Per-core (must):
      GCSubsystem, WB FIFO, RB slots/cache, GC slots,
      scoreboard, GC forwarding bypass, heap range/pointer filter
      Reason: stick to main pipeline, WB zero-cycle, RB non-blocking

    Shared (should):
      GCCycleController, RootScanner, HeapWalker,
      Scan/Clean/Sweep, Move forwarding table,
      global mark bitmap, card table, remembered set,
      epoch controller, metadata cache, stream buffer
      Reason: global state, avoid per-core duplication

    Tiered (per-core L0 + shared L2):
      RB cache/forwarding, metadata cache, stream buffer
      Reason: low latency hit locally, large capacity shared
    '''
    ncores: int = 1
    frontend_scope: str = "per_core"     # per_core | shared
    backend_scope: str = "shared"        # per_core | shared | cluster
    metadata_cache_scope: str = "shared" # per_core | shared | cluster(L0+shared)
    rb_l0_scope: str = "per_core"        # per_core | shared
    stream_buffer_scope: str = "shared"  # per_core | shared
    wb_fifo_scope: str = "per_core"      # per_core | shared
    scoreboard_scope: str = "per_core"   # per_core | shared
    gc_forwarding_scope: str = "per_core"
    cycle_control_scope: str = "shared"

@dataclass
class GCClusterConfig:
    nclusters: int = 1
    cores_per_cluster: int = 4
    shared_metadata_per_cluster: bool = True
    shared_heap_walker_per_cluster: bool = True



@dataclass
class GCDebugConfig:
    """调试/验证参数: 默认关闭, 综合可裁剪."""
    debug: bool = False           # 内部 debug 信号
    perf_counters_enable: bool = False  # 性能计数器
    trace_ports_enable: bool = False    # trace 输出端口
    debug_synthesis_guard: bool = False # synthesis guard (裁剪debug逻辑)
    max_queue_watermark_enable: bool = False  # 队列水位线
    engine_latency: int = 0       # 引擎仿真延迟 (制造背压)
    safepoint_timeout: int = 100  # safepoint超时
    max_steps: int = 1000         # 最大 GC 步数


@dataclass
class GCMemoryPolicyConfig:
    # Metadata Cache
    metadata_cache_enable: bool = False
    metadata_cache_size: int = 2048       # bytes
    metadata_cache_ways: int = 2
    metadata_cache_line_size: int = 64
    # Stream Buffer
    stream_buffer_enable: bool = False
    stream_buffer_entries: int = 4
    stream_buffer_line_size: int = 64
    stream_buffer_prefetch_distance: int = 2
    # D-cache Bypass
    dcache_bypass_enable: bool = True
    bypass_gc_scan: bool = True
    bypass_gc_sweep: bool = True
    bypass_gc_root: bool = True
    bypass_gc_object_walk: bool = True
    # Cache Partition
    cache_partition_enable: bool = False
    mutator_reserved_ways: int = 6
    gc_reserved_ways: int = 2
    gc_no_fill_policy: str = "bypass"  # bypass | evict | nofill
# ── 完整 GC 配置 ──────────────────────────────────────────────
@dataclass
class JasperGCConfig:
    frontend: GCFrontendConfig = field(default_factory=GCFrontendConfig)
    root_scan: GCRootScanConfig = field(default_factory=GCRootScanConfig)
    heap_walk: GCHeapWalkConfig = field(default_factory=GCHeapWalkConfig)
    mark_sweep: GCMarkSweepConfig = field(default_factory=GCMarkSweepConfig)
    move: GCMoveConfig = field(default_factory=GCMoveConfig)
    backend: GCBackendConfig = field(default_factory=GCBackendConfig)
    cycle: GCCycleConfig = field(default_factory=GCCycleConfig)
    memory_policy: GCMemoryPolicyConfig = field(default_factory=GCMemoryPolicyConfig)
    debug: GCDebugConfig = field(default_factory=GCDebugConfig)

    def update_frontend(self, **kwargs):
        for k, v in kwargs.items():
            if hasattr(self.frontend, k):
                setattr(self.frontend, k, v)
        return self

    def to_dict(self):
        return {
            'gc_slots': self.frontend.gc_slots,
            'rb_cache_ways': self.frontend.rb_cache_ways,
            'rb_slots': self.frontend.rb_slots,
            'wb_depth': self.frontend.wb_depth,
            'mv_depth': self.frontend.mv_depth,
            'wb_ptr_filter': self.frontend.wb_ptr_filter,
            'wb_card_shift': self.frontend.wb_card_shift,
            'wb_obj_shift': self.frontend.wb_obj_shift,
            'rb_mode': self.frontend.rb_mode,
            'wb_combine_depth': self.frontend.wb_combine_depth,
            'gc_slots_bank_impl': self.frontend.gc_slots_bank_impl,
            'gc_slots_bank_count': self.frontend.gc_slots_bank_count,
        }

# ── 三档 Profile ─────────────────────────────────────────────
PROFILES = {}

def define_profile(name: str, cfg: JasperGCConfig):
    PROFILES[name] = cfg
    return cfg

# Lite: MCU 级，最小面积
define_profile("lite", JasperGCConfig(
    frontend=GCFrontendConfig(gc_slots=8, rb_cache_ways=2, rb_slots=2, wb_depth=2, mv_depth=2),
    root_scan=GCRootScanConfig(root_fifo_depth=4, root_table_entries=64),
    heap_walk=GCHeapWalkConfig(heap_walk_slots=4, mark_queue_depth=16, layout_cache_entries=8),
    mark_sweep=GCMarkSweepConfig(card_table_size=8, sweep_entries=128, sweep_fifo_depth=4),
    move=GCMoveConfig(forward_table_entries=32, forward_chase_limit=2, reloc_fifo_depth=4),
    cycle=GCCycleConfig(enable_incremental=True),
    memory_policy=GCMemoryPolicyConfig(
        metadata_cache_enable=False,
        stream_buffer_enable=True, stream_buffer_entries=2,
        dcache_bypass_enable=True,
        cache_partition_enable=False,
    ),
))

# Standard: 默认平衡
define_profile("standard", JasperGCConfig(
    frontend=GCFrontendConfig(),
    root_scan=GCRootScanConfig(),
    heap_walk=GCHeapWalkConfig(),
    mark_sweep=GCMarkSweepConfig(),
    move=GCMoveConfig(),
    cycle=GCCycleConfig(),
    memory_policy=GCMemoryPolicyConfig(
        metadata_cache_enable=True, metadata_cache_size=4096,
        stream_buffer_enable=True, stream_buffer_entries=4,
        dcache_bypass_enable=True,
        cache_partition_enable=False,
    ),
))

# Server: 高压大内存
define_profile("server", JasperGCConfig(
    frontend=GCFrontendConfig(gc_slots=32, rb_cache_ways=8, rb_slots=16, wb_depth=16, mv_depth=16, wb_combine_depth=4),
    root_scan=GCRootScanConfig(root_fifo_depth=32, root_table_entries=1024, root_scan_width=4),
    heap_walk=GCHeapWalkConfig(heap_walk_slots=16, mark_queue_depth=128, object_scan_width=4),
    mark_sweep=GCMarkSweepConfig(card_table_size=32, card_table_ways=4, sweep_entries=1024),
    move=GCMoveConfig(forward_table_entries=256, forward_chase_limit=8, reloc_fifo_depth=32),
    cycle=GCCycleConfig(enable_compact=True, enable_reloc=True),
    memory_policy=GCMemoryPolicyConfig(
        metadata_cache_enable=True, metadata_cache_size=16384, metadata_cache_ways=4,
        stream_buffer_enable=True, stream_buffer_entries=8, stream_buffer_prefetch_distance=4,
        dcache_bypass_enable=True,
        cache_partition_enable=True, mutator_reserved_ways=6, gc_reserved_ways=2,
    ),
    # Server experimental: multi-backend
    backend=GCBackendConfig(
        scan_backend_count=4, sweep_backend_count=2, move_backend_count=4,
        metadata_bank_count=4, forwarding_bank_count=4, slots_bank_count=2,
        backend_dispatch_policy="hash_lsb", backend_merge_policy="ordered",
        forwarding_table_impl="banked_pipeline",
        metadata_pipeline_impl="pipelined",
        slots_impl="banked",
    ),
))

def gc_module_scope(cfg: JasperGCConfig, module: str) -> str:
    """Return module scope: per_core | shared | cluster"""
    scope_map = {
        "gc_subsystem": cfg.topology.frontend_scope,
        "wb_fifo": cfg.topology.wb_fifo_scope,
        "rb_slots": cfg.topology.frontend_scope,
        "rb_cache": cfg.topology.rb_l0_scope,
        "gc_slots": cfg.topology.frontend_scope,
        "scoreboard": cfg.topology.scoreboard_scope,
        "gc_forwarding": cfg.topology.gc_forwarding_scope,
        "cycle_controller": cfg.topology.cycle_control_scope,
        "metadata_cache": cfg.topology.metadata_cache_scope,
        "stream_buffer": cfg.topology.stream_buffer_scope,
        "root_scan": cfg.topology.backend_scope,
        "heap_walk": cfg.topology.backend_scope,
        "scan": cfg.topology.backend_scope,
        "sweep": cfg.topology.backend_scope,
        "move": cfg.topology.backend_scope,
    }
    return scope_map.get(module, "per_core")


def get_profile(name: str) -> JasperGCConfig:
    if name not in PROFILES:
        raise ValueError(f"Unknown GC profile: {name}. Choices: {list(PROFILES.keys())}")
    return PROFILES[name]
