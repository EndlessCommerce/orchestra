# Goal Evaluation: Stage 5 — Parallel Execution

## Goal Summary

Add concurrent multi-branch execution to the Orchestra pipeline engine. This involves implementing a parallel fan-out handler (`component` shape), a fan-in handler (`tripleoctagon` shape), join policies (wait_all, first_success, k_of_n, quorum), error policies (fail_fast, continue, ignore), context isolation for parallel branches, CXDB branch modeling, and parallel execution events. After this stage, pipelines can run multiple agents concurrently and consolidate their results.

---

<estimates>
ambiguity:
  rating: 2/5
  rationale:
    - "The plan is quite detailed — specifies exact node shapes (component, tripleoctagon), exact join/error policy names, context isolation semantics, and event types"
    - "Context behavior is explicit: branches get deep clones, changes NOT merged back, only fan-in outcome applied to parent"
    - "CXDB integration is specified: fork at fan-out turn, branch turns appended to forked context, fan-in references branch contexts"
    - "Some ambiguity remains around: the exact heuristic selection algorithm and the fan-in LLM evaluation prompt format"
    - "Most ambiguous decisions have now been resolved via evaluation (see Resolved Decisions below)"

complexity:
  rating: 4/5
  rationale:
    - "Concurrency is inherently complex — asyncio coordination, branch lifecycle management, cancellation"
    - "The runner's execution loop is currently synchronous and sequential; parallel execution uses asyncio.run() within the handler to keep runner changes minimal"
    - "Multiple interacting policies (join + error) create combinatorial behavior states"
    - "Graph pre-analysis for branch extraction adds upfront complexity but catches errors early"
    - "Fan-in consolidation with LLM evaluation introduces a handler that depends on branch results, which is a new execution pattern"
    - "Subgraph traversal within branches means branches can be multi-node chains — requires extracting and running sub-pipelines per branch"
    - "However, the existing handler registry pattern is clean and extensible, and the Context.snapshot() method provides a basis for cloning"

size:
  rating: 4/5
  loc_estimate: 800-1200
  worker_estimate: "3-4"
  rationale:
    - "New files: parallel_handler.py, fan_in_handler.py, join_policies.py, error_policies.py, graph_analysis.py, parallel event types"
    - "Modified files: registry.py, context.py (deep clone), events/types.py"
    - "Runner changes are minimal — parallel handler manages concurrency internally"
    - "Test files: 30+ test cases specified, ~500-700 lines of test code"
    - "Graph pre-analysis is the most code-heavy new component"
</estimates>

---

## Resolved Decisions

The following decisions were resolved during evaluation:

| Decision | Resolution |
|----------|-----------|
| **Concurrency model** | `asyncio.run()` inside the parallel handler. Runner stays synchronous. Contained async — zero impact on existing code. Nested parallel needs a workaround (detect existing event loop). |
| **Branch subgraph execution** | Graph pre-analysis. Walk the graph at fan-out time to extract per-branch subgraphs. Validates branch structure upfront (detects broken branches). Each branch runs as an independent sub-pipeline. |
| **Policy configuration** | Split across both nodes. `error_policy` + `max_parallel` on fan-out (component). `join_policy` + params (`k`, `quorum_fraction`) on fan-in (tripleoctagon). Most semantically precise. |
| **CXDB forking** | Optional. Parallel works without CXDB using in-memory context clones. CXDB forking is an enhancement when available. |

---

