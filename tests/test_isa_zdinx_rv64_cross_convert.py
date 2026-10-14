import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "zdinx_support", Path(__file__).with_name("test_isa_zdinx_rv64_sign_compare.py")
)
_support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_support)

run = _support.run
load_double_bits = _support.load_double_bits
op_fp = _support.op_fp
addi = _support.addi
NOP = _support.NOP


def lui(rd, imm20):
    return (imm20 << 12) | (rd << 7) | 0x37


def or_reg(rd, rs1, rs2):
    return (rs2 << 20) | (rs1 << 15) | (0b110 << 12) | (rd << 7) | 0x33


def slli(rd, rs1, shamt):
    return (shamt << 20) | (rs1 << 15) | (0b001 << 12) | (rd << 7) | 0x13


def csr(rd, address, rs1, funct3=2):
    return (address << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | 0x73


def boxed_single(rd, tmp, bits):
    program = [addi(rd, 0, -1), slli(rd, rd, 32)]
    program += [lui(tmp, bits >> 12)]
    if bits & 0xFFF:
        program += [addi(tmp, tmp, bits & 0xFFF)]
    program += [or_reg(rd, rd, tmp)]
    return program


EXTENSIONS = ["RV64I+GC+ZFINX+ZDINX", "RV64I+GC+*+ZFINX+ZDINX"]


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zdinx_rv64_single_to_double_nan_boxing_and_snan(extensions):
    program = []
    program += boxed_single(1, 20, 0x3FC00000)  # boxed +1.5f
    program += [lui(2, 0x3FC00)]                # unboxed +1.5f
    program += boxed_single(3, 21, 0x7F800001)  # boxed sNaN
    program += [
        csr(0, 1, 0, 1),
        op_fp(10, 1, 0, 0b0100001),
        op_fp(11, 2, 0, 0b0100001),
        op_fp(12, 3, 0, 0b0100001),
        NOP, NOP, NOP, NOP,
        csr(13, 1, 0),
    ]
    assert run(extensions, program, (10, 11, 12, 13)) == (
        0x3FF8000000000000,
        0x7FF8000000000000,
        0x7FF8000000000000,
        0x10,
    )


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zdinx_rv64_double_to_single_rounding_underflow_and_flags(extensions):
    program = []
    program += load_double_bits(1, 0x3FF00000)  # 1.0
    program += [lui(20, 0x10000), or_reg(1, 1, 20)]  # 1.0 + 2^-24, halfway
    program += [addi(2, 0, 1)]                 # minimum double subnormal
    program += load_double_bits(3, 0x7FF00000)
    program += [addi(3, 3, 1)]                 # double sNaN
    program += [
        addi(4, 0, 3),
        csr(0, 1, 0, 1),
        op_fp(10, 1, 1, 0b0100000, 0b000),  # RNE
        op_fp(11, 1, 1, 0b0100000, 0b001),  # RTZ
        op_fp(12, 1, 1, 0b0100000, 0b010),  # RDN
        op_fp(13, 1, 1, 0b0100000, 0b100),  # RMM
        csr(0, 2, 4, 1),
        op_fp(14, 1, 1, 0b0100000, 0b111),  # dynamic RUP
        op_fp(15, 2, 1, 0b0100000, 0b000),  # tiny -> zero, UF|NX
        op_fp(16, 3, 1, 0b0100000, 0b000),  # sNaN -> canonical, NV
        NOP, NOP, NOP, NOP,
        csr(17, 1, 0),
    ]
    assert run(extensions, program, tuple(range(10, 18))) == (
        0xFFFFFFFF3F800000,
        0xFFFFFFFF3F800000,
        0xFFFFFFFF3F800000,
        0xFFFFFFFF3F800001,
        0xFFFFFFFF3F800001,
        0xFFFFFFFF00000000,
        0xFFFFFFFF7FC00000,
        0x13,
    )
