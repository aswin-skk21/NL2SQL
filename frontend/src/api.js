// Thin client for the NL2SQL backend.
// Response shape mirrors QueryResponse in backend/app/api.py.

export async function askQuestion(question) {
  const res = await fetch("/api/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });

  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // response had no JSON body; keep the status-based message
    }
    throw new Error(detail);
  }

  return res.json();
}