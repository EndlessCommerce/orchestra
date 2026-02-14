# Goal Evaluation: Stage 6b — Worktree Isolation, Workspace Snapshots, and Turn-Level Resume

## Goal Summary

Add worktree-per-agent isolation for parallel writes, workspace snapshots linking checkpoints to git SHAs, and resume/replay at agent turn granularity. This builds on Stage 6a's session branches and per-turn commits by adding the parallel isolation layer and fine-grained resume/replay.

The plan covers six major capabilities:
1. Worktree-per-agent isolation during parallel fan-out
2. Worktree merge at fan-in with conflict surfacing
3. Workspace snapshots at two granularities (per-turn and per-node)
4. Resume at node boundary with git state restoration
5. Resume at specific agent turn
6. Replay at specific agent turn (fork execution)

---

<estimates>
ambiguity:
  rating: 2/5
  rationale:
    - "Plan specifies concrete paths (.orchestra/worktrees/{session-id}/{agent-name}), CLI syntax (--turn <turn_id>), and merge strategy (git merge --no-commit)"
    - "30+ test cases are fully enumerated with expected behaviors"
    - "Success criteria are specific and tied to observable behaviors"
    - "Some implementation details are left open: conflict serialization format, agent state capture/restore mechanism, Checkpoint v3 schema fields"
    - "The plan clearly scopes what's included and excluded"

complexity:
  rating: 4/5
  rationale:
    - "Git worktree lifecycle management adds significant state to track (creation, branch association, cleanup)"
    - "Worktree merge at fan-in introduces conflict handling — a notoriously complex domain"
    - "Resume/replay at turn granularity requires reconstructing both pipeline state AND git state AND LangGraph agent state — three coordinated restorations"
    - "Parallel handler currently has no git awareness; threading RepoContext through parallel branches with worktree paths requires careful plumbing"
    - "CXDB replay via create_context + copy turns is a novel pattern not yet used in the codebase"
    - "Multi-repo workspaces multiply the worktree/snapshot complexity"

size:
  rating: 4/5
  loc_estimate: 1500-3000
  worker_estimate: "3-5"
  rationale:
    - "New modules: worktree manager (~200-300 LOC), merge logic (~150-200 LOC), snapshot recording (~100-150 LOC), turn-level resume/replay (~200-300 LOC)"
    - "Modified modules: parallel_handler, fan_in_handler, resume_cmd, run.py, type_bundle, event types (~300-500 LOC changes)"
    - "CLI extensions: --turn flag, replay command (~100-200 LOC)"
    - "Test code: 30+ test cases across 5-6 test files (~800-1200 LOC)"
    - "Could be decomposed into 3-5 independent work streams: worktrees, snapshots, resume, replay, events"
</estimates>

---

