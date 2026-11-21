# Multi-stage production Dockerfile for NEXUS Frontend

# --- Stage 1: Build Stage ---
FROM node:20-alpine AS builder

WORKDIR /app

# Enable corepack for pnpm support
RUN corepack enable && corepack prepare pnpm@latest --activate

# Copy package definitions and lockfiles
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml* ./

# Install dependencies using frozen lockfile
RUN pnpm install --frozen-lockfile

# Copy configuration and source files
COPY index.html vite.config.ts tsconfig.json tailwind.config.js postcss.config.js ./
COPY src/ ./src/

# Compile TypeScript and bundle with Vite
RUN pnpm run build

# --- Stage 2: Production Nginx Runtime ---
FROM nginx:1.25-alpine AS runner

# Purge default static files
RUN rm -rf /usr/share/nginx/html/*

# Copy production bundle from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy custom Nginx configuration supporting SPA routing, API & WS proxying
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose HTTP web server port
EXPOSE 80

# Health check probe
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/health > /dev/null || exit 1

CMD ["nginx", "-g", "daemon off;"]
