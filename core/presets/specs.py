"""
Industry Preset Specifications — 15 presets, fully declarative.

Source of truth for requirements: docs/INDUSTRY_PRESETS.md and docs/VISUAL_PRESETS.md.
Every KPI is built from the shared primitives in kpis.py; every chart binds to
canonical fields and is skipped gracefully when a field is unmapped.
"""

from __future__ import annotations

from typing import List

from .model import ChartSpec as C, FieldSpec as F, KPISpec as K, PresetSpec


# ══════════════════════════════════════════════════════════════════════════════
# 1. RETAIL & E-COMMERCE
# ══════════════════════════════════════════════════════════════════════════════
RETAIL = PresetSpec(
    name="retail", label="Retail & E-commerce", icon="🛒",
    keywords=["sku", "order", "sales", "revenue", "product", "store", "qty",
              "basket", "pos", "item", "invoice", "customer"],
    primary_metric="revenue",
    fields=[
        F("order_date", "temporal", ["date", "order date", "bill date", "invoice date",
          "txn date", "created at", "purchase date"], required=True),
        F("revenue", "numeric", ["amount", "total", "net amount", "sales", "gross sales",
          "line total", "amt", "value", "revenue", "sale amount"], required=True),
        F("quantity", "numeric", ["qty", "quantity", "units", "pcs", "nos", "items"]),
        F("product", "categorical", ["product", "item", "item name", "sku",
          "description", "product title", "product name"], required=True),
        F("order_id", "identifier", ["order id", "order no", "bill no", "invoice no",
          "receipt", "transaction id"]),
        F("category", "categorical", ["category", "product type", "department", "group"]),
        F("store", "categorical", ["store", "location", "branch", "outlet", "channel",
          "marketplace"]),
        F("customer_id", "identifier", ["customer", "customer id", "buyer", "email",
          "customer name"]),
        F("discount", "numeric", ["discount", "promo", "coupon amount", "markdown"]),
        F("cost", "numeric", ["cost", "cogs", "purchase price", "landed cost"]),
    ],
    kpis=[
        K("total_revenue", "Total Revenue", "sum", {"field": "revenue"}, "currency",
          "up_good", "Sum of all sales"),
        K("order_count", "Orders", "distinct", {"field": "order_id", "fallback_rows": True},
          "integer", "up_good", "Distinct orders (or rows)"),
        K("aov", "Avg Order Value", "ratio", {"num": "total_revenue", "den": "order_count"},
          "currency", "up_good", "Revenue per order"),
        K("units_sold", "Units Sold", "sum", {"field": "quantity"}, "integer", "up_good",
          "Total quantity"),
        K("revenue_growth", "Revenue Growth", "growth", {"kpi": "total_revenue"},
          "percent", "up_good", "Latest vs previous period"),
        K("top_product_share", "Top-10 Product Share", "top_share",
          {"by": "product", "field": "revenue", "n": 10}, "percent", "neutral",
          "% of revenue from top 10 products"),
        K("discount_total", "Discounts Given", "sum", {"field": "discount"}, "currency",
          "up_bad", "Total discount value"),
        K("customers", "Unique Customers", "distinct", {"field": "customer_id"},
          "integer", "up_good", "Distinct customers"),
    ],
    tiles=["total_revenue", "revenue_growth", "order_count", "aov"],
    charts=[
        C("line", "Revenue trend", x="order_date", y="revenue"),
        C("bar", "Top products by revenue", x="product", y="revenue", top_n=10),
        C("donut", "Revenue by category", x="category", y="revenue"),
        C("bar", "Revenue by store / channel", x="store", y="revenue"),
        C("heat_dow", "Sales pattern by weekday", x="order_date", y="revenue"),
    ],
    filters=["order_date", "store", "category"],
    ai_prompt=("You are a senior retail analyst. Focus on sell-through, basket "
               "economics, product mix, store performance, promotion effectiveness "
               "and restock recommendations. Be specific and action-oriented."),
    report_tone="monthly sales review",
)

# ══════════════════════════════════════════════════════════════════════════════
# 2. B2B SALES & CRM
# ══════════════════════════════════════════════════════════════════════════════
SALES_CRM = PresetSpec(
    name="sales_crm", label="B2B Sales & CRM", icon="🤝",
    keywords=["deal", "opportunity", "pipeline", "stage", "lead", "account",
              "close", "won", "quota", "crm"],
    primary_metric="deal_value",
    fields=[
        F("deal_value", "numeric", ["amount", "deal value", "opportunity value", "acv",
          "contract value", "expected revenue", "value"], required=True),
        F("stage", "categorical", ["stage", "deal stage", "status", "pipeline stage",
          "phase"], required=True,
          value_vocab=["closed won", "closed lost", "negotiation", "proposal",
                       "qualified", "prospecting", "discovery", "demo"]),
        F("created_date", "temporal", ["created", "created date", "open date",
          "start date"], required=True),
        F("close_date", "temporal", ["close date", "closed", "won date",
          "expected close", "closed date"]),
        F("owner", "categorical", ["owner", "rep", "salesperson", "account executive",
          "assigned to", "sales rep"]),
        F("account", "categorical", ["account", "company", "customer", "client",
          "organization"]),
        F("source", "categorical", ["source", "lead source", "channel", "campaign"]),
    ],
    kpis=[
        K("pipeline_value", "Total Pipeline", "sum", {"field": "deal_value"}, "currency",
          "up_good", "Sum of all deal values"),
        K("deal_count", "Deals", "rows", {}, "integer", "up_good", "Number of deals"),
        K("avg_deal", "Avg Deal Size", "mean", {"field": "deal_value"}, "currency",
          "up_good", "Mean deal value"),
        K("win_rate", "Win Rate", "rate", {"field": "stage",
          "values": ["won", "closed won", "closed-won"]}, "percent", "up_good",
          "Share of deals won"),
        K("sales_cycle", "Avg Sales Cycle", "date_diff",
          {"start": "created_date", "end": "close_date"}, "days", "up_bad",
          "Days from creation to close"),
        K("pipeline_growth", "New Pipeline Growth", "growth", {"kpi": "pipeline_value"},
          "percent", "up_good", "Latest vs previous period"),
        K("top_account_share", "Top-10 Account Share", "top_share",
          {"by": "account", "field": "deal_value", "n": 10}, "percent", "neutral",
          "Concentration in top accounts"),
    ],
    tiles=["pipeline_value", "win_rate", "avg_deal", "sales_cycle"],
    charts=[
        C("funnel", "Pipeline by stage", x="stage", y="deal_value"),
        C("line", "New pipeline created", x="created_date", y="deal_value"),
        C("bar", "Pipeline by owner", x="owner", y="deal_value"),
        C("bar", "Pipeline by source", x="source", y="deal_value"),
        C("scatter", "Deal size vs cycle", x="created_date", y="deal_value",
          color="stage"),
    ],
    filters=["created_date", "owner", "stage", "source"],
    ai_prompt=("You are a sales operations analyst. Focus on pipeline health and "
               "coverage, funnel conversion between stages, rep performance, deal "
               "velocity, slippage and forecast confidence."),
    report_tone="weekly pipeline review",
)

