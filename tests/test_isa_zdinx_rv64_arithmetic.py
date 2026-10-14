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


def fma(opcode, rd, rs1, rs2, rs3, rm=0):
    return (rs3 << 27) | (1 << 25) | (rs2 << 20) | (rs1 << 15) | (rm << 12) | (rd << 7) | opcode


def csr(rd, address, rs1, funct3=2):
    return (address << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | 0x73


EXTENSIONS = ["RV64I+GC+ZDINX", "RV64I+GC+*+ZDINX"]


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zdinx_rv64_arithmetic_sqrt_and_fused_operations(extensions):
    program = []
    program += load_double_bits(1, 0x3FF80000)  # 1.5
    program += load_double_bits(2, 0x40000000)  # 2.0
    program += load_double_bits(3, 0x3FF00000)  # 1.0
    program += load_double_bits(4, 0x40100000)  # 4.0
    program += [
        op_fp(10, 1, 2, 0b0000001),
        op_fp(11, 1, 2, 0b0000101),
        op_fp(12, 1, 2, 0b0001001),
        op_fp(13, 1, 2, 0b0001101),
        op_fp(14, 4, 0, 0b0101101),
        fma(0x43, 15, 1, 2, 3),
        fma(0x47, 16, 1, 2, 3),
        fma(0x4B, 17, 1, 2, 3),
        fma(0x4F, 18, 1, 2, 3),
        NOP, NOP, NOP, NOP,
    ]
    assert run(extensions, program, tuple(range(10, 19))) == (
        0x400C000000000000,
        0xBFE0000000000000,
        0x4008000000000000,
        0x3FE8000000000000,
        0x4000000000000000,
        0x4010000000000000,
        0x4000000000000000,
        0xC000000000000000,
        0xC010000000000000,
    )


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zdinx_rv64_dynamic_rounding_and_exception_flags(extensions):
    program = []
    program += load_double_bits(1, 0x3FF00000)  # 1.0
    program += [addi(2, 0, 1)]                 # minimum subnormal
    program += [addi(3, 0, 0)]                 # +0
    program += load_double_bits(4, 0xBFF00000)  # -1.0
    program += [
        csr(0, 1, 0, 1),
        csr(0, 2, 3, 5),
        op_fp(10, 1, 2, 0b0000001, 7),
        NOP, NOP, NOP, NOP,
        csr(11, 1, 0),
        csr(0, 1, 0, 1),
        op_fp(12, 1, 3, 0b0001101),
        NOP, NOP, NOP, NOP,
        csr(13, 1, 0),
        csr(0, 1, 0, 1),
        op_fp(14, 4, 0, 0b0101101),
        NOP, NOP, NOP, NOP,
        csr(15, 1, 0),
    ]
    assert run(extensions, program, (10, 11, 12, 13, 14, 15)) == (
        0x3FF0000000000001,
        0x01,
        0x7FF0000000000000,
        0x08,
        0x7FF8000000000000,
        0x10,
    )
