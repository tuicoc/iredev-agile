import {
  ClipboardList,
  FileCheck2,
  FileText,
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
  return "default";
}

function priorityTone(priority) {
  if (priority === "high") return "red";
  if (priority === "medium") return "amber";
  if (priority === "low") return "green";
  return "default";
}

function statusTone(status) {
  if (status === "confirmed" || status === "answered" || status === "ready") {
    return "green";
  }
  if (status === "excluded" || status === "skipped") return "amber";
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

function metaText(item) {
  return [item.entity, item.step, item.aspect].filter(Boolean).join(" / ");
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
            Discussing: {closeRule}
          </div>
        )}
      </div>
    </div>
  );
}

function InterviewItem({ item, index }) {
  const turns = asArray(item.talk);
  const topic = metaText(item);
  const stakeholder = item.role || item.stakeholder || "Stakeholder";

  return (
    <article className="rounded-xl border border-[#E2D6C5] bg-[#FFFDF8]">
      <div className="px-3 py-2.5 border-b border-[#E9DFD1] bg-[#FCF8F1]">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-mono text-[10px] text-[#B86F50]">
            {item.id || item.item || `EL-${index + 1}`}
          </span>
          <Tag tone={typeTone(item.kind)}>{item.kind}</Tag>
          <Tag>{String(item.trap || "").replace(/_/g, " ")}</Tag>
          <Tag tone={statusTone(item.status)}>{item.status}</Tag>
          <span className="ml-auto text-[10px] text-[#A89C91]">{stakeholder}</span>
        </div>
        <div className="mt-1 text-[12px] font-semibold text-[#211914]">
          {topic || "Interview topic"}
        </div>
        {(item.risk || item.close || item.rule) && (
          <p className="mt-1 text-[10.5px] leading-relaxed text-[#776B60]">
            {item.rule || item.close || item.risk}
          </p>
        )}
      </div>

      <div className="space-y-2 px-3 py-3">
        {turns.length > 0 ? (
          turns.map((turn, turnIndex) => (
            <div key={turnIndex} className="space-y-2">
              <ChatBubble
                side="left"
                speaker="Interviewer Agent"
                topic={topic}
                closeRule={item.close}
                content={turn.question}
              />
              <ChatBubble
                side="right"
                speaker={`${stakeholder} (Enduser Agent)`}
                topic={topic}
                closeRule={item.close}
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
      </div>

      {(asArray(item.signals).length > 0 || item.source || item.concern_ref) && (
        <details className="border-t border-[#E9DFD1] px-3 py-2 text-[10.5px] text-[#776B60]">
          <summary className="cursor-pointer font-semibold text-[#4A4038]">
            Evidence and trace
          </summary>
          <div className="mt-2 space-y-1.5">
            {item.source && <p>Source: {item.source}</p>}
            {item.concern_ref && (
              <p>
                Concern: {item.concern_ref}
                {item.concern_theme ? ` - ${item.concern_theme}` : ""}
              </p>
            )}
            {asArray(item.signals).length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {asArray(item.signals).map((signal, signalIndex) => (
                  <Tag key={signalIndex}>{signal}</Tag>
                ))}
              </div>
            )}
          </div>
        </details>
      )}
    </article>
  );
}

function RequirementCard({ requirement, index }) {
  const acceptanceCriteria = asArray(requirement.acceptance_criteria);
  const reqType = requirement.type || requirement.req_type;
  const reqId = requirement.id || requirement.req_id || `REQ-${index + 1}`;
  const topic = [requirement.entity, requirement.step, requirement.aspect]
    .filter(Boolean)
    .join(" / ");

  return (
    <article className="rounded-xl border border-[#E2D6C5] bg-[#FFFDF8]">
      <div className="px-3 py-2.5 border-b border-[#E9DFD1] bg-[#FCF8F1]">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-mono text-[10px] text-[#B86F50]">{reqId}</span>
          <Tag tone={typeTone(reqType)}>{String(reqType || "").replace(/_/g, " ")}</Tag>
          <Tag tone={priorityTone(requirement.priority)}>{requirement.priority}</Tag>
          <Tag tone={statusTone(requirement.status)}>{requirement.status}</Tag>
          {requirement.requires_threshold && <Tag tone="amber">threshold needed</Tag>}
        </div>
        <p className="mt-2 text-[12px] font-semibold leading-relaxed text-[#211914]">
          {requirement.statement || requirement.description || requirement.question}
        </p>
        {topic && (
          <div className="mt-1 text-[10px] text-[#A89C91]">{topic}</div>
        )}
      </div>

      <div className="px-3 py-2.5 space-y-1.5">
        {requirement.rationale && (
          <p className="text-[10.5px] leading-relaxed text-[#776B60]">
            <span className="font-semibold text-[#4A4038]">Why: </span>
            {requirement.rationale}
          </p>
        )}
        <div className="flex flex-wrap gap-1.5 text-[10px] text-[#A89C91]">
          {requirement.stakeholder && <span>stakeholder: {requirement.stakeholder}</span>}
          {requirement.category && <span>category: {requirement.category}</span>}
          {requirement.concern_theme && <span>concern: {requirement.concern_theme}</span>}
          {(requirement.source || requirement.origin) && (
            <span>source: {requirement.source || requirement.origin}</span>
          )}
        </div>
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
            className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5"
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

export function TranscriptView({ data }) {
  const conversation = asArray(data?.conversation);

  if (!conversation.length) {
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
          {conversation.map((turn, index) => (
            <ChatBubble
              key={index}
              side={turn.role === "interviewer" ? "left" : "right"}
              speaker={turn.role === "interviewer" ? "Interviewer Agent" : "Enduser Agent"}
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
  const byType = data?.by_type || requirements.reduce((acc, req) => {
    const type = req.type || req.req_type || "unknown";
    acc[type] = (acc[type] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="h-full overflow-auto bg-[#FFFDF8]">
      <div className="p-4 space-y-3">
        <div className="rounded-xl border border-[#E2D6C5] bg-[#FBF7F0] p-3">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-[#211914]">
            <FileCheck2 size={14} className="text-[#B86F50]" />
            Requirement List
          </div>
          {data?.notes && (
            <p className="mt-2 text-[11px] leading-relaxed text-[#776B60]">
              {data.notes}
            </p>
          )}
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
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-3">
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

      <Section title="Notes" icon={FileText}>
        {data?.notes ? (
          <pre
            className="whitespace-pre-wrap rounded-xl border border-[#E2D6C5] bg-[#F6F1E8]
                       p-3 text-[10.5px] leading-relaxed text-[#776B60] font-sans"
          >
            {data.notes}
          </pre>
        ) : (
          <EmptyState label="No notes found." />
        )}
      </Section>
    </div>
  );
}

export function InterviewRecordRequirementsView({ data }) {
  const items = getInterviewItems(data);
  const answeredCount = items.filter((item) => item.status === "answered" || item.answer).length;

  return (
    <div className="h-full overflow-auto bg-[#FFFDF8]">
      <div className="p-4 space-y-3">
        <div className="rounded-xl border border-[#E2D6C5] bg-[#FBF7F0] p-3">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-[#211914]">
            <MessageSquareText size={14} className="text-[#B86F50]" />
            Interview Record
          </div>
          {data?.project_description && (
            <p className="mt-2 text-[11px] leading-relaxed text-[#776B60]">
              {data.project_description}
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-1.5">
            <MetaPill label="Items" value={data?.total_items ?? items.length} />
            <MetaPill label="Answered" value={answeredCount} tone="green" />
            <MetaPill label="Pending" value={Math.max(items.length - answeredCount, 0)} tone="amber" />
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

      <Section title="Notes" icon={FileText}>
        {data?.notes || data?.elicitation_notes ? (
          <pre
            className="whitespace-pre-wrap rounded-xl border border-[#E2D6C5] bg-[#F6F1E8]
                       p-3 text-[10.5px] leading-relaxed text-[#776B60] font-sans"
          >
            {data.notes || data.elicitation_notes}
          </pre>
        ) : (
          <EmptyState label="No elicitation notes found." />
        )}
      </Section>
    </div>
  );
}
