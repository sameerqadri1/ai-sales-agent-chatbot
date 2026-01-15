"""Redis client with graceful fallback for session management."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import redis
from redis.exceptions import RedisError, ConnectionError

logger = logging.getLogger(__name__)


class RedisClient:
    """
    Redis client wrapper with automatic fallback to in-memory storage.
    
    If Redis is unavailable (local dev without Redis, connection failure),
    falls back to dict-based in-memory storage gracefully.
    """
    
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.client: Optional[redis.Redis] = None
        self.fallback_storage: dict[str, Any] = {}
        self.use_fallback = False
        
        try:
            # Try to connect to Redis
            self.client = redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            # Test connection
            self.client.ping()
            logger.info(f"✅ Redis connected: {redis_url}")
        except (RedisError, ConnectionError, Exception) as e:
            logger.warning(f"⚠️ Redis unavailable ({e}), using in-memory fallback")
            self.use_fallback = True
            self.client = None
    
    def set(self, key: str, value: Any, ex: Optional[int] = None) -> bool:
        """
        Set a key-value pair in Redis (or fallback storage).
        
        Args:
            key: The key
            value: The value (will be JSON-serialized)
            ex: Expiration time in seconds (ignored in fallback mode)
        
        Returns:
            True if successful, False otherwise
        """
        try:
            serialized = json.dumps(value)
            
            if self.use_fallback:
                self.fallback_storage[key] = serialized
                return True
            
            if self.client:
                self.client.set(key, serialized, ex=ex)
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Redis SET error for key '{key}': {e}")
            return False
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get a value from Redis (or fallback storage).
        
        Args:
            key: The key
        
        Returns:
            The deserialized value, or None if not found
        """
        try:
            if self.use_fallback:
                serialized = self.fallback_storage.get(key)
                if serialized:
                    return json.loads(serialized)
                return None
            
            if self.client:
                serialized = self.client.get(key)
                if serialized:
                    return json.loads(serialized)
                return None
            
            return None
            
        except Exception as e:
            logger.error(f"Redis GET error for key '{key}': {e}")
            return None
    
    def delete(self, key: str) -> bool:
        """
        Delete a key from Redis (or fallback storage).
        
        Args:
            key: The key to delete
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if self.use_fallback:
                self.fallback_storage.pop(key, None)
                return True
            
            if self.client:
                self.client.delete(key)
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Redis DELETE error for key '{key}': {e}")
            return False
    
    def exists(self, key: str) -> bool:
        """
        Check if a key exists in Redis (or fallback storage).
        
        Args:
            key: The key to check
        
        Returns:
            True if key exists, False otherwise
        """
        try:
            if self.use_fallback:
                return key in self.fallback_storage
            
            if self.client:
                return bool(self.client.exists(key))
            
            return False
            
        except Exception as e:
            logger.error(f"Redis EXISTS error for key '{key}': {e}")
            return False
    
    def expire(self, key: str, seconds: int) -> bool:
        """
        Set expiration time for a key (Redis only, ignored in fallback).
        
        Args:
            key: The key
            seconds: Expiration time in seconds
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if self.use_fallback:
                # Fallback doesn't support expiration
                return True
            
            if self.client:
                return bool(self.client.expire(key, seconds))
            
            return False
            
        except Exception as e:
            logger.error(f"Redis EXPIRE error for key '{key}': {e}")
            return False
    
    def health_check(self) -> bool:
        """
        Check if Redis is healthy.
        
        Returns:
            True if Redis is connected and responsive, False otherwise
        """
        if self.use_fallback:
            return True  # Fallback is always "healthy"
        
        try:
            if self.client:
                self.client.ping()
                return True
            return False
        except Exception:
            return False

