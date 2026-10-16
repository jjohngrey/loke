"""Versioned PostgreSQL schema. Domain payloads stay JSON; invariants are relational."""
from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY

metadata = MetaData()
versions = Table("memory_schema_version", metadata,
                 Column("version", Integer, primary_key=True))
generations = Table("memory_generations", metadata,
                    Column("learner_id", String, primary_key=True),
                    Column("generation_id", String, nullable=False))
learners = Table("memory_learners", metadata,
    Column("learner_id", String, ForeignKey("memory_generations.learner_id"), primary_key=True),
    Column("generation_id", String, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False, index=True),
    Column("data", JSON, nullable=False),
    UniqueConstraint("learner_id", "generation_id"))


def scoped(name, *columns, constraints=()):
    return Table(name, metadata,
        Column("learner_id", String, primary_key=True),
        Column("key", String, primary_key=True),
        Column("generation_id", String, nullable=False),
        Column("data", JSON, nullable=False),
        *columns,
        ForeignKeyConstraint(["learner_id", "generation_id"],
                             ["memory_learners.learner_id", "memory_learners.generation_id"],
                             ondelete="CASCADE"), *constraints)


agents = scoped("memory_agents", Column("subject", String, nullable=False),
                constraints=(UniqueConstraint("learner_id", "generation_id", "subject"),))
events = scoped("memory_events", Column("sequence", BigInteger, nullable=False),
                Column("observed_at", DateTime(timezone=True), nullable=False),
                constraints=(UniqueConstraint("learner_id", "generation_id", "sequence"),))
states = scoped("memory_states")
sources = scoped("memory_sources", Column("terms", ARRAY(String), nullable=False))
Index("memory_sources_terms", sources.c.terms, postgresql_using="gin")
plans = scoped("memory_plans")
notifications = scoped("memory_notifications")
jobs = scoped("memory_jobs", Column("kind", String, nullable=False),
              Column("status", String, nullable=False),
              Column("due_at", DateTime(timezone=True), nullable=False),
              Column("lease_token", String), Column("lease_owner", String),
              Column("lease_until", DateTime(timezone=True)),
              Column("attempts", Integer, nullable=False, default=0))
Index("memory_jobs_due", jobs.c.kind, jobs.c.status, jobs.c.due_at)
outcomes = scoped("memory_outcomes", Column("fingerprint", String, nullable=False),
                  Column("created_at", DateTime(timezone=True), nullable=False),
                  Column("expires_at", DateTime(timezone=True), nullable=False))
objects = scoped("memory_objects", Column("kind", String, nullable=False),
                 Column("document_id", String, nullable=False))
corrections = scoped("memory_corrections", Column("event_id", String, nullable=False),
                     constraints=(ForeignKeyConstraint(["learner_id", "event_id"],
                                  ["memory_events.learner_id", "memory_events.key"]),))
