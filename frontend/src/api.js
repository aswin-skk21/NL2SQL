const TOKEN_KEY = "nl2sql_token";

// The bundle is static and readable by anyone who loads the page, so the token
// is never baked in at build time — each user pastes their own and it stays in
// this browser only.
export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token.trim());
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export class AuthError extends Error {}

export async function askQuestion(question) {
  const res = await fetch("/api/query", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
    },
    body: JSON.stringify({ question }),
  });

  if (res.status === 401) {
    throw new AuthError("Invalid or missing access token.");
  }

  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {}
    throw new Error(detail);
  }

  return res.json();
}
