import { defineConfig } from '@playwright/test';

// Run only against a fresh, dedicated Mongo database; never point this suite at
// development or production data. It creates users, changes credentials and roles.
// Install frontend dependencies and backend/requirements.txt in the Python used
// by E2E_PYTHON (default: python). Start Mongo separately and supply:
// E2E_MONGODB_URI, E2E_MONGODB_DB (must start with e2e_), E2E_JWT_SECRET
// (unique, >=32 characters). For repeatable runs use a new empty DB each time.
// Optional E2E_ADMIN_INITIAL_PASSWORD, E2E_ADMIN_PASSWORD and E2E_DEMO_PASSWORD
// override the local-only test credentials below; keep them consistent across runs.
const mongoUri = process.env.E2E_MONGODB_URI;
const mongoDb = process.env.E2E_MONGODB_DB;
const secret = process.env.E2E_JWT_SECRET;
if (!mongoUri || !mongoDb?.startsWith('e2e_') || !secret || secret.length < 32) {
  throw new Error('Set E2E_MONGODB_URI, E2E_MONGODB_DB (e2e_ prefix), and E2E_JWT_SECRET (32+ characters) for an isolated Mongo database.');
}

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  use: { baseURL: 'http://127.0.0.1:5173', trace: 'retain-on-failure' },
  projects: [
    { name: 'setup', testMatch: '00-setup.spec.ts' },
    { name: 'chromium', testIgnore: '00-setup.spec.ts', dependencies: ['setup'] },
  ],
  webServer: [
    {
      command: `${process.env.E2E_PYTHON ?? 'python'} -m uvicorn app.main:app --host 127.0.0.1 --port 8000`,
      cwd: '../backend',
      url: 'http://127.0.0.1:8000/api/health',
      reuseExistingServer: false,
      timeout: 120000,
      env: {
        MONGODB_URI: mongoUri, MONGODB_DB: mongoDb, JWT_SECRET: secret,
        SEED_ON_STARTUP: 'true', CORS_ORIGINS: 'http://127.0.0.1:5173',
        ADMIN_INITIAL_PASSWORD: process.env.E2E_ADMIN_INITIAL_PASSWORD ?? 'E2eInitialAdmin123!',
        DEMO_INITIAL_PASSWORD: process.env.E2E_DEMO_PASSWORD ?? 'LocalDemo123!',
      },
    },
    {
      command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: false,
      timeout: 120000,
      env: { DEV_API_PROXY: 'http://127.0.0.1:8000', VITE_API_BASE: '/api' },
    },
  ],
});
