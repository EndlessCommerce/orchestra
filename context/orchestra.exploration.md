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
| Git integration | Session branches, worktree-per-agent for parallel writes, auto-commit |
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
   Interfaces
   - CLI (run, compile, status, attach, replay, cleanup)
   - Event stream consumers (TUI, web UI, logging)
   - HTTP server (future, per attractor Section 9.5)
```

### Layer Responsibilities

**DOT Parser + Transforms + Validation.** Reads `.dot` pipeline files, applies AST transforms (variable expansion, model stylesheet, custom transforms), and validates the graph using the lint rule system. This is the attractor spec's parse-validate-initialize pipeline (Section 3.1) with no modifications.

**Pipeline Execution Engine.** The core traversal loop from attractor Section 3.2. Executes handlers, records outcomes, selects edges, saves checkpoints, and emits events. Orchestra implements this engine directly -- it is not LangGraph. The engine is single-threaded; parallelism exists only within the `parallel` handler.

**Agent Config (Orchestra Layer).** For codergen nodes, Orchestra resolves agent configuration before calling the backend. This includes composing prompts from layered YAML files, resolving model/provider through aliases and stylesheets, and assembling the tool set. The output is a fully resolved prompt + model + tools, which is passed to the `CodergenBackend`.

**CodergenBackend.** The pluggable interface for LLM execution. The pipeline engine calls `backend.run(node, prompt, context)` and receives a `String` or `Outcome` back. What happens inside is opaque. The primary implementation uses LangGraph's ReAct agent for tool-using agentic execution. This is the ONLY place LangGraph/LangChain appear in the stack.

**Workspace Layer.** Orchestra's software development extension. Listens to pipeline events and manages git state: creates session branches at pipeline start, provisions worktrees for parallel agents, records workspace snapshots at each checkpoint, and merges worktrees at fan-in. This layer sits above the pipeline engine and does not affect its execution logic.

**Interfaces.** CLI commands, event stream consumers (TUI, web UI), and an HTTP server (future). The pipeline engine is headless; presentation is separate (attractor Section 9.5-9.6).

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
    def run(self, node: Node, prompt: str, context: Context) -> str | Outcome:
        """Execute an LLM task for the given node.

        Args:
            node: The parsed Node with all its attributes (including agent config).
            prompt: The fully composed prompt (after Orchestra's prompt composition).
            context: The pipeline's shared key-value context.

        Returns:
            A string response (converted to SUCCESS Outcome by the handler),
            or an Outcome with explicit status, context_updates, etc.
        """
        ...
```

The pipeline engine calls `backend.run()` and does not know or care what happens inside. This is the ONLY integration point between the pipeline orchestration layer and LLM execution.

### LangGraphBackend (Primary Implementation)

Uses LangGraph's ReAct agent for within-node agentic execution:

```python
class LangGraphBackend(CodergenBackend):
    """Uses LangGraph's create_react_agent for tool-using LLM execution.

    This backend gives the LLM access to tools (read_file, edit_file,
    shell, grep, glob, plus any agent-configured additions) and runs
    an agentic loop: LLM -> tool calls -> LLM -> ... until done.
    """

    def run(self, node: Node, prompt: str, context: Context) -> str | Outcome:
        # Resolve model/provider from agent config + stylesheet + aliases
        model = resolve_model(node)
        tools = resolve_tools(node)

        # Create LangGraph ReAct agent
        agent = create_react_agent(model, tools)

        # Run the agent with the composed prompt
        result = agent.invoke({"messages": [("user", prompt)]})

        # Extract response and build Outcome
        return build_outcome(result)
```

This is the right level for LangGraph -- it manages the inner agentic loop (tool use, multi-turn LLM interaction) within a single pipeline node. LangGraph's checkpointing, streaming, and tool infrastructure add real value here.

### CLIAgentBackend

Wraps CLI coding agents (Claude Code, Codex, Gemini CLI) as subprocesses:

