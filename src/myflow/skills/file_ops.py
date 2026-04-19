from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

from myflow.skills.base import Skill, SkillExecutionError

# 目录遍历时跳过的目录名
_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".mypy_cache",
        "dist",
        "build",
        ".idea",
        ".tox",
        "eggs",
        ".eggs",
    }
)

# 目录 / zip 内遍历时大概率按二进制跳过（仍可在输出中标注 skipped）
_SKIP_READ_EXTS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".bmp",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".mp3",
        ".mp4",
        ".webm",
        ".mkv",
    }
)

_DEFAULT_MAX_TOTAL_CHARS = 200_000
_DEFAULT_MAX_FILES = 80


def _is_probably_binary(data: bytes) -> bool:
    sample = data[:16000]
    return b"\x00" in sample


def _decode_text_bytes(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def _read_file_as_chunk(rel_posix: str, path: Path) -> tuple[str, bool]:
    """返回 (片段正文, 是否为二进制跳过占位)。"""
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise SkillExecutionError(f"读取文件失败: {path}: {e}") from e
    ext = path.suffix.lower()
    if ext in _SKIP_READ_EXTS or _is_probably_binary(raw):
        return f"=== {rel_posix} ===\n(binary, skipped)\n", True
    text = _decode_text_bytes(raw)
    return f"=== {rel_posix} ===\n{text}\n", False


def _merge_blocks(chunks: list[tuple[str, str]], *, raw_single_file: bool) -> str:
    if raw_single_file and len(chunks) == 1:
        return chunks[0][1]
    parts: list[str] = []
    for rel, body in sorted(chunks, key=lambda x: x[0]):
        parts.append(body.rstrip("\n"))
    return "\n\n".join(parts) + ("\n" if parts else "")


def _walk_directory(
    root: Path,
    *,
    max_total_chars: int,
    max_files: int,
    rel_prefix: str = "",
) -> tuple[list[tuple[str, str]], int, bool, str]:
    """收集 (rel_path, block_text)；block 含 === 行。返回 chunks, file_count, truncated, tail_note。"""
    root = root.resolve()
    chunks: list[tuple[str, str]] = []
    total_chars = 0
    n_files = 0
    truncated = False
    stop = False

    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        if stop:
            break
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
        for fname in sorted(filenames):
            if n_files >= max_files:
                truncated = True
                stop = True
                break
            fp = Path(dirpath) / fname
            if not fp.is_file():
                continue
            try:
                rel = fp.relative_to(root)
            except ValueError:
                rel = Path(fp.name)
            rel_posix = "/".join((rel_prefix, str(rel).replace("\\", "/"))).strip("/")

            block, _ = _read_file_as_chunk(rel_posix, fp)
            if total_chars + len(block) > max_total_chars:
                truncated = True
                tail = "\n... (truncated: total size limit reached)\n"
                chunks.append(("__truncation__", tail))
                stop = True
                break
            chunks.append((rel_posix, block))
            total_chars += len(block)
            n_files += 1

    tail_note = ""
    if truncated and not any(c[0] == "__truncation__" for c in chunks):
        tail_note = "\n... (truncated: directory walk stopped early)\n"

    return chunks, n_files, truncated, tail_note


def _safe_extract_zip(zip_path: Path, dest: Path) -> None:
    dest = dest.resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            name = member.filename
            if name.startswith("/") or ".." in Path(name).parts:
                raise SkillExecutionError(f"zip 内含非法路径: {name!r}")
            target = (dest / name).resolve()
            try:
                target.relative_to(dest)
            except ValueError as e:
                raise SkillExecutionError(f"zip 路径越界: {name!r}") from e
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member, "r") as src:
                target.write_bytes(src.read())


