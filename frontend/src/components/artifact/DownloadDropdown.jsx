// src/components/artifact/DownloadDropdown.jsx
// =============================================================================
// Dropdown menu for downloading artifacts in JSON, Markdown, or PDF format.
// =============================================================================
import { useState, useRef, useEffect } from "react";
import { Download, FileJson, FileText, FileDown } from "lucide-react";
import { Tooltip } from "../ui";
import {
  downloadAsJson,
  downloadAsMarkdown,
  downloadAsPdf,
} from "./utils/artifactDownload";

const OPTIONS = [
  { id: "json", label: "Download as JSON", icon: FileJson },
  { id: "markdown", label: "Download as Markdown", icon: FileText },
  { id: "pdf", label: "Download as PDF", icon: FileDown },
];

export function DownloadDropdown({ data, rawContent, artifactType, title, iconBtnClass }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function onClickOutside(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    function onKey(e) { if (e.key === "Escape") setOpen(false); }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  function handleSelect(optionId) {
    setOpen(false);
    const content = rawContent ?? data;
    switch (optionId) {
      case "json":
        downloadAsJson(content, title);
        break;
      case "markdown":
        downloadAsMarkdown(content, artifactType, title);
        break;
      case "pdf":
        downloadAsPdf(content, artifactType, title);
        break;
    }
  }

  return (
    <div ref={ref} className="relative">
      <Tooltip text="Download">
        <button
          onClick={() => setOpen((v) => !v)}
          className={iconBtnClass}
          aria-haspopup="listbox"
          aria-expanded={open}
        >
          <Download size={14} />
        </button>
      </Tooltip>

      {open && (
        <div
          className="absolute right-0 top-full mt-1 z-50 min-w-[200px]
                     rounded-lg border border-[#E2D6C5] bg-[#FFFDF8]
                     shadow-lg shadow-black/8 overflow-hidden
                     animate-in fade-in slide-in-from-top-1"
          role="listbox"
        >
          {OPTIONS.map((opt) => {
            const Icon = opt.icon;
            return (
              <button
                key={opt.id}
                role="option"
                onClick={() => handleSelect(opt.id)}
                className="flex w-full items-center gap-2.5 px-3 py-2.5
                           text-[12px] font-medium text-[#4A4038]
                           hover:bg-[#F6F1E8] transition-colors
                           first:rounded-t-lg last:rounded-b-lg"
              >
                <Icon size={14} className="text-[#B86F50] flex-shrink-0" />
                {opt.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
