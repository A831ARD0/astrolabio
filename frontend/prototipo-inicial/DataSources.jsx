import { useState, useCallback } from "react";
import { uploadFile } from "./api";

export default function DataSources({ tables, refreshTables }) {
  const [dragOver, setDragOver] = useState(false);
  const [status, setStatus] = useState("");

  const handleFiles = useCallback(
    async (files) => {
      for (const file of files) {
        setStatus(`Cargando ${file.name}...`);
        try {
          const result = await uploadFile(file);
          setStatus(`"${result.table}" cargada (${result.rows} filas)`);
        } catch (e) {
          setStatus(`Error: ${e.message}`);
        }
      }
      refreshTables();
    },
    [refreshTables]
  );

  return (
    <div className="panel">
      <h2>Conexión de datos</h2>
      <p className="hint">
        Arrastra un archivo CSV o Excel para cargarlo — no se necesita configurar ninguna conexión manual.
      </p>
      <div
        className={`dropzone ${dragOver ? "dropzone-active" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          handleFiles(Array.from(e.dataTransfer.files));
        }}
        onClick={() => document.getElementById("file-input").click()}
      >
        <span>Suelta aquí tu archivo (.csv, .xlsx)</span>
        <span className="hint">o haz clic para seleccionar</span>
        <input
          id="file-input"
          type="file"
          accept=".csv,.xlsx,.xls"
          style={{ display: "none" }}
          onChange={(e) => handleFiles(Array.from(e.target.files))}
        />
      </div>
      {status && <div className="status-line">{status}</div>}

      <h3>Tablas cargadas</h3>
      {tables.length === 0 && <p className="hint">Todavía no hay tablas.</p>}
      <div className="table-list">
        {tables.map((t) => (
          <div key={t.table} className="table-card">
            <div className="table-card-title">{t.table}</div>
            <div className="hint">{t.rows} filas · {t.columns.length} columnas</div>
            <div className="col-chips">
              {t.columns.map((c) => (
                <span key={c.name} className="chip">
                  {c.name}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
