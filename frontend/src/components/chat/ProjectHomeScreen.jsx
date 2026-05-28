// src/components/chat/ProjectHomeScreen.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Shown in the main chat area when the user selects a project from the sidebar
// (but hasn't opened a specific chat yet).
// Displays project info + list of past requirement processes + start new button.
// ─────────────────────────────────────────────────────────────────────────────
import { useState, useEffect } from "react";
import { Clock, Trash2, FolderOpen, Plus } from "lucide-react";
import { fetchProjectChats, deleteChat } from "../../services/chatService";
import { LoadingSpinner } from "../ui/LoadingSpinner";

function formatDate(iso) {
  if (!iso) return "";
  const d   = new Date(iso);
  const now = new Date();
  const diff = (now - d) / 1000;
  if (diff < 60)              return "just now";
  if (diff < 3600)            return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400)           return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 86400 * 7)       return `${Math.floor(diff / 86400)}d ago`;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function ProjectHomeScreen({ project, onOpenChat, onCreateChat }) {
  const [chats,       setChats]       = useState([]);
  const [loading,     setLoading]     = useState(true);
  const [starting,    setStarting]    = useState(false);

  useEffect(() => {
    if (!project?.id) return;
    setLoading(true);
    fetchProjectChats(project.id)
      .then(setChats)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [project?.id]);

  const handleDelete = async (e, chatId) => {
    e.stopPropagation();
    await deleteChat(chatId).catch(() => {});
    setChats((prev) => prev.filter((c) => c.id !== chatId));
  };

  const handleCreate = async () => {
    if (starting) return;
    setStarting(true);
    await onCreateChat(project.id, project.name);
    setStarting(false);
  };

  return (
    <div className="flex flex-col h-full overflow-y-auto bg-white">
      <div className="max-w-[680px] w-full mx-auto px-6 py-10">

        {/* Project header */}
        <div className="flex items-start justify-between gap-4 mb-8">
          <div className="flex items-start gap-4 min-w-0">
            <div className="w-12 h-12 rounded-2xl bg-[#B86F50]/10 border border-[#B86F50]/20
                            flex items-center justify-center flex-shrink-0">
              <FolderOpen size={22} className="text-[#B86F50]" />
            </div>
            <div className="min-w-0">
              <h1 className="text-[22px] font-semibold text-[#1A1A1A] leading-tight truncate">
                {project.name}
              </h1>
              {project.description && (
                <p className="text-[13px] text-[#6B6B6B] mt-1 leading-relaxed">
                  {project.description}
                </p>
              )}
            </div>
          </div>

          <button
            onClick={handleCreate}
            disabled={starting}
            className="h-9 px-3 rounded-lg bg-[#B86F50] hover:bg-[#A76145]
                       text-white text-[13px] font-medium flex items-center gap-1.5
                       transition-colors shadow-sm disabled:opacity-60
                       disabled:cursor-not-allowed flex-shrink-0"
          >
            {starting ? <LoadingSpinner size={14} /> : <Plus size={15} />}
            New chat
          </button>
        </div>

        {/* Past processes */}
        <div>
          <div className="text-[11px] font-semibold text-[#95887C] uppercase mb-3">
            Requirement Processes
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-12">
              <LoadingSpinner size={20} className="text-[#B86F50]" />
            </div>
          ) : chats.length === 0 ? (
            <div className="text-center py-12">
              <div className="text-[#A8A8A8] text-[13px]">No processes yet</div>
              <div className="text-[#A8A8A8] text-[12px] mt-1">
                Create a new chat to start a requirements process
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              {chats.map((chat, idx) => (
                <div
                  key={chat.id}
                  onClick={() => onOpenChat(chat.id, project.id)}
                  className="flex items-center gap-4 px-4 py-3.5
                             bg-[#FFFFFF] border border-[#E5E5E5] rounded-xl
                             hover:border-[#C5C5C5] hover:bg-[#F8F8F8]
                             hover:shadow-[0_2px_8px_rgba(0,0,0,0.05)]
                             cursor-pointer transition-all duration-150 group"
                >
                  {/* Index circle */}
                  <div className="w-8 h-8 rounded-full bg-[#EFEFEF] flex items-center
                                  justify-center flex-shrink-0 text-[12px] font-semibold
                                  text-[#6B6B6B] group-hover:bg-[#DEDEDE]">
                    {chats.length - idx}
                  </div>

                  {/* Title + date */}
                  <div className="flex-1 min-w-0">
                    <div className="text-[13.5px] font-medium text-[#1A1A1A] truncate leading-snug">
                      {chat.title}
                    </div>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <Clock size={10} className="text-[#A8A8A8] flex-shrink-0" />
                      <span className="text-[11px] text-[#A0A0A0]">
                        {formatDate(chat.createdAt)}
                      </span>
                    </div>
                  </div>

                  {/* Delete button */}
                  <button
                    onClick={(e) => handleDelete(e, chat.id)}
                    className="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg
                               text-[#A8A8A8] hover:text-red-400 hover:bg-red-50
                               transition-all flex-shrink-0"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

    </div>
  );
}
