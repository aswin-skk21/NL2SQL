import { useState } from "react";
import { AuthError, askQuestion, clearToken, getToken, setToken } from "./api";

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

  async function handleSubmit(e) {
    e.preventDefault();
    if (!question.trim() || loading) return;

    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const data = await askQuestion(question);
      setResult(data);
    } catch (err) {
      if (err instanceof AuthError) {
        clearToken();
        setNeedsToken(true);
      }
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  if (needsToken) {
    return (
      <div className="app">
        <header className="app-header">
          <div className="logo-badge">SQL</div>
          <h1>IPSD Database Query Tool</h1>
          <p>Enter the access token to continue.</p>
        </header>

        <form className="query-form" onSubmit={handleTokenSubmit}>
          <input
            type="password"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            placeholder="Access token"
            autoFocus
          />
          <button type="submit" disabled={!tokenInput.trim()}>
            Continue
          </button>
        </form>

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
        <div className="logo-badge">SQL</div>
        <h1>NL2SQL</h1>
        <p>Ask a question about your data in plain English.</p>
      </header>

      <form className="query-form" onSubmit={handleSubmit}>
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. What were total sales last quarter?"
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

      {error && (
        <div className="error-box">
          <strong>Error</strong>
          <span>{error}</span>
        </div>
      )}

      {result && (
        <div className="result">
          <section className="card answer">
            <h2>Answer</h2>
            <p>{result.answer}</p>
          </section>

          {result.sql && (
            <section className="card sql">
              <h2>SQL</h2>
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
                          <td key={col}>{String(row[col])}</td>
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