# ══════════════════════════════════════════════════════════════════════════════
# 3. FINANCE & ACCOUNTING
# ══════════════════════════════════════════════════════════════════════════════
FINANCE = PresetSpec(
    name="finance", label="Finance & Accounting", icon="💰",
    keywords=["ledger", "debit", "credit", "expense", "income", "balance", "budget",
              "voucher", "account", "cashflow", "transaction", "payment"],
    primary_metric="amount",
    fields=[
        F("txn_date", "temporal", ["date", "txn date", "transaction date", "value date",
          "posting date", "voucher date"], required=True),
        F("amount", "numeric", ["amount", "value", "net", "net amount", "txn amount"],
          required=True),
        F("account", "categorical", ["account", "ledger", "account name", "category",
          "head", "particulars", "expense category"], required=True),
        F("type", "categorical", ["type", "txn type", "dr/cr", "voucher type",
          "income/expense", "transaction type"],
          value_vocab=["debit", "credit", "income", "expense", "dr", "cr"]),
        F("party", "categorical", ["party", "vendor", "payee", "customer", "narration",
          "merchant"]),
        F("debit", "numeric", ["debit", "dr", "withdrawal", "paid out", "expense amount"]),
        F("credit", "numeric", ["credit", "cr", "deposit", "paid in", "income amount"]),
        F("budget", "numeric", ["budget", "budgeted", "plan", "target"]),
    ],
    kpis=[
        K("net_total", "Net Cashflow", "sum", {"field": "amount"}, "currency", "up_good",
          "Sum including negatives"),
        K("inflows", "Inflows", "sum", {"field": "amount", "positive_only": True},
          "currency", "up_good", "Sum of positive amounts"),
        K("outflows", "Outflows", "sum", {"field": "amount", "negative_only": True},
          "currency", "up_bad", "Sum of negative amounts"),
        K("txn_count", "Transactions", "rows", {}, "integer", "neutral", "Row count"),
        K("net_growth", "Net Flow Growth", "growth", {"kpi": "net_total"}, "percent",
          "up_good", "Latest vs previous period"),
        K("top_head_share", "Top-5 Account Share", "top_share",
          {"by": "account", "field": "amount", "n": 5, "absolute": True}, "percent",
          "neutral", "Concentration of value in top account heads"),
        K("avg_txn", "Avg Transaction", "mean", {"field": "amount"}, "currency",
          "neutral", "Mean transaction value"),
    ],
    tiles=["net_total", "inflows", "outflows", "net_growth"],
    charts=[
        C("line", "Net flow over time", x="txn_date", y="amount"),
        C("bar", "Value by account head", x="account", y="amount", top_n=10,
          options={"absolute": True}),
        C("stacked_bar", "Flows by type over time", x="txn_date", y="amount",
          color="type"),
        C("bar", "Top parties by value", x="party", y="amount", top_n=10,
          options={"absolute": True}),
        C("hist", "Transaction size distribution", x="amount"),
    ],
    filters=["txn_date", "account", "type"],
    ai_prompt=("You are a financial analyst. Focus on liquidity, burn rate, expense "
               "category trends, budget variance, and unusual transactions. Use a "
               "conservative tone; do not give investment advice."),
    report_tone="monthly finance pack",
)

# ══════════════════════════════════════════════════════════════════════════════
# 4. HR & PEOPLE ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════
HR = PresetSpec(
    name="hr", label="HR & People Analytics", icon="🧑‍💼",
    keywords=["employee", "salary", "department", "designation", "attrition",
              "headcount", "joining", "hr", "tenure", "ctc"],
    primary_metric="salary",
    fields=[
        F("employee_id", "identifier", ["employee id", "emp id", "staff id",
          "employee code", "emp code", "employee name"], required=True),
        F("department", "categorical", ["department", "dept", "function", "team",
          "business unit"], required=True),
        F("salary", "numeric", ["salary", "ctc", "gross pay", "compensation",
          "annual salary", "wage", "monthly salary"]),
        F("join_date", "temporal", ["join date", "date of joining", "doj", "hire date",
          "start date"]),
        F("exit_date", "temporal", ["exit date", "termination date", "last working day",
          "resignation date", "leaving date"]),
        F("role", "categorical", ["designation", "role", "title", "position", "grade",
          "band", "level", "job title"]),
        F("gender", "categorical", ["gender", "sex"],
          value_vocab=["male", "female", "m", "f", "other"]),
        F("location", "categorical", ["location", "office", "city", "site"]),
        F("performance", "numeric", ["rating", "performance", "appraisal score",
          "performance rating"]),
    ],
    kpis=[
        K("headcount", "Headcount", "distinct", {"field": "employee_id",
          "fallback_rows": True}, "integer", "up_good", "Distinct employees"),
        K("median_salary", "Median Salary", "median", {"field": "salary"}, "currency",
          "neutral", "Median compensation"),
        K("exit_share", "Exited Share", "rate_notnull", {"field": "exit_date"},
          "percent", "up_bad", "Share of records with an exit date"),
        K("avg_tenure", "Avg Tenure", "date_diff", {"start": "join_date",
          "end": "exit_date", "open_end": "today", "unit": "years"}, "years", "up_good",
          "Mean years from joining"),
        K("avg_rating", "Avg Performance", "mean", {"field": "performance"}, "number",
          "up_good", "Mean performance rating"),
        K("salary_top_dept_share", "Top-5 Dept Salary Share", "top_share",
          {"by": "department", "field": "salary", "n": 5}, "percent", "neutral",
          "Payroll concentration"),
    ],
    tiles=["headcount", "median_salary", "exit_share", "avg_tenure"],
    charts=[
        C("bar", "Headcount by department", x="department", y=None, agg="count"),
        C("box", "Salary by department", x="department", y="salary"),
        C("line", "Hiring over time", x="join_date", y=None, agg="count"),
        C("donut", "Gender mix", x="gender", y=None, agg="count"),
        C("bar", "Median salary by role", x="role", y="salary", agg="median", top_n=12),
    ],
    filters=["department", "location", "role"],
    ai_prompt=("You are a people-analytics partner. Focus on retention risk, "
               "compensation equity, org shape and hiring-vs-exit balance. Use "
               "neutral, compliant language. Never identify individuals — discuss "
               "aggregates only."),
    report_tone="quarterly people review",
)

