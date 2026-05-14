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
    <section className="border-t border-[#E2D6C5]">
      <div
        className="sticky top-0 z-10 bg-[#FBF7F0]/95 backdrop-blur px-4 py-2.5
                   border-b border-[#E2D6C5] flex items-center gap-2"
      >
        {Icon && <Icon size={14} className="text-[#B86F50]" />}
        <h3 className="text-[12px] font-semibold text-[#211914]">{title}</h3>
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

export function MetaPill({ label, value, tone = "default" }) {
  if (value === null || value === undefined || value === "") return null;

  const tones = {
    default: "border-[#D8CBBB] bg-[#F6F1E8] text-[#776B60]",
    warm: "border-[#E6CABB] bg-[#F4E4D9] text-[#B86F50]",
    green: "border-green-200 bg-green-50 text-green-700",
    amber: "border-amber-200 bg-amber-50 text-amber-700",
    red: "border-red-200 bg-red-50 text-red-600",
    blue: "border-blue-200 bg-blue-50 text-blue-700",
  };

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1
                  text-[10.5px] ${tones[tone] || tones.default}`}
    >
      <span className="font-semibold text-[#4A4038]">{label}</span>
      {text(value)}
    </span>
  );
}

export function Tag({ children, tone = "default", title }) {
  if (children === null || children === undefined || children === "") return null;

  const tones = {
    default: "border-[#D8CBBB] bg-[#F6F1E8] text-[#776B60]",
    warm: "border-[#E6CABB] bg-[#F4E4D9] text-[#B86F50]",
    green: "border-green-200 bg-green-50 text-green-700",
    amber: "border-amber-200 bg-amber-50 text-amber-700",
    red: "border-red-200 bg-red-50 text-red-600",
    blue: "border-blue-200 bg-blue-50 text-blue-700",
    purple: "border-purple-200 bg-purple-50 text-purple-700",
  };

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
      className="rounded-lg border border-dashed border-[#D8CBBB] bg-[#FBF7F0]
                 px-3 py-6 text-center text-[12px] text-[#A89C91]"
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
    <div className="rounded-lg border border-[#E9DFD1] bg-[#FBF7F0] px-3 py-2">
      <div className="text-[9.5px] font-semibold uppercase text-[#A89C91]">
        {label}
      </div>
      <div className="mt-0.5 text-[10.5px] leading-relaxed text-[#4A4038]">
        {text(value)}
      </div>
    </div>
  );
}