class FileReaderInput(BaseModel):
    """读取本地文件、目录或 zip；也可传多路径（paths 或逗号分隔的 path）。"""

    path: str | None = Field(default=None, description="文件、目录或 .zip 路径")
    file_path: str | None = Field(default=None, description="兼容旧版，与 path 等价")
    paths: list[str] | None = Field(default=None, description="显式多路径列表（兼容 multi_file_reader）")
    max_total_chars: int = Field(default=_DEFAULT_MAX_TOTAL_CHARS, ge=4_000)
    max_files: int = Field(default=_DEFAULT_MAX_FILES, ge=1)

    @field_validator("paths", mode="before")
    @classmethod
    def _coerce_paths(cls, v: object) -> list[str] | None:
        if v is None:
            return None
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        raise TypeError("paths 须为字符串列表或逗号分隔字符串")

    @model_validator(mode="after")
    def _comma_split_path(self) -> FileReaderInput:
        raw = (self.path or self.file_path or "").strip()
        if self.paths is None and raw and "," in raw:
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            if len(parts) > 1:
                self.paths = parts
                self.path = None
                self.file_path = None
        return self

    @model_validator(mode="after")
    def _require_source(self) -> FileReaderInput:
        has_path = bool((self.path or self.file_path or "").strip())
        has_paths = bool(self.paths)
        if has_path and has_paths:
            raise ValueError("不能同时指定 path/file_path 与 paths")
        if not has_path and not has_paths:
            raise ValueError("必须提供 path、file_path 或 paths 之一")
        return self


class FileReaderOutput(BaseModel):
    file_content: str
    file_count: int = Field(default=0, description="参与输出的文件数（含标注为 binary skipped 的条目）")


class FileReaderSkill(Skill):
    name = "file_reader"
    description = (
        "读取本地路径：自动识别单个文本文件、目录（递归拼接）或 .zip（解压后遍历）。"
        "多文件时输出统一为带路径分隔的正文；单文件时仅为原文。"
    )
    when_to_use = "需要从磁盘加载素材（单个文件、整个文件夹或压缩包、或多个路径）供下游分析/生成时"
    do_not_use_when = "仅需写入文件时用 file_writer"
    idempotent = True
    input_model = FileReaderInput
    output_model = FileReaderOutput

    async def execute(self, inputs: FileReaderInput, context: dict) -> FileReaderOutput:
        if inputs.paths:
            return self._run_explicit_paths(inputs)
        path_str = (inputs.path or inputs.file_path or "").strip()
        p = Path(path_str).expanduser()
        return self._run_single_path(p, inputs)

    def _run_explicit_paths(self, inputs: FileReaderInput) -> FileReaderOutput:
        assert inputs.paths
        all_chunks: list[tuple[str, str]] = []
        total_files = 0
        any_trunc = False
        tail_extra = ""
        max_c = inputs.max_total_chars
        max_f = inputs.max_files
        running_chars = 0
        stop_paths = False

        for one in inputs.paths:
            if stop_paths:
                break
            remain_f = max(0, max_f - total_files)
            remain_c = max(0, max_c - running_chars)
            if remain_f <= 0 or remain_c <= 0:
                any_trunc = True
                tail_extra = "\n... (truncated: reached global size or file count limit)\n"
                break
            p = Path(one.strip()).expanduser()
            if not p.exists():
                raise SkillExecutionError(f"路径不存在: {p}")
            scoped = inputs.model_copy(
                update={
                    "max_files": max(1, remain_f),
                    "max_total_chars": max(4000, remain_c),
                }
            )
            if p.is_file() and p.suffix.lower() != ".zip":
                rel = str(p.resolve()).replace("\\", "/")
                block, _ = _read_file_as_chunk(rel, p)
                chunks_p, nf_p, tr_p = [("0", block)], 1, False
            else:
                chunks_p, nf_p, tr_p, _tail_p = self._collect_path(
                    p, scoped, rel_prefix=str(p.resolve()).replace("\\", "/")
                )
            for rel, body in chunks_p:
                if running_chars + len(body) > max_c:
                    any_trunc = True
                    all_chunks.append(("__limit__", "\n... (truncated: total size limit reached)\n"))
                    stop_paths = True
                    break
                all_chunks.append((rel, body))
                running_chars += len(body)
            total_files += nf_p
            any_trunc = any_trunc or tr_p
            if running_chars >= max_c:
                stop_paths = True

        text = _merge_blocks(all_chunks, raw_single_file=False)
        if any_trunc or tail_extra:
            text = text + tail_extra
        return FileReaderOutput(file_content=text, file_count=max(total_files, 1))

    def _run_single_path(self, p: Path, inputs: FileReaderInput) -> FileReaderOutput:
        if not p.exists():
            raise SkillExecutionError(f"路径不存在: {p}")
        chunks, n_files, trunc, tail = self._collect_path(p, inputs, rel_prefix="")
        raw_single = p.is_file() and p.suffix.lower() != ".zip" and len(chunks) <= 1
        body = _merge_blocks(chunks, raw_single_file=raw_single)
        if trunc or tail:
            body = body + tail
        fc = 1 if raw_single and n_files <= 1 else max(n_files, 1)
        return FileReaderOutput(file_content=body, file_count=fc)

    def _collect_path(
        self,
        p: Path,
        inputs: FileReaderInput,
        *,
        rel_prefix: str,
    ) -> tuple[list[tuple[str, str]], int, bool, str]:
        """返回 chunks, file_count, truncated, tail_note。"""
        max_c = inputs.max_total_chars
        max_f = inputs.max_files
        if p.is_file() and p.suffix.lower() == ".zip":
            with tempfile.TemporaryDirectory(prefix="myflow_zip_") as tmp:
                zp = p.resolve()
                dest = Path(tmp)
                try:
                    _safe_extract_zip(zp, dest)
                except zipfile.BadZipFile as e:
                    raise SkillExecutionError(f"无效的 zip 文件: {p}: {e}") from e
                ch, nf, tr, tail = _walk_directory(dest, max_total_chars=max_c, max_files=max_f)
                if tail.strip():
                    ch.append(("__tail__", tail))
                return ch, nf, tr, ""

        if p.is_file():
            rel = (rel_prefix + "/" + p.name).strip("/") if rel_prefix else p.name
            try:
                text = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                raw = p.read_bytes()
                if _is_probably_binary(raw):
                    block = f"=== {rel} ===\n(binary, skipped)\n"
                else:
                    text = _decode_text_bytes(raw)
                    block = f"=== {rel} ===\n{text}\n"
                return ([(rel, block)], 1, False, "")
            block = text
            return ([(rel, block)], 1, False, "")

        if p.is_dir():
            ch, nf, tr, tail = _walk_directory(
                p.resolve(), max_total_chars=max_c, max_files=max_f, rel_prefix=rel_prefix
            )
            if tail.strip():
                ch.append(("__tail__", tail))
            return ch, nf, tr, ""

        raise SkillExecutionError(f"无法处理的路径类型: {p}")


