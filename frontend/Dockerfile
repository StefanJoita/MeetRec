# ── Stage 1: Build ───────────────────────────────────────────
# node 22: jsdom/vitest cer node ^20.19 || ^22.13
FROM node:22-alpine AS builder

WORKDIR /app

# Copy package files first — cached layer if deps unchanged
# npm ci = instalare EXACTĂ din package-lock.json (build reproductibil)
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# Copy all source files
COPY . .

# Compile TypeScript + bundle with Vite → /app/dist
RUN npm run build

# ── Stage 2: Serve static files ──────────────────────────────
FROM nginx:1.25-alpine

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# SPA nginx config (serves index.html for any unknown path)
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy the built React app
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
