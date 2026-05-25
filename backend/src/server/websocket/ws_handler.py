# backend/src/server/websocket/ws_handler.py
# =============================================================================
# WebSocket handler — one persistent connection per user session.
#
# Artifact lifecycle
# ──────────────────
# [interview phase]
#   InterviewerAgent → interview_complete=True
#   → supervisor routes to review_turn
#   → review_turn calls interrupt() → graph PAUSES
#   → ws_handler detects __interrupt__ → emits "artifact" (interview_record)
#   → frontend shows artifact with Accept / Request Changes
#
# [accept]
#   frontend sends artifact_feedback {action: "accept"}
#   → ws_handler resumes graph with Command(resume={approved: True})
#   → review_turn_fn returns reviewed_interview_record
#   → ws_handler emits "artifact_accepted" for interview_record
#   → graph continues: supervisor → sprint_agent_turn
#   → SprintAgent builds product_backlog
#   → ws_handler emits "artifact" (product_backlog, awaitingFeedback=True)
#   → graph PAUSES again (sprint review interrupt)
#
# [revise]
#   frontend sends artifact_feedback {action: "revise", comment: "..."}
#   → ws_handler resumes graph with Command(resume={approved: False, feedback: "..."})
#   → review_turn_fn removes interview_record, sets review_feedback
#   → supervisor routes back to interviewer_turn
#   → ws_handler emits "revision_start"
#   → interviewer re-runs, produces new interview_record
#   → graph pauses at review_turn again
#   → ws_handler emits "artifact_revised" (new interview_record)
# =============================================================================

import json
import os
import time
import re
import threading
import uuid
import logging
from typing import Any, Dict, Optional

from ..data.database import (
    add_message,
    get_messages,
    update_message_artifact,
)
from ..auth.auth_utils import get_user_id_for_token_ws
from src.orchestrator import build_graph
from src.orchestrator.graph import ARTIFACT_SUMMARIES, configure_default_store
from src.memory.short_term import create_langgraph_postgres

log = logging.getLogger(__name__)

# Maps review_type to the corresponding artifact key that indicates approval
# in the review_turn output.
REVIEW_TYPES = {
    "product_vision":            "reviewed_product_vision",
    "elicitation_agenda":        "reviewed_elicitation_agenda",
    "interview_record":          "reviewed_interview_record",
    "requirement_list":          "requirement_list_approved",
    "product_backlog":           "product_backlog_approved",
    "validated_product_backlog": "validated_product_backlog_approved",
}

# All review node names that produce approve/reject results after interrupt
# resumes.  Used in _dispatch_node to route to _handle_review_result.
_REVIEW_NODE_NAMES = {
    "review_product_vision_turn",
    "review_elicitation_agenda_turn",
    "review_interview_record_turn",
    "review_requirement_list_turn",
    "review_product_backlog_turn",
    "review_validated_product_backlog_turn",
}

# Agent nodes that produce artifacts consumed by a subsequent interrupt —
# nothing to emit directly; the artifact card is sent when the next interrupt
# fires.
_AGENT_NODE_NAMES = {
    "sprint_agent_turn",
    "analyst_turn",
    "analyst_estimation_turn",
}

REVIEW_AGENT_NAMES = {
    "product_vision": "Visionary Agent",
    "elicitation_agenda": "Agenda Agent",
    "interview_record": "Interviewer Agent",
    "requirement_list": "Distiller Agent",
    "product_backlog": "Sprint Agent",
    "validated_product_backlog": "Analyst Agent",
}

ARTIFACT_TITLES = {
    "product_vision": "Product Vision",
    "elicitation_agenda": "Elicitation Agenda",
    "interview_record": "Interview Record",
    "requirement_list": "Requirement List",
    "product_backlog": "Product Backlog",
    "validated_product_backlog": "Validated Product Backlog",
}

