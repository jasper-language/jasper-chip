# rtl/isa.py
from dataclasses import dataclass

# RV32 base opcodes (subset)
OP_IMM   = 0b0010011
OP       = 0b0110011
LOAD     = 0b0000011
STORE    = 0b0100011
BRANCH   = 0b1100011
JAL      = 0b1101111
JALR     = 0b1100111
MISC_MEM = 0b0001111  # FENCE

# Custom-0 opcode space
CUSTOM0  = 0b0001011

# GC ops use funct3
GC_NEW   = 0b000
GC_DROP  = 0b001
GC_CLONE = 0b010
GC_PIN   = 0b011
GC_UNPIN = 0b100
GC_RELOC = 0b101
GC_EPOCH = 0b110
GC_MV_RELOC = 0b111  # Step74: CPU直接向MV协处理器发起RELOC

GC_F7    = 0b0000000  # reserved

def enc_r(opcode, rd, funct3, rs1, rs2, funct7):
    return ((funct7 & 0x7f) << 25) | ((rs2 & 0x1f) << 20) | ((rs1 & 0x1f) << 15) | \
        ((funct3 & 0x7) << 12) | ((rd & 0x1f) << 7) | (opcode & 0x7f)

def enc_i(opcode, rd, funct3, rs1, imm):
    imm12 = imm & 0xfff
    return (imm12 << 20) | ((rs1 & 0x1f) << 15) | ((funct3 & 0x7) << 12) | ((rd & 0x1f) << 7) | (opcode & 0x7f)

def enc_s(opcode, funct3, rs1, rs2, imm):
    imm12 = imm & 0xfff
    immhi = (imm12 >> 5) & 0x7f
    immlo = imm12 & 0x1f
    return (immhi << 25) | ((rs2 & 0x1f) << 20) | ((rs1 & 0x1f) << 15) | \
        ((funct3 & 0x7) << 12) | (immlo << 7) | (opcode & 0x7f)

def enc_b(opcode, funct3, rs1, rs2, imm):
    # imm is byte offset, must be multiple of 2
    imm13 = imm & 0x1fff
    b12   = (imm13 >> 12) & 1
    b11   = (imm13 >> 11) & 1
    b10_5 = (imm13 >> 5) & 0x3f
    b4_1  = (imm13 >> 1) & 0xf
    return (b12 << 31) | (b10_5 << 25) | ((rs2 & 0x1f) << 20) | ((rs1 & 0x1f) << 15) | \
        ((funct3 & 7) << 12) | (b4_1 << 8) | (b11 << 7) | (opcode & 0x7f)

def enc_jal(rd, imm):
    imm21 = imm & 0x1fffff
    j20   = (imm21 >> 20) & 1
    j10_1 = (imm21 >> 1) & 0x3ff
    j11   = (imm21 >> 11) & 1
    j19_12= (imm21 >> 12) & 0xff
    return (j20 << 31) | (j19_12 << 12) | (j11 << 20) | (j10_1 << 21) | ((rd & 0x1f) << 7) | (JAL & 0x7f)

def enc_fence():
    # simplest FENCE: opcode=0001111, funct3=000, rest zeros
    return enc_i(MISC_MEM, 0, 0b000, 0, 0)

# U-type encoder (LUI, AUIPC)
def enc_u(opcode, rd, imm):
    imm20 = imm & 0xFFFFF
    return (imm20 << 12) | ((rd & 0x1f) << 7) | (opcode & 0x7f)

LUI    = 0b0110111
AUIPC  = 0b0010111
SYSTEM = 0b1110011

# RV64 W-suffix opcodes
OP_IMM_32 = 0b0011011  # 0x1B
OP_32     = 0b0111011  # 0x3B

AMO      = 0b0101111  # 0x2F atomic operations (LR/SC/AMO)

# Additional opcodes for extensions
# Atomic: same OP code, funct7=0b00010xx handles LR/SC/AMO
# Zb* extensions: share OP/OP_IMM with specific funct7 values
# F/D/Q floating point
LOAD_FP  = 0b0000111  # 0x07
STORE_FP = 0b0100111  # 0x27
OP_FP    = 0b1010011  # 0x53 (single/double/quad)
OP_FP_32 = 0b1011011  # 0x5B (RV64 W-suffix for float)