class MultiFileReaderSkill(FileReaderSkill):
    """兼容旧工作流：与 file_reader 行为一致，优先在新 YAML 中使用 file_reader。"""

    include_in_prompt_catalog = False
    name = "multi_file_reader"
    description = "兼容别名，等同于 file_reader；请在新工作流中使用 file_reader(path / paths)。"
    when_to_use = "遗留步骤名；请改为 file_reader"
    do_not_use_when = "无"
    input_model = FileReaderInput
    output_model = FileReaderOutput


class FileWriterInput(BaseModel):
    file_path: str
    content: str


class FileWriterOutput(BaseModel):
    report_path: str
    bytes_written: int


class FileWriterSkill(Skill):
    name = "file_writer"
    description = "将内容写入本地文件，返回写入路径和字节数"
    when_to_use = "需要保存生成的报告、代码、配置等到文件时"
    do_not_use_when = "读取文件（使用 file_reader）"
    idempotent = False
    input_model = FileWriterInput
    output_model = FileWriterOutput

    async def execute(self, inputs: FileWriterInput, context: dict) -> FileWriterOutput:
        raw = (inputs.file_path or "").strip()
        if not raw:
            raise SkillExecutionError(
                "写入路径为空：请检查工作流是否缺少必填输入（例如 output_path），"
                "且 --input 参数名与工作流定义的 inputs 一致。"
            )
        try:
            path = Path(raw)
            path.parent.mkdir(parents=True, exist_ok=True)
            written = path.write_text(inputs.content, encoding="utf-8")
        except Exception as e:
            raise SkillExecutionError(f"写入文件失败: {inputs.file_path}: {e}") from e
        return FileWriterOutput(report_path=str(path), bytes_written=written)
