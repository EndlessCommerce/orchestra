# Goal Evaluation: Stage 7 — Validation Pipeline (Capstone)

## Goal Summary

Build the capstone stage that exercises all Orchestra features together: tool handler, CLI `attach`/`replay` commands, the full adversarial PR review pipeline (parallel reviewers, adversarial critique, conditional routing, human interaction, workspace management), CXDB observability with CLI detail view, and cross-feature integration tests. Validates that Stages 1-6 compose correctly under a realistic workload.

---

<estimates>
ambiguity:
  rating: 2/5
  rationale:
    - "Most components are well-specified with pseudocode in the attractor spec (Sections 4.10, 4.12) and detailed test tables"
    - "Tool handler (4.10) is clearly defined — shell execution, stdout capture, timeout"
    - "Manager loop handler deferred — removes the most underspecified component"
    - "CXDB UI renderers descoped in favor of CLI --detail view — removes the most ambiguous item"
    - "'orchestra attach' now has a clear approach: CXDB polling for events + Unix socket for interactive I/O"
    - "Replay command already exists (`replay_cmd.py` with --turn flag) — enhancement to support --checkpoint is incremental"
    - "Custom handler registration is already fully implemented in `handlers/registry.py` — just needs documentation/validation"
    - "PR review pipeline and agent configs are well-described — shapes, flow, and features are clear"
    - "Remaining ambiguity: attach Unix socket protocol details, CXDB polling interval tuning"

complexity:
  rating: 3/5
  rationale:
    - "Capstone stage composing all features from Stages 1-6 — integration surface area is large"
    - "Manager loop handler deferred — removes the most architecturally complex component"
    - "CXDB UI renderers descoped — removes unknown-complexity dependency"
    - "'orchestra attach' with CXDB polling + Unix socket is moderate complexity — polling is straightforward, socket forwarding is bounded"
    - "Cross-feature integration tests require carefully crafted scenarios that exercise multiple subsystems simultaneously"
    - "The PR review pipeline is a composition of existing features (parallel, conditional, interactive, workspace) — moderate complexity since all primitives exist"
    - "Tool handler is straightforward (subprocess execution)"
    - "Maintenance cost is low-to-moderate — mostly integration glue, not novel algorithms"

size:
  rating: 3/5
  loc_estimate: 2000-3500
  worker_estimate: "2-4"
  rationale:
    - "1 new handler (tool): ~100-200 LOC"
    - "1 new CLI command (attach) with CXDB polling + Unix socket: ~300-500 LOC"
    - "Replay --checkpoint enhancement: ~50-100 LOC"
    - "PR review pipeline DOT file + 4 agent YAML configs: ~200-300 LOC"
    - "PR diff tool (context injection via tool handler): ~50-100 LOC"
    - "Observability enhancements (token aggregation in NodeExecution, --detail): ~200-300 LOC"
    - "~50 test cases across 5 test categories: ~1000-2000 LOC"
    - "Some items are already done (custom handler registration, replay with git restore)"
    - "Manager loop handler and CXDB UI renderers removed — saves ~500-1000 LOC"
</estimates>

---

