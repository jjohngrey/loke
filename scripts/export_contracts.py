"""Run before npm run contracts:generate to keep frontend types in sync."""

import json
from pathlib import Path

from loke_contracts.memory import CommitGuard, JobLease
from loke_contracts.models import ChatScope, ContractBundle, MemoryContext
from loke_contracts.source import SourceDocument, SourceGraph


class PublishedContracts(ContractBundle):
    commit_guard: CommitGuard
    job_lease: JobLease
    chat_scope: ChatScope
    memory_context: MemoryContext
    source_document: SourceDocument
    source_graph: SourceGraph

root = Path(__file__).resolve().parent.parent
out = root / "shared/contracts/generated/contracts.schema.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(PublishedContracts.model_json_schema(), indent=2) + "\n")
print(out.relative_to(root))
