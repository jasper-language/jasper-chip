from amaranth import *; from amaranth.back import rtlil
from rtl.jasper_gc_accelerator_if import JasperGCAcceleratorIF

def test_cmd_ports_exist():
    dut = JasperGCAcceleratorIF()
    for sig in ['cmd_valid', 'cmd_ready', 'cmd_type', 'cmd_region_base',
                'cmd_epoch', 'cmd_correlation_id']:
        assert hasattr(dut, sig), f"missing {sig}"

def test_comp_ports_exist():
    dut = JasperGCAcceleratorIF()
    for sig in ['comp_valid', 'comp_ready', 'comp_status', 'comp_correlation_id',
                'comp_epoch', 'comp_bytes_scanned']:
        assert hasattr(dut, sig), f"missing {sig}"

def test_cap_ports_exist():
    dut = JasperGCAcceleratorIF()
    for sig in ['cap_supported_types', 'cap_max_region_size', 'cap_max_outstanding']:
        assert hasattr(dut, sig), f"missing {sig}"

def test_adapter_type_exists():
    dut = JasperGCAcceleratorIF()
    assert hasattr(dut, 'adapter_type')

def test_elaborates():
    m = Module(); m.submodules.dut = JasperGCAcceleratorIF()
    rtlil.convert(m, ports=[])
