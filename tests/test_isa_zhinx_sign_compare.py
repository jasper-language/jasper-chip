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


def op_fp(rd, rs1, rs2, funct7, funct3=0):
    return (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | 0x53


NOP = addi(0, 0, 0)
EXTENSIONS = [
    "RV32I+GC+ZFINX+ZHINX",
    "RV32I+GC+*+ZFINX+ZHINX",
]


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zhinx_sign_injection_and_minmax_use_x_registers(extensions):
    program = []
    program += li(1, 0xFFFF3E00)  # +1.5h
    program += li(2, 0xFFFFC000)  # -2.0h
    program += [
        op_fp(10, 1, 2, 0b0010010, 0),  # FSGNJ.H
        op_fp(11, 1, 2, 0b0010010, 1),  # FSGNJN.H
        op_fp(12, 1, 2, 0b0010010, 2),  # FSGNJX.H
        op_fp(13, 1, 2, 0b0010110, 0),  # FMIN.H
        op_fp(14, 1, 2, 0b0010110, 1),  # FMAX.H
        NOP,
        NOP,
        NOP,
        NOP,
    ]
    assert _run(extensions, program, (10, 11, 12, 13, 14)) == (
        0xFFFFBE00,
        0xFFFF3E00,
        0xFFFFBE00,
        0xFFFFC000,
        0xFFFF3E00,
    )


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zhinx_compare_classify_and_unboxed_nan(extensions):
    program = []
    program += li(1, 0xFFFF3E00)
    program += li(2, 0xFFFFC000)
    program += li(3, 0x00003E00)  # invalid NaN-box, interpreted as canonical qNaN
    program += [
        op_fp(10, 1, 1, 0b1010010, 2),  # FEQ.H
        op_fp(11, 1, 2, 0b1010010, 1),  # FLT.H
        op_fp(12, 2, 1, 0b1010010, 0),  # FLE.H
        op_fp(13, 2, 0, 0b1110010, 1),  # FCLASS.H negative normal
        op_fp(14, 3, 0, 0b1110010, 1),  # FCLASS.H unboxed qNaN
        op_fp(15, 3, 1, 0b0010110, 0),  # FMIN.H(qNaN, 1.5) -> 1.5
        NOP,
        NOP,
        NOP,
        NOP,
    ]
    assert _run(extensions, program, (10, 11, 12, 13, 14, 15)) == (
        1,
        0,
        1,
        1 << 1,
        1 << 9,
        0xFFFF3E00,
    )
