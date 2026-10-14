import contextlib
import io

from amaranth import *; from amaranth.back import rtlil
from rtl.jasper_gc_adapter_if import (
    AdapterInterface,
    CXLAdapterInterface,
    PCIeAdapterInterface,
    DPUAdapterInterface,
)

_BASE_SIGNALS = {'adapter_type', 'error_valid', 'error_code', 'status_busy'}


def _transport_specific_names(iface_class):
    """Return set of signal names beyond those inherited from AdapterInterface."""
    inst = iface_class()
    all_sigs = set(vars(inst).keys()) - _BASE_SIGNALS
    return {s for s in all_sigs if not s.startswith('_') and s in inst.__dict__}


def test_cxl_elab():
    m = Module(); m.submodules.dut = CXLAdapterInterface()
    rtlil.convert(m, ports=[])


def test_pcie_elab():
    m = Module(); m.submodules.dut = PCIeAdapterInterface()
    rtlil.convert(m, ports=[])


def test_dpu_elab():
    m = Module(); m.submodules.dut = DPUAdapterInterface()
    rtlil.convert(m, ports=[])


def test_interface_unique_signals():
    with contextlib.redirect_stderr(io.StringIO()):
        cxl = _transport_specific_names(CXLAdapterInterface)
        pcie = _transport_specific_names(PCIeAdapterInterface)
        dpu = _transport_specific_names(DPUAdapterInterface)
    assert len(cxl) >= 5, f"CXL should define >=5 transport-specific signals, got {len(cxl)}"
    assert len(pcie) >= 5, f"PCIe should define >=5 transport-specific signals, got {len(pcie)}"
    assert len(dpu) >= 5, f"DPU should define >=5 transport-specific signals, got {len(dpu)}"
    assert cxl != pcie, "CXL and PCIe signal sets must differ"
    assert pcie != dpu, "PCIe and DPU signal sets must differ"
    assert dpu != cxl, "DPU and CXL signal sets must differ"

    assert any('mem_' in s for s in cxl), "CXL should have mem_* signals"
    assert any('io_' in s for s in cxl), "CXL should have io_* signals"
    assert any('bar_' in s or 'dma_' in s or 'tlp_' in s for s in pcie), \
        "PCIe should have bar_/dma_/tlp_* signals"
    assert any('wr_' in s or 'nvme_' in s or 'rdma_' in s or 'host_' in s for s in dpu), \
        "DPU should have wr_/nvme_/rdma_/host_* signals"


def test_inheritance():
    assert issubclass(CXLAdapterInterface, AdapterInterface)
    assert issubclass(PCIeAdapterInterface, AdapterInterface)
    assert issubclass(DPUAdapterInterface, AdapterInterface)
    with contextlib.redirect_stderr(io.StringIO()):
        cxl = CXLAdapterInterface()
        pcie = PCIeAdapterInterface()
        dpu = DPUAdapterInterface()
    for inst in (cxl, pcie, dpu):
        assert hasattr(inst, 'adapter_type')
        assert hasattr(inst, 'error_valid')
        assert hasattr(inst, 'error_code')
        assert hasattr(inst, 'status_busy')
