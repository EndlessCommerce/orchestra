# Orchestra: Attractor-Based Pipeline Orchestration for Software Development

## Summary

Orchestra is an implementation of the [Attractor specification](../attractor/attractor-spec.md) extended for software development workflows. It provides a DOT-based pipeline execution engine with pluggable LLM backends, layered prompt composition, multi-repo workspace management, and git-tracked execution state.

The core pipeline engine follows the attractor spec directly: DOT-defined directed graphs, handler-typed nodes, deterministic edge selection, checkpoint/resume, and a structured event system. Orchestra extends this foundation with capabilities specific to software development: rich agent configuration (role/persona/personality/task prompt composition), multi-repo git workspace integration (session branches, worktree-per-agent isolation, workspace snapshots linking checkpoints to git SHAs), and a pluggable `CodergenBackend` interface whose primary implementation uses LangGraph/LangChain for within-node agentic execution.

LangGraph and LangChain appear in the stack exclusively behind the `CodergenBackend` interface -- not as the pipeline execution engine. The pipeline engine is Orchestra's own implementation of the attractor spec.

## Relationship to Attractor Spec

Orchestra's relationship to the attractor spec falls into three categories:

### Adopted Directly (Follow the Spec)

These features are implemented as specified in the attractor spec with no modifications.

| Feature | Attractor Reference | Notes |
|---------|-------------------|-------|
| Pipeline definition format (DOT) | Sections 2.1-2.13 | Graphviz DOT syntax with attractor's supported subset |
| Pipeline execution engine | Section 3 | Single-threaded traversal with handler dispatch |
| Handler-typed nodes | Section 4 | Shape-to-handler mapping (codergen, wait.human, conditional, parallel, fan_in, tool, manager_loop, start, exit) |
| Edge selection algorithm | Section 3.3 | 5-step deterministic: condition match > preferred label > suggested IDs > weight > lexical |
| Condition expression language | Section 10 | Boolean expressions on edges (`outcome=success`, `context.key=value`, `&&` conjunction) |
| Context and Outcome model | Section 5.1-5.2 | Key-value Context store + structured Outcome |
| Context fidelity | Section 5.4 | full, truncate, compact, summary:low/medium/high modes |
| Goal gates | Section 3.4 | Nodes with `goal_gate=true` must succeed before pipeline exit |
| Retry system | Sections 3.5-3.6 | Per-node `max_retries`, backoff policies, retry targets |
| Run directory / artifact store | Sections 5.5-5.6 | Structured directory per execution with per-node artifacts |
| Event system | Section 9.6 | Typed events for pipeline/stage/parallel/human/checkpoint lifecycle |
| Graph validation / lint rules | Section 7 | Diagnostic model with error/warning/info severity |
| AST transforms | Section 9.1 | Graph modification between parsing and validation |
| Tool handler nodes | Section 4.10 | Non-LLM tool execution as pipeline nodes |
| Manager/supervisor loop | Section 4.11 | Handler for supervising child pipelines |
| Interviewer pattern | Section 6 | Structured human-in-the-loop with Question/Answer model |
| Checkpoint/resume | Section 5.3 | JSON checkpoint after each node |

### Extended by Orchestra

These features adopt the attractor spec's foundation but add capabilities on top.

| Feature | Attractor Base | Orchestra Extension |
|---------|---------------|-------------------|
| CodergenBackend | Simple `run(node, prompt, context) -> String | Outcome` interface | Primary implementation uses LangGraph ReAct agent for within-node agentic execution; also supports CLI agent wrappers and direct API calls |
| Model/provider config | CSS-like model stylesheet (Section 8) | Adds provider aliases (smart/worker/cheap semantic tiers) alongside the stylesheet; aliases defined in config, referenceable from stylesheets |
| Checkpoints | JSON checkpoint per node (Section 5.3) | Extends each checkpoint with workspace snapshots: `{repo_name: git_sha}` for all workspace repos |
| Human interaction | Interviewer pattern for `wait.human` nodes (Section 6) | Adds chat-style interactive mode as an option for codergen nodes needing human input mid-task |
| Node prompts | Simple `prompt` attribute with `$goal` expansion | Layered prompt composition: role + persona + personality + task from separate YAML files |

### Added by Orchestra (Not in Attractor)

These are entirely new capabilities that the attractor spec does not address.

| Feature | Description |
|---------|-------------|
| Multi-repo workspace | Named repo workspaces with repo-qualified tool names (`backend:run-tests`) |
| Git integration | Session branches, worktree-per-agent for parallel writes, auto-commit, remote clone/push for cloud deployment |
| Workspace snapshots | Bidirectional checkpoint-to-git-SHA linking across repos |
| Agent configuration | Rich per-node agent config (prompt layers, model/provider, tool sets) |
| Agent-level tool registry | Decorator-based tool registration, repo-scoped tools, hybrid base+additions model |
| Session management | Named pipeline runs with lifecycle tracking, CLI commands |
| File discovery | Prompt/tool resolution: pipeline-relative > project config > `~/.orchestra/` |

## Architecture

```
Pipeline Definition (.dot files)
        |
   [DOT Parser + Transforms + Validation]
        |
   Pipeline Execution Engine (attractor spec)
   - Handler dispatch (codergen, human, conditional, parallel, ...)
   - Edge selection (5-step deterministic)
   - Checkpoint/resume
   - Context + Outcome model
   - Context fidelity
   - Goal gates + retry system
   - Event system
        |
        +-- codergen nodes --> Agent Config (Orchestra layer)
        |                       - Prompt composition (role + persona + personality + task)
        |                       - Model/provider resolution (aliases + stylesheet)
        |                       - Tool configuration (base + additions + restrictions)
        |                           |
        |                       CodergenBackend interface
        |                           |
        |                       +-- LangGraphBackend (LangGraph ReAct agent + tools)
        |                       +-- CLIAgentBackend (Claude Code, Codex subprocess)
        |                       +-- DirectLLMBackend (single API call, no tools)
        |
        +-- wait.human nodes --> Interviewer (Console, Callback, Queue, AutoApprove)
        +-- tool nodes --> Shell/API execution
        +-- parallel/fan_in --> Concurrent branch execution
        +-- conditional --> Edge condition evaluation
        +-- manager_loop --> Child pipeline supervision
        |
   Workspace Layer (Orchestra extension)
   - Multi-repo workspace management
   - Session branches + worktree-per-agent
   - Workspace snapshots (checkpoint <-> git SHA linking)
   - Session lifecycle (named runs, status, cleanup)
        |
   CXDB Storage Layer (replaces SQLite + JSON files)
   - Sessions as CXDB contexts (branch head pointers)
   - Checkpoints + events as CXDB turns (immutable Turn DAG)
   - Artifacts as CXDB blobs (content-addressed, deduplicated)
   - Type registry for structured projections
   - Built-in UI for execution visualization
        |
   Interfaces
   - CLI (run, compile, status, attach, replay, cleanup)
   - Event stream consumers (TUI, web UI, logging)
   - CXDB UI (turn visualization, custom renderers)
   - HTTP server (future, per attractor Section 9.5)
```

### Layer Responsibilities

**DOT Parser + Transforms + Validation.** Reads `.dot` pipeline files, applies AST transforms (variable expansion, model stylesheet, custom transforms), and validates the graph using the lint rule system. This is the attractor spec's parse-validate-initialize pipeline (Section 3.1) with no modifications.

**Pipeline Execution Engine.** The core traversal loop from attractor Section 3.2. Executes handlers, records outcomes, selects edges, saves checkpoints, and emits events. Orchestra implements this engine directly -- it is not LangGraph. The engine is single-threaded; parallelism exists only within the `parallel` handler.

**Agent Config (Orchestra Layer).** For codergen nodes, Orchestra resolves agent configuration before calling the backend. This includes composing prompts from layered YAML files, resolving model/provider through aliases and stylesheets, and assembling the tool set. The output is a fully resolved prompt + model + tools, which is passed to the `CodergenBackend`.

**CodergenBackend.** The pluggable interface for LLM execution. The pipeline engine calls `backend.run(node, prompt, context)` and receives a `String` or `Outcome` back. What happens inside is opaque. The primary implementation uses LangGraph's ReAct agent for tool-using agentic execution. This is the ONLY place LangGraph/LangChain appear in the stack.

