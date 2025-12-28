-- PRZYKŁADOWE DANE
INSERT INTO outbox_event (aggregate_type, aggregate_id, event_type, payload, status, attempts, next_run_at)
VALUES
('order', '1001', 'order.created', '{"orderId": "1001", "customerId": "C001", "totalCents": 5000}'::jsonb, 'pending', 0, now()),
('order', '1002', 'order.created', '{"orderId": "1002", "customerId": "C002", "totalCents": 7500}'::jsonb, 'retry', 1, now() - interval '1 minute'),
('invoice', '2001', 'invoice.generated', '{"invoiceId": "2001", "orderId": "1001", "amountCents": 5000}'::jsonb, 'done', 1, now()),
('invoice', '2002', 'invoice.generated', '{"invoiceId": "2002", "orderId": "1002", "amountCents": 7500}'::jsonb, 'dead', 5, now()),
('user', 'U001', 'user.registered', '{"userId": "U001", "email": "user1@example.com"}'::jsonb, 'pending', 0, now()),
('user', 'U002', 'user.registered', '{"userId": "U002", "email": "user2@example.com"}'::jsonb, 'retry', 2, now() - interval '2 minutes'),
('order', '1003', 'order.created', '{"orderId": "1003", "customerId": "C003", "totalCents": 12000}'::jsonb, 'pending', 0, now()),
('order', '1004', 'order.created', '{"orderId": "1004", "customerId": "C004", "totalCents": 3000}'::jsonb, 'done', 1, now()),
('invoice', '2003', 'invoice.generated', '{"invoiceId": "2003", "orderId": "1003", "amountCents": 12000}'::jsonb, 'retry', 1, now() - interval '30 seconds'),
('user', 'U003', 'user.registered', '{"userId": "U003", "email": "user3@example.com"}'::jsonb, 'dead', 4, now());
