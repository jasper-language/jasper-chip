"""Complete issue/decode/execute adapter for RISC-V V conversions."""

from amaranth import Array, Cat, Const, Elaboratable, Module, Mux, Signal

from .vfcvt_decode import VFCvtDecode
from .vfcvt_float_to_int_unit import VFFloatToIntRTZUnit
from .vfcvt_unit import VFIntToFloatUnit
from .vfncvt_float_unit import VFNarrowFloatUnit
from .vfwcvt_float_unit import VFWidenFloatUnit


class VFCvtPipeline(Elaboratable):
    def __init__(self, xlen=32, enable_fp32=True, enable_fp64=True):
        self.xlen = xlen
        self.enable_fp32 = enable_fp32
        self.enable_fp64 = enable_fp64
        self.issue_valid = Signal()
        self.insn = Signal(32)
        self.vtype = Signal(xlen)
        self.vl = Signal(8)
        self.vlmax = Signal(8)
        self.vstart = Signal(8)
        self.frm = Signal(3)
        self.vregs = [Signal(128, name=f"vfcvt_pipe_vreg_{reg}")
                      for reg in range(32)]
        self.issue_ready = Signal()
        self.redirect = Signal()
        self.illegal = Signal()
        self.busy = Signal()
        self.write_valid = Signal()
        self.write_reg = Signal(5)
        self.write_lane = Signal(2)
        self.write_is_f64 = Signal()
        self.write_data = Signal(64)
        self.fflags_write_valid = Signal()
        self.fflags_write_value = Signal(5)
        self.vstart_valid = Signal()
        self.vstart_value = Signal(8)
        self.done = Signal()

    def elaborate(self, platform):
        m = Module()
        m.submodules.decode = decode = VFCvtDecode(
            xlen=self.xlen, enable_fp32=self.enable_fp32,
            enable_fp64=self.enable_fp64)
        m.submodules.itof = itof = VFIntToFloatUnit()
        m.submodules.ftoi = ftoi = VFFloatToIntRTZUnit()
        m.submodules.narrow = narrow = VFNarrowFloatUnit()
        m.submodules.widen = widen = VFWidenFloatUnit()
        active = Signal()
        index = Signal(8)
        vl = Signal(8)
        tail_limit = Signal(8)
        vd = Signal(5)
        vs2 = Signal(5)
        mode = Signal(2)
        to_int = Signal()
        int_to_float = Signal()
        float_to_float = Signal()
        unsigned = Signal()
        fixed_rtz = Signal()
        round_odd = Signal()
        input_f64 = Signal()
        output_f64 = Signal()
        vm = Signal()
        vta = Signal()
        vma = Signal()
        rm = Signal(3)
        flags = Signal(5)
        snapshot = Array(Signal(128, name=f"vfcvt_pipe_snapshot_{reg}")
                         for reg in range(8))
        launch = self.issue_valid & ~active & decode.legal
        registers = Array(self.vregs)
        m.d.comb += [
            decode.insn.eq(self.insn), decode.vtype.eq(self.vtype),
            decode.vl.eq(self.vl), decode.vlmax.eq(self.vlmax),
            decode.vstart.eq(self.vstart), decode.frm.eq(self.frm),
            self.issue_ready.eq(~active), self.redirect.eq(launch),
            self.illegal.eq(self.issue_valid & ~active & decode.match &
                            ~decode.legal), self.busy.eq(active),
            self.write_valid.eq(0), self.write_reg.eq(0),
            self.write_lane.eq(0), self.write_is_f64.eq(output_f64),
            self.write_data.eq(0), self.fflags_write_valid.eq(0),
            self.fflags_write_value.eq(flags),
            self.vstart_valid.eq(active), self.vstart_value.eq(index),
            self.done.eq(0),
        ]

        source_offset = Mux(mode == VFCvtDecode.NARROW, index >> 1,
                            Mux(mode == VFCvtDecode.WIDEN, index >> 2,
                                Mux(input_f64, index >> 1, index >> 2)))
        dest_offset = Mux(output_f64, index >> 1, index >> 2)
        source_data = snapshot[source_offset]
        lane = Signal(64)
        with m.If(input_f64):
            m.d.comb += lane.eq(source_data.word_select(index[0], 64))
        with m.Else():
            m.d.comb += lane.eq(source_data.word_select(index[:2], 32))
        signed_input = Cat(lane[:32],
                           Mux(unsigned | ~lane[31], Const(0, 32),
                               Const(-1, 32)))
        m.d.comb += [
            itof.value.eq(Mux(mode == VFCvtDecode.WIDEN, signed_input, lane)),
            itof.is_f64.eq(output_f64),
            itof.int64.eq(output_f64 | (mode == VFCvtDecode.NARROW)),
            itof.unsigned.eq(unsigned), itof.rm.eq(rm),
            ftoi.value.eq(lane), ftoi.is_f64.eq(input_f64),
            ftoi.int64.eq(output_f64), ftoi.unsigned.eq(unsigned),
            ftoi.rm.eq(Mux(fixed_rtz, 1, rm)),
            narrow.value.eq(lane), narrow.rm.eq(rm),
            narrow.round_odd.eq(round_odd), widen.value.eq(lane[:32]),
        ]
        result = Mux(float_to_float,
                     Mux(mode == VFCvtDecode.WIDEN, widen.result,
                         narrow.result),
                     Mux(to_int, ftoi.result, itof.result))
        result_flags = Mux(float_to_float,
                           Mux(mode == VFCvtDecode.WIDEN, widen.flags,
                               narrow.flags),
                           Mux(to_int, ftoi.flags, itof.flags))
        enabled = vm | registers[0].bit_select(index, 1)
        dst_reg = Signal(6)
        m.d.comb += [dst_reg.eq(vd + dest_offset),
                     self.write_reg.eq(dst_reg[:5]),
                     self.write_lane.eq(Mux(output_f64, index[0], index[:2]))]

        with m.If(launch):
            m.d.sync += [
                active.eq(1), index.eq(decode.element), vl.eq(decode.evl),
                tail_limit.eq(decode.tail_limit), vd.eq(decode.vd),
                vs2.eq(decode.vs2), mode.eq(decode.mode),
                to_int.eq(decode.to_int),
                int_to_float.eq(decode.int_to_float),
                float_to_float.eq(decode.float_to_float),
                unsigned.eq(decode.unsigned),
                fixed_rtz.eq(decode.fixed_rtz),
                round_odd.eq(decode.round_odd),
                input_f64.eq(decode.input_f64),
                output_f64.eq(decode.output_f64), vm.eq(decode.vm),
                vta.eq(decode.vta), vma.eq(decode.vma),
                rm.eq(self.frm), flags.eq(0),
                *[snapshot[reg].eq(registers[decode.vs2 + reg])
                  for reg in range(8)],
            ]
        with m.Elif(active):
            with m.If(index < vl):
                with m.If(enabled):
                    m.d.comb += [self.write_valid.eq(1),
                                 self.write_data.eq(result)]
                    m.d.sync += flags.eq(flags | result_flags)
                with m.Elif(vma):
                    m.d.comb += [self.write_valid.eq(1),
                                 self.write_data.eq(Const(-1, 64))]
                m.d.sync += index.eq(index + 1)
            with m.Elif(index < tail_limit):
                with m.If(vta):
                    m.d.comb += [self.write_valid.eq(1),
                                 self.write_data.eq(Const(-1, 64))]
                m.d.sync += index.eq(index + 1)
            with m.Else():
                m.d.comb += [self.fflags_write_valid.eq(flags.any()),
                             self.fflags_write_value.eq(flags),
                             self.vstart_valid.eq(1),
                             self.vstart_value.eq(0), self.done.eq(1)]
                m.d.sync += active.eq(0)
        return m
