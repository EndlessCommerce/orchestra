# Stage 3: LLM Integration and Agent Configuration

## Overview

Replace simulation mode with real LLM execution. Implement the CodergenBackend interface with three backends (LangGraph, Direct LLM, CLI Agent), the provider/model resolution system (aliases + model stylesheet), layered prompt composition from YAML files, the file discovery system, and the agent-level tool registry. After this stage, Orchestra runs real AI-powered pipelines.

## What a Human Can Do After This Stage

1. Define agents with layered prompts (role + persona + personality + task) in YAML files
2. Configure providers with semantic model tiers (smart/worker/cheap) in `orchestra.yaml`
3. Use the model stylesheet in DOT files to assign models per-node by class or ID
4. Run a pipeline that makes real LLM calls and produces actual AI-generated output
5. Switch between backends (LangGraph for agentic tool use, DirectLLM for analysis, CLI for wrapping Claude Code/Codex)
6. Register custom tools and make them available to agents
7. Switch all agents between providers by changing one line in config

## Prerequisites

- Stage 2b complete (full execution engine with control flow and persistence)

## Scope

### Included

- **CodergenBackend Interface.** `run(node, prompt, context, on_turn=None) -> str | Outcome` protocol. This extends the attractor spec's `CodergenBackend` interface (Section 4.5) by adding an optional `on_turn` callback parameter. The pipeline engine calls this interface and passes an `on_turn` callback. Backends that support turn-level visibility invoke `on_turn` after each agent loop turn with an `AgentTurn` containing messages, tool calls, files written, token usage, and serialized agent state. Backends that don't support turn-level visibility (DirectLLM, CLI) ignore the callback. When a backend returns a bare `str`, the `CodergenHandler` wraps it in an `Outcome(status=SUCCESS, notes=response_text, context_updates={"last_response": response_text})`.
- **CodergenHandler Adapter Layer.** The existing `NodeHandler` protocol (`handle(node, context, graph) -> Outcome`) is preserved. `CodergenHandler` implements `NodeHandler` and wraps a `CodergenBackend`. It is responsible for: (1) composing the prompt via the prompt engine, (2) resolving the model via the resolution chain, (3) calling `backend.run(node, prompt, context, on_turn)`, (4) converting `str` results to `Outcome`, (5) writing `prompt.md` and `response.md` to the stage logs directory. The `SimulationCodergenHandler` is retained as `SimulationBackend` — a `CodergenBackend` implementation that returns simulated responses, usable for dry-runs and all existing tests.
- **Handler Registry Changes.** `default_registry()` registers `CodergenHandler(backend=SimulationBackend())` for shape `"box"` by default. When `orchestra.yaml` specifies a real backend, the CLI commands construct the appropriate backend and pass it to `CodergenHandler`. The `PipelineRunner` and `_execute_node()` method are unchanged — they continue to call `handler.handle(node, context, graph)`.
- **AgentTurn Data Model.** Dataclass emitted by backends after each turn: `turn_number`, `model`, `provider`, `messages`, `tool_calls`, `files_written`, `token_usage`, `agent_state`. The workspace layer (Stage 6) hooks into this for per-turn commits. A new CXDB turn type `dev.orchestra.AgentTurn` is registered for persisting agent turn data.
- **WriteTracker.** Tracks file modifications made by tools within each agent turn. Write tools (write-file, edit-file) call `write_tracker.record(path)` after every modification. `flush()` returns the tracked paths and resets for the next turn. The `@modifies_files` decorator auto-records paths for custom tools.
- **DirectLLMBackend.** Single LLM API call with no tool use. Suitable for analysis, review, and synthesis nodes. Uses LangChain chat model. Does not invoke `on_turn`.
- **LangGraphBackend.** LangGraph ReAct agent for within-node agentic execution with tools (read_file, edit_file, shell, grep, glob, plus agent-configured additions). Streams execution turn-by-turn, invokes `on_turn` after each turn with write-tracked files and agent state. This is the primary backend.
- **CLIAgentBackend.** Spawns CLI coding agents (Claude Code, Codex, Gemini CLI) as subprocesses. Passes prompt via stdin and context as JSON on a temp file (path provided via `--context-file` flag or `ORCHESTRA_CONTEXT_FILE` env var). Captures stdout as the response. Does not invoke `on_turn` — the workspace layer falls back to `git status` at node completion.
- **Backend Selection.** Configurable at global level in `orchestra.yaml`, per-pipeline, and (future) per-node.
- **Provider Configuration.** `orchestra.yaml` providers section: default provider, per-provider model maps with semantic tiers (smart/worker/cheap), provider-specific settings (max_tokens, api_base).
- **Provider Alias Resolution.** `llm_model: smart` + `llm_provider: anthropic` → `claude-opus-4-20250514`. Unknown aliases pass through as literal model strings.
- **Model Stylesheet Application.** Parse the CSS-like `model_stylesheet` graph attribute per attractor spec Section 8. Apply rules by specificity (ID > class > universal). Set `llm_model`, `llm_provider`, `reasoning_effort` on nodes that don't have explicit overrides. Implemented as a graph transform (applied after parsing, before validation).
- **Model Resolution Precedence.** Explicit node attribute > stylesheet rule (by specificity) > agent config model > graph-level default > provider default.
- **Prompt Composition Engine.** Four layers from YAML files: role (system prompt), persona (modifiers), personality (modifiers), task (Jinja2 template). Layers concatenated in order. Task layer uses Jinja2 for variable interpolation (`{{pr_diff}}`, etc.). Note: `$goal` expansion in DOT `prompt` attributes uses the existing variable expansion transform (simple string replacement). Jinja2 is used only in the task layer YAML files, which are a separate composition system. The two template syntaxes serve different scopes and do not overlap.
- **File Discovery.** Three-level resolution: pipeline-relative → project config paths → `~/.orchestra/`. Stops at first match.
- **Agent Configuration.** `agents` section in `orchestra.yaml`: per-agent role, persona, personality, task, tools. Node-level `agent` attribute references config by name. Inline agent attributes (`agent.role`, `agent.persona`, etc.) as alternatives.
- **Agent-Level Tool Registry.** Decorator-based registration (`@tool_registry.register()`). Flat tool names in Stage 3 (no repo-scoped naming — repo-scoped `backend:read-file` naming deferred to Stage 6 when workspace/repo concepts exist). Built-in tools: read-file, write-file, edit-file, search-code, shell. YAML shell command tool loading from `orchestra.yaml` tools section. Hybrid model: backend base set + agent additions + agent restrictions.
- **orchestra.yaml Configuration Loading.** Parse and validate the full `orchestra.yaml` structure: providers, agents, tools, backend selection.
- **LLM Error Handling.** LLM API errors (rate limits, network timeouts, auth failures) are caught by the backend and surfaced as `Outcome(status=FAIL, failure_reason=...)`. The existing node-level retry system (Stage 2a) handles retries at the pipeline level. Backends do NOT retry internally — this keeps retry policy centralized and configurable via DOT attributes.
- **New Dependencies.** Added to `pyproject.toml`: `langchain-core`, `langchain-anthropic`, `langchain-openai`, `langgraph`, `jinja2`.

