# Stage 6b: Worktree Isolation, Workspace Snapshots, and Turn-Level Resume

## Overview

Add worktree-per-agent isolation for parallel writes, workspace snapshots linking checkpoints to git SHAs, and resume/replay at agent turn granularity. After this stage, parallel agents can write to the same repo without conflicts during execution, worktrees are merged at fan-in, and pipelines can be resumed or replayed from any specific agent turn — not just node boundaries.

This is the second of three sub-stages decomposing Stage 6. It builds on Stage 6a's session branches and per-turn commits by adding the parallel isolation layer and the fine-grained resume/replay capabilities.

## What a Human Can Do After This Stage

1. Run parallel agents that each get their own git worktree for write isolation
2. See worktrees merged back at fan-in, with conflicts surfaced
3. Resume a pipeline from a checkpoint and have git repos restored to the correct SHAs
4. Resume from a specific agent turn (`orchestra resume <session_id> --turn <turn_id>`)
5. Replay from a specific agent turn (`orchestra replay <session_id> --turn <turn_id>`)
6. Inspect workspace snapshots showing which git SHA corresponds to each checkpoint

## Prerequisites

- Stage 6a complete (workspace config, session branches, per-turn commits, CXDB AgentTurn recording)

## Scope

### Included

- **Worktree-Per-Agent Isolation.** When parallel handler fans out to codergen nodes with write access to the same repo, create a git worktree per branch: `.orchestra/worktrees/{session-id}/{agent-name}`. Each agent commits independently to its worktree. Per-turn commits within parallel agents write to the agent's worktree. The RepoContext is updated to include the worktree path when applicable.
- **Worktree Merge at Fan-In.** At fan-in, merge worktrees back into the session branch using `git merge --no-commit`. On conflict, fail the merge and serialize conflict details (conflicting file list, conflict markers) into the context for the downstream node. Clean up worktrees after successful merge. Preserve worktrees on failure for inspection.
- **Workspace Snapshots at Two Granularities.** Fine-grained: each `dev.orchestra.AgentTurn` with file writes already includes the git SHA of that turn's commit (from Stage 6a). Coarse-grained: the `dev.orchestra.Checkpoint` at each node boundary includes a `workspace_snapshot` with the current HEAD SHA for each repo. Checkpoint turn version bumped to v3. Only recorded when repo state has changed.
- **Resume at Node Boundary with Git State.** Extend existing `orchestra resume <session_id>` to restore git repos to the correct commit SHAs from the Checkpoint's `workspace_snapshot`. Checkout each repo to the recorded HEAD SHA before continuing execution.
- **Resume at Agent Turn Granularity.** `orchestra resume <session_id> --turn <turn_id>` restores to a specific AgentTurn: pipeline state from the enclosing Checkpoint, git state from the AgentTurn's git_sha, LangGraph agent state from agent_state_ref. Standard `orchestra resume <session_id>` resumes from the latest node-boundary Checkpoint.
- **Replay at Agent Turn Granularity.** `orchestra replay <session_id> --turn <turn_id>` forks the CXDB context at the specified turn via `create_context(base_turn_id=turn_id)` — an O(1) operation that shares history up to the fork point without copying data. New execution appends turns to the forked context, diverging from the original.
- **Workspace Events.** Events for worktree creation (`WorktreeCreated`), worktree merge (`WorktreeMerged`), merge conflict (`WorktreeMergeConflict`), snapshot recording (`WorkspaceSnapshotRecorded`).

### Excluded (deferred)

- Remote git operations — clone, fetch, push (Stage 6c)
- Push policies (Stage 6c)
- `orchestra cleanup` CLI command (Stage 6c)

## Automated End-to-End Tests

Tests use temporary git repositories created in a test fixture. No external git repos or network access.

### Worktree Tests

| Test | Description |
|------|-------------|
| Worktree created for parallel | Parallel fan-out with 2 write-access agents → 2 worktrees created |
| Worktree isolation | Agent A's write in worktree A is not visible in worktree B |
| Worktree path | Created at `.orchestra/worktrees/{session-id}/{agent-name}` |
| Sequential agents no worktree | After fan-in, sequential nodes work directly on session branch (no worktree overhead) |
| Per-turn commits in worktree | Agent in worktree writes files → commits go to worktree branch, not session branch |

### Worktree Merge Tests

