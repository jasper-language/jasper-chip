import pytest
from amaranth.hdl import Fragment

from rtl.rv12_core import RV12Core, normalize_extension_spec


@pytest.mark.parametrize("spec,token", [
    ("RV32I+GC+ZK", "ZK"),
    ("RV32I+GC+ZKT", "ZKT"),
    ("RV32I+GC+*", "ZK"),
    ("RV32I+GC+*", "ZKT"),
])
def test_zk_and_zkt_tokens_are_retained(spec, token):
    assert token in normalize_extension_spec(spec)


def test_zk_enables_zkn_zkr_and_zkt_without_enabling_zks():
    core = RV12Core(xlen=32, extensions="RV32I+GC+ZK")
    assert core.enable_b
    assert core.enable_zkne
    assert core.enable_zknd
    assert core.enable_zknh
    assert core.enable_zkr
    assert core.enable_zkt
    assert not core.enable_zksh
    assert not core.enable_zksed
    Fragment.get(core, platform=None)


def test_zkt_policy_token_does_not_enable_crypto_instructions_by_itself():
    core = RV12Core(xlen=32, extensions="RV32I+GC+ZKT")
    assert core.enable_zkt
    assert not core.enable_zkne
    assert not core.enable_zknd
    assert not core.enable_zknh
    assert not core.enable_zksh
    assert not core.enable_zksed
    assert not core.enable_zkr
    Fragment.get(core, platform=None)


def test_star_enables_complete_zk_and_zks_suites():
    core = RV12Core(xlen=32, extensions="RV32I+GC+*")
    assert all((core.enable_b, core.enable_zkne, core.enable_zknd,
                core.enable_zknh, core.enable_zkr, core.enable_zkt,
                core.enable_zksh, core.enable_zksed))
