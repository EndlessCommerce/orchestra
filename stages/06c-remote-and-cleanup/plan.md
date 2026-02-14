# Stage 6c: Remote Git Operations and Cleanup

## Overview

Add remote git operations (clone, fetch, push) with configurable push policies, and the `orchestra cleanup` CLI command for removing stale session branches and orphaned worktrees. After this stage, Orchestra can be deployed to cloud servers or ephemeral containers, cloning repos on demand, pushing session branches to remotes, and managing the lifecycle of git artifacts.

This is the third and final sub-stage decomposing Stage 6. It builds on Stage 6a (session branches, per-turn commits) and Stage 6b (worktrees, snapshots, resume) by adding the remote lifecycle that enables non-local deployments.

## What a Human Can Do After This Stage

1. Configure a remote repo and have Orchestra clone it automatically on pipeline start
2. See session branches pushed to the remote after pipeline completion
3. Configure per-checkpoint push for ephemeral environments that may crash
4. Deploy Orchestra to a cloud server or ephemeral container and have it manage repos via remote URLs
5. Use `orchestra cleanup` to remove stale session branches and orphaned worktrees
6. Destroy an ephemeral environment, re-clone from remote, and resume from CXDB checkpoint

## Prerequisites

- Stage 6b complete (worktrees, snapshots, resume — remote push depends on workspace snapshots for checkpoint durability)

## Scope

### Included

- **Clone on Session Start.** If a workspace repo's `path` does not exist but `remote` is configured, Orchestra clones it before creating the session branch. If the path exists, Orchestra fetches to ensure the local clone is up to date. If neither `remote` nor `path` exists, raise a clear error.
- **Shallow Clones.** For large repos in ephemeral environments, `clone_depth` can be set per repo to use shallow clones (`git clone --depth N`). Session branches are created from the shallow clone. Deep history is fetched on demand only if needed (e.g., for merge conflict resolution).
- **Push Policies.** Controlled by the `push` field in `workspace.repos.{name}`:
  - `never` — default when no `remote` is configured. No push.
  - `on_completion` — default when `remote` is set. Push session branches to remote when pipeline completes successfully. Failed pipelines do not auto-push.
  - `on_checkpoint` — push after each auto-commit/checkpoint. Ensures code changes survive container restarts or crashes. Push is non-blocking; failures are logged as warnings, not pipeline errors.
- **Credentials.** Git authentication uses the host environment's existing credential configuration (SSH keys, credential helpers, `GIT_ASKPASS`, etc.). Orchestra does not manage credentials — it delegates to git. This works with cloud IAM roles, CI/CD credential injection, and SSH agent forwarding.
- **CLI: `orchestra cleanup`.** Remove stale session branches (configurable age threshold, default 7 days), orphaned worktrees (from crashed sessions), and old run directories. `--older-than` flag for override. Reports what was removed. Preserves branches for running/paused sessions.
- **Workspace Events.** Events for clone (`RepoCloned`), fetch (`RepoFetched`), push (`SessionBranchPushed`), push failure (`SessionBranchPushFailed`), cleanup (`CleanupCompleted`).

### Excluded (deferred indefinitely)

- Multi-repo coordination atomicity (treat snapshots as best-effort)
- Transactional semantics across repos
- Credential management by Orchestra

### Workspace Configuration with Remote

```yaml
# orchestra.yaml — local workspace (no remote, default behavior)
workspace:
  repos:
    project:
      path: ./my-project
      branch_prefix: orchestra/

# orchestra.yaml — cloud/CI deployment (remote repos)
workspace:
  repos:
    backend:
      path: /workspace/backend
      remote: git@github.com:org/backend.git
      branch_prefix: orchestra/
      push: on_completion          # push session branches when pipeline completes
    frontend:
      path: /workspace/frontend
      remote: git@github.com:org/frontend.git
      branch_prefix: orchestra/
      push: on_checkpoint          # push after each checkpoint (ephemeral environments)
      clone_depth: 50              # shallow clone for large repos

# orchestra.yaml — ephemeral container deployment
workspace:
  repos:
    monorepo:
      path: /tmp/workspace/monorepo
      remote: https://github.com/org/monorepo.git
      branch_prefix: orchestra/
      push: on_checkpoint
      clone_depth: 1
```

**Push policy reference:**

| Policy | When Pushed | Use Case |
|--------|-------------|----------|
| `never` | Never (default when no `remote`) | Local-only development |
| `on_completion` | After pipeline completes successfully (default when `remote` is set) | Standard cloud deployment — durable remote, short-lived pipelines |
| `on_checkpoint` | After each auto-commit/checkpoint | Ephemeral containers — survive crash/restart |

## Automated End-to-End Tests

Tests use local bare repositories as remotes. No network access required.

### Remote Git Tests

