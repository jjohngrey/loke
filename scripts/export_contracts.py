"""Run before npm run contracts:generate to keep frontend types in sync."""

import json
from pathlib import Path

from loke_contracts.models import ContractBundle

root = Path(__file__).resolve().parent.parent
out = root / "shared/contracts/generated/contracts.schema.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(ContractBundle.model_json_schema(), indent=2) + "\n")
print(out.relative_to(root))
