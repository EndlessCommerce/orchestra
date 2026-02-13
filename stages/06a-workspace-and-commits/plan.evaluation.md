# Goal Evaluation: Stage 6a — Workspace Configuration, Session Branches, and Per-Turn Commits

## Goal Summary

Stage 6a introduces the foundational workspace layer: multi-repo workspace configuration in `orchestra.yaml`, session branch management, per-turn git commits with LLM-generated messages and agent metadata, CXDB recording of agent turns with git SHAs, and repo-scoped built-in tools. This is the core git integration for sequential (non-parallel) pipelines.

The plan is well-specified with concrete branch naming conventions, exact git trailer names, YAML schemas, and detailed test tables. The main areas requiring decisions are around how the workspace manager integrates with the existing runner/handler/event architecture.

---

<estimates>
ambiguity:
  rating: 2/5
  rationale:
    - "Branch naming, commit author format, git trailer names, and YAML schema are all explicitly specified"
    - "Test tables with 25+ test cases serve as an executable specification"
    - "The on_turn callback integration point is defined (from Stage 3) but the workspace wrapping pattern needs design"
    - "RepoContext fields are listed but the threading model (how it reaches tools during execution) needs design"
    - "CLIAgentBackend fallback trigger point is described but the exact hook location is unspecified"

complexity:
  rating: 3/5
  rationale:
    - "Git subprocess operations are straightforward but stateful — dirty state, staging, and branch management require careful error handling"
    - "The on_turn callback wrapping is the most complex piece — the workspace layer must intercept each turn, conditionally stage/commit, and add metadata"
    - "LLM commit message generation adds an external call in the hot path of agent execution"
    - "The workspace layer touches config, handlers, events, CXDB, and tools — moderate cross-cutting concern"
    - "No worktree or merge complexity (deferred to 6b) — this is the simpler sequential-only case"
    - "Maintenance cost is moderate — git operations are OS-dependent and subprocess-based"

size:
  rating: 4/5
  loc_estimate: "2000-3000 (production code) + 1200-1800 (tests)"
  worker_estimate: "4-5"
  rationale:
    - "New modules: workspace config models (~50 LOC), git ops wrapper (~150 LOC), session branch manager (~100 LOC), commit message generator (~80 LOC), workspace manager / on_turn wrapper (~200 LOC), repo-scoped tool factory (~100 LOC), workspace events (~60 LOC), RepoContext (~30 LOC)"
    - "MCP tool server for repo-scoped tools (~200 LOC), CLI agent abstraction interface (~100 LOC), Claude Code adapter (~60 LOC)"
    - "Modifications to existing modules: OrchestraConfig (~20 LOC), AgentTurn model (~10 LOC), AgentTurnCompleted event (~5 LOC), CxdbObserver (~20 LOC), cli/run.py (~40 LOC), handlers/registry.py (~15 LOC), CLIAgentBackend (~50 LOC)"
    - "~30 automated test cases (including MCP tool server and CLI agent integration)"
    - "Larger than Stage 2b or Stage 3 due to MCP server scope"
</estimates>

---

