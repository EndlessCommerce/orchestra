# Orchestra — Implementation Plan

## Overview

Orchestra is a declarative multi-agent pipeline orchestration framework built on LangGraph. This plan follows the two-phase approach recommended in the evaluation: Phase 1 builds the core framework with single-repo support, Phase 2 adds parallel execution, interactive mode, and the validation pipeline.

## Investigation

- [ ] Determine the current latest stable LangGraph version and pin dependencies
    - [ ] Check LangGraph releases and identify the latest stable version
    - [ ] Check LangChain provider packages compatibility (langchain-anthropic, langchain-openai)
    - [ ] Document version pins in the plan
    - [ ] Mark TODO complete and commit the changes to git

## Phase 1: Core Framework

### 1. Project Scaffolding

- [ ] Initialize Python project with `uv` and set up directory structure
    - [ ] Create `pyproject.toml` targeting Python 3.11+ with uv
    - [ ] Pin core dependencies: langgraph, langchain-core, langchain-anthropic, langchain-openai, pydantic v2, typer, pyyaml, jinja2
    - [ ] Pin dev dependencies: pytest, pytest-asyncio, ruff (linting)
    - [ ] Create package directory structure:
        ```
        orchestra/
        ├── __init__.py
        ├── prompts/
        │   ├── __init__.py
        │   ├── composer.py
        │   └── discovery.py
        ├── tools/
        │   ├── __init__.py
        │   ├── registry.py
        │   └── builtins/
        │       └── __init__.py
        ├── agents/
        │   ├── __init__.py
        │   ├── harness.py
        │   └── providers.py
        ├── graph/
        │   ├── __init__.py
        │   ├── schema.py
        │   ├── compiler.py
        │   ├── state.py
        │   └── conditions.py
        ├── runtime/
        │   ├── __init__.py
        │   ├── session.py
        │   ├── git.py
        │   ├── worktree.py
        │   ├── snapshots.py
        │   └── observability.py
        ├── errors.py
        └── cli/
            ├── __init__.py
            └── main.py
        tests/
        ├── conftest.py
        ├── fixtures/
        │   └── pr-review.yaml
        ├── test_prompts.py
        ├── test_discovery.py
        ├── test_tools.py
        ├── test_providers.py
        ├── test_schema.py
        ├── test_compiler.py
        ├── test_conditions.py
        ├── test_state.py
        ├── test_session.py
        ├── test_git.py
        ├── test_observability.py
        ├── test_errors.py
        ├── test_cli.py
        ├── test_prompt_snapshots.py
        └── integration/
            ├── test_pipeline_fakellm.py
            ├── test_replay.py
            └── test_pr_review.py
        ```
    - [ ] Create initial `__init__.py` files with version and public API
    - [ ] Verify `uv sync` and `pytest` run successfully with empty test suite
    - [ ] Mark TODO complete and commit the changes to git

### 2. File Discovery System

- [ ] Implement 3-level file resolution: pipeline-relative → project config → global `~/.orchestra/`
    - [ ] Create `orchestra/prompts/discovery.py` with `FileDiscovery` class
    - [ ] Implement resolution order: relative to pipeline YAML dir → project `orchestra.yaml` paths → `~/.orchestra/`
    - [ ] Support configurable search paths via project-level `orchestra.yaml`
    - [ ] Write `tests/test_discovery.py` — verify 3-level resolution order with correct precedence
    - [ ] Mark TODO complete and commit the changes to git

### 3. Prompt Composition Engine

- [ ] Implement layered prompt assembly from YAML files (role + persona + personality + task)
    - [ ] Create `orchestra/prompts/composer.py` with `PromptComposer` class
    - [ ] Load YAML prompt layers: `role`, `persona`, `personality`, `task`
    - [ ] Each layer is additive text — concatenated in order to form the system prompt
    - [ ] Task layer uses Jinja2 for variable interpolation (e.g., `{{pr_diff}}`)
    - [ ] Integrate with `FileDiscovery` for loading prompt YAML files by name
    - [ ] Write `tests/test_prompts.py` — layered assembly produces expected concatenated output
    - [ ] Write `tests/test_prompt_snapshots.py` — snapshot tests for composed prompts
    - [ ] Mark TODO complete and commit the changes to git

### 4. Tool Registry

