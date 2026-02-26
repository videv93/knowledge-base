-- Assert no orphaned summaries: every summary in stg_summaries has a matching post in mart_posts.
-- This test passes when query returns zero rows.

select
    s.id as summary_id,
    s.post_id
from {{ ref('stg_summaries') }} as s
left join {{ ref('mart_posts') }} as mp
    on s.post_id = mp.id
where mp.id is null