### Excluded

- Human-in-the-loop and interactive mode (Stage 4)
- Parallel execution (Stage 5)
- Git integration — session branches, worktrees, workspace snapshots (Stage 6)
- Workspace tools that depend on git state (Stage 6)

## Automated End-to-End Tests

LLM calls are mocked in all automated tests. Use LangChain's `FakeListChatModel` or equivalent mocks. No API keys or network access required.

### CodergenBackend Tests

| Test | Description |
|------|-------------|
| DirectLLMBackend mock | Mock LLM returns expected response → backend returns it as string |
| DirectLLMBackend Outcome | Mock LLM returns structured JSON → backend parses into Outcome |
| DirectLLMBackend no on_turn | DirectLLMBackend does not invoke `on_turn` callback |
| LangGraphBackend mock | Mock LLM + mock tools → agent runs tool loop → returns result |
| LangGraphBackend tool use | Agent calls read_file tool → tool returns content → agent incorporates it |
| LangGraphBackend on_turn called | `on_turn` callback invoked after each agent loop turn |
| LangGraphBackend AgentTurn data | AgentTurn contains correct turn_number, messages, tool_calls, token_usage |
| LangGraphBackend files_written | Agent calls write_file → `AgentTurn.files_written` contains the path |
| LangGraphBackend agent_state | AgentTurn contains serialized agent state for resume |
| CLIAgentBackend mock | Mock subprocess returns stdout → backend captures it |
| CLIAgentBackend no on_turn | CLIAgentBackend does not invoke `on_turn` callback |
| Backend interface contract | All three backends conform to `run(node, prompt, context, on_turn) -> str | Outcome` |

### WriteTracker Tests

| Test | Description |
|------|-------------|
| Record and flush | `record("a.py")` then `flush()` → returns `["a.py"]` |
| Flush resets | After `flush()`, second `flush()` returns `[]` |
| Deduplication | `record("a.py")` twice → `flush()` returns `["a.py"]` once |
| Multiple files | Record multiple paths → all returned in order |
| Write tool integration | Built-in write-file tool calls `write_tracker.record()` on modification |
| Edit tool integration | Built-in edit-file tool calls `write_tracker.record()` on modification |
| modifies_files decorator | Custom tool with `@modifies_files` auto-records returned paths |

