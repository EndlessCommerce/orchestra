# Stage 7: Capstone — Validation Pipeline

## Overview

Build the adversarial PR review pipeline as a capstone that exercises all Orchestra features together. Implement the remaining components: tool handler, CLI enhancements (`replay --checkpoint`, `status --detail`), and the full PR review workflow with parallel reviewers, adversarial critique, conditional routing, human interaction, and workspace management. This stage validates that all prior stages compose correctly under a realistic workload.

## What a Human Can Do After This Stage

1. Run a full adversarial PR review: parallel security + architecture reviewers, adversarial critic with conditional looping, interactive synthesizer, workspace-aware
2. Replay from any checkpoint in any past session
3. Use the tool handler for non-LLM pipeline nodes (shell commands, API calls)
4. Inspect session details with `orchestra status --detail` (per-node token usage, timing, tool invocations)
5. Run Orchestra's own validation suite as a confidence check

## Prerequisites

- All prior stages complete (Stages 1-6)

## Investigation

- [x] Review the existing PR review pipeline (`examples/pr-review/pr-review.dot`) — it has parallel fan-out/fan-in, synthesis, human gate, and rework loop but lacks adversarial critic, tool handler node, and conditional looping
- [x] Review handler registry (`handlers/registry.py`) — no parallelogram or house shape registered
- [x] Review CLI commands (`cli/main.py`) — replay exists but only has `--turn` flag
- [x] Review status command (`cli/status.py`) — basic table only, no `--detail` flag
- [x] Review validation rules (`validation/rules.py`) — no rule for parallelogram nodes needing `tool_command`
- [x] Review event types (`events/types.py`) — 25 event types exist, no `ToolExecuted` event type
- [x] Review CXDB type bundle (`storage/type_bundle.py`) — all core types registered, no tool execution type
- [x] Review interviewer base (`interviewer/base.py`) — Protocol with `ask`, `ask_multiple`, `inform` methods
- [x] Review Outcome model (`models/outcome.py`) — no `token_usage` field (confirmed); observability must come from AgentTurn CXDB turns
- [x] Review replay_cmd.py — full replay with CXDB fork + git restore already works for `--turn`; need to add `--checkpoint` filter

## Resolved Decisions

- **Manager loop handler**: DEFERRED — not needed for PR pipeline (uses parallel + conditional routing instead)
- **CXDB UI renderers**: DESCOPED — replaced with `orchestra status --detail` CLI command
- **Attach command**: DEFERRED — removed from Stage 7 scope to focus capstone on validating composition of existing features
- **Replay --checkpoint**: Add `--checkpoint` flag alongside existing `--turn` (filters for Checkpoint turns only)
- **Tool handler security**: No sandbox; `shell=True` for flexibility; `tool_command` values should be static (authored by pipeline developer, not derived from LLM-generated context); scope working directory to workspace repo if configured
- **Observability aggregation**: Read-time aggregation from AgentTurn turns grouped by node_id
- **PR diff delivery**: Tool handler node as first pipeline node runs `git diff` → context `tool.output`
- **PR review prompts**: Keep existing prompt files (security, quality, correctness specialists); add new architecture/critic prompts alongside; DOT file controls which agents are active
- **Tool output storage**: No truncation — full stdout stored in both ToolExecuted event and `tool.output` context key

## Plan

- [x] Implement Tool Handler (`parallelogram` shape)
    - [x] Create `src/orchestra/handlers/tool_handler.py` implementing `NodeHandler` protocol
        - Read `tool_command` from `node.attributes`
        - Execute via `subprocess.run()` with `shell=True`, `capture_output=True`
        - NOTE: `shell=True` used for flexibility (pipes, redirects, env vars). Document that `tool_command` values should be static pipeline-developer-authored strings, not derived from LLM-generated context values
        - Support `timeout` attribute (parse duration string from node attributes, default 60s)
        - Set `tool.output` context key with stdout
        - Return `Outcome(SUCCESS)` with `context_updates={"tool.output": stdout}`
        - Return `Outcome(FAIL)` with `failure_reason` on non-zero exit, missing command, or timeout
        - Scope `cwd` to workspace repo path if workspace_manager is configured, otherwise pipeline directory
    - [x] Create `ToolExecuted` event type in `src/orchestra/events/types.py`
        - Fields: `node_id`, `command`, `exit_code`, `stdout`, `duration_ms`
        - Add to `EVENT_TYPE_MAP`
    - [x] Add `dev.orchestra.ToolExecution` type to CXDB type bundle in `src/orchestra/storage/type_bundle.py`
    - [x] Map `ToolExecuted` event to CXDB turn in `src/orchestra/events/observer.py` (CxdbObserver)
    - [x] Register `parallelogram` → `ToolHandler` in `src/orchestra/handlers/registry.py`
        - `ToolHandler` needs `workspace_manager` param (optional) for cwd resolution
    - [x] Add validation rule: `tool_command_on_tool_nodes` — parallelogram nodes should have `tool_command` attribute (WARNING severity)
    - [x] Write tests in `tests/test_tool_handler.py`:
        - Execute shell command (`echo hello`) → SUCCESS, `tool.output` = "hello"
        - Command failure (`false`) → FAIL
        - Command timeout → FAIL with timeout message
        - Output in context → `tool.output` key set correctly
        - No command specified → FAIL with "No tool_command specified"
        - Workspace cwd scoping → command runs in repo directory
    - [x] Mark TODO complete and commit the changes to git

