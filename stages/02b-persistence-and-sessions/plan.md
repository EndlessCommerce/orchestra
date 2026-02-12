# Stage 2b: Persistence and Sessions

## Overview

Add checkpoint resume and session management so pipelines survive crashes and can be paused/resumed. Implement replay via CXDB context forking for re-execution from any checkpoint.

After this stage, pipelines are fully persistent. A crashed or paused pipeline can be resumed from its last checkpoint. Sessions are queryable. Any checkpoint can be replayed by forking the CXDB context.

## What a Human Can Do After This Stage

1. Pause a running pipeline (Ctrl-C) and resume it later with `orchestra resume`
2. View session status with `orchestra status` — see running/completed/paused sessions
3. Replay from a specific checkpoint with `orchestra replay`
4. See session history in the CXDB UI

## Prerequisites

- Stage 2a complete (full control flow — resume needs branching/retry state to be meaningful)

## Scope

### Included

- **Checkpoint Resume.** Read the head turn of the CXDB context, extract the `dev.orchestra.Checkpoint` turn payload, restore context, completed_nodes, retry counters, determine next node, continue execution. New turns are appended to the same CXDB context.
- **Graceful Pause.** Handle Ctrl-C (SIGINT) cleanly: complete the current node if possible, save a checkpoint, and exit. The CXDB context's head turn IS the checkpoint — no separate save step.
- **Session Management via CXDB Contexts.** Each `orchestra run` creates a CXDB context (the session). Session status is tracked via turn types: PipelineStarted → NodeExecution... → PipelineCompleted/PipelineFailed. `orchestra status` queries CXDB contexts and reads head turns to determine status (running, paused, completed, failed).
- **Replay via CXDB Fork.** `orchestra replay <session_id> --checkpoint <turn_id>` forks the CXDB context at the specified turn (`POST /v1/contexts/fork`). This creates a new context sharing history up to that turn. Execution proceeds from the fork point into the new context.
- **CLI Extensions.** `orchestra status` — list sessions (CXDB contexts) with status and turn count. `orchestra resume <session_id>` — resume from head turn. `orchestra replay <session_id> --checkpoint <turn_id>` — fork context and re-execute.

### Excluded (deferred)

- LLM calls (Stage 3)
- Human-in-the-loop (Stage 4)
- Parallel execution (Stage 5)
- Agent-turn-level resume (Stage 6 — requires workspace snapshots)

## Automated End-to-End Tests

### Checkpoint/Resume Tests

| Test | Description |
|------|-------------|
| Resume from checkpoint | Execute 3-node pipeline, stop after node 2, resume → node 3 executes, pipeline completes |
| Context restored | After resume, context values from before pause are present |
| Completed nodes skipped | After resume, already-completed nodes are not re-executed |
| Retry counters preserved | Node with 1 retry used before pause → only 1 retry remaining after resume |
| Checkpoint turn integrity | Checkpoint turn payload in CXDB is valid and contains all required fields |
| Resume reads head turn | Resume reads the CXDB context's head turn to find the latest checkpoint |
| Resume branching pipeline | Resume a pipeline that was paused mid-branch — correct branch continues |

### Session Management Tests (CXDB Contexts)

| Test | Description |
|------|-------------|
| Session created | `orchestra run` creates a CXDB context; context_id is the session_id |
| Session completed | Successful pipeline → PipelineCompleted turn appended to context |
| Session failed | Failed pipeline → PipelineFailed turn appended to context |
| Session query | `orchestra status` lists CXDB contexts with status derived from head turn type |
| Session resume | `orchestra resume <id>` reads head turn from CXDB context and continues |

### Replay Tests (CXDB Fork)

| Test | Description |
|------|-------------|
| Fork from checkpoint | `orchestra replay --checkpoint <turn_id>` creates a new CXDB context via fork |
| Fork preserves history | New context shares turns up to the fork point with the original |
| Fork diverges | New execution appends new turns to the forked context, not the original |
| Original unchanged | Original context's turns are unaffected by the replay |

### CLI Tests

| Test | Description |
|------|-------------|
| `orchestra status` | Shows sessions (CXDB contexts) with ID, pipeline name, status, turn count |
| `orchestra resume` valid session | Resumes paused session from CXDB head turn, prints events, exits 0 |
| `orchestra resume` invalid session | Exits non-zero with "session not found" (CXDB context not found) |
| `orchestra replay` from checkpoint | Forks CXDB context at specified turn, re-executes from that point |

## Manual Testing Guide

### Prerequisites
- Stage 2a complete and passing
- `orchestra` CLI available

### Test 1: Pause and Resume

Run: `orchestra run test-linear.dot` (the 5-node pipeline from Stage 1)

During execution, press Ctrl-C to pause.

**Verify:**
- Pipeline stops gracefully
- Session status shows "paused"
- `orchestra status` lists the paused session

Run: `orchestra resume <session_id>`

**Verify:**
- Execution continues from the last checkpoint
- Already-completed nodes are not re-executed
- Pipeline completes normally

### Test 2: Session Status

Run several pipelines (some complete, some paused).

Run: `orchestra status`

**Verify:**
- Table shows all sessions with ID, pipeline name, status, and timestamps
- Completed, paused, and failed sessions all shown correctly

### Test 3: Replay from Checkpoint

Run a complete pipeline. Note the session ID.

Run: `orchestra replay <session_id> --checkpoint <turn_id>`

**Verify:**
- A new session is created (new CXDB context)
- Execution starts from the checkpoint, not from the beginning
- The original session is unchanged

## Success Criteria

- [x] Checkpoint resume reads the CXDB head turn and restores full pipeline state
- [x] Completed nodes are not re-executed after resume
- [x] Retry counters are preserved across pause/resume
- [x] Graceful pause (Ctrl-C) completes the current node and saves a checkpoint
- [x] Session management uses CXDB contexts — no SQLite or local files
- [x] Session status correctly derived from CXDB context head turn type
- [ ] ~~Replay forks the CXDB context at any checkpoint turn (O(1))~~ — deferred (CXDB fork API not available)
- [ ] ~~Forked context shares history but diverges on new execution~~ — deferred (CXDB fork API not available)
- [x] CLI commands (status, resume) work correctly against CXDB (replay deferred)
- [x] A human can run a pipeline, pause it, and resume it (replay deferred)
- [x] All automated tests pass
