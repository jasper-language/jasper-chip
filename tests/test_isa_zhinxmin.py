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


def flh(rd, rs1=0, immediate=0):
    return ((immediate & 0xFFF) << 20) | (rs1 << 15) | (1 << 12) | (rd << 7) | 0x07


NOP = addi(0, 0, 0)
EXTENSIONS = [
    "RV32I+GC+ZFINX+ZHINXMIN",
    "RV32I+GC+*+ZFINX+ZHINXMIN",
]


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zhinxmin_converts_between_boxed_half_and_single_in_x_registers(extensions):
    program = []
    program += li(1, 0xFFFF3E00)  # boxed binary16 1.5
    program += [op_fp(2, 1, 2, 0b0100000), NOP, NOP, NOP, NOP]  # FCVT.S.H
    program += [op_fp(3, 2, 0, 0b0100010), NOP, NOP, NOP, NOP]  # FCVT.H.S
    program += li(4, 0x00003E00)  # unboxed H input
    program += [op_fp(5, 4, 2, 0b0100000), NOP, NOP, NOP, NOP]
    assert _run(extensions, program, (2, 3, 5)) == (
        0x3FC00000,
        0xFFFF3E00,
        0x7FC00000,
    )


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zhinxmin_dynamic_rounding_nx_and_illegal_encodings(extensions):
    program = []
    program += li(1, 0x3F801000)  # halfway between 1.0h and its successor
    program += li(6, 0x13579BDF)
    program += li(7, 0x2468ACE0)
    program += li(8, 0x11223344)
    program += [
        csr(0, 1, 0, 1),
        csr(0, 2, 3, 5),
        op_fp(2, 1, 0, 0b0100010, 7),  # FCVT.H.S dynamic RUP
        NOP,
        NOP,
        NOP,
        NOP,
        csr(3, 1, 0),
        op_fp(6, 2, 0, 0b1110010),  # FMV.X.H is excluded
        op_fp(7, 2, 0, 0b1111010),  # FMV.H.X is excluded
        flh(8),                     # FLH is excluded
        NOP,
        NOP,
        NOP,
        NOP,
    ]
    assert _run(extensions, program, (2, 3, 6, 7, 8)) == (
        0xFFFF3C01,
        0x01,
        0x13579BDF,
        0x2468ACE0,
        0x11223344,
    )
