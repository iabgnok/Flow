"""统一 file_reader：单文件 / 多路径 / 目录 / zip / 截断 / 跳过规则。"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from myflow.skills.base import SkillExecutionError
from myflow.skills.file_ops import FileReaderInput, FileReaderSkill, MultiFileReaderSkill


def _inp(**kwargs: object) -> FileReaderInput:
    return FileReaderInput.model_validate(kwargs)


@pytest.fixture
def reader() -> FileReaderSkill:
    return FileReaderSkill()


@pytest.mark.asyncio
async def test_single_file_path_raw_text_no_headers(tmp_path: Path, reader: FileReaderSkill) -> None:
    f = tmp_path / "one.txt"
    f.write_text("hello-单文件", encoding="utf-8")
    out = await reader.execute(_inp(path=str(f)), {})
    assert out.file_content == "hello-单文件"
    assert "===" not in out.file_content
    assert out.file_count == 1


@pytest.mark.asyncio
async def test_single_file_uses_file_path_alias(tmp_path: Path, reader: FileReaderSkill) -> None:
    f = tmp_path / "a.txt"
    f.write_text("alias", encoding="utf-8")
    out = await reader.execute(_inp(file_path=str(f)), {})
    assert out.file_content == "alias"
    assert out.file_count == 1


@pytest.mark.asyncio
async def test_comma_separated_two_files_has_blocks(tmp_path: Path, reader: FileReaderSkill) -> None:
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("X", encoding="utf-8")
    b.write_text("Y", encoding="utf-8")
    out = await reader.execute(_inp(path=f"{a},{b}"), {})
    assert "===" in out.file_content
    assert "X" in out.file_content and "Y" in out.file_content


@pytest.mark.asyncio
async def test_paths_list_two_files(tmp_path: Path, reader: FileReaderSkill) -> None:
    a = tmp_path / "m1.txt"
    b = tmp_path / "m2.txt"
    a.write_text("p1", encoding="utf-8")
    b.write_text("p2", encoding="utf-8")
    out = await reader.execute(_inp(paths=[str(a), str(b)]), {})
    assert "p1" in out.file_content and "p2" in out.file_content
    assert "===" in out.file_content


@pytest.mark.asyncio
async def test_directory_merges_text_files_sorted(tmp_path: Path, reader: FileReaderSkill) -> None:
    d = tmp_path / "proj"
    d.mkdir()
    (d / "z.txt").write_text("Z", encoding="utf-8")
    (d / "a.txt").write_text("A", encoding="utf-8")
    out = await reader.execute(_inp(path=str(d)), {})
    assert "a.txt" in out.file_content and "z.txt" in out.file_content
    pos_a = out.file_content.index("a.txt")
    pos_z = out.file_content.index("z.txt")
    assert pos_a < pos_z
    assert "===" in out.file_content


@pytest.mark.asyncio
async def test_directory_skips_node_modules_tree(tmp_path: Path, reader: FileReaderSkill) -> None:
    d = tmp_path / "app"
    d.mkdir()
    (d / "ok.txt").write_text("visible", encoding="utf-8")
    nm = d / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "hidden.js").write_text("nope", encoding="utf-8")
    out = await reader.execute(_inp(path=str(d)), {})
    assert "visible" in out.file_content
    assert "nope" not in out.file_content


@pytest.mark.asyncio
async def test_read_zip_extracts_and_merges(tmp_path: Path, reader: FileReaderSkill) -> None:
    zf = tmp_path / "repo.zip"
    with zipfile.ZipFile(zf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("src/hi.txt", "from-zip")
    out = await reader.execute(_inp(path=str(zf)), {})
    assert "from-zip" in out.file_content
    assert "hi.txt" in out.file_content or "src" in out.file_content
    assert "===" in out.file_content


@pytest.mark.asyncio
async def test_max_files_truncates_directory(tmp_path: Path, reader: FileReaderSkill) -> None:
    d = tmp_path / "many"
    d.mkdir()
    (d / "f1.txt").write_text("1", encoding="utf-8")
    (d / "f2.txt").write_text("2", encoding="utf-8")
    out = await reader.execute(_inp(path=str(d), max_files=1, max_total_chars=100_000), {})
    assert "truncated" in out.file_content.lower() or "..." in out.file_content


@pytest.mark.asyncio
async def test_binary_by_extension_skipped(tmp_path: Path, reader: FileReaderSkill) -> None:
    d = tmp_path / "mix"
    d.mkdir()
    (d / "a.txt").write_text("ok", encoding="utf-8")
    (d / "b.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    out = await reader.execute(_inp(path=str(d)), {})
    assert "ok" in out.file_content
    assert "binary, skipped" in out.file_content or "skipped" in out.file_content


@pytest.mark.asyncio
async def test_corrupt_zip_raises(tmp_path: Path, reader: FileReaderSkill) -> None:
    bad = tmp_path / "not.zip"
    bad.write_text("this is not a zip", encoding="utf-8")
    with pytest.raises(SkillExecutionError, match="zip|无效"):
        await reader.execute(_inp(path=str(bad)), {})


@pytest.mark.asyncio
async def test_missing_path_raises(reader: FileReaderSkill) -> None:
    with pytest.raises(SkillExecutionError, match="不存在"):
        await reader.execute(_inp(path="/no/such/path/file-xyz-12345.txt"), {})


@pytest.mark.asyncio
async def test_multi_file_reader_skill_metadata() -> None:
    alias = MultiFileReaderSkill()
    assert alias.name == "multi_file_reader"
    assert alias.input_model is FileReaderInput


@pytest.mark.asyncio
async def test_alias_skill_executes_like_reader(tmp_path: Path) -> None:
    t = tmp_path / "t.txt"
    t.write_text("via-alias", encoding="utf-8")
    alias = MultiFileReaderSkill()
    out = await alias.execute(_inp(path=str(t)), {})
    assert out.file_content == "via-alias"


@pytest.mark.asyncio
async def test_file_reader_into_llm_analyze_shape(tmp_path: Path, reader: FileReaderSkill) -> None:
    """下游 llm_analyze.content 期望 str：整段引用应为 str，不为 dict。"""
    d = tmp_path / "course"
    d.mkdir()
    (d / "n.txt").write_text("note", encoding="utf-8")
    out = await reader.execute(_inp(path=str(d)), {})
    assert isinstance(out.file_content, str)
    assert len(out.file_content) > 0