<decision-points>
decision_points:
  - id: worktree-branch-naming
    question: What branch names should worktree branches use?
    tradeoffs:
      - Using a sub-branch of session branch (e.g., orchestra/pipeline/session/agent-name) keeps naming consistent but creates deep hierarchy
      - Using a flat name (e.g., orchestra-wt-{session}-{agent}) is simpler but less discoverable
      - Worktree branches must be unique per session to avoid conflicts across concurrent sessions
    recommendation:
      text: "Use {branch_prefix}{pipeline_name}/{session_id}/{agent_name} extending the session branch naming pattern from 6a"
      confidence: 4/5
    needs_context: []

  - id: worktree-creation-trigger
    question: How does the parallel handler know which branches need worktrees vs. which are read-only?
    tradeoffs:
      - Creating worktrees for ALL parallel branches is simple but wasteful for read-only branches
      - Checking node attributes for write access requires metadata that may not exist in DOT files
      - The plan says "codergen nodes with write access" but the current graph model has no write-access annotation
    recommendation:
      text: "Create worktrees for all parallel branches that contain codergen nodes (nodes using codergen handler). The handler type already implies LLM execution with tool access."
      confidence: 3/5
    decision: "RESOLVED — All codergen branches get worktrees. The parallel handler uses extract_branch_subgraphs() which returns BranchInfo with subgraph nodes. Check if any node in the branch subgraph uses the codergen handler (shape='box' or handler type in registry)."
    needs_context: []

  - id: repo-context-threading
    question: How does each parallel branch receive its worktree-modified RepoContext?
    tradeoffs:
      - Modifying RepoContext.path to point to worktree is simple but changes semantics (path is currently the repo root)
      - Adding a worktree_path field to RepoContext preserves the original path for reference
      - Cloning RepoContext per branch adds complexity but is necessary for isolation
    recommendation:
      text: "Add optional worktree_path to RepoContext. When set, repo-scoped tools use worktree_path instead of path. This preserves the original path for merge operations."
      confidence: 4/5
    needs_context: []

  - id: conflict-serialization-format
    question: What format should merge conflict details use when passed to downstream nodes?
    tradeoffs:
      - Raw conflict markers (<<<<<<< ======= >>>>>>>) are universally understood but verbose
      - Structured JSON with file list and per-file diffs is more machine-readable
      - Including full conflict content vs. just file names affects context size
    recommendation:
      text: "Structured format with conflicting file list and per-file conflict markers. Include both the list (for quick assessment) and the full markers (for resolution). Pass as a special key in context.parallel.results."
      confidence: 3/5
    needs_context:
      - What will the downstream node (likely another LLM agent) do with conflict information? Auto-resolve or surface to human?

  - id: agent-state-capture
    question: How is LangGraph agent state captured and stored for turn-level resume?
    tradeoffs:
      - LangGraph's internal state includes conversation history and checkpointer state
      - Serializing full LangGraph state may be large and version-dependent
      - The plan mentions agent_state_ref in AgentTurn but 6a's AgentTurn v2 has agent_state (JSON string), not a ref
      - Storing full state in CXDB turns may hit size limits
    recommendation:
      text: "Use the existing agent_state field in AgentTurn v2 to serialize the LangGraph conversation history (messages list). On resume, reconstruct the agent with this history. This is already partially captured but not restored."
      confidence: 3/5
    decision: "NEEDS REDESIGN — Deferred to implementation. LangGraph agents are stateless; state lives in messages list. The implementer should choose between cumulative vs. delta storage based on CXDB payload size limits discovered during development. Key finding: agent_state is currently empty ({}), LangGraph supports passing prior messages via send_message()."
    needs_context:
      - CXDB per-turn payload size limit (discover during implementation)

  - id: cxdb-replay-mechanism
    question: "How exactly does create_context + copy turns work for replay?"
    tradeoffs:
      - CXDB create_context takes a base_turn_id — this might create a linked context, not an independent copy
      - Manually copying turns with append_turn requires re-serializing each turn
      - The CXDB API may not support reading individual turn payloads for re-writing
    recommendation:
      text: "Investigate CXDB create_context(base_turn_id) semantics first. If it creates a fork-like context, use that directly. If not, use get_turns() to read turns up to fork point and append_turn() to copy them into a new context."
      confidence: 2/5
    decision: "RESOLVED — Test fork semantics against live CXDB first. The binary protocol returns head_turn_id and head_depth which strongly suggests native forking. If confirmed, replay is just create_context(fork_turn_id) with no manual copying needed."
    needs_context: []

  - id: checkpoint-v3-schema
    question: What fields does the Checkpoint v3 schema add beyond v2?
    tradeoffs:
      - Adding workspace_snapshot as a new field is backwards-compatible
      - Need to handle v1/v2 checkpoints that lack workspace_snapshot (resume from old sessions)
      - Schema versioning affects CXDB type bundle registration
    recommendation:
      text: "Add workspace_snapshot field (JSON dict mapping repo_name -> HEAD SHA) to Checkpoint v3. Resume logic should handle v1/v2 checkpoints by skipping git restoration when workspace_snapshot is absent."
      confidence: 5/5
    needs_context: []

  - id: worktree-cleanup-timing
    question: When exactly are worktrees cleaned up on success?
    tradeoffs:
      - Immediately after merge removes evidence but frees disk space
      - Keeping until session teardown allows inspection but accumulates disk usage
      - Plan says "clean up after successful merge" which is immediate
    recommendation:
      text: "Clean up immediately after successful merge (as plan states). The merge result is on the session branch, and the worktree branches can be deleted. Emit WorktreeMerged event before cleanup for observability."
      confidence: 4/5
    needs_context: []

  - id: multi-repo-worktree
    question: How do worktrees work when the workspace has multiple repos?
    tradeoffs:
      - Create worktrees in ALL repos for each parallel agent (simple but wasteful)
      - Only create worktrees in repos that the agent's tools are scoped to (requires knowing tool-repo mapping upfront)
      - Create worktrees lazily on first write (complex but efficient)
    recommendation:
      text: "Create worktrees in all configured repos for each parallel branch. This is simpler and the cost (creating a worktree) is low. The snapshot tests already expect per-repo SHAs."
      confidence: 4/5
    needs_context: []

  - id: resume-worktree-recreation
    question: "When resuming during parallel execution, how are worktrees recreated?"
    tradeoffs:
      - Recreating worktrees from scratch and checking out to the right SHA is straightforward
      - Need to determine which agents were in-flight and their last known state
      - The checkpoint must capture enough info to reconstruct worktree state
    recommendation:
      text: "Re-run the entire parallel node on resume. Worktrees are recreated fresh."
      confidence: 4/5
    decision: "RESOLVED — Re-run entire parallel node on resume. Current checkpoints only happen at node boundaries (before the parallel node). If interrupted mid-parallel, the last checkpoint is BEFORE the parallel node, so resume naturally re-runs it entirely. Worktrees are created fresh. No per-branch checkpointing needed."
    needs_context: []