- [ ] Implement decorator-based tool registration and YAML shell command tools with repo scoping
    - [ ] Create `orchestra/tools/registry.py` with `ToolRegistry` class
    - [ ] Implement `@tool_registry.register()` decorator for Python tool functions
    - [ ] Implement `@tool_registry.register_builtin()` for built-in tools (read-file, search-code, etc.)
    - [ ] Implement YAML shell command tool loading (from `workspace.tools` config)
    - [ ] Implement repo-qualified tool naming: `{repo}:{tool}` (e.g., `backend:run-tests`)
    - [ ] Auto-generate repo-scoped built-in tools for each workspace repo
    - [ ] Implement `RepoContext` for passing repo path, git state to tools
    - [ ] Support unscoped cross-repo tools
    - [ ] Write `tests/test_tools.py` — decorator-registered and YAML shell tools discoverable; repo:tool naming works
    - [ ] Mark TODO complete and commit the changes to git

### 5. Provider/Model Resolution

- [ ] Implement provider configuration and model alias resolution
    - [ ] Create `orchestra/agents/providers.py` with `ProviderResolver` class
    - [ ] Implement 3-level resolution chain: agent model alias → agent provider (or pipeline default) → provider model map
    - [ ] Support alias convention: `smart`, `worker`, `cheap`
    - [ ] Support literal model string passthrough (unknown alias = literal model name)
    - [ ] Support per-agent provider override
    - [ ] Support provider-specific config (`max_tokens`, `api_base`)
    - [ ] Instantiate LangChain ChatModel from resolved provider + model
    - [ ] Write `tests/test_providers.py` — all alias, literal, and override cases
    - [ ] Mark TODO complete and commit the changes to git

### 6. State Schema

- [ ] Implement base state schema with Pydantic extension merging
    - [ ] Create `orchestra/graph/state.py` with `OrchestraState` base
    - [ ] Base schema: `messages` (LangGraph MessageState), `agent_outputs: dict[str, Any]`, `metadata`
    - [ ] Support pipeline-defined Pydantic model extensions referenced by import path in YAML
    - [ ] Implement schema merging: base + extension → full state type
    - [ ] Write `tests/test_state.py` — base + extension produce valid merged type
    - [ ] Mark TODO complete and commit the changes to git

### 7. Graph Schema (YAML Validation)

- [ ] Implement Pydantic models validating the full pipeline YAML structure
    - [ ] Create `orchestra/graph/schema.py` with Pydantic models for all YAML sections: `providers`, `workspace`, `agents`, `graph`
    - [ ] Validate provider configs, agent configs, graph edge definitions
    - [ ] Validate graph edge references point to defined agents
    - [ ] Validate `join`, `condition`, `max_loops` on edges
    - [ ] Produce clear, actionable error messages (not raw Pydantic internals)
    - [ ] Write `tests/test_schema.py` — valid YAML passes; invalid YAML produces actionable errors
    - [ ] Mark TODO complete and commit the changes to git

### 8. Agent Harness

- [ ] Implement agent harness wrapping LangGraph nodes with prompt + tools + provider
    - [ ] Create `orchestra/agents/harness.py` with `AgentHarness` class
    - [ ] Compose system prompt via `PromptComposer` from agent's role/persona/personality/task
    - [ ] Resolve tools from `ToolRegistry` based on agent config
    - [ ] Resolve provider/model via `ProviderResolver`
    - [ ] Produce a callable LangGraph node function
    - [ ] Agent writes structured output to `agent_outputs[agent_name]`
    - [ ] Support `mode: autonomous` (runs to completion)
    - [ ] Write tests for agent harness — produces callable node with composed prompt, resolved tools, resolved model
    - [ ] Mark TODO complete and commit the changes to git

### 9. Condition Function Discovery

- [ ] Implement condition function auto-discovery via `@orchestra.condition()` decorator
    - [ ] Create `orchestra/graph/conditions.py` with `ConditionRegistry`
    - [ ] Implement `@orchestra.condition("name")` decorator
    - [ ] Auto-scan configurable directory (default: `conditions/` relative to pipeline YAML)
    - [ ] Function signature: `def condition(state: GraphState) -> str | list[str]`
    - [ ] Write `tests/test_conditions.py` — decorated functions discovered and callable by name
    - [ ] Mark TODO complete and commit the changes to git

### 10. Graph Compiler

