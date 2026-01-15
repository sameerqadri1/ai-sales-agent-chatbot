from __future__ import annotations

import logging
import os
from pathlib import Path
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

from chat_service import ChatService
from config import get_settings
from coupon_service import CouponService
from exceptions import ChatbotError, ValidationError
from openai_service import OpenAIService
from woocommerce_service import WooCommerceService
from redis_client import RedisClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Load .env from project root (parent directory of backend/)
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

settings = get_settings()

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
app.json.ensure_ascii = False

# CORS Configuration
cors_origins = settings.allowed_origins if settings.allowed_origins else "*"
CORS(app, resources={
    r"/*": {
        "origins": cors_origins,
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"],
        "supports_credentials": False
    }
})

# Initialize Redis client (with graceful fallback to in-memory if unavailable)
redis_client = RedisClient(settings.redis_url)

# Initialize services
openai_service = OpenAIService(settings.openai_api_key)
woocommerce_service = WooCommerceService(
    settings.wc_api_url,
    settings.wc_consumer_key,
    settings.wc_consumer_secret,
    settings.wc_brand_attribute_slug,
)
coupon_service = CouponService(
    wc_service=woocommerce_service,
    min_discount=settings.coupon_min_discount,
    max_discount=settings.coupon_max_discount,
    default_duration_minutes=settings.coupon_default_duration_minutes,
)

# Initialize Chat Service (SIMPLIFIED - direct WooCommerce search)
chat_service = ChatService(
    openai_service=openai_service,
    wc_service=woocommerce_service,
    coupon_service=coupon_service,
    redis_client=redis_client,
)

logger.info("ChatService initialized with SIMPLIFIED architecture (direct WooCommerce search)")


@app.get("/health")
def health_check():
    """Lightweight health endpoint for deployment probes."""
    return jsonify({"status": "ok"})


@app.post("/chat")
def chat_endpoint():
    payload = request.get_json(force=True, silent=True) or {}
    message = payload.get("message")
    history = payload.get("history")
    session_id = payload.get("session_id", "default")

    try:
        response = chat_service.handle_message(message, history, session_id)
        return jsonify(response)
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    except ChatbotError as exc:
        return jsonify({"error": str(exc)}), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