NODE_STATUS = {
    "visionary_turn": {
        "agentName": "Visionary Agent",
        "message": "Visionary Agent is shaping the Product Vision...",
    },
    "agenda_turn": {
        "agentName": "Agenda Agent",
        "message": "Agenda Agent is building the elicitation agenda...",
    },
    "interviewer_turn": {
        "agentName": "Interviewer Agent",
        "message": "Interviewer Agent and EndUser Agent are discussing requirements...",
    },
    "distiller_turn": {
        "agentName": "Distiller Agent",
        "message": "Distiller Agent is synthesising the Requirement List...",
    },
    "sprint_agent_turn": {
        "agentName": "Sprint Agent",
        "message": "Sprint Agent is turning requirements into backlog items...",
    },
    "analyst_estimation_turn": {
        "agentName": "Analyst Agent",
        "message": "Analyst Agent is estimating stories and checking INVEST...",
    },
    "analyst_turn": {
        "agentName": "Analyst Agent",
        "message": "Analyst Agent is writing acceptance criteria...",
    },
}

WORKFLOW_COMPLETE_MESSAGE = (
    "Backlog refinement is complete. The Validated Product Backlog has been "
    "accepted and the ready stories are available for Sprint planning."
)


# ─────────────────────────────────────────────────────────────────────────────
# WSHandler
# ─────────────────────────────────────────────────────────────────────────────

