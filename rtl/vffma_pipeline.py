"""Issue/decode/execute adapter for RISC-V V fused floating operations."""

from amaranth import Array, Const, Elaboratable, Module, Mux, Signal

from .vffma_decode import VFFMADecode
from .vffma_unit import VFFMAUnit


class VFFMAPipeline(Elaboratable):
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
        self.scalar = Signal(64)
        self.vregs = [Signal(128, name=f"vffma_pipe_vreg_{reg}")
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
        self.vstart_clear = Signal()
        self.done = Signal()

    def elaborate(self, platform):
        m = Module()
        m.submodules.decode = decode = VFFMADecode(
            xlen=self.xlen, enable_fp32=self.enable_fp32,
            enable_fp64=self.enable_fp64)
        m.submodules.fma = fma = VFFMAUnit()

        active = Signal()
        index = Signal(8)
        vl = Signal(8)
        tail_limit = Signal(8)
        vd = Signal(5)
        vs2 = Signal(5)
        vs1 = Signal(5)
        scalar = Signal(64)
        is_vv = Signal()
        is_f64 = Signal()
        widen = Signal()
        accumulate = Signal()
        multiply_only = Signal()
        add_only = Signal()
        wide_vs2 = Signal()
        negate_product = Signal()
        negate_addend = Signal()
        vm = Signal()
        vta = Signal()
        vma = Signal()
        rm = Signal(3)
        flags = Signal(5)

        launch = self.issue_valid & ~active & decode.legal
        m.d.comb += [
            decode.insn.eq(self.insn), decode.vtype.eq(self.vtype),
            decode.vl.eq(self.vl), decode.vlmax.eq(self.vlmax),
            decode.vstart.eq(self.vstart), decode.frm.eq(self.frm),
            decode.scalar.eq(self.scalar), self.issue_ready.eq(~active),
            self.redirect.eq(launch),
            self.illegal.eq(self.issue_valid & ~active & decode.match &
                            ~decode.legal),
            self.busy.eq(active), self.write_valid.eq(0),
            self.write_reg.eq(0), self.write_lane.eq(0),
            self.write_is_f64.eq(0), self.write_data.eq(0),
            self.fflags_write_valid.eq(0),
            self.fflags_write_value.eq(flags),
            self.vstart_clear.eq(0), self.done.eq(0),
        ]

        src_offset = Mux(widen | ~is_f64, index >> 2, index >> 1)
        src2_offset = Mux(wide_vs2, index >> 1, src_offset)
        dst_offset = Mux(widen | is_f64, index >> 1, index >> 2)
        src1_reg = Signal(6)
        src2_reg = Signal(6)
        dst_reg = Signal(6)
        m.d.comb += [src1_reg.eq(vs1 + src_offset),
                     src2_reg.eq(vs2 + src2_offset),
                     dst_reg.eq(vd + dst_offset)]
        registers = Array(self.vregs)
        src1_value = Signal(64)
        src2_value = Signal(64)
        dst_value = Signal(64)
        with m.If(widen | ~is_f64):
            m.d.comb += src1_value.eq(
                registers[src1_reg].word_select(index[:2], 32))
        with m.Else():
            m.d.comb += src1_value.eq(
                registers[src1_reg].word_select(index[0], 64))
        with m.If(wide_vs2 | is_f64):
            m.d.comb += src2_value.eq(
                registers[src2_reg].word_select(index[0], 64))
        with m.Else():
            m.d.comb += src2_value.eq(
                registers[src2_reg].word_select(index[:2], 32))
        with m.If(widen | is_f64):
            m.d.comb += dst_value.eq(
                registers[dst_reg].word_select(index[0], 64))
        with m.Else():
            m.d.comb += dst_value.eq(
                registers[dst_reg].word_select(index[:2], 32))

        one = Mux(is_f64, Const(0x3ff0000000000000, 64),
                  Const(0x3f800000, 64))
        zero = Const(0, 64)
        a = Mux(is_vv, src1_value, scalar)
        b = Mux(add_only, one,
                Mux(accumulate | multiply_only, src2_value, dst_value))
        c = Mux(add_only, src2_value,
                Mux(multiply_only, zero,
                    Mux(accumulate, dst_value, src2_value)))
        m.d.comb += [
            fma.a.eq(a), fma.b.eq(b), fma.c.eq(c),
            fma.is_f64.eq(is_f64), fma.widen.eq(widen),
            fma.widen_addend.eq(add_only & ~wide_vs2),
            fma.negate_product.eq(negate_product),
            fma.negate_addend.eq(negate_addend), fma.rm.eq(rm),
        ]

        enabled = vm | registers[0].bit_select(index, 1)
        in_body = index < vl
        in_tail = (index >= vl) & (index < tail_limit)
        write_element = (in_body & (enabled | vma)) | (in_tail & vta)
        result = Mux((in_body & ~enabled & vma) | (in_tail & vta),
                     Const(-1, 64), fma.result)
        m.d.comb += [
            self.write_valid.eq(active & write_element),
            self.write_reg.eq(dst_reg[:5]),
            self.write_lane.eq(Mux(widen | is_f64, index[0], index[:2])),
            self.write_is_f64.eq(widen | is_f64),
            self.write_data.eq(result),
        ]

        with m.If(launch):
            m.d.sync += [
                active.eq(1), index.eq(decode.element), vl.eq(decode.evl),
                tail_limit.eq(decode.tail_limit), vd.eq(decode.vd),
                vs2.eq(decode.vs2), vs1.eq(decode.vs1),
                scalar.eq(decode.scalar_value), is_vv.eq(decode.is_vv),
                is_f64.eq(decode.is_f64), widen.eq(decode.widen),
                accumulate.eq(decode.accumulate),
                multiply_only.eq(decode.multiply_only),
                add_only.eq(decode.add_only), wide_vs2.eq(decode.wide_vs2),
                negate_product.eq(decode.negate_product),
                negate_addend.eq(decode.negate_addend), vm.eq(decode.vm),
                vta.eq(decode.vta), vma.eq(decode.vma), rm.eq(self.frm),
                flags.eq(0),
            ]
        with m.Elif(active):
            with m.If(index < tail_limit):
                with m.If(in_body & enabled):
                    m.d.sync += flags.eq(flags | fma.flags)
                m.d.sync += index.eq(index + 1)
            with m.Else():
                m.d.comb += [
                    self.fflags_write_valid.eq(flags.any()),
                    self.fflags_write_value.eq(flags),
                    self.vstart_clear.eq(1), self.done.eq(1),
                ]
                m.d.sync += active.eq(0)
        return m
