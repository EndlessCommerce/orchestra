# Goal Evaluation: Stage 4 — Human-in-the-Loop

## Goal Summary

Add human interaction to pipelines via an `Interviewer` abstraction. Implement `wait.human` nodes (hexagon shape) that derive choices from outgoing edge labels and present them to a human, and chat-style interactive mode for codergen nodes (`agent.mode="interactive"`). Provide multiple interviewer implementations: Console (CLI), AutoApprove (CI), Queue (testing), Callback (integration), and Recording (audit).

---

<estimates>
ambiguity:
  rating: 2/5
  rationale:
    - "The plan specifies exact interfaces (Interviewer.ask, Interviewer.inform), question types (YES_NO, MULTIPLE_CHOICE, FREEFORM, CONFIRMATION), and answer values (YES, NO, SKIPPED, TIMEOUT)"
    - "Test cases are fully enumerated with expected behaviors"
    - "The hexagon shape for wait.human nodes and edge-label-to-choice derivation are explicit"
    - "Minor ambiguity: how the Interviewer is injected into handlers (constructor, registry, config?), and how interactive mode interacts with the existing CodergenHandler/backend architecture"
    - "Accelerator key parsing patterns are already partially implemented in edge_selection.py (_ACCELERATOR_PREFIX regex)"

complexity:
  rating: 3/5
  rationale:
    - "The Interviewer interface and its implementations are straightforward (strategy pattern)"
    - "WaitHumanHandler is well-scoped: derive choices from edges, present via interviewer, route based on selection — maps cleanly to existing Outcome.preferred_label and edge selection"
    - "Interactive mode is the most complex piece: multi-turn chat loop, checkpoint boundaries per turn, resume mid-conversation, integration with existing CodergenBackend protocol"
    - "Timeout handling adds some complexity (threading or signal-based stdin timeout)"
    - "The existing architecture (handler registry, edge selection, checkpoint/resume) is well-positioned for this — most of the plumbing exists"
    - "ConsoleInterviewer has inherent UX complexity (stdin reading, formatted output, accelerator keys)"

size:
  rating: 3/5
  loc_estimate: 800-1200
  worker_estimate: "1-2"
</estimates>

---

<decision-points>
decision_points:
  - id: interviewer-injection
    question: How should the Interviewer instance be provided to handlers that need it?
    tradeoffs:
      - "Constructor injection on WaitHumanHandler: clean, explicit, but requires threading it through default_registry()"
      - "Store on OrchestraConfig and pass config to handlers: consistent with how CodergenHandler gets agent config"
      - "Global/module-level setter: simple but testability suffers"
    recommendation:
      text: "Constructor injection via default_registry(), matching how CodergenHandler receives its backend. The interviewer becomes a parameter of default_registry() alongside backend and config."
      confidence: 4/5
    needs_context: []
    decision: "RESOLVED — Constructor injection via default_registry(). User confirmed."

  - id: interactive-mode-architecture
    question: Should interactive mode extend CodergenHandler, create a new handler, or be a new backend wrapper?
    tradeoffs:
      - "Extend CodergenHandler with an if-branch: keeps handler count low but adds complexity to an already clean class"
      - "New InteractiveCodergenHandler: clean separation but duplicates prompt composition logic"
      - "Backend wrapper (InteractiveBackend wrapping another backend): fits the existing layering, the handler stays unchanged and the backend manages the chat loop"
    recommendation:
      text: "Extend CodergenHandler with a mode check. The handler already checks node attributes for agent config — checking agent.mode='interactive' is a natural extension. The chat loop logic lives in a helper method or separate module, not in the backend."
      confidence: 3/5
    needs_context: []
    decision: "RESOLVED — Interactive mode included in Stage 4, must work with ALL backends. Extend CodergenHandler with mode check."

  - id: question-answer-models
    question: Should Question/Answer types use pydantic BaseModel or Python dataclasses?
    tradeoffs:
      - "Pydantic: consistent with all other models (Node, Edge, Outcome, Context), validation built-in, serializable for CXDB storage"
      - "Dataclass: lighter weight, no validation overhead, but inconsistent with codebase"
    recommendation:
      text: "Pydantic BaseModel, consistent with the rest of the codebase (Node, Edge, Outcome are all pydantic)"
      confidence: 5/5
    needs_context: []

  - id: timeout-mechanism
    question: How should stdin timeout be implemented for ConsoleInterviewer?
    tradeoffs:
      - "threading.Timer + input(): portable, but requires thread management and interrupt handling"
      - "select.select on stdin: Unix-only, not portable to Windows"
      - "signal.alarm: Unix-only, not portable, but simple"
      - "inputimeout library: external dependency"
    recommendation:
      text: "threading.Timer approach — create a daemon thread that reads stdin, with a timeout on the main thread via Event.wait(). Portable and testable. ConsoleInterviewer can have a _read_input_with_timeout() method."
      confidence: 3/5
    needs_context:
      - "Is Windows support required?"

  - id: recording-storage
    question: Where should RecordingInterviewer store its Q&A pairs — in-memory list, in context, or emitted as events?
    tradeoffs:
      - "In-memory list on the recorder: simple, accessible after run, but lost if process crashes"
      - "In context: survives checkpoints and resume, but pollutes the context namespace"
      - "Emitted as events to CXDB: durable, queryable, fits the event-sourcing architecture"
    recommendation:
      text: "Both in-memory list (for programmatic access in tests) AND emitted as events (for durability). The recorder emits a 'HumanInteraction' event for each Q&A pair via the event emitter, and also stores locally for immediate access."
      confidence: 4/5
    needs_context:
      - "Does RecordingInterviewer need access to the event emitter, or should events be handled elsewhere?"

  - id: accelerator-key-reuse
    question: Should the WaitHumanHandler reuse the existing _ACCELERATOR_PREFIX regex from edge_selection.py, or implement its own parsing?
    tradeoffs:
      - "Reuse: DRY, but edge_selection uses it for normalization (stripping prefixes), while WaitHumanHandler needs extraction (getting the key AND the label)"
      - "New parser: can handle all 4 patterns from the plan ([K] Label, K) Label, K - Label, first char fallback) with a richer return type"
    recommendation:
      text: "Extract a shared accelerator module (e.g., models/accelerator.py or handlers/accelerator.py) with parse_accelerator(label) -> (key, clean_label). Both edge_selection and WaitHumanHandler use it."
      confidence: 4/5
    needs_context: []

  - id: checkpoint-interactive-turns
    question: How should interactive mode checkpoint after each human turn — trigger a full checkpoint save, or use a lighter mechanism?
    tradeoffs:
      - "Full checkpoint (same as node completion): consistent, enables resume mid-conversation, but each turn creates a CXDB entry"
      - "Lightweight turn log (events only, no full state snapshot): less overhead but resume would need to replay from last full checkpoint"
    recommendation:
      text: "Full checkpoint after each human turn. The plan explicitly requires 'resume mid-conversation' which needs full state snapshots. The overhead is acceptable since human turns are infrequent."
      confidence: 4/5
    needs_context:
      - "What state needs to be captured for conversation resume — just the message history, or the full backend state?"
