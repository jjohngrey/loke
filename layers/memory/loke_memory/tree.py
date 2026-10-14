"""Small B+ tree of canonical log references, maintained under the learner lock."""
from uuid import uuid4

from sqlalchemy import func, insert, select, update

from . import tiered_tables as db


class LogTree:
    def __init__(self, conn, learner, generation, root):
        self.conn, self.learner, self.generation, self.root = conn, learner, generation, root

    def get(self, key):
        row = self.conn.execute(select(db.nodes).where(db.nodes.c.learner_id == self.learner,
                                                       db.nodes.c.key == key)).mappings().one()
        return dict(row["data"], id=key, parent=row["parent_id"])

    def put(self, node, new=False):
        value = {k: v for k, v in node.items() if k not in {"id", "parent"}}
        if new:
            self.conn.execute(insert(db.nodes).values(learner_id=self.learner, generation_id=self.generation,
                key=node["id"], root_id=self.root, parent_id=node["parent"], data=value))
        else:
            self.conn.execute(update(db.nodes).where(db.nodes.c.learner_id == self.learner,
                db.nodes.c.key == node["id"]).values(data=value, parent_id=node["parent"]))

    def create(self):
        self.put(dict(id=self.root, parent=None, children=[], count=0, tokens=0,
                      low=None, high=None, version=0, saturated=False), new=True)

    def append(self, key, sequence, token_count):
        path = [self.get(self.root)]
        while path[-1]["children"]:
            path.append(self.get(path[-1]["children"][-1]))
        leaf = path[-1]
        self.conn.execute(insert(db.assignments).values(learner_id=self.learner,
            generation_id=self.generation, key=key, node_id=leaf["id"], sequence=sequence, data={}))
        for node in path:
            node["count"] += 1
            node["tokens"] += token_count
            node["low"] = node["low"] or sequence
            node["high"] = sequence
            node["version"] += 1
            self.put(node)

    def _aggregate(self, ids):
        children = [self.get(key) for key in ids]
        return dict(children=ids, count=sum(c["count"] for c in children),
                    tokens=sum(c["tokens"] for c in children), low=children[0]["low"],
                    high=children[-1]["high"], version=0, saturated=False)

    def _reparent(self, ids, parent):
        for key in ids:
            child = self.get(key)
            child["parent"] = parent
            self.put(child)

    def split(self, key, fanout=8, max_depth=6):
        leaf = self.get(key)
        if leaf["children"] or leaf["count"] < 2:
            return False
        ancestors = []
        current = leaf
        while current["parent"]:
            current = self.get(current["parent"])
            ancestors.append(current)
        # Adding a level only happens if every ancestor is full (or the root is a leaf).
        if len(ancestors) >= max_depth and all(len(n["children"]) >= fanout for n in ancestors):
            root = self.get(self.root)
            root["saturated"] = True
            self.put(root)
            return False
        median = self.conn.execute(select(db.assignments.c.sequence).where(
            db.assignments.c.learner_id == self.learner, db.assignments.c.node_id == key)
            .order_by(db.assignments.c.sequence).offset(leaf["count"] // 2).limit(1)).scalar_one()
        left_id = str(uuid4()) if not leaf["parent"] else leaf["id"]
        right_id = str(uuid4())
        parent = leaf["parent"] or leaf["id"]
        for child_id, lower in ((left_id, True), (right_id, False)):
            condition = db.assignments.c.sequence < median if lower else db.assignments.c.sequence >= median
            query = select(func.count(), func.sum(db.logs.c.token_count),
                           func.min(db.assignments.c.sequence), func.max(db.assignments.c.sequence)).select_from(
                db.assignments.join(db.logs, (db.assignments.c.learner_id == db.logs.c.learner_id) &
                                    (db.assignments.c.key == db.logs.c.key))).where(
                db.assignments.c.learner_id == self.learner, db.assignments.c.node_id == key, condition)
            count, token_count, low, high = self.conn.execute(query).one()
            child = dict(id=child_id, parent=parent, children=[], count=count, tokens=token_count,
                         low=low, high=high, version=0, saturated=False)
            self.put(child, new=child_id != key)
        # Both groups are moved only after their nodes exist, preserving FK integrity.
        for child_id, condition in ((left_id, db.assignments.c.sequence < median),
                                    (right_id, db.assignments.c.sequence >= median)):
            self.conn.execute(update(db.assignments).where(db.assignments.c.learner_id == self.learner,
                db.assignments.c.node_id == key, condition).values(node_id=child_id))
        if not leaf["parent"]:
            self.put(dict(id=self.root, parent=None, **self._aggregate([left_id, right_id])))
        else:
            parent_node = self.get(parent)
            position = parent_node["children"].index(key)
            parent_node["children"].insert(position + 1, right_id)
            parent_node["version"] += 1
            self.put(parent_node)
            self._balance(parent, fanout)
        root = self.get(self.root)
        root["version"] += 1
        self.put(root)
        return True

    def _balance(self, key, fanout):
        node = self.get(key)
        if len(node["children"]) <= fanout:
            return
        middle = len(node["children"]) // 2
        left_ids, right_ids = node["children"][:middle], node["children"][middle:]
        left_id = str(uuid4()) if not node["parent"] else key
        right_id = str(uuid4())
        parent = node["parent"] or key
        self.put(dict(id=left_id, parent=parent, **self._aggregate(left_ids)), new=left_id != key)
        self.put(dict(id=right_id, parent=parent, **self._aggregate(right_ids)), new=True)
        self._reparent(left_ids, left_id)
        self._reparent(right_ids, right_id)
        if node["parent"] is None:
            self.put(dict(id=self.root, parent=None, **self._aggregate([left_id, right_id])))
        else:
            parent_node = self.get(parent)
            position = parent_node["children"].index(key)
            parent_node["children"].insert(position + 1, right_id)
            parent_node["version"] += 1
            self.put(parent_node)
            self._balance(parent, fanout)