<decision-points>
decision_points:
  - id: async-execution-model
    question: Should parallel branches use asyncio tasks, threading, or multiprocessing?
    resolution: "asyncio.run() inside the parallel handler. Runner stays synchronous. Each branch runs as an asyncio.Task. Nested parallel requires detecting an existing event loop and using loop.create_task() instead."
    tradeoffs:
      - asyncio is natural for I/O-bound work (LLM API calls) and is the simplest concurrency model in Python
      - The existing runner is synchronous — asyncio.run() within the handler keeps changes contained
      - Nested parallel needs a workaround since asyncio.run() can't be called inside an existing event loop
      - Full async runner would be more future-proof but touches all existing code and tests

  - id: branch-subgraph-execution
    question: How should branch subgraph execution work for multi-node chains?
    resolution: "Graph pre-analysis. At fan-out time, walk the graph from each outgoing edge to the fan-in node, collecting all nodes and edges per branch. Build mini PipelineGraph objects per branch. Validates structure upfront."
    tradeoffs:
      - Pre-analysis catches broken branches early (branch that never reaches fan-in)
      - Most explicit — you know exactly what each branch contains before execution
      - More code than the modified-graph approach but more robust
      - Handles conditionals and shared nodes within branches explicitly

  - id: cancellation-mechanism
    question: How should branches be cancelled for first_success and fail_fast policies?
    resolution: "Cooperative cancellation via a shared flag checked between node executions in the branch sub-runner. For in-flight LLM calls, let them complete but discard results."
    tradeoffs:
      - asyncio.Task.cancel() is immediate but requires handlers to be cancellation-safe
      - Cooperative cancellation is safer — checked at natural boundaries between nodes
      - In-flight LLM calls can't be cheaply cancelled (cost implications)

  - id: policy-configuration
    question: How are join_policy and error_policy specified on parallel/fan-in nodes?
    resolution: "Split across both nodes. error_policy + max_parallel on the fan-out (component) node. join_policy + policy params (k, quorum_fraction) on the fan-in (tripleoctagon) node."
    tradeoffs:
      - Most semantically precise — each attribute lives where it acts
      - error_policy controls branch management (fan-out concern)
      - join_policy controls result collection (fan-in concern)
      - User must look at two nodes to understand full parallel behavior

  - id: context-deep-clone
    question: How should context be deep-cloned for branch isolation?
    resolution: "Use copy.deepcopy() on the context._data dict to create branch contexts."
    tradeoffs:
      - Simple and correct for JSON-serializable primitives (which context data is expected to be)
      - May fail on non-picklable objects but context_updates are dict-based

  - id: fan-in-heuristic-details
    question: What exactly is the heuristic selection algorithm for fan-in?
    resolution: "Rank by: (1) OutcomeStatus priority (SUCCESS > PARTIAL_SUCCESS > FAIL), (2) a numeric 'score' from context_updates if present, (3) alphabetical node ID as tiebreaker."
    tradeoffs:
      - Simple and deterministic
      - Branches can optionally self-report a score via context_updates

  - id: nested-parallel
    question: Should nested parallel (a branch containing another fan-out/fan-in) be supported?
    resolution: "Supported. Required two fixes: (1) find_fan_in_node BFS now continues through inner tripleoctagon nodes instead of stopping, using BFS distance to pick the nearest common fan-in. (2) Runner prioritizes suggested_next_ids for direct navigation to fan-in, bypassing edge selection. Nested asyncio works via run_in_executor threads."
    tradeoffs:
      - Graph analysis needed fix to traverse through inner tripleoctagon nodes
      - Runner needed fix to navigate directly to fan-in via suggested_next_ids (no direct edge exists from fan-out to fan-in)
      - Nested asyncio.run() works because branches execute in thread pool threads via run_in_executor

  - id: cxdb-fork-integration
    question: Should CXDB context forking be required or optional for parallel execution?
    resolution: "Optional. Parallel works without CXDB using in-memory context clones. When CXDB is available, additionally fork CXDB contexts for branch turn tracking."
    tradeoffs:
      - No hard dependency on CXDB for core functionality
      - Existing checkpoint/event system works without CXDB (events go to stdout observer)
</decision-points>

---

## Success Criteria

The plan provides explicit success criteria (10 checklist items). Grade: **B+**

The criteria are good but could be more specific about automation. Here are enhanced criteria:

<success-criteria>
success_criteria:
  - id: parallel-fan-out
    description: Parallel handler fans out to multiple branches concurrently — a component-shaped node with N outgoing edges spawns N concurrent branches
    command: pytest tests/ -k "test_fan_out" -v
    expected: Exit code 0, fan-out tests pass for 2 and 4 branches
    automated: true

  - id: fan-in-consolidation
    description: Fan-in handler waits for all branches and consolidates results using heuristic selection
    command: pytest tests/ -k "test_fan_in" -v
    expected: Exit code 0, fan-in correctly selects best outcome
    automated: true

  - id: context-isolation
    description: Parallel branches receive isolated context clones — mutations in one branch do not affect other branches or the parent context
    command: pytest tests/ -k "test_context_isolation" -v
    expected: Exit code 0, parent context unchanged after branch execution
    automated: true

  - id: join-policies
    description: All four join policies work correctly (wait_all, first_success, k_of_n, quorum)
    command: pytest tests/ -k "test_join_policy" -v
    expected: Exit code 0, all 6 join policy test cases pass
    automated: true

  - id: error-policies
    description: All three error policies work correctly (fail_fast, continue, ignore)
    command: pytest tests/ -k "test_error_policy" -v
    expected: Exit code 0, all 3 error policy test cases pass
    automated: true

  - id: bounded-parallelism
    description: max_parallel attribute limits concurrent branch execution
    command: pytest tests/ -k "test_bounded_parallelism" -v
    expected: Exit code 0, at most max_parallel branches execute concurrently
    automated: true

  - id: parallel-events
    description: Correct event sequence emitted (ParallelStarted → BranchStarted* → BranchCompleted* → ParallelCompleted) with accurate counts and timing
    command: pytest tests/ -k "test_parallel_event" -v
    expected: Exit code 0, event sequence and metadata validated
    automated: true

  - id: fan-in-llm-evaluation
    description: Fan-in node with a prompt uses LLM (mocked) to evaluate and select best branch result
    command: pytest tests/ -k "test_llm_evaluation" -v
    expected: Exit code 0, mocked LLM selects correct candidate
    automated: true

  - id: end-to-end-pipeline
    description: Full fan-out/fan-in pipeline executes correctly — start → fan_out → [A, B, C] → fan_in → synthesize → exit
    command: pytest tests/ -k "test_full_parallel_pipeline" -v
    expected: Exit code 0, all branches execute, fan-in consolidates, downstream nodes receive results
    automated: true

  - id: handler-registration
    description: component and tripleoctagon shapes are registered in the default handler registry
    command: pytest tests/ -k "test_registry" -v
    expected: Exit code 0, registry returns handlers for both shapes
    automated: true

  - id: nested-parallel
    description: Nested parallel (a branch containing its own fan-out/fan-in) works correctly
    command: pytest tests/test_parallel_integration.py::test_nested_parallel -v
    expected: Exit code 0, outer and inner parallel events emitted correctly
    automated: true

  - id: all-stage5-tests
    description: All Stage 5 automated tests pass (41 test cases)
    command: pytest tests/ -k "parallel or fan_in or fan_out" -v
    expected: Exit code 0, 0 failures, 41 tests collected
    automated: true

  - id: existing-tests-unbroken
    description: All existing tests (Stages 1-4) continue to pass — no regressions
    command: pytest tests/ -v
    expected: Exit code 0, 437 tests pass, 0 failures
    automated: true

