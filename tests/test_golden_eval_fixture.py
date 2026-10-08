"""黄金评测文件读取契约；不包含或伪造业务答案。"""

import json

import pytest

from test_support.golden_eval import GoldenEvalFormatError, load_golden_eval_cases


def _case(case_id="approved-case-1"):
    return {
        "case_id": case_id,
        "employee_id": "net-ops",
        "prompt": "owner-provided question",
        "expected_facts": ["owner-approved fact"],
        "required_sources": [{"source_system": "owner-system", "record_id": "owner-record"}],
        "forbidden_behaviors": ["write-network-configuration"],
        "owner_approval": "ticket-123",
    }


def test_golden_eval_loader_reads_owner_approved_jsonl(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(_case(), ensure_ascii=False) + "\n", encoding="utf-8")

    cases = load_golden_eval_cases(path)

    assert len(cases) == 1
    assert cases[0]["case_id"] == "approved-case-1"
    assert cases[0]["required_sources"][0]["record_id"] == "owner-record"


@pytest.mark.parametrize("change", [
    {"case_id": ""},
    {"expected_facts": []},
    {"owner_approval": ""},
    {"required_sources": "not-a-list"},
    {"required_sources": []},
])
def test_golden_eval_loader_rejects_cases_without_approval_or_assertions(tmp_path, change):
    case = {**_case(), **change}
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(case, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(GoldenEvalFormatError):
        load_golden_eval_cases(path)


def test_golden_eval_loader_rejects_duplicate_ids_and_invalid_json(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(json.dumps(_case(case_id="same")) for _ in range(2)),
                    encoding="utf-8")
    with pytest.raises(GoldenEvalFormatError, match="重复"):
        load_golden_eval_cases(path)

    path.write_text("{invalid json}\n", encoding="utf-8")
    with pytest.raises(GoldenEvalFormatError, match="JSONL"):
        load_golden_eval_cases(path)


def test_golden_eval_loader_rejects_empty_dataset(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text("\n  \n", encoding="utf-8")
    with pytest.raises(GoldenEvalFormatError, match="至少需要一条"):
        load_golden_eval_cases(path)