| Test | Description |
|------|-------------|
| Clone on start | `remote` configured + `path` does not exist → repo cloned before session branch created |
| Fetch on start | `remote` configured + `path` exists → `git fetch` run before session branch created |
| No clone without remote | `remote` not configured + `path` exists → no clone/fetch, existing local behavior |
| Missing path no remote | `remote` not configured + `path` does not exist → clear error (not a silent clone) |
| Shallow clone | `clone_depth: 50` → `git clone --depth 50` used |
| Shallow clone default | No `clone_depth` → full clone |

### Push Policy Tests

| Test | Description |
|------|-------------|
| Push on completion | `push: on_completion` → session branch pushed to remote after pipeline completes |
| Push on checkpoint | `push: on_checkpoint` → session branch pushed after each auto-commit |
| Push never | `push: never` → no push even when `remote` is configured |
| Default push with remote | `remote` configured, no explicit `push` → defaults to `on_completion` |
| Default push without remote | No `remote` configured → defaults to `never` |
| Push failure non-fatal | Push fails (e.g., remote unreachable) → warning logged, pipeline continues |
| No push on pipeline failure | `push: on_completion` + pipeline fails → session branch not pushed |
| Multi-repo push | 2 repos with `push: on_completion` → both pushed on completion |
| Checkpoint push per-repo | Repo A `push: on_checkpoint`, Repo B `push: on_completion` → A pushed at each checkpoint, B only at completion |

### Cleanup Tests

| Test | Description |
|------|-------------|
| Cleanup removes old branches | Session branches older than threshold removed |
| Cleanup removes orphaned worktrees | Worktrees from crashed sessions removed |
| Cleanup preserves active sessions | Branches for running/paused sessions not removed |
| Cleanup reports what was removed | CLI output lists removed branches and worktrees |
| Cleanup age threshold | `--older-than 0` removes all stale branches; `--older-than 30` keeps recent ones |

### Remote End-to-End Integration Tests

| Test | Description |
|------|-------------|
| Full remote lifecycle | Clone from bare remote → pipeline runs → agent modifies files → auto-committed → pushed to remote on completion → remote has session branch with agent commits |
| Ephemeral container simulation | Clone from remote → run pipeline → push on checkpoint → delete local clone → re-clone → resume from CXDB checkpoint → git state restored from remote |
| Remote with parallel worktrees | Clone → fan-out → worktrees → fan-in → merge → push → remote has merged session branch |

## Manual Testing Guide

### Test 1: Remote Git Operations

Create a bare git repo to act as a remote:
```bash
git init --bare /tmp/test-remote.git
cd /tmp/test-source && git init && echo "hello" > README.md && git add . && git commit -m "init"
git remote add origin /tmp/test-remote.git && git push -u origin main
```

Create `orchestra.yaml` with a remote workspace:
```yaml
workspace:
  repos:
    project:
      path: /tmp/orchestra-workspace/project
      remote: /tmp/test-remote.git
      branch_prefix: orchestra/
      push: on_completion
```

Run: `orchestra run test-git.dot`

**Verify:**
- `/tmp/orchestra-workspace/project` was cloned from the bare remote
- Session branch created and agent changes committed locally
- After pipeline completion, session branch pushed to remote
- `git -C /tmp/test-remote.git branch` shows the session branch
- CXDB checkpoint turns contain workspace snapshots with SHAs that match the remote

### Test 2: Cleanup

Run several pipelines, then:

Run: `orchestra cleanup --older-than 0`

**Verify:**
- Stale session branches are removed
- Orphaned worktrees are removed
- Active session branches are preserved
- Output lists what was cleaned up

## Success Criteria

- [ ] Repos with `remote` configured are cloned automatically when path doesn't exist
- [ ] Repos with `remote` configured and existing path are fetched before session start
- [ ] Missing path without remote produces a clear error
- [ ] Shallow clones work with `clone_depth` configuration
- [ ] Session branches pushed to remote per the configured `push` policy (`on_completion`, `on_checkpoint`, `never`)
- [ ] Push failures are non-fatal — logged as warnings, pipeline continues
- [ ] Failed pipelines do not auto-push with `on_completion` policy
- [ ] `orchestra cleanup` removes stale branches older than configurable threshold
- [ ] `orchestra cleanup` removes orphaned worktrees from crashed sessions
- [ ] `orchestra cleanup` preserves branches for running/paused sessions
- [ ] `orchestra cleanup` reports what was removed
- [ ] Ephemeral environments work: clone → run → push → destroy → re-clone → resume from CXDB
- [ ] All automated tests pass using local bare repositories as remotes

---

## Implementation Plan

### Layer 1: New git_ops functions (clone, fetch, push, branch listing)

