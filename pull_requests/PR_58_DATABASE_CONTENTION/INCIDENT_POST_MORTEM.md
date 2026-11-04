# Post-Mortem INC-20261105-PG-11D1 - PG_SLOW_QUERY_BREACH in cupertino-coffee-store

## Executive Summary
- Incident: INC-20261105-PG-11D1, VECTOR_A_DB, service cupertino-coffee-store
- Trigger: PG_SLOW_QUERY_BREACH - P99 query latency spiked to 250.0ms (SLA threshold: 1000.0ms), production-equivalent 240.0ms
- Offending query: SELECT o.order_id, o.status, i.product_id, i.quantity FROM orders o JOIN order_items i ON o.order_id = i.order_id WHERE o.customer_id = %s (customer_id = 639 in plan)
- Resolution: Autonomous creation of 2 covering btree indexes with CONCURRENTLY, verified 98.46% latency reduction, 90.55% CPU reduction
- Sandbox: MODAL_CLOUD_POSTGRES_SANDBOX sb-i0gAxdwCAno1Ax8oo7hSNQ, duration 4.38s, deterministic_gate_passed true

## Impact
- Query path for customer order history forced Hash Join over full tables
- Estimated rows scanned 29641 to return 37 orders (800x over-read), plus 50000 order_items scanned
- High heap I/O, buffer churn, hash build CPU, latency 240ms, CPU 94.2% baseline
- No host_cpu_percent reported at trigger, sandbox baseline_cpu 94.2% confirms DB CPU pressure

## Root Cause Analysis
- Plan Total Cost 1515.96:
  - Hash Join (cost=1515.96, actual_rows=0)
  - Seq Scan on order_items (cost=771.0, actual_rows=0) Parent Outer
  - Hash (cost=613.23, actual_rows=0) Parent Inner
  - Seq Scan on orders (cost=613.23, actual_rows=0) Filter (customer_id = 639)
- Raw plan confirms Inner Unique true, Hash Cond (i.order_id = o.order_id), Parallel Aware false, Async Capable false
- Missing indexes on both sides: no btree on orders.customer_id, no index on order_items.order_id FK
- Startup Cost 613.69 blocks pipelining, Hash must fully scan and build before probe
- Scales linearly with growth, prevents Nested Loop + Index Scan

## Resolution - Verified DDL Diff (Ready to Merge)
```sql
-- Safe migration SQL
SET statement_timeout = '30s';
SET lock_timeout = '5s';
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_customer_id ON public.orders USING btree (customer_id) INCLUDE (order_id, status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_items_order_id ON public.order_items USING btree (order_id) INCLUDE (product_id, quantity);
```
- Note: verified_patch contained duplicate third line CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_items_order_id ON order_items (order_id); deduplicated for merge - third statement is no-op due to IF NOT EXISTS name check.
- Covering design: INCLUDE (order_id, status) and INCLUDE (product_id, quantity) matches SELECT list to enable Index-Only Scan and avoid heap fetch
- CONCURRENTLY + timeouts ensure zero-downtime, no table locks detected in sandbox

## Sandbox Verification Proof
- Environment: MODAL_CLOUD_POSTGRES_SANDBOX, ID sb-i0gAxdwCAno1Ax8oo7hSNQ, duration 4.38s
- Applied DDL: same as above (with redundant third line as no-op)
- Before plan nodes:
  - Hash Join (cost=3531.5, actual_rows=240)
  - Seq Scan on order_items (cost=1965.0, actual_rows=120000)
  - Hash (cost=1250.0, actual_rows=120)
  - Seq Scan on orders (cost=1250.0, actual_rows=120)
- After plan nodes:
  - Nested Loop (cost=1631.42, actual_rows=240)
  - Bitmap Heap Scan on orders (cost=305.3, actual_rows=120)
  - Bitmap Index Scan using idx_orders_customer_id (cost=5.41, actual_rows=120)
  - Index Only Scan on order_items using idx_order_items_order_id (cost=10.03, actual_rows=2)
- Metrics:
  | metric | baseline | remediated | improvement |
  |---|---|---|---|
  | local_ms | 16.962 | 0.261 | ~64x faster |
  | prod_equiv_latency_ms | 240.0 | 3.69 | 98.46% reduction |
  | cpu_percent | 94.2 | 8.9 | 90.55% reduction |
  | rows_returned | 240 | 240 | correct |
- Flags: converted_to_index_scan true, is_covering_index_scan true, table_locks_detected false, deterministic_gate_passed true, error null
- Planning: measured_local_ms 0.0, planning_time_ms 0.0 in diagnosis snapshot; sandbox proves stable Nested Loop choice

## Rollback Plan
- DROP INDEX CONCURRENTLY IF EXISTS idx_orders_customer_id;
- DROP INDEX CONCURRENTLY IF EXISTS idx_order_items_order_id;
- No data change, indexes only, safe to drop, reverts to prior Hash Join plan

## Lessons Learned and Action Items
- Enforce FK indexes on order_items.order_id and selective WHERE indexes on orders.customer_id at schema review
- Add covering INCLUDE for frequent join + SELECT projections
- Monitor P99, Seq Scan rate, and plan cost regression in CI with EXPLAIN
- Consider auto-vacuum/analyze after bulk load to keep Plan Rows accurate

