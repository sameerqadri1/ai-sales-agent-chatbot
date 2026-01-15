"""
Conversation orchestration logic for Buddy the Bear.
SIMPLIFIED VERSION - Direct WooCommerce search with GPT query expansion.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional

from coupon_service import CouponService
from exceptions import OpenAIError, ValidationError, WooCommerceError
from openai_service import OpenAIService
from woocommerce_service import WooCommerceService

logger = logging.getLogger(__name__)

Message = Dict[str, str]
History = List[Message]


# ============================================================================
# CONVERSATION STATE
# ============================================================================

class ConversationState:
    """
    Tracks conversation state per session for better context management.
    Single source of truth for user preferences and conversation history.
    """
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.created_at = time.time()
        
        # Core parameters
        self.age: Optional[float] = None
        self.budget: Optional[float] = None
        self.gender: Optional[str] = None
        self.occasion: Optional[str] = None
        
        # Interest tracking
        self.current_interest: Optional[str] = None
        self.previous_interests: List[str] = []
        
        # Conversation tracking
        self.message_count: int = 0
        self.products_shown_count: int = 0
        self.last_updated: float = time.time()
        
        # Additional context
        self.recipient_relationship: Optional[str] = None
        self.child_name: Optional[str] = None
        self.exclusions: List[str] = []
        self.preferences: List[str] = []
        self.price_sensitive: bool = False
    
    def update_from_parameters(self, parameters: Dict[str, Any]) -> None:
        """Update state from extracted parameters."""
        self.last_updated = time.time()
        
        if parameters.get("age") is not None:
            self.age = self._parse_age(parameters["age"])
        
        if parameters.get("budget") is not None:
            try:
                self.budget = float(parameters["budget"])
            except (TypeError, ValueError):
                pass  # Keep existing budget if parse fails
    
    @staticmethod
    def _parse_age(age_value: Any) -> Optional[float]:
        """
        Parse age from various formats:
        - Integer: 5 → 5.0
        - Float: 5.5 → 5.5
        - Range string: "4-6" → 5.0 (average)
        - String number: "5" → 5.0
        """
        if age_value is None:
            return None
        
        # If already a number, return it
        if isinstance(age_value, (int, float)):
            return float(age_value)
        
        # Convert to string and try to parse
        age_str = str(age_value).strip()
        
        # Try to parse as a range (e.g., "4-6", "4 - 6")
        if '-' in age_str:
            parts = age_str.split('-')
            if len(parts) == 2:
                try:
                    low = float(parts[0].strip())
                    high = float(parts[1].strip())
                    return (low + high) / 2  # Return average
                except ValueError:
                    pass
        
        # Try to parse as a single number
        try:
            return float(age_str)
        except ValueError:
            return None
        
        if parameters.get("gender"):
            self.gender = parameters["gender"]
        
        if parameters.get("occasion"):
            self.occasion = parameters["occasion"]
        
        # Handle interest transitions
        new_interest = parameters.get("interest")
        if new_interest:
            if self.current_interest and self.current_interest != new_interest:
                if self.current_interest not in self.previous_interests:
                    self.previous_interests.append(self.current_interest)
            self.current_interest = new_interest
        
        if parameters.get("recipient_relationship"):
            self.recipient_relationship = parameters["recipient_relationship"]
        
        self.message_count += 1
    
    def increment_products_shown(self, count: int = 1) -> None:
        """Increment counter for products shown."""
        self.products_shown_count += count
        self.last_updated = time.time()
    
    def get_session_duration(self) -> float:
        """Get session duration in seconds."""
        return time.time() - self.created_at
    
    def mark_price_sensitive(self) -> None:
        """Mark user as price-sensitive."""
        self.price_sensitive = True
    
    def add_exclusion(self, item: str) -> None:
        """Add user exclusion (things they don't want)."""
        item_lower = item.lower().strip()
        if item_lower and item_lower not in self.exclusions:
            self.exclusions.append(item_lower)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for logging."""
        return {
            "session_id": self.session_id,
            "age": self.age,
            "budget": self.budget,
            "gender": self.gender,
            "current_interest": self.current_interest,
            "message_count": self.message_count,
            "products_shown_count": self.products_shown_count,
            "price_sensitive": self.price_sensitive,
        }


# ============================================================================
# INPUT VALIDATION
# ============================================================================

class InputValidator:
    """Centralized input validation logic."""
    
    @staticmethod
    def validate_message(message: str, session_id: Optional[str] = None) -> tuple[bool, Optional[str]]:
        """Validate user input message."""
        if not message or not message.strip():
            return False, "Message cannot be empty."
        
        if len(message) > 500:
            return False, "Message too long. Please keep it under 500 characters."
        
        return True, None
    
    @staticmethod
    def is_primarily_english(text: str) -> bool:
        """Check if text is primarily English."""
        english_pattern = re.compile(r'^[a-zA-Z0-9\s\.,!?\'\"-:;()]+$')
        return bool(english_pattern.match(text))


# ============================================================================
# SESSION MANAGEMENT
# ============================================================================

class SessionManager:
    """Manage session state with Redis support."""
    
    def __init__(self, redis_client=None):
        self.redis_client = redis_client
        self.session_coupons: Dict[str, List[Dict[str, Any]]] = {}
        self.session_shown_products: Dict[str, List[int]] = {}
        self.rate_limit_tracker: Dict[str, List[float]] = {}
        self.first_product_timestamps: Dict[str, float] = {}
    
    def track_coupon(self, session_id: str, coupon_data: Dict[str, Any]) -> None:
        """Track coupon issued to session."""
        redis_key = f"session:{session_id}:coupons"
        
        if self.redis_client:
            coupons = self.redis_client.get(redis_key) or []
            coupons.append(coupon_data)
            self.redis_client.set(redis_key, coupons, ex=86400)
        else:
            if session_id not in self.session_coupons:
                self.session_coupons[session_id] = []
            self.session_coupons[session_id].append(coupon_data)
    
    def get_coupon_count(self, session_id: str) -> int:
        """Get number of coupons issued in this session."""
        redis_key = f"session:{session_id}:coupons"
        
        if self.redis_client:
            coupons = self.redis_client.get(redis_key) or []
            return len(coupons)
        else:
            return len(self.session_coupons.get(session_id, []))
    
    def track_products(self, session_id: str, products: List[Dict[str, Any]]) -> None:
        """Track products shown to user."""
        redis_key = f"session:{session_id}:shown_products"
        
        if self.redis_client:
            shown_ids = self.redis_client.get(redis_key) or []
            
            if session_id not in self.first_product_timestamps and products:
                self.redis_client.set(f"session:{session_id}:first_product_time", time.time(), ex=86400)
            
            for product in products:
                product_id = product.get("id")
                if product_id and product_id not in shown_ids:
                    shown_ids.append(product_id)
            
            self.redis_client.set(redis_key, shown_ids, ex=86400)
        else:
            if session_id not in self.session_shown_products:
                self.session_shown_products[session_id] = []
            
            if session_id not in self.first_product_timestamps and products:
                self.first_product_timestamps[session_id] = time.time()
            
            for product in products:
                product_id = product.get("id")
                if product_id and product_id not in self.session_shown_products[session_id]:
                    self.session_shown_products[session_id].append(product_id)
    
    def get_shown_product_ids(self, session_id: str) -> List[int]:
        """Get list of product IDs already shown."""
        redis_key = f"session:{session_id}:shown_products"
        
        if self.redis_client:
            return self.redis_client.get(redis_key) or []
        else:
            return self.session_shown_products.get(session_id, [])
    
    def get_time_since_first_product(self, session_id: str) -> Optional[float]:
        """Get seconds since first product was shown."""
        if self.redis_client:
            first_time = self.redis_client.get(f"session:{session_id}:first_product_time")
            if first_time:
                return time.time() - first_time
        else:
            first_time = self.first_product_timestamps.get(session_id)
            if first_time:
                return time.time() - first_time
        return None
    
    def check_rate_limit(self, session_id: str, limit: int = 20, window: int = 60) -> bool:
        """Check rate limiting: max 20 messages per minute."""
        current_time = time.time()
        redis_key = f"session:{session_id}:rate_limit"
        
        if self.redis_client:
            timestamps = self.redis_client.get(redis_key) or []
            timestamps = [ts for ts in timestamps if current_time - ts < window]
            
            if len(timestamps) >= limit:
                return False
            
            timestamps.append(current_time)
            self.redis_client.set(redis_key, timestamps, ex=window)
            return True
        else:
            if session_id not in self.rate_limit_tracker:
                self.rate_limit_tracker[session_id] = []
            
            self.rate_limit_tracker[session_id] = [
                ts for ts in self.rate_limit_tracker[session_id]
                if current_time - ts < window
            ]
            
            if len(self.rate_limit_tracker[session_id]) >= limit:
                return False
            
            self.rate_limit_tracker[session_id].append(current_time)
            return True


# ============================================================================
# PRODUCT FILTERING
# ============================================================================

class ProductFilter:
    """Centralized product filtering logic."""
    
    def __init__(self, session_manager: SessionManager):
        self.session = session_manager
        
        self.gender_keywords = {
            "female": ["barbie", "princess", "doll", "unicorn", "dress", "kitchen", "makeup", "mermaid"],
            "male": ["avengers", "spider-man", "spiderman", "iron man", "batman", "truck", "car", "robot", "dinosaur", "nerf"]
        }
    
    def apply_all_filters(
        self,
        products: List[Dict[str, Any]],
        age: Optional[float] = None,
        gender: Optional[str] = None,
        exclusions: Optional[List[str]] = None,
        session_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Apply all filters."""
        if not products:
            return []
        
        logger.debug(f"Filtering {len(products)} products")
        
        if age:
            products = self.filter_by_age(products, age)
        
        if gender and gender != "neutral":
            products = self.filter_by_gender(products, gender)
        
        if exclusions:
            products = self.filter_exclusions(products, exclusions)
        
        if session_id:
            excluded_ids = self.session.get_shown_product_ids(session_id)
            products = [p for p in products if p.get("id") not in excluded_ids]
        
        logger.debug(f"After filtering: {len(products)} products remain")
        return products
    
    def filter_by_age(self, products: List[Dict[str, Any]], age: float) -> List[Dict[str, Any]]:
        """Filter products by age appropriateness."""
        if not age or not products:
            return products
        
        filtered = []
        for product in products:
            if self._is_age_appropriate(product, age):
                filtered.append(product)
        
        return filtered
    
    def _is_age_appropriate(self, product: Dict[str, Any], user_age: float) -> bool:
        """Check if product is age-appropriate."""
        name = product.get("name", "").lower()
        tags = [tag.get("name", "").lower() for tag in product.get("tags", [])]
        categories = [cat.get("name", "").lower() for cat in product.get("categories", [])]
        all_text = f"{name} {' '.join(tags)} {' '.join(categories)}"
        
        age_patterns = [
            r'(\d+)\+',
            r'ages?\s+(\d+)',
            r'(\d+)\s*years?\+',
            r'for\s+(\d+)\+',
        ]
        
        min_age_found = None
        for pattern in age_patterns:
            matches = re.findall(pattern, all_text)
            if matches:
                ages_found = [int(m) for m in matches]
                min_age_found = min(ages_found)
                break
        
        if min_age_found is None:
            return True
        
        age_difference = user_age - min_age_found
        
        if user_age >= min_age_found:
            if age_difference <= 5:
                return True
            elif min_age_found >= 8:
                return True
            else:
                return False
        else:
            return False
    
    def filter_by_gender(self, products: List[Dict[str, Any]], desired_gender: str) -> List[Dict[str, Any]]:
        """Filter products by gender keywords."""
        if desired_gender == "neutral":
            return products
        
        lookup = self.gender_keywords.get(desired_gender, [])
        if not lookup:
            return products
        
        filtered = []
        for product in products:
            haystack = " ".join(
                str(value) for value in product.values() if isinstance(value, str)
            ).lower()
            if any(keyword in haystack for keyword in lookup):
                filtered.append(product)
        
        return filtered
    
    def filter_exclusions(self, products: List[Dict[str, Any]], exclusions: List[str]) -> List[Dict[str, Any]]:
        """Filter out products matching exclusion keywords."""
        if not exclusions:
            return products

        lowered = [token.lower() for token in exclusions]
        filtered = []
        
        for product in products:
            haystack = " ".join(
                str(value) for value in product.values() if isinstance(value, str)
            ).lower()
            if not any(token in haystack for token in lowered):
                filtered.append(product)
        
        return filtered

    def infer_gender(self, parameters: Dict[str, Any]) -> str:
        """Infer gender from parameters and interests."""
        gender = (parameters.get("gender") or "").lower()
        if gender in {"male", "boy"}:
            return "male"
        if gender in {"female", "girl"}:
            return "female"
        
        interest = (parameters.get("interest") or "").lower()
        for keyword in self.gender_keywords["female"]:
            if keyword in interest:
                return "female"
        for keyword in self.gender_keywords["male"]:
            if keyword in interest:
                return "male"
        
        return "neutral"


# ============================================================================
# SALES ENGINE
# ============================================================================

class SalesEngine:
    """Sales features (hesitation detection, coupon generation)."""
    
    def __init__(self, coupon_service: Optional[CouponService], session_manager: SessionManager):
        self.coupon_service = coupon_service
        self.session = session_manager
        
        self.explicit_hesitation_keywords = [
            "expensive", "too much", "think about it", "not sure",
            "maybe later", "let me think", "pricey", "costly",
            "budget", "cheaper", "discount", "sale", "deal"
        ]
    
    def check_for_coupon(
        self,
        message: str,
        conversation: History,
        session_id: str,
        time_since_first_product: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """Check if user is hesitating and generate coupon if appropriate."""
        if not self.coupon_service:
            return None
        
        is_hesitating = self.detect_hesitation(message)
        
        if not is_hesitating:
            return None
        
        coupon_count = self.session.get_coupon_count(session_id)
        if coupon_count >= 2:
            logger.info(f"[{session_id}] Max coupons reached (2)")
            return None
        
        try:
            discount = 3 if coupon_count == 0 else 5
            coupon_data = self.coupon_service.create_coupon(percent=discount)
            
            if coupon_data:
                self.session.track_coupon(session_id, coupon_data)
                logger.info(f"[{session_id}] Coupon generated: {coupon_data.get('code')} ({discount}% OFF)")
                return coupon_data
        
        except Exception as exc:
            logger.error(f"[{session_id}] Coupon generation failed: {exc}")
            return None
        
        return None
    
    def detect_hesitation(self, message: str) -> bool:
        """Detect if user is hesitating."""
        lowered = message.lower()
        return any(keyword in lowered for keyword in self.explicit_hesitation_keywords)


# ============================================================================
# MAIN CHAT SERVICE
# ============================================================================

class ChatService:
    """
    Main orchestration service - SIMPLIFIED VERSION.
    
    Flow:
    1. Extract parameters (GPT)
    2. Expand query (GPT) - "batman" → ["batman", "batmobile", "dc comics"]
    3. Search WooCommerce with each keyword
    4. Deduplicate and filter by age
    5. Format response (GPT)
    
    No complex AI ranking - let WooCommerce popularity ordering do the work.
    """
    
    def __init__(
        self,
        openai_service: OpenAIService,
        wc_service: WooCommerceService,
        coupon_service: Optional[CouponService] = None,
        redis_client=None,
    ) -> None:
        self.openai_service = openai_service
        self.wc_service = wc_service
        self.coupon_service = coupon_service
        
        # Initialize components
        self.validator = InputValidator()
        self.session = SessionManager(redis_client=redis_client)
        self.filter = ProductFilter(self.session)
        self.sales = SalesEngine(coupon_service, self.session)
        
        # Conversation state management
        self.conversation_states: Dict[str, ConversationState] = {}
        
        logger.info("ChatService initialized (SIMPLIFIED - direct WooCommerce search)")
    
    def handle_message(
        self,
        message: str,
        history: Optional[History] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Main entry point for the /chat endpoint."""
        sanitized_message = (message or "").strip()
        logger.info(f"[{session_id}] User message: {sanitized_message[:100]}")
        
        try:
            # STEP 1: Validation
            is_valid, error = self.validator.validate_message(sanitized_message, session_id)
            if not is_valid:
                raise ValidationError(error)
            
            if not self.validator.is_primarily_english(sanitized_message):
                return {
                    "reply": "I currently only support English. Please write your message in English!",
                    "products": [],
                    "parameters": {},
                    "coupon": None,
                    "source": "language_not_supported",
                }
            
            if session_id and not self.session.check_rate_limit(session_id):
                raise ValidationError("Too many requests. Please wait a moment.")
            
            # STEP 2: Build conversation context
            conversation = self._build_conversation(history, sanitized_message)
            
            # STEP 3: Extract parameters
            parameters = self.openai_service.extract_parameters_with_context(
                sanitized_message, conversation
            )
            logger.info(f"[{session_id}] Extracted: age={parameters.get('age')}, interest={parameters.get('interest')}")
            
            # STEP 4: Update conversation state
            if session_id:
                if session_id not in self.conversation_states:
                    self.conversation_states[session_id] = ConversationState(session_id)
                
                state = self.conversation_states[session_id]
                state.update_from_parameters(parameters)
                
                price_keywords = ["expensive", "cheap", "budget", "price", "discount"]
                if any(keyword in sanitized_message.lower() for keyword in price_keywords):
                    state.mark_price_sensitive()
            
            # STEP 5: Safety check
            if not parameters.get("is_appropriate", True):
                return self._safety_response(parameters)
            
            # STEP 6: Check if requesting alternatives
            if self._is_requesting_alternatives(sanitized_message):
                return self._handle_alternatives(conversation, parameters, session_id)
            
            # STEP 7: Check if clarification needed
            if not self._has_required_params(parameters, session_id):
                return self._clarification_response(conversation, parameters)
            
            # STEP 8: SIMPLIFIED SEARCH - Query expansion + WooCommerce
            products = self._search_products(parameters, session_id)
            logger.info(f"[{session_id}] Products found: {len(products)}")
            
            # STEP 9: Handle no results
            if not products:
                return self._no_results_response(parameters)
            
            # STEP 10: Check for coupon opportunity
            time_since_first_product = self.session.get_time_since_first_product(session_id)
            coupon = self.sales.check_for_coupon(
                message=sanitized_message,
                conversation=conversation,
                session_id=session_id,
                time_since_first_product=time_since_first_product
            )
            
            # STEP 11: Track shown products
            self.session.track_products(session_id, products)
            
            if session_id and session_id in self.conversation_states:
                self.conversation_states[session_id].increment_products_shown(len(products))
            
            # STEP 12: Generate response
            reply = self.openai_service.format_response(
                conversation=conversation,
                products=products,
                parameters=parameters,
                coupon=coupon
            )
            reply = self._normalize_text(reply)
            
            return {
                "reply": reply,
                "products": products,
                "parameters": parameters,
                "coupon": coupon,
                "source": "product_recommendations_with_coupon" if coupon else "product_recommendations",
            }
        
        except ValidationError:
            raise
        
        except OpenAIError as exc:
            logger.error(f"[{session_id}] OpenAI error: {exc}")
            return {
                "reply": "I'm having trouble right now. Please try again!",
                "products": [],
                "parameters": {},
                "coupon": None,
                "source": "openai_error",
            }
        
        except WooCommerceError as exc:
            logger.error(f"[{session_id}] WooCommerce error: {exc}")
            return {
                "reply": "I'm having trouble accessing products right now. Please try again!",
                "products": [],
                "parameters": {},
                "coupon": None,
                "source": "woocommerce_error",
            }
        
        except Exception as exc:
            logger.exception(f"[{session_id}] Unexpected error: {exc}")
            return {
                "reply": "Oops! Something went wrong. Please try again!",
                "products": [],
                "parameters": {},
                "coupon": None,
                "source": "unexpected_error",
            }
    
    # ========================================================================
    # SIMPLIFIED SEARCH
    # ========================================================================
    
    def _search_products(self, parameters: Dict[str, Any], session_id: Optional[str]) -> List[Dict[str, Any]]:
        """
        SIMPLIFIED SEARCH - Query expansion + WooCommerce.
        
        Flow:
        1. GPT expands query: "batman" → ["batman", "batmobile", "dc comics"]
        2. Search WooCommerce with each keyword
        3. Deduplicate results
        4. Apply age filter
        5. Filter already shown products
        6. Return top 5
        
        NO complex AI ranking - just use WooCommerce's popularity ordering.
        """
        age = self._safe_number(parameters.get("age"))
        interest = parameters.get("interest")
        
        if not age or not interest:
            logger.warning(f"[{session_id}] Missing params: age={age}, interest={interest}")
            return []
        
        logger.info(f"[{session_id}] Search: '{interest}' for age {age}")
        
        # STEP 1: Query expansion (GPT)
        try:
            expanded_keywords = self.openai_service.expand_search_query(interest, int(age))
            logger.info(f"[{session_id}] Expanded: {expanded_keywords}")
        except Exception as e:
            logger.error(f"[{session_id}] Query expansion failed: {e}")
            expanded_keywords = [interest]
        
        # STEP 2: Multi-keyword WooCommerce search
        all_products = []
        for keyword in expanded_keywords[:5]:  # Limit to 5 keywords for speed
            try:
                products = self.wc_service.search_products({
                    "search": keyword,
                    "per_page": 10,
                    "orderby": "popularity"
                })
                all_products.extend(products)
                logger.debug(f"[{session_id}] '{keyword}' → {len(products)} products")
            except Exception as e:
                logger.error(f"[{session_id}] Search failed for '{keyword}': {e}")
        
        # STEP 3: Deduplicate
        seen_ids = set()
        unique_products = []
        for product in all_products:
            product_id = product.get("id")
            if product_id and product_id not in seen_ids:
                seen_ids.add(product_id)
                unique_products.append(product)
        
        logger.info(f"[{session_id}] Deduped: {len(all_products)} → {len(unique_products)}")
        
        if not unique_products:
            return []
        
        # STEP 3.5: Validate keywords appear in product NAME (prevents irrelevant matches)
        before_validation = len(unique_products)
        unique_products = self._validate_products_by_keywords(unique_products, expanded_keywords, session_id)
        logger.info(f"[{session_id}] After name validation: {before_validation} → {len(unique_products)}")
        
        if not unique_products:
            return []
        
        # STEP 4: Age filter
        unique_products = self.filter.filter_by_age(unique_products, age)
        logger.info(f"[{session_id}] After age filter: {len(unique_products)}")
        
        # STEP 5: Filter exclusions
        exclusions = self._get_exclusions(parameters, session_id)
        if exclusions:
            unique_products = self.filter.filter_exclusions(unique_products, exclusions)
        
        # STEP 6: Filter already shown
        if session_id:
            shown_ids = self.session.get_shown_product_ids(session_id)
            unique_products = [p for p in unique_products if p.get("id") not in shown_ids]
        
        # STEP 7: Return top 5
        final = unique_products[:5]
        logger.info(f"[{session_id}] Final: {len(final)} products")
        return final
    
    # ========================================================================
    # HELPER METHODS
    # ========================================================================
    
    def _validate_products_by_keywords(
        self,
        products: List[Dict[str, Any]],
        keywords: List[str],
        session_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Filter products where at least one search keyword appears in product NAME.
        
        This prevents WooCommerce from returning irrelevant products that only
        match keywords in description (e.g., batteries matching "remote control"
        because description mentions "remote controls").
        
        Args:
            products: List of products from WooCommerce
            keywords: List of search keywords used
            session_id: For logging
        
        Returns:
            Products where at least one keyword word appears in the name
        """
        if not products or not keywords:
            return products
        
        # Generic words that appear in many products - don't use for matching
        STOPWORDS = {
            "toy", "toys", "set", "sets", "kit", "kits", "game", "games",
            "puzzle", "puzzles", "play", "kids", "children", "piece", "pieces",
            "pack", "box", "for", "with", "and", "the", "year", "years", "old"
        }
        
        # Extract individual words from all keywords, excluding stopwords
        keyword_words = set()
        for keyword in keywords:
            for word in keyword.lower().split():
                # Only add meaningful words (3+ chars) that aren't stopwords
                if len(word) >= 3 and word not in STOPWORDS:
                    keyword_words.add(word)
        
        if not keyword_words:
            return products
        
        validated = []
        for product in products:
            product_name = (product.get("name") or "").lower()
            
            # Check if ANY keyword word appears in the product name
            if any(word in product_name for word in keyword_words):
                validated.append(product)
            else:
                logger.debug(f"[{session_id}] Filtered out (no keyword in name): {product.get('name', '')[:50]}")
        
        return validated
    
    def _build_conversation(self, history: Optional[History], current_message: str) -> History:
        """Build conversation context."""
        conversation = []
        
        if history:
            for entry in history:
                role = entry.get("role")
                content = (entry.get("content") or "").strip()
                if role in {"user", "assistant"} and content:
                    conversation.append({"role": role, "content": content})
        
        conversation.append({"role": "user", "content": current_message})
        return conversation
    
    def _has_required_params(self, parameters: Dict[str, Any], session_id: Optional[str] = None) -> bool:
        """Check if we have minimum required parameters (age + interest)."""
        age = parameters.get("age")
        interest = parameters.get("interest")
        
        # Try conversation state if params missing
        if session_id and session_id in self.conversation_states:
            state = self.conversation_states[session_id]
            if not age and state.age:
                age = state.age
                parameters["age"] = age
            if not interest and state.current_interest:
                interest = state.current_interest
                parameters["interest"] = interest
        
        return bool(self._safe_number(age) and interest)
    
    @staticmethod
    def _safe_number(value: Any) -> Optional[float]:
        """
        Convert value to float, return None if invalid.
        Handles age ranges like "4-6" → 4.0 (lower bound for inclusive matching).
        """
        if value is None:
            return None
        
        # If already a number, validate and return
        if isinstance(value, (int, float)):
            return float(value) if value > 0 else None
        
        # Convert to string and try to parse
        value_str = str(value).strip()
        
        # Handle range format (e.g., "4-6") → use lower bound (4) for inclusive matching
        if '-' in value_str:
            parts = value_str.split('-')
            if len(parts) == 2:
                try:
                    low = float(parts[0].strip())
                    # Use lower bound so products for ages 4, 5, 6 all match
                    return low if low > 0 else None
                except ValueError:
                    pass
        
        # Try to parse as a single number
        try:
            number = float(value_str)
            return number if number > 0 else None
        except (TypeError, ValueError):
            return None
    
    def _get_exclusions(self, parameters: Dict[str, Any], session_id: Optional[str] = None) -> List[str]:
        """Extract exclusions from parameters and conversation state."""
        exclusions = []
        
        if session_id and session_id in self.conversation_states:
            state = self.conversation_states[session_id]
            exclusions.extend(state.exclusions)
        
        additional_notes = (parameters.get("additional_notes") or "").lower()
        if "no lego" in additional_notes or "not lego" in additional_notes:
            if "lego" not in exclusions:
                exclusions.append("lego")
        
        return exclusions
    
    def _is_requesting_alternatives(self, message: str) -> bool:
        """Detect if user is asking for alternatives."""
        lowered = message.lower()
        alternative_keywords = [
            "other options", "what else", "show me more", "anything else",
            "other toys", "something else", "more choices",
            "trending", "popular", "best seller"
        ]
        return any(keyword in lowered for keyword in alternative_keywords)
    
    def _handle_alternatives(
        self,
        conversation: History,
        parameters: Dict[str, Any],
        session_id: Optional[str]
    ) -> Dict[str, Any]:
        """Handle request for alternative products."""
        query = {"per_page": 10, "orderby": "popularity", "order": "desc"}
        
        # Check if user has current interest
        if session_id and session_id in self.conversation_states:
            current_interest = self.conversation_states[session_id].current_interest
            if current_interest:
                query["search"] = current_interest
        
        products = self.wc_service.search_products(query)
        
        products = self.filter.apply_all_filters(
            products,
            age=self._safe_number(parameters.get("age")),
            gender=self.filter.infer_gender(parameters),
            session_id=session_id
        )[:5]
        
        if products:
            self.session.track_products(session_id, products)
            reply = self.openai_service.format_response(conversation, products, parameters, coupon=None)
            reply = self._normalize_text(reply)
            return {
                "reply": reply,
                "products": products,
                "parameters": parameters,
                "coupon": None,
                "source": "alternatives_requested",
            }
        
        return self._no_results_response(parameters)
    
    def _safety_response(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Return safety decline message."""
        reply = self.openai_service.build_safety_decline_message()
        return {
            "reply": reply,
            "products": [],
            "parameters": parameters,
            "coupon": None,
            "source": "inappropriate_content_blocked",
        }
    
    def _clarification_response(self, conversation: History, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Ask for clarification when missing required params."""
        reply = self.openai_service.ask_for_clarification(conversation, parameters)
        reply = self._normalize_text(reply)
        return {
            "reply": reply,
            "products": [],
            "parameters": parameters,
            "coupon": None,
            "source": "clarification_needed",
        }
    
    def _no_results_response(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Handle no results scenario."""
        age = self._safe_number(parameters.get("age"))
        interest = parameters.get("interest") or "that"
        
        # Fetch trending products as alternatives
        try:
            trending_products = self.wc_service.search_products({
                "orderby": "popularity",
                "order": "desc",
                "per_page": 5,
                "status": "publish"
            })
        except Exception as e:
            logger.error(f"Failed to fetch trending products: {e}")
            trending_products = []
        
        if age:
            reply = (
                f"I couldn't find {interest} products for age {int(age)} right now. "
                f"Here are some popular products you might like instead! "
                f"Or tell me about other interests and I'll search again!"
            )
        else:
            reply = (
                f"I couldn't find {interest} products right now. "
                f"Here are some popular products you might like! "
                f"Feel free to tell me more about what you're looking for!"
            )
        
        reply = self._normalize_text(reply)
        
        return {
            "reply": reply,
            "products": trending_products,
            "parameters": parameters,
            "coupon": None,
            "source": "no_results_with_alternatives",
        }
    
    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalize text to remove problematic characters."""
        replacements = {
            "\u2018": "'",
            "\u2019": "'",
            "\u201c": '"',
            "\u201d": '"',
        }
        for src, target in replacements.items():
            text = text.replace(src, target)
        
        normalized = []
        for char in text:
            if ord(char) < 128 or char in '\n\r':
                normalized.append(char)
            else:
                normalized.append(' ')
        
        text = ''.join(normalized)
        text = text.replace("\r", " ")
        text = re.sub(r"\s*\n\s*", " ", text)
        text = re.sub(r"\s{2,}", " ", text)
        return text.strip()
