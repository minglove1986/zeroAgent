# zeroAgent K8s 部署清单

> 版本 v0.2 | 2026-07-20

---

## 文档版本

| 版本 | 日期 | 主要变更 |
|---|---|---|
| v0.1 | 2026-07-20 | 初版 K8s 部署清单 |
| v0.2 | 2026-07-20 | 同步技术栈变更（Neo4j/移除 Temporal/Langfuse 自托管） |

---

## 一、命名空间规划

```bash
# 创建命名空间
kubectl create namespace zeroagent-prod
kubectl create namespace zeroagent-staging
kubectl create namespace zeroagent-dev
kubectl create namespace zeroagent-monitor
kubectl create namespace zeroagent-infra
```

---

## 二、配置文件

### 2.1 ConfigMap

```yaml
# deploy/k8s/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: zeroagent-config
  namespace: zeroagent-prod
data:
  config.yaml: |
    app:
      name: zeroagent
      version: 1.0.0
      debug: false
    
    database:
      mysql:
        master_url: "mysql+aiomysql://zeroagent:pass@mysql-master.zeroagent-infra:3306/zeroagent"
        slave_url: "mysql+aiomysql://zeroagent:pass@mysql-slave.zeroagent-infra:3306/zeroagent"
        pool_size: 20
        max_overflow: 40
      
      redis:
        url: "redis://redis.zeroagent-infra:6379/0"
        max_connections: 50
    
    llm:
      providers:
        - name: agnes
          base_url: "https://apihub.agnes-ai.com/v1"
          api_key: "${AGNES_API_KEY}"
          models: ["agnes-2.0-flash"]
        - name: minimax
          base_url: "https://api.minimax.chat/v1"
          api_key: "${MINIMAX_API_KEY}"
          models: ["MiniMax-M3"]
      fallback:
        max_retries: 3
        timeout: 30
    
    milvus:
      host: "milvus.zeroagent-infra"
      port: 19530
    
    nebula:
      addresses:
        - "nebula-graphd.zeroagent-infra:9669"
    
    oss:
      endpoint: "oss-cn-hangzhou.aliyuncs.com"
      bucket: "zeroagent-prod"
      access_key: "${OSS_ACCESS_KEY}"
      secret_key: "${OSS_SECRET_KEY}"
    
    rabbitmq:
      url: "amqp://zeroagent:pass@rabbitmq.zeroagent-infra:5672/"
    
    langfuse:
      enabled: true
      public_key: "${LANGFUSE_PUBLIC_KEY}"
      secret_key: "${LANGFUSE_SECRET_KEY}"
      host: "http://langfuse.zeroagent-obs:3000"  # 仅自托管，禁止 Cloud
```

### 2.2 Secret

```yaml
# deploy/k8s/secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: zeroagent-secrets
  namespace: zeroagent-prod
type: Opaque
stringData:
  AGNES_API_KEY: "sk-xxxxxxxx"
  MINIMAX_API_KEY: "sk-xxxxxxxx"
  OSS_ACCESS_KEY: "LTAIxxxxxxxx"
  OSS_SECRET_KEY: "xxxxxxxx"
  MYSQL_PASSWORD: "xxxxxxxx"
  REDIS_PASSWORD: "xxxxxxxx"
  LANGFUSE_PUBLIC_KEY: "pk-xxxxxxxx"
  LANGFUSE_SECRET_KEY: "sk-xxxxxxxx"
```

---

## 三、FastAPI 主服务

### 3.1 Deployment

```yaml
# deploy/k8s/api-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: zeroagent-api
  namespace: zeroagent-prod
  labels:
    app: zeroagent-api
spec:
  replicas: 5
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 2
      maxUnavailable: 1
  selector:
    matchLabels:
      app: zeroagent-api
  template:
    metadata:
      labels:
        app: zeroagent-api
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
        prometheus.io/path: "/metrics"
    spec:
      containers:
      - name: api
        image: registry.zeroagent.local/zeroagent-api:v1.0.0
        imagePullPolicy: IfNotPresent
        ports:
        - containerPort: 8000
          name: http
        env:
        - name: ENV
          value: "production"
        - name: WORKERS
          value: "4"
        envFrom:
        - configMapRef:
            name: zeroagent-config
        - secretRef:
            name: zeroagent-secrets
        resources:
          requests:
            cpu: "500m"
            memory: "1Gi"
          limits:
            cpu: "2000m"
            memory: "4Gi"
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5
          failureThreshold: 3
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
          failureThreshold: 3
        startupProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 0
          periodSeconds: 5
          failureThreshold: 30
        volumeMounts:
        - name: config
          mountPath: /app/config
          readOnly: true
      volumes:
      - name: config
        configMap:
          name: zeroagent-config
      imagePullSecrets:
      - name: registry-zeroagent
---
apiVersion: v1
kind: Service
metadata:
  name: zeroagent-api-svc
  namespace: zeroagent-prod
spec:
  selector:
    app: zeroagent-api
  ports:
  - port: 80
    targetPort: 8000
    name: http
  type: ClusterIP
```

### 3.2 HPA 自动扩缩容

```yaml
# deploy/k8s/api-hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: zeroagent-api-hpa
  namespace: zeroagent-prod
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: zeroagent-api
  minReplicas: 3
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
    scaleUp:
      stabilizationWindowSeconds: 30
```

---

## 四、Celery Worker

