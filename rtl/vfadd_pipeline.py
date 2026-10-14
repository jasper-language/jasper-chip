"""Issue/decode/execute adapter for RISC-V V floating add/subtract."""

from amaranth import Array, Const, Elaboratable, Module, Mux, Signal

from .vfadd_decode import VFAddDecode
from .vfadd_unit import VFAddUnit


class VFAddPipeline(Elaboratable):
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
        self.vregs = [Signal(128, name=f"vfadd_pipe_vreg_{reg}")
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
        m.submodules.decode = decode = VFAddDecode(
            xlen=self.xlen, enable_fp32=self.enable_fp32,
            enable_fp64=self.enable_fp64)
        m.submodules.add = add = VFAddUnit()
        active = Signal()
        index = Signal(8)
        vl = Signal(8)
        tail_limit = Signal(8)
        vd = Signal(5)
        vs2 = Signal(5)
        vs1 = Signal(5)
        scalar = Signal(64)
        is_vv = Signal()
        subtract = Signal()
        reverse = Signal()
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
            decode.scalar.eq(self.scalar), self.issue_ready.eq(~active),
            self.redirect.eq(launch),
            self.illegal.eq(self.issue_valid & ~active & decode.match &
                            ~decode.legal), self.busy.eq(active),
            self.write_valid.eq(0), self.write_reg.eq(0),
            self.write_lane.eq(0), self.write_is_f64.eq(is_f64),
            self.write_data.eq(0), self.fflags_write_valid.eq(0),
            self.fflags_write_value.eq(flags),
            self.vstart_valid.eq(active), self.vstart_value.eq(index),
            self.done.eq(0), add.is_f64.eq(is_f64), add.rm.eq(rm),
        ]
        reg_offset = Mux(is_f64, index >> 1, index >> 2)
        src2_reg = Signal(6)
        src1_reg = Signal(6)
        dst_reg = Signal(6)
        m.d.comb += [src2_reg.eq(vs2 + reg_offset),
                     src1_reg.eq(vs1 + reg_offset),
                     dst_reg.eq(vd + reg_offset)]
        src2 = Signal(64)
        src1 = Signal(64)
        with m.If(is_f64):
            m.d.comb += [
                src2.eq(registers[src2_reg].word_select(index[0], 64)),
                src1.eq(registers[src1_reg].word_select(index[0], 64)),
            ]
        with m.Else():
            m.d.comb += [
                src2.eq(registers[src2_reg].word_select(index[:2], 32)),
                src1.eq(registers[src1_reg].word_select(index[:2], 32)),
            ]
        rhs = Mux(is_vv, src1, scalar)
        sign_mask = Mux(is_f64, Const(1 << 63, 64), Const(1 << 31, 64))
        m.d.comb += [
            add.a.eq(Mux(reverse, scalar, src2)),
            add.b.eq(Mux(reverse, src2 ^ sign_mask,
                         Mux(subtract, rhs ^ sign_mask, rhs))),
        ]
        enabled = vm | registers[0].bit_select(index, 1)
        with m.If(launch):
            m.d.sync += [
                active.eq(1), index.eq(decode.element), vl.eq(decode.evl),
                tail_limit.eq(decode.tail_limit), vd.eq(decode.vd),
                vs2.eq(decode.vs2), vs1.eq(decode.vs1),
                scalar.eq(decode.scalar_value), is_vv.eq(decode.is_vv),
                subtract.eq(decode.subtract), reverse.eq(decode.reverse),
                is_f64.eq(decode.is_f64), vm.eq(decode.vm),
                vta.eq(decode.vta), vma.eq(decode.vma),
                rm.eq(self.frm), flags.eq(0),
            ]
        with m.Elif(active):
            with m.If(index < vl):
                with m.If(enabled):
                    m.d.comb += [self.write_valid.eq(1),
                                 self.write_data.eq(add.result)]
                    m.d.sync += flags.eq(flags | add.flags)
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
        m.d.comb += [
            self.write_reg.eq(dst_reg[:5]),
            self.write_lane.eq(Mux(is_f64, index[0], index[:2])),
        ]
        return m
