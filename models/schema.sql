-- Food Memory Bot Database Schema

CREATE TABLE IF NOT EXISTS restaurants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    google_place_id TEXT UNIQUE,
    address TEXT,
    latitude REAL,
    longitude REAL,
    cuisine TEXT,
    price_level INTEGER,  -- 0-4 scale from Google Places
    dine_in BOOLEAN DEFAULT TRUE,
    takeout BOOLEAN DEFAULT FALSE,
    delivery BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    restaurant_id INTEGER NOT NULL,
    user_name TEXT,
    user_telegram_id INTEGER,
    dish TEXT,
    exact_order TEXT,
    rating REAL,  -- Optional numeric rating
    notes TEXT,
    sentiment TEXT CHECK(sentiment IN ('positive', 'negative', 'neutral', 'mixed')),
    sentiment_score REAL,  -- -1.0 to 1.0
    tags TEXT,  -- JSON array of tags
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (restaurant_id) REFERENCES restaurants(id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_restaurants_name ON restaurants(name);
CREATE INDEX IF NOT EXISTS idx_restaurants_cuisine ON restaurants(cuisine);
CREATE INDEX IF NOT EXISTS idx_entries_restaurant_id ON entries(restaurant_id);
CREATE INDEX IF NOT EXISTS idx_entries_user_telegram_id ON entries(user_telegram_id);
CREATE INDEX IF NOT EXISTS idx_entries_sentiment ON entries(sentiment);
CREATE INDEX IF NOT EXISTS idx_entries_created_at ON entries(created_at);
