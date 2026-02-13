# Stage 6a: Workspace Configuration, Session Branches, and Per-Turn Commits

## Overview

Add the foundational workspace layer: multi-repo workspace configuration in `orchestra.yaml`, session branch management, per-turn git commits with LLM-generated messages and agent metadata, and CXDB recording of agent turns with git SHAs. After this stage, every pipeline run creates a session branch, and agent changes are committed automatically with full traceability between git history and CXDB session data.

This is the first of three sub-stages decomposing Stage 6 (Git Integration and Workspace Management). It focuses on the core git integration that works for sequential (non-parallel) pipelines. Worktree isolation for parallel agents is deferred to Stage 6b. Remote git operations are deferred to Stage 6c.

## What a Human Can Do After This Stage

1. Configure workspaces in `orchestra.yaml` with one or more repos
2. Run a pipeline and see it create session branches (`orchestra/pipeline-name/session-id`)
3. Observe agents commit their changes to the session branch automatically after each turn
4. See LLM-generated commit messages (not generic "auto-commit")
5. Inspect commit author and git trailers tracing back to the CXDB session/node/turn
6. Correlate CXDB AgentTurn entries with git commits via SHA
7. Use `git log` on the session branch to see the full history of agent changes

## Prerequisites

- Stage 5 complete (parallel execution — needed for handler registry integration)
- Stage 2b complete (checkpoint/resume — CXDB recording extends existing checkpoint infrastructure)

## Scope

### Included

- **Multi-Repo Workspace Configuration.** `workspace.repos` section in `orchestra.yaml`: named repos with paths and branch prefixes. Single-repo is the degenerate case. Repo-qualified tool naming (`backend:run-tests`).
- **Session Branches.** At pipeline start, create a session branch in each workspace repo: `{branch_prefix}{pipeline-name}/{session-short-id}`. Record base commit SHA per repo. Branches left in place on completion for user to merge/delete.
- **Git Operations Layer.** Thin wrapper around subprocess `git` CLI calls — no external git library dependency. Provides: `create_branch`, `checkout`, `add`, `commit`, `status`, `log`, `rev_parse`, `diff`. All operations take a `cwd` parameter for repo path.
- **Per-Turn Commits (via `on_turn` callback).** The workspace layer hooks into the `on_turn` callback from CodergenBackend (implemented in Stage 3). After each agent turn that has `files_written`, the workspace layer: (1) stages exactly those files with `git add`, (2) generates a commit message via an LLM call (cheap model tier) from the diff and agent intent, (3) commits with agent metadata (author and git trailers), (4) records the SHA in the `dev.orchestra.AgentTurn` CXDB turn.
- **LLM Commit Message Generation.** A dedicated `CommitMessageGenerator` class that uses the `cheap` model alias from the providers config (`resolve_model("cheap", ...)`) to generate a conventional commit message from the staged diff and a summary of the agent's intent (extracted from the turn's messages). The message has an imperative summary line (under 72 chars) and a brief description. Mockable in tests with a deterministic generator.
- **Agent Metadata in Git.** Each per-turn commit includes: commit author set to `{node_id} ({model}) <orchestra@local>`, and git trailers: `Orchestra-Model`, `Orchestra-Provider`, `Orchestra-Node`, `Orchestra-Pipeline`, `Orchestra-Session`, `Orchestra-Turn`. This enables tracing from any git commit back to the CXDB session/node/turn.
- **MCP Tool Server for CLI Agents.** Orchestra runs an MCP stdio server exposing repo-scoped write tools (`{repo}:write-file`, `{repo}:edit-file`). When CLIAgentBackend is used, the external agent is launched with native file-write tools disabled and Orchestra's MCP server attached. All file writes from any backend flow through Orchestra's WriteTracker, ensuring uniform per-turn commit behavior. No git-status fallback path is needed.
- **CLI Agent Abstraction.** CLIAgentBackend accepts a generic configuration for tool restrictions (allowed/disallowed tools) and MCP servers, hiding implementation details of the specific CLI agent. A concrete Claude Code adapter maps these to `--allowedTools` and `--mcp-server` flags. Other CLI agents can be supported by adding new adapters.
- **Per-Turn CXDB Recording.** Each agent turn (whether or not it has file writes) is recorded as a `dev.orchestra.AgentTurn` CXDB turn with: turn_number, model, provider, messages, tool_calls, files_written, token_usage, git_sha (null if no files changed), commit_message, and agent_state_ref.
- **Workspace Events.** Events for branch creation (`SessionBranchCreated`) and per-turn commit (`AgentCommitCreated`).
- **RepoContext.** Context object passed to tools containing repo path, current branch, and git state. (Worktree path added in 6b.)
- **Repo-Scoped Built-In Tools.** Auto-generate per-repo versions of built-in tools (read-file, write-file, edit-file, search-code) that operate on the repo's working directory. Write tools call the WriteTracker (from Stage 3) to record modifications. Tool factory generates `{repo_name}:read-file`, `{repo_name}:write-file`, etc.

