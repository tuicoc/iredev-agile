import {
  ClipboardList,
  FileCheck2,
  FileText,
  GitBranch,
  MessageSquareText,
  ShieldAlert,
  Target,
} from "lucide-react";
import {
  asArray,
  EmptyState,
  MetaPill,
  Section,
  Tag,
  text,
} from "./viewUtils";

function typeTone(type) {
  if (type === "functional") return "warm";
  if (type === "non_functional") return "blue";
  if (type === "out_of_scope" || type === "constraint") return "purple";
  if (type === "system") return "green";
  return "default";
}

function statusTone(status) {
  if (["confirmed", "answered", "ready", "covered", "supports"].includes(status)) {
    return "green";
  }
  if (["excluded", "skipped", "gap", "weakens"].includes(status)) return "amber";
  if (["unclear", "partial", "qualifies"].includes(status)) return "blue";
  return "default";
}

function verdictTone(verdict) {
  if (verdict === "requirement_seed") return "green";
  if (verdict === "supporting_evidence") return "blue";
  if (verdict === "non_product") return "amber";
  return "default";
}

function confidenceTone(confidence) {
  if (confidence === "confirmed") return "green";
  if (confidence === "inferred") return "amber";
  return "default";
}

function getRequirementItems(data) {
  if (Array.isArray(data?.items)) return data.items;
  if (Array.isArray(data?.requirements)) return data.requirements;
  if (Array.isArray(data?.requirements_identified)) return data.requirements_identified;
  return [];
}

function getInterviewItems(data) {
  if (Array.isArray(data?.items)) return data.items;
  if (Array.isArray(data?.elicitation_items)) return data.elicitation_items;
  if (Array.isArray(data?.requirements_identified)) return data.requirements_identified;
  return [];
}

function requirementTypeCounts(requirements) {
  return requirements.reduce((acc, req) => {
    const type = req.type || req.req_type || "unknown";
    acc[type] = (acc[type] || 0) + 1;
    return acc;
  }, {});
}

function traceRefMeaning(ref) {
  const value = String(ref || "");
  let match = value.match(/^(EL-\d+)-S(\d+)$/i);
  if (match) return `${match[1]} signal evidence ${match[2]}`;

  match = value.match(/^(EL-\d+)-T(\d+)$/i);
  if (match) return `${match[1]} talk turn ${match[2]}`;

  match = value.match(/^(EL-\d+)-ASM(\d+)$/i);
  if (match) return `${match[1]} assumption evidence ${match[2]}`;

  if (/^ASM-\d+$/i.test(value)) return "product vision assumption";
  if (/^CONCERN-\d+$/i.test(value)) return "product vision concern";
  if (/^OOS-\d+$/i.test(value)) return "product vision scope boundary";
  if (/ProductVision\.scope/i.test(value)) return "product vision scope";
  return "trace source";
}

function traceRefLabel(ref) {
  const value = String(ref || "");
  if (/^EL-\d+-S\d+$/i.test(value)) return `${value}: signal`;
  if (/^EL-\d+-T\d+$/i.test(value)) return `${value}: talk`;
  if (/^EL-\d+-ASM\d+$/i.test(value)) return `${value}: assumption`;
  if (/^ASM-\d+$/i.test(value)) return `${value}: vision assumption`;
  if (/^CONCERN-\d+$/i.test(value)) return `${value}: vision concern`;
  if (/^OOS-\d+$/i.test(value)) return `${value}: scope`;
  if (/ProductVision\.scope/i.test(value)) return `${value}: scope`;
  return value;
}

function DetailLine({ label, value }) {
  if (!value) return null;

  return (
    <div className="grid gap-0.5 sm:grid-cols-[74px_1fr]">
      <dt className="text-[10px] font-semibold text-[#A89C91]">{label}</dt>
      <dd className="text-[10.5px] leading-relaxed text-[#4A4038]">{value}</dd>
    </div>
  );
}

function TraceRefTags({ refs }) {
  const rows = asArray(refs);
  if (!rows.length) return null;

  return (
    <div className="flex flex-wrap gap-1.5">
      {rows.map((ref) => (
        <Tag key={ref} tone="blue" title={traceRefMeaning(ref)}>
          {traceRefLabel(ref)}
        </Tag>
      ))}
    </div>
  );
}

