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

    def _extract_content(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """
        Extract clean content from html soup.

        Return dict with:
        - Product name
        - Price
        - Description
        - Availability
        """

        for element in soup(["script", "style", "header", "footer", "nav", "aside", "form", "iframe", "noscript"]):
            element.decompose()

        # Extract the title
        title = soup.title.string

        print(title)






