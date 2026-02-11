from __future__ import annotations

from orchestra.models.diagnostics import DiagnosticCollection
from orchestra.models.graph import PipelineGraph
from orchestra.validation.rules import ALL_RULES


class ValidationError(Exception):
    def __init__(self, diagnostics: DiagnosticCollection) -> None:
        self.diagnostics = diagnostics
        errors = diagnostics.errors
        messages = [f"  [{d.rule}] {d.message}" for d in errors]
        super().__init__(f"Validation failed with {len(errors)} error(s):\n" + "\n".join(messages))


def validate(graph: PipelineGraph) -> DiagnosticCollection:
    collection = DiagnosticCollection()
    for rule in ALL_RULES:
        for diagnostic in rule(graph):
            collection.add(diagnostic)
    return collection


def validate_or_raise(graph: PipelineGraph) -> DiagnosticCollection:
    collection = validate(graph)
    if collection.has_errors:
        raise ValidationError(collection)
    return collection