**Workspace Layer.** Orchestra's software development extension. Listens to pipeline events and manages git state: creates session branches at pipeline start, provisions worktrees for parallel agents, records workspace snapshots at each checkpoint, and merges worktrees at fan-in. This layer sits above the pipeline engine and does not affect its execution logic.

**CXDB Storage Layer.** All persistent state is stored in [CXDB](https://github.com/strongdm/cxdb), an AI Context Store. See the [CXDB Integration](#cxdb-integration) section for the full mapping. CXDB replaces SQLite and raw JSON files. The Turn DAG maps directly to pipeline execution traces: each node completion, event, and checkpoint is a typed turn. Sessions are CXDB contexts (branch head pointers). Replay is O(1) forking. Artifacts are content-addressed blobs with automatic deduplication.

**Interfaces.** CLI commands, event stream consumers (TUI, CXDB UI), and an HTTP server (future). The pipeline engine is headless; presentation is separate (attractor Section 9.5-9.6). CXDB's built-in React UI provides turn visualization with custom renderers for each Orchestra turn type.

## Pipeline Definition

Pipelines are defined in Graphviz DOT syntax per the attractor spec (Section 2). Orchestra adds custom node attributes for agent configuration.

### Orchestra-Specific Node Attributes

In addition to the attractor spec's standard attributes (Section 2.6), Orchestra recognizes:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `agent` | String | `""` | References an agent configuration by name (resolved from `orchestra.yaml`) |
| `agent.role` | String | `""` | Inline role prompt layer (alternative to `agent` reference) |
| `agent.persona` | String | `""` | Inline persona prompt layer |
| `agent.personality` | String | `""` | Inline personality prompt layer |
| `agent.task` | String | `""` | Inline task prompt template |
| `agent.tools` | String | `""` | Comma-separated tool names available to the LLM inside this node |
| `agent.mode` | String | `"autonomous"` | `autonomous` (no human interaction) or `interactive` (chat-style within node) |

### Example: Adversarial PR Review Pipeline

```dot
digraph pr_review {
    graph [
        goal="Review the pull request from multiple perspectives and produce a synthesized review",
        label="Adversarial PR Review",
        model_spec="
            * { llm_model: smart; llm_provider: anthropic; }
            .critic { llm_model: worker; llm_provider: openrouter; }
            #synthesizer { llm_model: smart; }
        "
    ]

    node [shape=box, timeout="900s"]

    start [shape=Mdiamond, label="Start"]
    exit  [shape=Msquare, label="Exit"]

    // Parallel reviewers -- each references an agent config
    security_reviewer [
        label="Security Review",
        agent="security-reviewer",
        goal_gate=true
    ]

    architecture_reviewer [
        label="Architecture Review",
        agent="architecture-reviewer",
        goal_gate=true
    ]

    // Fan-out to parallel reviewers
    fan_out [shape=component, label="Fan Out"]

    // Fan-in to collect results
    fan_in [shape=tripleoctagon, label="Collect Reviews"]

    // Critic with inline agent config
    critic [
        label="Adversarial Critique",
        class="critic",
        agent.role="adversarial-critic",
        agent.persona="devils-advocate",
        agent.personality="contrarian-precise",
        agent.task="critique-reviews",
        max_retries=2
    ]

    // Conditional routing after critic
    gate [shape=diamond, label="Critique Sufficient?"]

    // Synthesizer with interactive mode
    synthesizer [
        label="Synthesize Review",
        agent="synthesizer",
        agent.mode="interactive"
    ]

    // Graph edges
    start -> fan_out
    fan_out -> security_reviewer
    fan_out -> architecture_reviewer
    security_reviewer -> fan_in
    architecture_reviewer -> fan_in
    fan_in -> critic
    critic -> gate
    gate -> fan_out [label="Retry", condition="outcome!=success", weight=0]
    gate -> synthesizer [label="Proceed", condition="outcome=success", weight=1]
    synthesizer -> exit
}
```

### Orchestra Configuration File

Non-graph configuration (providers, workspaces, agent definitions, tool registrations) lives in `orchestra.yaml`, separate from the DOT pipeline file. This keeps the DOT file focused on graph structure while the YAML handles project-specific configuration.

```yaml
# orchestra.yaml -- project configuration
providers:
  default: anthropic
  anthropic:
    models:
      smart: claude-opus-4-20250514
      worker: claude-sonnet-4-20250514
      cheap: claude-haiku-3-20250514
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
      path: ../backend
      branch_prefix: orchestra/
      # Optional remote git config (for cloud/CI deployment):
      # remote: git@github.com:org/backend.git
      # push: on_completion    # on_completion | on_checkpoint | never
      # clone_depth: 50        # shallow clone depth (omit for full clone)
    frontend:
      path: ../frontend
      branch_prefix: orchestra/
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
    role: security-engineer
    persona: senior-security-engineer
    personality: thorough-skeptical
    task: review-pr-security
    tools:
      - backend:read-file
      - backend:search-code
      - backend:run-tests
      - frontend:read-file
      - frontend:search-code

  architecture-reviewer:
    role: software-architect
    persona: principal-engineer
    personality: pragmatic-opinionated
    task: review-pr-architecture
    tools:
      - backend:read-file
      - backend:search-code
      - frontend:read-file
      - frontend:search-code

  synthesizer:
    role: review-synthesizer
    persona: tech-lead
    personality: balanced-decisive
    task: synthesize-review
    tools: []
```

### Separation of Concerns

The DOT file defines **what** the pipeline does (graph structure, flow control, node types). The YAML file defines **how** it is configured (providers, workspaces, agent prompts, tools). This separation means:

- The same DOT pipeline can be used with different provider configurations
- Agent definitions are reusable across pipelines
- Graph structure is visualizable with standard Graphviz tooling
- DOT files remain clean and focused on flow

## Execution Engine

Orchestra implements the attractor spec's execution engine (Section 3) with no modifications. The following subsections summarize the key behaviors; the attractor spec is the authoritative reference.

### Core Execution Loop

The engine traverses the graph from the start node (shape=Mdiamond) using a simple loop: execute handler, record outcome, select next edge, advance. Attractor Section 3.2 defines this in full pseudocode.

### Edge Selection (5-Step Deterministic Algorithm)

After a node completes, the engine selects the next edge deterministically (attractor Section 3.3):

1. **Condition match.** Evaluate boolean expressions on edges against context and outcome. Condition-matched edges are eligible.
2. **Preferred label match.** If the outcome includes a `preferred_label`, match it against edge labels (normalized: lowercase, trimmed, accelerator prefixes stripped).
3. **Suggested next IDs.** If the outcome includes `suggested_next_ids`, match against edge targets.
4. **Highest weight.** Among remaining eligible unconditional edges, highest `weight` wins.
5. **Lexical tiebreak.** Equal weights are broken by alphabetical target node ID.

The LLM's role in routing is limited: it returns an outcome status (SUCCESS/FAIL/RETRY) and optionally suggests a preferred label or next IDs. Conditions (step 1) always have highest priority. The engine -- not the LLM -- decides which edge to follow.

### Goal Gate Enforcement

Nodes with `goal_gate=true` must reach SUCCESS or PARTIAL_SUCCESS before the pipeline can exit. When the engine reaches a terminal node (shape=Msquare), it checks all visited goal gate nodes. If any are unsatisfied, the engine reroutes to the `retry_target` (node-level, then graph-level) instead of exiting. See attractor Section 3.4.

### Retry System

Each node has a retry policy (attractor Sections 3.5-3.6):

- `max_retries` specifies additional attempts beyond the initial execution (so `max_retries=3` means up to 4 total)
- Backoff policies: `standard` (200ms, 2x), `aggressive` (500ms, 2x), `linear` (500ms, 1x), `patient` (2000ms, 3x)
- Jitter is applied by default to prevent thundering herd
- When retries are exhausted: `retry_target` for rerouting, `allow_partial` for accepting PARTIAL_SUCCESS, or FAIL

### Context Fidelity

Controls how much prior context carries to each node's LLM session (attractor Section 5.4):

| Mode | Session | Context Carried | Approximate Token Budget |
|------|---------|-----------------|-------------------------|
| `full` | Reused (same thread) | Full conversation history | Unbounded (uses compaction) |
| `truncate` | Fresh | Minimal: goal and run ID | Minimal |
| `compact` | Fresh | Structured bullet-point summary | Moderate |
| `summary:low` | Fresh | Brief textual summary | ~600 tokens |
| `summary:medium` | Fresh | Moderate detail: recent outcomes, context values | ~1500 tokens |
| `summary:high` | Fresh | Detailed: recent events, tool summaries, comprehensive context | ~3000 tokens |

Resolution precedence: edge `fidelity` attribute > target node `fidelity` > graph `default_fidelity` > `compact`.

### Event System

The engine emits typed events for every significant action (attractor Section 9.6):

- **Pipeline lifecycle:** PipelineStarted, PipelineCompleted, PipelineFailed
- **Stage lifecycle:** StageStarted, StageCompleted, StageFailed, StageRetrying
- **Parallel execution:** ParallelStarted, ParallelBranchStarted/Completed, ParallelCompleted
- **Human interaction:** InterviewStarted, InterviewCompleted, InterviewTimeout
- **Checkpoint:** CheckpointSaved

Events are consumed via observer/callback pattern or async stream. The pipeline engine is headless; all UI (CLI, web, TUI) consumes events.

### Graph Validation

Before execution, the engine validates the graph (attractor Section 7). Built-in lint rules include:

| Rule | Severity | Description |
|------|----------|-------------|
| `start_node` | ERROR | Exactly one start node (shape=Mdiamond) required |
| `terminal_node` | ERROR | At least one exit node (shape=Msquare) required |
| `reachability` | ERROR | All nodes reachable from start |
| `edge_target_exists` | ERROR | All edge targets reference existing nodes |
| `start_no_incoming` | ERROR | Start node has no incoming edges |
| `exit_no_outgoing` | ERROR | Exit node has no outgoing edges |
| `condition_syntax` | ERROR | Edge conditions parse correctly |
| `stylesheet_syntax` | ERROR | Model stylesheet parses correctly |
| `prompt_on_llm_nodes` | WARNING | Codergen nodes should have a `prompt` or `label` |
| `goal_gate_has_retry` | WARNING | Goal gate nodes should have a retry target |

`orchestra compile pipeline.dot` runs validation without execution -- a dry-run that resolves all references and reports diagnostics.

## Agent Configuration

Orchestra layers agent configuration on top of attractor's codergen nodes. When the pipeline engine dispatches to the codergen handler, Orchestra's agent config layer resolves the prompt, model, and tools before calling the `CodergenBackend`.

### Prompt Composition

Prompts are assembled from four layers, each a separate YAML file:

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
    vulnerability. You don't raise false alarms -- when you flag
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

The composed system prompt is assembled as `role + persona + personality + task`, each layer additive. The task layer uses Jinja2 for variable interpolation (`{{pr_diff}}`). The other layers are plain text blocks.

This layered approach is an Orchestra extension -- the attractor spec only supports simple `prompt` attributes with `$goal` expansion. The composed prompt is what gets passed to `CodergenBackend.run()`.

### File Discovery

Prompt files, agent definitions, and tool configurations are resolved via a discovery chain:

1. **Pipeline-relative**: relative to the `.dot` file's directory
2. **Project config**: paths specified in `orchestra.yaml`
3. **Global fallback**: `~/.orchestra/`

Resolution stops at the first match. This supports shared prompts/tools across projects via the global directory, with project-level overrides.

### Model and Provider Resolution

Orchestra combines attractor's model stylesheet with a provider alias system:

**Provider aliases** (Orchestra extension) define semantic model tiers in `orchestra.yaml`:

```yaml
providers:
  default: anthropic
  anthropic:
    models:
      smart: claude-opus-4-20250514
      worker: claude-sonnet-4-20250514
      cheap: claude-haiku-3-20250514
```

**Model stylesheet** (attractor Section 8) provides CSS-like per-node overrides in the DOT file:

```
model_spec="
    * { llm_model: smart; llm_provider: anthropic; }
    .code { llm_model: worker; }
    #critical_review { llm_model: gpt-4o; llm_provider: openai; reasoning_effort: high; }
"
```

**Resolution order** (highest to lowest precedence):

1. Explicit node attribute (`llm_model="gpt-4o"` on the node)
2. Stylesheet rule by specificity (ID > class > universal)
3. Agent config model setting
4. Graph-level default
5. Provider default

Alias resolution: if the resolved model string matches a key in `providers.{provider}.models`, it resolves to the mapped model string. If not found, it is treated as a literal model identifier. This means `llm_model: smart` resolves to `claude-opus-4-20250514` when the provider is `anthropic`, but `llm_model: gpt-4o` passes through unchanged.

**Key design property:** Changing `providers.default: openai` in `orchestra.yaml` switches all agents (that don't override) from Anthropic to OpenAI in one line, while preserving the smart/worker/cheap tier semantics.

### Agent-Level Tool Configuration

Tools available to the LLM inside codergen nodes operate on a hybrid model:

1. **Backend base toolset**: The `CodergenBackend` implementation provides a default set of tools (e.g., LangGraph backend provides read_file, edit_file, shell, grep, glob)
2. **Agent additions**: The agent config in `orchestra.yaml` can add tools (e.g., `backend:run-tests`, `frontend:run-lint`)
3. **Agent restrictions**: An agent config can restrict to a subset of available tools

Repo-scoped tools use a `{repo}:{tool}` naming convention. Built-in tools (read-file, write-file, search-code) are automatically generated per-repo in the workspace. Project-specific tools are defined per-repo in `orchestra.yaml`.

```python
from orchestra.tools import tool_registry, RepoContext

# Decorator-based registration for custom tools
@tool_registry.register_builtin("read-file")
def read_file(path: str, repo: RepoContext) -> str:
    """Read a file from the repo's working directory."""
    full_path = repo.resolve_path(path)
    return full_path.read_text()

# User-defined tools can also be repo-scoped
@tool_registry.register("run-migration", repo="backend")
def run_migration() -> str:
    """Run database migrations."""
    ...

# Cross-repo tools (not scoped to any single repo)
@tool_registry.register("run-integration-tests")
def run_integration_tests() -> str:
    """Run integration tests spanning frontend and backend."""
    ...
```

Note: this is distinct from attractor's tool handler nodes (Section 4.10), which are pipeline-level non-LLM tool execution. Agent-level tools are available to the LLM inside codergen nodes; tool handler nodes are standalone pipeline nodes that run shell commands or API calls without an LLM.

## CodergenBackend

The `CodergenBackend` is the interface between Orchestra's pipeline engine and LLM execution. It follows the attractor spec's design (Section 4.5) with Orchestra providing specific implementations.

### Interface

```python
class CodergenBackend(Protocol):
    def run(self, node: Node, prompt: str, context: Context,
            on_turn: Callable[[AgentTurn], None] | None = None) -> str | Outcome:
        """Execute an LLM task for the given node.

        Args:
            node: The parsed Node with all its attributes (including agent config).
            prompt: The fully composed prompt (after Orchestra's prompt composition).
            context: The pipeline's shared key-value context.
            on_turn: Optional callback invoked after each agent loop turn.
                     Receives an AgentTurn with the LLM response, tool calls,
                     files modified, and token usage for that turn. The workspace
                     layer uses this to commit changes and record CXDB turns
                     at agent-turn granularity.

        Returns:
            A string response (converted to SUCCESS Outcome by the handler),
            or an Outcome with explicit status, context_updates, etc.
        """
        ...

@dataclass
class AgentTurn:
    """Data emitted after each turn of the agent loop."""
    turn_number: int              # 0-indexed turn within this node execution
    model: str                    # resolved model string (e.g., "claude-sonnet-4-20250514")
    provider: str                 # resolved provider (e.g., "anthropic")
    messages: list[dict]          # LLM messages for this turn (prompt + response)
    tool_calls: list[ToolCall]    # tool calls made in this turn
    files_written: list[str]      # file paths modified by write tools in this turn
    token_usage: TokenUsage       # prompt + completion token counts
    agent_state: bytes | None     # serialized agent state for resume (LangGraph checkpoint)
```

The pipeline engine calls `backend.run()` and passes an `on_turn` callback. The backend invokes this callback after each turn of the agent loop. The workspace layer hooks into `on_turn` to commit file changes, record CXDB turns, and enable per-turn resume.

**Key design property:** The `on_turn` callback is optional. Backends that don't support turn-level visibility (like CLIAgentBackend) simply never call it, and the workspace layer falls back to a single commit at node completion. Backends that do support it (LangGraphBackend) call it after every turn, enabling fine-grained checkpoint/commit/resume.

### Write Tracking

File write tools (write-file, edit-file, and any tool that modifies the filesystem) report their writes via the tool registry's write tracker. This gives Orchestra explicit knowledge of what changed in each turn, rather than relying on `git status` after the fact.

```python
class WriteTracker:
    """Tracks file modifications made by tools within an agent turn."""

    def __init__(self):
        self._writes: list[str] = []

    def record(self, path: str) -> None:
        """Called by write tools after modifying a file."""
        if path not in self._writes:
            self._writes.append(path)

    def flush(self) -> list[str]:
        """Return tracked writes and reset for the next turn."""
        writes = self._writes.copy()
        self._writes.clear()
        return writes
```

Built-in write tools call `write_tracker.record(path)` after every file modification. The tracker is flushed at the end of each agent turn to populate `AgentTurn.files_written`. Only the files in `files_written` are staged for commit -- no `git status` scan needed.

Custom tools that modify files are expected to call the write tracker. Orchestra provides a `@modifies_files` decorator that auto-records paths returned by the tool:

```python
@tool_registry.register("apply-patch", repo="backend")
@modifies_files
def apply_patch(patch: str, repo: RepoContext) -> list[str]:
    """Apply a patch. Returns list of modified file paths."""
    modified = repo.apply_patch(patch)
    return modified  # @modifies_files records these paths
```

### LangGraphBackend (Primary Implementation)

Uses LangGraph's ReAct agent for within-node agentic execution. The backend intercepts each turn of the agent loop to invoke the `on_turn` callback with full turn data:

```python
class LangGraphBackend(CodergenBackend):
    """Uses LangGraph's create_react_agent for tool-using LLM execution.

    This backend gives the LLM access to tools (read_file, edit_file,
    shell, grep, glob, plus any agent-configured additions) and runs
    an agentic loop: LLM -> tool calls -> LLM -> ... until done.

    After each turn, the on_turn callback is invoked with the turn data.
    This enables the workspace layer to commit changes and record CXDB
    turns at agent-turn granularity.
    """

    def run(self, node: Node, prompt: str, context: Context,
            on_turn: Callable[[AgentTurn], None] | None = None) -> str | Outcome:
        model = resolve_model(node)
        tools = resolve_tools(node)
        write_tracker = WriteTracker()

        # Inject write tracker into tools that modify files
        tools = inject_write_tracker(tools, write_tracker)

        # Create LangGraph ReAct agent with checkpointing
        agent = create_react_agent(model, tools, checkpointer=checkpointer)

        # Stream the agent execution turn-by-turn
        turn_number = 0
        for event in agent.stream({"messages": [("user", prompt)]}):
            if is_agent_turn_complete(event):
                files_written = write_tracker.flush()
                if on_turn:
                    on_turn(AgentTurn(
                        turn_number=turn_number,
                        model=model.model_name,
                        provider=model.provider,
                        messages=extract_messages(event),
                        tool_calls=extract_tool_calls(event),
                        files_written=files_written,
                        token_usage=extract_token_usage(event),
                        agent_state=checkpointer.get_latest(),
                    ))
                turn_number += 1

        return build_outcome(result)
```

This is the right level for LangGraph -- it manages the inner agentic loop (tool use, multi-turn LLM interaction) within a single pipeline node. LangGraph's checkpointing, streaming, and tool infrastructure add real value here. The `on_turn` callback gives the outer layers visibility into each turn without breaking encapsulation.

### CLIAgentBackend

Wraps CLI coding agents (Claude Code, Codex, Gemini CLI) as subprocesses:

```python
class CLIAgentBackend(CodergenBackend):
    """Spawns a CLI agent as a subprocess.

    Pragmatic shortcut: get a full agentic loop for free.
    Tradeoff: no turn-level visibility. The on_turn callback is not
    invoked -- the workspace layer falls back to a single commit at
    node completion using git status to detect changes.
    """

    def run(self, node: Node, prompt: str, context: Context,
            on_turn: Callable[[AgentTurn], None] | None = None) -> str | Outcome:
        result = subprocess.run(
            ["claude", "--print", "--model", "sonnet", prompt],
            capture_output=True, text=True
        )
        return result.stdout
```

### DirectLLMBackend

Single LLM API call with no tool use. Suitable for analysis, review, and synthesis nodes that don't need to interact with the filesystem:

```python
class DirectLLMBackend(CodergenBackend):
    """Direct LLM API call. No tools, no agentic loop.

    Good for nodes that analyze, summarize, or review --
    not for nodes that need to read/write files or run commands.
    No files are modified, so on_turn is not invoked.
    """

    def run(self, node: Node, prompt: str, context: Context,
            on_turn: Callable[[AgentTurn], None] | None = None) -> str | Outcome:
        model = resolve_model(node)
        response = model.invoke([("system", prompt)])
        return response.content
```

### Backend Selection

The backend can be configured at multiple levels:

1. **Global default** in `orchestra.yaml`: `backend: langgraph`
2. **Per-pipeline** in `orchestra.yaml` under the pipeline key
3. **Per-node** via a `backend` attribute on the node (future extension)

Most pipelines will use a single backend. The interface exists to support diverse deployment scenarios: local development (LangGraphBackend), CI/CD (DirectLLMBackend for speed), and quick prototyping (CLIAgentBackend).

### Turn-Level Visibility by Backend

| Backend | Turn-level `on_turn` | Write tracking | Commit granularity |
|---------|---------------------|----------------|-------------------|
| LangGraphBackend | Yes — called after each agent loop turn | Explicit via WriteTracker | Per agent turn |
| CLIAgentBackend | No — opaque subprocess | Implicit via `git status` at node completion | Per node |
| DirectLLMBackend | No — single call, no file modifications | N/A | N/A |

## Workspace and Git Integration

Orchestra adds multi-repo workspace management and git integration as a layer above the pipeline engine. The engine emits events; the workspace layer reacts. This is entirely an Orchestra extension -- the attractor spec has no workspace or git concept.

### Multi-Repo Workspace

Workspaces are defined in `orchestra.yaml`:

```yaml
workspace:
  repos:
    backend:
      path: ../backend
      branch_prefix: orchestra/
    frontend:
      path: ../frontend
      branch_prefix: orchestra/
```

Each repo has its own git context, tools, and paths. Tools are repo-qualified (`backend:run-tests`). Single-repo projects are the degenerate case with one entry.

### Remote Git Operations

For cloud and CI/CD deployments where repos are not pre-existing on the host, workspace repos can be configured with a `remote` URL. Orchestra manages the clone/fetch/push lifecycle around its existing local git operations:

```yaml
workspace:
  repos:
    backend:
      path: /workspace/backend
      remote: git@github.com:org/backend.git
      branch_prefix: orchestra/
      push: on_completion          # push session branches when pipeline completes
    frontend:
      path: /workspace/frontend
      remote: git@github.com:org/frontend.git
      branch_prefix: orchestra/
      push: on_checkpoint          # push after each checkpoint (ephemeral environments)
      clone_depth: 50              # shallow clone for large repos
```

**Clone/fetch at session start.** If a workspace repo's `path` does not exist but `remote` is configured, Orchestra clones it before creating the session branch. If the path already exists, Orchestra fetches to ensure the local clone is up to date. Without a `remote`, Orchestra expects the repo to exist locally (existing behavior).

**Push policies.** The `push` attribute controls when session branches are pushed to the remote:

| Policy | Behavior | Use Case |
|--------|----------|----------|
| `never` | No push (default when no `remote`) | Local-only development |
| `on_completion` | Push after pipeline completes successfully (default when `remote` is set) | Standard cloud deployment |
| `on_checkpoint` | Push after each auto-commit/checkpoint | Ephemeral containers — survive crash/restart |

Push failures are non-fatal: logged as warnings, not pipeline errors. Failed pipelines with `push: on_completion` do not auto-push -- the user or a cleanup policy decides.

**Credentials.** Git authentication delegates to the host environment's existing credential configuration (SSH keys, credential helpers, `GIT_ASKPASS`, cloud IAM roles, CI/CD credential injection). Orchestra does not manage credentials.

**Shallow clones.** `clone_depth` enables shallow clones (`git clone --depth N`) for large repos in ephemeral environments. Deep history is fetched on demand only if needed (e.g., for merge conflict resolution).

**Ephemeral environment lifecycle.** In containers and serverless jobs, the full lifecycle is: clone from remote → create session branch → run pipeline → auto-commit agent changes → push to remote (per policy) → container exits. The CXDB turns with workspace snapshots persist in the CXDB server; the git commits persist in the remote. SHAs in CXDB point to commits in the remote, so the correlation survives the container's death. Resume clones again, restores git state from the CXDB checkpoint's workspace snapshot, and continues.

### Session Branches

When a pipeline run starts, Orchestra creates a session branch in each workspace repo:

- Branch name: `{branch_prefix}{pipeline-name}/{session-short-id}` (e.g., `orchestra/pr-review/a1b2c3`)
- Base commit SHA is recorded for each repo
- On completion, branches are left in place -- the user merges or deletes them
- `orchestra cleanup` handles stale session branches

### Worktree-Per-Agent Isolation

When the parallel handler fans out to multiple codergen nodes that have write access to the same repo, each parallel branch gets its own git worktree for that repo:

- Worktrees are created in `.orchestra/worktrees/{session-id}/{agent-name}`
- Each agent commits to its own worktree independently
- At fan-in, worktrees are merged back into the session branch
- Merge conflicts are surfaced to the downstream agent or human (via the Interviewer)
- Sequential agents (after fan-in) work directly on the session branch -- no worktree overhead

```
Execution Timeline (2-repo workspace, parallel agents with worktrees):

  checkpoint_0 ---- checkpoint_1a/1b ---- checkpoint_2 (fan-in) ---- checkpoint_3
       |                  |                       |                        |
   workspace:         agent worktrees:         merged workspace:        workspace:
   backend: abc123    security: wt_sec/def     backend: merged_sha     backend: jkl012
   frontend: 111aaa   arch: wt_arch/ghi        frontend: 111aaa        frontend: 333ccc
   (both at base)    (parallel, isolated)     (worktrees merged)      (sequential)
```

### Per-Turn Commits

When the workspace layer receives an `on_turn` callback from a CodergenBackend with `files_written` populated, it commits the changes and records the git SHA. The commit is precise (only tracked files are staged) and includes agent metadata in the git history.

**Commit process per agent turn:**

1. **Stage exactly the tracked files.** `git add` only the paths in `AgentTurn.files_written`. No `git status` scan -- the write tracker provides the exact list.
2. **Generate commit message via LLM.** Orchestra makes a separate LLM call (using the `cheap` model tier) with the staged diff and a brief summary of the agent's intent (extracted from the turn's messages). The LLM produces a conventional, human-readable commit message.
3. **Commit with agent metadata.** The commit includes structured metadata identifying the agent, model, and pipeline context:

```
Add email format and password strength validation to registration endpoint

Implements server-side validation for email format using RFC 5322 regex
and password strength checks (minimum length, complexity requirements)
in the registration controller. Adds corresponding request specs.

Orchestra-Model: claude-sonnet-4-20250514
Orchestra-Provider: anthropic
Orchestra-Node: security_reviewer
Orchestra-Pipeline: pr-review
Orchestra-Session: a1b2c3
Orchestra-Turn: 2
```

The commit author is set to identify the agent: `git commit --author="security_reviewer (claude-sonnet-4-20250514) <orchestra@local>"`. Git trailers (`Orchestra-Model`, etc.) provide structured, machine-parseable metadata. Both the author and trailers are visible in standard `git log` output.

4. **Record SHA in CXDB AgentTurn.** The resulting commit SHA is written to the `git_sha` field of the `dev.orchestra.AgentTurn` CXDB turn for this agent turn. This creates the bidirectional correlation: CXDB turn → git SHA, and `git log` trailers → CXDB session/node/turn.

**LLM commit message generation:**

```python
def generate_commit_message(diff: str, agent_intent: str, model: ChatModel) -> str:
    """Generate a conventional commit message from a diff.

    Uses the cheap model tier for cost efficiency. The prompt includes
    the staged diff and a summary of what the agent was trying to do
    (extracted from the agent's last assistant message).
    """
    response = model.invoke([
        ("system", "Generate a concise git commit message for the following changes. "
                   "First line: imperative summary under 72 chars. "
                   "Then a blank line and a brief description of what changed and why. "
                   "Do not include file lists or line counts."),
        ("user", f"Agent intent: {agent_intent}\n\nDiff:\n{diff}")
    ])
    return response.content.strip()
```

**Fallback for CLIAgentBackend.** Since the CLI backend doesn't provide turn-level visibility, the workspace layer falls back to `git status` at node completion, commits all changes in a single commit, and generates the commit message from the full diff. Agent metadata is still recorded (the model comes from the agent config rather than per-turn data).

### Workspace Snapshots

Workspace snapshots link CXDB state to git state. They are recorded at two granularities:

**Per agent turn (within a node).** Each `dev.orchestra.AgentTurn` CXDB turn with file writes includes the `git_sha` of the commit for that turn. This is the fine-grained correlation.

**Per node (at checkpoint boundaries).** The `dev.orchestra.Checkpoint` turn at each node boundary includes a workspace snapshot summarizing the current HEAD SHA for each repo:

```json
{
    "type_id": "dev.orchestra.Checkpoint",
    "type_version": 1,
    "data": {
        "current_node": "critic",
        "completed_nodes": ["start", "fan_out", "security_reviewer", "architecture_reviewer", "fan_in"],
        "context_snapshot": { "...": "..." },
        "retry_counters": {},
        "agent_turn_number": null,
        "workspace_snapshot": {
            "repos": [
                { "name": "backend", "git_sha": "abc123def", "branch": "orchestra/pr-review/a1b2c3" },
                { "name": "frontend", "git_sha": "111aaabbb", "branch": "orchestra/pr-review/a1b2c3" }
            ]
        }
    }
}
```

Workspace snapshots are only recorded when a repo's git state has actually changed since the last checkpoint -- read-only nodes and read-only turns incur no snapshot overhead.

### Resumability at Agent Turn Granularity

Orchestra supports resume at two levels:

**Resume at node boundary (standard).** `orchestra resume <session_id>` reads the CXDB context's head turn, finds the latest `dev.orchestra.Checkpoint`, restores pipeline state (completed_nodes, context, retry counters), and checks out each repo to its workspace snapshot SHA. Execution continues from the next node.

**Resume at agent turn (within a node).** `orchestra resume <session_id> --turn <turn_id>` restores to a specific `dev.orchestra.AgentTurn` within a codergen node:

1. The Checkpoint state is restored from the most recent `dev.orchestra.Checkpoint` before the target turn (which positions the pipeline at the correct node).
2. Each repo is checked out to the `git_sha` from the target AgentTurn (which restores the code to the exact state after that turn).
3. The LangGraph agent's internal state is restored from the `agent_state_ref` in the AgentTurn payload (which positions the agent at the correct point in its tool-use loop).
4. The agent continues from the next turn, with full context of what it has already done.

This means you can examine what the agent did at turn 3, check out the code at that point, and either resume from there or fork a new execution. The CXDB fork operation applies: `orchestra replay <session_id> --turn <turn_id>` forks the CXDB context at the AgentTurn and creates a new execution branch.

```
Node execution timeline with per-turn commits:

  AgentTurn 0          AgentTurn 1          AgentTurn 2          AgentTurn 3
  (reads files)        (edits controller)   (adds tests)         (reviews, done)
       |                    |                    |                    |
  CXDB turn:           CXDB turn:           CXDB turn:           CXDB turn:
  files_written: []    files_written:       files_written:       files_written: []
  git_sha: null        [controller.rb]      [spec.rb]            git_sha: null
                       git_sha: e4f5a6b     git_sha: 8c9d0e1
                       commit: "Add         commit: "Add
                       validation to..."    registration specs"
```

The CXDB Blob CAS ensures identical workspace snapshots across turns are deduplicated.

## Session Management

A session is a CXDB context -- a mutable branch head pointer into the Turn DAG. The turn chain within a context represents the full execution trace: events, checkpoints, and artifacts.

### Session Lifecycle

1. **Start**: `orchestra run pipeline.dot` creates a CXDB context (the session), registers Orchestra's turn types if needed, creates session branches in workspace repos, and initializes the pipeline engine
2. **Execute**: The engine traverses the graph, appending typed turns to the CXDB context. Within codergen nodes, each agent loop turn appends a `dev.orchestra.AgentTurn` with messages, tool calls, files written, and git SHA. At node boundaries, a `dev.orchestra.Checkpoint` is appended with the full pipeline state. The context's head pointer advances with each turn.
3. **Pause**: The engine can be interrupted (Ctrl-C or API signal); the last turn in the CXDB context IS the checkpoint -- no separate save step. If interrupted mid-agent-loop, the last AgentTurn is the restore point.
4. **Resume (node boundary)**: `orchestra resume <session_id>` reads the head turn, finds the latest Checkpoint, restores pipeline state and git state, continues from the next node.
5. **Resume (agent turn)**: `orchestra resume <session_id> --turn <turn_id>` restores to a specific AgentTurn within a node: pipeline state from the enclosing Checkpoint, git state from the AgentTurn's git_sha, agent state from the AgentTurn's agent_state_ref. Continues from the next turn.
6. **Replay**: `orchestra replay <session_id> --checkpoint <turn_id>` forks the CXDB context at the specified turn (O(1) operation). Works with both Checkpoint turns and AgentTurn turns. Execution proceeds from the fork point, diverging from the original.
7. **Complete**: Pipeline reaches the exit node; a PipelineCompleted turn is appended; workspace branches are left for user to merge/delete

### CXDB as Session Storage

All persistent state is stored in CXDB. There is no local SQLite database and no local run directory. CXDB replaces both:

- **Sessions → CXDB contexts.** Each pipeline run creates a CXDB context. The context ID is the session ID. The context's head turn tracks current execution position.
- **Agent turns → CXDB turns.** Within each codergen node, every agent loop iteration appends a `dev.orchestra.AgentTurn` turn. The turn payload contains: messages, tool calls, files written, git SHA (if files changed), commit message, model/provider, token usage, and a serialized agent state reference. This is the finest-grained record in the system.
- **Checkpoints → CXDB turns.** After each node completion, a checkpoint turn is appended. The turn payload contains: current_node, completed_nodes, context snapshot, retry counters, and workspace snapshot (current HEAD SHAs per repo).
- **Events → CXDB turns.** Every pipeline event (PipelineStarted, StageStarted, StageCompleted, etc.) is appended as a typed turn. This creates a persistent, queryable event log.
- **Artifacts → CXDB blobs.** Prompts, responses, and other artifacts are stored as part of turn payloads. CXDB's Blob CAS (content-addressed storage with BLAKE3 hashing) automatically deduplicates identical payloads across runs.
- **Replay → CXDB fork.** `POST /v1/contexts/fork` with `base_turn_id` pointing to any checkpoint or AgentTurn. O(1) -- no data copying. Enables replay from any agent turn, not just node boundaries.
- **Inspection → CXDB UI.** The CXDB React UI provides turn visualization with custom renderers. AgentTurn renderers show the agent's reasoning, tool calls, files changed, and a link to the git diff.

### CLI Commands

| Command | Description |
|---------|-------------|
| `orchestra run <pipeline.dot>` | Compile and execute a pipeline |
| `orchestra compile <pipeline.dot>` | Validate, resolve references, print graph structure (dry-run) |
| `orchestra status` | List running/completed sessions (queries CXDB contexts) |
| `orchestra resume <session_id>` | Resume a paused or crashed session from the head turn |
| `orchestra replay <session_id> --checkpoint <turn_id>` | Fork the CXDB context at a specific turn and re-execute |
| `orchestra attach <session_id>` | Connect to a running session's event stream (or interactive agent) |
| `orchestra cleanup` | Remove stale session branches and worktrees |
| `orchestra doctor` | Verify CXDB connectivity and type registry |

## CXDB Integration

Orchestra uses [CXDB](https://github.com/strongdm/cxdb) as its storage backend. CXDB is an AI Context Store built on a Turn DAG + Blob CAS architecture. It runs as an external server that Orchestra connects to via HTTP API.

### Why CXDB

The Turn DAG is a natural fit for pipeline execution traces:

- **Turns are checkpoints.** Each node completion appends an immutable turn. The turn chain IS the execution history.
- **Contexts are sessions.** A CXDB context is a branch head pointer -- exactly what a pipeline session needs.
- **Forking is replay.** `orchestra replay --checkpoint <turn_id>` is a single O(1) fork operation in CXDB. No data copying.
- **Branching is parallelism.** Parallel fan-out forks the context into branches; fan-in merges results back.
- **Blob CAS is artifact storage.** Prompts, responses, and status payloads are stored once and deduplicated by content hash (BLAKE3).
- **Type registry enables structured inspection.** Orchestra registers typed turn schemas; the CXDB UI projects them into structured, renderable views.

### CXDB Deployment

CXDB is a pre-deployed external dependency, like a database server. Orchestra does not manage its lifecycle.

- **Development**: Run CXDB via Docker: `docker run -p 9009:9009 -p 9010:9010 cxdb/cxdb:latest`
- **Configuration**: `orchestra.yaml` specifies the CXDB endpoint: `cxdb.url: http://localhost:9010`
- **Connectivity check**: `orchestra doctor` verifies CXDB is reachable and the type registry is current
- **No CXDB fallback**: Orchestra requires CXDB. If unavailable, `orchestra run` fails with a clear error.

### Turn Type Registry

Orchestra registers a type bundle with CXDB's type registry. This enables typed JSON projections and custom UI renderers.

| Type ID | Description | Key Payload Fields |
|---------|-------------|-------------------|
| `dev.orchestra.PipelineLifecycle` | Pipeline start/complete/fail events | pipeline_name, goal, status, duration, error |
| `dev.orchestra.NodeExecution` | Node start/complete/fail/retry events | node_id, handler_type, status, outcome, duration, total_token_usage, agent_turn_count |
| `dev.orchestra.AgentTurn` | Single turn of the agent loop within a codergen node | node_id, turn_number, model, provider, messages, tool_calls, files_written, token_usage, git_sha, commit_message, agent_state_ref |
| `dev.orchestra.Checkpoint` | Full checkpoint state (for resume) | current_node, completed_nodes, context_snapshot, retry_counters, workspace_snapshot, agent_turn_number |
| `dev.orchestra.HumanInteraction` | Human gate and interactive mode events | question, answer, selected_option, mode |
| `dev.orchestra.ParallelExecution` | Parallel fan-out/fan-in events | branch_count, branch_id, join_policy, success_count, failure_count |
| `dev.orchestra.WorkspaceSnapshot` | Git SHA mapping at checkpoint | repo_snapshots: [{repo_name, git_sha, branch}] |

### AgentTurn CXDB Type

The `dev.orchestra.AgentTurn` type captures each turn of the agent loop within a codergen node. This is the primary mechanism for correlating agent context with code changes at fine granularity.

```json
{
    "type_id": "dev.orchestra.AgentTurn",
    "type_version": 1,
    "data": {
        "node_id": "security_reviewer",
        "turn_number": 2,
        "model": "claude-sonnet-4-20250514",
        "provider": "anthropic",
        "messages": [
            {"role": "assistant", "content": "I'll add input validation to the registration endpoint..."},
            {"role": "tool", "name": "edit-file", "content": "..."}
        ],
        "tool_calls": [
            {"tool": "backend:read-file", "args": {"path": "app/controllers/registrations_controller.rb"}},
            {"tool": "backend:edit-file", "args": {"path": "app/controllers/registrations_controller.rb", "...": "..."}},
            {"tool": "backend:write-file", "args": {"path": "spec/requests/registrations_spec.rb", "...": "..."}}
        ],
        "files_written": [
            "app/controllers/registrations_controller.rb",
            "spec/requests/registrations_spec.rb"
        ],
        "token_usage": {"prompt_tokens": 4200, "completion_tokens": 1800},
        "git_sha": "e4f5a6b7",
        "commit_message": "Add email format and password strength validation to registration endpoint",
        "agent_state_ref": "langgraph_checkpoint_abc123"
    }
}
```

**Correlation chain.** Each AgentTurn contains both the agent's reasoning (messages, tool_calls) and the resulting code state (git_sha). Given any AgentTurn in CXDB, you can:
- See exactly what the agent did (messages + tool_calls)
- See exactly what files changed (files_written)
- Check out the exact code state (`git checkout {git_sha}`)
- Resume the agent from that point (agent_state_ref)

**Turn sequence within a node.** A codergen node produces a sequence of AgentTurn CXDB turns, one per agent loop iteration. Only turns with file writes produce git commits and populate `git_sha`. Read-only turns (e.g., the agent reads files to understand the codebase) still get AgentTurn records in CXDB but with `git_sha: null` and `files_written: []`.

### Python CXDB Client

Orchestra communicates with CXDB via its HTTP API (port 9010). A thin Python wrapper (`orchestra.storage.cxdb_client`) encapsulates the HTTP calls:

```python
class CxdbClient:
    """Thin wrapper over CXDB's HTTP API for Orchestra."""

    def __init__(self, base_url: str = "http://localhost:9010"):
        ...

    def create_context(self, base_turn_id: str = "0") -> Context:
        """Create a new CXDB context (= new session)."""
        ...

    def fork_context(self, base_turn_id: str) -> Context:
        """Fork a context at a specific turn (= replay from checkpoint)."""
        ...

    def append_turn(self, context_id: str, type_id: str, type_version: int, data: dict) -> Turn:
        """Append a typed turn to a context (= save checkpoint/event)."""
        ...

    def get_turns(self, context_id: str, limit: int = 64) -> list[Turn]:
        """Get turns from a context (= read execution history)."""
        ...

    def list_contexts(self) -> list[Context]:
        """List all contexts (= list sessions)."""
        ...

    def publish_type_bundle(self, bundle_id: str, bundle: dict) -> None:
        """Publish Orchestra's type bundle to the registry."""
        ...

    def health_check(self) -> bool:
        """Check CXDB connectivity."""
        ...
```

### Execution Trace as Turn DAG

A linear pipeline execution with agent turns produces this turn chain:

```
PipelineStarted
  → NodeExecution(start)
  → Checkpoint
  → NodeExecution(plan)
    → AgentTurn(turn=0, reads files)
    → AgentTurn(turn=1, edits code, git_sha=abc)
    → AgentTurn(turn=2, adds tests, git_sha=def)
    → AgentTurn(turn=3, reviews, done)
  → Checkpoint (workspace_snapshot: {backend: def})
  → ...
  → PipelineCompleted
```

A parallel pipeline produces forks:

```
... → ParallelExecution(fan_out) → [fork] NodeExecution(branch_a) → AgentTurn... → ...
                                 → [fork] NodeExecution(branch_b) → AgentTurn... → ...
                                 → ParallelExecution(fan_in, merges branches) → ...
```

Replay forks the context at any checkpoint or agent turn:

```
Node boundary:  ... → Checkpoint(node_2) → NodeExecution(node_3) → ...
Replay:         fork(Checkpoint(node_2)) → NodeExecution(node_3') → ...  (new context)

Agent turn:     ... → AgentTurn(node_3, turn=1, sha=abc) → AgentTurn(turn=2, sha=def) → ...
Replay:         fork(AgentTurn(turn=1, sha=abc)) → AgentTurn(turn=2', sha=ghi) → ...  (new context, code at abc)
```

## Human Interaction

Orchestra supports two patterns for human-in-the-loop interaction.

### Interviewer Pattern (for `wait.human` Nodes)

Follows the attractor spec (Section 6) directly. When the engine reaches a `wait.human` node (shape=hexagon), it derives choices from outgoing edge labels and presents them to a human via the Interviewer interface.

**Interviewer implementations:**

| Implementation | Use Case |
|----------------|----------|
| `ConsoleInterviewer` | CLI: reads from stdin, displays formatted prompts with option keys |
| `CallbackInterviewer` | Integration: delegates to a provided function (web UI, Slack, API) |
| `QueueInterviewer` | Testing: reads from a pre-filled answer queue for deterministic replay |
| `AutoApproveInterviewer` | CI/CD: always selects YES / first option for automation |
| `RecordingInterviewer` | Audit: wraps another interviewer and records all Q&A pairs |

### Chat-Style Interactive Mode (for Codergen Nodes)

An Orchestra extension for codergen nodes with `agent.mode="interactive"`. The agent streams output and the human can respond in a multi-turn conversation within that node:

- The agent and human exchange messages until the human signals completion (`/done`, `/approve`, `/reject`)
- Each human turn is a checkpoint boundary, enabling resume from any point in the conversation
- The CLI implements this via stdin/stdout; the interface is abstract to support future web UI

This is distinct from the Interviewer pattern: the Interviewer is for structured decisions (approve/reject, select an option), while interactive mode is for open-ended collaboration within a task.

## Implementation Scope

### Components

1. **DOT parser** -- Parse attractor's DOT subset into an in-memory graph model
2. **AST transforms** -- Variable expansion, model stylesheet application, custom transforms
3. **Graph validation** -- Lint rules with diagnostic model (error/warning/info)
4. **Pipeline execution engine** -- Core traversal loop per attractor Section 3
5. **Handler registry** -- Shape-to-handler mapping with custom handler support
6. **Node handlers** -- start, exit, codergen, wait.human, conditional, parallel, fan_in, tool, manager_loop
7. **Context and Outcome model** -- Key-value Context, structured Outcome, context fidelity
8. **Checkpoint system** -- CXDB turns per node, extended with workspace snapshots
9. **Edge selection** -- 5-step deterministic algorithm
10. **Goal gate enforcement** -- Check at exit, reroute to retry targets
11. **Retry system** -- Per-node retry policies with backoff
12. **Event system** -- Typed events for all lifecycle phases
13. **Condition expression evaluator** -- Parse and evaluate edge conditions
14. **Agent configuration layer** -- Prompt composition, model/provider resolution, tool configuration
15. **Prompt composition engine** -- Role + persona + personality + task from YAML files with Jinja2
16. **File discovery system** -- Pipeline-relative > project config > `~/.orchestra/`
17. **Model/provider resolution** -- Alias resolution + stylesheet application
18. **Agent-level tool registry** -- Decorator-based registration, repo-scoped tools, write tracking
19. **Write tracker** -- Tracks file modifications made by tools within each agent turn
20. **CodergenBackend interface** -- Pluggable LLM execution with `on_turn` callback for per-turn visibility
21. **LangGraphBackend** -- Primary backend using LangGraph ReAct agent with turn-level streaming and write tracking
22. **DirectLLMBackend** -- Single API call backend for analysis nodes
23. **CLIAgentBackend** -- CLI agent subprocess wrapper (node-level commit fallback)
24. **Workspace management** -- Multi-repo workspace, repo-qualified tools
25. **Git integration** -- Session branches, worktree-per-agent, per-turn commits with LLM messages and agent metadata, remote clone/fetch/push
26. **Commit message generation** -- LLM call (cheap tier) to generate conventional commit messages from diffs
27. **Workspace snapshots** -- Per-turn git SHA in AgentTurn CXDB turns + per-node HEAD SHA in Checkpoint turns
28. **CXDB client** -- Python HTTP wrapper for CXDB API (contexts, turns, type registry)
29. **CXDB type bundle** -- Turn type definitions for pipeline lifecycle, node execution, agent turns, checkpoints, human interaction, parallel execution, workspace snapshots
28. **Session management** -- Session lifecycle via CXDB contexts
29. **Interviewer system** -- Console, Callback, Queue, AutoApprove, Recording implementations
30. **CLI interface** -- Typer-based: run, compile, status, resume, replay, attach, cleanup, doctor
31. **Adversarial PR review pipeline** -- End-to-end validation pipeline

### Success Criteria

**Pipeline Definition and Parsing:**
- DOT files parse correctly per attractor's supported subset (digraph, graph/node/edge attributes, chained edges, subgraphs, comments)
- Orchestra-specific attributes (`agent`, `agent.role`, etc.) are recognized on codergen nodes
- `orchestra compile pipeline.dot` validates the graph and reports diagnostics without executing
- Invalid DOT or graph structure produces clear, actionable error messages

**Execution Engine:**
- Engine traverses the graph from start to exit, dispatching to handlers per shape-to-handler mapping
- Edge selection follows the 5-step deterministic algorithm
- Goal gates prevent exit when unsatisfied; engine reroutes to retry targets
- Per-node retry policies with backoff work correctly
- Context fidelity modes control how much context carries between nodes
- Checkpoints appended as CXDB turns after every node; resume works from any turn
- Typed events appended as CXDB turns for all lifecycle phases
- CXDB context fork enables O(1) replay from any checkpoint turn

**Agent Configuration:**
- Prompt layers (role, persona, personality, task) load from YAML files and compose into a single system prompt
- File discovery resolves files via pipeline-relative > project config > `~/.orchestra/`
- Provider aliases resolve: `model: smart` + `provider: anthropic` -> `claude-opus-4-20250514`; literal model strings pass through
- Model stylesheet applies overrides by specificity (ID > class > universal)
- Agent-level tools resolve: backend base set + agent additions; repo-qualified names work

**CodergenBackend:**
- LangGraphBackend runs an agentic loop with tools and invokes `on_turn` callback after each turn
- LangGraphBackend's write tracker records file modifications made by tools in each turn
- DirectLLMBackend makes a single API call and returns the response (no `on_turn`)
- CLIAgentBackend spawns a CLI agent subprocess and captures output (falls back to node-level commit via `git status`)
- All backends conform to the `run(node, prompt, context, on_turn) -> str | Outcome` interface

**Workspace and Git:**
- Session branches created at start, named `{prefix}{pipeline}/{session-id}`
- Per-turn commits: each agent turn with file writes gets its own git commit with only the tracked files staged
- Commit messages generated by LLM (cheap tier) from the staged diff and agent intent
- Agent metadata recorded in git: commit author identifies agent/model, git trailers provide structured metadata (model, provider, node, session, turn number)
- Per-turn git SHAs recorded in `dev.orchestra.AgentTurn` CXDB turns — bidirectional correlation between agent context and code state
- Worktrees provisioned for parallel codergen agents with write access to the same repo
- Worktrees merged at fan-in; conflicts surfaced to downstream agent or human
- Resume at node boundary restores pipeline state + git HEAD per repo
- Resume at agent turn restores pipeline state + git to turn's SHA + LangGraph agent state
- Repos with `remote` configured are cloned/fetched at session start
- Session branches pushed to remote per `push` policy (`on_completion`, `on_checkpoint`, `never`)
- Push failures are non-fatal (warnings, not pipeline errors)
- Ephemeral environments work: clone → run → push → destroy → re-clone → resume from CXDB

**Human Interaction:**
- Interviewer pattern works for `wait.human` nodes: presents choices, routes on selection
- AutoApproveInterviewer works for automated testing
- Chat-style interactive mode works for codergen nodes with `agent.mode="interactive"`
- Each human turn in interactive mode is a checkpoint boundary

**CXDB Storage:**
- CXDB client connects to the CXDB server and handles all persistence
- Sessions are CXDB contexts; checkpoints, agent turns, and events are typed turns
- `dev.orchestra.AgentTurn` captures each agent loop iteration with messages, tool calls, files written, git SHA, commit message, and model metadata
- Artifacts (prompts, responses) stored in turn payloads with blob-level deduplication
- Type bundle registered with CXDB type registry; all turn types project to typed JSON
- CXDB UI renders pipeline execution traces with custom renderers per turn type (AgentTurn renderer shows reasoning + diff link)
- `orchestra doctor` validates CXDB connectivity and type registry state

**End-to-End:**
- Adversarial PR review pipeline runs end-to-end: parallel reviewers fan-out, critic loops, synthesizer produces final review in interactive mode
- Pipeline can be resumed from any checkpoint (node boundary) or any agent turn (within a node)
- Pipeline can be replayed from any checkpoint or agent turn via CXDB context fork
- Given any CXDB AgentTurn, can check out the exact code state via git SHA and see the agent's full reasoning
- Given any git commit on a session branch, can trace back to the CXDB session/node/turn via git trailers
- Session status, token usage, and timing queryable via CXDB context/turn APIs

### Testing Strategy

- **Simulation mode**: Attractor's codergen handler supports a backend=None simulation mode that returns `[Simulated] Response for stage: {node_id}`. This enables testing the full pipeline engine without LLM calls.
- **CXDB in tests**: Automated tests run against a real CXDB instance (Docker container started in CI). The CXDB HTTP API is used for verification (read back turns, check context state). Tests create fresh contexts per test case.
- **QueueInterviewer**: Pre-filled answer queues enable deterministic testing of human-in-the-loop pipelines.
- **Prompt snapshot tests**: Verify that composed prompts match expected output for given agent configurations.
- **Graph validation tests**: Verify that lint rules catch invalid graphs and produce correct diagnostics.
- **Real LLM integration tests**: Gated behind `ORCHESTRA_REAL_LLM=1` env var. Use cheap models (Haiku-tier) to validate the full flow.

## Key Risks

1. **DOT parser complexity.** The attractor spec defines a specific DOT subset (Section 2.2) with typed attributes, duration values, and constraints beyond standard Graphviz. Implementing a correct parser for this subset requires care. Mitigation: use an existing DOT parser library and add validation on top; the attractor spec's BNF grammar is the reference.

2. **Custom execution engine.** Building the pipeline engine from the attractor spec is significant work, though the spec is detailed enough to build from (Section 3 pseudocode is nearly implementable as-is). Mitigation: the engine is intentionally simple -- single-threaded traversal, no concurrency in the outer loop. Start with the linear pipeline case, add parallel/conditional/retry incrementally.

3. **CodergenBackend abstraction leaks.** Different backends have different capabilities: LangGraphBackend supports multi-turn tool use, DirectLLMBackend does not. A pipeline that works with one backend may fail with another. Mitigation: document backend capabilities clearly; `orchestra compile` can warn about backend/node compatibility.

4. **Context fidelity implementation.** The `full` fidelity mode requires LLM session reuse across nodes, which interacts with checkpoint/resume (in-memory sessions can't be serialized). The attractor spec addresses this (Section 5.3: degrade to `summary:high` on first resumed node), but the implementation is non-trivial. Mitigation: start with `compact` as default; add `full` fidelity incrementally.

5. **Git integration complexity.** Multi-repo workspace snapshots + worktree-per-agent + auto-commits + checkpoint linking has many edge cases (conflicts, dirty state, partial failures across repos). Mitigation: start with single-repo, single-branch; add worktree-per-agent for parallel writes incrementally.

6. **Multi-repo coordination atomicity.** Agents writing to multiple repos simultaneously creates atomicity challenges -- what if a commit to repo_a succeeds but repo_b fails? Mitigation: treat workspace snapshots as best-effort (record whatever succeeded); add transactional semantics later if needed.

7. **Model stylesheet + alias interaction.** The combination of attractor's CSS-like stylesheet with Orchestra's alias system creates a 2D resolution space (specificity x alias resolution). The precedence rules must be clear and well-tested. Mitigation: define resolution order explicitly (as done above); snapshot test the resolution logic.

8. **Scope.** This is a large system. Mitigation: the attractor spec is self-contained and well-specified -- implement it layer by layer (parser > validation > engine > handlers). Orchestra's extensions (workspace, git, prompt composition) layer cleanly on top and can be added incrementally.

9. **CXDB dependency.** Orchestra requires a running CXDB instance. This adds an infrastructure dependency: developers must have CXDB running locally (Docker) and CI must provision it. Mitigation: CXDB is a single Docker container with no external dependencies. `orchestra doctor` provides clear diagnostics. The CXDB HTTP API is simple and well-documented.

10. **CXDB Python client.** No official Python client exists for CXDB. Orchestra must build a thin HTTP wrapper. Mitigation: the HTTP API is RESTful JSON -- the wrapper is straightforward (~200 lines). The API surface Orchestra needs is small (create/fork context, append/get turns, publish type bundle, health check).

### Open Questions (Deferred)

- **Coding agent loop spec implementation**: The attractor companion spec for a full coding agent loop (provider-aligned toolsets, steering, subagents) could eventually replace the LangGraphBackend as the primary CodergenBackend implementation. Deferred until the pipeline engine is stable.
- **Unified LLM client spec implementation**: The attractor companion spec for a provider-agnostic LLM client could eventually replace LangChain as the LLM interface used by backends. Deferred.
- **HTTP server mode**: Attractor Section 9.5 defines an HTTP server with SSE event streaming and web-based human interaction. Deferred to post-CLI.
- **Token budgets / cost limits**: The event system and session metadata track token usage per node. Formal budgets and cost guardrails are deferred to post-MVP.
- **Worktree merge conflict resolution UX**: When parallel agents edit the same file, the merge at fan-in may conflict. The current design surfaces conflicts but the exact UX is deferred.
- **Team/shared use**: Shared pipeline definitions, tool registries, and multi-user coordination. The file discovery conventions, HTTP server mode, and remote git operations are designed to support this when needed.