### Provider/Model Resolution Tests

| Test | Description |
|------|-------------|
| Alias resolution | `smart` + `anthropic` → `claude-opus-4-20250514` |
| Literal passthrough | `gpt-4o` → `gpt-4o` (not an alias, passes through) |
| Provider default | No provider specified → uses `providers.default` |
| Per-agent provider override | Agent specifies provider → overrides default |
| Provider-specific config | `max_tokens`, `api_base` passed to model constructor |

### Model Stylesheet Tests

| Test | Description |
|------|-------------|
| Parse stylesheet | `* { llm_model: smart; }` parses into rule with universal selector |
| Universal selector | `*` rule applies to all nodes |
| Class selector | `.code { llm_model: worker; }` applies to nodes with `class="code"` |
| ID selector | `#review { llm_model: gpt-4o; }` applies to node with ID `review` |
| Specificity order | ID > class > universal — higher specificity wins |
| Explicit override | Node attribute `llm_model="custom"` overrides stylesheet |
| Multiple classes | Node with `class="code,critical"` matches both `.code` and `.critical` |
| Full resolution chain | Explicit > stylesheet (by specificity) > agent config > graph default > provider default |

### Prompt Composition Tests

| Test | Description |
|------|-------------|
| Single layer | Role-only prompt composes correctly |
| All four layers | Role + persona + personality + task concatenated in order |
| Jinja2 interpolation | Task template with `{{variable}}` interpolated from context |
| Missing layer | Agent without persona → role + personality + task (skip missing) |
| Prompt snapshot tests | Composed prompts for known agent configs match expected snapshots |

### File Discovery Tests

| Test | Description |
|------|-------------|
| Pipeline-relative | Prompt file found relative to `.dot` file directory |
| Project config path | Prompt file found via `orchestra.yaml` configured path |
| Global fallback | Prompt file found in `~/.orchestra/` when not in other locations |
| Precedence | Pipeline-relative found → project config not checked |
| Not found | Clear error when prompt file not found at any level |

### Tool Registry Tests

| Test | Description |
|------|-------------|
| Register builtin tool | `@register("read-file")` → tool available as `read-file` |
| Register custom tool | `@register("run-migration")` → tool registered and callable |
| YAML shell tool | Tool defined in `orchestra.yaml` tools section → registered and callable |
| Agent tool resolution | Agent config `tools: [run-tests, read-file]` → correct tools assembled |
| Agent tool restriction | Agent config `tools: [read-file]` → only `read-file` available, not `write-file` |
| Unknown tool error | Agent references non-existent tool name → clear error at config validation |

### CodergenHandler Adapter Tests

| Test | Description |
|------|-------------|
| Handler wraps backend | CodergenHandler(backend=mock) calls backend.run() and returns Outcome |
| String to Outcome conversion | Backend returns str → handler wraps in Outcome(status=SUCCESS, notes=str) |
| Backend returns Outcome | Backend returns Outcome directly → handler passes it through |
| Prompt composition integration | Handler composes prompt from agent config before passing to backend |
| Model resolution integration | Handler resolves model from resolution chain and passes to backend |
| Writes prompt.md and response.md | Handler writes prompt and response files to stage logs directory |
| SimulationBackend compatibility | SimulationBackend returns same results as old SimulationCodergenHandler |
| Existing tests unchanged | All 137 existing tests pass with CodergenHandler(backend=SimulationBackend()) |

### End-to-End Integration Tests (Mocked LLM)

| Test | Description |
|------|-------------|
| Pipeline with agent config | Pipeline references agent by name → prompt composed from YAML layers → passed to mocked backend |
| Pipeline with stylesheet | Stylesheet assigns models → correct model resolved for each node → mocked backend called with correct model |
| Pipeline with inline agent | Node with `agent.role="engineer"` → role loaded → prompt composed correctly |
| Pipeline with tools | Agent has tools configured → LangGraphBackend receives correct tool set |
| Config validation | Invalid `orchestra.yaml` → clear, actionable errors |
| Backend selection | `orchestra.yaml` sets `backend: direct` → DirectLLMBackend used |

## Investigation

- [ ] Verify LangGraph latest stable API for ReAct agent, tool binding, and state serialization
    - [ ] Check `langgraph` PyPI for latest version and confirm `create_react_agent` API
    - [ ] Confirm how LangChain `StructuredTool` wrapping works for custom tools
    - [ ] Verify `FakeListChatModel` or equivalent mock is available for testing
    - [ ] Pin versions in pyproject.toml based on findings
    - [ ] Mark TODO complete and commit the changes to git

