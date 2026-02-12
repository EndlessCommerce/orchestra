# Goal Evaluation: Stage 2a — Control Flow

## Goal Summary

Extend the pipeline engine with the full attractor spec control flow: the 5-step edge selection algorithm (adding condition matching, preferred labels, and suggested next IDs to the existing weight + lexical tiebreak), a condition expression language parser/evaluator, retry policies with configurable backoff, goal gate enforcement at exit, and failure routing. All tested in simulation mode with a configurable simulation backend that returns specific outcomes per node.

After this stage, pipelines can branch, retry, enforce critical gates, and route failures — all without LLM calls.

---

<estimates>
ambiguity:
  rating: 1/5
  rationale:
    - "Every component maps directly to a named attractor spec section with pseudocode (Sections 3.3-3.7, 10)"
    - "The condition expression grammar is formally specified in BNF (Section 10.2)"
    - "The 5-step edge selection algorithm has an explicit priority order and pseudocode"
    - "Backoff policies are enumerated with exact numeric parameters (initial_delay, factor, max_delay)"
    - "All 23 test cases are specified with inputs and expected behavior"
    - "Scope is explicit: included vs excluded sections with stage references"
    - "Builds on a well-understood Stage 1 codebase (68 passing tests, clean architecture)"

complexity:
  rating: 2/5
  rationale:
    - "Condition expression parser is a small DSL — the grammar has only 6 productions and 2 operators"
    - "Edge selection is extending an existing function with 3 new steps prepended to 2 existing steps"
    - "Retry system is a new wrapper around the existing handler.handle() call — isolated concern"
    - "Goal gate enforcement is a new check at the exit point — single function"
    - "Failure routing is a new fallback chain after node failure — 4-step priority list"
    - "Each component is independently simple; the wiring into the existing runner is the main integration challenge"
    - "The existing runner.py is ~137 lines — the modifications are well-scoped"

size:
  rating: 2/5
  loc_estimate: 600-900
  worker_estimate: "1"
</estimates>

---

<decision-points>
decision_points:
  - id: condition-parser-implementation
    question: "Should the condition expression parser use Lark (already a dependency) or be hand-written?"
    tradeoffs:
      - "Lark: consistent with the DOT parser, formal grammar, good error messages, but the condition language is tiny (6 productions)"
      - "Hand-written: simpler for such a small grammar, fewer dependencies on Lark internals, but less formal"
      - "Regex-based split: quick to implement, handles the && split and key=value parsing, but fragile for edge cases"
    recommendation:
      text: "Hand-write the condition parser. The grammar is trivially simple (split on '&&', then parse each 'key op value' clause). Lark is overkill for 2 operators and no nesting. A hand-written parser is ~30-40 lines, easy to test, and avoids coupling to Lark internals."
      confidence: 4/5
    needs_context: []
    resolved: "DECIDED — Use Lark grammar. Consistency with DOT parser and formal error messages preferred over minimalism."

  - id: retry-backoff-policy-source
    question: "How should backoff policies be resolved — from the node attribute 'backoff_policy' name, from explicit node attributes (initial_delay, backoff_factor), or both?"
    tradeoffs:
      - "Named presets only (standard, aggressive, etc.): simple, matches the plan's language, but inflexible"
      - "Explicit attributes only: fully configurable per-node, but verbose"
      - "Named presets with attribute overrides: flexible, matches the spec's preset table, allows per-node customization"
    recommendation:
      text: "Use named presets. The attractor spec defines 5 preset policies with specific parameters. Per-node customization beyond the presets is not specified in the plan and adds unnecessary complexity for Stage 2a."
      confidence: 4/5
    needs_context: []
    resolved: "DECIDED — Use dict of node_id -> [OutcomeStatus] sequence. Pop next on each call."

  - id: configurable-simulation-backend
    question: "The plan requires a 'configurable simulation backend that can return specific outcomes per node (e.g., FAIL twice then SUCCESS).' How should this be implemented?"
    tradeoffs:
      - "Dict mapping node_id → list of outcomes: simple, deterministic, easy to set up in tests"
      - "Callback function per node: more flexible but harder to reason about"
      - "Extend the existing SimulationCodergenHandler with a configurable outcome sequence: reuses existing handler pattern"
    recommendation:
      text: "Extend SimulationCodergenHandler to accept a dict of node_id → list of OutcomeStatus. On each call, pop the next status from the list; if exhausted, return the last status. This keeps the handler pattern clean and is trivially testable."
      confidence: 5/5
    needs_context: []
    resolved: "DECIDED — Use outcome sequence dict approach."

  - id: runner-refactoring-approach
    question: "The existing PipelineRunner.run() is a single while loop. Should control flow features be added inline, or should the runner be refactored into smaller methods?"
    tradeoffs:
      - "Inline additions: faster to implement, but the run() method grows to ~200+ lines"
      - "Extract methods: cleaner (execute_node, handle_failure, check_goal_gates, execute_with_retry), easier to test, but requires refactoring working code"
    recommendation:
      text: "Extract methods. The plan adds 4 distinct concerns (retry loop, failure routing, goal gate check, full edge selection). Each maps to a named function in the spec pseudocode. The current run() is already 107 lines — adding all features inline would make it unwieldy."
      confidence: 5/5
    needs_context: []
    resolved: "DECIDED — Extract methods: execute_with_retry(), handle_failure(), check_goal_gates(). Matches spec pseudocode."

  - id: jitter-implementation
    question: "The spec says jitter adds 'random_uniform(0.5, 1.5)' multiplier. Should this be truly random or seedable for deterministic tests?"
    tradeoffs:
      - "Truly random: matches production behavior but makes delay assertions flaky"
      - "Seedable via dependency injection: deterministic in tests, real randomness in production"
    recommendation:
      text: "Use Python's random module with an optional seed parameter on the retry policy or a random.Random instance injection. Tests seed for determinism; production uses default randomness. This is a standard pattern."
      confidence: 5/5
    needs_context: []

  - id: conditional-handler-shape
    question: "The plan mentions a 'Conditional Handler: No-op handler for diamond-shaped nodes.' What shape attribute maps to diamond nodes?"
    tradeoffs:
      - "Use 'diamond' as the shape attribute — clear, but may not match DOT conventions"
      - "Use DOT's standard shape name for diamonds — DOT uses 'diamond' as a valid shape"
    recommendation:
      text: "Use shape='diamond' in the handler registry. DOT supports 'diamond' as a built-in shape. The conditional handler is a no-op (routing is handled by edge selection, not the handler), so it just returns SUCCESS."
      confidence: 5/5
    needs_context: []

  - id: goal-gate-rerouting-cycle-detection
    question: "When goal gate enforcement reroutes to a retry_target, could this create an infinite loop if the retry target leads back to the same unsatisfied gate?"
    tradeoffs:
      - "No cycle detection: simpler, but could hang indefinitely"
      - "Max reroute count: pragmatic limit (e.g., 3 reroutes per goal gate), prevents infinite loops"
      - "Track reroute history: detect repeated reroute to same target, fail on cycle"
    recommendation:
      text: "The spec's default_max_retry graph attribute (default 50) effectively limits total node executions. Add a max reroute counter (default = graph's default_max_retry) to prevent infinite loops. If exceeded, fail the pipeline with a clear error."
      confidence: 4/5
    needs_context: []
    resolved: "DECIDED — Use max reroute counter (default = graph's default_max_retry, typically 50). Fail pipeline with clear error if exceeded."
