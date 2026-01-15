"""Centralized exception hierarchy for Buddy the Bear backend."""


class ChatbotError(Exception):
    """Base exception for predictable application errors."""


class ValidationError(ChatbotError):
    """Raised when the user input payload is invalid."""


class OpenAIError(ChatbotError):
    """Raised when OpenAI fails or returns an unexpected payload."""


class WooCommerceError(ChatbotError):
    """Raised when the WooCommerce API call fails."""


class CouponError(ChatbotError):
    """Raised when coupon generation or creation fails."""


