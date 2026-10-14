# tests/test_jasper_gc_ip_profiles.py
from rtl.jasper_gc_config import JasperGCConfig, BackendProfile

def _check(cfg, tiles, lanes):
    assert cfg.tile_count == tiles, f"tiles {cfg.tile_count} != {tiles}"
    assert cfg.lane_per_tile == lanes, f"lanes {cfg.lane_per_tile} != {lanes}"

def test_profile_lite_1x1():
    _check(JasperGCConfig.from_profile(BackendProfile.LITE), 1, 1)

def test_profile_standard_1x1():
    _check(JasperGCConfig.from_profile(BackendProfile.STANDARD), 1, 1)

def test_profile_standard_plus_1x1():
    _check(JasperGCConfig.from_profile(BackendProfile.STANDARD_PLUS), 1, 1)

def test_profile_gateway_2x1():
    _check(JasperGCConfig.from_profile(BackendProfile.GATEWAY), 1, 2)

def test_profile_server_base_2x2():
    _check(JasperGCConfig.from_profile(BackendProfile.SERVER_BASE), 2, 2)

def test_profile_server_2x4():
    _check(JasperGCConfig.from_profile(BackendProfile.SERVER), 4, 2)

def test_profile_extreme_hold():
    cfg = JasperGCConfig.from_profile(BackendProfile.EXTREME)
    _check(cfg, 8, 2)
    assert cfg._status_hold is True
