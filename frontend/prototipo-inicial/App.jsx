import { useState, useEffect, useCallback } from "react";
import { listTables } from "./api";
import DataSources from "./DataSources";
import QueryBuilder from "./QueryBuilder";
import Dashboard from "./Dashboard";
import "./App.css";

const TABS = [
  { key: "sources", label: "1. Datos" },
  { key: "query", label: "2. Consultas" },
  { key: "dashboard", label: "3. Dashboard" },
];

export default function App() {
  const [tab, setTab] = useState("sources");
  const [tables, setTables] = useState([]);
  const [savedQueries, setSavedQueries] = useState([]);

  const refreshTables = useCallback(() => {
    listTables().then(setTables).catch(() => {});
  }, []);

  useEffect(() => {
    refreshTables();
  }, [refreshTables]);

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-title">Bonn BI — Prototipo</span>
        <nav className="tabs">
          {TABS.map((t) => (
            <button
              key={t.key}
              className={`tab-btn ${tab === t.key ? "tab-active" : ""}`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>
      <main>
        {tab === "sources" && <DataSources tables={tables} refreshTables={refreshTables} />}
        {tab === "query" && (
          <QueryBuilder tables={tables} savedQueries={savedQueries} setSavedQueries={setSavedQueries} />
        )}
        {tab === "dashboard" && <Dashboard savedQueries={savedQueries} />}
      </main>
    </div>
  );
}