```python
class CLIAgentBackend(CodergenBackend):
    """Spawns a CLI agent as a subprocess.

    Pragmatic shortcut: get a full agentic loop for free.
    Tradeoff: no programmatic control over the inner loop (no steering,
    no mid-task observation, no event stream from inside the agent).
    """

    def run(self, node: Node, prompt: str, context: Context) -> str | Outcome:
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
    """

    def run(self, node: Node, prompt: str, context: Context) -> str | Outcome:
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

### Workspace Snapshots

Each attractor checkpoint is extended with a workspace snapshot mapping repos to git SHAs:

```json
{
    "checkpoint_id": "cp_abc123",
    "session_id": "sess_def456",
    "timestamp": "2025-02-11T10:30:00Z",
    "current_node": "critic",
    "completed_nodes": ["start", "fan_out", "security_reviewer", "architecture_reviewer", "fan_in"],
    "context": { "...": "..." },
    "workspace_snapshot": {
        "backend": {
            "git_sha": "abc123def",
            "branch": "orchestra/pr-review/a1b2c3"
        },
        "frontend": {
            "git_sha": "111aaabbb",
            "branch": "orchestra/pr-review/a1b2c3"
        }
    }
}
```

Workspace snapshots are only recorded when a repo's git state has actually changed since the last checkpoint -- read-only nodes incur no snapshot overhead.

Resuming from a checkpoint restores both pipeline state (from the attractor checkpoint) AND git state (from the workspace snapshot) by checking out each repo to its corresponding SHA.

## Session Management

A session is a named pipeline run with a checkpoint chain and workspace snapshot chain.

### Session Lifecycle

1. **Start**: `orchestra run pipeline.dot` creates a session (ID, status, timestamps), creates session branches in workspace repos, initializes the pipeline engine
2. **Execute**: The engine traverses the graph, saving checkpoints and workspace snapshots after each node
3. **Pause**: The engine can be interrupted (Ctrl-C or API signal); state is saved in the last checkpoint
4. **Resume**: `orchestra resume <session_id>` loads the last checkpoint, restores git state, and continues from the next node
5. **Replay**: `orchestra replay <session_id> --checkpoint <id>` restores a specific checkpoint and re-executes from that point
6. **Complete**: Pipeline reaches the exit node; session status is updated; branches are left for user to merge/delete

### Session Storage

Session metadata is stored in a local SQLite database (separate from checkpoints):

- Session ID, pipeline name, status (running/paused/completed/failed), timestamps
- Token usage and cost tracking per node
- Tool invocation counts and timing

Checkpoints are stored as JSON files in the run directory (attractor Section 5.6). This dual storage means checkpoint resume is filesystem-based (portable), while session queries are database-backed (fast).

### CLI Commands

| Command | Description |
|---------|-------------|
| `orchestra run <pipeline.dot>` | Compile and execute a pipeline |
| `orchestra compile <pipeline.dot>` | Validate, resolve references, print graph structure (dry-run) |
| `orchestra status` | List running/completed sessions with checkpoint counts and token usage |
| `orchestra resume <session_id>` | Resume a paused or crashed session from last checkpoint |
| `orchestra replay <session_id> --checkpoint <id>` | Restore a specific checkpoint and re-execute |
| `orchestra attach <session_id>` | Connect to a running session's event stream (or interactive agent) |
| `orchestra cleanup` | Remove stale session branches, worktrees, and old run directories |

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
8. **Checkpoint system** -- JSON checkpoint per node, extended with workspace snapshots
9. **Edge selection** -- 5-step deterministic algorithm
10. **Goal gate enforcement** -- Check at exit, reroute to retry targets
11. **Retry system** -- Per-node retry policies with backoff
12. **Event system** -- Typed events for all lifecycle phases
13. **Condition expression evaluator** -- Parse and evaluate edge conditions
14. **Agent configuration layer** -- Prompt composition, model/provider resolution, tool configuration
15. **Prompt composition engine** -- Role + persona + personality + task from YAML files with Jinja2
16. **File discovery system** -- Pipeline-relative > project config > `~/.orchestra/`
17. **Model/provider resolution** -- Alias resolution + stylesheet application
18. **Agent-level tool registry** -- Decorator-based registration, repo-scoped tools
19. **CodergenBackend interface** -- Pluggable LLM execution
20. **LangGraphBackend** -- Primary backend using LangGraph ReAct agent
21. **DirectLLMBackend** -- Single API call backend for analysis nodes
22. **CLIAgentBackend** -- CLI agent subprocess wrapper
23. **Workspace management** -- Multi-repo workspace, repo-qualified tools
24. **Git integration** -- Session branches, worktree-per-agent, auto-commit
25. **Workspace snapshots** -- Checkpoint-to-git-SHA linking
26. **Session management** -- Session lifecycle, SQLite metadata store
27. **Interviewer system** -- Console, Callback, Queue, AutoApprove, Recording implementations
28. **CLI interface** -- Typer-based: run, compile, status, resume, replay, attach, cleanup
29. **Adversarial PR review pipeline** -- End-to-end validation pipeline

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
- Checkpoints are saved after every node; resume works from any checkpoint
- Typed events are emitted for all lifecycle phases

**Agent Configuration:**
- Prompt layers (role, persona, personality, task) load from YAML files and compose into a single system prompt
- File discovery resolves files via pipeline-relative > project config > `~/.orchestra/`
- Provider aliases resolve: `model: smart` + `provider: anthropic` -> `claude-opus-4-20250514`; literal model strings pass through
- Model stylesheet applies overrides by specificity (ID > class > universal)
- Agent-level tools resolve: backend base set + agent additions; repo-qualified names work

**CodergenBackend:**
- LangGraphBackend runs an agentic loop with tools (read, write, edit, shell, grep, glob)
- DirectLLMBackend makes a single API call and returns the response
- CLIAgentBackend spawns a CLI agent subprocess and captures output
- All backends conform to the `run(node, prompt, context) -> str | Outcome` interface

**Workspace and Git:**
- Session branches created at start, named `{prefix}{pipeline}/{session-id}`
- Worktrees provisioned for parallel codergen agents with write access to the same repo
- Worktrees merged at fan-in; conflicts surfaced to downstream agent or human
- Workspace snapshots recorded at each checkpoint (only when repo state changed)
- Resume restores both pipeline state and git state

**Human Interaction:**
- Interviewer pattern works for `wait.human` nodes: presents choices, routes on selection
- AutoApproveInterviewer works for automated testing
- Chat-style interactive mode works for codergen nodes with `agent.mode="interactive"`
- Each human turn in interactive mode is a checkpoint boundary

**End-to-End:**
- Adversarial PR review pipeline runs end-to-end: parallel reviewers fan-out, critic loops, synthesizer produces final review in interactive mode
- Pipeline can be resumed from any checkpoint
- Session status, token usage, and timing are tracked

### Testing Strategy

- **Simulation mode**: Attractor's codergen handler supports a backend=None simulation mode that returns `[Simulated] Response for stage: {node_id}`. This enables testing the full pipeline engine without LLM calls.
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

### Open Questions (Deferred)

- **Coding agent loop spec implementation**: The attractor companion spec for a full coding agent loop (provider-aligned toolsets, steering, subagents) could eventually replace the LangGraphBackend as the primary CodergenBackend implementation. Deferred until the pipeline engine is stable.
- **Unified LLM client spec implementation**: The attractor companion spec for a provider-agnostic LLM client could eventually replace LangChain as the LLM interface used by backends. Deferred.
- **HTTP server mode**: Attractor Section 9.5 defines an HTTP server with SSE event streaming and web-based human interaction. Deferred to post-CLI.
- **Token budgets / cost limits**: The event system and session metadata track token usage per node. Formal budgets and cost guardrails are deferred to post-MVP.
- **Worktree merge conflict resolution UX**: When parallel agents edit the same file, the merge at fan-in may conflict. The current design surfaces conflicts but the exact UX is deferred.
- **Team/shared use**: Shared pipeline definitions, tool registries, and remote execution. The file discovery conventions and HTTP server mode are designed to support this when needed.
