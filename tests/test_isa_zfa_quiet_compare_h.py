from pathlib import Path
import importlib.util

import pytest


_path = Path(__file__).with_name("test_isa_zfh_add_sub.py")
_spec = importlib.util.spec_from_file_location("jasper_zfa_qcmp_h_support", _path)
support = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(support)
runtime = support.runtime


def _compare(rd, function, a, b):
    return runtime.enc_r(runtime.OP_FP, rd, function, a, b, 0b1010010)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH+ZFA", "RV32I+GC+*"])
def test_zfa_half_quiet_compare_nan_order_zero_box_and_flags(extensions):
    prog = support._load_halves(((1, 0x7e01), (2, 0x7d01), (3, 0xc000),
                                 (4, 0x3e00), (5, 0x0000), (6, 0x8000)))
    cases = ((10, 0b100, 1, 4), (11, 0b101, 1, 4),
             (12, 0b100, 3, 4), (13, 0b101, 4, 3),
             (14, 0b100, 5, 6), (15, 0b101, 2, 4))
    for rd, function, a, b in cases:
        prog += [support._csr_clear()] + [runtime.nop()] * 4 + [
            _compare(rd, function, a, b), support._csr_read(rd + 10)]
    prog += support._li(7, 0x3e00)
    prog += [runtime.enc_r(runtime.OP_FP, 7, 0, 7, 0, 0b1111000),
             support._csr_clear(), _compare(16, 0b100, 7, 4),
             support._csr_read(26)]
    assert support._run(extensions, prog, tuple(range(10, 17)) +
                        tuple(range(20, 27))) == (
        0, 0, 1, 0, 1, 0, 0,
        0, 0, 0, 0, 0, 0b10000, 0)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH+ZFA", "RV32I+GC+*"])
def test_zfa_half_quiet_compare_pipeline_dependencies(extensions):
    prog = support._load_halves(((1, 0x3c00), (2, 0x4000)))
    prog += [_compare(10, 0b101, 1, 2),
             runtime.enc_i(runtime.OP_IMM, 11, 0, 10, 1)]
    assert support._run(extensions, prog, (10, 11)) == (1, 2)
