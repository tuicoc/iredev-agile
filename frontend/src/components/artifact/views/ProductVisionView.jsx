import {
  ArrowRight,
  Ban,
  CalendarClock,
  FileText,
  GitBranch,
  ShieldCheck,
  Users,
} from "lucide-react";

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function text(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function Section({ title, icon: Icon, children }) {
  return (
    <section className="border-t border-[#E2D6C5]">
      <div className="sticky top-0 z-10 bg-[#FBF7F0]/95 backdrop-blur px-4 py-2.5
                      border-b border-[#E2D6C5] flex items-center gap-2">
        {Icon && <Icon size={14} className="text-[#B86F50]" />}
        <h3 className="text-[12px] font-semibold text-[#211914]">{title}</h3>
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

function MetaPill({ label, value }) {
  if (!value) return null;

  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-[#D8CBBB]
                     bg-[#F6F1E8] px-2.5 py-1 text-[10.5px] text-[#776B60]">
      <span className="font-semibold text-[#4A4038]">{label}</span>
      {text(value)}
    </span>
  );
}

function EmptyState({ label }) {
  return (
    <div className="rounded-lg border border-dashed border-[#D8CBBB] bg-[#FBF7F0]
                    px-3 py-6 text-center text-[12px] text-[#A89C91]">
      {label}
    </div>
  );
}

function EntityFlowDiagram({ entities, links }) {
  if (!entities.length) return <EmptyState label="No entity flow found." />;

  const sorted = [...entities].sort((a, b) => (a.order ?? 0) - (b.order ?? 0));

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto pb-2">
        <div
          className="grid gap-3 min-w-[760px]"
          style={{
            gridTemplateColumns: `repeat(${sorted.length}, minmax(220px, 1fr))`,
          }}
        >
          {sorted.map((entity, idx) => (
            <div key={entity.name || idx} className="relative">
              {idx < sorted.length - 1 && (
                <div className="absolute top-7 -right-3 w-3 h-px bg-[#CDBEAC]" />
              )}
              <div className="rounded-xl border border-[#D8CBBB] bg-[#FFFDF8] overflow-hidden">
                <div className="px-3 py-2.5 bg-[#FCF8F1] border-b border-[#E2D6C5]">
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-semibold text-[12.5px] text-[#211914] truncate">
                      {entity.name}
                    </div>
                    <span className="rounded-full bg-[#ECE3D6] px-2 py-0.5 text-[9.5px]
                                     font-medium text-[#776B60]">
                      {entity.kind || "entity"}
                    </span>
                  </div>
                  {entity.purpose && (
                    <p className="mt-1 text-[10.5px] leading-relaxed text-[#776B60]">
                      {entity.purpose}
                    </p>
                  )}
                </div>
                <div className="p-2.5 space-y-1.5">
                  {asArray(entity.steps).map((step, stepIdx) => (
                    <div
                      key={`${entity.name || idx}-${step.name || stepIdx}`}
                      className="rounded-lg border border-[#E9DFD1] bg-[#F6F1E8] px-2.5 py-2"
                    >
                      <div className="flex items-center gap-2">
                        <span className="flex h-4 w-4 items-center justify-center rounded-full
                                         bg-[#B86F50] text-white text-[9px] font-semibold">
                          {stepIdx + 1}
                        </span>
                        <span className="text-[11px] font-medium text-[#211914]">
                          {step.name || text(step)}
                        </span>
                      </div>
                      {step.detail && (
                        <div className="mt-1 pl-6 text-[10.5px] leading-relaxed text-[#776B60]">
                          {step.detail}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {links.length > 0 && (
        <div className="rounded-xl border border-[#E2D6C5] bg-[#FBF7F0]">
          <div className="px-3 py-2 border-b border-[#E2D6C5] text-[11px]
                          font-semibold text-[#776B60]">
            Active Links
          </div>
          <div className="divide-y divide-[#E9DFD1]">
            {links.map((link, idx) => (
              <div key={idx} className="px-3 py-2.5">
                <div className="flex flex-wrap items-center gap-2 text-[11px]">
                  <span className="rounded-full bg-[#ECE3D6] px-2 py-0.5 font-medium text-[#4A4038]">
                    {link.source || link.from}
                  </span>
                  <ArrowRight size={13} className="text-[#B86F50]" />
                  <span className="rounded-full bg-[#ECE3D6] px-2 py-0.5 font-medium text-[#4A4038]">
                    {link.target || link.to}
                  </span>
                  {link.trigger && (
                    <span className="text-[#776B60]">
                      trigger: <span className="font-medium">{link.trigger}</span>
                    </span>
                  )}
                  {asArray(link.steps).length > 0 && (
                    <span className="text-[#776B60]">
                      steps: <span className="font-medium">{link.steps.join(", ")}</span>
                    </span>
                  )}
                </div>
                {link.detail && (
                  <p className="mt-1.5 text-[10.5px] leading-relaxed text-[#776B60]">
                    {link.detail}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function RoleDutyList({ roles }) {
  if (!roles.length) return <EmptyState label="No roles found." />;

  return (
    <div className="space-y-3">
      {roles.map((role, idx) => (
        <div key={role.name || idx} className="rounded-xl border border-[#E2D6C5] bg-[#FFFDF8]">
          <div className="px-3 py-2.5 bg-[#FCF8F1] border-b border-[#E2D6C5]
                          flex items-center justify-between gap-2">
            <div>
              <div className="text-[12.5px] font-semibold text-[#211914]">
                {role.name || role.role || "Role"}
              </div>
              <div className="text-[10.5px] text-[#776B60]">{role.kind || role.type}</div>
            </div>
            <span className="text-[10px] text-[#A89C91]">
              {asArray(role.duties).length} duties
            </span>
          </div>
          <div className="divide-y divide-[#E9DFD1]">
            {asArray(role.duties).map((duty, dutyIdx) => (
              <div key={duty.id || dutyIdx} className="px-3 py-2.5">
                <div className="flex flex-wrap items-center gap-2 mb-1">
                  <span className="font-mono text-[10px] text-[#B86F50]">
                    {duty.id || `duty-${dutyIdx + 1}`}
                  </span>
                  <span className="rounded bg-[#ECE3D6] px-1.5 py-0.5 text-[9.5px] text-[#776B60]">
                    {duty.priority || "priority"}
                  </span>
                  <span className="rounded bg-[#F6F1E8] px-1.5 py-0.5 text-[9.5px] text-[#776B60]">
                    {duty.aspect || "aspect"}
                  </span>
                  <span className="text-[10px] text-[#A89C91]">
                    {duty.entity} / {duty.step}
                  </span>
                </div>
                <p className="text-[11px] leading-relaxed text-[#211914]">{duty.rule}</p>
                {duty.risk && (
                  <p className="mt-1 text-[10.5px] leading-relaxed text-[#776B60]">
                    Risk: {duty.risk}
                  </p>
                )}
                {(asArray(duty.entity_refs).length > 0 || asArray(duty.flow_step_refs).length > 0) && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5 text-[10px] text-[#776B60]">
                    {asArray(duty.entity_refs).map((ref) => (
                      <span key={ref} className="rounded-full border border-[#D8CBBB] px-2 py-0.5">
                        entity: {ref}
                      </span>
                    ))}
                    {asArray(duty.flow_step_refs).map((ref) => (
                      <span key={ref} className="rounded-full border border-[#D8CBBB] px-2 py-0.5">
                        step: {ref}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function ConcernList({ concerns }) {
  if (!concerns.length) return <EmptyState label="No NFR concerns found." />;

  return (
    <div className="grid gap-2">
      {concerns.map((concern, idx) => (
        <div key={concern.id || idx} className="rounded-xl border border-[#E2D6C5] bg-[#FFFDF8] p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[10px] text-[#B86F50]">{concern.id}</span>
            <span className="rounded bg-[#ECE3D6] px-1.5 py-0.5 text-[9.5px] text-[#776B60]">
              {concern.category}
            </span>
          </div>
          <div className="mt-1 text-[12px] font-semibold text-[#211914]">{concern.theme}</div>
          <div className="mt-1 text-[10.5px] text-[#776B60]">
            Attached to: {text(concern.attached_to)} · Roles: {text(concern.affected_roles)}
          </div>
          {concern.rationale && (
            <p className="mt-1.5 text-[10.5px] leading-relaxed text-[#776B60]">
              {concern.rationale}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

function ScopeList({ scope }) {
  if (!scope.length) return <EmptyState label="No scope exclusions found." />;

  return (
    <div className="grid gap-2">
      {scope.map((item, idx) => (
        <div key={item.id || idx} className="rounded-xl border border-[#E2D6C5] bg-[#FFFDF8] p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[10px] text-[#B86F50]">{item.id}</span>
            <span className="text-[12px] font-semibold text-[#211914]">{item.item}</span>
          </div>
          {item.reason && (
            <p className="mt-1 text-[10.5px] leading-relaxed text-[#776B60]">{item.reason}</p>
          )}
        </div>
      ))}
    </div>
  );
}

export default function ProductVisionView({ data }) {
  const entities = asArray(data?.flow?.entities);
  const links = asArray(data?.flow?.links);
  const roles = asArray(data?.roles);
  const nfrConcerns = asArray(data?.nfr_concerns);
  const scope = asArray(data?.scope);

  return (
    <div className="h-full overflow-auto bg-[#FFFDF8]">
      <div className="p-4 space-y-3">
        <div className="rounded-xl border border-[#E2D6C5] bg-[#FBF7F0] p-3">
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
            <MetaPill label="Entities" value={entities.length} />
            <MetaPill label="Links" value={links.length} />
            <MetaPill label="Roles" value={roles.length} />
            <MetaPill label="NFR" value={nfrConcerns.length} />
            <MetaPill label="Scope" value={scope.length} />
          </div>
        </div>
      </div>

      <Section title="Visual Flow" icon={GitBranch}>
        <EntityFlowDiagram entities={entities} links={links} />
      </Section>

      <Section title="Roles And Duties" icon={Users}>
        <RoleDutyList roles={roles} />
      </Section>

      <Section title="NFR Concerns" icon={ShieldCheck}>
        <ConcernList concerns={nfrConcerns} />
      </Section>

      <Section title="Scope Boundaries" icon={Ban}>
        <ScopeList scope={scope} />
      </Section>

      <Section title="Notes" icon={CalendarClock}>
        {data?.notes ? (
          <pre className="whitespace-pre-wrap rounded-xl border border-[#E2D6C5] bg-[#F6F1E8]
                          p-3 text-[10.5px] leading-relaxed text-[#776B60] font-sans">
            {data.notes}
          </pre>
        ) : (
          <EmptyState label="No notes found." />
        )}
      </Section>
    </div>
  );
}