### Excluded (deferred)

- Worktree-per-agent isolation for parallel execution (Stage 6b)
- Worktree merge at fan-in (Stage 6b)
- Workspace snapshots in Checkpoint turns (Stage 6b)
- Resume at agent turn granularity (Stage 6b)
- Replay at agent turn granularity (Stage 6b)
- Remote git operations — clone, fetch, push (Stage 6c)
- Push policies (Stage 6c)
- `orchestra cleanup` CLI command (Stage 6c)
- Multi-repo coordination atomicity (deferred indefinitely)
- Transactional semantics across repos (deferred indefinitely)

### Workspace Configuration (Local Only)

```yaml
# orchestra.yaml — single repo workspace
workspace:
  repos:
    project:
      path: ./my-project
      branch_prefix: orchestra/

# orchestra.yaml — multi-repo workspace
workspace:
  repos:
    backend:
      path: /workspace/backend
      branch_prefix: orchestra/
    frontend:
      path: /workspace/frontend
      branch_prefix: orchestra/
```

Note: `remote`, `push`, and `clone_depth` fields are recognized but ignored in 6a. They are implemented in Stage 6c.

## Investigation

- [x] Review how `on_turn` callback is currently defined and wired (or not) in production code
  - `CodergenHandler.__init__` accepts `on_turn: OnTurnCallback | None = None` (`src/orchestra/handlers/codergen_handler.py:20`)
  - `default_registry()` at `src/orchestra/handlers/registry.py:44` creates `CodergenHandler(backend=backend, config=config)` — **no on_turn passed**
  - `LangGraphBackend.run()` at `src/orchestra/backends/langgraph_backend.py:34` accepts `on_turn` and fires it for each tool-calling step with `AgentTurn` including `files_written` from `WriteTracker.flush()`
  - `CLIAgentBackend.run()` accepts `on_turn` but never calls it (subprocess-based, no per-turn visibility)
  - **Gap confirmed**: on_turn is defined in protocol and supported by handler/backend, but never wired in production. `default_registry()` needs an `on_turn` parameter.

- [x] Review how WriteTracker integrates with builtins and LangGraphBackend
  - `WriteTracker` at `src/orchestra/backends/write_tracker.py` — simple `record(path)`/`flush()` with dict-backed storage
  - `write-file` and `edit-file` builtins accept optional `write_tracker` parameter and call `record()` on write
  - `LangGraphBackend` has a `_write_tracker` instance, calls `flush()` after each tool-calling step, populates `AgentTurn.files_written`
  - **Key**: `files_written` from `AgentTurn` tells the workspace layer exactly which files to `git add`

- [x] Review existing CXDB type bundle for AgentTurn v1 schema
  - `dev.orchestra.AgentTurn` v1 at `src/orchestra/storage/type_bundle.py:132-165` — fields: turn_number, node_id, model, provider, messages, tool_calls, files_written, token_usage, agent_state
  - `CxdbObserver._append_agent_turn()` at `src/orchestra/events/observer.py:157` emits v1 data from `AgentTurnCompleted` event
  - **Need**: v2 adds `git_sha` (field 10) and `commit_message` (field 11)

- [x] Review CLIAgentBackend for MCP/tool restriction integration points
  - `CLIAgentBackend` at `src/orchestra/backends/cli_agent.py` — runs `claude` command via subprocess with `--` args and env vars
  - No MCP server support, no tool restriction flags
  - `build_backend()` at `src/orchestra/cli/backend_factory.py:33` creates `CLIAgentBackend()` with no configuration
  - **Need**: Accept `CLIAgentConfig` with tool_restrictions and mcp_servers; Claude Code adapter maps to `--allowedTools` and `--mcp-server` flags

- [x] Review cli/run.py for workspace integration points
  - `run()` at `src/orchestra/cli/run.py:25` — loads config, parses graph, connects CXDB, builds backend and registry, runs pipeline
  - Integration point: between `build_backend()` (line 111) and `runner.run()` (line 125) — insert workspace setup, pass on_turn to registry
  - `display_id` (line 93) serves as session ID for branch naming

