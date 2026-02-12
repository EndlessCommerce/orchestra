# Goal Evaluation: Stage 3 — LLM Integration and Agent Configuration

## Goal Summary

Replace simulation mode with real LLM execution by implementing the CodergenBackend interface with three backends (LangGraph, DirectLLM, CLI Agent), a provider/model resolution system with aliases and a CSS-like model stylesheet, a 4-layer prompt composition engine from YAML files, a file discovery system, and an agent-level tool registry. After this stage, Orchestra runs real AI-powered pipelines.

This is a well-specified plan with comprehensive scope, clear interfaces, explicit test tables, and manual testing guides. The plan builds faithfully on the attractor spec (Section 4.5 CodergenBackend, Section 8 Model Stylesheet) with documented extensions (on_turn callback, semantic aliases, prompt layers).

---

<estimates>
ambiguity:
  rating: 2/5
  rationale:
    - "The plan is highly specific — interfaces, data models, method signatures, and test cases are all spelled out"
    - "The CodergenBackend protocol is explicit: run(node, prompt, context, on_turn=None) -> str | Outcome"
    - "Prompt composition layers are named and ordered (role + persona + personality + task)"
    - "Model resolution precedence is documented as a 5-level chain"
    - "Minor ambiguity: YAML prompt file format not fully specified — RESOLVED: simple `content` key + optional metadata"
    - "Minor ambiguity: exact agent configuration schema in orchestra.yaml is described in prose, not as a formal schema"
    - "Minor ambiguity: how LangGraphBackend serializes agent_state for resume is mentioned but not specified"
    - "Minor ambiguity: what 'tool restrictions' look like in agent config — RESOLVED: allowlist-only"

complexity:
  rating: 4/5
  rationale:
    - "Introduces 6+ new subsystems that must integrate with each other and the existing engine"
    - "LangGraph integration involves understanding an external framework's agent loop, state management, and tool binding"
    - "The model stylesheet parser is a new mini-language (CSS-like grammar) requiring a parser"
    - "Prompt composition with Jinja2 templates and 4-layer concatenation has edge cases (missing layers, variable scoping)"
    - "The tool registry bridges Orchestra's concept of tools with LangChain's ToolInterface"
    - "Three different backend implementations with different capabilities (on_turn support varies)"
    - "However, the existing architecture is well-designed for extension — NodeHandler protocol, event system, CXDB types all have clean seams"
    - "Maintenance cost is moderate: LangChain/LangGraph are fast-moving dependencies"

size:
  rating: 4/5
  loc_estimate: 3000-4500
  worker_estimate: "4-6"
  rationale:
    - "~15 new source files across backends, prompt engine, model resolution, tool registry, config parsing"
    - "~50+ new test cases across 8+ test files (the plan specifies 60+ test cases in tables)"
    - "Modifications to existing files: handler registry, config schema, CXDB type bundle, pyproject.toml"
    - "YAML prompt files and example configurations for testing"
    - "New dependencies to integrate: langchain-core, langchain-anthropic, langchain-openai, langgraph, jinja2"
</estimates>

---

