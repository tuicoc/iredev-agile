import { ClipboardList, FileText, Gauge, ListChecks, ShieldCheck } from "lucide-react";
import {
  asArray,
  EmptyState,
  MetaPill,
  Section,
  Tag,
  text,
} from "./viewUtils";

const INVEST_KEYS = ["independent", "negotiable", "valuable", "estimable", "small", "testable"];
const INVEST_SHORT = ["I", "N", "V", "E", "S", "T"];
const INVEST_LABELS = {
  independent: "Independent",
  negotiable: "Negotiable",
  valuable: "Valuable",
  estimable: "Estimable",
  small: "Small",
  testable: "Testable",
};

function getItems(data) {
  if (Array.isArray(data?.items)) return data.items;
  if (Array.isArray(data?.stories)) return data.stories;
  if (Array.isArray(data?.pbis)) return data.pbis;
  return [];
}

function pointsTone(points) {
  if (Number(points) <= 3) return "green";
  if (Number(points) <= 8) return "amber";
  return "red";
}

function statusTone(status) {
  if (status === "ready") return "green";
  if (status === "needs_refinement" || status === "oversized") return "amber";
  if (status === "invest_failed") return "red";
  return "default";
}

function typeTone(type) {
  if (type === "functional") return "warm";
  if (type === "non_functional") return "blue";
  if (type === "constraint") return "purple";
  return "default";
}

function pbiParts(item) {
  return {
    estimation: item.estimation || {},
    prioritization: item.prioritization || {},
    dependencies: item.dependencies || {},
    planning: item.planning || {},
    quality: item.quality || {},
    analysis: item.analysis || {},
    trace: item.requirement_trace || {},
  };
}

function investReason(key, item) {
  const { analysis, quality } = pbiParts(item);
  const notes = analysis.invest_notes || analysis.estimation_reasoning || "";
  const flags = asArray(quality.invest_flags ?? item.invest_flags);
  if (!flags.includes(key)) return `${INVEST_LABELS[key]} passed.`;
  return (
    notes ||
    `${INVEST_LABELS[key]} failed. This PBI needs refinement before it is ready.`
  );
}

function InvestScore({ item }) {
  const { quality } = pbiParts(item);
  const failed = asArray(quality.invest_flags ?? item.invest_flags);
  const hasResult = quality.invest_pass !== undefined || failed.length > 0;

  if (!hasResult) {
    return <span className="text-[10px] text-[#A89C91]">INVEST not evaluated</span>;
  }

  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[9.5px] font-semibold uppercase text-[#A89C91]">INVEST</span>
      {INVEST_KEYS.map((key, index) => {
        const ok = !failed.includes(key);
        return (
          <span
            key={key}
            title={investReason(key, item)}
            className={`inline-flex h-5 w-5 cursor-help items-center justify-center rounded text-[9px] font-bold
                        ${ok ? "bg-green-100 text-green-700" : "bg-red-100 text-red-600 ring-1 ring-red-200"}`}
          >
            {INVEST_SHORT[index]}
          </span>
        );
      })}
    </div>
  );
}

function ScoreRail({ item }) {
  const { estimation, prioritization, planning } = pbiParts(item);
  const storyPoints = estimation.story_points ?? item.story_points ?? 0;
  const rank = prioritization.priority_rank ?? item.priority_rank;
  const wsjf = prioritization.wsjf_score ?? item.wsjf_score;
  const status = planning.status ?? item.status;

  return (
    <div className="mt-2 grid gap-x-4 gap-y-1 text-[10.5px] text-[#776B60] sm:grid-cols-2">
      <span>
        <span className="font-semibold text-[#4A4038]">Story points:</span>{" "}
        <span className={pointsTone(storyPoints) === "red" ? "text-red-600 font-semibold" : ""}>
          {storyPoints}
        </span>
      </span>
      <span><span className="font-semibold text-[#4A4038]">Priority rank:</span> {rank || "-"}</span>
      <span>
        <span className="font-semibold text-[#4A4038]">WSJF score:</span>{" "}
        {wsjf === undefined ? "-" : Number(wsjf).toFixed(2)}
      </span>
      <span>
        <span className="font-semibold text-[#4A4038]">Planning:</span>{" "}
        <span className={statusTone(status) === "amber" ? "text-amber-700 font-medium" : ""}>
          {String(status || "-").replace(/_/g, " ")}
        </span>
      </span>
      <span><span className="font-semibold text-[#4A4038]">Business value:</span> {prioritization.business_value ?? "-"}</span>
      <span><span className="font-semibold text-[#4A4038]">Time criticality:</span> {prioritization.time_criticality ?? "-"}</span>
      <span><span className="font-semibold text-[#4A4038]">Risk reduction:</span> {prioritization.risk_reduction ?? "-"}</span>
    </div>
  );
}

