// src/data/agentMockData.js
// -----------------------------------------------------------------------------
// CARA fixture artifacts for frontend-only UI work.
//
// These mirror the current backend schemas across Visionary, Agenda,
// Interviewer, Distiller, Sprint, and Analyst so reviewers can exercise the
// artifact panel without running the LLM workflow.
// -----------------------------------------------------------------------------

export const MOCK_SESSION_ID = "mock-session-cafe-queue";
export const MOCK_CHAT_ID = "mock-chat-cafe-queue";
export const MOCK_PROJECT_ID = "mock-project-cafe-queue";

export const MOCK_PROJECT_DESCRIPTION =
  "Build a lightweight queue and pickup coordination tool for a small cafe. Guests should know where their order stands, baristas should see a manageable preparation queue, and shift leads should notice delays before the counter gets crowded.";

const productVision = {
  session_id: MOCK_SESSION_ID,
  created_at: "2026-05-21T09:00:00.000Z",
  status: "pending_review",
  description:
    "A lightweight queue and pickup coordination tool for a small cafe. It helps guests understand order progress, gives baristas a focused preparation queue, and gives shift leads early visibility into delays.",
  intent_summary:
    "The project asks for a first-release cafe queue tool that coordinates order status, preparation work, and delay awareness.",
  target_outcome:
    "Guests wait with less uncertainty while cafe staff keep preparation work visible and recover from bottlenecks sooner.",
  notes:
    "PASS 1 - READING\nThe input directly names guests, baristas, and shift leads as runtime roles. It also names concrete signals: guests wait for orders, baristas prepare orders, shift leads monitor crowding and delays.\n\nPASS 2 - FORKS\nThe first-release forks are status detail, preparation queue shape, and delay visibility. Payment and POS replacement are kept out of scope.",
  known_signals: [
    "Guests currently wait for cafe orders and need to know where the order stands.",
    "Baristas currently manage preparation work at the counter.",
    "Shift leads currently notice problems when the counter gets crowded.",
  ],
  roles: [
    {
      id: "ROLE-01",
      name: "Guest",
      need:
        "Guests need to know order progress and pickup readiness while waiting in or near the cafe.",
      lens: "stated",
      anchor: 'The input directly names "Guests" as people who should know order status.',
    },
    {
      id: "ROLE-02",
      name: "Barista",
      need:
        "Baristas need a preparation queue that keeps current work visible without adding counter-side overhead.",
      lens: "stated",
      anchor: 'The input directly names "baristas" and their preparation queue.',
    },
    {
      id: "ROLE-03",
      name: "Shift lead",
      need:
        "Shift leads need early delay signals so they can rebalance work before guests crowd the counter.",
      lens: "stated",
      anchor: 'The input directly names "shift leads" noticing delays and crowding.',
    },
  ],
  assumptions: [
    {
      id: "ASM-01",
      statement:
        "A status timeline is more useful than a pickup-only notification for guests waiting on cafe orders.",
      why_it_matters:
        "This fork changes whether the first release shows intermediate preparation states or only a final ready state.",
      lens: "implied",
      anchor:
        'The phrase "know where their order stands" implies more than a final pickup alert.',
    },
    {
      id: "ASM-02",
      statement:
        "A station-grouped preparation queue is more useful than one shared chronological queue for baristas.",
      why_it_matters:
        "This fork changes queue layout and how preparation work is grouped.",
      lens: "implied",
      anchor:
        'The phrase "manageable preparation queue" implies the queue shape is still undecided.',
    },
    {
      id: "ASM-03",
      statement:
        "Delay signals generated from queue pressure are more useful than manual staff reports for shift leads.",
      why_it_matters:
        "This fork changes whether the product computes delay warnings or relies on staff to flag them.",
      lens: "implied",
      anchor:
        'The phrase "notice delays before the counter gets crowded" implies proactive delay visibility.',
    },
  ],
  concerns: [
    {
      id: "CONCERN-01",
      theme: "clarity",
      affected_roles: ["Guest"],
      rationale:
        "Guests will notice quickly if status wording is vague or does not match what staff say at pickup.",
      lens: "implied",
      anchor: 'The input asks guests to "know where their order stands".',
    },
    {
      id: "CONCERN-02",
      theme: "timeliness",
      affected_roles: ["Guest", "Barista", "Shift lead"],
      rationale:
        "The tool only helps if order state and delay signals update while they can still change behavior.",
      lens: "implied",
      anchor:
        'The input connects delay awareness to preventing counter crowding.',
    },
    {
      id: "CONCERN-03",
      theme: "recoverability",
      affected_roles: ["Guest", "Barista"],
      rationale:
        "Cafe staff and guests need visible recovery when an order is missing, delayed, or marked incorrectly.",
      lens: "inferred",
      anchor:
        "Queue coordination products need recovery paths because order state can be wrong or stale.",
    },
  ],
  scope: [
    {
      id: "OOS-01",
      item: "The product does not process payments.",
      reason:
        "The request is about queue and pickup coordination, not checkout or payment capture.",
      lens: "inferred",
      anchor:
        "Cafe queue tools commonly integrate after payment rather than owning payment processing.",
    },
    {
      id: "OOS-02",
      item: "The product does not replace the POS as the source of order truth.",
      reason:
        "Keeping the POS authoritative prevents the first release from expanding into full order management.",
      lens: "inferred",
      anchor:
        "The request asks for coordination around orders, not a replacement order-entry system.",
    },
  ],
};

const reviewedProductVision = {
  ...productVision,
  status: "approved",
  reviewed_at: "2026-05-21T09:10:00.000Z",
  review_notes: null,
};