<decision-points>
decision_points:
  - id: prompt-yaml-schema
    question: What is the exact YAML schema for each prompt layer file (role, persona, personality, task)?
    tradeoffs:
      - Simple text-only files (just a string) are easy to implement but limit metadata
      - Structured YAML with fields (content, description, version) enables tooling but adds complexity
      - Free-form with a single required key (e.g., `content:`) is a good middle ground
    recommendation:
      text: "Simple YAML with a single `content` key containing the prompt text, plus optional `description` and `version` fields. Task files use Jinja2 in content."
      confidence: 3/5
    resolution: "RESOLVED — User chose simple `content` key with optional metadata."

  - id: langgraph-tool-binding
    question: How do Orchestra tool definitions map to LangGraph/LangChain tool interfaces?
    tradeoffs:
      - Direct LangChain @tool decorator is simplest but ties Orchestra to LangChain
      - Wrapping Orchestra tools in LangChain StructuredTool allows independence but adds a layer
      - Custom adapter pattern keeps Orchestra tools framework-agnostic
    recommendation:
      text: "Define Orchestra tools independently, then wrap them in LangChain StructuredTool within the LangGraphBackend. This keeps the tool registry framework-agnostic."
      confidence: 4/5

  - id: agent-state-serialization
    question: How should LangGraphBackend serialize agent_state for the AgentTurn?
    tradeoffs:
      - Full LangGraph checkpoint state is large but enables resume
      - Summary state (just key fields) is compact but limits resume capability
      - Agent state resume is deferred to later stages anyway
    recommendation:
      text: "Serialize the LangGraph state as a JSON-compatible dict. Don't attempt resume from agent_state in Stage 3 — just persist it for observability. Resume capability can be added in a later stage."
      confidence: 4/5

  - id: stylesheet-parser-implementation
    question: Should the model stylesheet parser use the existing lark dependency or a simpler regex/hand-rolled parser?
    tradeoffs:
      - Lark is already a dependency and handles grammar-based parsing well
      - The stylesheet grammar is simple enough for regex but that's fragile
      - Hand-rolled recursive descent is robust but more code
    recommendation:
      text: "Use lark — it's already a dependency, the grammar is well-defined in the attractor spec, and it handles error reporting well."
      confidence: 5/5

  - id: cli-agent-context-passing
    question: How does CLIAgentBackend pass context to CLI agents?
    tradeoffs:
      - Stdin-only is simple but some agents may not support it
      - Temp file with env var is flexible but requires cleanup
      - Different agents have different interfaces
    recommendation:
      text: "Configurable approach: prompt via stdin, context via temp JSON file with path in env var. Per-agent adapter configuration for agents with different interfaces."
      confidence: 3/5
    resolution: "RESOLVED — CLIAgentBackend included in Stage 3 as described in the plan."

  - id: tool-restriction-model
    question: Are agent tool restrictions allowlist-only, or also support denylist?
    tradeoffs:
      - Allowlist-only is simpler and more secure (explicit opt-in)
      - Denylist is convenient for "everything except write" scenarios
      - Both modes add complexity but maximum flexibility
    recommendation:
      text: "Allowlist-only for Stage 3. If agent specifies `tools:`, only those tools are available. If no `tools:` key, agent gets the backend's default set."
      confidence: 4/5

  - id: backend-selection-granularity
    question: Should Stage 3 support per-node backend selection?
    tradeoffs:
      - Global-only is simpler but forces all nodes to use the same backend type
      - Per-node is the most flexible and allows mixing analysis + coding nodes
    recommendation:
      text: "Global + per-node in Stage 3. Per-node via a `backend` node attribute (e.g., backend=direct for analysis nodes)."
      confidence: 4/5
    resolution: "RESOLVED — User chose per-node backend selection."

  - id: error-surface-detail
    question: How much detail should LLM API errors expose in the Outcome failure_reason?
    tradeoffs:
      - Full error details help debugging but may expose API keys or sensitive info
      - Sanitized errors are safe but harder to debug
      - Structured error categories (rate_limit, auth, network, model_error) enable smart retry
    recommendation:
      text: "Sanitized error with category: failure_reason='rate_limit: Rate limit exceeded (retry after 30s)'. Strip API keys and request bodies. Include error category for downstream retry logic."
      confidence: 4/5

  - id: langchain-version-pinning
    question: How tightly should LangChain/LangGraph versions be pinned?
    tradeoffs:
      - Loose pinning (>=0.2) allows updates but risks breaking changes
      - Tight pinning (==0.2.3) is stable but requires manual updates
      - Compatible release (~=0.2.3) balances stability and updates
    recommendation:
      text: "Use compatible release specifiers (~=) for langchain packages. LangChain has frequent breaking changes, so pin to minor version."
      confidence: 4/5

  - id: provider-configuration
    question: Which LLM providers are supported and how is OpenRouter configured?
    tradeoffs:
      - OpenRouter uses OpenAI-compatible API format, so langchain-openai works with custom base_url
      - A named 'openrouter' provider is more ergonomic than requiring users to configure base_url
      - Supporting three providers (anthropic, openai, openrouter) covers most use cases
    recommendation:
      text: "Three named providers: anthropic (langchain-anthropic), openai (langchain-openai), openrouter (langchain-openai with pre-configured base_url). Users select by name without needing to know implementation details."
      confidence: 5/5
    resolution: "RESOLVED — User wants Anthropic, OpenAI, and OpenRouter as named providers. OpenRouter uses langchain-openai under the hood with pre-configured base URL."
</decision-points>

---

## Success Criteria Rating: A-

The plan includes comprehensive success criteria (18 items) covering all major subsystems. The criteria are well-specified and mostly automatable. Minor deductions:

- Some criteria are integration-level ("A human can run a pipeline with real LLM calls") which require manual verification
- Missing explicit performance/latency criteria for LLM calls
- Missing criteria for error messages being actionable/helpful

