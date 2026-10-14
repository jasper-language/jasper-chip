from amaranth import *
from .isa_module import ISAExtension
from .isa import OP_V


class V(ISAExtension):
    """Decode guard for the V configuration instruction family.

    The V extension adds ~400+ instructions covering:
    - Vector configuration (vsetvli, vsetvl, vsetivli)
    - Vector loads/stores (unit-stride, strided, indexed)
    - Vector arithmetic (add, sub, shift, compare, etc.)
    - Vector mask operations
    - Vector reductions
    - Vector permutations
    - Floating-point vector ops

    Architectural vector state and execution live in RV12Core so integer
    register hazards and CSR updates share the scalar pipeline commit point.
    """
    def __init__(self, xlen=32):
        super().__init__(xlen=xlen, name="v")

    def elaborate(self, platform):
        m = Module()

        is_config = (self.opcode == OP_V) & (self.funct3 == 0b111)
        is_scalar_move = ((self.opcode == OP_V) & (self.funct7 == 0x21) &
                          (((self.funct3 == 0b010) & (self.rs1 == 0)) |
                           ((self.funct3 == 0b110) & (self.rs2 == 0))))
        is_whole_move = ((self.opcode == OP_V) & (self.funct7 == 0x4F) &
                         (self.funct3 == 0b011) &
                         ((self.rs1 == 0) | (self.rs1 == 1) |
                          (self.rs1 == 3) | (self.rs1 == 7)))
        is_vector_move = ((self.opcode == OP_V) & (self.funct7 == 0x2F) &
                          (self.rs2 == 0) &
                          ((self.funct3 == 0b000) | (self.funct3 == 0b100) |
                           (self.funct3 == 0b011)))
        funct6 = self.funct7[1:7]
        is_integer_slide = ((self.opcode == OP_V) &
                            ((funct6 == 0x0E) | (funct6 == 0x0F)) &
                            ((self.funct3 == 0b100) |
                             (self.funct3 == 0b011) |
                             (self.funct3 == 0b110)))
        is_integer_compress = ((self.opcode == OP_V) &
                               (funct6 == 0x17) &
                               (self.funct3 == 0b010))
        is_integer_gather = ((self.opcode == OP_V) &
                             (((funct6 == 0x0C) &
                               ((self.funct3 == 0b000) |
                                (self.funct3 == 0b100) |
                                (self.funct3 == 0b011))) |
                              ((funct6 == 0x0E) &
                               (self.funct3 == 0b000))))
        is_integer_add_sub = ((self.opcode == OP_V) &
                              (((funct6 == 0x00) &
                                ((self.funct3 == 0b000) | (self.funct3 == 0b100) |
                                 (self.funct3 == 0b011))) |
                               ((funct6 == 0x02) &
                                ((self.funct3 == 0b000) | (self.funct3 == 0b100))) |
                               ((funct6 == 0x03) &
                                ((self.funct3 == 0b100) | (self.funct3 == 0b011)))))
        is_integer_logic = ((self.opcode == OP_V) &
                            ((funct6 == 0x09) | (funct6 == 0x0A) |
                             (funct6 == 0x0B)) &
                            ((self.funct3 == 0b000) | (self.funct3 == 0b100) |
                             (self.funct3 == 0b011)))
        is_integer_average = ((self.opcode == OP_V) &
                              ((funct6 == 0x08) | (funct6 == 0x09) |
                               (funct6 == 0x0A) | (funct6 == 0x0B)) &
                              ((self.funct3 == 0b010) | (self.funct3 == 0b110)))
        is_integer_reduction = ((self.opcode == OP_V) &
                                (funct6 <= 0x07) &
                                (self.funct3 == 0b010))
        is_widening_integer_reduction = ((self.opcode == OP_V) &
                                         ((funct6 == 0x30) |
                                          (funct6 == 0x31)) &
                                         (self.funct3 == 0b000))
        is_integer_minmax = ((self.opcode == OP_V) &
                             ((funct6 == 0x04) | (funct6 == 0x05) |
                              (funct6 == 0x06) | (funct6 == 0x07)) &
                             ((self.funct3 == 0b000) | (self.funct3 == 0b100)))
        is_integer_shift = ((self.opcode == OP_V) &
                            ((funct6 == 0x25) | (funct6 == 0x28) |
                             (funct6 == 0x29) | (funct6 == 0x2A) |
                             (funct6 == 0x2B)) &
                            ((self.funct3 == 0b000) | (self.funct3 == 0b100) |
                             (self.funct3 == 0b011)))
        is_integer_saturating = ((self.opcode == OP_V) &
                                 (((funct6 == 0x20) | (funct6 == 0x21)) &
                                  ((self.funct3 == 0b000) | (self.funct3 == 0b100) |
                                   (self.funct3 == 0b011)) |
                                  ((funct6 == 0x22) | (funct6 == 0x23)) &
                                  ((self.funct3 == 0b000) | (self.funct3 == 0b100))))
        is_integer_divrem = ((self.opcode == OP_V) &
                             ((funct6 == 0x20) | (funct6 == 0x21) |
                              (funct6 == 0x22) | (funct6 == 0x23)) &
                             ((self.funct3 == 0b010) | (self.funct3 == 0b110)))
        is_integer_multiply = ((self.opcode == OP_V) &
                               ((funct6 == 0x24) | (funct6 == 0x25) |
                                (funct6 == 0x26) | (funct6 == 0x27)) &
                               ((self.funct3 == 0b010) | (self.funct3 == 0b110)))
        is_integer_multiply_add = ((self.opcode == OP_V) &
                                   ((funct6 == 0x29) | (funct6 == 0x2B) |
                                    (funct6 == 0x2D) | (funct6 == 0x2F)) &
                                   ((self.funct3 == 0b010) |
                                    (self.funct3 == 0b110)))
        is_fixed_point_multiply = ((self.opcode == OP_V) &
                                   (funct6 == 0x27) &
                                   ((self.funct3 == 0b000) |
                                    (self.funct3 == 0b100)))
        is_element_index = ((self.opcode == OP_V) &
                            (funct6 == 0x14) & (self.funct3 == 0b010) &
                            (self.rs1 == 0b10001) & (self.rs2 == 0))
        is_mask_iota = ((self.opcode == OP_V) &
                        (funct6 == 0x14) & (self.funct3 == 0b010) &
                        (self.rs1 == 0b10000))
        is_mask_scalar_query = ((self.opcode == OP_V) &
                                (funct6 == 0x10) & (self.funct3 == 0b010) &
                                ((self.rs1 == 0b10000) |
                                 (self.rs1 == 0b10001)))
        is_mask_prefix = ((self.opcode == OP_V) & (funct6 == 0x14) &
                          (self.funct3 == 0b010) &
                          ((self.rs1 == 0b00001) |
                           (self.rs1 == 0b00010) |
                           (self.rs1 == 0b00011)))
        is_mask_logical = ((self.opcode == OP_V) & self.funct7[0] &
                           (funct6 >= 0x18) & (funct6 <= 0x1F) &
                           (self.funct3 == 0b010))
        is_integer_compare = ((self.opcode == OP_V) &
                              (((funct6 == 0x18) | (funct6 == 0x19)) &
                               ((self.funct3 == 0b000) | (self.funct3 == 0b100) |
                                (self.funct3 == 0b011)) |
                               ((funct6 == 0x1A) | (funct6 == 0x1B)) &
                               ((self.funct3 == 0b000) | (self.funct3 == 0b100)) |
                               ((funct6 == 0x1C) | (funct6 == 0x1D)) &
                               ((self.funct3 == 0b000) | (self.funct3 == 0b100) |
                                (self.funct3 == 0b011)) |
                               ((funct6 == 0x1E) | (funct6 == 0x1F)) &
                               ((self.funct3 == 0b100) | (self.funct3 == 0b011))))
        is_carry_borrow = ((self.opcode == OP_V) &
                           (((((funct6 == 0x10) & ~self.funct7[0]) |
                              (funct6 == 0x11)) &
                             ((self.funct3 == 0b000) | (self.funct3 == 0b100) |
                              (self.funct3 == 0b011))) |
                            ((((funct6 == 0x12) & ~self.funct7[0]) |
                              (funct6 == 0x13)) &
                             ((self.funct3 == 0b000) | (self.funct3 == 0b100)))))
        m.d.comb += [
            self.matched.eq(self.valid &
                            (is_config | is_scalar_move | is_whole_move | is_vector_move |
                             is_integer_slide | is_integer_compress |
                             is_integer_gather |
                             is_integer_add_sub | is_integer_logic | is_integer_average |
                             is_integer_reduction | is_widening_integer_reduction |
                             is_integer_minmax |
                             is_integer_shift | is_integer_saturating |
                             is_integer_divrem | is_integer_multiply |
                             is_integer_multiply_add | is_fixed_point_multiply |
                             is_element_index | is_mask_iota | is_mask_scalar_query |
                             is_mask_prefix |
                             is_mask_logical |
                             is_integer_compare |
                             is_carry_borrow)),

            self.wb_en.eq(0),
            self.wb_data.eq(0),
            self.alu_out.eq(0),
            self.mem_addr.eq(0),
            self.mem_wdata.eq(0),
            self.redirect.eq(0),
            self.redirect_pc.eq(0),
            self.trap.eq(0),

            self.br_valid.eq(0),
            self.br_pc.eq(0),
            self.br_target.eq(0),
            self.br_taken.eq(0),
            self.br_is_branch.eq(0),
            self.br_is_jal.eq(0),
            self.br_is_jalr.eq(0),

            self.is_load.eq(0),
            self.is_store.eq(0),
            self.is_branch.eq(0),
            self.is_jal.eq(0),
            self.is_jalr.eq(0),
            self.is_fence.eq(0),
            self.is_gc.eq(0),

            self.gc_op.eq(0),
            self.gc_rd.eq(0),
            self.gc_rs1.eq(0),
            self.gc_rs2.eq(0),
            self.gc_is_reloc.eq(0),
        ]

        return m
