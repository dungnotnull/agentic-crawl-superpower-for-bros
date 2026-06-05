"""
Site Mappings — YAML-driven site configuration system.

Each site mapping defines:
  - URLs (listing, detail, pagination template)
  - Success keywords for content validation
  - JS extraction code for job cards
  - JS pagination code for next-page detection
  - Field definitions for structured JSON output
  - Block detection keywords

Mappings are loaded from YAML files in the sites/ directory.
Users can create new YAML files to add support for additional sites.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # Will fall back to built-in mappings


SITES_DIR = Path(__file__).parent / "sites"


@dataclass
class SiteURL:
    """URL configuration for a site."""
    listing_url: str
    listing_url_template: str  # Must contain {page} placeholder
    detail_url_pattern: str = ""  # Regex pattern for detail URLs


@dataclass
class SiteMapping:
    """Complete site mapping loaded from YAML or built-in defaults."""
    name: str
    display_name: str
    url: SiteURL
    success_keywords: list[str]
    js_extraction_code: str
    js_pagination_code: str
    fields: dict[str, Any] = field(default_factory=dict)

    def extract_job_id(self, detail_url: str | None) -> str | None:
        """Extract job ID from a detail URL using the site's pattern."""
        if not detail_url:
            return None
        m = re.search(r'[?&]id=(\d+)', detail_url)
        return m.group(1) if m else None


def list_available_sites() -> list[str]:
    """List all available site mapping names."""
    sites = []
    if SITES_DIR.exists():
        for f in SITES_DIR.iterdir():
            if f.suffix in (".yaml", ".yml") and f.is_file():
                sites.append(f.stem)
    # Always include built-in
    if "ekaigotenshoku" not in sites:
        sites.append("ekaigotenshoku")
    sites.sort()
    return sites


def load_site_mapping(name: str) -> SiteMapping:
    """Load a site mapping by name.

    Looks for a YAML file in sites/{name}.yaml first,
    then falls back to built-in mappings.

    If a YAML file exists but is missing JS extraction/pagination code,
    the built-in mapping's JS code is used as fallback.
    """
    yaml_path = SITES_DIR / f"{name}.yaml"
    if yaml_path.exists():
        mapping = _load_from_yaml(yaml_path)
        # If YAML didn't provide JS code, fall back to built-in
        if not mapping.js_extraction_code or not mapping.js_pagination_code:
            builtin = _get_builtin_mapping(name)
            if builtin:
                if not mapping.js_extraction_code:
                    mapping.js_extraction_code = builtin.js_extraction_code
                if not mapping.js_pagination_code:
                    mapping.js_pagination_code = builtin.js_pagination_code
        return mapping

    # Built-in mappings
    builtin = _get_builtin_mapping(name)
    if builtin:
        return builtin

    raise ValueError(
        f"Unknown site mapping: '{name}'. "
        f"Available: {', '.join(list_available_sites())}"
    )


def _get_builtin_mapping(name: str) -> SiteMapping | None:
    """Get a built-in mapping by name, or None if not available."""
    if name == "ekaigotenshoku":
        return _ekaigotenshoku_mapping()
    return None


def _load_from_yaml(path: Path) -> SiteMapping:
    """Load a site mapping from a YAML file."""
    if yaml is None:
        raise ImportError(
            "PyYAML is required for YAML site mappings. "
            "Install with: pip install pyyaml"
        )

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    url_data = data.get("url", {})
    url = SiteURL(
        listing_url=url_data.get("listing_url", ""),
        listing_url_template=url_data.get("listing_url_template",
                                           url_data.get("listing_url", "")),
        detail_url_pattern=url_data.get("detail_url_pattern", ""),
    )

    # Load JS code from separate files if referenced, otherwise inline
    extraction_code = data.get("js_extraction_code", "")
    pagination_code = data.get("js_pagination_code", "")

    # Check for external JS file references
    extraction_file = data.get("js_extraction_file")
    if extraction_file:
        js_path = path.parent / extraction_file
        if js_path.exists():
            extraction_code = js_path.read_text(encoding="utf-8")

    pagination_file = data.get("js_pagination_file")
    if pagination_file:
        js_path = path.parent / pagination_file
        if js_path.exists():
            pagination_code = js_path.read_text(encoding="utf-8")

    return SiteMapping(
        name=data.get("name", path.stem),
        display_name=data.get("display_name", data.get("name", path.stem)),
        url=url,
        success_keywords=data.get("success_keywords", []),
        js_extraction_code=extraction_code,
        js_pagination_code=pagination_code,
        fields=data.get("fields", {}),
    )


# ── Built-in mapping for ekaigotenshoku.com ──────────────────────────────

