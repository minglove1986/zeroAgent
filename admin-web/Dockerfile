# zeroAgent Admin Web (管理端) - Dockerfile
# Multi-stage build: builder → runtime
# @author 赵振明
# @date 2026-07-29
#
# 构建上下文: 项目根目录（..）→ 通过 admin-web/ 子路径拷贝文件
# 宿主机映射: 3001:3000（内部 Next.js 端口 3000 → 宿主机 3001）

# ========== 构建阶段 ==========
FROM node:18-alpine AS builder

WORKDIR /app

# 拷贝 admin-web/ 子目录的依赖描述文件（构建上下文为项目根目录，需指定 admin-web/ 前缀）
COPY admin-web/package*.json ./
RUN npm ci --prefer-offline

# 拷贝 admin-web/ 源代码
COPY admin-web/ .

# 设置构建时环境变量（生产环境通过 compose 覆盖）
# API_PROXY_TARGET：next.config.ts 中 rewrites 运行时读取，Docker 容器内必须用 compose 服务名 api:8000
ENV API_PROXY_TARGET=http://api:8000
ENV NEXT_PUBLIC_API_PROXY_TARGET=http://api:8000

# 执行 Next.js 静态站点生成 / 构建
RUN npm run build

# ========== 生产运行阶段 ==========
FROM node:18-alpine

WORKDIR /app

# 仅安装生产依赖，减小镜像体积
COPY admin-web/package*.json ./
RUN npm ci --omit=dev --no-audit --no-fund

# 从 builder 阶段拷贝构建产物（.next/ 和 public/）
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package.json ./package.json

# 暴露 Next.js 生产端口（与 docker-compose 中的 3001 映射对应）
EXPOSE 3000

# 启动 Next.js 生产服务器
CMD ["npm", "run", "start"]