const elicitationAgenda = {
  session_id: MOCK_SESSION_ID,
  created_at: "2026-05-21T09:20:00.000Z",
  status: "pending_review",
  notes:
    "ASM-01 -> IT-001\nASM-02 -> IT-002\nASM-03 -> IT-003\nCONCERN-01 -> IT-001\nCONCERN-02 -> IT-002, IT-003\nCONCERN-03 -> IT-004\nOOS-02 -> IT-004\nROLE-01 Guest -> IT-001\nROLE-02 Barista -> IT-002, IT-004\nROLE-03 Shift lead -> IT-003\n\n--- Reviewer commentary ---\nThe agenda keeps one evidence job per item and probes each stated role at least once.",
  items: [
    {
      id: "IT-001",
      vision_refs: ["ASM-01", "CONCERN-01"],
      perspective: "Guest",
      context:
        "After placing a cafe order and waiting nearby without knowing whether to stay close to the pickup counter.",
      decision_target:
        "status timeline granularity vs pickup-only notification",
      seed_question:
        "Think about the last time you waited for a cafe order. What did you try to figure out while you were waiting?",
      coverage_points: [
        "What status details the guest currently looks for while waiting.",
        "Which uncertainty makes the guest approach staff or crowd the counter.",
        "Which wording or signal would be clear enough without staff explanation.",
      ],
      close_when:
        "The answer settles which status states are useful and what makes them clear to a waiting guest.",
      merge_anchor:
        "One answer from Guest in the waiting scene settles status detail and clarity because both determine what the guest can confidently observe.",
      notes:
        "Merged ASM-01 and CONCERN-01 because the same waiting scene tests both status depth and clarity.",
    },
    {
      id: "IT-002",
      vision_refs: ["ASM-02", "CONCERN-02"],
      perspective: "Barista",
      context:
        "During a rush when multiple paid orders are waiting and drinks or food may be prepared at different stations.",
      decision_target: "station-grouped queue vs one chronological queue",
      seed_question:
        "When the rush builds today, how do you decide which order or item to work on next?",
      coverage_points: [
        "How baristas currently split or sequence preparation work.",
        "Which queue view would reduce missed or duplicated work.",
        "Which timing signal matters before an order becomes a delay.",
      ],
      close_when:
        "The answer settles whether grouping by station or preserving one chronological list better supports preparation.",
      merge_anchor:
        "One answer from Barista in the rush scene settles queue shape and timeliness because queue grouping changes how fast work can be noticed and started.",
      notes:
        "Uses the role that lives the preparation queue rather than an observer.",
    },
    {
      id: "IT-003",
      vision_refs: ["ASM-03", "CONCERN-02"],
      perspective: "Shift lead",
      context:
        "While watching the counter during a busy period and deciding whether to move staff between stations.",
      decision_target: "computed delay signal vs manual escalation",
      seed_question:
        "Before the counter gets crowded today, what clues tell you that the queue is starting to fall behind?",
      coverage_points: [
        "Which visible conditions lead the shift lead to intervene.",
        "Which delay threshold is actionable before guests complain.",
        "Which signal should be shown without forcing staff to write reports.",
      ],
      close_when:
        "The answer settles what delay indicator is actionable for rebalancing work.",
      merge_anchor:
        "One answer from Shift lead in the counter-monitoring scene settles proactive delay detection and timeliness because both drive intervention timing.",
      notes:
        "Shift lead evidence is separate from barista evidence because the decision is staffing intervention.",
    },
    {
      id: "IT-004",
      vision_refs: ["OOS-02", "CONCERN-03"],
      perspective: "Barista",
      context:
        "When an order shown at the pickup counter does not match what the POS or kitchen ticket says.",
      decision_target: "POS-authoritative recovery vs in-tool order editing",
      seed_question:
        "When an order state is wrong today, what do you trust first and what do you do to recover?",
      coverage_points: [
        "Which system or artifact staff treat as the order source of truth.",
        "What recovery steps staff take when status is wrong.",
        "Which correction should be visible to guests without replacing POS edits.",
      ],
      close_when:
        "The answer settles how the product should show recovery while keeping POS authority outside product scope.",
      merge_anchor:
        "One answer from Barista in the mismatch scene settles POS boundary and recoverability because recovery depends on which source remains authoritative.",
      notes:
        "Tests a scope boundary from the staff side that enforces it.",
    },
  ],
};

const reviewedElicitationAgenda = {
  ...elicitationAgenda,
  status: "approved",
  reviewed_at: "2026-05-21T09:25:00.000Z",
  review_notes: null,
};

