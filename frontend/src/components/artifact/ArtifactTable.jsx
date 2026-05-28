export function ArtifactTable({ data, column, tableTitle }) {
  const rows = Array.isArray(data) ? data : [];
  const columns = Array.isArray(column) ? column : [];
  const renderCell = (col, item) => {
    let value;
    try {
      value = col.displayValue?.(item);
    } catch {
      value = null;
    }

    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "object" && !Array.isArray(value)) {
      if (value.$$typeof) return value;
      return JSON.stringify(value);
    }
    if (Array.isArray(value)) return value.join(", ");
    return value;
  };

  return (
    <>
      {tableTitle && (
        <div className="font-bold mt-1.5 ml-3.5">{tableTitle}</div>
      )}
      <div className="px-4 py-3 overflow-x-auto">
        <table className="w-full text-[12px] border-collapse min-w-[700px]">
          <thead>
            <tr className="text-left border-b border-[#E5E5E5]">
              {columns.map((val, idx) => (
                <th
                  key={idx}
                  className={
                    val.titleStyle ?? `py-2 pr-3 font-semibold text-[#6B6B6B]`
                  }
                >
                  {val.title}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((item, idx) => {
              return (
                <tr
                  key={idx}
                  className="border-b border-[#E8E8E8] hover:bg-[#F8F8F8] group"
                >
                  {/* Rank */}
                  {columns.map((col, idex) => (
                    <td
                      key={idex}
                      className={col.rowStyle ?? `py-2.5 pr-3 align-top`}
                    >
                      {renderCell(col, item)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
