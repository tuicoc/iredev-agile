// src/components/chat/ChatInput.jsx
// =============================================================================
// Message input bar at the bottom of the chat.
//
// Behaviour:
//   - Auto-growing textarea (up to 220px)
//   - Enter to send, Shift+Enter for newline
//   - While streaming: shows a "Stop" button instead of Send
//   - onCancel() is called when the user clicks Stop
//   - Paperclip (process-start composer only): uploads a PDF, backend converts
//     it to Markdown via MarkItDown; ready attachments are passed to onSend
//     and become part of the Visionary's input signal
// =============================================================================
import { createElement, useState, useEffect, useRef } from "react";
import {
  ArrowUp,
  Bot,
  BrainCircuit,
  Check,
  ChevronDown,
  ChevronUp,
  FileText,
  Loader2,
  Minus,
  Paperclip,
  Plus,
  Square,
  Users,
  X,
} from "lucide-react";
import { Tooltip } from "../ui";
import { convertProcessFile } from "../../services/chatService";
import {
  MODEL_OPTIONS,
  VISION_MODE_OPTIONS,
  normalizeProcessConfig,
} from "../../utils/processConfig";

function optionsWithValue(value) {
  if (MODEL_OPTIONS.some((option) => option.value === value)) return MODEL_OPTIONS;
  return [...MODEL_OPTIONS, { value, label: value }];
}

function modelLabel(value) {
  return MODEL_OPTIONS.find((option) => option.value === value)?.label || value;
}

function visionLabel(value) {
  return VISION_MODE_OPTIONS.find((option) => option.value === value)?.label || "Extract";
}

