"""
Bright Data Product Page — Hero & OG Image Scraper
====================================================
Streamlit app that extracts hero-image and og:image URLs from
Bright Data product pages (e.g. /products/web-scraper/hotwire).

Features
--------
* Paste dozens of URLs at once (one per line).
* Rate-limited scraping (1-2 s between requests).
* Results table with clickable image URLs.
* One-click ZIP download of all discovered images.
"""

import io
import re
import time
import zipfile
from pathlib import PurePosixPath
from urllib.parse import urlparse

import requests
import streamlit as st
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RATE_LIMIT_SECONDS = 1.5  # pause between requests (1-2 s range)
REQUEST_TIMEOUT = 20  # seconds
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# Scraping helpers
# ---------------------------------------------------------------------------


def fetch_page(url: str) -> requests.Response | None:
    """GET *url* and return the Response, or None on failure."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp
    except requests.RequestException as exc:
        st.warning(f"⚠️ Failed to fetch `{url}`: {exc}")
        return None


def extract_og_image(soup: BeautifulSoup) -> str | None:
    """Return the og:image content attribute value, if present."""
    tag = soup.find("meta", property="og:image")
    if tag and tag.get("content"):
        return tag["content"].strip()
    return None


def extract_hero_image(soup: BeautifulSoup) -> str | None:
    """
    Return the hero image src from the known Bright Data layout:
    <div class="s_col col-md-6 d-md-flex flex-column align-items-md-end …">
        <img … src="…" class="no_lazy d-none d-md-block" …>
    </div>

    We match the container div by a distinctive subset of CSS classes,
    then grab the first <img> with class ``no_lazy``.
    """
    # Strategy 1: find the specific div container
    required_classes = [
        "s_col",
        "col-md-6",
        "d-md-flex",
        "flex-column",
        "align-items-md-end",
    ]
    container = soup.find("div", class_=lambda c: c and all(rc in c for rc in required_classes))
    if container:
        img = container.find("img", class_=lambda c: c and "no_lazy" in c)
        if img and img.get("src"):
            return img["src"].strip()

    # Strategy 2 (fallback): look for any img.no_lazy inside a .s_col
    for div in soup.find_all("div", class_=lambda c: c and "s_col" in c):
        img = div.find("img", class_=lambda c: c and "no_lazy" in c)
        if img and img.get("src"):
            return img["src"].strip()

    return None


def scrape_images(url: str) -> dict:
    """Scrape a single URL and return a result dict."""
    result = {"url": url, "hero_image": None, "og_image": None, "status": "pending"}

    resp = fetch_page(url)
    if resp is None:
        result["status"] = "error"
        return result

    soup = BeautifulSoup(resp.text, "lxml")
    result["hero_image"] = extract_hero_image(soup)
    result["og_image"] = extract_og_image(soup)
    result["status"] = "ok"
    return result


# ---------------------------------------------------------------------------
# Image download helpers
# ---------------------------------------------------------------------------


def _safe_filename(img_url: str, page_url: str, suffix: str) -> str:
    """Derive a human-friendly filename from the image URL."""
    # Use the last path segment of the page URL as a prefix
    page_slug = PurePosixPath(urlparse(page_url).path).name or "page"
    page_slug = re.sub(r"[^\w\-]", "_", page_slug)

    img_name = PurePosixPath(urlparse(img_url).path).name or "image"
    return f"{page_slug}__{suffix}__{img_name}"


def build_zip(results: list[dict], progress_bar) -> bytes | None:
    """Download every discovered image and return a ZIP as bytes."""
    image_urls: list[tuple[str, str, str]] = []  # (img_url, page_url, kind)
    for r in results:
        if r.get("hero_image"):
            image_urls.append((r["hero_image"], r["url"], "hero"))
        if r.get("og_image"):
            image_urls.append((r["og_image"], r["url"], "og"))

    if not image_urls:
        return None

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, (img_url, page_url, kind) in enumerate(image_urls):
            progress_bar.progress(
                (idx + 1) / len(image_urls),
                text=f"Downloading image {idx + 1}/{len(image_urls)}…",
            )
            try:
                img_resp = requests.get(img_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
                img_resp.raise_for_status()
                fname = _safe_filename(img_url, page_url, kind)
                zf.writestr(fname, img_resp.content)
            except requests.RequestException:
                pass  # skip unreachable images silently
            time.sleep(0.5)  # gentle rate-limit for image downloads

    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(
        page_title="Bright Data Image Scraper",
        page_icon="🖼️",
        layout="wide",
    )

    st.title("🖼️ Bright Data — Hero & OG Image Scraper")
    st.markdown(
        "Paste Bright Data product-page URLs below (one per line) to extract "
        "**hero images** and **og:image** meta tags at scale."
    )

    # --- URL input -----------------------------------------------------------
    url_text = st.text_area(
        "Enter URLs (one per line)",
        height=220,
        placeholder=(
            "https://brightdata.com/products/web-scraper/hotwire\n"
            "https://brightdata.com/products/web-scraper/zillow\n"
            "https://brightdata.com/products/web-scraper/amazon\n"
            "…"
        ),
    )

    col_left, col_right = st.columns(2)
    with col_left:
        rate_limit = st.slider(
            "Delay between requests (seconds)",
            min_value=1.0,
            max_value=5.0,
            value=RATE_LIMIT_SECONDS,
            step=0.5,
        )
    with col_right:
        download_images = st.checkbox("Download images as ZIP when done", value=True)

    run_btn = st.button("🚀 Start Scraping", type="primary", use_container_width=True)

    # --- Scraping logic ------------------------------------------------------
    if run_btn:
        raw_urls = [u.strip() for u in url_text.splitlines() if u.strip()]
        if not raw_urls:
            st.error("Please enter at least one URL.")
            return

        # Validate URLs
        valid_urls: list[str] = []
        for u in raw_urls:
            if not u.startswith("http"):
                u = "https://" + u
            valid_urls.append(u)

        total = len(valid_urls)
        st.info(f"Scraping **{total}** URL(s) with a {rate_limit}s delay…")

        progress = st.progress(0, text="Starting…")
        results: list[dict] = []

        for idx, url in enumerate(valid_urls):
            progress.progress(
                (idx) / total,
                text=f"[{idx + 1}/{total}] Scraping {url}",
            )
            result = scrape_images(url)
            results.append(result)

            # Rate-limit (skip delay after last URL)
            if idx < total - 1:
                time.sleep(rate_limit)

        progress.progress(1.0, text="✅ Done!")

        # --- Results table ---------------------------------------------------
        st.subheader("Results")

        # Build a display-friendly table
        table_data = []
        for r in results:
            table_data.append(
                {
                    "Page URL": r["url"],
                    "Hero Image": r["hero_image"] or "—",
                    "OG Image": r["og_image"] or "—",
                    "Status": "✅" if r["status"] == "ok" else "❌",
                }
            )

        st.dataframe(
            table_data,
            use_container_width=True,
            column_config={
                "Page URL": st.column_config.LinkColumn("Page URL"),
                "Hero Image": st.column_config.LinkColumn("Hero Image"),
                "OG Image": st.column_config.LinkColumn("OG Image"),
            },
        )

        # Summary counts
        ok_count = sum(1 for r in results if r["status"] == "ok")
        hero_count = sum(1 for r in results if r["hero_image"])
        og_count = sum(1 for r in results if r["og_image"])
        st.markdown(
            f"**{ok_count}/{total}** pages scraped · "
            f"**{hero_count}** hero images · **{og_count}** OG images found"
        )

        # --- Copyable raw output --------------------------------------------
        with st.expander("📋 Copy-friendly raw output"):
            lines = []
            for r in results:
                lines.append(f"Page:  {r['url']}")
                lines.append(f"  Hero:  {r['hero_image'] or 'N/A'}")
                lines.append(f"  OG:    {r['og_image'] or 'N/A'}")
                lines.append("")
            st.code("\n".join(lines), language=None)

        # --- CSV download ----------------------------------------------------
        csv_lines = ["Page URL,Hero Image,OG Image,Status"]
        for r in results:
            csv_lines.append(
                f'"{r["url"]}","{r["hero_image"] or ""}","{r["og_image"] or ""}","{r["status"]}"'
            )
        csv_bytes = "\n".join(csv_lines).encode()

        st.download_button(
            label="⬇️ Download results as CSV",
            data=csv_bytes,
            file_name="brightdata_images.csv",
            mime="text/csv",
        )

        # --- ZIP image download (optional) -----------------------------------
        if download_images and (hero_count or og_count):
            st.subheader("📦 Download Images")
            dl_progress = st.progress(0, text="Preparing image downloads…")
            zip_bytes = build_zip(results, dl_progress)
            dl_progress.progress(1.0, text="✅ Images ready!")

            if zip_bytes:
                st.download_button(
                    label="⬇️ Download all images as ZIP",
                    data=zip_bytes,
                    file_name="brightdata_images.zip",
                    mime="application/zip",
                )


if __name__ == "__main__":
    main()
