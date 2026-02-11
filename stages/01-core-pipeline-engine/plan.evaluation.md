# Goal Evaluation: Stage 1 — Core Pipeline Engine (Simulation Mode)

## Goal Summary

Deliver the foundational pipeline runner: parse DOT files into an in-memory graph model using Lark, validate against attractor spec lint rules, execute linear pipelines in simulation mode (no LLM), persist execution state to CXDB as typed turns, and expose via a CLI (`compile`, `run`, `doctor`). This is the minimum viable pipeline runner — a human writes a `.dot` file, compiles it, runs it, and inspects the execution trace in CXDB.

---

<estimates>
ambiguity:
  rating: 1/5
  rationale:
    - "Every component is explicitly specified: DOT parser (Lark), CLI (Typer), HTTP client (httpx), storage (CXDB)"
    - "Implementation sequence is defined as 12 ordered steps"
    - "Test cases are enumerated with specific inputs and expected outputs"
    - "Scope boundaries are explicit — 'Included' vs 'Excluded' sections with stage references for deferred work"
    - "The prerequisite (CXDB API verification) is called out with estimated time"
    - "Only minor ambiguities remain around CXDB API endpoint naming and session ID strategy"

complexity:
  rating: 3/5
  rationale:
    - "DOT parser via Lark requires translating the attractor BNF grammar — non-trivial but well-specified"
    - "Graph validation is a set of independent lint rules — each simple, collectively moderate"
    - "CXDB client is a thin HTTP wrapper (~200 lines) — low complexity"
    - "The execution engine for linear-only traversal is straightforward — the attractor spec provides pseudocode"
    - "The event system + CXDB turn persistence adds integration complexity across subsystems"
    - "Overall, each component is individually simple but there are 12 components to wire together end-to-end"

size:
  rating: 3/5
  loc_estimate: 2500-3500
  worker_estimate: "1-2"
</estimates>

---

