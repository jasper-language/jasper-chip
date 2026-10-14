from pathlib import Path
import importlib.util

import pytest


_path = Path(__file__).with_name("test_isa_zfh_add_sub.py")
_spec = importlib.util.spec_from_file_location("jasper_zfh_fma_support", _path)
support = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(support)
runtime = support.runtime


def _r4(opcode, rd, rm, rs1, rs2, rs3):
    return ((rs3 & 0x1f) << 27) | (0b10 << 25) | ((rs2 & 0x1f) << 20) | \
        ((rs1 & 0x1f) << 15) | ((rm & 7) << 12) | ((rd & 0x1f) << 7) | opcode


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH", "RV32I+GC+*"])
def test_zfh_fma_family_single_rounding_dynamic_and_zero_sign(extensions):
    prog = support._load_halves(((1, 0x3e00), (2, 0x4000), (3, 0x3c00),
                                 (4, 0x3c01), (5, 0x3bff), (6, 0xbc00),
                                 (7, 0x0001)))
    prog += [support._csr_clear(),
             _r4(runtime.MADD, 10, 0, 1, 2, 3), support._fmv_x_h(10, 10),
             _r4(runtime.MSUB, 11, 0, 1, 2, 3), support._fmv_x_h(11, 11),
             _r4(runtime.NMSUB, 12, 0, 1, 2, 3), support._fmv_x_h(12, 12),
             _r4(runtime.NMADD, 13, 0, 1, 2, 3), support._fmv_x_h(13, 13),
             _r4(runtime.MADD, 14, 0, 4, 5, 6), support._fmv_x_h(14, 14),
             _r4(runtime.MADD, 15, 0, 3, 3, 7), support._fmv_x_h(15, 15),
             _r4(runtime.MADD, 16, 3, 3, 3, 7), support._fmv_x_h(16, 16)]
    prog += support._li(9, 3)
    prog += [(0x002 << 20) | (9 << 15) | (0b001 << 12) | 0x73,
             _r4(runtime.MADD, 17, 7, 3, 3, 7), support._fmv_x_h(17, 17),
             _r4(runtime.MSUB, 18, 0, 3, 3, 3), support._fmv_x_h(18, 18),
             _r4(runtime.MSUB, 19, 2, 3, 3, 3), support._fmv_x_h(19, 19),
             support._csr_read(20)]
    assert support._run(extensions, prog, tuple(range(10, 20)) + (20,)) == (
        0x4400, 0x4000, 0xffffc000, 0xffffc400, 0x0ffe,
        0x3c00, 0x3c01, 0x3c01, 0, 0xffff8000, 0b00001)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH", "RV32I+GC+*"])
def test_zfh_fma_special_overflow_underflow_nan_box_and_flags(extensions):
    prog = support._load_halves(((1, 0x0000), (2, 0x7c00), (3, 0x3c00),
                                 (4, 0xfc00), (5, 0x7e01), (6, 0x7d01),
                                 (7, 0x7bff), (8, 0x4000), (9, 0x0001),
                                 (18, 0x3800)))
    cases = ((10, runtime.MADD, 0, 1, 2, 3),
             (11, runtime.MADD, 0, 2, 3, 4),
             (12, runtime.MADD, 0, 5, 3, 3),
             (13, runtime.MADD, 0, 6, 3, 3),
             (14, runtime.MADD, 0, 7, 8, 1),
             (15, runtime.MADD, 1, 7, 8, 1),
             (16, runtime.MADD, 0, 9, 18, 1),
             (17, runtime.MADD, 4, 9, 18, 1))
    for fd, opcode, rm, a, b, c in cases:
        prog += [support._csr_clear()] + [runtime.nop()] * 4 + [
            _r4(opcode, fd, rm, a, b, c), support._fmv_x_h(fd, fd),
            support._csr_read(fd + 10)]
    prog += support._li(19, 0x3c00)
    prog += [runtime.enc_r(runtime.OP_FP, 19, 0, 19, 0, 0b1111000),
             support._csr_clear(), _r4(runtime.MADD, 28, 0, 19, 3, 3),
             support._fmv_x_h(28, 28), support._csr_read(28)]
    assert support._run(extensions, prog, tuple(range(10, 18)) +
                        tuple(range(20, 29))) == (
        0x7e00, 0x7e00, 0x7e00, 0x7e00, 0x7c00, 0x7bff, 0, 0x0001,
        0b10000, 0b10000, 0, 0b10000, 0b00101, 0b00101,
        0b00011, 0b00011, 0)
