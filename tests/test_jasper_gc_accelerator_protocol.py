from amaranth import *; from amaranth.back import rtlil
from rtl.jasper_gc_accelerator_config import (
    CmdType, CompletionStatus, AcceleratorAdapterType, AcceleratorProfile, JasperGCAcceleratorConfig
)
from rtl.jasper_gc_accelerator_ip import JasperGCAcceleratorIP

def test_cmd_type_enum():
    assert CmdType.SCAN_REGION.value == 0
    assert CmdType.BACKGROUND_GC_PHASE.value == 8

def test_completion_status_enum():
    assert CompletionStatus.OK.value == 0
    assert CompletionStatus.UNSUPPORTED.value == 5

def test_adapter_type_enum():
    assert AcceleratorAdapterType.CHIPLET.value == 0
    assert AcceleratorAdapterType.PCIE.value == 3

def test_accelerator_ip_elaborates_lite():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_LITE)
    m = Module(); m.submodules.dut = JasperGCAcceleratorIP(cfg)
    rtlil.convert(m, ports=[])

def test_accelerator_ip_elaborates_standard():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_STANDARD)
    m = Module(); m.submodules.dut = JasperGCAcceleratorIP(cfg)
    rtlil.convert(m, ports=[])

def test_accelerator_ip_elaborates_server():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    m = Module(); m.submodules.dut = JasperGCAcceleratorIP(cfg)
    rtlil.convert(m, ports=[])

def test_accelerator_ip_elaborates_extreme():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_EXTREME)
    m = Module(); m.submodules.dut = JasperGCAcceleratorIP(cfg)
    rtlil.convert(m, ports=[])

def test_adapter_type_exposed():
    cfg = JasperGCAcceleratorConfig(adapter_type=AcceleratorAdapterType.CHIPLET)
    m = Module(); m.submodules.dut = JasperGCAcceleratorIP(cfg)
    o = rtlil.convert(m, ports=[])
    assert 'adapter_type' in o
