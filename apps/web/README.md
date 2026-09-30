# FaceLens web

Next.js 16 (App Router), TypeScript, Tailwind CSS v4, and shadcn/ui (Radix). This is the user-facing app for the three FaceLens tools.

## Run locally

```bash
# 1. API (see apps/api/README.md): http://127.0.0.1:8000
# 2. Web:
cd apps/web
npm ci
npm run dev            # http://localhost:3000; /v1/* is rewritten to the API
```

`API_ORIGIN` (default `http://127.0.0.1:8000`) sets where `/v1/*` is proxied. Rewrites are fixed **at build time**, so set it before `next build`.

## Checks

| Command | What it runs |
|---|---|
| `npm run typecheck` | `tsc --noEmit` |
| `npm run lint` | ESLint with the React Compiler rules, zero warnings allowed |
| `npm test` | Vitest: unit and component tests, plus a flow test against a fake API |
| `npm run test:e2e` | Playwright: a real API (YuNet face detection) and a production standalone build, desktop and mobile. Uses axe-core (WCAG 2.2 AA) and fails on any CSP violation. Needs the API venv and `facelens-api fetch-models`. |
| `npm run gen:api` | Regenerates `src/lib/api/schema.d.ts` from `apps/api/openapi.json` (never hand-edit it) |

## Design decisions

- **Same-origin API at `/v1`.** In production the load balancer sends `/v1/*` straight to FastAPI, so rate limits see real client IPs and uploads never pass through Node. The Next rewrite does the same routing in development.
- **Strict CSP.** `src/proxy.ts` issues a per-request nonce with `strict-dynamic` and `connect-src 'self'`. Every page renders dynamically so the nonce can be applied. Radix's runtime `<style>` gets the nonce via `get-nonce` (`components/site/style-nonce.tsx`).
- **Photos never touch `next/image`.** It would cache user photos on the server. Previews are local `blob:` URLs, and results use short-lived signed links.
- **Client-side re-encoding.** The chosen photo is decoded, framed, downscaled to ≤ 2048 px, and re-encoded on the device. EXIF/GPS data and the original filename never leave the browser. The API sanitizes again anyway.
- **Mocks are always visible.** The `is_mock` flag from the API drives a banner and a badge on every result.

## Troubleshooting

If Vitest or the build fails with `Cannot find native binding` (rolldown), npm dropped optional platform packages from the lockfile (npm/cli#4828). Regenerate it with `rm -rf node_modules package-lock.json && npm install`, and commit the new lockfile.