const interviewItems = [
  {
    id: "EL-001",
    item: "IT-001",
    vision_refs: ["ASM-01", "CONCERN-01"],
    perspective: "Guest",
    context:
      "After placing a cafe order and waiting nearby without knowing whether to stay close to the pickup counter.",
    decision_target: "status timeline granularity vs pickup-only notification",
    close_when:
      "The answer settles which status states are useful and what makes them clear to a waiting guest.",
    coverage_points: [
      "What status details the guest currently looks for while waiting.",
      "Which uncertainty makes the guest approach staff or crowd the counter.",
      "Which wording or signal would be clear enough without staff explanation.",
    ],
    coverage: [
      {
        point: "What status details the guest currently looks for while waiting.",
        status: "covered",
        evidence:
          "The guest wants to know whether the order is queued, being prepared, or ready at pickup.",
      },
      {
        point: "Which uncertainty makes the guest approach staff or crowd the counter.",
        status: "covered",
        evidence:
          "The guest asks staff when there is no visible change after several minutes.",
      },
    ],
    signals: [
      "Guests look for queued, preparing, final check, and ready states while waiting.",
      "Guests approach staff when the status has not changed for several minutes.",
      "Guests need the order name or number next to status text to trust the status.",
      "A pickup-only ping is too late to reduce counter crowding during busy periods.",
    ],
    assumption_evidence: [
      {
        vision_ref: "ASM-01",
        stance: "supports",
        evidence:
          "The guest described intermediate states as useful before pickup readiness.",
        implication:
          "Requirement should include a guest-facing order status timeline.",
      },
    ],
    gaps: [],
    rule:
      "Guest-facing status should show at least queued, preparing, final check, and ready states with order identity.",
    talk: [
      {
        question:
          "Think about the last time you waited for a cafe order. What did you try to figure out while you were waiting?",
        answer:
          "I tried to figure out if my order was still in the line, actually being made, or already ready but missed. If nothing changes after a few minutes I usually walk closer to the counter and ask.",
      },
      {
        question:
          "What would make the status clear enough that you would not need to ask staff?",
        answer:
          "Use plain labels like queued, preparing, final check, and ready, and show my order number or name next to it. A final pickup ping alone is helpful but too late for the waiting part.",
      },
    ],
    status: "answered",
  },
  {
    id: "EL-002",
    item: "IT-002",
    vision_refs: ["ASM-02", "CONCERN-02"],
    perspective: "Barista",
    context:
      "During a rush when multiple paid orders are waiting and drinks or food may be prepared at different stations.",
    decision_target: "station-grouped queue vs one chronological queue",
    close_when:
      "The answer settles whether grouping by station or preserving one chronological list better supports preparation.",
    coverage_points: [
      "How baristas currently split or sequence preparation work.",
      "Which queue view would reduce missed or duplicated work.",
      "Which timing signal matters before an order becomes a delay.",
    ],
    coverage: [
      {
        point: "How baristas currently split or sequence preparation work.",
        status: "covered",
        evidence:
          "Baristas mentally split drinks, food, and handoff tasks even when tickets arrive chronologically.",
      },
      {
        point: "Which timing signal matters before an order becomes a delay.",
        status: "covered",
        evidence:
          "A visible age marker after five minutes tells staff to check the order before guests ask.",
      },
    ],
    signals: [
      "Baristas split preparation work by drinks, food, and handoff tasks.",
      "A single chronological list forces baristas to scan unrelated work.",
      "Station grouping reduces the chance two baristas start the same item.",
      "Orders older than five minutes need a visible warning before guests ask.",
    ],
    assumption_evidence: [
      {
        vision_ref: "ASM-02",
        stance: "supports",
        evidence:
          "The barista said station grouping matches current preparation work.",
        implication:
          "Requirement should group preparation queue items by station while preserving order age.",
      },
    ],
    gaps: [],
    rule:
      "Preparation queue should group items by station and show order age warnings around five minutes.",
    talk: [
      {
        question:
          "When the rush builds today, how do you decide which order or item to work on next?",
        answer:
          "We do not really work from one pure line. Drinks, food, and handoff split naturally. If everything is one chronological list, I scan past a lot of unrelated items.",
      },
      {
        question:
          "What would make the queue easier to trust during the rush?",
        answer:
          "Group by station but keep age visible. If something is over five minutes, it should stand out before the guest asks. Also make it clear when someone has already started an item.",
      },
    ],
    status: "answered",
  },
  {
    id: "EL-003",
    item: "IT-003",
    vision_refs: ["ASM-03", "CONCERN-02"],
    perspective: "Shift lead",
    context:
      "While watching the counter during a busy period and deciding whether to move staff between stations.",
    decision_target: "computed delay signal vs manual escalation",
    close_when:
      "The answer settles what delay indicator is actionable for rebalancing work.",
    coverage_points: [
      "Which visible conditions lead the shift lead to intervene.",
      "Which delay threshold is actionable before guests complain.",
      "Which signal should be shown without forcing staff to write reports.",
    ],
    coverage: [
      {
        point: "Which visible conditions lead the shift lead to intervene.",
        status: "covered",
        evidence:
          "The shift lead intervenes when several orders are aging and one station has more pending work than others.",
      },
      {
        point: "Which signal should be shown without forcing staff to write reports.",
        status: "covered",
        evidence:
          "The shift lead wants automatic station-level warnings rather than manual reports.",
      },
    ],
    signals: [
      "Shift leads intervene when several orders are aging at the same time.",
      "Station imbalance is a better delay clue than one individual late order.",
      "A five to seven minute warning gives enough time to move staff.",
      "Manual delay reporting is skipped during rushes.",
    ],
    assumption_evidence: [
      {
        vision_ref: "ASM-03",
        stance: "supports",
        evidence:
          "The shift lead said automatic station-level warnings are preferable to manual reports.",
        implication:
          "Requirement should compute delay signals from queue age and station pressure.",
      },
    ],
    gaps: [],
    rule:
      "Delay warnings should be computed from order age and station pressure, with a warning window around five to seven minutes.",
    talk: [
      {
        question:
          "Before the counter gets crowded today, what clues tell you that the queue is starting to fall behind?",
        answer:
          "I look for several orders aging at once and whether one station has too many pending items. One late order can be normal, but a cluster means I need to move someone.",
      },
      {
        question:
          "Would staff manually report those delays during the rush?",
        answer:
          "Usually no. People are too busy. I would rather see an automatic station warning around five to seven minutes so I can act before guests gather.",
      },
    ],
    status: "answered",
  },
  {
    id: "EL-004",
    item: "IT-004",
    vision_refs: ["OOS-02", "CONCERN-03"],
    perspective: "Barista",
    context:
      "When an order shown at the pickup counter does not match what the POS or kitchen ticket says.",
    decision_target: "POS-authoritative recovery vs in-tool order editing",
    close_when:
      "The answer settles how the product should show recovery while keeping POS authority outside product scope.",
    coverage_points: [
      "Which system or artifact staff treat as the order source of truth.",
      "What recovery steps staff take when status is wrong.",
      "Which correction should be visible to guests without replacing POS edits.",
    ],
    coverage: [
      {
        point: "Which system or artifact staff treat as the order source of truth.",
        status: "covered",
        evidence:
          "Staff treat the POS ticket as authoritative when status conflicts.",
      },
      {
        point: "Which correction should be visible to guests without replacing POS edits.",
        status: "covered",
        evidence:
          "Guests should see a refreshed status or a staff-checking message, not an editable order detail.",
      },
    ],
    signals: [
      "The POS ticket is the authoritative order source during conflicts.",
      "Queue status should refresh after POS correction.",
      "Guests should see that staff are checking an order when status is uncertain.",
      "Baristas should not edit paid order details in the queue tool.",
    ],
    assumption_evidence: [
      {
        vision_ref: "OOS-02",
        stance: "supports",
        evidence:
          "The barista treats the POS ticket as the source of truth.",
        implication:
          "Requirement should preserve POS authority and avoid in-tool order edits.",
      },
    ],
    gaps: [],
    rule:
      "The queue tool should refresh from POS corrections and show recovery status without editing paid order details.",
    talk: [
      {
        question:
          "When an order state is wrong today, what do you trust first and what do you do to recover?",
        answer:
          "The POS ticket wins. We correct the source there or decide a remake there. The queue screen should refresh from that, not become another place to edit the order.",
      },
      {
        question:
          "What should guests see while staff are checking the mismatch?",
        answer:
          "They should see something like staff checking or status refreshing, then the corrected status. They should not see us changing the paid order details in the queue tool.",
      },
    ],
    status: "answered",
  },
];