- [x] Add `clone`, `fetch`, `push`, `list_branches`, and `branch_date` to `src/orchestra/workspace/git_ops.py`
    - [x] `clone(url: str, path: Path, *, depth: int | None = None) -> None` — runs `git clone [--depth N] <url> <path>`
    - [x] `fetch(remote: str, *, cwd: Path, depth: int | None = None) -> None` — runs `git fetch [--depth N] <remote>`
    - [x] `push(remote: str, branch: str, *, cwd: Path, set_upstream: bool = False) -> None` — runs `git push [-u] <remote> <branch>`
    - [x] `list_branches(pattern: str, *, cwd: Path) -> list[str]` — runs `git branch --list <pattern>` and returns branch names
    - [x] `branch_date(branch: str, *, cwd: Path) -> str` — runs `git log -1 --format=%ci <branch>` and returns the date string
    - [x] Write unit tests for all new functions in `tests/test_git_ops_remote.py` (use local bare repos as remotes)
    - [x] Mark TODO complete and commit the changes to git

### Layer 2: New event types for remote operations

- [x] Add event types to `src/orchestra/events/types.py`
    - [x] `RepoCloned(Event)` — fields: `repo_name`, `remote_url`, `clone_path`, `depth` (optional)
    - [x] `RepoFetched(Event)` — fields: `repo_name`, `remote_url`, `depth` (optional)
    - [x] `SessionBranchPushed(Event)` — fields: `repo_name`, `branch_name`, `remote_url`
    - [x] `SessionBranchPushFailed(Event)` — fields: `repo_name`, `branch_name`, `remote_url`, `error`
    - [x] `CleanupCompleted(Event)` — fields: `removed_branches` (list[str]), `removed_worktrees` (list[str]), `preserved_branches` (list[str])
    - [x] Register all new types in `EVENT_TYPE_MAP`
    - [x] Add stdout handling in `StdoutObserver.on_event()` in `src/orchestra/events/observer.py`
    - [x] Mark TODO complete and commit the changes to git

### Layer 3: Clone/fetch on session start

- [ ] Add clone/fetch logic to workspace startup in `src/orchestra/workspace/session_branch.py`
    - [ ] Before `create_session_branches()` creates branches, check each repo config:
        - If `path` does not exist and `remote` is set → clone (with `clone_depth` if configured)
        - If `path` exists and `remote` is set → fetch (with `clone_depth` if configured for shallow fetch)
        - If `path` does not exist and `remote` is not set → raise `WorkspaceError` with clear message
        - If `path` exists and `remote` is not set → existing behavior (no-op)
    - [ ] Extract this into a `prepare_repos()` function called from `WorkspaceManager.setup_session()` before `create_session_branches()`
    - [ ] Emit `RepoCloned` / `RepoFetched` events from `WorkspaceManager.setup_session()`
    - [ ] Write tests in `tests/test_remote_git.py`:
        - `test_clone_on_start` — remote + path missing → cloned
        - `test_fetch_on_start` — remote + path exists → fetched
        - `test_no_clone_without_remote` — no remote + path exists → no clone/fetch
        - `test_missing_path_no_remote_error` — no remote + path missing → clear error
        - `test_shallow_clone` — `clone_depth: 50` → `git clone --depth 50`
        - `test_shallow_clone_default` — no `clone_depth` → full clone
        - `test_shallow_fetch` — fetch with `clone_depth` uses `--depth N`
    - [ ] Mark TODO complete and commit the changes to git

### Layer 4: Push policy resolution and config defaults

- [ ] Add push policy defaults to `RepoConfig` validation
    - [ ] In `src/orchestra/config/settings.py`, add a `@model_validator` or property that resolves the effective push policy:
        - If `push` is explicitly set → use it
        - If `remote` is set and `push` is empty → default to `on_completion`
        - If `remote` is not set and `push` is empty → default to `never`
    - [ ] Add `effective_push_policy` property (or resolve in validator) returning `"never"` | `"on_completion"` | `"on_checkpoint"`
    - [ ] Write tests for default resolution in `tests/test_push_policy.py`:
        - `test_default_push_with_remote` — remote set, no push → `on_completion`
        - `test_default_push_without_remote` — no remote → `never`
        - `test_explicit_push_override` — explicit `push: never` with remote → `never`
    - [ ] Mark TODO complete and commit the changes to git

### Layer 5: Push on completion

