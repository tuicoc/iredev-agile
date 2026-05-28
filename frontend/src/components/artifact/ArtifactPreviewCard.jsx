// src/components/artifact/ArtifactPreviewCard.jsx
// Clickable card shown below an assistant message.
// Shows an "awaiting feedback" indicator when relevant.
import {
  Code2,
  Globe,
  FileText,
  ImageIcon,
  BookOpen,
  Lightbulb,
  List,
  ClipboardList,
  ListChecks,
  LayoutList,
  CheckSquare,
  Sparkles,
  ChevronRight,
  Check,
} from "lucide-react";
import { getArtifactDisplayName } from "./ArtifactPanel";

const TYPE_ICONS = {
  // Code/web artifact types
  react: Code2,
  html: Globe,
  code: Code2,
  markdown: FileText,
  svg: ImageIcon,
  // CARA artifact types
  interview_record: BookOpen,
  product_vision: Lightbulb,
  elicitation_agenda: List,
  requirement_list: ClipboardList,
  user_story_draft: ListChecks,
  product_backlog: LayoutList,
  validated_product_backlog: CheckSquare,
  analyst_estimation: Sparkles,
};

export function ArtifactPreviewCard({ artifact, onOpen }) {
  const Icon = TYPE_ICONS[artifact.type] ?? FileText;

  return (
    <button
      onClick={onOpen}
      className="flex items-center gap-3 pl-3 pr-2.5 py-2.5
                 bg-[#FFFFFF] border border-[#E5E5E5] rounded-xl
                 hover:border-[#C5C5C5] hover:bg-[#F8F8F8]
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
                           : "bg-[#FEF0E8] border-[#FFD0B0]"
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
          <span className="text-[13px] font-semibold text-[#1A1A1A] truncate leading-snug">
            {getArtifactDisplayName(artifact.type)}
          </span>
          {artifact.iteration && (
            <span className="text-[10px] text-[#A0A0A0] flex-shrink-0">
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
            <span className="text-[#6B6B6B] capitalize">
              {artifact.type} · Click to open
            </span>
          )}
        </div>
      </div>

      <ChevronRight
        size={14}
        className="text-[#A8A8A8] group-hover:text-[#6B6B6B]
                                          group-hover:translate-x-0.5 transition-all flex-shrink-0"
      />
    </button>
  );
}
