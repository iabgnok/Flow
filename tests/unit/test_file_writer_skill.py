from __future__ import annotations

from pathlib import Path

import pytest

from myflow.skills.base import SkillExecutionError
from myflow.skills.file_ops import FileWriterInput, FileWriterSkill


def _inp(**kwargs: object) -> FileWriterInput:
    return FileWriterInput.model_validate(kwargs)


@pytest.fixture
def writer() -> FileWriterSkill:
    return FileWriterSkill()


@pytest.mark.asyncio
async def test_single_file_overwrite_default(tmp_path: Path, writer: FileWriterSkill) -> None:
    out_path = tmp_path / "out.txt"
    out = await writer.execute(_inp(file_path=str(out_path), content="hello"), {})
    assert out.report_path == str(out_path)
    assert out.bytes_written > 0
    assert out.file_count == 1
    assert out.report_paths == [str(out_path)]
    assert out.bytes_written_total == out.bytes_written
    assert out_path.read_text(encoding="utf-8") == "hello"


@pytest.mark.asyncio
async def test_path_alias_supported(tmp_path: Path, writer: FileWriterSkill) -> None:
    out_path = tmp_path / "a.txt"
    out = await writer.execute(_inp(path=str(out_path), content="x"), {})
    assert out.report_path == str(out_path)
    assert out_path.read_text(encoding="utf-8") == "x"


@pytest.mark.asyncio
async def test_comma_separated_paths_write_same_content(tmp_path: Path, writer: FileWriterSkill) -> None:
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    out = await writer.execute(_inp(path=f"{a},{b}", content="SAME"), {})
    assert out.file_count == 2
    assert a.read_text(encoding="utf-8") == "SAME"
    assert b.read_text(encoding="utf-8") == "SAME"
    assert out.report_paths == [str(a), str(b)]


@pytest.mark.asyncio
async def test_paths_list_write_same_content(tmp_path: Path, writer: FileWriterSkill) -> None:
    a = tmp_path / "m1.txt"
    b = tmp_path / "m2.txt"
    out = await writer.execute(_inp(paths=[str(a), str(b)], content="p"), {})
    assert out.file_count == 2
    assert "m1.txt" in out.report_paths[0]
    assert a.read_text(encoding="utf-8") == "p"
    assert b.read_text(encoding="utf-8") == "p"


@pytest.mark.asyncio
async def test_mode_create_fails_when_exists(tmp_path: Path, writer: FileWriterSkill) -> None:
    p = tmp_path / "exist.txt"
    p.write_text("old", encoding="utf-8")
    with pytest.raises(SkillExecutionError, match="已存在|create"):
        await writer.execute(_inp(file_path=str(p), content="new", mode="create"), {})


@pytest.mark.asyncio
async def test_mode_append_appends(tmp_path: Path, writer: FileWriterSkill) -> None:
    p = tmp_path / "log.txt"
    p.write_text("A", encoding="utf-8")
    await writer.execute(_inp(file_path=str(p), content="B", mode="append"), {})
    assert p.read_text(encoding="utf-8") == "AB"


@pytest.mark.asyncio
async def test_ensure_trailing_newline(tmp_path: Path, writer: FileWriterSkill) -> None:
    p = tmp_path / "nl.txt"
    await writer.execute(_inp(file_path=str(p), content="line", ensure_trailing_newline=True), {})
    assert p.read_text(encoding="utf-8") == "line\n"


@pytest.mark.asyncio
async def test_writes_batch_supports_per_item_mode(tmp_path: Path, writer: FileWriterSkill) -> None:
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("X", encoding="utf-8")
    out = await writer.execute(
        _inp(
            writes=[
                {"path": str(a), "content": "Y", "mode": "append"},
                {"path": str(b), "content": "Z", "mode": "create"},
            ]
        ),
        {},
    )
    assert out.file_count == 2
    assert a.read_text(encoding="utf-8") == "XY"
    assert b.read_text(encoding="utf-8") == "Z"

