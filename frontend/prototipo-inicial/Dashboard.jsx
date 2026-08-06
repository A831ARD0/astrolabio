import { useState, useEffect, useCallback } from "react";
import { Responsive, WidthProvider } from "react-grid-layout";
import ReactECharts from "echarts-for-react";
import { runQuery } from "./api";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";

const GridLayout = WidthProvider(Responsive);

const CHART_TYPES = ["bar", "line", "pie", "table"];

function buildOption(chartType, data) {
  const cols = data.columns;
  if (!cols.length || !data.rows.length) return { title: { text: "Sin datos" } };
  const labelCol = cols[0];
  const valueCols = cols.slice(1);

  if (chartType === "pie") {
    const valueCol = valueCols[0] || cols[0];
    return {
      tooltip: { trigger: "item" },
      series: [{
        type: "pie",
        radius: "65%",
        data: data.rows.map((r) => ({ name: String(r[labelCol]), value: r[valueCol] })),
      }],
    };
  }

  return {
    tooltip: { trigger: "axis" },
    legend: { data: valueCols },
    xAxis: { type: "category", data: data.rows.map((r) => String(r[labelCol])) },
    yAxis: { type: "value" },
    series: valueCols.map((vc) => ({
      name: vc,
      type: chartType === "line" ? "line" : "bar",
      data: data.rows.map((r) => r[vc]),
    })),
  };
}

function Widget({ item, savedQueries }) {
  const [data, setData] = useState(null);
  const query = savedQueries.find((q) => q.id === item.queryId);

  useEffect(() => {
    if (!query) return;
    runQuery(query.spec).then(setData).catch(() => setData(null));
  }, [query]);

  if (!query) return <div className="widget-empty">Consulta no encontrada</div>;
  if (!data) return <div className="widget-empty">Cargando…</div>;

  if (item.chartType === "table") {
    return (
      <div className="widget-table-wrap">
        <table>
          <thead><tr>{data.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>
            {data.rows.slice(0, 50).map((row, i) => (
              <tr key={i}>{data.columns.map((c) => <td key={c}>{String(row[c])}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return <ReactECharts option={buildOption(item.chartType, data)} style={{ height: "100%", width: "100%" }} />;
}

export default function Dashboard({ savedQueries }) {
  const [items, setItems] = useState([]);
  const [layout, setLayout] = useState([]);
  const [pickQuery, setPickQuery] = useState("");
  const [pickChart, setPickChart] = useState("bar");

  const addWidget = useCallback(() => {
    if (!pickQuery) return;
    const id = crypto.randomUUID();
    const query = savedQueries.find((q) => q.id === pickQuery);
    setItems((it) => [...it, { id, queryId: pickQuery, chartType: pickChart, title: query?.name || "Widget" }]);
    setLayout((l) => [...l, { i: id, x: (l.length * 4) % 12, y: Infinity, w: 4, h: 6 }]);
  }, [pickQuery, pickChart, savedQueries]);

  function removeWidget(id) {
    setItems((it) => it.filter((w) => w.id !== id));
    setLayout((l) => l.filter((w) => w.i !== id));
  }

  return (
    <div className="panel">
      <h2>Dashboard</h2>
      <p className="hint">Agrega gráficos desde tus consultas guardadas y arrástralos/redimensiónalos libremente.</p>

      <div className="row-inline">
        <select value={pickQuery} onChange={(e) => setPickQuery(e.target.value)}>
          <option value="">Selecciona una consulta guardada…</option>
          {savedQueries.map((q) => <option key={q.id} value={q.id}>{q.name}</option>)}
        </select>
        <select value={pickChart} onChange={(e) => setPickChart(e.target.value)}>
          {CHART_TYPES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <button className="btn-primary" disabled={!pickQuery} onClick={addWidget}>+ Agregar al dashboard</button>
      </div>

      {items.length === 0 && <p className="hint">Aún no hay widgets. Guarda una consulta y agrégala aquí.</p>}

      <GridLayout
        className="layout"
        layouts={{ lg: layout }}
        breakpoints={{ lg: 900, sm: 0 }}
        cols={{ lg: 12, sm: 4 }}
        rowHeight={30}
        onLayoutChange={(l) => setLayout(l)}
        draggableHandle=".widget-handle"
      >
        {items.map((item) => (
          <div key={item.id} className="widget-box">
            <div className="widget-handle">
              <span>{item.title}</span>
              <button className="btn-icon" onClick={() => removeWidget(item.id)}>✕</button>
            </div>
            <div className="widget-body">
              <Widget item={item} savedQueries={savedQueries} />
            </div>
          </div>
        ))}
      </GridLayout>
    </div>
  );
}
