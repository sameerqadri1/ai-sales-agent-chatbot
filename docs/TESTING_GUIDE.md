# 🧪 Developer & Testing Guide - AI Sales Agent Chatbot

**Author:** Sameer Qadri (Sinc Solution Team)  
**Target Audience:** QA Engineers, Backend Developers, Integration Engineers

---

## 📑 Table of Contents

1. [Overview](#overview)
2. [Local Testing Setup](#local-testing-setup)
3. [Testing API Endpoints with cURL](#testing-api-endpoints-with-curl)
4. [Testing Multi-Turn Memory & Redis State](#testing-multi-turn-memory--redis-state)
5. [Stress Testing & Catalog Metadata Discovery](#stress-testing--catalog-metadata-discovery)

---

## 🎯 Overview

This guide explains how developers and QA engineers can test the **AI Sales Agent Chatbot** backend API endpoints, validate conversation history retention, and run metadata discovery tools.

---

## 💻 Local Testing Setup

1. Start your local Redis instance:
   ```bash
   redis-server
   ```
2. Activate your Python virtual environment and start the Flask API:
   ```bash
   cd backend
   python app.py
   ```
   The backend will start on `http://127.0.0.1:8000`.

---

## 📡 Testing API Endpoints with cURL

### 1. Health Probe (`GET /health`)

```bash
curl -i http://127.0.0.1:8000/health
```

Expected Response (`200 OK`):
```json
{
  "status": "ok"
}
```

---

### 2. Conversational Search (`POST /chat`)

Test a single-turn product inquiry:

```bash
curl -i -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Do you have any wireless Bluetooth headphones under $60?",
    "session_id": "test-session-001"
  }'
```

Expected Response (`200 OK`):
```json
{
  "reply": "Yes! Here are top wireless Bluetooth headphones under $60 from our catalog...",
  "products": [
    {
      "id": 405,
      "name": "Wireless Over-Ear Headphones",
      "price": "49.99",
      "permalink": "https://your-store-domain.com/product/wireless-headphones"
    }
  ],
  "session_id": "test-session-001"
}
```

---

## 🔄 Testing Multi-Turn Memory & Redis State

Send a follow-up request using the same `session_id` to verify context memory:

```bash
curl -i -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Which of those has the best battery life?",
    "session_id": "test-session-001"
  }'
```

The AI will recall the headphones recommended in turn 1 and answer based on store metadata.

---

## 🛠️ Stress Testing & Catalog Metadata Discovery

To inspect and validate your WooCommerce store category, tag, and attribute structures, run the metadata discovery tool under `tools/`:

```bash
cd tools
python wc_metadata_dump.py
```

This utility verifies that your WooCommerce REST credentials are valid and exports a sample catalog diagnostic report (`wc_categories.csv`, `wc_tags.csv`, `wc_attributes.csv`).
