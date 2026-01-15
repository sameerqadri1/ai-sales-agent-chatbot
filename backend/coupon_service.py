"""Dynamic coupon generation service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict
import random
import secrets

from exceptions import CouponError, WooCommerceError
from woocommerce_service import WooCommerceService


class CouponService:
    def __init__(
        self,
        wc_service: WooCommerceService,
        min_discount: int,
        max_discount: int,
        default_duration_minutes: int,
    ) -> None:
        self.wc_service = wc_service
        self.min_discount = min(min_discount, max_discount)
        self.max_discount = max(min_discount, max_discount)
        self.default_duration_minutes = default_duration_minutes

    def create_coupon(self, percent: int | None = None) -> Dict:
        """Create a limited-use percent coupon between the configured bounds."""
        discount = self._clamp_discount(percent)
        payload = {
            "code": self._generate_code(),
            "discount_type": "percent",
            "amount": str(discount),
            "usage_limit": 1,
            "usage_limit_per_user": 1,
            "date_expires": self._expiry_timestamp(),
            "description": "Buddy the Bear hesitation saver",
            "individual_use": True,
            "meta_data": [{"key": "generated_by", "value": "buddy_chatbot"}],
        }

        try:
            return self.wc_service.create_coupon(payload)
        except WooCommerceError as exc:
            raise CouponError(f"Failed to create coupon: {exc}") from exc

    def _clamp_discount(self, percent: int | None) -> int:
        if percent is None:
            return random.randint(self.min_discount, self.max_discount)
        return max(self.min_discount, min(self.max_discount, percent))

    def _generate_code(self) -> str:
        suffix = secrets.token_hex(3).upper()
        return f"BUDDY-SAVE-{suffix}"

    def _expiry_timestamp(self) -> str:
        """
        Return expiry date in WooCommerce-compatible format.
        
        CRITICAL FIX: WooCommerce interprets date-only as START of day (00:00:00),
        not end of day. So "2025-11-22" expires at midnight START of Nov 22,
        which means it's invalid after Nov 21 ends.
        
        Solution: Add 2 days to ensure coupon is valid for full 24+ hours.
        - Customer generates coupon on Nov 21 at 7 PM
        - We send date_expires: 2025-11-23 (2 days from now)
        - WooCommerce interprets as: Nov 23 00:00:00 (start of Nov 23)
        - Coupon is valid: All of Nov 21 (remaining) + All of Nov 22 + Until midnight Nov 23
        - Customer gets ~30-48 hours validity depending on generation time
        
        Returns:
            str: Date in 'YYYY-MM-DD' format (e.g., '2025-11-23')
        """
        # Get current UTC time
        now_utc = datetime.now(timezone.utc)
        
        # Convert to UAE timezone (site timezone)
        uae_timezone = timezone(timedelta(hours=4))
        now_uae = now_utc.astimezone(uae_timezone)
        
        # Add 2 days to ensure valid for full 24+ hours
        # (WooCommerce interprets date-only as START of day, not end)
        expires_date = now_uae + timedelta(days=2)
        
        # Return date only - WooCommerce will interpret as midnight start of that day
        return expires_date.strftime('%Y-%m-%d')

