// src/components/artifact/utils/artifactDownload.js
// =============================================================================
// Multi-format artifact download: JSON, Markdown, PDF
// =============================================================================
import { jsPDF } from "jspdf";

// ── Helpers ──────────────────────────────────────────────────────────────────
function asArray(v) { return Array.isArray(v) ? v : []; }
function txt(v) {
  if (v === null || v === undefined || v === "") return "-";
  if (Array.isArray(v)) return v.map(txt).join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
function slug(title) {
  return (title || "artifact").replace(/\s+/g, "-").toLowerCase();
}
function hr() { return "\n---\n\n"; }

// ── 1. Download as JSON ──────────────────────────────────────────────────────
export function downloadAsJson(data, filename) {
  const content = typeof data === "string" ? data : JSON.stringify(data ?? {}, null, 2);
  triggerDownload(content, `${slug(filename)}.json`, "application/json");
}

// ── 2. Download as Markdown ──────────────────────────────────────────────────
export function downloadAsMarkdown(data, artifactType, filename) {
  const parsed = typeof data === "string" ? safeParse(data) : data;
  const md = convertToMarkdown(parsed, artifactType, filename);
  triggerDownload(md, `${slug(filename)}.md`, "text/markdown");
}

// ── 3. Download as PDF ──────────────────────────────────────────────────────
export function downloadAsPdf(data, artifactType, filename) {
  const parsed = typeof data === "string" ? safeParse(data) : data;
  const md = convertToMarkdown(parsed, artifactType, filename);
  generatePdf(md, slug(filename));
}

// ── Trigger browser download ─────────────────────────────────────────────────
function triggerDownload(content, filename, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}

function safeParse(str) {
  try { return JSON.parse(str); } catch { return null; }
}

// ── Markdown Router ──────────────────────────────────────────────────────────
function convertToMarkdown(data, artifactType, title) {
  if (!data) return `# ${title || "Artifact"}\n\n\`\`\`json\nnull\n\`\`\`\n`;
  switch (artifactType) {
    case "product_vision":            return mdProductVision(data, title);
    case "elicitation_agenda":        return mdElicitationAgenda(data, title);
    case "interview_record":          return mdInterviewRecord(data, title);
    case "requirement_list":          return mdRequirementList(data, title);
    case "product_backlog":           return mdProductBacklog(data, title);
    case "validated_product_backlog": return mdValidatedBacklog(data, title);
    default:                          return mdFallback(data, title);
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// Per-Type Markdown Converters
// ═════════════════════════════════════════════════════════════════════════════

// ── Product Vision ───────────────────────────────────────────────────────────
function mdProductVision(d, title) {
  let md = `# ${title || "Product Vision"}\n\n`;
  if (d.description) md += `${d.description}\n\n`;

  // Direction
  md += `## Direction\n\n`;
  if (d.intent_summary) md += `**Intent:** ${d.intent_summary}\n\n`;
  if (d.target_outcome) md += `**Target Outcome:** ${d.target_outcome}\n\n`;
  const signals = asArray(d.known_signals);
  if (signals.length) {
    md += `**Known Signals:**\n`;
    signals.forEach(s => { md += `- ${txt(s)}\n`; });
    md += "\n";
  }

  // Roles
  const roles = asArray(d.roles);
  if (roles.length) {
    md += `## Roles\n\n`;
    roles.forEach((r, i) => {
      md += `### ${r.id || `ROLE-${i + 1}`}: ${r.name || "Role"}\n\n`;
      md += `- **Lens:** ${r.lens || "-"}\n`;
      if (r.need) md += `- **Need:** ${r.need}\n`;
      if (r.anchor) md += `- **Anchor:** ${r.anchor}\n`;
      md += "\n";
    });
  }

  // Assumptions
  const assumptions = asArray(d.assumptions);
  if (assumptions.length) {
    md += `## Assumptions\n\n`;
    assumptions.forEach((a, i) => {
      md += `### ${a.id || `ASM-${i + 1}`}\n\n`;
      md += `- **Lens:** ${a.lens || "-"}\n`;
      if (a.statement) md += `- **Statement:** ${a.statement}\n`;
      if (a.why_it_matters) md += `- **Why it matters:** ${a.why_it_matters}\n`;
      if (a.anchor) md += `- **Anchor:** ${a.anchor}\n`;
      md += "\n";
    });
  }

  // Concerns
  const concerns = asArray(d.concerns);
  if (concerns.length) {
    md += `## Concerns\n\n`;
    concerns.forEach((c, i) => {
      md += `### ${c.id || `CONCERN-${i + 1}`}\n\n`;
      md += `- **Theme:** ${c.theme || "-"}\n`;
      md += `- **Lens:** ${c.lens || "-"}\n`;
      const affected = asArray(c.affected_roles);
      if (affected.length) md += `- **Affected roles:** ${affected.join(", ")}\n`;
      if (c.rationale) md += `- **Rationale:** ${c.rationale}\n`;
      if (c.anchor) md += `- **Anchor:** ${c.anchor}\n`;
      md += "\n";
    });
  }

  // Scope
  const scope = asArray(d.scope);
  if (scope.length) {
    md += `## Out of Scope\n\n`;
    scope.forEach((s, i) => {
      md += `### ${s.id || `OOS-${i + 1}`}\n\n`;
      md += `- **Lens:** ${s.lens || "-"}\n`;
      if (s.item) md += `- **Item:** ${s.item}\n`;
      if (s.reason) md += `- **Reason:** ${s.reason}\n`;
      if (s.anchor) md += `- **Anchor:** ${s.anchor}\n`;
      md += "\n";
    });
  }

  if (d.notes) md += hr() + `## Notes\n\n${d.notes}\n`;
  return md;
}

// ── Elicitation Agenda ───────────────────────────────────────────────────────
function mdElicitationAgenda(d, title) {
  let md = `# ${title || "Elicitation Agenda"}\n\n`;
  const items = asArray(d.items || d.agenda_items || d.elicitation_items);

  md += `**Total items:** ${d.total_items ?? items.length}\n\n`;

  if (items.length) {
    md += `## Agenda Items\n\n`;
    items.forEach((item, i) => {
      const id = item.id || item.item_id || `IT-${i + 1}`;
      const perspective = item.perspective || item.role || "Stakeholder";
      const target = item.decision_target || item.elicitation_goal || "Evidence job";
      md += `### ${id}: ${target}\n\n`;
      md += `- **Perspective:** ${perspective}\n`;
      if (item.status && item.status !== "planned") md += `- **Status:** ${item.status}\n`;
      if (item.context || item.scene || item.baseline)
        md += `- **Context:** ${item.context || item.scene || item.baseline}\n`;
      if (item.seed_question || item.probe)
        md += `- **Question:** ${item.seed_question || item.probe}\n`;
      if (item.close_when || item.close)
        md += `- **Close when:** ${item.close_when || item.close}\n`;
      if (item.merge_anchor) md += `- **Merge:** ${item.merge_anchor}\n`;
      const refs = asArray(item.vision_refs);
      if (refs.length) md += `- **Vision refs:** ${refs.join(", ")}\n`;
      const cp = asArray(item.coverage_points);
      if (cp.length) {
        md += `- **Coverage points:**\n`;
        cp.forEach((p, j) => { md += `  ${j + 1}. ${txt(p)}\n`; });
      }
      if (item.notes) md += `- **Notes:** ${item.notes}\n`;
      md += "\n";
    });
  }

  if (d.notes) md += hr() + `## Notes\n\n${d.notes}\n`;
  return md;
}

// ── Interview Record ─────────────────────────────────────────────────────────
function mdInterviewRecord(d, title) {
  let md = `# ${title || "Interview Record"}\n\n`;
  const items = getInterviewItems(d);

  const answered = items.filter(i => i.status === "answered" || i.answer).length;
  md += `**Items:** ${d.total_items ?? items.length} | **Answered:** ${answered}\n\n`;

  if (items.length) {
    md += `## Conversation By Agenda Item\n\n`;
    items.forEach((item, i) => {
      const id = item.id || `EL-${i + 1}`;
      const stakeholder = item.perspective || item.role || item.stakeholder || "Stakeholder";
      const topic = item.decision_target || item.item || id;
      md += `### ${id}: ${topic}\n\n`;
      md += `- **Perspective:** ${stakeholder}\n`;
      md += `- **Status:** ${item.status || "-"}\n`;
      if (item.context) md += `- **Context:** ${item.context}\n`;
      md += "\n";

      const turns = asArray(item.talk);
      if (turns.length) {
        md += `#### Dialogue\n\n`;
        turns.forEach(t => {
          md += `> **Interviewer:** ${t.question || "-"}\n\n`;
          md += `> **${stakeholder}:** ${t.answer || "-"}\n\n`;
        });
      } else if (item.answer) {
        md += `**Answer:** ${item.answer}\n\n`;
      }

      if (item.rule) md += `**Closure rule:** ${item.rule}\n\n`;

      const sigs = asArray(item.signals);
      if (sigs.length) {
        md += `**Signals:**\n`;
        sigs.forEach(s => { md += `- ${txt(s)}\n`; });
        md += "\n";
      }
      const gaps = asArray(item.gaps);
      if (gaps.length) {
        md += `**Gaps:**\n`;
        gaps.forEach(g => { md += `- ${txt(g)}\n`; });
        md += "\n";
      }

      const cov = asArray(item.coverage);
      if (cov.length) {
        md += `**Coverage:**\n`;
        cov.forEach(c => {
          md += `- [${c.status || "-"}] ${c.point || txt(c)}${c.evidence ? ` — ${c.evidence}` : ""}\n`;
        });
        md += "\n";
      }

      const ae = asArray(item.assumption_evidence);
      if (ae.length) {
        md += `**Assumption Evidence:**\n`;
        ae.forEach(e => {
          md += `- ${e.vision_ref || "-"} (${e.stance || "-"})`;
          if (e.evidence) md += `: ${e.evidence}`;
          if (e.implication) md += ` — Implication: ${e.implication}`;
          md += "\n";
        });
        md += "\n";
      }
    });
  }

  if (d.notes) md += hr() + `## Notes\n\n${d.notes}\n`;
  return md;
}

function getInterviewItems(d) {
  if (Array.isArray(d?.items)) return d.items;
  if (Array.isArray(d?.elicitation_items)) return d.elicitation_items;
  if (Array.isArray(d?.requirements_identified)) return d.requirements_identified;
  return [];
}

// ── Requirement List ─────────────────────────────────────────────────────────
function mdRequirementList(d, title) {
  let md = `# ${title || "Requirement List"}\n\n`;
  const reqs = getRequirementItems(d);
  const conflicts = asArray(d.conflicts);
  const gaps = asArray(d.gaps || d.gaps_identified);

  md += `**Total requirements:** ${d.total_requirements ?? reqs.length}`;
  if (conflicts.length) md += ` | **Conflicts:** ${conflicts.length}`;
  if (gaps.length) md += ` | **Gaps:** ${gaps.length}`;
  md += "\n\n";

  if (reqs.length) {
    md += `## Requirements\n\n`;
    reqs.forEach((r, i) => {
      const id = r.id || r.req_id || `REQ-${i + 1}`;
      const type = r.type || r.req_type || "";
      md += `### ${id}${type ? ` [${type.replace(/_/g, " ")}]` : ""}\n\n`;
      const stmt = r.statement || r.description || r.question;
      if (stmt) md += `**${stmt}**\n\n`;
      if (r.stakeholder) md += `- **Stakeholder:** ${r.stakeholder}\n`;
      if (r.status) md += `- **Status:** ${r.status}\n`;
      if (r.confidence) md += `- **Confidence:** ${r.confidence}\n`;
      if (r.observable_outcome) md += `- **Outcome:** ${r.observable_outcome}\n`;
      if (r.rationale) md += `- **Why:** ${r.rationale}\n`;
      if (r.operating_condition) md += `- **Condition:** ${r.operating_condition}\n`;
      if (r.trigger_event) md += `- **Trigger:** ${r.trigger_event}\n`;
      if (r.product_object) md += `- **Object:** ${r.product_object}\n`;
      if (r.participation_structure) md += `- **Participation:** ${r.participation_structure}\n`;
      const refs = asArray(r.trace_refs);
      if (refs.length) md += `- **Trace refs:** ${refs.join(", ")}\n`;
      const ac = asArray(r.acceptance_criteria);
      if (ac.length) {
        md += `- **Acceptance criteria:**\n`;
        ac.forEach(c => { md += `  - ${txt(c)}\n`; });
      }
      md += "\n";
    });
  }

  if (conflicts.length) {
    md += `## Conflicts\n\n`;
    conflicts.forEach((c, i) => {
      md += `- **${c.id || `CF-${i + 1}`}** [${c.kind || "-"}]: ${txt(c.left)} vs ${txt(c.right)}`;
      if (c.issue) md += ` — ${c.issue}`;
      md += "\n";
    });
    md += "\n";
  }

  if (gaps.length) {
    md += `## Gaps\n\n`;
    gaps.forEach(g => { md += `- ${txt(g)}\n`; });
    md += "\n";
  }

  if (d.notes) md += hr() + `## Notes\n\n${d.notes}\n`;
  return md;
}

function getRequirementItems(d) {
  if (Array.isArray(d?.items)) return d.items;
  if (Array.isArray(d?.requirements)) return d.requirements;
  if (Array.isArray(d?.requirements_identified)) return d.requirements_identified;
  return [];
}

// ── Product Backlog ──────────────────────────────────────────────────────────
function mdProductBacklog(d, title) {
  let md = `# ${title || "Product Backlog"}\n\n`;
  const items = getBacklogItems(d);
  const totalPts = d.total_story_points ??
    items.reduce((s, i) => s + Number(i.estimation?.story_points ?? i.story_points ?? 0), 0);
  const ready = d.ready_count ??
    items.filter(i => (i.planning?.status ?? i.status) === "ready").length;

  md += `**Stories:** ${d.total_items ?? d.total_stories ?? items.length}`;
  md += ` | **Story Points:** ${totalPts}`;
  md += ` | **Ready:** ${ready}\n\n`;

  if (items.length) {
    md += `## Backlog Items\n\n`;
    items.forEach((item, i) => { md += mdPbiCard(item, i); });
  }

  if (d.methodology) {
    md += `## Methodology\n\n`;
    Object.entries(d.methodology).forEach(([k, v]) => {
      md += `- **${k.replace(/_/g, " ")}:** ${v}\n`;
    });
    md += "\n";
  }

  md += mdQualityWarnings(d.quality_warnings);
  if (d.notes) md += hr() + `## Notes\n\n${d.notes}\n`;
  return md;
}

// ── Validated Product Backlog ────────────────────────────────────────────────
function mdValidatedBacklog(d, title) {
  let md = `# ${title || "Validated Product Backlog"}\n\n`;
  const items = getBacklogItems(d);
  const stats = d.refinement_stats || {};
  const totalAc = stats.total_ac ??
    items.reduce((s, i) => s + asArray(i.quality?.acceptance_criteria ?? i.acceptance_criteria).length, 0);
  const ready = stats.ready_count ?? stats.ready_pbis ?? d.ready_count ??
    items.filter(i => (i.planning?.status ?? i.status) === "ready").length;
  const total = stats.total_pbis ?? d.total_items ?? items.length;

  md += `**Ready PBIs:** ${ready}/${total} | **Acceptance Criteria:** ${totalAc}\n\n`;

  if (items.length) {
    md += `## Validated PBIs\n\n`;
    items.forEach((item, i) => {
      md += mdPbiCard(item, i);
      // Acceptance Criteria (Gherkin)
      const ac = asArray(item.quality?.acceptance_criteria ?? item.acceptance_criteria);
      if (ac.length) {
        md += `**Acceptance Criteria:**\n\n`;
        ac.forEach((c, j) => {
          const acId = c.id || `AC-${j + 1}`;
          const acType = c.type ? ` [${c.type.replace(/_/g, " ")}]` : "";
          md += `- **${acId}${acType}**\n`;
          md += `  - Given: ${txt(c.given)}\n`;
          md += `  - When: ${txt(c.when)}\n`;
          md += `  - Then: ${txt(c.then)}\n`;
        });
        md += "\n";
      }
    });
  }

  md += mdQualityWarnings(d.quality_warnings);
  if (d.notes) md += hr() + `## Notes\n\n${d.notes}\n`;
  return md;
}

// ── Shared PBI card markdown ─────────────────────────────────────────────────
function mdPbiCard(item, index) {
  const id = item.id || item.pbi_id || `PBI-${index + 1}`;
  const est = item.estimation || {};
  const pri = item.prioritization || {};
  const plan = item.planning || {};
  const deps = item.dependencies || {};
  const analysis = item.analysis || {};
  const trace = item.requirement_trace || {};
  const quality = item.quality || {};

  let md = `### ${id}: ${item.title || item.description || id}\n\n`;
  if (item.type) md += `- **Type:** ${item.type.replace(/_/g, " ")}\n`;
  if (item.domain) md += `- **Domain:** ${item.domain}\n`;
  if (item.description) md += `- **Description:** ${item.description}\n`;

  const sp = est.story_points ?? item.story_points ?? 0;
  md += `- **Story Points:** ${sp}\n`;
  md += `- **Priority Rank:** ${pri.priority_rank ?? item.priority_rank ?? "-"}\n`;
  const wsjf = pri.wsjf_score ?? item.wsjf_score;
  md += `- **WSJF Score:** ${wsjf !== undefined ? Number(wsjf).toFixed(2) : "-"}\n`;
  md += `- **Planning Status:** ${(plan.status ?? item.status ?? "-").replace(/_/g, " ")}\n`;
  if (pri.business_value !== undefined) md += `- **Business Value:** ${pri.business_value}\n`;
  if (pri.time_criticality !== undefined) md += `- **Time Criticality:** ${pri.time_criticality}\n`;
  if (pri.risk_reduction !== undefined) md += `- **Risk Reduction:** ${pri.risk_reduction}\n`;

  // INVEST
  const investFlags = asArray(quality.invest_flags ?? item.invest_flags);
  const investKeys = ["independent", "negotiable", "valuable", "estimable", "small", "testable"];
  if (investFlags.length || quality.invest_pass !== undefined) {
    const result = investKeys.map(k => investFlags.includes(k) ? `~~${k}~~` : k).join(", ");
    md += `- **INVEST:** ${result}\n`;
  }

  // Dependencies
  const blockedBy = asArray(deps.blocked_by);
  const blocks = asArray(deps.blocks);
  if (blockedBy.length) md += `- **Blocked by:** ${blockedBy.join(", ")}\n`;
  if (blocks.length) md += `- **Blocks:** ${blocks.join(", ")}\n`;

  // Trace
  const traceParts = [trace.requirement_id, trace.entity, trace.step, trace.aspect].filter(Boolean);
  if (traceParts.length) md += `- **Trace:** ${traceParts.join(" / ")}\n`;
  if (trace.statement) md += `- **Requirement:** ${trace.statement}\n`;
  if (analysis.feasibility_notes) md += `- **Feasibility:** ${analysis.feasibility_notes}\n`;
  if (analysis.estimation_reasoning) md += `- **Estimation Reasoning:** ${analysis.estimation_reasoning}\n`;

  md += "\n";
  return md;
}

function getBacklogItems(d) {
  if (Array.isArray(d?.items)) return d.items;
  if (Array.isArray(d?.stories)) return d.stories;
  if (Array.isArray(d?.pbis)) return d.pbis;
  return [];
}

function mdQualityWarnings(warnings) {
  if (!warnings) return "";
  const entries = Object.entries(warnings).filter(([, v]) => asArray(v).length > 0);
  if (!entries.length) return "";
  let md = `## Quality Warnings\n\n`;
  entries.forEach(([key, vals]) => {
    md += `### ${key.replace(/_/g, " ")}\n\n`;
    asArray(vals).forEach(v => { md += `- ${txt(v)}\n`; });
    md += "\n";
  });
  return md;
}

// ── Fallback ─────────────────────────────────────────────────────────────────
function mdFallback(data, title) {
  return `# ${title || "Artifact"}\n\n\`\`\`json\n${JSON.stringify(data, null, 2)}\n\`\`\`\n`;
}

// ═════════════════════════════════════════════════════════════════════════════
// PDF Generation
// ═════════════════════════════════════════════════════════════════════════════
function generatePdf(markdownText, filename) {
  const doc = new jsPDF({ unit: "mm", format: "a4" });
  const pageW = doc.internal.pageSize.getWidth();
  const pageH = doc.internal.pageSize.getHeight();
  const marginL = 15;
  const marginR = 15;
  const marginTop = 20;
  const marginBot = 15;
  const maxW = pageW - marginL - marginR;
  let y = marginTop;

  const lines = markdownText.split("\n");

  for (const line of lines) {
    const trimmed = line.trimEnd();

    // Determine style
    let fontSize = 10;
    let fontStyle = "normal";
    let prefix = "";

    if (trimmed.startsWith("### ")) {
      fontSize = 12;
      fontStyle = "bold";
      prefix = trimmed.slice(4);
    } else if (trimmed.startsWith("## ")) {
      fontSize = 14;
      fontStyle = "bold";
      prefix = trimmed.slice(3);
    } else if (trimmed.startsWith("# ")) {
      fontSize = 18;
      fontStyle = "bold";
      prefix = trimmed.slice(2);
    } else if (trimmed.startsWith("---")) {
      // Draw horizontal rule
      if (y + 4 > pageH - marginBot) { doc.addPage(); y = marginTop; }
      y += 2;
      doc.setDrawColor(180, 180, 180);
      doc.line(marginL, y, pageW - marginR, y);
      y += 4;
      continue;
    } else if (trimmed === "") {
      y += 3;
      if (y > pageH - marginBot) { doc.addPage(); y = marginTop; }
      continue;
    } else {
      // Strip markdown bold markers for display
      prefix = trimmed.replace(/\*\*/g, "").replace(/~~/g, "");
    }

    if (prefix === "") prefix = trimmed.replace(/\*\*/g, "").replace(/~~/g, "");

    // Handle list prefix indentation
    let indent = 0;
    if (prefix.startsWith("  - ") || prefix.startsWith("  ")) {
      indent = 4;
      prefix = prefix.trimStart();
      if (prefix.startsWith("- ")) prefix = "  • " + prefix.slice(2);
    } else if (prefix.startsWith("- ")) {
      prefix = "• " + prefix.slice(2);
    } else if (/^\d+\.\s/.test(prefix)) {
      // keep numbered lists as-is
    } else if (prefix.startsWith("> ")) {
      prefix = "  " + prefix.slice(2);
      indent = 2;
    }

    doc.setFontSize(fontSize);
    doc.setFont("helvetica", fontStyle);

    const wrappedLines = doc.splitTextToSize(prefix, maxW - indent);
    const lineHeight = fontSize * 0.45;

    for (const wl of wrappedLines) {
      if (y + lineHeight > pageH - marginBot) {
        doc.addPage();
        y = marginTop;
      }
      doc.text(wl, marginL + indent, y);
      y += lineHeight;
    }

    // Extra spacing after headings
    if (fontSize > 10) y += 2;
  }

  doc.save(`${filename}.pdf`);
}
