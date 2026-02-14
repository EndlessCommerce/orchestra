# Goal Evaluation: Stage 6c — Remote Git Operations and Cleanup

## Goal Summary

Add remote git operations (clone, fetch, push) with configurable push policies and an `orchestra cleanup` CLI command. This completes the workspace lifecycle by enabling non-local deployments: cloud servers and ephemeral containers can clone repos on demand, push session branches to remotes, and manage stale git artifacts.

The plan builds on a well-established foundation: `RepoConfig` already reserves `remote`, `push`, and `clone_depth` fields; `git_ops.py` provides low-level git commands (but no clone/fetch/push yet); the CLI structure, event system, and workspace manager are all extensible.

---

<estimates>
ambiguity:
  rating: 1/5
  rationale:
    - "Config schema is fully specified with YAML examples and a push policy reference table"
    - "All three push policies (never, on_completion, on_checkpoint) have clear trigger conditions and defaults"
    - "Clone/fetch behavior fully specified for all path×remote combinations (4 cases)"
    - "Shallow clone semantics specified with clone_depth field"
    - "Credentials explicitly delegated to host environment — no ambiguity about auth scope"
    - "Cleanup command has specified defaults (7 days), flags (--older-than), and preservation rules"
    - "Test matrix covers 24 specific test cases with descriptions"
    - "Only minor gap: no specification for cleanup of remote branches vs. local-only"

complexity:
  rating: 2/5
  rationale:
    - "Core operations (clone, fetch, push) are standard git commands with well-known semantics"
    - "Push policies are simple conditionals triggered at known lifecycle points (pipeline completion, checkpoint)"
    - "Non-blocking push with warning-only failures is a clean design that avoids retry/error-handling complexity"
    - "Cleanup is a straightforward filter-and-delete with age threshold"
    - "Credential delegation eliminates the hardest part of remote git (auth management)"
    - "Integration with existing event system and workspace manager follows established patterns"
    - "Main complexity is in the ephemeral lifecycle test (clone → run → push → destroy → re-clone → resume)"

size:
  rating: 2/5
  loc_estimate: 600-900
  worker_estimate: "2-3"
  rationale:
    - "~100-150 LOC: New git_ops functions (clone, fetch, push, branch age/cleanup)"
    - "~50-80 LOC: Push policy logic in workspace_manager.py (hook into pipeline completion + checkpoint events)"
    - "~50-80 LOC: Clone/fetch-on-start logic in workspace_manager.py or session_branch.py"
    - "~80-120 LOC: CLI cleanup command (arg parsing, discovery, filtering, deletion, reporting)"
    - "~30-50 LOC: New event types (RepoCloned, RepoFetched, SessionBranchPushed, SessionBranchPushFailed, CleanupCompleted)"
    - "~20-30 LOC: Config validation updates (push policy defaults, clone_depth validation)"
    - "~300-400 LOC: Tests (24 unit/integration tests + 3 E2E tests)"
</estimates>

---

<decision-points>
decision_points:
  - id: cleanup-scope-local-vs-remote
    question: Should `orchestra cleanup` also remove session branches from the remote, or only local branches and worktrees?
    resolution: Local-only. No remote branch deletion.
    resolved: true

  - id: push-timing-async
    question: Should on_checkpoint pushes be truly non-blocking (async/fire-and-forget) or synchronous-but-error-tolerant?
    resolution: Synchronous with caught exceptions. Log warning on failure, continue pipeline.
    resolved: true

  - id: clone-location-in-lifecycle
    question: Where in the startup sequence should clone/fetch occur — before or after session branch creation?
    resolution: Before session branch creation, in WorkspaceManager.setup() or a new prepare_repos() step.
    resolved: true

  - id: cleanup-stale-detection
    question: How to determine the age of a session branch for cleanup?
    resolution: Use the branch tip commit date (git log -1 --format=%ci).
    resolved: true

  - id: cleanup-active-session-detection
    question: How to determine if a session is still running/paused (to preserve its branches)?
    resolution: Query CXDB using existing derive_session_status() from engine/session.py. Fail with error if CXDB unavailable.
    resolved: true

  - id: shallow-clone-fetch-strategy
    question: When a shallow clone exists and fetch is needed, should fetch also be shallow?
    resolution: Use git fetch --depth N when clone_depth is configured. Regular fetch for full clones.
    resolved: true

  - id: push-branch-tracking
    question: Should the session branch be set up to track the remote branch (git push -u) or just pushed without tracking?
    resolution: Use git push -u on first push to set up tracking. Subsequent pushes use git push.
    resolved: true

  - id: multi-repo-push-ordering
    question: When multiple repos have push policies, should they be pushed sequentially or concurrently?
    resolution: Sequential. Simpler logging and debugging, negligible performance difference.
    resolved: true
