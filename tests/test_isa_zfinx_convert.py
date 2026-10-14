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


def _op_fp(rd, rs1, rs2, funct7, rm):
    return (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (rm << 12) | (rd << 7) | 0x53


def _csr(rd, csr, rs1, funct3=0b010):
    return (csr << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | 0x73


def _clear_fflags():
    return _csr(0, 0x001, 0, 0b001)


def _read_fflags(rd):
    return _csr(rd, 0x001, 0)


def _set_frm(rm):
    return _csr(0, 0x002, rm, 0b101)


def _nops(count=4):
    return [_addi(0, 0, 0)] * count


EXTENSIONS = ["RV32I+GC+ZFINX", "RV32I+GC+*+ZFINX"]


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zfinx_float_to_integer_rounding_saturation_flags(extensions):
    program = _li(1, 0x3FC00000)  # +1.5
    registers = []
    for rd, flag_rd, rm in zip(range(3, 8), range(20, 25), range(5)):
        program += [_clear_fflags(), _op_fp(rd, 1, 0, 0b1100000, rm)] + _nops()
        program += [_read_fflags(flag_rd)]
        registers += [rd, flag_rd]

    # Dynamic RDN and a negative source.
    program += _li(2, 0xBFC00000)
    program += [_set_frm(0b010), _clear_fflags(), _op_fp(8, 2, 0, 0b1100000, 0b111)] + _nops()
    program += [_read_fflags(25)]
    registers += [8, 25]

    # NaN to signed and a negative finite value to unsigned both saturate with NV.
    program += _li(11, 0x7FC00000)
    program += [_clear_fflags(), _op_fp(9, 11, 0, 0b1100000, 0b000)] + _nops()
    program += [_read_fflags(26), _clear_fflags(), _op_fp(10, 2, 1, 0b1100000, 0b000)] + _nops()
    program += [_read_fflags(27)]
    registers += [9, 26, 10, 27]

    assert _run(extensions, program, tuple(registers)) == (
        2, 0b00001,
        1, 0b00001,
        1, 0b00001,
        2, 0b00001,
        2, 0b00001,
        0xFFFFFFFE, 0b00001,
        0x7FFFFFFF, 0b10000,
        0, 0b10000,
    )


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zfinx_integer_to_float_rounding_flags_and_dependency(extensions):
    program = _li(1, 0x01000001)  # 2^24 + 1, halfway between adjacent floats.
    registers = []
    for rd, flag_rd, rm in zip(range(3, 8), range(20, 25), range(5)):
        program += [_clear_fflags(), _op_fp(rd, 1, 0, 0b1101000, rm)] + _nops()
        program += [_read_fflags(flag_rd)]
        registers += [rd, flag_rd]

    # Dynamic RUP must match static RUP.
    program += [_set_frm(0b011), _clear_fflags(), _op_fp(8, 1, 0, 0b1101000, 0b111)] + _nops()
    program += [_read_fflags(25)]
    registers += [8, 25]

    # Exact conversion raises no flag; its x-register result is immediately consumable.
    program += _li(9, 42)
    program += [_clear_fflags(), _op_fp(10, 9, 0, 0b1101000, 0b000), _addi(11, 10, 1)] + _nops()
    program += [_read_fflags(26)]
    registers += [10, 11, 26]

    assert _run(extensions, program, tuple(registers)) == (
        0x4B800000, 0b00001,
        0x4B800000, 0b00001,
        0x4B800000, 0b00001,
        0x4B800001, 0b00001,
        0x4B800001, 0b00001,
        0x4B800001, 0b00001,
        0x42280000, 0x42280001, 0,
    )
