"""Every committed block fixture must survive a parse and re-serialize unchanged."""

from __future__ import annotations

from pathlib import Path

import pytest

from mc7asm import Severity, parse_image, validate_image
from scripts import capture_fixtures
from tests.support import reference_blocks

FIXTURES = Path(__file__).parent / "fixtures" / "blocks"
ALL_FIXTURES = sorted(FIXTURES.rglob("*.mc7"))
FAKE_FIXTURES = sorted((FIXTURES / "fake").glob("*.mc7"))


def fixture_id(path: Path) -> str:
    return str(path.relative_to(FIXTURES))


def test_the_fake_corpus_is_committed() -> None:
    assert [path.name for path in FAKE_FIXTURES] == ["DB1.mc7", "FC1.mc7", "OB1.mc7"]
    assert set(FAKE_FIXTURES) <= set(ALL_FIXTURES)


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=fixture_id)
def test_fixture_reserializes_byte_for_byte(path: Path) -> None:
    raw = path.read_bytes()
    image = parse_image(raw)
    assert image.to_bytes() == raw
    assert b"".join(section.data for section in image.sections()) == raw
    assert image.size == len(raw)


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=fixture_id)
def test_fixture_name_matches_its_header(path: Path) -> None:
    assert parse_image(path.read_bytes()).header.name == path.stem


@pytest.mark.parametrize("path", FAKE_FIXTURES, ids=fixture_id)
def test_fake_fixture_has_exactly_the_documented_layout(path: Path) -> None:
    image = parse_image(path.read_bytes())
    assert validate_image(image) == []
    assert image.declared_layout_fits
    assert image.trailing_unknown == b""
    assert image.header.length == image.size


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=fixture_id)
def test_fixture_sections_fit_between_header_and_footer(path: Path) -> None:
    findings = validate_image(parse_image(path.read_bytes()))
    assert [f for f in findings if f.severity is Severity.ERROR] == []


def test_fake_fixtures_are_what_the_capture_script_produces(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert capture_fixtures.main(["--fake", "--output", str(tmp_path)]) == 0
    produced = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    committed = {path.name: path.read_bytes() for path in FAKE_FIXTURES}
    assert produced == committed
    assert set(committed.values()) == set(reference_blocks().values())
    assert capsys.readouterr().out.count("trailing unknown 0)") == 3
