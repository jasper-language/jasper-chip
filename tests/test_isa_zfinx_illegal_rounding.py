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


def _add(rd, rs1, rs2, rm):
    return (rs2 << 20) | (rs1 << 15) | (rm << 12) | (rd << 7) | 0x53


def _csrwi(csr, immediate):
    return (csr << 20) | (immediate << 15) | (0b101 << 12) | 0x73


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFINX", "RV32I+GC+*+ZFINX"])
def test_zfinx_reserved_and_invalid_dynamic_rounding_never_write_back(extensions):
    program = _li(1, 0x3F800000) + _li(2, 0x40000000)
    program += _li(8, 0x11111111) + _li(9, 0x22222222) + _li(10, 0x33333333)
    program += [
        _add(8, 1, 2, 0b101),
        _add(9, 1, 2, 0b110),
        _csrwi(0x002, 0b101),
        _add(10, 1, 2, 0b111),
        _addi(11, 8, 1),
        _addi(12, 9, 1),
        _addi(13, 10, 1),
    ]

    assert _run(extensions, program, (8, 9, 10, 11, 12, 13)) == (
        0x11111111,
        0x22222222,
        0x33333333,
        0x11111112,
        0x22222223,
        0x33333334,
    )
