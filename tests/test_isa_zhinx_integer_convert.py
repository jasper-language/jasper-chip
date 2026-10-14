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


def csr(rd, address, rs1, funct3=2):
    return (address << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | 0x73


NOP = addi(0, 0, 0)
EXTENSIONS = [
    "RV32I+GC+ZFINX+ZHINX",
    "RV32I+GC+*+ZFINX+ZHINX",
]


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zhinx_half_to_integer_all_rounding_modes_and_dynamic_frm(extensions):
    program = []
    program += li(1, 0xFFFF3E00)  # +1.5h
    registers = []
    for rm, rd in enumerate(range(10, 15)):
        program += [
            csr(0, 1, 0, 1),
            op_fp(rd, 1, 0, 0b1100010, rm),  # FCVT.W.H
            NOP,
            NOP,
            NOP,
            NOP,
            csr(rd + 10, 1, 0),
        ]
        registers += [rd, rd + 10]
    program += [
        csr(0, 1, 0, 1),
        csr(0, 2, 3, 5),
        op_fp(15, 1, 0, 0b1100010, 7),  # dynamic RUP
        NOP,
        NOP,
        NOP,
        NOP,
        csr(25, 1, 0),
    ]
    registers += [15, 25]
    assert _run(extensions, program, tuple(registers)) == (
        2, 1,
        1, 1,
        1, 1,
        2, 1,
        2, 1,
        2, 1,
    )


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zhinx_signed_unsigned_integer_to_half_and_invalid_unsigned(extensions):
    program = []
    program += li(1, 3)
    program += li(2, 0xFFFFFFFE)
    program += li(3, 0xFFFFBE00)  # -1.5h
    program += [
        op_fp(10, 1, 0, 0b1101010),  # FCVT.H.W 3
        op_fp(11, 2, 0, 0b1101010),  # FCVT.H.W -2
        op_fp(12, 1, 1, 0b1101010),  # FCVT.H.WU 3
        csr(0, 1, 0, 1),
        op_fp(13, 3, 1, 0b1100010),  # FCVT.WU.H(-1.5) -> 0, NV
        NOP,
        NOP,
        NOP,
        NOP,
        csr(14, 1, 0),
    ]
    assert _run(extensions, program, (10, 11, 12, 13, 14)) == (
        0xFFFF4200,
        0xFFFFC000,
        0xFFFF4200,
        0,
        0x10,
    )