| Test | Description |
|------|-------------|
| Clean merge | Two agents edit different files → merge succeeds automatically |
| Merge conflict surfaced | Two agents edit the same file → conflict details serialized in context for downstream node |
| Worktree cleanup on success | After successful merge, worktrees are removed |
| Worktree preserved on failure | Merge failure → worktrees preserved for inspection |
| Merge result on session branch | After successful merge, session branch contains changes from both agents |

### Workspace Snapshot Tests

| Test | Description |
|------|-------------|
| Checkpoint includes workspace snapshot | Node-boundary Checkpoint turn has workspace_snapshot with current HEAD SHAs |
| Checkpoint snapshot only on change | Read-only node → no workspace_snapshot in Checkpoint |
| Snapshot per repo | Multi-repo workspace → workspace_snapshot has separate SHA for each repo |
| Snapshot after parallel | After parallel + fan-in merge → snapshot reflects merged state |

### Resume with Git State Tests

| Test | Description |
|------|-------------|
| Resume at node boundary | Pause after node 2, resume → repo at Checkpoint workspace_snapshot SHA |
| Resume at node restores multiple repos | Both repos restored to correct SHAs from Checkpoint turn |
| Resume at agent turn | `--turn <turn_id>` → repo checked out to AgentTurn.git_sha |
| Resume at agent turn restores agent state | Agent continues from next turn with full prior context |
| Resume at read-only turn | AgentTurn with null git_sha → repo at most recent prior SHA |
| Resume restores worktree | Resume during parallel execution → worktrees recreated from context state |

### Replay at Agent Turn Tests

| Test | Description |
|------|-------------|
| Replay from agent turn | `--turn <turn_id>` → CXDB context forked at turn_id via create_context(base_turn_id), new context shares history up to fork point |
| Replay restores git state | New context + git at AgentTurn.git_sha → agent continues with correct code |
| Replay diverges | New execution appends new AgentTurns to new context, original unchanged |

### End-to-End Integration Tests

| Test | Description |
|------|-------------|
| Parallel with worktrees | Fan-out → 2 agents write to same repo in isolated worktrees → per-turn commits in each worktree → fan-in → worktrees merged → session branch has both agents' commits |
| Resume at node boundary | Run pipeline → pause → resume → git state correct → pipeline completes |
| Resume at agent turn | Run pipeline → pause mid-node → resume --turn → agent continues from that turn with correct code and context |

## Manual Testing Guide

### Test 1: Parallel with Worktrees

Create a pipeline with parallel agents that both write to the same repo.

Run: `orchestra run test-parallel-git.dot`

**Verify:**
- During execution, `.orchestra/worktrees/{session-id}/` contains worktree directories
- After fan-in, worktrees are merged into the session branch
- `git log` on the session branch shows commits from both agents
- Both agents' changes are present in the final state

### Test 2: Resume at Node Boundary

Run: `orchestra run test-git.dot` (multi-node pipeline)

During execution, press Ctrl-C between nodes.

Make an external change to the repo (e.g., `git checkout main` and modify a file).

Run: `orchestra resume <session_id>`

**Verify:**
- Repo is restored to the session branch at the correct commit
- Pipeline continues from the next node
- Final state includes both the resumed work and new work

### Test 3: Resume at Agent Turn

Run: `orchestra run test-git.dot`

During execution, press Ctrl-C mid-agent-loop (agent has made some turns).

Run: `orchestra status <session_id>` to see AgentTurn entries and their turn IDs.

Run: `orchestra resume <session_id> --turn <turn_id>`

**Verify:**
- Repo is checked out to the git SHA from the specified AgentTurn
- Agent continues from the next turn (not from the beginning of the node)
- New turns produce new commits with correct sequence numbering

## Success Criteria

- [ ] Worktrees created for parallel agents writing to the same repo; per-turn commits write to agent's worktree
- [ ] Worktrees merged at fan-in; conflicts fail the merge and surface details to downstream node
- [ ] Worktrees cleaned up after successful merge, preserved on failure
- [ ] Workspace snapshots at two granularities: per-turn SHA in AgentTurn (from 6a), per-node HEAD SHAs in Checkpoint (v3)
- [ ] Resume at node boundary restores pipeline state + git HEAD per repo
- [ ] Resume at agent turn restores pipeline state + git to turn's SHA + LangGraph agent state
- [ ] Replay at agent turn forks the CXDB context at the specified turn (O(1), no data copying)
- [ ] Sequential nodes after fan-in work on session branch directly (no unnecessary worktrees)
- [ ] Multi-repo workspaces work with independent snapshots per repo
- [ ] All automated tests pass using temporary git repositories

