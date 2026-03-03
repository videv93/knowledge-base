/*
  Newsletter Candidate Ranking Model

  Purpose: Ranks blog posts from the current week for newsletter inclusion based on
  source quality, publication recency, and category diversity.

  Scoring Algorithm:
  - Source Quality (0-100 pts): Primary factor based on source quality_rating (1-5 scale)
  - Publication Recency (0-50 pts): Exponential decay favoring recent posts
  - Category Diversity (0-20 pts): Bonus for top posts in each category

  Filters:
  - Only posts from last 7 days
  - Only posts with AI summaries
  - Only posts from active sources
  - Exclude low-quality posts

  Output: Top 20 ranked candidates with all fields needed for newsletter generation

  Diversity Note: The diversity bonus awards points to top 3 posts per category,
  but the final LIMIT 20 is applied AFTER scoring. This means high-quality categories
  may dominate the top 20. Future iterations could enforce max posts per category.

  Performance Recommendations:
  - Index on mart_posts.publication_date for date filtering
  - Index on mart_posts.is_low_quality for quality filtering
  - Index on mart_sources.status for active source filtering
*/

with weekly_posts as (
  -- Get posts from the last 7 days with quality filters
  select
    p.id,
    p.source_id,
    p.title,
    p.url,
    p.summary_text,
    p.author_name,
    p.source_name,
    p.category,
    p.publication_date,
    p.tags,
    p.difficulty_classification,
    s.quality_rating
  from {{ ref('mart_posts') }} p
  inner join {{ ref('mart_sources') }} s
    on p.source_id = s.id
  where
    p.publication_date >= current_date - interval '7 days'
    and p.summary_text is not null  -- Newsletter requires AI summaries
    and p.is_low_quality = false     -- Exclude low-quality posts
    and s.status = 'active'          -- Only active sources
    and s.quality_rating is not null -- Ensure quality rating exists for scoring
),

ranked_posts as (
  -- Calculate category rank for diversity bonus
  select
    id,
    source_id,
    title,
    url,
    summary_text,
    author_name,
    source_name,
    category,
    publication_date,
    tags,
    difficulty_classification,
    quality_rating,
    row_number() over (
      partition by category
      order by quality_rating desc, publication_date desc
    ) as category_rank
  from weekly_posts
),

scored_posts as (
  -- Calculate composite ranking score using pre-computed category_rank
  select
    id,
    source_id,
    title,
    url,
    summary_text,
    author_name,
    source_name,
    category,
    publication_date,
    tags,
    difficulty_classification,

    -- Composite score calculation
    -- Quality component: 0-100 points based on 1-5 rating scale
    (quality_rating / 5.0) * 100 +
    -- Recency component: 0-50 points with exponential decay (recent posts score higher)
    (1.0 / (1 + (current_date - publication_date::date))) * 50 +
    -- Diversity component: 20 point bonus for top 3 posts in each category
    (case when category_rank <= 3 then 20 else 0 end) as score

  from ranked_posts
),

top_candidates as (
  -- Select top 20 candidates ordered by score
  select
    id,
    source_id,
    title,
    url,
    summary_text,
    author_name,
    source_name,
    category,
    publication_date,
    tags,
    difficulty_classification,
    score
  from scored_posts
  order by score desc, publication_date desc
  limit 20
)

select * from top_candidates
