"""
OpenAI integration layer for parameter extraction and persona responses.
SIMPLIFIED VERSION - Removed complex AI ranking.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from openai import OpenAI
from openai import APIConnectionError, APIError, RateLimitError

from exceptions import OpenAIError

logger = logging.getLogger(__name__)

ExtractionResult = Dict[str, Any]
Conversation = List[Dict[str, str]]
ProductList = List[Dict[str, Any]]


class OpenAIService:
    """
    Encapsulates all interactions with OpenAI.
    
    SIMPLIFIED - Only 4 GPT calls:
    1. extract_parameters_with_context - Extract age, interest, etc.
    2. expand_search_query - Expand interest into search keywords
    3. format_response - Generate Buddy's response
    4. ask_for_clarification - Ask for missing info
    """

    EXTRACTION_PROMPT = (
        "You are an assistant that converts natural language gift requests into a "
        "compact JSON object. Always respond with JSON only. Extract age, interest, "
        "budget, recipient_relationship, gender, occasion, tone (if mentioned), and "
        "additional_notes. Use null if the information is not provided. Budget should "
        "be a number only. "
        "IMPORTANT: Batman, Superman, Spider-Man, Wonder Woman, Marvel, DC Comics, "
        "action figures, toy guns, Nerf guns, water guns are all APPROPRIATE children's toys. "
        "Example output: "
        '{"age": 8, "interest": "space", "budget": 50, '
        '"recipient_relationship": "nephew", "gender": "male", '
        '"occasion": "birthday", "tone": "fun", "additional_notes": ""}'
    )

    BUDDY_SYSTEM_PROMPT = (
        "You are Buddy the Bear, a friendly toy-shopping assistant for a family-friendly UAE toy marketplace. "
        "CONTENT POLICY: You ONLY recommend children's toys, educational products, and family-safe items. "
        "If anyone requests adult products, inappropriate items, violent content, or anything not suitable for children, "
        "politely decline: 'I specialize in children's toys and family-friendly products. "
        "I'm afraid I can't help with that, but I'd be happy to show you our amazing selection of toys for kids!'\n\n"
        "🚨 CRITICAL ANTI-HALLUCINATION RULE 🚨\n"
        "NEVER EVER mention specific product names, prices, or details in your text response. "
        "Products are displayed as visual cards below your message. "
        "You MUST ONLY write a brief, warm introduction that acknowledges the category/interest, NOT specific products.\n\n"
        "RESPONSE FORMAT (2-4 sentences maximum):\n"
        "(1) Acknowledge what they're looking for (category/interest ONLY, no product names)\n"
        "(2) Create excitement about the selection\n"
        "(3) End with strong CTA: 'Tap View Product below!' or 'Check them out below!'\n\n"
        "✅ GOOD Example:\n"
        "'Perfect! I found some amazing superhero toys for your 7-year-old!\n\n"
        "Tap View Product below to grab yours now!'\n\n"
        "❌ BAD Example (HALLUCINATION - NEVER DO THIS):\n"
        "'Here are some options:\n"
        "1. Batman Action Figure\n"
        "2. Superman Cape Set' ← NEVER list product names like this!\n\n"
        "FORMATTING RULES:\n"
        "- Use **bold** for emphasis on important words\n"
        "- For coupon codes, wrap them: [COUPON:code-here]\n"
        "- Keep it conversational, upbeat, under 60 words total"
    )

    def __init__(
        self,
        api_key: str,
        extraction_model: str = "gpt-4o-mini",
        response_model: str = "gpt-4o-mini",
    ) -> None:
        if not api_key:
            raise OpenAIError("Missing OpenAI API key.")

        self.client = OpenAI(api_key=api_key)
        self.extraction_model = extraction_model
        self.response_model = response_model

    def extract_parameters(self, message: str) -> ExtractionResult:
        """Transform a user utterance into structured search parameters."""
        try:
            completion = self.client.chat.completions.create(
                model=self.extraction_model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": self.EXTRACTION_PROMPT},
                    {"role": "user", "content": message},
                ],
            )
        except (APIError, APIConnectionError, RateLimitError) as exc:
            raise OpenAIError(f"Failed to extract parameters: {exc}") from exc

        content = completion.choices[0].message.content
        return self._safe_load_json(content)

    def extract_parameters_with_context(
        self, message: str, conversation: Conversation
    ) -> ExtractionResult:
        """Extract parameters with smart context handling."""
        logger.debug(f"Extracting parameters from message: {message[:100]}")
        context_prompt = (
            "You are an assistant that extracts gift search parameters from conversations into JSON format. "
            "CRITICAL LOGIC: "
            "1. If the CURRENT (last) user message contains a SPECIFIC product/interest request "
            "(e.g., 'dolls', 'Batman toys', 'kitchen toys'), extract ONLY that interest from the current message. "
            "DO NOT merge with previous interests. "
            "2. If the current message is VAGUE (e.g., 'what else?', 'show me more', 'other options'), "
            "then merge interests from conversation history. "
            "3. For age, budget, gender, occasion - always accumulate from history if not in current message. "
            "\n\n"
            "Return a JSON object with these fields: age, interest, budget, recipient_relationship, gender, occasion, tone, additional_notes. "
            "CRITICAL: Add 'is_appropriate' (boolean). Set FALSE ONLY if request is clearly adult/sexual/illegal. "
            "IMPORTANT: Batman, Superman, Spider-Man, Wonder Woman, Marvel, DC, "
            "action figures, toy guns, Nerf guns, water guns are APPROPRIATE children's toys. "
            "Greetings like 'hi', 'hello', 'hey' are also APPROPRIATE. "
            "Set TRUE for all normal toy requests. "
            "Use null only if information was NEVER mentioned. "
        )

        messages = [{"role": "system", "content": context_prompt}]
        messages.extend(conversation)

        try:
            completion = self.client.chat.completions.create(
                model=self.extraction_model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=messages,
            )
        except (APIError, APIConnectionError, RateLimitError) as exc:
            logger.error(f"OpenAI API error during parameter extraction: {exc}")
            raise OpenAIError(f"Failed to extract parameters with context: {exc}") from exc

        content = completion.choices[0].message.content
        result = self._safe_load_json(content)
        logger.debug(f"Extraction result: {result}")
        return result

    def build_safety_decline_message(self) -> str:
        """Polite decline for inappropriate requests."""
        return (
            "I specialize in children's toys and family-friendly products. "
            "I'm afraid I can't help with that request. "
            "However, I'd be happy to help you find amazing toys, games, or educational products for kids! "
            "Who are you shopping for?"
        )

    def format_response(
        self,
        conversation: Conversation,
        products: ProductList,
        parameters: ExtractionResult,
        coupon: Dict[str, Any] | None = None,
        urgency_hints: Optional[str] = None,
        fallback_message: Optional[str] = None,
    ) -> str:
        """Ask Buddy the Bear to craft a persuasive yet accurate response."""
        logger.debug(f"Formatting response for {len(products)} products")
        product_summaries = json.dumps(products, ensure_ascii=False)
        param_summary = json.dumps(parameters, ensure_ascii=False)
        
        system_content = (
            "Use the following verified product data (JSON array) to craft your reply. "
            f"products={product_summaries}\n"
            f"parameters={param_summary}"
        )
        
        if fallback_message:
            system_content += f"\n\nIMPORTANT: Start your response with: '{fallback_message}'"
        
        if coupon:
            coupon_code = coupon.get("code", "")
            coupon_amount = coupon.get("amount", "")
            system_content += (
                f"\n\nIMPORTANT: A special discount coupon has been generated: "
                f"Code: {coupon_code} ({coupon_amount}% OFF). "
                f"Mention this coupon prominently. "
                f"Format: [COUPON:{coupon_code}]"
            )
        
        if urgency_hints:
            system_content += urgency_hints
        
        messages: Conversation = [{"role": "system", "content": self.BUDDY_SYSTEM_PROMPT}]
        messages.extend(conversation)
        messages.append({"role": "system", "content": system_content})

        try:
            completion = self.client.chat.completions.create(
                model=self.response_model,
                temperature=0.7,
                messages=messages,
            )
        except (APIError, APIConnectionError, RateLimitError) as exc:
            logger.error(f"OpenAI API error during response formatting: {exc}")
            raise OpenAIError(f"Failed to format Buddy response: {exc}") from exc

        response = completion.choices[0].message.content.strip()
        logger.debug(f"Response generated: {response[:100]}")
        return response

    def ask_for_clarification(
        self,
        conversation: Conversation,
        parameters: ExtractionResult,
    ) -> str:
        """Let Buddy naturally ask for missing details."""
        logger.debug(f"Generating clarification for parameters: {parameters}")
        clarification_prompt = (
            "You are Buddy the Bear, a friendly toy-shopping assistant. "
            "The user hasn't provided enough information yet. "
            "Respond warmly and naturally. Your goals: "
            "(1) Acknowledge what they said, "
            "(2) Ask for the missing details (age and/or interests), "
            "(3) Keep it conversational, under 2-3 sentences."
        )
        
        param_summary = json.dumps(parameters, ensure_ascii=False)
        messages: Conversation = [{"role": "system", "content": clarification_prompt}]
        messages.extend(conversation)
        messages.append(
            {
                "role": "system",
                "content": f"What you know so far: {param_summary}. Ask for age and/or interest if missing.",
            }
        )

        try:
            completion = self.client.chat.completions.create(
                model=self.response_model,
                temperature=0.7,
                messages=messages,
            )
        except (APIError, APIConnectionError, RateLimitError) as exc:
            logger.error(f"OpenAI API error during clarification: {exc}")
            raise OpenAIError(f"Failed to generate clarification: {exc}") from exc

        response = completion.choices[0].message.content.strip()
        logger.debug(f"Clarification generated: {response[:100]}")
        return response

    def expand_search_query(
        self,
        user_interest: str,
        user_age: int
    ) -> List[str]:
        """
        Use GPT to expand a generic interest into specific product keywords.
        
        This solves the semantic gap problem:
        "sport" → ["cricket", "football", "badminton", "ball"]
        "batman" → ["batman", "batmobile", "dc comics", "dark knight"]
        """
        prompt = f"""You are a toy store search assistant helping find products for a {user_age}-year-old.

