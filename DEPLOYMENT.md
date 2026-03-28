# 部署到 Google Cloud Run

## 前置条件

1. Google Cloud 账号（有免费额度）
2. 安装 Google Cloud CLI: https://cloud.google.com/sdk/docs/install
3. 代码上传到 GitHub

## 部署步骤

### 1. 初始化 Google Cloud

```bash
gcloud init
gcloud config set project YOUR_PROJECT_ID
```

### 2. 启用必要的 APIs

```bash
gcloud services enable run.googleapis.com
gcloud services enable cloudbuild.googleapis.com
```

### 3. 推送代码到 GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/news-aggregator.git
git push -u origin main
```

### 4. 部署到 Cloud Run

**方法A：使用 gcloud CLI（推荐）**

```bash
gcloud run deploy news-aggregator \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated
```

**方法B：通过 Google Cloud Console**

1. 打开 https://console.cloud.google.com
2. 选择 Cloud Run
3. 点击 "创建服务"
4. 选择 "从源代码连续部署"
5. 连接你的 GitHub 仓库
6. 选择分支为 `main`
7. Build 类型选 "Dockerfile"
8. 点击部署

### 5. 获取公网 URL

部署完成后，Google Cloud 会提供一个 URL，形如：
```
https://news-aggregator-xxxxx-uc.a.run.app
```

在不同设备上访问这个 URL 就可以看到你的新闻聚合页面。

## 更新代码

推送到 GitHub 后，Cloud Run 会自动重新部署：

```bash
git add .
git commit -m "Update news aggregator"
git push origin main
```

## 成本

- 每月 **100 万次请求免费**
- 每月 **36 万 GB-秒免费**
- 一般个人使用完全免费，不会产生费用

## 故障排查

查看部署日志：
```bash
gcloud run logs read news-aggregator --limit 50
```

查看完整详情：
```bash
gcloud run services describe news-aggregator --region us-central1
```