# ══════════════════════════════════════════════════════════════════════════════
# 5. MARKETING & DIGITAL ADVERTISING
# ══════════════════════════════════════════════════════════════════════════════
MARKETING = PresetSpec(
    name="marketing", label="Marketing & Ads", icon="📣",
    keywords=["campaign", "impressions", "clicks", "spend", "ctr", "cpc", "roas",
              "conversions", "ad", "adset", "channel"],
    primary_metric="spend",
    fields=[
        F("date", "temporal", ["date", "day", "reporting date", "week"], required=True),
        F("spend", "numeric", ["spend", "cost", "amount spent", "ad spend",
          "budget spent"], required=True),
        F("impressions", "numeric", ["impressions", "impr", "views", "reach"]),
        F("clicks", "numeric", ["clicks", "link clicks", "sessions", "visits"]),
        F("conversions", "numeric", ["conversions", "results", "purchases", "leads",
          "signups", "installs"]),
        F("conversion_value", "numeric", ["conversion value", "revenue",
          "purchase value", "sales value"]),
        F("campaign", "categorical", ["campaign", "campaign name", "ad set",
          "ad group", "adset name"], required=True),
        F("channel", "categorical", ["channel", "platform", "source", "medium",
          "network"]),
    ],
    kpis=[
        K("total_spend", "Total Spend", "sum", {"field": "spend"}, "currency", "up_bad",
          "Total ad spend"),
        K("total_conversions", "Conversions", "sum", {"field": "conversions"},
          "integer", "up_good", "Total conversions"),
        K("total_clicks", "Clicks", "sum", {"field": "clicks"}, "integer", "up_good",
          "Total clicks"),
        K("total_impressions", "Impressions", "sum", {"field": "impressions"},
          "integer", "up_good", "Total impressions"),
        K("cpa", "Cost per Conversion", "ratio", {"num": "total_spend",
          "den": "total_conversions"}, "currency", "up_bad", "Spend ÷ conversions"),
        K("cpc", "Cost per Click", "ratio", {"num": "total_spend",
          "den": "total_clicks"}, "currency", "up_bad", "Spend ÷ clicks"),
        K("ctr", "CTR", "ratio", {"num": "total_clicks", "den": "total_impressions",
          "as_percent": True}, "percent", "up_good", "Clicks ÷ impressions"),
        K("total_value", "Conversion Value", "sum", {"field": "conversion_value"},
          "currency", "up_good", "Revenue attributed"),
        K("roas", "ROAS", "ratio", {"num": "total_value", "den": "total_spend"},
          "ratio", "up_good", "Value ÷ spend"),
        K("spend_growth", "Spend Growth", "growth", {"kpi": "total_spend"}, "percent",
          "neutral", "Latest vs previous period"),
    ],
    tiles=["total_spend", "total_conversions", "cpa", "roas"],
    charts=[
        C("line", "Spend over time", x="date", y="spend"),
        C("line", "Conversions over time", x="date", y="conversions"),
        C("bar", "Spend by campaign", x="campaign", y="spend", top_n=10),
        C("stacked_bar", "Spend by channel over time", x="date", y="spend",
          color="channel"),
        C("scatter", "Spend vs conversions by campaign", x="spend", y="conversions",
          color="channel", options={"group_by": "campaign"}),
    ],
    filters=["date", "channel", "campaign"],
    ai_prompt=("You are a performance-marketing analyst. Focus on budget "
               "reallocation, CPA/ROAS efficiency by campaign and channel, creative "
               "fatigue and funnel bottlenecks. Recommend concrete budget shifts."),
    report_tone="weekly performance report",
)

# ══════════════════════════════════════════════════════════════════════════════
# 6. LOGISTICS & SUPPLY CHAIN
# ══════════════════════════════════════════════════════════════════════════════
LOGISTICS = PresetSpec(
    name="logistics", label="Logistics & Supply Chain", icon="🚚",
    keywords=["shipment", "awb", "carrier", "delivery", "courier", "freight",
              "tracking", "dispatch", "warehouse", "consignment"],
    primary_metric="cost",
    fields=[
        F("ship_date", "temporal", ["ship date", "dispatch date", "pickup date",
          "order date", "shipped on"], required=True),
        F("status", "categorical", ["status", "delivery status", "shipment status",
          "current status"], required=True,
          value_vocab=["delivered", "in transit", "rto", "returned", "out for delivery",
                       "pending", "exception", "lost"]),
        F("delivery_date", "temporal", ["delivery date", "delivered on", "pod date"]),
        F("promised_date", "temporal", ["promised date", "edd", "expected delivery",
          "eta"]),
        F("carrier", "categorical", ["carrier", "courier", "transporter", "partner",
          "3pl", "courier partner"]),
        F("cost", "numeric", ["freight", "shipping cost", "charge", "freight amount",
          "shipping charge"]),
        F("weight", "numeric", ["weight", "chargeable weight", "kg"]),
        F("origin", "categorical", ["origin", "from", "pickup city", "source city"]),
        F("destination", "categorical", ["destination", "to", "zone", "pincode",
          "delivery city"]),
        F("shipment_id", "identifier", ["awb", "tracking no", "lr no", "shipment id",
          "consignment", "awb number"]),
    ],
    kpis=[
        K("shipments", "Shipments", "distinct", {"field": "shipment_id",
          "fallback_rows": True}, "integer", "up_good", "Total shipments"),
        K("delivered_rate", "Delivered %", "rate", {"field": "status",
          "values": ["delivered"]}, "percent", "up_good", "Share delivered"),
        K("rto_rate", "RTO / Return %", "rate", {"field": "status",
          "values": ["rto", "returned", "return"]}, "percent", "up_bad",
          "Share returned to origin"),
        K("avg_transit", "Avg Transit Days", "date_diff", {"start": "ship_date",
          "end": "delivery_date"}, "days", "up_bad", "Ship → delivery days"),
        K("total_freight", "Total Freight", "sum", {"field": "cost"}, "currency",
          "up_bad", "Total shipping cost"),
        K("cost_per_shipment", "Cost / Shipment", "ratio", {"num": "total_freight",
          "den": "shipments"}, "currency", "up_bad", "Freight ÷ shipments"),
        K("volume_growth", "Volume Growth", "growth", {"kpi": "shipments"}, "percent",
          "up_good", "Latest vs previous period"),
    ],
    tiles=["shipments", "delivered_rate", "avg_transit", "cost_per_shipment"],
    charts=[
        C("line", "Shipments over time", x="ship_date", y=None, agg="count"),
        C("bar", "Shipments by carrier", x="carrier", y=None, agg="count"),
        C("stacked_bar", "Status mix over time", x="ship_date", y=None, agg="count",
          color="status"),
        C("bar", "Freight cost by carrier", x="carrier", y="cost"),
        C("bar", "Top destinations", x="destination", y=None, agg="count", top_n=12),
    ],
    filters=["ship_date", "carrier", "status", "destination"],
    ai_prompt=("You are a supply-chain analyst. Focus on SLA breaches, carrier "
               "scorecards, transit-time by lane, RTO reduction and cost per "
               "shipment."),
    report_tone="monthly ops review",
)