<decision-points>
decision_points:
  - id: workspace-manager-architecture
    question: How should the WorkspaceManager integrate with the existing runner/handler/event architecture?
    decision: "RESOLVED — Option C (hybrid). CLI calls setup_session() for branches. WorkspaceManager is also an EventObserver (StageStarted/StageCompleted for node tracking). WorkspaceManager.on_turn_callback() is passed to CodergenHandler. Runner stays unmodified."
    tradeoffs:
      - "Option A: Inject WorkspaceManager into the runner — runner calls it at pipeline start (create branches) and passes it to handlers. Clean but couples runner to workspace."
      - "Option B: Use event observers — WorkspaceManager listens for PipelineStarted (create branches) and AgentTurnCompleted (commit). Decoupled but the observer pattern is fire-and-forget, not suitable for branch creation that must complete before execution."
      - "Option C: Hybrid — CLI run command calls WorkspaceManager.setup() before runner.run(), and WorkspaceManager wraps the on_turn callback for per-turn commits. Keeps runner unmodified."
    recommendation:
      text: "Option C (hybrid). CLI run command calls workspace.setup_session() before runner.run() for branch creation. The on_turn callback passed to CodergenHandler is a workspace-aware wrapper that stages/commits on each turn. This avoids modifying the runner and keeps the workspace layer at the edges."
      confidence: 4/5
    needs_context: []

  - id: on-turn-wrapping
    question: How does the workspace layer's on_turn wrapper get access to session metadata (pipeline name, session ID, node ID, repo config)?
    decision: "RESOLVED — WorkspaceManager method. Initialized with session metadata at setup time. on_turn_callback method passed as the on_turn parameter."
    tradeoffs:
      - "Closure capture — the wrapper function closes over session state when constructed in cli/run.py. Simple but creates a large closure."
      - "WorkspaceManager instance — the wrapper is a method on WorkspaceManager which holds session state. Testable and clean."
      - "Context injection — session metadata is added to the Context object and read from there. Requires modifying Context."
    recommendation:
      text: "WorkspaceManager method. WorkspaceManager is initialized with session metadata at setup time, and its on_turn_callback method is passed as the on_turn parameter. This is testable and keeps state encapsulated."
      confidence: 5/5
    needs_context: []

  - id: cli-write-tracking
    question: How should CLIAgentBackend file writes be tracked — git-status fallback or MCP tool server?
    decision: "RESOLVED — MCP tool server. Orchestra serves repo-scoped write tools over MCP. CLIAgentBackend launches the external agent with file-write tools disabled and Orchestra's MCP server attached. All writes go through WriteTracker. No fallback path needed."
    tradeoffs:
      - "Git-status fallback is simpler but creates two commit paths with different behaviors."
      - "MCP tool server is more infrastructure but creates a single uniform write-tracking path for all backends."
      - "Disabling native write tools in the CLI agent requires an abstracted interface for tool restrictions."
    recommendation:
      text: "MCP tool server. Eliminates the fallback path entirely. All file writes go through Orchestra's WriteTracker regardless of backend type."
      confidence: 4/5
    needs_context: []

  - id: cli-agent-abstraction
    question: How should tool restrictions and MCP server config be passed to CLI agents?
    decision: "RESOLVED — Abstract interface. CLIAgentBackend accepts a generic tool restriction config (allowed/disallowed tools, MCP server paths) that hides implementation details of the specific CLI agent. Concrete implementations map to agent-specific flags (e.g., Claude Code --allowedTools, --mcp-server)."
    tradeoffs:
      - "Agent-specific flags are quick but brittle — each new agent type needs custom code."
      - "Abstract interface is more work upfront but supports multiple CLI agents cleanly."
    recommendation:
      text: "Abstract interface with a concrete Claude Code implementation. The interface defines tool_restrictions and mcp_servers as configuration. The Claude Code adapter maps these to --allowedTools and --mcp-server flags."
      confidence: 4/5
    needs_context: []

  - id: commit-message-sync-vs-async
    question: Should LLM commit message generation be synchronous (blocking the agent loop) or asynchronous?
    decision: "RESOLVED — Synchronous. Commit completes before next agent turn."
    tradeoffs:
      - "Synchronous is simpler — commit completes before next agent turn. Adds latency to each turn with writes."
      - "Asynchronous (fire-and-forget commit) is faster but risks ordering issues and incomplete commits on crash."
      - "The cheap model tier should be fast (e.g., Haiku-class) so latency is likely <1s per commit."
    recommendation:
      text: "Synchronous. The commit should complete before the next agent turn begins. This ensures the git SHA is available for CXDB recording and prevents race conditions. The cheap model should be fast enough."
      confidence: 5/5
    needs_context: []

  - id: commit-message-fallback
    question: What happens if the LLM commit message generation fails (API error, timeout)?
    decision: "RESOLVED — Deterministic fallback. Never fail the pipeline because of a commit message."
    tradeoffs:
      - "Fail the agent turn — safe but disruptive."
      - "Use a deterministic fallback message — e.g., 'chore: auto-commit files from agent turn {n}'. Keeps the pipeline running."
      - "Retry once, then fallback — best-effort LLM message with a safety net."
    recommendation:
      text: "Deterministic fallback message on any LLM failure. Use 'chore: auto-commit agent changes' with a body listing the files. Log a warning. Never fail the pipeline because of a commit message."
      confidence: 5/5
    needs_context: []

  - id: agent-turn-cxdb-version
    question: Should the dev.orchestra.AgentTurn CXDB type be version-bumped (v2) to add git_sha and commit_message, or extend v1?
    decision: "RESOLVED — Version bump to v2."
    tradeoffs:
      - "Version bump (v2) is cleaner — new fields are clearly associated with the workspace feature."
      - "Extending v1 with optional fields is simpler — CXDB may handle missing fields gracefully."
    recommendation:
      text: "Version bump to v2. The git_sha and commit_message fields are a meaningful schema change. V1 AgentTurns from pre-workspace sessions remain valid."
      confidence: 4/5
    needs_context: []

  - id: repo-tool-registration
    question: When are repo-scoped tools generated — at config load time, at pipeline start, or lazily?
    decision: "RESOLVED — At pipeline start, during workspace.setup_session()."
    tradeoffs:
      - "Config load time — tools available before pipeline runs, but workspace config may not be finalized."
      - "Pipeline start (setup_session) — tools generated when repos are validated and branches created. Natural point."
      - "Lazily on first use — complex and error-prone."
    recommendation:
      text: "At pipeline start, during workspace.setup_session(). This is when repos are validated and branches created, so it's the natural point to generate repo-scoped tools."
      confidence: 4/5
    needs_context: []

  - id: workspace-config-validation
    question: When should workspace config be validated — what errors should be caught early?
    decision: "RESOLVED — Validate at setup_session. Also validate that the 'cheap' model alias resolves to a real model."
    tradeoffs:
      - "Validate at config load (repo paths exist, are git repos, branch prefix format) — fast fail."
      - "Validate at session setup — can check git status, HEAD exists, etc."
      - "Both — validation at load for format, at setup for git state."
    recommendation:
      text: "Validate at setup_session. Check that each repo path exists, is a git repo (has .git), has a clean enough state to create a branch, HEAD is valid, and the 'cheap' model alias resolves. Raise a clear error if any check fails."
      confidence: 4/5
    needs_context: []
