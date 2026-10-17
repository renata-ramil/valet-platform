# Production build of the resident/valet/manager PWA, served as static
# files behind the edge reverse proxy (see deploy/Caddyfile). Build with
# the repo root as context: `docker build -f frontend/Dockerfile .`
FROM node:20-slim AS builder

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

FROM caddy:2-alpine
COPY --from=builder /app/dist /srv
CMD ["caddy", "file-server", "--root", "/srv", "--listen", ":80"]