# ══════════════════════════════════════════════════════════════════════════════
# 7. MANUFACTURING & PRODUCTION
# ══════════════════════════════════════════════════════════════════════════════
MANUFACTURING = PresetSpec(
    name="manufacturing", label="Manufacturing & Production", icon="🏭",
    keywords=["production", "machine", "shift", "defect", "downtime", "batch",
              "output", "line", "plant", "rejects"],
    primary_metric="output_qty",
    fields=[
        F("date", "temporal", ["date", "production date", "shift date"], required=True),
        F("output_qty", "numeric", ["output", "produced", "quantity", "good qty",
          "units produced", "actual", "production qty"], required=True),
        F("planned_qty", "numeric", ["plan", "target", "planned", "scheduled qty",
          "plan qty"]),
        F("defect_qty", "numeric", ["defects", "rejects", "rework", "scrap", "ng qty",
          "rejection"]),
        F("machine", "categorical", ["machine", "line", "equipment", "work center",
          "station"]),
        F("shift", "categorical", ["shift", "shift name"],
          value_vocab=["a", "b", "c", "day", "night", "general"]),
        F("product", "categorical", ["product", "item", "part no", "sku", "batch"]),
        F("downtime_min", "numeric", ["downtime", "stoppage", "breakdown minutes",
          "idle time", "downtime minutes"]),
    ],
    kpis=[
        K("total_output", "Total Output", "sum", {"field": "output_qty"}, "integer",
          "up_good", "Units produced"),
        K("total_planned", "Planned Output", "sum", {"field": "planned_qty"}, "integer",
          "neutral", "Units planned"),
        K("plan_attainment", "Plan Attainment", "ratio", {"num": "total_output",
          "den": "total_planned", "as_percent": True}, "percent", "up_good",
          "Output ÷ plan"),
        K("total_defects", "Defects", "sum", {"field": "defect_qty"}, "integer",
          "up_bad", "Defective units"),
        K("defect_rate", "Defect Rate", "ratio", {"num": "total_defects",
          "den": "total_output", "as_percent": True}, "percent", "up_bad",
          "Defects ÷ output"),
        K("downtime_hours", "Downtime (hrs)", "sum", {"field": "downtime_min",
          "scale": 1 / 60}, "number", "up_bad", "Total downtime hours"),
        K("output_growth", "Output Growth", "growth", {"kpi": "total_output"},
          "percent", "up_good", "Latest vs previous period"),
    ],
    tiles=["total_output", "plan_attainment", "defect_rate", "downtime_hours"],
    charts=[
        C("line", "Output vs time", x="date", y="output_qty"),
        C("bar", "Output by machine / line", x="machine", y="output_qty"),
        C("bar", "Defects by product", x="product", y="defect_qty", top_n=10),
        C("stacked_bar", "Output by shift over time", x="date", y="output_qty",
          color="shift"),
        C("bar", "Downtime by machine", x="machine", y="downtime_min"),
    ],
    filters=["date", "machine", "shift", "product"],
    ai_prompt=("You are a production analyst. Focus on bottlenecks, defect Pareto, "
               "downtime causes, plan attainment and OEE improvement."),
    report_tone="weekly production review",
)

# ══════════════════════════════════════════════════════════════════════════════
# 8. HEALTHCARE
# ══════════════════════════════════════════════════════════════════════════════
HEALTHCARE = PresetSpec(
    name="healthcare", label="Healthcare (Clinic / Hospital)", icon="🏥",
    keywords=["patient", "doctor", "appointment", "opd", "ipd", "diagnosis",
              "admission", "hospital", "clinic", "consultation"],
    primary_metric="revenue",
    fields=[
        F("visit_date", "temporal", ["date", "visit date", "appointment date",
          "admission date", "bill date"], required=True),
        F("department", "categorical", ["department", "specialty", "unit", "ward",
          "service"], required=True),
        F("patient_id", "identifier", ["patient id", "mrn", "uhid", "reg no",
          "patient name"]),
        F("doctor", "categorical", ["doctor", "physician", "consultant", "provider"]),
        F("revenue", "numeric", ["amount", "bill amount", "charges", "fee",
          "net amount"]),
        F("visit_type", "categorical", ["visit type", "opd/ipd", "appointment type",
          "type"], value_vocab=["opd", "ipd", "new", "follow-up", "followup",
                                "emergency"]),
        F("status", "categorical", ["status", "appointment status"],
          value_vocab=["completed", "no-show", "no show", "cancelled", "scheduled"]),
        F("discharge_date", "temporal", ["discharge date", "end date"]),
    ],
    kpis=[
        K("visits", "Patient Visits", "rows", {}, "integer", "up_good", "Total visits"),
        K("unique_patients", "Unique Patients", "distinct", {"field": "patient_id"},
          "integer", "up_good", "Distinct patients"),
        K("total_revenue", "Revenue", "sum", {"field": "revenue"}, "currency",
          "up_good", "Total billing"),
        K("revenue_per_visit", "Revenue / Visit", "ratio", {"num": "total_revenue",
          "den": "visits"}, "currency", "up_good", "Billing per visit"),
        K("no_show_rate", "No-show Rate", "rate", {"field": "status",
          "values": ["no-show", "no show", "noshow"]}, "percent", "up_bad",
          "Missed appointments"),
        K("avg_los", "Avg Length of Stay", "date_diff", {"start": "visit_date",
          "end": "discharge_date"}, "days", "up_bad", "Admission → discharge"),
        K("visit_growth", "Visit Growth", "growth", {"kpi": "visits"}, "percent",
          "up_good", "Latest vs previous period"),
    ],
    tiles=["visits", "total_revenue", "no_show_rate", "revenue_per_visit"],
    charts=[
        C("line", "Visits over time", x="visit_date", y=None, agg="count"),
        C("bar", "Revenue by department", x="department", y="revenue"),
        C("bar", "Visits by doctor", x="doctor", y=None, agg="count", top_n=12),
        C("donut", "Visit type mix", x="visit_type", y=None, agg="count"),
        C("heat_dow", "Demand by weekday", x="visit_date", y=None),
    ],
    filters=["visit_date", "department", "doctor", "visit_type"],
    ai_prompt=("You are a healthcare operations analyst. Focus on capacity, no-show "
               "reduction, department revenue mix and demand patterns. Never discuss "
               "individual patients; clinical-outcome claims are out of scope."),
    report_tone="monthly operations & revenue review",
)