</decision-points>

---

<success-criteria>
success_criteria:
  - id: worktree-creation
    description: Parallel fan-out with 2 write-access agents creates 2 separate worktrees at the expected paths
    command: pytest tests/test_worktree.py -k "worktree_created_for_parallel"
    expected: Exit code 0, test passes; worktrees exist at .orchestra/worktrees/{session-id}/{agent-name}
    automated: true

  - id: worktree-isolation
    description: Agent A's writes in its worktree are not visible in Agent B's worktree
    command: pytest tests/test_worktree.py -k "worktree_isolation"
    expected: Exit code 0; file written by agent A exists in worktree A but not in worktree B
    automated: true

  - id: per-turn-commits-in-worktree
    description: Per-turn commits from agents in worktrees go to the worktree branch, not the session branch
    command: pytest tests/test_worktree.py -k "per_turn_commits_in_worktree"
    expected: Exit code 0; git log of worktree branch shows agent commits, session branch does not
    automated: true

  - id: clean-merge
    description: Two agents editing different files merge successfully at fan-in
    command: pytest tests/test_worktree_merge.py -k "clean_merge"
    expected: Exit code 0; session branch contains changes from both agents
    automated: true

  - id: merge-conflict-surfaced
    description: Two agents editing the same file produces conflict details in downstream context
    command: pytest tests/test_worktree_merge.py -k "merge_conflict"
    expected: Exit code 0; conflict details include file list and conflict markers
    automated: true

  - id: worktree-cleanup-on-success
    description: Worktrees are removed after successful merge
    command: pytest tests/test_worktree_merge.py -k "cleanup_on_success"
    expected: Exit code 0; .orchestra/worktrees/{session-id}/ directory removed or empty
    automated: true

  - id: worktree-preserved-on-failure
    description: Worktrees are preserved when merge fails
    command: pytest tests/test_worktree_merge.py -k "preserved_on_failure"
    expected: Exit code 0; worktree directories still exist
    automated: true

  - id: checkpoint-workspace-snapshot
    description: Node-boundary Checkpoint includes workspace_snapshot with HEAD SHAs
    command: pytest tests/test_workspace_snapshot.py -k "checkpoint_includes_snapshot"
    expected: Exit code 0; Checkpoint turn data contains workspace_snapshot dict with repo SHAs
    automated: true

  - id: snapshot-only-on-change
    description: Read-only node does not produce workspace_snapshot in Checkpoint
    command: pytest tests/test_workspace_snapshot.py -k "snapshot_only_on_change"
    expected: Exit code 0; Checkpoint for read-only node has no workspace_snapshot
    automated: true

  - id: resume-node-boundary-git
    description: Resume at node boundary restores repo to Checkpoint workspace_snapshot SHA
    command: pytest tests/test_resume_git.py -k "resume_at_node_boundary"
    expected: Exit code 0; after resume, git rev-parse HEAD matches stored SHA
    automated: true

  - id: resume-agent-turn
    description: Resume with --turn flag restores to specific AgentTurn's git_sha
    command: pytest tests/test_resume_git.py -k "resume_at_agent_turn"
    expected: Exit code 0; repo checked out to AgentTurn.git_sha, agent continues from next turn
    automated: true

  - id: replay-creates-new-context
    description: Replay creates a new CXDB context with turns copied up to fork point
    command: pytest tests/test_replay.py -k "replay_from_agent_turn"
    expected: Exit code 0; new context exists with correct turn count, original unchanged
    automated: true

  - id: replay-diverges
    description: New execution after replay appends turns to new context only
    command: pytest tests/test_replay.py -k "replay_diverges"
    expected: Exit code 0; original context turn count unchanged, new context has additional turns
    automated: true

  - id: sequential-no-worktree
    description: Sequential nodes after fan-in work on session branch directly without worktrees
    command: pytest tests/test_worktree.py -k "sequential_no_worktree"
    expected: Exit code 0; no worktree directories created for sequential nodes
    automated: true

  - id: e2e-parallel-worktrees
    description: Full pipeline with parallel fan-out, worktree isolation, per-turn commits, fan-in merge, and session branch verification
    command: pytest tests/test_worktree_e2e.py -k "parallel_with_worktrees"
    expected: Exit code 0; session branch has commits from both agents after merge
    automated: true

  - id: e2e-resume-node
    description: Full pipeline run, pause, resume at node boundary with correct git state
    command: pytest tests/test_worktree_e2e.py -k "resume_at_node_boundary"
    expected: Exit code 0; pipeline completes with correct final state
    automated: true

  - id: all-tests-pass
    description: Full test suite passes with no regressions
    command: pytest tests/
    expected: Exit code 0; all tests pass including new and existing
    automated: true

