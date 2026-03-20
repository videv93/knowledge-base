import asyncio
import json

from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler


async def main():
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url="https://nextjs.org/blog")

    soup = BeautifulSoup(result.html, "html.parser")
    posts = []

    for title_el in soup.find_all("a", class_=lambda c: c and "title" in c):
        card = title_el.parent
        title = title_el.get_text(strip=True)
        link = f"https://nextjs.org{title_el['href']}"

        date_el = card.find("p")
        posted_date = date_el.get_text(strip=True) if date_el else None

        author_divs = card.find_all("div", attrs={"aria-label": True})
        authors = [div["aria-label"].replace("Avatar of ", "") for div in author_divs]

        desc_el = card.find("div", class_=lambda c: c and "prose" in c)
        description = desc_el.get_text(strip=True) if desc_el else None

        posts.append(
            {
                "title": title,
                "description": description,
                "authors": authors,
                "posted_date": posted_date,
                "link": link,
            }
        )

    print(json.dumps(posts, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