</decision-points>

---

## Success Criteria Grade: A-

The plan includes 12 explicit success criteria items covering all major features. The test tables add 25+ automated test cases. The main gap is that success criteria are checklist items rather than executable commands. Suggested executable criteria:

<success-criteria>
success_criteria:
  - id: workspace-config-parsed
    description: OrchestraConfig successfully parses workspace.repos section from orchestra.yaml
    command: |
      pytest tests/unit/test_workspace_config.py -k "test_parse_workspace_config"
    expected: Exit code 0
    automated: true

  - id: session-branch-creation
    description: Pipeline start creates a session branch in each workspace repo following naming convention
    command: |
      pytest tests/integration/test_session_branches.py -k "test_branch_creation"
    expected: Exit code 0 — branch matches {prefix}{pipeline}/{session-id}
    automated: true

  - id: session-branch-multi-repo
    description: Two repos configured produces two independent session branches
    command: |
      pytest tests/integration/test_session_branches.py -k "test_multi_repo_branches"
    expected: Exit code 0
    automated: true

  - id: session-branch-persists
    description: Session branch still exists after pipeline completion (not auto-deleted)
    command: |
      pytest tests/integration/test_session_branches.py -k "test_branch_persists"
    expected: Exit code 0
    automated: true

  - id: per-turn-commit-isolation
    description: Each agent turn with file writes produces exactly one commit with only the written files staged
    command: |
      pytest tests/integration/test_per_turn_commits.py -k "test_only_tracked_files_staged"
    expected: Exit code 0
    automated: true

  - id: per-turn-commit-chain
    description: 3 agent turns with writes produce 3 separate commits on the session branch
    command: |
      pytest tests/integration/test_per_turn_commits.py -k "test_multiple_turns_multiple_commits"
    expected: Exit code 0
    automated: true

  - id: no-commit-on-read-only-turn
    description: Agent turn that only reads files produces no commit
    command: |
      pytest tests/integration/test_per_turn_commits.py -k "test_turn_without_writes_no_commit"
    expected: Exit code 0
    automated: true

  - id: commit-message-format
    description: LLM-generated commit message has imperative summary under 72 chars, blank line, then description
    command: |
      pytest tests/unit/test_commit_message_generator.py -k "test_message_format"
    expected: Exit code 0
    automated: true

  - id: commit-message-fallback
    description: LLM failure produces a deterministic fallback commit message without failing the pipeline
    command: |
      pytest tests/unit/test_commit_message_generator.py -k "test_fallback_on_error"
    expected: Exit code 0
    automated: true

  - id: agent-metadata-author
    description: Commit author matches {node_id} ({model}) <orchestra@local>
    command: |
      pytest tests/integration/test_per_turn_commits.py -k "test_agent_metadata_in_author"
    expected: Exit code 0
    automated: true

  - id: agent-metadata-trailers
    description: Each commit has all 6 required git trailers (Model, Provider, Node, Pipeline, Session, Turn)
    command: |
      pytest tests/integration/test_per_turn_commits.py -k "test_agent_metadata_in_trailers"
    expected: Exit code 0
    automated: true

  - id: mcp-tool-server
    description: MCP stdio server exposes repo-scoped write tools and routes writes through WriteTracker
    command: |
      pytest tests/unit/test_mcp_server.py
    expected: Exit code 0
    automated: true

  - id: cli-agent-mcp-integration
    description: CLIAgentBackend launches with MCP server attached and native write tools disabled; writes go through Orchestra
    command: |
      pytest tests/integration/test_cli_agent_mcp.py -k "test_writes_through_mcp"
    expected: Exit code 0
    automated: true

  - id: cxdb-agent-turn-with-sha
    description: AgentTurn CXDB turns include git_sha for turns with writes, null for read-only turns
    command: |
      pytest tests/integration/test_cxdb_agent_turns.py -k "test_agent_turn_sha"
    expected: Exit code 0
    automated: true

  - id: bidirectional-correlation
    description: CXDB AgentTurn git_sha matches git commit; git commit trailers identify CXDB session/turn
    command: |
      pytest tests/integration/test_cxdb_agent_turns.py -k "test_bidirectional_correlation"
    expected: Exit code 0
    automated: true

  - id: repo-scoped-tools
    description: Per-repo tools resolve paths relative to repo directory and record writes via WriteTracker
    command: |
      pytest tests/unit/test_repo_scoped_tools.py
    expected: Exit code 0
    automated: true

  - id: full-lifecycle-e2e
    description: Full workspace lifecycle — branch created, per-turn commits with metadata, CXDB turns with SHAs, branch remains after completion
    command: |
      pytest tests/integration/test_workspace_e2e.py -k "test_full_lifecycle"
    expected: Exit code 0
    automated: true