def _ekaigotenshoku_mapping() -> SiteMapping:
    """Built-in site mapping for ekaigotenshoku.com."""
    return SiteMapping(
        name="ekaigotenshoku",
        display_name="Ekaigo Tenshoku",
        url=SiteURL(
            listing_url="https://www.ekaigotenshoku.com/kyujin/list?z01=1",
            listing_url_template="https://www.ekaigotenshoku.com/kyujin?page={page}&z01=1",
            detail_url_pattern=r"/kyujin/detail\?id=(\d+)",
        ),
        success_keywords=["求人", "介護", "給与", "勤務地", "施設", "募集", "正社員"],
        js_extraction_code="""
            () => {
                let cards = [];

                // Phase 1: Target known Chakra UI card class directly
                const chakraCards = document.querySelectorAll('div.css-1lbxuix');
                if (chakraCards.length >= 10) {
                    cards = Array.from(chakraCards);
                }

                // Phase 2: Find ALL detail links, walk up to card container
                if (cards.length < 10) {
                    const detailLinks = document.querySelectorAll('a[href*="/kyujin/detail"]');
                    const seenIds = new Set();
                    const dedupedLinks = [];
                    detailLinks.forEach(a => {
                        const href = a.getAttribute('href');
                        if (!href) return;
                        const m = href.match(/[?&]id=(\\d+)/);
                        const id = m ? m[1] : href;
                        if (!seenIds.has(id)) {
                            seenIds.add(id);
                            dedupedLinks.push(a);
                        }
                    });

                    const fallbackCards = [];
                    dedupedLinks.forEach(a => {
                        let parent = a.closest('div');
                        while (parent && parent !== document.body) {
                            const tag = parent.tagName.toLowerCase();
                            const cls = parent.className || '';
                            if (tag === 'div' && cls.length > 0) {
                                fallbackCards.push(parent);
                                break;
                            }
                            parent = parent.parentElement;
                        }
                    });
                    if (fallbackCards.length > cards.length) {
                        cards = fallbackCards;
                    }
                }

                // Phase 3: Generic fallback selectors (last resort)
                if (cards.length < 3) {
                    const selectors = [
                        '.jobList li', '.job-list-item', '.p-jobList__item',
                        '.kyujin-list li', '[class*="jobList"] > li',
                        '.job-item', '.kyujin-item', '.recruit-item',
                        '[class*="job-list"] > li', '[class*="kyujin"] li',
                        '[class*="recruit"] li', 'article.job',
                        '.search-result-item', '.list-item', '[class*="card"]'
                    ];
                    for (const sel of selectors) {
                        const found = document.querySelectorAll(sel);
                        if (found.length > 2) { cards = Array.from(found); break; }
                    }
                }
                if (!cards.length) {
                    cards = Array.from(document.querySelectorAll('main li, article, section li'));
                }

                const out = [];
                const seenOut = new Set();

                cards.forEach(card => {
                    const getText = (...sels) => {
                        for (const s of sels) {
                            const el = card.querySelector(s);
                            if (el) {
                                const t = el.textContent.trim();
                                if (t) return t;
                            }
                        }
                        return null;
                    };

                    const getVisibleText = (...sels) => {
                        for (const s of sels) {
                            const el = card.querySelector(s);
                            if (el) {
                                const t = el.innerText.trim() || el.textContent.trim();
                                if (t) return t;
                            }
                        }
                        return null;
                    };

                    const title = getVisibleText('h2', 'h3', 'h4', '.title', '[class*="title"]', '[class*="name"]');
                    const detailEl = card.querySelector('a[href*="/kyujin/detail"]') || card.querySelector('a');
                    const link = detailEl ? detailEl.href : null;

                    let idKey = null;
                    if (link) {
                        const m = link.match(/[?&]id=(\\d+)/);
                        idKey = m ? m[1] : link;
                    }
                    if (!idKey) idKey = title;
                    if (seenOut.has(idKey)) return;
                    seenOut.add(idKey);

                    let salary = null;
                    let jobType = null;
                    card.querySelectorAll('table tr').forEach(tr => {
                        const th = tr.querySelector('th');
                        const td = tr.querySelector('td');
                        if (th && td) {
                            const thText = th.textContent.trim();
                            if (thText.includes('給与')) {
                                salary = td.textContent.trim();
                            } else if (thText.includes('雇用形態') || thText.includes('職種') || thText.includes('サービス')) {
                                jobType = (jobType ? jobType + ' | ' : '') + td.textContent.trim();
                            }
                        }
                    });

                    if (!salary) salary = getText('[class*="salary"]', '[class*="kyuyo"]', '[class*="wage"]', '[class*="pay"]');
                    if (!jobType) jobType = getText('[class*="type"]', '[class*="employment"]', '[class*="koyou"]');
                    const company = getText('.company', '[class*="company"]', '[class*="facility"]', '[class*="office"]');

                    let location = getText('[class*="location"]', '[class*="address"]', '[class*="area"]', '[class*="place"]');
                    if (!location) {
                        const locBadge = card.querySelector('span[name]:not([name="おすすめ"]):not([name="派遣"]):not([name="正社員"]):not([name="パート"])');
                        if (locBadge) location = locBadge.textContent.trim();
                    }

                    if (title) out.push({title, company, salary, location, jobType, link, detail_url: link});
                });
                return out;
            }
        """,
        js_pagination_code="""
            () => {
                const nextImg = document.querySelector('img[src*="next-button"], img[src*="next_button"], img[src*="arrow-right"]');
                if (nextImg) {
                    const a = nextImg.closest('a');
                    if (a && a.href) return a.href;
                }
                const sels = ['a[rel="next"]', '.pagination .next a', '.pager-next a',
                              '[aria-label="次のページ"]', '.pager a[class*="next"]',
                              '.pagination a[class*="next"]'];
                for (const s of sels) {
                    try {
                        const el = document.querySelector(s);
                        if (el && el.href) return el.href;
                    } catch(e) {}
                }
                try {
                    const nextLinks = document.querySelectorAll('[class*="next"] a, a[class*="next"]');
                    for (const el of nextLinks) {
                        if (el.href && !el.closest('.swiper-slide, .swiper, .carousel, [class*="swiper"], [class*="carousel"]')) {
                            return el.href;
                        }
                    }
                } catch(e) {}
                for (const a of document.querySelectorAll('a')) {
                    if (/次へ|次のページ/.test(a.innerText) && a.href) return a.href;
                }
                return null;
            }
        """,
        fields={
            "job_id": "job_id",
            "title": "title",
            "company": "company",
            "salary": "salary",
            "location": "location",
            "employment_type": "jobType",
            "detail_url": "detail_url",
        },
    )