## Plan

### Phase 1: Foundation — Dependencies, Data Models, Config Schema

- [x] Add new dependencies to `pyproject.toml`
    - [x] Add `langchain-core`, `langchain-anthropic`, `langchain-openai`, `langgraph`, `jinja2`
    - [x] Use compatible release specifiers (`~=`) pinned to latest stable minor versions
    - [x] Run `pip install -e ".[dev]"` to verify installation
    - [x] Mark TODO complete and commit the changes to git

- [x] Define `AgentTurn` data model and `CodergenBackend` protocol
    - [x] Create `src/orchestra/backends/__init__.py`
    - [x] Create `src/orchestra/backends/protocol.py` — define `CodergenBackend` protocol: `run(node, prompt, context, on_turn=None) -> str | Outcome`
    - [x] Create `src/orchestra/models/agent_turn.py` — define `AgentTurn` dataclass with fields: `turn_number`, `model`, `provider`, `messages`, `tool_calls`, `files_written`, `token_usage`, `agent_state`
    - [x] Write tests in `tests/test_agent_turn.py` for AgentTurn construction and serialization
    - [x] Mark TODO complete and commit the changes to git

- [x] Extend `orchestra.yaml` config schema for providers, agents, tools, backend selection
    - [x] Update `src/orchestra/config/settings.py` with new Pydantic models:
        - `ProviderConfig` — models dict (smart/worker/cheap mapping), settings (max_tokens, api_base)
        - `ProvidersConfig` — default provider name, per-provider configs (anthropic, openai, openrouter)
        - `AgentConfig` — role, persona, personality, task (file paths), tools list, provider override, model override
        - `ToolConfig` — name, command (for YAML shell tools), description
        - `OrchestraConfig` — extend with `providers`, `agents`, `tools`, `backend` fields
    - [x] Write tests in `tests/test_config.py` for loading valid configs, missing optional fields, invalid configs producing clear errors
    - [x] Verify existing config tests still pass (only `cxdb` section was previously tested)
    - [x] Mark TODO complete and commit the changes to git

### Phase 2: WriteTracker

- [x] Implement WriteTracker and `@modifies_files` decorator
    - [x] Create `src/orchestra/backends/write_tracker.py`:
        - `WriteTracker` class with `record(path)`, `flush() -> list[str]`
        - Deduplication via ordered set (preserves first-seen order)
        - `@modifies_files` decorator that auto-records returned paths
    - [x] Write tests in `tests/test_write_tracker.py`:
        - Record and flush returns paths
        - Flush resets state
        - Deduplication — same path recorded twice returns once
        - Multiple files returned in order
        - `@modifies_files` decorator auto-records returned paths
    - [x] Mark TODO complete and commit the changes to git

### Phase 3: Tool Registry

- [x] Implement the agent-level tool registry
    - [x] Create `src/orchestra/tools/__init__.py`
    - [x] Create `src/orchestra/tools/registry.py`:
        - `ToolRegistry` class with `register(name, fn, description)` and `@register()` decorator
        - `get(name) -> Tool` and `get_tools(names: list[str]) -> list[Tool]`
        - `Tool` dataclass: `name`, `description`, `fn`, `schema` (for LangChain compatibility)
    - [x] Create `src/orchestra/tools/builtins.py`:
        - Built-in tools: `read-file`, `write-file`, `edit-file`, `search-code`, `shell`
        - Each tool is a function that takes appropriate args and returns a string result
        - `write-file` and `edit-file` accept an optional `WriteTracker` and call `record()` on modification
    - [x] Create `src/orchestra/tools/yaml_tools.py`:
        - Load tool definitions from `orchestra.yaml` `tools` section
        - Shell command tools: name + command template → registered tool that runs subprocess
    - [x] Write tests in `tests/test_tool_registry.py`:
        - Register builtin tool via decorator → available by name
        - Register custom tool → registered and callable
        - YAML shell tool → registered and callable (mock subprocess)
        - Agent tool resolution — `tools: [read-file, search-code]` → correct tools assembled
        - Agent tool restriction — only listed tools available
        - Unknown tool name → clear error
    - [x] Mark TODO complete and commit the changes to git

### Phase 4: File Discovery

- [x] Implement the 3-level file discovery system
    - [x] Create `src/orchestra/config/file_discovery.py`:
        - `discover_file(filename, pipeline_dir, config_paths, global_dir) -> Path`
        - Three-level resolution: pipeline-relative → project config paths → `~/.orchestra/`
        - Stops at first match
        - Raises clear error with all searched locations when not found
    - [x] Write tests in `tests/test_file_discovery.py`:
        - Pipeline-relative: file found relative to `.dot` file directory
        - Project config path: file found via configured path
        - Global fallback: file found in `~/.orchestra/`
        - Precedence: pipeline-relative found → project config not checked
        - Not found: clear error listing all searched locations
    - [x] Mark TODO complete and commit the changes to git

