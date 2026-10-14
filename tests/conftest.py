"""Shared pytest fixtures/options for GC chip tests."""

# 注册仓库自带的极简 rfc3986 兼容 shim（自研代码，非上游 vendored 代码）。
# 若系统已安装官方 rfc3986，shim 会自动让位。
import _rfc3986_shim  # noqa: F401

import pytest

def pytest_addoption(parser):
    parser.addoption("--profile", action="store", default="standard",
                     help="GC profile: lite, standard, server")
    parser.addoption("--runslow", action="store_true", default=False,
                     help="run slow benchmark/performance tests")


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "slow: long benchmark/performance tests that are skipped by default",
    )


def pytest_generate_tests(metafunc):
    if "profile" in metafunc.fixturenames:
        profile = metafunc.config.getoption("profile")
        metafunc.parametrize("profile", [profile], scope="session")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runslow"):
        return
    skip_slow = pytest.mark.skip(reason="need --runslow option to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)
