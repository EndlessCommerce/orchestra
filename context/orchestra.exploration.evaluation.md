# Goal Evaluation: Orchestra — Declarative Agent Orchestration on LangGraph

## Goal Summary

Orchestra is a framework for declarative multi-agent pipeline orchestration built on top of LangGraph. It encompasses: prompt composition from YAML layers, a tool registry with multi-repo workspace support, a graph compiler (YAML → LangGraph StateGraph), session/execution management with git integration (worktree-per-agent for parallel writes, workspace snapshots linking checkpoints to git SHAs), observability, and a CLI interface. The validation target is an end-to-end adversarial PR review pipeline.

The exploration document is exceptionally thorough — it defines 15 components, resolves 11 major design decisions, specifies a detailed YAML schema, SQL schema, architecture diagram, and ~35 success criteria. It also identifies 8 risks and 6 deferred open questions.

---

<estimates>
ambiguity:
  rating: 2/5
  rationale:
    - "The exploration document resolves nearly all major design decisions with explicit choices and rationale"
    - "YAML schema examples are concrete and detailed (providers, workspace, agents, graph sections)"
    - "SQL schema for workspace snapshots is specified"
    - "Success criteria are enumerated at a granular level (~35 items)"
    - "Remaining ambiguity is in implementation details: exact Python API signatures, specific error message formats, exact CLI argument parsing, and the boundary between 'compile-time' and 'runtime' validation"
    - "The condition function plugin system has clear intent but no example of the actual decorator implementation or state type"
    - "Interactive mode UX is described conceptually but the stdin/stdout protocol is not specified"

complexity:
  rating: 5/5
  rationale:
    - "15 components spanning 5 architectural layers"
    - "Multi-repo git worktree management with checkpoint-SHA bidirectional linking is inherently complex"
    - "Fan-out/fan-in parallel execution with worktree isolation and merge-at-fan-in is a non-trivial distributed systems problem applied to git"
    - "The graph compiler must handle parallel edges, conditional routing, join semantics, max_loops, and state schema merging"
    - "Interactive mode with multi-turn chat, per-turn checkpointing, and abstract interface for future web UI adds significant surface area"
    - "Provider/model alias resolution with 3-level chain (agent → pipeline default → provider map) has edge cases"
    - "File discovery with 3-level resolution (pipeline-relative → project → global) requires careful path handling"
    - "Testing requires FakeLLM infrastructure, dry-run compilation, snapshot tests, AND optional real LLM integration"

size:
  rating: 5/5
  loc_estimate: 8000-15000
  worker_estimate: "2-4"
  rationale:
    - "15 distinct components, each requiring implementation + tests"
    - "Prompt composer: ~300-500 LOC"
    - "File discovery: ~200-400 LOC"
    - "Tool registry (with repo scoping, shell tools, decorators): ~500-800 LOC"
    - "Agent harness (provider resolution, prompt assembly, LangGraph node wrapping): ~400-600 LOC"
    - "State schema (base + Pydantic extension merging): ~200-300 LOC"
    - "Graph schema (Pydantic models for YAML validation): ~400-600 LOC"
    - "Graph compiler (YAML → StateGraph with fan-out/fan-in/conditions/loops): ~800-1200 LOC"
    - "Condition plugin discovery: ~150-250 LOC"
    - "Session management: ~400-600 LOC"
    - "Git integration (branches, auto-commit, SHA tracking): ~600-1000 LOC"
    - "Worktree manager (create, merge, cleanup): ~400-700 LOC"
    - "Workspace snapshot index (SQLite): ~300-500 LOC"
    - "Observability (structured logging, token tracking): ~300-500 LOC"
    - "Error handling (circuit breaker, tool error surfacing): ~200-300 LOC"
    - "CLI (Typer, 7+ commands): ~500-800 LOC"
    - "Tests (unit + integration + FakeLLM infra): ~3000-5000 LOC"
    - "PR review pipeline YAML + prompts + conditions: ~200-400 LOC"
    - "This is a multi-week effort for a single developer, or 1-2 weeks for a small team"
</estimates>

---

