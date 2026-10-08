# Owner-approved golden evaluation JSONL

Pass the path with `UE_GOLDEN_EVAL_PATH=/absolute/path/cases.jsonl`; pytest's
`golden_eval_cases` fixture reads one JSON object per non-empty line. The loader
validates structure and approval references only. It does not call a model or
score answers.

Each case must contain:

- `case_id`, `employee_id`, and `prompt`: stable case identity and authorized input.
- `expected_facts`: non-empty list of owner-approved facts that a future evaluator
  may check; do not author these from synthetic or unverified business records.
- `required_sources`: list of `{ "source_system": "...", "record_id": "..." }`
  provenance constraints. Extend with owner-defined timestamps or metadata when
  the source system provides them.
- `forbidden_behaviors`: list of prohibited actions or claims; it may be empty.
- `owner_approval`: ticket or other auditable reference authorizing the data and
  expected assertions for this evaluation.

No golden cases are checked into this repository yet. A business owner must
provide authorized data and expected assertions before an answer-correctness
evaluation can run or be reported as passing.