function PbiCard({ item, index }) {
  const { dependencies, planning, analysis, trace } = pbiParts(item);
  const itemId = item.id || item.pbi_id || `PBI-${index + 1}`;
  const traceTopic = [trace.requirement_id, trace.entity, trace.step, trace.aspect]
    .filter(Boolean)
    .join(" / ");

  return (
    <article className="rounded-xl border border-[#E2D6C5] bg-[#FFFDF8]">
      <div className="px-3 py-2.5 border-b border-[#E9DFD1] bg-[#FCF8F1]">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-mono text-[10px] text-[#B86F50]">{itemId}</span>
          <Tag tone={typeTone(item.type)}>{String(item.type || "").replace(/_/g, " ")}</Tag>
          {item.domain && <Tag>{item.domain}</Tag>}
          {asArray(planning.tags).map((tag) => (
            <Tag key={tag}>{tag}</Tag>
          ))}
        </div>
        <h4 className="mt-2 text-[12.5px] font-semibold leading-snug text-[#211914]">
          {item.title || item.description || itemId}
        </h4>
        {item.description && (
          <p className="mt-1 text-[10.5px] leading-relaxed text-[#776B60]">
            {item.description}
          </p>
        )}
        <ScoreRail item={item} />
      </div>

      <div className="px-3 py-2.5 space-y-2">
        <InvestScore item={item} />
        {traceTopic && (
          <p className="text-[10.5px] leading-relaxed text-[#776B60]">
            <span className="font-semibold text-[#4A4038]">Trace: </span>
            {traceTopic}
          </p>
        )}
        {(asArray(dependencies.blocked_by).length > 0 || asArray(dependencies.blocks).length > 0) && (
          <p className="text-[10.5px] leading-relaxed text-[#776B60]">
            <span className="font-semibold text-[#4A4038]">Dependencies: </span>
            {asArray(dependencies.blocked_by).map((dep) => `blocked by ${dep}`).join(", ")}
            {asArray(dependencies.blocked_by).length > 0 && asArray(dependencies.blocks).length > 0 ? "; " : ""}
            {asArray(dependencies.blocks).map((dep) => `blocks ${dep}`).join(", ")}
          </p>
        )}
        {(analysis.feasibility_notes || analysis.estimation_reasoning || trace.statement) && (
          <details className="text-[10.5px] leading-relaxed text-[#776B60]">
            <summary className="cursor-pointer font-semibold text-[#4A4038]">
              Analysis and requirement trace
            </summary>
            <div className="mt-2 space-y-1.5">
              {analysis.feasibility_notes && <p>{analysis.feasibility_notes}</p>}
              {analysis.estimation_reasoning && <p>{analysis.estimation_reasoning}</p>}
              {trace.statement && <p>Requirement: {trace.statement}</p>}
              {trace.rationale && <p>Rationale: {trace.rationale}</p>}
              {asArray(trace.acceptance_criteria).length > 0 && (
                <p>Source AC: {asArray(trace.acceptance_criteria).map(text).join("; ")}</p>
              )}
            </div>
          </details>
        )}
      </div>
    </article>
  );
}

function QualityWarnings({ warnings }) {
  const entries = Object.entries(warnings || {}).filter(([, value]) => asArray(value).length > 0);
  if (!entries.length) return null;

  return (
    <Section title="Quality Warnings" icon={ShieldCheck}>
      <div className="grid gap-2">
        {entries.map(([key, values]) => (
          <div key={key} className="rounded-xl border border-amber-200 bg-amber-50 p-3">
            <div className="text-[10px] font-semibold uppercase text-amber-700">
              {key.replace(/_/g, " ")}
            </div>
            <ul className="mt-1.5 space-y-1 text-[10.5px] leading-relaxed text-amber-900">
              {asArray(values).map((value, index) => (
                <li key={index} className="flex gap-2">
                  <span>-</span>
                  <span>{text(value)}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Section>
  );
}

export function ProductBacklogView({ data }) {
  const items = getItems(data);
  const totalPoints =
    data?.total_story_points ??
    items.reduce((sum, item) => sum + Number(item.estimation?.story_points ?? item.story_points ?? 0), 0);
  const readyCount =
    data?.ready_count ??
    items.filter((item) => (item.planning?.status ?? item.status) === "ready").length;
  const needsRefinement =
    data?.needs_refinement_count ??
    items.filter((item) => (item.planning?.status ?? item.status) === "needs_refinement").length;

  return (
    <div className="h-full overflow-auto bg-[#FFFDF8]">
      <div className="p-4 space-y-3">
        <div className="rounded-xl border border-[#E2D6C5] bg-[#FBF7F0] p-3">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-[#211914]">
            <ClipboardList size={14} className="text-[#B86F50]" />
            Product Backlog
          </div>
          {data?.pass_notes && (
            <p className="mt-2 text-[11px] leading-relaxed text-[#776B60]">
              {data.pass_notes}
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-1.5">
            <MetaPill label="Stories" value={data?.total_items ?? data?.total_stories ?? items.length} />
            <MetaPill label="Story Points" value={totalPoints} />
            <MetaPill label="Ready" value={readyCount} tone="green" />
            <MetaPill label="Needs Refinement" value={needsRefinement} tone={needsRefinement ? "amber" : "default"} />
          </div>
        </div>
      </div>

      <Section title="Backlog Items" icon={ListChecks}>
        {items.length ? (
          <div className="grid gap-3">
            {items.map((item, index) => (
              <PbiCard key={item.id || item.pbi_id || index} item={item} index={index} />
            ))}
          </div>
        ) : (
          <EmptyState label="No backlog items found." />
        )}
      </Section>

      {(data?.methodology || asArray(data?.source_artifacts).length > 0) && (
        <Section title="Methodology" icon={Gauge}>
          <div className="rounded-xl border border-[#E2D6C5] bg-[#FFFDF8] p-3 text-[10.5px] leading-relaxed text-[#776B60]">
            {Object.entries(data?.methodology || {}).map(([key, value]) => (
              <p key={key}>
                <span className="font-semibold text-[#4A4038]">{key.replace(/_/g, " ")}: </span>
                {value}
              </p>
            ))}
            {asArray(data?.source_artifacts).length > 0 && (
              <p>
                <span className="font-semibold text-[#4A4038]">Source artifacts: </span>
                {asArray(data.source_artifacts).join(", ")}
              </p>
            )}
          </div>
        </Section>
      )}

      <QualityWarnings warnings={data?.quality_warnings} />

      <Section title="Notes" icon={FileText}>
        {data?.notes || data?.pass_notes || data?.rebuild_feedback ? (
          <div className="space-y-2">
            {(data?.notes || data?.pass_notes) && (
              <pre
                className="whitespace-pre-wrap rounded-xl border border-[#E2D6C5] bg-[#F6F1E8]
                           p-3 text-[10.5px] leading-relaxed text-[#776B60] font-sans"
              >
                {data.notes || data.pass_notes}
              </pre>
            )}
            {data?.rebuild_feedback && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-[10.5px] leading-relaxed text-amber-900">
                <span className="font-semibold">Rebuild feedback:</span>{" "}
                {data.rebuild_feedback}
              </div>
            )}
          </div>
        ) : (
          <EmptyState label="No backlog notes found." />
        )}
      </Section>
    </div>
  );
}