- [x] Confirm no existing MCP or git infrastructure in codebase
  - No MCP code exists anywhere in `src/orchestra/`
  - No git utility code exists — this is all new

## Plan

### 1. Add workspace configuration models to OrchestraConfig

- [ ] Create `RepoConfig` Pydantic model with fields: `path: str`, `branch_prefix: str = "orchestra/"`, `remote: str = ""` (recognized but ignored in 6a), `push: str = ""` (recognized but ignored), `clone_depth: int = 0` (recognized but ignored)
  - [ ] Update `src/orchestra/config/settings.py` — add `RepoConfig` and `WorkspaceConfig` models
  - [ ] `WorkspaceConfig` has `repos: dict[str, RepoConfig] = Field(default_factory=dict)`
  - [ ] Add `workspace: WorkspaceConfig = WorkspaceConfig()` to `OrchestraConfig`
  - [ ] Path resolution: relative paths resolved against `config_dir` (the directory containing `orchestra.yaml`)
  - [ ] Write unit tests: `tests/unit/test_workspace_config.py` — parse single repo, multi-repo, empty workspace, relative path resolution, unknown fields ignored
  - [ ] Run tests, verify passing
  - [ ] Mark TODO complete and commit the changes to git

### 2. Create git operations layer

- [ ] Create `src/orchestra/workspace/__init__.py` (empty package init)
- [ ] Create `src/orchestra/workspace/git_ops.py` — thin subprocess wrapper around git CLI
  - [ ] `run_git(*args, cwd: Path) -> str` — core runner, raises `GitError` on non-zero exit
  - [ ] `GitError(Exception)` with `returncode`, `stderr`, `command` fields
  - [ ] `rev_parse(ref: str, cwd: Path) -> str` — resolve ref to SHA
  - [ ] `create_branch(name: str, cwd: Path) -> None` — `git checkout -b {name}`
  - [ ] `checkout(ref: str, cwd: Path) -> None` — `git checkout {ref}`
  - [ ] `add(paths: list[str], cwd: Path) -> None` — `git add` exactly the listed paths
  - [ ] `commit(message: str, author: str, trailers: dict[str, str], cwd: Path) -> str` — `git commit` with `--author` and `--trailer` flags, returns commit SHA via `rev_parse("HEAD")`
  - [ ] `status(cwd: Path) -> str` — `git status --porcelain`
  - [ ] `log(n: int, format: str, cwd: Path) -> str` — `git log -n {n} --format={format}`
  - [ ] `diff(staged: bool, cwd: Path) -> str` — `git diff` or `git diff --cached`
  - [ ] `is_git_repo(path: Path) -> bool` — check if path is inside a git working tree
  - [ ] `current_branch(cwd: Path) -> str` — `git rev-parse --abbrev-ref HEAD`
  - [ ] Write unit tests: `tests/unit/test_git_ops.py` — use `git init` in tmp dirs to test each operation. Test: create_branch, checkout, add+commit, rev_parse, status, diff, is_git_repo, GitError on bad commands
  - [ ] Run tests, verify passing
  - [ ] Mark TODO complete and commit the changes to git

### 3. Create session branch manager

- [ ] Create `src/orchestra/workspace/session_branch.py`
  - [ ] `create_session_branches(repos: dict[str, RepoConfig], pipeline_name: str, session_id: str, config_dir: Path) -> dict[str, SessionBranchInfo]`
  - [ ] `SessionBranchInfo` dataclass: `repo_name: str`, `repo_path: Path`, `branch_name: str`, `base_sha: str`
  - [ ] For each repo: resolve path (relative to config_dir), validate it's a git repo, record base SHA (`rev_parse("HEAD")`), create branch `{prefix}{pipeline_name}/{session_id}`, checkout branch
  - [ ] Branch naming: sanitize pipeline_name (replace spaces/special chars with hyphens)
  - [ ] Validation: raise `WorkspaceError` if repo path doesn't exist, isn't a git repo, or HEAD is invalid
  - [ ] Write unit tests: `tests/unit/test_session_branch.py` — branch creation, naming convention, base SHA recording, multi-repo, branch persists after function returns, validation errors for bad paths
  - [ ] Run tests, verify passing
  - [ ] Mark TODO complete and commit the changes to git

### 4. Add workspace events

- [ ] Update `src/orchestra/events/types.py`
  - [ ] Add `SessionBranchCreated(Event)` — fields: `repo_name: str`, `branch_name: str`, `base_sha: str`, `repo_path: str`
  - [ ] Add `AgentCommitCreated(Event)` — fields: `repo_name: str`, `node_id: str`, `sha: str`, `message: str`, `files: list[str]`, `turn_number: int`
  - [ ] Add both to `EVENT_TYPE_MAP`
