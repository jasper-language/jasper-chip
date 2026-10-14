# rtl/jasper_gc_config.py
# Unified Jasper-GC backend configuration — supersedes gc_config.py/GCCycleConfig
from dataclasses import dataclass, field
from enum import Enum


class BackendProfile(Enum):
    LITE = "lite"
    STANDARD = "standard"
    STANDARD_PLUS = "standard_plus"
    GATEWAY = "gateway"
    SERVER_BASE = "server_base"
    SERVER = "server"
    EXTREME = "extreme"


class DispatchPolicy(Enum):
    NONE = 0
    CORE_AFFINITY = 1
    REGION_AFFINITY = 2
    HASH_LSB = 3
    BACKPRESSURE_AWARE = 4
    HYBRID = 5
    LOAD_AWARE = 6


class MergePolicy(Enum):
    BYPASS = 0
    ORDERED_BY_DOMAIN = 1
    PER_DOMAIN_QUEUE = 2
    HIERARCHICAL = 3


class BackpressurePolicy(Enum):
    NONE = 0
    PER_TILE_READY = 1
    PER_TILE_SKID = 2
    BACKPRESSURE_AWARE = 3
    CREDIT_BASED = 4


class PartitionPolicy(Enum):
    SHARED = 0
    PER_TILE = 1
    REGION_BANKED = 2


class PowerPolicy(Enum):
    ALWAYS_ON = 0
    CLOCK_GATED_IDLE = 1
    LOAD_BASED = 2
    PHASE_BASED = 3


