import pytest
from amaranth.hdl import Fragment

from rtl.rv12_core import RV12Core, normalize_extension_spec


@pytest.mark.parametrize("spec,token", [
    ("RV32I+GC+ZKN", "ZKN"),
    ("RV32I+GC+ZKS", "ZKS"),
    ("RV32I+GC+*", "ZKN"),
    ("RV32I+GC+*", "ZKS"),
])
def test_standard_crypto_composite_tokens_are_retained(spec, token):
    assert token in normalize_extension_spec(spec)


def test_zkn_enables_complete_nist_suite_without_shangmi_suite():
    core = RV12Core(xlen=32, extensions="RV32I+GC+ZKN")
    assert core.enable_b
    assert core.enable_zkne
    assert core.enable_zknd
    assert core.enable_zknh
    assert not core.enable_zksh
    assert not core.enable_zksed
    Fragment.get(core, platform=None)


def test_zks_enables_complete_shangmi_suite_without_nist_suite():
    core = RV12Core(xlen=32, extensions="RV32I+GC+ZKS")
    assert core.enable_b
    assert core.enable_zksh
    assert core.enable_zksed
    assert not core.enable_zkne
    assert not core.enable_zknd
    assert not core.enable_zknh
    Fragment.get(core, platform=None)


def test_star_enables_both_complete_crypto_suites():
    core = RV12Core(xlen=32, extensions="RV32I+GC+*")
    assert all((core.enable_b, core.enable_zkne, core.enable_zknd,
                core.enable_zknh, core.enable_zksh, core.enable_zksed))