---

## Investigation

- [x] Verify CXDB O(1) fork semantics work with current Python client
    - [x] Write a small test: create context A, append 3 turns, fork at turn 2, verify new context has turns 1-2, append to both, verify independence
    - [x] Confirm `create_context(base_turn_id=str(turn_id))` in `CxdbClient` works as expected
    - [x] Update the plan with findings
    - [x] Mark TODO complete and commit the changes to git
    - **Findings:** CXDB O(1) fork works as expected. `create_context(base_turn_id=str(turn_id))` forks at the specified turn. The new context shares history up to the fork point (O(1), no data copying). New turns append independently to each context. Tests in `tests/test_cxdb_fork.py`.

## Plan

### Layer 1: Git Worktree Operations

- [x] Add worktree git operations to `git_ops.py`
    - [x] Add `worktree_add(worktree_path: Path, branch: str, *, cwd: Path) -> None` — runs `git worktree add <worktree_path> -b <branch>`
    - [x] Add `worktree_remove(worktree_path: Path, *, cwd: Path) -> None` — runs `git worktree remove <worktree_path> --force`
    - [x] Add `worktree_list(*, cwd: Path) -> list[str]` — runs `git worktree list --porcelain`
    - [x] Add `merge(branch: str, *, cwd: Path) -> None` — runs `git merge --no-ff --no-commit <branch>`
    - [x] Add `merge_abort(*, cwd: Path) -> None` — runs `git merge --abort`
    - [x] Add `merge_conflicts(*, cwd: Path) -> list[str]` — parses `git diff --name-only --diff-filter=U` to get conflicting files
    - [x] Add `read_file(path: Path) -> str` — reads file content (for conflict markers)
    - [x] Add `branch_delete(name: str, *, cwd: Path) -> None` — runs `git branch -D <name>`
    - [x] Write unit tests in `tests/test_git_ops_worktree.py` for each new operation using a tmp git repo fixture
    - [x] Mark TODO complete and commit the changes to git

### Layer 2: Worktree Lifecycle Manager

- [x] Add `worktree_path` field to `RepoContext`
    - [x] Update `src/orchestra/workspace/repo_context.py`: add `worktree_path: Path | None = None` to `RepoContext` dataclass
    - [x] Mark TODO complete and commit the changes to git

- [x] Create `src/orchestra/workspace/worktree_manager.py`
    - [x] `WorktreeManager` class with `__init__(self, repo_contexts: dict[str, RepoContext], session_id: str, pipeline_name: str, branch_prefix: str, event_emitter: EventEmitter)`
    - [x] `create_worktrees(self, branch_id: str) -> dict[str, RepoContext]` — for each repo, calls `git_ops.worktree_add()` at `.orchestra/worktrees/{session_id}/{branch_id}`, creates worktree branch `{branch_prefix}{pipeline_name}/{session_id}/{branch_id}`, returns new `RepoContext` copies with `worktree_path` set. Emits `WorktreeCreated` per repo.
    - [x] `merge_worktrees(self, branch_ids: list[str]) -> WorktreeMergeResult` — for each repo: checkout session branch, for each branch_id run `git merge --no-commit`. On success: commit, clean up worktree dirs + delete branches. On conflict: capture file list + conflict markers, abort merge, preserve worktrees. Returns `WorktreeMergeResult(success: bool, conflicts: dict)`. Emits `WorktreeMerged` or `WorktreeMergeConflict`.
    - [x] `cleanup_worktrees(self, branch_ids: list[str]) -> None` — removes worktree dirs and branches (called after successful merge)
    - [x] `WorktreeMergeResult` dataclass: `success: bool`, `conflicts: dict[str, dict]` (repo_name → conflict info), `merged_shas: dict[str, str]` (repo_name → merged HEAD SHA)
    - [x] Mark TODO complete and commit the changes to git

### Layer 3: Workspace Events

