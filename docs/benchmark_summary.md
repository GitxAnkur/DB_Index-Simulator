# Fixed-Suite Benchmark Summary

Generated: 2026-11-22T08:24:44+00:00  
Repetitions per method: 5  
Result limit: 10  
Statistic: median database execution time in milliseconds.

| Query | Full scan | B-tree | Hash | Composite | HNSW | Hybrid | Cached |
|---|---:|---:|---:|---:|---:|---:|---:|
| Samsung smartphone | 10.378 | 0.886 | 0.763 | 0.747 | 0.558 | 3.453 | 0.0 |
| Laptops | 11.504 | 2.641 | 2.489 | 2.689 | 0.547 | 0.514 | 0.0 |
| Laptop under 80000 | 9.839 | 1.711 | 1.599 | 1.609 | 0.7 | 0.658 | 0.0 |
| Black laptop under 80000 | 9.333 | 0.728 | 0.608 | 0.576 | 1.088 | 1.644 | 0.0 |
| Lightweight laptop for programming | 23.813 | 17.054 | 16.706 | 19.946 | 0.593 | 0.606 | 0.0 |
| Wireless headphones for travel | 15.783 | 20.6 | 20.666 | 22.073 | 0.597 | 0.577 | 0.0 |
| Gaming monitor under 30000 | 10.129 | 1.67 | 1.501 | 1.49 | 0.863 | 0.937 | 0.0 |

The cached method starts with a cache miss and then reports hits; its median is often 0 ms because most repetitions bypass the database.
HNSW and hybrid timings are database execution only; query embedding time is reported separately in the JSON/CSV.
