# ── Stage 1: Build React app ────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

# Build-time env vars (injected by GitHub Actions / Azure)
ARG VITE_API_URL
ARG VITE_WS_URL
ARG VITE_LIVEKIT_URL

ENV VITE_API_URL=${VITE_API_URL}
ENV VITE_WS_URL=${VITE_WS_URL}
ENV VITE_LIVEKIT_URL=${VITE_LIVEKIT_URL}

RUN npm run build

# ── Stage 2: Serve with Nginx ───────────────────
FROM nginx:1.25-alpine

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
