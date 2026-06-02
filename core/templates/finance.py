"""Finance & Accounting Analytics Template."""
from .base import BaseTemplate


class FinanceTemplate(BaseTemplate):
    name        = "finance"
    description = "Finance & Accounting Analytics"

    primary_kpi_keys   = ["net_total", "inflows", "outflows", "in_out_ratio", "std", "outliers"]
    preferred_charts   = ["line", "bar", "histogram", "scatter"]
    trigger_keywords   = [
        "account", "accounts", "balance", "transaction", "transactions",
        "debit", "credit", "budget", "expense", "expenses", "income",
        "cost", "payment", "invoice", "tax", "asset", "liability", "equity",
    ]

    def ai_prompt_prefix(self) -> str:
        return (
            "You are a senior financial analyst. "
            "The dataset contains financial or accounting data. "
            "Focus your analysis on cash flow patterns, unusual transactions, "
            "budget variance, and ratio analysis. "
            "Flag any figures that may indicate anomalies or require audit attention. "
        )
