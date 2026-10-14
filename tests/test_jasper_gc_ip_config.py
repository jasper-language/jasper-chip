# tests/test_jasper_gc_ip_config.py
import pytest
from rtl.jasper_gc_config import JasperGCConfig, BackendProfile, DispatchPolicy, MergePolicy, BackpressurePolicy

def test_lite_config():
    cfg = JasperGCConfig.from_profile(BackendProfile.LITE)
    assert cfg.tile_count == 1
    assert cfg.lane_per_tile == 1
    assert cfg.enable_debug is False
    assert cfg.enable_perf_counters is False

def test_standard_config():
    cfg = JasperGCConfig.from_profile(BackendProfile.STANDARD)
    assert cfg.tile_count == 1
    assert cfg.lane_per_tile == 1
    assert cfg.metadata_cache_size == 32
    assert cfg.metadata_pipeline_depth == 8

def test_standard_plus_config():
    cfg = JasperGCConfig.from_profile(BackendProfile.STANDARD_PLUS)
    assert cfg.metadata_cache_size == 64  # larger cache
    assert cfg.metadata_pipeline_depth == 4  # lower latency

def test_gateway_config():
    cfg = JasperGCConfig.from_profile(BackendProfile.GATEWAY)
    assert cfg.tile_count == 1   # 2L×1 = 1 tile × 2 lanes
    assert cfg.lane_per_tile == 2
    assert cfg.dispatch_policy == DispatchPolicy.HASH_LSB

def test_server_base_config():
    cfg = JasperGCConfig.from_profile(BackendProfile.SERVER_BASE)
    assert cfg.tile_count == 2
    assert cfg.lane_per_tile == 2
    assert cfg.dispatch_policy == DispatchPolicy.CORE_AFFINITY

def test_server_config():
    cfg = JasperGCConfig.from_profile(BackendProfile.SERVER)
    assert cfg.tile_count == 4
    assert cfg.lane_per_tile == 2
    assert cfg.dispatch_policy == DispatchPolicy.HYBRID

def test_extreme_config():
    cfg = JasperGCConfig.from_profile(BackendProfile.EXTREME)
    assert cfg.tile_count == 8
    assert cfg.lane_per_tile == 2
    assert cfg._status_hold is True

def test_illegal_lane_per_tile():
    cfg = JasperGCConfig(lane_per_tile=3)
    errors = cfg.validate()
    assert any("lane_per_tile" in e for e in errors)

def test_illegal_tile_count():
    cfg = JasperGCConfig(tile_count=3)
    errors = cfg.validate()
    assert any("tile_count" in e for e in errors)

def test_illegal_tile_count_non_power2():
    cfg = JasperGCConfig(tile_count=6)
    errors = cfg.validate()
    assert any("tile_count" in e for e in errors)

def test_lite_tile_count_2():
    cfg = JasperGCConfig.from_profile(BackendProfile.LITE)
    cfg.tile_count = 2
    errors = cfg.validate()
    assert any("cannot use tile_count > 1" in e for e in errors)

def test_lite_lane_per_tile_2():
    cfg = JasperGCConfig.from_profile(BackendProfile.LITE)
    cfg.lane_per_tile = 2
    errors = cfg.validate()
    assert any("cannot use lane_per_tile > 1" in e for e in errors)

def test_validate_passes():
    cfg = JasperGCConfig.from_profile(BackendProfile.STANDARD)
    assert cfg.validate() == []

def test_validate_gateway_passes():
    cfg = JasperGCConfig.from_profile(BackendProfile.GATEWAY)
    assert cfg.validate() == []

def test_validate_server_passes():
    cfg = JasperGCConfig.from_profile(BackendProfile.SERVER)
    assert cfg.validate() == []


def test_validate_large_server_scale_passes():
    cfg = JasperGCConfig.from_profile(BackendProfile.SERVER)
    cfg.tile_count = 32
    assert cfg.validate() == []

    cfg = JasperGCConfig.from_profile(BackendProfile.SERVER)
    cfg.tile_count = 64
    assert cfg.validate() == []

def test_extreme_not_default():
    cfg = JasperGCConfig.from_profile(BackendProfile.EXTREME)
    assert cfg._status_hold is True