const interviewRecord = {
  session_id: MOCK_SESSION_ID,
  project_description: MOCK_PROJECT_DESCRIPTION,
  created_at: "2026-05-21T09:45:00.000Z",
  status: "pending_review",
  items: interviewItems,
  notes: interviewItems
    .map((item) => {
      const turns = item.talk.map((turn) => `Q: ${turn.question}\nA: ${turn.answer}`).join("\n");
      return `[${item.item}] ${item.perspective}\n${turns}`;
    })
    .join("\n\n"),
};

const reviewedInterviewRecord = {
  ...interviewRecord,
  status: "approved",
  reviewed_at: "2026-05-21T09:50:00.000Z",
  review_notes: null,
};

const requirementList = {
  session_id: MOCK_SESSION_ID,
  project_description: MOCK_PROJECT_DESCRIPTION,
  synthesised_at: "2026-05-21T10:05:00.000Z",
  status: "pending_review",
  notes:
    "PASS 1 - PER-RECORD EXTRACTION\n  [EL-001]: Extracted guest-facing status and clarity requirements from waiting signals.\n  [EL-002]: Extracted station queue and age warning requirements from barista preparation signals.\n  [EL-003]: Extracted delay warning logic from shift lead intervention signals.\n  [EL-004]: Extracted POS-authoritative recovery requirements and preserved scope boundaries.\n\nPASS 2 - SYNTHESIZE\n  Consolidated per-record items, added no extra vision constraints, adjudicated no final conflicts.\n\nVISION OOS PRESERVATION (Python, deterministic)\n  - Preserved 2 vision scope item(s) as out_of_scope.",
  items: [
    {
      id: "FR-01",
      type: "functional",
      stakeholder: "Guest",
      statement:
        "The product displays a guest-facing order status timeline with queued, preparing, final check, and ready states.",
      rationale:
        "Guests said intermediate states reduce uncertainty before pickup readiness.",
      trace_refs: ["EL-001-S01", "EL-001-S04", "ASM-01", "CONCERN-01"],
      acceptance_criteria: [
        "Each active guest order displays one of queued, preparing, final check, or ready.",
        "The status timeline includes the guest order name or number.",
        "The ready state is visually distinct from earlier states.",
      ],
      status: "confirmed",
      confidence: "confirmed",
      trigger_event: "guest views an active paid order",
      product_object: "order status timeline",
      observable_outcome: "Guest can see where the order stands before pickup.",
      operating_condition: "while the order is active and not yet picked up",
      participation_structure: "single-actor",
    },
    {
      id: "FR-02",
      type: "functional",
      stakeholder: "Barista",
      statement:
        "The product groups preparation queue items by station while preserving each order's age.",
      rationale:
        "Baristas said station grouping matches how they split rush work and reduces scanning unrelated items.",
      trace_refs: ["EL-002-S01", "EL-002-S02", "EL-002-S03", "ASM-02"],
      acceptance_criteria: [
        "The preparation queue can show drink, food, and handoff station groups.",
        "Each grouped item shows its order age.",
        "An item already started by one barista is marked as in progress.",
      ],
      status: "confirmed",
      confidence: "confirmed",
      trigger_event: "barista opens the preparation queue",
      product_object: "station-grouped preparation queue",
      observable_outcome: "Barista can identify station work without scanning unrelated items.",
      operating_condition: "during active preparation",
      participation_structure: "multi-actor",
    },
    {
      id: "FR-03",
      type: "functional",
      stakeholder: "Shift lead",
      statement:
        "The product shows automatic station-level delay warnings based on order age and station pressure.",
      rationale:
        "Shift leads said automatic warnings are needed because manual reporting is skipped during rushes.",
      trace_refs: ["EL-003-S01", "EL-003-S02", "EL-003-S04", "ASM-03"],
      acceptance_criteria: [
        "The shift view highlights stations with multiple aging orders.",
        "The warning appears without staff manually submitting a delay report.",
        "The warning identifies the affected station and the count of aging orders.",
      ],
      status: "confirmed",
      confidence: "inferred",
      trigger_event: "order age and station pressure cross a warning threshold",
      product_object: "station-level delay warning",
      observable_outcome:
        "Shift lead can see where to rebalance staff before counter crowding.",
      operating_condition: "during busy periods with active preparation",
      participation_structure: "authority-mediated",
    },
    {
      id: "FR-04",
      type: "functional",
      stakeholder: "Guest",
      statement:
        "The product displays a recovery status when an order state is being checked or refreshed from the POS.",
      rationale:
        "Baristas said guests should see that staff are checking a mismatch instead of seeing editable paid order details.",
      trace_refs: ["EL-004-S02", "EL-004-S03", "CONCERN-03", "OOS-02"],
      acceptance_criteria: [
        "When an order state is uncertain, the guest display shows a staff-checking or refreshing state.",
        "After POS correction, the guest display updates to the corrected status.",
        "The guest display does not expose paid order editing controls.",
      ],
      status: "confirmed",
      confidence: "confirmed",
      trigger_event: "order status conflicts with POS or kitchen ticket state",
      product_object: "guest recovery status",
      observable_outcome:
        "Guest can see that the order is being checked and then see the corrected status.",
      operating_condition: "when status is stale, mismatched, or refreshed",
      participation_structure: "multi-actor",
    },
    {
      id: "NFR-01",
      type: "non_functional",
      stakeholder: "Guest",
      statement:
        "The product uses consistent, plain-language status labels across guest and staff views.",
      rationale:
        "Guests need status wording that is clear enough without staff explanation.",
      trace_refs: ["EL-001-S03", "CONCERN-01"],
      acceptance_criteria: [
        "The same status label text appears wherever the same order state is shown.",
        "Status labels avoid internal cafe abbreviations.",
      ],
      status: "confirmed",
      confidence: "confirmed",
      trigger_event: "order status is displayed",
      product_object: "status label text",
      observable_outcome:
        "Guest sees status wording that matches staff-facing order state.",
      operating_condition: "across active order displays",
      participation_structure: "single-actor",
    },
    {
      id: "SYS-01",
      type: "system",
      stakeholder: "product-wide",
      statement:
        "The system preserves POS authority by refreshing queue state from POS corrections rather than editing paid order details.",
      rationale:
        "Baristas treat the POS ticket as the authoritative order source during conflicts.",
      trace_refs: ["EL-004-S01", "EL-004-S04", "OOS-02"],
      acceptance_criteria: [
        "Queue state can refresh after POS correction.",
        "Paid order detail edits are not available in the queue tool.",
      ],
      status: "confirmed",
      confidence: "confirmed",
      trigger_event: "POS order state changes or conflicts with queue state",
      product_object: "queue state synchronization",
      observable_outcome:
        "Queue state follows POS corrections without becoming the order source of truth.",
      operating_condition: "when POS corrections or mismatches occur",
      participation_structure: "authority-mediated",
    },
    {
      id: "OOS-01",
      type: "out_of_scope",
      stakeholder: null,
      statement: "The product does not process payments.",
      rationale:
        "The Product Vision excludes checkout and payment capture from the coordination tool.",
      trace_refs: ["OOS-01", "ProductVision.scope[0]"],
      acceptance_criteria: [],
      status: "excluded",
      confidence: "confirmed",
      trigger_event: "",
      product_object: "",
      observable_outcome: "",
      operating_condition: "",
      participation_structure: "",
    },
    {
      id: "OOS-02",
      type: "out_of_scope",
      stakeholder: null,
      statement:
        "The product does not replace the POS as the source of order truth.",
      rationale:
        "The Product Vision keeps POS authority outside first-release scope.",
      trace_refs: ["OOS-02", "ProductVision.scope[1]"],
      acceptance_criteria: [],
      status: "excluded",
      confidence: "confirmed",
      trigger_event: "",
      product_object: "",
      observable_outcome: "",
      operating_condition: "",
      participation_structure: "",
    },
  ],
  conflicts: [],
  gaps: [],
};

