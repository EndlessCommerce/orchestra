# Orchestra: Declarative Agent Orchestration on LangGraph

## Summary

Orchestra is a framework that provides declarative configuration, prompt management, tool registration, and runtime management on top of LangGraph. It targets software development workflows — enabling users to define multi-agent pipelines (e.g., PR review, goal-driven development) as data, compile them to LangGraph execution graphs, and interact with running pipelines through CLI and web interfaces with full observability and git-tracked agent output.

## Problem Context

### The Core Problem: Agent Pipeline Configuration Gap

LangGraph provides excellent low-level primitives — `StateGraph`, `add_node`, `add_edge`, conditional routing, checkpointing, human-in-the-loop — but requires imperative Python code to define every graph. For teams that want to:

1. **Compose agents from reusable building blocks** (prompts, tools, personas)
2. **Define workflows declaratively** without writing graph construction code
3. **Manage execution with full observability** and the ability to resume, replay, and attach to running sessions
4. **Track agent outputs in git** alongside the code being worked on

...there is no integrated solution. Existing frameworks either operate at a different level of abstraction (CrewAI's role metaphor, AutoGen's conversation model) or require buying into a managed platform (LangGraph Platform, which is enterprise-licensed).

### Related Well-Known Problems

1. **Workflow-as-Code vs Workflow-as-Data**: The Airflow/Prefect/Temporal pattern — defining DAGs declaratively vs imperatively. Orchestra applies this to agent pipelines.
2. **Configuration-Driven Architecture**: The Kubernetes/Terraform pattern — separating "what" from "how" via declarative specs that are compiled into runtime behavior.
3. **Tool/Plugin Registry**: The VS Code extension / Terraform provider pattern — a registry of capabilities that can be composed into configurations.
4. **Prompt Engineering Management**: Managing prompt variants, composition, and versioning as a first-class concern.
5. **Execution Observability & Time Travel**: The debugger/replay pattern applied to non-deterministic LLM execution, linking execution state to code state.

## System Architecture

### Layer Model

```
┌─────────────────────────────────────────────────────┐
│  Layer 5: Interfaces (CLI, Web UI, API)             │
├─────────────────────────────────────────────────────┤
│  Layer 4: Runtime Management                        │
│  (session mgmt, observability, git integration)     │
├─────────────────────────────────────────────────────┤
│  Layer 3: Graph Compiler                            │
│  (declarative config → LangGraph StateGraph)        │
├─────────────────────────────────────────────────────┤
│  Layer 2: Agent Building Blocks                     │
│  (prompt composer, tool registry, agent harness)    │
├─────────────────────────────────────────────────────┤
│  Layer 1: LangGraph Runtime                         │
│  (StateGraph, checkpointing, execution)             │
└─────────────────────────────────────────────────────┘
```

## Potential Solutions

### Solution 1: Monolithic Python Package

A single Python package (`orchestra`) with submodules for each layer:

```
orchestra/
├── prompts/          # Prompt composition engine
│   ├── composer.py   # Builds system prompts from role + persona + task + personality
│   ├── templates/    # Built-in prompt templates
│   └── registry.py   # Prompt template registry
├── tools/            # Tool registry
│   ├── registry.py   # Tool registration and discovery
│   ├── builtins/     # Built-in tools (git, shell, etc.)
│   └── loaders.py    # Load user-defined tools from config
├── agents/           # Agent harness
│   ├── harness.py    # Agent configuration (model, tools, prompts, mode)
│   └── providers.py  # LLM provider configuration
├── graph/            # Graph compiler
│   ├── schema.py     # Declarative graph schema (Pydantic models)
│   ├── compiler.py   # Schema → LangGraph StateGraph
│   └── validators.py # Schema validation
├── runtime/          # Execution management
│   ├── session.py    # Session lifecycle (start, pause, resume, attach)
│   ├── git.py        # Git integration (commit tracking, worktrees)
│   ├── checkpoint.py # Checkpoint ↔ git commit linking
│   └── store.py      # Execution state database
├── cli/              # CLI interface
│   └── main.py       # Click/Typer CLI
└── server/           # Web/API interface (deferred)
    ├── api.py        # FastAPI endpoints
    └── ui/           # Web dashboard
```

**Declarative Graph Schema (YAML example):**

