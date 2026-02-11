# Stage 7: Capstone — Validation Pipeline

## Overview

Build the adversarial PR review pipeline as a capstone that exercises all Orchestra features together. Implement the remaining components: manager loop handler, tool handler, CLI commands (`attach`, `replay`), and the full PR review workflow with parallel reviewers, adversarial critique, conditional routing, human interaction, and workspace management. This stage validates that all prior stages compose correctly under a realistic workload.

## What a Human Can Do After This Stage

1. Run a full adversarial PR review: parallel security + architecture reviewers, adversarial critic with conditional looping, interactive synthesizer, workspace-aware
2. Attach to a running session's event stream or interactive agent
3. Replay from any checkpoint in any past session
4. Use the tool handler for non-LLM pipeline nodes (shell commands, API calls)
5. Use the manager loop handler for supervising child pipelines
6. Run Orchestra's own validation suite as a confidence check

## Prerequisites

- All prior stages complete (Stages 1-6)

## Scope

### Included

- **Tool Handler.** Execute shell commands or API calls as pipeline nodes (parallelogram shape). `tool_command` attribute. Stdout captured to `tool.output` context key. Error handling with timeout support. Per attractor Section 4.10.
- **Manager Loop Handler.** Supervisor loop for child pipelines (house shape). Observe/steer/wait cycles. Auto-start child pipeline. Configurable poll interval, max cycles, stop conditions. Per attractor Section 4.11.
- **CLI: `orchestra attach <session_id>`.** Connect to a running session's event stream. If the active node is interactive, forward stdin/stdout for human participation.
- **CLI: `orchestra replay <session_id> --checkpoint <id>`.** Restore specific checkpoint including git state and re-execute from that point. (Session-level resume was in Stage 2; this adds checkpoint-specific replay with git.)
- **Adversarial PR Review Pipeline.** The full pipeline from the exploration document:
  - Parallel fan-out: security reviewer + architecture reviewer
  - Fan-in: collect reviews
  - Adversarial critic with goal gate and conditional loop
  - Conditional routing: if critique insufficient, re-run reviews
  - Interactive synthesizer: human collaborates on the final review
  - Workspace integration: operates on git repos
- **PR Review Agent Configurations.** Full agent YAML files for security-reviewer, architecture-reviewer, critic (adversarial), and synthesizer (interactive). Role, persona, personality, task layers for each.
- **PR Review Tools.** `local:get-git-diff` built-in tool (primary input). Optional `github:get-pr-diff` tool (swappable, requires credentials).
- **Custom Handler Registration.** Validate that the handler registry supports custom handlers per attractor Section 4.12. Document the extension point.
- **Observability via CXDB.** Per-node token usage (prompt/completion), tool invocation counts, and wall-clock timing stored as fields in `dev.orchestra.NodeExecution` turn payloads. Queryable via CXDB API and visible in CXDB UI. `orchestra status --detail` reads from CXDB turns.
- **CXDB UI Renderers.** Custom renderers for Orchestra turn types: pipeline lifecycle timeline, node execution detail views with prompt/response, parallel execution branch visualization, human interaction Q&A display.
- **Real LLM Integration Test.** Gated behind `ORCHESTRA_REAL_LLM=1` environment variable. Uses cheap models (Haiku-tier). Validates the full flow with real AI responses.

### Excluded

- HTTP server mode (deferred to post-CLI, per attractor Section 9.5)
- Token budgets / cost limits (deferred)
- Web UI (deferred)
- Team/shared use features (deferred)

## Automated End-to-End Tests

All tests use mocked LLMs unless gated behind `ORCHESTRA_REAL_LLM=1`.

### Tool Handler Tests

| Test | Description |
|------|-------------|
| Execute shell command | `tool_command="echo hello"` → outcome SUCCESS, `tool.output` = "hello" |
| Command failure | `tool_command="false"` → outcome FAIL |
| Command timeout | Long-running command exceeds `timeout` → FAIL with timeout message |
| Output in context | `tool.output` context key set with command stdout |
| No command specified | Missing `tool_command` → FAIL with "No tool_command specified" |

### Manager Loop Handler Tests

| Test | Description |
|------|-------------|
| Auto-start child | `stack.child_autostart=true` → child pipeline started |
| Observe cycle | Child telemetry ingested into parent context |
| Stop on child completion | Child status=completed → manager returns SUCCESS |
| Stop on child failure | Child status=failed → manager returns FAIL |
| Max cycles exceeded | No stop condition met within max_cycles → FAIL |
| Custom stop condition | `manager.stop_condition` evaluates to true → manager returns SUCCESS |

### CLI Attach/Replay Tests

| Test | Description |
|------|-------------|
| Attach to running session | Connects and receives events from the active session |
| Attach to interactive node | Stdin/stdout forwarded for human interaction |
| Replay from checkpoint | Restores specific checkpoint, re-executes from that point |
| Replay with git restore | Git repos restored to the checkpoint's workspace snapshot SHAs |

### PR Review Pipeline Tests (Mocked LLM)

| Test | Description |
|------|-------------|
| Full pipeline execution | start → fan_out → [security, architecture] → fan_in → critic → gate → synthesizer → exit |
| Parallel reviewers | Both reviewers execute concurrently, produce distinct outputs |
| Critic loop | Critic returns insufficient → pipeline loops back to reviewers → critic re-evaluates |
| Critic accepts | Critic returns sufficient → pipeline proceeds to synthesizer |
| Goal gate on reviewers | Both reviewers have `goal_gate=true` → must succeed before exit |
| Interactive synthesizer | Synthesizer in interactive mode → QueueInterviewer provides responses → produces final review |
| Model stylesheet applied | Different models assigned to different roles per stylesheet |
| Workspace integration | Pipeline creates session branches, agents commit to them |
| Checkpoint at every node | Every node transition produces a valid checkpoint with workspace snapshot |
| Resume mid-pipeline | Stop after fan-in → resume → critic and synthesizer execute correctly |