evaluation_dependencies:
  - pytest test framework
  - Temporary git repositories (test fixtures)
  - CXDB test instance (for integration tests)
  - LangGraph backend (for agent state tests)
</success-criteria>

---

## Success Criteria Rating: A-

The plan provides good success criteria (10 checked items). They are observable and testable. Deducting slightly because:
- The criteria are phrased as feature descriptions rather than verifiable assertions
- No explicit performance criteria (e.g., worktree creation should be fast)
- No explicit criteria for the CLI flags (--turn parsing, validation of turn_id)

The suggested success criteria above would bring it to an A.

---

<missing-context>
missing_context:
  - category: technical
    items:
      - id: cxdb-create-context-semantics
        question: "What does CXDB create_context(base_turn_id) actually do? Does it fork, link, or just set a parent pointer?"
        status: "RESOLVED — CXDB supports O(1) native forking. create_context(base_turn_id=N) creates a new context whose head points to turn N. History is shared, not copied. Confirmed by exploration doc, CXDB GitHub README, and binary protocol analysis. See additional-context section for full details."

      - id: cxdb-turn-payload-readback
        question: "Can get_turns() return full turn payloads that can be re-written with append_turn()?"
        status: "NO LONGER NEEDED — CXDB fork is native O(1). No turn copying required for replay."

      - id: langgraph-state-init
        question: "Can a LangGraph agent be initialized with prior conversation history?"
        status: "RESOLVED — Yes. LangGraphBackend.send_message() passes full _conversation_messages to agent.stream(). Agent is stateless; state is in the messages list. Two approaches for resume: (A) Use LangGraph checkpointer (matches exploration doc's agent_state_ref design), or (B) reconstruct messages from AgentTurn sequence (simpler, no new dependencies)."

      - id: agent-state-ref-definition
        question: "What is agent_state_ref in the exploration doc vs agent_state in the v2 schema?"
        status: "RESOLVED — The exploration doc (line 1035) shows agent_state_ref as 'langgraph_checkpoint_abc123', implying use of LangGraph's built-in checkpointer. Current implementation doesn't use checkpointer and stores {} in agent_state. Design choice deferred to implementation: either adopt LangGraph checkpointer or use messages-based reconstruction."

      - id: parallel-handler-checkpoint-state
        question: "How does the parallel handler currently save its in-flight state to checkpoints?"
        status: "RESOLVED — It doesn't. Checkpoints only happen at node boundaries. Decision: re-run entire parallel node on resume."

      - id: git-worktree-cleanup-branches
        question: "Should worktree branches be deleted after merge?"
        status: "RESOLVED — Yes. Delete branches after successful merge."

      - id: cxdb-payload-size-limit
        question: "What is the maximum payload size for a CXDB turn?"
        status: "RESOLVED — No documented limit. Payloads are msgpack + Zstd compressed in Blob CAS with BLAKE3 content addressing and automatic deduplication. Size is unlikely to be a practical concern."
