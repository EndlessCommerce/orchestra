# Goal Evaluation: Stage 6 — Git Integration and Workspace Management

## Goal Summary

Stage 6 adds the workspace layer that makes Orchestra a software development tool: multi-repo workspace management, session branches, worktree-per-agent isolation for parallel writes, workspace snapshots linking checkpoints to git SHAs, per-turn commits with LLM-generated messages and agent metadata, repo-scoped tools, remote git operations, and a cleanup CLI command.

This is the largest and most complex stage in the Orchestra roadmap so far. It introduces an entirely new subsystem (git/workspace) that weaves into nearly every existing subsystem: configuration, event system, CXDB recording, checkpoint/resume, parallel execution, agent backends, built-in tools, and CLI.

---

<estimates>
ambiguity:
  rating: 2/5
  rationale:
    - "The plan is exceptionally detailed — specific YAML schemas, exact branch naming conventions, exact git trailer names, exact CXDB turn types"
    - "Most implementation choices are pre-made: worktree paths, commit author format, push policies, etc."
    - "The two areas of ambiguity are: (1) the LLM commit message generation integration (which model tier, what prompt template, how to extract 'agent intent'), and (2) the exact merge conflict resolution flow at fan-in"
    - "Test tables are comprehensive and act as a specification"
    - "RepoContext is mentioned but not fully specified (what fields, how it's passed to tools)"

complexity:
  rating: 5/5
  rationale:
    - "This stage touches nearly every subsystem in Orchestra: config, events, CXDB, checkpoint/resume, parallel execution, backends, tools, CLI"
    - "Git worktree management is inherently complex — creation, isolation, merge, cleanup, and error handling"
    - "Per-turn commits require hooking into the agent loop at a granularity that doesn't exist yet (on_turn callback is defined but workspace layer needs to intercept it)"
    - "Resume at agent-turn granularity is a new concept beyond the existing node-level checkpoints"
    - "CXDB context forking for replay is a new CXDB operation"
    - "Remote git operations add clone/fetch/push lifecycle with multiple policies and error handling"
    - "Multi-repo multiplies the complexity of every git operation"
    - "Worktree merge at fan-in with conflict detection is a non-trivial 3-way merge problem"
    - "The maintenance cost is high — git operations are stateful, OS-dependent, and failure-prone"

size:
  rating: 5/5
  loc_estimate: "4000-6000 (production code) + 3000-5000 (tests)"
  worker_estimate: "5-8"
  rationale:
    - "New modules needed: workspace config, git operations layer, session branch manager, worktree manager, commit generator (LLM), workspace snapshot manager, repo-scoped tool wrapper, cleanup CLI, remote git ops"
    - "Modifications to existing modules: OrchestraConfig, AgentTurn model, CheckpointSaved event, CxdbObserver, resume.py, parallel_handler, fan_in_handler, codergen_handler, builtins, cli/main"
    - "~80 test cases specified across 10 test categories"
    - "This stage is easily 2-3x the size of any previous stage"
</estimates>

---

