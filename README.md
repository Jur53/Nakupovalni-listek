# Pametna kosarica

Full-stack grocery price comparison application with quantity-aware baskets,
authenticated shopping lists, daily Mercator, SPAR, Lidl, Hofer, and Tuš
catalog imports, exact GTIN canonicalization, and retailer price history.

## Stack

- FastAPI, SQLAlchemy, Alembic, PostgreSQL (SQLite is supported for local tests)
- Next.js 16, React 19, TypeScript, Tailwind CSS
- JWT bearer authentication behind an HTTP-only same-site frontend cookie

## Local setup

Prerequisites are Python 3.13, npm 11.19.0, PostgreSQL, and a Node.js release
supported by the locked frontend stack: Node 22 from 22.22.2, Node 24 from
24.15.0, or Node 26 and newer. The backend
dependencies and frontend lockfile are pinned; use the commands below from the
repository root rather than installing packages ad hoc.

Backend:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
cp backend/.env.example backend/.env
# Set JWT_SECRET in backend/.env, for example with: openssl rand -hex 32
.venv/bin/python -m alembic -c backend/alembic.ini upgrade head
.venv/bin/python -m backend.seed
.venv/bin/uvicorn backend.main:app --reload
```

Frontend, in another terminal:

```bash
npm install --global npm@11.19.0
npm --prefix frontend ci
BACKEND_URL=http://127.0.0.1:8000 npm --prefix frontend run dev
```

Open `http://localhost:3000`. The frontend proxies API traffic through its own
origin; bearer tokens are never stored in browser JavaScript storage.

For an existing database created with the retired `backend/schema.sql`, back it
up and follow the baseline migration instructions in `backend/README.md`.

Run the one-shot catalog refresh with
`.venv/bin/python -m backend.import_catalog --retailer all` and schedule it in
an external daily job runner. See `backend/README.md` for importer behavior,
monitoring, and the adapter contract for adding stores.

## Production security and releases

- Set `APP_ENV=production`. Supply `DATABASE_URL`, a unique high-entropy
  `JWT_SECRET` of at least 32 characters, and exact HTTPS `CORS_ORIGINS` through
  the deployment platform's secret/configuration store. Never commit a
  production environment file. Rotating `JWT_SECRET` invalidates existing
  sessions.
- Set the frontend's server-only `BACKEND_URL` to the backend's HTTPS origin.
  It must not contain credentials, a path, query parameters, or a fragment;
  do not expose it as a browser/public environment variable.
- Terminate TLS and rate-limit `/auth/login` and `/auth/register` at the edge
  proxy or WAF. Apply both burst and sustained limits, return `429` when
  exceeded, and only trust forwarded client addresses from known proxies.
- Back up PostgreSQL and verify a restore before each release that changes the
  schema. Apply `alembic upgrade head` as a single pre-deploy job, then deploy
  the backend and frontend, and only then admit traffic after `/ready` passes.
  Application startup does not run migrations.
- Roll back application versions only while they remain compatible with the
  migrated schema. For destructive or irreversible data changes, restore the
  verified database backup instead of assuming `alembic downgrade` can recover
  the prior state.

## Verification

```bash
.venv/bin/python -m pytest backend/tests
.venv/bin/python -m alembic -c backend/alembic.ini upgrade head
.venv/bin/python -m alembic -c backend/alembic.ini check
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend test
BACKEND_URL=http://127.0.0.1:8000 npm --prefix frontend run build
```

See `backend/README.md` for the API, migration, seed, and scraper contracts and
`frontend/README.md` for frontend environment details.
