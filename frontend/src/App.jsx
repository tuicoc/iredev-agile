// src/App.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Root component — wires all pieces together.
//
// Layout:
//   MainLayout
//   ├── Sidebar          (left, fixed width)
//   ├── Chat column      (centre, flex-1 hoặc fixed % khi artifact open)
//   ├── ResizableDivider (kéo thả, chỉ hiện khi artifact open)
//   └── ArtifactPanel    (right, fixed % width, shown only when open)
// ─────────────────────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────────────────────
// Three view states in the main chat area:
//   1. No active project & no chat  → HomeScreen (welcome)
//   2. Active project, no active chat → ProjectHomeScreen
//   3. Active chat                   → Message list
// ─────────────────────────────────────────────────────────────────────────────
import { useRef, useEffect, useState, useCallback } from "react";
import { useChat }              from "./context/ChatContext";
import { ProtectedRoute }      from "./components/layout/ProtectedRoute";
import { MainLayout }          from "./components/layout/MainLayout";
import { Sidebar }             from "./components/sidebar/Sidebar";
import { HomeScreen }          from "./components/chat/HomeScreen";
import { ProjectHomeScreen }   from "./components/chat/ProjectHomeScreen";
import { MessageBubble }       from "./components/chat/MessageBubble";
import { ChatInput }           from "./components/chat/ChatInput";
import { IntakeQuestions }     from "./components/chat/IntakeQuestions";
import { ArtifactPanel }       from "./components/artifact/ArtifactPanel";
import { BASE_PROJECT_NAME }  from "./services/chatService";
import { LoadingSpinner }      from "./components/ui/LoadingSpinner";
import { ErrorBanner }         from "./components/ui/ErrorBanner";
import { GripVertical }        from "lucide-react";

