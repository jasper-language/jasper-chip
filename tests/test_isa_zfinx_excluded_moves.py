import importlib.util
from pathlib import Path

import pytest


_support_spec = importlib.util.spec_from_file_location(
    "zfh_add_sub_support", Path(__file__).with_name("test_isa_zfh_add_sub.py")
)
_support = importlib.util.module_from_spec(_support_spec)
_support_spec.loader.exec_module(_support)
_run = _support._run


def _lui(rd, value):
    return (value & 0xFFFFF000) | (rd << 7) | 0x37


def _addi(rd, rs1, immediate):
    return ((immediate & 0xFFF) << 20) | (rs1 << 15) | (rd << 7) | 0x13


def _li(rd, value):
    value &= 0xFFFFFFFF
    upper = (value + 0x800) & 0xFFFFF000
    return [_lui(rd, upper), _addi(rd, rd, (value - upper) & 0xFFF)]


def _op_fp(rd, rs1, rs2, funct7, funct3=0):
    return (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | 0x53


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFINX", "RV32I+GC+*+ZFINX"])
def test_zfinx_excludes_fmv_x_w_and_fmv_w_x(extensions):
    program = []
    program += _li(1, 0x3F800000)
    program += _li(3, 0x13579BDF)
    program += _li(5, 0x2468ACE0)

    # Both encodings are explicitly excluded by Zfinx. They must not write an x
    # destination even though ordinary Zfinx arithmetic uses the integer file.
    program += [
        _op_fp(3, 1, 0, 0b1110000),  # FMV.X.W x3, x1: illegal in Zfinx
        _op_fp(5, 1, 0, 0b1111000),  # FMV.W.X x5, x1: illegal in Zfinx
        _addi(6, 3, 1),
        _addi(7, 5, 1),
    ]

    assert _run(extensions, program, (3, 5, 6, 7)) == (
        0x13579BDF,
        0x2468ACE0,
        0x13579BE0,
        0x2468ACE1,
    )
