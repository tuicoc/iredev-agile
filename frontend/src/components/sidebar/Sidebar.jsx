// src/components/sidebar/Sidebar.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Sidebar with project folders.
// Clicking a project → opens ProjectHomeScreen in main area.
// Expanding the chevron → shows chat list inline.
// ─────────────────────────────────────────────────────────────────────────────
import { useState, useCallback, useEffect } from "react";
import {
  PanelLeftClose, PanelLeft, Search, Settings, LogOut,
  FolderOpen, Folder, Plus, Trash2, ChevronRight,
  MoreHorizontal, Pencil, Check, X,
} from "lucide-react";
import { Tooltip }        from "../ui";
import { LoadingSpinner } from "../ui/LoadingSpinner";
import { SettingsModal }  from "../settings/SettingsModal";
import { useAuth }        from "../../context/AuthContext";
import { AGENT_MOCK_MODE } from "../../config/env";
import { MOCK_CHAT_ID, MOCK_PROJECT_ID } from "../../data/agentMockData";
import {
  fetchProjects, createProject, deleteProject, updateProject,
  fetchProjectChats, deleteChat,
} from "../../services/chatService";

const MOCK_PROJECT = {
  id: MOCK_PROJECT_ID,
  name: "Mock Cafe Queue",
};

const MOCK_PROJECT_CHATS = [
  {
    id: MOCK_CHAT_ID,
    title: "Mock Agent Workflow",
  },
];

// ── Single chat row inside expanded folder ─────────────────────────────────
function ChatRow({ chat, isActive, onSelect, onDelete }) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      onClick={onSelect}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={`flex items-center gap-2 pl-8 pr-2 py-[6px] rounded-lg
                  cursor-pointer text-[12px] transition-colors duration-100
                  ${isActive
                    ? "bg-[#E5D9C9] text-[#211914]"
                    : "text-[#5B5048] hover:bg-[#E7DDCF]"}`}
    >
      <span className="flex-1 truncate leading-snug">{chat.title}</span>
      {hovered && (
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(chat.id); }}
          className="p-0.5 rounded text-[#B0A49A] hover:text-red-400 flex-shrink-0"
        >
          <Trash2 size={11} />
        </button>
      )}
    </div>
  );
}

// ── Inline rename input ────────────────────────────────────────────────────
function RenameInput({ value, onSave, onCancel }) {
  const [text, setText] = useState(value);
  function handleKey(e) {
    if (e.key === "Enter" && text.trim()) onSave(text.trim());
    if (e.key === "Escape") onCancel();
  }
  return (
    <div className="flex items-center gap-1 flex-1" onClick={(e) => e.stopPropagation()}>
      <input
        autoFocus
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKey}
        className="flex-1 min-w-0 bg-[#FFFDF8] border border-[#B86F50]/50 rounded px-1.5 py-0.5
                   text-[12px] text-[#211914] focus:outline-none focus:ring-1 focus:ring-[#B86F50]/30"
      />
      <button
        onClick={() => text.trim() && onSave(text.trim())}
        className="text-[#B86F50] hover:text-[#A76145] flex-shrink-0"
      >
        <Check size={12} />
      </button>
      <button onClick={onCancel} className="text-[#A89C91] hover:text-[#776B60] flex-shrink-0">
        <X size={12} />
      </button>
    </div>
  );
}

