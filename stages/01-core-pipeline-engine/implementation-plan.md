# Stage 1: Core Pipeline Engine — Implementation Plan

## Investigation

- [ ] Verify CXDB Docker image availability and API surface
    - [ ] Run `docker pull cxdb/cxdb:latest` — if unavailable, check Docker Hub for correct tag or build from source using the Dockerfile in the [CXDB repo](https://github.com/strongdm/cxdb)
    - [ ] Start CXDB: `docker run -p 9009:9009 -p 9010:9010 cxdb/cxdb:latest`
    - [ ] Exercise the HTTP API endpoints:
        - `GET /health` — verify response format
        - `POST /v1/contexts/create` — create a context, note the context_id format (u64 integer)
        - `POST /v1/contexts/:id/append` — append a turn, note accepted payload format
        - `GET /v1/contexts/:id/turns` — retrieve turns
        - `GET /v1/contexts` — list contexts
        - `PUT /v1/registry/bundles/:bundle_id` — publish a test type bundle
    - [ ] Document any differences from the assumed API in `plan.md` Prerequisites table
    - [ ] If the Docker image tag is different, update all references in the plan and this document
    - [ ] Mark TODO complete and commit the changes to git

- [ ] Prototype the Lark grammar from the attractor BNF (Section 2.2)
    - [ ] Translate the attractor BNF grammar to Lark EBNF syntax
    - [ ] Test against the minimal examples in attractor spec Section 2.13 (simple linear, branching, human gate)
    - [ ] Verify: chained edges, subgraphs, all value types (String, Integer, Float, Boolean, Duration), comments
    - [ ] Verify rejection of: undirected graphs, multiple digraph blocks
    - [ ] Note any BNF-to-Lark translation issues and update the plan
    - [ ] Mark TODO complete and commit the changes to git

## Plan

### 1. Project Scaffolding

- [x] Set up project structure and tooling
    - [x] Create `pyproject.toml` with `uv` as package manager
        - Dependencies: `lark`, `typer`, `httpx`, `pydantic`, `pyyaml`, `pytest`
        - Entry point: `orchestra` CLI command pointing to `src/orchestra/cli/main.py`
        - Python 3.11+ required
    - [x] Create `src/orchestra/__init__.py` (package root)
    - [x] Create package directories:
        - `src/orchestra/cli/` — CLI commands (Typer)
        - `src/orchestra/parser/` — DOT parser (Lark grammar + transformer)
        - `src/orchestra/models/` — Pydantic models (graph, config, events, outcomes)
        - `src/orchestra/validation/` — Graph validation lint rules
        - `src/orchestra/engine/` — Pipeline execution engine
        - `src/orchestra/handlers/` — Node handlers (start, exit, codergen)
        - `src/orchestra/storage/` — CXDB client and type bundle
        - `src/orchestra/events/` — Event system (observer pattern)
        - `src/orchestra/config/` — Configuration discovery and parsing
        - `src/orchestra/transforms/` — AST transforms (variable expansion)
    - [x] Create `tests/` directory with `conftest.py`
    - [x] Create `tests/fixtures/` directory for test DOT files
    - [x] Run `uv sync` to verify the project builds
    - [x] Run `uv run orchestra --help` to verify CLI entry point works
    - [x] Mark TODO complete and commit the changes to git

### 2. Configuration Discovery and Parsing

- [x] Implement `orchestra.yaml` configuration loading with env var overrides
    - [x] Create `src/orchestra/config/settings.py`:
        - `CxdbConfig` Pydantic model: `url: str = "http://localhost:9010"`
        - `OrchestraConfig` Pydantic model: `cxdb: CxdbConfig`
        - `load_config()` function with precedence: **env vars > orchestra.yaml > defaults**
            1. Search CWD → parent directories → filesystem root for `orchestra.yaml`
            2. If found, parse with `pyyaml` and validate with Pydantic
            3. If no `orchestra.yaml` found, use defaults (`cxdb.url = http://localhost:9010`)
            4. Apply environment variable overrides: `ORCHESTRA_CXDB_URL` overrides `cxdb.url`
        - Env var override is applied last, so it always wins regardless of orchestra.yaml contents
    - [x] Write tests for config loading:
        - Loads from CWD
        - Walks parent directories
        - Falls back to defaults when no file found
        - Validates the Pydantic model
        - `ORCHESTRA_CXDB_URL` env var overrides orchestra.yaml value
        - `ORCHESTRA_CXDB_URL` env var overrides default value
    - [x] Mark TODO complete and commit the changes to git

### 3. CXDB Client and Doctor Command

- [x] Implement the CXDB HTTP client
    - [x] Create `src/orchestra/storage/cxdb_client.py`:
        - `CxdbClient` class with `httpx.Client` for HTTP calls
        - `health_check() -> dict` — `GET /health`
        - `create_context(base_turn_id: str = "0") -> dict` — `POST /v1/contexts/create`
        - `append_turn(context_id: str, type_id: str, type_version: int, data: dict) -> dict` — `POST /v1/contexts/:id/append`
        - `get_turns(context_id: str, limit: int = 64) -> list[dict]` — `GET /v1/contexts/:id/turns?limit={limit}&view=typed`
        - `list_contexts(limit: int = 100, offset: int = 0) -> list[dict]` — `GET /v1/contexts?limit={limit}&offset={offset}`
        - `publish_type_bundle(bundle_id: str, bundle: dict) -> None` — `PUT /v1/registry/bundles/:bundle_id`
        - Error handling: raise descriptive exceptions on connection failure, HTTP errors
    - [x] Create `src/orchestra/storage/type_bundle.py`:
        - `ORCHESTRA_TYPE_BUNDLE` constant with the full type bundle JSON (from plan.evaluation.md):
            - `dev.orchestra.PipelineLifecycle` (fields: pipeline_name, goal, status, duration_ms, error, session_display_id)
            - `dev.orchestra.NodeExecution` (fields: node_id, handler_type, status, prompt, response, outcome, duration_ms)
            - `dev.orchestra.Checkpoint` (fields: current_node, completed_nodes, context_snapshot, retry_counters)
        - `publish_orchestra_types(client: CxdbClient) -> None` function
    - [x] Write unit tests for `CxdbClient` (mock HTTP responses with `httpx.MockTransport` — no extra dependency needed)
    - [x] Write integration tests for `CxdbClient` (require CXDB Docker container, marked with `@pytest.mark.integration`)
    - [x] Mark TODO complete and commit the changes to git

- [x] Implement `orchestra doctor` CLI command
    - [x] Create `src/orchestra/cli/main.py` with Typer app
    - [x] Create `src/orchestra/cli/doctor.py`:
        - `doctor()` command: load config → create `CxdbClient` → call `health_check()` → print status
        - Check CXDB connectivity: print OK or print clear error with Docker setup instructions
        - Check type bundle registration: attempt `publish_orchestra_types()`, report status
    - [x] Write CLI tests for `orchestra doctor` (using Typer's `CliRunner`)
    - [x] Mark TODO complete and commit the changes to git

### 4. DOT Parser

- [x] Define the graph model (Pydantic) — **must be done first; the transformer depends on these models**
    - [x] Create `src/orchestra/models/graph.py`:
        - `Node` model: `id: str`, `label: str`, `shape: str`, `prompt: str`, `attributes: dict[str, Any]` (remaining attributes like `goal_gate`, `max_retries`, `timeout`, `class`, etc.)
        - `Edge` model: `from_node: str`, `to_node: str`, `label: str`, `condition: str`, `weight: int`, `attributes: dict[str, Any]`
        - `PipelineGraph` model: `name: str`, `nodes: dict[str, Node]`, `edges: list[Edge]`, `graph_attributes: dict[str, Any]`
        - Helper methods: `get_outgoing_edges(node_id)`, `get_node(node_id)`, `get_start_node()`, `get_exit_nodes()`, `goal` property (from graph_attributes)
    - [x] Mark TODO complete and commit the changes to git

- [x] Implement the Lark grammar and transformer
    - [x] Create `src/orchestra/parser/grammar.lark`:
        - Translate attractor BNF (Section 2.2) to Lark EBNF
        - Support: `digraph`, `graph`/`node`/`edge` attribute blocks, node statements, edge statements (including chained `A -> B -> C`), subgraphs, comments (`//` and `/* */`), all value types (String, Integer, Float, Boolean, Duration), qualified IDs (`agent.role`), optional semicolons
        - Support `GraphAttrDecl` production: top-level `key = value` declarations (e.g., `rankdir = LR`) outside of `graph [...]` blocks — merge these into `graph_attributes`
        - Reject: undirected graphs (`graph { ... }` or `--` edges), multiple digraph blocks
        - **Grammar strictness:** follow attractor BNF strictly — commas are required between attributes in `AttrBlock` (per Section 2.3). Do not relax to accept semicolons or bare whitespace as separators, even though standard Graphviz DOT allows them.
    - [x] Create `src/orchestra/parser/transformer.py`:
        - Lark `Transformer` subclass that converts the parse tree to the in-memory graph model
        - Handle chained edges: `A -> B -> C [attrs]` → two edges with shared attributes
        - Handle node/edge default blocks: accumulate defaults, apply to subsequent nodes/edges within scope
        - Handle subgraphs: flatten contents into parent graph, scope defaults to subgraph
        - Handle all value type conversions: String (strip quotes, unescape), Integer, Float, Boolean, Duration (to seconds or raw string)
        - Handle `GraphAttrDecl`: merge top-level `key = value` into graph attributes
    - [x] Create `src/orchestra/parser/parser.py`:
        - `parse_dot(source: str) -> PipelineGraph` function
        - Load Lark grammar, parse source, transform to graph model
        - Wrap Lark parse errors in user-friendly error messages
    - [x] Mark TODO complete and commit the changes to git

- [x] Write DOT parsing tests
    - [x] Create `tests/fixtures/` DOT files for all test cases:
        - `test-linear.dot` — simple 5-node linear pipeline (from Manual Testing Guide)
        - `test-invalid-no-start-exit.dot` — no start or exit node
        - `test-chained-edges.dot` — `A -> B -> C [label="x"]`
        - `test-subgraph.dot` — subgraph with scoped defaults
        - `test-all-value-types.dot` — String, Integer, Float, Boolean, Duration attributes
        - `test-comments.dot` — line and block comments
        - `test-node-edge-defaults.dot` — `node [shape=box]` / `edge [weight=0]` defaults
        - `test-graph-attributes.dot` — `goal`, `label`, `model_stylesheet`/`model_spec`
        - `test-undirected.dot` — `graph { A -- B }` (should be rejected)
        - `test-multiple-graphs.dot` — two `digraph` blocks (should be rejected)
    - [x] Create `tests/test_dot_parsing.py` implementing all 10 DOT parsing tests from the plan:
        - Parse simple linear pipeline
        - Parse graph-level attributes (including `model_spec` alias)
        - Parse node attributes
        - Parse edge attributes
        - Parse chained edges
        - Parse node/edge defaults
        - Parse subgraphs
        - Parse comments
        - Parse all value types
        - Reject undirected graph
        - Reject multiple graphs
    - [x] Run tests: `uv run pytest tests/test_dot_parsing.py -v`
    - [x] Mark TODO complete and commit the changes to git

### 5. Graph Validation

- [x] Implement validation lint rules
    - [x] Create `src/orchestra/models/diagnostics.py`:
        - `Severity` enum: `ERROR`, `WARNING`, `INFO`
        - `Diagnostic` model: `rule: str`, `severity: Severity`, `message: str`, `node_id: str | None`, `edge: tuple[str, str] | None`, `suggestion: str`
        - `DiagnosticCollection` model with `errors`, `warnings`, `has_errors` helpers
    - [x] Create `src/orchestra/validation/rules.py`:
        - Each rule is a function: `(graph: PipelineGraph) -> list[Diagnostic]`
        - Implement rules:
            - `start_node` — exactly one `shape=Mdiamond` node
            - `terminal_node` — at least one `shape=Msquare` node
            - `reachability` — all nodes reachable from start (BFS/DFS)
            - `edge_target_exists` — all edge `to_node` references exist in graph
            - `start_no_incoming` — start node has no incoming edges
            - `exit_no_outgoing` — exit node has no outgoing edges
            - `condition_syntax` — edge conditions parse correctly (basic syntax check — full condition evaluator is Stage 2a, but catch obvious syntax errors now)
            - `stylesheet_syntax` — `model_stylesheet` / `model_spec` value parses correctly (basic syntax check)
            - `prompt_on_llm_nodes` — codergen nodes (`shape=box`) should have `prompt` or `label`
    - [x] Create `src/orchestra/validation/validator.py`:
        - `validate(graph: PipelineGraph) -> DiagnosticCollection` — runs all rules
        - `validate_or_raise(graph: PipelineGraph) -> DiagnosticCollection` — raises if any ERROR diagnostics
    - [x] Mark TODO complete and commit the changes to git

- [x] Write validation tests
    - [x] Create `tests/test_validation.py` implementing all 8 validation tests from the plan:
        - Missing start node → ERROR
        - Missing exit node → ERROR
        - Start node has incoming edges → ERROR
        - Exit node has outgoing edges → ERROR
        - Unreachable node → ERROR
        - Edge target doesn't exist → ERROR
        - Missing prompt on codergen node → WARNING
        - Valid pipeline passes — no ERROR diagnostics
        - Actionable error messages — each diagnostic includes rule, severity, node/edge ID, message, suggestion
    - [x] Run tests: `uv run pytest tests/test_validation.py -v`
    - [x] Mark TODO complete and commit the changes to git

### 6. Context, Outcome Model, and Variable Expansion

- [x] Implement the Context and Outcome models
    - [x] Create `src/orchestra/models/context.py`:
        - `Context` class: key-value store with `get(key, default=None)`, `set(key, value)`, `snapshot() -> dict`
        - Built-in keys set by the engine: `outcome`, `graph.goal`, `current_node`, `last_stage`, `last_response`
    - [x] Create `src/orchestra/models/outcome.py`:
        - `OutcomeStatus` enum: `SUCCESS`, `FAIL`, `PARTIAL_SUCCESS`, `RETRY`
        - `Outcome` model: `status: OutcomeStatus`, `preferred_label: str`, `suggested_next_ids: list[str]`, `context_updates: dict[str, Any]`, `notes: str`, `failure_reason: str`
    - [x] Mark TODO complete and commit the changes to git

- [x] Implement variable expansion transform
    - [x] Create `src/orchestra/transforms/variable_expansion.py`:
        - `expand_variables(graph: PipelineGraph) -> PipelineGraph` function
        - Expand `$goal` in node `prompt` attributes to the graph-level `goal` attribute value
        - Return a new graph with expanded prompts (or mutate in place — decide during implementation)
    - [x] Write tests for variable expansion:
        - `$goal` in prompt is replaced with `graph [goal="..."]` value
        - Nodes without `$goal` in prompt are unchanged
        - Missing graph `goal` attribute → `$goal` replaced with empty string
    - [x] Mark TODO complete and commit the changes to git

### 7. Execution Engine and Handlers

- [x] Implement node handlers
    - [x] Create `src/orchestra/handlers/base.py`:
        - `NodeHandler` Protocol: `handle(node: Node, context: Context, graph: PipelineGraph) -> Outcome`
    - [x] Create `src/orchestra/handlers/start.py`:
        - `StartHandler`: no-op, returns SUCCESS outcome
    - [x] Create `src/orchestra/handlers/exit.py`:
        - `ExitHandler`: no-op, returns SUCCESS outcome
    - [x] Create `src/orchestra/handlers/codergen.py`:
        - `SimulationCodergenHandler`: returns `Outcome(status=SUCCESS, notes="[Simulated] Response for stage: {node_id}")` with the response text also set in `context_updates`
        - Uses the node's expanded prompt (after variable expansion)
    - [x] Create `src/orchestra/handlers/registry.py`:
        - `HandlerRegistry` class: maps shape → handler instance
        - Default registry: `Mdiamond → StartHandler`, `Msquare → ExitHandler`, `box → SimulationCodergenHandler`
    - [x] Mark TODO complete and commit the changes to git

- [x] Implement the core execution engine
    - [x] Create `src/orchestra/engine/edge_selection.py`:
        - `select_edge(node_id, outcome, context, graph) -> Edge | None` — partial implementation of attractor Section 3.3:
            - **Stage 1 implements steps 4+5 only** (weight + lexical tiebreak among unconditional edges). This is forward-compatible with Stage 2a which adds condition evaluation (step 1), preferred label (step 2), and suggested next IDs (step 3).
            - Among all outgoing edges from `node_id`, select the one with the highest `weight` (default 0)
            - If weights are equal, select the edge whose `to_node` comes first lexicographically
            - If no outgoing edges, return `None`
    - [x] Create `src/orchestra/engine/runner.py`:
        - `PipelineRunner` class:
            - `__init__(graph, handler_registry, event_dispatcher, cxdb_client, context_id)`
            - `run() -> Outcome` — core traversal loop per attractor Section 3.2:
                1. Start at the start node
                2. Check if current node is terminal → break
                3. Resolve handler from registry based on node shape
                4. Execute handler → get Outcome
                5. Record completion, apply context updates
                6. Set built-in context keys (`outcome`, `current_node`, `last_stage`, `last_response`)
                7. Emit events (StageStarted, StageCompleted or StageFailed)
                8. Emit `CheckpointSaved` event with full state (CxdbObserver handles the CXDB turn append — see Step 8)
                9. Select next edge using `select_edge()` (weight + lexical tiebreak)
                10. If no edge selected and outcome is FAIL → emit PipelineFailed and return failure outcome
                11. If no edge selected and outcome is SUCCESS → break (reached terminal state)
                12. Advance to next node
                13. On pipeline completion, emit PipelineCompleted
            - **Failure handling:** if a handler returns `FAIL` or `RETRY` and no outgoing edge is selected, the runner emits `PipelineFailed` with the failure details and returns the failure outcome. Retry logic (re-executing the node) is deferred to Stage 2a — in Stage 1, `RETRY` is treated as `FAIL`.
    - [x] Write unit tests for the execution engine (mock handlers, mock CXDB):
        - 3-node linear pipeline executes in order
        - 5-node linear pipeline executes sequentially
        - Context propagation between nodes
        - Handler returning FAIL → PipelineFailed emitted, run returns failure outcome
    - [x] Mark TODO complete and commit the changes to git

### 8. Event System

- [x] Implement the typed event system
    - [x] Create `src/orchestra/events/types.py`:
        - Event base class (Pydantic): `timestamp: datetime`, `event_type: str`
        - `PipelineStarted`: `pipeline_name`, `goal`, `session_display_id`
        - `PipelineCompleted`: `pipeline_name`, `duration_ms`, `session_display_id`
        - `PipelineFailed`: `pipeline_name`, `error`, `session_display_id`
        - `StageStarted`: `node_id`, `handler_type`
        - `StageCompleted`: `node_id`, `handler_type`, `status`, `duration_ms`
        - `StageFailed`: `node_id`, `handler_type`, `error`
        - `CheckpointSaved`: `node_id`, `context_snapshot`
    - [x] Create `src/orchestra/events/observer.py`:
        - `EventObserver` Protocol: `on_event(event: Event) -> None`
        - `StdoutObserver`: prints formatted events to stdout
        - `CxdbObserver`: appends typed CXDB turns for each event
            - Maps event types → CXDB turn types:
                - `PipelineStarted/Completed/Failed` → `dev.orchestra.PipelineLifecycle`
                - `StageStarted/Completed/Failed` → `dev.orchestra.NodeExecution`
                - `CheckpointSaved` → `dev.orchestra.Checkpoint`
            - **CXDB write boundary:** CxdbObserver is the *sole* writer of CXDB turns. The runner emits events (including `CheckpointSaved` with full state), and the CxdbObserver translates them to CXDB append calls. The runner does NOT call `cxdb_client.append_turn()` directly — all CXDB writes flow through the observer. This keeps the write path unified and testable.
    - [x] Create `src/orchestra/events/dispatcher.py`:
        - `EventDispatcher` class: holds list of observers, dispatches events to all
    - [x] Write tests for the event system:
        - Events dispatched to all registered observers
        - StdoutObserver formats events correctly
        - CxdbObserver maps events to correct CXDB turn types
    - [x] Mark TODO complete and commit the changes to git

### 9. CXDB Storage Integration and Checkpoints

- [x] Wire CXDB storage into the execution engine
    - [x] Update `PipelineRunner` to:
        - Create a CXDB context at pipeline start (via `cxdb_client.create_context()`)
        - Generate a short display ID (first 6 chars of UUID) and include in the `PipelineStarted` event
        - Use CXDB context_id as canonical session identifier
        - Publish the Orchestra type bundle before the first run (idempotent)
        - Pass `cxdb_client` and `context_id` to the `CxdbObserver` so it can append turns
    - [x] Implement checkpoint events:
        - After each node completion, the runner emits a `CheckpointSaved` event containing:
            - `current_node`: current node ID
            - `completed_nodes`: list of completed node IDs
            - `context_snapshot`: full context key-value dump
            - `retry_counters`: empty dict for Stage 1
        - The `CxdbObserver` receives this event and appends a `dev.orchestra.Checkpoint` turn (all CXDB writes flow through the observer — the runner does not call `append_turn()` directly)
    - [x] Verify turn types in CXDB:
        - PipelineStarted → `dev.orchestra.PipelineLifecycle` with status="started"
        - StageStarted/Completed → `dev.orchestra.NodeExecution` with appropriate status
        - CheckpointSaved → `dev.orchestra.Checkpoint` with full state
        - PipelineCompleted → `dev.orchestra.PipelineLifecycle` with status="completed"
    - [x] Write integration tests against real CXDB (marked `@pytest.mark.integration`):
        - Context created on pipeline start
        - Turns appended in correct order
        - Turn types match expected CXDB types
        - Checkpoint turns contain correct state
        - NodeExecution payloads include prompt, response, outcome
        - Context isolation: two runs create two separate contexts
    - [x] Mark TODO complete and commit the changes to git

### 10. CLI Commands — Compile and Run

- [x] Implement `orchestra compile` command
    - [x] Create `src/orchestra/cli/compile.py`:
        - `compile(pipeline: Path)` command:
            1. Read the DOT file
            2. Parse with `parse_dot()`
            3. Validate with `validate_or_raise()`
            4. Print graph structure summary: node count, edge count, goal, node list with shapes
            5. Print any WARNING diagnostics
            6. Exit 0 on success, non-zero on validation errors
    - [x] Write CLI tests:
        - Valid pipeline → exit 0, prints graph summary
        - Invalid pipeline → exit non-zero, prints ERROR diagnostics with rule names and suggestions
    - [x] Mark TODO complete and commit the changes to git

- [x] Implement `orchestra run` command
    - [x] Create `src/orchestra/cli/run.py`:
        - `run(pipeline: Path)` command:
            1. Load config (orchestra.yaml)
            2. Read and parse the DOT file
            3. Validate the graph (exit on errors)
            4. Apply transforms (variable expansion)
            5. Create CXDB client, verify connectivity (fail fast if CXDB unavailable)
            6. Publish type bundle (idempotent)
            7. Create CXDB context (session)
            8. Set up event observers (StdoutObserver + CxdbObserver)
            9. Create handler registry (simulation mode)
            10. Create PipelineRunner and execute
            11. Print session ID (CXDB context_id + display ID)
            12. Exit 0 on success, non-zero on failure
    - [x] Handle CXDB unavailability: exit non-zero with clear error message, suggest `orchestra doctor`
    - [x] Write CLI tests:
        - `orchestra run` on valid pipeline → exit 0, events printed, session ID shown
        - `orchestra run` on invalid pipeline → exit non-zero with validation errors
        - `orchestra run` without CXDB → exit non-zero with clear error
    - [x] Mark TODO complete and commit the changes to git

### 11. Execution Tests

- [ ] Write execution-focused tests
    - [ ] Create `tests/test_execution.py` implementing all 6 execution tests from the plan:
        - Execute 3-node linear pipeline: `start → plan → exit`, all nodes execute in order, final outcome SUCCESS
        - Execute 5-node linear pipeline: all nodes execute sequentially, context updates visible to next node
        - Simulation mode output: codergen handler returns `[Simulated] Response for stage: {node_id}`
        - Variable expansion: `prompt="Implement: $goal"` with `graph [goal="build widget"]` → `"Implement: build widget"`
        - Context propagation: Node A's context_updates visible to Node B
        - Events emitted: PipelineStarted, StageStarted/StageCompleted per node, CheckpointSaved per node, PipelineCompleted in correct order
    - [ ] Run tests: `uv run pytest tests/test_execution.py -v`
    - [ ] Mark TODO complete and commit the changes to git

### 12. CXDB Storage Integration Tests

- [ ] Write CXDB storage integration tests
    - [ ] Create `tests/test_cxdb_storage.py` implementing all 9 CXDB storage tests from the plan (marked `@pytest.mark.integration`):
        - Context created: `orchestra run` creates a CXDB context
        - Turns appended: each event and checkpoint appended as typed turn
        - Turn types correct: PipelineStarted → `dev.orchestra.PipelineLifecycle`, etc.
        - Checkpoint turns: contain current_node, completed_nodes, context snapshot
        - NodeExecution payloads: include prompt, response, outcome
        - Turn order: turns retrieved from CXDB are in correct execution order
        - Type bundle registered: Orchestra's type bundle published to CXDB
        - CXDB health check: `orchestra doctor` reports status correctly
        - Context isolation: running same pipeline twice creates two separate CXDB contexts
    - [ ] Run tests: `uv run pytest tests/test_cxdb_storage.py -v` (requires CXDB running)
    - [ ] Mark TODO complete and commit the changes to git

### 13. End-to-End CLI Tests

- [ ] Write end-to-end CLI tests
    - [ ] Create `tests/test_cli.py` implementing all 6 CLI tests from the plan:
        - `orchestra compile` valid pipeline → exit 0, prints graph structure
        - `orchestra compile` invalid pipeline → exit non-zero, prints diagnostics
        - `orchestra run` linear pipeline → end-to-end execution, events printed, persisted to CXDB
        - `orchestra run` invalid pipeline → exit non-zero with validation errors
        - `orchestra run` without CXDB → exit non-zero with clear error
        - `orchestra doctor` → reports CXDB connectivity and type registry status
    - [ ] Run full test suite: `uv run pytest tests/ -v`
    - [ ] Mark TODO complete and commit the changes to git

### 14. Test Fixtures and Manual Testing

- [ ] Create test fixtures and verify manual testing
    - [ ] Ensure `tests/fixtures/test-linear.dot` matches the Manual Testing Guide's `test-linear.dot`
    - [ ] Ensure `tests/fixtures/test-invalid.dot` matches the Manual Testing Guide's `test-invalid.dot`
    - [ ] Walk through Manual Testing Guide steps 1-5 and verify:
        - `orchestra compile test-linear.dot` → 5 nodes, 4 edges, exit 0
        - `orchestra compile test-invalid.dot` → ERROR diagnostics, exit non-zero
        - `orchestra run test-linear.dot` → events printed, session ID shown
        - CXDB UI at `http://localhost:9010` shows the execution trace
        - `orchestra doctor` → reports healthy
    - [ ] Mark TODO complete and commit the changes to git

### 15. Review and Cleanup

- [ ] Identify any code that is unused or could be cleaned up
    - [ ] Look at all previous TODOs and changes in git to identify changes
    - [ ] Identify any code that is no longer used, and remove it
    - [ ] Identify any unnecessary comments, and remove them (these are comments that explain "what" for a single line of code)
    - [ ] If there are any obvious code smells of redundant code, add TODOs below to address them (for example, multiple new classes include private methods that perform similar functions, or are large with many private methods that could be extracted into private classes or public classes)
    - [ ] Mark TODO complete and commit the changes to git

### 16. Identify and Run All Specs

- [ ] Identify all specs that need to be run and updated
    - [ ] Look at all previous TODOs and changes in git to identify changes
    - [ ] Identify any specs that cover these changes that need to be run, and run these specs
    - [ ] Add any specs that failed to a new TODO to fix these
    - [ ] Identify any missing specs that need to be added or updated
    - [ ] Add these specs to a new TODO
    - [ ] Mark TODO complete and commit the changes to git

## Decisions Made (from plan.evaluation.md + implementation plan review)

These decisions are resolved and should be followed during implementation:

| Decision | Resolution |
|----------|-----------|
| Session ID strategy | Use CXDB context_id as canonical ID + short display ID (first 6 chars UUID) stored in PipelineLifecycle start turn |
| CXDB API endpoints | Follow the verified HTTP API mapping in plan.md Prerequisites table |
| CXDB type registry | Use HTTP API with named JSON fields; CXDB handles msgpack encoding via registry |
| CXDB unavailability | Fail fast — `orchestra run` exits non-zero with clear error |
| Lark grammar | Translate full attractor BNF upfront; test against all DOT parsing test cases |
| Grammar strictness | Follow attractor BNF strictly — commas required between attributes (per Section 2.3), do not relax to standard DOT |
| Event observer pattern | Use `typing.Protocol` with `on_event(event: Event)` method; StdoutObserver + CxdbObserver |
| CXDB write boundary | CxdbObserver is the sole writer of CXDB turns; the runner emits events, the observer translates them to CXDB appends |
| Graph model | Use Pydantic models (PipelineGraph, Node, Edge) for validation and serialization |
| Config model | Use Pydantic for config (consistent with graph model) |
| Config env var override | `ORCHESTRA_CXDB_URL` env var overrides orchestra.yaml and defaults (highest precedence) |
| Edge selection (Stage 1) | Implement attractor Section 3.3 steps 4+5 (weight + lexical tiebreak). Skip condition eval, preferred label, and suggested IDs (Stage 2a) |
| Runner failure handling | On FAIL/RETRY with no applicable edge, emit PipelineFailed and return failure outcome. RETRY treated as FAIL in Stage 1 |
| HTTP mocking | Use `httpx.MockTransport` for CxdbClient unit tests (no extra dependency) |

## Unresolved (to verify during Investigation)

| Item | Resolution Path |
|------|----------------|
| CXDB Docker image tag (`cxdb/cxdb:latest`) | Verify with `docker pull`; if unavailable, build from source |
| Attractor BNF → Lark EBNF translation | Prototype during Investigation step 2 |