### Observability Tests (CXDB)

| Test | Description |
|------|-------------|
| Token usage in turns | Per-node token counts (prompt/completion) present in NodeExecution turn payloads |
| Tool invocations in turns | Tool calls counted and timed per node, stored in turn payloads |
| Timing in turns | Wall-clock duration per node and total pipeline in turn payloads |
| `orchestra status --detail` | Detailed view reads metrics from CXDB turns |
| CXDB UI visualization | Pipeline execution visible in CXDB UI with custom renderers |

### Cross-Feature Integration Tests

These tests verify that features from all stages compose correctly:

| Test | Description |
|------|-------------|
| Conditional + retry + goal gate | Pipeline with branching, retries on failure, and goal gate enforcement — all interact correctly |
| Parallel + human gate | Parallel branches → fan-in → human gate → routing — human interaction after parallel execution |
| Parallel + worktrees + resume | Parallel agents with worktrees → pause → resume → worktrees restored → fan-in merges correctly |
| Agent config + stylesheet + tools | Agent with layered prompts, stylesheet model override, and custom tools — all resolved correctly |
| Full 10+ node pipeline | Large pipeline with mixed node types executes without errors |

### Real LLM Integration Test (Gated)

**Only runs when `ORCHESTRA_REAL_LLM=1` is set.** Uses cheap models (Haiku-tier).

| Test | Description |
|------|-------------|
| PR review end-to-end | Full adversarial PR review pipeline with real LLM calls on a sample diff |
| Reviewers produce distinct reviews | Security and architecture reviewers focus on their domains |
| Critic evaluates coherently | Critic identifies gaps or confirms sufficiency |
| Synthesizer produces final review | Interactive synthesizer produces a coherent combined review |
| All artifacts present | Run directory contains all prompts, responses, and status files |
| Checkpoints valid | All checkpoints loadable and contain correct state |

## Manual Testing Guide

### Prerequisites
- All prior stages complete and passing
- LLM API key configured
- A git repository with a recent PR or diff to review

### Test 1: Full PR Review Pipeline

Set up a workspace with a repo that has a recent diff (e.g., create a branch with some changes).

Configure `orchestra.yaml` with the workspace and agents.

Run: `orchestra run pipelines/pr-review.dot`

**Verify:**
- Pipeline starts, creates session branches
- Security reviewer and architecture reviewer execute in parallel
- Events show parallel branch execution
- Fan-in collects both reviews
- Adversarial critic evaluates the reviews
- If critic is unsatisfied, loop back to reviewers (observe the loop)
- If critic is satisfied, proceed to synthesizer
- Synthesizer enters interactive mode — prompts appear for your input
- Type feedback and `/done` to complete
- Final review is in the run directory
- Session branch has any code changes
- `orchestra status` shows the completed session with token usage

### Test 2: Attach to Running Session

Start a long-running pipeline in one terminal:
```
orchestra run pipelines/pr-review.dot
```

In another terminal:
```
orchestra attach <session_id>
```

**Verify:**
- Event stream appears in real-time in the second terminal
- When the pipeline reaches an interactive node, the attached terminal can participate
- Detaching (Ctrl-C) does not affect the running pipeline

### Test 3: Replay from Checkpoint

After running a pipeline, list checkpoints:
```
orchestra status <session_id> --checkpoints
```

Pick a checkpoint from mid-pipeline:
```
orchestra replay <session_id> --checkpoint <checkpoint_id>
```

**Verify:**
- Pipeline re-executes from the specified checkpoint
- Git repos are at the correct state for that checkpoint
- Subsequent nodes execute fresh (not from cache)
- A new run directory is created for the replay

### Test 4: Tool Handler

Create a pipeline with a tool handler node:
```dot
run_tests [shape=parallelogram, label="Run Tests", tool_command="cd test-repo && python -m pytest"]
```

**Verify:**
- Tool executes the shell command
- Stdout captured and available in context as `tool.output`
- Next node can access the test results

### Test 5: End-to-End Validation

Run the full automated test suite:
```
pytest tests/ -v
```

Run the real LLM integration tests (requires API key):
```
ORCHESTRA_REAL_LLM=1 pytest tests/integration/test_pr_review.py -v
```

**Verify:**
- All automated tests pass
- Real LLM integration test produces a coherent PR review
- No errors or warnings in the output

## Success Criteria

- [ ] Tool handler executes shell commands and captures output
- [ ] Manager loop handler supervises child pipelines with observe/steer/wait cycles
- [ ] `orchestra attach` connects to running sessions and forwards interactive I/O
- [ ] `orchestra replay` restores specific checkpoints including git state
- [ ] Adversarial PR review pipeline runs end-to-end exercising all features:
  - Parallel fan-out/fan-in
  - Conditional routing with critic loop
  - Goal gate enforcement on reviewers
  - Interactive synthesizer with human collaboration
  - Model stylesheet assigning different models per role
  - Workspace management with session branches and commits
- [ ] Agent configurations compose correctly: layered prompts + model resolution + tool sets
- [ ] Observability tracks per-node token usage, tool invocations, and timing in CXDB turn payloads
- [ ] CXDB UI renderers display pipeline execution traces with structured views per turn type
- [ ] Custom handler registration works per the extension point
- [ ] All cross-feature integration tests pass (features from all stages compose correctly)
- [ ] Real LLM integration test produces a coherent PR review (gated behind env var)
- [ ] A human can run the full PR review workflow, participate interactively, and inspect all results
- [ ] All automated tests pass
