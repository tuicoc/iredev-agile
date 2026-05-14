// src/components/chat/ChatHeader.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Top bar of the main chat area.
// Shows the active chat title (or "Claude" on the home screen),
// a model selector pill, and icon buttons for Share and New Chat.
// ─────────────────────────────────────────────────────────────────────────────
import { ChevronDown, Share2, SquarePen } from "lucide-react";
import { Tooltip } from "../ui";

export function ChatHeader({ activeChatId, chats, onNew, subChat, onSelect }) {
  const title = activeChatId
    ? (chats.find((c) => c.id === activeChatId)?.title ?? "Chat")
    : "Collaborative Agile Requirements Agent";

  return (
    <header
      className="flex items-center justify-between h-[52px] px-4
                       border-b border-[#E2D6C5] bg-[#F7F3EA] flex-shrink-0"
    >
      {/* Left: title + model pill */}
      <div className="flex items-center gap-2.5 min-w-0">
        <span className="text-[14px] font-semibold text-[#211914] truncate max-w-[260px]">
          {title}
        </span>

        {/* Conversation selector pill */}
        {activeChatId && (
          <select
            value={subChat}
            onChange={(e) => onSelect(activeChatId, e.target.value)}
            className="flex items-center gap-1 pl-2.5 pr-1.5 py-1
                           text-[12px] text-[#776B60] font-medium
                           bg-[#ECE3D6] hover:bg-[#D8CBBB]
                           rounded-full border border-[#D8CBBB]
                           transition-colors flex-shrink-0"
          >
            <option value={0}>Requirement Process</option>
            <option value={1}>Interviewer Conversation</option>
            <option value={2}>EndUser Conversation</option>
          </select>
        )}
      </div>

      {/* Right: icon actions */}
      <div className="flex items-center gap-0.5">
        <Tooltip text="Share">
          <button
            className="w-8 h-8 flex items-center justify-center rounded-lg
                             text-[#776B60] hover:bg-[#ECE3D6] hover:text-[#211914]
                             transition-colors"
          >
            <Share2 size={15} />
          </button>
        </Tooltip>
        <Tooltip text="New chat">
          <button
            onClick={onNew}
            className="w-8 h-8 flex items-center justify-center rounded-lg
                             text-[#776B60] hover:bg-[#ECE3D6] hover:text-[#211914]
                             transition-colors"
          >
            <SquarePen size={15} />
          </button>
        </Tooltip>
      </div>
    </header>
  );
}