# ══════════════════════════════════════════════════════════════════════════════
# 9. EDUCATION
# ══════════════════════════════════════════════════════════════════════════════
EDUCATION = PresetSpec(
    name="education", label="Education (School / Coaching)", icon="🎓",
    keywords=["student", "marks", "attendance", "class", "batch", "exam", "fee",
              "subject", "grade", "roll"],
    primary_metric="score",
    fields=[
        F("student_id", "identifier", ["student id", "roll no", "admission no",
          "enrollment no", "student name"], required=True),
        F("class_group", "categorical", ["class", "grade", "batch", "course",
          "section", "standard"], required=True),
        F("score", "numeric", ["marks", "score", "percentage", "grade points",
          "result", "total marks"]),
        F("subject", "categorical", ["subject", "paper", "module", "course name"]),
        F("date", "temporal", ["date", "attendance date", "exam date", "payment date"]),
        F("attendance", "numeric", ["present", "attendance", "days present",
          "attendance %", "attendance percentage"]),
        F("fee_paid", "numeric", ["fee paid", "amount paid", "received", "paid"]),
        F("fee_due", "numeric", ["due", "balance", "outstanding", "pending"]),
        F("teacher", "categorical", ["teacher", "faculty", "instructor"]),
    ],
    kpis=[
        K("students", "Students", "distinct", {"field": "student_id",
          "fallback_rows": True}, "integer", "up_good", "Distinct students"),
        K("avg_score", "Avg Score", "mean", {"field": "score"}, "number", "up_good",
          "Mean marks"),
        K("avg_attendance", "Avg Attendance", "mean", {"field": "attendance"},
          "number", "up_good", "Mean attendance"),
        K("fees_collected", "Fees Collected", "sum", {"field": "fee_paid"}, "currency",
          "up_good", "Total received"),
        K("fees_outstanding", "Fees Outstanding", "sum", {"field": "fee_due"},
          "currency", "up_bad", "Total pending"),
        K("collection_rate", "Collection Rate", "ratio", {"num": "fees_collected",
          "den_sum": ["fees_collected", "fees_outstanding"], "as_percent": True},
          "percent", "up_good", "Paid ÷ (paid + due)"),
    ],
    tiles=["students", "avg_score", "avg_attendance", "collection_rate"],
    charts=[
        C("box", "Scores by subject", x="subject", y="score"),
        C("bar", "Avg score by class / batch", x="class_group", y="score", agg="mean"),
        C("hist", "Score distribution", x="score"),
        C("bar", "Outstanding fees by class", x="class_group", y="fee_due"),
        C("line", "Attendance over time", x="date", y="attendance", agg="mean"),
    ],
    filters=["class_group", "subject", "date"],
    ai_prompt=("You are an education analyst. Focus on learning outcomes, the "
               "attendance-performance link, batch variance and fee-collection "
               "risk. Discuss aggregates only; never name individual students."),
    report_tone="term report",
)

# ══════════════════════════════════════════════════════════════════════════════
# 10. REAL ESTATE & PROPERTY
# ══════════════════════════════════════════════════════════════════════════════
REAL_ESTATE = PresetSpec(
    name="real_estate", label="Real Estate & Property", icon="🏢",
    keywords=["property", "unit", "flat", "tower", "bhk", "sqft", "booking", "rent",
              "lease", "project", "broker"],
    primary_metric="price",
    fields=[
        F("unit_id", "identifier", ["unit", "flat no", "unit no", "property id",
          "plot no"], required=True),
        F("price", "numeric", ["price", "sale price", "rent", "agreement value",
          "asking price", "amount"], required=True),
        F("status", "categorical", ["status", "availability"], required=True,
          value_vocab=["sold", "booked", "available", "rented", "vacant", "blocked",
                       "occupied"]),
        F("area_sqft", "numeric", ["area", "sqft", "carpet area", "built-up",
          "super area", "size"]),
        F("project", "categorical", ["project", "tower", "building", "property",
          "society", "community"]),
        F("unit_type", "categorical", ["type", "bhk", "configuration", "layout",
          "category"]),
        F("date", "temporal", ["booking date", "sale date", "agreement date",
          "lease start", "date"]),
        F("broker", "categorical", ["broker", "agent", "channel partner",
          "lead source", "source"]),
    ],
    kpis=[
        K("units_total", "Total Units", "distinct", {"field": "unit_id",
          "fallback_rows": True}, "integer", "neutral", "Units in inventory"),
        K("sold_rate", "Sold / Occupied %", "rate", {"field": "status",
          "values": ["sold", "booked", "rented", "occupied"]}, "percent", "up_good",
          "Absorption / occupancy"),
        K("total_value", "Total Value", "sum", {"field": "price"}, "currency",
          "up_good", "Sum of unit values"),
        K("avg_price", "Avg Price", "mean", {"field": "price"}, "currency", "neutral",
          "Mean unit price"),
        K("price_per_sqft", "Price / Sqft", "ratio_fields", {"num_field": "price",
          "den_field": "area_sqft"}, "currency", "neutral", "Σprice ÷ Σarea"),
        K("booking_growth", "Booking Growth", "growth", {"kpi": "units_total"},
          "percent", "up_good", "Latest vs previous period"),
    ],
    tiles=["units_total", "sold_rate", "avg_price", "price_per_sqft"],
    charts=[
        C("stacked_bar", "Inventory status by project", x="project", y=None,
          agg="count", color="status"),
        C("line", "Bookings over time", x="date", y=None, agg="count"),
        C("box", "Price by unit type", x="unit_type", y="price"),
        C("bar", "Value by project", x="project", y="price"),
        C("bar", "Bookings by broker / source", x="broker", y=None, agg="count"),
    ],
    filters=["project", "unit_type", "status", "date"],
    ai_prompt=("You are a real-estate analyst. Focus on absorption pace, pricing "
               "power by configuration, aging inventory and collection risk."),
    report_tone="monthly inventory review",
)

