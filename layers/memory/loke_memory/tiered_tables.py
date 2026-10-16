"""Canonical chat/log rows and derived summaries/tree routing records."""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKeyConstraint, Index, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY

from .tables import scoped

messages = scoped("memory_messages", Column("chat_id", String, nullable=False),
    Column("sequence", BigInteger, nullable=False), Column("observed_at", DateTime(timezone=True), nullable=False))
Index("memory_messages_chat", messages.c.learner_id, messages.c.chat_id, messages.c.sequence)
logs = scoped("memory_agent_logs", Column("root_id", String, nullable=False),
    Column("chat_id", String, nullable=False), Column("sequence", BigInteger, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("terms", ARRAY(String), nullable=False), Column("token_count", Integer, nullable=False),
    Column("concept_tags", ARRAY(String), nullable=False), Column("node_tags", ARRAY(String), nullable=False),
    Column("project_id", String), Column("folder_path", ARRAY(String), nullable=False),
    constraints=(ForeignKeyConstraint(["learner_id", "root_id"],
                                      ["memory_agents.learner_id", "memory_agents.key"], ondelete="CASCADE"),))
Index("memory_logs_terms", logs.c.terms, postgresql_using="gin")
Index("memory_logs_concepts", logs.c.concept_tags, postgresql_using="gin")
Index("memory_logs_nodes", logs.c.node_tags, postgresql_using="gin")
Index("memory_logs_sequence", logs.c.learner_id, logs.c.root_id, logs.c.sequence)
summaries = scoped("memory_summaries", Column("chat_id", String, nullable=False),
    Column("tier", Integer, nullable=False), Column("start_sequence", BigInteger, nullable=False),
    Column("end_sequence", BigInteger, nullable=False), Column("active", Integer, nullable=False))
Index("memory_summaries_chat", summaries.c.learner_id, summaries.c.chat_id, summaries.c.active)
nodes = scoped("memory_nodes", Column("root_id", String, nullable=False), Column("parent_id", String),
    constraints=(ForeignKeyConstraint(["learner_id", "root_id"],
        ["memory_agents.learner_id", "memory_agents.key"], ondelete="CASCADE"),
        ForeignKeyConstraint(["learner_id", "parent_id"], ["memory_nodes.learner_id", "memory_nodes.key"],
                             ondelete="CASCADE")))
assignments = scoped("memory_assignments", Column("node_id", String, nullable=False),
    Column("sequence", BigInteger, nullable=False),
    constraints=(ForeignKeyConstraint(["learner_id", "key"],
        ["memory_agent_logs.learner_id", "memory_agent_logs.key"], ondelete="CASCADE"),
        ForeignKeyConstraint(["learner_id", "node_id"],
        ["memory_nodes.learner_id", "memory_nodes.key"], ondelete="CASCADE")))
Index("memory_assignments_node", assignments.c.learner_id, assignments.c.node_id, assignments.c.sequence)