// ── Project folder row ─────────────────────────────────────────────────────
function ProjectFolder({
  project,
  isExpanded,
  isActive,        // true when this project's home is showing
  activeChatId,
  onOpenProject,   // click on name → show project home
  onToggleExpand,  // click on chevron → expand/collapse chat list
  onSelectChat,
  onDelete,
  onRename,
}) {
  const [showMenu,  setShowMenu]  = useState(false);
  const [renaming,  setRenaming]  = useState(false);
  const [chats,     setChats]     = useState([]);
  const [loadingChats, setLoadingChats] = useState(false);

  useEffect(() => {
    if (!isExpanded) return;
    if (AGENT_MOCK_MODE) {
      setChats(MOCK_PROJECT_CHATS);
      setLoadingChats(false);
      return;
    }
    setLoadingChats(true);
    fetchProjectChats(project.id)
      .then(setChats)
      .catch(() => {})
      .finally(() => setLoadingChats(false));
  }, [isExpanded, project.id]);

  // Expose refresh so parent can call it after a new chat is created
  const refreshChats = useCallback(() => {
    if (AGENT_MOCK_MODE) {
      setChats(MOCK_PROJECT_CHATS);
      return;
    }
    fetchProjectChats(project.id).then(setChats).catch(() => {});
  }, [project.id]);

  // Make refresh available via ref-like prop
  useEffect(() => {
    if (project._refreshRef) project._refreshRef.current = refreshChats;
  }, [project._refreshRef, refreshChats]);

  const handleDeleteChat = useCallback(async (chatId) => {
    if (AGENT_MOCK_MODE) return;
    await deleteChat(chatId).catch(() => {});
    setChats((prev) => prev.filter((c) => c.id !== chatId));
  }, []);

  return (
    <>
      {/* Folder row */}
      <div
        className={`group flex items-center gap-1.5 px-2 py-[7px] rounded-lg
                    cursor-pointer text-[13px] transition-colors duration-100 select-none
                    ${isActive && !activeChatId
                      ? "bg-[#E5D9C9] text-[#211914]"
                      : "text-[#4A4038] hover:bg-[#E7DDCF]"}`}
      >
        {/* Chevron — toggles expand/collapse */}
        <button
          onClick={(e) => { e.stopPropagation(); onToggleExpand(project.id); }}
          className="p-0.5 -ml-0.5 rounded hover:bg-black/[0.06] flex-shrink-0"
        >
          <ChevronRight
            size={13}
            className={`text-[#A89C91] transition-transform duration-150
                        ${isExpanded ? "rotate-90" : ""}`}
          />
        </button>

        {/* Folder icon */}
        {isExpanded || isActive
          ? <FolderOpen size={14} className="text-[#B86F50] flex-shrink-0" />
          : <Folder     size={14} className="text-[#776B60] flex-shrink-0 group-hover:text-[#B86F50]" />
        }

        {/* Name — clicking opens project home */}
        {renaming ? (
          <RenameInput
            value={project.name}
            onSave={(name) => { onRename(project.id, name); setRenaming(false); }}
            onCancel={() => setRenaming(false)}
          />
        ) : (
          <span
            className="flex-1 truncate font-medium leading-snug"
            onClick={() => onOpenProject(project)}
          >
            {project.name}
          </span>
        )}

        {/* Context menu */}
        {!renaming && (
          <div className="relative opacity-0 group-hover:opacity-100 flex-shrink-0">
            <button
              onClick={(e) => { e.stopPropagation(); setShowMenu((v) => !v); }}
              className="p-1 rounded hover:bg-[#D8CBBB] text-[#A89C91] hover:text-[#4A4038]"
            >
              <MoreHorizontal size={13} />
            </button>
            {showMenu && (
              <>
                <div className="fixed inset-0 z-30" onClick={() => setShowMenu(false)} />
                <div className="absolute right-0 top-5 ml-1 z-40 bg-[#FFFDF8] border border-[#E2D6C5]
                                rounded-xl shadow-lg py-1 w-[140px]">
                  <button
                    onClick={(e) => { e.stopPropagation(); setRenaming(true); setShowMenu(false); }}
                    className="w-full flex items-center gap-2 px-3 py-1.5 text-[12px]
                               text-[#4A4038] hover:bg-[#FCF8F1] transition-colors"
                  >
                    <Pencil size={11} className="text-[#776B60]" /> Rename
                  </button>
                  <div className="h-px bg-[#E9DFD1] my-1" />
                  <button
                    onClick={(e) => { e.stopPropagation(); onDelete(project.id); setShowMenu(false); }}
                    className="w-full flex items-center gap-2 px-3 py-1.5 text-[12px]
                               text-red-500 hover:bg-red-50 transition-colors"
                  >
                    <Trash2 size={11} /> Delete
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Expanded: inline chat list */}
      {isExpanded && (
        <div className="ml-1 mb-1">
          {loadingChats ? (
            <div className="flex items-center gap-2 pl-8 py-1.5">
              <LoadingSpinner size={10} className="text-[#B86F50]" />
              <span className="text-[11px] text-[#A89C91]">Loading…</span>
            </div>
          ) : chats.length === 0 ? (
            <div className="pl-8 py-1.5 text-[11px] text-[#B0A49A] italic">No processes yet</div>
          ) : (
            chats.map((chat) => (
              <ChatRow
                key={chat.id}
                chat={chat}
                isActive={chat.id === activeChatId}
                onSelect={() => onSelectChat(chat.id, project.id)}
                onDelete={handleDeleteChat}
              />
            ))
          )}
        </div>
      )}
    </>
  );
}

// ── Inline new project form ────────────────────────────────────────────────
function NewProjectForm({ onSave, onCancel }) {
  const [name, setName] = useState("");
  function handleKey(e) {
    if (e.key === "Enter" && name.trim()) onSave(name.trim());
    if (e.key === "Escape") onCancel();
  }
  return (
    <div className="flex items-center gap-1.5 px-2 py-1.5 mb-1">
      <Folder size={14} className="text-[#B86F50] flex-shrink-0" />
      <input
        autoFocus
        placeholder="Project name…"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={handleKey}
        className="flex-1 bg-[#FFFDF8] border border-[#B86F50]/50 rounded-lg px-2 py-1
                   text-[12px] text-[#211914] focus:outline-none focus:ring-1 focus:ring-[#B86F50]/30"
      />
      <button
        onClick={() => name.trim() && onSave(name.trim())}
        disabled={!name.trim()}
        className="text-[#B86F50] hover:text-[#A76145] disabled:opacity-30 flex-shrink-0"
      >
        <Check size={13} />
      </button>
      <button onClick={onCancel} className="text-[#A89C91] hover:text-[#776B60] flex-shrink-0">
        <X size={13} />
      </button>
    </div>
  );
}

// ── Main Sidebar export ────────────────────────────────────────────────────
export function Sidebar({ activeChatId, activeProjectId, onOpenProject, onSelectChat }) {
  const [projects,        setProjects]        = useState([]);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [expandedFolders, setExpandedFolders] = useState({}); // {projectId: bool}
  const [creatingProject, setCreatingProject] = useState(false);
  const [collapsed,       setCollapsed]       = useState(false);
  const [showSettings,    setShowSettings]    = useState(false);
  const [query,           setQuery]           = useState("");

  const { user, logout, authVersion } = useAuth();

  useEffect(() => {
    if (AGENT_MOCK_MODE) {
      setProjects([MOCK_PROJECT]);
      setExpandedFolders({ [MOCK_PROJECT_ID]: true });
      setLoadingProjects(false);
      return;
    }
    if (authVersion === 0) { setProjects([]); setLoadingProjects(false); return; }
    setLoadingProjects(true);
    fetchProjects()
      .then(setProjects)
      .catch(() => {})
      .finally(() => setLoadingProjects(false));
  }, [authVersion]);

  const handleCreateProject = async (name) => {
    if (AGENT_MOCK_MODE) {
      setCreatingProject(false);
      return;
    }
    setCreatingProject(false);
    try {
      const p = await createProject(name);
      setProjects((prev) => [p, ...prev]);
      // Auto-open + auto-expand new project
      onOpenProject(p);
      setExpandedFolders((prev) => ({ ...prev, [p.id]: true }));
    } catch {}
  };

  const handleDeleteProject = async (projectId) => {
    if (AGENT_MOCK_MODE) return;
    // If currently viewing this project, clear view
    if (activeProjectId === projectId) onOpenProject(null);
    try {
      await deleteProject(projectId);
      setProjects((prev) => prev.filter((p) => p.id !== projectId));
    } catch {}
  };

  const handleRenameProject = async (projectId, name) => {
    if (AGENT_MOCK_MODE) return;
    if (!name) return;
    try {
      const updated = await updateProject(projectId, { name });
      setProjects((prev) => prev.map((p) => (p.id === projectId ? updated : p)));
    } catch {}
  };

  const toggleExpand = (projectId) => {
    setExpandedFolders((prev) => ({ ...prev, [projectId]: !prev[projectId] }));
  };

  const filteredProjects = projects.filter((p) =>
    p.name.toLowerCase().includes(query.toLowerCase())
  );

  // ── Collapsed strip ──────────────────────────────────────────────────────
  if (collapsed) {
    return (
      <aside className="w-[52px] h-full flex flex-col items-center
                        bg-[#EFE8DC] border-r border-[#D8CBBB] py-3 gap-2 flex-shrink-0">
        <Tooltip text="Expand">
          <button
            onClick={() => setCollapsed(false)}
            className="w-8 h-8 flex items-center justify-center rounded-lg
                       text-[#776B60] hover:bg-[#E7DDCF] transition-colors"
          >
            <PanelLeft size={16} />
          </button>
        </Tooltip>
        <Tooltip text="New project">
          <button
            onClick={() => { setCollapsed(false); setCreatingProject(true); }}
            className="w-8 h-8 flex items-center justify-center rounded-lg
                       text-[#776B60] hover:bg-[#E7DDCF] transition-colors"
          >
            <Plus size={15} />
          </button>
        </Tooltip>
      </aside>
    );
  }

  // ── Expanded ─────────────────────────────────────────────────────────────
  return (
    <>
      <aside className="w-[260px] h-full flex flex-col flex-shrink-0
                        bg-[#EFE8DC] border-r border-[#D8CBBB]">
        {/* Logo + collapse */}
        <div className="flex items-center justify-between px-3 pt-3 pb-2">
          <div className="flex items-center gap-2">
            <div className="w-[26px] h-[26px] rounded-full bg-[#B86F50]
                            flex items-center justify-center flex-shrink-0">
              <span className="text-white text-[10px] font-semibold">C</span>
            </div>
            <span className="text-[13px] font-semibold text-[#211914]">
              CARA
            </span>
          </div>
          <Tooltip text="Close sidebar">
            <button
              onClick={() => setCollapsed(true)}
              className="w-7 h-7 flex items-center justify-center rounded-lg
                         text-[#776B60] hover:bg-[#E7DDCF] transition-colors"
            >
              <PanelLeftClose size={15} />
            </button>
          </Tooltip>
        </div>

        {/* New Project */}
        <div className="px-2 pb-2">
          <button
            onClick={() => setCreatingProject(true)}
            className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg
                       text-[13px] text-[#4A4038] hover:bg-[#E7DDCF] transition-colors"
          >
            <Plus size={14} className="text-[#B86F50]" />
            New project
          </button>
        </div>

        {/* Search */}
        <div className="px-2 pb-2">
          <div className="relative">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#A89C91]" />
            <input
              type="text"
              placeholder="Search projects…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full pl-7 pr-3 py-1.5 bg-[#F7F3EA]/70 border border-[#D8CBBB]
                         rounded-lg text-[12px] text-[#211914] placeholder:text-[#A89C91]
                         focus:outline-none focus:ring-1 focus:ring-[#B86F50]/30
                         focus:border-[#B86F50]/40 transition-all"
            />
          </div>
        </div>

        {/* Project list */}
        <div className="flex-1 overflow-y-auto px-2 pb-2">
          {creatingProject && (
            <NewProjectForm
              onSave={handleCreateProject}
              onCancel={() => setCreatingProject(false)}
            />
          )}

          {loadingProjects && projects.length === 0 && (
            <div className="flex items-center justify-center py-8">
              <LoadingSpinner size={18} className="text-[#B86F50]" />
            </div>
          )}

          {!loadingProjects && filteredProjects.length === 0 && !creatingProject && (
            <div className="px-3 py-8 text-center">
              <div className="text-[#A89C91] text-[12px]">No projects yet</div>
              <button
                onClick={() => setCreatingProject(true)}
                className="mt-2 text-[12px] text-[#B86F50] hover:underline"
              >
                Create your first project
              </button>
            </div>
          )}

          {filteredProjects.map((project) => (
            <ProjectFolder
              key={project.id}
              project={project}
              isExpanded={!!expandedFolders[project.id]}
              isActive={project.id === activeProjectId}
              activeChatId={activeChatId}
              onOpenProject={onOpenProject}
              onToggleExpand={toggleExpand}
              onSelectChat={(chatId, projId) => onSelectChat(chatId, projId)}
              onDelete={handleDeleteProject}
              onRename={handleRenameProject}
            />
          ))}
        </div>

        {/* Bottom nav */}
        <div className="border-t border-[#D8CBBB] p-2 space-y-0.5">
          <button
            onClick={() => setShowSettings(true)}
            className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg
                       text-[12px] text-[#776B60] hover:bg-[#E7DDCF]
                       hover:text-[#4A4038] transition-colors"
          >
            <Settings size={13} /> Settings
          </button>
          <div className="flex items-center gap-2.5 px-2.5 py-2 mt-0.5 rounded-lg group">
            <div className="w-6 h-6 rounded-full bg-[#776B60] flex items-center
                            justify-center flex-shrink-0">
              <span className="text-white text-[10px] font-semibold">
                {(user?.name || user?.email || "U")[0].toUpperCase()}
              </span>
            </div>
            <span className="text-[12px] text-[#4A4038] truncate flex-1">
              {user?.email || "user@example.com"}
            </span>
            <Tooltip text="Sign out">
              <button
                onClick={logout}
                className="opacity-0 group-hover:opacity-100 w-5 h-5 flex items-center
                           justify-center rounded text-[#A89C91] hover:text-red-400 transition-all"
              >
                <LogOut size={12} />
              </button>
            </Tooltip>
          </div>
        </div>
      </aside>

      <SettingsModal open={showSettings} onClose={() => setShowSettings(false)} />
    </>
  );
}
