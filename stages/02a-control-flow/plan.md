# Stage 2a: Control Flow

## Overview

Extend the pipeline engine with the full attractor spec control flow: conditional routing via the 5-step edge selection algorithm, the condition expression language, retry policies with backoff, goal gate enforcement, and failure routing.

After this stage, the execution engine handles branching, retries, and critical gate enforcement. Pipelines can take different paths based on node outcomes. Persistence (resume, sessions, replay) is deferred to Stage 2b.

## What a Human Can Do After This Stage

1. Build pipelines with conditional branches (diamond nodes with conditions on edges)
2. Observe retries when a node fails — see backoff delays and retry counts in stdout events
3. See goal gate enforcement — pipeline refuses to exit when critical nodes haven't succeeded
4. Watch failure routing — failed nodes route to retry targets or fail edges

## Prerequisites

- Stage 1 complete (DOT parsing, validation, linear execution, CLI)

## Scope

### Included

- **Condition Expression Language.** Parse and evaluate boolean expressions on edges per attractor Section 10: `=`, `!=` operators, `&&` conjunction, `outcome`, `preferred_label`, and `context.*` variable resolution. Empty conditions always evaluate to true.
- **5-Step Edge Selection Algorithm.** Per attractor Section 3.3: (1) condition match, (2) preferred label match, (3) suggested next IDs, (4) highest weight, (5) lexical tiebreak. Replaces Stage 1's simplified "follow the single outgoing edge" logic.
- **Conditional Handler.** No-op handler for diamond-shaped nodes — routing handled by the engine's edge selection.
- **Retry System.** Per-node `max_retries` with backoff policies (standard, aggressive, linear, patient, none). Jitter. `should_retry` predicate. `execute_with_retry` loop per attractor Section 3.5-3.6. Configurable simulation backend that can return specific outcomes per node (e.g., FAIL twice then SUCCESS) for testing.
- **Goal Gate Enforcement.** At exit, check all visited `goal_gate=true` nodes. If any unsatisfied, reroute to `retry_target` / `fallback_retry_target` / graph-level targets. Per attractor Section 3.4.
- **Failure Routing.** On FAIL: check fail edge → retry_target → fallback_retry_target → pipeline termination. Per attractor Section 3.7.
- **`allow_partial`.** Accept PARTIAL_SUCCESS when retries exhausted on nodes with `allow_partial=true`.

### Excluded (deferred)

- Checkpoint resume, session management, replay (Stage 2b)
- LLM calls (Stage 3) — retries tested with simulation mode that can return configurable outcomes
- Human-in-the-loop (Stage 4)
- Parallel execution (Stage 5)

## Automated End-to-End Tests

All tests use simulation mode. For retry and goal gate tests, a configurable simulation backend returns specific outcomes per node (e.g., FAIL twice then SUCCESS).

### Condition Expression Tests

| Test | Description |
|------|-------------|
| Parse `outcome=success` | Evaluates to true when outcome is SUCCESS |
| Parse `outcome!=success` | Evaluates to true when outcome is not SUCCESS |
| Parse `context.key=value` | Evaluates to true when context has key with matching value |
| Parse `&&` conjunction | `outcome=success && context.flag=true` requires both clauses |
| Missing context key | `context.missing=value` evaluates to false (missing key = empty string) |
| Empty condition | Always evaluates to true |
| Invalid condition syntax | Produces parse error during validation |

### Edge Selection Tests

| Test | Description |
|------|-------------|
| Condition match wins | Edge with matching condition selected over higher-weight unconditional edge |
| Preferred label match | Outcome with `preferred_label="Fix"` selects edge labeled "Fix" |
| Label normalization | `"[Y] Yes"` normalizes to match `"yes"` |
| Suggested next IDs | Outcome with `suggested_next_ids=["node_b"]` selects edge to `node_b` |
| Weight tiebreak | Among unconditional edges, highest weight wins |
| Lexical tiebreak | Equal weights broken by alphabetical target node ID |
| Full priority chain | All 5 steps tested in a single graph with competing edges |

### Retry Tests

| Test | Description |
|------|-------------|
| Retry on FAIL | Node with `max_retries=2` retried twice after initial failure |
| Retry on RETRY status | Node returning RETRY status triggers retry |
| Retry exhaustion | After all retries, final outcome used for routing |
| Backoff delays | Standard policy delays: 200ms, 400ms, 800ms (verify within tolerance) |
| allow_partial | Node with `allow_partial=true` returns PARTIAL_SUCCESS when retries exhausted |
| No retry on SUCCESS | Successful node not retried |

### Goal Gate Tests

| Test | Description |
|------|-------------|
| Gate satisfied | All goal_gate nodes succeeded → pipeline exits normally |
| Gate unsatisfied with retry_target | Goal gate failed → engine reroutes to retry_target instead of exiting |
| Gate unsatisfied with graph retry_target | Node-level retry_target missing → falls back to graph-level |
| Gate unsatisfied no target | No retry target at any level → pipeline fails with clear error |
| Partial success satisfies gate | PARTIAL_SUCCESS counts as satisfied |

### Failure Routing Tests

| Test | Description |
|------|-------------|
| Fail edge | Node fails → follows `condition="outcome=fail"` edge |
| Retry target | No fail edge → jumps to node-level `retry_target` |
| Fallback retry target | No retry_target → jumps to `fallback_retry_target` |
| Pipeline termination | No failure route → pipeline terminates with error |

## Manual Testing Guide

### Prerequisites
- Stage 1 complete and passing
- `orchestra` CLI available

### Test 1: Conditional Branching

Create `test-branching.dot`:
```dot
digraph test_branching {
    graph [goal="Test conditional routing"]
    node [shape=box]

    start [shape=Mdiamond]
    exit  [shape=Msquare]

    do_work  [label="Do Work", prompt="Do the work"]
    gate     [shape=diamond, label="Check Result"]
    success  [label="Handle Success", prompt="Work succeeded"]
    failure  [label="Handle Failure", prompt="Work failed"]

    start -> do_work -> gate
    gate -> success [label="Pass", condition="outcome=success", weight=1]
    gate -> failure [label="Fail", condition="outcome!=success", weight=0]
    success -> exit
    failure -> exit
}
```

Run: `orchestra run test-branching.dot`

**Verify:**
- In simulation mode, `do_work` returns SUCCESS
- The `gate` routes to `success` (not `failure`)
- Events show: start → do_work → gate → success → exit

### Test 2: Observe Retry Behavior

Create `test-retry.dot` with a node configured with `max_retries=2`. Use a simulation mode configuration that causes the node to fail initially.

**Verify:**
- Events show StageRetrying with attempt number and delay
- After retries exhausted, failure routing kicks in
- Backoff delays are visible in event timestamps

## Success Criteria

- [ ] Condition expressions parse and evaluate correctly for all operators and variable types
- [ ] 5-step edge selection algorithm is deterministic and follows the spec priority order
- [ ] Retry system respects max_retries, applies backoff with jitter, and handles exhaustion
- [ ] Goal gates prevent exit when critical nodes haven't succeeded, and reroute correctly
- [ ] Failure routing follows the correct fallback chain (fail edge → retry_target → fallback → terminate)
- [ ] A human can build a branching pipeline, run it, and observe correct routing
- [ ] All automated tests pass
