# Build context: this frontend directory, not the repository root.
# Example shape: docker build -f Dockerfile --build-arg APP_ENV=production .
# Supply the public build args below for each environment. Never pass backend secrets.
# NEXT_PUBLIC_* is baked into the bundle: runtime env changes cannot retarget it.
# APP_ENV must remain identical at build/start; do not override it on Cloud Run.
ARG APP_ENV=production

FROM node:22-bookworm-slim AS dependencies
WORKDIR /app/frontend
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci

FROM dependencies AS build
ARG APP_ENV
ARG NEXT_PUBLIC_ADMIN_API_BASE_URL
ARG NEXT_PUBLIC_ADMIN_SERVICE_ID
ARG NEXT_PUBLIC_GOOGLE_CLIENT_ID
ENV APP_ENV=${APP_ENV} \
    NEXT_PUBLIC_ADMIN_API_BASE_URL=${NEXT_PUBLIC_ADMIN_API_BASE_URL} \
    NEXT_PUBLIC_ADMIN_SERVICE_ID=${NEXT_PUBLIC_ADMIN_SERVICE_ID} \
    NEXT_PUBLIC_GOOGLE_CLIENT_ID=${NEXT_PUBLIC_GOOGLE_CLIENT_ID}
# .dockerignore admits only build inputs and excludes actual dotenv/credentials.
COPY . .
# The canonical target owns public assets; currently no public directory exists.
RUN mkdir -p targets/admin/public && npm run build \
    && rm -rf targets/admin/.next-admin/cache

FROM dependencies AS production-dependencies
RUN npm prune --omit=dev && npm cache clean --force

FROM node:22-bookworm-slim AS runtime
WORKDIR /app/frontend
ARG APP_ENV
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    APP_ENV=${APP_ENV} \
    PORT=8080
COPY --from=production-dependencies --chown=node:node /app/frontend/node_modules ./node_modules
COPY --from=build --chown=node:node /app/frontend/package.json ./package.json
COPY --from=build --chown=node:node /app/frontend/config/load-target-env.js ./config/load-target-env.js
COPY --from=build --chown=node:node /app/frontend/targets/admin/next.config.js ./targets/admin/next.config.js
COPY --from=build --chown=node:node /app/frontend/targets/admin/public ./targets/admin/public
COPY --from=build --chown=node:node /app/frontend/targets/admin/.next-admin ./targets/admin/.next-admin
USER node
EXPOSE 8080
# Existing next start target contract; Cloud Run supplies PORT.
# TCP startup needs no new health route. Configure HTTP probes separately;
# Admin /auth-required is public, while its production root redirects.
CMD ["sh", "-c", "exec npm start -- -H 0.0.0.0 -p \"${PORT:-8080}\""]
