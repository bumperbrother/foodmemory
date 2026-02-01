"""Google Places API service for restaurant enrichment."""

import logging
from typing import Optional
from dataclasses import dataclass
import httpx

logger = logging.getLogger(__name__)

# Mapping from Google Place types to cuisine names
TYPE_TO_CUISINE = {
    "thai_restaurant": "Thai",
    "chinese_restaurant": "Chinese",
    "japanese_restaurant": "Japanese",
    "korean_restaurant": "Korean",
    "vietnamese_restaurant": "Vietnamese",
    "indian_restaurant": "Indian",
    "mexican_restaurant": "Mexican",
    "italian_restaurant": "Italian",
    "french_restaurant": "French",
    "american_restaurant": "American",
    "mediterranean_restaurant": "Mediterranean",
    "greek_restaurant": "Greek",
    "spanish_restaurant": "Spanish",
    "middle_eastern_restaurant": "Middle Eastern",
    "turkish_restaurant": "Turkish",
    "brazilian_restaurant": "Brazilian",
    "peruvian_restaurant": "Peruvian",
    "seafood_restaurant": "Seafood",
    "steak_house": "Steakhouse",
    "sushi_restaurant": "Sushi",
    "ramen_restaurant": "Ramen",
    "pizza_restaurant": "Pizza",
    "hamburger_restaurant": "Burgers",
    "fast_food_restaurant": "Fast Food",
    "cafe": "Cafe",
    "coffee_shop": "Coffee",
    "bakery": "Bakery",
    "ice_cream_shop": "Dessert",
    "bar": "Bar",
    "pub": "Pub",
    "brunch_restaurant": "Brunch",
    "breakfast_restaurant": "Breakfast",
    "buffet_restaurant": "Buffet",
    "vegan_restaurant": "Vegan",
    "vegetarian_restaurant": "Vegetarian",
}


@dataclass
class PlaceData:
    """Restaurant data from Google Places."""
    place_id: str
    name: str
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    cuisine: Optional[str] = None
    price_level: Optional[int] = None
    dine_in: bool = True
    takeout: bool = False
    delivery: bool = False


class PlacesService:
    """Google Places API integration."""

    BASE_URL = "https://places.googleapis.com/v1/places:searchText"

    def __init__(self, api_key: str, default_location: str = "Orange County, CA"):
        self.api_key = api_key
        self.default_location = default_location

    async def search_restaurant(
        self,
        name: str,
        location_hint: Optional[str] = None,
    ) -> Optional[PlaceData]:
        """Search for a restaurant by name and optional location.

        Args:
            name: Restaurant name to search for
            location_hint: Optional location to narrow search

        Returns:
            PlaceData if found, None otherwise
        """
        location = location_hint or self.default_location
        query = f"{name} restaurant {location}"

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location,places.types,places.priceLevel,places.dineIn,places.takeout,places.delivery",
        }

        body = {
            "textQuery": query,
            "maxResultCount": 1,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.BASE_URL,
                    headers=headers,
                    json=body,
                    timeout=10.0,
                )

                if response.status_code != 200:
                    logger.warning(f"Places API returned status {response.status_code}: {response.text}")
                    return None

                data = response.json()
                places = data.get("places", [])

                if not places:
                    logger.info(f"No places found for query: {query}")
                    return None

                place = places[0]
                return self._parse_place(place)

        except httpx.TimeoutException:
            logger.warning(f"Timeout searching for restaurant: {name}")
            return None
        except httpx.HTTPError as e:
            logger.error(f"HTTP error searching for restaurant: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error searching for restaurant: {e}")
            return None

    def _parse_place(self, place: dict) -> PlaceData:
        """Parse a Google Places API response into PlaceData."""
        place_id = place.get("id", "")
        name = place.get("displayName", {}).get("text", "")
        address = place.get("formattedAddress")

        location = place.get("location", {})
        latitude = location.get("latitude")
        longitude = location.get("longitude")

        # Extract cuisine from place types
        types = place.get("types", [])
        cuisine = self._extract_cuisine(types)

        # Parse price level (Google returns as string like "PRICE_LEVEL_MODERATE")
        price_level_str = place.get("priceLevel", "")
        price_level = self._parse_price_level(price_level_str)

        # Service options
        dine_in = place.get("dineIn", True)
        takeout = place.get("takeout", False)
        delivery = place.get("delivery", False)

        return PlaceData(
            place_id=place_id,
            name=name,
            address=address,
            latitude=latitude,
            longitude=longitude,
            cuisine=cuisine,
            price_level=price_level,
            dine_in=dine_in,
            takeout=takeout,
            delivery=delivery,
        )

    def _extract_cuisine(self, types: list[str]) -> Optional[str]:
        """Extract cuisine type from Google Place types."""
        for place_type in types:
            if place_type in TYPE_TO_CUISINE:
                return TYPE_TO_CUISINE[place_type]

        # Default to "Restaurant" if it's a food establishment but no specific type
        if "restaurant" in types or "food" in types:
            return "Restaurant"

        return None

    def _parse_price_level(self, price_level_str: str) -> Optional[int]:
        """Parse Google's price level string to integer."""
        mapping = {
            "PRICE_LEVEL_FREE": 0,
            "PRICE_LEVEL_INEXPENSIVE": 1,
            "PRICE_LEVEL_MODERATE": 2,
            "PRICE_LEVEL_EXPENSIVE": 3,
            "PRICE_LEVEL_VERY_EXPENSIVE": 4,
        }
        return mapping.get(price_level_str)
