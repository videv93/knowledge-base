-- Assert no duplicate URLs exist in stg_posts (carried through from raw layer).
-- This test passes when query returns zero rows.

select
    url,
    count(*) as url_count
from {{ ref('stg_posts') }}
group by url
having count(*) > 1