- [ ] Implement CLI: `orchestra replay --checkpoint`
    - [ ] Update `src/orchestra/cli/replay_cmd.py`
        - Add `--checkpoint` option (mutually exclusive with `--turn`)
        - When `--checkpoint` given, filter turns for `dev.orchestra.Checkpoint` type
        - Find the matching checkpoint turn by ID
        - Extract `next_node_id`, `workspace_snapshot`, `context_snapshot` from checkpoint data
        - Restore workspace repos from `workspace_snapshot` SHAs (not single `git_sha`)
        - Otherwise reuse existing fork-and-resume logic
    - [ ] Write tests in `tests/test_replay_checkpoint.py`:
        - Replay from specific checkpoint → restores correct node and context
        - Replay with workspace snapshot → git repos restored to checkpoint SHAs
        - Invalid checkpoint ID → error message
        - `--checkpoint` and `--turn` both provided → error
    - [ ] Mark TODO complete and commit the changes to git

- [ ] Implement CLI: `orchestra status --detail`
    - [ ] Update `src/orchestra/cli/status.py`
        - Add `--detail` flag and optional `session_id` argument
        - When `--detail` given with session_id:
            - Read all turns for the session from CXDB
            - Group `dev.orchestra.AgentTurn` turns by `node_id`
            - Aggregate token usage (sum `input_tokens` + `output_tokens` per node)
            - Extract timing from `dev.orchestra.NodeExecution` turns (`duration_ms`)
            - Count tool invocations from `tool_calls` field in AgentTurn turns
            - Display structured table: Node | Status | Tokens (In/Out) | Tools | Duration
        - When `--detail` given without session_id: show detail for most recent session
    - [ ] Write tests in `tests/test_status_detail.py`:
        - `--detail` shows per-node token usage aggregated from AgentTurn turns
        - `--detail` shows timing from NodeExecution turns
        - `--detail` shows tool invocation counts from AgentTurn turns
        - `--detail` with no session → shows most recent
    - [ ] Mark TODO complete and commit the changes to git

- [ ] Update Adversarial PR Review Pipeline
    - [ ] Update `examples/pr-review/pr-review.dot` to match Stage 7 spec:
        - Add `get_diff` tool handler node (shape=parallelogram) as first node after start: `tool_command="git diff HEAD~1"`
        - Change reviewers from 3 to 2: security reviewer + architecture reviewer (per Stage 7 spec)
        - Add adversarial `critic` node after fan-in with `goal_gate=true`
        - Add `gate` conditional node (shape=diamond) after critic for routing
        - Add conditional edge: gate → fan_out when `context.critic_verdict="insufficient"`
        - Add conditional edge: gate → synthesizer when `context.critic_verdict="sufficient"`
        - Make synthesizer interactive: `agent.mode="interactive"`
        - Keep human approval gate and rework loop
    - [ ] Update `examples/pr-review/orchestra.yaml`
        - Change from `direct` to `langgraph` backend (supports interactive mode)
        - Add architecture-reviewer agent configuration (keep existing quality/correctness configs for reuse)
        - Add critic agent configuration (adversarial persona)
        - Update synthesizer to interactive mode
    - [ ] Create agent YAML configs for new agents (keep existing prompt files alongside):
        - `prompts/personas/architecture-specialist.yaml` — architecture, design patterns, coupling focus
        - `prompts/personas/adversarial-critic.yaml` — adversarial, finds gaps, demands rigor
        - `prompts/roles/review-critic.yaml` — evaluates review quality, outputs verdict
        - `prompts/tasks/critique-reviews.yaml` — evaluate reviews, set `critic_verdict` context key
    - [ ] Update existing task prompts to reference `{{ tool.output }}` for the diff content
    - [ ] Create test fixture `tests/fixtures/pr-review-adversarial.dot` (simplified version for testing)
    - [ ] Mark TODO complete and commit the changes to git