// ── Resizable Divider ─────────────────────────────────────────────────────────
function ResizableDivider({ onMouseDown }) {
  return (
    <div
      onMouseDown={onMouseDown}
      className="relative flex-shrink-0 w-[6px] h-full cursor-col-resize group z-10 select-none"
    >
      <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-px
                      bg-[#DEDEDE] group-hover:bg-[#B86F50] transition-colors duration-150" />
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
                      flex items-center justify-center w-5 h-9 rounded-full
                      bg-[#F0F0F0] border border-[#DEDEDE]
                      group-hover:bg-[#F5E3D7] group-hover:border-[#B86F50]
                      shadow-sm transition-all duration-150 opacity-0 group-hover:opacity-100">
        <GripVertical size={11} className="text-[#A8A8A8] group-hover:text-[#B86F50]" />
      </div>
    </div>
  );
}

function useResizable({ defaultRightPct = 40, minRight = 22, maxRight = 68 } = {}) {
  const [rightPct,    setRightPct]    = useState(defaultRightPct);
  const isDragging   = useRef(false);
  const containerRef = useRef(null);

  const handleMouseDown = useCallback((e) => {
    e.preventDefault();
    isDragging.current = true;
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
  }, []);

  useEffect(() => {
    const onMove = (e) => {
      if (!isDragging.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const pct  = ((rect.right - e.clientX) / rect.width) * 100;
      if (pct >= minRight && pct <= maxRight) setRightPct(pct);
    };
    const onUp = () => {
      if (!isDragging.current) return;
      isDragging.current = false;
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  }, [minRight, maxRight]);

  return { rightPct, containerRef, handleMouseDown };
}

// ── ChatLayout ────────────────────────────────────────────────────────────────
function ChatLayout() {
  const {
    activeChatId,
    subChat,
    messages,
    streaming,
    workflowRunning,
    openArtifact,
    loadingMessages,
    error,
    activeProcessConfig,
    setActiveProcessConfig,
    setOpenArtifact,
    setError,
    setSubChat,
    selectChat,
    clearActiveChat,
    createRequirementChat,
    sendMessage,
    retryMessage,
    cancelStream,
    sendArtifactFeedback,
    placeHolderMessage,
    pendingQuestions,
    submitQuestionAnswers,
  } = useChat();

  // Active project — set when user clicks a project folder name in sidebar.
  // null = no project selected (show global home screen).
  const [activeProject, setActiveProject] = useState(null);

  const bottomRef = useRef(null);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const { rightPct, containerRef, handleMouseDown } = useResizable();

  // ── Sidebar callbacks ───────────────────────────────────────────────────
  // Called when user clicks project folder name
  const handleOpenProject = useCallback((project) => {
    setActiveProject(project);   // null = deselect
    clearActiveChat();
  }, [clearActiveChat]);

  // Called when user clicks a chat row inside a folder
  const handleSelectChat = useCallback((chatId, projectId) => {
    const proj = activeProject?.id === projectId ? activeProject : { id: projectId };
    setActiveProject(proj);
    selectChat(chatId, 0, projectId);
  }, [activeProject, selectChat]);

  const handleCreateProjectChat = useCallback(async (projectId, projectName) => {
    setActiveProject({ id: projectId, name: projectName });
    return createRequirementChat(projectId, projectName);
  }, [createRequirementChat]);

  const handleNewChat = useCallback(() => {
    setActiveProject(null);
    clearActiveChat();
  }, [clearActiveChat]);

  // ── Decide what to show in the center area ──────────────────────────────
  const showProjectHome = activeProject && !activeChatId;
  const showMessages    = !!activeChatId;
  const showStopButton  = streaming || (workflowRunning && !!placeHolderMessage);
  const requirementProcessStarted =
    subChat === 0 && messages.some((msg) => msg.role === "user");

  return (
    <MainLayout>
      <Sidebar
        activeChatId={activeChatId}
        activeProjectId={activeProject?.id ?? null}
        onNewChat={handleNewChat}
        onOpenProject={handleOpenProject}
        onSelectChat={handleSelectChat}
        onCreateChat={handleCreateProjectChat}
      />

      {/* Content area */}
      <div ref={containerRef} className="flex flex-1 min-w-0 h-full overflow-hidden">

        {/* Center column */}
        <div
          className="flex flex-col h-full min-w-0 bg-white"
          style={openArtifact ? { width: `${100 - rightPct}%` } : { flex: 1 }}
        >
          {/* Header — only when a chat is open */}
          {showMessages && (
            <header className="flex items-center h-[52px] px-5
                               border-b border-[#E5E5E5] bg-white flex-shrink-0">
              <div className="flex items-center gap-2 min-w-0">
                {activeProject && activeProject.name !== BASE_PROJECT_NAME && (
                  <span className="text-[12px] text-[#7A7A7A] flex-shrink-0">
                    {activeProject.name}
                  </span>
                )}
                {activeProject && activeProject.name !== BASE_PROJECT_NAME && (
                  <span className="text-[12px] text-[#C8C3BC] flex-shrink-0">/</span>
                )}
                <span className="text-[13.5px] font-semibold text-[#1A1A1A] truncate">
                  Requirement Process
                </span>
              </div>
            </header>
          )}

          <ErrorBanner message={error} onDismiss={() => setError(null)} />

          {/* Main content */}
          {showProjectHome ? (
            <div className="flex-1 overflow-hidden">
              <ProjectHomeScreen
                project={activeProject}
                onOpenChat={(chatId, projId) => handleSelectChat(chatId, projId)}
                onCreateChat={handleCreateProjectChat}
              />
            </div>
          ) : showMessages ? (
            <>
              <div className="flex-1 overflow-y-auto min-h-0">
                {loadingMessages ? (
                  <div className="flex items-center justify-center h-full">
                    <LoadingSpinner size={22} className="text-[#B86F50]" />
                  </div>
                ) : (
                  <div className="max-w-[720px] mx-auto px-6 py-8 space-y-7">
                    {messages.map((msg) => (
                      <MessageBubble
                        key={msg.id}
                        message={msg}
                        onOpenArtifact={(art) => setOpenArtifact({ ...art, messageId: msg.id })}
                        onRetry={retryMessage}
                      />
                    ))}
                    {placeHolderMessage && (
                      <div className="flex items-center">
                        <LoadingSpinner size={22} className="text-[#B86F50]" />
                        <div className="text-[#A8A8A8] text-[13px] ml-2">
                          {placeHolderMessage}
                        </div>
                      </div>
                    )}
                    <div ref={bottomRef} />
                  </div>
                )}
              </div>
              {pendingQuestions && (
                <IntakeQuestions
                  questions={pendingQuestions.questions}
                  onSubmit={submitQuestionAnswers}
                />
              )}
              <ChatInput
                onSend={sendMessage}
                disabled={streaming || (subChat === 0 && requirementProcessStarted)}
                isStreaming={showStopButton}
                onCancel={cancelStream}
                processConfig={activeProcessConfig}
                onProcessConfigChange={setActiveProcessConfig}
                configLocked={requirementProcessStarted}
                showProcessControls={subChat === 0}
              />
            </>
          ) : (
            /* Home: greeting + input centered vertically */
            <div className="flex flex-col flex-1 min-h-0 items-center justify-center">
              <HomeScreen />
              <div className="w-full mt-6">
                <ChatInput
                  onSend={sendMessage}
                  disabled={false}
                  isStreaming={false}
                  onCancel={cancelStream}
                  processConfig={activeProcessConfig}
                  onProcessConfigChange={setActiveProcessConfig}
                  configLocked={false}
                  showProcessControls={true}
                />
              </div>
            </div>
          )}
        </div>

        {/* Resizable divider */}
        {openArtifact && <ResizableDivider onMouseDown={handleMouseDown} />}

        {/* Artifact panel */}
        {openArtifact && (
          <div
            className="h-full flex-shrink-0 border-l border-[#E5E5E5] overflow-hidden"
            style={{ width: `${rightPct}%` }}
          >
            <ArtifactPanel
              artifact={openArtifact}
              messages={messages}
              onClose={() => setOpenArtifact(null)}
              onAccept={() => sendArtifactFeedback("accept", "")}
              onRevise={(comment) => sendArtifactFeedback("revise", comment)}
            />
          </div>
        )}
      </div>
    </MainLayout>
  );
}

export default function App() {
  return (
    <ProtectedRoute>
      <ChatLayout />
    </ProtectedRoute>
  );
}