```yaml
# pipeline: pr-review.yaml
name: adversarial-pr-review
description: Multi-perspective PR review with adversarial critique

providers:
  # Default provider for all agents (can be overridden per-agent)
  default: anthropic

  anthropic:
    models:
      smart: claude-opus-4-20250514
      worker: claude-sonnet-4-20250514
      cheap: claude-haiku-3-20250514
    # Provider-specific config
    max_tokens: 8192

  openai:
    models:
      smart: gpt-4o
      worker: gpt-4o-mini
      cheap: gpt-4o-mini

  openrouter:
    models:
      smart: anthropic/claude-opus-4
      worker: anthropic/claude-sonnet-4
      cheap: meta-llama/llama-3.1-70b
    api_base: https://openrouter.ai/api/v1

workspace:
  repos:
    backend:
      path: ../backend         # relative to workspace root, or absolute
      branch_prefix: orchestra/ # session branches created under this prefix
    frontend:
      path: ../frontend
      branch_prefix: orchestra/
    # Single-repo projects just have one entry:
    # app:
    #   path: .

  # Project-level tool defaults (per-repo)
  tools:
    backend:
      run-tests:
        command: "docker compose exec app bundle exec rspec"
      run-lint:
        command: "docker compose exec app bundle exec rubocop"
    frontend:
      run-tests:
        command: "npm test"
      run-lint:
        command: "npm run lint"

agents:
  security-reviewer:
    model: smart                 # resolves via default provider (anthropic) → claude-opus-4
    role: security-engineer
    persona: senior-security-engineer
    personality: thorough-skeptical
    task: review-pr-security
    tools:
      - backend:read-file        # repo-qualified tool names
      - backend:search-code
      - backend:run-tests
      - frontend:read-file
      - frontend:search-code
    mode: autonomous

  architecture-reviewer:
    model: smart                 # same alias, same resolved model
    role: software-architect
    persona: principal-engineer
    personality: pragmatic-opinionated
    task: review-pr-architecture
    tools:
      - backend:read-file
      - backend:search-code
      - frontend:read-file
      - frontend:search-code
    mode: autonomous

  critic:
    model: worker                # cheaper model for iterative critique
    provider: openrouter         # override: use openrouter instead of default anthropic
    role: adversarial-critic
    persona: devils-advocate
    personality: contrarian-precise
    task: critique-reviews
    tools: []
    mode: autonomous

  synthesizer:
    model: smart                 # back to default provider (anthropic)
    role: review-synthesizer
    persona: tech-lead
    personality: balanced-decisive
    task: synthesize-review
    tools: []
    mode: interactive            # chat-style human interaction (multi-turn)

  # You can also pin to a specific model string, bypassing aliases:
  # fast-triage:
  #   model: claude-haiku-3-20250514   # literal model name
  #   provider: anthropic              # required when using literal model name

graph:
  # Parallel fan-out to reviewers
  - from: START
    to: [security-reviewer, architecture-reviewer]

  # Both reviews feed into critic
  - from: [security-reviewer, architecture-reviewer]
    to: critic
    join: all  # wait for all

  # Critic can send back to reviewers or forward to synthesis
  - from: critic
    to: [security-reviewer, architecture-reviewer, synthesizer]
    condition: critic-routing  # references a registered condition function
    max_loops: 2

  # Final synthesis
  - from: synthesizer
    to: END
```

**Prompt Composition Model:**

```yaml
# prompts/roles/security-engineer.yaml
role:
  name: security-engineer
  system: |
    You are a security engineer performing code review.
    Your primary concern is identifying security vulnerabilities,
    authentication/authorization issues, injection attacks,
    and data exposure risks.

# prompts/personas/senior-security-engineer.yaml
persona:
  name: senior-security-engineer
  extends: security-engineer
  modifiers: |
    You have 15 years of experience. You've seen every class of
    vulnerability. You don't raise false alarms — when you flag
    something, it matters. You provide specific remediation steps.

# prompts/personalities/thorough-skeptical.yaml
personality:
  name: thorough-skeptical
  modifiers: |
    You are methodical and exhaustive. You assume code is guilty
    until proven innocent. You check edge cases others miss.
    You never say "looks good" without evidence.

# prompts/tasks/review-pr-security.yaml
task:
  name: review-pr-security
  template: |
    Review the following pull request for security concerns.
    
    {{pr_diff}}
    
    Provide your review as structured findings with:
    - Severity (critical/high/medium/low/info)
    - Location (file:line)
    - Description
    - Remediation
```

The composed system prompt would be assembled from `role + persona + personality + task`, each layer additive.

**Tool Registry Model (Multi-Repo Aware):**

Tools are scoped to repos via a `{repo}:{tool}` naming convention. Built-in tools (read-file, search-code, git operations) are automatically generated per-repo in the workspace. Project-specific tools are defined per-repo in the workspace config.

```python
# Built-in tools are repo-aware — the registry auto-generates
# scoped versions for each repo in the workspace:
#   backend:read-file, frontend:read-file
#   backend:write-file, frontend:write-file
#   backend:git-commit, frontend:git-commit
#   backend:search-code, frontend:search-code

# The underlying implementation receives the repo context:
from orchestra.tools import tool_registry, RepoContext

@tool_registry.register_builtin("read-file")
def read_file(path: str, repo: RepoContext) -> str:
    """Read a file from the repo's working directory."""
    full_path = repo.resolve_path(path)
    return full_path.read_text()

# User-defined tools can also be repo-scoped:
@tool_registry.register("run-migration", repo="backend")
def run_migration() -> str:
    """Run database migrations."""
    ...

# Shell command tools from YAML config are auto-scoped to their repo:
# workspace.tools.backend.run-tests → becomes "backend:run-tests"

# Cross-repo tools (not scoped to any single repo) are also possible:
@tool_registry.register("run-integration-tests")
def run_integration_tests() -> str:
    """Run integration tests spanning frontend and backend."""
    ...
```

When an agent is configured with `backend:run-tests`, the tool receives the backend repo's `RepoContext` automatically — including its path, git state, and environment.

**Git Integration Model (Multi-Repo, Worktree-per-Agent):**

Each graph execution session operates across a workspace of one or more git repos. Parallel agents with write access to the same repo get isolated git worktrees; sequential agents share the session branch directly.

**Session lifecycle:**

