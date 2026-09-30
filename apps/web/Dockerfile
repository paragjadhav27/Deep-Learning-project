# syntax=docker/dockerfile:1.7
# Production web image: Next.js standalone server (same one the e2e suite runs).
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Rewrites are resolved at build time: where /v1/* goes when the web server receives it.
# In production the load balancer should route /v1/* to the API before it reaches Next.
ARG API_ORIGIN=http://api:8000
ENV API_ORIGIN=${API_ORIGIN}
RUN npx next build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S app && adduser -S app -G app
COPY --from=build --chown=app:app /app/.next/standalone ./
COPY --from=build --chown=app:app /app/.next/static ./.next/static
COPY --from=build --chown=app:app /app/public ./public
USER app
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:3000/privacy >/dev/null || exit 1
CMD ["node", "server.js"]
