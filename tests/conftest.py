"""Pytest configuration: opt-in flags for the tests that talk to a real PLC."""

from __future__ import annotations

import os

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("plc", "real PLC integration tests")
    group.addoption(
        "--plc-host",
        default=os.environ.get("MC7_TEST_PLC_HOST"),
        help="IP address of a real S7-300; enables the integration tests",
    )
    group.addoption("--plc-rack", type=int, default=0, help="rack of the CPU (default 0)")
    group.addoption("--plc-slot", type=int, default=2, help="slot of the CPU (default 2)")
    group.addoption("--plc-port", type=int, default=102, help="TCP port (default 102)")
    group.addoption(
        "--plc-allow-writes",
        action="store_true",
        help="also run the tests that write to the PLC (see --plc-marker-byte, --plc-block)",
    )
    group.addoption(
        "--plc-marker-byte",
        type=int,
        default=None,
        help="byte offset of 4 bit-memory bytes (MBn..MBn+3) the tests may overwrite",
    )
    group.addoption(
        "--plc-block",
        default=None,
        help="block the round-trip test may upload and download unchanged, for example DB100",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    host = config.getoption("--plc-host")
    allow_writes = config.getoption("--plc-allow-writes")
    skip_integration = pytest.mark.skip(reason="needs --plc-host (or MC7_TEST_PLC_HOST)")
    skip_writes = pytest.mark.skip(reason="needs --plc-allow-writes")
    for item in items:
        if "integration" in item.keywords and not host:
            item.add_marker(skip_integration)
        elif "plc_write" in item.keywords and not allow_writes:
            item.add_marker(skip_writes)
