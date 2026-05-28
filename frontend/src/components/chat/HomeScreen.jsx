// src/components/chat/HomeScreen.jsx
const GUIDE_LINES = [
  "What is happening today — the friction, confusion, workaround, or risk before the product exists",
  "Who is affected — runtime roles and any subgroups whose needs should not be flattened",
  "What kind of product might help, even if the exact shape is still open",
  "What the product should sit beside, not replace, or not decide",
  "What outcome should improve for users, staff, customers, or other affected roles",
];

export function HomeScreen() {
  return (
    <div className="flex flex-col items-center w-full max-w-[680px] mx-auto px-6 pb-6">
      <h1 className="text-[2rem] font-semibold text-[#1A1A1A] leading-tight text-center">
        How can CARA help you?
      </h1>

      {/* Subtitle + ? hint */}
      <p className="mt-2 text-[14px] text-[#7A7A7A] text-center leading-relaxed">
        Start a new requirements engineering process or open an existing project.{" "}
        <span className="group relative inline-block align-middle">
          {/* ? button */}
          <button
            className="inline-flex items-center justify-center w-[18px] h-[18px]
                       rounded-full border border-[#D4D4D4] text-[#A0A0A0]
                       text-[10px] font-semibold leading-none
                       hover:border-[#B86F50] hover:text-[#B86F50]
                       transition-colors duration-150 cursor-default select-none"
            tabIndex={-1}
          >
            ?
          </button>

          {/* Tooltip — shown on hover */}
          <div
            className="pointer-events-none absolute left-1/2 -translate-x-1/2 top-full mt-3
                       w-[340px] rounded-xl bg-white border border-[#E5E5E5]
                       shadow-[0_8px_24px_rgba(0,0,0,0.09)]
                       opacity-0 group-hover:opacity-100 scale-95 group-hover:scale-100
                       transition-all duration-150 origin-top z-30 text-left"
          >
            {/* Arrow */}
            <div className="absolute -top-[5px] left-1/2 -translate-x-1/2
                            w-2.5 h-2.5 bg-white border-l border-t border-[#E5E5E5]
                            rotate-45" />

            <div className="px-4 pt-4 pb-3.5">
              <p className="text-[11px] font-semibold text-[#6B6B6B] uppercase tracking-wide mb-3">
                Start with product intent
              </p>
              <div className="space-y-2.5">
                {GUIDE_LINES.map((line, i) => (
                  <p key={i} className="text-[12.5px] text-[#3A3A3A] leading-snug">
                    {line}
                  </p>
                ))}
              </div>
              <p className="mt-3 pt-3 border-t border-[#F0F0F0] text-[11.5px] text-[#A0A0A0] leading-snug">
                You can be uncertain. Competing ideas and unresolved boundaries are useful
                input — Visionary will turn them into reviewable forks.
              </p>
            </div>
          </div>
        </span>
      </p>
    </div>
  );
}