const requirementListApproved = {
  ...requirementList,
  status: "approved",
  reviewed_at: "2026-05-21T10:10:00.000Z",
  review_notes: null,
};

const activeRequirements = requirementList.items.filter(
  (item) => item.type !== "out_of_scope" && item.status !== "excluded",
);

function requirementTrace(requirement, priority = "medium") {
  return {
    requirement_id: requirement.id,
    requirement_type: requirement.type,
    stakeholder: requirement.stakeholder || "product-wide",
    statement: requirement.statement,
    rationale: requirement.rationale,
    acceptance_criteria: requirement.acceptance_criteria,
    trace_refs: requirement.trace_refs,
    priority,
    status: requirement.status,
    threshold_needed: false,
    confidence: requirement.confidence,
    trigger_event: requirement.trigger_event,
    product_object: requirement.product_object,
    observable_outcome: requirement.observable_outcome,
    operating_condition: requirement.operating_condition,
    participation_structure: requirement.participation_structure,
  };
}

const storyDraftRows = [
  {
    requirementId: "FR-01",
    title: "Guest order status timeline",
    description:
      "As a Guest, I can view my active paid order moving through queued, preparing, final check, and ready states, so that I know where my order stands before pickup.",
    thought:
      "Maps the status timeline requirement directly to the waiting guest's active-order moment.",
    priority: "high",
  },
  {
    requirementId: "FR-02",
    title: "Station-grouped preparation queue",
    description:
      "As a Barista, I can view active preparation items grouped by station with order age visible, so that I can focus on my station work during rushes.",
    thought:
      "Keeps queue shape and order age together because both are needed in the same preparation view.",
    priority: "high",
  },
  {
    requirementId: "FR-03",
    title: "Automatic delay warnings",
    description:
      "As a Shift lead, I can see automatic station-level delay warnings when queue pressure builds, so that I can rebalance staff before guests crowd the counter.",
    thought:
      "The trace is inferred from queue-pressure signals, so the story names the staffing intervention explicitly.",
    priority: "high",
  },
  {
    requirementId: "FR-04",
    title: "Guest-visible recovery status",
    description:
      "As a Guest, I can see when staff are checking or refreshing my order status, so that I understand recovery is in progress during a mismatch.",
    thought:
      "Keeps recovery visible to guests without adding order editing behavior.",
    priority: "medium",
  },
  {
    requirementId: "NFR-01",
    title: "Consistent plain-language labels",
    description:
      "As a Guest, I can read consistent plain-language status labels across order views, so that I can understand status without staff explanation.",
    thought:
      "Represents the clarity NFR as a reviewable label consistency story.",
    priority: "medium",
  },
  {
    requirementId: "SYS-01",
    title: "POS-authoritative queue refresh",
    description:
      "As a Product, I can refresh queue state from POS corrections without queue-side paid order edits, so that POS remains the source of order truth.",
    thought:
      "Frames the system guarantee as a product-owned capability because the stakeholder is product-wide.",
    priority: "high",
  },
];

