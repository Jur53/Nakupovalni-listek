# Pametna košarica frontend

Next.js 16 frontend for selecting grocery quantities, comparing store totals, splitting a purchase, and saving authenticated shopping lists.

## Local development

Requires Node.js 22.22.2, Node.js 24.15 or newer in the 24.x line, or Node.js
26 or newer, plus npm 11.19.0.

```bash
npm ci
npm run dev
```

The browser only calls same-origin paths under `/api/backend/*`. Explicit Next.js
route handlers proxy the supported public API calls and keep access tokens in an
`httpOnly`, same-site cookie for authenticated calls. Unknown backend paths are
not proxied.

Set the server-only `BACKEND_URL` to the backend origin. Development defaults to
`http://127.0.0.1:8000`; production requires an explicit HTTPS URL, except for a
loopback backend on the same host. It must not contain credentials, a path,
query parameters, or a fragment.

```bash
BACKEND_URL=http://127.0.0.1:8000 npm run dev
```

## Verification

```bash
npm run lint
npm run typecheck
npm test
npm run build
```
