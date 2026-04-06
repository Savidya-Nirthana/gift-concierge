from playwright.async_api import async_playwright
from collections import deque
import asyncio
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Set
import re
from urllib.parse import urljoin, urlparse
from markdownify import markdownify as md


class KaprukaCrawler:
    def __init__(self, base_url: str, max_depath: int, exclude_patterns: List[str]):
        self.base_url = base_url
        self.max_depth = max_depath
        self.exclude_patterns = exclude_patterns
        self.visited: Set[str] = set()
        self.documents: List[Dict[str, Any]] = []


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

    def extract_main_content(soup: BeautifulSoup, url: str):
        details_div = soup.find("div", id='Tab1')

        title = soup.title.string if soup.title else url.split("/")[-1]

        test = details_div.find_all(["p", "ul"])
        content = ""
        for i in test:
            if "<p>" in str(i):
                p_content = i.get_text()
                content += p_content + "\n\n"
            elif "<ul>" in str(i):
                features = "\n".join([li.get_text(strip=True) for li in details_div.find_all('li')])
                content += features + "\n\n"
        return content
    
    def extract_meta(soup, prop):
        """ Return content of a <meta property="..."> tag. """
        tag = soup.find("meta", property=prop)
        return tag['content'].strip() if tag and tag.get("content") else ""

    def extract_sku(soup):
        el = soup.find("input",{"id": "id", "type": "hidden"})
        if el and el.get("value"):
            return el["value"]
        return extract_meta(soup, "product:retailer_item_id")


    def extract_links(soup, url: str):
        links = []
        for a in soup.find_all("a", href=True):
            href = a.get("href", '')
            if not href:
                continue

            if href.startswith('/'):
                href = "https://www.kapruka.com" + href
            elif not href.startswith('http'):
                href = urljoin(url, href)

            if href.startswith( "https://www.kapruka.com"):
                href = href.split('#')[0].split('?')[0]
                if href and href !=url:
                    links.append(href)
        return links


    def extract_varients(soup: BeautifulSoup, url: str):
        script_tags = soup.find_all('script')
        products_data = {}
        toppers = []
        links = extract_links(soup, url)
        print(links)
        for script in script_tags:
            if script.string and 'let products' in script.string:
                match = re.search(r'let products\s*=\s*(\[.*?\]);', script.string, re.DOTALL)
                if match:
                    products_data = json.loads(match.group(1))
                    break 
            else:
                availability = extract_meta(soup,"product:availability")
                price_lkr = extract_meta(soup, "product:price:amount")
                product_sku = extract_sku(soup)

                all_products = []
                product_map = []
                text = script.string or ""
                if "allProducts" in text:
                    match_toppers = re.search(
                        r'var\s+allProducts\s*=\s*(\[.*?\]);',
                        text
                    )
                    if match_toppers:
                        all_products = json.loads(match_toppers.group(1))

                if "productMapJson" in text:
                    match_price = re.search(r'var\s+productMapJson\s*=\s*(\{.*?\});', text, re.DOTALL)
                    if match_price:
                        try:
                            product_map = json.loads(match_price.group(1))
                        except json.JSONDecodeError:
                            pass
                if len(toppers) == 0:
                    if all_products and product_map:

                        for product in all_products:
                            pid = product.get("productID", "")
                            topper = {
                                "productID": pid,
                                "name": product.get("name", ""),
                                "price_lkr": product_map.get(pid, "N/A"),
                                "price_usd": product.get("price", ""),
                                "available": product.get("available", ""),
                                "type": product.get("type", ""),
                                "imageName": product.get("imageName", ""),
                                "deliveryType": product.get("deliveryType", ""),
                                "bestseller": product.get("bestseller", ""),
                            }
                            toppers.append(topper)

            price_valid_until = ""
            try:
                data = json.loads(script.string or "")
                if str(data.get("@type", "")).lower() in ("product",):
                    offers = data.get("offers", [{}])
                    if isinstance(offers, list):
                        offers = offers[0]
                        price_lkr         = price_lkr or str(offers.get("price", ""))
                        price_valid_until  = offers.get("priceValidUntil", "")
                        avail_url          = offers.get("availability", "")
                        available          = "InStock" in avail_url or available
            except Exception:
                pass

            products_data = {
                "availabilty" :"in stock" if availability else "Out of stock",
                "price_lkr" : price_lkr, 
                "product sku" : product_sku,
                "price valid until" : price_valid_until,
                "toppers" : toppers
            }
                    
                

        return products_data



    async def crawl_async(self, start_urls: List[str], request_delay: float = 2.0) -> List[Dict[str, Any]]:
        queue = deque([(url, 0) for url in start_urls])

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            page.set_default_timeout(30000)

            while queue:
                url, depth = queue.popleft()
                if depth > self.max_depth or not self._should_crawl(url):
                    continue

                try:
                    print(f"🔍 [{depth}] {url}")
                    self.visited.add(url)

                    await page.goto(url, wait_until="domcontentloaded", timeout=60000)

                    try:
                        await page.wait_for_selector("body", timeout=10000)
                        await page.wait_for_timeout(3000)

                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        await page.wait_for_timeout(1000)

                    except:
                        await page.wait_for_timeout(5000)
                    
                    html = await page.content()
                    soup = BeautifulSoup(html, "html.parser")

                    doc_data = self.extract_main_content(soup, url)
                    print(doc_data)
                    break
                except:
                    pass