const userStoryDraft = {
  id: "mock-user-story-draft-001",
  session_id: MOCK_SESSION_ID,
  source_artifacts: ["requirement_list_approved", "reviewed_product_vision"],
  created_at: "2026-05-21T10:20:00.000Z",
  total_stories: storyDraftRows.length,
  pass_notes:
    "PASS 1 - PER-REQUIREMENT STORY CREATION\n" +
    storyDraftRows.map((row) => `  [${row.requirementId}] ${row.thought}`).join("\n"),
  stories: storyDraftRows.map((row) => {
    const requirement = activeRequirements.find((item) => item.id === row.requirementId);
    return {
      source_story_id: row.requirementId,
      source_requirement_id: row.requirementId,
      type: requirement.type,
      domain: requirement.stakeholder || requirement.type,
      title: row.title,
      description: row.description,
      requirement_trace: requirementTrace(requirement, row.priority),
      is_split_child: false,
      split: { parent_story_id: null, suffix: null, reasoning: null },
      thought: row.thought,
    };
  }),
};

const storyPointById = {
  "FR-01": 3,
  "FR-02": 5,
  "FR-03": 5,
  "FR-04": 3,
  "NFR-01": 3,
  "SYS-01": 5,
};

const analystEstimation = {
  id: "mock-analyst-estimation-001",
  session_id: MOCK_SESSION_ID,
  source_artifacts: ["user_story_draft", "reviewed_product_vision"],
  estimated_at: "2026-05-21T10:35:00.000Z",
  split_round: 0,
  stories: userStoryDraft.stories.map((story) => {
    const points = storyPointById[story.source_story_id] || 3;
    const blockedBy = story.source_story_id === "SYS-01" ? [] : ["SYS-01"];
    return {
      source_story_id: story.source_story_id,
      source_requirement_id: story.source_requirement_id,
      type: story.type,
      domain: story.domain,
      title: story.title,
      description: story.description,
      requirement_trace: story.requirement_trace,
      split: story.split,
      feasibility: {
        is_feasible: true,
        feasibility_notes:
          story.source_story_id === "SYS-01"
            ? "Feasible if first release reads order state from the selected POS source."
            : "Feasible once the POS-refresh boundary is established.",
      },
      invest: {
        invest_pass: true,
        invest_flags: [],
        invest_notes:
          "Story is independently reviewable, valuable to the named role, and small enough for planning.",
        criteria: {
          independent: true,
          negotiable: true,
          valuable: true,
          estimable: true,
          small: true,
          testable: true,
        },
      },
      dependencies: {
        blocked_by: blockedBy,
        blocks:
          story.source_story_id === "SYS-01"
            ? ["FR-01", "FR-02", "FR-03", "FR-04"]
            : [],
      },
      split_proposals: [],
      needs_split: false,
      risks: [
        {
          category: story.source_story_id === "SYS-01" ? "integration" : "unknown",
          description:
            story.source_story_id === "SYS-01"
              ? "POS data freshness may vary by provider."
              : "Operational thresholds may need confirmation in pilot cafe usage.",
          level: story.source_story_id === "SYS-01" ? "medium" : "low",
          mitigation:
            story.source_story_id === "SYS-01"
              ? "Keep the first release read-only against POS order state."
              : "Review labels and warnings with cafe staff before launch.",
        },
      ],
      estimation: {
        complexity: points >= 5 ? 3 : 2,
        effort: points >= 5 ? 3 : 2,
        uncertainty: story.requirement_trace.confidence === "inferred" ? 3 : 2,
        story_points: points,
        reasoning:
          points >= 5
            ? "Requires coordination across state, display, and operational timing."
            : "Small UI-facing story with clear review criteria.",
        split_warning: "",
      },
    };
  }),
  has_pending_splits: false,
  total_story_points: Object.values(storyPointById).reduce((sum, points) => sum + points, 0),
  estimation_stats: {
    total_stories: storyDraftRows.length,
    stories_needing_split: 0,
    invest_failures: 0,
  },
  pass_notes:
    "PASS 1 - FEASIBILITY / INVEST / DEPS / RISKS / SPLITS\n  All stories are feasible for a first-release backlog. SYS-01 should precede status and recovery work because it preserves POS authority.\n\nPASS 2 - COMPLEXITY / EFFORT / UNCERTAINTY (per story)\n  Estimated all stories using concept scores and Fibonacci snapping.",
};

