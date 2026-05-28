# backend/routes/chat_routes.py
# =============================================================================
# Chat REST endpoints (no streaming here — streaming is handled by WebSocket).
#
#   GET    /api/chats                            List top-level chats (no project)
#   POST   /api/chats                            Create a top-level chat
#   DELETE /api/chats/<chat_id>                  Delete a chat
#   GET    /api/chats/<chat_id>/<sub>/messages   List messages
#   POST   /api/chats/<chat_id>/<sub>/messages   Save a user message
#   POST   /api/chats/process/start/<chat_id>    Start requirement process
# =============================================================================

import uuid
import re
from flask import Blueprint, request, jsonify
from ..data import database
from ..auth.auth_utils import require_auth
from ..websocket.ws_handler import ws_handler
import logging

from concurrent.futures import ThreadPoolExecutor


logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor()
pending_taks = {}

chat_bp = Blueprint("chat", __name__)

_MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9._:/+\-]+$")
_MAX_INTERVIEW_TURNS = 1000


def _parse_max_turns(value) -> int:
    try:
        max_turns = int(value or 150)
    except (TypeError, ValueError):
        max_turns = 150
    return min(max(max_turns, 5), _MAX_INTERVIEW_TURNS)


def _parse_vision_mode(value) -> str:
    raw = str(value or "fidelity").strip().lower()
    if raw in {"coverage", "infer", "inferred", "reasoning"}:
        return "coverage"
    if raw in {"fidelity", "extract", "normal", "standard"}:
        return "fidelity"
    return "fidelity"


def _clean_model_name(value) -> str | None:
    if not isinstance(value, str):
        return None
    model = value.strip()
    if not model or len(model) > 120:
        return None
    if not _MODEL_NAME_RE.match(model):
        return None
    return model


def _normalise_llm_overrides(data: dict) -> dict:
    raw = data.get("llmOverrides") or data.get("llm_overrides") or {}
    if not isinstance(raw, dict):
        raw = {}

    default_model = _clean_model_name(
        ((raw.get("default") or {}).get("model") if isinstance(raw.get("default"), dict) else None)
        or data.get("defaultModel")
    )
    interview_model = _clean_model_name(
        ((raw.get("interview") or {}).get("model") if isinstance(raw.get("interview"), dict) else None)
        or data.get("interviewModel")
    )

    overrides = {}
    if default_model:
        overrides["default"] = {"model": default_model}
    if interview_model:
        overrides["interview"] = {"model": interview_model}
    return overrides


# =============================================================================
# Conversations
# =============================================================================


@chat_bp.route("", methods=["GET"])
@require_auth
def list_chats(current_user):
    """
    GET /api/chats
    Return top-level chats (not inside any project) for the authenticated user.
    """
    chats = database.get_chats_for_user(current_user["id"])
    return jsonify(sorted(chats, key=lambda c: c["createdAt"], reverse=True)), 200


@chat_bp.route("", methods=["POST"])
@require_auth
def create_chat(current_user):
    """
    POST /api/chats
    Body: { "title": "My chat", "projectId": "<optional>" }
    """
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    project_id = (data.get("projectId") or "").strip() or None

    if not title:
        return jsonify({"error": "Validation error", "message": "title is required."}), 400

    # If projectId given, verify ownership
    if project_id:
        project = database.get_project(project_id)
        if not project:
            return jsonify({"error": "Not found", "message": f"Project '{project_id}' not found."}), 404
        if project["userId"] != current_user["id"]:
            return jsonify({"error": "Forbidden", "message": "You don't own this project."}), 403

    chat = database.create_chat(user_id=current_user["id"], title=title, project_id=project_id)
    return jsonify(chat), 201


@chat_bp.route("/<chat_id>", methods=["DELETE"])
@require_auth
def delete_chat(current_user, chat_id):
    """DELETE /api/chats/<chat_id>"""
    chat = database.get_chat(chat_id)
    if not chat:
        return jsonify({"error": "Not found", "message": f"Chat '{chat_id}' does not exist."}), 404
    if chat["userId"] != current_user["id"]:
        return jsonify({"error": "Forbidden", "message": "You don't own this chat."}), 403

    database.delete_chat(chat_id)
    return jsonify({"ok": True}), 200


# =============================================================================
# Messages
# =============================================================================