### Phase 5: Prompt Composition Engine

- [x] Implement the 4-layer prompt composition engine
    - [x] Create `src/orchestra/prompts/__init__.py`
    - [x] Create `src/orchestra/prompts/engine.py`:
        - `compose_prompt(agent_config, context, pipeline_dir, config) -> str`
        - Load each layer (role, persona, personality, task) from YAML files via file discovery
        - YAML schema: `content` key (required), optional `description`, `version`
        - Concatenate layers in order: role + persona + personality + task
        - Skip missing/unconfigured layers
        - Task layer: render `content` as Jinja2 template with context variables
    - [x] Create `src/orchestra/prompts/loader.py`:
        - `load_prompt_layer(filepath) -> str` — parse YAML, extract `content` key
        - Validate YAML structure
    - [x] Write tests in `tests/test_prompt_composition.py`:
        - Single layer: role-only composes correctly
        - All four layers: concatenated in order with separators
        - Jinja2 interpolation: `{{variable}}` in task template interpolated from context
        - Missing layer: agent without persona → role + personality + task (skip missing)
        - Prompt snapshot tests: known agent configs match expected output
    - [x] Mark TODO complete and commit the changes to git

### Phase 6: Provider and Model Resolution

- [x] Implement provider alias resolution
    - [x] Create `src/orchestra/config/providers.py`:
        - `resolve_model(alias, provider_name, providers_config) -> str`
        - Map semantic tiers (smart/worker/cheap) to provider-specific model strings
        - Unknown aliases pass through as literal strings
        - Default provider fallback when none specified
    - [x] Write tests in `tests/test_provider_resolution.py`:
        - Alias resolution: `smart` + `anthropic` → `claude-opus-4-20250514`
        - Literal passthrough: `gpt-4o` → `gpt-4o`
        - Provider default: no provider specified → uses `providers.default`
        - Per-agent provider override
        - Provider-specific config (max_tokens, api_base) passed through
    - [x] Mark TODO complete and commit the changes to git

- [x] Implement model stylesheet parsing and application (graph transform)
    - [x] Create `src/orchestra/transforms/model_stylesheet.py`:
        - `apply_model_stylesheet(graph) -> PipelineGraph` — graph transform
        - Parse CSS-like `model_stylesheet` graph attribute using regex
        - Selectors: `*` (universal), `.class` (class), `#id` (ID)
        - Properties: `llm_model`, `llm_provider`, `reasoning_effort`
        - Apply rules by specificity: ID > class > universal
        - Only set properties on nodes that don't have explicit overrides
    - [x] Write tests in `tests/test_model_stylesheet.py`:
        - Parse stylesheet: `* { llm_model: smart; }` parses correctly
        - Universal selector applies to all nodes
        - Class selector: `.code { llm_model: worker; }` applies to matching nodes
        - ID selector: `#review { llm_model: gpt-4o; }` applies to specific node
        - Specificity order: ID > class > universal
        - Explicit node attribute overrides stylesheet
        - Multiple classes on a node match multiple selectors
    - [x] Mark TODO complete and commit the changes to git

- [x] Implement the full model resolution chain
    - [x] Create `src/orchestra/config/model_resolution.py`:
        - `resolve_node_model(node, agent_config, graph, providers_config) -> tuple[str, str]` returning (model, provider)
        - Precedence: explicit node attribute > stylesheet rule > agent config > graph-level default > provider default
    - [x] Write tests in `tests/test_model_resolution.py`:
        - Full resolution chain with each level overriding lower levels
        - Each level tested in isolation
    - [x] Mark TODO complete and commit the changes to git

### Phase 7: CodergenHandler Adapter and SimulationBackend

