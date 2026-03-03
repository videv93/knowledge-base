/*
  Performance Test for mart_newsletter_candidates

  Acceptance Criteria: Query must complete within 5 seconds for 150+ weekly posts

  This test documents the performance requirement. Actual validation requires:
  1. Running EXPLAIN ANALYZE on the model query
  2. Measuring execution time under realistic data volumes
  3. Monitoring performance in production

  This test ensures the model respects the LIMIT 20 constraint.
  For actual performance testing, use: EXPLAIN ANALYZE SELECT * FROM mart_newsletter_candidates;
*/

-- This test fails if the model returns more than 20 rows (violates LIMIT 20)
-- It passes with 0 rows (no weekly posts) or 1-20 rows
select
  count(*) as row_count
from {{ ref('mart_newsletter_candidates') }}
-- Performance expectation: < 5 seconds for 150+ weekly posts
-- Validate with: EXPLAIN ANALYZE SELECT * FROM mart_newsletter_candidates;
having count(*) > 20  -- Fail if exceeds LIMIT 20
