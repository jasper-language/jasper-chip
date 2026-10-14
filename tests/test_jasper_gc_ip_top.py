# tests/test_jasper_gc_ip_top.py
from amaranth import *; from amaranth.back import rtlil
from rtl.jasper_gc_config import JasperGCConfig, BackendProfile
from rtl.jasper_gc_ip import JasperGCIP

def _elab(cfg):
    m = Module()
    m.submodules.dut = JasperGCIP(cfg)
    rtlil.convert(m, ports=[])
    return m.submodules.dut

# --- Elaboration tests (all profiles must elaborate) ---

def test_elab_lite():
    _elab(JasperGCConfig.from_profile(BackendProfile.LITE))

def test_elab_standard():
    _elab(JasperGCConfig.from_profile(BackendProfile.STANDARD))

def test_elab_gateway():
    _elab(JasperGCConfig.from_profile(BackendProfile.GATEWAY))

def test_elab_server_base():
    _elab(JasperGCConfig.from_profile(BackendProfile.SERVER_BASE))

def test_elab_server():
    _elab(JasperGCConfig.from_profile(BackendProfile.SERVER))

def test_elab_extreme():
    _elab(JasperGCConfig.from_profile(BackendProfile.EXTREME))

def test_elab_custom_1x1():
    cfg = JasperGCConfig(lane_per_tile=1, tile_count=1)
    _elab(cfg)

def test_elab_custom_2x4():
    from rtl.jasper_gc_config import DispatchPolicy, MergePolicy, BackpressurePolicy, BackendProfile
    cfg = JasperGCConfig.from_profile(BackendProfile.GATEWAY)
    cfg.tile_count = 4
    _elab(cfg)

# --- Port presence tests ---

def test_elab_has_event_ports():
    dut = _elab(JasperGCConfig.from_profile(BackendProfile.STANDARD))
    assert hasattr(dut, "gc_event_valid")
    assert hasattr(dut, "gc_event_ready")
    assert hasattr(dut, "gc_event_addr")

def test_elab_has_result_ports():
    dut = _elab(JasperGCConfig.from_profile(BackendProfile.STANDARD))
    assert hasattr(dut, "gc_result_valid")
    assert hasattr(dut, "gc_result_ready")

def test_elab_has_dual_event_ports():
    dut = _elab(JasperGCConfig.from_profile(BackendProfile.GATEWAY))
    assert hasattr(dut, "gc_event1_valid")
    assert hasattr(dut, "gc_event1_ready")

def test_elab_cluster_has_epoch_seq_domain():
    dut = _elab(JasperGCConfig.from_profile(BackendProfile.SERVER_BASE))
    # cluster routes epoch/seq/domain through OrderedMerge
    assert hasattr(dut, "gc_result_epoch")
    assert hasattr(dut, "gc_result_seq")
    assert hasattr(dut, "gc_result_merge_domain")

def test_elab_has_control():
    dut = _elab(JasperGCConfig.from_profile(BackendProfile.STANDARD))
    assert hasattr(dut, "flush")
    assert hasattr(dut, "current_epoch")
    assert hasattr(dut, "gc_enable")

def test_elab_debug_guarded():
    cfg = JasperGCConfig.from_profile(BackendProfile.LITE)
    cfg.enable_debug = False
    dut = _elab(cfg)
    # debug_state is still a Signal (just unused)
    assert hasattr(dut, "debug_state")

def test_elab_perf_optional():
    cfg = JasperGCConfig.from_profile(BackendProfile.STANDARD)
    cfg.enable_perf_counters = False
    dut = _elab(cfg)
    assert hasattr(dut, "perf_event_count")

def test_elab_ext_interface_optional():
    cfg = JasperGCConfig.from_profile(BackendProfile.STANDARD)
    cfg.enable_external_gc_interface = False
    dut = _elab(cfg)
    # When disabled, gc_ext should not exist
    assert hasattr(dut, "gc_ext") == False, "ext interface should be absent when disabled"

def test_elab_ext_interface_enabled():
    cfg = JasperGCConfig.from_profile(BackendProfile.SERVER)
    cfg.enable_external_gc_interface = True
    dut = _elab(cfg)
    assert hasattr(dut, "gc_ext"), "ext interface should exist when enabled"
