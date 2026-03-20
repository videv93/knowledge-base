import asyncio
import json

from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler


async def main():
    async with AsyncWebCrawler() as crawler:
        # Step 1: Get the blog listing page
        listing = await crawler.arun(url="https://vite.dev/blog")
        soup = BeautifulSoup(listing.html, "html.parser")

        posts = []
        for entry in soup.find_all("li", class_="blog-entry"):
            article = entry.find("article")
            if not article:
                continue

            time_el = article.find("time")
            posted_date = time_el.get_text(strip=True) if time_el else None

            title_el = article.find("a", href=True)
            title = title_el.get_text(strip=True) if title_el else None
            link = f"https://vite.dev{title_el['href']}" if title_el else None

            posts.append(
                {
                    "title": title,
                    "description": None,
                    "author": None,
                    "posted_date": posted_date,
                    "link": link,
                }
            )

        # Step 2: Crawl each post individually to get description
        for post in posts:
            result = await crawler.arun(url=post["link"])
            if not result or not result.html:
                continue

            post_soup = BeautifulSoup(result.html, "html.parser")
            vpdoc = post_soup.find("div", class_="vp-doc")
            if not vpdoc:
                continue

            # First substantial content paragraph as description
            # Skip date lines and banner notices linking to newer versions
            for p in vpdoc.find_all("p"):
                text = p.get_text(strip=True)
                if len(text) < 40:
                    continue
                if "Check out the" in text and "announcement" in text:
                    continue
                post["description"] = text
                break

    print(json.dumps(posts, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
