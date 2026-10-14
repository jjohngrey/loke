"""Tiered context and per-category logs. Summaries never replace canonical records."""
import hashlib
import json
import math
from datetime import UTC, datetime
from uuid import uuid4

from loke_contracts.memory import (
    AgentMatch,
    ChatScope,
    ConflictError,
    MemoryContext,
    MemoryExcerpt,
    OperationalAction,
)
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Integer, any_, cast, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from . import tables as base
from . import tiered_tables as db
from .retrieval import tokens
from .tree import LogTree


class MemoryLimits(BaseModel):
    summary_trigger: int = Field(default=100, ge=4, le=1000)
    recent_messages: int = Field(default=40, ge=1, le=100)
    summaries_per_tier: int = Field(default=8, ge=2, le=8)
    leaf_records: int = Field(default=200, ge=2, le=1000)
    leaf_tokens: int = Field(default=12000, ge=100, le=50000)
    fanout: int = Field(default=8, ge=2, le=8)
    max_depth: int = Field(default=6, ge=1, le=6)
    context_tokens: int = Field(default=3000, ge=100, le=3000)
    batch_size: int = Field(default=10, ge=1, le=10)

    @model_validator(mode="after")
    def valid_tail(self):
        if self.recent_messages >= self.summary_trigger:
            raise ValueError("Recent-message tail must be smaller than summary trigger.")
        return self


def estimate(text):
    # Versioned conservative byte-based estimator, not a claim of provider token counts.
    return max(1, math.ceil(len(text.encode("utf-8")) / 3))


