import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "zfa_zhinx_fli_support", Path(__file__).with_name("test_isa_zhinx_integer_convert.py")
)
_support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_support)

run = _support._run
li = _support.li
op_fp = _support.op_fp
addi = _support.addi
csr = _support.csr
NOP = _support.NOP


FLI_H = (
    0xBC00, 0x0400, 0x0100, 0x0200,
    0x1C00, 0x2000, 0x2C00, 0x3000,
    0x3400, 0x3500, 0x3600, 0x3700,
    0x3800, 0x3900, 0x3A00, 0x3B00,
    0x3C00, 0x3D00, 0x3E00, 0x3F00,
    0x4000, 0x4100, 0x4200, 0x4400,
    0x4800, 0x4C00, 0x5800, 0x5C00,
    0x7800, 0x7C00, 0x7C00, 0x7E00,
)

EXTENSIONS = [
    "RV32I+GC+ZFINX+ZHINX+ZFA",
    "RV32I+GC+*+ZFINX+ZHINX",
]


def fli_h(rd, index, funct3=0, rs2=1):
    return op_fp(rd, index, rs2, 0b1111010, funct3)


@pytest.mark.parametrize("extensions", EXTENSIONS)
@pytest.mark.parametrize("start", [0, 16])
def test_zfa_zhinx_fli_h_complete_table_nan_box_and_fflags(extensions, start):
    program = []
    program += li(31, 0x1F)
    program += [csr(0, 1, 31, 1)]
    program += [fli_h(destination, start + destination - 1)
                for destination in range(1, 17)]
    program += [NOP, NOP, NOP, NOP, csr(30, 1, 0)]
    expected = tuple(0xFFFF0000 | value for value in FLI_H[start:start + 16])
    assert run(extensions, program, tuple(range(1, 17)) + (30,)) == expected + (0x1F,)


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zfa_zhinx_fli_h_dependency_and_reserved_fields(extensions):
    program = [
        addi(22, 0, 0x55),
        addi(23, 0, 0x66),
        fli_h(20, 16),               # +1.0h
        addi(21, 20, 1),             # immediate integer dependency
        fli_h(22, 16, funct3=1),     # reserved funct3
        fli_h(23, 16, rs2=2),        # reserved rs2
        NOP, NOP, NOP, NOP,
    ]
    assert run(extensions, program, (20, 21, 22, 23)) == (
        0xFFFF3C00,
        0xFFFF3C01,
        0x55,
        0x66,
    )


def test_zhinx_fli_h_requires_zfa():
    program = [
        addi(10, 0, 0x55),
        fli_h(10, 16),
        NOP, NOP, NOP, NOP,
    ]
    assert run("RV32I+GC+ZFINX+ZHINX", program, (10,)) == (0x55,)