evaluation_dependencies:
  - pytest test framework
  - Temporary git repositories (created in fixtures via git init)
  - Mock/deterministic CommitMessageGenerator for tests (avoid real LLM calls)
  - CXDB client mock or test instance for turn recording verification
</success-criteria>

---

<missing-context>
missing_context:
  - category: technical
    items:
      - id: cheap-model-alias-existence
        question: Is the "cheap" model alias currently configured in any orchestra.yaml, or does it need to be added to documentation/examples?
        why_it_matters: The CommitMessageGenerator uses resolve_model("cheap", ...) — if no "cheap" alias exists in the user's config, the resolution will fall through to using "cheap" as a literal model name, which will fail. Resolved decision is to error at setup_session if alias is missing.
        how_to_resolve: Check existing orchestra.yaml examples; ensure the "cheap" alias is documented as required when workspace is configured.
        status: open

      - id: on-turn-wiring-in-registry
        question: The current default_registry() creates CodergenHandler without an on_turn callback. How is on_turn currently wired in production?
        why_it_matters: The workspace layer needs to inject its on_turn wrapper into CodergenHandler. Currently, default_registry() at line 44 creates CodergenHandler(backend=backend, config=config) with no on_turn. The workspace on_turn needs to be passed here.
        how_to_resolve: Modify default_registry() to accept an optional on_turn parameter and pass it to CodergenHandler. The cli/run.py would construct the workspace on_turn callback and pass it when building the registry.
        status: resolved — approach confirmed (modify default_registry signature)

      - id: mcp-server-transport
        question: What MCP transport should the tool server use — stdio, HTTP/SSE, or Unix socket?
        why_it_matters: The MCP server serves repo-scoped write tools to CLI agents. The transport must work with the CLI agent's MCP client implementation.
        how_to_resolve: Check what MCP transports Claude Code supports. Stdio is the most common for local MCP servers.
        status: open
</missing-context>

---

<additional-context>
## Resolved Context

### Architecture — DECIDED: Hybrid (Option C)
CLI run command calls `workspace.setup_session()` before `runner.run()` for branch creation. WorkspaceManager is also an EventObserver (listens for StageStarted/StageCompleted for node tracking). `WorkspaceManager.on_turn_callback()` is passed through `default_registry()` to `CodergenHandler`. Runner stays unmodified.