</decision-points>

---

## Success Criteria

The plan provides explicit success criteria (7 items, all testable). Rating: **A-**

The criteria are comprehensive but could be strengthened with specific test commands. Suggested A-grade criteria:

<success-criteria>
success_criteria:
  - id: condition-parse-evaluate
    description: "Condition expressions parse and evaluate correctly for all operators (=, !=), conjunction (&&), and variable types (outcome, preferred_label, context.*)"
    command: "uv run pytest tests/ -k 'condition' -v"
    expected: "All 7 condition expression tests pass (=, !=, context.*, &&, missing key, empty condition, invalid syntax)"
    automated: true

  - id: edge-selection-5-step
    description: "5-step edge selection algorithm is deterministic and follows spec priority order"
    command: "uv run pytest tests/ -k 'edge_selection' -v"
    expected: "All 7 edge selection tests pass (condition match, preferred label, label normalization, suggested next IDs, weight, lexical, full priority chain)"
    automated: true

  - id: retry-system
    description: "Retry system respects max_retries, applies backoff with jitter, and handles exhaustion correctly"
    command: "uv run pytest tests/ -k 'retry' -v"
    expected: "All 6 retry tests pass (retry on FAIL, retry on RETRY, exhaustion, backoff delays, allow_partial, no retry on SUCCESS)"
    automated: true

  - id: goal-gate-enforcement
    description: "Goal gates prevent exit when critical nodes haven't succeeded, and reroute correctly"
    command: "uv run pytest tests/ -k 'goal_gate' -v"
    expected: "All 5 goal gate tests pass (satisfied, unsatisfied with retry_target, graph-level fallback, no target, partial satisfies)"
    automated: true

  - id: failure-routing
    description: "Failure routing follows the correct fallback chain"
    command: "uv run pytest tests/ -k 'failure_routing' -v"
    expected: "All 4 failure routing tests pass (fail edge, retry target, fallback retry target, pipeline termination)"
    automated: true

  - id: manual-branching-pipeline
    description: "A human can build a branching pipeline, run it, and observe correct routing"
    command: "uv run orchestra run tests/fixtures/test-branching.dot"
    expected: "Exit code 0; events show conditional routing (start -> do_work -> gate -> success -> exit, not failure path)"
    automated: true

  - id: backward-compatibility
    description: "All existing Stage 1 tests continue to pass unchanged"
    command: "uv run pytest tests/ -v"
    expected: "Exit code 0; all 68+ tests pass (Stage 1 tests unchanged + new Stage 2a tests)"
    automated: true

  - id: configurable-sim-backend
    description: "Simulation backend can return specific outcomes per node for test scenarios"
    command: "uv run pytest tests/ -k 'configurable_simulation' -v"
    expected: "Tests demonstrate node returning FAIL twice then SUCCESS, triggering retry logic"
    automated: true

evaluation_dependencies:
  - Python 3.11+ with uv
  - CXDB Docker container (for integration tests)
  - pytest test framework
  - Existing Stage 1 test suite (68 tests) as regression baseline
</success-criteria>

---

<missing-context>
missing_context: []
# No missing context — the goal is fully specified:
# - Attractor spec provides formal grammar, pseudocode, and named constants for every component
# - The Stage 1 codebase is complete and well-understood (68 tests, clean architecture)
# - The plan enumerates all 23 test cases with descriptions
# - Backoff policies are defined with exact numeric parameters
# - Scope boundaries are explicit (included vs excluded with stage references)
# - The existing edge_selection.py, runner.py, and handler patterns are clear extension points
</missing-context>