<decision-points>
decision_points:
  - id: implementation-phasing
    question: Should all 15 components be built in a single pass, or should they be phased incrementally with working milestones?
    tradeoffs:
      - Single pass risks a long period with nothing runnable; integration bugs surface late
      - Incremental phasing allows validation at each milestone but requires careful dependency ordering
      - The exploration document says "single plan-and-execute pass" but the size rating suggests this is risky
    recommendation:
      text: >
        Two phases with validation at each step.
        Phase 1 (core framework): Prompt composer + file discovery + tool registry + agent harness + state schema + graph schema + graph compiler + basic session management + basic git integration (single-repo, branch-per-session) + observability + CLI (compile, run, status) + FakeLLM tests.
        Phase 2 (parallel, interactive, validation): Worktree-per-agent + workspace snapshots + fan-in merge + interactive mode + CLI (attach, replay, cleanup) + integration tests + PR review validation pipeline with real LLMs.
      confidence: 5/5
    needs_context: []
    resolved: "Two phases with validation at each step. See additional-context section."

  - id: langgraph-version-pinning
    question: Which LangGraph version to target, and how tightly to couple?
    tradeoffs:
      - LangGraph v1.0 is recent; API may still shift
      - Tight coupling gives access to all features but risks breakage
      - Wrapping critical APIs adds indirection but provides upgrade insulation
    recommendation:
      text: Pin to the latest stable LangGraph release (>=0.2.x as of early 2026). Wrap StateGraph construction and checkpoint access behind thin Orchestra abstractions, but pass through for execution and state management.
      confidence: 3/5
    needs_context:
      - What is the current latest stable LangGraph version?
      - Are there known upcoming breaking changes?

  - id: python-version-and-packaging
    question: What Python version to target and what packaging tool to use?
    tradeoffs:
      - Python 3.11+ gives better performance and typing features
      - Python 3.12+ has even better typing but may limit user compatibility
      - Poetry vs setuptools vs hatch vs uv for packaging
    recommendation:
      text: Target Python 3.11+, use uv for dependency management and packaging (fast, modern, good lockfile support).
      confidence: 4/5
    needs_context:
      - Is there an existing Python environment or packaging preference?

  - id: yaml-parsing-library
    question: Which YAML parser — PyYAML, ruamel.yaml, or strictyaml?
    tradeoffs:
      - PyYAML is ubiquitous but lacks round-trip preservation and has known safety issues with yaml.load
      - ruamel.yaml supports round-trip and YAML 1.2 but is slower and heavier
      - strictyaml prevents implicit typing surprises but is less flexible
      - Since YAML is parsed into Pydantic models, round-trip preservation is not needed
    recommendation:
      text: PyYAML with yaml.safe_load (since we parse into Pydantic models, we don't need round-trip). Add pydantic-settings or a thin loader wrapper for good error messages on parse failures.
      confidence: 4/5
    needs_context: []

  - id: cli-framework
    question: Typer vs Click vs argparse for the CLI?
    tradeoffs:
      - Typer provides type-hint-driven CLI definition and auto-generates help
      - Click is the mature underlying library (Typer wraps it)
      - argparse is stdlib but more verbose
    recommendation:
      text: Typer (as stated in the exploration doc). It aligns with the Pydantic-heavy approach and provides excellent developer experience.
      confidence: 5/5
    needs_context: []

  - id: test-framework
    question: pytest vs unittest for the test suite?
    tradeoffs:
      - pytest is the de facto standard for modern Python with rich plugin ecosystem
      - unittest is stdlib but more verbose
    recommendation:
      text: pytest with pytest-asyncio if any async code is needed. Use fixtures for FakeLLM setup.
      confidence: 5/5
    needs_context: []

  - id: fakellm-implementation
    question: Use LangChain's built-in FakeListLLM/FakeChatModel, or build a custom FakeLLM?
    tradeoffs:
      - LangChain provides FakeListChatModel that returns canned responses in order
      - Custom FakeLLM could pattern-match on input prompts for more realistic testing
      - Custom adds maintenance burden but more flexible assertions
    recommendation:
      text: Start with LangChain's FakeListChatModel for unit tests. Build a thin wrapper that maps prompt patterns → responses for integration tests if needed.
      confidence: 4/5
    needs_context: []

  - id: async-vs-sync
    question: Should the core APIs be async or sync?
    tradeoffs:
      - LangGraph supports both sync and async execution
      - Async enables concurrent tool calls and I/O within agents
      - Sync is simpler to implement and debug
      - CLI interaction (stdin/stdout) is naturally synchronous
      - Real LLM calls benefit from async (concurrent streaming)
    recommendation:
      text: Sync for the initial implementation (CLI-first, simpler debugging). Design interfaces to be async-compatible (return types, no blocking I/O in hot paths) so async can be added later. LangGraph's sync executor handles the graph-level parallelism.
      confidence: 3/5
    needs_context:
      - Is concurrent tool execution within a single agent important for the PR review use case?

  - id: workspace-snapshot-storage
    question: Store workspace snapshots in LangGraph's checkpoint metadata or in a separate Orchestra SQLite table?
    tradeoffs:
      - LangGraph checkpoint metadata keeps everything co-located but couples to LangGraph's storage format
      - Separate SQLite table is more flexible and queryable but requires dual-write synchronization
      - The exploration doc recommends dual-write
    recommendation:
      text: Follow the exploration doc — dual-write with separate SQLite tables for Orchestra metadata. Store a summary in LangGraph checkpoint metadata for convenience, but the SQLite tables are the source of truth for workspace snapshots.
      confidence: 4/5
    needs_context: []

  - id: pr-review-pipeline-scope
    question: How realistic should the PR review validation pipeline be? Local git diff vs actual GitHub PR?
    tradeoffs:
      - Local git diff is self-contained, no external dependencies, testable in CI
      - GitHub PR integration requires credentials, network access, rate limits
      - The exploration doc mentions `github:get-pr-diff` as a tool but this requires GitHub API access
    recommendation:
      text: Build the PR review pipeline with a `local:get-git-diff` tool as the primary input source (works offline, testable). Add `github:get-pr-diff` as an optional tool that can be swapped in. This validates the architecture without requiring GitHub credentials.
      confidence: 4/5
    needs_context:
      - Should the demo pipeline work entirely offline, or is GitHub API access expected?
</decision-points>

---

<success-criteria>
success_criteria:
  - id: prompt-composition
    description: Can load YAML prompt layers (role, persona, personality, task) and compose them into a single system prompt string
    command: pytest tests/test_prompts.py -v
    expected: All prompt composition tests pass — layered assembly produces expected concatenated output
    automated: true

  - id: file-discovery
    description: Prompt and config files resolved via discovery chain — pipeline-relative → project config → global ~/.orchestra/
    command: pytest tests/test_discovery.py -v
    expected: Tests verify 3-level resolution order with correct precedence
    automated: true

  - id: tool-registration
    description: Can register tools via @tool_registry.register() decorator and via YAML shell commands; tools are repo-qualified
    command: pytest tests/test_tools.py -v
    expected: Decorator-registered and YAML shell tools are discoverable; repo:tool naming works
    automated: true

  - id: provider-model-resolution
    description: Provider/model alias resolution works correctly across all cases
    command: pytest tests/test_providers.py -v
    expected: |
      - model: smart + provider: anthropic → claude-opus-4-20250514
      - Literal model strings pass through unchanged
      - Per-agent provider override works
      - Missing alias produces clear error
    automated: true

  - id: schema-validation
    description: Pydantic schema validates the full pipeline YAML structure
    command: pytest tests/test_schema.py -v
    expected: Valid YAML passes; invalid YAML produces actionable error messages (not raw Pydantic internals)
    automated: true

  - id: graph-compilation
    description: Graph compiler produces a runnable LangGraph StateGraph from valid YAML
    command: pytest tests/test_compiler.py -v
    expected: Fan-out, fan-in (join: all), conditional edges, and max_loops all compile to correct LangGraph structure
    automated: true

  - id: compile-dry-run
    description: orchestra compile validates YAML and prints compiled graph structure without executing
    command: orchestra compile tests/fixtures/pr-review.yaml
    expected: Exit code 0; outputs graph structure showing nodes, edges, and resolved references
    automated: true

  - id: condition-discovery
    description: Condition functions auto-discovered from plugin directory via @orchestra.condition() decorator
    command: pytest tests/test_conditions.py -v
    expected: Decorated functions in configurable directory are found and callable by name
    automated: true

  - id: state-schema-extension
    description: Pipeline-defined Pydantic state extensions merge correctly with base schema
    command: pytest tests/test_state.py -v
    expected: Base schema (messages, agent_outputs, metadata) + custom extensions produce valid merged type
    automated: true

  - id: session-lifecycle
    description: Sessions can be started, tracked, and queried
    command: pytest tests/test_session.py -v
    expected: Session creation, status persistence in SQLite, and query by ID all work
    automated: true

  - id: git-integration
    description: Session branches created and auto-commits tracked
    command: pytest tests/test_git.py -v
    expected: |
      - Branch created at session start with correct naming convention
      - Agent changes auto-committed to session branch
      - Workspace snapshots record repo:SHA mappings
    automated: true

  - id: worktree-management
    description: Worktrees created for parallel agents, merged at fan-in, cleaned up
    command: pytest tests/test_worktree.py -v
    expected: |
      - Worktrees created in .orchestra/worktrees/{session}/{agent}
      - Merge at fan-in produces single SHA per repo
      - Cleanup removes worktrees after successful merge
    automated: true

  - id: observability-logging
    description: Token usage, tool invocations, and timing logged per node to SQLite
    command: pytest tests/test_observability.py -v
    expected: Structured records queryable from SQLite after graph execution
    automated: true

  - id: error-handling
    description: Circuit breaker halts pipeline on repeated failures; tool errors surfaced to agent
    command: pytest tests/test_errors.py -v
    expected: Pipeline stops after max_failures_per_session; tool errors appear as agent messages
    automated: true

  - id: cli-commands
    description: All CLI commands (run, compile, attach, replay, status, cleanup) are functional
    command: pytest tests/test_cli.py -v
    expected: Each command accepts correct arguments and produces expected output/behavior
    automated: true

  - id: end-to-end-fakellm
    description: Full pipeline compiles and runs end-to-end with FakeLLM, verifying checkpoints and git integration
    command: pytest tests/integration/test_pipeline_fakellm.py -v
    expected: |
      - Pipeline YAML loads, compiles, and executes
      - Checkpoints created after each node
      - Git commits linked to checkpoints via workspace snapshots
      - Agent outputs propagated between nodes
    automated: true

  - id: end-to-end-real-llm
    description: PR review pipeline runs with real LLM calls (gated behind env var)
    command: ORCHESTRA_REAL_LLM=1 pytest tests/integration/test_pr_review.py -v
    expected: |
      - 2+ reviewer agents fan-out
      - Critic loops 0-2 times
      - Synthesizer produces coherent final review
      - All checkpoints and git state correct
    automated: true
    notes: Requires ORCHESTRA_REAL_LLM=1 and valid API keys; skipped in normal CI

  - id: prompt-snapshot-tests
    description: Composed prompts match expected snapshot output
    command: pytest tests/test_prompt_snapshots.py -v
    expected: Snapshot comparison passes for all configured prompt compositions
    automated: true

  - id: parallel-write-warning
    description: Compiler warns when parallel agents have write access to the same repo
    command: pytest tests/test_compiler.py -k "parallel_write_warning" -v
    expected: Warning emitted for parallel agents sharing write access to a repo
    automated: true

  - id: replay-checkpoint
    description: orchestra replay restores LangGraph state AND git working trees
    command: pytest tests/integration/test_replay.py -v
    expected: After replay, LangGraph state matches checkpoint and all repos are at correct SHAs
    automated: true

evaluation_dependencies:
  - Python 3.11+
  - LangGraph (latest stable)
  - LangChain (for provider abstraction and FakeLLM)
  - Pydantic v2
  - Typer (CLI)
  - pytest + pytest-asyncio
  - PyYAML
  - Jinja2 (task template rendering)
  - SQLite (stdlib, no extra dependency)
  - Git (system)
  - Valid LLM API keys (for real LLM integration tests only)
</success-criteria>

---

<missing-context>
missing_context:
  - category: technical
    items:
      - id: langgraph-version
        question: Which version of LangGraph should be targeted?
        why_it_matters: API differences between versions (especially around checkpointing, state management, and async) affect implementation significantly
        how_to_resolve: Check LangGraph releases; pin to latest stable

      - id: langchain-provider-versions
        question: Which LangChain provider packages are needed (langchain-anthropic, langchain-openai, etc.)?
        why_it_matters: Provider packages have their own version constraints and API differences
        how_to_resolve: Check LangChain ecosystem compatibility matrix for the target LangGraph version

  - category: organizational
    items:
      - id: ci-cd
        question: Is there a CI/CD pipeline to set up, or is this local-only for now?
        why_it_matters: CI setup for FakeLLM tests, linting, and type checking affects initial scaffolding
        how_to_resolve: Check for existing GitHub Actions workflows or CI configuration

      - id: open-source-intent
        question: Is this intended to be open-sourced?
        why_it_matters: Affects documentation requirements, API stability commitments, packaging for PyPI, and license choice
        how_to_resolve: Ask the project owner
</missing-context>

---

<additional-context>

## Resolved Context (from evaluation Q&A)

**Implementation phasing**: Two phases, with validation at each step. Phase 1 covers core framework (prompt composition, tool registry, agent harness, graph schema, graph compiler, basic session management, basic git integration, CLI compile + run). Phase 2 covers parallel execution (worktree-per-agent, workspace snapshots, fan-in merge), interactive mode, full observability, remaining CLI commands (attach, replay, status, cleanup), and the PR review validation pipeline. Each phase validates with tests before moving to the next.

**Timeline**: No hard deadline. Quality over speed. This means full implementation is the goal without cutting corners on architecture or tests.

**Existing codebase**: Greenfield project. No existing code beyond the `context/` directory. Project scaffolding (pyproject.toml, directory structure, test setup) is part of the work.

**Python packaging**: Python 3.11+ with uv for dependency management and packaging.

**Primary use case**: The PR review pipeline is a validation example; the framework itself is the product. This means generic flexibility and clean abstractions are prioritized over PR-review-specific optimizations.

**PR pipeline input source**: Local git diff is the primary input source for the demo pipeline. GitHub API integration is optional and not required for the initial validation.

**Team composition**: Not a factor in planning — do not constrain based on team size.
</additional-context>
