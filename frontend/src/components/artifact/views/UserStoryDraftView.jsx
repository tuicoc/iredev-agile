import {
  ClipboardList,
  FileText,
  GitBranch,
  ListChecks,
  Trash2,
} from "lucide-react";
import {
  asArray,
  EmptyState,
  MetaPill,
  Section,
  Tag,
  text,
} from "./viewUtils";

const RESHAPE_TONES = {
  carry: "green",
  merge: "blue",
  split: "purple",
  rewrite: "amber",
  add: "warm",
};

function getStories(data) {
  if (Array.isArray(data?.stories)) return data.stories;
  if (Array.isArray(data?.items)) return data.items;
  return [];
}

function sourceIds(story) {
  const ids = asArray(story.source_requirement_ids);
  if (ids.length) return ids;
  return story.source_requirement_id ? [story.source_requirement_id] : [];
}

function storyId(story, index) {
  return story.source_story_id || story.id || `ST-${String(index + 1).padStart(3, "0")}`;
}

function typeTone(type) {
  if (type === "functional") return "warm";
  if (type === "non_functional") return "blue";
  if (type === "constraint" || type === "system") return "purple";
  return "default";
}

function reshapeLabel(value) {
  return String(value || "carry").replace(/_/g, " ");
}

function TraceDetails({ trace }) {
  if (!trace || !Object.keys(trace).length) return null;

  const traceRefs = asArray(trace.trace_refs);
  const mergedIds = asArray(trace.merged_requirement_ids);
  const acceptanceCriteria = asArray(trace.acceptance_criteria);

  return (
    <details className="text-[10.5px] leading-relaxed text-[#6B6B6B]">
      <summary className="cursor-pointer font-semibold text-[#3A3A3A]">
        Requirement trace
      </summary>
      <div className="mt-2 space-y-1.5">
        {trace.requirement_id && (
          <p>
            <span className="font-semibold text-[#3A3A3A]">Requirement:</span>{" "}
            {trace.requirement_id}
          </p>
        )}
        {trace.stakeholder && (
          <p>
            <span className="font-semibold text-[#3A3A3A]">Stakeholder:</span>{" "}
            {trace.stakeholder}
          </p>
        )}
        {trace.statement && (
          <p>
            <span className="font-semibold text-[#3A3A3A]">Statement:</span>{" "}
            {trace.statement}
          </p>
        )}
        {trace.rationale && (
          <p>
            <span className="font-semibold text-[#3A3A3A]">Rationale:</span>{" "}
            {trace.rationale}
          </p>
        )}
        {traceRefs.length > 0 && (
          <p>
            <span className="font-semibold text-[#3A3A3A]">Trace refs:</span>{" "}
            {traceRefs.map(text).join(", ")}
          </p>
        )}
        {mergedIds.length > 0 && (
          <p>
            <span className="font-semibold text-[#3A3A3A]">Merged ids:</span>{" "}
            {mergedIds.map(text).join(", ")}
          </p>
        )}
        {acceptanceCriteria.length > 0 && (
          <p>
            <span className="font-semibold text-[#3A3A3A]">Source AC:</span>{" "}
            {acceptanceCriteria.map(text).join("; ")}
          </p>
        )}
      </div>
    </details>
  );
}

function StoryCard({ story, index }) {
  const id = storyId(story, index);
  const sources = sourceIds(story);
  const reshape = story.reshape_op || "carry";

  return (
    <article className="rounded-lg border border-[#E5E5E5] bg-[#FFFFFF]">
      <div className="border-b border-[#E8E8E8] bg-[#F8F8F8] px-3 py-2.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-mono text-[10px] text-[#B86F50]">{id}</span>
          <Tag tone={typeTone(story.type)}>{String(story.type || "").replace(/_/g, " ")}</Tag>
          {story.domain && <Tag>{story.domain}</Tag>}
          <Tag tone={RESHAPE_TONES[reshape] || "default"}>{reshapeLabel(reshape)}</Tag>
        </div>

        <h4 className="mt-2 break-words text-[12.5px] font-semibold leading-snug text-[#1A1A1A]">
          {story.title || story.description || id}
        </h4>
        {story.description && (
          <p className="mt-1 break-words text-[10.5px] leading-relaxed text-[#6B6B6B]">
            {story.description}
          </p>
        )}
      </div>

      <div className="space-y-2 px-3 py-2.5">
        {sources.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[9.5px] font-semibold uppercase text-[#A0A0A0]">
              Sources
            </span>
            {sources.map((source) => (
              <Tag key={source}>{source}</Tag>
            ))}
          </div>
        )}

        {story.thought && (
          <p className="break-words text-[10.5px] leading-relaxed text-[#6B6B6B]">
            <span className="font-semibold text-[#3A3A3A]">Shaping rationale:</span>{" "}
            {story.thought}
          </p>
        )}

        <TraceDetails trace={story.requirement_trace || {}} />
      </div>
    </article>
  );
}