</missing-context>

---

<additional-context>

## Resolved Context from Codebase Investigation

### CXDB create_context(base_turn_id) — CONFIRMED: Native O(1) Forking

The binary protocol (`src/orchestra/storage/binary_protocol.py:101-120`) sends `base_turn_id` as a u64 in a `MSG_CTX_CREATE` frame. The response returns `context_id`, `head_turn_id`, and `head_depth`.

**Finding: The plan is WRONG when it says "CXDB does not support native forking."** Multiple authoritative sources confirm CXDB supports O(1) context forking:

1. **Exploration doc** (`context/orchestra.exploration.md:952`): *"Replay → CXDB fork. `POST /v1/contexts/fork` with `base_turn_id` pointing to any checkpoint or AgentTurn. O(1) -- no data copying."*

2. **Exploration doc** (`context/orchestra.exploration.md:978`): *"Forking is replay. `orchestra replay --checkpoint <turn_id>` is a single O(1) fork operation in CXDB. No data copying."*

3. **Exploration doc** (`context/orchestra.exploration.md:940`): *"`orchestra replay <session_id> --checkpoint <turn_id>` forks the CXDB context at the specified turn (O(1) operation)."*

4. **CXDB GitHub README** (https://github.com/strongdm/cxdb): Confirms "fork conversations at any point without copying history" — a context is "a mutable branch head pointer."

5. **Exploration doc API sketch** (`context/orchestra.exploration.md:1063-1065`): Shows a planned `fork_context(base_turn_id)` method separate from `create_context`.

**The mechanism:** `create_context(base_turn_id=N)` creates a new context whose head points to turn N in the existing Turn DAG. The new context shares history (turns 0..N) with the original. New turns appended to either context diverge independently. This is O(1) because CXDB contexts are branch head pointers, not data copies.

**Impact on implementation:** The replay feature is much simpler than the plan describes:
```python
# Replay from a specific turn — just fork the CXDB context
new_ctx = cxdb.create_context(base_turn_id=str(fork_turn_id))
# new_ctx already has all turns up to fork_turn_id
# Append new turns to new_ctx["context_id"] — original context unaffected
```

No turn copying logic needed. The plan's "create_context + copy turns" approach is unnecessary.

**Verification test** (recommended as first implementation task):
1. Create context A, append 3 turns, record turn IDs
2. Fork: `create_context(base_turn_id=turn_2_id)` → context B
3. Assert: `get_turns(context_B_id)` returns turns 1-2
4. Append turn to context B
5. Assert: `get_turns(context_A_id)` still returns only turns 1-3 (unchanged)
6. Assert: `get_turns(context_B_id)` returns turns 1-2 + new turn

### LangGraph Agent State Restoration

The `LangGraphBackend` (`src/orchestra/backends/langgraph_backend.py`) already supports initialization with prior messages:

1. `send_message()` maintains `_conversation_messages` (line 47, 88-109)
2. Each call passes the full message history to `agent.stream({"messages": messages})` (line 100-101)
3. The agent is recreated fresh each call via `create_react_agent()` (line 92) — state is in the messages, not the agent

**The exploration doc reveals the intended design** (`context/orchestra.exploration.md:1000,1035`):
- The AgentTurn type is designed to have an `agent_state_ref` field containing `"langgraph_checkpoint_abc123"`
- This suggests the original design intended to use LangGraph's built-in checkpointer (which assigns checkpoint IDs)
- However, the current LangGraphBackend does NOT use LangGraph's checkpointer — it creates a fresh agent each call

**Current state vs. intended design:**
- `agent_state` field in AgentTurn v2 exists but stores `{}` (line 178)
- The exploration doc shows `agent_state_ref: "langgraph_checkpoint_abc123"` — a reference to LangGraph's checkpoint system
- The current implementation doesn't use LangGraph checkpoints at all

**For turn-level resume, two approaches:**

**Option A: Use LangGraph's checkpointer** (matches exploration doc intent)
- Configure `create_react_agent()` with a `MemorySaver` or persistent checkpointer
- Each agent turn gets a checkpoint ID automatically
- Store checkpoint ID in `agent_state_ref`
- On resume, load the checkpointer state
- Pro: LangGraph handles serialization. Con: Adds dependency on LangGraph's checkpointer.

**Option B: Messages-based restoration** (simpler, no new dependencies)
- Each AgentTurn already has `messages` field with the assistant message
- On resume, reconstruct full conversation from AgentTurn sequence (all turns in the node)
- Set `_conversation_messages` and call `send_message()`
- Pro: No new dependencies, uses existing data. Con: Must read all prior turns.

**CXDB payload size:** No documented limit. Payloads are msgpack + Zstd compressed in the Blob CAS with BLAKE3 content addressing. Identical payloads are deduplicated. Size is unlikely to be a practical concern.

**Decision:** Deferred to implementation. Either approach works. Option B is simpler and doesn't require changes to the LangGraph integration.

### Parallel Handler Architecture

The parallel handler (`src/orchestra/handlers/parallel_handler.py`) has these key integration points for worktrees:

1. **Branch extraction:** `extract_branch_subgraphs()` returns `dict[str, BranchInfo]` where each BranchInfo contains `subgraph` and `first_node_id`
2. **Context cloning:** Each branch gets `parent_context.clone()` (line 103)
3. **Branch execution:** Each branch gets a new `PipelineRunner` with the branch subgraph (line 112-115)
4. **No workspace awareness:** The handler doesn't know about repos, worktrees, or tools

**Integration approach:** The WorkspaceManager (which is already an EventObserver) should listen for `ParallelBranchStarted` events and create worktrees at that point. Or, the parallel handler needs to be extended to accept a workspace callback for worktree lifecycle management.

### Checkpoint State for Parallel Resume

The current checkpoint system (`src/orchestra/engine/resume.py`) does NOT support resuming mid-parallel execution. Checkpoints only capture state at node boundaries. The parallel handler runs all branches to completion synchronously via `asyncio.run()`. If interrupted mid-parallel, the last checkpoint would be BEFORE the parallel node.

**Implication:** Resume mid-parallel requires either:
1. Checkpointing within the parallel handler (between branch completions)
2. Re-running the entire parallel node on resume (simpler but wasteful)
3. Storing per-branch progress in the checkpoint

The plan's test "Resume restores worktree — Resume during parallel execution → worktrees recreated from context state" implies option 1 or 3.

</additional-context>

---

## Notes

### What's Well-Specified
- Worktree paths and lifecycle (creation, merge, cleanup)
- Test cases are comprehensive (30+ enumerated)
- Clear scope boundaries (included vs. excluded)
- Prerequisites are explicit
- Manual testing guide with concrete verification steps

### What Needs Clarification Before Implementation
All major unknowns are now resolved. The only remaining verification is a live CXDB fork test (recommended as first implementation task to confirm the documented O(1) fork behavior works as expected with the Python client).

### Resolved During Evaluation
1. **Worktree trigger** — All codergen branches get worktrees (check node handler types in branch subgraph)
2. **Branch cleanup** — Delete worktree branches after successful merge
3. **Mid-parallel resume** — Re-run entire parallel node (no per-branch checkpointing)
4. **LangGraph state** — Agents are stateless; messages list is the state. `send_message()` already passes full history.
5. **agent_state_ref** — Exploration doc intended this as a LangGraph checkpoint ID (`"langgraph_checkpoint_abc123"`). Current impl doesn't use checkpointer. Two approaches: adopt checkpointer or reconstruct from messages. Deferred to implementation.
6. **CXDB replay** — **Plan is wrong about "no native forking."** CXDB supports O(1) context forking via `create_context(base_turn_id)`. Confirmed by exploration doc, CXDB README, and API design. No turn copying needed. This significantly simplifies the replay feature.
7. **CXDB payload size** — No documented limit. Payloads use msgpack + Zstd + BLAKE3 content-addressed deduplication.
8. **Plan correction needed** — The plan should be updated to remove the statement "CXDB does not support native forking — implemented as create_context + copy turns" and replace with native fork semantics.

### Implementation Ordering Suggestion
The work naturally decomposes into layers:
1. **Worktree lifecycle** (creation, path management, cleanup) — foundational, no CXDB dependency
2. **Worktree merge** (fan-in integration) — depends on 1
3. **Workspace snapshots** (Checkpoint v3) — independent of 1-2
4. **Resume with git state** (node boundary) — depends on 3
5. **Resume at agent turn** — depends on 4 + agent state investigation
6. **Replay at agent turn** — depends on 5 + CXDB investigation
7. **Events** — can be woven in throughout