function ChatBubble({ side, speaker, topic, content, closeRule }) {
  const isLeft = side === "left";

  return (
    <div className={`flex ${isLeft ? "justify-start" : "justify-end"}`}>
      <div
        className={`max-w-[82%] rounded-2xl border px-3 py-2.5 ${
          isLeft
            ? "rounded-tl-sm border-[#E2D6C5] bg-[#F6F1E8]"
            : "rounded-tr-sm border-[#D8CBBB] bg-[#ECE3D6]"
        }`}
      >
        <div className="mb-1 flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] font-semibold text-[#211914]">{speaker}</span>
          {topic && <span className="text-[9.5px] text-[#A89C91]">{topic}</span>}
        </div>
        <p className="whitespace-pre-wrap text-[11px] leading-relaxed text-[#302822]">
          {content || "-"}
        </p>
        {closeRule && (
          <div className="mt-1.5 text-[9.5px] leading-relaxed text-[#776B60]">
            Close when: {closeRule}
          </div>
        )}
      </div>
    </div>
  );
}

function CompactList({ items, emptyLabel }) {
  const rows = asArray(items);
  if (!rows.length) return <EmptyState label={emptyLabel} />;

  return (
    <ul className="space-y-1.5">
      {rows.map((item, index) => (
        <li
          key={index}
          className="rounded-lg border border-[#E9DFD1] bg-[#F6F1E8] px-2.5 py-2
                     text-[10.5px] leading-relaxed text-[#4A4038]"
        >
          {text(item)}
        </li>
      ))}
    </ul>
  );
}

function CoverageList({ coverage, planned }) {
  const rows = asArray(coverage);
  const plannedRows = asArray(planned);
  if (!rows.length && !plannedRows.length) return null;

  return (
    <details className="border-t border-[#E9DFD1] px-3 py-2 text-[10.5px] text-[#776B60]">
      <summary className="cursor-pointer font-semibold text-[#4A4038]">
        Coverage ({rows.length + plannedRows.length})
      </summary>
      <div className="mt-2 space-y-2">
        {plannedRows.length > 0 && (
          <div>
            <div className="mb-1.5 text-[10px] font-semibold text-[#776B60]">
              Planned
            </div>
            <ul className="space-y-1">
              {plannedRows.map((entry, index) => (
                <li key={index} className="flex gap-2 text-[10.5px] leading-relaxed text-[#4A4038]">
                  <span className="font-mono text-[#B86F50]">-</span>
                  <span>{text(entry)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {rows.map((entry, index) => (
          <div key={index} className="rounded-lg border border-[#E9DFD1] bg-[#F6F1E8] px-2.5 py-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <Tag tone={statusTone(entry.status)}>{entry.status}</Tag>
              <span className="font-medium text-[#4A4038]">{entry.point}</span>
            </div>
            {entry.evidence && (
              <p className="mt-1 text-[10px] leading-relaxed text-[#776B60]">
                {entry.evidence}
              </p>
            )}
          </div>
        ))}
      </div>
    </details>
  );
}

function AssumptionEvidenceList({ evidence }) {
  const rows = asArray(evidence);
  if (!rows.length) return null;

  return (
    <details className="border-t border-[#E9DFD1] px-3 py-2 text-[10.5px] text-[#776B60]">
      <summary className="cursor-pointer font-semibold text-[#4A4038]">
        Assumption Evidence ({rows.length})
      </summary>
      <div className="mt-2 space-y-2">
        {rows.map((entry, index) => (
          <div key={index} className="rounded-lg border border-[#E9DFD1] bg-[#FFFDF8] px-2.5 py-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="font-mono text-[10px] text-[#B86F50]">
                {entry.vision_ref}
              </span>
              <Tag tone={statusTone(entry.stance)}>{entry.stance}</Tag>
            </div>
            {entry.evidence && (
              <p className="mt-1 text-[10.5px] leading-relaxed text-[#4A4038]">
                {entry.evidence}
              </p>
            )}
            {entry.implication && (
              <p className="mt-1 text-[10px] leading-relaxed text-[#776B60]">
                Implication: {entry.implication}
              </p>
            )}
          </div>
        ))}
      </div>
    </details>
  );
}

function InterviewItem({ item, index }) {
  const turns = asArray(item.talk);
  const refs = asArray(item.vision_refs);
  const coveragePoints = asArray(item.coverage_points);
  const stakeholder = item.perspective || item.role || item.stakeholder || "Stakeholder";
  const topic = item.decision_target || item.item || `EL-${index + 1}`;
  const closeRule = item.close_when || item.close || item.rule;

  return (
    <article className="rounded-lg border border-[#E2D6C5] bg-[#FFFDF8]">
      <div className="border-b border-[#E9DFD1] bg-[#FCF8F1] px-3 py-2.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-mono text-[10px] text-[#B86F50]">
            {item.id || `EL-${index + 1}`}
          </span>
          {item.item && <Tag>{item.item}</Tag>}
          <Tag tone="warm">{stakeholder}</Tag>
          <Tag tone={statusTone(item.status)}>{item.status}</Tag>
          {refs.map((ref) => (
            <Tag key={ref} tone="blue">{ref}</Tag>
          ))}
        </div>
        <p className="mt-1.5 text-[12px] font-semibold leading-relaxed text-[#211914]">
          {topic}
        </p>
        {item.context && (
          <p className="mt-1 text-[10.5px] leading-relaxed text-[#776B60]">
            {item.context}
          </p>
        )}
      </div>

      <div className="space-y-3 px-3 py-3">
        {turns.length > 0 ? (
          turns.map((turn, turnIndex) => (
            <div key={turnIndex} className="space-y-2">
              <ChatBubble
                side="left"
                speaker="Interviewer Agent"
                topic={topic}
                closeRule={closeRule}
                content={turn.question}
              />
              <ChatBubble
                side="right"
                speaker={`${stakeholder} (EndUser Agent)`}
                topic={topic}
                closeRule={closeRule}
                content={turn.answer}
              />
            </div>
          ))
        ) : item.answer ? (
          <pre className="whitespace-pre-wrap text-[11px] leading-relaxed text-[#4A4038] font-sans">
            {item.answer}
          </pre>
        ) : (
          <EmptyState label="No dialogue captured for this agenda item." />
        )}

        {item.rule && (
          <p className="rounded-lg border border-[#E9DFD1] bg-[#F6F1E8] px-3 py-2
                        text-[10.5px] leading-relaxed text-[#4A4038]">
            <span className="font-semibold">Closure rule: </span>
            {item.rule}
          </p>
        )}
      </div>

      <CoverageList coverage={item.coverage} planned={coveragePoints} />

      {(asArray(item.signals).length > 0 || asArray(item.gaps).length > 0) && (
        <details className="border-t border-[#E9DFD1] px-3 py-2 text-[10.5px] text-[#776B60]">
          <summary className="cursor-pointer font-semibold text-[#4A4038]">
            Signals and gaps
          </summary>
          <div className="mt-2 space-y-3">
            {asArray(item.signals).length > 0 && (
              <div>
                <div className="mb-1.5 text-[10px] font-semibold text-[#776B60]">
                  Signals
                </div>
                <CompactList items={item.signals} emptyLabel="No signals found." />
              </div>
            )}
            {asArray(item.gaps).length > 0 && (
              <div>
                <div className="mb-1.5 text-[10px] font-semibold text-[#776B60]">
                  Gaps
                </div>
                <CompactList items={item.gaps} emptyLabel="No gaps found." />
              </div>
            )}
          </div>
        </details>
      )}

      <AssumptionEvidenceList evidence={item.assumption_evidence} />
    </article>
  );
}

function RequirementCard({ requirement, index }) {
  const acceptanceCriteria = asArray(requirement.acceptance_criteria);
  const traceRefs = asArray(requirement.trace_refs);
  const reqType = requirement.type || requirement.req_type;
  const reqId = requirement.id || requirement.req_id || `REQ-${index + 1}`;
  const status = String(requirement.status || "").trim();
  const confidence = String(requirement.confidence || "").trim();
  const showStatus = status && !["confirmed", "ready"].includes(status.toLowerCase());
  const showConfidence = confidence.toLowerCase() === "inferred";
  const details = [
    ["Outcome", requirement.observable_outcome],
    ["Why", requirement.rationale],
    ["Condition", requirement.operating_condition],
    ["Trigger", requirement.trigger_event],
    ["Object", requirement.product_object],
    ["Participation", requirement.participation_structure],
  ].filter(([, value]) => value);

  return (
    <article className="rounded-lg border border-[#E2D6C5] bg-[#FFFDF8]">
      <div className="border-b border-[#E9DFD1] bg-[#FCF8F1] px-3 py-2.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-mono text-[10px] text-[#B86F50]">{reqId}</span>
          {reqType && <Tag tone={typeTone(reqType)}>{String(reqType).replace(/_/g, " ")}</Tag>}
          {requirement.stakeholder && <Tag>{requirement.stakeholder}</Tag>}
          {showStatus && <Tag tone={statusTone(status)}>{status}</Tag>}
          {showConfidence && <Tag tone={confidenceTone(confidence)}>{confidence}</Tag>}
        </div>
        <p className="mt-2 text-[12px] font-semibold leading-relaxed text-[#211914]">
          {requirement.statement || requirement.description || requirement.question}
        </p>
      </div>

      <div className="space-y-3 px-3 py-2.5">
        <TraceRefTags refs={traceRefs} />

        {details.length > 0 && (
          <dl className="space-y-1.5">
            {details.map(([label, value]) => (
              <DetailLine key={label} label={label} value={value} />
            ))}
          </dl>
        )}
      </div>

      {acceptanceCriteria.length > 0 && (
        <details className="border-t border-[#E9DFD1] px-3 py-2 text-[10.5px] text-[#776B60]">
          <summary className="cursor-pointer font-semibold text-[#4A4038]">
            Acceptance criteria ({acceptanceCriteria.length})
          </summary>
          <ul className="mt-2 space-y-1">
            {acceptanceCriteria.map((criterion, criterionIndex) => (
              <li key={criterionIndex} className="flex gap-2">
                <span>-</span>
                <span>{text(criterion)}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}

function ConflictList({ conflicts }) {
  if (!conflicts.length) return null;

  return (
    <Section title="Conflicts Require Resolution" icon={ShieldAlert}>
      <div className="space-y-2">
        {conflicts.map((conflict, index) => (
          <article
            key={conflict.id || index}
            className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5"
          >
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="font-mono text-[10px] text-amber-800">
                {conflict.id || `CF-${index + 1}`}
              </span>
              <Tag tone="amber">{conflict.kind}</Tag>
              <span className="text-[10.5px] text-amber-900">
                {text(conflict.left)} vs {text(conflict.right)}
              </span>
            </div>
            {conflict.scope && (
              <p className="mt-1 text-[10px] leading-relaxed text-amber-800">
                Scope: {conflict.scope}
              </p>
            )}
            {conflict.issue && (
              <p className="mt-1.5 text-[10.5px] leading-relaxed text-amber-900">
                {conflict.issue}
              </p>
            )}
            {asArray(conflict.paths).length > 0 && (
              <p className="mt-1 text-[10px] leading-relaxed text-amber-800">
                Paths: {asArray(conflict.paths).join("; ")}
              </p>
            )}
          </article>
        ))}
      </div>
    </Section>
  );
}

function ExtractionWalks({ walks }) {
  const entries = Object.entries(walks || {});
  if (!entries.length) return null;

  return (
    <Section title="Extraction Walks" icon={GitBranch}>
      <div className="space-y-3">
        {entries.map(([recordId, rows]) => (
          <article key={recordId} className="rounded-lg border border-[#E2D6C5] bg-[#FFFDF8]">
            <div className="border-b border-[#E9DFD1] bg-[#FCF8F1] px-3 py-2 text-[11px] font-semibold text-[#211914]">
              {recordId}
            </div>
            <div className="divide-y divide-[#E9DFD1]">
              {asArray(rows).map((entry, index) => (
                <div key={`${recordId}-${entry.signal_id || index}`} className="px-3 py-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-mono text-[10px] text-[#B86F50]">
                      {entry.signal_id}
                    </span>
                    <Tag tone={verdictTone(entry.verdict)}>
                      {String(entry.verdict || "").replace(/_/g, " ")}
                    </Tag>
                  </div>
                  {entry.reason && (
                    <p className="mt-1 text-[10.5px] leading-relaxed text-[#776B60]">
                      {entry.reason}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </article>
        ))}
      </div>
    </Section>
  );
}

export function TranscriptView({ data }) {
  const conversation = asArray(data?.conversation);
  const itemTurns = getInterviewItems(data).flatMap((item) =>
    asArray(item.talk).flatMap((turn) => [
      { role: "interviewer", content: turn.question },
      { role: item.perspective || item.role || "stakeholder", content: turn.answer },
    ]),
  );
  const turns = conversation.length ? conversation : itemTurns;

  if (!turns.length) {
    return (
      <div className="h-full overflow-auto bg-[#FFFDF8] p-4">
        <EmptyState label="No conversation recorded." />
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto bg-[#FFFDF8]">
      <Section title="Transcript" icon={MessageSquareText}>
        <div className="space-y-3">
          {turns.map((turn, index) => (
            <ChatBubble
              key={index}
              side={turn.role === "interviewer" ? "left" : "right"}
              speaker={turn.role === "interviewer" ? "Interviewer Agent" : text(turn.role)}
              content={turn.content}
            />
          ))}
        </div>
      </Section>
    </div>
  );
}

export function RequirementsView({ data }) {
  const requirements = getRequirementItems(data);
  const conflicts = asArray(data?.conflicts);
  const gaps = asArray(data?.gaps || data?.gaps_identified);
  const byType = data?.by_type || requirementTypeCounts(requirements);

  return (
    <div className="h-full overflow-auto bg-[#FFFDF8]">
      <div className="p-4 space-y-3">
        <div className="rounded-lg border border-[#E2D6C5] bg-[#FBF7F0] p-3">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-[#211914]">
            <FileCheck2 size={14} className="text-[#B86F50]" />
            Requirement List
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <MetaPill label="Requirements" value={data?.total_requirements ?? requirements.length} />
            {Object.entries(byType).map(([key, value]) => (
              <MetaPill key={key} label={key.replace(/_/g, " ")} value={value} />
            ))}
            <MetaPill label="Conflicts" value={conflicts.length} tone={conflicts.length ? "amber" : "green"} />
            <MetaPill label="Gaps" value={gaps.length} tone={gaps.length ? "amber" : "default"} />
          </div>
        </div>
      </div>

      <Section title="Requirements" icon={ClipboardList}>
        {requirements.length ? (
          <div className="grid gap-3">
            {requirements.map((requirement, index) => (
              <RequirementCard
                key={requirement.id || requirement.req_id || index}
                requirement={requirement}
                index={index}
              />
            ))}
          </div>
        ) : (
          <EmptyState label="No requirements extracted yet." />
        )}
      </Section>

      <ConflictList conflicts={conflicts} />

      {gaps.length > 0 && (
        <Section title="Gaps" icon={Target}>
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
            <ul className="space-y-1.5 text-[10.5px] leading-relaxed text-amber-900">
              {gaps.map((gap, index) => (
                <li key={index} className="flex gap-2">
                  <span>-</span>
                  <span>{text(gap)}</span>
                </li>
              ))}
            </ul>
          </div>
        </Section>
      )}

      <ExtractionWalks walks={data?.extraction_walks} />

      {data?.notes && (
        <Section title="Notes" icon={FileText}>
          <pre
            className="whitespace-pre-wrap rounded-lg border border-[#E2D6C5] bg-[#F6F1E8]
                       p-3 text-[10.5px] leading-relaxed text-[#776B60] font-sans"
          >
            {data.notes}
          </pre>
        </Section>
      )}
    </div>
  );
}

export function InterviewRecordRequirementsView({ data }) {
  const items = getInterviewItems(data);
  const answeredCount = items.filter((item) => item.status === "answered" || item.answer).length;
  const signalCount = items.reduce((count, item) => count + asArray(item.signals).length, 0);
  const gapCount = items.reduce((count, item) => count + asArray(item.gaps).length, 0);

  return (
    <div className="h-full overflow-auto bg-[#FFFDF8]">
      <div className="p-4 space-y-3">
        <div className="rounded-lg border border-[#E2D6C5] bg-[#FBF7F0] p-3">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-[#211914]">
            <MessageSquareText size={14} className="text-[#B86F50]" />
            Interview Record
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <MetaPill label="Items" value={data?.total_items ?? items.length} />
            <MetaPill label="Answered" value={answeredCount} tone="green" />
            <MetaPill label="Signals" value={signalCount} />
            <MetaPill label="Gaps" value={gapCount} tone={gapCount ? "amber" : "green"} />
          </div>
        </div>
      </div>

      <Section title="Conversation By Agenda Item" icon={ClipboardList}>
        {items.length ? (
          <div className="grid gap-3">
            {items.map((item, index) => (
              <InterviewItem key={item.id || item.item || index} item={item} index={index} />
            ))}
          </div>
        ) : (
          <EmptyState label="No interview records found." />
        )}
      </Section>

      {data?.notes && (
        <Section title="Notes" icon={FileText}>
          <pre
            className="whitespace-pre-wrap rounded-lg border border-[#E2D6C5] bg-[#F6F1E8]
                       p-3 text-[10.5px] leading-relaxed text-[#776B60] font-sans"
          >
            {data.notes}
          </pre>
        </Section>
      )}
    </div>
  );
}
