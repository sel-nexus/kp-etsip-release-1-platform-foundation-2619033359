# KP ETSIP — quality inventory prototype

The application implements local identity and profile, portfolio and application inventory, an executive dashboard, user and role administration, reporting and a separate audit view with CSV exports. Access is role- and portfolio-scoped. Application quality metrics are manually entered, not live measurements or external integrations.

> **Human-accepted prototype risk — not production ready:** Portfolio, application, user, role-permission, password and profile writes are not atomic with their audit events. A write can succeed while a subsequent audit insert fails, leaving the change without its audit event, even if the request reports an error. **FR-AUDIT-01 is unmet.** Investigate uncertain failures and reconcile affected data and audit records; do not rely on the audit trail as complete. CSV export events record initiation before streaming, not successful delivery. Stale inventory reservations or an administration lock require manual recovery (see below).

## Local run

For a manual run use Python 3.12, Node.js 22 and npm (the container build uses these versions), plus a reachable MongoDB; the Compose setup requires Docker and Compose instead. Use an isolated MongoDB instance for development, never a shared or production database. The default backend example points to `mongodb://127.0.0.1:27017` and database `kp_etsip`; start Mongo separately or set `MONGODB_URI` and `MONGODB_DB` to your isolated instance. Do not expose an unauthenticated MongoDB publicly.

Copy `backend/.env.example` to `backend/.env` and `frontend/.env.example` to `frontend/.env` if absent. These files are local and gitignored. The example leaves secrets blank. Set `JWT_SECRET` in `backend/.env` to a unique random secret of at least 32 characters (generate one with `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`). When seeding is enabled, both initial passwords must be at least 12 characters and at most 72 bytes. Use separate strong passwords; do not commit secrets.

In a terminal:

```sh
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

In a second terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open http://localhost:5173. Vite proxies `/api` to the backend. Alternatively, after configuring `backend/.env`, run `docker compose up --build` from the root and visit http://localhost:8080. Compose overrides the Mongo URI to its unauthenticated, internal-network MongoDB service; it does not publish MongoDB to the host and persists data in the `mongo_data` volume. This is for isolated local use only.

With `SEED_ON_STARTUP=true`, the configured initial passwords are used for the administrator (`admin@ketsip.local`) and demo accounts (`executive@ketsip.local`, `leader@ketsip.local`, `engineer@ketsip.local`, `auditor@ketsip.local`, `readonly@ketsip.local`). The administrator must change its initial password. Seed inserts only missing records; changing environment passwords does not reset existing users. The seeded leader is assigned Payments.

## Inventory coordination and recovery

Application create and transfer reserve the destination portfolio by an atomic update on its MongoDB document. Portfolio deletion first marks that document only if no reservations exist, blocking new reservations, then checks for application references. User portfolio assignments also use reservations. A busy or nonempty portfolio returns 409. This coordination works across API processes on a standalone MongoDB without multi-document transactions; all application writers, including seed jobs, must use the same protocol. Majority-acknowledged writes protect the protocol from normal replica-set failover.

An uncertain database failure or process crash may leave a reservation or deletion marker behind: operations then fail closed rather than risking an orphan. An operator must stop all writers, inspect the portfolio and its application and user references, then remove only confirmed stale `applicationReservations` or `deleting` fields before resuming. Never expire these automatically. Direct database writes that bypass this protocol are unsafe.

Administration mutations are serialized using the `admin_locks` document with `_id` `admin-mutations`. A crash or failed unlock can leave it behind, causing administration mutations to return 409. To recover, stop all writers, verify no administration mutation is in progress, inspect the affected user/role state and audit records, and remove the confirmed stale lock before resuming. Investigate uncertain writes and potentially missing audit events in both recovery cases.

## Security and deployment

Set a unique high-entropy `JWT_SECRET` of at least 32 characters, use separate strong initial passwords, disable seeding after provisioning, use authenticated TLS MongoDB and restrict database network access. Terminate HTTPS at the CDN/load balancer, configure explicit CORS origins if cross-origin, and never expose the development compose database publicly. The example leaves secret fields blank; supply unique values privately. JWTs last eight hours; profile password changes revoke older tokens. Logout clears the browser token but does not revoke an already copied token. Bearer tokens are stored in sessionStorage to satisfy the API contract; XSS can read them. The nginx configuration sets a restrictive CSP; avoid unsafe HTML insertion and maintain CSP at the production edge. Configure rate limiting at the edge for login.

## Checks

With an isolated MongoDB running and dependencies installed, run these from the repository root in separate terminals, or return to the root between commands:

```sh
cd backend && PYTHONPATH=. pytest -q
cd frontend && npm test && npm run build
```

Backend tests use uniquely named temporary databases on `TEST_MONGODB_URI` (default `mongodb://127.0.0.1:27017`) and drop those databases during fixture cleanup. Use an isolated MongoDB instance, not development or production data.

### Playwright browser suite

The suite creates users and changes credentials, roles and inventory. Start MongoDB separately on an isolated instance and use a **new, empty, dedicated database for every run**, never a development or production database. The suite seeds and mutates that database and does not clean it up automatically. Install the backend requirements in the Python executable used by `E2E_PYTHON` (default `python`), run `npm ci` in `frontend`, and install Playwright Chromium and its system dependencies as needed (`npx playwright install chromium`). Ensure ports 8000 and 5173 are free: Playwright starts its own Uvicorn backend and Vite frontend and does not reuse existing servers.

From `frontend`, set `E2E_MONGODB_URI` to the isolated Mongo URI, `E2E_MONGODB_DB` to a fresh database name beginning with `e2e_`, and `E2E_JWT_SECRET` to a unique random secret of at least 32 characters. The backend also rejects the public example secret. For example, in a POSIX shell, after starting isolated local MongoDB:

```sh
export E2E_MONGODB_URI='mongodb://127.0.0.1:27017'
export E2E_MONGODB_DB="e2e_$(python -c 'import uuid; print(uuid.uuid4().hex)')"
export E2E_JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
# Optional: select the Python with backend requirements installed.
# export E2E_PYTHON='/absolute/path/to/python'
node node_modules/@playwright/test/cli.js test
```

Playwright runs a setup project that changes the seeded administrator's initial password, followed by Chromium tests with one worker at `http://127.0.0.1:5173`. It enables seeding and configures the API proxy. Optional `E2E_ADMIN_INITIAL_PASSWORD`, `E2E_ADMIN_PASSWORD` (the post-change password), and `E2E_DEMO_PASSWORD` override test defaults; keep them consistent across the suite and use valid seed passwords. Individual specs also support email/password overrides; see `frontend/e2e/`. `E2E_BASE_URL` does not configure this suite. Treat all test credentials as local-only.