- [ ] Implement YAML → LangGraph StateGraph compilation
    - [ ] Create `orchestra/graph/compiler.py` with `GraphCompiler` class
    - [ ] Parse validated schema into LangGraph `StateGraph`
    - [ ] Implement `START` → agents edges
    - [ ] Implement fan-out: `from: X, to: [A, B]` → parallel edges
    - [ ] Implement fan-in: `from: [A, B], to: C, join: all` → wait-for-all join
    - [ ] Implement conditional edges: `condition: name` → resolved condition function
    - [ ] Implement `max_loops` on edges
    - [ ] Implement `END` terminal edges
    - [ ] Wire agent harnesses as nodes
    - [ ] Configure LangGraph `SqliteSaver` for checkpointing
    - [ ] Warn when parallel agents have write access to the same repo
    - [ ] Write `tests/test_compiler.py` — fan-out, fan-in, conditional edges, max_loops all compile correctly
    - [ ] Write `tests/test_compiler.py -k parallel_write_warning` — warning emitted for shared write access
    - [ ] Mark TODO complete and commit the changes to git

### 11. Basic Session Management

- [ ] Implement session lifecycle with SQLite persistence
    - [ ] Create `orchestra/runtime/session.py` with `SessionManager`
    - [ ] Session creation with unique ID
    - [ ] Session status tracking: `created`, `running`, `paused`, `completed`, `failed`
    - [ ] Persist session state (ID, status, timestamps, pipeline name) in SQLite
    - [ ] Query sessions by ID, status
    - [ ] Write `tests/test_session.py` — session creation, persistence, query
    - [ ] Mark TODO complete and commit the changes to git

### 12. Basic Git Integration

- [ ] Implement session branches and auto-commit tracking (single-repo first)
    - [ ] Create `orchestra/runtime/git.py` with `GitManager`
    - [ ] Create session branch at session start: `{prefix}{pipeline}/{session-id}`
    - [ ] Auto-commit agent changes to session branch
    - [ ] Record workspace snapshots: `{checkpoint_id → {repo: sha}}`
    - [ ] Only record snapshots when repo state has actually changed
    - [ ] Write `tests/test_git.py` — branch creation, auto-commit, snapshot recording
    - [ ] Mark TODO complete and commit the changes to git

### 13. Observability Layer

- [ ] Implement structured SQLite logging for token usage, tool invocations, timing
    - [ ] Create `orchestra/runtime/observability.py` with `ObservabilityLogger`
    - [ ] Log per-node: token usage (prompt/completion), tool invocations, wall-clock timing
    - [ ] Store in SQLite session database
    - [ ] Optional LangSmith integration auto-detected via `LANGSMITH_API_KEY`
    - [ ] Write `tests/test_observability.py` — structured records queryable after execution
    - [ ] Mark TODO complete and commit the changes to git

### 14. Error Handling

- [ ] Implement layered error handling with circuit breaker
    - [ ] Create `orchestra/errors.py` with error types and circuit breaker
    - [ ] LLM call retries: delegate to LangChain's built-in retry mechanism
    - [ ] Tool execution failures: surface to agent as error messages
    - [ ] Pipeline circuit breaker: configurable `max_failures_per_session`
    - [ ] Write `tests/test_errors.py` — circuit breaker halts; tool errors surfaced
    - [ ] Mark TODO complete and commit the changes to git

### 15. CLI Interface (Phase 1 Commands)

- [ ] Implement Typer-based CLI with `compile`, `run`, and `status` commands
    - [ ] Create `orchestra/cli/main.py` with Typer app
    - [ ] `orchestra compile <pipeline.yaml>` — validate YAML, resolve all references, print compiled graph structure
    - [ ] `orchestra run <pipeline.yaml>` — compile and execute graph with checkpointing
    - [ ] `orchestra status` — show running/completed sessions with checkpoint counts and token usage
    - [ ] Register CLI entry point in `pyproject.toml`
    - [ ] Write `tests/test_cli.py` — each command accepts correct arguments and produces expected output
    - [ ] Mark TODO complete and commit the changes to git

### 16. FakeLLM Test Infrastructure & Phase 1 Integration Test

