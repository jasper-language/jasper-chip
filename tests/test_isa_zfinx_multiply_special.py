import importlib.util
from pathlib import Path

import pytest


_spec = importlib.util.spec_from_file_location(
    "support", Path(__file__).with_name("test_isa_zfh_add_sub.py")
)
_support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_support)
_run = _support._run


def _lui(rd, value):
    return (value & 0xFFFFF000) | (rd << 7) | 0x37


def _addi(rd, rs1, immediate):
    return ((immediate & 0xFFF) << 20) | (rs1 << 15) | (rd << 7) | 0x13


def _li(rd, value):
    value &= 0xFFFFFFFF
    upper = (value + 0x800) & 0xFFFFF000
    return [_lui(rd, upper), _addi(rd, rd, (value - upper) & 0xFFF)]


def _mul(rd, rs1, rs2):
    return (0b0001000 << 25) | (rs2 << 20) | (rs1 << 15) | (rd << 7) | 0x53


def _csr(rd, csr, rs1, funct3=0b010):
    return (csr << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | 0x73


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFINX", "RV32I+GC+*+ZFINX"])
def test_zfinx_multiply_special_values_nan_and_invalid_flags(extensions):
    values = (0x80000000, 0x40000000, 0x7F800000, 0x7FC12345, 0x7F800001, 0)
    program = []
    for register, value in enumerate(values, start=1):
        program += _li(register, value)
    program += [_csr(0, 1, 0, 0b001)]
    program += [
        _mul(8, 1, 2),   # -0 * +2 = -0
        _mul(9, 3, 2),   # +inf * +2 = +inf
        _mul(10, 4, 2),  # qNaN * +2 = canonical qNaN, no NV
        _mul(11, 5, 2),  # sNaN * +2 = canonical qNaN, NV
        _mul(12, 6, 3),  # +0 * +inf = canonical qNaN, NV
    ]
    program += [_addi(0, 0, 0)] * 5
    program += [_csr(20, 1, 0)]

    assert _run(extensions, program, (8, 9, 10, 11, 12, 20)) == (
        0x80000000,
        0x7F800000,
        0x7FC00000,
        0x7FC00000,
        0x7FC00000,
        0b10000,
    )