1. Session starts → create session branch `{prefix}{pipeline}/{session-id}` in EACH repo; record base commit SHAs
2. Graph compiler identifies parallel fan-out segments where multiple agents have write access to the same repo → creates a worktree per agent for those repos
3. Agent makes code changes → auto-commit to its worktree (parallel) or the session branch (sequential)
4. At fan-in (join point) → merge agent worktrees back into the session branch; surface conflicts to the downstream agent or human
5. Each LangGraph checkpoint stores a **workspace snapshot**: `{checkpoint_id, repos: {name: sha, ...}, timestamp}`
6. Resuming from a checkpoint → `git checkout` each repo to its corresponding SHA + restore LangGraph state
7. Session state stored in a local SQLite database (or Postgres for shared/remote)

```
Execution Timeline (2-repo workspace, parallel agents with worktrees):
  
  checkpoint_0 ──── checkpoint_1a/1b ──── checkpoint_2 (fan-in) ──── checkpoint_3
       │                  │                       │                        │
   workspace:         agent worktrees:         merged workspace:        workspace:
   backend: abc123    security: wt_sec/def     backend: merged_sha     backend: jkl012
   frontend: 111aaa   arch: wt_arch/ghi        frontend: 111aaa        frontend: 333ccc
   (both at base)    (parallel, isolated)     (worktrees merged)      (sequential)
```

The workspace snapshot model means:
- **Resuming** from checkpoint_2 restores the merged state of all repos after the fan-in
- **Not every checkpoint touches every repo** — only repos with changes get new SHAs
- **Parallel agents** in separate worktrees commit independently; the fan-in merge produces a single SHA per repo
- **Sequential agents** (after fan-in) work directly on the session branch — no worktree overhead

**Worktree management:**
- Worktrees are created in a `.orchestra/worktrees/` directory relative to the repo
- Named `{session-id}/{agent-name}` for debuggability
- Cleaned up after fan-in merge completes successfully
- On session failure/abort, worktrees are preserved for inspection and cleaned up by `orchestra cleanup`

**Workspace Snapshot Schema (SQLite):**

```sql
CREATE TABLE workspace_snapshots (
    checkpoint_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE repo_states (
    checkpoint_id TEXT NOT NULL,
    repo_name TEXT NOT NULL,
    git_sha TEXT NOT NULL,
    branch TEXT NOT NULL,
    worktree_path TEXT,          -- NULL for session branch, path for agent worktree
    agent_name TEXT,             -- NULL for merged state, agent name for per-agent state
    PRIMARY KEY (checkpoint_id, repo_name, COALESCE(agent_name, '')),
    FOREIGN KEY (checkpoint_id) REFERENCES workspace_snapshots(checkpoint_id)
);
```

### Solution 2: Layered Packages (Monorepo)

Same architecture as Solution 1, but split into installable packages:

```
orchestra-core      # prompts, tools, agents, graph compiler
orchestra-runtime   # session management, git integration, checkpointing
orchestra-cli       # CLI interface
orchestra-server    # web API + UI (deferred)
```

**Pros:** Cleaner dependency boundaries, users can install only what they need.
**Cons:** More packaging overhead, premature for initial development.

### Solution 3: Configuration-Only Layer (Thin Wrapper)

Minimal Python — mostly YAML/JSON configuration that gets interpreted into LangGraph at runtime. The framework is primarily a schema + compiler + CLI, with most logic living in LangGraph itself.

**Pros:** Less code to maintain, closer to LangGraph's native patterns.
**Cons:** Less flexibility for custom runtime management (git integration, session attachment, observability).

## Tradeoff Analysis

### Declarative Format: YAML vs Python DSL vs JSON

| Factor | YAML | Python DSL | JSON |
|--------|------|-----------|------|
| Readability | High | Medium-High | Low |
| Validation | Via schema | Native types | Via schema |
| Expressiveness | Low (no logic) | High | Lowest |
| LLM-friendliness | High | Medium | High |
| Editor support | Basic | Full IDE | Basic |
| Conditional logic | Requires references to code | Inline | Requires references |

**Recommendation:** YAML as the primary format, with Python DSL as an escape hatch for complex conditional logic. Conditions/routing functions can be registered in Python and referenced by name in YAML.

### Prompt Composition: Layered Assembly vs Template Engine vs Prompt Objects

| Factor | Layered Assembly | Template Engine (Jinja2) | Prompt Objects |
|--------|-----------------|-------------------------|----------------|
| Composability | High (role + persona + ...) | Medium (includes/blocks) | High (OOP) |
| Non-technical editing | Easy (edit one YAML file) | Moderate | Hard |
| Runtime flexibility | Moderate | High (logic in templates) | High |
| Testability | High (each layer testable) | Medium | High |

**Recommendation:** Layered assembly with Jinja2 for the task template layer. Roles, personas, and personalities are additive text blocks. Tasks use Jinja2 for variable interpolation (`{{pr_diff}}`).

### Git Integration: Branch-per-session vs Worktree-per-session vs Commit-only

| Factor | Branch-per-session | Worktree-per-session | Commit-only |
|--------|-------------------|---------------------|-------------|
| Parallel execution | No (single working dir) | Yes | No |
| Isolation | Low | High | N/A |
| Complexity | Low | Medium | Lowest |
| Resume/replay fidelity | High | High | Medium |
| Disk usage | Low | Medium (full checkout) | Low |