- [x] Refactor SimulationCodergenHandler into SimulationBackend + CodergenHandler
    - [x] Create `src/orchestra/backends/simulation.py`:
        - `SimulationBackend` implementing `CodergenBackend` protocol
        - Same behavior as current `SimulationCodergenHandler` but returns `str` or `Outcome`
        - Accepts `outcome_sequences` like the current handler
    - [x] Create `src/orchestra/handlers/codergen_handler.py`:
        - `CodergenHandler` implementing `NodeHandler` protocol
        - Constructor: `__init__(backend, prompt_engine, model_resolver, config)`
        - `handle(node, context, graph) -> Outcome`:
            1. Compose prompt via prompt engine (or use node.prompt if no agent config)
            2. Resolve model via resolution chain
            3. Call `backend.run(node, prompt, context, on_turn)`
            4. Convert `str` result to `Outcome(status=SUCCESS, notes=str, context_updates={"last_response": str})`
            5. Pass through `Outcome` results directly
            6. Write `prompt.md` and `response.md` to stage logs directory
    - [x] Update `src/orchestra/handlers/codergen.py` — keep `SimulationCodergenHandler` as a thin wrapper or alias for backwards compatibility during transition, then remove
    - [x] Update `src/orchestra/handlers/registry.py` — `default_registry()` registers `CodergenHandler(backend=SimulationBackend())` for shape `"box"`
    - [x] Write tests in `tests/test_codergen_handler.py`:
        - Handler wraps backend: calls `backend.run()` and returns Outcome
        - String to Outcome conversion: backend returns str → handler wraps in Outcome
        - Backend returns Outcome: passes through directly
        - Prompt composition integration: handler composes prompt from agent config
        - Model resolution integration: handler resolves model and passes to backend
        - Writes prompt.md and response.md to logs directory
        - SimulationBackend compatibility: same results as old SimulationCodergenHandler
    - [x] Run full test suite — verify all 137 existing tests pass unchanged
    - [x] Mark TODO complete and commit the changes to git

### Phase 8: DirectLLMBackend

- [x] Implement DirectLLMBackend
    - [x] Create `src/orchestra/backends/direct_llm.py`:
        - `DirectLLMBackend` implementing `CodergenBackend`
        - Single LLM API call via LangChain chat model, no tool use
        - Constructor takes provider config for instantiating the correct LangChain model
        - Does not invoke `on_turn` callback
        - Catches LLM API errors (rate limits, auth, network) → returns `Outcome(status=FAIL, failure_reason=...)`
        - Sanitizes error messages (strips API keys, request bodies)
    - [x] Write tests in `tests/test_direct_llm_backend.py`:
        - Mock LLM returns expected response → backend returns it as string
        - Mock LLM returns structured JSON → backend parses into Outcome
        - DirectLLMBackend does not invoke `on_turn` callback
        - LLM API error → Outcome(status=FAIL) with sanitized failure_reason
    - [x] Mark TODO complete and commit the changes to git

### Phase 9: LangGraphBackend

- [x] Implement LangGraphBackend
    - [x] Create `src/orchestra/backends/langgraph_backend.py`:
        - `LangGraphBackend` implementing `CodergenBackend`
        - Creates LangGraph ReAct agent with provided tools (wrapping Orchestra tools in LangChain StructuredTool)
        - Streams execution turn-by-turn
        - After each turn: builds `AgentTurn` with turn_number, messages, tool_calls, files_written (from WriteTracker), token_usage, agent_state
        - Invokes `on_turn(agent_turn)` callback
        - Returns final result as string or Outcome
        - Catches LLM API errors → Outcome(status=FAIL)
    - [x] Create `src/orchestra/backends/tool_adapter.py`:
        - `to_langchain_tool(orchestra_tool) -> StructuredTool` — wraps Orchestra tool for LangChain
        - Preserves tool name, description, and schema
    - [x] Write tests in `tests/test_langgraph_backend.py`:
        - Mock LLM + mock tools → agent runs tool loop → returns result
        - Agent calls read_file tool → tool returns content → agent incorporates it
        - `on_turn` callback invoked after each agent loop turn
        - AgentTurn contains correct turn_number, messages, tool_calls, token_usage
        - Agent calls write_file → `AgentTurn.files_written` contains the path
        - AgentTurn contains serialized agent state for observability
        - LLM API error → Outcome(status=FAIL)
    - [x] Mark TODO complete and commit the changes to git

### Phase 10: CLIAgentBackend

- [x] Implement CLIAgentBackend
    - [x] Create `src/orchestra/backends/cli_agent.py`:
        - `CLIAgentBackend` implementing `CodergenBackend`
        - Spawns CLI agent (Claude Code, Codex, Gemini CLI) as subprocess
        - Passes prompt via stdin, context via temp JSON file (path in `ORCHESTRA_CONTEXT_FILE` env var or `--context-file` flag)
        - Captures stdout as response
        - Does not invoke `on_turn`
        - Configurable command template per agent type
    - [x] Write tests in `tests/test_cli_agent_backend.py`:
        - Mock subprocess returns stdout → backend captures it as response
        - CLIAgentBackend does not invoke `on_turn` callback
        - Context file written to temp directory with correct content
        - Subprocess error → Outcome(status=FAIL)
    - [x] Mark TODO complete and commit the changes to git

### Phase 11: AgentTurn CXDB Persistence

