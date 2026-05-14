// src/components/chat/CodeBlock.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Renders a fenced code block (``` ... ```) with:
//   - A header bar showing the language name and a Copy button
//   - The raw code in a monospace pre element
// ─────────────────────────────────────────────────────────────────────────────
import { useState } from 'react'
import { Copy, Check } from 'lucide-react'

export function CodeBlock({ language, code }) {
  const [copied, setCopied] = useState(false)

  function handleCopy() {
    navigator.clipboard?.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="rounded-xl overflow-hidden border border-[#D8CBBB] my-1">
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-2
                      bg-[#ECE3D6] border-b border-[#D8CBBB]">
        <span className="text-[11px] font-mono text-[#776B60] font-medium">
          {language || 'code'}
        </span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 text-[11px] text-[#776B60]
                     hover:text-[#211914] transition-colors"
        >
          {copied ? <><Check size={11}/> Copied</> : <><Copy size={11}/> Copy</>}
        </button>
      </div>

      {/* Code */}
      <pre className="px-4 py-3.5 bg-[#F6F1E8] text-[12.5px] font-mono
                      text-[#302822] leading-relaxed overflow-x-auto">
        {code}
      </pre>
    </div>
  )
}