- [ ] Build FakeLLM infrastructure and end-to-end integration test
    - [ ] Create `tests/conftest.py` with FakeLLM fixtures (using LangChain's `FakeListChatModel`)
    - [ ] Create `tests/fixtures/pr-review.yaml` — test pipeline YAML
    - [ ] Create test prompt files for the fixture pipeline
    - [ ] Write `tests/integration/test_pipeline_fakellm.py`:
        - [ ] Pipeline YAML loads, compiles, and executes end-to-end
        - [ ] Checkpoints created after each node
        - [ ] Git commits linked to checkpoints via workspace snapshots
        - [ ] Agent outputs propagated between nodes
    - [ ] Mark TODO complete and commit the changes to git

---

## Phase 2: Parallel Execution, Interactive Mode & Validation

### 17. Worktree Manager

- [ ] Implement worktree-per-agent isolation for parallel writes
    - [ ] Create `orchestra/runtime/worktree.py` with `WorktreeManager`
    - [ ] Create worktrees in `.orchestra/worktrees/{session}/{agent}` for parallel agents with write access
    - [ ] Merge worktrees back into session branch at fan-in (3-way merge)
    - [ ] Surface merge conflicts to downstream agent or human
    - [ ] Clean up worktrees after successful merge
    - [ ] Preserve worktrees on failure for inspection
    - [ ] Write `tests/test_worktree.py` — create, merge, cleanup lifecycle
    - [ ] Mark TODO complete and commit the changes to git

### 18. Workspace Snapshots

- [ ] Implement workspace snapshot index linking checkpoints to git SHAs across repos
    - [ ] Create `orchestra/runtime/snapshots.py` with `WorkspaceSnapshotIndex`
    - [ ] Implement SQLite schema: `workspace_snapshots` + `repo_states` tables
    - [ ] Dual-write: store summary in LangGraph checkpoint metadata + Orchestra SQLite
    - [ ] Record per-repo SHA, branch, worktree path, agent name
    - [ ] Only record when repo state changes since last checkpoint
    - [ ] Support multi-repo workspaces
    - [ ] Write integration tests for snapshot recording and retrieval
    - [ ] Mark TODO complete and commit the changes to git

### 19. Interactive Mode

- [ ] Implement chat-style interactive mode for `mode: interactive` agents
    - [ ] Extend `AgentHarness` for `mode: interactive`
    - [ ] Implement multi-turn chat loop via stdin/stdout
    - [ ] Support human commands: `/done`, `/approve`, `/reject`
    - [ ] Each human turn creates a checkpoint boundary
    - [ ] Abstract interface to support future web UI
    - [ ] Write tests for interactive mode (mock stdin/stdout)
    - [ ] Mark TODO complete and commit the changes to git

### 20. CLI Phase 2 Commands

- [ ] Implement `attach`, `replay`, and `cleanup` CLI commands
    - [ ] `orchestra attach <session_id>` — connect to running session's interactive agent (stream output, send input)
    - [ ] `orchestra replay <session_id> --checkpoint <id>` — restore LangGraph state AND git working trees
    - [ ] `orchestra cleanup` — remove stale session branches and worktrees (configurable age threshold)
    - [ ] Write `tests/test_cli.py` extensions for new commands
    - [ ] Write `tests/integration/test_replay.py` — after replay, LangGraph state matches checkpoint and repos at correct SHAs
    - [ ] Mark TODO complete and commit the changes to git

### 21. PR Review Validation Pipeline

- [ ] Build the adversarial PR review pipeline as end-to-end validation
    - [ ] Create pipeline YAML: `pipelines/pr-review.yaml`
    - [ ] Create prompt files for all agents: security-reviewer, architecture-reviewer, critic, synthesizer
    - [ ] Create condition function: `conditions/critic_routing.py`
    - [ ] Implement `local:get-git-diff` built-in tool (primary input, works offline)
    - [ ] Optionally implement `github:get-pr-diff` tool (swappable, requires credentials)
    - [ ] Write `tests/integration/test_pr_review.py` (gated behind `ORCHESTRA_REAL_LLM=1`):
        - [ ] 2+ reviewer agents fan-out
        - [ ] Critic loops 0-2 times
        - [ ] Synthesizer produces coherent final review
        - [ ] All checkpoints and git state correct
    - [ ] Mark TODO complete and commit the changes to git

---

## Review & Cleanup

- [ ] Identify any code that is unused, or could be cleaned up
    - [ ] Look at all previous TODOs and changes in git to identify changes
    - [ ] Identify any code that is no longer used, and remove it
    - [ ] Identify any unnecessary comments, and remove them (comments that explain "what" for a single line of code)
    - [ ] If there are any obvious code smells of redundant code, add TODOs below to address them (e.g., multiple classes with similar private methods that could be extracted)
    - [ ] Mark TODO complete and commit the changes to git

- [ ] Identify all specs that need to be run and updated
    - [ ] Look at all previous TODOs and changes in git to identify changes
    - [ ] Identify any specs that cover these changes that need to be run, and run these specs
    - [ ] Add any specs that failed to a new TODO to fix these
    - [ ] Identify any missing specs that need to be added or updated
    - [ ] Add these specs to a new TODO
    - [ ] Mark TODO complete and commit the changes to git
