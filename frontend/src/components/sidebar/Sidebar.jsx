// src/components/sidebar/Sidebar.jsx
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
  fetchProjectChats, deleteChat, BASE_PROJECT_NAME,
} from "../../services/chatService";

// ── Color tokens (Claude-aligned neutral palette) ──────────────────────────
const S = {
  bg:         "#F3F3F3",   // sidebar background
  border:     "#E5E5E5",   // dividers
  hover:      "#EBEBEB",   // hover row
  active:     "#E3E3E3",   // active/selected
  text:       "#1A1A1A",   // primary text
  muted:      "#6B6B6B",   // secondary text / icons
  icon:       "#6B6B6B",   // icon default color
  brand:      "#B86F50",   // CARA brand (logo only)
  inputBg:    "#FAFAFA",
  inputBorder:"#D9D9D9",
};

const MOCK_PROJECT       = { id: MOCK_PROJECT_ID, name: "Mock Cafe Queue" };
const MOCK_PROJECT_CHATS = [{ id: MOCK_CHAT_ID, title: "Mock Agent Workflow" }];

// ── Single chat row ─────────────────────────────────────────────────────────
function ChatRow({ chat, isActive, onSelect, onDelete }) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      onClick={onSelect}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{ backgroundColor: isActive ? S.active : hovered ? S.hover : "transparent" }}
      className="flex items-center gap-2 pl-8 pr-2 py-[6px] rounded-lg
                 cursor-pointer text-[12px] transition-colors duration-100"
    >
      <span className="flex-1 truncate leading-snug" style={{ color: isActive ? S.text : S.muted }}>
        {chat.title}
      </span>
      {hovered && (
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(chat.id); }}
          className="p-0.5 rounded transition-colors flex-shrink-0"
          style={{ color: S.muted }}
          onMouseEnter={e => e.currentTarget.style.color = "#E53E3E"}
          onMouseLeave={e => e.currentTarget.style.color = S.muted}
        >
          <Trash2 size={11} />
        </button>
      )}
    </div>
  );
}

// ── Inline rename input ─────────────────────────────────────────────────────
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
        className="flex-1 min-w-0 rounded px-1.5 py-0.5 text-[12px] focus:outline-none"
        style={{
          background: S.inputBg,
          border: `1px solid ${S.brand}60`,
          color: S.text,
        }}
      />
      <button onClick={() => text.trim() && onSave(text.trim())} style={{ color: S.brand }} className="flex-shrink-0">
        <Check size={12} />
      </button>
      <button onClick={onCancel} style={{ color: S.muted }} className="flex-shrink-0">
        <X size={12} />
      </button>
    </div>
  );
}

// ── Base project chat list (flat, no folder header) ─────────────────────────
function BaseChatList({ baseProject, activeChatId, onSelectChat }) {
  const [chats, setChats] = useState([]);

  useEffect(() => {
    if (!baseProject?.id) return;
    fetchProjectChats(baseProject.id).then(setChats).catch(() => {});
  }, [baseProject?.id, activeChatId]); // refresh whenever active chat changes (new chat created)

  const handleDelete = useCallback(async (chatId) => {
    await deleteChat(chatId).catch(() => {});
    setChats((prev) => prev.filter((c) => c.id !== chatId));
  }, []);

  if (!baseProject || chats.length === 0) return null;

  return (
    <div className="mb-1">
      {chats.map((chat) => (
        <ChatRow
          key={chat.id}
          chat={chat}
          isActive={chat.id === activeChatId}
          onSelect={() => onSelectChat(chat.id, baseProject.id)}
          onDelete={handleDelete}
        />
      ))}
      <div className="h-px mx-1 my-2" style={{ background: S.border }} />
    </div>
  );
}