function DroppedRequirements({ dropped }) {
  const items = asArray(dropped);
  if (!items.length) return null;

  return (
    <Section title="Dropped Requirements" icon={Trash2}>
      <div className="grid gap-2">
        {items.map((item, index) => (
          <div
            key={`${asArray(item.requirement_ids).join("-") || index}`}
            className="rounded-lg border border-amber-200 bg-amber-50 p-3"
          >
            <div className="flex flex-wrap items-center gap-1.5">
              {asArray(item.requirement_ids).map((id) => (
                <Tag key={id} tone="amber">{id}</Tag>
              ))}
            </div>
            <p className="mt-1.5 break-words text-[10.5px] leading-relaxed text-amber-900">
              {text(item.reason)}
            </p>
          </div>
        ))}
      </div>
    </Section>
  );
}

function NotesSection({ notes }) {
  if (!notes) return null;

  return (
    <Section title="Shaping Notes" icon={FileText}>
      <div className="rounded-lg border border-[#E5E5E5] bg-[#F8F8F8] p-3">
        <p className="whitespace-pre-wrap break-words text-[10.5px] leading-relaxed text-[#3A3A3A]">
          {notes}
        </p>
      </div>
    </Section>
  );
}

export function UserStoryDraftView({ data }) {
  const stories = getStories(data);
  const dropped = asArray(data?.dropped);
  const sourceCount = new Set(stories.flatMap(sourceIds)).size;
  const reshapedCount = stories.filter((story) => {
    const op = story.reshape_op || "carry";
    return op !== "carry" && op !== "none";
  }).length;
  const notes = data?.notes || data?.pass_notes || "";

  return (
    <div className="h-full overflow-auto bg-[#FFFFFF]">
      <div className="space-y-3 p-4">
        <div className="rounded-lg border border-[#E5E5E5] bg-[#F8F8F8] p-3">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-[#1A1A1A]">
            <ClipboardList size={14} className="text-[#B86F50]" />
            User Story Draft
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <MetaPill label="Stories" value={data?.total_stories ?? stories.length} />
            <MetaPill label="Sources" value={sourceCount} />
            <MetaPill label="Reshaped" value={reshapedCount} tone={reshapedCount ? "amber" : "default"} />
            <MetaPill label="Dropped" value={dropped.length} tone={dropped.length ? "amber" : "default"} />
          </div>
        </div>
      </div>

      <Section title="Draft Stories" icon={ListChecks}>
        {stories.length ? (
          <div className="grid gap-3">
            {stories.map((story, index) => (
              <StoryCard key={storyId(story, index)} story={story} index={index} />
            ))}
          </div>
        ) : (
          <EmptyState label="No draft stories found." />
        )}
      </Section>

      <DroppedRequirements dropped={dropped} />
      <NotesSection notes={notes} />

      {data?.rebuild_feedback && (
        <Section title="Reviewer Feedback Applied" icon={GitBranch}>
          <div className="rounded-lg border border-[#E5E5E5] bg-[#F8F8F8] p-3">
            <p className="whitespace-pre-wrap break-words text-[10.5px] leading-relaxed text-[#3A3A3A]">
              {data.rebuild_feedback}
            </p>
          </div>
        </Section>
      )}
    </div>
  );
}
