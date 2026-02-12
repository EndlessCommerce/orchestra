# Goal Evaluation: Stage 2b — Persistence and Sessions

## Goal Summary

Add checkpoint resume and session management so pipelines survive crashes and can be paused/resumed. Implement replay via CXDB context forking. After this stage: `orchestra resume` restores from last checkpoint, `orchestra status` shows sessions, and `orchestra replay` forks a CXDB context at any checkpoint for re-execution.

---

<estimates>
ambiguity:
  rating: 2/5
  rationale:
    - "The plan specifies exact CLI commands, CXDB API endpoints, and turn types"
    - "Test cases are enumerated with expected behavior"
    - "Key architecture decisions are pre-made: CXDB is the sole persistence layer, no SQLite/local files"
    - "Some implementation details are unspecified: how 'next node' is determined from checkpoint, CXDB fork API contract, session status derivation for 'running' vs 'paused'"
    - "Signal handling (SIGINT) strategy has edge cases not fully addressed"

complexity:
  rating: 3/5
  rationale:
    - "Signal handling (SIGINT) during node execution is inherently tricky — must complete current node cleanly, save checkpoint, then exit"
    - "Resume logic must faithfully reconstruct _RunState (context, completed_nodes, retry_counters, visited_outcomes) and determine correct next node"
    - "CXDB fork API is an external dependency whose contract must be verified"
    - "Session status derivation requires robust interpretation of head turn types"
    - "Most patterns are well-established — the plan extends existing runner and observer infrastructure"
    - "A simple solution is possible: checkpoint already contains all state needed for resume"

size:
  rating: 3/5
  loc_estimate: 800-1200
  worker_estimate: "1-2"
  rationale:
    - "New engine module: resume logic (~150 LOC)"
    - "New engine module: signal/pause handling (~80 LOC)"
    - "CXDB client extensions: fork, head turn (~50 LOC)"
    - "New CLI commands: status, resume, replay (~200 LOC)"
    - "Session management logic (~100 LOC)"
    - "Tests: ~20 new tests (~400 LOC)"
    - "Modifications to existing runner.py for resume entry point"
</estimates>

---

