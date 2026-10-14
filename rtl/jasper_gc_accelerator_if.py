# rtl/jasper_gc_accelerator_if.py
# Unified accelerator interface: command / completion / adapter.
from amaranth import *

class JasperGCAcceleratorIF(Elaboratable):
    """Unified accelerator command/completion interface.
    Not bound to any specific transport (chiplet/CXL/DPU/PCIe).
    """
    def __init__(self, config=None):
        self.config = config
        # Command
        self.cmd_valid = Signal(); self.cmd_ready = Signal()
        self.cmd_type = Signal(4); self.cmd_flags = Signal(8)
        self.cmd_region_base = Signal(32); self.cmd_region_size = Signal(32)
        self.cmd_metadata_base = Signal(32); self.cmd_forwarding_base = Signal(32)
        self.cmd_remembered_set_base = Signal(32)
        self.cmd_object_table_base = Signal(32)
        self.cmd_epoch = Signal(8); self.cmd_merge_domain = Signal(4)
        self.cmd_priority = Signal(2); self.cmd_correlation_id = Signal(16)
        # Completion
        self.comp_valid = Signal(); self.comp_ready = Signal()
        self.comp_status = Signal(3); self.comp_correlation_id = Signal(16)
        self.comp_epoch = Signal(8); self.comp_merge_domain = Signal(4)
        self.comp_bytes_scanned = Signal(32)
        self.comp_objects_scanned = Signal(32)
        self.comp_live_objects = Signal(32); self.comp_dead_objects = Signal(32)
        self.comp_objects_moved = Signal(32); self.comp_bytes_moved = Signal(32)
        self.comp_metadata_updates = Signal(32)
        self.comp_error_code = Signal(8)
        # Capability
        self.cap_supported_types = Signal(9)
        self.cap_max_region_size = Signal(32)
        self.cap_max_outstanding = Signal(8)
        # Current epoch (from Core / control register, NOT from cmd_epoch)
        self.current_epoch = Signal(8)
        # Adapter type (read-only indication)
        self.adapter_type = Signal(2)

    def elaborate(self, platform):
        m = Module()
        # Passthrough: no logic in skeleton
        dummy = Signal()
        m.d.sync += dummy.eq(dummy)
        return m
