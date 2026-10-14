from amaranth import *


class ISAExtension(Elaboratable):
    def __init__(self, xlen=32, name="isa"):
        self.xlen = xlen

        self.valid   = Signal(name=f"{name}_valid")
        self.opcode  = Signal(7,  name=f"{name}_opcode")
        self.funct3  = Signal(3,  name=f"{name}_funct3")
        self.funct7  = Signal(7,  name=f"{name}_funct7")
        self.rd      = Signal(5,  name=f"{name}_rd")
        self.rs1     = Signal(5,  name=f"{name}_rs1")
        self.rs2     = Signal(5,  name=f"{name}_rs2")
        self.imm     = Signal(xlen, name=f"{name}_imm")
        self.pc      = Signal(xlen, name=f"{name}_pc")
        self.ex1_a   = Signal(xlen, name=f"{name}_ex1_a")
        self.ex1_b   = Signal(xlen, name=f"{name}_ex1_b")

        self.matched = Signal(name=f"{name}_matched")

        self.wb_en     = Signal(name=f"{name}_wb_en")
        self.wb_data   = Signal(xlen, name=f"{name}_wb_data")
        self.alu_out   = Signal(xlen, name=f"{name}_alu_out")
        self.mem_addr  = Signal(xlen, name=f"{name}_mem_addr")
        self.mem_wdata = Signal(xlen, name=f"{name}_mem_wdata")
        self.redirect  = Signal(name=f"{name}_redirect")
        self.redirect_pc = Signal(xlen, name=f"{name}_redirect_pc")
        self.trap      = Signal(name=f"{name}_trap")

        self.bp_mispredict = Signal(name=f"{name}_bp_mispredict")
        self.br_valid    = Signal(name=f"{name}_br_valid")
        self.br_pc       = Signal(xlen, name=f"{name}_br_pc")
        self.br_target   = Signal(xlen, name=f"{name}_br_target")
        self.br_taken    = Signal(name=f"{name}_br_taken")
        self.br_is_branch = Signal(name=f"{name}_br_is_branch")
        self.br_is_jal   = Signal(name=f"{name}_br_is_jal")
        self.br_is_jalr  = Signal(name=f"{name}_br_is_jalr")

        self.is_load   = Signal(name=f"{name}_is_load")
        self.is_store  = Signal(name=f"{name}_is_store")
        self.is_branch = Signal(name=f"{name}_is_branch")
        self.is_jal    = Signal(name=f"{name}_is_jal")
        self.is_jalr   = Signal(name=f"{name}_is_jalr")
        self.is_fence  = Signal(name=f"{name}_is_fence")
        self.is_gc     = Signal(name=f"{name}_is_gc")

        self.gc_op       = Signal(3,  name=f"{name}_gc_op")
        self.gc_rd       = Signal(5,  name=f"{name}_gc_rd")
        self.gc_rs1      = Signal(xlen, name=f"{name}_gc_rs1")
        self.gc_rs2      = Signal(xlen, name=f"{name}_gc_rs2")
        self.gc_is_reloc = Signal(name=f"{name}_gc_is_reloc")

    def elaborate(self, platform):
        raise NotImplementedError