</decision-points>

---

## Success Criteria: B+

The plan provides explicit success criteria (11 checkbox items) and comprehensive test tables. However, they're stated as checkbox items without commands or automation details. Suggested A-grade criteria:

<success-criteria>
success_criteria:
  - id: interviewer-implementations
    description: All interviewer implementations (AutoApprove, Queue, Recording, Callback) pass their unit tests
    command: pytest tests/ -k "test_auto_approve or test_queue_interviewer or test_recording or test_callback" -v
    expected: All tests pass, exit code 0
    automated: true

  - id: wait-human-handler
    description: WaitHumanHandler derives choices from outgoing edge labels, presents to interviewer, and routes based on selection
    command: pytest tests/ -k "test_wait_human" -v
    expected: All tests pass including edge derivation, accelerator parsing, routing, timeout, and context updates
    automated: true

  - id: accelerator-parsing
    description: All accelerator key patterns parse correctly
    command: pytest tests/ -k "test_accelerator" -v
    expected: "[K] Label, K) Label, K - Label, and first-character fallback all parse correctly"
    automated: true

  - id: interactive-mode
    description: Chat-style interactive mode supports multi-turn conversation with /done, /approve, /reject commands
    command: pytest tests/ -k "test_interactive" -v
    expected: Multi-turn exchange, commands, and checkpoint-per-turn tests all pass
    automated: true

  - id: interactive-resume
    description: Interactive mode can resume mid-conversation from a checkpoint
    command: pytest tests/ -k "test_resume_mid_conversation" -v
    expected: Conversation resumes from correct turn with history preserved
    automated: true

  - id: e2e-human-gate
    description: Full pipeline with human gate routes correctly using QueueInterviewer
    command: pytest tests/ -k "test_pipeline_human_gate or test_pipeline_reject or test_pipeline_auto_approve" -v
    expected: Pipeline routes to correct path based on interviewer response
    automated: true

  - id: e2e-multiple-gates
    description: Pipeline with multiple human gates handles sequential decisions
    command: pytest tests/ -k "test_multiple_human_gates" -v
    expected: Both gates route correctly using pre-filled queue answers
    automated: true

  - id: e2e-interactive-node
    description: Pipeline with interactive codergen node completes via QueueInterviewer
    command: pytest tests/ -k "test_pipeline_interactive" -v
    expected: Agent and human exchange messages, node completes successfully
    automated: true

  - id: hexagon-shape-registered
    description: Hexagon shape is registered in the default handler registry
    command: python -c "from orchestra.handlers.registry import default_registry; r = default_registry(); assert r.get('hexagon') is not None"
    expected: Exit code 0, no assertion error
    automated: true

  - id: no-regressions
    description: All existing tests continue to pass
    command: pytest tests/ -v
    expected: All tests pass, exit code 0
    automated: true

