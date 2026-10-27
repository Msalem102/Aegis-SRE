-- High-frequency query executed ~450 calls/min
-- Triggered whenever a customer opens their order history dashboard:
SELECT 
    id, 
    user_id, 
    status, 
    total_amount, 
    created_at
FROM orders
WHERE user_id = 42819
  AND status = 'completed'
ORDER BY created_at DESC
LIMIT 50;
