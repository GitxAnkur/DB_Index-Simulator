-- Schema for the product search benchmarking system.
-- PostgreSQL 16+ and pgvector are required.

CREATE EXTENSION IF NOT EXISTS vector;

DROP TABLE IF EXISTS products CASCADE;

CREATE TABLE products (
    product_id       VARCHAR(10) PRIMARY KEY,
    name             TEXT        NOT NULL,
    category         TEXT        NOT NULL,
    brand            TEXT        NOT NULL,
    price_inr        NUMERIC(12, 2) NOT NULL CHECK (price_inr >= 0),
    color            TEXT,
    rating           NUMERIC(2, 1) CHECK (rating >= 0 AND rating <= 5),
    stock_quantity   INTEGER     NOT NULL CHECK (stock_quantity >= 0),
    use_case         TEXT,
    specifications   TEXT,
    description      TEXT,
    tags             TEXT,
    image_key        TEXT,
    image_prompt     TEXT,
    embedding        VECTOR(384)
);

-- Single-column B-tree indexes (Method 2).
CREATE INDEX idx_products_price_btree    ON products USING btree (price_inr);
CREATE INDEX idx_products_category_btree ON products USING btree (category);
CREATE INDEX idx_products_rating_btree   ON products USING btree (rating);

-- Hash index used for brand equality (Method 3).
CREATE INDEX idx_products_brand_hash ON products USING hash (brand);

-- Multicolumn B-tree index (Method 4). Column order matters:
-- category is the leading column, followed by price and colour.
CREATE INDEX idx_products_category_price_color_btree
    ON products USING btree (category, price_inr, color);

-- HNSW vector index (Method 5). Built after embeddings are loaded by
-- scripts/generate_embeddings.py so that index construction is measured.