# ══════════════════════════════════════════════════════════════════════════════
# 11. HOSPITALITY & F&B
# ══════════════════════════════════════════════════════════════════════════════
HOSPITALITY = PresetSpec(
    name="hospitality", label="Hospitality & Restaurants", icon="🍽️",
    keywords=["menu", "dish", "kot", "restaurant", "zomato", "swiggy", "dine",
              "covers", "table", "room", "occupancy", "bill"],
    primary_metric="revenue",
    fields=[
        F("date", "temporal", ["date", "bill date", "order date", "business date",
          "check-in"], required=True),
        F("revenue", "numeric", ["amount", "net sales", "bill amount", "total",
          "order value", "sales"], required=True),
        F("item", "categorical", ["item", "dish", "menu item", "product",
          "room type", "item name"]),
        F("order_id", "identifier", ["bill no", "order id", "kot no", "booking id",
          "invoice no"]),
        F("channel", "categorical", ["channel", "source", "order type", "mode"],
          value_vocab=["dine-in", "dine in", "takeaway", "delivery", "zomato",
                       "swiggy", "ota", "direct", "walk-in"]),
        F("quantity", "numeric", ["qty", "quantity", "covers", "nights", "rooms",
          "pax"]),
        F("discount", "numeric", ["discount", "promo", "commission",
          "aggregator commission"]),
    ],
    kpis=[
        K("total_revenue", "Revenue", "sum", {"field": "revenue"}, "currency",
          "up_good", "Total sales"),
        K("orders", "Orders / Bills", "distinct", {"field": "order_id",
          "fallback_rows": True}, "integer", "up_good", "Bill count"),
        K("avg_bill", "Avg Bill Value", "ratio", {"num": "total_revenue",
          "den": "orders"}, "currency", "up_good", "Revenue per bill"),
        K("discount_total", "Discounts / Commission", "sum", {"field": "discount"},
          "currency", "up_bad", "Total given away"),
        K("revenue_growth", "Revenue Growth", "growth", {"kpi": "total_revenue"},
          "percent", "up_good", "Latest vs previous period"),
        K("top_item_share", "Top-10 Item Share", "top_share", {"by": "item",
          "field": "revenue", "n": 10}, "percent", "neutral",
          "Menu concentration"),
    ],
    tiles=["total_revenue", "orders", "avg_bill", "revenue_growth"],
    charts=[
        C("line", "Daily revenue", x="date", y="revenue"),
        C("bar", "Top items", x="item", y="revenue", top_n=15),
        C("donut", "Channel mix", x="channel", y="revenue"),
        C("heat_dow", "Revenue by weekday", x="date", y="revenue"),
        C("stacked_bar", "Channel revenue over time", x="date", y="revenue",
          color="channel"),
    ],
    filters=["date", "channel", "item"],
    ai_prompt=("You are an F&B and hospitality analyst. Focus on menu engineering, "
               "channel profitability (aggregator commissions), peak-hour staffing "
               "and pricing."),
    report_tone="weekly trading report",
)

# ══════════════════════════════════════════════════════════════════════════════
# 12. SAAS & SUBSCRIPTIONS
# ══════════════════════════════════════════════════════════════════════════════
SAAS = PresetSpec(
    name="saas", label="SaaS & Subscriptions", icon="☁️",
    keywords=["mrr", "subscription", "plan", "churn", "arr", "billing", "trial",
              "renewal", "customer", "tier"],
    primary_metric="mrr_amount",
    fields=[
        F("customer_id", "identifier", ["customer", "customer id", "user id",
          "account", "email"], required=True),
        F("mrr_amount", "numeric", ["mrr", "amount", "plan amount",
          "subscription value", "arr", "price"], required=True),
        F("start_date", "temporal", ["start date", "created", "subscription date",
          "signup date"], required=True),
        F("cancel_date", "temporal", ["cancel date", "churn date", "ended at",
          "cancelled at"]),
        F("plan", "categorical", ["plan", "tier", "product", "package", "sku"]),
        F("status", "categorical", ["status"], value_vocab=["active", "cancelled",
          "canceled", "trialing", "past_due", "churned"]),
        F("billing_period", "categorical", ["interval", "billing cycle",
          "billing period"], value_vocab=["monthly", "annual", "yearly", "month",
                                          "year"]),
    ],
    kpis=[
        K("mrr", "MRR (book)", "sum", {"field": "mrr_amount", "where_field": "status",
          "where_values": ["active", "trialing", "past_due"], "where_fallback": True},
          "currency", "up_good", "Sum of active subscription value"),
        K("customers", "Customers", "distinct", {"field": "customer_id"}, "integer",
          "up_good", "Distinct customers"),
        K("arpa", "ARPA", "ratio", {"num": "mrr", "den": "customers"}, "currency",
          "up_good", "Revenue per account"),
        K("churn_rate", "Churned Share", "rate", {"field": "status",
          "values": ["cancelled", "canceled", "churned"]}, "percent", "up_bad",
          "Share of churned subscriptions"),
        K("lifetime_months", "Avg Lifetime", "date_diff", {"start": "start_date",
          "end": "cancel_date", "open_end": "today", "unit": "months"}, "months",
          "up_good", "Months from signup"),
        K("mrr_growth", "New MRR Growth", "growth", {"kpi": "mrr"}, "percent",
          "up_good", "By signup period"),
    ],
    tiles=["mrr", "customers", "arpa", "churn_rate"],
    charts=[
        C("line", "New MRR by signup period", x="start_date", y="mrr_amount"),
        C("bar", "MRR by plan", x="plan", y="mrr_amount"),
        C("donut", "Status mix", x="status", y=None, agg="count"),
        C("stacked_bar", "Signups by plan over time", x="start_date", y=None,
          agg="count", color="plan"),
        C("hist", "Subscription value distribution", x="mrr_amount"),
    ],
    filters=["plan", "status", "start_date"],
    ai_prompt=("You are a SaaS metrics analyst. Focus on MRR movement, churn "
               "drivers by plan and tenure, expansion opportunities and growth "
               "efficiency."),
    report_tone="monthly investor-style metrics summary",
)

