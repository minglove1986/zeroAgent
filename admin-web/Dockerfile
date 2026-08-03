# zeroAgent Admin Web (管理端) - Dockerfile
# Multi-stage build: builder → runtime
# @author 赵振明
# @date 2026-07-29

# ========== 构建阶段 ==========
FROM node:18-alpine AS builder

WORKDIR /app

# 安装所有依赖（包括 devDependencies）
COPY package*.json ./
RUN npm ci --prefer-offline

# 拷贝源代码
COPY . .

# 设置构建时环境变量（生产环境用后端容器名）
ENV NEXT_PUBLIC_API_PROXY_TARGET=http://backend_api:8000

# 执行 Next.js 静态站点生成 / 构建
RUN npm run build

# ========== 生产运行阶段 ==========
FROM node:18-alpine

WORKDIR /app

# 仅安装生产依赖
COPY package*.json ./
RUN npm ci --production --no-audit --no-fund

# 从 builder 阶段拷贝构建产物（.next/ 和 public/）
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package.json ./package.json

# 暴露 Next.js 生产端口（与 docker-compose 中的 3001 映射对应）
EXPOSE 3000

# 启动 Next.js 生产服务器
CMD ["npm", "run", "start"]