- [ ] Update `src/orchestra/events/observer.py`
  - [ ] `StdoutObserver.on_event()` — handle `SessionBranchCreated` (log branch name) and `AgentCommitCreated` (log SHA and message summary)
  - [ ] `CxdbObserver.on_event()` — no CXDB recording needed for these events (they're informational; the git data flows through AgentTurn v2)
- [ ] Write unit tests: test event construction, StdoutObserver output for new events
- [ ] Run tests, verify passing
- [ ] Mark TODO complete and commit the changes to git

### 5. Extend AgentTurn model and CXDB type bundle

- [ ] Update `src/orchestra/models/agent_turn.py`
  - [ ] Add `git_sha: str = ""` and `commit_message: str = ""` fields to `AgentTurn` dataclass
  - [ ] Update `to_dict()` to include new fields
- [ ] Update `src/orchestra/events/types.py`
  - [ ] Add `git_sha: str = ""` and `commit_message: str = ""` to `AgentTurnCompleted` event
- [ ] Update `src/orchestra/storage/type_bundle.py`
  - [ ] Add `dev.orchestra.AgentTurn` v2 with fields 1-9 (same as v1) plus field `10: git_sha (string, optional)` and field `11: commit_message (string, optional)`
- [ ] Update `src/orchestra/events/observer.py`
  - [ ] `CxdbObserver._append_agent_turn()` — emit v2 with `git_sha` and `commit_message` fields; use `type_version=2`
- [ ] Write unit tests: verify AgentTurn.to_dict() includes new fields, verify CxdbObserver emits v2 data
- [ ] Run existing tests to ensure backward compatibility
- [ ] Mark TODO complete and commit the changes to git

### 6. Create commit message generator

- [ ] Create `src/orchestra/workspace/commit_message.py`
  - [ ] `CommitMessageGenerator` protocol/ABC with `generate(diff: str, intent: str) -> str`
  - [ ] `LLMCommitMessageGenerator` — uses `resolve_model("cheap", ...)` and a LangChain ChatModel to generate messages
    - [ ] Prompt template: given a git diff and a summary of the agent's intent, produce a conventional commit message with imperative summary line (under 72 chars) and brief description
    - [ ] Extracts intent from the agent turn's most recent human message (or a summary of tool calls)
    - [ ] On any error (API failure, timeout, malformed response): logs a warning, returns fallback message
  - [ ] `DeterministicCommitMessageGenerator` — returns `"chore: auto-commit agent changes\n\nFiles: {file_list}"`. Used in tests and as fallback.
  - [ ] `build_commit_message_generator(config: OrchestraConfig) -> CommitMessageGenerator` factory function
    - [ ] Resolves `cheap` model alias; if it can't resolve (literal "cheap" returned), raise `WorkspaceError` with clear message to configure the alias
    - [ ] Builds a LangChain ChatModel for the cheap tier (reuse pattern from `backend_factory.build_chat_model()` but with the cheap alias)
  - [ ] Write unit tests: `tests/unit/test_commit_message_generator.py` — test LLM generator with mocked model, test deterministic generator, test fallback on error, test message format validation (summary line length, imperative mood heuristic), test intent extraction from messages
  - [ ] Run tests, verify passing
  - [ ] Mark TODO complete and commit the changes to git

### 7. Create RepoContext and repo-scoped tool factory

- [ ] Create `src/orchestra/workspace/repo_context.py`
  - [ ] `RepoContext` dataclass: `name: str`, `path: Path`, `branch: str`, `base_sha: str`
- [ ] Create `src/orchestra/workspace/repo_tools.py`
  - [ ] `create_repo_tools(repos: dict[str, RepoContext], write_tracker: WriteTracker) -> list[Tool]`
  - [ ] For each repo, generate: `{repo}:read-file`, `{repo}:write-file`, `{repo}:edit-file`, `{repo}:search-code`
  - [ ] Read tools resolve `path` argument relative to `repo.path`
  - [ ] Write tools resolve path relative to `repo.path` AND call `write_tracker.record(absolute_path)`
  - [ ] Path validation: reject paths that escape the repo directory (no `../` traversal)
  - [ ] Return list of `Tool` instances for registration
- [ ] Write unit tests: `tests/unit/test_repo_tools.py` — tool naming, path resolution, write tracking, path traversal rejection, multi-repo generates correct tool set
- [ ] Run tests, verify passing
- [ ] Mark TODO complete and commit the changes to git

### 8. Create WorkspaceManager

- [ ] Create `src/orchestra/workspace/workspace_manager.py`
  - [ ] `WorkspaceManager` class — the central orchestrator for workspace operations
  - [ ] `__init__(config: OrchestraConfig, event_emitter: EventEmitter, commit_gen: CommitMessageGenerator)`
  - [ ] `setup_session(pipeline_name: str, session_id: str) -> dict[str, RepoContext]`
    - [ ] Validate workspace config (repo paths exist, are git repos, HEAD valid)
    - [ ] Create session branches in each repo via `session_branch.create_session_branches()`
    - [ ] Emit `SessionBranchCreated` events
    - [ ] Store session metadata: pipeline_name, session_id, repo contexts, branch infos
    - [ ] Return repo contexts for tool generation
  - [ ] `on_turn_callback(turn: AgentTurn) -> None` — the on_turn callback passed to CodergenHandler
    - [ ] `_current_node_id` tracked via EventObserver (see below)
    - [ ] If `turn.files_written` is empty: set `turn.git_sha = ""`, return
    - [ ] For each repo that has modified files (match `files_written` paths to repo directories):
      - [ ] `git_ops.add(files, cwd=repo_path)` — stage exactly the written files
      - [ ] `git_ops.diff(staged=True, cwd=repo_path)` — get staged diff for commit message
      - [ ] Generate commit message via `commit_gen.generate(diff, intent)`
      - [ ] Build author string: `{node_id} ({turn.model}) <orchestra@local>`
      - [ ] Build trailers dict: `Orchestra-Model`, `Orchestra-Provider`, `Orchestra-Node`, `Orchestra-Pipeline`, `Orchestra-Session`, `Orchestra-Turn`
      - [ ] `git_ops.commit(message, author, trailers, cwd=repo_path)` — commit with metadata
      - [ ] Get SHA via return value of commit
      - [ ] Set `turn.git_sha = sha`, `turn.commit_message = message`
      - [ ] Emit `AgentCommitCreated` event
  - [ ] Implement `EventObserver` protocol (`on_event(event: Event)`)
    - [ ] On `StageStarted`: update `_current_node_id = event.node_id`
    - [ ] On `StageCompleted`/`StageFailed`: clear `_current_node_id`
  - [ ] `has_workspace` property — True if workspace config has repos
  - [ ] Write unit tests: `tests/unit/test_workspace_manager.py` — setup creates branches, on_turn with writes commits, on_turn without writes skips, correct author/trailers, event emission, node tracking via EventObserver
  - [ ] Run tests, verify passing
  - [ ] Mark TODO complete and commit the changes to git

### 9. Wire on_turn callback through handler registry

- [ ] Update `src/orchestra/handlers/registry.py`
  - [ ] Add `on_turn: OnTurnCallback | None = None` parameter to `default_registry()`
  - [ ] Pass `on_turn` to `CodergenHandler(backend=backend, config=config, on_turn=on_turn)` at line 44
  - [ ] Also pass to `InteractiveHandler` if it accepts on_turn (check if needed)
- [ ] Update existing tests that call `default_registry()` to ensure they still pass (parameter is optional, defaults to None)
- [ ] Write unit test: verify that when `on_turn` is provided, `CodergenHandler` receives it and passes it to `backend.run()`
- [ ] Run tests, verify passing
- [ ] Mark TODO complete and commit the changes to git

### 10. Integrate workspace into CLI run command

- [ ] Update `src/orchestra/cli/run.py`
  - [ ] After `build_backend(config)` and before `default_registry()`:
    - [ ] Import and construct `WorkspaceManager` if `config.workspace.repos` is non-empty
    - [ ] Call `workspace_manager.setup_session(pipeline_name, display_id)` to create branches
    - [ ] Build commit message generator via `build_commit_message_generator(config)`
    - [ ] Generate repo-scoped tools via `create_repo_tools()`
    - [ ] Add `WorkspaceManager` as an `EventObserver` to the `dispatcher`
  - [ ] Pass `workspace_manager.on_turn_callback` as `on_turn` to `default_registry()`
  - [ ] If no workspace configured, pass `on_turn=None` (existing behavior)
  - [ ] Handle `WorkspaceError` with clear error messages and `typer.Exit(code=1)`
- [ ] Write integration test: `tests/integration/test_workspace_cli_integration.py` — verify that running the CLI with a workspace-configured orchestra.yaml creates branches and commits
- [ ] Run tests, verify passing
- [ ] Mark TODO complete and commit the changes to git

### 11. Create MCP tool server for CLI agents

- [ ] Create `src/orchestra/workspace/mcp_server.py`
  - [ ] `MCPToolServer` class — runs an MCP stdio server exposing repo-scoped tools
  - [ ] `__init__(repo_contexts: dict[str, RepoContext], write_tracker: WriteTracker)`
  - [ ] Implements MCP protocol over stdin/stdout (JSON-RPC 2.0)
    - [ ] `initialize` — returns server capabilities and tool list
    - [ ] `tools/list` — returns repo-scoped tools (`{repo}:write-file`, `{repo}:edit-file`, `{repo}:read-file`)
    - [ ] `tools/call` — executes the requested tool, routes writes through WriteTracker
  - [ ] `start() -> subprocess.Popen` — launches the MCP server as a subprocess (or runs in-process via threading)
  - [ ] `stop()` — cleanly shuts down the server
  - [ ] `get_server_command() -> list[str]` — returns the command to launch the MCP server (for passing to CLI agent)
  - [ ] Consider using `mcp` Python SDK if available, otherwise implement minimal JSON-RPC handler
- [ ] Write unit tests: `tests/unit/test_mcp_server.py` — server starts, tool list returned, write routes through WriteTracker, read resolves to repo, server stops cleanly
- [ ] Run tests, verify passing
- [ ] Mark TODO complete and commit the changes to git

### 12. Create CLI agent abstraction and Claude Code adapter

- [ ] Create `src/orchestra/backends/cli_agent_config.py`
  - [ ] `CLIAgentConfig` dataclass: `disallowed_tools: list[str] = []`, `allowed_tools: list[str] = []`, `mcp_servers: list[MCPServerConfig] = []`
  - [ ] `MCPServerConfig` dataclass: `name: str`, `command: list[str]`, `env: dict[str, str] = {}`
  - [ ] `CLIAgentAdapter` protocol: `build_args(config: CLIAgentConfig) -> list[str]`, `build_env(config: CLIAgentConfig) -> dict[str, str]`
  - [ ] `ClaudeCodeAdapter` — concrete implementation
    - [ ] Maps `disallowed_tools` to `--disallowedTools` flag
    - [ ] Maps `mcp_servers` to `--mcp-config` or appropriate Claude Code flags
    - [ ] Disables native file-write tools (`Edit`, `Write`, `MultiEdit`) via disallowed_tools
- [ ] Update `src/orchestra/backends/cli_agent.py`
  - [ ] Accept optional `agent_config: CLIAgentConfig | None = None` and `adapter: CLIAgentAdapter | None = None`
  - [ ] When running the subprocess, merge adapter-generated args and env vars
- [ ] Update `src/orchestra/cli/backend_factory.py`
  - [ ] When building CLI backend with workspace config, construct `CLIAgentConfig` with MCP server and tool restrictions, pass to `CLIAgentBackend`
- [ ] Write unit tests: `tests/unit/test_cli_agent_config.py` — ClaudeCodeAdapter produces correct args, disallowed tools mapped, MCP config mapped
- [ ] Write integration test: `tests/integration/test_cli_agent_mcp.py` — verify CLIAgentBackend launches with correct flags (mock subprocess)
- [ ] Run tests, verify passing
- [ ] Mark TODO complete and commit the changes to git

### 13. Write integration tests for per-turn commits and CXDB

- [ ] Create `tests/integration/test_per_turn_commits.py`
  - [ ] Fixture: create a temp git repo with an initial commit, construct workspace config pointing to it
  - [ ] Test: agent turn with writes → exactly those files committed to session branch
  - [ ] Test: only tracked files staged (other dirty files untouched)
  - [ ] Test: turn without writes → no commit
  - [ ] Test: 3 turns with writes → 3 separate commits on session branch
  - [ ] Test: commit author matches `{node_id} ({model}) <orchestra@local>`
  - [ ] Test: commit has all 6 trailers (Orchestra-Model, Orchestra-Provider, Orchestra-Node, Orchestra-Pipeline, Orchestra-Session, Orchestra-Turn)
  - [ ] Test: commit message generated by mock LLM
- [ ] Create `tests/integration/test_cxdb_agent_turns.py`
  - [ ] Test: AgentTurn with writes has SHA populated
  - [ ] Test: AgentTurn without writes has empty SHA
  - [ ] Test: bidirectional correlation — AgentTurn.git_sha matches git commit, git trailer values match CXDB session/turn
- [ ] Create `tests/integration/test_workspace_e2e.py`
  - [ ] Test: full lifecycle — pipeline starts, branches created, agent modifies files across turns, per-turn commits with metadata, AgentTurn CXDB turns with SHAs, pipeline completes, branches remain
  - [ ] Test: multi-repo pipeline — 2 repos, separate branches and commits per repo
- [ ] Run all tests, verify passing
- [ ] Mark TODO complete and commit the changes to git

### 14. Identify and run all specs that need updating

- [ ] Look at all previous TODOs and changes in git to identify modified files
- [ ] Run existing test suite: `pytest tests/` to catch any regressions
  - [ ] Especially: `tests/unit/test_settings.py` (config changes), `tests/unit/test_observer.py` (event/observer changes), `tests/unit/test_type_bundle.py` (CXDB changes), `tests/unit/test_registry.py` (handler registry changes), `tests/unit/test_agent_turn.py` (model changes)
- [ ] Fix any failing tests from modifications to existing modules
- [ ] Identify any missing test coverage for edge cases:
  - [ ] Workspace with no repos configured (should be no-op)
  - [ ] Repo path that doesn't exist (clear error)
  - [ ] Repo path that exists but isn't a git repo (clear error)
  - [ ] Dirty working tree at session start (should still work — create branch from current state)
  - [ ] Commit with empty diff (should not happen due to files_written check, but defensive)
  - [ ] LLM commit message generation timeout/failure (fallback message)
- [ ] Add any missing tests as new test cases
- [ ] Mark TODO complete and commit the changes to git

### 15. Identify unused code and clean up

- [ ] Look at all previous TODOs and changes in git to identify changes
- [ ] Identify any code that is no longer used, and remove it
- [ ] Identify any unnecessary comments, and remove them (comments that explain "what" for a single line of code)
- [ ] If there are any obvious code smells of redundant code, add TODOs below to address them (for example, multiple new classes include private methods that perform similar functions, or are large with many private methods that could be extracted)
- [ ] Verify imports are clean — no unused imports in modified files
- [ ] Ensure consistent code style across new modules (type annotations, docstrings for public APIs only)
- [ ] Mark TODO complete and commit the changes to git

## Automated End-to-End Tests

Tests use temporary git repositories created in a test fixture. No external git repos or network access.

### Session Branch Tests

| Test | Description |
|------|-------------|
| Branch creation | Pipeline start → session branch created in each workspace repo |
| Branch naming | Branch name follows `{prefix}{pipeline}/{session-id}` convention |
| Base SHA recorded | Base commit SHA recorded for each repo at session start |
| Branch persists | After pipeline completion, session branch still exists (not deleted) |
| Multi-repo branches | 2 repos configured → 2 session branches created, one per repo |

### Per-Turn Commit Tests

| Test | Description |
|------|-------------|
| Turn with writes committed | Agent turn writes a file → exactly that file committed to session branch |
| Only tracked files staged | Agent turn writes `a.py` → only `a.py` staged, not other dirty files |
| Turn without writes no commit | Agent turn that only reads files → no commit |
| Multiple turns multiple commits | 3 turns with writes → 3 separate commits on session branch |
| Commit message via LLM | Commit message generated by LLM from diff and agent intent |
| Commit message format | First line under 72 chars, imperative mood, blank line, description |
| Agent metadata in author | Commit author is `{node_id} ({model}) <orchestra@local>` |
| Agent metadata in trailers | Commit has trailers: Orchestra-Model, Orchestra-Provider, Orchestra-Node, Orchestra-Pipeline, Orchestra-Session, Orchestra-Turn |
| CLI writes via MCP | CLI backend writes through Orchestra MCP tools → WriteTracker fires → per-turn commits work |
| CLI native writes disabled | CLI backend cannot use native write tools → all writes go through Orchestra |

### Per-Turn CXDB Recording Tests

| Test | Description |
|------|-------------|
| AgentTurn recorded per turn | Each agent loop turn → `dev.orchestra.AgentTurn` CXDB turn appended |
| AgentTurn with writes has SHA | Turn that writes files → AgentTurn.git_sha populated with commit SHA |
| AgentTurn without writes null SHA | Read-only turn → AgentTurn.git_sha is null |
| AgentTurn contains messages | AgentTurn payload includes LLM messages for that turn |
| AgentTurn contains tool calls | AgentTurn payload includes tool calls made in that turn |
| AgentTurn contains model metadata | AgentTurn payload includes model and provider strings |
| AgentTurn contains agent state | AgentTurn payload includes agent_state_ref for resume |

### MCP Tool Server Tests

| Test | Description |
|------|-------------|
| MCP server starts | MCP stdio server starts and exposes repo-scoped tools |
| MCP write routes through WriteTracker | Write via MCP tool → WriteTracker.record() called |
| MCP read resolves to repo | Read via MCP tool resolves path relative to repo directory |
| CLI agent receives MCP config | CLIAgentBackend passes MCP server to external agent via abstracted interface |
| CLI agent write tools disabled | External agent launched with native file-write tools disabled |

### Repo-Scoped Tools Tests

| Test | Description |
|------|-------------|
| Tool factory generates per-repo tools | Workspace with 2 repos → `backend:read-file`, `frontend:read-file`, etc. |
| Read resolves relative to repo | `backend:read-file` with path `src/main.py` reads from backend repo |
| Write records via WriteTracker | `backend:write-file` calls WriteTracker.record() |
| Write resolves to repo path | `frontend:write-file` writes to frontend repo directory |

### End-to-End Integration Tests

| Test | Description |
|------|-------------|
| Full workspace lifecycle | Pipeline starts → branches created → agent modifies files across multiple turns → per-turn commits with LLM messages and metadata → AgentTurn CXDB turns with SHAs → pipeline completes → branches remain |
| Per-turn commit chain | Agent makes 3 turns with writes → `git log` shows 3 commits with correct authors and trailers → CXDB has 3 AgentTurns with corresponding SHAs |
| Bidirectional correlation | Given CXDB AgentTurn → can checkout git_sha → code matches. Given git commit → trailers identify CXDB session/turn |
| Multi-repo pipeline | Pipeline modifies files in 2 repos → separate branches, per-turn commits per repo |

## Manual Testing Guide

### Prerequisites
- Stage 5 complete and passing
- A git repository to use as a workspace (can be a fresh test repo)
- LLM API key configured (for commit message generation)

### Test 1: Session Branches and Per-Turn Commits

Create `orchestra.yaml` with a workspace pointing to a test git repo:
```yaml
workspace:
  repos:
    project:
      path: ./test-repo
      branch_prefix: orchestra/
```

Create a simple pipeline that modifies a file:
```dot
digraph test_git {
    graph [goal="Add a hello world file"]
    start [shape=Mdiamond]
    exit  [shape=Msquare]
    code  [shape=box, label="Write Code", prompt="Create a file called hello.py with a hello world program"]
    start -> code -> exit
}
```

Run: `orchestra run test-git.dot`

**Verify:**
- `git branch` in the test repo shows a new branch: `orchestra/test-git/{session-id}`
- `git log` on the session branch shows per-turn commits (one per agent turn that wrote files)
- Each commit has a meaningful LLM-generated message (not a generic "auto-commit")
- Each commit author is `code ({model}) <orchestra@local>`
- Each commit has `Orchestra-Model`, `Orchestra-Node`, `Orchestra-Session`, `Orchestra-Turn` trailers
- The main branch is unchanged
- CXDB shows AgentTurn entries with git SHAs matching the commit SHAs

## Success Criteria

- [ ] Workspace config parsed from `orchestra.yaml` with `workspace.repos` section
- [ ] Session branches created at pipeline start, one per workspace repo
- [ ] Branch naming follows `{prefix}{pipeline}/{session-id}` convention
- [ ] Per-turn commits: each agent turn with file writes produces a commit with only the written files staged
- [ ] Commit messages generated by LLM (cheap tier) from staged diff and agent intent
- [ ] Agent metadata in every commit: author identifies agent/model, git trailers provide session/node/turn/model/provider
- [ ] MCP tool server exposes repo-scoped write tools over stdio for CLI agents
- [ ] CLIAgentBackend launches external agents with native write tools disabled and Orchestra MCP server attached
- [ ] CLI agent abstraction supports tool restrictions and MCP server config via a generic interface
- [ ] `dev.orchestra.AgentTurn` CXDB turns recorded for each agent loop turn with messages, tool calls, files written, git SHA, and agent state
- [ ] Bidirectional correlation: CXDB AgentTurn → git SHA, and git commit trailers → CXDB session/node/turn
- [ ] Repo-scoped built-in tools operate on the correct repo directory and record writes via WriteTracker
- [ ] Multi-repo workspaces work with independent branches and commits per repo
- [ ] A human can run a pipeline, inspect per-turn commits with `git log` (seeing agent metadata), and correlate with CXDB turns
- [ ] All automated tests pass using temporary git repositories
