// src/components/artifact/ArtifactCodeView.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Shows the raw source code of an artifact with line numbers.
// Rendered inside the "Code" tab of ArtifactPanel.
// ─────────────────────────────────────────────────────────────────────────────

export function ArtifactCodeView({ content, language }) {
  const lines = content.split("\n");

  return (
    <div className="h-full bg-[#F7F7F7] p-4 overflow-auto">
      <div className="mb-3">
        <span
          className="px-2 py-0.5 bg-[#EFEFEF] border border-[#DEDEDE]
                         rounded text-[10.5px] font-mono text-[#6B6B6B]"
        >
          {language || "text"}
        </span>
      </div>
      <pre className="text-[12px] font-mono text-[#1A1A1A] leading-relaxed">
        {lines.map((line, i) => (
          <div
            key={i}
            className="flex gap-4 hover:bg-black/[0.025] px-1 rounded"
          >
            <span className="select-none text-[#A8A8A8] text-right w-6 flex-shrink-0">
              {i + 1}
            </span>
            <span>{line || " "}</span>
          </div>
        ))}
      </pre>
    </div>
  );
}
