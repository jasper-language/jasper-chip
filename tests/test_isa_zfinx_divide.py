import importlib.util
from pathlib import Path
import pytest

_spec = importlib.util.spec_from_file_location("support", Path(__file__).with_name("test_isa_zfh_add_sub.py"))
_support = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_support)
_run = _support._run

def _lui(rd, v): return (v & 0xfffff000) | (rd << 7) | 0x37
def _addi(rd, rs1, imm): return ((imm & 0xfff) << 20) | (rs1 << 15) | (rd << 7) | 0x13
def _li(rd, v):
    v &= 0xffffffff; hi = (v + 0x800) & 0xfffff000
    return [_lui(rd, hi), _addi(rd, rd, (v - hi) & 0xfff)]
def _div(rd, a, b, rm): return (0b0001100 << 25) | (b << 20) | (a << 15) | (rm << 12) | (rd << 7) | 0x53
def _csr(rd, csr, rs1, f3=0b010): return (csr << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | 0x73
def _clear(): return _csr(0, 1, 0, 0b001)
def _flags(rd): return _csr(rd, 1, 0)
def _nops(): return [_addi(0, 0, 0)] * 4

@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFINX", "RV32I+GC+*+ZFINX"])
def test_zfinx_divide_rounding_encodings_exceptions_and_dependency(extensions):
    p = _li(1, 0x40c00000) + _li(2, 0x40000000)  # 6 / 2 = 3
    regs = []
    for rd, fr, rm in zip(range(3, 8), range(20, 25), range(5)):
        p += [_clear(), _div(rd, 1, 2, rm)] + _nops() + [_flags(fr)]; regs += [rd, fr]
    p += _li(8, 0x3f800000) + _li(9, 0)
    p += [_clear(), _div(10, 8, 9, 0)] + _nops() + [_flags(25)]; regs += [10, 25]
    p += [_clear(), _div(11, 9, 9, 0)] + _nops() + [_flags(26)]; regs += [11, 26]
    p += _li(12, 0x7f800001)
    p += [_clear(), _div(13, 12, 8, 0)] + _nops() + [_flags(27)]; regs += [13, 27]
    p += [_div(14, 1, 2, 0), _addi(15, 14, 1)]; regs += [14, 15]
    assert _run(extensions, p, tuple(regs)) == (
        0x40400000,0, 0x40400000,0, 0x40400000,0, 0x40400000,0, 0x40400000,0,
        0x7f800000,0b01000, 0x7fc00000,0b10000, 0x7fc00000,0b10000,
        0x40400000,0x40400001,
    )