const backlogScores = {
  "SYS-01": { rank: 1, business_value: 9, time_criticality: 9, risk_reduction: 9 },
  "FR-01": { rank: 2, business_value: 10, time_criticality: 8, risk_reduction: 7 },
  "FR-02": { rank: 3, business_value: 9, time_criticality: 8, risk_reduction: 8 },
  "FR-03": { rank: 4, business_value: 8, time_criticality: 8, risk_reduction: 9 },
  "FR-04": { rank: 5, business_value: 7, time_criticality: 7, risk_reduction: 7 },
  "NFR-01": { rank: 6, business_value: 6, time_criticality: 5, risk_reduction: 6 },
};

const orderedStoryIds = Object.entries(backlogScores)
  .sort(([, a], [, b]) => a.rank - b.rank)
  .map(([storyId]) => storyId);

const productBacklog = {
  id: "mock-product-backlog-001",
  session_id: MOCK_SESSION_ID,
  source_artifacts: [
    "requirement_list_approved",
    "reviewed_product_vision",
    "user_story_draft",
    "analyst_estimation",
  ],
  status: "draft",
  total_items: orderedStoryIds.length,
  total_story_points: analystEstimation.total_story_points,
  ready_count: orderedStoryIds.length,
  needs_refinement_count: 0,
  invest_failed_count: 0,
  oversized_count: 0,
  split_round: 0,
  items: orderedStoryIds.map((storyId, index) => {
    const story = userStoryDraft.stories.find((item) => item.source_story_id === storyId);
    const estimate = analystEstimation.stories.find((item) => item.source_story_id === storyId);
    const score = backlogScores[storyId];
    const points = estimate.estimation.story_points;
    return {
      id: `PBI-${String(index + 1).padStart(3, "0")}`,
      source_story_id: story.source_story_id,
      source_requirement_id: story.source_requirement_id,
      type: story.type,
      domain: story.domain,
      title: story.title,
      description: story.description,
      requirement_trace: story.requirement_trace,
      split: story.split,
      estimation: {
        story_points: points,
        complexity: estimate.estimation.complexity,
        effort: estimate.estimation.effort,
        uncertainty: estimate.estimation.uncertainty,
      },
      prioritization: {
        priority_rank: score.rank,
        wsjf_score: Number(((score.business_value + score.time_criticality + score.risk_reduction) / points).toFixed(2)),
        business_value: score.business_value,
        time_criticality: score.time_criticality,
        risk_reduction: score.risk_reduction,
      },
      dependencies: {
        blocked_by: storyId === "SYS-01" ? [] : ["PBI-001"],
        blocks: storyId === "SYS-01" ? ["PBI-002", "PBI-003", "PBI-004", "PBI-005"] : [],
      },
      planning: {
        status: "ready",
        target_sprint: null,
        tags: [story.domain, story.type].filter(Boolean),
      },
      quality: {
        invest_pass: true,
        invest_flags: [],
        acceptance_criteria: [],
      },
      analysis: {
        is_feasible: estimate.feasibility.is_feasible,
        feasibility_notes: estimate.feasibility.feasibility_notes,
        invest_notes: estimate.invest.invest_notes,
        risks: estimate.risks,
        estimation_reasoning: estimate.estimation.reasoning,
        split_warning: estimate.estimation.split_warning,
        wsjf_thought:
          storyId === "SYS-01"
            ? "Highest risk reduction because POS authority unblocks downstream status and recovery stories."
            : "Score balances stakeholder value against dependency on POS-authoritative refresh.",
      },
    };
  }),
  methodology: {
    story_format: "As a <role>, I can <capability>, so that <benefit>.",
    estimation: "Fibonacci story points from AnalystAgent.",
    prioritization: "WSJF scores with dependency-aware ordering.",
    quality_gate: "INVEST status from AnalystAgent.",
  },
  pass_notes:
    "Prioritized POS authority first, followed by guest status visibility and staff delay controls.",
  quality_warnings: {
    invest: [],
    format: [],
    fibonacci: [],
    oversized: [],
  },
  created_at: "2026-05-21T10:45:00.000Z",
};

const productBacklogApproved = productBacklog;