evaluation_dependencies:
  - pytest
  - Existing SimulationBackend for branch execution
  - Existing RecordingEmitter pattern for event verification
  - asyncio (stdlib) for concurrent branch execution
</success-criteria>

---

<missing-context>
missing_context:
  - category: technical
    items:
      - id: async-in-codebase
        question: Is asyncio used anywhere in the current codebase, or is everything synchronous?
        why_it_matters: Determines whether asyncio.run() in the handler is the first async usage or fits an existing pattern
        how_to_resolve: Search codebase for async/await keywords
        status: "Resolved — codebase is fully synchronous except for asyncio.run() in the parallel handler, which is the first and only async entry point. All 40 parallel tests pass."

      - id: cxdb-fork-api
        question: Does the CXDB binary protocol support context forking (creating a new context branched from a specific turn)?
        why_it_matters: The plan specifies CXDB branch modeling — create_context(base_turn_id) appears to support forking but needs verification
        how_to_resolve: Check CXDB documentation or test with actual CXDB instance
        status: "Resolved — CXDB integration is optional and implemented. create_context(base_turn_id) used for forking. ParallelExecution turns persisted. 2 CXDB-specific tests pass."
</missing-context>

---

<additional-context>
## Resolved Context from Codebase Exploration

### Architecture Foundation
The existing codebase provides a clean foundation for parallel execution:

1. **Handler Registry** (`handlers/registry.py`): Simple shape→handler mapping. Adding `component` and `tripleoctagon` handlers follows the established pattern.

2. **PipelineRunner** (`engine/runner.py`): Sequential `_execute_loop` with a `while True` pattern. The parallel handler manages concurrency internally via `asyncio.run()`, so runner changes are minimal. Key method: `_execute_node()` handles retry, events, and context updates — this is reusable for branch execution within extracted subgraphs.

3. **Context** (`models/context.py`): Minimal class with `get/set/snapshot`. `snapshot()` returns a shallow dict copy. `copy.deepcopy()` on `_data` will provide branch isolation.

4. **Event System** (`events/types.py`): Pydantic event models emitted via `EventEmitter.emit()`. New parallel event types (ParallelStarted, ParallelBranchStarted, ParallelBranchCompleted, ParallelCompleted) need to be added and registered in `EVENT_TYPE_MAP`.

5. **CXDB Client** (`storage/cxdb_client.py`): `create_context(base_turn_id)` supports creating a context forked from a specific turn. CXDB integration is optional — parallel execution works without it.

6. **Graph Model** (`models/graph.py`): `get_outgoing_edges(node_id)` discovers branch targets from fan-out. `get_incoming_edges(node_id)` can locate the fan-in node. Graph pre-analysis will use these methods to extract per-branch subgraphs.

### Existing Patterns to Follow
- Handlers implement `handle(node, context, graph) → Outcome`
- Event emission via `self._emitter.emit(event_type, **data)`
- Test fixtures use DOT files in `tests/fixtures/`
- SimulationBackend with `outcome_sequences` for deterministic testing
- RecordingEmitter for event sequence verification

### Key Design Decisions Summary
- **Concurrency**: `asyncio.run()` contained in parallel handler. Runner stays sync.
- **Branch execution**: Graph pre-analysis extracts per-branch subgraphs upfront.
- **Policy placement**: Split — error_policy + max_parallel on fan-out, join_policy on fan-in.
- **CXDB**: Optional enhancement, not required for parallel execution.
- **Cancellation**: Cooperative flag between node executions.
- **Context isolation**: `copy.deepcopy()` on context data.
- **Nested parallel**: Supported after fixes to graph analysis (BFS traversal through inner tripleoctagon nodes) and runner (direct navigation via suggested_next_ids).
</additional-context>

---

## Completion Status

**Stage 5 is COMPLETE.** All success criteria met. Verified 2026-02-13.

- 437 total tests pass (41 parallel-specific), 0 failures, 0 regressions
- All missing context items resolved
- Nested parallel support added and tested (required fixes to graph_analysis.py and runner.py)
- All 10 success criteria checked off in plan.md