**Recommendation:** Worktree-per-session for parallel pipelines, branch-per-session as default for single pipelines. The runtime should abstract this — users shouldn't need to think about worktrees vs branches.

### State Linking: Checkpoint ID in Git vs Git SHA in Checkpoint vs Dual-Write

| Factor | Checkpoint ID in Git Commit | Git SHA in Checkpoint DB | Dual-Write (both) |
|--------|---------------------------|------------------------|-------------------|
| Simplicity | Medium | Medium | Lower |
| Completeness | Partial (git → agent state) | Partial (agent state → git) | Full bidirectional |
| Resumability | Need DB lookup from commit | Need git lookup from checkpoint | Either direction works |
| Implementation | Custom git commit metadata | Custom checkpoint metadata | Both |

**Recommendation:** Dual-write approach with workspace snapshots. Store a workspace snapshot (map of repo→SHA) in the checkpoint metadata (LangGraph supports custom metadata on checkpoints), and store checkpoint_id in git commit trailers in each affected repo. A local SQLite database serves as the bidirectional index across all repos.

### Execution Store: SQLite vs PostgreSQL vs Filesystem

| Factor | SQLite | PostgreSQL | Filesystem |
|--------|--------|-----------|------------|
| Zero-config | Yes | No | Yes |
| Concurrent access | Limited | Excellent | Poor |
| Remote deployment | No (local file) | Yes | No |
| LangGraph native support | No | Yes (PostgresSaver) | No |
| Query capability | Good | Excellent | None |

**Recommendation:** SQLite for local/CLI usage (zero-config, embedded). PostgreSQL when deploying remotely (future). LangGraph's built-in `SqliteSaver` for checkpoints, with a parallel SQLite database for Orchestra's own session/execution metadata.

### Provider/Model Configuration: Alias Resolution

The provider system uses a 3-level resolution chain:

```
Agent config          Pipeline config           Resolved model
─────────────        ─────────────────         ──────────────
model: "smart"   →   provider (agent-level     →  actual model string
                      or pipeline default)
                  →   providers.{provider}
                      .models.{alias}
```

**Resolution rules:**
1. Agent specifies `model:` (alias like "smart" or literal like "claude-opus-4-20250514")
2. Agent optionally specifies `provider:` to override pipeline default
3. If `model` is an alias (found in `providers.{provider}.models`), resolve to the mapped model string
4. If `model` is a literal string (not found in aliases), use it directly with the specified provider (escape hatch for specific models)

**Recommended alias convention:** `smart`, `worker`, `cheap` — shipped as a convention for pipeline portability. Users can define any additional aliases. Providers don't need to implement all aliases — resolution fails with a clear error if an alias is missing for the resolved provider.