// ── Project folder row ──────────────────────────────────────────────────────
function ProjectFolder({
  project, isExpanded, isActive, activeChatId,
  onOpenProject, onToggleExpand, onSelectChat, onDelete, onRename, onCreateChat,
}) {
  const [showMenu,     setShowMenu]     = useState(false);
  const [renaming,     setRenaming]     = useState(false);
  const [chats,        setChats]        = useState([]);
  const [loadingChats, setLoadingChats] = useState(false);
  const [hovered,      setHovered]      = useState(false);

  useEffect(() => {
    if (!isExpanded) return;
    if (AGENT_MOCK_MODE) { setChats(MOCK_PROJECT_CHATS); return; }
    setLoadingChats(true);
    fetchProjectChats(project.id).then(setChats).catch(() => {}).finally(() => setLoadingChats(false));
  }, [isExpanded, project.id]);

  const refreshChats = useCallback(() => {
    if (AGENT_MOCK_MODE) { setChats(MOCK_PROJECT_CHATS); return; }
    fetchProjectChats(project.id).then(setChats).catch(() => {});
  }, [project.id]);

  useEffect(() => {
    if (project._refreshRef) project._refreshRef.current = refreshChats;
  }, [project._refreshRef, refreshChats]);

  const handleDeleteChat = useCallback(async (chatId) => {
    if (AGENT_MOCK_MODE) return;
    await deleteChat(chatId).catch(() => {});
    setChats((prev) => prev.filter((c) => c.id !== chatId));
  }, []);

  const isRowActive = isActive && !activeChatId;
  const rowBg = isRowActive ? S.active : hovered ? S.hover : "transparent";

  return (
    <>
      <div
        className="group flex items-center gap-1.5 px-2 py-[7px] rounded-lg
                   cursor-pointer text-[13px] transition-colors duration-100 select-none"
        style={{ backgroundColor: rowBg, color: S.text }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {/* Chevron */}
        <button
          onClick={(e) => { e.stopPropagation(); onToggleExpand(project.id); }}
          className="p-0.5 -ml-0.5 rounded flex-shrink-0"
          style={{ color: S.muted }}
        >
          <ChevronRight
            size={12}
            className={`transition-transform duration-200 ${isExpanded ? "rotate-90" : ""}`}
          />
        </button>

        {/* Folder icon */}
        <div className="flex-shrink-0 flex items-center justify-center w-5 h-5">
          {isExpanded || isActive
            ? <FolderOpen size={15} style={{ color: S.text }} />
            : <Folder     size={15} style={{ color: hovered ? S.text : S.icon }} />
          }
        </div>

        {/* Name */}
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
              className="p-1 rounded transition-colors"
              style={{ color: S.muted }}
            >
              <MoreHorizontal size={13} />
            </button>
            {showMenu && (
              <>
                <div className="fixed inset-0 z-30" onClick={() => setShowMenu(false)} />
                <div
                  className="absolute right-0 top-5 z-40 rounded-xl shadow-lg py-1 w-[140px]"
                  style={{ background: "#FFFFFF", border: `1px solid ${S.border}` }}
                >
                  <button
                    onClick={(e) => { e.stopPropagation(); setRenaming(true); setShowMenu(false); }}
                    className="w-full flex items-center gap-2 px-3 py-1.5 text-[12px] transition-colors hover:bg-[#F3F3F3]"
                    style={{ color: S.text }}
                  >
                    <Pencil size={11} style={{ color: S.muted }} /> Rename
                  </button>
                  <div className="h-px my-1" style={{ background: S.border }} />
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

      {isExpanded && (
        <div className="ml-1 mb-1">
          {loadingChats ? (
            <div className="flex items-center gap-2 pl-8 py-1.5">
              <LoadingSpinner size={10} style={{ color: S.brand }} />
              <span className="text-[11px]" style={{ color: S.muted }}>Loading…</span>
            </div>
          ) : chats.length === 0 ? (
            <div className="pl-8 py-1.5 text-[11px] italic" style={{ color: S.muted }}>No processes yet</div>
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

// ── New project form ─────────────────────────────────────────────────────────
function NewProjectForm({ onSave, onCancel }) {
  const [name, setName] = useState("");
  function handleKey(e) {
    if (e.key === "Enter" && name.trim()) onSave(name.trim());
    if (e.key === "Escape") onCancel();
  }
  return (
    <div className="flex items-center gap-1.5 px-2 py-1.5 mb-1">
      <Folder size={13} style={{ color: S.icon }} className="flex-shrink-0" />
      <input
        autoFocus
        placeholder="Project name…"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={handleKey}
        className="flex-1 rounded-lg px-2 py-1 text-[12px] focus:outline-none"
        style={{
          background: S.inputBg,
          border: `1px solid ${S.brand}50`,
          color: S.text,
        }}
      />
      <button
        onClick={() => name.trim() && onSave(name.trim())}
        disabled={!name.trim()}
        className="flex-shrink-0 disabled:opacity-30"
        style={{ color: S.brand }}
      >
        <Check size={13} />
      </button>
      <button onClick={onCancel} className="flex-shrink-0" style={{ color: S.muted }}>
        <X size={13} />
      </button>
    </div>
  );
}

// ── Main Sidebar ─────────────────────────────────────────────────────────────
export function Sidebar({ activeChatId, activeProjectId, onNewChat, onOpenProject, onSelectChat, onCreateChat }) {
  const [projects,        setProjects]        = useState([]);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [expandedFolders, setExpandedFolders] = useState({});
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
    fetchProjects().then(setProjects).catch(() => {}).finally(() => setLoadingProjects(false));
  }, [authVersion]);

  const handleCreateProject = async (name) => {
    if (AGENT_MOCK_MODE) { setCreatingProject(false); return; }
    setCreatingProject(false);
    try {
      const p = await createProject(name);
      setProjects((prev) => [p, ...prev]);
      onOpenProject(p);
      setExpandedFolders((prev) => ({ ...prev, [p.id]: true }));
    } catch {}
  };

  const handleDeleteProject = async (projectId) => {
    if (AGENT_MOCK_MODE) return;
    if (activeProjectId === projectId) onOpenProject(null);
    try {
      await deleteProject(projectId);
      setProjects((prev) => prev.filter((p) => p.id !== projectId));
    } catch {}
  };

  const handleRenameProject = async (projectId, name) => {
    if (AGENT_MOCK_MODE || !name) return;
    try {
      const updated = await updateProject(projectId, { name });
      setProjects((prev) => prev.map((p) => (p.id === projectId ? updated : p)));
    } catch {}
  };

  const toggleExpand = (projectId) =>
    setExpandedFolders((prev) => ({ ...prev, [projectId]: !prev[projectId] }));

  const baseProject      = projects.find((p) => p.name === BASE_PROJECT_NAME);
  const filteredProjects = projects.filter((p) =>
    p.name !== BASE_PROJECT_NAME &&
    p.name.toLowerCase().includes(query.toLowerCase())
  );

  // ── Collapsed strip ────────────────────────────────────────────────────────
  if (collapsed) {
    return (
      <aside
        className="w-[52px] h-full flex flex-col items-center py-3 gap-2 flex-shrink-0"
        style={{ background: S.bg, borderRight: `1px solid ${S.border}` }}
      >
        <Tooltip text="Expand sidebar">
          <button
            onClick={() => setCollapsed(false)}
            className="w-8 h-8 flex items-center justify-center rounded-lg transition-colors"
            style={{ color: S.icon }}
            onMouseEnter={e => e.currentTarget.style.backgroundColor = S.hover}
            onMouseLeave={e => e.currentTarget.style.backgroundColor = "transparent"}
          >
            <PanelLeft size={16} />
          </button>
        </Tooltip>
        <Tooltip text="New chat">
          <button
            onClick={() => { setCollapsed(false); onNewChat?.(); }}
            className="w-8 h-8 flex items-center justify-center rounded-lg transition-colors"
            style={{ color: S.icon }}
            onMouseEnter={e => e.currentTarget.style.backgroundColor = S.hover}
            onMouseLeave={e => e.currentTarget.style.backgroundColor = "transparent"}
          >
            <Plus size={15} />
          </button>
        </Tooltip>
      </aside>
    );
  }

  // ── Expanded ───────────────────────────────────────────────────────────────
  return (
    <>
      <aside
        className="w-[260px] h-full flex flex-col flex-shrink-0"
        style={{ background: S.bg, borderRight: `1px solid ${S.border}` }}
      >
        {/* Logo + collapse */}
        <div className="flex items-center justify-between px-3 pt-3 pb-2">
          <div className="flex items-center gap-2">
            <div
              className="w-[26px] h-[26px] rounded-full flex items-center justify-center flex-shrink-0"
              style={{ background: "linear-gradient(135deg, #E07840 0%, #C04898 100%)" }}
            >
              <span className="text-white text-[10px] font-semibold">C</span>
            </div>
            <span className="text-[13px] font-semibold" style={{ color: S.text }}>CARA</span>
          </div>
          <Tooltip text="Close sidebar">
            <button
              onClick={() => setCollapsed(true)}
              className="w-7 h-7 flex items-center justify-center rounded-lg transition-colors"
              style={{ color: S.icon }}
              onMouseEnter={e => e.currentTarget.style.backgroundColor = S.hover}
              onMouseLeave={e => e.currentTarget.style.backgroundColor = "transparent"}
            >
              <PanelLeftClose size={15} />
            </button>
          </Tooltip>
        </div>

        {/* New Chat button */}
        <div className="px-2 pb-2">
          <button
            className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg
                       text-[13px] transition-colors"
            style={{ color: S.text }}
            onMouseEnter={e => e.currentTarget.style.backgroundColor = S.hover}
            onMouseLeave={e => e.currentTarget.style.backgroundColor = "transparent"}
            onClick={onNewChat}
          >
            <Plus size={14} style={{ color: S.icon }} />
            New chat
          </button>
        </div>

        {/* Search */}
        <div className="px-2 pb-2">
          <div className="relative">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: S.muted }} />
            <input
              type="text"
              placeholder="Search projects…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full pl-7 pr-3 py-1.5 rounded-lg text-[12px] focus:outline-none transition-all"
              style={{
                background: "#FAFAFA",
                border: `1px solid ${S.inputBorder}`,
                color: S.text,
              }}
            />
          </div>
        </div>

        {/* Project list */}
        <div className="flex-1 overflow-y-auto px-2 pb-2">
          {/* Projects section header */}
          <div className="flex items-center justify-between px-1 mb-1">
            <span className="text-[10.5px] font-semibold uppercase tracking-wide" style={{ color: S.muted }}>Projects</span>
            <Tooltip text="New project">
              <button
                onClick={() => setCreatingProject(true)}
                className="w-5 h-5 flex items-center justify-center rounded-md transition-colors"
                style={{ color: S.muted }}
                onMouseEnter={e => { e.currentTarget.style.backgroundColor = S.hover; e.currentTarget.style.color = S.text; }}
                onMouseLeave={e => { e.currentTarget.style.backgroundColor = "transparent"; e.currentTarget.style.color = S.muted; }}
              >
                <Plus size={12} />
              </button>
            </Tooltip>
          </div>

          {/* Flat list for base-project chats (no folder) */}
          <BaseChatList
            baseProject={baseProject}
            activeChatId={activeChatId}
            onSelectChat={onSelectChat}
          />

          {creatingProject && (
            <NewProjectForm
              onSave={handleCreateProject}
              onCancel={() => setCreatingProject(false)}
            />
          )}

          {loadingProjects && projects.length === 0 && (
            <div className="flex items-center justify-center py-8">
              <LoadingSpinner size={18} style={{ color: S.brand }} />
            </div>
          )}

          {!loadingProjects && filteredProjects.length === 0 && !creatingProject && (
            <div className="px-3 py-8 text-center">
              <div className="text-[12px]" style={{ color: S.muted }}>No projects yet</div>
              <button
                onClick={() => setCreatingProject(true)}
                className="mt-2 text-[12px] hover:underline"
                style={{ color: S.brand }}
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
              onCreateChat={onCreateChat}
            />
          ))}
        </div>

        {/* Bottom — user + actions */}
        <div style={{ borderTop: `1px solid ${S.border}` }} className="p-2">
          <div
            className="flex items-center gap-2 px-1.5 py-1.5 rounded-xl group transition-colors cursor-default"
            onMouseEnter={e => e.currentTarget.style.backgroundColor = S.hover}
            onMouseLeave={e => e.currentTarget.style.backgroundColor = "transparent"}
          >
            <div
              className="w-[26px] h-[26px] rounded-full flex items-center justify-center flex-shrink-0 ring-2"
              style={{ background: "#7A7A7A", ringColor: S.border }}
            >
              <span className="text-white text-[10px] font-semibold">
                {(user?.name || user?.email || "U")[0].toUpperCase()}
              </span>
            </div>
            <span className="text-[11.5px] truncate flex-1" style={{ color: S.text }}>
              {user?.email || "user@example.com"}
            </span>
            <Tooltip text="Settings">
              <button
                onClick={() => setShowSettings(true)}
                className="opacity-0 group-hover:opacity-100 w-6 h-6 flex items-center
                           justify-center rounded-md transition-all flex-shrink-0"
                style={{ color: S.muted }}
                onMouseEnter={e => { e.currentTarget.style.backgroundColor = S.active; e.currentTarget.style.color = S.text; }}
                onMouseLeave={e => { e.currentTarget.style.backgroundColor = "transparent"; e.currentTarget.style.color = S.muted; }}
              >
                <Settings size={12} />
              </button>
            </Tooltip>
            <Tooltip text="Sign out">
              <button
                onClick={logout}
                className="opacity-0 group-hover:opacity-100 w-6 h-6 flex items-center
                           justify-center rounded-md transition-all flex-shrink-0"
                style={{ color: S.muted }}
                onMouseEnter={e => { e.currentTarget.style.color = "#E53E3E"; e.currentTarget.style.backgroundColor = "#FFF5F5"; }}
                onMouseLeave={e => { e.currentTarget.style.color = S.muted; e.currentTarget.style.backgroundColor = "transparent"; }}
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
