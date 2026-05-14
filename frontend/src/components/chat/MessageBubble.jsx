// src/components/chat/MessageBubble.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Renders a single chat message — handles both user and assistant roles.
//
// User messages:    plain text, right-aligned, warm-grey bubble
// Assistant messages: rich content (markdown, code blocks), left-aligned,
//                     optional artifact preview card below
// ─────────────────────────────────────────────────────────────────────────────
import { AssistantContent } from "./AssistantContent";
import { MessageActions } from "./MessageActions";
import { ArtifactPreviewCard } from "../artifact/ArtifactPreviewCard";
import { RotateCcw } from "lucide-react";

const AGENT_BY_ARTIFACT = {
  product_vision: "Visionary Agent",
  elicitation_agenda: "Agenda Agent",
  interview_record: "Interviewer Agent",
  requirement_list: "Distiller Agent",
  product_backlog: "Sprint Agent",
  validated_product_backlog: "Analyst Agent",
};

function agentNameFor(message) {
  if (message.agentName) return message.agentName;
  if (message.artifact?.agentName) return message.artifact.agentName;
  if (message.artifact?.type && AGENT_BY_ARTIFACT[message.artifact.type]) {
    return AGENT_BY_ARTIFACT[message.artifact.type];
  }
  if (message.role === "interviewer") return "Interviewer Agent";
  if (message.role === "enduser") {
    const stakeholder = message.messageMeta?.stakeholderRole;
    return stakeholder ? `${stakeholder} (EndUser Agent)` : "EndUser Agent";
  }

  const content = message.content || "";
  if (content.includes("Product Vision")) return "Visionary Agent";
  if (content.includes("Elicitation Agenda")) return "Agenda Agent";
  if (content.includes("Requirements Interview")) return "Interviewer Agent";
  if (content.includes("Requirement List")) return "Distiller Agent";
  if (content.includes("Product Backlog")) return "Sprint Agent";
  if (content.includes("Acceptance Criteria") || content.includes("Validated Product Backlog")) {
    return "Analyst Agent";
  }
  return "CARA";
}

function ConversationContext({ meta }) {
  if (!meta || !Object.keys(meta).length) return null;

  const hasIndexedItem =
    meta.agendaItemIndex != null && meta.agendaTotalItems != null;
  const itemLabel = hasIndexedItem
    ? `Item ${meta.agendaItemIndex}/${meta.agendaTotalItems}`
    : meta.agendaItemId
      ? `Item ${meta.agendaItemId}`
      : "";
  const topic = [meta.entity, meta.step].filter(Boolean).join(" / ");
  const parts = [itemLabel, topic].filter(Boolean);

  if (!parts.length) return null;

  return (
    <span className="text-[10.5px] font-normal leading-snug text-[#9A8F84]">
      {" "}
      · {parts.join(" · ")}
    </span>
  );
}

export function MessageBubble({ message, onOpenArtifact, onRetry }) {
  const isUser = message.role === "user";
  const isEnduser = message.role === "enduser";
  const isInterviewer = message.role === "interviewer";
  const isRightSide = isUser || isEnduser;
  const isConversationAgent = isEnduser || isInterviewer;
  const agentName = isUser ? null : agentNameFor(message);
  const canRetry = !isUser && (message.cancelled || message.isError);
  const avatarInitial = isUser ? "U" : (agentName || message.role || "C").charAt(0).toUpperCase();

  return (
    <div
      className={`flex gap-3 msg-enter ${isRightSide ? "justify-end" : "justify-start"}`}
    >
      {!isRightSide && (
        <div
          className={`w-7 h-7 rounded-full flex items-center justify-center
                         flex-shrink-0 mt-0.5 shadow-sm
                         ${message.isRevision ? "bg-[#7A644F]" : "bg-[#B86F50]"}`}
        >
          {message.isRevision ? (
            <RotateCcw size={12} className="text-white" />
          ) : (
            <span className="text-white text-[10px] font-semibold">
              {avatarInitial}
            </span>
          )}
        </div>
      )}

      <div
        className={`flex flex-col gap-2 ${isRightSide ? "items-end max-w-[75%]" : "items-start max-w-[85%]"}`}
      >
        {!isUser && (
          <div
            className={`flex flex-wrap items-baseline gap-x-1 text-[11px] font-medium leading-snug text-[#776B60] mt-0.5 ${
              isEnduser ? "justify-end text-right" : ""
            }`}
          >
            <span>{agentName}</span>
            {isConversationAgent && (
              <ConversationContext meta={message.messageMeta} />
            )}
          </div>
        )}

        {/* Revision label */}
        {message.isRevision && (
          <div className="flex items-center gap-1.5 text-[11px] text-[#7A644F] font-medium -mb-1">
            <RotateCcw size={11} />
            Revision v{message.iteration}
            {message.revisionComment && (
              <span className="text-[#776B60] font-normal">
                — "{message.revisionComment}"
              </span>
            )}
          </div>
        )}

        {/* Bubble */}
        {(isUser || !message.artifact) && (
          <div
            className={`text-[14px] leading-[1.65] ${
              isUser
                ? "bg-[#ECE3D6] text-[#211914] px-4 py-2.5 rounded-[18px] rounded-br-[4px]"
                : isEnduser
                  ? "bg-[#DDE8E0] text-[#17221D] px-4 py-2.5 rounded-[18px] rounded-br-[4px] border border-[#C6D7CB]"
                  : isInterviewer
                    ? "bg-[#FFFDF8] text-[#211914] px-4 py-2.5 rounded-[18px] rounded-bl-[4px] border border-[#E2D6C5]"
                    : "text-[#211914] px-0 py-0"
            }`}
          >
            {isUser || isConversationAgent ? (
              <p className="whitespace-pre-wrap">{message.content}</p>
            ) : (
              <AssistantContent
                content={message.content}
                streaming={message.streaming}
              />
            )}
            {message.cancelled && (
              <div className="mt-2 inline-flex items-center gap-1.5 rounded-full
                              border border-[#D8CBBB] bg-[#F6F1E8] px-2 py-1
                              text-[11px] font-medium text-[#776B60]">
                <span className="h-1.5 w-1.5 rounded-full bg-[#B86F50]" />
                Generation stopped
              </div>
            )}
          </div>
        )}

        {/* Artifact preview card */}
        {!isUser && message.artifact && !message.streaming && (
          <ArtifactPreviewCard
            artifact={message.artifact}
            onOpen={() => onOpenArtifact(message.artifact)}
          />
        )}

        {/* Action buttons */}
        {!isUser &&
          !message.streaming &&
          !message.isRevision &&
          !message.isSystemPrompt &&
          (message.content || message.cancelled) && (
            <MessageActions
              content={message.content}
              onRetry={canRetry ? () => onRetry?.(message.id) : null}
            />
          )}
      </div>

      {isRightSide && (
        <div
          className={`w-7 h-7 rounded-full flex items-center
                        justify-center flex-shrink-0 mt-0.5 shadow-sm ${
                          isEnduser ? "bg-[#4F7B63]" : "bg-[#776B60]"
                        }`}
        >
          <span className="text-white text-[10px] font-semibold">{avatarInitial}</span>
        </div>
      )}
    </div>
  );
}
