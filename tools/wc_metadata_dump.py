"""
Utility script to inspect WooCommerce catalog structure for Buddy the Bear.

This script uses the same REST credentials as the main backend to export:
  - Categories          -> wc_categories.csv
  - Tags                -> wc_tags.csv
  - Attributes & terms  -> wc_attributes.csv, wc_attribute_terms.csv
  - Products (sample)   -> wc_products.csv

The file lives in a dedicated 'tools/' folder so it can be safely deleted
after you're done with discovery.
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth


# Load .env from project root (one level above /tools)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path)

WC_API_URL = os.getenv("WC_API_URL", "").rstrip("/")
WC_CONSUMER_KEY = os.getenv("WC_CONSUMER_KEY", "")
WC_CONSUMER_SECRET = os.getenv("WC_CONSUMER_SECRET", "")


def _validate_env() -> None:
    if not WC_API_URL or not WC_CONSUMER_KEY or not WC_CONSUMER_SECRET:
        print(
            "ERROR: WC_API_URL, WC_CONSUMER_KEY and WC_CONSUMER_SECRET "
            "must be set in the environment before running this script."
        )
        sys.exit(1)


session = requests.Session()
if WC_CONSUMER_KEY and WC_CONSUMER_SECRET:
    session.auth = HTTPBasicAuth(WC_CONSUMER_KEY, WC_CONSUMER_SECRET)
session.timeout = 10


def wc_get(path: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Paginate through a WooCommerce GET endpoint."""
    results: List[Dict[str, Any]] = []
    page = 1
    per_page = (params or {}).get("per_page", 100)

    while True:
        query = dict(params or {})
        query["per_page"] = per_page
        query["page"] = page

        url = f"{WC_API_URL}{path}"
        resp = session.get(url, params=query)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            break

        results.extend(data)
        if len(data) < per_page:
            break
        page += 1

    return results


def dump_categories() -> None:
    cats = wc_get("/products/categories", {"per_page": 100})
    with open("wc_categories.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "slug", "parent", "count"])
        for c in cats:
            w.writerow(
                [
                    c.get("id"),
                    c.get("name"),
                    c.get("slug"),
                    c.get("parent"),
                    c.get("count"),
                ]
            )
    print(f"[wc_metadata_dump] Wrote {len(cats)} categories -> wc_categories.csv")


def dump_tags() -> None:
    tags = wc_get("/products/tags", {"per_page": 100})
    with open("wc_tags.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "slug", "count"])
        for t in tags:
            w.writerow(
                [
                    t.get("id"),
                    t.get("name"),
                    t.get("slug"),
                    t.get("count"),
                ]
            )
    print(f"[wc_metadata_dump] Wrote {len(tags)} tags -> wc_tags.csv")


def dump_attributes_and_terms() -> None:
    attrs = wc_get("/products/attributes", {"per_page": 100})
    with open("wc_attributes.csv", "w", newline="", encoding="utf-8") as f_attr, open(
        "wc_attribute_terms.csv", "w", newline="", encoding="utf-8"
    ) as f_terms:
        wa = csv.writer(f_attr)
        wt = csv.writer(f_terms)
        wa.writerow(["id", "name", "slug", "type", "order_by"])
        wt.writerow(["attribute_id", "attribute_name", "term_id", "term_name", "term_slug"])

        for a in attrs:
            attr_id = a.get("id")
            wa.writerow(
                [
                    attr_id,
                    a.get("name"),
                    a.get("slug"),
                    a.get("type"),
                    a.get("order_by"),
                ]
            )

            terms = wc_get(f"/products/attributes/{attr_id}/terms", {"per_page": 100})
            for t in terms:
                wt.writerow(
                    [
                        attr_id,
                        a.get("name"),
                        t.get("id"),
                        t.get("name"),
                        t.get("slug"),
                    ]
                )

    print(
        "[wc_metadata_dump] Wrote "
        f"{len(attrs)} attributes -> wc_attributes.csv and wc_attribute_terms.csv"
    )


def dump_products(sample_only: bool = True, max_products: int = 500) -> None:
    """
    Dump product sample to CSV.

    Set sample_only=False if you want to export the full catalog.
    """
    params = {"per_page": 100}
    products = wc_get("/products", params)
    if sample_only:
        products = products[:max_products]

    with open("wc_products.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "id",
                "name",
                "price",
                "stock_status",
                "stock_quantity",
                "vendor",
                "categories",
                "tags",
                "attributes",
            ]
        )
        for p in products:
            cats = ";".join(
                f"{c.get('name')}|{c.get('slug')}" for c in (p.get("categories") or [])
            )
            tags = ";".join(
                f"{t.get('name')}|{t.get('slug')}" for t in (p.get("tags") or [])
            )
            attrs = ";".join(
                f"{a.get('name')}|{a.get('slug')}|{','.join(a.get('options') or [])}"
                for a in (p.get("attributes") or [])
            )
            vendor = (p.get("store") or {}).get("name")
            w.writerow(
                [
                    p.get("id"),
                    p.get("name"),
                    p.get("price"),
                    p.get("stock_status"),
                    p.get("stock_quantity"),
                    vendor,
                    cats,
                    tags,
                    attrs,
                ]
            )

    print(f"[wc_metadata_dump] Wrote {len(products)} products -> wc_products.csv")


def main() -> None:
    _validate_env()
    print("[wc_metadata_dump] Fetching WooCommerce metadata...")
    dump_categories()
    dump_tags()
    dump_attributes_and_terms()
    dump_products(sample_only=True, max_products=500)
    print("[wc_metadata_dump] Done. You can safely delete the 'tools/' folder when finished.")


if __name__ == "__main__":
    main()


