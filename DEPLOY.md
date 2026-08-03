# Deploying NL2SQL on the Windows server

Target: a domain-joined Windows machine that reaches all seven SQL Servers via
Windows Authentication, serving a handful of internal colleagues.

Everything below runs **on the Windows box**, not on your laptop. Steps 1–7 get
it running in the foreground; step 8 turns it into a service.

---

## 0. Before you start — what to confirm with IT

These are the things that block deployments and are not in your control:

| Question | Why it matters |
|---|---|
| Which **domain account** will the service run as? | Windows Auth means SQL sees *the service account*, not you. It needs read access on all 7 servers. |
| Can that account **log on as a service** without interactive MFA? | Your own account authenticates via Duo interactively — a service cannot. Ask for a service account or a gMSA. |
| Is **outbound HTTPS to `generativelanguage.googleapis.com`** allowed? | Every query calls Gemini. A blocked egress proxy fails all queries. |
| Which **port** may listen, and does the firewall allow it internally? | Default 8000. |

> The account question is the single most common reason this kind of deployment
> stalls. Settle it first.

---

## 1. Prerequisites

Install on the Windows machine:

- **Python 3.11+** (3.13 is what the pins were verified against) — tick "Add to PATH"
- **[ODBC Driver 18 for SQL Server](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)**
- **Git**
- **Node.js 18+** — only needed to build the frontend. If Node is not permitted
  on the server, see step 6 for the alternative.

Verify:

```bat
python --version
git --version
node --version
```

---

## 2. Clone and create a virtualenv

```bat
cd C:\apps
git clone <your-repo-url> NL2SQL
cd NL2SQL
python -m venv venv
venv\Scripts\activate
pip install -r backend\requirements.txt
```

---

## 3. Configure secrets

```bat
copy .env.example .env
```

Generate the shared token and paste both values into `.env`:

```bat
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

`.env` should end up with:

```
GOOGLE_API_KEY=<your gemini key>
NL2SQL_API_TOKEN=<the generated token>
```

The app **refuses to start** if either is missing — that is deliberate, since
this endpoint runs generated SQL against production.

---

## 4. Handle ODBC Driver 18 encryption

Driver 18 defaults to `Encrypt=yes` and validates the server certificate. Internal
SQL Servers usually have self-signed certs, so the first connection often fails with:

```
SSL Provider: The certificate chain was issued by an authority that is not trusted.
```

If that happens, add `TrustServerCertificate` to the affected servers in
`backend\app\config.py`:

```python
"sqlProd1": ServerConfig(
    host="sqlProd1",
    databases=[],
    extra_params={"TrustServerCertificate": "yes"},
),
```

Prefer a properly trusted certificate where your team can arrange it.

---

## 5. Discover databases and build the schema cache

This is the step that populates the (intentionally empty) cache.

```bat
cd backend
python scripts\discover_databases.py
```

It connects to each server in `SERVERS`, lists databases, and writes your
selections into `app\config.py`. Use `--dry-run` first to preview, or `--all` to
accept everything.

Then build the embedding index:

```bat
python scripts\schema_cache.py
```

This writes `backend\scripts\schema_cache.json` and `schema_embeddings.npy`.
Re-run it whenever the database schema changes.

> **Note:** `discover_databases.py` edits `app/config.py` in place, so that file
> will show as modified in git on the server. Either commit the populated version
> from the server, or leave it dirty and never `git checkout` over it.

Sanity check before moving on — this should print a non-zero table count:

```bat
python -c "import sys; sys.path.insert(0,'.'); from scripts.schema_cache import load_cache; print(len(load_cache().tables), 'tables cached')"
```

---

## 6. Build the frontend

```bat
cd ..\frontend
npm ci
npm run build
```

This produces `frontend\dist`, which the API serves at `/`.

**If Node is not allowed on the server:** run those commands on your laptop and
copy the resulting `frontend\dist` folder to the same path on the server. It is
static HTML/CSS/JS with no build-time secrets.

---

## 7. First run

```bat
cd ..\backend
..\venv\Scripts\python server.py
```

From another window:

```bat
curl http://localhost:8000/api/health
```

Expect `{"status":"ok","tables_cached":<n>,...}` with `n` matching step 5.

Then open `http://localhost:8000/` in a browser, paste the token, and ask a
question. Confirm a real answer comes back before setting up the service.

