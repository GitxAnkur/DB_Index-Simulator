# Dataset Validation Report

**Dataset:** `synthetic_products_100000.csv`  
**Validated:** 2026-11-21T12:34:12+00:00  
**Rows:** 100,000  
**Overall status:** PASS

The original CSV was not modified. It was read with UTF-8 BOM handling and validated before import.

## Checks

| Check | Result |
|---|---|
| `row_count_exact` | PASS |
| `unique_product_ids` | PASS |
| `ten_categories` | PASS |
| `category_distribution` | PASS |
| `no_missing_values` | PASS |
| `prices_numeric_nonnegative` | PASS |
| `ratings_in_range` | PASS |
| `stock_nonnegative` | PASS |
| `no_duplicate_records` | PASS |
| `product_id_format` | PASS |
| `id_range_complete` | PASS |

## Category distribution

| Category | Products | Expected |
|---|---:|---:|
| Camera | 10,000 | 10,000 |
| Gaming Accessories | 10,000 | 10,000 |
| Headphones | 10,000 | 10,000 |
| Keyboard | 10,000 | 10,000 |
| Laptop | 10,000 | 10,000 |
| Monitor | 10,000 | 10,000 |
| Smartphone | 10,000 | 10,000 |
| Smartwatch | 10,000 | 10,000 |
| Speaker | 10,000 | 10,000 |
| Tablet | 10,000 | 10,000 |

## Data quality

- Unique product IDs: **100,000**
- Duplicate product IDs: **0**
- Duplicate full records: **0**
- Missing values: **0**
- Distinct brands: **45**
- Distinct use cases: **39**
- Colours: Black, Blue, Green, Grey, Red, Silver, White
- Price (INR): min **501.00**, max **279,993.00**, mean **60,490.48**, invalid/negative **0**
- Rating: min **2.8**, max **5.0**, mean **3.898**, out of range **0**
- Stock: min **0**, max **150**, negative **0**

## Notes

- The supplied category labels are singular (for example 'Laptop'). They are preserved exactly in PostgreSQL; the UI displays the same labels.
- Product names are intentionally non-unique; the primary key is product_id and no duplicate rows exist.
- The CSV has a UTF-8 BOM in its header; imports use utf-8-sig.
- image_key and image_prompt are preserved for a future image system; no images are generated in this version.