# F/D fused multiply-add opcodes
MADD  = 0b1000011  # 0x43
MSUB  = 0b1000111  # 0x47
NMSUB = 0b1001011  # 0x4B
NMADD = 0b1001111  # 0x4F

# Custom opcode spaces used by some extensions
# V extension (vector)
OP_V = 0b1010111  # 0x57

# Vector instruction encoders
def enc_vsetvli(rd, rs1, vtype):
    """vsetvli rd, rs1, vtype"""
    zimm = vtype & 0x7ff
    return (zimm << 20) | ((rs1 & 0x1f) << 15) | (0b111 << 12) | ((rd & 0x1f) << 7) | OP_V

CUSTOM_1 = 0b0101011  # 0x2B
CUSTOM_2 = 0b1011011  # 0x5B
CUSTOM_3 = 0b1111011  # 0x7B

# Zifencei: FENCE.I immediate value
FENCE_I_IMM = 0x001  # imm[11:0] = 1 for FENCE.I under SYSTEM opcode

# Zicond funct7
ZICOND_F7   = 0b0000111  # funct7 for czero.eqz/nez

# RV64 W-suffix encoders (I-type: ADDIW/SLLIW/SRLIW/SRAIW)
def enc_iw(rd, funct3, rs1, imm):
    """I-type W-suffix: ADDIW(f3=000), SLLIW(f3=001), SRLIW/SRAIW(f3=101).
    imm is the 12-bit I-immediate; for shifts, imm[4:0]=shamt, imm[11:5]=funct7[6:0].
    SRAIW requires imm[6]=1 (i.e. 0x40 for funct7[5]=1), e.g. enc_iw(rd, 0b101, rs1, 0x40|shamt)."""
    return enc_i(OP_IMM_32, rd, funct3, rs1, imm)

# RV64 W-suffix encoders (R-type: ADDW/SUBW/SLLW/SRLW/SRAW)
def enc_rw(rd, funct3, rs1, rs2, funct7):
    """R-type W-suffix: ADDW(f3=0,f7=0x00), SUBW(f3=0,f7=0x20),
    SLLW(f3=1,f7=0x00), SRLW(f3=5,f7=0x00), SRAW(f3=5,f7=0x20)."""
    return enc_r(OP_32, rd, funct3, rs1, rs2, funct7)

# GC encoders (R-type in CUSTOM0)
def enc_gc_new(rd, rs1=0, rs2=0):      return enc_r(CUSTOM0, rd, GC_NEW,   rs1, rs2, GC_F7)
def enc_gc_drop(rs1):                  return enc_r(CUSTOM0, 0,  GC_DROP,  rs1, 0,   GC_F7)
def enc_gc_clone(rd, rs1):             return enc_r(CUSTOM0, rd, GC_CLONE, rs1, 0,   GC_F7)
def enc_gc_pin(rs1):                   return enc_r(CUSTOM0, 0,  GC_PIN,   rs1, 0,   GC_F7)
def enc_gc_unpin(rs1):                 return enc_r(CUSTOM0, 0,  GC_UNPIN, rs1, 0,   GC_F7)
def enc_gc_reloc(rs1_old, rs2_new):    return enc_r(CUSTOM0, 0,  GC_RELOC, rs1_old, rs2_new, GC_F7)

# Step74：CPU直接向MV协处理器发起RELOC（不经过sweep）
def enc_gc_mv_reloc(rs1_old, rs2_new, rd=0): return enc_r(CUSTOM0, rd, GC_MV_RELOC, rs1_old, rs2_new, GC_F7)

# GC_EPOCH: 推进 GC epoch（用于 scan 的 generation 切换；rd 固定为 0）
def enc_gc_epoch():                 return enc_r(CUSTOM0, 0,  GC_EPOCH, 0, 0,   GC_F7)