<success-criteria>
success_criteria:
  # Backend Interface Contract
  - id: backend-interface-contract
    description: All three CodergenBackend implementations conform to run(node, prompt, context, on_turn=None) -> str | Outcome
    command: pytest tests/ -k "backend_interface_contract or backend_contract"
    expected: Exit code 0, all contract tests pass
    automated: true

  - id: direct-llm-backend
    description: DirectLLMBackend makes a single mocked LLM call and returns the response
    command: pytest tests/ -k "DirectLLM"
    expected: Exit code 0, all DirectLLM tests pass
    automated: true

  - id: langgraph-backend
    description: LangGraphBackend runs a mocked ReAct agent loop with tools and invokes on_turn
    command: pytest tests/ -k "LangGraph"
    expected: Exit code 0, all LangGraph tests pass including on_turn verification
    automated: true

  - id: cli-agent-backend
    description: CLIAgentBackend spawns a mock subprocess and captures stdout
    command: pytest tests/ -k "CLIAgent"
    expected: Exit code 0, all CLIAgent tests pass
    automated: true

  # Adapter Layer
  - id: codergen-handler-wraps-backend
    description: CodergenHandler implements NodeHandler and wraps CodergenBackend correctly
    command: pytest tests/ -k "CodergenHandler"
    expected: Exit code 0, handler correctly delegates to backend and converts results
    automated: true

  - id: simulation-backend-compatibility
    description: SimulationBackend replaces SimulationCodergenHandler with identical behavior
    command: pytest tests/
    expected: Exit code 0, all 137+ existing tests pass unchanged
    automated: true

  # AgentTurn and WriteTracker
  - id: agent-turn-data
    description: LangGraphBackend emits AgentTurn with correct fields after each turn
    command: pytest tests/ -k "AgentTurn"
    expected: Exit code 0, turn_number, messages, tool_calls, files_written, token_usage verified
    automated: true

  - id: agent-turn-cxdb
    description: AgentTurn data persisted to CXDB as dev.orchestra.AgentTurn turns
    command: pytest tests/ -k "agent_turn_cxdb or AgentTurn_cxdb"
    expected: Exit code 0, CXDB turn type registered and data persisted
    automated: true

  - id: write-tracker
    description: WriteTracker records, deduplicates, and flushes file paths correctly
    command: pytest tests/ -k "WriteTracker or write_tracker"
    expected: Exit code 0, all WriteTracker tests pass including decorator test
    automated: true

  # Provider/Model Resolution
  - id: alias-resolution
    description: Semantic aliases (smart/worker/cheap) resolve to provider-specific model strings
    command: pytest tests/ -k "alias_resolution or provider_resolution"
    expected: Exit code 0, smart+anthropic resolves correctly, literals pass through
    automated: true

  - id: model-resolution-chain
    description: Full precedence chain works (explicit > stylesheet > agent > graph > provider)
    command: pytest tests/ -k "resolution_chain or resolution_precedence"
    expected: Exit code 0, each precedence level correctly overrides lower levels
    automated: true

  # Model Stylesheet
  - id: stylesheet-parsing
    description: CSS-like model stylesheet parses and applies rules by specificity
    command: pytest tests/ -k "stylesheet"
    expected: Exit code 0, universal/class/ID selectors work, specificity order correct
    automated: true

  # Prompt Composition
  - id: prompt-composition
    description: Four-layer prompt composition from YAML files with Jinja2 interpolation
    command: pytest tests/ -k "prompt_composition or prompt_engine"
    expected: Exit code 0, layers concatenated in order, Jinja2 variables interpolated, missing layers skipped
    automated: true

  # File Discovery
  - id: file-discovery
    description: Three-level file resolution (pipeline-relative > project config > global)
    command: pytest tests/ -k "file_discovery"
    expected: Exit code 0, correct precedence, clear error on not found
    automated: true

  # Tool Registry
  - id: tool-registry
    description: Tool registration, YAML shell tools, and agent tool assembly work correctly
    command: pytest tests/ -k "tool_registry"
    expected: Exit code 0, decorator registration, YAML tools, agent restrictions all verified
    automated: true

  # Configuration
  - id: config-validation
    description: orchestra.yaml configuration loads, validates, and reports clear errors
    command: pytest tests/ -k "config"
    expected: Exit code 0, valid configs load, invalid configs produce actionable errors
    automated: true

  # End-to-End Integration
  - id: e2e-agent-pipeline
    description: Full pipeline with agent config, stylesheet, and mocked backend executes correctly
    command: pytest tests/ -k "integration"
    expected: Exit code 0, prompt composed, model resolved, backend called, outcome returned
    automated: true

  # Provider Switching
  - id: provider-switching
    description: Changing default provider in config switches all agents to different provider
    command: pytest tests/ -k "provider_switch or switch_provider"
    expected: Exit code 0, all nodes resolve to new provider's models
    automated: true

  # Error Handling
  - id: llm-error-handling
    description: LLM API errors surface as Outcome(status=FAIL) for existing retry system
    command: pytest tests/ -k "llm_error or backend_error"
    expected: Exit code 0, errors caught and wrapped in Outcome with failure_reason
    automated: true

  # Full Suite
  - id: full-test-suite
    description: All tests pass (existing 137 + new Stage 3 tests)
    command: pytest tests/
    expected: Exit code 0, 0 failures, 190+ tests pass
    automated: true

  # Manual Verification
  - id: manual-real-llm
    description: A human can run a pipeline with real LLM calls and inspect AI-generated output
    expected: |
      Human verifies:
      - orchestra run test-llm.dot executes with real LLM call
      - write/response.md contains actual AI-generated content
      - write/prompt.md contains the expanded prompt
      - Events show real execution timing
    automated: false