- [ ] Add push-on-completion logic to `src/orchestra/cli/run.py`
    - [ ] After `runner.run()` returns and before `workspace_manager.teardown_session()`, if `outcome.status == SUCCESS`:
        - Iterate over repos with effective push policy `on_completion`
        - For each: call `git_ops.push("origin", branch_name, cwd=repo_path, set_upstream=True)`
        - Wrap in try/except: on failure, log warning via `logger.warning()` and emit `SessionBranchPushFailed`
        - On success, emit `SessionBranchPushed`
    - [ ] Extract push logic into a method on `WorkspaceManager` (e.g., `push_session_branches(policy_filter: str)`) so `cli/run.py` stays clean
    - [ ] Write tests in `tests/test_push_policy.py`:
        - `test_push_on_completion` — pipeline succeeds → session branch pushed
        - `test_no_push_on_pipeline_failure` — pipeline fails → no push
        - `test_push_failure_non_fatal` — push fails (bad remote) → warning logged, no exception
        - `test_multi_repo_push` — 2 repos with `on_completion` → both pushed
    - [ ] Mark TODO complete and commit the changes to git

### Layer 6: Push on checkpoint (PushObserver)

- [ ] Add `PushObserver` to `src/orchestra/events/observer.py`
    - [ ] Create `PushObserver` class implementing `EventObserver`
    - [ ] Constructor takes `workspace_manager: WorkspaceManager` and `config: OrchestraConfig`
    - [ ] `on_event()` listens for `CheckpointSaved` events
    - [ ] On `CheckpointSaved`: call `workspace_manager.push_session_branches(policy_filter="on_checkpoint")`
    - [ ] Register `PushObserver` in `cli/run.py` after `CxdbObserver` so CXDB write completes first
    - [ ] Write tests in `tests/test_push_policy.py`:
        - `test_push_on_checkpoint` — checkpoint saved → session branch pushed for repos with `on_checkpoint` policy
        - `test_checkpoint_push_per_repo` — repo A `on_checkpoint`, repo B `on_completion` → only A pushed at checkpoint
        - `test_checkpoint_push_failure_non_fatal` — push fails → warning, pipeline continues
    - [ ] Mark TODO complete and commit the changes to git

### Layer 7: Cleanup CLI command

- [ ] Implement `orchestra cleanup` command
    - [ ] Create `src/orchestra/cli/cleanup.py` with a `cleanup` function:
        - `--older-than` option (default 7 days)
        - `--config` option for config path (optional)
        - Discover all session branches matching `branch_prefix` pattern in configured repos
        - For each branch, check age via `git_ops.branch_date()`
        - Query CXDB to identify active sessions (running/paused) using `derive_session_status()` + `extract_session_info()`
        - Preserve branches for active sessions
        - Remove stale branches older than threshold via `git_ops.branch_delete()`
        - Remove orphaned worktrees via `git_ops.worktree_remove()` (worktrees in `.orchestra/worktrees/` with no active session)
        - Report what was removed to stdout
        - Emit `CleanupCompleted` event
    - [ ] Register command in `src/orchestra/cli/main.py`
    - [ ] Write tests in `tests/test_cleanup.py`:
        - `test_cleanup_removes_old_branches` — branches older than threshold removed
        - `test_cleanup_removes_orphaned_worktrees` — worktrees from crashed sessions removed
        - `test_cleanup_preserves_active_sessions` — running/paused session branches preserved
        - `test_cleanup_reports_removed` — CLI output lists what was removed
        - `test_cleanup_age_threshold` — `--older-than 0` removes all; `--older-than 30` keeps recent
    - [ ] Mark TODO complete and commit the changes to git

### Layer 8: End-to-end integration tests

- [ ] Write E2E tests in `tests/test_remote_e2e.py`
    - [ ] `test_full_remote_lifecycle` — clone from bare remote → pipeline runs → agent modifies files → auto-committed → pushed to remote on completion → remote has session branch with agent commits
    - [ ] `test_ephemeral_container_simulation` — clone from remote → run pipeline → push on checkpoint → delete local clone → re-clone → resume from CXDB checkpoint → git state restored from remote
    - [ ] `test_remote_with_parallel_worktrees` — clone → fan-out → worktrees → fan-in → merge → push → remote has merged session branch
    - [ ] Mark TODO complete and commit the changes to git

### Layer 9: Review and cleanup

- [ ] Identify any code that is unused, or could be cleaned up
    - [ ] Look at all previous TODOs and changes in git to identify changes
    - [ ] Identify any code that is no longer used, and remove it
    - [ ] Identify any unnecessary comments, and remove them (these are comments that explain "what" for a single line of code)
    - [ ] If there are any obvious code smells of redundant code, add TODOs below to address them
    - [ ] Mark TODO complete and commit the changes to git

### Layer 10: Run full test suite and fix regressions

- [ ] Identify all specs that need to be run and updated
    - [ ] Look at all previous TODOs and changes in git to identify changes
    - [ ] Run the full test suite: `pytest tests/ --tb=short`
    - [ ] Identify any specs that cover these changes that need to be run, and run these specs
    - [ ] Add any specs that failed to a new TODO to fix these
    - [ ] Identify any missing specs that need to be added or updated
    - [ ] Add these specs to a new TODO
    - [ ] Mark TODO complete and commit the changes to git