- [x] Add new event types to `src/orchestra/events/types.py`
    - [x] `WorktreeCreated(Event)` — fields: `repo_name`, `branch_id`, `worktree_path`, `worktree_branch`
    - [x] `WorktreeMerged(Event)` — fields: `repo_name`, `branch_ids: list[str]`, `merged_sha`
    - [x] `WorktreeMergeConflict(Event)` — fields: `repo_name`, `branch_ids: list[str]`, `conflicting_files: list[str]`
    - [x] `WorkspaceSnapshotRecorded(Event)` — fields: `node_id`, `workspace_snapshot: dict[str, str]`
    - [x] Register all four in `EVENT_TYPE_MAP`
    - [x] Update `StdoutObserver` in `observer.py` to log new events
    - [x] Update `CxdbObserver` in `observer.py` to record `WorktreeCreated` and `WorktreeMerged` events (as `dev.orchestra.WorktreeEvent` v1)
    - [x] Mark TODO complete and commit the changes to git

### Layer 4: Parallel Handler Integration

- [x] Integrate worktrees into the parallel handler
    - [x] Update `ParallelHandler.__init__()` to accept optional `workspace_manager: WorkspaceManager | None`
    - [x] In `_execute_branches()`, before running each branch: if `workspace_manager` is set, call `workspace_manager.create_worktrees_for_branch(branch_id)` to get worktree-aware `RepoContext`s
    - [x] Thread worktree `RepoContext` through the branch's context so that repo tools in branch execution use the worktree path
    - [x] Store `branch_id → worktree_info` mapping for fan-in merge
    - [x] Mark TODO complete and commit the changes to git

- [x] Integrate worktree merge into the fan-in handler
    - [x] Update `FanInHandler.__init__()` to accept optional `workspace_manager: WorkspaceManager | None`
    - [x] After join evaluation, if `workspace_manager` is set: call `workspace_manager.merge_worktrees(branch_ids)` to merge all worktree branches back into the session branch
    - [x] On merge success: add merged SHA to context, continue normally
    - [x] On merge conflict: serialize conflict details into `context_updates["parallel.merge_conflicts"]` with structure `{"repo_name": {"conflicting_files": [...], "conflicts": {"file": "markers"}}}`. Continue with `PARTIAL_SUCCESS` status so downstream node can see conflicts
    - [x] Mark TODO complete and commit the changes to git

- [x] Update `WorkspaceManager` to track worktree state
    - [x] Add `_active_worktrees: dict[str, dict[str, RepoContext]]` to `WorkspaceManager` (branch_id → repo_name → RepoContext)
    - [x] Add `create_worktrees_for_branch(branch_id: str) -> dict[str, RepoContext]` method
    - [x] Add `merge_worktrees(branch_ids: list[str]) -> WorktreeMergeResult` method
    - [x] Update `on_turn_callback()` to use worktree path when committing if the agent is running in a worktree (match files against `worktree_path` when set)
    - [x] Mark TODO complete and commit the changes to git

- [x] Wire workspace_manager through handler registry to parallel + fan-in handlers
    - [x] Update `default_registry()` in `registry.py` to accept optional `workspace_manager` parameter
    - [x] Pass `workspace_manager` to `ParallelHandler` and `FanInHandler` constructors
    - [x] Update `cli/run.py` to pass `workspace_manager` to `default_registry()`
    - [x] Update `cli/resume_cmd.py` to pass `workspace_manager` to `default_registry()`
    - [x] Mark TODO complete and commit the changes to git

### Layer 5: Workspace Snapshots

- [x] Add workspace snapshots to checkpoints
    - [x] Add `workspace_snapshot: dict[str, str]` field to `CheckpointSaved` event in `types.py` (default `{}`)
    - [x] Update `WorkspaceManager` to track whether repo state has changed since last checkpoint (compare HEAD SHAs)
    - [x] Add `get_workspace_snapshot() -> dict[str, str]` method to `WorkspaceManager` — returns `{repo_name: HEAD_SHA}` for each repo. Returns `{}` if no repos have changed since last snapshot.
    - [x] Update `PipelineRunner._save_checkpoint()` to include `workspace_snapshot` in the emitted event — this requires the runner to have access to the workspace manager or for the checkpoint event to be enriched by the workspace manager observer
    - [x] **Approach:** Have `WorkspaceManager.on_event()` listen for `CheckpointSaved` events and enrich them with `workspace_snapshot` before CXDB records them. Alternatively, have the runner query `workspace_manager.get_workspace_snapshot()` when saving checkpoints. **Decision:** Use the runner approach — add optional `workspace_manager` to `PipelineRunner.__init__()` and query it in `_save_checkpoint()`.
    - [x] Update `CxdbObserver._append_checkpoint()` to bump to v3 and include `workspace_snapshot` in data
    - [x] Update `src/orchestra/storage/type_bundle.py` to register `dev.orchestra.Checkpoint` v3 schema
    - [x] Mark TODO complete and commit the changes to git