def identity(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def _excerpt(row, kind):
    data = row["data"]
    return MemoryExcerpt(role=data.get("role"), action_status=data.get("action", {}).get("status"), record_id=row["key"], agent_id=data.get("agent_id"),
        chat_id=row["chat_id"], kind=kind, text=data["text"],
        observed_at=data["observed_at"], reference_ids=[row["key"]] if kind == "summary" else data.get("reference_ids", []))


class TieredMemory:
    limits = MemoryLimits()

    def ensure_category_agent(self, learner_id, generation_id, category):
        if not category or len(category) > 120:
            raise ValueError("Category must contain 1 to 120 characters.")
        with self.engine.begin() as conn:
            generation = self._lock(conn, learner_id)
            current = self._profile(conn, learner_id, generation)
            if generation != generation_id or not current["storage_consent"]:
                raise ConflictError("Category memory is not consented or was reset.")
            existing = conn.execute(select(base.agents.c.key).where(base.agents.c.learner_id == learner_id,
                base.agents.c.subject == category)).scalar_one_or_none()
            if existing:
                return existing
            key = str(uuid4())
            conn.execute(insert(base.agents).values(learner_id=learner_id, generation_id=generation,
                key=key, subject=category, data=dict(subject_key=category, prompt_version="memory-v1")))
            return key

    def _message(self, conn, learner, generation, scope, request, role, text, references, operation):
        key = identity(scope.chat_id, request, role)
        value = dict(role=role, text=text, scope=scope.model_dump(), reference_ids=references, operation=operation)
        previous = conn.execute(select(db.messages.c.data).where(db.messages.c.learner_id == learner,
            db.messages.c.key == key)).scalar_one_or_none()
        if previous:
            if any(previous[k] != v for k, v in value.items()):
                raise ConflictError("Interaction ID cannot overwrite different content.")
            return key
        sequence = (conn.execute(select(func.max(db.messages.c.sequence)).where(
            db.messages.c.learner_id == learner, db.messages.c.chat_id == scope.chat_id)).scalar() or 0) + 1
        value["observed_at"] = datetime.now(UTC).isoformat()
        conn.execute(insert(db.messages).values(learner_id=learner, generation_id=generation,
            key=key, chat_id=scope.chat_id, sequence=sequence, observed_at=value["observed_at"], data=value))
        return key

    def _log(self, conn, learner, generation, root_id, action_id, scope, text, references, action):
        action = OperationalAction.model_validate(action).model_dump(mode="json")
        if len(text) > 32000 or len(references) > 100:
            raise ValueError("Operational log payload exceeds its bounds.")
        root = conn.execute(select(base.agents.c.key).where(base.agents.c.learner_id == learner,
            base.agents.c.generation_id == generation, base.agents.c.key == root_id)).first()
        if not root:
            raise ValueError("Category agent is outside this learner generation.")
        key = identity(root_id, action_id)
        data = dict(text=text, reference_ids=references, action=action,
                    scope=scope.model_dump(), agent_id=root_id)
        previous = conn.execute(select(db.logs.c.data).where(db.logs.c.learner_id == learner,
            db.logs.c.key == key)).scalar_one_or_none()
        if previous:
            if any(previous[k] != v for k, v in data.items()):
                raise ConflictError("Action ID cannot overwrite different operational history.")
            return key
        sequence = (conn.execute(select(func.max(db.logs.c.sequence)).where(
            db.logs.c.learner_id == learner, db.logs.c.root_id == root_id)).scalar() or 0) + 1
        now = datetime.now(UTC)
        data["observed_at"] = now.isoformat()
        conn.execute(insert(db.logs).values(learner_id=learner, generation_id=generation,
            key=key, root_id=root_id, chat_id=scope.chat_id, sequence=sequence, observed_at=now,
            terms=sorted(tokens(text))[:5000], token_count=estimate(text), concept_tags=scope.concept_tags,
            node_tags=scope.node_tags, project_id=scope.project_id, folder_path=scope.folder_path, data=data))
        tree = LogTree(conn, learner, generation, root_id)
        if not conn.execute(select(db.nodes.c.key).where(db.nodes.c.learner_id == learner,
                                                         db.nodes.c.key == root_id)).first():
            tree.create()
        tree.append(key, sequence, estimate(text))
        return key

    def append_agent_log(self, learner_id, generation_id, root_id, action_id, scope: ChatScope,
                         text, reference_ids, action):
        with self.engine.begin() as conn:
            generation = self._lock(conn, learner_id)
            current = self._profile(conn, learner_id, generation)
            if generation != generation_id or not current["storage_consent"]:
                raise ConflictError("Operational memory is not consented or was reset.")
            return self._log(conn, learner_id, generation, root_id, action_id, scope,
                             text, reference_ids, action)

    def record_turn(self, learner_id, generation_id, request_id, scope: ChatScope, user_text, response,
                    root_id, references=None, action=None):
        if len(user_text) > 15000 or len(response) > 16000:
            raise ValueError("Interaction payload exceeds its bounds.")
        with self.engine.begin() as conn:
            generation = self._lock(conn, learner_id)
            current = self._profile(conn, learner_id, generation)
            if generation != generation_id or not current["storage_consent"]:
                raise ConflictError("Conversation memory was reset or is not consented.")
            return self._record_turn(conn, learner_id, generation, request_id, scope, user_text,
                                     response, root_id, references or [], action or {})

    def _record_turn(self, conn, learner, generation, request, scope, user_text, response, root, references, action):
        user = self._message(conn, learner, generation, scope, request, "user", user_text, references, action.get("operation", "action"))
        assistant = self._message(conn, learner, generation, scope, request, "assistant", response, references, action.get("operation", "action"))
        record = self._log(conn, learner, generation, root, request, scope,
                           user_text + "\n" + response, references + [user, assistant], action)
        return dict(user=user, assistant=assistant, log=record)

    def search_agents(self, learner_id, generation_id, query, scope: ChatScope, limit=3):
        if not 1 <= limit <= 5:
            raise ValueError("Agent-search limit must be 1 to 5.")
        words = sorted(tokens(query))[:100]
        with self.engine.begin() as conn:
            generation = self._lock(conn, learner_id)
            if generation != generation_id:
                raise ConflictError("Agent memory was reset.")
            content = sum((cast(word == any_(db.logs.c.terms), Integer) for word in words), 0)
            concepts = sum((cast(tag == any_(db.logs.c.concept_tags), Integer) for tag in scope.concept_tags), 0)
            node_tags = sum((cast(tag == any_(db.logs.c.node_tags), Integer) for tag in scope.node_tags), 0)
            folder = sum((cast(tag == any_(db.logs.c.folder_path), Integer) for tag in scope.folder_path), 0)
            project = cast(db.logs.c.project_id == scope.project_id, Integer) if scope.project_id else 0
            # A folder/project hint cannot qualify a record with no content or concept match.
            eligible = or_(db.logs.c.terms.overlap(words), db.logs.c.concept_tags.overlap(scope.concept_tags),
                           db.logs.c.node_tags.overlap(scope.node_tags))
            score = content * 4 + concepts * 3 + node_tags * 3 + folder + func.coalesce(project, 0)
            rows = list(conn.execute(select(db.logs, db.assignments.c.node_id, score.label("score"))
                .join(db.assignments, (db.logs.c.learner_id == db.assignments.c.learner_id) &
                                      (db.logs.c.key == db.assignments.c.key))
                .where(db.logs.c.learner_id == learner_id, db.logs.c.generation_id == generation, eligible)
                .order_by(score.desc(), db.logs.c.observed_at.desc(), db.logs.c.key).limit(51)).mappings())
            matches = {}
            candidate_truncated = len(rows) > 50
            for row in rows[:50]:
                node = row["node_id"]
                if node not in matches and len(matches) >= limit:
                    continue
                if node not in matches:
                    reasons = []
                    if words and set(words) & set(row["terms"]):
                        reasons.append("content_match")
                    if set(scope.concept_tags) & set(row["concept_tags"]):
                        reasons.append("concept_tag")
                    if set(scope.node_tags) & set(row["node_tags"]):
                        reasons.append("node_tag")
                    if scope.project_id and scope.project_id == row["project_id"]:
                        reasons.append("project_hint")
                    if set(scope.folder_path) & set(row["folder_path"]):
                        reasons.append("folder_hint")
                    matches[node] = AgentMatch(agent_id=node, root_id=row["root_id"], score=row["score"],
                                               record_ids=[], reasons=reasons, candidate_scan_truncated=candidate_truncated)
                if len(matches[node].record_ids) < 3:
                    matches[node].record_ids.append(row["key"])
            return list(matches.values())

    def memory_context(self, learner_id, generation_id, query, scope: ChatScope):
        # Capture the candidates outside this read transaction, then validate generation again.
        matches = self.search_agents(learner_id, generation_id, query, scope)
        with self.engine.begin() as conn:
            if self._lock(conn, learner_id) != generation_id:
                raise ConflictError("Conversation memory was reset.")
            recent = list(conn.execute(select(db.messages).where(db.messages.c.learner_id == learner_id,
                db.messages.c.chat_id == scope.chat_id).order_by(db.messages.c.sequence.desc())
                .limit(self.limits.recent_messages + 1)).mappings())
            summaries = list(conn.execute(select(db.summaries).where(db.summaries.c.learner_id == learner_id,
                db.summaries.c.chat_id == scope.chat_id, db.summaries.c.active == 1)
                .order_by(db.summaries.c.end_sequence.desc()).limit(9)).mappings())
            ids = [key for match in matches for key in match.record_ids]
            logs = list(conn.execute(select(db.logs).where(db.logs.c.learner_id == learner_id,
                db.logs.c.key.in_(ids)).order_by(db.logs.c.observed_at.desc(), db.logs.c.key)).mappings())
            result = MemoryContext(generation_id=generation_id, matches=matches,
                truncated=len(recent) > self.limits.recent_messages or len(summaries) > 8
                    or any(m.candidate_scan_truncated for m in matches)
                    or any(r["data"].get("truncated", False) for r in summaries))
            result.maintenance_saturated = bool(conn.execute(select(db.nodes.c.key).where(
                db.nodes.c.learner_id == learner_id, db.nodes.c.parent_id.is_(None),
                db.nodes.c.data["saturated"].as_boolean().is_(True)).limit(1)).first())
            budget = self.limits.context_tokens - estimate(result.model_dump_json()) - 100
            # Recent chat first, selected category logs next, summaries last. Output records carry citations.
            groups = ((recent[:self.limits.recent_messages], "interaction", result.recent),
                      (logs, "agent_log", result.logs), (summaries[:8], "summary", result.summaries))
            for rows, kind, target in groups:
                fraction = {"interaction": 0.5, "agent_log": 0.3, "summary": 0.2}[kind]
                group_budget = min(budget, int(self.limits.context_tokens * fraction))
                for row in rows:
                    excerpt = _excerpt(row, kind)
                    overhead = estimate(excerpt.model_dump_json(exclude={"text"}))
                    if min(budget, group_budget) <= overhead:
                        result.truncated = True
                        continue
                    allowed = min(estimate(excerpt.text), min(budget, group_budget) - overhead)
                    if estimate(excerpt.text) > allowed:
                        # UTF-8 byte slicing makes the estimator bound true for multilingual text too.
                        excerpt.text = excerpt.text.encode()[:allowed * 3].decode("utf-8", errors="ignore")
                        result.truncated = True
                    target.append(excerpt)
                    cost = overhead + estimate(excerpt.text)
                    budget -= cost
                    group_budget -= cost
            result.recent.reverse()
            return result

    def memory_node(self, learner_id, generation_id, key, after_sequence=0, limit=25, expected_tree_version=None):
        if not 1 <= limit <= 100 or after_sequence < 0:
            raise ValueError("Tree read bounds exceeded.")
        with self.engine.begin() as conn:
            if self._lock(conn, learner_id) != generation_id:
                raise ConflictError("Memory tree was reset.")
            node = conn.execute(select(db.nodes).where(db.nodes.c.learner_id == learner_id,
                                                       db.nodes.c.key == key)).mappings().first()
            if node is None:
                return None
            tree_version = conn.execute(select(db.nodes.c.data["version"].as_integer()).where(
                db.nodes.c.learner_id == learner_id, db.nodes.c.key == node["root_id"])).scalar_one()
            if expected_tree_version is not None and tree_version != expected_tree_version:
                raise ConflictError("Memory tree changed. Reload node references.")
            records = list(conn.execute(select(db.assignments.c.key, db.assignments.c.sequence).where(
                db.assignments.c.learner_id == learner_id, db.assignments.c.node_id == key,
                db.assignments.c.sequence > after_sequence).order_by(db.assignments.c.sequence)
                .limit(limit + 1)))
            return dict(node["data"], id=key, root_id=node["root_id"], parent_id=node["parent_id"], tree_version=tree_version,
                record_ids=[r[0] for r in records[:limit]], truncated=len(records) > limit,
                next_sequence=records[limit - 1][1] if len(records) > limit else None)

    def original_record(self, learner_id, generation_id, key):
        with self.engine.begin() as conn:
            if self._lock(conn, learner_id) != generation_id:
                raise ConflictError("Original memory was reset.")
            for table in (db.messages, db.logs, db.summaries):
                row = conn.execute(select(table.c.data).where(table.c.learner_id == learner_id,
                                                              table.c.key == key)).scalar_one_or_none()
                if row is not None:
                    return row
            return None

    def maintain_memory(self, learner_id, generation_id):
        with self.engine.begin() as conn:
            generation = self._lock(conn, learner_id)
            if generation != generation_id:
                raise ConflictError("Memory maintenance belongs to an old generation.")
            checkpoints = select(db.summaries.c.chat_id, func.max(db.summaries.c.end_sequence).label("last")).where(
                db.summaries.c.learner_id == learner_id).group_by(db.summaries.c.chat_id).subquery()
            chats = list(conn.execute(select(db.messages.c.chat_id).outerjoin(checkpoints,
                db.messages.c.chat_id == checkpoints.c.chat_id).where(db.messages.c.learner_id == learner_id,
                db.messages.c.sequence > func.coalesce(checkpoints.c.last, 0))
                .group_by(db.messages.c.chat_id).having(func.count() >= self.limits.summary_trigger)
                .order_by(func.min(db.messages.c.observed_at), db.messages.c.chat_id)
                .limit(self.limits.batch_size)).scalars())
            for chat in chats:
                self._summarize(conn, learner_id, generation, chat)
            # Select a bounded number of oversized leaves, then split references using SQL.
            leaves = list(conn.execute(select(db.nodes).where(db.nodes.c.learner_id == learner_id,
                func.json_array_length(db.nodes.c.data["children"]) == 0,
                db.nodes.c.data["count"].as_integer() > 1,
                or_(db.nodes.c.data["count"].as_integer() > self.limits.leaf_records,
                    db.nodes.c.data["tokens"].as_integer() > self.limits.leaf_tokens))
                .order_by(db.nodes.c.data["count"].as_integer().desc(), db.nodes.c.key)
                .limit(self.limits.batch_size)).mappings())
            split = 0
            for row in leaves[:self.limits.batch_size]:
                if LogTree(conn, learner_id, generation, row["root_id"]).split(row["key"],
                        self.limits.fanout, self.limits.max_depth):
                    split += 1
            return dict(chats=len(chats), splits=split)

    def _summarize(self, conn, learner, generation, chat):
        checkpoint = conn.execute(select(func.max(db.summaries.c.end_sequence)).where(
            db.summaries.c.learner_id == learner, db.summaries.c.chat_id == chat)).scalar() or 0
        rows = list(conn.execute(select(db.messages).where(db.messages.c.learner_id == learner,
            db.messages.c.chat_id == chat, db.messages.c.sequence > checkpoint)
            .order_by(db.messages.c.sequence).limit(self.limits.summary_trigger)).mappings())
        if len(rows) >= self.limits.summary_trigger:
            covered = rows[:self.limits.summary_trigger - self.limits.recent_messages]
            references = [r["key"] for r in covered]
            entries = [dict(role=r["data"]["role"], observed_at=r["data"]["observed_at"],
                            text=r["data"]["text"][:240], record_id=r["key"],
                            reference_ids=r["data"]["reference_ids"], operation=r["data"].get("operation", "unknown"),
                            truncated=len(r["data"]["text"]) > 240) for r in covered]
            goals = [e for e in entries if e["role"] == "user" and e["operation"] == "goal"]
            explicit = [e for e in entries if e["role"] == "user" and
                        any(term in e["text"].lower() for term in ("i prefer", "my goal", "i want", "i need"))]
            anchors = "\n".join(f"{e['observed_at']} explicit user statement [{e['record_id']}]: {e['text']}"
                                for e in goals + explicit)
            text = anchors + "\n" + "\n".join(f"{e['observed_at']} {e['role']}: {e['text']}" for e in entries)
            self._summary(conn, learner, generation, chat, 0, covered[0]["sequence"],
                          covered[-1]["sequence"], text, references, entries)
        for tier in range(self.limits.max_depth):
            old = list(conn.execute(select(db.summaries).where(db.summaries.c.learner_id == learner,
                db.summaries.c.chat_id == chat, db.summaries.c.tier == tier, db.summaries.c.active == 1)
                .order_by(db.summaries.c.start_sequence).limit(self.limits.summaries_per_tier + 1)).mappings())
            if len(old) <= self.limits.summaries_per_tier:
                break
            children = old[:self.limits.summaries_per_tier]
            references = [r["key"] for r in children]
            text = "\n".join(r["data"]["text"][:600] for r in children)
            self._summary(conn, learner, generation, chat, tier + 1, children[0]["start_sequence"],
                          children[-1]["end_sequence"], text, references, [])
            conn.execute(update(db.summaries).where(db.summaries.c.learner_id == learner,
                db.summaries.c.key.in_(references)).values(active=0))

    @staticmethod
    def _summary(conn, learner, generation, chat, tier, start, end, text, references, entries):
        key = identity(chat, tier, start, end)
        value = dict(text=text[:6000], truncated=len(text) > 6000 or any(e.get("truncated") for e in entries), observed_at=datetime.now(UTC).isoformat(), reference_ids=references,
            entries=entries, generator="extractive-v1", token_estimator="utf8-bytes-v1",
            source_fingerprint=identity(references), start_sequence=start, end_sequence=end,
            goals_preferences=[e for e in entries if e["role"] == "user" and (e.get("operation") == "goal" or
                any(term in e["text"].lower() for term in ("i prefer", "my goal", "i want", "i need")))],
            question_refs=[e["record_id"] for e in entries if e["role"] == "user" and "?" in e["text"]],
            completion_status="Only committed responses are logged; question resolution is not inferred.")
        conn.execute(pg_insert(db.summaries).values(learner_id=learner, generation_id=generation,
            key=key, chat_id=chat, tier=tier, start_sequence=start, end_sequence=end, active=1,
            data=value).on_conflict_do_nothing())
