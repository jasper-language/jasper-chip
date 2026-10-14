from pathlib import Path
import importlib.util

import pytest


_path = Path(__file__).with_name("test_isa_zfh_add_sub.py")
_spec = importlib.util.spec_from_file_location("jasper_zfh_sqrt_support", _path)
support = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(support)
runtime = support.runtime


def _fsqrt(fd, rm, fs1):
    return runtime.enc_r(runtime.OP_FP, fd, rm, fs1, 0, 0b0101110)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH", "RV32I+GC+*"])
def test_zfh_sqrt_rounding_dynamic_subnormal_and_flags(extensions):
    prog = support._load_halves(((1, 0x4400), (2, 0x4000), (3, 0x0001)))
    prog.append(support._csr_clear())
    cases = ((10, 0, 1), (11, 0, 2), (12, 1, 2), (13, 2, 2),
             (14, 3, 2), (15, 4, 2), (16, 0, 3))
    for fd, rm, fs1 in cases:
        prog += [_fsqrt(fd, rm, fs1), support._fmv_x_h(fd, fd)]
    prog += support._li(9, 3)
    prog += [(0x002 << 20) | (9 << 15) | (0b001 << 12) | 0x73,
             _fsqrt(17, 7, 2), support._fmv_x_h(17, 17), support._csr_read(20)]
    assert support._run(extensions, prog, tuple(range(10, 18)) + (20,)) == (
        0x4000, 0x3da8, 0x3da8, 0x3da8, 0x3da9, 0x3da8,
        0x0c00, 0x3da9, 0b00001)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH", "RV32I+GC+*"])
def test_zfh_sqrt_special_nan_box_invalid_and_signed_zero(extensions):
    prog = support._load_halves(((1, 0x0000), (2, 0x8000), (3, 0x7c00),
                                 (4, 0xbc00), (5, 0x7e01), (6, 0x7d01)))
    cases = ((10, 1), (11, 2), (12, 3), (13, 4), (14, 5), (15, 6))
    for fd, fs1 in cases:
        prog += [support._csr_clear(), _fsqrt(fd, 0, fs1),
                 support._fmv_x_h(fd, fd), support._csr_read(fd + 10)]
    prog += support._li(7, 0x4000)
    prog += [runtime.enc_r(runtime.OP_FP, 7, 0, 7, 0, 0b1111000),
             support._csr_clear(), _fsqrt(16, 0, 7), support._fmv_x_h(16, 16),
             support._csr_read(26)]
    assert support._run(extensions, prog, tuple(range(10, 17)) +
                        tuple(range(20, 27))) == (
        0, 0xffff8000, 0x7c00, 0x7e00, 0x7e00, 0x7e00, 0x7e00,
        0, 0, 0, 0b10000, 0, 0b10000, 0)
