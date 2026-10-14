import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "zfh_runner", Path(__file__).with_name("test_isa_zfh_add_sub.py")
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
_run = _module._run


def lui(rd, value):
    return (value & 0xFFFFF000) | (rd << 7) | 0x37


def addi(rd, rs1, immediate):
    return ((immediate & 0xFFF) << 20) | (rs1 << 15) | (rd << 7) | 0x13


def li(rd, value):
    value &= 0xFFFFFFFF
    upper = (value + 0x800) & 0xFFFFF000
    return [lui(rd, upper), addi(rd, rd, (value - upper) & 0xFFF)]


def op_fp(rd, rs1, rs2, funct7, rm=0):
    return (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (rm << 12) | (rd << 7) | 0x53


def fma(opcode, rd, rs1, rs2, rs3, rm=0):
    return (rs3 << 27) | (2 << 25) | (rs2 << 20) | (rs1 << 15) | (rm << 12) | (rd << 7) | opcode


def csr(rd, address, rs1, funct3=2):
    return (address << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | 0x73


NOP = addi(0, 0, 0)
EXTENSIONS = [
    "RV32I+GC+ZFINX+ZHINX",
    "RV32I+GC+*+ZFINX+ZHINX",
]


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zhinx_basic_arithmetic_sqrt_and_fused_operations(extensions):
    program = []
    program += li(1, 0xFFFF3E00)  # 1.5h
    program += li(2, 0xFFFF4000)  # 2.0h
    program += li(3, 0xFFFF3C00)  # 1.0h
    program += li(4, 0xFFFF4400)  # 4.0h
    program += [
        op_fp(10, 1, 2, 0b0000010),  # FADD.H = 3.5
        op_fp(11, 1, 2, 0b0000110),  # FSUB.H = -0.5
        op_fp(12, 1, 2, 0b0001010),  # FMUL.H = 3.0
        op_fp(13, 1, 2, 0b0001110),  # FDIV.H = 0.75
        op_fp(14, 4, 0, 0b0101110),  # FSQRT.H = 2.0
        fma(0x43, 15, 1, 2, 3),      # FMADD.H = 4.0
        fma(0x47, 16, 1, 2, 3),      # FMSUB.H = 2.0
        fma(0x4B, 17, 1, 2, 3),      # FNMSUB.H = -2.0
        fma(0x4F, 18, 1, 2, 3),      # FNMADD.H = -4.0
        NOP,
        NOP,
        NOP,
        NOP,
    ]
    assert _run(extensions, program, tuple(range(10, 19))) == (
        0xFFFF4300,
        0xFFFFB800,
        0xFFFF4200,
        0xFFFF3A00,
        0xFFFF4000,
        0xFFFF4400,
        0xFFFF4000,
        0xFFFFC000,
        0xFFFFC400,
    )


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zhinx_rounding_dynamic_frm_and_exception_flags(extensions):
    program = []
    program += li(1, 0xFFFF3C00)  # 1.0h
    program += li(2, 0xFFFF0001)  # minimum positive subnormal
    program += li(3, 0xFFFF0000)  # +0
    program += li(4, 0xFFFFBC00)  # -1.0h
    program += [
        csr(0, 1, 0, 1),
        op_fp(10, 1, 2, 0b0000010, 0),  # RNE: 1.0, NX
        NOP,
        NOP,
        NOP,
        NOP,
        csr(11, 1, 0),
        csr(0, 1, 0, 1),
        csr(0, 2, 3, 5),
        op_fp(12, 1, 2, 0b0000010, 7),  # dynamic RUP: successor, NX
        NOP,
        NOP,
        NOP,
        NOP,
        csr(13, 1, 0),
        csr(0, 1, 0, 1),
        op_fp(14, 1, 3, 0b0001110),     # 1 / 0 -> +inf, DZ
        NOP,
        NOP,
        NOP,
        NOP,
        csr(15, 1, 0),
        csr(0, 1, 0, 1),
        op_fp(16, 4, 0, 0b0101110),     # sqrt(-1) -> qNaN, NV
        NOP,
        NOP,
        NOP,
        NOP,
        csr(17, 1, 0),
    ]
    assert _run(extensions, program, (10, 11, 12, 13, 14, 15, 16, 17)) == (
        0xFFFF3C00,
        0x01,
        0xFFFF3C01,
        0x01,
        0xFFFF7C00,
        0x08,
        0xFFFF7E00,
        0x10,
    )