<decision-points>
decision_points:
  - id: stage-decomposition
    question: Should this stage be decomposed into sub-stages (like Stage 2 was split into 2a/2b)?
    decision: RESOLVED — Yes, decompose into 3 sub-stages (6a, 6b, 6c). See additional-context section for details.
    tradeoffs:
      - A single stage keeps the scope coherent but is very large (5/5 size, 5/5 complexity)
      - Sub-stages (e.g., 6a=session branches + per-turn commits, 6b=worktrees + merge, 6c=remote ops) allow incremental delivery and testing
      - Previous precedent exists — Stage 2 was decomposed into 2a (control flow) and 2b (persistence)
    recommendation:
      text: Decompose into 3 sub-stages. 6a=workspace config + session branches + per-turn commits + CXDB recording. 6b=worktree isolation + merge at fan-in + workspace snapshots + resume/replay at turn granularity. 6c=remote git operations + push policies + cleanup CLI.
      confidence: 5/5
    needs_context: []

  - id: git-operations-abstraction
    question: Should git operations be wrapped in an abstraction layer, or use subprocess calls directly?
    decision: RESOLVED — Subprocess wrapper around `git` CLI. No external library.
    tradeoffs:
      - A GitRepo abstraction (like gitpython or dulwich) provides a cleaner API but adds a dependency
      - Direct subprocess calls to `git` are simpler, have no dependency, and match the CLI-oriented design
      - GitPython is widely used but has known memory leak issues
      - dulwich is a pure-Python implementation but doesn't support worktrees well
    recommendation:
      text: Use a thin wrapper around subprocess `git` calls — no external git library dependency. This matches the existing pattern in builtins.py (subprocess for grep, shell) and keeps the dependency footprint small.
      confidence: 4/5
    needs_context: []

  - id: llm-commit-message-integration
    question: How should the LLM commit message generation be integrated — dedicated service, inline call, or configurable?
    decision: RESOLVED — Dedicated CommitMessageGenerator class using the "cheap" model alias from providers config.
    tradeoffs:
      - A dedicated CommitMessageGenerator class is testable and mockable
      - Inline LLM call in the workspace layer is simpler but harder to test
    recommendation:
      text: Dedicated CommitMessageGenerator class that accepts a CodergenBackend (or a simpler LLM call interface) and generates messages from diff + intent summary. Uses resolve_model("cheap", ...) for the model. Mock in tests with a deterministic generator.
      confidence: 4/5
    needs_context: []

  - id: worktree-merge-strategy
    question: What merge strategy should be used at fan-in, and how should conflicts be surfaced?
    decision: RESOLVED — Fail and surface conflict details to downstream node. No auto-resolution, no conflict agent.
    tradeoffs:
      - git merge (3-way) is the standard but may produce complex conflicts
      - git merge with --no-commit allows inspection before finalizing
      - Conflict surfacing to downstream agent requires encoding conflict markers in a structured format
      - Conflict surfacing to human via Interviewer adds a dependency on Stage 4
    recommendation:
      text: Use `git merge --no-commit` for each worktree branch into the session branch. On conflict, fail the merge and serialize conflict details (file list, conflict markers) into the context for the downstream node.
      confidence: 4/5
    needs_context: []

  - id: agent-turn-resume-state
    question: How should agent state be serialized for turn-level resume?
    tradeoffs:
      - LangGraph agent state can be serialized via its built-in checkpointing
      - CLIAgentBackend has no meaningful state to serialize
      - The plan mentions `agent_state_ref` — this could be a reference to a stored state blob or inline state
      - Inline state in CXDB turns could be large (full message history)
    recommendation:
      text: Store agent_state_ref as a reference to a LangGraph checkpoint ID (for LangGraph backend) or null (for CLI backend). Actual state restoration delegates to the backend's native checkpointing.
      confidence: 3/5
    needs_context:
      - Does LangGraph's checkpointing support external storage and restore-by-ID?
      - How large is typical LangGraph agent state?

  - id: repo-scoped-tools-implementation
    question: How should repo-scoped tools be generated — dynamic wrapper, tool factory, or tool registry per repo?
    tradeoffs:
      - Dynamic wrappers around existing builtins keep the tool registry simple
      - A tool factory creates named tools (`backend:read-file`) with proper path resolution
      - Per-repo tool registries duplicate tool definitions but are isolated
    recommendation:
      text: Tool factory approach — for each repo in the workspace config, generate wrapped versions of read-file, write-file, edit-file, search-code with the repo name prefix. Paths are resolved relative to the repo's working directory (or worktree path if in parallel).
      confidence: 4/5
    needs_context: []

  - id: cxdb-fork-for-replay
    question: Does CXDB support context forking, or does this need to be implemented?
    decision: RESOLVED — No native fork. Implement as create_context + copy turns.
    tradeoffs:
      - If CXDB has a native fork operation, replay is straightforward
      - If not, replay requires copying turns up to the fork point into a new context
      - The current CxdbClient has create_context and append_turn but no fork operation
    recommendation:
      text: Implement replay as create_context + copy turns up to the fork point. This avoids requiring new CXDB server features.
      confidence: 4/5
    needs_context: []

  - id: workspace-snapshot-in-checkpoint
    question: Should workspace snapshots be a separate CXDB turn type or added to the existing Checkpoint turn?
    tradeoffs:
      - Adding to Checkpoint (as a new field) requires a version bump but keeps snapshots colocated
      - A separate turn type is more modular but requires coordination to read both on resume
    recommendation:
      text: Add workspace_snapshot field to the existing Checkpoint turn (version bump to v3). This keeps resume logic simple — one turn has all state.
      confidence: 4/5
    needs_context: []

  - id: cleanup-age-threshold
    question: What should the default age threshold be for `orchestra cleanup`?
    tradeoffs:
      - Too short risks cleaning up paused sessions that are still useful
      - Too long accumulates stale branches
    recommendation:
      text: Default to 7 days for branches and worktrees, with a `--older-than` flag for override
      confidence: 4/5
    needs_context: []
</decision-points>

---

## Success Criteria Grade: A-

The plan includes detailed success criteria (23 items). They are well-structured and cover the major features. The main gap is that they are checklist items, not executable test commands. The automated test tables compensate for this. Suggested additions to reach A:

<success-criteria>
success_criteria:
  - id: session-branch-creation
    description: Pipeline start creates a session branch in each workspace repo following the naming convention
    command: |
      cd /tmp/test-repo && git branch | grep "orchestra/test-pipeline/"
    expected: At least one branch matching the pattern exists
    automated: true

  - id: per-turn-commit-isolation
    description: Each agent turn with file writes produces exactly one commit with only the written files staged
    command: |
      pytest tests/integration/test_workspace_commits.py -k "test_only_tracked_files_staged"
    expected: Exit code 0
    automated: true

  - id: llm-commit-message-format
    description: Commit messages have an imperative summary line under 72 chars, blank line, then description
    command: |
      pytest tests/unit/test_commit_message_generator.py -k "test_message_format"
    expected: Exit code 0
    automated: true

  - id: agent-metadata-in-commits
    description: Every per-turn commit has the correct author format and all required git trailers
    command: |
      pytest tests/integration/test_workspace_commits.py -k "test_agent_metadata"
    expected: Exit code 0 — author matches `{node_id} ({model}) <orchestra@local>`, all 6 trailers present
    automated: true

  - id: worktree-isolation
    description: Parallel agents writing to the same repo get isolated worktrees; changes are not visible across agents
    command: |
      pytest tests/integration/test_worktrees.py -k "test_worktree_isolation"
    expected: Exit code 0
    automated: true

  - id: worktree-merge-clean
    description: Non-conflicting parallel changes merge cleanly at fan-in
    command: |
      pytest tests/integration/test_worktrees.py -k "test_clean_merge"
    expected: Exit code 0 — session branch contains changes from both agents
    automated: true

  - id: worktree-merge-conflict
    description: Conflicting parallel changes surface conflict information to downstream node
    command: |
      pytest tests/integration/test_worktrees.py -k "test_merge_conflict_surfaced"
    expected: Exit code 0 — conflict details available in context
    automated: true

  - id: cxdb-agent-turn-with-sha
    description: AgentTurn CXDB turns include git_sha for turns with file writes, null for read-only turns
    command: |
      pytest tests/integration/test_workspace_cxdb.py -k "test_agent_turn_sha"
    expected: Exit code 0
    automated: true

  - id: checkpoint-workspace-snapshot
    description: Checkpoint turns include workspace_snapshot with HEAD SHAs for each repo
    command: |
      pytest tests/integration/test_workspace_cxdb.py -k "test_checkpoint_snapshot"
    expected: Exit code 0
    automated: true

  - id: resume-at-node-boundary
    description: Resume restores git repos to the correct commit SHAs from the checkpoint workspace_snapshot
    command: |
      pytest tests/integration/test_workspace_resume.py -k "test_resume_node_boundary"
    expected: Exit code 0
    automated: true

  - id: resume-at-agent-turn
    description: Resume with --turn flag restores git to the specific AgentTurn's git_sha
    command: |
      pytest tests/integration/test_workspace_resume.py -k "test_resume_agent_turn"
    expected: Exit code 0
    automated: true

  - id: bidirectional-correlation
    description: Can navigate from CXDB AgentTurn to git commit and from git commit trailers back to CXDB session/turn
    command: |
      pytest tests/integration/test_workspace_cxdb.py -k "test_bidirectional_correlation"
    expected: Exit code 0
    automated: true

  - id: repo-scoped-tools
    description: Repo-scoped tools resolve paths to the correct worktree/branch and record writes via WriteTracker
    command: |
      pytest tests/unit/test_repo_scoped_tools.py
    expected: Exit code 0
    automated: true

  - id: remote-clone-on-start
    description: Repos with remote configured are cloned when path doesn't exist
    command: |
      pytest tests/integration/test_remote_git.py -k "test_clone_on_start"
    expected: Exit code 0
    automated: true

  - id: push-on-completion
    description: Session branches pushed to remote when push policy is on_completion and pipeline succeeds
    command: |
      pytest tests/integration/test_remote_git.py -k "test_push_on_completion"
    expected: Exit code 0
    automated: true

  - id: push-failure-non-fatal
    description: Push failures are logged as warnings and do not fail the pipeline
    command: |
      pytest tests/integration/test_remote_git.py -k "test_push_failure_non_fatal"
    expected: Exit code 0
    automated: true

  - id: cleanup-command
    description: orchestra cleanup removes stale branches and orphaned worktrees, preserves active sessions
    command: |
      pytest tests/integration/test_cleanup.py
    expected: Exit code 0
    automated: true

  - id: full-lifecycle-e2e
    description: Full workspace lifecycle — branches created, per-turn commits with metadata, CXDB turns with SHAs, checkpoint with snapshot, branches remain after completion
    command: |
      pytest tests/integration/test_workspace_e2e.py -k "test_full_lifecycle"
    expected: Exit code 0
    automated: true

  - id: cli-backend-fallback
    description: CLIAgentBackend produces a single commit per node via git status detection
    command: |
      pytest tests/integration/test_workspace_commits.py -k "test_cli_backend_fallback"
    expected: Exit code 0
    automated: true

  - id: multi-repo-workspace
    description: Pipeline with 2 repos creates independent branches, commits, and snapshots per repo
    command: |
      pytest tests/integration/test_workspace_e2e.py -k "test_multi_repo"
    expected: Exit code 0
    automated: true