# ══════════════════════════════════════════════════════════════════════════════
# 13. LENDING & NBFC
# ══════════════════════════════════════════════════════════════════════════════
LENDING = PresetSpec(
    name="lending", label="Lending & NBFC", icon="🏦",
    keywords=["loan", "emi", "dpd", "disbursed", "npa", "borrower", "principal",
              "overdue", "bucket", "portfolio", "lan"],
    primary_metric="principal",
    fields=[
        F("loan_id", "identifier", ["loan id", "account no", "agreement no", "lan",
          "loan number"], required=True),
        F("principal", "numeric", ["loan amount", "principal", "disbursed amount",
          "sanctioned", "sanction amount"], required=True),
        F("disbursal_date", "temporal", ["disbursal date", "disbursement date",
          "sanction date", "date"], required=True),
        F("outstanding", "numeric", ["outstanding", "pos", "principal outstanding",
          "balance"]),
        F("dpd", "numeric", ["dpd", "days past due", "overdue days"]),
        F("bucket", "categorical", ["bucket", "delinquency bucket", "npa class"],
          value_vocab=["current", "0", "1-30", "31-60", "61-90", "90+", "npa"]),
        F("status", "categorical", ["status", "loan status"],
          value_vocab=["active", "closed", "written-off", "npa", "settled"]),
        F("branch", "categorical", ["branch", "center", "agent", "officer", "ro",
          "region"]),
        F("emi_due", "numeric", ["demand", "emi due", "due amount"]),
        F("emi_paid", "numeric", ["collected", "received", "paid", "emi paid",
          "collection"]),
        F("product", "categorical", ["product", "loan type", "scheme"]),
    ],
    kpis=[
        K("disbursed", "Disbursed", "sum", {"field": "principal"}, "currency",
          "up_good", "Total disbursement"),
        K("loans", "Loans", "distinct", {"field": "loan_id", "fallback_rows": True},
          "integer", "up_good", "Loan count"),
        K("portfolio", "Outstanding", "sum", {"field": "outstanding"}, "currency",
          "neutral", "Portfolio outstanding"),
        K("avg_ticket", "Avg Ticket", "ratio", {"num": "disbursed", "den": "loans"},
          "currency", "neutral", "Disbursed ÷ loans"),
        K("par30", "PAR-30", "share_where_num", {"value_field": "outstanding",
          "cond_field": "dpd", "op": ">", "threshold": 30}, "percent", "up_bad",
          "% of outstanding with DPD > 30"),
        K("collection_eff", "Collection Efficiency", "ratio_fields",
          {"num_field": "emi_paid", "den_field": "emi_due", "as_percent": True},
          "percent", "up_good", "Collected ÷ due"),
        K("disb_growth", "Disbursement Growth", "growth", {"kpi": "disbursed"},
          "percent", "up_good", "Latest vs previous period"),
    ],
    tiles=["portfolio", "collection_eff", "par30", "disbursed"],
    charts=[
        C("line", "Disbursement over time", x="disbursal_date", y="principal"),
        C("stacked_bar", "Portfolio by bucket", x="branch", y="outstanding",
          color="bucket"),
        C("bar", "Outstanding by branch", x="branch", y="outstanding"),
        C("donut", "Status mix", x="status", y=None, agg="count"),
        C("hist", "DPD distribution", x="dpd"),
    ],
    filters=["branch", "product", "bucket", "disbursal_date"],
    ai_prompt=("You are a credit-risk analyst. Focus on early-warning delinquency "
               "trends, PAR movement, branch outliers and collection efficiency. "
               "Use compliance-neutral wording."),
    report_tone="monthly portfolio review",
)

# ══════════════════════════════════════════════════════════════════════════════
# 14. ENERGY & UTILITIES
# ══════════════════════════════════════════════════════════════════════════════
ENERGY = PresetSpec(
    name="energy", label="Energy & Utilities", icon="⚡",
    keywords=["kwh", "energy", "generation", "consumption", "meter", "solar",
              "load", "grid", "inverter", "mwh", "units"],
    primary_metric="energy_kwh",
    fields=[
        F("timestamp", "temporal", ["timestamp", "date", "time", "reading time",
          "interval", "reading date"], required=True),
        F("energy_kwh", "numeric", ["kwh", "generation", "consumption", "units",
          "energy", "mwh", "kwh generated"], required=True),
        F("site", "categorical", ["site", "plant", "meter", "location", "building",
          "feeder"]),
        F("expected_kwh", "numeric", ["expected", "target", "budget", "pr expected",
          "planned"]),
        F("cost", "numeric", ["cost", "amount", "bill amount", "tariff cost"]),
        F("demand_kw", "numeric", ["kw", "demand", "load", "peak demand"]),
    ],
    kpis=[
        K("total_energy", "Total Energy", "sum", {"field": "energy_kwh"}, "number",
          "up_good", "Total kWh"),
        K("avg_daily", "Avg per Reading", "mean", {"field": "energy_kwh"}, "number",
          "up_good", "Mean kWh per record"),
        K("performance_ratio", "Performance Ratio", "ratio_fields",
          {"num_field": "energy_kwh", "den_field": "expected_kwh",
           "as_percent": True}, "percent", "up_good", "Actual ÷ expected"),
        K("total_cost", "Total Cost", "sum", {"field": "cost"}, "currency", "up_bad",
          "Energy cost"),
        K("cost_per_kwh", "Cost / kWh", "ratio", {"num": "total_cost",
          "den": "total_energy"}, "currency", "up_bad", "Unit cost"),
        K("energy_growth", "Energy Growth", "growth", {"kpi": "total_energy"},
          "percent", "up_good", "Latest vs previous period"),
        K("peak_demand", "Peak Demand", "max", {"field": "demand_kw"}, "number",
          "up_bad", "Maximum load"),
    ],
    tiles=["total_energy", "performance_ratio", "cost_per_kwh", "peak_demand"],
    charts=[
        C("line", "Energy over time", x="timestamp", y="energy_kwh"),
        C("bar", "Energy by site", x="site", y="energy_kwh"),
        C("heat_dow", "Load pattern by weekday", x="timestamp", y="energy_kwh"),
        C("scatter", "Actual vs expected", x="expected_kwh", y="energy_kwh",
          color="site"),
        C("line", "Demand profile", x="timestamp", y="demand_kw"),
    ],
    filters=["site", "timestamp"],
    ai_prompt=("You are an energy analyst. Focus on underperformance detection, "
               "load patterns, peak-demand charges and tariff optimization."),
    report_tone="monthly generation/consumption report",
)

