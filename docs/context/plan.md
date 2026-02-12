# Stage 2a: Control Flow — Implementation Plan

## Plan

- [x] Add condition expression parser using Lark
  - [x] Create `src/orchestra/conditions/grammar.lark` with the condition expression grammar (Section 10.2): `ConditionExpr ::= Clause ('&&' Clause)*`, `Clause ::= Key Operator Literal`, operators `=` and `!=`, keys `outcome`, `preferred_label`, `context.*`
  - [x] Create `src/orchestra/conditions/evaluator.py` with `parse_condition(expr: str)` and `evaluate_condition(expr: str, outcome: Outcome, context: Context) -> bool`. Implement `resolve_key()` for outcome, preferred_label, and context.* variable resolution. Missing context keys resolve to empty string. Empty condition always returns true.
  - [x] Add `condition_syntax` validation to `src/orchestra/validation/rules.py` — parse all edge conditions during validation and report syntax errors as ERROR diagnostics
  - [x] Write tests in `tests/test_conditions.py`: parse `outcome=success`, `outcome!=success`, `context.key=value`, `&&` conjunction, missing context key, empty condition, invalid syntax (7 tests per plan)
  - [x] Mark TODO complete and commit the changes to git

- [x] Extend edge selection with steps 1-3 (condition match, preferred label, suggested next IDs)
  - [x] Update `src/orchestra/engine/edge_selection.py` to implement the full 5-step algorithm: (1) evaluate condition expressions on edges, select first matching conditional edge; (2) if outcome has preferred_label, find edge with matching label after normalization (lowercase, trim, strip accelerator prefixes like `[Y] `, `Y) `, `Y - `); (3) if outcome has suggested_next_ids, find edge whose target is in the list; (4) highest weight among unconditional edges; (5) lexical tiebreak
  - [x] Update existing edge selection test `test_unconditional_preferred_over_conditional` — the semantics change: with condition evaluation, conditional edges that *match* now win over unconditional edges (Step 1 beats Step 4). This test used invalid condition syntax (`outcome == success` with spaces), so it should be updated to use valid syntax and test the correct behavior.
  - [x] Write tests in `tests/test_edge_selection.py`: condition match wins, preferred label match, label normalization (`[Y] Yes` → `yes`), suggested next IDs, full priority chain (all 5 steps in one graph). Keep existing weight tiebreak, lexical tiebreak, and no-edges tests.
  - [x] Mark TODO complete and commit the changes to git

- [x] Add conditional (diamond) handler
  - [x] Create `src/orchestra/handlers/conditional.py` — no-op handler for `shape=diamond` nodes. Returns SUCCESS (routing is handled by edge selection, not the handler).
  - [x] Register in `src/orchestra/handlers/registry.py` `default_registry()`: `registry.register("diamond", ConditionalHandler())`
  - [x] Mark TODO complete and commit the changes to git

- [x] Add configurable simulation backend for testing retries
  - [x] Extend `src/orchestra/handlers/codergen.py` `SimulationCodergenHandler` to accept an optional `outcome_sequences: dict[str, list[OutcomeStatus]]`. On each `handle()` call for a node_id, pop the next status from the list. If the list is exhausted, use the last status. If no sequence for a node_id, return SUCCESS as before.
  - [x] Write test in `tests/test_configurable_simulation.py` verifying: node returns FAIL twice then SUCCESS when sequence is `[FAIL, FAIL, SUCCESS]`; node without sequence returns SUCCESS; exhausted sequence returns last status
  - [x] Mark TODO complete and commit the changes to git

- [x] Implement retry system with backoff policies
  - [x] Create `src/orchestra/engine/retry.py` with: `BackoffConfig` dataclass (initial_delay_ms, backoff_factor, max_delay_ms, jitter), `RetryPolicy` dataclass (max_attempts, backoff), preset policies dict (`none`, `standard`, `aggressive`, `linear`, `patient` with exact parameters from spec), `calculate_delay(config, attempt, rng)` function, `execute_with_retry(node, handler, context, graph, policy, emitter, rng) -> Outcome` function
  - [x] Add `StageRetrying` event type to `src/orchestra/events/types.py` with fields: node_id, attempt, max_attempts, delay_ms
  - [x] Integrate into `src/orchestra/engine/runner.py`: extract `_execute_node()` method, wrap handler.handle() call with retry loop. Resolve retry policy from node attributes: `max_retries` (default 0, also respect graph-level `default_max_retry`), `backoff_policy` name (default `standard`), `allow_partial` (default false). Pass seedable `random.Random` instance for jitter determinism in tests.
  - [x] Write tests in `tests/test_retry.py`: retry on FAIL (node with max_retries=2 retried twice), retry on RETRY status, retry exhaustion (final outcome used for routing), backoff delays (standard policy: ~200ms, ~400ms, ~800ms within tolerance), allow_partial (PARTIAL_SUCCESS when retries exhausted), no retry on SUCCESS (6 tests per plan)
  - [x] Mark TODO complete and commit the changes to git

