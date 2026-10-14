"""Reusable byte-stepped RISC-V V memory execution engine."""

from amaranth import Array, Cat, Const, Elaboratable, Module, Mux, Signal


class VMemoryUnit(Elaboratable):
    def __init__(self, xlen=32):
        self.xlen = xlen
        self.start = Signal()
        self.start_load = Signal()
        self.start_indexed = Signal()
        self.start_strided = Signal()
        self.start_fof = Signal()
        self.start_whole = Signal()
        self.start_mask = Signal()
        self.start_vm = Signal()
        self.start_vma = Signal()
        self.start_vta = Signal()
        self.start_base = Signal(xlen)
        self.start_stride = Signal(xlen)
        self.start_vreg = Signal(5)
        self.start_index_vreg = Signal(5)
        self.start_eew_bytes = Signal(4)
        self.start_index_bytes = Signal(4)
        self.start_fields = Signal(4)
        self.start_field_stride = Signal(4)
        self.start_element = Signal(8)
        self.start_evl = Signal(8)
        self.start_tail_limit = Signal(8)

        self.vregs = [Signal(128, name=f"vmem_vreg_{reg}")
                      for reg in range(32)]
        self.dmem_grant = Signal()
        self.dmem_error = Signal()
        self.dmem_rdata = Signal(32)
        self.dmem_valid = Signal()
        self.dmem_we = Signal()
        self.dmem_addr = Signal(xlen)
        self.dmem_wdata = Signal(32)

        self.active = Signal()
        self.trap = Signal()
        self.done = Signal()
        self.write_valid = Signal()
        self.write_reg = Signal(5)
        self.write_byte = Signal(4)
        self.write_data = Signal(8)
        self.vl_write_valid = Signal()
        self.vl_write_value = Signal(8)
        self.vstart_valid = Signal()
        self.vstart_value = Signal(8)

    def elaborate(self, platform):
        m = Module()
        vregs = Array(self.vregs)
        active = Signal()
        load = Signal()
        indexed = Signal()
        strided = Signal()
        fof = Signal()
        whole = Signal()
        mask = Signal()
        vm = Signal()
        vma = Signal()
        vta = Signal()
        base = Signal(self.xlen)
        stride = Signal(self.xlen)
        vreg = Signal(5)
        index_vreg = Signal(5)
        eew_bytes = Signal(4)
        index_bytes = Signal(4)
        fields = Signal(4)
        field_stride = Signal(4)
        element = Signal(8)
        field = Signal(4)
        byte = Signal(4)
        evl = Signal(8)
        tail_limit = Signal(8)
        tail = Signal()

        index_flat = Signal(1024)
        index_value = Signal(self.xlen)
        field_base = Signal(6)
        data_offset = Signal(12)
        data_reg_offset = Signal(6)
        data_byte = Signal(4)
        store_byte = Signal(8)
        element_enabled = Signal()
        address = Signal(self.xlen)
        request = Signal()
        load_byte = Signal(8)

        m.d.comb += [
            self.active.eq(active), self.trap.eq(0), self.done.eq(0),
            self.write_valid.eq(0), self.write_reg.eq(field_base + data_reg_offset),
            self.write_byte.eq(data_byte), self.write_data.eq(0),
            self.vl_write_valid.eq(0), self.vl_write_value.eq(element),
            self.vstart_valid.eq(active), self.vstart_value.eq(element),
            index_flat.eq(Cat(*[vregs[index_vreg + reg] for reg in range(8)])),
            index_value.eq(Mux(index_bytes == 1,
                index_flat.word_select(element, 8),
                Mux(index_bytes == 2, index_flat.word_select(element, 16),
                    Mux(index_bytes == 4,
                        index_flat.word_select(element, 32),
                        index_flat.word_select(element, 64))))),
            field_base.eq(vreg + field * field_stride),
            data_offset.eq(element * eew_bytes + byte),
            data_reg_offset.eq(data_offset >> 4),
            data_byte.eq(data_offset[:4]),
            store_byte.eq(vregs[field_base + data_reg_offset].word_select(
                data_byte, 8)),
            element_enabled.eq(whole | mask | vm |
                               vregs[0].bit_select(element, 1)),
            address.eq(Mux(indexed,
                base + index_value + field * eew_bytes + byte,
                Mux(strided,
                    base + element * stride + field * eew_bytes + byte,
                    base + (element * fields + field) * eew_bytes + byte))),
            load_byte.eq(self.dmem_rdata.word_select(address[:2], 8)),
            request.eq(active & ~tail & (element < evl) & element_enabled),
            self.dmem_valid.eq(request), self.dmem_we.eq(~load & request),
            self.dmem_addr.eq(address),
            self.dmem_wdata.eq(
                (self.dmem_rdata &
                 ~(Const(0xff, 32) << (address[:2] << 3))) |
                (store_byte << (address[:2] << 3))),
        ]

        with m.If(self.start & ~active):
            m.d.sync += [
                active.eq(1), load.eq(self.start_load),
                indexed.eq(self.start_indexed), strided.eq(self.start_strided),
                fof.eq(self.start_fof), whole.eq(self.start_whole),
                mask.eq(self.start_mask), vm.eq(self.start_vm),
                vma.eq(self.start_vma), vta.eq(self.start_vta),
                base.eq(self.start_base), stride.eq(self.start_stride),
                vreg.eq(self.start_vreg), index_vreg.eq(self.start_index_vreg),
                eew_bytes.eq(self.start_eew_bytes),
                index_bytes.eq(self.start_index_bytes),
                fields.eq(self.start_fields),
                field_stride.eq(self.start_field_stride),
                element.eq(self.start_element), field.eq(0), byte.eq(0),
                evl.eq(self.start_evl), tail_limit.eq(self.start_tail_limit),
                tail.eq(0),
            ]

        with m.If(active):
            with m.If(~tail & (element < evl)):
                with m.If(~element_enabled):
                    with m.If(load & vma):
                        m.d.comb += [self.write_valid.eq(1),
                                     self.write_data.eq(0xff)]
                    self._advance(m, byte, field, element, eew_bytes, fields)
                with m.Elif(self.dmem_grant & self.dmem_error):
                    with m.If(fof & (element != 0)):
                        m.d.comb += [self.vl_write_valid.eq(1),
                                     self.vl_write_value.eq(element)]
                    with m.Else():
                        m.d.comb += self.trap.eq(1)
                    m.d.sync += active.eq(0)
                with m.Elif(self.dmem_grant):
                    with m.If(load):
                        m.d.comb += [self.write_valid.eq(1),
                                     self.write_data.eq(load_byte)]
                    self._advance(m, byte, field, element, eew_bytes, fields)
            with m.Elif(~tail & load & ~whole & ~mask &
                        (element < tail_limit)):
                m.d.sync += tail.eq(1)
            with m.Elif(tail & (element < tail_limit)):
                with m.If(vta):
                    m.d.comb += [self.write_valid.eq(1),
                                 self.write_data.eq(0xff)]
                self._advance(m, byte, field, element, eew_bytes, fields)
            with m.Else():
                m.d.comb += [self.done.eq(1), self.vstart_value.eq(0)]
                m.d.sync += [active.eq(0), tail.eq(0)]
        return m

    @staticmethod
    def _advance(m, byte, field, element, eew_bytes, fields):
        with m.If(byte + 1 < eew_bytes):
            m.d.sync += byte.eq(byte + 1)
        with m.Elif(field + 1 < fields):
            m.d.sync += [byte.eq(0), field.eq(field + 1)]
        with m.Else():
            m.d.sync += [byte.eq(0), field.eq(0), element.eq(element + 1)]
