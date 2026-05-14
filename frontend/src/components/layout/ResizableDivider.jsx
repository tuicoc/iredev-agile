// src/components/layout/ResizableDivider.jsx
// Thanh kéo giữa chat panel và artifact panel
import { GripVertical } from 'lucide-react'

export function ResizableDivider({ onMouseDown }) {
  return (
    <div
      onMouseDown={onMouseDown}
      className="relative flex-shrink-0 w-[5px] h-full
                 cursor-col-resize group z-10
                 flex items-center justify-center"
      style={{ background: 'transparent' }}
    >
      {/* Line track */}
      <div
        className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-px
                   bg-[#D8CBBB] group-hover:bg-[#B86F50]
                   group-active:bg-[#A76145]
                   transition-colors duration-150"
      />

      {/* Grip handle in the middle */}
      <div
        className="relative z-10 flex items-center justify-center
                   w-5 h-10 rounded-full
                   bg-[#EFE8DC] border border-[#D8CBBB]
                   group-hover:bg-[#F5E3D7] group-hover:border-[#B86F50]
                   group-active:bg-[#F5E6DC] group-active:border-[#A76145]
                   shadow-sm transition-all duration-150
                   opacity-0 group-hover:opacity-100"
      >
        <GripVertical size={12} className="text-[#A89C91] group-hover:text-[#B86F50]" />
      </div>
    </div>
  )
}