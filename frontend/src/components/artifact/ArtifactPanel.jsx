// src/components/artifact/ArtifactPanel.jsx
// =============================================================================
// Right-side panel with smart tabs based on artifact type.
//
// interview_record          → tabs: Interview
// product_vision            → tabs: Vision
// elicitation_agenda        → tabs: Elicitation Agenda
// requirement_list          → tabs: Requirements
// user_story_draft          → tabs: JSON (raw view)
// analyst_estimation        → tabs: JSON (raw view)
// product_backlog           → tabs: Backlog
// product_backlog_approved  → tabs: Backlog
// validated_product_backlog → tabs: Validated Backlog
// fallback                  → tabs: JSON (raw view)
// =============================================================================
import { useState, useMemo, useEffect } from "react";
import {
  Copy,
  Check,
  X,
  List,
  ClipboardList,
  CheckSquare,
  Code2,
  File,
} from "lucide-react";
import { Tooltip } from "../ui";
import { ArtifactFeedbackBar } from "./ArtifactFeedbackBar";
import { DownloadDropdown } from "./DownloadDropdown";
import {
  TranscriptView,
  RequirementsView,
  InterviewRecordRequirementsView,
} from "./views/InterviewRecordView";
import { ProductBacklogView } from "./views/ProductBacklogView";
import { ValidatedBacklogView } from "./views/ValidatedBacklogView";
import ProductVisionView from "./views/ProductVisionView";
import { ElicitationAgendaView } from "./views/ElicitationAgendaView";
import { useChat } from "../../context/ChatContext";

// ── Detect artifact type from content ────────────────────────────────────────
function detectArtifactType(artifact) {
  if (artifact?.type) return artifact.type;
  if (!artifact?.content) return "unknown";

  let data = null;
  try {
    data =
      typeof artifact.content === "string"
        ? JSON.parse(artifact.content)
        : artifact.content;
  } catch {
    return "text";
  }

  if (!data) return "unknown";

  return "json";
}

// ── Tab definitions per artifact type ────────────────────────────────────────
function getTabsForType(artifactType) {
  switch (artifactType) {
    case "interview_record":
      return [
        { id: "interview_requirements", label: "Interview", icon: List },
      ];
    case "requirement_list":
      return [
        // { id: "transcript", label: "Transcript", icon: FileText },
        { id: "requirements", label: "Requirements", icon: List },
      ];
    case "product_backlog":
      return [{ id: "backlog", label: "Backlog", icon: ClipboardList }];
    case "product_vision":
      return [{ id: "vision", label: "Vision", icon: List }];
    case "elicitation_agenda":
      return [
        { id: "elicitation_agenda", label: "Elicitation Agenda", icon: List },
      ];
    case "validated_product_backlog":
      return [
        { id: "validated", label: "Validated Backlog", icon: CheckSquare },
      ];
    default:
      return [{ id: "json", label: "JSON", icon: Code2 }];
  }
}

// ── Friendly display name per artifact type ──────────────────────────────────
export function getArtifactDisplayName(artifactType) {
  const NAMES = {
    interview_record: "Interview Record",
    product_vision: "Product Vision",
    elicitation_agenda: "Elicitation Agenda",
    requirement_list: "Requirement List",
    user_story_draft: "User Story Draft",
    analyst_estimation: "Analyst Estimation",
    product_backlog: "Product Backlog",
    validated_product_backlog: "Validated Product Backlog",
  };
  return NAMES[artifactType] || String(artifactType || "artifact").replace(/_/g, " ");
}

// ── JSON fallback view ────────────────────────────────────────────────────────
function JsonView({ content }) {
  let pretty =
    typeof content === "string"
      ? content
      : JSON.stringify(content ?? "", null, 2);
  try {
    pretty = JSON.stringify(JSON.parse(pretty), null, 2);
  } catch {}

  const lines = (pretty || "").split("\n");
  return (
    <div className="h-full bg-[#F6F1E8] p-4 overflow-auto">
      <pre className="text-[11.5px] font-mono text-[#302822] leading-relaxed">
        {lines.map((line, i) => (
          <div
            key={i}
            className="flex gap-4 hover:bg-black/[0.025] px-1 rounded"
          >
            <span className="select-none text-[#B0A49A] text-right w-6 flex-shrink-0">
              {i + 1}
            </span>
            <span>{line || " "}</span>
          </div>
        ))}
      </pre>
    </div>
  );
}