- [ ] Write PR Review Pipeline Tests (Mocked LLM)
    - [ ] Create `tests/test_pr_review_pipeline.py` with mocked LLM (SimulationBackend or mock):
        - Full pipeline execution: start → get_diff → fan_out → [security, architecture] → fan_in → critic → gate → synthesizer → exit
        - Parallel reviewers execute concurrently, produce distinct outputs
        - Critic loop: critic returns insufficient → loops back to reviewers → critic re-evaluates
        - Critic accepts: critic returns sufficient → proceeds to synthesizer
        - Goal gate on critic: critic has `goal_gate=true` → must succeed before exit
        - Interactive synthesizer: QueueInterviewer provides responses → produces final review
        - Model stylesheet applied: different models assigned to different roles
        - Workspace integration: session branches created, agents commit
        - Checkpoint at every node: every node transition produces a valid checkpoint
        - Resume mid-pipeline: stop after fan-in → resume → critic and synthesizer execute correctly
    - [ ] Mark TODO complete and commit the changes to git

- [ ] Write Cross-Feature Integration Tests
    - [ ] Create `tests/test_cross_feature.py` with 5 scenarios:
        - Conditional + retry + goal gate: pipeline with branching, retries on failure, goal gate enforcement
        - Parallel + human gate: parallel branches → fan-in → human gate → routing
        - Parallel + worktrees + resume: parallel agents with worktrees → pause → resume → worktrees restored → fan-in merges
        - Agent config + stylesheet + tools: agent with layered prompts, stylesheet model override, and tools
        - Full 10+ node pipeline: large pipeline with mixed node types executes without errors
    - [ ] Mark TODO complete and commit the changes to git

- [ ] Write Custom Handler Registration Test
    - [ ] Add test to `tests/test_tool_handler.py` or separate file:
        - Register custom handler via `registry.register("custom_shape", CustomHandler())`
        - Build pipeline with custom_shape node
        - Execute → custom handler is dispatched
    - [ ] Mark TODO complete and commit the changes to git

- [ ] Write Real LLM Integration Test (Gated)
    - [ ] Create `tests/test_pr_review_real.py` gated behind `ORCHESTRA_REAL_LLM=1`:
        - Full adversarial PR review pipeline with real LLM calls on a sample diff
        - Use cheap models (Haiku-tier) to minimize cost
        - Verify reviewers produce domain-specific reviews
        - Verify critic evaluates coherently
        - Verify synthesizer produces final review
        - Verify all artifacts present in run directory
        - Verify checkpoints are loadable and contain correct state
    - [ ] Mark TODO complete and commit the changes to git

- [ ] Review and cleanup
    - [ ] Look at all previous TODOs and changes in git to identify changes
    - [ ] Identify any code that is no longer used, and remove it
    - [ ] Identify any unnecessary comments, and remove them
    - [ ] If there are any obvious code smells or redundant code, add TODOs below to address them
    - [ ] Mark TODO complete and commit the changes to git

- [ ] Identify all specs that need to be run and updated
    - [ ] Look at all previous TODOs and changes in git to identify changes
    - [ ] Run the full test suite (`pytest tests/ -v --tb=short`)
    - [ ] Identify any specs that failed and fix them
    - [ ] Verify total test count >= 750 (currently 703 + new tests)
    - [ ] Mark TODO complete and commit the changes to git

## Success Criteria

- [ ] Tool handler executes shell commands and captures output to `tool.output` context key
- [ ] `orchestra replay --checkpoint` restores specific checkpoints including git state
- [ ] `orchestra status --detail` shows per-node token usage, tool invocations, and timing
- [ ] Adversarial PR review pipeline runs end-to-end exercising all features:
  - Parallel fan-out/fan-in (security + architecture reviewers)
  - Adversarial critic with conditional loop
  - Goal gate enforcement on critic
  - Interactive synthesizer with human collaboration
  - Model stylesheet assigning different models per role
  - Workspace management with session branches and commits
- [ ] Agent configurations compose correctly: layered prompts + model resolution + tool sets
- [ ] Custom handler registration works per the extension point
- [ ] All cross-feature integration tests pass (5 scenarios)
- [ ] Real LLM integration test produces a coherent PR review (gated behind env var)
- [ ] All automated tests pass (>= 750 tests, 0 failures)
