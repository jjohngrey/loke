"""Historical bootstrap schema for migration fixtures only. Runtime uses tables.py."""

from sqlalchemy import JSON, Column, Integer, MetaData, String, Table

metadata = MetaData()


def record_table(name: str) -> Table:
    return Table(
        name,
        metadata,
        Column("id", String, primary_key=True),
        Column("learner_id", String, index=True),
        Column("data", JSON, nullable=False),
    )


learners = Table(
    "learners",
    metadata,
    Column("id", String, primary_key=True),
    Column("revision", Integer, nullable=False, default=0),
    Column("data", JSON, nullable=False),
)
agents = record_table("agents")
concepts = record_table("concepts")
events = record_table("learning_events")
states = record_table("concept_state")
sources = record_table("sources")
plans = record_table("plans")
jobs = record_table("jobs")