```yaml
# deploy/k8s/worker-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: zeroagent-worker
  namespace: zeroagent-prod
spec:
  replicas: 3
  selector:
    matchLabels:
      app: zeroagent-worker
  template:
    metadata:
      labels:
        app: zeroagent-worker
    spec:
      containers:
      - name: worker
        image: registry.zeroagent.local/zeroagent-api:v1.0.0
        command: ["celery", "-A", "app.workers.celery_app", "worker", "--loglevel=info", "--concurrency=4"]
        envFrom:
        - configMapRef:
            name: zeroagent-config
        - secretRef:
            name: zeroagent-secrets
        resources:
          requests:
            cpu: "1000m"
            memory: "2Gi"
          limits:
            cpu: "4000m"
            memory: "8Gi"
```

---

## 五、Ingress 网关

```yaml
# deploy/k8s/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: zeroagent-ingress
  namespace: zeroagent-prod
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "50m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "300"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "300"
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/rate-limit: "100"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - api.zeroagent.local
    secretName: zeroagent-tls
  rules:
  - host: api.zeroagent.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: zeroagent-api-svc
            port:
              number: 80
```

---

## 六、ServiceAccount & RBAC

```yaml
# deploy/k8s/serviceaccount.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: zeroagent-api
  namespace: zeroagent-prod
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: zeroagent-api-role
  namespace: zeroagent-prod
rules:
- apiGroups: [""]
  resources: ["configmaps", "secrets"]
  verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: zeroagent-api-rolebinding
  namespace: zeroagent-prod
subjects:
- kind: ServiceAccount
  name: zeroagent-api
  namespace: zeroagent-prod
roleRef:
  kind: Role
  name: zeroagent-api-role
  apiGroup: rbac.authorization.k8s.io
```

---

## 七、镜像拉取凭证

```yaml
# deploy/k8s/registry-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: registry-zeroagent
  namespace: zeroagent-prod
type: kubernetes.io/dockerconfigjson
stringData:
  .dockerconfigjson: |
    {
      "auths": {
        "registry.zeroagent.local": {
          "username": "deployer",
          "password": "xxxxxxxx",
          "email": "devops@zeroagent.local"
        }
      }
    }
```

---

## 八、部署顺序

### 8.1 一次性部署

```bash
# 1. 创建命名空间
kubectl apply -f deploy/k8s/namespaces.yaml

# 2. 创建配置和密钥
kubectl apply -f deploy/k8s/configmap.yaml
kubectl apply -f deploy/k8s/secret.yaml
kubectl apply -f deploy/k8s/registry-secret.yaml

# 3. 部署中间件（首次或新环境）
# MySQL / Redis / RabbitMQ / Milvus / Neo4j
# 通过 Helm 或 Operator 部署

# 4. 部署应用
kubectl apply -f deploy/k8s/serviceaccount.yaml
kubectl apply -f deploy/k8s/api-deployment.yaml
kubectl apply -f deploy/k8s/api-hpa.yaml
kubectl apply -f deploy/k8s/worker-deployment.yaml

# 5. 部署网关
kubectl apply -f deploy/k8s/ingress.yaml

# 6. 验证
kubectl get pods -n zeroagent-prod
kubectl get svc -n zeroagent-prod
kubectl get ingress -n zeroagent-prod
```

### 8.2 滚动升级

```bash
# 更新镜像
kubectl set image deployment/zeroagent-api api=registry.zeroagent.local/zeroagent-api:v1.0.1 -n zeroagent-prod

# 查看升级状态
kubectl rollout status deployment/zeroagent-api -n zeroagent-prod

# 回滚
kubectl rollout undo deployment/zeroagent-api -n zeroagent-prod
```

---

## 九、监控集成

### 9.1 Prometheus ServiceMonitor

```yaml
# deploy/k8s/servicemonitor.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: zeroagent-api
  namespace: zeroagent-prod
  labels:
    app: zeroagent-api
spec:
  selector:
    matchLabels:
      app: zeroagent-api
  endpoints:
  - port: http
    path: /metrics
    interval: 15s
```

### 9.2 告警规则

```yaml
# deploy/k8s/prometheusrule.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: zeroagent-alerts
  namespace: zeroagent-prod
spec:
  groups:
  - name: zeroagent
    rules:
    - alert: HighErrorRate
      expr: |
        sum(rate(http_requests_total{status=~"5.."}[5m])) by (service)
        / sum(rate(http_requests_total[5m])) by (service) > 0.05
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "错误率超过 5%"
    
    - alert: HighLatency
      expr: |
        histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, service))
        > 5
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "P99 延迟超过 5s"
    
    - alert: HighCost
      expr: llm_token_cost_hourly_total > 100
      for: 30m
      labels:
        severity: warning
      annotations:
        summary: "每小时 LLM 成本超过 ¥100"
```

---

## 十、灾难恢复清单

| 故障 | 恢复步骤 |
|---|---|
| 单 Pod 崩溃 | K8s 自动重启，无需干预 |
| 节点故障 | K8s 调度到其他节点，约 1-3 分钟 |
| Deployment 升级失败 | `kubectl rollout undo` 回滚 |
| 配置错误 | 修改 ConfigMap 后 `kubectl rollout restart` |
| 数据库故障 | 切到从库，重启应用 |
| 区域故障 | 跨区域灾备切换（DR 站点） |