- [x] Register `dev.orchestra.AgentTurn` CXDB type and persist turns
    - [x] Update `src/orchestra/storage/type_bundle.py`:
        - Add `dev.orchestra.AgentTurn` v1 type with fields: turn_number, node_id, model, provider, messages (as JSON string), tool_calls (as JSON string), files_written (array), token_usage (map), agent_state (as JSON string)
    - [x] Update `src/orchestra/events/types.py`:
        - Add `AgentTurnCompleted` event type with AgentTurn data
    - [x] Update `src/orchestra/events/observer.py`:
        - `CxdbObserver` handles `AgentTurnCompleted` events → appends as `dev.orchestra.AgentTurn` turn
    - [x] Write tests:
        - AgentTurn CXDB type registered correctly in type bundle
        - CxdbObserver persists AgentTurnCompleted events
    - [x] Mark TODO complete and commit the changes to git

### Phase 12: CLI Integration — Wire Everything Together

- [ ] Update CLI commands to support real backend selection
    - [ ] Update `src/orchestra/cli/run.py`:
        - Load full `orchestra.yaml` config (providers, agents, tools, backend)
        - Construct appropriate backend based on config (simulation, direct, langgraph, cli)
        - Build `CodergenHandler` with backend, prompt engine, model resolver
        - Apply model stylesheet transform after variable expansion
        - Pass `on_turn` callback that emits `AgentTurnCompleted` events
    - [ ] Update `src/orchestra/handlers/registry.py`:
        - Accept backend parameter in `default_registry()` or provide `build_registry(config)` factory
    - [ ] Ensure `orchestra run` still defaults to simulation mode when no provider is configured
    - [ ] Write tests verifying CLI wiring:
        - Default (no provider) → SimulationBackend used
        - Config with `backend: direct` → DirectLLMBackend used
        - Config with `backend: langgraph` → LangGraphBackend used
    - [ ] Mark TODO complete and commit the changes to git

### Phase 13: End-to-End Integration Tests (Mocked LLM)

- [ ] Write end-to-end integration tests with mocked LLM
    - [ ] Create `tests/test_e2e_llm_integration.py`:
        - Pipeline with agent config → prompt composed from YAML layers → passed to mocked backend
        - Pipeline with stylesheet → correct model resolved for each node → mocked backend called with correct model
        - Pipeline with inline agent attributes (`agent.role="engineer"`) → prompt composed correctly
        - Pipeline with tools → LangGraphBackend receives correct tool set
        - Config validation → invalid orchestra.yaml → clear, actionable errors
        - Backend selection → config sets backend → correct backend used
        - Provider switching → changing default provider → all nodes use new provider's models
    - [ ] Create test fixtures: sample `.dot` files, YAML prompt files, `orchestra.yaml` configs
    - [ ] Verify all tests pass: `pytest tests/` with 0 failures
    - [ ] Mark TODO complete and commit the changes to git

### Phase 14: Backend Interface Contract Tests

- [ ] Write backend interface contract tests
    - [ ] Create `tests/test_backend_contract.py`:
        - All three backends + SimulationBackend conform to `run(node, prompt, context, on_turn) -> str | Outcome`
        - All backends accept `on_turn=None` without error
        - DirectLLM and CLI backends ignore `on_turn`
        - LangGraph backend invokes `on_turn`
    - [ ] Mark TODO complete and commit the changes to git

### Phase 15: Review and Cleanup

- [ ] Identify any code that is unused, or could be cleaned up
    - [ ] Look at all previous TODOs and changes in git to identify changes
    - [ ] Identify any code that is no longer used, and remove it (e.g., old `SimulationCodergenHandler` if fully replaced)
    - [ ] Identify any unnecessary comments, and remove them
    - [ ] If there are any obvious code smells or redundant code, add TODOs below to address them
    - [ ] Mark TODO complete and commit the changes to git

- [ ] Identify all specs that need to be run and updated
    - [ ] Look at all previous TODOs and changes in git to identify changes
    - [ ] Run the full test suite: `pytest tests/`
    - [ ] Identify any specs that failed and add them to a new TODO to fix
    - [ ] Identify any missing specs that need to be added or updated
    - [ ] Add these specs to a new TODO
    - [ ] Mark TODO complete and commit the changes to git

