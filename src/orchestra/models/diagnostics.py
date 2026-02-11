from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Severity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class Diagnostic(BaseModel):
    rule: str
    severity: Severity
    message: str
    node_id: str | None = None
    edge: tuple[str, str] | None = None
    suggestion: str = ""


class DiagnosticCollection(BaseModel):
    diagnostics: list[Diagnostic] = Field(default_factory=list)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == Severity.WARNING]

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def add(self, diagnostic: Diagnostic) -> None:
        self.diagnostics.append(diagnostic)