<decision-points>
decision_points:
  - id: cxdb-session-id-strategy
    question: "CXDB context IDs are server-assigned monotonic integers (u64), not UUIDs. The plan mentions 'context_id matches session_id' — how does Orchestra generate/track session IDs?"
    tradeoffs:
      - "Use CXDB's assigned context_id as the session ID — simple, but Orchestra has no control over the ID format"
      - "Generate a human-friendly session ID (short hash, slug) and store it as metadata in the first turn — more user-friendly but adds a mapping layer"
      - "Use a combination: CXDB context_id for internal tracking, human-readable short ID for CLI display"
    recommendation:
      text: "Use CXDB's context_id as the canonical session identifier. Generate a short display ID (e.g., first 6 chars of a UUID or hash) for CLI output and human reference, stored as a field in the PipelineLifecycle start turn. Map display ID → context_id via a CXDB turn query when needed."
      confidence: 4/5
    needs_context: []
    resolved: "DECIDED — Use CXDB context_id + short display ID in PipelineLifecycle start turn."

  - id: cxdb-api-endpoint-mapping
    question: "The CXDB HTTP API uses different endpoint paths than what the plan's CxdbClient interface implies. How should the client be structured?"
    tradeoffs:
      - "The plan's CxdbClient.create_context() maps to POST /v1/contexts/create (not POST /v1/contexts)"
      - "The plan's append_turn() maps to POST /v1/contexts/:id/append (not POST /v1/contexts/:id/turns)"
      - "The plan's get_turns() maps to GET /v1/contexts/:id/turns (this one matches)"
      - "Health check is GET /health"
      - "Type bundle publish is PUT /v1/registry/bundles/:bundle_id"
    recommendation:
      text: "The prerequisite step already calls for CXDB API verification. The CxdbClient implementation should match the actual API (documented above). The plan's interface signatures are correct in spirit — just the underlying HTTP paths need adjustment. This is minor and already anticipated by the prerequisite."
      confidence: 5/5
    needs_context: []

  - id: cxdb-type-registry-field-tags
    question: "CXDB's type registry uses numeric field tags (msgpack), not named keys. The plan shows JSON payloads with named fields. How should Orchestra encode turn payloads?"
    tradeoffs:
      - "CXDB's HTTP API accepts JSON with named fields in the 'data' object and converts to msgpack internally — the HTTP gateway handles the translation"
      - "For maximum control, Orchestra could use the binary protocol with explicit numeric tags — higher performance but more complex client"
      - "The HTTP API's 'data' field accepts plain JSON objects; the server uses the type registry to map field names to tags during encoding"
    recommendation:
      text: "Use the HTTP API exclusively for Stage 1. The HTTP gateway accepts JSON payloads with named fields and handles msgpack conversion internally. The type registry bundle must define numeric tags → field name mappings so the server can encode/decode. This is the documented approach for non-Go clients."
      confidence: 5/5
    needs_context: []

  - id: cxdb-unavailability-behavior
    question: "The plan states 'orchestra run without CXDB exits non-zero with clear error.' Should this be a hard requirement (fail fast) or should there be a degraded mode?"
    tradeoffs:
      - "Fail fast (plan's current position): simple, CXDB is a stated requirement, no ambiguity about what happened"
      - "Degraded mode (log to stdout only): more developer-friendly for quick iteration, but creates a second code path and undermines CXDB-first principle"
    recommendation:
      text: "Fail fast, as the plan states. The stages README explicitly says 'CXDB from Stage 1' and 'no local run directory, SQLite database, or JSON checkpoint files.' A degraded mode would violate this principle and add maintenance burden. The CXDB Docker command is simple and orchestra doctor provides clear diagnostics."
      confidence: 5/5
    needs_context: []

  - id: lark-grammar-fidelity
    question: "The attractor BNF grammar needs translation to Lark EBNF. How should edge cases in the translation be handled?"
    tradeoffs:
      - "Translate the BNF mechanically and test against the attractor spec's examples — high fidelity but may miss undocumented edge cases"
      - "Start with a simpler grammar that handles the Stage 1 test cases, then expand — faster to build but may need rework"
    recommendation:
      text: "Translate the full attractor BNF to Lark EBNF upfront. The grammar is well-specified (Section 2.2) and Lark's EBNF is very close to BNF. Test against all the DOT parsing test cases in the plan. The grammar handles the full subset even though Stage 1 only exercises linear pipelines — this avoids parser rework in later stages."
      confidence: 5/5
    needs_context: []

  - id: event-observer-pattern
    question: "The plan says events are 'both printed to stdout (observer pattern) AND appended as typed CXDB turns.' What is the observer registration/dispatch mechanism?"
    tradeoffs:
      - "Simple callback list: engine holds a list of callables, calls each on event emission — simple, synchronous, easy to test"
      - "Python Protocol/ABC: define an EventObserver protocol, register implementations — more structured, better for type checking"
      - "Event bus / pub-sub: decoupled producers and consumers — more complex, useful for async but overkill for Stage 1"
    recommendation:
      text: "Use a simple Protocol (typing.Protocol) for EventObserver with a single on_event(event: Event) method. Register two observers: StdoutObserver (prints formatted events) and CxdbObserver (appends typed turns). This is clean, testable, and extensible for later stages without being over-engineered."
      confidence: 4/5
    needs_context: []
    resolved: "DECIDED — Use typing.Protocol with on_event() method."

  - id: graph-model-representation
    question: "What Python data structures should represent the in-memory graph model after parsing?"
    tradeoffs:
      - "Dataclasses: simple, typed, no dependencies — good for a clean domain model"
      - "Pydantic models: validation built in, serialization for free — adds a dependency but reduces boilerplate"
      - "NetworkX graph: rich graph algorithms available — heavy dependency for what is mostly traversal"
    recommendation:
      text: "Use Python dataclasses for the graph model (PipelineGraph, Node, Edge). The graph is simple enough that NetworkX is overkill, and Pydantic adds an unnecessary dependency. Dataclasses with a few helper methods (get_outgoing_edges, get_node, etc.) are sufficient and keep the dependency footprint minimal."
      confidence: 4/5
    needs_context: []
    resolved: "DECIDED — Use Pydantic models. Validation and serialization are worth the dependency."

  - id: config-file-parsing
    question: "The plan specifies orchestra.yaml discovery (CWD → parent directories → defaults). Should the config model be validated?"
    tradeoffs:
      - "Minimal parsing: load YAML, access keys directly — simple but fragile"
      - "Typed config model: dataclass or Pydantic model with defaults — safer, better error messages"
    recommendation:
      text: "Use a simple dataclass for the config model with defaults. Stage 1 only needs cxdb.url — the config is minimal. Use pyyaml to load and validate the structure. Expand the config model in later stages."
      confidence: 4/5
    needs_context: []
    resolved: "DECIDED — Use Pydantic for config model as well (consistent with graph model decision). Validation and defaults handled natively."
</decision-points>

---

