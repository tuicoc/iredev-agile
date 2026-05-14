// src/hooks/useChat.js
// =============================================================================
// Central chat state hook — handles streaming, artifacts, and feedback loop.
//
// WebSocket events handled:
//   token            → append to assistant bubble
//   done             → mark message finished
//   artifact         → attach artifact (awaitingFeedback=true → show feedback bar)
//   artifact_accepted→ mark artifact as accepted, hide feedback bar
//   error            → show error in bubble
// =============================================================================
import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { useWebSocket } from "./useWebSocket";
import { wsService }    from "../services/websocketService";
import {
  fetchMessages as apiFetchMessages,
  sendMessage   as apiSendMessage,
  saveAssistantMessage as apiSaveAssistantMessage,
  createChat    as apiCreateChat,
  deleteChat    as apiDeleteChat,
  startReq,
  createProjectChat,
} from "../services/chatService";
import { uid }     from "../utils/helpers";
import { useAuth } from "../context/AuthContext";

const getRequirementMaxTurns = () => {
  const value = Number(localStorage.getItem("requirement_max_turns"));
  if (!Number.isFinite(value) || value <= 0) return 150;
  return Math.min(Math.max(Math.round(value), 5), 200);
};

const agentNameFromStatus = (status) => {
  if (!status) return "CARA";
  if (status.includes("Visionary Agent")) return "Visionary Agent";
  if (status.includes("Agenda Agent")) return "Agenda Agent";
  if (status.includes("Interviewer Agent")) return "Interviewer Agent";
  if (status.includes("EndUser Agent")) return "EndUser Agent";
  if (status.includes("Distiller Agent")) return "Distiller Agent";
  if (status.includes("Sprint Agent")) return "Sprint Agent";
  if (status.includes("Analyst Agent")) return "Analyst Agent";
  return "CARA";
};

const caraPromptMessage = () => ({
  id: `cara_prompt_${uid()}`,
  role: "assistant",
  agentName: "CARA",
  content: "What would you like to build today?",
  isSystemPrompt: true,
});

const CORRUPTED_RUN_MESSAGE =
  "Generation was interrupted because you left this chat. The active run was stopped to prevent background execution.";

function decorateMessages(list) {
  const decorated = (list || []).map((message) => {
    if (message.content === CORRUPTED_RUN_MESSAGE) {
      return {
        ...message,
        agentName: "CARA",
        cancelled: true,
      };
    }
    return message;
  });
  return normalizeArtifactTimeline(decorated);
}

function normalizeArtifactTimeline(list) {
  const counters = {};
  const latestIndexByType = {};

  const withVersions = (list || []).map((message, index) => {
    const artifact = message.artifact;
    if (!artifact) return message;

    const type = artifact.type || "artifact";
    counters[type] = (counters[type] || 0) + 1;
    latestIndexByType[type] = index;

    const explicitIteration = Number(artifact.iteration);
    const iteration =
      Number.isFinite(explicitIteration) && explicitIteration > 0
        ? explicitIteration
        : counters[type];

    return {
      ...message,
      artifact: {
        ...artifact,
        iteration,
        messageId: artifact.messageId || message.id,
        chatId: artifact.chatId || message.chatId,
      },
    };
  });

  return withVersions.map((message, index) => {
    const artifact = message.artifact;
    if (!artifact) return message;

    const type = artifact.type || "artifact";
    const isLatestVersion = latestIndexByType[type] === index;

    return {
      ...message,
      artifact: {
        ...artifact,
        accepted: Boolean(artifact.accepted && isLatestVersion),
        awaitingFeedback: Boolean(artifact.awaitingFeedback && isLatestVersion),
        revising: Boolean(artifact.revising && isLatestVersion),
      },
    };
  });
}

