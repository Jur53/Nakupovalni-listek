# Backend

## Setup

From the repository root:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
cp backend/.env.example backend/.env
.venv/bin/python -m alembic -c backend/alembic.ini upgrade head
.venv/bin/python -m backend.seed
.venv/bin/uvicorn backend.main:app --reload
```

Use Python 3.13 and the pinned requirements files for reproducible installs.
`JWT_SECRET` is mandatory in every environment, must contain at least 32
characters, and cannot be a known placeholder. After copying `.env.example`,
generate a local value with `openssl rand -hex 32`. Production must use a
different high-entropy secret from the deployment secret manager.
`CORS_ORIGINS` is a JSON array. No tables are created and no scraping runs
during application startup.

In production, inject `APP_ENV=production`, `DATABASE_URL`, `JWT_SECRET`, and
`CORS_ORIGINS` from a secret/configuration manager; do not commit or print their
values. Use a least-privileged PostgreSQL role and require encrypted database
connections where the database is not on the same trusted host. The frontend's
server-only `BACKEND_URL` must be the backend HTTPS origin without credentials,
a path, query parameters, or a fragment. Keep it out of browser/public
environment variables.

Authentication endpoints do not replace edge abuse controls. Rate-limit
`/auth/login` and `/auth/register` at the reverse proxy or WAF using short burst
and longer sustained limits, return `429` when exceeded, and derive client IPs
only from forwarded headers supplied by trusted proxies.
The backend also applies configurable bounded per-process limits using
`AUTH_RATE_LIMIT_WINDOW_SECONDS`, `LOGIN_RATE_LIMIT`, `REGISTER_RATE_LIMIT`, and
`AUTH_RATE_LIMIT_MAX_KEYS`; these limits are not shared across workers.

## Migrations

For a fresh database, run
`.venv/bin/python -m alembic -c backend/alembic.ini upgrade head`, followed by
`.venv/bin/python -m alembic -c backend/alembic.ini check` to detect model and
migration drift.

For a database already created from the original `schema.sql`, back it up, then mark the matching baseline before upgrading:

```bash
.venv/bin/python -m alembic -c backend/alembic.ini stamp 0001_original
.venv/bin/python -m alembic -c backend/alembic.ini upgrade head
```

Migration `0002_reliability` preserves anonymous lists by assigning them to the disabled, non-login legacy user. It normalizes invalid quantities and merges duplicate list/product rows before adding constraints. Alembic is authoritative; `schema.sql` is retired.

For a production release:

1. Create an encrypted PostgreSQL snapshot or custom-format `pg_dump`, retain
   it according to the recovery policy, and restore it into an isolated
   database to verify it.
2. Stop schema-writing jobs and run `alembic upgrade head` once as a dedicated
   pre-deploy job. Do not run migrations concurrently in every application
   process.
3. Deploy the application only after migration succeeds. Keep instances out of
   service until `/ready` succeeds; `/health` is liveness only.
4. Run `.venv/bin/python -m backend.apply_catalog_taxonomy` once to synchronize
   the checked-in taxonomy and backfill existing canonical products.
5. Resume catalog imports after the new release is ready and monitor migration,
   readiness, taxonomy coverage, and application logs.

Prefer rolling back application code when the old version is compatible with
the new schema. Test every planned Alembic downgrade before relying on it;
`0004_merge_spar_store` intentionally cannot reconstruct merged store ownership.
For an incompatible or destructive migration, stop writers and restore the
verified backup using the documented disaster-recovery procedure.

## API contract

- `POST /auth/register`: `{"email":"a@example.com","password":"at-least-12-chars"}` returns `201` with `{"access_token":"...","token_type":"bearer"}`.
- `POST /auth/login`: the same JSON shape returns a bearer token.
- `GET /auth/me`: requires `Authorization: Bearer TOKEN`.
- `GET /trgovine` and `GET /cene`: public, ordered, with `offset` and `limit` (`limit <= 100`). `/cene` returns only the latest dated price for each product/store.
- `GET /categories`: visible top-level shopper taxonomy with recursive `children` and descendant-inclusive `product_count`. Repeated optional `trgovina_ids` limits counts to active products offered by those stores.
- `GET /izdelki`: paginated catalog search. It accepts `q`, legacy `kategorija`, taxonomy `kategorija_id`, repeated optional `trgovina_ids`, `offset`, and `limit`. Selecting a taxonomy parent includes every descendant. Each canonical product is returned once with `kategorija_id`, its top-to-leaf `kategorija_pot`, its retained legacy `kategorija`, its cheapest active offer in `najcenejsa_ponudba`, and every selected store's current offer in price order in `ponudbe`. The response retains the old flat `categories` list and also includes `category_tree`. Omitting `trgovina_ids` checks all stores.
- `GET /health` and `GET /ready`: liveness and database-readiness probes.
- `POST /primerjava`: `{"items":[{"izdelek_id":1,"kolicina":2}],"trgovina_ids":[1,2]}`. Product and store IDs must be unique and quantities positive. `trgovina_ids` may be omitted to check all stores. Complete-store totals and the cheapest per-product split use only selected stores. If none covers the full basket, the API returns `celoten_nakup_na_voljo: false` with nullable one-store fields and still provides the cheapest per-product split.
- `POST /seznami`: authenticated atomic create with `{"ime":"Weekly","items":[{"izdelek_id":1,"kolicina":2}]}`.
- `GET /seznami`, `GET /seznami/{id}`, `POST /seznami/{id}/izdelki`: authenticated and owner-scoped. Duplicate list items return `409`.

Unknown product or store IDs return `404`. A comparison returns `422` only when a requested product has no current offer in any selected store. Monetary response values are fixed-point JSON strings (for example, `"3.30"`), never binary floats. Ties are stable by database ID.

## Catalog import

Run a complete one-shot import after applying migrations:

```bash
.venv/bin/python -m backend.import_catalog --retailer all
.venv/bin/python -m backend.import_catalog --retailer mercator
.venv/bin/python -m backend.import_catalog --retailer spar
.venv/bin/python -m backend.import_catalog --retailer lidl
.venv/bin/python -m backend.import_catalog --retailer hofer
.venv/bin/python -m backend.import_catalog --retailer tus
```

The command discovers and crawls the anonymous grocery catalogs for Mercator, SPAR, Lidl, Hofer, and Tuš. Tuš is store-specific, so imports use reference store `5861` (Planet Tuš Celje); the adapter accepts explicit `store_ids` for future branch-aware integrations. Valid GTIN-8/12/13/14 values create or match canonical products. Invalid or absent GTINs stay in the source catalog and are never matched by name. Hofer's public catalog does not expose GTINs, so Hofer products remain source-only until explicitly mapped. Anonymous public prices are projected into `cene`; loyalty-only and conditional multipack promotions remain in source history but are not used for one-unit comparisons.

Imports use PostgreSQL advisory locks, so overlapping jobs for the same retailer are skipped. Existing source products are marked inactive only after an adapter-declared complete crawl that retains at least 80% of the largest of the five most recent successful runs, or 80% of the existing active source catalog when no completed run exists yet. Only a genuinely empty new store skips the size gate. Failed or implausibly small crawls are recorded in `catalog_import_runs` and leave the previous active catalog unchanged. SPAR's public API key is read from its current storefront configuration instead of being stored locally.

Schedule this one-shot command outside FastAPI. Ensure the scheduler injects
the production environment securely rather than embedding secrets in the
crontab. For example, a daily cron entry from the repository root is:

```cron
17 2 * * * flock -n /run/lock/nakupovalni-listek-import.lock /srv/nakupovalni-listek/.venv/bin/python -m backend.import_catalog --retailer all >> /var/log/nakupovalni-listek-import.log 2>&1
```

Run the job under an account that can read the backend environment and connect to PostgreSQL. Monitor its exit code and `catalog_import_runs`. Confirm retailer terms and permissions before commercial or high-volume use.

Rotate scheduler output so failures cannot fill the disk. For example, install
the following as `/etc/logrotate.d/nakupovalni-listek`, replacing the service
account and group with the deployment's actual non-root account:

```text
/var/log/nakupovalni-listek-import.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 appuser appgroup
}
```

To add another store, implement the `CatalogAdapter` protocol from `backend.catalog_import`, return normalized `CatalogProduct` values, and register its factory in `backend.import_catalog.ADAPTERS`. GTIN matching, history, locking, run tracking, inactive-state handling, and canonical price projection are shared.

### Curated product mappings

Exact GTINs remain the automatic and preferred way to combine retailer products.
For products whose GTIN is missing, changed, or inconsistent, edit
`backend/product_mappings.json`. Each entry defines the shared display name,
category, unit, and retailer members that should be treated as one product.
Members use a retailer name plus exactly one stable selector:
`external_id`, exact `source_name`, or `gtin`. Prefer `external_id` because
retailers can rename products.

```json
{
  "key": "example-milk-1l",
  "name": "Example milk 1 l",
  "category": "Milk",
  "unit": "1 l",
  "members": [
    {"retailer": "Mercator", "external_id": "12345"},
    {"retailer": "SPAR", "external_id": "67890"}
  ]
}
```

Mappings are applied transactionally during every catalog import. To apply a
new mapping immediately to data already in the database, run:

```bash
.venv/bin/python -m backend.apply_product_mappings
```

When separate canonical products are merged, their retailer links, GTINs,
price history, and saved-list items are moved to the selected canonical product;
duplicate dated prices keep the lower observed value and duplicate list
quantities are added together. Back up production data before applying a large
mapping change.

### Shopper taxonomy

`backend/catalog_taxonomy.json` is the authoritative, versioned taxonomy and
ordered classification rule set. It contains 15 visible grocery/essentials
roots plus a hidden review branch for clothing, tools, garden, seasonal, and
other out-of-scope merchandise. Promotions, dietary attributes, brands, and
package sizes are intentionally not categories. Slugs are stable API keys;
renaming a display label does not change category identity.

After migration `0005_catalog_taxonomy`, synchronize definitions and classify
the existing catalog transactionally with:

```bash
.venv/bin/python -m backend.apply_catalog_taxonomy
```

The command is idempotent and prints classified, visible, hidden, and
unclassified coverage plus non-empty category counts. Classification preserves
both `izdelki.kategorija` and `retailer_products.kategorija`: it first considers
the curated/legacy canonical category, then active retailer category paths, and
finally ordered product-name keywords. Matching is Unicode/case normalized and
does not merge canonical product identities.

Each successful catalog import upserts the small definition set before
classification, but classifies only canonical IDs encountered by that import;
it does not rescan the full catalog. Once category definitions exist, the public
shopper catalog exposes only products assigned to visible categories. Databases
without synchronized definitions retain the legacy visibility fallback, which
also keeps isolated `create_all` test fixtures practical. No taxonomy sync or
backfill runs during FastAPI startup.

The older `python -m backend.scraper_mercator CATEGORY_ID` command remains available for targeted diagnostics; production refreshes should use `backend.import_catalog`.

Run tests from the repository root with
`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest backend/tests -p no:cacheprovider`. These tests use fast in-memory
SQLite; CI separately applies migrations and exercises readiness against
PostgreSQL.