evaluation_dependencies:
  - pytest test framework
  - Temporary git repositories (created in fixtures)
  - Local bare repositories for remote simulation
  - Mock/stub for LLM commit message generation in tests
  - CXDB client (or mock) for turn recording verification
</success-criteria>

---

<missing-context>
missing_context:
  - category: technical
    items:
      - id: langgraph-checkpointing
        question: Does the current LangGraph integration support checkpointing and restore-by-ID?
        why_it_matters: Resume at agent-turn granularity requires restoring LangGraph agent state. The current LangGraphBackend creates a fresh agent on each run() call with no persistence.
        how_to_resolve: Review LangGraph's MemorySaver and checkpoint APIs; determine if the backend needs to be modified to support stateful checkpointing.
        status: open

      - id: worktree-git-version
        question: What minimum git version is required for worktree support?
        why_it_matters: Git worktrees were introduced in git 2.5 and have had various improvements since. Some features (worktree remove, worktree list --porcelain) require newer versions.
        how_to_resolve: Document minimum git version requirement (recommend 2.20+) and add a check in orchestra doctor.
        status: open
</missing-context>

---

<additional-context>
## Resolved Context

### Stage Decomposition — DECIDED: 3 sub-stages
Stage 6 will be decomposed into:
- **6a**: Workspace config + session branches + per-turn commits + CXDB AgentTurn recording
- **6b**: Worktree isolation + merge at fan-in + workspace snapshots + resume/replay at turn granularity
- **6c**: Remote git operations + push policies + cleanup CLI

### Git Operations Layer — DECIDED: Subprocess wrapper
Use a thin wrapper around subprocess `git` calls. No external git library dependency (no GitPython, no dulwich). This matches existing patterns in `src/orchestra/tools/builtins.py`.

### CXDB Fork — DECIDED: Copy turns (no native fork)
CXDB does not support native context forking. Replay will be implemented as `create_context` + copy turns from the source context up to the fork point into the new context.

### Model Tiers — RESOLVED: Exists in providers config
The tier concept exists via model aliases in `orchestra.yaml` providers section. The `providers.{name}.models` dict maps aliases (like `cheap`, `standard`) to concrete model strings. Commit message generation will use `resolve_model("cheap", provider_name, providers_config)` to get the appropriate model. See `src/orchestra/config/providers.py:resolve_model()` and `src/orchestra/config/model_resolution.py`.

### Merge Conflicts at Fan-In — DECIDED: Fail and surface details
When parallel agents produce merge conflicts at fan-in, the merge will fail and conflict details (conflicting file list, conflict markers) will be serialized into the context for the downstream node to handle. The pipeline does not auto-resolve or invoke a conflict-resolution agent.
</additional-context>

---

## Analysis

### Strengths
- The plan is remarkably detailed — branch naming conventions, YAML schemas, exact git trailer names, exact CXDB turn types, and 80+ test cases
- Test tables serve as a comprehensive specification
- The workspace config YAML examples cover local, cloud, and ephemeral deployment scenarios
- Manual testing guide is thorough with step-by-step verification
- Clear exclusions (multi-repo atomicity, transactional semantics) prevent scope creep

### Concerns
1. **Size is the primary risk.** This stage is 2-3x larger than any previous stage. It touches every subsystem. The decomposition decision point is the most important recommendation.
2. **Git operations are inherently stateful and brittle.** Tests need real git repos (temporary), and edge cases around dirty state, partial commits, and merge conflicts are numerous.
3. **The per-turn commit + LLM message generation creates a tight coupling** between the workspace layer and the agent loop. This needs careful design to avoid slowing down agent execution.
4. **Resume at agent-turn granularity requires LangGraph state serialization** that doesn't exist in the current backend implementation. This is a significant prerequisite.
5. **Replay via CXDB context forking** may require new CXDB server capabilities or a complex client-side simulation.
