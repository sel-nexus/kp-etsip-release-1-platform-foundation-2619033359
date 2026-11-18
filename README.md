# KP ETSIP — identity foundation

This slice provides local sign-in and profile management. Dashboard, inventory, administration and reporting are not implemented yet. Destination pages identify that limitation rather than showing fabricated data.

## Local run

MongoDB must be available at `mongodb://127.0.0.1:27017`. `backend/.env` and `frontend/.env` are local, gitignored configuration; copy the matching `.env.example` files if absent. These example values are for an isolated development machine only. Before starting, replace `JWT_SECRET` in `backend/.env` with a unique random value (for example, generate one with `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`). Run:

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
npm install
npm run dev
```

Open http://localhost:5173. Vite proxies `/api` to the backend. Alternatively run `docker compose up --build` from the root and visit http://localhost:8080. Compose uses an unauthenticated MongoDB on an internal network for local use only and a persistent `mongo_data` volume.

Local seed credentials, when `.env.example` values are used: `admin@ketsip.local` / `LocalAdmin123!` (initial change required), and `executive@ketsip.local`, `leader@ketsip.local`, `engineer@ketsip.local`, `auditor@ketsip.local`, `readonly@ketsip.local` / `LocalDemo123!`. Seed inserts only missing records; changing environment passwords does not reset existing users. Leader has no assigned portfolios until a later administration slice.

## Security and deployment

Set a unique high-entropy `JWT_SECRET` of at least 32 characters, use separate strong initial passwords, disable seeding after provisioning, use authenticated TLS MongoDB and restrict database network access. Terminate HTTPS at the CDN/load balancer, configure explicit CORS origins if cross-origin, and never expose the development compose database publicly. The example secret and passwords are public dummy values and **must not be used in deployment**. The public example secret is rejected at startup, including during seeding. JWTs last eight hours; profile password changes revoke older tokens. Logout clears the browser token but does not revoke an already copied token. Bearer tokens are stored in sessionStorage to satisfy the API contract; XSS can read them. The nginx configuration sets a restrictive CSP; avoid unsafe HTML insertion and maintain CSP at the production edge. Configure rate limiting at the edge for login.

## Checks

```sh
cd backend && PYTHONPATH=. pytest -q tests/test_auth.py
cd frontend && npm test && npm run build
```

Backend tests use a uniquely named temporary database on `TEST_MONGODB_URI` (default localhost MongoDB) and drop only that database. The browser spec uses a live running frontend, backend and MongoDB, and changes the demo engineer's preference; use a disposable seeded environment. Run from `frontend` with `node node_modules/@playwright/test/cli.js test` and optional `E2E_BASE_URL`, `E2E_EMAIL`, `E2E_PASSWORD`. Browser tests are not run as part of this slice handoff.
