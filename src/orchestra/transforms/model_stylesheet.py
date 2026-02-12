from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from orchestra.models.graph import PipelineGraph

STYLESHEET_PROPERTIES = {"llm_model", "llm_provider", "reasoning_effort"}


@dataclass
class StyleRule:
    selector_type: str  # "universal", "class", "id"
    selector_value: str  # e.g., "code", "review" (empty for universal)
    properties: dict[str, str] = field(default_factory=dict)

    @property
    def specificity(self) -> int:
        if self.selector_type == "id":
            return 3
        if self.selector_type == "class":
            return 2
        return 1


def parse_stylesheet(stylesheet_text: str) -> list[StyleRule]:
    rules: list[StyleRule] = []
    pattern = re.compile(
        r"([*#.][\w-]*)\s*\{([^}]*)\}",
        re.DOTALL,
    )
    for match in pattern.finditer(stylesheet_text):
        selector_str = match.group(1).strip()
        body = match.group(2).strip()

        if selector_str == "*":
            selector_type = "universal"
            selector_value = ""
        elif selector_str.startswith("#"):
            selector_type = "id"
            selector_value = selector_str[1:]
        elif selector_str.startswith("."):
            selector_type = "class"
            selector_value = selector_str[1:]
        else:
            continue

        properties: dict[str, str] = {}
        for prop_match in re.finditer(r"([\w_-]+)\s*:\s*([^;]+);?", body):
            prop_name = prop_match.group(1).strip()
            prop_value = prop_match.group(2).strip().rstrip(";")
            if prop_name in STYLESHEET_PROPERTIES:
                properties[prop_name] = prop_value

        rules.append(StyleRule(
            selector_type=selector_type,
            selector_value=selector_value,
            properties=properties,
        ))

    return rules


def _node_matches(rule: StyleRule, node_id: str, node_classes: set[str]) -> bool:
    if rule.selector_type == "universal":
        return True
    if rule.selector_type == "id":
        return rule.selector_value == node_id
    if rule.selector_type == "class":
        return rule.selector_value in node_classes
    return False


def apply_model_stylesheet(graph: PipelineGraph) -> PipelineGraph:
    stylesheet_text = graph.graph_attributes.get("model_stylesheet", "")
    if not stylesheet_text:
        return graph

    rules = parse_stylesheet(stylesheet_text)
    rules.sort(key=lambda r: r.specificity, reverse=True)

    for node in graph.nodes.values():
        class_attr = node.attributes.get("class", "")
        node_classes = {c.strip() for c in str(class_attr).split(",") if c.strip()}

        matching_rules = [r for r in rules if _node_matches(r, node.id, node_classes)]

        for rule in matching_rules:
            for prop_name, prop_value in rule.properties.items():
                if prop_name not in node.attributes:
                    node.attributes[prop_name] = prop_value

    return graph
