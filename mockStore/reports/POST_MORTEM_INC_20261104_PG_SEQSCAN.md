# Post-Mortem: INC-20261104-PG-SEQSCAN - PG_SLOW_QUERY_BREACH on postgres-live-telemetry

## Summary
- **Incident ID:** INC-20261104-PG-SEQSCAN
- **Vector:** VECTOR_A_DB
- **Service:** postgres-live-telemetry
- **Error Code:** PG_SLOW_QUERY_BREACH
- **Error:** P99 query latency spiked to 240.0ms (SLA threshold: 1000.0ms)
- **Status:** Resolved autonomously, verified in sandbox, ready to merge
- **Sandbox:** MODAL_CLOUD_POSTGRES_SANDBOX / sb-ZOlufMBBlX11w6yKo0Pp1k (5.64s)

## Impact
- Offending query repeatedly performed full-table I/O:
```sql
SELECT o.order_id, o.status, i.product_id, i.quantity FROM orders o JOIN order_items i ON o.order_id = i.order_id WHERE o.customer_id = %s;
```
- Production-equivalent latency: 240.0ms per execution
- CPU saturation: 94.2% baseline
- Estimated rows scanned per execution: ~29609 (orders) + ~50000 (order_items) vs Plan Rows 66, actual_rows 0 in production sample
- No covering index meant every customer lookup scanned all heap pages, inflating shared buffers and Hash Join memory overhead (startup cost 613.69).

## Root Cause Analysis
Root cause is missing indexes on both sides of the Hash Join. The inner Hash branch performs a Seq Scan on orders with Filter (customer_id = 639) because no btree index exists on orders(customer_id); only orders_pkey on order_id exists. The outer branch performs a full Seq Scan on order_items because no foreign-key index exists on order_items(order_id) to support Hash Cond (i.order_id = o.order_id).

Production plan (EXPLAIN):
- Hash Join (cost=1515.96, actual_rows=0)
- Seq Scan on order_items (cost=771.0, actual_rows=0)
- Hash (cost=613.23, actual_rows=0)
- Seq Scan on orders (cost=613.23, actual_rows=0) Filter: (customer_id = 639)

Total cost 1515.96 dominated by Seq Scan on order_items cost=771.0 (Plan Rows 50000) and Seq Scan on orders cost=613.23 (Plan Rows 37). Planner forced to hash ~37 rows after scanning ~29609 rows and probe against ~50000 rows. Extremely low selectivity with >99% rows discarded after I/O.

## Remediation - Verified DDL Migration
Safe online migration with CONCURRENTLY to avoid blocking writes:
```sql
-- Safe migration SQL
SET statement_timeout = '30s';
SET lock_timeout = '5s';
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_customer_id ON public.orders USING btree (customer_id) INCLUDE (order_id, status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_items_order_id ON public.order_items USING btree (order_id) INCLUDE (product_id, quantity);
```
Note: Original verified_patch contained a third duplicate statement `CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_items_order_id ON order_items (order_id);` which is a redundant no-op due to IF NOT EXISTS after the covering index is created. Deduplicated to 2 covering indexes above. Both are INCLUDE covering indexes to enable Index-Only / Bitmap Heap scans without heap fetches for SELECT list (order_id, status, product_id, quantity).

## Sandbox Verification Proof
**Environment:** MODAL_CLOUD_POSTGRES_SANDBOX (sb-ZOlufMBBlX11w6yKo0Pp1k)

Before (baseline):
- Hash Join (cost=3531.52, actual_rows=240)
- Seq Scan on order_items (cost=1965.0, actual_rows=120000)
- Hash (cost=1250.0, actual_rows=120)
- Seq Scan on orders (cost=1250.0, actual_rows=120)

After (remediated):
- Nested Loop (cost=1592.39, actual_rows=240)
- Bitmap Heap Scan on orders (cost=299.7, actual_rows=120)
- Bitmap Index Scan using idx_orders_customer_id (cost=5.38, actual_rows=120)
- Index Only Scan on order_items using idx_order_items_order_id (cost=10.08, actual_rows=2)

| Metric | Baseline | Remediated | Improvement |
|---|---|---|---|
| Production-equivalent latency | 240.0ms | 4.38ms | -98.18% |
| Local execution | 17.005ms | 0.31ms | -98.18% |
| CPU | 94.2% | 9.1% | -90.34% |
| Plan shape | Hash Join + 2x Seq Scan | Nested Loop + Bitmap + Index-Only | converted_to_index_scan=true |
| Covering | false | true (is_covering_index_scan=true) | yes |
| Rows returned | 240 | 240 | correct |
| Table locks | - | false | none |
| Deterministic gate | - | passed (true) | pass |
| Error | - | null | none |

## Rollback Plan
```sql
DROP INDEX CONCURRENTLY IF EXISTS public.idx_order_items_order_id;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_orders_customer_id;
```
Indexes are new, unused elsewhere, drop is online and safe. No data change.

## Action Items
- [ ] Merge this PR and apply migration during low-traffic window with CONCURRENTLY
- [ ] Add FK index lint in CI to require index on order_items(order_id)
- [ ] Add EXPLAIN regression test for customer_id lookup asserting Index Scan, no Seq Scan
- [ ] Review SLA threshold (1000.0ms) vs P99 alert at 240.0ms - tune alert sensitivity
- [ ] Monitor pg_stat_user_indexes for usage of new indexes and bloat

## Appendix
- Raw production plan Total Cost 1515.96, Startup 613.69, Plan Rows 66, Plan Width 18, Join Type Inner, Hash Cond (i.order_id = o.order_id)
- Sandbox duration 5.64s, deterministic_gate_passed=true