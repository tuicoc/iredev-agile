import {
  Ban,
  CalendarClock,
  FileText,
  HelpCircle,
  Lightbulb,
  ShieldCheck,
  Users,
} from "lucide-react";
import {
  asArray,
  EmptyState,
  MetaPill,
  Section,
  Tag,
  text,
} from "./viewUtils";

function lensTone(lens) {
  if (lens === "stated") return "green";
  if (lens === "implied") return "blue";
  if (lens === "inferred") return "amber";
  return "default";
}

function PlainList({ items, emptyLabel }) {
  const rows = asArray(items);
  if (!rows.length) return <EmptyState label={emptyLabel} />;

  return (
    <ul className="space-y-1.5">
      {rows.map((item, index) => (
        <li key={index} className="flex gap-2 text-[10.5px] leading-relaxed text-[#4A4038]">
          <span className="font-mono text-[#B86F50]">-</span>
          <span>{text(item)}</span>
        </li>
      ))}
    </ul>
  );
}

function DirectionLine({ label, value }) {
  if (!value) return null;

  return (
    <p className="text-[11px] leading-relaxed text-[#4A4038]">
      <span className="font-semibold text-[#211914]">{label}: </span>
      {value}
    </p>
  );
}

function RoleCard({ role, index }) {
  return (
    <article className="rounded-lg border border-[#E2D6C5] bg-[#FFFDF8]">
      <div className="flex flex-wrap items-center gap-1.5 border-b border-[#E9DFD1] bg-[#FCF8F1] px-3 py-2.5">
        <span className="font-mono text-[10px] text-[#B86F50]">
          {role.id || `ROLE-${index + 1}`}
        </span>
        <span className="text-[12px] font-semibold text-[#211914]">
          {role.name || "Role"}
        </span>
        <Tag tone={lensTone(role.lens)}>{role.lens}</Tag>
      </div>
      <div className="space-y-2 px-3 py-2.5">
        {role.need && (
          <p className="text-[10.5px] leading-relaxed text-[#4A4038]">
            {role.need}
          </p>
        )}
        {role.anchor && (
          <p className="text-[10px] leading-relaxed text-[#776B60]">
            <span className="font-semibold text-[#4A4038]">Anchor: </span>
            {role.anchor}
          </p>
        )}
      </div>
    </article>
  );
}

function AssumptionCard({ item, index }) {
  return (
    <article className="rounded-lg border border-[#E2D6C5] bg-[#FFFDF8] px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-mono text-[10px] text-[#B86F50]">
          {item.id || `ASM-${index + 1}`}
        </span>
        <Tag tone={lensTone(item.lens)}>{item.lens}</Tag>
      </div>
      <p className="mt-1.5 text-[12px] font-semibold leading-relaxed text-[#211914]">
        {item.statement}
      </p>
      {item.why_it_matters && (
        <p className="mt-1.5 text-[10.5px] leading-relaxed text-[#776B60]">
          {item.why_it_matters}
        </p>
      )}
      {item.anchor && (
        <p className="mt-1.5 text-[10px] leading-relaxed text-[#A89C91]">
          Anchor: {item.anchor}
        </p>
      )}
    </article>
  );
}

function ConcernCard({ concern, index }) {
  return (
    <article className="rounded-lg border border-[#E2D6C5] bg-[#FFFDF8] px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-mono text-[10px] text-[#B86F50]">
          {concern.id || `CONCERN-${index + 1}`}
        </span>
        <Tag tone="blue">{concern.theme || "quality"}</Tag>
        <Tag tone={lensTone(concern.lens)}>{concern.lens}</Tag>
      </div>
      {asArray(concern.affected_roles).length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {asArray(concern.affected_roles).map((role) => (
            <Tag key={role}>{role}</Tag>
          ))}
        </div>
      )}
      {concern.rationale && (
        <p className="mt-2 text-[10.5px] leading-relaxed text-[#4A4038]">
          {concern.rationale}
        </p>
      )}
      {concern.anchor && (
        <p className="mt-1.5 text-[10px] leading-relaxed text-[#A89C91]">
          Anchor: {concern.anchor}
        </p>
      )}
    </article>
  );
}