<decision-points>
decision_points:
  - id: next-node-from-checkpoint
    question: "How is the 'next node' determined when resuming from a checkpoint?"
    tradeoffs:
      - "The checkpoint saves `current_node` (the last completed node). To find the next node, you need the outcome of that node to run edge selection — but the outcome isn't stored in the checkpoint."
      - "Option A: Store `next_node_id` explicitly in the checkpoint. Simple, direct, no ambiguity on resume."
      - "Option B: Re-derive next node by replaying the last edge selection. Requires storing the outcome in the checkpoint."
      - "Option C: Store both current and next node. Redundant but unambiguous."
    recommendation:
      text: "Store `next_node_id` in the checkpoint payload. The runner already knows the next node at checkpoint time — saving it avoids re-derivation entirely."
      confidence: 5/5
    needs_context: []

  - id: checkpoint-as-head-turn
    question: "The plan says 'the CXDB context's head turn IS the checkpoint'. But currently, the last turn could be any event type (StageCompleted, PipelineCompleted, etc). Should checkpoints always be the final turn, or should resume scan backwards for the latest Checkpoint turn?"
    tradeoffs:
      - "If checkpoint is always last: simpler resume (just read head), but constrains event ordering"
      - "If scan backwards: more resilient, but requires reading multiple turns and filtering"
      - "Currently, CheckpointSaved is emitted last in _execute_node, so it IS the last turn after each node. But PipelineCompleted/PipelineFailed may come after."
    recommendation:
      text: "Ensure CheckpointSaved is always the last turn before pause. On resume, read the head turn and verify it's a Checkpoint type. If not (e.g., pipeline already completed), reject the resume with an appropriate error."
      confidence: 4/5
    needs_context:
      - "Should a completed/failed pipeline be resumable? Or only paused ones?"

  - id: cxdb-fork-api
    question: "Does CXDB support `POST /v1/contexts/fork`? What's the request/response contract?"
    tradeoffs:
      - "If the fork API exists: replay is straightforward O(1) fork"
      - "If it doesn't: must emulate fork by creating new context and copying turns up to the checkpoint — expensive and loses CXDB's structural sharing"
    recommendation:
      text: "Verify the CXDB fork API exists and test it before implementing replay. If absent, defer replay to a later stage or implement a copy-based fallback."
      confidence: 4/5
    needs_context:
      - "What is the CXDB fork API contract? Does it accept a turn_id to fork at?"
      - "Does CXDB support fork natively, or is this a planned feature?"

  - id: sigint-handling-strategy
    question: "How should SIGINT (Ctrl-C) be handled during pipeline execution?"
    tradeoffs:
      - "Option A: Python signal.signal(SIGINT) sets a flag, runner checks flag between nodes. Simple but won't interrupt a long-running node."
      - "Option B: Raise a custom exception from signal handler, catch it in the runner loop. Immediate but may leave node in inconsistent state."
      - "Option C: Flag-based with cooperative checking — set flag, current node completes naturally, runner exits after checkpoint. The plan says 'complete current node if possible'."
    recommendation:
      text: "Flag-based cooperative approach (Option C). Set a `_pause_requested` flag in the signal handler. The runner checks this flag after each node execution (after checkpoint is saved). This matches the plan's 'complete current node if possible' requirement."
      confidence: 5/5
    needs_context: []

  - id: session-id-format
    question: "Which identifier do CLI commands use — the 6-char display ID or the CXDB context_id?"
    tradeoffs:
      - "Display ID (6-char): human-friendly but requires mapping back to context_id, and may collide"
      - "CXDB context_id: unambiguous but less ergonomic (likely a long integer)"
      - "Both: accept either, try display ID first then context_id"
    recommendation:
      text: "Accept both formats. The display_id is stored in the PipelineStarted turn, so `orchestra status` can show it. CLI commands try display_id match first, fall back to context_id."
      confidence: 4/5
    needs_context:
      - "Is the display_id stored persistently in CXDB? (Yes — it's in the PipelineStarted turn payload)"

  - id: running-vs-paused-status
    question: "How does `orchestra status` distinguish 'running' from 'paused'? There's no heartbeat mechanism."
    tradeoffs:
      - "Option A: If head turn is Checkpoint type → paused. If head turn is StageStarted → running. If PipelineCompleted/Failed → completed/failed."
      - "Option B: Add a PipelinePaused turn type emitted during graceful shutdown."
      - "Option C: Treat 'running' and 'paused' as the same state ('in-progress') since there's no way to distinguish a paused pipeline from a crashed one."
    recommendation:
      text: "Add a PipelinePaused lifecycle event. Emit it during graceful SIGINT handling before exit. This makes status unambiguous: head turn PipelinePaused → paused, Checkpoint without PipelinePaused → crashed/interrupted, PipelineCompleted → completed, PipelineFailed → failed."
      confidence: 5/5
    needs_context: []

  - id: visited-outcomes-in-checkpoint
    question: "The checkpoint currently stores completed_nodes, context_snapshot, and retry_counters. But _RunState also tracks visited_outcomes and reroute_count. Should these be in the checkpoint too?"
    tradeoffs:
      - "Without visited_outcomes: goal gate checks after resume won't know which nodes succeeded vs failed"
      - "Without reroute_count: resume might allow more reroutes than max_reroutes"
      - "Adding them increases checkpoint size slightly but ensures faithful state restoration"
    recommendation:
      text: "Add visited_outcomes and reroute_count to the checkpoint payload. These are essential for correct goal gate enforcement after resume."
      confidence: 5/5
    needs_context: []

  - id: pipeline-graph-on-resume
    question: "Resume needs the original pipeline graph. Where does it come from?"
    tradeoffs:
      - "Option A: Store the DOT file path in the checkpoint/session. Re-parse on resume."
      - "Option B: Store the serialized graph in the checkpoint. Self-contained but large."
      - "Option C: Store the DOT file path in the PipelineStarted turn. Resume re-parses from file."
    recommendation:
      text: "Store the DOT file path in the PipelineStarted turn (Option C). The graph is deterministic from the file, and storing the path is small. If the file has changed, warn the user."
      confidence: 4/5
    needs_context:
      - "Should resume fail if the DOT file has been modified since the original run? Or proceed with a warning?"
</decision-points>

---

## Success Criteria: B+

The plan includes good success criteria covering checkpoint resume, node skip, retry preservation, graceful pause, session management, replay forking, and CLI commands. Upgrading to A.

**Note:** Replay tests are deferred pending CXDB fork API availability (see additional context).

