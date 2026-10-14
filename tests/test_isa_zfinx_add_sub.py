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
    lower = (value - upper) & 0xFFF
    return [_lui(rd, upper), _addi(rd, rd, lower)]


def _fp(rd, rs1, rs2, funct7, rm):
    return (
        (funct7 << 25)
        | (rs2 << 20)
        | (rs1 << 15)
        | (rm << 12)
        | (rd << 7)
        | 0x53
    )


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


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFINX", "RV32I+GC+*+ZFINX"])
def test_zfinx_add_sub_all_rounding_modes_flags_and_dependencies(extensions):
    program = []
    program += _li(1, 0x3F800000)  # 1.0
    program += _li(2, 0x33800000)  # 2^-24, exactly half an ulp at 1.0

    results = []
    for rd, flag_rd, rm in zip(range(3, 8), range(20, 25), range(5)):
        program += [_clear_fflags(), _fp(rd, 1, 2, 0b0000000, rm)]
        program += _nops()
        program += [_read_fflags(flag_rd)]
        results += [rd, flag_rd]

    # Dynamic RUP must agree with static RUP.
    program += [_set_frm(0b011), _clear_fflags(), _fp(8, 1, 2, 0b0000000, 0b111)]
    program += _nops()
    program += [_read_fflags(25)]
    results += [8, 25]

    # Exact subtraction at the normal/subnormal boundary must raise no flags.
    program += _li(9, 0x00800000)
    program += _li(10, 0x007FFFFF)
    program += [_clear_fflags(), _fp(11, 9, 10, 0b0000100, 0b000)]
    program += _nops()
    program += [_read_fflags(26)]
    results += [11, 26]

    # Positive overflow under RTZ saturates and raises OF|NX.
    program += _li(12, 0x7F7FFFFF)
    program += [_clear_fflags(), _fp(13, 12, 12, 0b0000000, 0b001)]
    program += _nops()
    program += [_read_fflags(27)]
    results += [13, 27]

    # The following integer instruction must consume the just-produced x value.
    program += [_fp(14, 1, 1, 0b0000000, 0b000), _addi(15, 14, 1)]
    results += [14, 15]

    assert _run(extensions, program, tuple(results)) == (
        0x3F800000,
        0b00001,
        0x3F800000,
        0b00001,
        0x3F800000,
        0b00001,
        0x3F800001,
        0b00001,
        0x3F800001,
        0b00001,
        0x3F800001,
        0b00001,
        0x00000001,
        0,
        0x7F7FFFFF,
        0b00101,
        0x40000000,
        0x40000001,
    )
