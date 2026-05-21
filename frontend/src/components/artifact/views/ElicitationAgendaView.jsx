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

function countBy(items, readValue) {
  return items.reduce((acc, item) => {
    const value = readValue(item) || "unknown";
    acc[value] = (acc[value] || 0) + 1;
    return acc;
  }, {});
}

function InfoRow({ label, value }) {
  if (!value) return null;

  return (
    <div className="grid gap-0.5 sm:grid-cols-[88px_1fr]">
      <dt className="text-[10px] font-semibold text-[#A89C91]">
        {label}
      </dt>
      <dd className="text-[10.5px] leading-relaxed text-[#4A4038]">
        {value}
      </dd>
    </div>
  );
}

function NumberedList({ items, emptyLabel }) {
  const rows = asArray(items);
  if (!rows.length) return <EmptyState label={emptyLabel} />;

  return (
    <ol className="space-y-1.5">
      {rows.map((item, index) => (
        <li key={index} className="flex gap-2 text-[10.5px] leading-relaxed text-[#4A4038]">
          <span className="font-mono text-[9.5px] text-[#B86F50]">{index + 1}.</span>
          <span>{text(item)}</span>
        </li>
      ))}
    </ol>
  );
}

function AgendaItemCard({ item, index }) {
  const refs = asArray(item.vision_refs);
  const coveragePoints = asArray(item.coverage_points);
  const perspective = item.perspective || item.role || "Stakeholder";
  const title = item.decision_target || item.elicitation_goal || "Evidence job";
  const status = item.status && item.status !== "planned" ? item.status : null;

  return (
    <article className="rounded-lg border border-[#E2D6C5] bg-[#FFFDF8]">
      <div className="border-b border-[#E9DFD1] bg-[#FCF8F1] px-3 py-2.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-mono text-[10px] text-[#B86F50]">
            {item.id || item.item_id || `IT-${index + 1}`}
          </span>
          <Tag tone="warm">{perspective}</Tag>
          {status && <Tag>{status}</Tag>}
        </div>
        <p className="mt-1.5 text-[12px] font-semibold leading-relaxed text-[#211914]">
          {title}
        </p>
      </div>

      <div className="space-y-2.5 px-3 py-2.5">
        <dl className="space-y-2">
          <InfoRow label="Context" value={item.context || item.scene || item.baseline} />
          <InfoRow label="Question" value={item.seed_question || item.probe} />
          <InfoRow label="Close" value={item.close_when || item.close} />
          <InfoRow label="Merge" value={item.merge_anchor} />
        </dl>

        {refs.length > 0 && (
          <p className="text-[10px] leading-relaxed text-[#776B60]">
            <span className="font-semibold text-[#4A4038]">Refs: </span>
            {refs.join(", ")}
          </p>
        )}

        <div>
          <div className="mb-1.5 text-[10.5px] font-semibold text-[#776B60]">
            Coverage
          </div>
          <NumberedList items={coveragePoints} emptyLabel="No coverage points found." />
        </div>

        {item.notes && (
          <p className="text-[10.5px] leading-relaxed text-[#776B60]">
            <span className="font-semibold text-[#4A4038]">Notes: </span>
            {item.notes}
          </p>
        )}
      </div>
    </article>
  );
}

function AgendaAudit({ notes }) {
  const [audit, commentary] = String(notes).split("--- Reviewer commentary ---");
  return (
    <div className="space-y-3">
      <pre
        className="whitespace-pre-wrap rounded-lg border border-[#E2D6C5] bg-[#F6F1E8]
                   p-3 text-[10.5px] leading-relaxed text-[#776B60] font-sans"
      >
        {audit.trim()}
      </pre>
      {commentary && (
        <pre
          className="whitespace-pre-wrap rounded-lg border border-[#E2D6C5] bg-[#FFFDF8]
                     p-3 text-[10.5px] leading-relaxed text-[#776B60] font-sans"
        >
          {commentary.trim()}
        </pre>
      )}
    </div>
  );
}

export function ElicitationAgendaView({ data }) {
  const items = asArray(data?.items || data?.agenda_items || data?.elicitation_items);
  const byPerspective = countBy(items, (item) => item.perspective || item.role);
  const visionRefCount = new Set(items.flatMap((item) => asArray(item.vision_refs))).size;
  const coverageCount = items.reduce(
    (total, item) => total + asArray(item.coverage_points).length,
    0,
  );

  return (
    <div className="h-full overflow-auto bg-[#FFFDF8]">
      <div className="p-4 space-y-3">
        <div className="rounded-lg border border-[#E2D6C5] bg-[#FBF7F0] p-3">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-[#211914]">
            <ClipboardList size={14} className="text-[#B86F50]" />
            Elicitation Agenda
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-[#776B60]">
            {items.length
              ? "Agenda items are evidence jobs: one perspective, one current scene, one decision target."
              : "No agenda items found."}
          </p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <MetaPill label="Items" value={data?.total_items ?? items.length} />
            <MetaPill label="Perspectives" value={Object.keys(byPerspective).length} />
            <MetaPill label="Vision refs" value={visionRefCount} />
            <MetaPill label="Coverage points" value={coverageCount} />
          </div>
        </div>
      </div>

      <Section title="Perspective Coverage" icon={GitBranch}>
        {Object.keys(byPerspective).length ? (
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(byPerspective).map(([perspective, count]) => (
              <MetaPill key={perspective} label={perspective} value={count} />
            ))}
          </div>
        ) : (
          <EmptyState label="No perspectives found." />
        )}
      </Section>

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

      {data?.notes && (
        <Section title="Notes" icon={FileText}>
          <AgendaAudit notes={data.notes} />
        </Section>
      )}
    </div>
  );
}