@dataclass
class JasperGCConfig:
    # Structure
    cpu_core_count: int = 1
    lane_per_tile: int = 1
    tile_count: int = 1
    backend_profile: BackendProfile = BackendProfile.STANDARD

    # Caches / tables / queues
    metadata_cache_size: int = 32
    metadata_ways: int = 4
    metadata_pipeline_depth: int = 8
    forwarding_entries: int = 64
    forwarding_chase_depth: int = 4
    ordered_merge_queue_depth: int = 8
    skid_buffer_depth: int = 2
    merge_domain_count: int = 4

    # Fabric policies
    dispatch_policy: DispatchPolicy = DispatchPolicy.NONE
    merge_policy: MergePolicy = MergePolicy.BYPASS
    backpressure_policy: BackpressurePolicy = BackpressurePolicy.NONE
    affinity_policy: DispatchPolicy = DispatchPolicy.NONE
    partition_policy: PartitionPolicy = PartitionPolicy.SHARED
    power_policy: PowerPolicy = PowerPolicy.CLOCK_GATED_IDLE

    # Feature toggles
    enable_clock_gating: bool = True
    enable_load_based_enable: bool = False
    enable_debug: bool = False
    enable_perf_counters: bool = False
    enable_trace: bool = False
    enable_external_gc_interface: bool = False
    enable_forwarding: bool = True
    enable_metadata_caching: bool = True

    # Internal / research
    _status_hold: bool = False
    _load_aware_implemented: bool = False

    def validate(self) -> list[str]:
        errors = []
        if self.lane_per_tile not in (1, 2):
            errors.append(f"lane_per_tile must be 1 or 2, got {self.lane_per_tile}")
        if self.cpu_core_count < 1:
            errors.append(f"cpu_core_count must be >= 1, got {self.cpu_core_count}")
        if self.tile_count not in (1, 2, 4, 8, 16, 32, 64):
            errors.append(f"tile_count must be 1/2/4/8/16/32/64, got {self.tile_count}")
        if self.tile_count & (self.tile_count - 1) != 0:
            errors.append(f"tile_count must be power of 2, got {self.tile_count}")
        if self.backend_profile in (BackendProfile.LITE, BackendProfile.STANDARD, BackendProfile.STANDARD_PLUS):
            if self.tile_count > 1:
                errors.append(f"{self.backend_profile.value} profile cannot use tile_count > 1")
            if self.lane_per_tile > 1:
                errors.append(f"{self.backend_profile.value} profile cannot use lane_per_tile > 1")
            if self.dispatch_policy != DispatchPolicy.NONE:
                errors.append(f"{self.backend_profile.value} cannot use dispatch — single tile")
        if self.dispatch_policy == DispatchPolicy.LOAD_AWARE and not self._load_aware_implemented:
            errors.append("load_aware dispatch not implemented — set _load_aware_implemented=True or change policy")
        if self._status_hold:
            pass
        return errors

    @classmethod
    def from_profile(cls, profile: BackendProfile) -> 'JasperGCConfig':
        presets = {
            BackendProfile.LITE: cls(
                backend_profile=profile, lane_per_tile=1, tile_count=1,
                metadata_cache_size=16, metadata_ways=2,
                metadata_pipeline_depth=8, forwarding_entries=32,
                ordered_merge_queue_depth=8, enable_debug=False,
                enable_perf_counters=False, enable_load_based_enable=False,
            ),
            BackendProfile.STANDARD: cls(
                backend_profile=profile, lane_per_tile=1, tile_count=1,
                metadata_cache_size=32, metadata_ways=4,
                metadata_pipeline_depth=8, forwarding_entries=64,
                ordered_merge_queue_depth=8,
                enable_debug=False, enable_perf_counters=False,
            ),
            BackendProfile.STANDARD_PLUS: cls(
                backend_profile=profile, lane_per_tile=1, tile_count=1,
                metadata_cache_size=64, metadata_ways=8,
                metadata_pipeline_depth=4, forwarding_entries=128,
                ordered_merge_queue_depth=8,
                enable_debug=False, enable_perf_counters=False,
            ),
            BackendProfile.GATEWAY: cls(
                backend_profile=profile, lane_per_tile=2, tile_count=1,
                metadata_cache_size=32, metadata_ways=4,
                metadata_pipeline_depth=8, forwarding_entries=64,
                ordered_merge_queue_depth=8,
                dispatch_policy=DispatchPolicy.HASH_LSB,
                merge_policy=MergePolicy.ORDERED_BY_DOMAIN,
                backpressure_policy=BackpressurePolicy.PER_TILE_READY,
                partition_policy=PartitionPolicy.SHARED,
                enable_load_based_enable=False,
            ),
            BackendProfile.SERVER_BASE: cls(
                backend_profile=profile, lane_per_tile=2, tile_count=2,
                metadata_cache_size=32, metadata_ways=4,
                metadata_pipeline_depth=8, forwarding_entries=64,
                ordered_merge_queue_depth=8,
                dispatch_policy=DispatchPolicy.CORE_AFFINITY,
                merge_policy=MergePolicy.ORDERED_BY_DOMAIN,
                backpressure_policy=BackpressurePolicy.PER_TILE_SKID,
                partition_policy=PartitionPolicy.PER_TILE,
                enable_load_based_enable=False,
            ),
            BackendProfile.SERVER: cls(
                backend_profile=profile, lane_per_tile=2, tile_count=4,
                metadata_cache_size=64, metadata_ways=8,
                metadata_pipeline_depth=8, forwarding_entries=128,
                ordered_merge_queue_depth=16,
                dispatch_policy=DispatchPolicy.HYBRID,
                merge_policy=MergePolicy.PER_DOMAIN_QUEUE,
                backpressure_policy=BackpressurePolicy.BACKPRESSURE_AWARE,
                partition_policy=PartitionPolicy.PER_TILE,
                enable_load_based_enable=True,
                enable_debug=True,
            ),
            BackendProfile.EXTREME: cls(
                backend_profile=profile, lane_per_tile=2, tile_count=8,
                metadata_cache_size=128, metadata_ways=16,
                metadata_pipeline_depth=8, forwarding_entries=256,
                ordered_merge_queue_depth=32,
                dispatch_policy=DispatchPolicy.HYBRID,
                merge_policy=MergePolicy.HIERARCHICAL,
                backpressure_policy=BackpressurePolicy.CREDIT_BASED,
                partition_policy=PartitionPolicy.REGION_BANKED,
                enable_load_based_enable=True,
                enable_debug=True,
                _status_hold=True,
                _load_aware_implemented=False,
            ),
        }
        return presets[profile]