// ── Main ArtifactPanel ────────────────────────────────────────────────────────
export function ArtifactPanel({
  artifact,
  onClose,
  onAccept,
  onRevise,
  messages,
  onOpenArtifact,
}) {
  const { setOpenArtifact } = useChat();
  const artifactList = useMemo(
    () => messages.filter((mess) => !!mess.artifact?.content),
    [messages],
  );

  const artifactType = useMemo(
    () => detectArtifactType(artifact),
    [artifact?.content, artifact?.type],
  );
  const tabs = useMemo(() => getTabsForType(artifactType), [artifactType]);

  const [activeTab, setActiveTab] = useState(() => tabs[0]?.id);
  const [copied, setCopied] = useState(false);

  // When artifact changes, reset tab if current tab doesn't exist in new tabs.
  useEffect(() => {
    if (!tabs.find((t) => t.id === activeTab)) {
      setActiveTab(tabs[0]?.id);
    }
  }, [tabs, activeTab]);

  // Parse the JSON content once
  const parsedData = useMemo(() => {
    if (!artifact?.content) return null;
    try {
      return typeof artifact.content === "string"
        ? JSON.parse(artifact.content)
        : artifact.content;
    } catch {
      return null;
    }
  }, [artifact?.content]);

  function handleCopy() {
    navigator.clipboard?.writeText(
      typeof artifact?.content === "string"
        ? artifact.content
        : JSON.stringify(artifact?.content ?? "", null, 2),
    );
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }



  const iconBtn =
    "w-7 h-7 flex items-center justify-center rounded-md " +
    "text-[#776B60] hover:text-[#211914] hover:bg-[#ECE3D6] transition-colors";

  // ── Render active tab content ───────────────────────────────────────────────
  function renderTabContent() {
    if (!parsedData && activeTab !== "json") {
      return <JsonView content={artifact?.content || ""} />;
    }

    switch (activeTab) {
      case "transcript":
        return <TranscriptView data={parsedData} />;
      case "interview_requirements":
        return <InterviewRecordRequirementsView data={parsedData} />;
      case "requirements":
        return <RequirementsView data={parsedData} />;
      case "backlog":
        return <ProductBacklogView data={parsedData} />;
      case "validated":
        return <ValidatedBacklogView data={parsedData} />;
      case "vision":
        return <ProductVisionView data={parsedData} />;
      case "elicitation_agenda":
        return <ElicitationAgendaView data={parsedData} />;
      case "json":
      default:
        return <JsonView content={artifact?.content || ""} />;
    }
  }

  return (
    <div className="flex flex-col h-full bg-[#FFFDF8] panel-enter">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div
        className="flex items-center gap-3 px-4 h-[52px]
                      border-b border-[#E2D6C5] bg-[#FBF7F0] flex-shrink-0"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-semibold text-[#211914] truncate leading-tight">
              {artifact?.title || "Artifact"}
            </span>
            {artifact?.iteration && (
              <span className="px-1.5 py-0.5 bg-[#ECE3D6] rounded text-[10px] font-medium text-[#776B60] flex-shrink-0">
                v{artifact.iteration}
              </span>
            )}
            {artifact?.accepted && (
              <span
                className="flex items-center gap-1 px-1.5 py-0.5
                               bg-green-50 border border-green-200
                               rounded text-[10px] font-medium text-green-700 flex-shrink-0"
              >
                <Check size={9} /> Accepted
              </span>
            )}
          </div>
          <div className="text-[10.5px] text-[#776B60] capitalize leading-tight">
            {getArtifactDisplayName(artifactType)}
            {artifact?.awaitingFeedback && (
              <span className="ml-1.5 text-[#B86F50]">· awaiting feedback</span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-0.5">
          <Tooltip text={copied ? "Copied!" : "Copy JSON"}>
            <button onClick={handleCopy} className={iconBtn}>
              {copied ? <Check size={14} /> : <Copy size={14} />}
            </button>
          </Tooltip>
          <DownloadDropdown
            data={parsedData}
            rawContent={artifact?.content}
            artifactType={artifactType}
            title={artifact?.title || getArtifactDisplayName(artifactType)}
            iconBtnClass={iconBtn}
          />
          <div className="w-px h-4 bg-[#E2D6C5] mx-0.5" />
          <Tooltip text="Close">
            <button onClick={onClose} className={iconBtn}>
              <X size={14} />
            </button>
          </Tooltip>
        </div>
      </div>

      {artifactList.length > 1 && (
        <div className="flex gap-1 px-4 border-b border-[#E2D6C5] bg-[#FBF7F0] flex-shrink-0 overflow-y-auto w-full">
          {artifactList.map((tab, idx) => {
            const isActive =
              tab.id === artifact?.messageId ||
              (tab.artifact.type === artifact?.type &&
                tab.artifact.iteration === artifact?.iteration);
            return (
              <button
                key={idx}
                onClick={() =>
                  setOpenArtifact({ ...tab.artifact, messageId: tab.id })
                }
                className={`whitespace-nowrap flex items-center gap-1.5 px-3 py-2.5 text-[12px] font-medium
                            border-b-2 -mb-px transition-colors ${
                              isActive
                                ? "border-[#B86F50] text-[#B86F50]"
                                : "border-transparent text-[#776B60] hover:text-[#211914]"
                            }`}
              >
                <File size={12} />
                {getArtifactDisplayName(tab.artifact.type)}
                {tab.artifact.iteration && (
                  <span className="text-[10px] font-semibold text-inherit opacity-75">
                    v{tab.artifact.iteration}
                  </span>
                )}
                {tab.artifact.accepted && (
                  <span className="text-[10px] font-medium text-green-700">
                    Accepted
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}

      {/* ── Tab bar ─────────────────────────────────────────────────────── */}
      {tabs.length > 1 && (
        <div className="flex gap-1 px-4 border-b border-[#E2D6C5] bg-[#FBF7F0] flex-shrink-0">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-1.5 px-3 py-2.5 text-[12px] font-medium
                            border-b-2 -mb-px transition-colors ${
                              tab.id === activeTab
                                ? "border-[#B86F50] text-[#B86F50]"
                                : "border-transparent text-[#776B60] hover:text-[#211914]"
                            }`}
              >
                <Icon size={12} />
                {tab.label}
              </button>
            );
          })}
        </div>
      )}

      {/* ── Body ────────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-hidden">{renderTabContent()}</div>

      {/* ── Feedback bar ────────────────────────────────────────────────── */}
      {artifact?.awaitingFeedback &&
        !artifact?.accepted &&
        onAccept &&
        onRevise && (
          <ArtifactFeedbackBar
            artifact={artifact}
            iteration={artifact.iteration ?? 1}
            onAccept={onAccept}
            onRevise={onRevise}
          />
        )}
    </div>
  );
}
