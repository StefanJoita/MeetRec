# ── Stage 1: Build ───────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files first — cached layer if deps unchanged
COPY package.json package-lock.json* ./
RUN npm install

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