<decision-points>
decision_points:
  - id: attach-ipc-mechanism
    question: How does `orchestra attach` connect to a running pipeline session's event stream?
    tradeoffs:
      - "CXDB polling for events is nearly free since events already persist — but has 1-2s latency"
      - "Unix socket for interactive I/O provides bidirectional stdin/stdout forwarding"
      - "Running pipeline needs to open a Unix socket server when an interactive node is active"
      - "Multiple attach sessions could connect simultaneously via separate socket connections"
    recommendation:
      text: "CXDB polling for event stream (read-only) + Unix socket for interactive I/O forwarding. The running pipeline opens a Unix socket at a well-known path (e.g., /tmp/orchestra/{session_id}.sock) when entering interactive mode. Attach polls CXDB for new turns and connects to the socket when interactive."
      confidence: 4/5
    needs_context: []
    resolved: true
    resolution: "User selected CXDB polling + Unix socket approach"

  - id: manager-child-lifecycle
    question: How does the manager loop handler start and monitor child pipelines?
    resolved: true
    resolution: "DEFERRED — Manager loop handler removed from Stage 7 scope. The PR review pipeline uses parallel handler + conditional routing instead."

  - id: cxdb-ui-renderers
    question: What are CXDB UI renderers and how are they built?
    resolved: true
    resolution: "DESCOPED — Replaced with `orchestra status --detail` for rich CLI-based inspection. CXDB type schemas will be documented so renderers can be built in a future stage."

  - id: replay-checkpoint-vs-turn
    question: Should replay use --checkpoint or --turn flag? The existing replay command uses --turn.
    tradeoffs:
      - Extend existing --turn to also accept checkpoint IDs — simpler, one command
      - Add separate --checkpoint flag — clearer semantics, but two ways to do the same thing
      - Replace --turn with --checkpoint (breaking change) — clean API but breaks existing usage
    recommendation:
      text: "Keep existing --turn flag and add --checkpoint as an alias or alternate path. Checkpoints are a type of turn in CXDB (dev.orchestra.Checkpoint), so the mechanics are identical."
      confidence: 4/5
    needs_context: []
    resolved: true
    resolution: "Add --checkpoint as a separate flag that filters for dev.orchestra.Checkpoint turns only. Keep --turn for general use."

  - id: tool-handler-security
    question: Should tool commands have security restrictions (sandbox, allowed commands, working directory)?
    tradeoffs:
      - No restrictions — simple, flexible, user controls what commands are in the DOT file
      - Configurable allowlist — safer but adds configuration burden
      - Working directory scoping to workspace repos — prevents accidental writes outside workspace
    recommendation:
      text: "No sandbox for initial implementation. The tool_command is authored by the pipeline developer (not generated by LLM). Scope working directory to the workspace repo path if configured."
      confidence: 4/5
    needs_context: []
    resolved: true
    resolution: "No sandbox. Scope working directory to workspace repo path if configured."

  - id: observability-aggregation
    question: Where should per-node token usage be aggregated — in NodeExecution turns or computed on read?
    tradeoffs:
      - Write-time aggregation in NodeExecution turns — fast reads, but requires collecting tokens before writing the turn
      - Read-time aggregation from AgentTurn turns — no schema changes, but slower queries
      - Both — redundant but flexible
    recommendation:
      text: "Read-time aggregation. Compute per-node token totals from AgentTurn turns when displaying --detail. No schema changes needed."
      confidence: 4/5
    needs_context: []
    resolved: true
    resolution: "Read-time aggregation. The Outcome model does NOT have token_usage (confirmed by code review). Token usage flows via AgentTurn → AgentTurnCompleted → dev.orchestra.AgentTurn CXDB turns. The `orchestra status --detail` command will aggregate from AgentTurn turns grouped by node_id at read time. No changes to Outcome, event types, or handlers needed."

  - id: pr-diff-tool-delivery
    question: How is the git diff provided to PR review agents?
    tradeoffs:
      - Context injection at pipeline start — diff loaded once, placed in context, agents read it
      - Built-in tool (local:get-git-diff) — agents call the tool, more flexible for different ranges
      - Both — context has default diff, tool allows custom queries
    recommendation:
      text: "Context injection at pipeline start via a tool handler node that runs `git diff` and places output in context. Subsequent LLM nodes read from context via Jinja2 templating. This showcases the tool handler being built in this stage."
      confidence: 4/5
    needs_context: []
    resolved: true
    resolution: "Tool handler node as first pipeline node runs `git diff` and places output in context as `tool.output`. Reviewers read via Jinja2 template (e.g., `{{ tool.output }}`). Diff range configurable via tool_command attribute in the DOT node."
</decision-points>

---

## Success Criteria Rating: B+

The plan includes detailed success criteria checklist items and comprehensive test tables. The criteria are end-to-end and cover all scope items. However:
- No automated commands for each criterion (manual checklist only)
- No specific pass/fail thresholds (e.g., "all 60 tests pass")
- Missing observability verification criteria

Suggested A-grade criteria:

<success-criteria>
success_criteria:
  - id: tool-handler-tests
    description: All 5 tool handler tests pass
    command: pytest tests/handlers/test_tool_handler.py -v
    expected: Exit code 0, 5 tests pass, 0 failures
    automated: true

  - id: cli-attach-tests
    description: Attach command connects to running session and receives events
    command: pytest tests/cli/test_attach.py -v
    expected: Exit code 0, all tests pass
    automated: true

  - id: cli-replay-checkpoint
    description: Replay from specific checkpoint restores correct state
    command: pytest tests/cli/test_replay_checkpoint.py -v
    expected: Exit code 0, all tests pass
    automated: true

  - id: pr-review-pipeline-mocked
    description: Full PR review pipeline executes end-to-end with mocked LLM
    command: pytest tests/e2e/test_pr_review_pipeline.py -v
    expected: "Exit code 0, all 10 test cases pass: full flow, parallel reviewers, critic loop, critic accepts, goal gate, interactive synthesizer, model stylesheet, workspace integration, checkpoint at every node, resume mid-pipeline"
    automated: true

  - id: cross-feature-integration
    description: All 5 cross-feature integration tests pass
    command: pytest tests/integration/test_cross_feature.py -v
    expected: Exit code 0, 5 tests pass
    automated: true

  - id: observability-cxdb
    description: Token usage, tool invocations, and timing present in CXDB turns
    command: pytest tests/observability/test_cxdb_metrics.py -v
    expected: Exit code 0, all observability tests pass
    automated: true

  - id: status-detail
    description: orchestra status --detail shows per-node metrics
    command: pytest tests/cli/test_status_detail.py -v
    expected: Exit code 0, --detail flag produces structured output with token counts and timing
    automated: true

  - id: custom-handler-registration
    description: Custom handlers can be registered and dispatched
    command: pytest tests/handlers/test_registry.py -v -k custom
    expected: Exit code 0, custom handler test passes
    automated: true

  - id: full-test-suite
    description: Entire test suite passes with no regressions
    command: pytest tests/ -v --tb=short
    expected: Exit code 0, 0 failures, total test count >= 750
    automated: true

  - id: real-llm-integration
    description: Real LLM integration test produces coherent PR review (gated)
    command: ORCHESTRA_REAL_LLM=1 pytest tests/integration/test_pr_review_real.py -v
    expected: Exit code 0, reviewers produce domain-specific feedback, critic evaluates, synthesizer produces final review
    automated: true
    notes: Only runs when ORCHESTRA_REAL_LLM=1 is set. Uses Haiku-tier models to minimize cost.

  - id: manual-pr-review
    description: A human can run the full PR review workflow interactively
    expected: |
      Human verifies:
      - Pipeline starts and creates session branches
      - Parallel reviewers execute concurrently
      - Critic evaluates and loops if unsatisfied
      - Synthesizer enters interactive mode with human prompts
      - Final review is coherent and saved to run directory
      - orchestra status --detail shows completed session with metrics
    automated: false

evaluation_dependencies:
  - pytest test framework
  - CXDB instance running (for integration tests)
  - LLM API key (for gated real LLM tests only)
  - Git repository with sample diff (for PR review tests)
</success-criteria>

---

<missing-context>
missing_context: []
# All missing context has been resolved — see <additional-context> section for details.
# Technical items resolved by code review; business items resolved via user input.
</missing-context>

---

<additional-context>

## Resolved Decisions

**Attach mechanism**: CXDB polling for event stream + Unix socket for interactive I/O forwarding. The running pipeline opens a Unix socket at a well-known path when entering interactive mode. Attach polls CXDB for new turns at ~1s interval and connects to the socket for bidirectional forwarding during interactive nodes.

**CXDB UI renderers**: Descoped from Stage 7. Replaced with `orchestra status --detail` CLI command that reads metrics from CXDB turns and displays rich structured output (per-node token usage, timing, tool invocations). CXDB type schemas (dev.orchestra.NodeExecution, dev.orchestra.AgentTurn, etc.) are already defined and will be documented for future renderer development.

**Manager loop handler**: Deferred entirely from Stage 7. The PR review pipeline uses the existing parallel handler + conditional routing pattern instead. Manager loop can be implemented in a future stage when the supervisor pattern is needed.