</decision-points>

---

## Success Criteria: A-

The plan provides explicit success criteria (12 checkboxes) that are specific, testable, and cover the key functional requirements. The test matrix (24 unit/integration + 3 E2E tests) is comprehensive.

Minor gaps:
- No explicit criteria for event emissions (RepoCloned, SessionBranchPushed, etc.)
- No criteria for shallow clone fetch behavior
- No criteria for CLI output formatting of cleanup command

Suggested additions incorporated below:

<success-criteria>
success_criteria:
  # Clone/Fetch Tests
  - id: clone-on-start
    description: Repos with remote configured are cloned when path doesn't exist
    command: pytest tests/test_remote_git.py -k "clone_on_start"
    expected: Exit code 0, test passes
    automated: true

  - id: fetch-on-start
    description: Repos with remote configured and existing path are fetched
    command: pytest tests/test_remote_git.py -k "fetch_on_start"
    expected: Exit code 0, test passes
    automated: true

  - id: missing-path-no-remote-error
    description: Missing path without remote produces a clear error
    command: pytest tests/test_remote_git.py -k "missing_path_no_remote"
    expected: Exit code 0, test passes, error message is descriptive
    automated: true

  - id: shallow-clone
    description: clone_depth configuration produces shallow clones
    command: pytest tests/test_remote_git.py -k "shallow_clone"
    expected: Exit code 0, clone has limited history
    automated: true

  # Push Policy Tests
  - id: push-on-completion
    description: Session branch pushed to remote after successful pipeline completion
    command: pytest tests/test_push_policy.py -k "push_on_completion"
    expected: Exit code 0, remote has session branch
    automated: true

  - id: push-on-checkpoint
    description: Session branch pushed after each checkpoint
    command: pytest tests/test_push_policy.py -k "push_on_checkpoint"
    expected: Exit code 0, remote updated at each checkpoint
    automated: true

  - id: push-never
    description: No push when policy is never, even with remote configured
    command: pytest tests/test_push_policy.py -k "push_never"
    expected: Exit code 0, remote has no session branch
    automated: true

  - id: push-default-policies
    description: Default push policy is on_completion with remote, never without
    command: pytest tests/test_push_policy.py -k "default_push"
    expected: Exit code 0
    automated: true

  - id: push-failure-non-fatal
    description: Push failures log warnings but don't fail the pipeline
    command: pytest tests/test_push_policy.py -k "push_failure_non_fatal"
    expected: Exit code 0, warning logged, pipeline continues
    automated: true

  - id: no-push-on-pipeline-failure
    description: on_completion policy does not push when pipeline fails
    command: pytest tests/test_push_policy.py -k "no_push_on_pipeline_failure"
    expected: Exit code 0, remote has no session branch
    automated: true

  # Cleanup Tests
  - id: cleanup-old-branches
    description: Cleanup removes session branches older than threshold
    command: pytest tests/test_cleanup.py -k "cleanup_removes_old_branches"
    expected: Exit code 0, old branches removed
    automated: true

  - id: cleanup-orphaned-worktrees
    description: Cleanup removes orphaned worktrees from crashed sessions
    command: pytest tests/test_cleanup.py -k "cleanup_orphaned_worktrees"
    expected: Exit code 0, orphaned worktrees removed
    automated: true

  - id: cleanup-preserves-active
    description: Cleanup preserves branches for running/paused sessions
    command: pytest tests/test_cleanup.py -k "cleanup_preserves_active"
    expected: Exit code 0, active branches preserved
    automated: true

  - id: cleanup-reports-removed
    description: Cleanup CLI reports what was removed
    command: pytest tests/test_cleanup.py -k "cleanup_reports"
    expected: Exit code 0, output lists removed items
    automated: true

  - id: cleanup-age-threshold
    description: --older-than flag controls age threshold
    command: pytest tests/test_cleanup.py -k "cleanup_age_threshold"
    expected: Exit code 0, threshold respected
    automated: true

  # Event Emission Tests
  - id: remote-events-emitted
    description: Clone, fetch, push, and cleanup events are emitted
    command: pytest tests/test_workspace_events.py -k "remote" or pytest tests/test_remote_git.py -k "event"
    expected: Exit code 0, all events captured by RecordingEmitter
    automated: true

  # E2E Integration Tests
  - id: full-remote-lifecycle
    description: Clone → pipeline → agent changes → push → remote has session branch with commits
    command: pytest tests/test_remote_e2e.py -k "full_remote_lifecycle"
    expected: Exit code 0
    automated: true

  - id: ephemeral-container-simulation
    description: Clone → run → push → delete local → re-clone → resume from CXDB
    command: pytest tests/test_remote_e2e.py -k "ephemeral_container"
    expected: Exit code 0
    automated: true

  - id: remote-with-parallel-worktrees
    description: Clone → fan-out → worktrees → fan-in → merge → push → remote has merged branch
    command: pytest tests/test_remote_e2e.py -k "remote_parallel_worktrees"
    expected: Exit code 0
    automated: true

  # Full Suite
  - id: all-tests-pass
    description: Full test suite passes with no regressions
    command: pytest tests/ --tb=short
    expected: Exit code 0, 0 failures
    automated: true

