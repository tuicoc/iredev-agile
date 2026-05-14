import { ClipboardCheck, FileText, ListChecks, ShieldCheck, TestTube2 } from "lucide-react";
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
  if (Array.isArray(data?.pbis)) return data.pbis;
  if (Array.isArray(data?.stories)) return data.stories;
  return [];
}

function typeTone(type) {
  if (type === "functional") return "warm";
  if (type === "non_functional") return "blue";
  return "default";
}

function statusTone(status) {
  if (status === "ready") return "green";
  if (status === "needs_refinement") return "amber";
  return "default";
}

function acTone(type) {
  if (type === "happy_path") return "green";
  if (type === "edge_case") return "amber";
  if (type === "error_case") return "red";
  return "default";
}

function pointsTone(points) {
  if (Number(points) <= 3) return "green";
  if (Number(points) <= 8) return "amber";
  return "red";
}

function itemParts(item) {
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
  const { analysis, quality } = itemParts(item);
  const failed = asArray(quality.invest_flags ?? item.invest_flags);
  if (!failed.includes(key)) return `${INVEST_LABELS[key]} passed.`;
  return (
    analysis.invest_notes ||
    analysis.estimation_reasoning ||
    `${INVEST_LABELS[key]} failed. Review the source story and split/refine it before approval.`
  );
}

function InvestScore({ item }) {
  const { quality } = itemParts(item);
  const failed = asArray(quality.invest_flags ?? item.invest_flags);

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
  const { estimation, prioritization, planning } = itemParts(item);
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

function AcceptanceCriteria({ criteria }) {
  const list = asArray(criteria);

  if (!list.length) {
    return <EmptyState label="No acceptance criteria defined." />;
  }

  return (
    <div className="space-y-2">
      {list.map((criterion, index) => (
        <div key={criterion.id || index} className="rounded-lg border border-[#E9DFD1] bg-[#FBF7F0] px-3 py-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-[9.5px] text-[#B86F50]">
              {criterion.id || `AC-${index + 1}`}
            </span>
            <Tag tone={acTone(criterion.type)}>
              {String(criterion.type || "").replace(/_/g, " ")}
            </Tag>
          </div>
          <div className="mt-1.5 space-y-0.5 text-[10.5px] leading-relaxed text-[#4A4038]">
            <p><span className="font-semibold text-[#776B60]">Given</span> {text(criterion.given)}</p>
            <p><span className="font-semibold text-[#776B60]">When</span> {text(criterion.when)}</p>
            <p><span className="font-semibold text-[#776B60]">Then</span> {text(criterion.then)}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

function PbiValidationCard({ item, index }) {
  const { dependencies, quality, analysis, trace } = itemParts(item);
  const criteria = quality.acceptance_criteria ?? item.acceptance_criteria ?? [];
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
          <Tag tone={criteria.length ? "green" : "amber"}>{criteria.length} AC</Tag>
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

      <div className="px-3 py-2.5 space-y-3">
        <InvestScore item={item} />
        <div>
          <div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase text-[#776B60]">
            <TestTube2 size={12} className="text-[#B86F50]" />
            Acceptance Criteria
          </div>
          <AcceptanceCriteria criteria={criteria} />
        </div>

        {(traceTopic || asArray(dependencies.blocked_by).length > 0 || asArray(dependencies.blocks).length > 0 || analysis.ac_generation_note) && (
          <details className="text-[10.5px] leading-relaxed text-[#776B60]">
            <summary className="cursor-pointer font-semibold text-[#4A4038]">
              Trace, dependencies, and notes
            </summary>
            <div className="mt-2 space-y-1.5">
              {traceTopic && <p>Trace: {traceTopic}</p>}
              {trace.statement && <p>Requirement: {trace.statement}</p>}
              {asArray(dependencies.blocked_by).length > 0 && (
                <p>Blocked by: {asArray(dependencies.blocked_by).join(", ")}</p>
              )}
              {asArray(dependencies.blocks).length > 0 && (
                <p>Blocks: {asArray(dependencies.blocks).join(", ")}</p>
              )}
              {analysis.ac_generation_note && <p>{analysis.ac_generation_note}</p>}
            </div>
          </details>
        )}
      </div>
    </article>
  );
}

export function ValidatedBacklogView({ data }) {
  const items = getItems(data);
  const stats = data?.refinement_stats || {};
  const totalAc =
    stats.total_ac ??
    items.reduce(
      (sum, item) =>
        sum + asArray(item.quality?.acceptance_criteria ?? item.acceptance_criteria).length,
      0,
    );
  const readyCount =
    stats.ready_count ??
    stats.ready_pbis ??
    data?.ready_count ??
    items.filter((item) => (item.planning?.status ?? item.status) === "ready").length;
  const totalItems = stats.total_pbis ?? data?.total_items ?? items.length;

  return (
    <div className="h-full overflow-auto bg-[#FFFDF8]">
      <div className="p-4 space-y-3">
        <div className="rounded-xl border border-[#E2D6C5] bg-[#FBF7F0] p-3">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-[#211914]">
            <ClipboardCheck size={14} className="text-[#B86F50]" />
            Validated Product Backlog
          </div>
          {data?.refinement_summary && (
            <p className="mt-2 text-[11px] leading-relaxed text-[#776B60]">
              {data.refinement_summary}
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-1.5">
            <MetaPill label="Ready PBIs" value={`${readyCount}/${totalItems}`} tone="green" />
            <MetaPill label="Acceptance Criteria" value={totalAc} />
          </div>
        </div>
      </div>

      <Section title="Validated PBIs" icon={ListChecks}>
        {items.length ? (
          <div className="grid gap-3">
            {items.map((item, index) => (
              <PbiValidationCard key={item.id || item.pbi_id || index} item={item} index={index} />
            ))}
          </div>
        ) : (
          <EmptyState label="No validated backlog items found." />
        )}
      </Section>

      {data?.quality_warnings && (
        <Section title="Quality Warnings" icon={ShieldCheck}>
          <div className="grid gap-2">
            {Object.entries(data.quality_warnings)
              .filter(([, values]) => asArray(values).length > 0)
              .map(([key, values]) => (
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
      )}

      <Section title="Notes" icon={FileText}>
        {data?.refinement_summary || data?.rebuild_feedback ? (
          <div className="space-y-2">
            {data?.refinement_summary && (
              <pre
                className="whitespace-pre-wrap rounded-xl border border-[#E2D6C5] bg-[#F6F1E8]
                           p-3 text-[10.5px] leading-relaxed text-[#776B60] font-sans"
              >
                {data.refinement_summary}
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
          <EmptyState label="No validation notes found." />
        )}
      </Section>
    </div>
  );
}
