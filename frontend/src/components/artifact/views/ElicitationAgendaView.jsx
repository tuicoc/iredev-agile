import {
  ClipboardList,
  MessageSquareText,
} from "lucide-react";
import {
  asArray,
  EmptyState,
  MetaPill,
  Section,
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
      <dt className="text-[10px] font-semibold text-[#A0A0A0]">
        {label}
      </dt>
      <dd className="text-[10.5px] leading-relaxed text-[#3A3A3A]">
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
        <li key={index} className="flex gap-2 text-[10.5px] leading-relaxed text-[#3A3A3A]">
          <span className="font-mono text-[9.5px] text-[#B86F50]">{index + 1}.</span>
          <span>{text(item)}</span>
        </li>
      ))}
    </ol>
  );
}

function AgendaItemCard({ item, index }) {
  const frictions = asArray(item.frictions_to_probe || item.coverage_points);
  const perspective = item.perspective || item.role || "Stakeholder";
  const title = item.scene || item.context || item.elicitation_goal || "Evidence scene";
  const question =
    item.critical_incident_prompt ||
    item.seed_question ||
    item.probe;
  const status = item.status && item.status !== "planned" ? item.status : null;

  return (
    <article className="rounded-lg border border-[#E5E5E5] bg-[#FFFFFF]">
      <div className="border-b border-[#E8E8E8] bg-[#F8F8F8] px-3 py-2.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-mono text-[10px] text-[#B86F50]">
            {item.id || item.item_id || `IT-${index + 1}`}
          </span>
          <span className="rounded border border-[#FFD0B0] bg-[#FEF0E8] px-1.5 py-0.5 text-[9.5px] font-medium text-[#B86F50]">
            {perspective}
          </span>
          {status && (
            <span className="rounded border border-[#DEDEDE] bg-[#F7F7F7] px-1.5 py-0.5 text-[9.5px] font-medium text-[#6B6B6B]">
              {status}
            </span>
          )}
        </div>
        <p className="mt-1.5 text-[12px] font-semibold leading-relaxed text-[#1A1A1A]">
          {title}
        </p>
      </div>

      <div className="space-y-2.5 px-3 py-2.5">
        <dl className="space-y-2">
          <InfoRow label="Question" value={question} />
          <InfoRow label="Close" value={item.close_when || item.close} />
        </dl>

        <div>
          <div className="mb-1.5 text-[10.5px] font-semibold text-[#6B6B6B]">
            Frictions to probe
          </div>
          <NumberedList items={frictions} emptyLabel="No frictions found." />
        </div>
      </div>
    </article>
  );
}

export function ElicitationAgendaView({ data }) {
  const items = asArray(data?.items || data?.agenda_items || data?.elicitation_items);
  const byPerspective = countBy(items, (item) => item.perspective || item.role);
  const frictionCount = items.reduce(
    (total, item) =>
      total + asArray(item.frictions_to_probe || item.coverage_points).length,
    0,
  );

  return (
    <div className="h-full overflow-auto bg-[#FFFFFF]">
      <div className="p-4 space-y-3">
        <div className="rounded-lg border border-[#E5E5E5] bg-[#F8F8F8] p-3">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-[#1A1A1A]">
            <ClipboardList size={14} className="text-[#B86F50]" />
            Elicitation Agenda
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-[#6B6B6B]">
            {items.length
              ? "Agenda items are evidence jobs: one perspective, one current scene, one decision target."
              : "No agenda items found."}
          </p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <MetaPill label="Items" value={data?.total_items ?? items.length} />
            <MetaPill label="Perspectives" value={Object.keys(byPerspective).length} />
            <MetaPill label="Frictions" value={frictionCount} />
          </div>
        </div>
      </div>

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
    </div>
  );
}
