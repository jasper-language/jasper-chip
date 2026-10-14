from amaranth import *
from rtl.jasper_gc_unified_config import JasperGCUnifiedConfig
from rtl.jasper_gc_ip import JasperGCIP
from rtl.jasper_gc_accelerator_ip import JasperGCAcceleratorIP


class JasperGCUnifiedIP(Elaboratable):
    def __init__(self, config: JasperGCUnifiedConfig):
        self.config = config
        bc, ac = config.resolve()
        self._bc = bc
        self._ac = ac

        # ── Backend ports (always present) ──────────────────────────
        self.gc_event_valid = Signal()
        self.gc_event_ready = Signal()
        self.gc_event_type = Signal(4)
        self.gc_event_addr = Signal(32)
        self.gc_event_data = Signal(32)
        self.gc_event_tag = Signal(8)
        self.gc_event_epoch = Signal(8)
        self.gc_event_seq = Signal(8)
        self.gc_event_merge_domain = Signal(4)
        self.core_id = Signal(8)
        self.region_id = Signal(8)
        core_count = bc.cpu_core_count if bc is not None else 1
        self.cpu_event_valid = [Signal() for _ in range(core_count)]
        self.cpu_event_ready = [Signal() for _ in range(core_count)]
        self.cpu_event_type = [Signal(4) for _ in range(core_count)]
        self.cpu_event_addr = [Signal(32) for _ in range(core_count)]
        self.cpu_event_data = [Signal(32) for _ in range(core_count)]
        self.cpu_event_tag = [Signal(8) for _ in range(core_count)]
        self.cpu_event_epoch = [Signal(8) for _ in range(core_count)]
        self.cpu_event_seq = [Signal(8) for _ in range(core_count)]
        self.cpu_region_id = [Signal(8) for _ in range(core_count)]

        self.gc_event1_valid = Signal()
        self.gc_event1_ready = Signal()
        self.gc_event1_type = Signal(4)
        self.gc_event1_addr = Signal(32)
        self.gc_event1_data = Signal(32)
        self.gc_event1_tag = Signal(8)
        self.gc_event1_epoch = Signal(8)
        self.gc_event1_seq = Signal(8)

        self.gc_result_valid = Signal()
        self.gc_result_ready = Signal()
        self.gc_result_data = Signal(32)
        self.gc_result_tag = Signal(8)
        self.gc_result_epoch = Signal(8)
        self.gc_result_seq = Signal(8)
        self.gc_result_merge_domain = Signal(4)
        self.gc_result_status = Signal(4)

        self.current_epoch = Signal(8)
        self.flush = Signal()
        self.flush_epoch = Signal(8)
        self.gc_enable = Signal()
        self.config_lock = Signal()

        # ── Accelerator ports (conditional) ─────────────────────────
        if ac is not None:
            self.acc_cmd_valid = Signal()
            self.acc_cmd_ready = Signal()
            self.acc_cmd_type = Signal(4)
            self.acc_cmd_flags = Signal(8)
            self.acc_cmd_region_base = Signal(32)
            self.acc_cmd_region_size = Signal(32)
            self.acc_cmd_metadata_base = Signal(32)
            self.acc_cmd_forwarding_base = Signal(32)
            self.acc_cmd_remembered_set_base = Signal(32)
            self.acc_cmd_object_table_base = Signal(32)
            self.acc_cmd_epoch = Signal(8)
            self.acc_cmd_merge_domain = Signal(4)
            self.acc_cmd_priority = Signal(2)
            self.acc_cmd_correlation_id = Signal(16)

            self.acc_comp_valid = Signal()
            self.acc_comp_ready = Signal()
            self.acc_comp_status = Signal(3)
            self.acc_comp_correlation_id = Signal(16)
            self.acc_comp_epoch = Signal(8)
            self.acc_comp_merge_domain = Signal(4)
            self.acc_comp_bytes_scanned = Signal(32)
            self.acc_comp_objects_scanned = Signal(32)
            self.acc_comp_live_objects = Signal(32)
            self.acc_comp_dead_objects = Signal(32)
            self.acc_comp_objects_moved = Signal(32)
            self.acc_comp_bytes_moved = Signal(32)
            self.acc_comp_metadata_updates = Signal(32)
            self.acc_comp_error_code = Signal(8)

            self.acc_cap_supported_types = Signal(9)
            self.acc_cap_max_region_size = Signal(32)
            self.acc_cap_max_outstanding = Signal(8)
            self.acc_adapter_type = Signal(2)

    def elaborate(self, platform):
        m = Module()
        bc = self._bc
        ac = self._ac

        # ── Backend sub-block ──────────────────────────────────────────
        backend = JasperGCIP(config=bc)
        m.submodules.backend = backend

        m.d.comb += [
            backend.gc_event_valid.eq(self.gc_event_valid),
            self.gc_event_ready.eq(backend.gc_event_ready),
            backend.gc_event_type.eq(self.gc_event_type),
            backend.gc_event_addr.eq(self.gc_event_addr),
            backend.gc_event_data.eq(self.gc_event_data),
            backend.gc_event_tag.eq(self.gc_event_tag),
            backend.gc_event_epoch.eq(self.gc_event_epoch),
            backend.gc_event_seq.eq(self.gc_event_seq),
            backend.gc_event_merge_domain.eq(self.gc_event_merge_domain),
            backend.core_id.eq(self.core_id),
            backend.region_id.eq(self.region_id),

            backend.gc_event1_valid.eq(self.gc_event1_valid),
            self.gc_event1_ready.eq(backend.gc_event1_ready),
            backend.gc_event1_type.eq(self.gc_event1_type),
            backend.gc_event1_addr.eq(self.gc_event1_addr),
            backend.gc_event1_data.eq(self.gc_event1_data),
            backend.gc_event1_tag.eq(self.gc_event1_tag),
            backend.gc_event1_epoch.eq(self.gc_event1_epoch),
            backend.gc_event1_seq.eq(self.gc_event1_seq),

            self.gc_result_valid.eq(backend.gc_result_valid),
            backend.gc_result_ready.eq(self.gc_result_ready),
            self.gc_result_data.eq(backend.gc_result_data),
            self.gc_result_tag.eq(backend.gc_result_tag),
            self.gc_result_epoch.eq(backend.gc_result_epoch),
            self.gc_result_seq.eq(backend.gc_result_seq),
            self.gc_result_merge_domain.eq(backend.gc_result_merge_domain),
            self.gc_result_status.eq(backend.gc_result_status),

            backend.current_epoch.eq(self.current_epoch),
            backend.flush.eq(self.flush),
            backend.flush_epoch.eq(self.flush_epoch),
            backend.gc_enable.eq(self.gc_enable),
            backend.config_lock.eq(self.config_lock),
        ]
        for i in range(len(self.cpu_event_valid)):
            m.d.comb += [
                backend.cpu_event_valid[i].eq(self.cpu_event_valid[i]),
                self.cpu_event_ready[i].eq(backend.cpu_event_ready[i]),
                backend.cpu_event_type[i].eq(self.cpu_event_type[i]),
                backend.cpu_event_addr[i].eq(self.cpu_event_addr[i]),
                backend.cpu_event_data[i].eq(self.cpu_event_data[i]),
                backend.cpu_event_tag[i].eq(self.cpu_event_tag[i]),
                backend.cpu_event_epoch[i].eq(self.cpu_event_epoch[i]),
                backend.cpu_event_seq[i].eq(self.cpu_event_seq[i]),
                backend.cpu_region_id[i].eq(self.cpu_region_id[i]),
            ]

        # ── Accelerator sub-block (conditional) ────────────────────────
        if ac is not None:
            accel = JasperGCAcceleratorIP(
                config=ac,
                enable_memory=self.config.accelerator_enable_memory,
                memory_model=self.config.accelerator_memory_model,
            )
            m.submodules.accel = accel
            I = accel.iface

            m.d.comb += [
                I.cmd_valid.eq(self.acc_cmd_valid),
                self.acc_cmd_ready.eq(I.cmd_ready),
                I.cmd_type.eq(self.acc_cmd_type),
                I.cmd_flags.eq(self.acc_cmd_flags),
                I.cmd_region_base.eq(self.acc_cmd_region_base),
                I.cmd_region_size.eq(self.acc_cmd_region_size),
                I.cmd_metadata_base.eq(self.acc_cmd_metadata_base),
                I.cmd_forwarding_base.eq(self.acc_cmd_forwarding_base),
                I.cmd_remembered_set_base.eq(self.acc_cmd_remembered_set_base),
                I.cmd_object_table_base.eq(self.acc_cmd_object_table_base),
                I.cmd_epoch.eq(self.acc_cmd_epoch),
                I.cmd_merge_domain.eq(self.acc_cmd_merge_domain),
                I.cmd_priority.eq(self.acc_cmd_priority),
                I.cmd_correlation_id.eq(self.acc_cmd_correlation_id),
                I.current_epoch.eq(self.current_epoch),

                self.acc_comp_valid.eq(I.comp_valid),
                I.comp_ready.eq(self.acc_comp_ready),
                self.acc_comp_status.eq(I.comp_status),
                self.acc_comp_correlation_id.eq(I.comp_correlation_id),
                self.acc_comp_epoch.eq(I.comp_epoch),
                self.acc_comp_merge_domain.eq(I.comp_merge_domain),
                self.acc_comp_bytes_scanned.eq(I.comp_bytes_scanned),
                self.acc_comp_objects_scanned.eq(I.comp_objects_scanned),
                self.acc_comp_live_objects.eq(I.comp_live_objects),
                self.acc_comp_dead_objects.eq(I.comp_dead_objects),
                self.acc_comp_objects_moved.eq(I.comp_objects_moved),
                self.acc_comp_bytes_moved.eq(I.comp_bytes_moved),
                self.acc_comp_metadata_updates.eq(I.comp_metadata_updates),
                self.acc_comp_error_code.eq(I.comp_error_code),

                self.acc_cap_supported_types.eq(I.cap_supported_types),
                self.acc_cap_max_region_size.eq(I.cap_max_region_size),
                self.acc_cap_max_outstanding.eq(I.cap_max_outstanding),
                self.acc_adapter_type.eq(I.adapter_type),
            ]

        return m