### Layer 6: Resume with Git State

- [x] Extend resume at node boundary to restore git state
    - [x] Update `restore_from_turns()` in `engine/resume.py` to extract `workspace_snapshot` from the latest Checkpoint turn and include it in `ResumeInfo`
    - [x] Add `workspace_snapshot: dict[str, str]` field to `ResumeInfo` dataclass (default `{}`)
    - [x] Create `src/orchestra/workspace/restore.py` with function `restore_git_state(workspace_snapshot: dict[str, str], repos: dict[str, RepoConfig], config_dir: Path) -> None` — for each repo in snapshot: resolve repo path, checkout session branch, verify/checkout to the recorded SHA
    - [x] Update `cli/resume_cmd.py` to call `restore_git_state()` after `restore_from_turns()` succeeds, before starting the runner
    - [x] Set up workspace (session branches, repo tools, write tracker) in resume command, same as in `run.py`
    - [x] Mark TODO complete and commit the changes to git

### Layer 7: Resume at Agent Turn

- [x] Add `--turn` flag to resume command
    - [x] Update `cli/resume_cmd.py`: add `turn: str = typer.Option(None, "--turn", help="Resume from a specific agent turn ID")` parameter
    - [x] Create `engine/turn_resume.py` with function `restore_from_turn(turns: list[dict], turn_id: str, context_id: str) -> TurnResumeInfo`
    - [x] `TurnResumeInfo` dataclass: `state: _RunState` (from enclosing Checkpoint), `next_node_id: str`, `turn_number: int`, `git_sha: str`, `prior_messages: list[dict]` (reconstructed conversation history for the agent), `pipeline_name`, `dot_file_path`, `graph_hash`, `context_id`
    - [x] Logic: find the specified AgentTurn, find the most recent Checkpoint before it, restore pipeline state from Checkpoint, extract `git_sha` from the AgentTurn, collect all prior AgentTurns for the same node to reconstruct message history
    - [x] In `resume_cmd.py`: if `--turn` is provided, call `restore_from_turn()` instead of `restore_from_turns()`. Restore git state to the AgentTurn's `git_sha`. Initialize the backend with prior conversation history via `send_message()`. Resume the runner from the node containing the turn.
    - [x] Mark TODO complete and commit the changes to git

### Layer 8: Replay at Agent Turn

- [x] Add `replay` CLI command
    - [x] Create `src/orchestra/cli/replay_cmd.py` with function `replay(session_id: str, turn: str)`
    - [x] Register `replay` command in the CLI app (`src/orchestra/cli/main.py`)
    - [x] Logic: resolve session_id → context_id, read turns, find specified turn, fork CXDB context via `client.create_context(base_turn_id=str(turn_id))`, restore git state from AgentTurn's `git_sha`, set up workspace + backend + dispatcher pointing at new forked context, resume execution from the turn's node
    - [x] The forked context shares history up to the fork point — new turns append only to the forked context, original is unchanged
    - [x] Mark TODO complete and commit the changes to git

### Layer 9: Tests

- [x] Write worktree lifecycle tests (`tests/test_worktree.py`)
    - [x] `test_worktree_created_for_parallel` — parallel fan-out with 2 codergen branches → 2 worktrees created at expected paths
    - [x] `test_worktree_isolation` — write file in worktree A, verify not visible in worktree B
    - [x] `test_worktree_path` — verify worktrees created at `.orchestra/worktrees/{session-id}/{agent-name}`
    - [x] `test_sequential_no_worktree` — sequential node after fan-in uses session branch directly, no worktree
    - [x] `test_per_turn_commits_in_worktree` — agent in worktree commits to worktree branch, not session branch
    - [x] Mark TODO complete and commit the changes to git

- [x] Write worktree merge tests (`tests/test_worktree_merge.py`)
    - [x] `test_clean_merge` — two agents edit different files → merge succeeds, session branch has both changes
    - [x] `test_merge_conflict_surfaced` — two agents edit same file → conflict details serialized in context
    - [x] `test_worktree_cleanup_on_success` — after successful merge, worktree dirs removed
    - [x] `test_worktree_preserved_on_failure` — on merge conflict, worktree dirs preserved
    - [x] `test_merge_result_on_session_branch` — after merge, session branch HEAD contains changes from both agents
    - [x] Mark TODO complete and commit the changes to git

