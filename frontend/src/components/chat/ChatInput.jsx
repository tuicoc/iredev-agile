// src/components/chat/ChatInput.jsx
// =============================================================================
// Message input bar at the bottom of the chat.
//
// Behaviour:
//   - Auto-growing textarea (up to 220px)
//   - Enter to send, Shift+Enter for newline
//   - While streaming: shows a "Stop" button instead of Send
//   - onCancel() is called when the user clicks Stop
// =============================================================================
import { useState, useEffect, useRef } from "react";
import { Paperclip, ArrowUp, Square, Mic } from "lucide-react";
import { Tooltip } from "../ui";

export function ChatInput({ onSend, disabled, isStreaming = disabled, onCancel }) {
  const [text, setText] = useState("");
  const taRef = useRef(null);

  // Auto-grow textarea to fit content
  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 220) + "px";
  }, [text]);

  function handleKeyDown(e) {
    // Enter (no Shift) = send; Shift+Enter = newline
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  function submit() {
    if (!text.trim() || inputDisabled) return;
    onSend(text);
    setText("");
  }

  const inputDisabled = disabled || isStreaming;

  return (
    <div className="px-4 pb-5 pt-2 flex-shrink-0">
      <div className="max-w-[720px] mx-auto">
        {/* Input card */}
        <div
          className="relative bg-[#FFFDF8] rounded-2xl border border-[#E2D6C5]
                        shadow-[0_2px_8px_rgba(0,0,0,0.06)]
                        focus-within:border-[#B86F50]/50
                        focus-within:shadow-[0_0_0_3px_rgba(184,111,80,0.12),0_2px_8px_rgba(0,0,0,0.06)]
                        transition-all duration-150"
        >
          {/* Textarea */}
          <textarea
            ref={taRef}
            rows={1}
            placeholder="Message CARA…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={inputDisabled}
            className="w-full px-4 pt-3.5 pb-[52px] bg-transparent text-[14px]
                       text-[#211914] leading-relaxed
                       placeholder:text-[#A89C91]
                       focus:outline-none resize-none
                       max-h-[220px] overflow-y-auto
                       disabled:opacity-60"
          />

          {/* Bottom action row — sits inside the card */}
          <div
            className="absolute bottom-0 left-0 right-0
                          flex items-center justify-between px-3 pb-3 pt-1"
          >
            {/* Left: attach button */}
            <Tooltip text="Attach files">
              <button
                disabled={inputDisabled}
                className="w-8 h-8 flex items-center justify-center rounded-lg
                           text-[#A89C91] hover:text-[#776B60] hover:bg-[#EFE6D8]
                           disabled:opacity-40 transition-colors"
              >
                <Paperclip size={16} />
              </button>
            </Tooltip>

            {/* Right: mic + send-or-stop */}
            <div className="flex items-center gap-1.5">
              <Tooltip text="Voice input">
                <button
                  disabled={inputDisabled}
                  className="w-8 h-8 flex items-center justify-center rounded-lg
                             text-[#A89C91] hover:text-[#776B60] hover:bg-[#EFE6D8]
                             disabled:opacity-40 transition-colors"
                >
                  <Mic size={15} />
                </button>
              </Tooltip>

              {isStreaming ? (
                // ── Stop button — shown while AI is generating ──────────────
                // Clicking this calls onCancel() which aborts the SSE stream
                <Tooltip text="Stop generating">
                  <button
                    onClick={onCancel}
                    className="w-8 h-8 flex items-center justify-center rounded-full
                               bg-[#211914] hover:bg-[#4A4038]
                               text-white transition-colors shadow-sm"
                  >
                    <Square size={12} fill="currentColor" />
                  </button>
                </Tooltip>
              ) : (
                // ── Send button — shown when idle ───────────────────────────
                <Tooltip text="Send message">
                  <button
                    onClick={submit}
                    disabled={!text.trim() || inputDisabled}
                    className={`w-8 h-8 flex items-center justify-center rounded-full
                                transition-all duration-150 ${
                                  text.trim() && !inputDisabled
                                    ? "bg-[#B86F50] hover:bg-[#A76145] text-white shadow-sm"
                                    : "bg-[#ECE3D6] text-[#B0A49A] cursor-not-allowed"
                                }`}
                  >
                    <ArrowUp size={15} strokeWidth={2.5} />
                  </button>
                </Tooltip>
              )}
            </div>
          </div>
        </div>

        {/* Disclaimer */}
        <p className="text-center text-[11px] text-[#B0A49A] mt-2.5">
          CARA can make mistakes. Please check important information.
        </p>
      </div>
    </div>
  );
}
