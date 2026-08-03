import { useState } from "react";
import { AuthError, askQuestion, clearToken, getToken, setToken } from "./api";

const EXAMPLE_QUESTIONS = [
  "How many rows are in the largest table?",
  "Show me the 10 most recently added records",
  "List the distinct values in a status or type column",
];

function formatCell(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API can be unavailable (e.g. non-HTTPS); fail silently.
    }
  }

  return (
    <button type="button" className="copy-btn" onClick={handleCopy}>
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export default function App() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [tokenInput, setTokenInput] = useState("");
  const [needsToken, setNeedsToken] = useState(!getToken());

  function handleTokenSubmit(e) {
    e.preventDefault();
    if (!tokenInput.trim()) return;
    setToken(tokenInput);
    setTokenInput("");
    setNeedsToken(false);
    setError(null);
  }

  async function runQuery(q) {
    if (!q.trim() || loading) return;

    setLoading(true);
    setError(null);

    try {
      const data = await askQuestion(q);
      setResult(data);
    } catch (err) {
      if (err instanceof AuthError) {
        clearToken();
        setNeedsToken(true);
      }
      setError(err.message);
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(e) {
    e.preventDefault();
    runQuery(question);
  }

  function handleExampleClick(text) {
    setQuestion(text);
  }

  if (needsToken) {
    return (
      <div className="app">
        <header className="app-header">
          <div className="logo-badge">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" aria-hidden="true">
              <ellipse cx="12" cy="5" rx="7" ry="2.5" stroke="currentColor" strokeWidth="1.6" />
              <path
                d="M5 5v6c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5V5"
                stroke="currentColor"
                strokeWidth="1.6"
              />
              <path
                d="M5 11v6c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-6"
                stroke="currentColor"
                strokeWidth="1.6"
              />
            </svg>
          </div>
          <h1>NL2SQL</h1>
          <p>Enter the access token to continue.</p>
        </header>

        <form className="query-form" onSubmit={handleTokenSubmit}>
          <input
            type="password"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            placeholder="Access token"
            aria-label="Access token"
            autoFocus
          />
          <button type="submit" disabled={!tokenInput.trim()}>
            Continue
          </button>
        </form>
        <p className="hint">Ask whoever runs this deployment for your token.</p>

        {error && (
          <div className="error-box">
            <strong>Error</strong>
            <span>{error}</span>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="logo-badge">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" aria-hidden="true">
            <ellipse cx="12" cy="5" rx="7" ry="2.5" stroke="currentColor" strokeWidth="1.6" />
            <path
              d="M5 5v6c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5V5"
              stroke="currentColor"
              strokeWidth="1.6"
            />
            <path
              d="M5 11v6c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-6"
              stroke="currentColor"
              strokeWidth="1.6"
            />
          </svg>
        </div>
        <h1>NL2SQL</h1>
        <p>Ask a question about your data in plain English.</p>
      </header>

      <form className="query-form" onSubmit={handleSubmit}>
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. What were total sales last quarter?"
          aria-label="Question"
          disabled={loading}
        />
        <button type="submit" disabled={loading || !question.trim()}>
          {loading ? (
            <>
              <span className="spinner" aria-hidden="true" />
              Thinking…
            </>
          ) : (
            "Ask"
          )}
        </button>
      </form>

      {!result && !error && (
        <div className="examples">
          {EXAMPLE_QUESTIONS.map((q) => (
            <button
              key={q}
              type="button"
              className="example-chip"
              onClick={() => handleExampleClick(q)}
              disabled={loading}
            >
              {q}
            </button>
          ))}
        </div>
      )}

      {error && (
        <div className="error-box">
          <strong>Error</strong>
          <span>{error}</span>
        </div>
      )}

      {result && (
        <div className={`result${loading ? " result-stale" : ""}`}>
          <section className="card answer">
            <h2>Answer</h2>
            <p>{result.answer}</p>
          </section>

          {result.sql && (
            <section className="card sql">
              <div className="card-heading">
                <h2>SQL</h2>
                <CopyButton text={result.sql} />
              </div>
              <pre>{result.sql}</pre>
            </section>
          )}

          {result.error && (
            <div className="error-box">
              <strong>Error</strong>
              <span>{result.error}</span>
            </div>
          )}

          {result.rows && result.columns && (
            <section className="card rows">
              <h2>
                Results{" "}
                <span className="row-count">
                  ({result.row_count} row{result.row_count === 1 ? "" : "s"}
                  {result.truncated ? ", truncated" : ""}
                  {result.row_count > result.rows.length
                    ? `, showing first ${result.rows.length}`
                    : ""}
                  )
                </span>
              </h2>
              <div className="table-wrapper">
                <table>
                  <thead>
                    <tr>
                      {result.columns.map((col) => (
                        <th key={col}>{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.map((row, i) => (
                      <tr key={i}>
                        {result.columns.map((col) => (
                          <td
                            key={col}
                            className={
                              typeof row[col] === "number" ? "cell-number" : undefined
                            }
                          >
                            {formatCell(row[col])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
