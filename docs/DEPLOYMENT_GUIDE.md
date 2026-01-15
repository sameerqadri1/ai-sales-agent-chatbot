# 🚀 Production Deployment Guide - AI Sales Agent Chatbot

**Author:** Sameer Qadri (Sinc Solution Team)  
**Target Architecture:** Containerized Microservice / Cloud Platform (Render, Railway, AWS, DigitalOcean)

---

## 📑 Table of Contents

1. [Overview](#overview)
2. [Prerequisites & Hosting Requirements](#prerequisites--hosting-requirements)
3. [Environment Configuration Security](#environment-configuration-security)
4. [Redis Setup](#redis-setup)
5. [Deploying Backend API (Render / Railway / Docker)](#deploying-backend-api)
6. [WordPress Plugin & Frontend Deployment](#wordpress-plugin--frontend-deployment)
7. [Health Checks & Production Monitoring](#health-checks--production-monitoring)

---

## 🎯 Overview

This guide provides step-by-step instructions for deploying the **AI Sales Agent Chatbot** backend and frontend widget into a production environment.

The system consists of three primary deployment targets:
1. **Flask API Backend**: Handles catalog discovery, OpenAI LLM orchestration, and dynamic WooCommerce coupon creation.
2. **Redis Memory Store**: Provides persistent session state across conversation turns.
3. **Frontend Embed Widget / WordPress Plugin**: Embeds the conversational interface on your e-commerce storefront.

---

## 🔧 Prerequisites & Hosting Requirements

- **Python Runtime**: Python `3.9+`
- **Redis Server**: Managed Redis instance (Redis Cloud, Upstash, AWS ElastiCache)
- **SSL / TLS Certificate**: HTTPS mandatory for production API & CORS security
- **WooCommerce API Credentials**: Read/Write Consumer Key & Secret

---

## 🔒 Environment Configuration Security

Never commit production secret keys (`OPENAI_API_KEY`, `WC_CONSUMER_SECRET`) to Git. Use environment variables in your hosting provider configuration dashboard:

```env
# Production Environment Variables
OPENAI_API_KEY=sk-prod-your-openai-api-key
WC_API_URL=https://your-store-domain.com/wp-json/wc/v3
WC_CONSUMER_KEY=ck_prod_your_consumer_key
WC_CONSUMER_SECRET=cs_prod_your_consumer_secret
WC_BRAND_ATTRIBUTE_SLUG=pa_brand
ALLOWED_ORIGINS=https://your-store-domain.com,https://www.your-store-domain.com
COUPON_MIN_DISCOUNT=5
COUPON_MAX_DISCOUNT=10
COUPON_DEFAULT_DURATION_MINUTES=1440
REDIS_URL=rediss://:your-redis-password@your-redis-host:6379/0
SESSION_TIMEOUT_MINUTES=120
CONVERSATION_MEMORY_TURNS=15
```

---

## ⚡ Redis Setup

Redis provides state persistence across chat sessions.

### Option A: Redis Cloud / Upstash (Recommended)
1. Create a free or paid database instance at [Redis Cloud](https://redis.com/) or [Upstash](https://upstash.com/).
2. Copy the `rediss://` endpoint URL with password authentication.
3. Set `REDIS_URL` in your backend environment variables.

### Option B: Self-Hosted Docker Redis
```bash
docker run -d \
  --name ai-sales-redis \
  -p 6379:6379 \
  --restart always \
  redis:alpine redis-server --requirepass "your_secure_redis_password"
```

---

## ☁️ Deploying Backend API

### Deploying on Render

1. Connect your GitHub repository (`sameerqadri1/ai-sales-agent-chatbot`) to Render.
2. Create a new **Web Service**.
3. Configure settings:
   - **Environment**: `Python 3`
   - **Root Directory**: `backend`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app --workers 4 --bind 0.0.0.0:$PORT`
4. Add environment variables under the **Environment** tab.

---

## 🔌 WordPress Plugin & Frontend Deployment

1. Compress the `wordpress-plugin/` directory into a `.zip` archive.
2. Log into your WordPress Admin Dashboard -> **Plugins** -> **Add New** -> **Upload Plugin**.
3. Upload and activate `AI Sales Agent Chatbot Widget`.
4. In `wp-config.php`, specify your production API URL:
   ```php
   define('BUDDY_WIDGET_CUSTOM_API_URL', 'https://your-api-service.onrender.com/chat');
   ```

---

## 🩺 Health Checks & Production Monitoring

The backend exposes a lightweight health probe at `GET /health` for zero-downtime deployment monitoring:

```bash
curl -f https://your-api-service.onrender.com/health
```

Expected output (`200 OK`):
```json
{
  "status": "ok"
}
```
