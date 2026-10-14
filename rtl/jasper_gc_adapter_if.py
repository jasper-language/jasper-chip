# rtl/jasper_gc_adapter_if.py
# Adapter interface stubs for CXL/PCIe/DPU adapter boundaries.
# Signal definitions only -- no implementation logic.
from amaranth import *


class AdapterInterface(Elaboratable):
    """Abstract base for all adapter interfaces. Defines common signals."""
    def __init__(self):
        self.adapter_type = Signal(2)
        self.error_valid = Signal()
        self.error_code = Signal(8)
        self.status_busy = Signal()

    def elaborate(self, platform):
        m = Module()
        return m


class CXLAdapterInterface(AdapterInterface):
    """CXL adapter interface stub -- signal definitions only, no logic.

    Implements the CXL.mem and CXL.io protocol signals at the transaction layer.
    """
    def __init__(self):
        super().__init__()
        # --- CXL.mem request path ---
        self.mem_req_valid = Signal()
        self.mem_req_ready = Signal()
        self.mem_req_addr = Signal(52)
        self.mem_req_is_write = Signal()
        self.mem_req_tag = Signal(16)
        self.mem_req_data = Signal(32)

        # --- CXL.mem response path ---
        self.mem_rsp_valid = Signal()
        self.mem_rsp_ready = Signal()
        self.mem_rsp_tag = Signal(16)
        self.mem_rsp_data = Signal(32)
        self.mem_rsp_error = Signal()

        # --- CXL.io MMIO request path ---
        self.io_req_valid = Signal()
        self.io_req_ready = Signal()
        self.io_req_addr = Signal(52)
        self.io_req_is_write = Signal()
        self.io_req_data = Signal(32)

        # --- CXL.io MMIO response path ---
        self.io_rsp_valid = Signal()
        self.io_rsp_ready = Signal()
        self.io_rsp_data = Signal(32)
        self.io_rsp_error = Signal()

        # --- Doorbell (CXL.io write to CSR BAR) ---
        self.doorbell_valid = Signal()
        self.doorbell_data = Signal(32)

        # --- MSI-X interrupt request ---
        self.msix_valid = Signal()
        self.msix_vector = Signal(5)

        # --- Coherency bias mode ---
        self.bias_mode = Signal()

    def elaborate(self, platform):
        m = Module()
        return m


class PCIeAdapterInterface(AdapterInterface):
    """PCIe adapter interface stub -- signal definitions only, no logic.

    Implements PCIe Transaction Layer Packet (TLP) interface signals:
    - DMA read/write descriptors
    - BAR access (MMIO)
    - MSI-X interrupt request
    - Doorbell register interface
    """
    def __init__(self):
        super().__init__()
        # --- BAR/MMIO request path ---
        self.bar_valid = Signal()
        self.bar_ready = Signal()
        self.bar_addr = Signal(12)
        self.bar_is_write = Signal()
        self.bar_data = Signal(32)

        # --- BAR/MMIO response path ---
        self.bar_rsp_valid = Signal()
        self.bar_rsp_ready = Signal()
        self.bar_rsp_data = Signal(32)

        # --- DMA descriptor fetch ---
        self.dma_desc_valid = Signal()
        self.dma_desc_ready = Signal()
        self.dma_desc_addr = Signal(64)
        self.dma_desc_tag = Signal(10)

        # --- DMA read completion (host->device) ---
        self.dma_tx_valid = Signal()
        self.dma_tx_ready = Signal()
        self.dma_tx_data = Signal(32)
        self.dma_tx_tag = Signal(10)
        self.dma_tx_last = Signal()

        # --- DMA write request (device->host) ---
        self.dma_rx_valid = Signal()
        self.dma_rx_ready = Signal()
        self.dma_rx_addr = Signal(64)
        self.dma_rx_data = Signal(32)
        self.dma_rx_tag = Signal(10)
        self.dma_rx_last = Signal()

        # --- DMA error status ---
        self.dma_error_valid = Signal()
        self.dma_error_code = Signal(3)

        # --- Doorbell register write ---
        self.doorbell_valid = Signal()
        self.doorbell_offset = Signal(12)
        self.doorbell_data = Signal(32)

        # --- MSI-X interrupt request ---
        self.msix_valid = Signal()
        self.msix_vector = Signal(5)

        # --- TLP-level error status (from PCIe core) ---
        self.tlp_ur = Signal()
        self.tlp_ca = Signal()
        self.tlp_crs = Signal()

    def elaborate(self, platform):
        m = Module()
        return m


class DPUAdapterInterface(AdapterInterface):
    """DPU/SmartNIC adapter interface stub -- signal definitions only, no logic.

    Implements network-offload interface signals:
    - RDMA send/recv work requests
    - NVMe-oF command capsules
    - Multi-host context tags
    """
    def __init__(self):
        super().__init__()
        # --- RDMA send work request (device->host) ---
        self.wr_send_valid = Signal()
        self.wr_send_ready = Signal()
        self.wr_send_addr = Signal(64)
        self.wr_send_len = Signal(16)
        self.wr_send_tag = Signal(16)

        # --- RDMA recv work request (host->device) ---
        self.wr_recv_valid = Signal()
        self.wr_recv_ready = Signal()
        self.wr_recv_addr = Signal(64)
        self.wr_recv_len = Signal(16)
        self.wr_recv_tag = Signal(16)

        # --- RDMA completion notification ---
        self.rdma_comp_valid = Signal()
        self.rdma_comp_ready = Signal()
        self.rdma_comp_tag = Signal(16)
        self.rdma_comp_status = Signal(3)

        # --- NVMe-oF command path ---
        self.nvme_cmd_valid = Signal()
        self.nvme_cmd_ready = Signal()
        self.nvme_cmd_opcode = Signal(8)
        self.nvme_cmd_cid = Signal(16)
        self.nvme_cmd_data = Signal(32)

        # --- NVMe-oF completion path ---
        self.nvme_comp_valid = Signal()
        self.nvme_comp_ready = Signal()
        self.nvme_comp_cid = Signal(16)
        self.nvme_comp_status = Signal(8)

        # --- Multi-host context ---
        self.host_id = Signal(4)
        self.host_ctx_valid = Signal()
        self.host_ctx_addr = Signal(64)
        self.host_ctx_tag = Signal(16)

        # --- Per-host command queue interface ---
        self.host_cmdq_valid = Signal()
        self.host_cmdq_ready = Signal()
        self.host_cmdq_data = Signal(32)
        self.host_cmdq_id = Signal(4)

        # --- Doorbell from any host ---
        self.doorbell_valid = Signal()
        self.doorbell_host = Signal(4)

    def elaborate(self, platform):
        m = Module()
        return m