- [x] Implement failure routing
  - [x] Create `src/orchestra/engine/failure_routing.py` with `resolve_failure_target(node, graph) -> str | None` implementing the 4-step fallback chain: (1) outgoing edge with `condition="outcome=fail"` — use condition evaluator; (2) node attribute `retry_target`; (3) node attribute `fallback_retry_target`; (4) return None (pipeline terminates)
  - [x] Integrate into `src/orchestra/engine/runner.py`: after retry exhaustion with FAIL outcome, call `resolve_failure_target()`. If a target is found, set `current_node` to that target and continue the loop. If None, emit PipelineFailed and return.
  - [x] Write tests in `tests/test_failure_routing.py`: fail edge followed, retry_target used when no fail edge, fallback_retry_target used when no retry_target, pipeline termination when no failure route (4 tests per plan)
  - [x] Mark TODO complete and commit the changes to git

- [ ] Implement goal gate enforcement
  - [ ] Create `src/orchestra/engine/goal_gates.py` with `check_goal_gates(visited_outcomes: dict[str, OutcomeStatus], graph: PipelineGraph) -> str | None` — iterate visited nodes with `goal_gate=true` attribute, check if their outcome is SUCCESS or PARTIAL_SUCCESS. If any unsatisfied, return the reroute target: node's `retry_target` → node's `fallback_retry_target` → graph's `retry_target` → graph's `fallback_retry_target` → None (fail). Include max reroute counter (default = graph's `default_max_retry` or 50) to prevent infinite loops.
  - [ ] Integrate into `src/orchestra/engine/runner.py`: when reaching an exit node (shape=Msquare), call `check_goal_gates()` before exiting. If a reroute target is returned, set `current_node` to that target and continue the loop. If None and gates unsatisfied, emit PipelineFailed.
  - [ ] Write tests in `tests/test_goal_gates.py`: gate satisfied (exit normally), gate unsatisfied with retry_target (reroute), gate unsatisfied with graph-level retry_target (fallback), gate unsatisfied no target (pipeline fails), partial success satisfies gate (5 tests per plan)
  - [ ] Mark TODO complete and commit the changes to git

- [ ] Refactor PipelineRunner.run() into extracted methods
  - [ ] Extract `_execute_node()` — handles a single node: get handler, emit StageStarted, call execute_with_retry, update context, emit StageCompleted/StageFailed, emit CheckpointSaved
  - [ ] Extract `_handle_node_failure()` — calls failure routing, returns next node or None
  - [ ] Extract `_check_exit_gates()` — calls goal gate enforcement at exit, returns next node or None
  - [ ] Track `visited_outcomes: dict[str, OutcomeStatus]` for goal gate checking
  - [ ] Track `retry_counters: dict[str, int]` for checkpoint state
  - [ ] Track `reroute_count: int` for cycle protection
  - [ ] Verify all 68 existing Stage 1 tests still pass after refactoring
  - [ ] Mark TODO complete and commit the changes to git

- [ ] Add test fixtures for manual testing
  - [ ] Create `tests/fixtures/test-branching.dot` — the conditional branching pipeline from the Stage 2a plan (start → do_work → gate → success/failure → exit)
  - [ ] Create `tests/fixtures/test-retry.dot` — a pipeline with a node configured with `max_retries=2` for testing retry behavior
  - [ ] Verify `orchestra run tests/fixtures/test-branching.dot` works end-to-end
  - [ ] Mark TODO complete and commit the changes to git

- [ ] Identify all specs that need to be run and updated
  - [ ] Look at all previous TODOs and changes in git to identify changes
  - [ ] Run full test suite: `uv run pytest tests/ -v` and verify all tests pass (68 existing + new Stage 2a tests)
  - [ ] Identify any specs that failed and add a new TODO to fix them
  - [ ] Identify any missing spec coverage — check that all 23 test cases from the Stage 2a plan are covered
  - [ ] Mark TODO complete and commit the changes to git

- [ ] Identify any code that is unused, or could be cleaned up
  - [ ] Look at all previous TODOs and changes in git to identify changes
  - [ ] Identify any code that is no longer used, and remove it
  - [ ] Identify any unnecessary comments, and remove them (comments that explain "what" for a single line of code)
  - [ ] If there are any obvious code smells of redundant code, add TODOs below to address them
  - [ ] Mark TODO complete and commit the changes to git