class WSHandler:

    def __init__(self) -> None:
        self._state: dict = {}
        self._state_lock = threading.Lock()

        # { user_id → {"ws": ws, "lock": lock} }
        self.active_ws: Dict[str, Dict] = {}

        # Pending artifact context per chat — used to correlate accept/revise
        # with the last artifact that was emitted.
        # { chat_id → {review_type, artifact_id, message_id} }
        self._artifact_ctx: Dict[str, Dict] = {}
        self._pending_interrupts: Dict[str, Any] = {}
        self._completion_sent: set[str] = set()
        self._conversation_ctx: Dict[str, Dict[str, Any]] = {}

        # Held so the pool's lifetime matches the handler's. Closed by the
        # runtime when the process exits; no explicit shutdown hook needed.
        self._lg_pool = None
        self.graph = self._build_graph_for_server()

    def _build_graph_for_server(self):
        """Build the LangGraph workflow with Postgres-backed checkpointer + store.

        Falls back to LangGraph's in-memory backends if IREDEV_PG_CONNECTION is
        unset or Postgres init fails (e.g. local dev without Docker). The
        fallback is single-process only — restart or scale-out will lose state.
        """
        pg_conn = os.getenv("IREDEV_PG_CONNECTION")
        if not pg_conn:
            log.warning(
                "[WS] IREDEV_PG_CONNECTION not set — workflow state will not "
                "survive restart and cannot be shared across worker processes."
            )
            return build_graph()

        try:
            min_conn = int(os.getenv("LG_MIN_CONN", "1"))
            max_conn = int(os.getenv("LG_MAX_CONN", "10"))
            checkpointer, store, pool = create_langgraph_postgres(
                pg_conn, min_size=min_conn, max_size=max_conn
            )
        except Exception as exc:
            log.error(
                "[WS] Postgres checkpointer/store init failed (%s) — falling "
                "back to in-memory state. Multi-user/restart will lose state.",
                exc,
                exc_info=True,
            )
            return build_graph()

        # Bind the same Postgres store to graph.py's artifact-sync helpers so
        # _sync_artifacts_to_store + get_artifact_from_store share one backend.
        configure_default_store(store)
        self._lg_pool = pool
        log.info("[WS] LangGraph state bound to Postgres (multi-user ready)")
        return build_graph(checkpointer=checkpointer, store=store)

    # =========================================================================
    # Token streaming
    # =========================================================================

    def _stream_tokens(self, text: str):
        """Yield (token, delay) pairs for word-level streaming."""
        words = re.findall(r"\S+\s*|\n+", text)
        for word in words:
            if word.rstrip().endswith((".", "!", "?", ":")):
                delay = 0.06
            elif "\n" in word:
                delay = 0.04
            else:
                delay = 0.025
            yield word, delay

    def _send_token_stream(
        self,
        ws,
        lock,
        chat_id: str,
        mess_id: str,
        text: str,
        role: str,
        stop_event: Optional[threading.Event] = None,
        agent_name: Optional[str] = None,
        message_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Stream text token-by-token; return accumulated string."""
        accum = ""
        for token, delay in self._stream_tokens(text):
            if stop_event and stop_event.is_set():
                log.info("[WS] token stream stopped chat=%s message=%s", chat_id, mess_id)
                break

            accum += token
            ok = self._send(ws, lock, {
                "type": "token",
                "chatId": chat_id,
                "messageId": mess_id,
                "token": token,
                "role": role,
                "agentName": agent_name,
                "messageMeta": message_meta or {},
            })
            if not ok:
                break
            time.sleep(delay)

        self._send(ws, lock, {
            "type": "done",
            "chatId": chat_id,
            "messageId": mess_id,
            "agentName": agent_name,
            "messageMeta": message_meta or {},
        })
        return accum

    # =========================================================================
    # Workflow runner
    # =========================================================================

    def run_iredev_workflow(self, initial_state: Any, user_id: str, chat_id: str):
        """
        Stream one segment of the LangGraph workflow.

        initial_state can be:
          - A WorkflowState dict  (new segment / first run)
          - A Command(resume=...) (resuming after interrupt)
        """
        ws_entry = self.active_ws.get(user_id, {})
        ws = ws_entry.get("ws")
        lock = ws_entry.get("lock")
        ws_id = ws_entry.get("ws_id")
        if not ws or not lock:
            log.warning("[WS] run_iredev_workflow: no active ws for user=%s", user_id)
            return

        if (
            isinstance(initial_state, dict)
            and initial_state.get("session_id")
            and not (initial_state.get("artifacts") or {})
        ):
            self._completion_sent.discard(chat_id)

        stop_event = self._reset_stop(ws_id, chat_id) if ws_id else None
        config = {"configurable": {"thread_id": chat_id}}

        try:
            for step_output in self.graph.stream(initial_state, config=config):
                if stop_event and stop_event.is_set():
                    log.info("[WS] workflow stopped before dispatch chat=%s", chat_id)
                    return

                # ── Graph paused at interrupt() ────────────────────────────
                if "__interrupt__" in step_output:
                    interrupt_data = step_output["__interrupt__"]
                    self._on_graph_interrupt(interrupt_data, chat_id, ws, lock, stop_event)
                    break

                # ── Normal node output ─────────────────────────────────────
                for node_name, updates in step_output.items():
                    if stop_event and stop_event.is_set():
                        log.info("[WS] workflow stopped before node=%s chat=%s", node_name, chat_id)
                        return
                    if not updates:
                        continue
                    log.debug("[WS] node=%s updates=%s", node_name, list(updates.keys()))
                    self._dispatch_node(node_name, updates, chat_id, ws, lock, stop_event)

        except Exception as exc:
            log.error("[WS] workflow error user=%s chat=%s: %s",
                      user_id, chat_id, exc, exc_info=True)
            self._send(ws, lock, {
                "type": "error",
                "chatId": chat_id,
                "error": str(exc),
            })

    def _on_graph_interrupt(
        self,
        interrupt_data: Any,
        chat_id: str,
        ws,
        lock,
        stop_event: Optional[threading.Event] = None,
    ):
        """
        Called when graph.stream() yields __interrupt__.
 
        Reads review_type and ui_summary from the interrupt payload,
        emits a "workflow_summary" message, then emits the artifact card.
 
        All HITL nodes follow the same interrupt payload schema:
          {
            "review_type":    "<str>",
            "artifact_data":  <dict>,
            "review_payload": <dict>,
            "ui_summary":     "<markdown>",  ← pre-built in graph.py
          }
        """
        log.info("[WS] Graph interrupted (review gate) chat=%s", chat_id)
        self._pending_interrupts[chat_id] = interrupt_data

        # Extract artifact from interrupt payload
        payloads = interrupt_data[0].value

        record_content = payloads.get("artifact_data")

        if record_content is None:
            log.warning("[WS] interrupt payload has unexpected shape: %s", interrupt_data)
            return

        text_mess_id = str(uuid.uuid4())

        # ── 1. Emit summary message ────────────────────────────────────────
        review_type = payloads.get("review_type")
        ui_summary = payloads.get("ui_summary", ARTIFACT_SUMMARIES.get(review_type, ""))
        agent_name = REVIEW_AGENT_NAMES.get(review_type, "CARA")
        self._send_token_stream(
            ws,
            lock,
            chat_id,
            text_mess_id,
            ui_summary,
            "assistant",
            stop_event,
            agent_name,
        )
        if stop_event and stop_event.is_set():
            log.info("[WS] workflow stopped during review summary chat=%s", chat_id)
            return
        add_message(chat_id, role="assistant", content=ui_summary, messID=text_mess_id)

        # ── 2. Emit artifact card ──────────────────────────────────────────
        artifact_mess_id = str(uuid.uuid4())
        artifact_id = record_content.get("id", f"interview_record_{chat_id}")
        artifact_iteration = self._next_artifact_iteration(chat_id, review_type)

        # Build display artifact from the review payload
        artifact_display = {
            "id": artifact_id,
            "title": ARTIFACT_TITLES.get(review_type, review_type.replace("_", " ").title()),
            "content": json.dumps(record_content, indent=2, ensure_ascii=False),
            "language": "json",
            "type": review_type,
            "agentName": agent_name,
            "iteration": artifact_iteration,
        }


        enriched = {**artifact_display, "awaitingFeedback": True}

        ws_payload = {
            "type": "artifact",
            "chatId": chat_id,
            "messageId": artifact_mess_id,
            "artifact": artifact_display,
            "awaitingFeedback": True,
            "iteration": artifact_iteration,
        }

        self._send(ws, lock, ws_payload)

        # Update context
        self._artifact_ctx[chat_id] = {
            "review_type": review_type,
            "artifact_id": artifact_id,
            "message_id": artifact_mess_id,
            "iteration": artifact_iteration,
            "artifact": enriched,
        }

        # Persist
        add_message(chat_id=chat_id, role="assistant", content="", messID=artifact_mess_id, artifact=enriched)
        self._pending_interrupts.pop(chat_id, None)

    def _next_artifact_iteration(self, chat_id: str, review_type: Optional[str]) -> int:
        if not review_type:
            return 1
        try:
            messages = get_messages(chat_id, 0)
        except Exception as exc:
            log.warning("[WS] could not read artifact versions chat=%s type=%s: %s", chat_id, review_type, exc)
            return 1

        matching_count = 0
        max_seen = 0
        for message in messages:
            artifact = message.get("artifact") or {}
            if artifact.get("type") != review_type:
                continue
            matching_count += 1
            try:
                max_seen = max(max_seen, int(artifact.get("iteration") or 0))
            except (TypeError, ValueError):
                pass
        return max(max_seen, matching_count) + 1

    def _dispatch_node(
        self,
        node_name: str,
        updates: Dict,
        chat_id: str,
        ws,
        lock,
        stop_event: Optional[threading.Event] = None,
    ):
        """Route node output to the correct handler."""
        if stop_event and stop_event.is_set():
            log.info("[WS] node dispatch skipped after stop node=%s chat=%s", node_name, chat_id)
            return

        if node_name == "supervisor":
            self._handle_supervisor_status(updates, chat_id, ws, lock, stop_event)
            return

        if node_name == "interviewer_turn":
            self._handle_conversation_turn(updates, chat_id, ws, lock, stop_event)

        elif node_name == "enduser_turn":
            self._handle_conversation_turn(updates, chat_id, ws, lock, stop_event)

        elif node_name in _REVIEW_NODE_NAMES:
            # This fires AFTER interrupt resumes — contains approve/reject result
            self._handle_review_result(updates, chat_id, ws, lock)

        elif node_name in _AGENT_NODE_NAMES:
            # Agent turns that produce artifacts (no interrupt needed here).
            # Their artifacts are emitted when the subsequent interrupt node fires.
            log.debug("[WS] %s completed — artifact will be emitted at next interrupt.", node_name)

        else:
            log.debug("[WS] Unhandled node: %s", node_name)

    def _handle_supervisor_status(
        self,
        updates: Dict,
        chat_id: str,
        ws,
        lock,
        stop_event: Optional[threading.Event] = None,
    ):
        """Emit lightweight workflow status frames for long silent agent steps."""
        next_node = updates.get("next_node")
        if not next_node:
            return

        if next_node == "__end__":
            self._send(ws, lock, {
                "type": "workflow_status",
                "chatId": chat_id,
                "running": False,
                "complete": True,
            })
            with self._state_lock:
                if chat_id in self._completion_sent:
                    return
                self._completion_sent.add(chat_id)

            mess_id = str(uuid.uuid4())
            accum = self._send_token_stream(
                ws,
                lock,
                chat_id,
                mess_id,
                WORKFLOW_COMPLETE_MESSAGE,
                "assistant",
                stop_event,
                "CARA",
            )
            if accum.strip():
                add_message(chat_id=chat_id, role="assistant", content=accum, messID=mess_id)
            return

        status = NODE_STATUS.get(next_node)
        if not status:
            return

        self._send(ws, lock, {
            "type": "workflow_status",
            "chatId": chat_id,
            "running": True,
            "node": next_node,
            **status,
        })

    def _extract_agenda_message_meta(self, updates: Dict, chat_id: str) -> Dict[str, Any]:
        """Read current agenda context for UI display without altering workflow state."""
        agenda = updates.get("elicitation_agenda") or {}
        item = None
        current_index = None
        total_items = None

        if isinstance(agenda, dict):
            items = agenda.get("items") or []
            total_items = len(items) if isinstance(items, list) else None
            raw_index = agenda.get("current_index", 0)
            try:
                current_index = int(raw_index)
            except (TypeError, ValueError):
                current_index = 0
            if isinstance(items, list) and 0 <= current_index < len(items):
                item = items[current_index]

        if not item:
            cached = self._conversation_ctx.get(chat_id) or {}
            return dict(cached)

        meta = {
            "agendaItemId": item.get("id"),
            "agendaItemIndex": (current_index + 1) if current_index is not None else None,
            "agendaTotalItems": total_items,
            "stakeholderRole": item.get("perspective"),
            "focusKind": item.get("focus_kind"),
            "focusRef": item.get("focus_ref"),
            "coveredRefs": item.get("covered_refs"),
            "closeWhen": item.get("close_when"),
            "coveragePoints": item.get("coverage_points"),
        }
        return {k: v for k, v in meta.items() if v not in (None, "")}

    def _handle_conversation_turn(
        self,
        updates: Dict,
        chat_id: str,
        ws,
        lock,
        stop_event: Optional[threading.Event] = None,
    ):
        """Stream the last conversation turn (interviewer or enduser)."""
        conversation = updates.get("conversation") or []
        if not conversation:
            return

        last = conversation[-1]
        role = last.get("role", "unknown")
        content = last.get("content", "").strip()
        if not content:
            return

        mess_id = str(uuid.uuid4())
        message_meta = self._extract_agenda_message_meta(updates, chat_id)
        if message_meta:
            self._conversation_ctx[chat_id] = message_meta

        stakeholder_role = (message_meta.get("stakeholderRole") or "").strip()
        if role == "interviewer":
            agent_name = "Interviewer Agent"
        elif stakeholder_role:
            agent_name = f"{stakeholder_role} (EndUser Agent)"
        else:
            agent_name = "EndUser Agent"
        accum = self._send_token_stream(
            ws,
            lock,
            chat_id,
            mess_id,
            content,
            role,
            stop_event,
            agent_name,
            message_meta,
        )
        if accum.strip():
            add_message(chat_id=chat_id, role=role, content=accum, messID=mess_id)

    def _handle_review_result(self, updates: Dict, chat_id: str, ws, lock):
        """
        Handle review_turn output after interrupt resumes.

        approved=True:
          - emit artifact_accepted for the reviewed artifact
          - graph will continue to the next node (handled in next iteration)

        approved=False:
          - emit revision_start so frontend shows "Revising..." spinner
          - graph re-routes to the appropriate agent turn; next interrupt
            will emit artifact_revised
        """
        ctx = self._artifact_ctx.get(chat_id)
        if not ctx:
            log.warning("[WS] _handle_review_result: no artifact context for chat=%s", chat_id)
            return

        artifact_id = ctx.get("artifact_id")
        review_type = ctx.get("review_type")
        review_file = REVIEW_TYPES.get(review_type)
        artifacts = updates.get("artifacts") or {}
        mess_id = ctx.get("message_id", str(uuid.uuid4()))
        approved = review_file in artifacts  # presence of review result sentinel indicates approval

        if approved:
            log.info("[WS] Review APPROVED chat=%s type=%s", chat_id, review_type)

            artifact_display = {
                "id": artifact_id,
                "title": ARTIFACT_TITLES.get(review_type, review_type.replace("_", " ").title()),
                "content": json.dumps(artifacts.get(review_file), indent=2, ensure_ascii=False),
                "language": "json",
                "type": review_type,
                "agentName": REVIEW_AGENT_NAMES.get(review_type, "CARA"),
                "iteration": ctx.get("iteration", 1),
            }

            # Mark artifact as accepted in DB
            enriched = {**artifact_display, "accepted": True, "awaitingFeedback": False}
            update_message_artifact(mess_id, enriched)

            # Notify frontend
            self._send(ws, lock, {
                "type": "artifact_accepted",
                "chatId": chat_id,
                "messageId": mess_id,
                "artifactId": artifact_id,
            })

            # Clear context — next node will set new context if needed
            self._artifact_ctx.pop(chat_id, None)

        else:
            log.info("[WS] Revise %s chat=%s", review_type, chat_id)
            current_artifact = ctx.get("artifact") or {}
            if current_artifact:
                update_message_artifact(
                    mess_id,
                    {
                        **current_artifact,
                        "accepted": False,
                        "awaitingFeedback": False,
                        "revisionRequested": True,
                    },
                )

    # =========================================================================
    # Per-connection state
    # =========================================================================

    def _init(self, ws_id: int, lock: threading.Lock, user_id: str, ws: Any):
        with self._state_lock:
            self._state[ws_id] = {"lock": lock, "stop": {}}
            self.active_ws[user_id] = {"ws": ws, "lock": lock, "ws_id": ws_id}

    def _cleanup(self, ws_id: int):
        with self._state_lock:
            self._state.pop(ws_id, None)

    def _get(self, ws_id: int) -> Optional[dict]:
        return self._state.get(ws_id)

    def _reset_stop(self, ws_id: int, chat_id: str) -> Optional[threading.Event]:
        with self._state_lock:
            s = self._state.get(ws_id)
            if not s:
                return None
            stop_event = threading.Event()
            s["stop"][chat_id] = stop_event
            return stop_event

    def _set_stop(self, ws_id: int, chat_id: str) -> bool:
        with self._state_lock:
            s = self._state.get(ws_id)
            if not s:
                return False
            stop_event = s["stop"].setdefault(chat_id, threading.Event())
            stop_event.set()
            return True

    # =========================================================================
    # Thread-safe send
    # =========================================================================

    def _send(self, ws, lock: threading.Lock, payload: dict) -> bool:
        try:
            with lock:
                ws.send(json.dumps(payload))
            return True
        except Exception as exc:
            log.debug("[WS] send failed: %s", exc)
            return False

    # =========================================================================
    # Connection entry point
    # =========================================================================

    def handle_connection(self, ws):
        from flask import request as flask_req

        token = flask_req.args.get("token", "")
        user_id = get_user_id_for_token_ws(token)

        if not user_id:
            log.warning("[WS] Rejected  token_prefix=%r", token[:20])
            try:
                ws.send(json.dumps({"type": "error", "error": "Unauthorized"}))
            except Exception:
                pass
            return

        lock = threading.Lock()
        ws_id = id(ws)
        self._init(ws_id, lock, user_id, ws)
        log.info("[WS] Connected  user=%s  ws=%s", user_id, ws_id)

        try:
            self._send(ws, lock, {"type": "connected", "userId": user_id})

            while True:
                try:
                    raw = ws.receive()
                except Exception as exc:
                    log.info("[WS] receive() raised: %s  ws=%s", exc, ws_id)
                    break
                if raw is None:
                    break
                self._dispatch(ws, lock, ws_id, user_id, raw)

        except Exception as exc:
            log.error("[WS] Unhandled  user=%s  err=%s", user_id, exc, exc_info=True)
        finally:
            self._cleanup(ws_id)
            log.info("[WS] Disconnected  user=%s  ws=%s", user_id, ws_id)

    # =========================================================================
    # Frame dispatcher
    # =========================================================================

    def _dispatch(self, ws, lock, ws_id: int, user_id: str, raw: str):
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("[WS] Bad JSON  user=%s: %r", user_id, raw)
            return

        ftype = frame.get("type", "")
        log.debug("[WS] → %s  user=%s", ftype, user_id)

        if ftype == "ping":
            self._send(ws, lock, {"type": "pong"})

        elif ftype == "chat_message":
            chat_id = frame.get("chatId", "").strip()
            content = frame.get("content", "").strip()
            sub_chat = int(frame.get("subChat", 0))

            if not chat_id or not content:
                self._send(ws, lock, {
                    "type": "error",
                    "error": "chat_message requires chatId and content",
                })
                return

            self._reset_stop(ws_id, chat_id)

            if sub_chat in (1, 2):
                role = "interviewer" if sub_chat == 1 else "enduser"
                mess_id = str(uuid.uuid4())
                resp = f"Hello from {role.capitalize()}"
                stop_event = self._reset_stop(ws_id, chat_id)
                agent_name = "Interviewer Agent" if role == "interviewer" else "EndUser Agent"
                accum = self._send_token_stream(
                    ws,
                    lock,
                    chat_id,
                    mess_id,
                    resp,
                    role,
                    stop_event,
                    agent_name,
                )
                if accum.strip():
                    add_message(chat_id=chat_id, role=role, content=accum,
                                messID=mess_id, subChatID=sub_chat)

        elif ftype == "stop_stream":
            chat_id = frame.get("chatId", "").strip()
            if chat_id:
                stopped = self._set_stop(ws_id, chat_id)
                log.info("[WS] stop_stream chat=%s stopped=%s", chat_id, stopped)

        elif ftype == "retry_workflow":
            chat_id = frame.get("chatId", "").strip()
            if not chat_id:
                self._send(ws, lock, {
                    "type": "error",
                    "error": "retry_workflow requires chatId",
                })
                return
            t = threading.Thread(
                target=self.retry_iredev_workflow,
                args=(user_id, chat_id),
                daemon=True,
            )
            t.start()

        elif ftype == "artifact_feedback":
            self._on_artifact_feedback(ws, lock, user_id, frame)

        else:
            log.debug("[WS] Unknown frame type='%s'", ftype)

    def _on_artifact_feedback(self, ws, lock, user_id: str, frame: dict):
        """Handle accept / revise from frontend."""
        chat_id = frame.get("chatId", "").strip()
        artifact_id = frame.get("artifactId", "").strip()
        action = frame.get("action", "").strip()
        comment = frame.get("comment", "").strip()

        if not artifact_id or action not in ("accept", "revise"):
            self._send(ws, lock, {
                "type": "error",
                "error": "artifact_feedback requires artifactId and action (accept|revise)",
            })
            return

        from langgraph.types import Command

        if action == "accept":
            resume_cmd = Command(resume={"approved": True, "feedback": ""})
        else:
            if not comment:
                self._send(ws, lock, {
                    "type": "error",
                    "error": "revise action requires a non-empty comment",
                })
                return
            resume_cmd = Command(resume={"approved": False, "feedback": comment})

        log.info("[WS] artifact_feedback action=%s chat=%s artifact=%s",
                 action, chat_id, artifact_id)

        # Run in background thread — never block the receive loop
        t = threading.Thread(
            target=self.run_iredev_workflow,
            args=(resume_cmd, user_id, chat_id),
            daemon=True,
        )
        t.start()

    def retry_iredev_workflow(self, user_id: str, chat_id: str):
        """Retry the current workflow step from the latest LangGraph checkpoint."""
        ws_entry = self.active_ws.get(user_id, {})
        ws = ws_entry.get("ws")
        lock = ws_entry.get("lock")
        ws_id = ws_entry.get("ws_id")
        if not ws or not lock:
            log.warning("[WS] retry_iredev_workflow: no active ws for user=%s", user_id)
            return

        pending_interrupt = self._pending_interrupts.get(chat_id)
        if pending_interrupt is not None:
            stop_event = self._reset_stop(ws_id, chat_id) if ws_id else None
            log.info("[WS] retrying pending interrupt chat=%s", chat_id)
            self._on_graph_interrupt(pending_interrupt, chat_id, ws, lock, stop_event)
            return

        config = {"configurable": {"thread_id": chat_id}}
        try:
            snapshot = self.graph.get_state(config)
            state_values = dict(snapshot.values or {})
        except Exception as exc:
            log.error("[WS] retry state lookup failed chat=%s: %s", chat_id, exc, exc_info=True)
            self._send(ws, lock, {
                "type": "error",
                "chatId": chat_id,
                "error": "Could not find the current workflow state to retry.",
            })
            return

        if not state_values:
            self._send(ws, lock, {
                "type": "error",
                "chatId": chat_id,
                "error": "No workflow state is available to retry.",
            })
            return

        log.info("[WS] retrying workflow from latest state chat=%s", chat_id)
        self.run_iredev_workflow(state_values, user_id, chat_id)


ws_handler = WSHandler()
