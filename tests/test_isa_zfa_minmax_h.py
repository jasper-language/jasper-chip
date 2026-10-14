from pathlib import Path
import importlib.util

import pytest


_path = Path(__file__).with_name("test_isa_zfh_add_sub.py")
_spec = importlib.util.spec_from_file_location("jasper_zfa_minmax_h_support", _path)
support = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(support)
runtime = support.runtime


def _minmax(fd, function, a, b):
    return runtime.enc_r(runtime.OP_FP, fd, function, a, b, 0b0010110)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH+ZFA", "RV32I+GC+*"])
def test_zfa_half_minimum_maximum_nan_zero_ordering_box_and_flags(extensions):
    prog = support._load_halves(((1, 0x0000), (2, 0x8000), (3, 0x7e01),
                                 (4, 0x7d01), (5, 0x3c00), (6, 0xc000)))
    cases = ((10, 0b010, 1, 2), (11, 0b011, 1, 2),
             (12, 0b010, 3, 5), (13, 0b011, 6, 3),
             (14, 0b010, 4, 5), (15, 0b010, 6, 5))
    for fd, function, a, b in cases:
        prog += [support._csr_clear()] + [runtime.nop()] * 4 + [
            _minmax(fd, function, a, b), support._fmv_x_h(fd, fd),
            support._csr_read(fd + 10)]
    prog += support._li(7, 0x3c00)
    prog += [runtime.enc_r(runtime.OP_FP, 7, 0, 7, 0, 0b1111000),
             support._csr_clear(), _minmax(16, 0b011, 7, 5),
             support._fmv_x_h(16, 16), support._csr_read(26)]
    assert support._run(extensions, prog, tuple(range(10, 17)) +
                        tuple(range(20, 27))) == (
        0xffff8000, 0, 0x7e00, 0x7e00, 0x7e00, 0xffffc000, 0x7e00,
        0, 0, 0, 0, 0b10000, 0, 0)


def test_zfa_half_minimum_requires_zfa():
    prog = support._load_halves(((1, 0xc000), (2, 0x3c00), (10, 0x3c00)))
    prog += [_minmax(10, 0b010, 1, 2), support._fmv_x_h(10, 10)]
    assert support._run("RV32I+GC+ZFH", prog, (10,)) == (0x3c00,)
