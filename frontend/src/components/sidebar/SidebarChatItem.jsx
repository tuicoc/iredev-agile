// src/components/sidebar/SidebarChatItem.jsx
// ─────────────────────────────────────────────────────────────────────────────
// A single row in the sidebar chat list.
// Shows the chat title, and reveals a delete button on hover.
// ─────────────────────────────────────────────────────────────────────────────
import { useState } from 'react'
import { Trash2 } from 'lucide-react'

export function SidebarChatItem({ chat, isActive, onSelect, onDelete }) {
  const [hovered, setHovered] = useState(false)

  return (
    <div
      onClick={onSelect}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={`
        group flex items-center gap-2 px-2.5 py-[7px] rounded-lg
        cursor-pointer text-[13px] transition-colors duration-100
        ${isActive
          ? 'bg-[#E5D9C9] text-[#211914]'
          : 'text-[#4A4038] hover:bg-[#E7DDCF]'}
      `}
    >
      <span className="flex-1 truncate leading-snug">{chat.title}</span>

      {/* Delete — only on hover */}
      {hovered && (
        <button
          onClick={e => { e.stopPropagation(); onDelete() }}
          className="p-0.5 rounded text-[#A89C91] hover:text-[#B86F50] transition-colors flex-shrink-0"
        >
          <Trash2 size={12} />
        </button>
      )}
    </div>
  )
}