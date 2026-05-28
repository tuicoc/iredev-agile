export function asArray(value) {
  return Array.isArray(value) ? value : [];
}

export function text(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (Array.isArray(value)) return value.map(text).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function formatDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return text(value);
  return date.toLocaleString();
}

export function Section({ title, icon: Icon, children }) {
  return (
    <section className="border-t border-[#E5E5E5]">
      <div
        className="sticky top-0 z-10 bg-[#F8F8F8]/95 backdrop-blur px-4 py-2.5
                   border-b border-[#E5E5E5] flex items-center gap-2"
      >
        {Icon && <Icon size={14} className="text-[#B86F50]" />}
        <h3 className="text-[12px] font-semibold text-[#1A1A1A]">{title}</h3>
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

// Unified warm-palette semantic tones — all derived from the same warm base
// so every artifact view speaks the same visual language.
const TONES = {
  default: "border-[#DEDEDE] bg-[#F7F7F7] text-[#6B6B6B]",
  warm:    "border-[#FFD0B0] bg-[#FEF0E8] text-[#B86F50]",
  green:   "border-[#B8D4BB] bg-[#EEF5EF] text-[#3A6642]",
  amber:   "border-[#D4C09E] bg-[#F5EDD6] text-[#7A5422]",
  red:     "border-[#D4AAAA] bg-[#F5EAEA] text-[#7A3333]",
  blue:    "border-[#B0BED4] bg-[#EEF1F8] text-[#364F78]",
  purple:  "border-[#C4B0D4] bg-[#F0EEF5] text-[#5B4278]",
};

export function MetaPill({ label, value, tone = "default" }) {
  if (value === null || value === undefined || value === "") return null;

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1
                  text-[10.5px] ${TONES[tone] || TONES.default}`}
    >
      <span className="font-semibold text-[#3A3A3A]">{label}</span>
      {text(value)}
    </span>
  );
}

export function Tag({ children, tone = "default", title }) {
  if (children === null || children === undefined || children === "") return null;

  const tones = TONES;

  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[9.5px]
                  font-medium ${tones[tone] || tones.default}`}
      title={title}
    >
      {text(children)}
    </span>
  );
}

export function EmptyState({ label }) {
  return (
    <div
      className="rounded-lg border border-dashed border-[#DEDEDE] bg-[#F8F8F8]
                 px-3 py-6 text-center text-[12px] text-[#A0A0A0]"
    >
      {label}
    </div>
  );
}

export function FieldGrid({ children }) {
  return <div className="grid gap-2 sm:grid-cols-2">{children}</div>;
}

export function Field({ label, value }) {
  if (value === null || value === undefined || value === "") return null;

  return (
    <div className="rounded-lg border border-[#E8E8E8] bg-[#F8F8F8] px-3 py-2">
      <div className="text-[9.5px] font-semibold uppercase text-[#A0A0A0]">
        {label}
      </div>
      <div className="mt-0.5 text-[10.5px] leading-relaxed text-[#3A3A3A]">
        {text(value)}
      </div>
    </div>
  );
}
