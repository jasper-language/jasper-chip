"""Issue/decode/execute adapter for RISC-V V memory instructions."""

from amaranth import Elaboratable, Module, Signal

from .vmemory_decode import VMemoryDecode
from .vmemory_unit import VMemoryUnit


class VMemoryPipeline(Elaboratable):
    def __init__(self, xlen=32):
        self.xlen = xlen
        self.issue_valid = Signal()
        self.insn = Signal(32)
        self.is_load = Signal()
        self.base = Signal(xlen)
        self.stride = Signal(xlen)
        self.vtype = Signal(xlen)
        self.vl = Signal(8)
        self.vlmax = Signal(8)
        self.vstart = Signal(8)
        self.vregs = [Signal(128, name=f"vmem_pipe_vreg_{reg}")
                      for reg in range(32)]

        self.issue_ready = Signal()
        self.redirect = Signal()
        self.illegal = Signal()
        self.busy = Signal()
        self.dmem_grant = Signal()
        self.dmem_error = Signal()
        self.dmem_rdata = Signal(32)
        self.dmem_valid = Signal()
        self.dmem_we = Signal()
        self.dmem_addr = Signal(xlen)
        self.dmem_wdata = Signal(32)
        self.write_valid = Signal()
        self.write_reg = Signal(5)
        self.write_byte = Signal(4)
        self.write_data = Signal(8)
        self.vl_write_valid = Signal()
        self.vl_write_value = Signal(8)
        self.vstart_valid = Signal()
        self.vstart_value = Signal(8)
        self.done = Signal()
        self.execute_trap = Signal()

    def elaborate(self, platform):
        m = Module()
        m.submodules.decode = decode = VMemoryDecode(xlen=self.xlen)
        m.submodules.execute = execute = VMemoryUnit(xlen=self.xlen)
        launch = self.issue_valid & ~execute.active & decode.legal
        m.d.comb += [
            decode.insn.eq(self.insn), decode.is_load.eq(self.is_load),
            decode.vtype.eq(self.vtype), decode.vl.eq(self.vl),
            decode.vlmax.eq(self.vlmax), decode.vstart.eq(self.vstart),
            execute.start.eq(launch), execute.start_load.eq(self.is_load),
            execute.start_indexed.eq(decode.indexed),
            execute.start_strided.eq(decode.strided),
            execute.start_fof.eq(decode.fof),
            execute.start_whole.eq(decode.whole),
            execute.start_mask.eq(decode.mask), execute.start_vm.eq(decode.vm),
            execute.start_vma.eq(decode.vma), execute.start_vta.eq(decode.vta),
            execute.start_base.eq(self.base), execute.start_stride.eq(self.stride),
            execute.start_vreg.eq(decode.vreg),
            execute.start_index_vreg.eq(decode.index_vreg),
            execute.start_eew_bytes.eq(decode.eew_bytes),
            execute.start_index_bytes.eq(decode.index_bytes),
            execute.start_fields.eq(decode.fields),
            execute.start_field_stride.eq(decode.field_stride),
            execute.start_element.eq(decode.element),
            execute.start_evl.eq(decode.evl),
            execute.start_tail_limit.eq(decode.tail_limit),
            *[execute.vregs[reg].eq(self.vregs[reg]) for reg in range(32)],
            execute.dmem_grant.eq(self.dmem_grant),
            execute.dmem_error.eq(self.dmem_error),
            execute.dmem_rdata.eq(self.dmem_rdata),
            self.issue_ready.eq(~execute.active),
            self.redirect.eq(launch),
            self.illegal.eq(self.issue_valid & ~execute.active & ~decode.legal),
            self.busy.eq(execute.active),
            self.dmem_valid.eq(execute.dmem_valid),
            self.dmem_we.eq(execute.dmem_we),
            self.dmem_addr.eq(execute.dmem_addr),
            self.dmem_wdata.eq(execute.dmem_wdata),
            self.write_valid.eq(execute.write_valid),
            self.write_reg.eq(execute.write_reg),
            self.write_byte.eq(execute.write_byte),
            self.write_data.eq(execute.write_data),
            self.vl_write_valid.eq(execute.vl_write_valid),
            self.vl_write_value.eq(execute.vl_write_value),
            self.vstart_valid.eq(execute.vstart_valid),
            self.vstart_value.eq(execute.vstart_value),
            self.done.eq(execute.done),
            self.execute_trap.eq(execute.trap),
        ]
        return m
