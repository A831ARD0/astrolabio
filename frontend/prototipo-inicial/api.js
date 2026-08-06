const BASE = "http://localhost:8000/api";

export async function uploadFile(file) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/upload`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listTables() {
  const res = await fetch(`${BASE}/tables`);
  return res.json();
}

export async function runQuery(spec) {
  const res = await fetch(`${BASE}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(spec),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
