"""Loader for owner-approved, source-grounded golden evaluation JSONL."""

from __future__ import annotations

import json
from pathlib import Path


class GoldenEvalFormatError(ValueError):
    """A golden evaluation file is malformed or lacks an approval reference."""


_REQUIRED_STRING_FIELDS = ("case_id", "employee_id", "prompt", "owner_approval")


def load_golden_eval_cases(path: str | Path) -> list[dict]:
    """Read approved cases without scoring or inventing expected business answers."""
    source = Path(path)
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise GoldenEvalFormatError(f"无法读取黄金评测 JSONL：{source}: {exc}") from exc

    cases: list[dict] = []
    seen_ids: set[str] = set()
    for line_no, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            case = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GoldenEvalFormatError(
                f"黄金评测 JSONL 第 {line_no} 行格式无效：{exc.msg}"
            ) from exc
        if not isinstance(case, dict):
            raise GoldenEvalFormatError(f"黄金评测 JSONL 第 {line_no} 行必须是 JSON 对象")

        for field in _REQUIRED_STRING_FIELDS:
            value = case.get(field)
            if not isinstance(value, str) or not value.strip():
                raise GoldenEvalFormatError(
                    f"黄金评测 JSONL 第 {line_no} 行字段 {field} 必须是非空字符串"
                )
        if case["case_id"] in seen_ids:
            raise GoldenEvalFormatError(
                f"黄金评测 JSONL 第 {line_no} 行 case_id 重复：{case['case_id']}"
            )
        seen_ids.add(case["case_id"])

        facts = case.get("expected_facts")
        forbidden = case.get("forbidden_behaviors")
        sources = case.get("required_sources")
        if not isinstance(facts, list) or not facts or any(
                not isinstance(item, str) or not item.strip() for item in facts):
            raise GoldenEvalFormatError(
                f"黄金评测 JSONL 第 {line_no} 行 expected_facts 必须是非空字符串列表"
            )
        if not isinstance(forbidden, list) or any(
                not isinstance(item, str) or not item.strip() for item in forbidden):
            raise GoldenEvalFormatError(
                f"黄金评测 JSONL 第 {line_no} 行 forbidden_behaviors 必须是字符串列表"
            )
        if not isinstance(sources, list) or not sources or any(
                not isinstance(item, dict)
                or not isinstance(item.get("source_system"), str)
                or not item["source_system"].strip()
                or not isinstance(item.get("record_id"), str)
                or not item["record_id"].strip()
                for item in sources):
            raise GoldenEvalFormatError(
                f"黄金评测 JSONL 第 {line_no} 行 required_sources 必须包含 source_system/record_id"
            )
        cases.append(case)
    if not cases:
        raise GoldenEvalFormatError("黄金评测 JSONL 至少需要一条经授权的用例")
    return cases
