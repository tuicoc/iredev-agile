// src/components/chat/FormattedText.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Converts a plain string with basic markdown-like syntax into styled JSX.
// Handles: # headings, ## headings, - bullets, 1. numbered lists,
//          --- horizontal rules, **bold**, and `inline code`.
//
// Note: This is intentionally lightweight. For a production app you'd use
//       a library like 'react-markdown' instead.
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Parse **bold** and `inline code` within a single line of text.
 * Returns an array of plain strings and React <strong>/<code> elements.
 */
function renderInline(text) {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**'))
      return <strong key={i} className="font-semibold text-[#1A1A1A]">{part.slice(2,-2)}</strong>
    if (part.startsWith('`') && part.endsWith('`'))
      return <code key={i} className="inline-code">{part.slice(1,-1)}</code>
    return part
  })
}

export function FormattedText({ text }) {
  if (!text.trim()) return null

  return (
    <div className="space-y-[7px]">
      {text.split('\n').map((line, i) => {

        if (line.startsWith('## '))
          return <h3 key={i} className="font-semibold text-[15px] text-[#1A1A1A] mt-3 mb-1">
            {renderInline(line.slice(3))}
          </h3>

        if (line.startsWith('# '))
          return <h2 key={i} className="font-bold text-[17px] text-[#1A1A1A] mt-3 mb-1">
            {renderInline(line.slice(2))}
          </h2>

        if (line.startsWith('- ') || line.startsWith('• '))
          return (
            <div key={i} className="flex gap-2.5 ml-1">
              <span className="text-[#6B6B6B] mt-[3px] flex-shrink-0 text-[10px]">●</span>
              <span className="text-[14px] leading-relaxed">{renderInline(line.slice(2))}</span>
            </div>
          )

        const numMatch = line.match(/^(\d+)\.\s(.+)/)
        if (numMatch)
          return (
            <div key={i} className="flex gap-2.5 ml-1">
              <span className="text-[#6B6B6B] font-medium text-[13px] min-w-[1.1rem] flex-shrink-0">
                {numMatch[1]}.
              </span>
              <span className="text-[14px] leading-relaxed">{renderInline(numMatch[2])}</span>
            </div>
          )

        if (line.trim() === '---')
          return <hr key={i} className="border-[#E5E5E5] my-3" />

        if (!line.trim())
          return <div key={i} className="h-2" />

        return (
          <p key={i} className="text-[14px] leading-[1.7] text-[#1A1A1A]">
            {renderInline(line)}
          </p>
        )
      })}
    </div>
  )
}