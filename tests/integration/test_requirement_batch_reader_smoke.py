"""与 requirement_batch_io/run_specs 对齐：file_reader 对夹具路径冒烟（不调 LLM）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from myflow.skills.file_ops import FileReaderInput, FileReaderSkill

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "requirement_batch_io" / "fixtures"


async def _run(inp: FileReaderInput) -> str:
    out = await FileReaderSkill().execute(inp, {})
    return out.file_content


@pytest.mark.asyncio
async def test_r13_comma_separated_three_files() -> None:
    p = f"{FIX / 'r13_news.txt'},{FIX / 'r13_source2.txt'},{FIX / 'r13_source3.txt'}"
    text = await _run(FileReaderInput.model_validate({"path": p}))
    assert "新闻稿" in text
    assert "===" in text


@pytest.mark.asyncio
async def test_r17_comma_separated_pdfs_as_text() -> None:
    p = f"{FIX / 'r17_annual_notes.txt'},{FIX / 'r17_firm_delta.txt'},{FIX / 'r17_firm_echo.txt'}"
    text = await _run(FileReaderInput.model_validate({"path": p}))
    assert "年报" in text
    assert "===" in text


@pytest.mark.asyncio
async def test_r18_zip_path() -> None:
    text = await _run(FileReaderInput.model_validate({"path": str(FIX / "r18_repo_sample.zip")}))
    assert "main.py" in text
    assert "README" in text
    assert "===" in text


@pytest.mark.asyncio
async def test_r19_directory_path() -> None:
    text = await _run(FileReaderInput.model_validate({"path": str(FIX / 'r19_course')}))
    assert "r19_lecture.md" in text or "Lesson" in text
    assert "===" in text


@pytest.mark.asyncio
async def test_r19_paths_single_directory_like_run_specs() -> None:
    """run_specs 里 source_dir 以 paths 绑定时的等价形态。"""
    inp = FileReaderInput.model_validate({"paths": [str(FIX / "r19_course")]})
    out = await FileReaderSkill().execute(inp, {})
    assert out.file_count >= 1
    assert "quiz" in out.file_content.lower() or "lecture" in out.file_content.lower()