evaluation_dependencies:
  - pytest test framework (already configured)
  - QueueInterviewer for deterministic test responses
  - AutoApproveInterviewer for CI mode tests
  - SimulationBackend for mocking LLM responses in interactive mode tests
  - DOT fixture files with hexagon nodes
</success-criteria>

---

<missing-context>
missing_context:
  - category: technical
    items:
      - id: interactive-backend-compatibility
        question: Should interactive mode work with all backends (Simulation, Direct, LangGraph, CLI Agent) or only specific ones?
        why_it_matters: "If interactive mode needs to work with LangGraph's ReAct agent, the chat loop must integrate with LangGraph's streaming. If only Direct/Simulation, it's simpler."
        how_to_resolve: "Ask user — the attractor spec does NOT mention interactive mode at all (it's plan-specific, not in the spec)"
        status: RESOLVED
        resolution: "All backends. Interactive mode must work with Simulation, Direct, LangGraph, and CLI Agent."

      - id: hexagon-parser-support
        question: Does the DOT parser already handle hexagon shape, or does the parser/transformer need updating?
        why_it_matters: "If the parser doesn't recognize hexagon, it's a prerequisite step"
        how_to_resolve: "Check parser/transformer.py for shape handling"
        status: RESOLVED
        resolution: "The DOT parser passes shape attributes through as-is (transformer.py:87 reads shape from merged attributes with default 'box'). No parser changes needed — hexagon will work out of the box."

      - id: interviewer-event-type
        question: Should human interactions be stored as a new CXDB turn type (e.g., HumanInteraction) or reuse existing event types?
        why_it_matters: "New turn type requires updating the type bundle schema in CXDB storage"
        how_to_resolve: "Check existing event types in events/ and CXDB type bundle definition"
        status: RESOLVED
        resolution: "A new HumanInteraction event type should be added to events/types.py, following the existing pattern (pydantic BaseModel with event_type field). The CXDB type bundle will need updating but this is idempotent (publish_type_bundle is already called on each run)."

      - id: interactive-mode-not-in-spec
        question: "Interactive mode (agent.mode='interactive') is specified in the plan but NOT in the attractor spec. Is this intentional scope expansion, or should it be deferred?"
        why_it_matters: "This is the most complex feature in the plan (~30-40% of the effort). If it's not in the spec, it may be premature."
        how_to_resolve: "Ask user"
        status: RESOLVED
        resolution: "Include in Stage 4. User confirmed this as intentional scope expansion."

  - category: business
    items: []
    # The plan is technically focused with no business ambiguity

  - category: organizational
    items: []
    # Single developer project, no organizational dependencies
</missing-context>

---

<additional-context>
## Resolved Context from Codebase Exploration

### Parser / Hexagon Shape
The DOT parser (`parser/transformer.py:87`) extracts `shape` from node attributes with `"box"` as default. Shapes are passed through as arbitrary strings — no allowlist. **Hexagon shape will parse without any changes.**

### Existing Accelerator Key Handling
`edge_selection.py:10` already has `_ACCELERATOR_PREFIX = re.compile(r"^\[?\w\]?\s*[-–)]\s*|^\[\w\]\s+")` for normalizing labels (stripping prefixes). This handles stripping but not extraction. The plan needs a richer parser that returns `(key, clean_label)` tuples.

### Event System
Events are pydantic models in `events/types.py` with a dispatcher that maps `event_type` strings to classes. Adding a `HumanInteraction` event follows the established pattern. The `EventDispatcher` uses `EVENT_TYPE_MAP` for dispatch.

### Handler Registry
`default_registry()` in `handlers/registry.py` takes `backend` and `config` parameters. Adding `interviewer` as a third parameter is a natural extension. The `WaitHumanHandler` would be registered for shape `"hexagon"`.

### Outcome Model
The existing `Outcome` model already has `preferred_label` and `suggested_next_ids` — exactly what `WaitHumanHandler` needs to route. The handler returns `suggested_next_ids=[selected_edge.to_node]` and edge selection Step 3 handles it.

### Attractor Spec Coverage
- **Section 4.6** (WaitForHumanHandler): Fully specified with pseudocode, covers choice derivation, accelerator parsing, timeout handling, context updates
- **Section 6** (Interviewer Pattern): Fully specified with Question/Answer models, all 5 interviewer implementations, timeout handling
- **NOT in spec**: Interactive mode (`agent.mode="interactive"`) — this is plan-specific scope expansion beyond the attractor spec
</additional-context>

