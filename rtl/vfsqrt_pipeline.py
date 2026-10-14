"""Issue/decode/execute adapter for RISC-V V floating square root."""

from amaranth import Array, Const, Elaboratable, Module, Mux, Signal

from .vfsqrt_decode import VFSqrtDecode
from .vfsqrt_unit import VFSqrtUnit


class VFSqrtPipeline(Elaboratable):
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
        self.vregs = [Signal(128, name=f"vfsqrt_pipe_vreg_{reg}")
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
        m.submodules.decode = decode = VFSqrtDecode(
            xlen=self.xlen, enable_fp32=self.enable_fp32,
            enable_fp64=self.enable_fp64)
        m.submodules.sqrt = sqrt = VFSqrtUnit()
        active = Signal()
        waiting = Signal()
        index = Signal(8)
        vl = Signal(8)
        tail_limit = Signal(8)
        vd = Signal(5)
        vs2 = Signal(5)
        is_f64 = Signal()
        vm = Signal()
        vta = Signal()
        vma = Signal()
        rm = Signal(3)
        flags = Signal(5)
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
            self.write_lane.eq(0), self.write_is_f64.eq(is_f64),
            self.write_data.eq(0), self.fflags_write_valid.eq(0),
            self.fflags_write_value.eq(flags),
            self.vstart_valid.eq(active), self.vstart_value.eq(index),
            self.done.eq(0), sqrt.start.eq(0),
            sqrt.is_f64.eq(is_f64), sqrt.rm.eq(rm),
        ]
        reg_offset = Mux(is_f64, index >> 1, index >> 2)
        src_reg = Signal(6)
        dst_reg = Signal(6)
        m.d.comb += [src_reg.eq(vs2 + reg_offset),
                     dst_reg.eq(vd + reg_offset)]
        lane = Signal(64)
        with m.If(is_f64):
            m.d.comb += lane.eq(
                registers[src_reg].word_select(index[0], 64))
        with m.Else():
            m.d.comb += lane.eq(
                registers[src_reg].word_select(index[:2], 32))
        enabled = vm | registers[0].bit_select(index, 1)
        m.d.comb += [sqrt.a.eq(lane),
                     sqrt.start.eq(active & ~waiting &
                                   (index < vl) & enabled)]
        with m.If(launch):
            m.d.sync += [
                active.eq(1), waiting.eq(0), index.eq(decode.element),
                vl.eq(decode.evl), tail_limit.eq(decode.tail_limit),
                vd.eq(decode.vd), vs2.eq(decode.vs2),
                is_f64.eq(decode.is_f64), vm.eq(decode.vm),
                vta.eq(decode.vta), vma.eq(decode.vma),
                rm.eq(self.frm), flags.eq(0),
            ]
        with m.Elif(active):
            with m.If(index < vl):
                with m.If(~enabled):
                    with m.If(vma):
                        m.d.comb += [self.write_valid.eq(1),
                                     self.write_data.eq(Const(-1, 64))]
                    m.d.sync += index.eq(index + 1)
                with m.Elif(~waiting):
                    m.d.sync += waiting.eq(1)
                with m.Elif(sqrt.done):
                    m.d.comb += [self.write_valid.eq(1),
                                 self.write_data.eq(sqrt.result)]
                    m.d.sync += [flags.eq(flags | sqrt.flags),
                                 waiting.eq(0), index.eq(index + 1)]
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
                m.d.sync += [active.eq(0), waiting.eq(0)]
        m.d.comb += [
            self.write_reg.eq(dst_reg[:5]),
            self.write_lane.eq(Mux(is_f64, index[0], index[:2])),
        ]
        return m
