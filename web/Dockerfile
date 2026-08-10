# =============================================================================
# zeroAgent 员工端 Web (web/) - Dockerfile
# Multi-stage build: builder → runtime
# @author 赵振明
# @date 2026-08-05 14:30:00
#
# 宿主机映射: 3000:3000（内部 Next.js 端口 3000 → 宿主机 3000）
# API 代理目标: 通过 NEXT_PUBLIC_API_PROXY_TARGET 环境变量注入（compose 内为 http://api:8000）
# 构建上下文: 项目根目录（..）→ 通过 web/ 子路径拷贝文件
# =============================================================================

# ========== 构建阶段 ==========
FROM node:18-alpine AS builder

WORKDIR /app

# 拷贝 web/ 子目录的依赖描述文件（构建上下文为项目根目录，需指定 web/ 前缀）
COPY web/package*.json ./
RUN npm ci --prefer-offline

# 拷贝 web/ 源代码
COPY web/ .

# 设置构建时环境变量（生产环境通过 compose 覆盖）
# API_PROXY_TARGET：next.config.ts 中 rewrites 运行时读取，Docker 容器内必须用 compose 服务名 api:8000
ENV API_PROXY_TARGET=http://api:8000
ENV NEXT_PUBLIC_API_PROXY_TARGET=http://api:8000

# 减少构建期内存峰值（默认无上限 → OOM kill on Windows hosts with <6GB headroom）
ENV NODE_OPTIONS=--max-old-space-size=3072
ENV NEXT_TELEMETRY_DISABLED=1

# 执行 Next.js 构建（生成 .next 产物）
RUN npm run build

# ========== 生产运行阶段 ==========
FROM node:18-alpine

WORKDIR /app

# 仅安装生产依赖，减小镜像体积
COPY web/package*.json ./
RUN npm ci --omit=dev --no-audit --no-fund

# 从 builder 阶段拷贝构建产物
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package.json ./package.json

# 暴露 Next.js 生产端口（宿主机 3000 → 容器 3000）
EXPOSE 3000

# 启动 Next.js 生产服务器（自动监听 3000 端口）
CMD ["npm", "run", "start"]
