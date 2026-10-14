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


def _load(rd, rs1, immediate, opcode, funct3=0b010):
    return ((immediate & 0xFFF) << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode


def _store(rs2, rs1, immediate, opcode=0x27, funct3=0b010):
    immediate &= 0xFFF
    return (
        ((immediate >> 5) << 25)
        | (rs2 << 20)
        | (rs1 << 15)
        | (funct3 << 12)
        | ((immediate & 0x1F) << 7)
        | opcode
    )


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFINX", "RV32I+GC+*+ZFINX"])
def test_zfinx_excludes_flw_fsw_without_register_or_memory_side_effects(extensions):
    program = []
    program += _li(1, 0xDEADBEEF)
    program += _li(2, 0)
    program += _li(4, 0x13579BDF)
    program += [
        _store(1, 2, 0),             # FSW x1, 0(x2): illegal in Zfinx
        _addi(0, 0, 0),
        _addi(0, 0, 0),
        _load(3, 2, 0, 0x03),       # LW observes unchanged zero-initialized memory
        _load(4, 2, 0, 0x07),       # FLW x4, 0(x2): illegal in Zfinx
        _addi(5, 4, 1),
    ]

    assert _run(extensions, program, (3, 4, 5)) == (
        0,
        0x13579BDF,
        0x13579BE0,
    )