---

## 8. Run it as a Windows service

Use **NSSM** (simplest) or Task Scheduler. With NSSM:

```bat
nssm install NL2SQL "C:\apps\NL2SQL\venv\Scripts\python.exe" "C:\apps\NL2SQL\backend\server.py"
nssm set NL2SQL AppDirectory C:\apps\NL2SQL\backend
nssm set NL2SQL AppStdout C:\apps\NL2SQL\logs\nl2sql.log
nssm set NL2SQL AppStderr C:\apps\NL2SQL\logs\nl2sql.log
nssm set NL2SQL Start SERVICE_AUTO_START
```

Set the logon identity to the domain service account from step 0 — this is what
makes `Trusted_Connection=yes` work:

```bat
nssm set NL2SQL ObjectName DOMAIN\svc_nl2sql "<password>"
nssm start NL2SQL
```

Then allow the port internally:

```bat
netsh advfirewall firewall add rule name="NL2SQL" dir=in action=allow protocol=TCP localport=8000
```

> The service steps could not be tested from this machine — they need the domain
> box. If `nssm start` fails, check `logs\nl2sql.log` first; a SQL login failure
> there almost always means the service account lacks read access, not a code
> problem.

---

## 9. Give colleagues access

Send them the URL (`http://<server>:8000/`) and the token, **separately from the
URL** and not over a channel that logs plaintext. On first visit they paste the
token once; it stays in their browser's localStorage.

To rotate the token: change `NL2SQL_API_TOKEN` in `.env`, restart the service,
redistribute. Everyone is prompted again automatically.

### About HTTPS

Traffic — including the token and your query results — is plain HTTP. On a
trusted internal network that is often accepted, but anyone who can sniff the
segment sees both. If this holds sensitive data, front it with IIS or Caddy
doing TLS and proxying to `127.0.0.1:8000`, and set `NL2SQL_HOST=127.0.0.1` so
the app is only reachable through the proxy.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `RuntimeError: GOOGLE_API_KEY is not set` | `.env` missing or in the wrong place. It is read from `backend\.env` first, then the repo root. |
| `RuntimeError: NL2SQL_API_TOKEN is not set` | Same file; generate one per step 3. |
| `Schema cache not found` at startup | Step 5 was not run on this machine. |
| `Schema cache is empty` warning, every query 500s | `databases=[]` still empty in `config.py` — re-run `discover_databases.py`. |
| `certificate chain ... not trusted` | Step 4. |
| `Login failed for user 'DOMAIN\svc_...'` | Service account lacks SQL read access. Not a code issue. |
| Queries hang then fail after ~60s | `NL2SQL_QUERY_TIMEOUT` hit. Raise it, or the question needs a narrower query. |
| Browser shows the token prompt repeatedly | Token mismatch between browser and `.env`; confirm the service restarted after a change. |
| `Query failed. Check the server log` | Generic by design. The real traceback is in the service log. Set `NL2SQL_DEBUG_ERRORS=1` temporarily to surface detail in the response. |

---

## Operating notes

- **Re-run `scripts\schema_cache.py`** after schema changes, or routing silently
  targets stale tables.
- **Cost:** every question calls Gemini (embedding + Flash routing + Pro
  generation + Flash answer), and each failed validation attempt adds another Pro
  call. Watch the first weeks of usage.
- **Read-only by construction:** the validator rejects anything that is not a
  single `SELECT`. Enforce it at the database layer too — grant the service
  account `db_datareader` and nothing more, so a guard bug cannot become a write.