- [x] Write workspace snapshot tests (`tests/test_workspace_snapshot.py`)
    - [x] `test_checkpoint_includes_workspace_snapshot` — checkpoint after node with file writes includes `workspace_snapshot` with HEAD SHAs
    - [x] `test_checkpoint_snapshot_only_on_change` — read-only node → checkpoint has empty `workspace_snapshot`
    - [x] `test_snapshot_per_repo` — multi-repo workspace → snapshot has separate SHA for each repo
    - [x] `test_snapshot_after_parallel` — after parallel + fan-in merge → snapshot reflects merged state
    - [x] Mark TODO complete and commit the changes to git

- [x] Write resume with git state tests (`tests/test_resume_git.py`)
    - [x] `test_resume_at_node_boundary` — resume restores repo to checkpoint's workspace_snapshot SHA
    - [x] `test_resume_at_node_restores_multiple_repos` — both repos restored to correct SHAs
    - [x] `test_resume_at_agent_turn` — `--turn` restores repo to AgentTurn.git_sha
    - [x] `test_resume_at_agent_turn_restores_agent_state` — agent continues with correct prior context
    - [x] `test_resume_at_read_only_turn` — null git_sha → repo at most recent prior SHA
    - [x] Mark TODO complete and commit the changes to git

- [x] Write replay tests (`tests/test_replay.py`)
    - [x] `test_replay_from_agent_turn` — fork creates new CXDB context sharing history up to fork point
    - [x] `test_replay_restores_git_state` — git at AgentTurn.git_sha after fork
    - [x] `test_replay_diverges` — new execution appends to new context, original unchanged
    - [x] Mark TODO complete and commit the changes to git

- [x] Write end-to-end integration tests (`tests/test_worktree_e2e.py`)
    - [x] `test_parallel_with_worktrees` — full flow: fan-out → 2 agents write in isolated worktrees → per-turn commits → fan-in → merge → session branch has both agents' commits
    - [x] `test_resume_at_node_boundary_e2e` — run → pause → resume → git state correct → completes
    - [x] `test_resume_at_agent_turn_e2e` — run → pause mid-node → resume --turn → agent continues from that turn
    - [x] Mark TODO complete and commit the changes to git

### Layer 10: Review and Cleanup

- [ ] Identify any code that is unused, or could be cleaned up
    - [ ] Look at all previous TODOs and changes in git to identify changes
    - [ ] Identify any code that is no longer used, and remove it
    - [ ] Identify any unnecessary comments, and remove them (these are comments that explain "what" for a single line of code)
    - [ ] If there are any obvious code smells of redundant code, add TODOs below to address them
    - [ ] Mark TODO complete and commit the changes to git

- [ ] Identify all specs that need to be run and updated
    - [ ] Look at all previous TODOs and changes in git to identify changes
    - [ ] Run the full test suite (`pytest tests/`) to verify no regressions
    - [ ] Identify any existing tests that may need updates due to changed signatures (e.g., `default_registry()`, `PipelineRunner.__init__()`, `RepoContext`)
    - [ ] Fix any failing tests
    - [ ] Mark TODO complete and commit the changes to git

### Key Design Decisions

**Worktree branch naming:** `{branch_prefix}{pipeline_name}/{session_id}/{branch_id}` — extends the session branch naming from 6a.

**Worktree creation trigger:** Create worktrees for all parallel branches that contain codergen nodes (shape=`box`). Check nodes in the branch subgraph via `extract_branch_subgraphs()`.

**RepoContext threading:** Add optional `worktree_path` field. When set, repo tools use `worktree_path` for all file operations instead of `path`. Original `path` preserved for merge operations back to the main repo.

**Agent state for turn resume:** Use messages-based reconstruction (Option B). Each AgentTurn already stores `messages`. On resume, reconstruct the full conversation from all prior AgentTurns for the same node and pass to `send_message()`. No LangGraph checkpointer dependency needed.

**CXDB replay:** Native O(1) forking via `create_context(base_turn_id=turn_id)`. No turn copying needed. Contexts are branch head pointers in the turn DAG.

**Mid-parallel resume:** Re-run the entire parallel node. Checkpoints only happen at node boundaries, so the last checkpoint before a parallel interruption is BEFORE the parallel node. Worktrees are created fresh on re-run.

**Conflict serialization:** Structured dict with `conflicting_files` list and per-file conflict markers text. Passed via `context_updates["parallel.merge_conflicts"]` for downstream node consumption.
