# Appendix A: Data Models

```python
from pydantic import BaseModel, Field
from enum import Enum

class GoalSpec(BaseModel):
    title: str
    description: str
    acceptance_criteria: list[str]
    constraints: list[str]
    scope: str = Field(description="in_scope / out_of_scope boundary")

class EvalRound(BaseModel):
    round: int
    proposal: str
    critique: str
    verdict: str
    refined_goal: GoalSpec | None = None

class Task(BaseModel):
    id: str
    title: str
    description: str
    dependencies: list[str] = []
    inputs: list[str] = []
    outputs: list[str] = []
    verification: str = Field(description="How to verify this task is done")

class PlanStep(BaseModel):
    task_id: str
    title: str
    tools_needed: list[str]
    estimated_complexity: str  # "low" | "medium" | "high"
    rollback_strategy: str

class ExecutionPlan(BaseModel):
    steps: list[PlanStep]
    estimated_duration: str
    risk_assessment: str

class StepResult(BaseModel):
    step_index: int
    title: str
    status: str                # "complete" | "failed" | "skipped"
    output: str
    files_changed: list[str]
    duration_seconds: float

class CheckResult(BaseModel):
    name: str
    passed: bool
    output: str
    errors: str

class VerificationResult(BaseModel):
    checks: dict[str, CheckResult]
    llm_review: str | None = None
    passed: bool

class CommitRecord(BaseModel):
    sha: str
    message: str
    files: list[str]
    timestamp: str
```
