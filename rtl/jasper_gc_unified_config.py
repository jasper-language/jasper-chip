from dataclasses import dataclass
from enum import Enum
from typing import Optional
from rtl.jasper_gc_config import (
    JasperGCConfig,
    BackendProfile,
    DispatchPolicy,
    MergePolicy,
    BackpressurePolicy,
)
from rtl.jasper_gc_accelerator_config import JasperGCAcceleratorConfig, AcceleratorProfile


class UnifiedProfile(Enum):
    LITE = "lite"
    STANDARD = "standard"
    SERVER = "server"
    EXTREME = "extreme"
    ACCEL_ONLY = "accel_only"


class ProductProfile(Enum):
    MCU = "mcu"
    EDGE = "edge"
    MOBILE = "mobile"
    LAPTOP = "laptop"
    DESKTOP = "desktop"
    SERVER = "server"


class BackendMode(Enum):
    SINGLE = "single"
    WIDE_TILE = "wide_tile"
    MULTI_BACKEND = "multi_backend"


class SweepMode(Enum):
    STANDARD = "standard"
    PIPELINED = "pipelined"
    MULTI_ENGINE = "multi_engine"


class AcceleratorMode(Enum):
    DISABLED = "disabled"
    INLINE = "inline"
    EXTERNAL = "external"
    ACCEL_ONLY = "accel_only"


