# rtl/jasper_gc_accelerator_config.py
# Jasper-GC Accelerator configuration and types.
from dataclasses import dataclass
from enum import Enum

class AcceleratorProfile(Enum):
    ACCEL_LITE = "accel_lite"
    ACCEL_STANDARD = "accel_standard"
    ACCEL_SERVER = "accel_server"
    ACCEL_EXTREME = "accel_extreme"

class AcceleratorAdapterType(Enum):
    CHIPLET = 0       # CPU-package / chiplet (MAINLINE)
    CXL = 1           # CXL.mem coherent (FUTURE_EXPERIMENT)
    DPU = 2           # DPU/SmartNIC (FUTURE_GATEWAY_EXPERIMENT)
    PCIE = 3          # PCIe DMA (FUTURE_BACKGROUND_BATCH)

class CmdType(Enum):
    SCAN_REGION = 0
    SWEEP_REGION = 1
    COMPACT_REGION = 2
    REBUILD_METADATA = 3
    CLEAN_REMEMBERED_SET = 4
    PREFETCH_METADATA = 5
    RELOCATE_COLD_OBJECTS = 6
    LARGE_OBJECT_MOVE = 7
    BACKGROUND_GC_PHASE = 8

class CompletionStatus(Enum):
    OK = 0
    RETRY = 1
    BUSY = 2
    ABORTED = 3
    ERROR = 4
    UNSUPPORTED = 5

@dataclass
class JasperGCAcceleratorConfig:
    profile: AcceleratorProfile = AcceleratorProfile.ACCEL_STANDARD
    adapter_type: AcceleratorAdapterType = AcceleratorAdapterType.CHIPLET
    command_queue_depth: int = 8
    completion_queue_depth: int = 8
    max_region_size: int = 0x10000000  # 256MB
    max_outstanding_commands: int = 4
    support_scan: bool = True
    support_sweep: bool = True
    support_compact: bool = False
    support_rebuild: bool = False
    support_relocate: bool = False
    support_large_move: bool = False
    support_bg_phase: bool = False
    enable_coherent_access: bool = True
    enable_debug: bool = False
    _status_hold: bool = False

    def validate(self) -> list[str]:
        errors = []
        if self.adapter_type == AcceleratorAdapterType.CHIPLET:
            pass  # MAINLINE — always allowed
        elif self.adapter_type == AcceleratorAdapterType.CXL:
            pass  # FUTURE_EXPERIMENT — allowed but not implemented
        elif self.adapter_type == AcceleratorAdapterType.DPU:
            pass  # FUTURE_GATEWAY_EXPERIMENT — allowed but not implemented
        elif self.adapter_type == AcceleratorAdapterType.PCIE:
            pass  # FUTURE_BACKGROUND_BATCH — allowed but not implemented
        if self.profile == AcceleratorProfile.ACCEL_EXTREME and not self._status_hold:
            errors.append("ACCEL_EXTREME requires _status_hold=True")
        return errors

    @classmethod
    def from_profile(cls, profile: AcceleratorProfile) -> 'JasperGCAcceleratorConfig':
        presets = {
            AcceleratorProfile.ACCEL_LITE: cls(
                profile=profile,
                command_queue_depth=4, completion_queue_depth=4,
                max_outstanding_commands=2,
                support_compact=False, support_rebuild=False,
                support_relocate=False, support_large_move=False,
                support_bg_phase=False, enable_coherent_access=False,
                adapter_type=AcceleratorAdapterType.PCIE,
            ),
            AcceleratorProfile.ACCEL_STANDARD: cls(
                profile=profile,
                command_queue_depth=8, completion_queue_depth=8,
                max_outstanding_commands=4,
                support_compact=False, support_rebuild=True,
                support_relocate=False, support_large_move=False,
                support_bg_phase=False, enable_coherent_access=True,
                adapter_type=AcceleratorAdapterType.CHIPLET,
            ),
            AcceleratorProfile.ACCEL_SERVER: cls(
                profile=profile,
                command_queue_depth=16, completion_queue_depth=16,
                max_outstanding_commands=8,
                support_compact=True, support_rebuild=True,
                support_relocate=True, support_large_move=False,
                support_bg_phase=True, enable_coherent_access=True,
                adapter_type=AcceleratorAdapterType.CHIPLET,
            ),
            AcceleratorProfile.ACCEL_EXTREME: cls(
                profile=profile,
                command_queue_depth=32, completion_queue_depth=32,
                max_outstanding_commands=16,
                support_compact=True, support_rebuild=True,
                support_relocate=True, support_large_move=True,
                support_bg_phase=True, enable_coherent_access=True,
                adapter_type=AcceleratorAdapterType.CHIPLET,
                _status_hold=True,
            ),
        }
        return presets[profile]
