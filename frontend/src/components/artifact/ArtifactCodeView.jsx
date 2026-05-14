// src/components/artifact/ArtifactCodeView.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Shows the raw source code of an artifact with line numbers.
// Rendered inside the "Code" tab of ArtifactPanel.
// ─────────────────────────────────────────────────────────────────────────────

export function ArtifactCodeView({ content, language }) {
  const lines = content.split("\n");

  return (
    <div className="h-full bg-[#F6F1E8] p-4 overflow-auto">
      <div className="mb-3">
        <span
          className="px-2 py-0.5 bg-[#ECE3D6] border border-[#D8CBBB]
                         rounded text-[10.5px] font-mono text-[#776B60]"
        >
          {language || "text"}
        </span>
      </div>
      <pre className="text-[12px] font-mono text-[#302822] leading-relaxed">
        {lines.map((line, i) => (
          <div
            key={i}
            className="flex gap-4 hover:bg-black/[0.025] px-1 rounded"
          >
            <span className="select-none text-[#B0A49A] text-right w-6 flex-shrink-0">
              {i + 1}
            </span>
            <span>{line || " "}</span>
          </div>
        ))}
      </pre>
    </div>
  );
}