<success-criteria>
success_criteria:
  # Checkpoint/Resume
  - id: resume-from-checkpoint
    description: "Execute 3-node pipeline, stop after node 2, resume → node 3 executes, pipeline completes"
    command: "pytest tests/test_resume.py -k 'test_resume_from_checkpoint'"
    expected: "Exit code 0, test passes"
    automated: true

  - id: context-restored
    description: "After resume, context values from before pause are present"
    command: "pytest tests/test_resume.py -k 'test_context_restored_on_resume'"
    expected: "Exit code 0, test passes"
    automated: true

  - id: completed-nodes-skipped
    description: "After resume, already-completed nodes are not re-executed"
    command: "pytest tests/test_resume.py -k 'test_completed_nodes_skipped'"
    expected: "Exit code 0, test passes"
    automated: true

  - id: retry-counters-preserved
    description: "Node with 1 retry used before pause → only remaining retries after resume"
    command: "pytest tests/test_resume.py -k 'test_retry_counters_preserved'"
    expected: "Exit code 0, test passes"
    automated: true

  - id: resume-branching-pipeline
    description: "Resume a pipeline paused mid-branch — correct branch continues"
    command: "pytest tests/test_resume.py -k 'test_resume_branching'"
    expected: "Exit code 0, test passes"
    automated: true

  - id: visited-outcomes-preserved
    description: "Goal gate checks work correctly after resume (visited_outcomes restored)"
    command: "pytest tests/test_resume.py -k 'test_goal_gates_after_resume'"
    expected: "Exit code 0, test passes"
    automated: true

  # Graceful Pause (SIGINT)
  - id: graceful-pause
    description: "SIGINT during execution completes current node, saves checkpoint, and exits cleanly"
    command: "pytest tests/test_pause.py -k 'test_graceful_pause'"
    expected: "Exit code 0, test passes"
    automated: true
    notes: "Test uses flag-based simulation rather than actual signals"

  # Session Management
  - id: session-created
    description: "orchestra run creates a CXDB context; context_id is the session_id"
    command: "pytest tests/test_sessions.py -k 'test_session_created'"
    expected: "Exit code 0, test passes"
    automated: true

  - id: session-status-completed
    description: "Successful pipeline → session status shows completed"
    command: "pytest tests/test_sessions.py -k 'test_session_completed'"
    expected: "Exit code 0, test passes"
    automated: true

  - id: session-status-paused
    description: "Paused pipeline → session status shows paused"
    command: "pytest tests/test_sessions.py -k 'test_session_paused'"
    expected: "Exit code 0, test passes"
    automated: true

  - id: session-status-failed
    description: "Failed pipeline → session status shows failed"
    command: "pytest tests/test_sessions.py -k 'test_session_failed'"
    expected: "Exit code 0, test passes"
    automated: true

  # Replay
  - id: replay-forks-context
    description: "orchestra replay creates a new CXDB context via fork at the specified turn"
    command: "pytest tests/test_replay.py -k 'test_fork_from_checkpoint'"
    expected: "Exit code 0, test passes"
    automated: true
    notes: "Depends on CXDB fork API availability"

  - id: replay-diverges
    description: "New execution appends turns to forked context, original unchanged"
    command: "pytest tests/test_replay.py -k 'test_fork_diverges'"
    expected: "Exit code 0, test passes"
    automated: true

  # CLI
  - id: cli-status
    description: "orchestra status lists sessions with ID, pipeline name, status"
    command: "pytest tests/test_cli.py -k 'test_cli_status'"
    expected: "Exit code 0, test passes"
    automated: true

  - id: cli-resume-valid
    description: "orchestra resume <id> resumes paused session, exits 0"
    command: "pytest tests/test_cli.py -k 'test_cli_resume'"
    expected: "Exit code 0, test passes"
    automated: true

  - id: cli-resume-invalid
    description: "orchestra resume <invalid_id> exits non-zero with error message"
    command: "pytest tests/test_cli.py -k 'test_cli_resume_invalid'"
    expected: "Exit code 0, test passes"
    automated: true

  - id: cli-replay
    description: "orchestra replay <id> --checkpoint <turn_id> forks and re-executes"
    command: "pytest tests/test_cli.py -k 'test_cli_replay'"
    expected: "Exit code 0, test passes"
    automated: true

  # Full suite regression
  - id: full-suite-passes
    description: "All existing tests still pass (no regressions)"
    command: "pytest tests/"
    expected: "Exit code 0, 0 failures, 107+ existing tests + new tests all green"
    automated: true

