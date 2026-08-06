import { useState, useMemo } from "react";
import { runQuery } from "./api";

const AGGS = ["sum", "avg", "count", "count_distinct", "min", "max"];
const OPS = ["=", "!=", ">", ">=", "<", "<=", "contiene"];

export default function QueryBuilder({ tables, savedQueries, setSavedQueries }) {
  const [tableName, setTableName] = useState("");
  const [dimensions, setDimensions] = useState([]);
  const [metrics, setMetrics] = useState([]);
  const [filters, setFilters] = useState([]);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState("");
  const [queryLabel, setQueryLabel] = useState("");

  const table = useMemo(() => tables.find((t) => t.table === tableName), [tables, tableName]);
  const columns = table ? table.columns.map((c) => c.name) : [];

  function toggleDimension(col) {
    setDimensions((d) => (d.includes(col) ? d.filter((x) => x !== col) : [...d, col]));
  }

  function addMetric() {
    if (!columns.length) return;
    setMetrics((m) => [...m, { column: columns[0], agg: "sum", alias: "" }]);
  }
  function updateMetric(i, patch) {
    setMetrics((m) => m.map((x, idx) => (idx === i ? { ...x, ...patch } : x)));
  }
  function removeMetric(i) {
    setMetrics((m) => m.filter((_, idx) => idx !== i));
  }

  function addFilter() {
    if (!columns.length) return;
    setFilters((f) => [...f, { column: columns[0], op: "=", value: "" }]);
  }
  function updateFilter(i, patch) {
    setFilters((f) => f.map((x, idx) => (idx === i ? { ...x, ...patch } : x)));
  }
  function removeFilter(i) {
    setFilters((f) => f.filter((_, idx) => idx !== i));
  }

  function buildSpec() {
    return {
      table: tableName,
      dimensions,
      metrics: metrics.map((m) => ({ ...m, alias: m.alias || `${m.agg}_${m.column}` })),
      filters,
      limit: 1000,
    };
  }

  async function handleRun() {
    setError("");
    try {
      const spec = buildSpec();
      const result = await runQuery(spec);
      setPreview(result);
    } catch (e) {
      setError(e.message);
    }
  }

  function handleSave() {
    if (!preview) return;
    const name = queryLabel || `Consulta ${savedQueries.length + 1}`;
    setSavedQueries((qs) => [
      ...qs,
      { id: crypto.randomUUID(), name, spec: buildSpec() },
    ]);
    setQueryLabel("");
  }

  return (
    <div className="panel">
      <h2>Constructor de consultas</h2>
      <p className="hint">Elige tabla, columnas y filtros con menús — no se escribe SQL.</p>

      <label className="field-label">Tabla</label>
      <select value={tableName} onChange={(e) => { setTableName(e.target.value); setDimensions([]); setMetrics([]); setFilters([]); setPreview(null); }}>
        <option value="">Selecciona una tabla…</option>
        {tables.map((t) => (
          <option key={t.table} value={t.table}>{t.table}</option>
        ))}
      </select>

      {tableName && (
        <>
          <label className="field-label">Agrupar por (dimensiones)</label>
          <div className="col-chips">
            {columns.map((c) => (
              <button
                key={c}
                className={`chip chip-toggle ${dimensions.includes(c) ? "chip-selected" : ""}`}
                onClick={() => toggleDimension(c)}
              >
                {c}
              </button>
            ))}
          </div>

          <label className="field-label">Métricas</label>
          {metrics.map((m, i) => (
            <div key={i} className="row-inline">
              <select value={m.agg} onChange={(e) => updateMetric(i, { agg: e.target.value })}>
                {AGGS.map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
              <select value={m.column} onChange={(e) => updateMetric(i, { column: e.target.value })}>
                {columns.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <input
                placeholder="alias (opcional)"
                value={m.alias}
                onChange={(e) => updateMetric(i, { alias: e.target.value })}
              />
              <button className="btn-icon" onClick={() => removeMetric(i)}>✕</button>
            </div>
          ))}
          <button className="btn-secondary" onClick={addMetric}>+ Agregar métrica</button>

          <label className="field-label">Filtros</label>
          {filters.map((f, i) => (
            <div key={i} className="row-inline">
              <select value={f.column} onChange={(e) => updateFilter(i, { column: e.target.value })}>
                {columns.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <select value={f.op} onChange={(e) => updateFilter(i, { op: e.target.value })}>
                {OPS.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
              <input
                placeholder="valor"
                value={f.value}
                onChange={(e) => updateFilter(i, { value: e.target.value })}
              />
              <button className="btn-icon" onClick={() => removeFilter(i)}>✕</button>
            </div>
          ))}
          <button className="btn-secondary" onClick={addFilter}>+ Agregar filtro</button>

          <div className="row-inline" style={{ marginTop: 16 }}>
            <button className="btn-primary" onClick={handleRun}>▶ Ejecutar</button>
            <input
              placeholder="Nombre de la consulta"
              value={queryLabel}
              onChange={(e) => setQueryLabel(e.target.value)}
            />
            <button className="btn-secondary" disabled={!preview} onClick={handleSave}>
              💾 Guardar consulta
            </button>
          </div>

          {error && <div className="status-line status-error">{error}</div>}

          {preview && (
            <div className="preview">
              <table>
                <thead>
                  <tr>{preview.columns.map((c) => <th key={c}>{c}</th>)}</tr>
                </thead>
                <tbody>
                  {preview.rows.slice(0, 20).map((row, i) => (
                    <tr key={i}>
                      {preview.columns.map((c) => <td key={c}>{String(row[c])}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="hint">{preview.rows.length} filas de resultado</div>
            </div>
          )}
        </>
      )}

      {savedQueries.length > 0 && (
        <>
          <h3>Consultas guardadas</h3>
          <div className="col-chips">
            {savedQueries.map((q) => <span key={q.id} className="chip">{q.name}</span>)}
          </div>
        </>
      )}
    </div>
  );
}
