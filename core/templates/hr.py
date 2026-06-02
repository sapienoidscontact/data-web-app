"""HR & People Analytics Template."""
from .base import BaseTemplate


class HRTemplate(BaseTemplate):
    name        = "hr"
    description = "HR & People Analytics"

    primary_kpi_keys   = ["headcount", "avg_salary", "gini", "null_rate", "outliers"]
    preferred_charts   = ["box", "histogram", "bar", "scatter"]
    trigger_keywords   = [
        "employee", "employees", "staff", "worker", "headcount",
        "salary", "salaries", "wage", "wages", "department",
        "hire", "tenure", "performance", "leave", "absence", "role",
    ]

    def ai_prompt_prefix(self) -> str:
        return (
            "You are a senior people analytics specialist. "
            "The dataset contains HR or workforce data. "
            "Focus your analysis on headcount trends, compensation equity, "
            "attrition risk, and performance patterns. "
            "Be sensitive about individual privacy — reference only aggregate statistics. "
        )