export function useChat() {
  const [activeChatId,    setActiveChatId]    = useState(null);
  const [activeProjectId, setActiveProjectId] = useState(null);
  const [subChat,         setSubChat]         = useState(null);
  const [messages,        setMessages]        = useState([]);
  const [streaming,       setStreaming]       = useState(false);
  const [openArtifact,    setOpenArtifact]    = useState(null);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [error,           setError]           = useState(null);
  const [wsConnected,     setWsConnected]     = useState(false);
  const [workflowRunning, setWorkflowRunning] = useState(false);
  const [workflowStatus,  setWorkflowStatus]  = useState(null);

  const { authVersion } = useAuth();

  const activeChatIdRef  = useRef(activeChatId);
  const placeholderIdRef = useRef(null);

  useEffect(() => {
    activeChatIdRef.current = activeChatId;
  }, [activeChatId]);

  const rawPlaceHolderMessage = useMemo(() => {
    if (!messages) return null;
    const artifactList = messages.filter((mess) => !!mess.artifact, []);

    switch (artifactList.length) {
      case 0:
        return "Visionary Agent is responding...";
      case 1:
        return artifactList.at(-1)?.artifact?.accepted
          ? "Agenda Agent is responding..."
          : "Waiting for Human Feedback on Product Vision ...";
      case 2:
        return artifactList.at(-1)?.artifact?.accepted
          ? "Interviewer Agent and EndUser Agent are responding..."
          : "Waiting for Human Feedback on Elicitation Agenda ...";
      case 3:
        return artifactList.at(-1)?.artifact?.accepted
          ? "Distiller Agent is responding..."
          : "Waiting for Human Feedback on Interview Record ...";
      case 4:
        return artifactList.at(-1)?.artifact?.accepted
          ? "Sprint Agent and Analyst Agent are responding..."
          : "Waiting for Human Feedback on Requirement List ...";
      case 5:
        return artifactList.at(-1)?.artifact?.accepted
          ? "Analyst Agent is responding..."
          : "Waiting for Human Feedback on Product Backlog ...";
      case 6:
        return artifactList.at(-1)?.artifact?.accepted
          ? null
          : "Waiting for Human Feedback on Validated Product Backlog ...";
      default:
        return null;
    }
  }, [messages]);

  const placeHolderMessage = useMemo(() => {
    if (workflowStatus?.running && workflowStatus.message) {
      return workflowStatus.message;
    }
    if (!rawPlaceHolderMessage) return null;
    if (rawPlaceHolderMessage.startsWith("Waiting for Human Feedback")) {
      return rawPlaceHolderMessage;
    }
    return workflowRunning || streaming ? rawPlaceHolderMessage : null;
  }, [rawPlaceHolderMessage, streaming, workflowRunning, workflowStatus]);

  // ── Reset when user logs out ───────────────────────────────────────────────
  useEffect(() => {
    if (authVersion === 0) {
      setActiveChatId(null);
      setActiveProjectId(null);
      setMessages([]);
      setOpenArtifact(null);
      setStreaming(false);
      setWorkflowRunning(false);
      setWorkflowStatus(null);
    }
  }, [authVersion]);

  // ── WebSocket handlers ────────────────────────────────────────────────────

  const handleToken = useCallback(({ chatId, messageId, token, role, agentName, messageMeta }) => {
    if (chatId !== activeChatIdRef.current) return;
    setStreaming(true);
    setMessages((prev) => {
      const idx = prev.findIndex(
        (m) => m.id === messageId || m.id === placeholderIdRef.current
      );
      if (idx !== -1) {
        return prev.map((m, i) =>
          i === idx
            ? {
                ...m,
                agentName: agentName || m.agentName,
                messageMeta: Object.keys(messageMeta || {}).length ? messageMeta : m.messageMeta,
                content: m.content + token,
              }
            : m
        );
      }
      placeholderIdRef.current = messageId;
      return [
        ...prev,
        {
          id: messageId,
          role: role || "assistant",
          agentName,
          messageMeta: messageMeta || {},
          content: token,
          streaming: true,
        },
      ];
    });
  }, []);

  const handleDone = useCallback(({ chatId, messageId }) => {
    if (chatId !== activeChatIdRef.current) return;
    setMessages((prev) =>
      prev.map((m) =>
        m.id === messageId || m.id === placeholderIdRef.current
          ? { ...m, id: messageId, streaming: false }
          : m
      )
    );
    placeholderIdRef.current = null;
    setStreaming(false);
  }, []);

  const handleArtifact = useCallback(
    ({ chatId, messageId, artifact, awaitingFeedback, iteration }) => {
      const enriched = {
        ...artifact,
        awaitingFeedback,
        iteration: iteration ?? artifact?.iteration,
        messageId,
        chatId,
      };
      setMessages((prev) => {
        const exists = prev.some(
          (m) => m.id === messageId || m.id === placeholderIdRef.current
        );
        if (exists) {
          return normalizeArtifactTimeline(prev.map((m) =>
            m.id === messageId || m.id === placeholderIdRef.current
              ? { ...m, id: messageId, artifact: enriched }
              : m
          ));
        }
        return normalizeArtifactTimeline([
          ...prev,
          {
            id: messageId,
            role: "assistant",
            agentName: enriched.agentName,
            content: "",
            streaming: false,
            artifact: enriched,
          },
        ]);
      });
      if (chatId === activeChatIdRef.current) {
        setWorkflowRunning(false);
        setWorkflowStatus(null);
        setOpenArtifact(enriched);
      }
    },
    []
  );

  const handleArtifactAccepted = useCallback(
    ({ chatId, messageId, artifactId }) => {
      setMessages((prev) => {
        const target = prev.find((m) =>
          messageId ? m.id === messageId : m.artifact?.id === artifactId
        );
        const acceptedType = target?.artifact?.type || null;

        return normalizeArtifactTimeline(prev.map((m) => {
          if (!m.artifact) return m;
          const isTarget = messageId ? m.id === messageId : m.artifact.id === artifactId;
          const isSameType = acceptedType && m.artifact.type === acceptedType;
          if (!isTarget && !isSameType) return m;
          if (!isTarget) {
            return { ...m, artifact: { ...m.artifact, accepted: false, awaitingFeedback: false } };
          }
          return { ...m, artifact: { ...m.artifact, accepted: true, awaitingFeedback: false } };
        }));
      });
      setOpenArtifact((prev) => {
        if (!prev) return null;
        const isTarget = messageId ? prev.messageId === messageId : prev.id === artifactId;
        if (!isTarget) return prev;
        return { ...prev, accepted: true, awaitingFeedback: false };
      });
      if (chatId === activeChatIdRef.current) {
        setWorkflowRunning(true);
      }
    },
    []
  );

  const handleWsError = useCallback(
    ({ chatId, messageId, artifactId, error: serverError }) => {
      if (artifactId) {
        setMessages((prev) =>
          prev.map((m) => {
            if (!m.artifact || m.artifact.id !== artifactId) return m;
            return { ...m, artifact: { ...m.artifact, awaitingFeedback: false } };
          })
        );
        setOpenArtifact((prev) =>
          prev && prev.id === artifactId ? { ...prev, awaitingFeedback: false } : prev
        );
        setWorkflowRunning(false);
        setWorkflowStatus(null);
        setError(serverError || "Feedback session has ended for this artifact.");
        return;
      }
      if (chatId && chatId !== activeChatIdRef.current) return;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === messageId || m.id === placeholderIdRef.current
            ? { ...m, content: `⚠️ ${serverError || "Something went wrong."}`, streaming: false, isError: true }
            : m
        )
      );
      placeholderIdRef.current = null;
      setStreaming(false);
      setWorkflowRunning(false);
      setWorkflowStatus(null);
      setError(serverError || "Failed to get a response.");
    },
    []
  );

  const handleWorkflowStatus = useCallback(({ chatId, running, complete, message, agentName, node }) => {
    if (chatId !== activeChatIdRef.current) return;
    if (complete) {
      setWorkflowRunning(false);
      setWorkflowStatus(null);
      return;
    }
    setWorkflowRunning(Boolean(running));
    setWorkflowStatus(
      running
        ? { running: true, message, agentName, node }
        : null,
    );
  }, []);

  useWebSocket({
    onToken:            handleToken,
    onDone:             handleDone,
    onError:            handleWsError,
    onArtifact:         handleArtifact,
    onArtifactAccepted: handleArtifactAccepted,
    onWorkflowStatus:   handleWorkflowStatus,
    onConnected:        () => setWsConnected(true),
    onDisconnected:     () => setWsConnected(false),
  });

  // ── Actions ───────────────────────────────────────────────────────────────

  const corruptActiveRun = useCallback(async () => {
    const shouldCorrupt =
      activeChatId &&
      (streaming || workflowRunning || workflowStatus?.running) &&
      !String(rawPlaceHolderMessage || "").startsWith("Waiting for Human Feedback");

    if (!shouldCorrupt) return;

    const chatId = activeChatId;
    const subChatId = subChat ?? 0;
    const stoppedAgentName =
      workflowStatus?.agentName ||
      agentNameFromStatus(workflowStatus?.message || rawPlaceHolderMessage);

    wsService.stopStream(chatId);
    placeholderIdRef.current = null;
    setStreaming(false);
    setWorkflowRunning(false);
    setWorkflowStatus(null);
    setMessages((prev) => {
      const hasCorruptMessage = prev.some((m) => m.content === CORRUPTED_RUN_MESSAGE);
      const stopped = prev.map((m) =>
        m.streaming
          ? { ...m, agentName: m.agentName || stoppedAgentName, streaming: false, cancelled: true }
          : m,
      );
      if (hasCorruptMessage) return stopped;
      return [
        ...stopped,
        {
          id: `corrupted_${uid()}`,
          role: "assistant",
          agentName: "CARA",
          content: CORRUPTED_RUN_MESSAGE,
          streaming: false,
          cancelled: true,
        },
      ];
    });

    try {
      await apiSaveAssistantMessage(chatId, CORRUPTED_RUN_MESSAGE, subChatId);
    } catch {}
  }, [
    activeChatId,
    rawPlaceHolderMessage,
    streaming,
    subChat,
    workflowRunning,
    workflowStatus,
  ]);

  /** Select a chat (called from sidebar or after creating a new one) */
  const selectChat = useCallback(
    async (id, newSubChat = 0, projectId = null) => {
      if (id === activeChatId && subChat === newSubChat) return;
      await corruptActiveRun();
      if (activeChatId) wsService.stopStream(activeChatId);
      placeholderIdRef.current = null;
      setActiveChatId(id);
      setActiveProjectId(projectId);
      setSubChat(newSubChat);
      setMessages([]);
      setOpenArtifact(null);
      setError(null);
      setStreaming(false);
      setWorkflowRunning(false);
      setWorkflowStatus(null);
      setLoadingMessages(true);
      try {
        const msgs = await apiFetchMessages(id, newSubChat);
        const decorated = decorateMessages(msgs);
        setMessages(
          newSubChat === 0 && projectId && decorated.length === 0
            ? [caraPromptMessage()]
            : decorated
        );
      } catch {
        setError("Could not load messages. Please try again.");
      } finally {
        setLoadingMessages(false);
      }
    },
    [activeChatId, corruptActiveRun, subChat]
  );

  const clearActiveChat = useCallback(async () => {
    await corruptActiveRun();
    if (activeChatId) wsService.stopStream(activeChatId);
    placeholderIdRef.current = null;
    setActiveChatId(null);
    setActiveProjectId(null);
    setMessages([]);
    setOpenArtifact(null);
    setError(null);
    setStreaming(false);
    setWorkflowRunning(false);
    setWorkflowStatus(null);
  }, [activeChatId, corruptActiveRun]);

  const deleteChat = useCallback(
    async (id) => {
      if (id === activeChatId) {
        await corruptActiveRun();
        wsService.stopStream(id);
        placeholderIdRef.current = null;
        setActiveChatId(null);
        setMessages([]);
        setOpenArtifact(null);
        setStreaming(false);
        setWorkflowRunning(false);
        setWorkflowStatus(null);
      }
      try {
        await apiDeleteChat(id);
      } catch {}
    },
    [activeChatId, corruptActiveRun]
  );

  const createRequirementChat = useCallback(async (projectId, projectName = "New Process") => {
    const title  = `Requirements — ${projectName || "New Process"}`;
    const tempId = `temp_${uid()}`;

    await corruptActiveRun();
    if (activeChatId) wsService.stopStream(activeChatId);
    placeholderIdRef.current = null;
    setActiveChatId(tempId);
    setActiveProjectId(projectId);
    setSubChat(0);
    setMessages([caraPromptMessage()]);
    setOpenArtifact(null);
    setError(null);
    setStreaming(false);
    setWorkflowRunning(false);
    setWorkflowStatus(null);

    try {
      const serverChat = projectId
        ? await createProjectChat(projectId, title)
        : await apiCreateChat(title);
      setActiveChatId(serverChat.id);
      return serverChat.id;
    } catch {
      setActiveChatId(null);
      setError("Could not create conversation. Please try again.");
      return null;
    }
  }, [activeChatId, corruptActiveRun]);

  const cancelStream = useCallback(() => {
    if (activeChatId) wsService.stopStream(activeChatId);
    const stoppedAgentName = agentNameFromStatus(rawPlaceHolderMessage);
    setStreaming(false);
    setWorkflowRunning(false);
    setWorkflowStatus(null);
    setMessages((prev) => {
      let stoppedExisting = false;
      const next = prev.map((m) => {
        if (!m.streaming) return m;
        stoppedExisting = true;
        return {
          ...m,
          agentName: m.agentName || stoppedAgentName,
          streaming: false,
          cancelled: true,
        };
      });
      if (stoppedExisting) return next;
      return [
        ...next,
        {
          id: `cancelled_${uid()}`,
          role: "assistant",
          agentName: stoppedAgentName,
          content: "Generation was stopped before a response was completed.",
          streaming: false,
          cancelled: true,
        },
      ];
    });
    placeholderIdRef.current = null;
  }, [activeChatId, rawPlaceHolderMessage]);

  const retryMessage = useCallback(
    async (messageId) => {
      const idx = messages.findIndex((m) => m.id === messageId);
      if (idx === -1 || !activeChatId) return;

      const isRequirementProcess = subChat === 0;
      const previousUser = [...messages.slice(0, idx)].reverse().find((m) => m.role === "user");
      if (!isRequirementProcess && !previousUser?.content?.trim()) return;

      setError(null);
      setStreaming(true);
      setWorkflowRunning(isRequirementProcess);
      setWorkflowStatus(null);
      setOpenArtifact(null);
      setMessages((prev) => prev.slice(0, idx));

      try {
        if (isRequirementProcess) {
          wsService.retryWorkflow(activeChatId);
        } else {
          wsService.sendChatMessage(activeChatId, `ph_${uid()}`, previousUser.content, subChat);
        }
      } catch {
        placeholderIdRef.current = null;
        setStreaming(false);
        setWorkflowRunning(false);
        setWorkflowStatus(null);
        setError("Retry failed. Please try again.");
      }
    },
    [activeChatId, messages, subChat],
  );

  const sendMessage = useCallback(
    async (text) => {
      if (!text.trim() || streaming) return;
      setError(null);
      const trimmed = text.trim();
      let chatId = activeChatId;
      const hasRequirementUserTurn = messages.some((m) => m.role === "user");
      const startsRequirementProcess =
        subChat === 0 &&
        !!activeProjectId &&
        !hasRequirementUserTurn;

      // Create top-level chat if no active chat
      if (!chatId) {
        const title  = trimmed.slice(0, 50) + (trimmed.length > 50 ? "…" : "");
        const tempId = `temp_${uid()}`;
        setActiveChatId(tempId);
        chatId = tempId;
        try {
          const serverChat = await apiCreateChat(title);
          setActiveChatId(serverChat.id);
          chatId = serverChat.id;
        } catch {
          setActiveChatId(null);
          setError("Could not create conversation. Please try again.");
          return;
        }
      }

      const localId = `local_${uid()}`;
      setMessages((prev) => [...prev, { id: localId, role: "user", content: trimmed }]);
      setStreaming(true);
      setWorkflowRunning(startsRequirementProcess);
      setWorkflowStatus(null);

      try {
        const saved = await apiSendMessage(chatId, trimmed, subChat);
        setMessages((prev) => prev.map((m) => (m.id === localId ? saved : m)));
        if (startsRequirementProcess) {
          await startReq(
            {
              projectName: trimmed.slice(0, 50),
              projectDescription: trimmed,
              maxIterations: getRequirementMaxTurns(),
            },
            chatId,
          );
        } else {
          wsService.sendChatMessage(chatId, `ph_${uid()}`, trimmed, subChat);
        }
      } catch {
        placeholderIdRef.current = null;
        setStreaming(false);
        setWorkflowRunning(false);
        setWorkflowStatus(null);
        setError("Failed to send. Please try again.");
      }
    },
    [activeChatId, activeProjectId, messages, streaming, subChat]
  );

  /** Start a requirement process inside a project chat */
  const handleStartProcess = useCallback(
    async (config, projectId) => {
      const title  = `Requirements — ${config.projectName || "New Process"}`;
      const tempId = `temp_${uid()}`;
      setActiveChatId(tempId);
      setActiveProjectId(projectId);
      setSubChat(0);
      setMessages([]);
      setWorkflowRunning(true);
      setWorkflowStatus(null);

      let chatId = tempId;
      try {
        let serverChat;
        if (projectId) {
          serverChat = await createProjectChat(projectId, title);
        } else {
          serverChat = await apiCreateChat(title);
        }
        setActiveChatId(serverChat.id);
        chatId = serverChat.id;
      } catch {
        setActiveChatId(null);
        setWorkflowRunning(false);
        setWorkflowStatus(null);
        setError("Could not create conversation. Please try again.");
        return;
      }

      const localId = `local_${uid()}`;
      setMessages([{ id: localId, role: "user", content: config.projectDescription }]);
      await apiSendMessage(chatId, config.projectDescription, 0).catch(() => {});

      setStreaming(true);
      try {
        await startReq(
          {
            ...config,
            maxIterations: config.maxIterations ?? getRequirementMaxTurns(),
          },
          chatId,
        );
      } catch {
        placeholderIdRef.current = null;
        setStreaming(false);
        setWorkflowRunning(false);
        setWorkflowStatus(null);
        setError("Failed to start process. Please try again.");
      }

      return chatId;
    },
    []
  );

  const openArtifactRef = useRef(null);
  useEffect(() => { openArtifactRef.current = openArtifact; }, [openArtifact]);

  const sendArtifactFeedback = useCallback((action, comment = "") => {
    const art    = openArtifactRef.current;
    if (!art) return;
    const chatId    = art.chatId || activeChatIdRef.current;
    const messageId = art.messageId || "";
    wsService.send({ type: "artifact_feedback", chatId, messageId, artifactId: art.id, action, comment });
    setWorkflowRunning(true);
    setWorkflowStatus(null);

    const optimistic = (prev) => {
      if (!prev) return null;
      return action === "accept"
        ? { ...prev, awaitingFeedback: false, accepted: true }
        : { ...prev, awaitingFeedback: false, revising: true };
    };
    setOpenArtifact(optimistic);
    setMessages((prev) =>
      normalizeArtifactTimeline(prev.map((m) => {
        if (!m.artifact) return m;
        const isTarget = art.messageId ? m.id === art.messageId : m.artifact.id === art.id;
        const isSameType = art.type && m.artifact.type === art.type;
        if (!isTarget && !(action === "accept" && isSameType)) return m;
        if (!isTarget) {
          return { ...m, artifact: { ...m.artifact, accepted: false, awaitingFeedback: false } };
        }
        return { ...m, artifact: optimistic(m.artifact) };
      }))
    );
  }, []);

  return {
    placeHolderMessage,
    activeChatId,
    activeProjectId,
    subChat,
    messages,
    streaming,
    workflowRunning,
    openArtifact,
    loadingMessages,
    error,
    wsConnected,
    setOpenArtifact,
    setError,
    setSubChat,
    selectChat,
    clearActiveChat,
    deleteChat,
    createRequirementChat,
    sendMessage,
    retryMessage,
    cancelStream,
    sendArtifactFeedback,
    handleStartProcess,
  };
}
