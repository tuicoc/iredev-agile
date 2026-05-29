// src/components/chat/IntakeQuestions.jsx
// =============================================================================
// Inline "AskUserQuestion"-style card, shown directly above the chat composer
// when the Visionary's intake gate (Pass 0) is waiting for answers.
//
// Mirrors Claude's question interface: a floating card with paginated
// questions, numbered options, a free-text "Something else" row, a per-question
// Skip, and keyboard navigation (↑↓ to move, Enter to select, Esc to clear a
// custom entry).
//
// Props:
//   questions {Array}    [{ header, question, multi_select, options:[{label, description}] }]
//   onSubmit  {Function} called once with the full answer set when the last
//                        question is answered/skipped (or the card is closed):
//                        [{ header, question, multi_select, selected:[label…],
//                           custom_text, skipped }]
// =============================================================================
import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { ChevronLeft, ChevronRight, X, Check, Pencil, ArrowRight, CornerDownLeft } from "lucide-react";

function emptyAnswer() {
  return { selected: [], customText: "", skipped: false, touched: false };
}

export function IntakeQuestions({ questions = [], onSubmit }) {
  const total = questions.length;
  const [current, setCurrent] = useState(0);
  const [answers, setAnswers] = useState(() => questions.map(emptyAnswer));
  const [focus, setFocus] = useState(0);
  const [customOpen, setCustomOpen] = useState(false);
  const [mounted, setMounted] = useState(false);

  const cardRef = useRef(null);
  const customRef = useRef(null);

  const q = questions[current] || {};
  const opts = q.options || [];
  const multi = !!q.multi_select;
  const cur = answers[current] || emptyAnswer();
  const isLast = current === total - 1;
  const somethingElseIdx = opts.length; // focus index of the "Something else" row

  useEffect(() => setMounted(true), []);

  // Reset row focus + custom input visibility when the question changes.
  useEffect(() => {
    setFocus(0);
    setCustomOpen(Boolean(answers[current]?.customText));
    if (!answers[current]?.customText) {
      requestAnimationFrame(() => cardRef.current?.focus());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current]);

  const buildPayload = useCallback(
    (arr) =>
      questions.map((qq, i) => {
        const a = arr[i] || emptyAnswer();
        const selected = a.selected || [];
        const customText = (a.customText || "").trim();
        return {
          header: qq.header || "",
          question: qq.question || "",
          multi_select: !!qq.multi_select,
          selected,
          custom_text: customText,
          skipped: a.skipped || (selected.length === 0 && !customText),
        };
      }),
    [questions],
  );

  const goNextOrSubmit = useCallback(
    (arr) => {
      if (isLast) onSubmit?.(buildPayload(arr));
      else setCurrent((c) => Math.min(c + 1, total - 1));
    },
    [isLast, onSubmit, buildPayload, total],
  );

  const patchCurrent = useCallback(
    (patch) => answers.map((a, i) => (i === current ? { ...a, ...patch } : a)),
    [answers, current],
  );

  const chooseOption = useCallback(
    (label) => {
      let arr;
      if (multi) {
        const has = cur.selected.includes(label);
        const selected = has
          ? cur.selected.filter((l) => l !== label)
          : [...cur.selected, label];
        arr = patchCurrent({ selected, skipped: false, touched: true });
        setAnswers(arr); // multi: toggle only, advance via "Continue"
      } else {
        arr = patchCurrent({ selected: [label], customText: "", skipped: false, touched: true });
        setAnswers(arr);
        setCustomOpen(false);
        goNextOrSubmit(arr); // single: select advances
      }
    },
    [multi, cur.selected, patchCurrent, goNextOrSubmit],
  );

  const skipCurrent = useCallback(() => {
    const arr = patchCurrent({ selected: [], customText: "", skipped: true, touched: true });
    setAnswers(arr);
    goNextOrSubmit(arr);
  }, [patchCurrent, goNextOrSubmit]);

  const continueMulti = useCallback(() => {
    // Capture any text typed into "Something else" that wasn't explicitly added.
    const pendingCustom = customOpen ? (customRef.current?.value || "").trim() : "";
    const arr = patchCurrent({
      customText: pendingCustom || cur.customText,
      touched: true,
    });
    setAnswers(arr);
    goNextOrSubmit(arr);
  }, [customOpen, cur.customText, patchCurrent, goNextOrSubmit]);

  const submitCustom = useCallback(() => {
    const text = (customRef.current?.value || "").trim();
    if (!text) return;
    const arr = patchCurrent({
      customText: text,
      selected: multi ? cur.selected : [],
      skipped: false,
      touched: true,
    });
    setAnswers(arr);
    if (!multi) goNextOrSubmit(arr);
  }, [multi, cur.selected, patchCurrent, goNextOrSubmit]);

  const closeAll = useCallback(() => onSubmit?.(buildPayload(answers)), [onSubmit, buildPayload, answers]);

  const onCardKeyDown = useCallback(
    (e) => {
      if (customOpen) return; // the custom <input/> owns its keys while open
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setFocus((f) => Math.min(f + 1, somethingElseIdx));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setFocus((f) => Math.max(f - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (focus === somethingElseIdx) {
          setCustomOpen(true);
          requestAnimationFrame(() => customRef.current?.focus());
        } else if (opts[focus]) {
          chooseOption(opts[focus].label);
        }
      }
    },
    [customOpen, focus, somethingElseIdx, opts, chooseOption],
  );

  const footerHint = useMemo(
    () =>
      multi
        ? "↑↓ to navigate · Enter to toggle · pick any that fit, then Continue"
        : "↑↓ to navigate · Enter to select",
    [multi],
  );

  if (!total) return null;

  return (
    <div className="px-6 pb-2 flex-shrink-0">
      <div className="max-w-[720px] mx-auto">
        <div
          ref={cardRef}
          tabIndex={0}
          onKeyDown={onCardKeyDown}
          className={`rounded-2xl border border-[#E5E5E5] bg-white shadow-lg outline-none
                      transition-all duration-200 ease-out
                      ${mounted ? "opacity-100 translate-y-0" : "opacity-0 translate-y-2"}`}
        >
          {/* Header — question + pagination + close */}
          <div className="flex items-start gap-3 px-4 pt-3.5 pb-2.5">
            <div className="flex-1 min-w-0">
              {q.header && (
                <span className="inline-block mb-1 px-1.5 py-0.5 rounded
                                 bg-[#F5E3D7] text-[10.5px] font-semibold uppercase tracking-wide
                                 text-[#9A5638]">
                  {q.header}
                </span>
              )}
              <p className="text-[15px] font-medium text-[#1A1A1A] leading-snug">
                {q.question}
              </p>
            </div>
            <div className="flex items-center gap-1 flex-shrink-0 pt-0.5">
              <button
                onClick={() => setCurrent((c) => Math.max(c - 1, 0))}
                disabled={current === 0}
                className="w-6 h-6 flex items-center justify-center rounded-md text-[#9A9A9A]
                           hover:text-[#1A1A1A] hover:bg-[#EFEFEF] disabled:opacity-30
                           disabled:hover:bg-transparent transition-colors"
                aria-label="Previous question"
              >
                <ChevronLeft size={15} />
              </button>
              <span className="text-[11.5px] text-[#8A8A8A] tabular-nums select-none">
                {current + 1} of {total}
              </span>
              <button
                onClick={() => setCurrent((c) => Math.min(c + 1, total - 1))}
                disabled={isLast}
                className="w-6 h-6 flex items-center justify-center rounded-md text-[#9A9A9A]
                           hover:text-[#1A1A1A] hover:bg-[#EFEFEF] disabled:opacity-30
                           disabled:hover:bg-transparent transition-colors"
                aria-label="Next question"
              >
                <ChevronRight size={15} />
              </button>
              <button
                onClick={closeAll}
                className="w-6 h-6 ml-0.5 flex items-center justify-center rounded-md text-[#9A9A9A]
                           hover:text-[#1A1A1A] hover:bg-[#EFEFEF] transition-colors"
                aria-label="Skip all and continue"
              >
                <X size={15} />
              </button>
            </div>
          </div>

          {/* Options */}
          <div className="max-h-[46vh] overflow-y-auto">
            {opts.map((opt, i) => {
              const selected = cur.selected.includes(opt.label);
              const focused = focus === i;
              return (
                <button
                  key={i}
                  type="button"
                  onMouseEnter={() => setFocus(i)}
                  onClick={() => chooseOption(opt.label)}
                  className={`w-full flex items-center gap-3 px-4 py-2.5 text-left
                              border-t border-[#F1F1F1] transition-colors
                              ${focused ? "bg-[#F6F5F3]" : "hover:bg-[#FAFAFA]"}`}
                >
                  <span
                    className={`w-6 h-6 flex-shrink-0 flex items-center justify-center rounded-md text-[11.5px] font-semibold
                                ${selected
                                  ? "bg-[#B86F50] text-white"
                                  : "bg-[#F0F0F0] text-[#6B6B6B]"}`}
                  >
                    {selected ? <Check size={13} /> : i + 1}
                  </span>
                  <span className="flex-1 min-w-0">
                    <span className="block text-[13.5px] text-[#1A1A1A] leading-tight">
                      {opt.label}
                    </span>
                    {opt.description && (
                      <span className="block text-[11.5px] text-[#9A9A9A] leading-snug mt-0.5">
                        {opt.description}
                      </span>
                    )}
                  </span>
                  {focused && !multi && (
                    <ArrowRight size={14} className="flex-shrink-0 text-[#B86F50]" />
                  )}
                </button>
              );
            })}

            {/* Something else (free text) */}
            <div
              className={`flex items-center gap-3 px-4 py-2.5 border-t border-[#F1F1F1]
                          ${focus === somethingElseIdx && !customOpen ? "bg-[#F6F5F3]" : ""}`}
              onMouseEnter={() => setFocus(somethingElseIdx)}
            >
              <span className="w-6 h-6 flex-shrink-0 flex items-center justify-center rounded-md
                               bg-[#F0F0F0] text-[#6B6B6B]">
                <Pencil size={12} />
              </span>
              {customOpen ? (
                <div className="flex-1 flex items-center gap-2">
                  <input
                    ref={customRef}
                    defaultValue={cur.customText}
                    placeholder="Type your own answer…"
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        submitCustom();
                      } else if (e.key === "Escape") {
                        setCustomOpen(false);
                        cardRef.current?.focus();
                      }
                    }}
                    className="flex-1 bg-transparent text-[13.5px] text-[#1A1A1A]
                               placeholder:text-[#B0B0B0] focus:outline-none"
                  />
                  <button
                    onClick={submitCustom}
                    className="flex items-center gap-1 px-2 py-1 rounded-md text-[11.5px] font-medium
                               text-[#B86F50] hover:bg-[#F5E3D7] transition-colors"
                  >
                    <CornerDownLeft size={12} /> {multi ? "Add" : "Use"}
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    setCustomOpen(true);
                    requestAnimationFrame(() => customRef.current?.focus());
                  }}
                  className="flex-1 text-left text-[13.5px] text-[#6B6B6B] hover:text-[#1A1A1A] transition-colors"
                >
                  Something else…
                </button>
              )}
              <button
                onClick={skipCurrent}
                className="flex-shrink-0 px-2.5 py-1 rounded-md text-[12px] font-medium
                           text-[#8A8A8A] hover:text-[#1A1A1A] hover:bg-[#EFEFEF] transition-colors"
              >
                Skip
              </button>
            </div>
          </div>

          {/* Footer — hint + (multi) Continue */}
          <div className="flex items-center justify-between gap-3 px-4 py-2.5 border-t border-[#EDEDED] bg-[#FAFAFA]">
            <span className="text-[11px] text-[#A8A8A8] truncate">{footerHint}</span>
            {multi && (
              <button
                onClick={continueMulti}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium
                           bg-[#B86F50] hover:bg-[#A76145] text-white transition-colors flex-shrink-0"
              >
                {isLast ? "Submit" : "Continue"} <ArrowRight size={13} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default IntakeQuestions;