**All features equal priority**: No features are deprioritized — tool handler, attach, replay enhancement, PR review pipeline, observability, and cross-feature integration tests are all in scope and equally important.

**Replay --checkpoint flag**: Add `--checkpoint` as a separate flag alongside existing `--turn`. The `--checkpoint` flag filters for `dev.orchestra.Checkpoint` turns only, providing clearer UX for checkpoint-specific replay.

**Token usage aggregation**: Read-time aggregation from `dev.orchestra.AgentTurn` CXDB turns. The `Outcome` model does NOT have a `token_usage` field (confirmed by code review: `models/outcome.py`). Token usage flows via `AgentTurn` → `AgentTurnCompleted` event → `dev.orchestra.AgentTurn` CXDB turns. The `orchestra status --detail` command will aggregate from AgentTurn turns grouped by `node_id` at read time. No schema changes needed.

**PR diff delivery**: Tool handler node as first pipeline node runs `git diff` and places output in context as `tool.output`. Reviewers read the diff via Jinja2 template in their task prompts (e.g., `{{ tool.output }}`). Diff range is configurable via the `tool_command` attribute in the DOT node.

**Real LLM budget**: No budget constraint. Use whatever models produce the best validation. Correctness is the priority over cost.

## Resolved Missing Context (from code review)

**CXDB streaming API**: No. The `CxdbClient` (`storage/cxdb_client.py`) uses HTTP request/response for reads (`get_turns`, `list_contexts`) and binary protocol for writes. No WebSocket/SSE subscription endpoints exist. The attach command will use HTTP polling with `get_turns` at ~1s interval, filtering for turns newer than the last seen.

**CodergenHandler token usage**: No. The `Outcome` model (`models/outcome.py`) has fields: `status`, `preferred_label`, `suggested_next_ids`, `context_updates`, `notes`, `failure_reason` — no `token_usage`. Token usage is tracked separately via `AgentTurn` dataclass (`models/agent_turn.py`), which has `token_usage: dict[str, int]`. This flows through `AgentTurnCompleted` events to `dev.orchestra.AgentTurn` CXDB turns. For observability, `orchestra status --detail` will read AgentTurn turns and aggregate by node_id.

## Existing Infrastructure (Already Implemented)

The following items listed in the plan's scope are already fully or partially implemented:

1. **Custom handler registration** (`handlers/registry.py`) — `HandlerRegistry.register()` method exists. Stage 7 just needs to validate and document the extension point.

2. **Replay with git restore** (`cli/replay_cmd.py`) — Full replay from turn with CXDB context forking and git state restoration. The `--checkpoint` flag enhancement is incremental.

3. **Event system** (`events/types.py`, `events/observer.py`) — 25 event types, StdoutObserver, CxdbObserver, PushObserver all exist.

4. **CXDB type bundle** (`storage/type_bundle.py`) — Type schemas for PipelineLifecycle, NodeExecution, AgentTurn, Checkpoint, ParallelExecution, WorktreeEvent already registered.

5. **Agent token tracking** — `AgentTurnCompleted` event already includes `token_usage` dict. CxdbObserver already persists this in `dev.orchestra.AgentTurn` turns.

## Revised Scope Summary

### In Scope
- Tool handler (parallelogram shape, `tool_command` attribute, per attractor 4.10)
- CLI `orchestra attach` (CXDB polling + Unix socket for interactive)
- CLI `orchestra replay --checkpoint` (extend existing replay command)
- Adversarial PR review pipeline (DOT file + 4 agent YAML configs)
- PR review tools (git diff via tool handler node)
- `orchestra status --detail` (rich CLI view replacing CXDB UI renderers)
- Observability: per-node token usage, tool invocations, wall-clock timing in NodeExecution turns
- Custom handler registration validation and documentation
- Cross-feature integration tests (5 scenarios)
- Real LLM integration test (gated behind env var)

### Descoped (from original plan)
- Manager loop handler (deferred to future stage)
- CXDB UI renderers (replaced with CLI --detail view)

</additional-context>