### CLI Write Tracking — DECIDED: MCP tool server (no git-status fallback)
Orchestra serves repo-scoped write tools (`{repo}:write-file`, `{repo}:edit-file`) over MCP. CLIAgentBackend launches the external agent with native file-write tools disabled and Orchestra's MCP server attached. All writes flow through WriteTracker. This eliminates the fallback path — all backends use the same per-turn commit mechanism.

### CLI Agent Abstraction — DECIDED: Abstract interface
CLIAgentBackend accepts a generic configuration for tool restrictions (allowed/disallowed tools) and MCP servers, hiding implementation details of the specific CLI agent. A concrete Claude Code adapter maps these to `--allowedTools` and `--mcp-server` flags. Other CLI agents can be supported by adding new adapters.

### Commit Messages — DECIDED: Synchronous with deterministic fallback
LLM commit message generation is synchronous (blocks until complete). On any LLM failure, a deterministic fallback message is used (`chore: auto-commit agent changes` with file list in body). The pipeline never fails because of a commit message.

### Cheap Model Alias — DECIDED: Error at setup_session
If the `cheap` model alias cannot be resolved via `resolve_model("cheap", ...)`, `workspace.setup_session()` raises a clear error telling the user to configure the alias in their `orchestra.yaml` providers section.

### CXDB AgentTurn — DECIDED: Version bump to v2
The `dev.orchestra.AgentTurn` type is bumped to v2 with new fields: `git_sha` (string, nullable) and `commit_message` (string, nullable). V1 turns from pre-workspace sessions remain valid.
</additional-context>

---

## Analysis

### Strengths
- Well-scoped sub-stage — sequential-only git integration, no worktree complexity
- Concrete specifications for branch naming, commit metadata, and CXDB turn schema
- Clear deferred items prevent scope creep into 6b/6c territory
- Test tables serve as executable specification with 25+ test cases
- Clean prerequisite chain (requires Stage 5 only for registry integration)

### Integration Points (files that need modification)

| File | Change |
|------|--------|
| `src/orchestra/config/settings.py` | Add `WorkspaceConfig`, `RepoConfig` models to `OrchestraConfig` |
| `src/orchestra/models/agent_turn.py` | Add `git_sha` and `commit_message` fields |
| `src/orchestra/events/types.py` | Add `SessionBranchCreated`, `AgentCommitCreated` events |
| `src/orchestra/events/observer.py` | Handle new event types in `StdoutObserver` and `CxdbObserver` |
| `src/orchestra/storage/type_bundle.py` | Bump `dev.orchestra.AgentTurn` to v2 with git_sha field |
| `src/orchestra/handlers/registry.py` | Accept and pass `on_turn` to `CodergenHandler` |
| `src/orchestra/cli/run.py` | Initialize workspace manager, create branches, wire on_turn, start MCP server |
| `src/orchestra/backends/cli_agent.py` | Accept tool restrictions and MCP server config via abstract interface |

### New Modules

| Module | Responsibility |
|--------|---------------|
| `src/orchestra/workspace/git_ops.py` | Thin subprocess wrapper for git commands |
| `src/orchestra/workspace/session_branch.py` | Create/manage session branches per repo |
| `src/orchestra/workspace/workspace_manager.py` | Orchestrates setup, on_turn wrapping, EventObserver for node tracking |
| `src/orchestra/workspace/commit_message.py` | LLM-based commit message generation with deterministic fallback |
| `src/orchestra/workspace/repo_context.py` | RepoContext dataclass |
| `src/orchestra/workspace/repo_tools.py` | Tool factory for repo-scoped built-in tools |
| `src/orchestra/workspace/mcp_server.py` | MCP stdio server exposing repo-scoped tools to CLI agents |
| `src/orchestra/backends/cli_agent_config.py` | Abstract interface for CLI agent tool restrictions and MCP servers |

### Concerns
1. **The on_turn callback threading is the trickiest integration.** The workspace on_turn wrapper must be constructed with session metadata, then passed through cli/run.py → default_registry() → CodergenHandler → backend.run(). This is a multi-layer pass-through.
2. **LLM commit message generation adds latency.** Using the cheap tier mitigates this, but each turn with file writes will block for an LLM call. Deterministic fallback on failure is essential.
3. **Git state assumptions.** The workspace layer assumes repos are in a clean state at session start. Dirty working trees, uncommitted changes, or detached HEAD states need clear error handling.
4. **MCP server lifecycle.** The MCP stdio server must start before the CLI agent launches and stop after it exits. Process management and error handling need care — a hung MCP server shouldn't orphan processes.