**Key design property:** Changing `providers.default: openai` in ONE place switches all agents (that don't override) from Anthropic to OpenAI, while preserving the smart/worker/cheap tier semantics. This makes A/B testing across providers trivial.

| Factor | Alias System | Direct model strings | Provider-only (no aliases) |
|--------|-------------|---------------------|--------------------------|
| Provider switching | One-line change | Edit every agent | One-line change |
| Semantic clarity | High ("smart" vs "worker") | Low (model string) | None |
| Per-agent override | Supported | N/A (already direct) | Provider only, not tier |
| Cost visibility | Implicit in alias | Explicit in model name | Implicit |
| New provider onboarding | Define alias mappings once | N/A | Just set provider |

### Multi-Repo Workspace: Named Workspaces vs Repo-Param Tools vs Workspace Manifest

| Factor | Named Workspaces (A) | Repo-Param Tool (B) | Workspace Manifest (C) |
|--------|---------------------|---------------------|----------------------|
| Type safety | High (`backend:run-tests` is explicit) | Low (string param) | Medium |
| Agent clarity | High (agent declares exactly which repos) | Low (any agent can access any repo) | Medium |
| Config ergonomics | Good (YAML is readable) | Simpler per-tool | More indirection |
| Tool generation | Auto-generate per repo | Single tool, dynamic dispatch | Auto-discover from manifest |
| Cross-repo tools | Supported (unscoped tools) | Natural (just pass repo param) | Supported |
| Single-repo simplicity | Degenerate case (one entry) | No change needed | Overkill |

**Recommendation:** Named workspaces (A). Repo-qualified tool names (`backend:run-tests`) make agent configurations explicit about which repos they touch. Single-repo projects are the degenerate case with one workspace entry. Cross-repo tools are unscoped.

### Monolith vs Monorepo Packages

| Factor | Monolith | Monorepo |
|--------|----------|----------|
| Initial velocity | Fast | Slower |
| Dependency management | Simple | Complex |
| User install flexibility | Lower | Higher |
| Refactoring ease | Higher | Lower |

**Recommendation:** Start as monolith, extract packages later if needed. The internal module boundaries (prompts, tools, agents, graph, runtime, cli) serve as future package boundaries.

## Decision Points

### Resolved Decisions

1. **Condition Functions** → **Plugin directory with decorator-based discovery.** Orchestra scans a configurable directory (default: `conditions/` relative to the pipeline YAML) for Python files containing functions decorated with `@orchestra.condition("name")`. The function signature is `def condition_name(state: GraphState) -> str | list[str]`, returning target node name(s). The scan directory is configurable via pipeline YAML or project `orchestra.yaml`.

2. **Agent State Schema** → **Base schema with structured output slots.** Base schema includes `messages` (LangGraph MessageState), `agent_outputs: dict[str, Any]` (keyed by agent name — each agent writes structured output here for downstream agents to read), and `metadata` (session info, timestamps). Pipeline-defined extensions are Pydantic models referenced by import path in YAML. The graph compiler merges base + extension into the full state type.

3. **Interactive Mode UX** → **Chat-style back-and-forth.** When `mode: interactive`, the agent streams output and the human can respond in a multi-turn conversation within that node. The agent and human exchange messages until the human signals completion (e.g., `/done`, `/approve`, `/reject`). Each human turn is a checkpoint boundary, enabling resume from any point in the conversation. The CLI implements this via stdin/stdout; the interface is abstract to support future web UI.

4. **Pipeline Input / Invocation Context** → **Tool-based input gathering.** Rather than a static `inputs:` schema, pipeline agents use tools to fetch their own context. For example, a PR review pipeline's first agent would use a `github:get-pr-diff` tool to retrieve the diff. This makes agents autonomous in context gathering and avoids a separate input declaration mechanism. Built-in tools for common inputs (GitHub PRs, local git diffs, file contents) are provided. Pipeline YAML can specify `context_tools:` at the top level to declare which input-gathering tools are available to all agents.

5. **Session Branch Lifecycle** → **Create at session start, leave on completion.** Session branches are created when a session starts, named `{branch_prefix}{pipeline-name}/{session-short-id}` (e.g., `orchestra/pr-review/a1b2c3`). On completion, branches are left in place — the user merges or deletes them. `orchestra cleanup` command handles stale session branches (e.g., older than N days, or from completed sessions).

6. **Checkpoint Granularity** → **After every node (LangGraph default).** Checkpoints are taken after every node completes, which is LangGraph's default behavior. Workspace snapshots (repo SHAs) are only recorded when a repo's git state has actually changed since the last checkpoint — read-only nodes incur no snapshot overhead. This gives maximum replay granularity with minimal cost.

7. **Error Handling & Retries** → **Layered approach.** LLM call retries are handled by LangChain's built-in retry mechanism (exponential backoff for rate limits/timeouts). Tool execution failures are surfaced to the agent as error messages — the agent decides how to proceed (retry, skip, ask human). Pipeline-level circuit breaker: configurable `max_failures_per_session` before halting the entire pipeline. Token budgets and cost limits are deferred to post-MVP.

8. **Observability** → **Structured SQLite logging + real-time streaming.** Log token usage, tool invocations, wall-clock timing, and agent reasoning per node into the session SQLite database. `orchestra attach` streams agent output in real-time. Optional LangSmith integration for detailed tracing (auto-detected if `LANGSMITH_API_KEY` is set). Custom web dashboard deferred.

9. **Testing Architecture** → **FakeLLM + dry-run + prompt snapshots.** Unit and integration tests use a `FakeLLM` (canned responses configurable per test). `orchestra compile pipeline.yaml` validates YAML, resolves all references (prompts, tools, conditions, providers), and prints the compiled graph structure without executing — serves as a dry-run. Snapshot tests verify that composed prompts match expected output. Optional real LLM integration tests gated behind `ORCHESTRA_REAL_LLM=1`.

10. **File Discovery & Layout** → **Relative to pipeline YAML + global fallback.** Prompt files, condition functions, and tool definitions are resolved relative to the pipeline YAML file's directory. A global `~/.orchestra/` directory provides shared prompts/tools across projects. Project-level `orchestra.yaml` can override search paths. Resolution order: pipeline-relative → project `orchestra.yaml` paths → `~/.orchestra/`.

11. **Parallel Agent Repo Conflicts** → **Worktree-per-agent for full isolation.** Each parallel agent that has write access to a repo gets its own git worktree for that repo. After fan-in (when parallel agents converge), worktrees are merged back into the session branch. Merge conflicts are surfaced to the next downstream agent (or to the human in interactive mode). This enables true parallel writes at the cost of worktree management complexity. The graph compiler warns when parallel agents have write access to the same repo.

## Recommendation

**Confidence: 4/5** — Strong alignment between goals and proposed architecture. The main risk is scope — this is a large system, and disciplined scoping of the initial deliverable is critical.

### Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Implementation** | Python core + TypeScript web UI (deferred) | LangGraph is Python-native; web UI comes later |
| **LangGraph coupling** | Tight — LangGraph IS the runtime | Avoids premature abstraction; leverage checkpoints, state, execution directly |
| **Declarative format** | YAML primary, Python escape hatches | Readable, LLM-friendly, git-diffable; Python for routing conditions |
| **Prompt composition** | Layered assembly (role + persona + personality + task) | Each layer is a composable, reusable YAML file; task layer uses Jinja2 for variable interpolation |
| **Tool registry** | Code-registered tools (decorators) + declarative shell tools in YAML | Flexible for both simple commands and complex tool logic |
| **Project tools** | Layered — `orchestra.project.yaml` in target repo + pipeline overrides | Projects define tools once; pipelines can extend/override |
| **Multi-repo workspace** | Named repo workspaces with repo-qualified tool names (`repo:tool`) | Each repo has its own git context, tools, paths; agents explicitly declare which repos they access |
| **Tool scoping** | Per-repo tool names (`backend:run-tests`, `frontend:run-tests`) | Unambiguous; agents declare exactly which repos/tools they need |
| **Routing conditions** | Plugin directory with `@orchestra.condition()` decorator; configurable scan dir | Auto-discovery avoids manual registration; configurable directory supports flexible project layouts |
| **Git integration** | Dual-write workspace snapshots (checkpoint↔{repo:SHA,...}); worktree-per-agent for parallel writes | Full bidirectional navigation between agent state and code state; true parallel isolation |
| **Checkpoint linking** | Workspace snapshot object: `{checkpoint_id, repos: {name: sha, ...}}` | Single checkpoint maps to N repos; resume restores all repos to their corresponding SHAs |
| **Checkpoint granularity** | After every node (LangGraph default); workspace snapshot only when repo state changed | Maximum replay granularity with minimal overhead for read-only nodes |
| **State schema** | Base schema (`messages`, `agent_outputs: dict[str, Any]`, `metadata`) + Pydantic extensions | Structured inter-agent data passing via `agent_outputs`; pipeline extensions for domain-specific fields |
| **Pipeline inputs** | Tool-based context gathering (agents use tools to fetch their own inputs) | Agents are autonomous in context gathering; no separate input declaration needed; aligns with tool-centric architecture |
| **Execution store** | SQLite local (LangGraph SqliteSaver + Orchestra metadata DB) | Zero-config for CLI; PostgreSQL path available later for remote |
| **Interactive mode** | Chat-style back-and-forth (multi-turn within node, CLI stdin/stdout) | Natural conversation flow; each human turn is a checkpoint boundary; abstract interface for future web UI |
| **LLM providers** | LangChain provider abstraction | Inherits all LangChain-supported providers; natural fit with LangGraph |
| **Model aliases** | Recommended convention (smart/worker/cheap) + custom aliases | Decouple agent capability intent from vendor/model; switch providers in one line; convention aids portability |
| **Literal model fallback** | Unknown aliases treated as literal model strings | Escape hatch for specific models not in alias map |
| **Provider scoping** | Pipeline-level default + per-agent override | Flexibility to mix providers (e.g., Anthropic for "smart", OpenRouter for "worker") |
| **Error handling** | Layered: LangChain retries for LLM + tool errors surfaced to agent + pipeline circuit breaker | Agents handle tool failures intelligently; pipeline halts on repeated failures; token budgets deferred |
| **Observability** | Structured SQLite logging (tokens, tools, timing) + real-time streaming + optional LangSmith | Rich local observability without external dependencies; LangSmith for detailed tracing when available |
| **Testing** | FakeLLM + `orchestra compile` dry-run + prompt snapshot tests + optional real LLM tests | Fast CI with canned responses; dry-run validates config without execution; real LLM tests gated behind env var |
| **File discovery** | Relative to pipeline YAML → project `orchestra.yaml` → `~/.orchestra/` | Predictable resolution order; shared prompts/tools across projects via global dir; project-level overrides |
| **Session branches** | Create at start, named `{prefix}{pipeline}/{session-id}`, left on completion | User controls merge/delete; `orchestra cleanup` for stale branches |
| **Parallel repo conflicts** | Worktree-per-agent for parallel agents with write access | Full isolation enables true parallel writes; merge conflicts surfaced at fan-in to downstream agent or human |
| **Deployment** | Local CLI first; remote server deferred | Reduce scope; add FastAPI server later |
| **Package structure** | Monolith with clean internal module boundaries | Fast initial development; extract packages later if needed |

### Implementation Scope

Build the full system in a single plan-and-execute pass, validated by an end-to-end PR review pipeline.

**Components:**
1. Prompt composition engine (role + persona + personality + task from YAML files)
2. File discovery system (relative to pipeline YAML → project `orchestra.yaml` → `~/.orchestra/`)
3. Tool registry (decorator-based registration + shell command tools, repo-scoped)
4. Agent harness (wraps LangGraph node: prompt + tools + provider/model alias resolution)
5. Base state schema (`messages`, `agent_outputs: dict[str, Any]`, `metadata`) + Pydantic extensions
6. Declarative graph schema (Pydantic models validating the YAML structure)
7. Graph compiler (YAML → LangGraph StateGraph with checkpointing)
8. Condition function plugin directory (auto-discovery via `@orchestra.condition()` decorator)
9. Session management (start, pause, resume, attach to running session)
10. Git integration (session branches, worktree-per-agent for parallel writes, auto-commit, workspace snapshot checkpoint↔SHA linking)
11. Worktree lifecycle management (create at fan-out, merge at fan-in, cleanup)
12. Observability layer (structured SQLite logging: tokens, tools, timing per node)
13. Error handling (LangChain retries, tool error surfacing, pipeline circuit breaker)
14. CLI interface (Typer-based: `orchestra run`, `orchestra compile`, `orchestra attach`, `orchestra replay`, `orchestra status`, `orchestra cleanup`)
15. Adversarial PR review pipeline (end-to-end validation with real LLMs)

**Success Criteria:**
- Can load YAML prompt layers (role, persona, personality, task) and compose them into a single system prompt string
- Prompt files resolved via discovery chain: pipeline-relative → project config → global `~/.orchestra/`
- Can register tools via `@tool_registry.register()` and via YAML shell commands
- Tool names are repo-qualified (`backend:run-tests`) when workspace has multiple repos
- Provider/model alias resolution works: `model: smart` + `provider: anthropic` → `claude-opus-4-20250514`; literal model strings pass through; per-agent provider override works
- Agent harness produces a callable LangGraph node with composed prompt, resolved tools, and resolved model
- Pydantic schema validates the full pipeline YAML (providers, workspace, agents, graph)
- Invalid YAML produces clear, actionable error messages (not Pydantic internals)
- Graph compiler produces a runnable LangGraph StateGraph from valid YAML
- Fan-out (parallel agents), fan-in (join: all), conditional edges, and max_loops all compile correctly
- Condition functions auto-discovered from configurable plugin directory via `@orchestra.condition()` decorator
- `orchestra compile pipeline.yaml` validates YAML, resolves all references, and prints compiled graph structure without executing
- Compiler warns when parallel agents have write access to the same repo
- Pipeline-defined state extensions (Pydantic models) merge correctly with base schema
- `orchestra run pipeline.yaml` compiles and executes a graph with LangGraph checkpointing (SqliteSaver)
- Session branches created at start, named `{prefix}{pipeline}/{session-id}`
- Session state (session ID, status, timestamps) persisted in SQLite
- Agent code changes auto-committed to session branch (sequential) or agent worktree (parallel)
- Worktrees created for parallel agents with write access to the same repo; merged at fan-in
- Workspace snapshots recorded: each checkpoint maps to `{repo_name: git_sha}` for all workspace repos; snapshots only recorded when repo state changes
- `orchestra replay <session_id> --checkpoint <id>` restores LangGraph state AND git working tree(s)
- `orchestra status` shows running/completed sessions with checkpoint counts and token usage
- `orchestra attach <session_id>` connects to a running session's interactive agent (chat-style stdin/stdout, multi-turn)
- `orchestra cleanup` removes stale session branches and worktrees
- Structured logging: token usage, tool invocations, wall-clock timing per node stored in SQLite
- Pipeline circuit breaker: configurable `max_failures_per_session` halts on repeated failures
- Tool execution failures surfaced to agent as error messages
- Optional LangSmith integration auto-detected via `LANGSMITH_API_KEY`
- PR review pipeline: 2+ reviewer agents fan-out (with worktree isolation if writing), critic loops back 0-2 times, synthesizer produces final review via chat-style interactive mode; all with real LLM calls
- Agents use tools to gather context (e.g., `github:get-pr-diff`) — no static input declaration needed
- Agents write structured output to `agent_outputs` for downstream consumption
- Can replay the pipeline from any checkpoint (including mid-conversation checkpoints in interactive nodes)
- Prompt snapshot tests: composed prompts match expected output
- Unit tests for all layers (prompt, tools, schema, compiler, session, git, worktree, observability)
- Integration tests (FakeLLM): compile and run graphs end-to-end, verify checkpoints and git commits are linked
- Integration tests with cheap LLM (Haiku-tier) validate the full flow, gated behind `ORCHESTRA_REAL_LLM=1`

**Testing strategy:** FakeLLM with canned responses for unit and integration tests in CI. `orchestra compile` dry-run validates pipeline configuration without execution. Prompt snapshot tests verify composed prompt output. Optional real LLM integration tests gated behind `ORCHESTRA_REAL_LLM=1` env var for full validation.

### Architecture Diagram

```
                    ┌─────────────────────────────────────────┐
                    │             orchestra CLI                │
                    │  run │ attach │ replay │ status │ cleanup│
                    │  compile (dry-run)                       │
                    └──────────────────┬──────────────────────┘
                                       │
                    ┌──────────────────▼──────────────────────┐
                    │          Runtime Manager                 │
                    │ ┌──────────┐ ┌──────────────┐           │
                    │ │ Session  │ │  Workspace   │           │
                    │ │ Manager  │ │  Git Tracker │           │
                    │ └────┬─────┘ └──────┬───────┘           │
                    │      │              │                   │
                    │ ┌────▼──────────────▼───────┐           │
                    │ │  Worktree Manager         │           │
                    │ │  (per-agent isolation      │           │
                    │ │   for parallel writes)     │           │
                    │ └──────────────┬─────────────┘           │
                    │                │                         │
                    │ ┌──────────────▼─────────────┐           │
                    │ │  Workspace Snapshot Index  │           │
                    │ │  checkpoint_id ↔           │           │
                    │ │  {repo: sha, agent: wt}    │           │
                    │ │  (SQLite)                  │           │
                    │ └────────────────────────────┘           │
                    │                                         │
                    │ ┌────────────────────────────┐           │
                    │ │  Observability             │           │
                    │ │  tokens │ tools │ timing   │           │
                    │ │  (SQLite + optional         │           │
                    │ │   LangSmith)               │           │
                    │ └────────────────────────────┘           │
                    └──────────────────┬──────────────────────┘
                                       │
                    ┌──────────────────▼──────────────────────┐
                    │          Graph Compiler                  │
                    │                                         │
                    │  YAML ──► Pydantic ──►  LangGraph       │
                    │           Schema        StateGraph       │
                    │                                         │
                    │  Condition plugin discovery              │
                    │  (@orchestra.condition decorator)        │
                    └──────────────────┬──────────────────────┘
                                       │
          ┌────────────────────────────┼────────────────────────────┐
          │                            │                            │
 ┌────────▼──────┐           ┌────────▼──────┐           ┌─────────▼─────┐
 │ Prompt        │           │ Tool          │           │ Agent         │
 │ Composer      │           │ Registry      │           │ Harness       │
 │               │           │               │           │               │
 │ role          │           │ @register()   │           │ provider      │
 │ + persona     │           │ shell tools   │           │ + prompts     │
 │ + personality │           │ repo:tool     │           │ + tools       │
 │ + task        │           │ scoping       │           │ + mode        │
 │               │           │ context tools │           │ + agent_output│
 └───────────────┘           └───────┬───────┘           └───────────────┘
                                     │
                    ┌────────────────▼────────────────┐
                    │   Workspace (Multi-Repo)         │
                    │                                  │
                    │  ┌─────────┐     ┌──────────┐    │
                    │  │ repo_a  │     │ repo_b   │    │
                    │  │ path    │     │ path     │    │
                    │  │ git ctx │     │ git ctx  │    │
                    │  │ tools   │     │ tools    │    │
                    │  │ worktrees│     │ worktrees│    │
                    │  └─────────┘     └──────────┘    │
                    └────────────────┬────────────────┘
                                     │
                    ┌────────────────▼────────────────┐
                    │      LangGraph Runtime           │
                    │  StateGraph │ Checkpoint          │
                    │  Execution  │ SqliteSaver         │
                    │  Base state: messages,            │
                    │    agent_outputs, metadata        │
                    └──────────────────────────────────┘
```

**Note:** Single-repo projects are the degenerate case — a workspace with one repo entry. The same abstractions apply; tools are simply unqualified or use the single repo name.

### Key Risks

1. **LangGraph API stability**: v1.0 is recent; breaking changes are possible. Mitigation: pin versions, wrap critical APIs.
2. **Scope creep**: The web UI, remote deployment, and advanced features could delay the core. Mitigation: strict phasing; Phase 1-3 must work before expanding.
3. **State schema rigidity**: The `agent_outputs` dict provides flexibility but could become untyped soup. Mitigation: start with the PR review use case's actual output shapes; encourage Pydantic models for agent output types in pipeline extensions.
4. **Git integration complexity**: Multi-repo workspace snapshots + worktree-per-agent + auto-commits + checkpoint linking has many edge cases (conflicts, dirty state, partial failures across repos). Worktree-per-agent adds worktree lifecycle management and merge-at-fan-in complexity. Mitigation: start with single-repo, single-worktree; add worktree-per-agent for parallel writes incrementally.
5. **Multi-repo coordination**: Agents writing to multiple repos simultaneously creates atomicity challenges — what if a commit to repo_a succeeds but repo_b fails? Mitigation: treat workspace snapshots as best-effort (record whatever succeeded); add transactional semantics later if needed.
6. **Worktree-per-agent merge conflicts**: Parallel agents writing to the same repo in separate worktrees may produce conflicting changes. The merge at fan-in is non-trivial — it requires 3-way merge logic and a strategy for surfacing unresolvable conflicts. Mitigation: implement basic `git merge` at fan-in; surface conflicts to the next agent or human; defer automatic conflict resolution.
7. **Tool-based inputs lack static validation**: Because pipeline inputs are gathered by tools at runtime (not declared in YAML), there's no way to validate "this pipeline needs a GitHub PR" before execution starts. A misconfigured tool or missing credential fails at runtime, not at compile time. Mitigation: `orchestra compile` dry-run validates tool availability and credentials; `context_tools:` in YAML provides documentation of expected inputs even if not enforced.
8. **Interactive mode complexity**: Chat-style multi-turn interaction within a node is more complex than review-and-approve. Managing conversation state, checkpoint boundaries per human turn, and eventual web UI streaming all add implementation surface. Mitigation: start with simple stdin/stdout chat loop; checkpoint after each human message; defer streaming protocol.

### Open Questions (Deferred)

- **Team vs individual use**: Shared pipeline definitions and tool registries can be addressed later. File discovery conventions (relative → project → global) are designed to support this when needed.
- **Evaluation/metrics**: Structured evaluation output from pipeline runs — valuable but not required for MVP. The `agent_outputs` state field provides a natural place to emit structured results; a formal evaluation schema can be layered on top.
- **External tool integrations**: GitHub CLI, Jira, Linear — leave to user-defined tools for now. The tool-based pipeline input model means GitHub PR fetching is already a tool (`github:get-pr-diff`), not a special integration.
- **Token budgets / cost limits**: The layered error handling approach defers token budgets and cost guardrails to post-MVP. The observability layer (SQLite logging of token usage per node) provides the data needed to implement budgets later.
- **Worktree merge conflict resolution**: When parallel agents edit the same file in different worktrees, the merge at fan-in may conflict. The current design surfaces conflicts to the downstream agent or human, but the exact UX and tooling for conflict resolution is deferred.
- **Web UI for interactive mode**: Chat-style interactive mode is CLI-first. The abstract interface supports future web UI, but the real-time streaming protocol and web socket architecture are deferred.