@dataclass
class JasperGCUnifiedConfig:
    profile: UnifiedProfile = UnifiedProfile.STANDARD

    backend_mode: BackendMode = BackendMode.SINGLE
    sweep_mode: SweepMode = SweepMode.STANDARD
    accelerator_mode: AcceleratorMode = AcceleratorMode.DISABLED

    lane_per_tile: Optional[int] = None
    tile_count: Optional[int] = None
    cpu_core_count: Optional[int] = None
    enable_accelerator: Optional[bool] = None  # Backward-compatible alias.

    backend_config: Optional[JasperGCConfig] = None
    accel_config: Optional[JasperGCAcceleratorConfig] = None

    accelerator_memory_model: str = "memory_access"
    accelerator_enable_memory: bool = True

    def _shape_from_mode(self) -> tuple[int, int]:
        lane = self.lane_per_tile
        tiles = self.tile_count
        if self.backend_mode == BackendMode.SINGLE:
            lane = 1 if lane is None else lane
            tiles = 1 if tiles is None else tiles
            if lane != 1 or tiles != 1:
                raise ValueError("BackendMode.SINGLE requires lane_per_tile=1 and tile_count=1")
        elif self.backend_mode == BackendMode.WIDE_TILE:
            lane = 2 if lane is None else lane
            tiles = 1 if tiles is None else tiles
            if lane != 2 or tiles != 1:
                raise ValueError("BackendMode.WIDE_TILE requires lane_per_tile=2 and tile_count=1")
        elif self.backend_mode == BackendMode.MULTI_BACKEND:
            lane = 2 if lane is None else lane
            tiles = 2 if tiles is None else tiles
            if lane not in (1, 2):
                raise ValueError("BackendMode.MULTI_BACKEND requires lane_per_tile=1 or 2")
            if tiles <= 1:
                raise ValueError("BackendMode.MULTI_BACKEND requires tile_count > 1")
        else:
            raise ValueError(f"Unknown backend_mode: {self.backend_mode}")
        return lane, tiles

    @staticmethod
    def _profile_for_mode(mode: BackendMode, profile: UnifiedProfile,
                          tile_count: int) -> BackendProfile:
        if mode == BackendMode.SINGLE:
            if profile == UnifiedProfile.LITE:
                return BackendProfile.LITE
            if profile == UnifiedProfile.STANDARD:
                return BackendProfile.STANDARD
            return BackendProfile.STANDARD_PLUS
        if mode == BackendMode.WIDE_TILE:
            return BackendProfile.GATEWAY
        if mode == BackendMode.MULTI_BACKEND:
            if profile == UnifiedProfile.EXTREME:
                if tile_count >= 8:
                    return BackendProfile.EXTREME
                return BackendProfile.SERVER if tile_count >= 4 else BackendProfile.SERVER_BASE
            if profile == UnifiedProfile.LITE:
                return BackendProfile.SERVER_BASE
            return BackendProfile.SERVER
        return BackendProfile.STANDARD

    @classmethod
    def from_product_profile(
        cls,
        product_profile: "ProductProfile",
        **kwargs,
    ) -> "JasperGCUnifiedConfig":
        defaults = {
            ProductProfile.MCU: {
                "profile": UnifiedProfile.LITE,
                "backend_mode": BackendMode.SINGLE,
                "sweep_mode": SweepMode.STANDARD,
                "accelerator_mode": AcceleratorMode.DISABLED,
                "lane_per_tile": 1,
                "tile_count": 1,
                "cpu_core_count": 1,
            },
            ProductProfile.EDGE: {
                "profile": UnifiedProfile.STANDARD,
                "backend_mode": BackendMode.MULTI_BACKEND,
                "sweep_mode": SweepMode.STANDARD,
                "accelerator_mode": AcceleratorMode.DISABLED,
                "lane_per_tile": 2,
                "tile_count": 4,
                "cpu_core_count": 4,
            },
            ProductProfile.MOBILE: {
                "profile": UnifiedProfile.STANDARD,
                "backend_mode": BackendMode.MULTI_BACKEND,
                "sweep_mode": SweepMode.STANDARD,
                "accelerator_mode": AcceleratorMode.INLINE,
                "lane_per_tile": 2,
                "tile_count": 8,
                "cpu_core_count": 8,
            },
            ProductProfile.LAPTOP: {
                "profile": UnifiedProfile.STANDARD,
                "backend_mode": BackendMode.MULTI_BACKEND,
                "sweep_mode": SweepMode.STANDARD,
                "accelerator_mode": AcceleratorMode.INLINE,
                "lane_per_tile": 2,
                "tile_count": 16,
                "cpu_core_count": 16,
            },
            ProductProfile.DESKTOP: {
                "profile": UnifiedProfile.SERVER,
                "backend_mode": BackendMode.MULTI_BACKEND,
                "sweep_mode": SweepMode.STANDARD,
                "accelerator_mode": AcceleratorMode.EXTERNAL,
                "lane_per_tile": 2,
                "tile_count": 32,
                "cpu_core_count": 32,
            },
            ProductProfile.SERVER: {
                "profile": UnifiedProfile.SERVER,
                "backend_mode": BackendMode.MULTI_BACKEND,
                "sweep_mode": SweepMode.STANDARD,
                "accelerator_mode": AcceleratorMode.EXTERNAL,
                "lane_per_tile": 2,
                "tile_count": 64,
                "cpu_core_count": 64,
            },
        }[product_profile]

        merged = defaults.copy()
        merged.update(kwargs)
        return cls(**merged)

    def resolve(self):
        preset = _UNIFIED_PRESETS[self.profile]

        lane_per_tile, tile_count = self._shape_from_mode()
        if self.enable_accelerator is not None:
            accel_mode = AcceleratorMode.INLINE if self.enable_accelerator else AcceleratorMode.DISABLED
        else:
            accel_mode = self.accelerator_mode

        if self.backend_config is not None:
            bc = self.backend_config
        else:
            bp = self._profile_for_mode(self.backend_mode, self.profile, tile_count)
            bc = JasperGCConfig.from_profile(bp)
            bc.lane_per_tile = lane_per_tile
            bc.tile_count = tile_count
            bc.cpu_core_count = self.cpu_core_count or tile_count
        if self.cpu_core_count is not None:
            bc.cpu_core_count = self.cpu_core_count

        if self.backend_mode == BackendMode.WIDE_TILE:
            bc.dispatch_policy = DispatchPolicy.HASH_LSB
            bc.merge_policy = MergePolicy.ORDERED_BY_DOMAIN
            bc.backpressure_policy = BackpressurePolicy.PER_TILE_READY
        elif self.backend_mode == BackendMode.MULTI_BACKEND:
            if bc.dispatch_policy == DispatchPolicy.NONE:
                bc.dispatch_policy = DispatchPolicy.HASH_LSB
            if bc.tile_count > 32 and bc.dispatch_policy in (
                DispatchPolicy.BACKPRESSURE_AWARE,
                DispatchPolicy.HYBRID,
                DispatchPolicy.LOAD_AWARE,
            ):
                # Ready-aware dispatch feeds lane ready into tile selection. That is useful for
                # small/medium RTL simulation, but creates a ready->data combinational path that
                # is not acceptable for large domain-partitioned synthesis profiles.
                bc.dispatch_policy = DispatchPolicy.HASH_LSB
            if bc.merge_policy == MergePolicy.BYPASS:
                bc.merge_policy = MergePolicy.ORDERED_BY_DOMAIN
            if bc.backpressure_policy == BackpressurePolicy.NONE:
                bc.backpressure_policy = BackpressurePolicy.PER_TILE_SKID

        if accel_mode in (AcceleratorMode.INLINE, AcceleratorMode.EXTERNAL, AcceleratorMode.ACCEL_ONLY):
            if self.accel_config is not None:
                ac = self.accel_config
            else:
                ac = JasperGCAcceleratorConfig.from_profile(preset.accel_profile)
        else:
            ac = None

        if accel_mode == AcceleratorMode.ACCEL_ONLY:
            bc = JasperGCConfig.from_profile(BackendProfile.LITE)
            bc.lane_per_tile = 1
            bc.tile_count = 1

        errors = bc.validate()
        if errors:
            raise ValueError(f"Backend config validation failed: {'; '.join(errors)}")
        if ac is not None:
            aerr = ac.validate()
            if aerr:
                raise ValueError(f"Accelerator config validation failed: {'; '.join(aerr)}")

        return bc, ac


class _Preset:
    def __init__(self, accel_profile: AcceleratorProfile = AcceleratorProfile.ACCEL_STANDARD):
        self.accel_profile = accel_profile


_UNIFIED_PRESETS: dict[UnifiedProfile, _Preset] = {
    UnifiedProfile.LITE: _Preset(),
    UnifiedProfile.STANDARD: _Preset(),
    UnifiedProfile.SERVER: _Preset(accel_profile=AcceleratorProfile.ACCEL_SERVER),
    UnifiedProfile.EXTREME: _Preset(accel_profile=AcceleratorProfile.ACCEL_EXTREME),
    UnifiedProfile.ACCEL_ONLY: _Preset(accel_profile=AcceleratorProfile.ACCEL_STANDARD),
}
