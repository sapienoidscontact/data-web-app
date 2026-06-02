"""Sales Analytics Template."""
from .base import BaseTemplate


class SalesTemplate(BaseTemplate):
    name        = "sales"
    description = "Sales & Revenue Analytics"

    primary_kpi_keys   = ["total_revenue", "aov", "pareto", "mean", "outliers"]
    preferred_charts   = ["bar", "line", "scatter", "pie"]
    trigger_keywords   = [
        "revenue", "sales", "order", "orders", "customer", "customers",
        "product", "products", "price", "prices", "quantity", "qty",
        "units", "discount", "profit", "margin", "invoice",
    ]

    def ai_prompt_prefix(self) -> str:
        return (
            "You are a senior sales analyst. "
            "The dataset contains sales or revenue data. "
            "Focus your analysis on revenue performance, top customers or products, "
            "growth trends, and anomalies. "
            "Be specific about business implications and actionable next steps. "
        )
