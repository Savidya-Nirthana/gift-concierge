from playwright.async_api import async_playwright
from collections import deque
import asyncio
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Set
import re
from urllib.parse import urljoin, urlparse
from markdownify import markdownify as md
import json
from infrastructure.config import CRAWL_OUT_DIR
from pathlib import Path

class KaprukaCrawlerV2:
    def __init__(self, base_url: str, max_depth: int, exclude_patterns: List[str], max_pages: int = 500, save_steps: int = 20, max_workers: int = 5):
        self.base_url = base_url
        self.max_depth = max_depth
        self.exclude_patterns = exclude_patterns
        self.max_pages = max_pages
        self.visited: Set[str] = set()
        self.documents: List[Dict[str, Any]] = []
        self.save_steps = save_steps
        self._saved_count = 0
        self.max_workers = max_workers


    def _normalize_url(self, url: str) -> str:
        """Normalize URL: lowercase, strip trailing slash, remove locale prefixes."""
        url = url.lower().rstrip('/')
        # Remove /au/ and /lk/ locale prefixes (duplicate pages)
        url = re.sub(r'(https://www\.kapruka\.com)/(au|lk)/', r'\1/', url)
        return url

    def _should_crawl(self, url: str) -> bool:
        """Check if the URL should be crawled based on rules"""
        if url in self.visited:
            return False
        
        if not url.startswith(self.base_url):
            return False
        
        for pattern in self.exclude_patterns:
            if pattern in url:
                return False
            
        
        if re.search(r'\.(jpg|jpeg|png|gif|pdf|zip|exe)$', url, re.I):
            return False
        
        return True

    def _is_product_page(self, soup: BeautifulSoup) -> bool:
        """Check if the page is a single product page (has Tab1 detail div)."""
        return soup.find("div", id="Tab1") is not None

    
    
    def extract_meta(self, soup, prop):
        """ Return content of a <meta property="..."> tag. """
        tag = soup.find("meta", property=prop)
        return tag['content'].strip() if tag and tag.get("content") else ""

    def extract_sku(self, soup):
        el = soup.find("input",{"id": "id", "type": "hidden"})
        if el and el.get("value"):
            return el["value"]
        return extract_meta(soup, "product:retailer_item_id")


    def extract_links(self, soup, url: str):
        links = []
        for a in soup.find_all("a", href=True):
            href = a.get("href", '')
            if not href:
                continue

            if href.startswith('/'):
                href = "https://www.kapruka.com" + href
            elif not href.startswith('http'):
                href = urljoin(url, href)

            if href.startswith("https://www.kapruka.com"):
                href = href.split('#')[0].split('?')[0]
                href = self._normalize_url(href)
                # Early filter: skip links that match exclude patterns
                skip = False
                for pattern in self.exclude_patterns:
                    if pattern in href:
                        skip = True
                        break
                if not skip and href and href != self._normalize_url(url):
                    links.append(href)
        return links


    def _extract_product_info(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """Extract structured product info: price, SKU, availability, variants."""
        info = {
            "availability": "",
            "price_lkr": "",
            "price_usd": "",
            "sku": "",
            "price_valid_until": "",
            "variants": [],
        }

        info["availability"] = self.extract_meta(soup, "product:availability") or ""
        info["price_lkr"] = self.extract_meta(soup, "product:price:amount") or ""
        info["sku"] = self.extract_sku(soup) or ""

        script_tags = soup.find_all('script')
        for script in script_tags:
            text = script.string or ""

            if 'let products' in text:
                match = re.search(r'let products\s*=\s*(\[.*?\]);', text, re.DOTALL)
                if match:
                    try:
                        products_data = json.loads(match.group(1))
                        for pv in products_data:
                            name_parts = []
                            for k, v in pv.get("variants", {}).items():
                                name_parts.append(f"{k}: {v}")
                            name = ", ".join(name_parts) or pv.get("id", "")
                            info["variants"].append({
                                "name": name,
                                "price_lkr": pv.get("priceFormatted", ""),
                                "price_usd": pv.get("price", ""),
                                "available": pv.get("availability", ""),
                                "type": "product_variant",
                                "delivery": "",
                            })
                    except Exception:
                        pass

            # ── structured data (JSON-LD) ──
            try:
                data = json.loads(text)
                if str(data.get("@type", "")).lower() == "product":
                    offers = data.get("offers", [{}])
                    if isinstance(offers, list) and offers:
                        offers = offers[0]
                    if isinstance(offers, dict):
                        info["price_lkr"] = info["price_lkr"] or str(offers.get("price", ""))
                        info["price_valid_until"] = offers.get("priceValidUntil", "")
                        avail_url = offers.get("availability", "")
                        if "InStock" in avail_url:
                            info["availability"] = "instock"
                    continue
            except Exception:
                pass

            # ── variant list from allProducts + productMapJson ──
            if not info["variants"]:
                all_products = []
                product_map = {}

                if "allProducts" in text:
                    m = re.search(r'var\s+allProducts\s*=\s*(\[.*?\]);', text)
                    if m:
                        try:
                            all_products = json.loads(m.group(1))
                        except json.JSONDecodeError:
                            pass

                if "productMapJson" in text:
                    m = re.search(r'var\s+productMapJson\s*=\s*(\{.*?\});', text, re.DOTALL)
                    if m:
                        try:
                            product_map = json.loads(m.group(1))
                        except json.JSONDecodeError:
                            pass

                if all_products and product_map:
                    for p in all_products:
                        pid = p.get("productID", "")
                        info["variants"].append({
                            "name": p.get("name", ""),
                            "price_lkr": product_map.get(pid, ""),
                            "price_usd": p.get("price", ""),
                            "available": p.get("available", ""),
                            "type": p.get("type", ""),
                            "delivery": p.get("deliveryType", ""),
                        })

        return info

    def _format_product_markdown(self, title: str, description_md: str,
                                  info: Dict[str, Any], url: str) -> str:
        """Build a semantically structured Markdown document for one product."""
        lines: List[str] = []

        # ── Title ──
        lines.append(f"# {title.strip()}\n")

        # ── Description ──
        desc = description_md.strip()
        if desc:
            lines.append("## Description\n")
            lines.append(desc + "\n")

        # ── Product details ──
        details: List[str] = []
        if info.get("price_lkr"):
            details.append(f"- **Price (LKR):** {info['price_lkr']}")
        if info.get("price_usd"):
            details.append(f"- **Price (USD):** {info['price_usd']}")
        if info.get("sku"):
            details.append(f"- **SKU:** {info['sku']}")
        avail = info.get("availability", "")
        if avail:
            status = "In Stock" if "instock" in avail.lower() else avail.title()
            details.append(f"- **Availability:** {status}")
        if info.get("price_valid_until"):
            details.append(f"- **Price valid until:** {info['price_valid_until']}")
        details.append(f"- **URL:** {url}")

        if details:
            lines.append("## Product Details\n")
            lines.append("\n".join(details) + "\n")

        # ── Variants table ──
        variants = info.get("variants", [])
        if variants:
            lines.append("## Available Options / Add-ons\n")
            lines.append("| Option / Add-on | Price (LKR) | Price (USD) | Available | Delivery |")
            lines.append("|---------|-------------|-------------|-----------|----------|")
            for v in variants:
                name  = v.get("name", "—")
                plkr  = v.get("price_lkr", "—")
                pusd  = v.get("price_usd", "—")
                avl   = "Yes" if str(v.get("available", "")).lower() in ("true", "1", "yes", "y") else "No"
                dlv   = v.get("delivery", "—")
                lines.append(f"| {name} | {plkr} | {pusd} | {avl} | {dlv} |")
            lines.append("")

        return "\n".join(lines)

    # ─── public extraction methods ────────────────────────────────────

    def extract_category_links(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """For category/listing pages: extract only the title and links, no content."""
        title = soup.title.string if soup.title else url.split("/")[-1]
        links = self.extract_links(soup, url)
        return {
            "content": "",
            "title": title,
            "links": list(set(links)),
            "page_type": "category"
        }

    def extract_main_content(self, soup: BeautifulSoup, url: str):
        """Extract product page content as a structured Markdown document."""
        title = soup.title.string.strip() if soup.title else url.split("/")[-1]

        # ── description: convert the Tab1 HTML → Markdown via markdownify ──
        details_div = soup.find("div", id='Tab1')
        description_md = ""
        if details_div:
            # markdownify converts <p>, <ul>, <li>, <strong> etc. to proper MD
            description_md = md(str(details_div), strip=["img", "a", "script"]).strip()

        # ── product info (price, SKU, availability, variants) ──
        info = self._extract_product_info(soup, url)

        # ── assemble final Markdown ──
        content = self._format_product_markdown(title, description_md, info, url)

        links = self.extract_links(soup, url)
        return {
            "content": content,
            "title": title,
            "links": list(set(links)),
            "page_type": "product"
        }

    def _save_progress(self):
        """Save all unsaved documents to MD files."""
        if self._saved_count >= len(self.documents):
            return

        _project_root = Path(__file__).resolve().parent.parent.parent.parent
        path = _project_root / "data" / "temp"
        path.mkdir(parents=True, exist_ok=True)

        for i in range(self._saved_count, len(self.documents)):
            filename = path / f"kapruka_crawl_progress_{i + 1}.md"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(self.documents[i]["content"])
            print(f"💾 Saved doc {i + 1}/{len(self.documents)} to {filename}")
        self._saved_count = len(self.documents)


    async def crawl_async(self, start_urls: List[str], request_delay: float = 0):
        queue = asyncio.Queue()

        for url in start_urls:
            await queue.put((self._normalize_url(url), 0))

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            # ✅ Worker function (SAFE)
            async def worker(worker_id: int):
                while True:
                    try:
                        url, depth = await asyncio.wait_for(queue.get(), timeout=5)
                    except asyncio.TimeoutError:
                        return  # worker exits cleanly

                    if depth > self.max_depth:
                        queue.task_done()
                        continue

                    if not self._should_crawl(url):
                        queue.task_done()
                        continue

                    self.visited.add(url)

                    page = await browser.new_page()

                    try:
                        print(f"🔍 [W{worker_id}] [{depth}] {url}")

                        await page.goto(url, wait_until="domcontentloaded", timeout=60000)

                        html = await page.content()
                        soup = BeautifulSoup(html, "html.parser")

                        if self._is_product_page(soup):
                            doc_data = self.extract_main_content(soup, url)
                            doc_data["url"] = url
                            doc_data["depth_level"] = depth

                            if len(doc_data["content"]) > 100:
                                self.documents.append(doc_data)
                                print(f"✅ Product ({len(self.documents)})")

                        else:
                            doc_data = self.extract_category_links(soup, url)

                        # enqueue new links
                        if depth < self.max_depth:
                            for link in doc_data["links"]:
                                if link not in self.visited:
                                    await queue.put((link, depth + 1))

                        print(f"📊 Docs: {len(self.documents)} | Queue: {queue.qsize()}")

                    except Exception as e:
                        print(f"❌ Error {url}: {e}")

                    finally:
                        await page.close()
                        queue.task_done()

            # ✅ Start workers
            workers = [
                asyncio.create_task(worker(i))
                for i in range(self.max_workers)
            ]

            await queue.join()

            # ✅ Stop workers safely
            for w in workers:
                w.cancel()

            await browser.close()

        return self.documents



    
    def crawl(self, start_urls: List[str], request_delay: float = 2.0) -> List[Dict[str, Any]]:
        """
        Synchronous wrapper for async crawl (for Jupyter compatibility).

        Args:
            start_urls: List of seed URLs
            request_delay: Seconds between requests

        Returns:
            List of crawled documents
        """
        import sys
        import concurrent.futures

        # Normalize start URLs
        normalized_urls = [self._normalize_url(url) for url in start_urls]

        def _run_in_thread():
            """Run the async crawl in a fresh ProactorEventLoop on a new thread."""
            if sys.platform == "win32":
                loop = asyncio.ProactorEventLoop()
            else:
                loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    self.crawl_async(normalized_urls, request_delay)
                )
            finally:
                loop.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run_in_thread)
            return future.result()


__all__ = ["KaprukaCrawler"]





