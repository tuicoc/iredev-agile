// src/components/artifact/ArtifactPreviewCard.jsx
// Clickable card shown below an assistant message.
// Shows an "awaiting feedback" indicator when relevant.
import {
  Code2,
  Globe,
  FileText,
  ImageIcon,
  File,
  ChevronRight,
  Check,
} from "lucide-react";
import { getArtifactDisplayName } from "./ArtifactPanel";

const TYPE_ICONS = {
  react: Code2,
  html: Globe,
  code: Code2,
  markdown: FileText,
  svg: ImageIcon,
};

export function ArtifactPreviewCard({ artifact, onOpen }) {
  const Icon = TYPE_ICONS[artifact.type] ?? File;

  return (
    <button
      onClick={onOpen}
      className="flex items-center gap-3 pl-3 pr-2.5 py-2.5
                 bg-[#FFFDF8] border border-[#E2D6C5] rounded-xl
                 hover:border-[#CEC0AE] hover:bg-[#FCF8F1]
                 shadow-[0_1px_3px_rgba(0,0,0,0.05)]
                 hover:shadow-[0_2px_6px_rgba(0,0,0,0.07)]
                 transition-all duration-150 text-left w-full max-w-[320px] group"
    >
      {/* Icon tile — orange while awaiting, green when accepted */}
      <div
        className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0
                       border ${
                         artifact.accepted
                           ? "bg-green-50 border-green-200"
                           : "bg-[#F4E4D9] border-[#E6CABB]"
                       }`}
      >
        {artifact.accepted ? (
          <Check size={16} className="text-green-600" />
        ) : (
          <Icon size={16} className="text-[#B86F50]" />
        )}
      </div>

      {/* Text */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="text-[13px] font-semibold text-[#211914] truncate leading-snug">
            {getArtifactDisplayName(artifact.type)}
          </span>
          {artifact.iteration && (
            <span className="text-[10px] text-[#A89C91] flex-shrink-0">
              v{artifact.iteration}
            </span>
          )}
        </div>
        <div className="text-[11px] mt-0.5">
          {artifact.accepted ? (
            <span className="text-green-600 font-medium">Accepted</span>
          ) : artifact.awaitingFeedback ? (
            <span className="text-[#B86F50] font-medium">
              Awaiting your review
            </span>
          ) : (
            <span className="text-[#776B60] capitalize">
              {artifact.type} · Click to open
            </span>
          )}
        </div>
      </div>

      <ChevronRight
        size={14}
        className="text-[#B0A49A] group-hover:text-[#776B60]
                                          group-hover:translate-x-0.5 transition-all flex-shrink-0"
      />
    </button>
  );
}