<success-criteria>
success_criteria:
  - id: dot-parse-linear
    description: "A simple linear pipeline DOT file parses into a correct in-memory graph model"
    command: "uv run pytest tests/ -k 'test_parse_simple_linear' -v"
    expected: "Test passes; graph has correct nodes, edges, and attributes"
    automated: true

  - id: dot-parse-full-subset
    description: "All DOT parsing test cases pass (attributes, chained edges, defaults, subgraphs, comments, value types, rejection cases)"
    command: "uv run pytest tests/ -k 'dot_parsing' -v"
    expected: "All 11 parsing tests pass"
    automated: true

  - id: validation-catches-errors
    description: "Graph validation catches missing start/exit, unreachable nodes, invalid edges, and produces actionable diagnostics"
    command: "uv run pytest tests/ -k 'validation' -v"
    expected: "All 8 validation tests pass with correct severity levels and messages"
    automated: true

  - id: execution-linear
    description: "Linear pipeline executes from start to exit in simulation mode with correct event sequence"
    command: "uv run pytest tests/ -k 'execution' -v"
    expected: "All 6 execution tests pass; events emitted in correct order; simulation responses match expected format"
    automated: true

  - id: cxdb-storage
    description: "Pipeline execution creates CXDB context, appends typed turns, and maintains correct turn order"
    command: "uv run pytest tests/ -k 'cxdb_storage' -v"
    expected: "All 9 CXDB storage tests pass against a real CXDB instance"
    automated: true
    notes: "Requires CXDB Docker container running"

  - id: cli-compile-valid
    description: "orchestra compile on a valid pipeline exits 0 and prints graph structure"
    command: "uv run orchestra compile tests/fixtures/test-linear.dot"
    expected: "Exit code 0; output includes node count, edge count, and graph goal"
    automated: true

  - id: cli-compile-invalid
    description: "orchestra compile on an invalid pipeline exits non-zero with diagnostics"
    command: "uv run orchestra compile tests/fixtures/test-invalid.dot; echo $?"
    expected: "Exit code non-zero; output includes ERROR diagnostics with rule names and suggested fixes"
    automated: true

  - id: cli-run-e2e
    description: "orchestra run executes a linear pipeline end-to-end, printing events and persisting to CXDB"
    command: "uv run orchestra run tests/fixtures/test-linear.dot"
    expected: "Exit code 0; stdout shows PipelineStarted → StageStarted/Completed per node → PipelineCompleted; CXDB context created with typed turns"
    automated: true
    notes: "Requires CXDB Docker container running"

  - id: cli-doctor
    description: "orchestra doctor reports CXDB connectivity and type registry status"
    command: "uv run orchestra doctor"
    expected: "Exit code 0; output reports CXDB healthy and type bundle registered"
    automated: true
    notes: "Requires CXDB Docker container running"

  - id: cxdb-unavailable-error
    description: "orchestra run without CXDB exits non-zero with clear error message"
    command: "CXDB_URL=http://localhost:99999 uv run orchestra run tests/fixtures/test-linear.dot; echo $?"
    expected: "Exit code non-zero; error message mentions CXDB connectivity and suggests running orchestra doctor"
    automated: true

  - id: all-tests-pass
    description: "Full test suite passes"
    command: "uv run pytest tests/ -v"
    expected: "Exit code 0; 0 failures"
    automated: true
    notes: "Requires CXDB Docker container running for integration tests"

  - id: manual-cxdb-inspection
    description: "After running a pipeline, the CXDB UI shows the execution trace with typed, structured turn payloads"
    expected: |
      Human verifies in CXDB UI (http://localhost:9010):
      - Context appears for the pipeline run
      - Turn chain shows PipelineLifecycle, NodeExecution, and Checkpoint turns
      - NodeExecution turns show prompt, response, outcome, and node_id in structured payload
      - Checkpoint turns show current_node, completed_nodes, and context snapshot
    automated: false

evaluation_dependencies:
  - Python 3.11+ with uv
  - CXDB Docker container (docker run -p 9009:9009 -p 9010:9010 cxdb/cxdb:latest)
  - pytest test framework
  - Typer CLI framework
  - Lark parser toolkit
  - httpx HTTP client
</success-criteria>

---

<missing-context>
missing_context:
  - category: technical
    items:
      - id: cxdb-http-api-append-path
        question: "The CXDB append turn endpoint is POST /v1/contexts/:id/append (not /turns). Has this been verified against a running instance?"
        why_it_matters: "The CxdbClient implementation must use the correct endpoint paths."
        how_to_resolve: "RESOLVED — CXDB HTTP API documentation verified. Plan updated with correct endpoint mapping."
        status: resolved

      - id: cxdb-type-bundle-field-format
        question: "CXDB type registry bundles use numeric field tags as keys. How are Orchestra's types defined in the registry?"
        why_it_matters: "The type bundle must be published in CXDB's expected format with numeric tags."
        how_to_resolve: "RESOLVED — see additional-context section for the complete type bundle definition with numeric tags."
        status: resolved

      - id: cxdb-docker-image-tag
        question: "Is cxdb/cxdb:latest the correct Docker image tag?"
        why_it_matters: "If the image tag is wrong, CI and local dev cannot start CXDB."
        how_to_resolve: "UNRESOLVED — needs verification before implementation. Run 'docker pull cxdb/cxdb:latest'. If unavailable, build from source."
        status: unresolved

      - id: attractor-bnf-to-lark
        question: "Has the attractor BNF grammar (Section 2.2) been validated for direct Lark EBNF translation?"
        why_it_matters: "Lark uses a slightly different syntax than BNF. The translation needs care."
        how_to_resolve: "UNRESOLVED — prototype the Lark grammar during implementation step 3. The attractor BNF is well-defined and Lark EBNF is close."
        status: unresolved
</missing-context>

---

<additional-context>

## CXDB HTTP API — Verified Endpoint Mapping

The following endpoint mapping is verified against the CXDB HTTP API documentation (https://github.com/strongdm/cxdb/blob/main/docs/http-api.md):

| Plan's CxdbClient Method | Actual CXDB Endpoint | Notes |
|--------------------------|---------------------|-------|
| `create_context(base_turn_id)` | `POST /v1/contexts/create` | Body: `{"base_turn_id": "0"}` |
| `fork_context(base_turn_id)` | `POST /v1/contexts/fork` | Body: `{"base_turn_id": "42"}` |
| `append_turn(context_id, ...)` | `POST /v1/contexts/:id/append` | Body: `{"type_id": "...", "type_version": 1, "data": {...}}` |
| `get_turns(context_id, limit)` | `GET /v1/contexts/:id/turns` | Query: `?limit=64&view=typed` |
| `list_contexts()` | `GET /v1/contexts` | Query: `?limit=100&offset=0` |
| `publish_type_bundle(bundle_id, bundle)` | `PUT /v1/registry/bundles/:bundle_id` | Body: registry bundle JSON with numeric field tags |
| `health_check()` | `GET /health` | Response: `{"status": "ok", ...}` |

### CXDB Context ID Format

CXDB context IDs are **server-assigned monotonic u64 integers** (returned as strings in JSON). They are NOT UUIDs. The plan's test `"context_id matches session_id"` needs to account for this — Orchestra should either:
1. Use the CXDB context_id directly as the session identifier, or
2. Generate a human-friendly display ID and store it in the PipelineLifecycle start turn

### CXDB Type Bundle Format

Orchestra's type bundle must use numeric field tags. Example for `dev.orchestra.PipelineLifecycle`:

```json
{
  "registry_version": 1,
  "bundle_id": "dev.orchestra.v1",
  "types": {
    "dev.orchestra.PipelineLifecycle": {
      "versions": {
        "1": {
          "fields": {
            "1": {"name": "pipeline_name", "type": "string"},
            "2": {"name": "goal", "type": "string", "optional": true},
            "3": {"name": "status", "type": "string"},
            "4": {"name": "duration_ms", "type": "u64", "optional": true, "semantic": "unix_ms"},
            "5": {"name": "error", "type": "string", "optional": true},
            "6": {"name": "session_display_id", "type": "string", "optional": true}
          }
        }
      }
    },
    "dev.orchestra.NodeExecution": {
      "versions": {
        "1": {
          "fields": {
            "1": {"name": "node_id", "type": "string"},
            "2": {"name": "handler_type", "type": "string"},
            "3": {"name": "status", "type": "string"},
            "4": {"name": "prompt", "type": "string", "optional": true},
            "5": {"name": "response", "type": "string", "optional": true},
            "6": {"name": "outcome", "type": "string", "optional": true},
            "7": {"name": "duration_ms", "type": "u64", "optional": true}
          }
        }
      }
    },
    "dev.orchestra.Checkpoint": {
      "versions": {
        "1": {
          "fields": {
            "1": {"name": "current_node", "type": "string"},
            "2": {"name": "completed_nodes", "type": "array", "items": "string"},
            "3": {"name": "context_snapshot", "type": "map"},
            "4": {"name": "retry_counters", "type": "map", "optional": true}
          }
        }
      }
    }
  }
}
```

The HTTP append endpoint accepts **named JSON fields** in the `data` object and uses the registry to encode to msgpack. This means Orchestra can write turns with human-readable field names, as long as the type bundle is published first.

</additional-context>
