# Orchestra — Implementation Stages

Orchestra is implemented in seven stages. Each stage produces a vertically-sliced, end-to-end testable artifact — a working application that a human can run, inspect, and verify before proceeding to the next stage.

## Principles

- **Vertical slices.** Each stage delivers a complete capability from user input to user-visible output. No stage is purely a "backend component" without a way to exercise it.
- **Simulation-first.** The pipeline engine works in simulation mode (no LLM) from Stage 1. Real LLM integration comes in Stage 3. This means the orchestration layer is testable without API keys.
- **CXDB from Stage 1.** All persistent state is stored in [CXDB](https://github.com/strongdm/cxdb) from the first stage. There is no local run directory, SQLite database, or JSON checkpoint files. CXDB is an external dependency (Docker container).
- **Automated tests with mocked externals.** Every stage includes end-to-end tests that mock LLM APIs but run against a real CXDB instance. Tests run fast and deterministically.
- **Manual testing.** Every stage includes directions for a human to manually exercise the artifact and verify correct behavior.
- **Incremental complexity.** Each stage builds on the previous. The execution engine gets richer (branching → retry → persistence → LLM → human gates → parallelism → git) while the earlier capabilities remain stable.

## Stage Sequence

| Stage | Delivers | Human Can... |
|-------|----------|-------------|
| [1. Core Pipeline Engine](./01-core-pipeline-engine/plan.md) | DOT parsing, validation, linear execution in simulation mode, CXDB storage, CLI | Write a `.dot` file, compile it, run it, inspect the execution trace in CXDB UI |
| [2a. Control Flow](./02a-control-flow/plan.md) | Conditional routing, 5-step edge selection, condition expressions, retries with backoff, goal gates, failure routing | Build branching pipelines, observe retry behavior, see goal gate enforcement |
| [2b. Persistence and Sessions](./02b-persistence-and-sessions/plan.md) | Checkpoint resume, session management via CXDB contexts, replay via CXDB fork, session CLI commands | Pause and resume runs, list sessions, replay from any checkpoint |
| [3. LLM Integration and Agents](./03-llm-integration-and-agents/plan.md) | CodergenBackend implementations, provider/model resolution, prompt composition, tool registry | Run AI-powered pipelines with real LLM calls and rich agent configuration |
| [4. Human-in-the-Loop](./04-human-in-the-loop/plan.md) | Interviewer pattern, wait.human handler, interactive mode | Participate in pipeline decisions and collaborate with agents interactively |
| [5. Parallel Execution](./05-parallel-execution/plan.md) | Parallel fan-out/fan-in, join policies, context isolation | Run multiple agents concurrently with result consolidation |
| [6. Git and Workspace](./06-git-and-workspace/plan.md) | Multi-repo workspace, session branches, worktrees, workspace snapshots | Run pipelines that manage git repos for software development |
| [7. Validation Pipeline](./07-validation-pipeline/plan.md) | Adversarial PR review pipeline, manager loop, remaining CLI, capstone integration | Run a full multi-agent PR review workflow end-to-end |

## Dependencies

```
Stage 1 ──→ Stage 2a ──→ Stage 2b ──→ Stage 3 ──→ Stage 4
                                         │                │
                                         └──→ Stage 5 ──→ Stage 6 ──→ Stage 7
```

- Stage 2a depends on Stage 1 (execution engine exists)
- Stage 2b depends on Stage 2a (resume needs control flow; sessions need the full execution model)
- Stage 3 depends on Stage 2b (LLM pipelines need full control flow and persistence)
- Stage 4 depends on Stage 3 (human interaction needs working LLM nodes for context)
- Stage 5 depends on Stage 3 (parallel branches need working codergen nodes)
- Stage 6 depends on Stage 5 (worktree-per-agent depends on parallel execution)
- Stage 7 depends on all prior stages

## Technology

- **Language:** Python 3.11+
- **Package manager:** uv
- **Pipeline definition:** Graphviz DOT syntax (attractor spec)
- **Configuration:** YAML (orchestra.yaml)
- **LLM execution:** LangGraph/LangChain (behind CodergenBackend interface)
- **CLI:** Typer
- **Storage:** [CXDB](https://github.com/strongdm/cxdb) (sessions, checkpoints, events, artifacts — replaces SQLite and JSON files)
- **Testing:** pytest