function ScopeCard({ item, index }) {
  return (
    <article className="rounded-lg border border-[#E2D6C5] bg-[#FFFDF8] px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-mono text-[10px] text-[#B86F50]">
          {item.id || `OOS-${index + 1}`}
        </span>
        <Tag tone="purple">out of scope</Tag>
        <Tag tone={lensTone(item.lens)}>{item.lens}</Tag>
      </div>
      <p className="mt-1.5 text-[12px] font-semibold leading-relaxed text-[#211914]">
        {item.item}
      </p>
      {item.reason && (
        <p className="mt-1.5 text-[10.5px] leading-relaxed text-[#776B60]">
          {item.reason}
        </p>
      )}
      {item.anchor && (
        <p className="mt-1.5 text-[10px] leading-relaxed text-[#A89C91]">
          Anchor: {item.anchor}
        </p>
      )}
    </article>
  );
}

export default function ProductVisionView({ data }) {
  const roles = asArray(data?.roles);
  const assumptions = asArray(data?.assumptions);
  const concerns = asArray(data?.concerns);
  const scope = asArray(data?.scope);
  const knownSignals = asArray(data?.known_signals);

  return (
    <div className="h-full overflow-auto bg-[#FFFDF8]">
      <div className="p-4 space-y-3">
        <div className="rounded-lg border border-[#E2D6C5] bg-[#FBF7F0] p-3">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-[#211914]">
            <FileText size={14} className="text-[#B86F50]" />
            Product Vision
          </div>
          {data?.description && (
            <p className="mt-2 text-[11px] leading-relaxed text-[#776B60]">
              {data.description}
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-1.5">
            <MetaPill label="Roles" value={roles.length} />
            <MetaPill label="Assumptions" value={assumptions.length} />
            <MetaPill label="Concerns" value={concerns.length} />
            <MetaPill label="Scope" value={scope.length} />
            <MetaPill label="Known signals" value={knownSignals.length} />
          </div>
        </div>
      </div>

      <Section title="Direction" icon={Lightbulb}>
        <div className="space-y-3">
          <DirectionLine label="Intent" value={data?.intent_summary} />
          <DirectionLine label="Target outcome" value={data?.target_outcome} />
          <div>
            <div className="mb-1.5 text-[10.5px] font-semibold text-[#776B60]">
              Known signals
            </div>
            <PlainList items={knownSignals} emptyLabel="No known signals found." />
          </div>
        </div>
      </Section>

      <Section title="Roles" icon={Users}>
        {roles.length ? (
          <div className="grid gap-3">
            {roles.map((role, index) => (
              <RoleCard key={role.id || role.name || index} role={role} index={index} />
            ))}
          </div>
        ) : (
          <EmptyState label="No roles found." />
        )}
      </Section>

      <Section title="Assumptions" icon={HelpCircle}>
        {assumptions.length ? (
          <div className="grid gap-3">
            {assumptions.map((item, index) => (
              <AssumptionCard key={item.id || index} item={item} index={index} />
            ))}
          </div>
        ) : (
          <EmptyState label="No assumptions found." />
        )}
      </Section>

      <Section title="Concerns" icon={ShieldCheck}>
        {concerns.length ? (
          <div className="grid gap-3">
            {concerns.map((concern, index) => (
              <ConcernCard key={concern.id || index} concern={concern} index={index} />
            ))}
          </div>
        ) : (
          <EmptyState label="No concerns found." />
        )}
      </Section>

      <Section title="Scope" icon={Ban}>
        {scope.length ? (
          <div className="grid gap-3">
            {scope.map((item, index) => (
              <ScopeCard key={item.id || index} item={item} index={index} />
            ))}
          </div>
        ) : (
          <EmptyState label="No scope boundaries found." />
        )}
      </Section>

      {data?.notes && (
        <Section title="Notes" icon={CalendarClock}>
          <pre className="whitespace-pre-wrap rounded-lg border border-[#E2D6C5] bg-[#F6F1E8]
                          p-3 text-[10.5px] leading-relaxed text-[#776B60] font-sans">
            {data.notes}
          </pre>
        </Section>
      )}
    </div>
  );
}