evaluation_dependencies:
  - pytest test framework
  - git CLI (for bare repo creation in test fixtures)
  - Existing workspace test fixtures (git_repo, config, emitter)
  - CXDB client (for resume/replay E2E tests)
</success-criteria>

---

<missing-context>
missing_context: []
# All technical context has been resolved via codebase investigation:
#
# 1. cxdb-session-status: RESOLVED — derive_session_status() in engine/session.py
#    already extracts running/paused/completed/failed from PipelineLifecycle turns.
#    The status CLI command (cli/status.py) demonstrates the exact query pattern.
#
# 2. pipeline-completion-hook: RESOLVED — Push-on-completion inserts between
#    runner.run() return and the finally block in cli/run.py (lines 178-179),
#    before workspace_manager.teardown_session() restores original branches.
#
# 3. checkpoint-hook: RESOLVED — Event dispatch is synchronous. A new observer
#    listening for CheckpointSaved executes after CxdbObserver.append_turn()
#    completes, guaranteeing CXDB state matches before push.
</missing-context>

---

<additional-context>
## Resolved Decisions

1. **Cleanup scope: Local-only.** `orchestra cleanup` removes only local branches and worktrees. No remote branch deletion. This keeps cleanup simple and avoids requiring push access for maintenance operations.

2. **Active session detection: CXDB query.** Cleanup queries CXDB for sessions with running/paused status to preserve their branches. This is the most accurate approach. If CXDB is unavailable, cleanup should fail with a clear error rather than risk deleting active branches.

3. **Push model: Synchronous.** on_checkpoint pushes are synchronous with caught exceptions. Push failures log warnings but do not fail the pipeline. This is simpler than async and ensures pushed state is consistent with CXDB checkpoints.

## Resolved Technical Context

### CXDB Session Status (cxdb-session-status)

Fully supported by existing infrastructure — no new code needed for status derivation:

- **`derive_session_status(turns)`** in `src/orchestra/engine/session.py` extracts status from PipelineLifecycle turns. Returns `"running"`, `"paused"`, `"completed"`, or `"failed"`.
- **`extract_session_info(context_id, turns)`** returns full session info including `display_id`, `pipeline_name`, `status`, `turn_count`.
- **`CxdbClient.list_contexts()`** + **`get_turns(context_id)`** provides the query pattern.
- The existing `orchestra status` CLI command (`cli/status.py`) demonstrates this exact pattern.

Cleanup can reuse these functions directly to identify active sessions.

### Pipeline Completion Hook (pipeline-completion-hook)

Clear insertion point exists in `src/orchestra/cli/run.py`:

```
runner.run() returns outcome    ← line 174
                                ← INSERT push-on-completion HERE (check outcome.status == SUCCESS)
finally:                        ← line 179
    workspace_manager.teardown_session()  ← line 182 (restores original branches)
```

Session branches are still checked out when push executes. Push happens before `teardown_session()` restores original branches.

### Checkpoint Push Hook (checkpoint-hook)

Event dispatch is **synchronous** via `EventDispatcher.emit()` in `events/dispatcher.py`. The sequence is:

1. `_save_checkpoint()` in `runner.py` calls `self._emitter.emit("CheckpointSaved", ...)`
2. `CxdbObserver.on_event()` runs synchronously → `append_turn()` to CXDB
3. Next observer in chain runs synchronously

**Implementation**: Add a `PushObserver` that listens for `CheckpointSaved`. Register it after `CxdbObserver` in the dispatcher so CXDB write completes first. Push executes synchronously, guaranteeing pushed code matches CXDB state.

## Key Implementation Patterns

- **git_ops.py extensions:** Add `clone(url, path, depth=None)`, `fetch(remote, cwd, depth=None)`, `push(remote, branch, cwd, set_upstream=False)`, `branch_date(branch, cwd)`, `list_branches(pattern, cwd)` functions following the existing `run_git()` pattern.
- **Push-on-completion:** Insert in `cli/run.py` between `runner.run()` return and `finally` teardown block. Check `outcome.status == SUCCESS` before pushing.
- **Push-on-checkpoint:** New `PushObserver` in `events/observer.py` listening for `CheckpointSaved`. Registered after `CxdbObserver` in dispatcher chain.
- **Cleanup CLI:** Register as `app.command(name="cleanup")` in `cli/main.py` following the existing Typer pattern. Reuse `derive_session_status()` and `extract_session_info()` from `engine/session.py` to identify active sessions. Use `branch_prefix` from config to identify Orchestra-managed branches.
- **Event types:** Add to `events/types.py` following existing dataclass pattern: `RepoCloned`, `RepoFetched`, `SessionBranchPushed`, `SessionBranchPushFailed`, `CleanupCompleted`.
</additional-context>

---

## Analysis

### Strengths of This Plan

1. **Minimal ambiguity.** The plan specifies exact config schemas, all four path×remote combinations, three push policies with defaults, and a comprehensive test matrix. An implementer can translate this directly to code.

2. **Clean credential design.** Delegating authentication to the host environment is the right call — it avoids a massive scope expansion and works with existing CI/CD, cloud IAM, and SSH patterns.

3. **Well-scoped exclusions.** Multi-repo atomicity and transactional semantics are explicitly deferred, which prevents scope creep into distributed systems territory.

4. **Existing extension points.** The codebase is already prepared: `RepoConfig` has reserved fields, `git_ops.py` is ready for new functions, the event system is extensible, and the CLI uses Typer's `app.command()` pattern.

5. **Test-driven specification.** 24 unit/integration tests + 3 E2E tests provide clear acceptance criteria beyond the prose description.

### Implementation Notes

The work naturally decomposes into 3 parallel streams:
1. **Clone/Fetch** — New git_ops functions + startup logic in workspace_manager
2. **Push Policies** — Event-driven push at completion/checkpoint + policy resolution
3. **Cleanup CLI** — New CLI command + branch/worktree discovery and deletion

These can be implemented by 2-3 workers with minimal coordination, merging at the E2E integration test layer.
