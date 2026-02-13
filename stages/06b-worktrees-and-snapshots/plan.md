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
- **Replay at Agent Turn Granularity.** `orchestra replay <session_id> --turn <turn_id>` creates a new CXDB context, copies turns from the source context up to the fork point, and starts new execution from that point. (CXDB does not support native forking — implemented as create_context + copy turns.)
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
| Replay from agent turn | `--turn <turn_id>` → new CXDB context created with turns copied up to fork point |
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
- [ ] Replay at agent turn creates a new CXDB context with turns copied up to fork point
- [ ] Sequential nodes after fan-in work on session branch directly (no unnecessary worktrees)
- [ ] Multi-repo workspaces work with independent snapshots per repo
- [ ] All automated tests pass using temporary git repositories
