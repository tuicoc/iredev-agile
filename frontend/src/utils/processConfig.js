export const MODEL_OPTIONS = [
  { value: "gpt-5.4", label: "GPT-5.4" },
  { value: "gpt-5.4-mini", label: "GPT-5.4 Mini" },
  { value: "gpt-5.4-nano", label: "GPT-5.4 Nano" },
  { value: "gpt-4o-mini", label: "GPT-4o Mini" },
  { value: "gemini-3.1-flash-lite", label: "Gemini 3.1 Flash Lite" },
];

export const VISION_MODE_OPTIONS = [
  { value: "extract", label: "Extract" },
  { value: "infer", label: "Infer" },
];

export const DEFAULT_PROCESS_CONFIG = {
  defaultModel: "gpt-5.4",
  interviewModel: "gpt-5.4-mini",
  visionMode: "infer",
  maxIterations: 150,
};

const MIN_TURNS = 5;
const MAX_TURNS = 1000;

export function clampTurns(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return DEFAULT_PROCESS_CONFIG.maxIterations;
  return Math.min(Math.max(Math.round(numeric), MIN_TURNS), MAX_TURNS);
}

function modelValue(value, fallback) {
  const raw = typeof value === "string" ? value.trim() : "";
  return raw || fallback;
}

export function normalizeProcessConfig(config = {}) {
  const base = {
    ...DEFAULT_PROCESS_CONFIG,
    ...config,
  };

  return {
    defaultModel: modelValue(base.defaultModel, DEFAULT_PROCESS_CONFIG.defaultModel),
    interviewModel: modelValue(base.interviewModel, DEFAULT_PROCESS_CONFIG.interviewModel),
    visionMode: base.visionMode === "infer" || base.visionMode === "coverage"
      ? "infer"
      : "extract",
    maxIterations: clampTurns(base.maxIterations),
  };
}

export function processConfigToStartPayload(config = {}) {
  const normalised = normalizeProcessConfig(config);
  return {
    maxIterations: normalised.maxIterations,
    visionMode: normalised.visionMode === "infer" ? "coverage" : "fidelity",
    llmOverrides: {
      default: { model: normalised.defaultModel },
      interview: { model: normalised.interviewModel },
    },
  };
}

export function processConfigStorageKey(chatId) {
  return `requirement_process_config:${chatId}`;
}

export function loadChatProcessConfig(chatId) {
  if (!chatId) return normalizeProcessConfig();
  try {
    const saved = localStorage.getItem(processConfigStorageKey(chatId));
    return normalizeProcessConfig(saved ? JSON.parse(saved) : {});
  } catch {
    return normalizeProcessConfig();
  }
}

export function saveChatProcessConfig(chatId, config) {
  if (!chatId) return;
  try {
    localStorage.setItem(
      processConfigStorageKey(chatId),
      JSON.stringify(normalizeProcessConfig(config)),
    );
  } catch {
    // Storage is a convenience; the workflow payload remains authoritative.
  }
}
