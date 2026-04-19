"""Runner 对 str 入参的 dict 自动序列化（multi_file_reader → llm_analyze 等）。"""

from typing import Union

from pydantic import BaseModel

from myflow.engine.runner import (
    _expects_str_annotation,
    format_path_content_dict_as_text,
)


def test_format_path_content_dict_sorted_paths() -> None:
    text = format_path_content_dict_as_text({"b.txt": "two", "a.py": "one"})
    assert "=== a.py ===\none" in text
    assert "=== b.txt ===\ntwo" in text
    assert text.index("=== a.py ===") < text.index("=== b.txt ===")


class _M(BaseModel):
    s: str
    o: Union[str, None] = None


def test_expects_str_optional() -> None:
    fields = _M.model_fields
    assert _expects_str_annotation(fields["s"].annotation) is True
    assert _expects_str_annotation(fields["o"].annotation) is True
