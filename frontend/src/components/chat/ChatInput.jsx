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
import { createElement, useState, useEffect, useRef } from "react";
import {
  ArrowUp,
  Bot,
  BrainCircuit,
  Check,
  ChevronDown,
  ChevronUp,
  Minus,
  Plus,
  Square,
  Users,
} from "lucide-react";
import { Tooltip } from "../ui";
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
      <div className="flex items-center gap-2 text-[11px] font-medium text-[#776B60]">
        {createElement(icon, { size: 13 })}
        <span>{label}</span>
      </div>
      <button
        type="button"
        onClick={onToggle}
        className="flex h-8 w-full items-center justify-between gap-2 rounded-full bg-[#FFFDF8] px-3 text-[12px] text-[#211914] shadow-sm ring-1 ring-[#E2D6C5] transition-colors hover:bg-[#F7F1E8]"
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
        <div className="absolute left-0 right-0 top-full z-20 mt-1 rounded-xl border border-[#E2D6C5] bg-[#FFFDF8] p-1.5 shadow-[0_10px_24px_rgba(49,38,27,0.14)]">
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
                    ? "bg-[#F0E7D8] text-[#211914]"
                    : "text-[#5B5048] hover:bg-[#F7F1E8]"
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
      <div className="flex items-center gap-2 text-[11px] font-medium text-[#776B60]">
        <BrainCircuit size={13} />
        <span>Visionary</span>
      </div>
      <div className="inline-grid h-8 grid-cols-2 rounded-full bg-[#ECE3D6] p-0.5">
        {VISION_MODE_OPTIONS.map((option) => (
          <button
            type="button"
            key={option.value}
            onClick={() => onChange(option.value)}
            className={`rounded-full px-3 text-[11.5px] font-medium transition-all ${
              value === option.value
                ? "bg-[#FFFDF8] text-[#211914] shadow-sm"
                : "text-[#776B60] hover:text-[#211914]"
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
      <div className="text-[11px] font-medium text-[#776B60]">Interview turns</div>
      <div className="inline-flex h-8 items-center overflow-hidden rounded-full bg-[#ECE3D6] p-0.5">
        <button
          type="button"
          onClick={() => update(value - 1)}
          className="flex h-7 w-7 items-center justify-center rounded-full text-[#776B60] hover:bg-[#FFFDF8] hover:text-[#211914]"
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
          className="turns-number-input h-7 w-14 bg-transparent text-center text-[12px] font-medium text-[#211914] outline-none"
        />
        <button
          type="button"
          onClick={() => update(value + 1)}
          className="flex h-7 w-7 items-center justify-center rounded-full text-[#776B60] hover:bg-[#FFFDF8] hover:text-[#211914]"
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
    <div className="mb-3 rounded-xl border border-[#E2D6C5] bg-[#FCF8F1] px-3 py-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.65)]">
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
        <span className="min-w-0 truncate text-[12.5px] font-medium leading-none text-[#776B60] sm:text-[13px]">
          {summary}
        </span>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={onToggle}
      className="group flex min-w-0 max-w-full items-center gap-2 rounded-full px-2.5 py-1.5 text-left text-[#211914] transition-colors hover:bg-[#F3EBDD]"
      aria-expanded={expanded}
    >
      <span className="min-w-0 truncate text-[12.5px] font-medium leading-none text-[#776B60] sm:text-[13px]">
        {summary}
      </span>
      {expanded
        ? <ChevronUp size={15} className="flex-shrink-0 text-[#95887C] group-hover:text-[#4A4038]" />
        : <ChevronDown size={15} className="flex-shrink-0 text-[#95887C] group-hover:text-[#4A4038]" />}
    </button>
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
  const taRef = useRef(null);
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

  function submit() {
    if (!text.trim() || inputDisabled) return;
    onSend(text, currentProcessConfig);
    setConfigOpen(false);
    setText("");
  }

  const inputDisabled = disabled || isStreaming;
  const effectiveConfigOpen = configOpen && showProcessControls && !configLocked;

  return (
    <div className="px-4 pb-5 pt-2 flex-shrink-0">
      <div className="max-w-[720px] mx-auto">
        <div
          className="bg-[#FFFDF8] rounded-2xl border border-[#E2D6C5]
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
                       text-[#211914] leading-relaxed
                       placeholder:text-[#A89C91]
                       focus:outline-none resize-none
                       max-h-[220px] overflow-y-auto
                       disabled:opacity-60"
          />

          <div className="border-t border-[#EFE6DA] px-3 py-3">
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
              {isStreaming ? (
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
