// src/components/artifact/ArtifactFeedbackBar.jsx
// =============================================================================
// Shown at the bottom of the ArtifactPanel when the backend is waiting for
// human feedback (awaitingFeedback === true).
//
// Renders two modes:
//   1. Default: "Accept" button + "Request changes" button
//   2. After clicking "Request changes": a textarea + "Send" button
//
// Props:
//   artifactId  {string}    ID of the artifact version awaiting feedback
//   chatId      {string}    Active chat ID
//   messageId   {string}    Message ID that owns this artifact
//   iteration   {number}    Which revision iteration we're on (shown in UI)
//   onAccept    {Function}  Called when user clicks Accept
//   onRevise    {Function}  Called with (comment) when user submits feedback

// Shown at the bottom of the ArtifactPanel when awaitingFeedback === true.
// Also shows a "Revising…" spinner when revising === true (optimistic state
// between the user clicking "Request changes" and the artifact_revised frame
// arriving from the backend).
import { useState } from "react";
import { AlertTriangle, Check, Pencil, Send, X, Loader } from "lucide-react";

function parseArtifactContent(artifact) {
  try {
    return typeof artifact?.content === "string"
      ? JSON.parse(artifact.content)
      : artifact?.content || {};
  } catch {
    return {};
  }
}

export function ArtifactFeedbackBar({
  artifact,
  iteration,
  onAccept,
  onRevise,
}) {
  const [revising, setRevising] = useState(false);
  const [comment, setComment] = useState("");
  const parsed = parseArtifactContent(artifact);
  const conflicts = Array.isArray(parsed?.conflicts) ? parsed.conflicts : [];
  const hasConflicts =
    artifact?.type === "requirement_list" &&
    (parsed?.has_conflicts || conflicts.length > 0);
  const approveOnly = artifact?.type === "interview_record";

  // The artifact is currently being revised by the backend
  if (artifact?.revising) {
    return (
      <div className="border-t border-[#E5E5E5] bg-[#F8F8F8] flex-shrink-0">
        <div className="flex items-center gap-2.5 px-4 py-4">
          <Loader
            size={14}
            className="text-[#B86F50] animate-spin flex-shrink-0"
          />
          <span className="text-[12px] text-[#3A3A3A] font-medium">
            Revising — generating new version…
          </span>
        </div>
      </div>
    );
  }

  function handleReviseSubmit() {
    if (!comment.trim()) return;
    onRevise(comment.trim());
    setComment("");
    setRevising(false);
  }

  function handleKeyDown(e) {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") handleReviseSubmit();
    if (e.key === "Escape") {
      setRevising(false);
      setComment("");
    }
  }

  return (
    <div className="border-t border-[#E5E5E5] bg-[#F8F8F8] flex-shrink-0">
      {/* Iteration indicator */}
      <div className="flex items-center justify-between px-4 pt-3 pb-1">
        <div className="flex items-center gap-1.5">
          <span className="relative flex h-2 w-2">
            <span
              className="animate-ping absolute inline-flex h-full w-full
                             rounded-full bg-[#B86F50] opacity-75"
            />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-[#B86F50]" />
          </span>
          <span className="text-[12px] font-medium text-[#1A1A1A]">
            Awaiting your review
          </span>
        </div>
        <span className="text-[11px] text-[#A0A0A0]">
          v{iteration}
        </span>
      </div>

      {hasConflicts ? (
        <div className="px-4 pb-3">
          <div className="mb-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
            <div className="flex items-center gap-2 text-[12px] font-semibold text-amber-800">
              <AlertTriangle size={14} />
              Conflict resolution required
            </div>
            <p className="mt-1 text-[11px] leading-relaxed text-amber-900">
              Resolve the conflicts before this Requirement List can be accepted.
              The Distiller Agent will regenerate the list from your resolution.
            </p>
          </div>
          <textarea
            autoFocus
            rows={4}
            placeholder="Write the resolution decision for each conflict..."
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            onKeyDown={handleKeyDown}
            className="w-full px-3 py-2 bg-[#FFFFFF] border border-[#E5E5E5] rounded-lg
                       text-[13px] text-[#1A1A1A] placeholder:text-[#A0A0A0]
                       focus:outline-none focus:ring-1 focus:ring-[#B86F50]/30
                       focus:border-[#B86F50]/50 resize-none transition-all"
          />
          <div className="flex justify-end mt-2">
            <button
              onClick={handleReviseSubmit}
              disabled={!comment.trim()}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg
                         text-[12px] font-medium
                         bg-[#B86F50] hover:bg-[#A76145] text-white
                         disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Send size={13} /> Send resolution
            </button>
          </div>
        </div>
      ) : revising ? (
        <div className="px-4 pb-3">
          <textarea
            autoFocus
            rows={3}
            placeholder="Describe what you'd like changed… (Ctrl+Enter to send)"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            onKeyDown={handleKeyDown}
            className="w-full px-3 py-2 bg-[#FFFFFF] border border-[#E5E5E5] rounded-lg
                       text-[13px] text-[#1A1A1A] placeholder:text-[#A0A0A0]
                       focus:outline-none focus:ring-1 focus:ring-[#B86F50]/30
                       focus:border-[#B86F50]/50 resize-none transition-all"
          />
          <div className="flex gap-2 mt-2">
            <button
              onClick={() => {
                setRevising(false);
                setComment("");
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg
                         text-[12px] text-[#6B6B6B] hover:bg-[#EFEFEF] transition-colors"
            >
              <X size={13} /> Cancel
            </button>
            <button
              onClick={handleReviseSubmit}
              disabled={!comment.trim()}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg
                         text-[12px] font-medium ml-auto
                         bg-[#B86F50] hover:bg-[#A76145] text-white
                         disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Send size={13} /> Send feedback
            </button>
          </div>
        </div>
      ) : (
        <div className="flex gap-2 px-4 pb-3">
          <button
            onClick={onAccept}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg
                       text-[13px] font-medium
                       bg-[#16A34A] hover:bg-[#15803D] text-white
                       transition-colors shadow-sm"
          >
            <Check size={14} /> Accept
          </button>
          {!approveOnly && (
            <button
              onClick={() => setRevising(true)}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg
                         text-[13px] font-medium
                         border border-[#E5E5E5] text-[#3A3A3A]
                         hover:bg-[#EFEFEF] hover:border-[#C5C5C5] transition-colors"
            >
              <Pencil size={13} /> Request changes
            </button>
          )}
        </div>
      )}
    </div>
  );
}
