"""WooCommerce REST API integration layer."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import requests
from requests import Response
from requests.auth import HTTPBasicAuth

from exceptions import WooCommerceError

logger = logging.getLogger(__name__)

Product = Dict[str, Any]


class WooCommerceService:
    def __init__(
        self,
        api_url: str,
        consumer_key: str,
        consumer_secret: str,
        brand_attribute_slug: str = "pa_brand",
    ) -> None:
        if not all([api_url, consumer_key, consumer_secret]):
            raise WooCommerceError("Missing WooCommerce API configuration.")

        self.api_url = api_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(consumer_key, consumer_secret)
        self.timeout = 10

        # Attribute slugs for filtering
        self.brand_attribute_slug = brand_attribute_slug
        self.age_attribute_slug = "pa_age"
        self.gender_attribute_slug = "pa_gender"
        
        # Attribute IDs and cached terms
        self.brand_attribute_id: Optional[int] = None
        self.brand_terms: Dict[str, Dict[str, Any]] = {}
        self.age_attribute_id: Optional[int] = None
        self.age_terms: Dict[str, Dict[str, Any]] = {}
        self.gender_attribute_id: Optional[int] = None
        self.gender_terms: Dict[str, Dict[str, Any]] = {}
        
        # Initialize attribute catalogs
        self._init_brand_catalog()
        self._init_age_catalog()
        self._init_gender_catalog()

    def search_products(self, params: Dict[str, Any]) -> List[Product]:
        """Search published products that match the derived parameters."""
        # Allow up to 100 products per request for better selection
        # Don't artificially limit - let caller decide
        requested_per_page = int(params.get("per_page", 20))
        per_page = min(requested_per_page, 100)  # WooCommerce API max is 100
        
        query = {
            "status": "publish",
            "per_page": per_page,
            "order": "desc",
            "orderby": "popularity",  # Popular products first
        }
        if search_term := params.get("search"):
            query["search"] = search_term
        if min_price := params.get("min_price"):
            query["min_price"] = min_price
        if max_price := params.get("max_price"):
            query["max_price"] = max_price
        if category := params.get("category"):
            query["category"] = category
        if attribute := params.get("attribute"):
            query["attribute"] = attribute
        if attribute_term := params.get("attribute_term"):
            query["attribute_term"] = attribute_term

        response = self._request("GET", "/products", params=query)
        data = response.json()
        products = [self._map_product(item) for item in data]
        
        # Filter out ONLY obvious test/sample products
        # Be conservative - only remove clear test products, not legitimate toys
        filtered = []
        for p in products:
            if not p:
                continue
            if self._is_test_product(p):
                logger.debug(f"Filtered out test product: {p.get('name', 'Unknown')}")
                continue
            # REMOVED: _is_non_toy_product filter - too aggressive, filtering out real toys
            filtered.append(p)
        
        logger.info(f"Product search returned {len(filtered)} products after filtering (from {len(data)} raw)")
        return filtered

    def create_coupon(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a coupon code via WooCommerce."""
        response = self._request("POST", "/coupons", json=payload)
        coupon_data = response.json()
        
        # Normalize date_expires to date-only format (YYYY-MM-DD)
        # WooCommerce returns ISO format (YYYY-MM-DDTHH:MM:SS)
        # but we want consistent date-only format for display
        if "date_expires" in coupon_data and coupon_data["date_expires"]:
            # Extract just the date part (before 'T')
            date_str = coupon_data["date_expires"]
            if "T" in date_str:
                coupon_data["date_expires"] = date_str.split("T")[0]
        
        return coupon_data

    def match_brand(self, text: str) -> Optional[Dict[str, Any]]:
        """Attempt to match brand names from user text to WooCommerce brand terms."""
        if not text or not self.brand_terms:
            return None
        normalized_text = f" {self._normalize_brand_key(text)} "
        for key, info in self.brand_terms.items():
            if f" {key} " in normalized_text:
                return info
        return None
    
    def search_by_attributes(
        self,
        age_slug: Optional[str] = None,
        gender_slug: Optional[str] = None,
        brand_slug: Optional[str] = None,
        per_page: int = 50
    ) -> List[Product]:
        """
        Search products filtered by WooCommerce attributes.
        This is the new intelligent search method using structured data.
        
        Args:
            age_slug: Age attribute term slug (e.g., "preschool-age-3-5")
            gender_slug: Gender attribute term slug (e.g., "boys", "girls")
            brand_slug: Brand attribute term slug (e.g., "hot-wheels")
            per_page: Maximum products to return
            
        Returns:
            List of products matching the attribute filters
        """
        # Start with base query
        query = {
            "status": "publish",
            "per_page": min(per_page, 100),
            "order": "desc",
            "orderby": "popularity",  # Popular products first
        }
        
        # WooCommerce API supports ONE attribute filter directly
        # For multiple attributes, we fetch and filter client-side
        if age_slug:
            query["attribute"] = "age"
            query["attribute_term"] = age_slug
            logger.info(f"Searching with age attribute: {age_slug}")
        
        # Fetch products from WooCommerce
        try:
            response = self._request("GET", "/products", params=query)
            data = response.json()
            products = [self._map_product(item) for item in data]
            
            # Filter out test/sample products
            products = [p for p in products if p and not self._is_test_product(p) and not self._is_non_toy_product(p)]
            
            # Apply additional attribute filters client-side
            if gender_slug:
                products = self._filter_by_attribute(products, "gender", gender_slug)
                logger.info(f"Filtered by gender '{gender_slug}': {len(products)} products")
            
            if brand_slug:
                products = self._filter_by_attribute(products, "brands", brand_slug)
                logger.info(f"Filtered by brand '{brand_slug}': {len(products)} products")
            
            return products
            
        except Exception as e:
            logger.error(f"Attribute search failed: {e}")
            return []
    
    def _filter_by_attribute(
        self,
        products: List[Product],
        attribute_name: str,
        term_slug: str
    ) -> List[Product]:
        """
        Client-side filter for products by attribute term.
        Needed because WooCommerce API doesn't support multiple attribute filters in one query.
        """
        filtered = []
        for product in products:
            attributes = product.get("attributes", [])
            for attr in attributes:
                attr_slug = attr.get("slug", "")
                # Match attribute name (remove 'pa_' prefix if present) - CASE INSENSITIVE
                normalized_attr_slug = attr_slug.replace("pa_", "").lower()
                if normalized_attr_slug == attribute_name.lower():
                    # Check if product has the desired term
                    options = attr.get("options", [])
                    # Normalize options for comparison
                    normalized_options = [
                        opt.lower().replace(" ", "-").replace("&", "").replace("(", "").replace(")", "")
                        for opt in options
                    ]
                    normalized_term = term_slug.lower().replace(" ", "-")
                    
                    if any(normalized_term in opt for opt in normalized_options):
                        filtered.append(product)
                        break
        
        return filtered
    
    def map_age_to_attribute(self, age: float) -> Optional[str]:
        """
        Map user's child age to WooCommerce age attribute term slug.
        
        Based on client's WooCommerce age categories:
        - Infant & Toddlers (Age 0-3)
        - Preschool (Age 3-5)
        - School Age (Age 5-12)
        - Teen Age & Above (Age 12+)
        
        Args:
            age: Child's age in years
            
        Returns:
            WooCommerce age attribute term slug or None
        """
        # Age range mappings to WooCommerce term slugs
        # These match the client's actual WooCommerce attribute structure
        if age < 3:
            return "infant-toddlers-age-0-3"
        elif 3 <= age < 5:
            return "preschool-age-3-5"
        elif 5 <= age < 12:
            return "school-age-age5-12"
        elif age >= 12:
            return "teen-age-above-age-12"
        
        return "school-age-age5-12"  # Safe default
    
    def map_gender_to_attribute(self, gender: Optional[str]) -> Optional[str]:
        """
        Map extracted gender to WooCommerce gender attribute term slug.
        
        Based on client's WooCommerce gender categories:
        - Boys
        - Girls
        - Kids Unisex
        - Baby & Toddlers
        
        Args:
            gender: Inferred gender ("male", "female", "neutral", etc.)
            
        Returns:
            WooCommerce gender attribute term slug or None
        """
        if not gender:
            return None
        
        gender_lower = gender.lower()
        
        # Map common gender terms to WooCommerce attribute slugs
        gender_map = {
            "male": "boys",
            "boy": "boys",
            "boys": "boys",
            "female": "girls",
            "girl": "girls",
            "girls": "girls",
            "neutral": "kids-unisex",
            "unisex": "kids-unisex",
            "baby": "baby-toddlers",
            "toddler": "baby-toddlers",
        }
        
        return gender_map.get(gender_lower)

    def _init_brand_catalog(self) -> None:
        try:
            attr_id = self._resolve_brand_attribute_id()
        except WooCommerceError:
            return

        if not attr_id:
            return

        self.brand_attribute_id = attr_id
        try:
            self.brand_terms = self._fetch_attribute_terms(attr_id)
        except WooCommerceError:
            self.brand_terms = {}
    
    def _init_age_catalog(self) -> None:
        """Initialize age attribute catalog."""
        try:
            attr_id = self._resolve_attribute_id("age")
            if not attr_id:
                return
            
            self.age_attribute_id = attr_id
            self.age_terms = self._fetch_attribute_terms(attr_id)
        except WooCommerceError:
            self.age_terms = {}
    
    def _init_gender_catalog(self) -> None:
        """Initialize gender attribute catalog."""
        try:
            attr_id = self._resolve_attribute_id("gender")
            if not attr_id:
                return
            
            self.gender_attribute_id = attr_id
            self.gender_terms = self._fetch_attribute_terms(attr_id)
        except WooCommerceError:
            self.gender_terms = {}
    
    def _resolve_attribute_id(self, attribute_name: str) -> Optional[int]:
        """Generic method to resolve attribute ID by name."""
        try:
            response = self._request("GET", "/products/attributes")
            attributes = response.json()
            
            # Look for exact match by slug or name
            for attr in attributes:
                if (attr.get("slug", "").lower() == attribute_name.lower() or
                    attr.get("name", "").lower() == attribute_name.lower()):
                    return attr.get("id")
            
            return None
        except Exception:
            return None

    def _resolve_brand_attribute_id(self) -> Optional[int]:
        response = self._request("GET", "/products/attributes")
        attributes = response.json()

        exact_match = next(
            (
                attr
                for attr in attributes
                if attr.get("slug") == self.brand_attribute_slug
            ),
            None,
        )
        if exact_match:
            return exact_match.get("id")

        fallback_match = next(
            (
                attr
                for attr in attributes
                if "brand" in (attr.get("slug") or attr.get("name", "")).lower()
            ),
            None,
        )
        return fallback_match.get("id") if fallback_match else None

    def _fetch_attribute_terms(self, attribute_id: int) -> Dict[str, Dict[str, Any]]:
        terms: Dict[str, Dict[str, Any]] = {}
        page = 1
        per_page = 100

        while True:
            response = self._request(
                "GET",
                f"/products/attributes/{attribute_id}/terms",
                params={"per_page": per_page, "page": page},
            )
            data = response.json()
            if not data:
                break
            for term in data:
                key = self._normalize_brand_key(term.get("name", ""))
                if not key:
                    continue
                terms[key] = {
                    "id": term.get("id"),
                    "name": term.get("name"),
                    "slug": term.get("slug"),
                    "attribute_slug": self.brand_attribute_slug,
                }
            if len(data) < per_page:
                break
            page += 1

        return terms

    @staticmethod
    def _normalize_brand_key(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Response:
        url = f"{self.api_url}{path}"
        try:
            response = self.session.request(
                method,
                url,
                params=params,
                json=json,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise WooCommerceError(f"WooCommerce request failed: {exc}") from exc
        return response

    def _is_non_toy_product(self, product: Product) -> bool:
        name = product.get("name", "").lower()
        description = product.get("description", "").lower() or ""
        
        # Define keywords that indicate NON-TOY products (electronics, household items, etc.)
        # DO NOT include toy-related keywords here!
        non_toy_keywords = [
            "battery", "batteries", "charger", "power adapter", "usb cable",
            "plug", "adapter", "earphone", "headphone", "speaker", "microphone",
            "case", "cover", "screen protector", "power bank", "card reader",
            "storage", "memory card", "sim card", "router", "modem", "webcam",
            "light bulb", "led strip", "extension cord", "surge protector",
            "cleaning kit", "tool set", "repair kit", "kitchenware", "cookware",
            "dinnerware", "cutlery", "mug", "cup", "bottle", "flask",
            "towel", "linen", "bedding", "curtain", "rug", "mat",
            "detergent", "cleaner", "laundry", "soap", "shampoo", "lotion",
            "perfume", "fragrance", "cosmetic", "cream", "serum",
            "razor", "shaver", "toothbrush electric", "toothpaste", "deodorant",
            "air freshener", "candle", "diffuser", "plant", "flower",
            "fertilizer", "soil", "seed", "pest control", "insect repellent",
            "pet food", "cat litter", "dog bed", "fish tank", "bird cage",
            "car mat", "tire", "wiper blade", "oil filter", "air filter",
            "brake pad", "spark plug", "engine oil", "coolant", "car wax",
            "polisher", "vacuum cleaner", "mop", "bucket", "broom", "dustpan",
            "garbage bag", "tissue", "paper towel", "hand sanitizer",
            "face mask", "thermometer", "blood pressure monitor", "first aid kit",
            "vitamin", "supplement", "medicine", "pain reliever", "antiseptic",
            "bandage", "disinfectant", "gloves", "sanitizer", "ointment",
            "spray", "gel", "pad", "strip", "patch", "wrap", "tape",
            "holder", "stand", "mount", "clip", "organizer", "rack",
            "shelf", "cabinet", "drawer", "box", "bin", "container",
            "bag", "pouch", "wallet", "keychain", "pen", "pencil",
            "notebook", "diary", "calendar", "planner", "sticker", "label",
            "marker", "highlighter", "eraser", "sharpener", "ruler",
            "scissors", "glue", "tape dispenser", "stapler", "punch",
            "calculator", "printer", "scanner", "projector", "monitor",
            "keyboard", "mouse", "webcam", "headset", "webcam", "microphone",
            "usb hub", "card reader", "flash drive", "external hard drive",
            "ssd", "power strip", "extension cable", "router", "modem",
            "network cable", "ethernet cable", "hdmi cable", "vga cable",
            "displayport cable", "audio cable", "rca cable", "optical cable",
            "coaxial cable", "antenna cable", "sata cable", "ide cable",
            "power cable", "charging cable", "data cable", "adapter cable",
            "converter", "splitter", "switch", "hub", "docking station",
            "kettle", "toaster", "blender", "mixer", "food processor",
            "microwave", "oven", "stove", "fridge", "freezer", "dishwasher",
            "washing machine", "dryer", "iron", "steamer", "sewing machine",
            "fan", "heater", "air conditioner", "purifier", "humidifier",
            "dehumidifier", "water filter", "coffee machine", "espresso maker",
            "grinder", "dispenser", "storage jar", "spice rack", "utensil holder",
            "cutting board", "knife set", "chopping board", "measuring cup",
            "measuring spoon", "colander", "sieve", "whisk", "spatula",
            "ladle", "tongs", "grater", "peeler", "can opener", "bottle opener",
            "corkscrew", "funnel", "strainer", "masher", "tenderizer",
            "meat thermometer", "kitchen scale", "timer", "alarm clock",
            "wall clock", "desk clock", "table lamp", "floor lamp",
            "ceiling light", "chandelier", "spotlight", "downlight",
            "track light", "strip light", "fairy light", "string light",
            "projector light", "party light", "disco light", "laser light",
            "strobe light", "fog machine", "bubble machine", "snow machine",
            "wind machine", "smoke machine", "haze machine", "confetti machine",
            "uv light", "black light", "flashlight", "torch", "lantern",
            "headlamp", "camping light", "tent light", "work light",
            "inspection lamp", "emergency light", "night light", "reading light",
            "desk light", "clip light", "book light", "magnifying lamp",
            "magnifying glass", "microscope", "telescope", "binocular",
            "monocular", "compass", "altimeter", "barometer", "weather station",
            "gps tracker", "fitness tracker", "heart rate monitor", "pedometer",
            "stopwatch", "timer", "calculator", "currency detector",
            "label printer", "shredder", "laminator", "binding machine",
            "paper cutter", "hole punch", "stapler", "staple remover",
            "folder", "file", "binder", "clip board", "whiteboard",
            "blackboard", "cork board", "display board", "easel", "flip chart",
            "projector screen", "speaker stand", "microphone stand",
            "music stand", "camera tripod", "light stand", "backdrop stand",
            "reflector", "softbox", "umbrella", "flash diffuser", "gel filter",
            "camera bag", "lens bag", "laptop bag", "backpack", "travel bag",
            "duffel bag", "tote bag", "shopping bag", "cooler bag",
            "lunch bag", "storage bag", "vacuum bag", "ziplock bag",
            "garbage can", "recycling bin", "waste basket", "litter bin",
            "ash tray", "umbrella stand", "coat rack", "shoe rack",
            "hat stand", "jewelry box", "watch winder", "tie rack",
            "belt rack", "scarf hanger", "hanger", "clothesline",
            "drying rack", "laundry basket", "hamper", "ironing board",
            "iron cover", "sewing kit", "yarn", "needle", "thread",
            "fabric", "pattern", "scissors", "tape measure", "pin cushion",
            "thimble", "seam ripper", "rotary cutter", "cutting mat",
            "quilting ruler", "template", "stencil", "embroidery hoop",
            "cross stitch kit", "diamond painting", "paint by numbers",
            "coloring book", "sketchbook", "drawing pad", "canvas",
            "paint set", "brush set", "palette", "easel", "art paper",
            "craft kit", "model kit", "puzzle", "jigsaw puzzle", "board game",
            "card game", "dice game", "party game", "magic trick",
            "science kit", "robot kit", "coding toy", "drone", "rc car",
            "rc helicopter", "rc boat", "action figure", "doll", "barbie",
            "lego", "playmobil", "hot wheels", "matchbox", "nerf", "hasbro",
            "mattel", "disney", "marvel", "star wars", "pokemon",
            "superman", "batman", "spiderman", "wonder woman", "captain america",
            "iron man", "hulk", "thor", "black panther", "minnie mouse",
            "mickey mouse", "frozen", "elsa", "anna", "olaf", "paw patrol",
            "peppa pig", "thomas and friends", "brio", "fisher-price",
            "vtech", "leapfrog", "crayola", "play-doh", "kinetic sand",
            "slime", "fidget spinner", "pop it", "squishy", "plush toy",
            "stuffed animal", "teddy bear", "dollhouse", "play kitchen",
            "tool bench", "art easel", "building blocks", "magnetic tiles",
            "train set", "race track", "robot", "dinosaur toy", "animal toy",
            "car toy", "truck toy", "plane toy", "boat toy", "helicopter toy",
            "toy weapon", "blaster", "sword", "shield", "bow and arrow",
            "water gun", "bubbles", "kite", "frisbee", "ball", "jump rope",
            "hula hoop", "scooter", "skateboard", "roller skates",
            "bicycle", "tricycle", "balance bike", "ride-on toy", "swing set",
            "slide", "trampoline", "playhouse", "sandpit", "water table",
            "fishing rod", "fishing net", "bucket and spade", "beach toy",
            "pool toy", "inflatable toy", "water slide", "sprinkler",
            "garden tool", "watering can", "gloves", "potting mix",
            "gardening set", "flower pot", "seed kit", "compost bin",
            "garden hose", "hose reel", "nozzle", "sprayer", "irrigation kit",
            "bird feeder", "bird house", "insect hotel", "butterfly house",
            "worm farm", "composter", "rain gauge", "weather vane",
            "wind chimes", "bird bath", "gnome", "statue", "fountain",
            "pond liner", "pond pump", "filter", "uv clarifier",
            "water treatment", "fish food", "aquarium", "terrarium",
            "vivarium", "habitat", "substrate", "heater", "light", "filter",
            "pump", "air stone", "ornament", "decoration", "background",
            "plant", "rock", "wood", "cave", "hideout", "gravel", "sand",
            "net", "scraper", "brush", "siphon", "vacuum", "test kit",
            "medication", "conditioner", "water conditioner", "bacteria starter",
            "algae remover", "snail remover", "plant food", "co2 system",
            "diffuser", "regulator", "bubble counter", "check valve",
            "drop checker", "thermometer", "chiller", "fan", "heater",
            "wavemaker", "protein skimmer", "reactor", "sump", "refugium",
            "dosing pump", "auto top off", "salt mix", "ro/di unit",
            "tds meter", "aquarium cabinet", "stand", "hood", "canopy",
            "lighting fixture", "led light", "t5 light", "metal halide light",
            "filter media", "sponge filter", "power filter", "hang on back filter",
            "canister filter", "undergravel filter", "internal filter",
            "external filter", "sump filter", "refugium filter", "wet/dry filter",
            "fluidized bed filter", "diatom filter", "uv sterilizer",
            "ozone generator", "protein skimmer pump", "return pump",
            "circulation pump", "air pump", "water pump", "dosing pump",
            "auto top off pump", "saltwater test kit", "freshwater test kit",
            "ammonia test kit", "nitrite test kit", "nitrate test kit",
            "ph test kit", "kh test kit", "gh test kit", "calcium test kit",
            "magnesium test kit", "alkalinity test kit", "phosphate test kit",
            "silicate test kit", "copper test kit", "iron test kit",
            "iodine test kit", "strontium test kit", "boron test kit",
            "potassium test kit", "trace element test kit", "redox test kit",
            "salinity refractometer", "hydrometer", "thermometer", "timer",
            "controller", "monitor", "datalogger", "alarm system",
            "auto feeder", "auto doser", "wavemaker controller", "lighting controller",
            "temperature controller", "ph controller", "redox controller",
            "dosing controller", "auto top off controller", "level sensor",
            "flow sensor", "pressure sensor", "temperature sensor", "ph sensor",
            "redox sensor", "conductivity sensor", "orp sensor", "dissolved oxygen sensor",
            "co2 sensor", "humidity sensor", "light sensor", "water leak sensor",
            "smoke detector", "gas detector", "carbon monoxide detector",
            "motion sensor", "door sensor", "window sensor", "glass break sensor",
            "vibration sensor", "shock sensor", "panic button", "siren",
            "strobe light", "alarm panel", "keypad", "remote control",
            "ip camera", "security camera", "cctv camera", "dome camera",
            "bullet camera", "ptz camera", "hidden camera", "spy camera",
            "nvr", "dvr", "video recorder", "monitor", "tv", "projector",
            "projector screen", "sound bar", "home theater system", "dvd player",
            "blu-ray player", "streaming device", "media player", "gaming console",
            "retro console", "handheld console", "vr headset", "ar headset",
            "smartwatch", "fitness tracker", "earbuds", "headphones",
            "bluetooth speaker", "portable speaker", "smart speaker",
            "google home", "amazon echo", "smart display", "smart hub",
            "smart plug", "smart switch", "smart light bulb", "smart lock",
            "smart thermostat", "smart sensor", "smart curtain", "smart blind",
            "smart window", "smart door", "smart garage door", "smart doorbell",
            "smart security camera", "smart smoke detector", "smart carbon monoxide detector",
            "smart water leak detector", "smart motion sensor", "smart door sensor",
            "smart window sensor", "smart glass break sensor", "smart vibration sensor",
            "smart panic button", "smart siren", "smart alarm panel", "smart keypad",
            "smart remote control", "smart universal remote", "smart ir blaster",
            "smart rf blaster", "smart home gateway", "smart home bridge",
            "smart home controller", "smart home app", "smart home platform",
            "smart home automation", "smart home ecosystem", "smart home device",
            "smart home solution", "smart home system", "smart home hub",
            "smart home assistant", "smart home security", "smart home lighting",
            "smart home climate control", "smart home entertainment", "smart home convenience",
            "smart home energy management", "smart home safety", "smart home monitoring",
            "smart home health care", "smart home elderly care", "smart home pet care",
            "smart home garden care", "smart home water management", "smart home air quality",
            "smart home security camera", "smart home video doorbell", "smart home motion sensor",
            "smart home door sensor", "smart home window sensor", "smart home glass break sensor",
            "smart home vibration sensor", "smart home panic button", "smart home siren",
            "smart home alarm panel", "smart home keypad", "smart home remote control",
            "smart home universal remote", "smart home ir blaster", "smart home rf blaster",
            "smart home gateway", "smart home bridge", "smart home controller",
            "smart home app", "smart home platform", "smart home automation",
            "smart home ecosystem", "smart home device", "smart home solution",
            "smart home system", "smart home hub", "smart home assistant",
            "smart home security", "smart home lighting", "smart home climate control",
            "smart home entertainment", "smart home convenience", "smart home energy management",
            "smart home safety", "smart home monitoring", "smart home health care",
            "smart home elderly care", "smart home pet care", "smart home garden care",
            "smart home water management", "smart home air quality",
            "smart home security camera", "smart home video doorbell", "smart home motion sensor",
            "smart home door sensor", "smart home window sensor", "smart home glass break sensor",
            "smart home vibration sensor", "smart home panic button", "smart home siren",
            "smart home alarm panel", "smart home keypad", "smart home remote control",
            "smart home universal remote", "smart home ir blaster", "smart home rf blaster",
            "smart home gateway", "smart home bridge", "smart home controller",
            "smart home app", "smart home platform", "smart home automation",
            "smart home ecosystem", "smart home device", "smart home solution",
            "smart home system", "smart home hub", "smart home assistant",
            "smart home security", "smart home lighting", "smart home climate control",
            "smart home entertainment", "smart home convenience", "smart home energy management",
            "smart home safety", "smart home monitoring", "smart home health care",
            "smart home elderly care", "smart home pet care", "smart home garden care",
            "smart home water management", "smart home air quality"
        ]

        for keyword in non_toy_keywords:
            if keyword in name or keyword in description:
                return True
        return False

    @staticmethod
    def _map_product(item: Dict[str, Any]) -> Product:
        """Map WooCommerce product data to our internal format with encoding fixes."""
        images = item.get("images") or []
        first_image = images[0]["src"] if images else None
        stock_qty = item.get("stock_quantity")
        
        # Clean product name from encoding issues
        name = item.get("name", "")
        name = WooCommerceService._fix_encoding(name)
        
        # Clean description
        description = item.get("short_description", "")
        description = WooCommerceService._fix_encoding(description)
        
        tags = [
            {"id": tag.get("id"), "name": tag.get("name"), "slug": tag.get("slug")}
            for tag in item.get("tags", [])
        ]
        categories = [
            {
                "id": cat.get("id"),
                "name": cat.get("name"),
                "slug": cat.get("slug"),
            }
            for cat in item.get("categories", [])
        ]
        attributes = [
            {
                "id": attr.get("id"),
                "name": attr.get("name"),
                "slug": attr.get("slug"),
                "options": attr.get("options"),
            }
            for attr in item.get("attributes", [])
        ]
        return {
            "id": item.get("id"),
            "name": name,
            "price": item.get("price"),
            "currency": item.get("price_html"),
            "product_url": item.get("permalink"),  # Frontend expects 'product_url'
            "permalink": item.get("permalink"),    # Keep for backward compatibility
            "description": description,
            "image_url": first_image,              # Frontend expects 'image_url'
            "image": first_image,                  # Keep for backward compatibility
            "stock_status": item.get("stock_status"),
            "stock_quantity": stock_qty,
            "vendor": item.get("store", {}).get("name") if item.get("store") else None,
            "categories": categories,
            "tags": tags,
            "attributes": attributes,
            "meta_data": item.get("meta_data", []),
        }

    @staticmethod
    def _is_test_product(product: Product) -> bool:
        """
        Filter out test/sample products from results.
        Only excludes if the product name is EXACTLY or PRIMARILY "test", "testing", "sample" etc.
        Does NOT exclude products that merely contain these words (e.g., "Best Testing Kit for Kids").
        """
        name = (product.get("name") or "").lower().strip()
        
        if not name:
            return False
        
        # Exact matches (case-insensitive)
        exact_test_names = [
            "test", "testing", "sample", "test product", "sample product",
            "test 1", "test 2", "sample 1", "sample 2", "test item"
        ]
        
        if name in exact_test_names:
            return True
        
        # Check if name STARTS with test/sample (followed by space or number)
        test_prefixes = ["test ", "testing ", "sample "]
        if any(name.startswith(prefix) for prefix in test_prefixes):
            # But allow if it's followed by more descriptive text (>3 words)
            words = name.split()
            if len(words) <= 2:  # "test product", "sample 1"
                return True
        
        return False
    
    @staticmethod
    def _fix_encoding(text: str) -> str:
        """
        Fix common UTF-8 encoding issues in WooCommerce data.
        Handles double-encoded UTF-8 and special characters.
        """
        if not text:
            return text
        
        import unicodedata
        
        # Step 1: Fix double-encoded UTF-8 (common WooCommerce issue)
        # Try to decode as latin-1 and re-encode as utf-8
        try:
            # If text was incorrectly decoded, this will fix it
            text_bytes = text.encode('latin-1')
            text = text_bytes.decode('utf-8')
        except (UnicodeDecodeError, UnicodeEncodeError):
            # Text is already correctly encoded, continue
            pass
        
        # Step 2: Normalize Unicode (decompose combined characters)
        text = unicodedata.normalize('NFKD', text)
        
        # Step 3: Replace common problematic characters with ASCII equivalents
        replacements = [
            ('\u2014', '-'),      # Em dash
            ('\u2013', '-'),      # En dash
            ('\u2019', "'"),      # Right single quote
            ('\u2018', "'"),      # Left single quote
            ('\u201c', '"'),      # Left double quote
            ('\u201d', '"'),      # Right double quote
            ('\u2022', '-'),      # Bullet point
            ('\u2026', '...'),    # Ellipsis
            ('\u2011', '-'),      # Non-breaking hyphen
            ('\u00ad', ''),       # Soft hyphen (invisible)
            ('\u200b', ''),       # Zero-width space
            ('\u200c', ''),       # Zero-width non-joiner
            ('\u200d', ''),       # Zero-width joiner
            ('\u00a0', ' '),      # Non-breaking space
        ]
        
        for old_char, new_char in replacements:
            text = text.replace(old_char, new_char)
        
        # Step 4: Remove any remaining non-printable characters except newlines/tabs
        text = ''.join(
            char for char in text 
            if unicodedata.category(char)[0] != 'C' or char in '\n\r\t'
        )
        
        # Step 5: Normalize back to composed form
        text = unicodedata.normalize('NFC', text)
        
        return text.strip()