- [ ] Final verification — all success criteria from plan.md
    - [ ] All three CodergenBackend implementations conform to the protocol
    - [ ] CodergenHandler wraps CodergenBackend and implements NodeHandler — PipelineRunner unchanged
    - [ ] SimulationBackend replaces SimulationCodergenHandler — all 137 existing tests pass
    - [ ] LangGraphBackend invokes `on_turn` with correct AgentTurn data
    - [ ] AgentTurn persisted to CXDB as `dev.orchestra.AgentTurn`
    - [ ] WriteTracker records file modifications and `@modifies_files` works
    - [ ] Provider alias resolution maps semantic tiers to model strings
    - [ ] Model stylesheet applies per-node overrides by specificity (graph transform)
    - [ ] Full resolution precedence chain works
    - [ ] Prompt composition assembles 4 layers with Jinja2
    - [ ] File discovery resolves via 3-level chain
    - [ ] Tool registry supports decorators, YAML shell tools, flat naming
    - [ ] LLM API errors surface as Outcome(status=FAIL)
    - [ ] Full test suite passes: 190+ tests, 0 failures
    - [ ] Mark TODO complete and commit the changes to git

## Manual Testing Guide

### Prerequisites
- Stage 2b complete and passing
- At least one LLM API key available (e.g., `ANTHROPIC_API_KEY`)
- `orchestra.yaml` configured with provider credentials

### Test 1: Simple LLM Pipeline

Create `orchestra.yaml`:
```yaml
providers:
  default: anthropic
  anthropic:
    models:
      smart: claude-opus-4-20250514
      worker: claude-sonnet-4-20250514
      cheap: claude-haiku-3-20250514
```

Create `test-llm.dot`:
```dot
digraph test_llm {
    graph [goal="Write a haiku about programming"]

    start  [shape=Mdiamond]
    exit   [shape=Msquare]
    write  [shape=box, label="Write Haiku", prompt="Write a haiku about: $goal", llm_model="cheap"]

    start -> write -> exit
}
```

Run: `orchestra run test-llm.dot`

**Verify:**
- Pipeline executes with a real LLM call
- `write/response.md` in the run directory contains an actual haiku
- `write/prompt.md` contains the expanded prompt
- Events show real execution timing

### Test 2: Agent with Layered Prompts

Create prompt files:
- `prompts/roles/code-reviewer.yaml` with a role system prompt
- `prompts/personas/senior-engineer.yaml` with persona modifiers
- `prompts/tasks/review-code.yaml` with a task template using `{{code_snippet}}`

Create an agent configuration in `orchestra.yaml` referencing these files. Create a pipeline using this agent.

Run: `orchestra run test-agent.dot`

**Verify:**
- Inspect `{node}/prompt.md` — all four layers are present in the composed prompt
- The Jinja2 template variable was interpolated
- The LLM response is coherent with the combined prompt

### Test 3: Model Stylesheet

Create a pipeline with a `model_stylesheet` that assigns different models to different node classes.

Run: `orchestra run test-stylesheet.dot`

**Verify:**
- Different nodes use different models (observable via events or logs showing which model was called)
- Specificity works: ID override > class > universal

### Test 4: Switch Providers

Change `providers.default` in `orchestra.yaml` from `anthropic` to `openai`. Run the same pipeline.

**Verify:**
- All nodes now use OpenAI models
- The smart/worker/cheap aliases resolve to OpenAI model names
- Pipeline produces valid output from a different provider

## Success Criteria

- [ ] All three CodergenBackend implementations work and conform to the `run(node, prompt, context, on_turn=None)` interface
- [ ] CodergenHandler wraps CodergenBackend and implements the existing NodeHandler protocol — PipelineRunner is unchanged
- [ ] SimulationBackend replaces SimulationCodergenHandler and all existing tests continue to pass
- [ ] LangGraphBackend invokes `on_turn` after each agent loop turn with correct AgentTurn data
- [ ] AgentTurn data is persisted to CXDB as `dev.orchestra.AgentTurn` turns
- [ ] WriteTracker records file modifications from write tools and flushes per turn
- [ ] `@modifies_files` decorator auto-records paths for custom tools
- [ ] Provider alias resolution maps semantic tiers to concrete model strings
- [ ] Model stylesheet applies per-node overrides by specificity (implemented as a graph transform)
- [ ] Full model resolution precedence chain works (explicit > stylesheet > agent > graph > provider)
- [ ] Prompt composition assembles four layers from YAML files with Jinja2 interpolation
- [ ] File discovery resolves files via the 3-level chain
- [ ] Tool registry supports decorator registration, YAML shell tools, and flat naming
- [ ] Agent configuration from `orchestra.yaml` correctly composes prompts, resolves models, and assembles tools
- [ ] LLM API errors surface as Outcome(status=FAIL) and are handled by the existing node-level retry system
- [ ] A human can run a pipeline with real LLM calls and inspect the AI-generated output
- [ ] Changing one line in `orchestra.yaml` (default provider) switches all agents to a different provider
- [ ] All automated tests pass with mocked LLMs (including all 137 existing tests via SimulationBackend)
