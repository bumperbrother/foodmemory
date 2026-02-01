"""Database service for Food Memory Bot using async SQLite."""

import json
import aiosqlite
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


@dataclass
class Restaurant:
    """Restaurant data model."""
    id: int
    name: str
    google_place_id: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    cuisine: Optional[str] = None
    price_level: Optional[int] = None
    dine_in: bool = True
    takeout: bool = False
    delivery: bool = False


@dataclass
class Entry:
    """Food entry data model."""
    id: int
    restaurant_id: int
    user_name: Optional[str] = None
    user_telegram_id: Optional[int] = None
    dish: Optional[str] = None
    exact_order: Optional[str] = None
    rating: Optional[float] = None
    notes: Optional[str] = None
    sentiment: Optional[str] = None
    sentiment_score: Optional[float] = None
    tags: list[str] = None
    created_at: Optional[str] = None
    restaurant_name: Optional[str] = None  # For joined queries


class DatabaseService:
    """Async SQLite database operations."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        """Initialize database and create tables from schema."""
        schema_path = Path(__file__).parent.parent / "models" / "schema.sql"
        schema = schema_path.read_text()

        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(schema)
            await db.commit()

    async def _get_connection(self) -> aiosqlite.Connection:
        """Get or create database connection."""
        if self._connection is None:
            self._connection = await aiosqlite.connect(self.db_path)
            self._connection.row_factory = aiosqlite.Row
        return self._connection

    async def close(self) -> None:
        """Close database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None

    async def find_restaurant_by_name(self, name: str) -> Optional[Restaurant]:
        """Find restaurant by name using fuzzy matching."""
        db = await self._get_connection()
        # Try exact match first, then LIKE match
        cursor = await db.execute(
            "SELECT * FROM restaurants WHERE LOWER(name) = LOWER(?) LIMIT 1",
            (name,)
        )
        row = await cursor.fetchone()

        if not row:
            # Try partial match
            cursor = await db.execute(
                "SELECT * FROM restaurants WHERE LOWER(name) LIKE LOWER(?) LIMIT 1",
                (f"%{name}%",)
            )
            row = await cursor.fetchone()

        if row:
            return Restaurant(
                id=row["id"],
                name=row["name"],
                google_place_id=row["google_place_id"],
                address=row["address"],
                latitude=row["latitude"],
                longitude=row["longitude"],
                cuisine=row["cuisine"],
                price_level=row["price_level"],
                dine_in=bool(row["dine_in"]),
                takeout=bool(row["takeout"]),
                delivery=bool(row["delivery"]),
            )
        return None

    async def find_or_create_restaurant(
        self,
        name: str,
        google_place_id: Optional[str] = None,
        address: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        cuisine: Optional[str] = None,
        price_level: Optional[int] = None,
        dine_in: bool = True,
        takeout: bool = False,
        delivery: bool = False,
    ) -> Restaurant:
        """Find existing restaurant or create new one with Place data."""
        db = await self._get_connection()

        # Check if restaurant exists by google_place_id first
        if google_place_id:
            cursor = await db.execute(
                "SELECT * FROM restaurants WHERE google_place_id = ?",
                (google_place_id,)
            )
            row = await cursor.fetchone()
            if row:
                return Restaurant(
                    id=row["id"],
                    name=row["name"],
                    google_place_id=row["google_place_id"],
                    address=row["address"],
                    latitude=row["latitude"],
                    longitude=row["longitude"],
                    cuisine=row["cuisine"],
                    price_level=row["price_level"],
                    dine_in=bool(row["dine_in"]),
                    takeout=bool(row["takeout"]),
                    delivery=bool(row["delivery"]),
                )

        # Check by name
        existing = await self.find_restaurant_by_name(name)
        if existing:
            # Update with new Place data if we have it
            if google_place_id and not existing.google_place_id:
                await db.execute(
                    """UPDATE restaurants SET
                       google_place_id = ?, address = ?, latitude = ?, longitude = ?,
                       cuisine = COALESCE(?, cuisine), price_level = COALESCE(?, price_level),
                       dine_in = ?, takeout = ?, delivery = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (google_place_id, address, latitude, longitude, cuisine, price_level,
                     dine_in, takeout, delivery, existing.id)
                )
                await db.commit()
                existing.google_place_id = google_place_id
                existing.address = address
                existing.latitude = latitude
                existing.longitude = longitude
                existing.cuisine = cuisine or existing.cuisine
                existing.price_level = price_level or existing.price_level
                existing.dine_in = dine_in
                existing.takeout = takeout
                existing.delivery = delivery
            return existing

        # Create new restaurant
        cursor = await db.execute(
            """INSERT INTO restaurants
               (name, google_place_id, address, latitude, longitude, cuisine, price_level, dine_in, takeout, delivery)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, google_place_id, address, latitude, longitude, cuisine, price_level, dine_in, takeout, delivery)
        )
        await db.commit()

        return Restaurant(
            id=cursor.lastrowid,
            name=name,
            google_place_id=google_place_id,
            address=address,
            latitude=latitude,
            longitude=longitude,
            cuisine=cuisine,
            price_level=price_level,
            dine_in=dine_in,
            takeout=takeout,
            delivery=delivery,
        )

    async def add_entry(
        self,
        restaurant_id: int,
        user_name: Optional[str] = None,
        user_telegram_id: Optional[int] = None,
        dish: Optional[str] = None,
        exact_order: Optional[str] = None,
        rating: Optional[float] = None,
        notes: Optional[str] = None,
        sentiment: Optional[str] = None,
        sentiment_score: Optional[float] = None,
        tags: Optional[list[str]] = None,
    ) -> Entry:
        """Add a new food entry."""
        db = await self._get_connection()
        tags_json = json.dumps(tags) if tags else None

        cursor = await db.execute(
            """INSERT INTO entries
               (restaurant_id, user_name, user_telegram_id, dish, exact_order, rating, notes, sentiment, sentiment_score, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (restaurant_id, user_name, user_telegram_id, dish, exact_order, rating, notes, sentiment, sentiment_score, tags_json)
        )
        await db.commit()

        return Entry(
            id=cursor.lastrowid,
            restaurant_id=restaurant_id,
            user_name=user_name,
            user_telegram_id=user_telegram_id,
            dish=dish,
            exact_order=exact_order,
            rating=rating,
            notes=notes,
            sentiment=sentiment,
            sentiment_score=sentiment_score,
            tags=tags or [],
        )

    async def update_entry(self, entry_id: int, **kwargs) -> bool:
        """Update an existing entry with provided fields."""
        db = await self._get_connection()

        if "tags" in kwargs and kwargs["tags"] is not None:
            kwargs["tags"] = json.dumps(kwargs["tags"])

        set_clauses = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [entry_id]

        await db.execute(
            f"UPDATE entries SET {set_clauses} WHERE id = ?",
            values
        )
        await db.commit()
        return True

    async def get_entry(self, entry_id: int) -> Optional[Entry]:
        """Get entry by ID."""
        db = await self._get_connection()
        cursor = await db.execute(
            """SELECT e.*, r.name as restaurant_name FROM entries e
               JOIN restaurants r ON e.restaurant_id = r.id
               WHERE e.id = ?""",
            (entry_id,)
        )
        row = await cursor.fetchone()
        if row:
            tags = json.loads(row["tags"]) if row["tags"] else []
            return Entry(
                id=row["id"],
                restaurant_id=row["restaurant_id"],
                user_name=row["user_name"],
                user_telegram_id=row["user_telegram_id"],
                dish=row["dish"],
                exact_order=row["exact_order"],
                rating=row["rating"],
                notes=row["notes"],
                sentiment=row["sentiment"],
                sentiment_score=row["sentiment_score"],
                tags=tags,
                created_at=row["created_at"],
                restaurant_name=row["restaurant_name"],
            )
        return None

    async def get_entries_for_restaurant(self, restaurant_id: int, limit: int = 20) -> list[Entry]:
        """Get all entries for a specific restaurant."""
        db = await self._get_connection()
        cursor = await db.execute(
            """SELECT e.*, r.name as restaurant_name FROM entries e
               JOIN restaurants r ON e.restaurant_id = r.id
               WHERE e.restaurant_id = ?
               ORDER BY e.created_at DESC LIMIT ?""",
            (restaurant_id, limit)
        )
        rows = await cursor.fetchall()

        entries = []
        for row in rows:
            tags = json.loads(row["tags"]) if row["tags"] else []
            entries.append(Entry(
                id=row["id"],
                restaurant_id=row["restaurant_id"],
                user_name=row["user_name"],
                user_telegram_id=row["user_telegram_id"],
                dish=row["dish"],
                exact_order=row["exact_order"],
                rating=row["rating"],
                notes=row["notes"],
                sentiment=row["sentiment"],
                sentiment_score=row["sentiment_score"],
                tags=tags,
                created_at=row["created_at"],
                restaurant_name=row["restaurant_name"],
            ))
        return entries

    async def search_entries(
        self,
        cuisine: Optional[str] = None,
        sentiment: Optional[str] = None,
        user_telegram_id: Optional[int] = None,
        search_term: Optional[str] = None,
        limit: int = 20,
    ) -> list[Entry]:
        """Search entries with various filters."""
        db = await self._get_connection()

        query = """SELECT e.*, r.name as restaurant_name FROM entries e
                   JOIN restaurants r ON e.restaurant_id = r.id WHERE 1=1"""
        params = []

        if cuisine:
            query += " AND LOWER(r.cuisine) LIKE LOWER(?)"
            params.append(f"%{cuisine}%")

        if sentiment:
            query += " AND e.sentiment = ?"
            params.append(sentiment)

        if user_telegram_id:
            query += " AND e.user_telegram_id = ?"
            params.append(user_telegram_id)

        if search_term:
            query += " AND (LOWER(r.name) LIKE LOWER(?) OR LOWER(e.dish) LIKE LOWER(?) OR LOWER(e.notes) LIKE LOWER(?))"
            params.extend([f"%{search_term}%"] * 3)

        query += " ORDER BY e.created_at DESC LIMIT ?"
        params.append(limit)

        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()

        entries = []
        for row in rows:
            tags = json.loads(row["tags"]) if row["tags"] else []
            entries.append(Entry(
                id=row["id"],
                restaurant_id=row["restaurant_id"],
                user_name=row["user_name"],
                user_telegram_id=row["user_telegram_id"],
                dish=row["dish"],
                exact_order=row["exact_order"],
                rating=row["rating"],
                notes=row["notes"],
                sentiment=row["sentiment"],
                sentiment_score=row["sentiment_score"],
                tags=tags,
                created_at=row["created_at"],
                restaurant_name=row["restaurant_name"],
            ))
        return entries

    async def get_distinct_cuisines(self) -> list[str]:
        """Get list of distinct cuisines from saved restaurants."""
        db = await self._get_connection()
        cursor = await db.execute(
            "SELECT DISTINCT cuisine FROM restaurants WHERE cuisine IS NOT NULL AND cuisine != '' ORDER BY cuisine"
        )
        rows = await cursor.fetchall()
        return [row["cuisine"] for row in rows]

    async def get_random_positive_restaurant(
        self,
        cuisine: Optional[str] = None,
        exclude_ids: Optional[list[int]] = None,
    ) -> Optional[tuple[Restaurant, list[Entry]]]:
        """Get a random restaurant with positive sentiment entries."""
        db = await self._get_connection()

        query = """SELECT DISTINCT r.* FROM restaurants r
                   JOIN entries e ON r.id = e.restaurant_id
                   WHERE e.sentiment = 'positive'"""
        params = []

        if cuisine:
            query += " AND LOWER(r.cuisine) LIKE LOWER(?)"
            params.append(f"%{cuisine}%")

        if exclude_ids:
            placeholders = ",".join("?" * len(exclude_ids))
            query += f" AND r.id NOT IN ({placeholders})"
            params.extend(exclude_ids)

        query += " ORDER BY RANDOM() LIMIT 1"

        cursor = await db.execute(query, params)
        row = await cursor.fetchone()

        if not row:
            return None

        restaurant = Restaurant(
            id=row["id"],
            name=row["name"],
            google_place_id=row["google_place_id"],
            address=row["address"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            cuisine=row["cuisine"],
            price_level=row["price_level"],
            dine_in=bool(row["dine_in"]),
            takeout=bool(row["takeout"]),
            delivery=bool(row["delivery"]),
        )

        entries = await self.get_entries_for_restaurant(restaurant.id, limit=5)
        return restaurant, entries

    async def get_restaurant_by_name(self, name: str) -> Optional[Restaurant]:
        """Get restaurant by exact or partial name match."""
        return await self.find_restaurant_by_name(name)
