import {
  ClipboardList,
  FileText,
  GitBranch,
  MessageSquareText,
} from "lucide-react";
import {
  asArray,
  EmptyState,
  MetaPill,
  Section,
  Tag,
  text,
} from "./viewUtils";

function countBy(items, key) {
  return items.reduce((acc, item) => {
    const value = item?.[key] || "unknown";
    acc[value] = (acc[value] || 0) + 1;
    return acc;
  }, {});
}

function kindTone(kind) {
  if (kind === "conflict") return "amber";
  if (kind === "concern") return "blue";
  if (kind === "need") return "green";
  return "default";
}

function aspectTone(aspect) {
  if (String(aspect || "").includes("quality")) return "blue";
  if (String(aspect || "").includes("conflict")) return "amber";
  if (String(aspect || "").includes("rule")) return "warm";
  return "default";
}

function LabeledText({ label, children, muted = false }) {
  if (!children) return null;

  return (
    <p className={`text-[10.5px] leading-relaxed ${muted ? "text-[#776B60]" : "text-[#4A4038]"}`}>
      <span className="font-semibold text-[#776B60]">{label}: </span>
      {children}
    </p>
  );
}

function AgendaItemCard({ item, index }) {
  const topic = [item.entity, item.step].filter(Boolean).join(" / ");

  return (
    <article className="rounded-xl border border-[#E2D6C5] bg-[#FFFDF8]">
      <div className="flex flex-wrap items-start gap-3 px-3 py-2.5 border-b border-[#E9DFD1] bg-[#FCF8F1]">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-[10px] text-[#B86F50]">
              {item.id || item.item_id || `agenda-${index + 1}`}
            </span>
            <Tag tone={kindTone(item.kind)}>{item.kind}</Tag>
            <Tag tone={aspectTone(item.aspect)}>
              {String(item.aspect || "").replace(/_/g, " ")}
            </Tag>
            {item.trap && <Tag>{String(item.trap).replace(/_/g, " ")}</Tag>}
          </div>
          <div className="mt-1 text-[12px] font-semibold text-[#211914]">
            {topic || "Agenda item"}
          </div>
        </div>
        <div className="rounded-full bg-[#ECE3D6] px-2.5 py-1 text-[10px] font-medium text-[#4A4038]">
          {item.role || "Stakeholder"}
        </div>
      </div>

      <div className="px-3 py-2.5 space-y-1.5">
        <LabeledText label="Context">{item.baseline || item.scene}</LabeledText>
        {item.baseline && item.scene && (
          <LabeledText label="Scene" muted>{item.scene}</LabeledText>
        )}
        <LabeledText label="Probe">{item.probe || item.elicitation_goal}</LabeledText>
        <LabeledText label="Gap">{item.gap}</LabeledText>
        <LabeledText label="Done when">{item.close}</LabeledText>
        {item.risk && (
          <LabeledText label="Risk" muted>{item.risk}</LabeledText>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-1.5 px-3 py-2 border-t border-[#E9DFD1] text-[10px] text-[#A89C91]">
        <span>source: {text(item.source || item.source_ref || item.entry)}</span>
        {item.peer && <span>peer: {item.peer}</span>}
        {item.concern_ref && <span>concern: {item.concern_ref}</span>}
        {item.concern_theme && <span>{item.concern_theme}</span>}
      </div>
    </article>
  );
}

export function ElicitationAgendaView({ data }) {
  const items = asArray(data?.items || data?.agenda_items || data?.elicitation_items);
  const summary = data?.summary || {};
  const kinds = countBy(items, "kind");
  const aspects = countBy(items, "aspect");
  const roles = Object.keys(countBy(items, "role")).length;

  return (
    <div className="h-full overflow-auto bg-[#FFFDF8]">
      <div className="p-4 space-y-3">
        <div className="rounded-xl border border-[#E2D6C5] bg-[#FBF7F0] p-3">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-[#211914]">
            <ClipboardList size={14} className="text-[#B86F50]" />
            Elicitation Agenda
          </div>
          {data?.notes && (
            <p className="mt-2 text-[11px] leading-relaxed text-[#776B60]">
              {data.notes}
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-1.5">
            <MetaPill label="Items" value={summary.total ?? data?.total_items ?? items.length} />
            <MetaPill label="Needs" value={summary.needs ?? kinds.need} tone="green" />
            <MetaPill label="Conflicts" value={summary.conflicts ?? kinds.conflict} tone="amber" />
            <MetaPill label="Concerns" value={summary.concerns ?? kinds.concern} tone="blue" />
            <MetaPill label="Roles" value={roles} />
          </div>
        </div>
      </div>

      {(data?.flow || Object.keys(aspects).length > 0) && (
        <Section title="Agenda Spine" icon={GitBranch}>
          <div className="rounded-xl border border-[#E2D6C5] bg-[#FFFDF8] p-3">
            {data?.flow && (
              <div className="text-[11px] leading-relaxed text-[#4A4038]">
                {text(data.flow)}
              </div>
            )}
            {Object.keys(aspects).length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {Object.entries(aspects).map(([aspect, count]) => (
                  <MetaPill
                    key={aspect}
                    label={aspect.replace(/_/g, " ")}
                    value={count}
                  />
                ))}
              </div>
            )}
          </div>
        </Section>
      )}

      <Section title="Interview Items" icon={MessageSquareText}>
        {items.length ? (
          <div className="grid gap-3">
            {items.map((item, index) => (
              <AgendaItemCard key={item.id || item.item_id || index} item={item} index={index} />
            ))}
          </div>
        ) : (
          <EmptyState label="No elicitation agenda items found." />
        )}
      </Section>

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
