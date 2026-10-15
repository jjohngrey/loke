"""Run before npm run contracts:generate to keep frontend types in sync."""

import json
from pathlib import Path

from loke_contracts.models import ContractBundle as LearningContractBundle
from loke_contracts.runtime import (
    RunEvent,
    RunLimits,
    RunOutcome,
    RuntimeCancelResult,
    RuntimeControl,
    RuntimeRequest,
    RuntimeReset,
    RuntimeResetResult,
)


class ContractBundle(LearningContractBundle):
    runtime_request: RuntimeRequest
    runtime_control: RuntimeControl
    runtime_reset: RuntimeReset
    runtime_reset_result: RuntimeResetResult
    runtime_cancel_result: RuntimeCancelResult
    run_limits: RunLimits
    run_event: RunEvent
    run_outcome: RunOutcome

root = Path(__file__).resolve().parent.parent
out = root / "shared/contracts/generated/contracts.schema.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(ContractBundle.model_json_schema(), indent=2) + "\n")
print(out.relative_to(root))