evaluation_dependencies:
  - pytest test framework
  - LangChain FakeListChatModel for mocked LLM tests
  - Existing test fixtures (13 DOT files)
  - CXDB mock/test infrastructure (already in test suite)
  - At least one LLM API key for manual testing only
</success-criteria>

---

<missing-context>
missing_context:
  - category: technical
    items:
      - id: langgraph-version-compatibility
        question: Which version of LangGraph is targeted? The API has changed significantly between versions.
        why_it_matters: LangGraph's ReAct agent API, checkpoint system, and tool binding have changed across versions. Wrong version could mean significant rework.
        how_to_resolve: Check latest stable LangGraph version and pin to it. Verify the ReAct agent API matches plan assumptions.

      - id: agent-turn-cxdb-schema
        question: What are the exact field tags and schema for the dev.orchestra.AgentTurn CXDB type?
        why_it_matters: CXDB uses numeric field tags with msgpack. The type schema needs to be defined for persistence and retrieval.
        how_to_resolve: Follow the pattern of existing CXDB types (PipelineLifecycle, NodeExecution, Checkpoint) in type_bundle.py.
</missing-context>

---

<additional-context>
## Resolved Context

### Prompt YAML Schema
User confirmed: Simple YAML with a required `content` key containing the prompt text, plus optional `description` and `version` fields. Task layer files use Jinja2 templates within the `content` value.

### Provider Configuration
User confirmed three named providers for Stage 3:
- **anthropic** — Uses `langchain-anthropic` natively
- **openai** — Uses `langchain-openai` with default OpenAI base URL
- **openrouter** — Uses `langchain-openai` under the hood with OpenRouter's base URL pre-configured. Users select `openrouter` as a provider name without needing to manually configure the base URL.

This means the plan's provider config example should be updated. The `providers` section needs to support all three, and `openrouter` should work out-of-the-box with just an `OPENROUTER_API_KEY` env var.

### CLIAgentBackend
User confirmed: CLIAgentBackend is included in Stage 3. It delegates the entire agent loop to an external CLI program (e.g., Claude Code, Codex). Orchestra passes the prompt, the external agent handles its own tool loop, and Orchestra receives the final output. This is distinct from LangGraphBackend where Orchestra controls the agent loop.

### Per-Node Backend Selection
User confirmed: Stage 3 supports per-node backend selection via a `backend` node attribute. For example, `backend="direct"` on analysis/review nodes and `backend="langgraph"` on coding nodes within the same pipeline. Global default in `orchestra.yaml` with per-node override.

### Tool Restrictions
Allowlist-only model for Stage 3. If an agent specifies `tools: [read-file, search-code]`, only those tools are available. If no `tools:` key is set, the agent gets the backend's default tool set.

### Existing Architecture Reference
The codebase has 137 existing tests across 23 files. Key integration points for Stage 3:
- `NodeHandler` protocol in `src/orchestra/handlers/base.py`
- `SimulationCodergenHandler` in `src/orchestra/handlers/codergen.py`
- `HandlerRegistry` in `src/orchestra/handlers/registry.py` (maps shapes to handlers)
- `Outcome` model in `src/orchestra/models/outcome.py`
- `PipelineRunner._execute_node()` in `src/orchestra/engine/runner.py`
- CXDB type bundle in `src/orchestra/storage/type_bundle.py`
- Config loading in `src/orchestra/config/settings.py`
</additional-context>
