import requests
from bs4 import BeautifulSoup
import json
import time
import re
from urllib.parse import urlparse

# ── URL list ──────────────────────────────────────────────────────────────────
faq_urls = [
    "https://www.kapruka.com/shop/home-faq/",
    "https://www.kapruka.com/shop/clothing-faq/",
    "https://www.kapruka.com/shop/electronicsfaq/",
    "https://www.kapruka.com/shop/kapruka-grocery-faqs/",
    "https://www.kapruka.com/shop/fashion-faq/",
    "https://www.kapruka.com/shop/foods-faq/",
    "https://www.kapruka.com/shop/fruits-faq/",
    "https://www.kapruka.com/faq/pharmacy",
    "https://www.kapruka.com/shop/homelifestyle_faq/",
    "https://www.kapruka.com/shop/kapruka-books-faq/",          # fixed broken URL
    "https://www.kapruka.com/shop/sports",
    "https://www.kapruka.com/faq/mother-baby",
    "https://www.kapruka.com/shop/watches_jewelry-faq/",
    "https://www.kapruka.com/shop/cosmetics-faq/",
    "https://www.kapruka.com/shop/cake-faqs/",
    "https://www.kapruka.com/shop/flowers-faq/",
    "https://www.kapruka.com/shop/chocolates-faq/",
    "https://www.kapruka.com/shop/personalized_gifts-faq/",
    "https://www.kapruka.com/faq/cards",
    "https://www.kapruka.com/faq/kids-toys",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Helper: derive a readable slug from a URL ─────────────────────────────────
def slug_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    # take the last segment, strip common suffixes
    segment = path.split("/")[-1]
    segment = re.sub(r"[-_]faq[s]?$", "", segment, flags=re.IGNORECASE)
    return segment.replace("-", "_").replace(" ", "_") or "unknown"


# ── Fetch one page ────────────────────────────────────────────────────────────
def fetch_page(url: str, timeout: int = 15) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        print(f"  [ERROR] Could not fetch {url}: {e}")
        return None


# ── Extract FAQ from HTML ─────────────────────────────────────────────────────
def extract_faq(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    # Page title
    title_tag = soup.find("h1")
    page_title = title_tag.get_text(strip=True) if title_tag else slug_from_url(url)

    result = {
        "source_url": url,
        "page_title": page_title,
        "categories": [],
    }

    # ── Strategy 1: look for the .kp-faq-wrap <section> ──────────────────────
    faq_section = soup.find("section", class_="kp-faq-wrap")

    if faq_section:
        result["categories"] = _parse_kp_section(faq_section)

    # ── Strategy 2: generic h2/h3 + p/ul pattern ─────────────────────────────
    if not result["categories"]:
        result["categories"] = _parse_generic(soup)

    # ── Strategy 3: flat h3 + p (no h2 grouping) ─────────────────────────────
    if not result["categories"]:
        result["categories"] = _parse_flat_h3(soup)

    return result


# ── Parser A: structured kp-faq-wrap ─────────────────────────────────────────
def _parse_kp_section(section) -> list:
    categories = []
    current_cat = None

    for el in section.children:
        if not hasattr(el, "name") or el.name is None:
            continue

        if el.name == "h2":
            current_cat = {"category": el.get_text(strip=True), "faqs": []}
            categories.append(current_cat)

        elif el.name == "div" and "kp-faq-item" in el.get("class", []):
            if current_cat is None:
                current_cat = {"category": "General", "faqs": []}
                categories.append(current_cat)

            entry = _build_entry(el)
            if entry["question"]:
                current_cat["faqs"].append(entry)

    return categories


# ── Parser B: generic – any h2 followed by h3+p blocks ───────────────────────
def _parse_generic(soup) -> list:
    categories = []
    current_cat = None

    # look inside main content area first; fall back to body
    content = (
        soup.find("div", class_=re.compile(r"colibri-post-content|entry-content|post-content"))
        or soup.find("main")
        or soup.body
    )
    if not content:
        return []

    for el in content.descendants:
        if not hasattr(el, "name") or el.name is None:
            continue

        if el.name == "h2":
            current_cat = {"category": el.get_text(strip=True), "faqs": []}
            categories.append(current_cat)

        elif el.name == "h3":
            if current_cat is None:
                current_cat = {"category": "General", "faqs": []}
                categories.append(current_cat)

            question = el.get_text(strip=True)
            answer_parts, bullet_points = [], []

            # collect siblings until next h3 or h2
            for sib in el.find_next_siblings():
                if sib.name in ("h2", "h3"):
                    break
                if sib.name == "p":
                    t = sib.get_text(separator=" ", strip=True)
                    if t:
                        answer_parts.append(t)
                elif sib.name == "ul":
                    bullet_points += [li.get_text(strip=True) for li in sib.find_all("li")]

            entry = {"question": question, "answer": " ".join(answer_parts)}
            if bullet_points:
                entry["bullet_points"] = bullet_points
            if question:
                current_cat["faqs"].append(entry)

    return [c for c in categories if c["faqs"]]


# ── Parser C: flat h3 blocks (no h2 grouping at all) ─────────────────────────
def _parse_flat_h3(soup) -> list:
    faqs = []
    for h3 in soup.find_all("h3"):
        question = h3.get_text(strip=True)
        answer_parts, bullets = [], []
        for sib in h3.find_next_siblings():
            if sib.name in ("h2", "h3"):
                break
            if sib.name == "p":
                t = sib.get_text(separator=" ", strip=True)
                if t:
                    answer_parts.append(t)
            elif sib.name == "ul":
                bullets += [li.get_text(strip=True) for li in sib.find_all("li")]

        if question and (answer_parts or bullets):
            entry = {"question": question, "answer": " ".join(answer_parts)}
            if bullets:
                entry["bullet_points"] = bullets
            faqs.append(entry)

    if faqs:
        return [{"category": "General", "faqs": faqs}]
    return []


# ── Build a single FAQ entry from a kp-faq-item div ──────────────────────────
def _build_entry(div) -> dict:
    q_tag = div.find("h3")
    question = q_tag.get_text(strip=True) if q_tag else ""

    answer_parts, bullets = [], []
    for child in div.children:
        if not hasattr(child, "name") or child.name is None:
            continue
        if child.name == "h3":
            continue
        if child.name == "p":
            t = child.get_text(separator=" ", strip=True)
            if t:
                answer_parts.append(t)
        elif child.name == "ul":
            bullets += [li.get_text(strip=True) for li in child.find_all("li")]

    entry = {"question": question, "answer": " ".join(answer_parts)}
    if bullets:
        entry["bullet_points"] = bullets
    return entry


# ── Main ──────────────────────────────────────────────────────────────────────
def main(output_file: str = "data/kapruka_all_faqs.json"):
    all_pages = []
    failed_urls = []

    for idx, url in enumerate(faq_urls, start=1):
        print(f"[{idx:02d}/{len(faq_urls)}] Fetching: {url}")

        html = fetch_page(url)
        if html is None:
            failed_urls.append(url)
            continue

        data = extract_faq(html, url)
        total_q = sum(len(cat["faqs"]) for cat in data["categories"])
        print(f"  [OK] '{data['page_title']}' - {len(data['categories'])} categories, {total_q} Q&As")

        all_pages.append(data)

        # polite delay between requests
        if idx < len(faq_urls):
            time.sleep(1.5)

    # ── Save combined output ──────────────────────────────────────────────────
    combined = {
        "total_pages": len(all_pages),
        "total_questions": sum(
            len(cat["faqs"])
            for page in all_pages
            for cat in page["categories"]
        ),
        "failed_urls": failed_urls,
        "pages": all_pages,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*55}")
    print(f"Done! Saved {output_file}")
    print(f"  Pages extracted : {combined['total_pages']}")
    print(f"  Total Q&As      : {combined['total_questions']}")
    if failed_urls:
        print(f"  Failed URLs     : {len(failed_urls)}")
        for u in failed_urls:
            print(f"    - {u}")


if __name__ == "__main__":
    main()