function ModelDropdown({ label, value, onChange, icon, open, onToggle }) {
  const options = optionsWithValue(value);
  const selectedLabel = modelLabel(value);

  return (
    <div className="relative space-y-2">
      <div className="flex items-center gap-2 text-[11px] font-medium text-[#6B6B6B]">
        {createElement(icon, { size: 13 })}
        <span>{label}</span>
      </div>
      <button
        type="button"
        onClick={onToggle}
        className="flex h-8 w-full items-center justify-between gap-2 rounded-full bg-[#FFFFFF] px-3 text-[12px] text-[#1A1A1A] shadow-sm ring-1 ring-[#E5E5E5] transition-colors hover:bg-[#F5F5F5]"
        aria-expanded={open}
      >
        <span className="truncate">{selectedLabel}</span>
        {open ? (
          <ChevronUp size={14} className="flex-shrink-0 text-[#95887C]" />
        ) : (
          <ChevronDown size={14} className="flex-shrink-0 text-[#95887C]" />
        )}
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-20 mt-1 rounded-xl border border-[#E5E5E5] bg-[#FFFFFF] p-1.5 shadow-[0_10px_24px_rgba(49,38,27,0.14)]">
          {options.map((option) => {
            const selected = option.value === value;
            return (
              <button
                type="button"
                key={option.value}
                onClick={() => {
                  onChange(option.value);
                  onToggle(false);
                }}
                className={`flex h-8 w-full items-center justify-between rounded-lg px-2.5 text-left text-[12px] transition-colors ${
                  selected
                    ? "bg-[#F0F0F0] text-[#1A1A1A]"
                    : "text-[#505050] hover:bg-[#F5F5F5]"
                }`}
              >
                <span className="truncate">{option.label}</span>
                {selected && <Check size={13} className="flex-shrink-0" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function VisionModeControl({ value, onChange }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-[11px] font-medium text-[#6B6B6B]">
        <BrainCircuit size={13} />
        <span>Visionary</span>
      </div>
      <div className="inline-grid h-8 grid-cols-2 rounded-full bg-[#EFEFEF] p-0.5">
        {VISION_MODE_OPTIONS.map((option) => (
          <button
            type="button"
            key={option.value}
            onClick={() => onChange(option.value)}
            className={`rounded-full px-3 text-[11.5px] font-medium transition-all ${
              value === option.value
                ? "bg-[#FFFFFF] text-[#1A1A1A] shadow-sm"
                : "text-[#6B6B6B] hover:text-[#1A1A1A]"
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function TurnControl({ value, onChange }) {
  const update = (next) => {
    onChange(normalizeProcessConfig({ maxIterations: next }).maxIterations);
  };

  return (
    <div className="space-y-2">
      <div className="text-[11px] font-medium text-[#6B6B6B]">Interview turns</div>
      <div className="inline-flex h-8 items-center overflow-hidden rounded-full bg-[#EFEFEF] p-0.5">
        <button
          type="button"
          onClick={() => update(value - 1)}
          className="flex h-7 w-7 items-center justify-center rounded-full text-[#6B6B6B] hover:bg-[#FFFFFF] hover:text-[#1A1A1A]"
        >
          <Minus size={13} />
        </button>
        <input
          type="number"
          min={5}
          max={1000}
          step={1}
          value={value}
          onChange={(event) => update(event.target.value)}
          className="turns-number-input h-7 w-14 bg-transparent text-center text-[12px] font-medium text-[#1A1A1A] outline-none"
        />
        <button
          type="button"
          onClick={() => update(value + 1)}
          className="flex h-7 w-7 items-center justify-center rounded-full text-[#6B6B6B] hover:bg-[#FFFFFF] hover:text-[#1A1A1A]"
        >
          <Plus size={13} />
        </button>
      </div>
    </div>
  );
}

function ProcessSettingsPanel({ config, onChange }) {
  const [openModelPicker, setOpenModelPicker] = useState(null);
  const current = normalizeProcessConfig(config);

  const update = (patch) => {
    onChange?.(normalizeProcessConfig({ ...current, ...patch }));
  };

  return (
    <div className="mb-3 rounded-xl border border-[#E5E5E5] bg-[#F8F8F8] px-3 py-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.65)]">
      <div className="grid gap-4 md:grid-cols-2">
        <ModelDropdown
          label="General model"
          value={current.defaultModel}
          onChange={(defaultModel) => update({ defaultModel })}
          icon={Bot}
          open={openModelPicker === "default"}
          onToggle={(nextOpen = openModelPicker !== "default") =>
            setOpenModelPicker(nextOpen ? "default" : null)
          }
        />
        <ModelDropdown
          label="Interview model"
          value={current.interviewModel}
          onChange={(interviewModel) => update({ interviewModel })}
          icon={Users}
          open={openModelPicker === "interview"}
          onToggle={(nextOpen = openModelPicker !== "interview") =>
            setOpenModelPicker(nextOpen ? "interview" : null)
          }
        />
      </div>
      <div className="mt-4 flex flex-wrap items-end justify-between gap-4">
        <VisionModeControl
          value={current.visionMode}
          onChange={(visionMode) => update({ visionMode })}
        />
        <TurnControl
          value={current.maxIterations}
          onChange={(maxIterations) => update({ maxIterations })}
        />
      </div>
    </div>
  );
}

function ProcessConfigToggle({ config, locked, expanded, onToggle }) {
  const current = normalizeProcessConfig(config);
  const summary = `${modelLabel(current.defaultModel)} · ${modelLabel(current.interviewModel)} · ${visionLabel(current.visionMode)} · ${current.maxIterations}`;

  if (locked) {
    return (
      <div className="flex min-w-0 max-w-full items-center rounded-full px-2.5 py-1.5">
        <span className="min-w-0 truncate text-[12.5px] font-medium leading-none text-[#6B6B6B] sm:text-[13px]">
          {summary}
        </span>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={onToggle}
      className="group flex min-w-0 max-w-full items-center gap-2 rounded-full px-2.5 py-1.5 text-left text-[#1A1A1A] transition-colors hover:bg-[#F0F0F0]"
      aria-expanded={expanded}
    >
      <span className="min-w-0 truncate text-[12.5px] font-medium leading-none text-[#6B6B6B] sm:text-[13px]">
        {summary}
      </span>
      {expanded
        ? <ChevronUp size={15} className="flex-shrink-0 text-[#95887C] group-hover:text-[#3A3A3A]" />
        : <ChevronDown size={15} className="flex-shrink-0 text-[#95887C] group-hover:text-[#3A3A3A]" />}
    </button>
  );
}

function AttachmentChip({ attachment, onRemove }) {
  const isError = attachment.status === "error";
  const isConverting = attachment.status === "converting";

  return (
    <div
      className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[12px] ${
        isError
          ? "border-[#E8B4B4] bg-[#FDF3F3] text-[#A04545]"
          : "border-[#E5E5E5] bg-[#F8F8F8] text-[#3A3A3A]"
      }`}
    >
      {isConverting ? (
        <Loader2 size={13} className="flex-shrink-0 animate-spin text-[#B86F50]" />
      ) : (
        <FileText
          size={13}
          className={`flex-shrink-0 ${isError ? "text-[#A04545]" : "text-[#B86F50]"}`}
        />
      )}
      <span className="max-w-[180px] truncate font-medium">{attachment.filename}</span>
      {isConverting && <span className="text-[#A0A0A0]">converting…</span>}
      {isError && (
        <span className="max-w-[200px] truncate" title={attachment.error}>
          {attachment.error}
        </span>
      )}
      {attachment.status === "ready" && attachment.truncated && (
        <span className="text-[#A0A0A0]">(truncated)</span>
      )}
      <button
        type="button"
        onClick={onRemove}
        className={`flex-shrink-0 rounded-full p-0.5 transition-colors ${
          isError
            ? "text-[#A04545] hover:bg-[#F2DCDC]"
            : "text-[#A0A0A0] hover:bg-[#E8E8E8] hover:text-[#3A3A3A]"
        }`}
        aria-label={`Remove ${attachment.filename}`}
      >
        <X size={12} />
      </button>
    </div>
  );
}

export function ChatInput({
  onSend,
  disabled,
  isStreaming = disabled,
  onCancel,
  processConfig,
  onProcessConfigChange,
  configLocked = false,
  showProcessControls = true,
}) {
  const [text, setText] = useState("");
  const [configOpen, setConfigOpen] = useState(false);
  const [attachments, setAttachments] = useState([]);
  const taRef = useRef(null);
  const fileRef = useRef(null);
  const currentProcessConfig = normalizeProcessConfig(processConfig);

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

  async function handleFilePick(e) {
    const files = Array.from(e.target.files || []);
    e.target.value = ""; // allow re-selecting the same file later
    for (const file of files) {
      const id = `att_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
      setAttachments((prev) => [
        ...prev,
        { id, filename: file.name, status: "converting" },
      ]);
      try {
        const res = await convertProcessFile(file);
        setAttachments((prev) =>
          prev.map((a) =>
            a.id === id
              ? {
                  ...a,
                  status: "ready",
                  filename: res.filename || a.filename,
                  markdown: res.markdown,
                  truncated: !!res.truncated,
                }
              : a,
          ),
        );
      } catch (err) {
        setAttachments((prev) =>
          prev.map((a) =>
            a.id === id
              ? { ...a, status: "error", error: err?.message || "Conversion failed" }
              : a,
          ),
        );
      }
    }
  }

  function removeAttachment(id) {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  }

  function submit() {
    if (!canSend) return;
    onSend(
      text,
      currentProcessConfig,
      readyAttachments.map(({ filename, markdown }) => ({ filename, markdown })),
    );
    setConfigOpen(false);
    setText("");
    setAttachments([]);
  }

  const inputDisabled = disabled || isStreaming;
  const effectiveConfigOpen = configOpen && showProcessControls && !configLocked;
  // Attachments feed the process start (project_description), so the paperclip
  // only appears while this composer can still start a process.
  const showAttach = showProcessControls && !configLocked;
  const readyAttachments = attachments.filter((a) => a.status === "ready");
  const converting = attachments.some((a) => a.status === "converting");
  const canSend =
    (text.trim() || readyAttachments.length > 0) && !inputDisabled && !converting;

  return (
    <div className="px-4 pb-5 pt-2 flex-shrink-0">
      <div className="max-w-[720px] mx-auto">
        <div
          className="bg-[#FFFFFF] rounded-2xl border border-[#E5E5E5]
                        shadow-[0_2px_8px_rgba(0,0,0,0.06)]
                        focus-within:border-[#B86F50]/50
                        focus-within:shadow-[0_0_0_3px_rgba(184,111,80,0.12),0_2px_8px_rgba(0,0,0,0.06)]
                        transition-all duration-150"
        >
          <textarea
            ref={taRef}
            rows={1}
            placeholder="Message CARA…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={inputDisabled}
            className="w-full px-4 pt-3.5 pb-2 bg-transparent text-[14px]
                       text-[#1A1A1A] leading-relaxed
                       placeholder:text-[#A0A0A0]
                       focus:outline-none resize-none
                       max-h-[220px] overflow-y-auto
                       disabled:opacity-60"
          />

          {attachments.length > 0 && (
            <div className="flex flex-wrap gap-2 px-4 pb-2.5">
              {attachments.map((att) => (
                <AttachmentChip
                  key={att.id}
                  attachment={att}
                  onRemove={() => removeAttachment(att.id)}
                />
              ))}
            </div>
          )}

          <div className="border-t border-[#E8E8E8] px-3 py-3">
            {effectiveConfigOpen && (
              <ProcessSettingsPanel
                config={currentProcessConfig}
                onChange={onProcessConfigChange}
              />
            )}

            <div className="flex items-center justify-between gap-2">
              {showProcessControls ? (
                <ProcessConfigToggle
                  config={currentProcessConfig}
                  locked={configLocked}
                  expanded={effectiveConfigOpen}
                  onToggle={() => setConfigOpen((open) => !open)}
                />
              ) : (
                <span />
              )}
              <div className="flex items-center gap-1.5">
                {showAttach && (
                  <>
                    <input
                      ref={fileRef}
                      type="file"
                      accept=".pdf,application/pdf"
                      multiple
                      className="hidden"
                      onChange={handleFilePick}
                    />
                    <Tooltip text="Attach PDF">
                      <button
                        type="button"
                        onClick={() => fileRef.current?.click()}
                        disabled={inputDisabled}
                        className="w-8 h-8 flex items-center justify-center rounded-full
                                   text-[#6B6B6B] hover:bg-[#F0F0F0] hover:text-[#1A1A1A]
                                   transition-colors disabled:opacity-50
                                   disabled:cursor-not-allowed"
                      >
                        <Paperclip size={15} />
                      </button>
                    </Tooltip>
                  </>
                )}
                {isStreaming ? (
                  <Tooltip text="Stop generating">
                    <button
                      onClick={onCancel}
                      className="w-8 h-8 flex items-center justify-center rounded-full
                                 bg-[#1A1A1A] hover:bg-[#3A3A3A]
                                 text-white transition-colors shadow-sm"
                    >
                      <Square size={12} fill="currentColor" />
                    </button>
                  </Tooltip>
                ) : (
                  <Tooltip text="Send message">
                    <button
                      onClick={submit}
                      disabled={!canSend}
                      className={`w-8 h-8 flex items-center justify-center rounded-full
                                  transition-all duration-150 ${
                                    canSend
                                      ? "bg-[#B86F50] hover:bg-[#A76145] text-white shadow-sm"
                                      : "bg-[#EFEFEF] text-[#A8A8A8] cursor-not-allowed"
                                  }`}
                    >
                      <ArrowUp size={15} strokeWidth={2.5} />
                    </button>
                  </Tooltip>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Disclaimer */}
        <p className="text-center text-[11px] text-[#A8A8A8] mt-2.5">
          CARA can make mistakes. Please check important information.
        </p>
      </div>
    </div>
  );
}