@chat_bp.route("/<chat_id>/<sub_chat_id>/messages", methods=["GET"])
@require_auth
def list_messages(current_user, chat_id, sub_chat_id):
    chat = database.get_chat(chat_id)
    if not chat:
        return jsonify({"error": "Not found", "message": f"Chat '{chat_id}' does not exist."}), 404
    if chat["userId"] != current_user["id"]:
        return jsonify({"error": "Forbidden", "message": "You don't own this chat."}), 403

    return jsonify(database.get_messages(chat_id, sub_chat_id)), 200


@chat_bp.route("/<chat_id>/<sub_chat_id>/messages", methods=["POST"])
@require_auth
def save_message(current_user, chat_id, sub_chat_id):
    chat = database.get_chat(chat_id)
    if not chat:
        return jsonify({"error": "Not found", "message": f"Chat '{chat_id}' does not exist."}), 404
    if chat["userId"] != current_user["id"]:
        return jsonify({"error": "Forbidden", "message": "You don't own this chat."}), 403

    data = request.get_json(silent=True) or {}
    role = (data.get("role") or "").strip()
    content = (data.get("content") or "").strip()

    if role not in ("user", "assistant"):
        return jsonify({"error": "Validation error", "message": "role must be 'user' or 'assistant'."}), 400
    if not content:
        return jsonify({"error": "Validation error", "message": "content is required."}), 400

    message = database.add_message(chat_id=chat_id, role=role, content=content, subChatID=sub_chat_id)
    return jsonify(message), 201


@chat_bp.route("/process/start/<chat_id>", methods=["POST"])
@require_auth
def start(current_user, chat_id):
    chat = database.get_chat(chat_id)
    if not chat:
        return jsonify({"error": "Not found", "message": f"Chat '{chat_id}' does not exist."}), 404
    if chat["userId"] != current_user["id"]:
        return jsonify({"error": "Forbidden", "message": "You don't own this chat."}), 403

    req_id = str(uuid.uuid4())
    data = request.get_json(silent=True) or {}
    projDescr = data.get("projectDescription", "").strip()
    if not projDescr:
        return jsonify({"error": "Validation error", "message": "Project Description is required."}), 400

    max_turns = _parse_max_turns(data.get("maxIterations", 150))
    vision_mode = _parse_vision_mode(data.get("visionMode") or data.get("vision_mode"))
    llm_overrides = _normalise_llm_overrides(data)

    from src.config.intake_hint import INTAKE_HINT, VISIONARY_CONTRACT
    input_guidance = INTAKE_HINT
    visionary_contract = VISIONARY_CONTRACT

    initial_state = {
        # ── Session ───────────────────────────────────────────────────────
        "session_id": req_id,
        "project_description": projDescr,
        "input_guidance": input_guidance,
        "visionary_contract": visionary_contract,
        "vision_mode": vision_mode,
        "llm_overrides": llm_overrides,
        # ── Phase ─────────────────────────────────────────────────────────
        "system_phase": "sprint_zero_planning",
        # ── Artifacts ─────────────────────────────────────────────────────
        "artifacts": {},
        # ── Interview sub-state ───────────────────────────────────────────
        "conversation": [],
        "turn_count": 0,
        # max_turns is a global safety net. Each focus item also has its own
        # turn safety limit inside InterviewerAgent.
        "max_turns": max_turns,
        "interview_complete": False,
        # ── Live requirements draft (populated incrementally per turn) ─────
        # InterviewerAgent.update_requirements appends here after each
        # stakeholder reply. write_interview_record copies this into
        # interview_record["items"].
        "requirements_draft": [],
        "backlog_draft": [],
        "errors": [],
        "_needs_srs_synthesis": False,
        "_workflow_started_message": False,
    }
    logger.info(
        "Starting requirement process chat=%s request=%s vision_mode=%s max_turns=%s llm=%s",
        chat_id,
        req_id,
        vision_mode,
        max_turns,
        llm_overrides,
    )

    task = executor.submit(
        ws_handler.run_iredev_workflow, initial_state, current_user["id"], chat_id
    )
    pending_taks[req_id] = task
    return {
        "request_id": req_id,
        "process_config": {
            "visionMode": vision_mode,
            "maxIterations": max_turns,
            "llmOverrides": llm_overrides,
        },
    }