const acByPbi = {
  "PBI-001": [
    ["the POS order state changes", "the queue state refreshes", "the queue reflects the corrected POS state without exposing paid order edit controls", "happy_path"],
    ["queue state conflicts with POS state", "staff inspect the order", "the POS state remains the authoritative value shown after refresh", "edge_case"],
  ],
  "PBI-002": [
    ["a guest has an active paid order", "the guest opens order status", "the product displays queued, preparing, final check, or ready for that order", "happy_path"],
    ["an order reaches ready state", "the status timeline updates", "the ready state is visually distinct from earlier states", "happy_path"],
  ],
  "PBI-003": [
    ["multiple active orders contain drink, food, and handoff items", "a barista opens the preparation queue", "the product groups queue items by station", "happy_path"],
    ["a station item is started by one barista", "another barista views the queue", "the item is marked as in progress", "edge_case"],
  ],
  "PBI-004": [
    ["several orders at one station cross the warning window", "the shift lead views station status", "the affected station is highlighted with a delay warning", "happy_path"],
    ["no staff member has manually reported a delay", "order age and station pressure cross the warning condition", "the product still displays the station-level warning", "edge_case"],
  ],
  "PBI-005": [
    ["an order status is being checked after a mismatch", "the guest display updates", "the product shows a staff-checking or refreshing status", "happy_path"],
    ["the POS correction completes", "the queue refreshes", "the guest display shows the corrected order status", "happy_path"],
  ],
  "PBI-006": [
    ["the same order state appears in guest and staff views", "both views are rendered", "the status label text is identical", "happy_path"],
    ["a status label is displayed to a guest", "the label is rendered", "the label does not contain internal cafe abbreviations", "edge_case"],
  ],
};

let acSeq = 1;
const validatedProductBacklog = {
  ...productBacklogApproved,
  status: "validated",
  validated_at: "2026-05-21T11:05:00.000Z",
  ready_count: productBacklogApproved.items.length,
  refinement_summary:
    "PASS 3 - AC GENERATION (per PBI)\n" +
    productBacklogApproved.items.map((item) => `  [${item.id}] Acceptance criteria are product-observable and preserve the requirement trace.`).join("\n"),
  refinement_stats: {
    total_pbis: productBacklogApproved.items.length,
    ready_count: productBacklogApproved.items.length,
    total_ac: Object.values(acByPbi).reduce((sum, rows) => sum + rows.length, 0),
  },
  items: productBacklogApproved.items.map((item) => ({
    ...item,
    planning: {
      ...item.planning,
      status: "ready",
    },
    quality: {
      ...item.quality,
      acceptance_criteria: (acByPbi[item.id] || []).map(([given, when, then, type]) => ({
        id: `AC-${String(acSeq++).padStart(3, "0")}`,
        given,
        when,
        then,
        type,
      })),
    },
    analysis: {
      ...item.analysis,
      ac_generation_note:
        "Acceptance criteria use Given-When-Then clauses with product-observable outcomes.",
    },
  })),
};

const validatedProductBacklogApproved = validatedProductBacklog;

export const MOCK_AGENT_ARTIFACTS = {
  product_vision: productVision,
  reviewed_product_vision: reviewedProductVision,
  elicitation_agenda_artifact: elicitationAgenda,
  reviewed_elicitation_agenda: reviewedElicitationAgenda,
  interview_record: interviewRecord,
  reviewed_interview_record: reviewedInterviewRecord,
  requirement_list: requirementList,
  requirement_list_approved: requirementListApproved,
  user_story_draft: userStoryDraft,
  analyst_estimation: analystEstimation,
  product_backlog: productBacklog,
  product_backlog_approved: productBacklogApproved,
  validated_product_backlog: validatedProductBacklog,
  validated_product_backlog_approved: validatedProductBacklogApproved,
};

export const MOCK_REVIEW_ARTIFACTS = {
  product_vision: productVision,
  elicitation_agenda: elicitationAgenda,
  interview_record: interviewRecord,
  requirement_list: requirementList,
  product_backlog: productBacklog,
  validated_product_backlog: validatedProductBacklog,
};

const REVIEW_SEQUENCE = [
  ["product_vision", "Product Vision", "Visionary Agent", productVision],
  ["elicitation_agenda", "Elicitation Agenda", "Agenda Agent", elicitationAgenda],
  ["interview_record", "Interview Record", "Interviewer Agent", interviewRecord],
  ["requirement_list", "Requirement List", "Distiller Agent", requirementList],
  ["product_backlog", "Product Backlog", "Sprint Agent", productBacklog],
  ["validated_product_backlog", "Validated Product Backlog", "Analyst Agent", validatedProductBacklog],
];

function makeArtifactMessage([type, title, agentName, raw], index, list) {
  const messageId = `mock-artifact-message-${String(index + 1).padStart(2, "0")}`;
  const artifactId = raw.id || `mock-${type}-${String(index + 1).padStart(2, "0")}`;
  const isLast = index === list.length - 1;

  return {
    id: messageId,
    role: "assistant",
    agentName,
    content: "",
    streaming: false,
    artifact: {
      id: artifactId,
      title,
      content: JSON.stringify(raw, null, 2),
      language: "json",
      type,
      agentName,
      iteration: 1,
      accepted: !isLast,
      awaitingFeedback: isLast,
      messageId,
      chatId: MOCK_CHAT_ID,
    },
  };
}

export const MOCK_ARTIFACT_MESSAGES = REVIEW_SEQUENCE.map(makeArtifactMessage);
export const MOCK_DISTILLER_ARTIFACT_MESSAGES = REVIEW_SEQUENCE
  .slice(0, 4)
  .map(makeArtifactMessage);

export const MOCK_WORKFLOW_STATE = {
  session_id: MOCK_SESSION_ID,
  project_description: MOCK_PROJECT_DESCRIPTION,
  system_phase: "backlog_refinement",
  artifacts: MOCK_AGENT_ARTIFACTS,
  split_round: 0,
  interview_complete: true,
};
