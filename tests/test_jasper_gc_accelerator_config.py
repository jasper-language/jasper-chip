import pytest
from rtl.jasper_gc_accelerator_config import (
    JasperGCAcceleratorConfig, AcceleratorProfile, AcceleratorAdapterType
)

def test_lite_config():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_LITE)
    assert cfg.adapter_type == AcceleratorAdapterType.PCIE
    assert cfg.support_compact is False

def test_standard_config():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_STANDARD)
    assert cfg.adapter_type == AcceleratorAdapterType.CHIPLET
    assert cfg.support_rebuild is True

def test_server_config():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    assert cfg.support_compact is True
    assert cfg.adapter_type == AcceleratorAdapterType.CHIPLET

def test_extreme_hold():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_EXTREME)
    assert cfg._status_hold is True

def test_table_custom():
    cfg = JasperGCAcceleratorConfig(profile=AcceleratorProfile.ACCEL_LITE)
    assert cfg.validate() == []  # PCIe adapter allowed even for lite

def test_chiplet_mainline():
    cfg = JasperGCAcceleratorConfig(adapter_type=AcceleratorAdapterType.CHIPLET)
    assert cfg.validate() == []

def test_cxl_future():
    cfg = JasperGCAcceleratorConfig(adapter_type=AcceleratorAdapterType.CXL)
    assert cfg.validate() == []  # future allowed but not implemented

def test_dpu_future():
    cfg = JasperGCAcceleratorConfig(adapter_type=AcceleratorAdapterType.DPU)
    assert cfg.validate() == []  # future allowed but not implemented

def test_pcie_future():
    cfg = JasperGCAcceleratorConfig(adapter_type=AcceleratorAdapterType.PCIE)
    assert cfg.validate() == []  # future allowed but not implemented

def test_extreme_no_hold():
    cfg = JasperGCAcceleratorConfig(profile=AcceleratorProfile.ACCEL_EXTREME, _status_hold=False)
    errors = cfg.validate()
    assert any("_status_hold" in e for e in errors)