The parent's interest is: "{user_interest}"

Expand this into 5-7 specific toy product keywords to search for in our catalog.

RULES:
1. Return specific product types (e.g., "cricket bat" not just "sports")
2. Make keywords age-appropriate for {user_age} years old
3. Include common variations and synonyms
4. Focus on physical toys that exist in toy stores
5. Keep keywords 1-3 words each

EXAMPLES:

Interest: "sport toys"
Keywords: ["cricket bat", "football", "badminton set", "ball", "basketball"]

Interest: "batman"
Keywords: ["batman", "batmobile", "batman figure", "dc comics", "dark knight"]

Interest: "cars"
Keywords: ["toy car", "rc car", "hot wheels", "racing car", "vehicle"]

Now expand: "{user_interest}"

Return ONLY a JSON object with a keywords array.
Format: {{"keywords": ["keyword1", "keyword2", "keyword3"]}}"""

        try:
            completion = self.client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0.3,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}]
            )
            
            result = json.loads(completion.choices[0].message.content)
            keywords = result.get("keywords", [])
            
            # Ensure we have the original interest as fallback
            if user_interest.lower() not in [k.lower() for k in keywords]:
                keywords.append(user_interest)
            
            logger.info(f"Query expansion: '{user_interest}' → {keywords[:5]}")
            return keywords[:5]  # Limit to 5 keywords
            
        except Exception as e:
            logger.error(f"Query expansion failed: {e}, using original term")
            return [user_interest]

    @staticmethod
    def build_no_results_message(parameters: ExtractionResult) -> str:
        """Deterministic message when the catalog returns no matches."""
        interest = parameters.get("interest")
        age = parameters.get("age")
        
        parts = []
        
        if interest:
            parts.append(f"I'm sorry, we don't currently have {interest} products available.")
        else:
            parts.append("I'm sorry, I couldn't find any products matching your request.")
        
        if age:
            parts.append(f"Could you tell me about other interests for your {age}-year-old?")
        else:
            parts.append("Could you tell me about other interests they might have?")
        
        parts.append("I'd love to help you find the perfect gift!")
        
        return " ".join(parts)

    @staticmethod
    def _safe_load_json(payload: str) -> ExtractionResult:
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise OpenAIError("OpenAI returned an invalid JSON payload.") from exc
