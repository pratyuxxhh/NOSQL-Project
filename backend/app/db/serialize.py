"""Convert Neo4j values (nodes, relationships, paths, temporal types) to JSON-safe
dicts for the API and the dashboard's graph views. Sensitive values are masked."""

from datetime import date, datetime
from typing import Any

from neo4j.graph import Node, Path, Relationship

HIDDEN = {"password_hash", "key_hash"}
# Property that names a node, per label, for display.
KEY_PROPERTY = {
    "Device": "device_id",
    "Card": "card_hash",
    "Phone": "number_hash",
    "Ring": "ring_id",
}


def jsonable(value: Any) -> Any:
    if hasattr(value, "iso_format"):  # neo4j.time.DateTime / Date
        return value.iso_format()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    return value


def props(entity: Node | Relationship) -> dict[str, Any]:
    return {k: jsonable(v) for k, v in dict(entity).items() if k not in HIDDEN}


def node_label(node: Node) -> str:
    return next(iter(node.labels), "Node")


def node_key(node: Node) -> str:
    label = node_label(node)
    return str(node.get(KEY_PROPERTY.get(label, "id"), node.element_id))


def node_caption(node: Node) -> str:
    """Short display name; hashes are never shown in full."""
    label = node_label(node)
    if label == "Card":
        return f"Card ****{node.get('last4', '????')}"
    if label == "Phone":
        return f"Phone #{str(node.get('number_hash', ''))[:6]}"
    if label == "Address":
        return f"{node.get('line', '')}, {node.get('city', '')}"
    if label == "User":
        return node.get("name", node_key(node))
    if label == "Merchant":
        return node.get("name", node_key(node))
    return node_key(node)


def node_dict(node: Node) -> dict[str, Any]:
    data = props(node)
    if node_label(node) in ("Card", "Phone"):  # identify by masked caption, not by hash
        data.pop("card_hash", None)
        data.pop("number_hash", None)
    return {
        "id": node.element_id,
        "key": node_key(node),
        "label": node_label(node),
        "caption": node_caption(node),
        "props": data,
    }


def rel_dict(rel: Relationship) -> dict[str, Any]:
    return {
        "id": rel.element_id,
        "source": rel.start_node.element_id,
        "target": rel.end_node.element_id,
        "type": rel.type,
        "props": props(rel),
    }


class GraphBuilder:
    """Collects nodes and relationships (deduplicated) into {nodes, edges}."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.edges: dict[str, dict] = {}

    def add(self, value: Any) -> None:
        if isinstance(value, Node):
            self.nodes.setdefault(value.element_id, node_dict(value))
        elif isinstance(value, Relationship):
            for end in (value.start_node, value.end_node):
                if end is not None and end.element_id not in self.nodes and len(end.labels):
                    self.nodes[end.element_id] = node_dict(end)
            self.edges.setdefault(value.element_id, rel_dict(value))
        elif isinstance(value, Path):
            for n in value.nodes:
                self.add(n)
            for r in value.relationships:
                self.add(r)
        elif isinstance(value, list):
            for v in value:
                self.add(v)

    def result(self) -> dict[str, list[dict]]:
        # Drop edges whose endpoints were not returned (e.g. label-less stubs).
        edges = [e for e in self.edges.values() if e["source"] in self.nodes and e["target"] in self.nodes]
        return {"nodes": list(self.nodes.values()), "edges": edges}


def path_in_words(path: Path) -> str:
    """'A1 -[USES_DEVICE]- Device D1 -[USES_DEVICE]- A2'"""
    parts = [node_caption(path.nodes[0])]
    for rel, node in zip(path.relationships, path.nodes[1:]):
        parts += [f"-[{rel.type}]-", f"{node_label(node)} {node_caption(node)}"]
    return " ".join(parts)