evaluation_dependencies:
  - pytest
  - CXDB running (or mocked for unit tests)
  - Existing test infrastructure (SimulationCodergenHandler, RecordingEmitter)
</success-criteria>

---

<missing-context>
missing_context:
  - category: technical
    items:
      - id: cxdb-fork-api-contract
        question: "Does CXDB support POST /v1/contexts/fork?"
        why_it_matters: "The replay feature depends on this API. Without it, replay must be emulated or deferred."
        how_to_resolve: "RESOLVED — tested against running CXDB instance. See additional-context."
        status: resolved

      - id: cxdb-head-turn-api
        question: "Is there a dedicated API to read just the head (latest) turn of a context?"
        why_it_matters: "Resume reads the head turn to find the latest checkpoint."
        how_to_resolve: "Use get_turns with limit=1. CXDB returns turns in append order, so the last turn is the most recent. Can read all turns and take the last one, or use limit parameter."
        status: resolved

      - id: cxdb-turn-id-format
        question: "What is the format of turn IDs returned by CXDB?"
        why_it_matters: "Replay specifies a turn_id to fork at."
        how_to_resolve: "Need to inspect turn responses from get_turns on an existing context."
        status: open
</missing-context>

---

<additional-context>

## Resolved Decisions

### next-node-from-checkpoint → Store `next_node_id` in checkpoint
The checkpoint payload will include a `next_node_id` field. The runner stores this at checkpoint time (it already knows the next node from edge selection). On resume, the runner jumps directly to this node.

### running-vs-paused-status → Add `PipelinePaused` event
A new `PipelinePaused` lifecycle event will be added. It is emitted during graceful SIGINT handling, after the current node's checkpoint is saved and before process exit. This makes session status unambiguous:
- Head turn = `PipelinePaused` → **paused**
- Head turn = `Checkpoint` (no PipelinePaused) → **crashed/interrupted**
- Head turn = `PipelineCompleted` → **completed**
- Head turn = `PipelineFailed` → **failed**

### resume-modified-graph → Fail with error
Resume will fail if the DOT file has been modified since the original run. The graph file hash (blake3, already a project dependency) will be stored in the `PipelineStarted` turn. On resume, the file is re-hashed and compared.

### cxdb-fork-api → Not available, defer replay
**Tested against running CXDB instance (localhost:9010):**
- `POST /v1/contexts/fork` → 404
- `POST /v1/contexts/{id}/fork` → 404

The CXDB fork API does not exist on the current instance. **Recommendation: defer the replay feature (`orchestra replay`) to a later stage.** This removes ~25% of the planned scope (replay tests, fork client method, replay CLI command) and focuses Stage 2b on the core value: checkpoint resume + session management + graceful pause.

The replay feature can be revisited when either:
1. CXDB adds a fork endpoint
2. A copy-based fallback is deemed acceptable (create new context, copy turns up to checkpoint)

### visited-outcomes-in-checkpoint → Add to checkpoint
The checkpoint payload will be extended with `visited_outcomes` (dict of node_id → status) and `reroute_count` (int). The `dev.orchestra.Checkpoint` type bundle will be updated to version 2 with these additional fields.

### pipeline-graph-on-resume → Store DOT path + hash in PipelineStarted
The `PipelineStarted` turn will include `dot_file_path` and `graph_hash` fields. Resume re-parses the graph from the file and verifies the hash matches.

## Revised Scope (with replay deferred)

**In scope:**
- Checkpoint resume (read head turn, restore state, continue from next_node_id)
- Graceful pause (SIGINT → flag → complete node → checkpoint → PipelinePaused → exit)
- Session management (status derived from head turn type)
- CLI: `orchestra status`, `orchestra resume`
- Extended checkpoint payload (next_node_id, visited_outcomes, reroute_count)
- Extended PipelineStarted payload (dot_file_path, graph_hash)

**Deferred:**
- `orchestra replay` (blocked on CXDB fork API)
- Replay tests
- CxdbClient.fork_context() method

## Revised Size Estimate

With replay deferred:
- LOC estimate: **600-900** (down from 800-1200)
- Worker estimate: **1**
- Test count: ~15 new tests (down from ~20)

</additional-context>
