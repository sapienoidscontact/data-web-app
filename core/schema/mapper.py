"""
Business Domain Mapper — maps a SchemaProfile to a business domain.

Domains: sales, hr, finance, marketing, logistics, general

Strategy:
  1. Score each domain by counting keyword matches across column names.
  2. Boost the score for columns classified as numeric_continuous (likely KPI cols).
  3. Return the domain with the highest score; ties go to 'general'.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, Tuple

from .detector import SchemaProfile

# ── Domain keyword registry ───────────────────────────────────────────────────
# Each token that appears in a column name adds 1 point to the domain's score.
_DOMAIN_TOKENS: Dict[str, list] = {
    "sales": [
        "revenue", "sales", "sale", "order", "orders", "customer", "customers",
        "product", "products", "price", "prices", "quantity", "qty", "units",
        "discount", "profit", "margin", "invoice", "deal", "deals", "pipeline",
        "conversion", "upsell", "quota", "target", "forecast",
    ],
    "hr": [
        "employee", "employees", "staff", "worker", "workers", "headcount",
        "salary", "salaries", "wage", "wages", "compensation", "department",
        "departments", "hire", "hired", "termination", "resigned", "tenure",
        "performance", "rating", "appraisal", "leave", "absence", "training",
        "role", "position", "grade", "band", "level",
    ],
    "finance": [
        "account", "accounts", "balance", "balances", "transaction", "transactions",
        "debit", "credit", "budget", "budgets", "expense", "expenses", "income",
        "cost", "costs", "payment", "payments", "invoice", "invoices", "tax",
        "asset", "assets", "liability", "liabilities", "equity", "cashflow",
        "pnl", "ebitda", "roi", "irr", "npv", "ledger", "journal",
    ],
    "marketing": [
        "campaign", "campaigns", "impression", "impressions", "click", "clicks",
        "conversion", "conversions", "lead", "leads", "channel", "channels",
        "spend", "cpc", "cpm", "ctr", "roas", "roi", "attribution",
        "audience", "segment", "segments", "reach", "engagement", "bounce",
        "session", "sessions", "pageview", "pageviews", "subscriber",
    ],
    "logistics": [
        "shipment", "shipments", "delivery", "deliveries", "warehouse",
        "inventory", "stock", "carrier", "route", "routes", "tracking",
        "sku", "item", "items", "dispatch", "freight", "parcel", "weight",
        "dimension", "eta", "pod", "return", "returns", "lead_time",
    ],
}


def map_domain(schema: SchemaProfile) -> Tuple[str, Dict[str, int]]:
    """
    Score each business domain against column names and return the best match.

    Args:
        schema: A SchemaProfile produced by detect_schema().

    Returns:
        A tuple of (domain_name, scores_dict) where domain_name is the best
        matching domain ('sales', 'hr', 'finance', 'marketing', 'logistics',
        or 'general') and scores_dict maps every domain to its integer score.
    """
    scores: Dict[str, int] = defaultdict(int)

    for col_name, col_profile in schema.columns.items():
        tokens = set(re.split(r"[_\s\-\.]+", col_name.lower()))
        for domain, keywords in _DOMAIN_TOKENS.items():
            for kw in keywords:
                if kw in tokens or col_name.lower().startswith(kw):
                    # Boost weight for numeric columns (likely KPIs)
                    weight = 2 if col_profile.role in (
                        "numeric_continuous", "numeric_discrete"
                    ) else 1
                    scores[domain] += weight

    if not scores or max(scores.values()) == 0:
        return "general", dict(scores)

    best_domain = max(scores, key=lambda d: scores[d])
    return best_domain, dict(scores)