# ══════════════════════════════════════════════════════════════════════════════
# 15. NONPROFIT & NGO
# ══════════════════════════════════════════════════════════════════════════════
NONPROFIT = PresetSpec(
    name="nonprofit", label="Nonprofit & NGO", icon="🤲",
    keywords=["donation", "donor", "grant", "beneficiary", "ngo", "program", "cause",
              "fundraising", "contribution"],
    primary_metric="amount",
    fields=[
        F("date", "temporal", ["date", "donation date", "transaction date", "period"],
          required=True),
        F("amount", "numeric", ["amount", "donation", "contribution", "grant amount",
          "spend"], required=True),
        F("donor_id", "identifier", ["donor", "donor id", "email", "supporter",
          "donor name"]),
        F("program", "categorical", ["program", "project", "cause", "campaign",
          "grant"]),
        F("channel", "categorical", ["channel", "source", "platform", "mode"]),
        F("type", "categorical", ["type", "frequency"],
          value_vocab=["one-time", "recurring", "monthly", "grant", "income",
                       "expense"]),
        F("beneficiaries", "numeric", ["beneficiaries", "reach", "participants",
          "households"]),
        F("budget", "numeric", ["budget", "allocated", "sanctioned"]),
    ],
    kpis=[
        K("total_raised", "Total Raised", "sum", {"field": "amount"}, "currency",
          "up_good", "Total donations"),
        K("donors", "Donors", "distinct", {"field": "donor_id", "fallback_rows": True},
          "integer", "up_good", "Distinct donors"),
        K("avg_donation", "Avg Donation", "ratio", {"num": "total_raised",
          "den": "donors"}, "currency", "up_good", "Amount per donor"),
        K("recurring_share", "Recurring Share", "rate", {"field": "type",
          "values": ["recurring", "monthly"]}, "percent", "up_good",
          "Share of recurring gifts"),
        K("top_donor_share", "Top-10 Donor Share", "top_share", {"by": "donor_id",
          "field": "amount", "n": 10}, "percent", "up_bad",
          "Concentration risk"),
        K("raised_growth", "Fundraising Growth", "growth", {"kpi": "total_raised"},
          "percent", "up_good", "Latest vs previous period"),
        K("total_reach", "Beneficiaries Reached", "sum", {"field": "beneficiaries"},
          "integer", "up_good", "Total reach"),
    ],
    tiles=["total_raised", "donors", "avg_donation", "recurring_share"],
    charts=[
        C("line", "Donations over time", x="date", y="amount"),
        C("bar", "Raised by program", x="program", y="amount"),
        C("donut", "Channel mix", x="channel", y="amount"),
        C("hist", "Donation size distribution", x="amount"),
        C("bar", "Raised by type", x="type", y="amount"),
    ],
    filters=["program", "channel", "date"],
    ai_prompt=("You are a nonprofit analyst. Focus on donor retention, "
               "concentration risk, program efficiency and channel effectiveness. "
               "Keep donor privacy — aggregates only."),
    report_tone="quarterly impact & fundraising report",
)


ALL_PRESETS: List[PresetSpec] = [
    RETAIL, SALES_CRM, FINANCE, HR, MARKETING, LOGISTICS, MANUFACTURING,
    HEALTHCARE, EDUCATION, REAL_ESTATE, HOSPITALITY, SAAS, LENDING, ENERGY,
    NONPROFIT,
]

PRESET_BY_NAME = {p.name: p for p in ALL_PRESETS}


# What a domain expert checks FIRST in each industry — surfaced as the report's
# "Industry Lens" so the analysis reads as tailored, not generic.
INDUSTRY_LENS: dict = {
    "retail": [
        "Same-store vs new-store growth, and weekday/weekend split",
        "Dependence on top SKUs and the effect of discounting on volume",
        "Repeat-customer rate as the leading signal beneath revenue",
    ],
    "sales_crm": [
        "Pipeline coverage vs target and conversion between stages",
        "Deal velocity and slipping/aged opportunities",
        "Revenue concentration in a few reps or accounts (bus-factor risk)",
    ],
    "finance": [
        "Cash burn vs runway and month-on-month expense creep",
        "Budget variance drivers and recurring vs one-off spend",
        "Unusual or largest transactions that distort the totals",
    ],
    "hr": [
        "Attrition hot-spots by department and tenure band",
        "Pay equity and compa-ratio outliers",
        "Hiring-vs-exit balance and its effect on headcount trajectory",
    ],
    "marketing": [
        "CPA/ROAS efficiency by campaign and channel, with spend context",
        "Creative fatigue (CTR decay) and frequency saturation",
        "Blended-metric mix shifts that hide true channel performance",
    ],
    "logistics": [
        "On-time / SLA breach rate and first-attempt success",
        "Carrier cost-vs-speed trade-off and lane-level performance",
        "RTO/return concentration by destination",
    ],
    "manufacturing": [
        "Plan attainment and the OEE loss tree (availability/quality/output)",
        "Defect Pareto by product and line, with SPC-style control",
        "Downtime cause concentration by machine and shift",
    ],
    "healthcare": [
        "Capacity vs demand by day/hour and no-show clustering",
        "Revenue mix by department and doctor productivity",
        "New-vs-follow-up balance and payer/service mix drift",
    ],
    "education": [
        "Attendance-to-performance link and at-risk cohort size",
        "Batch/teacher variance in outcomes",
        "Fee-collection rate and outstanding-dues aging",
    ],
    "real_estate": [
        "Absorption/occupancy pace vs launch or plan",
        "Price realization per sqft by configuration",
        "Aging unsold inventory and collection/arrears risk",
    ],
    "hospitality": [
        "Menu engineering: item volume vs margin quadrants",
        "Channel profitability and aggregator commission drag",
        "Peak-hour demand for staffing and covers/table efficiency",
    ],
    "saas": [
        "MRR movement (new/expansion/contraction/churn) and NRR",
        "Churn by plan and tenure band; cohort retention decay",
        "Revenue concentration and expansion opportunity",
    ],
    "lending": [
        "PAR buckets and roll/migration rates (early-warning delinquency)",
        "Collection efficiency vs disbursal growth tension",
        "Branch/officer outliers in portfolio quality",
    ],
    "energy": [
        "Performance ratio vs expected and underperformance detection",
        "Load/generation profile by hour and peak-demand charges",
        "Site-level league table and downtime-loss quantification",
    ],
    "nonprofit": [
        "Donor retention by acquisition channel and cohort",
        "Donation concentration risk in a few large donors",
        "Program cost-efficiency and grant burn vs timeline",
    ],
}
