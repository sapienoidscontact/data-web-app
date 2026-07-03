# Industry Preset Requirements

Preset specifications for every target industry: who the users are, what they need
answered, what their exported data actually looks like (source systems, file format,
layout style), the canonical field schema with real-world synonyms, the KPI pack, the
default dashboard, and the report/AI configuration.

Each preset follows the declarative format defined in
`docs/WORKFLOW_REPLACEMENT_ROADMAP.md` and is designed to plug into the existing
architecture: `detect` extends `core/schema/mapper.py` + `BaseTemplate.trigger_keywords`,
`fields` powers the new field-level mapper, `kpis` extends `core/kpi/library.py`,
`dashboard` drives `core/visualization`, `ai_prompt` extends `ai_prompt_prefix()`.

**Reading the field tables:** *Canonical field* is the internal name all KPIs and charts
bind to. *Synonyms* are matched (case/punctuation-insensitive, token-based) against real
column headers. *Req* = required for the preset's core dashboard; optional fields unlock
extra KPIs when present.

**Cross-industry file-style rules the ingest layer must handle everywhere:**
- Excel exports with 1–5 title rows above the header (logo, company name, date range).
- Total/subtotal rows at the bottom (and grouped subtotals mid-table in ERP exports).
- Currency strings (`₹1,23,456.00`, `$1,234.50`, `(500)` = negative), percent strings.
- Dates as `DD-MM-YYYY`, `DD/MM/YY`, `MMM-YY`, Excel serials, and month-name columns.
- Pivoted layouts (months/branches as columns) → auto-unpivot to long format.
- Mixed-case, whitespace-padded, and duplicated headers (`Amount`, `Amount.1`).

---

## 1. Retail & E-commerce

**Users & needs:** store owners, e-com managers, D2C brands. Questions: What's selling?
Which products/stores drive revenue? Is revenue growing MoM? What should I restock?
When are my peak hours/days? Which discounts work?

**Source systems & data style:** Shopify/WooCommerce order exports (clean long CSV, one
row per order-line, ISO dates), Amazon Seller Central (wide CSV, many fee columns), POS
systems like Square/Petpooja (daily summary Excel with title rows), Tally/Vyapar item-wise
sales registers (Excel, merged headers, subtotal rows, DD-MM-YYYY). Grain: order-line or
daily-summary.

| Canonical field | Req | Role | Synonyms |
|---|---|---|---|
| order_date | ✔ | temporal | date, order date, bill date, invoice date, txn date, created at |
| revenue | ✔ | numeric | amount, total, net amount, sales, gross sales, line total, amt, value |
| quantity | ✔ | numeric | qty, quantity, units, pcs, nos, items |
| product | ✔ | categorical | product, item, item name, sku, description, product title |
| order_id | – | identifier | order id, order no, bill no, invoice no, receipt |
| category | – | categorical | category, product type, department, group |
| store | – | categorical | store, location, branch, outlet, channel, marketplace |
| customer_id | – | identifier | customer, customer id, buyer, email |
| discount | – | numeric | discount, promo, coupon amount, markdown |
| cost | – | numeric | cost, cogs, purchase price, landed cost |

**KPI pack:** total_revenue, order_count (distinct order_id), aov (revenue/orders),
units_sold, revenue_mom_growth, revenue_yoy_growth, top_product_share (top-10 % of
revenue), avg_basket_size (units/order), discount_rate (discount/gross), gross_margin
((revenue−cost)/revenue, needs cost), repeat_customer_rate (needs customer_id),
revenue_per_store (needs store).

**Dashboard:** tiles [total_revenue, revenue_mom_growth, order_count, aov] → line
revenue-by-order_date (daily/weekly auto-grain) → bar top-10 products → bar revenue by
category → bar/heatmap revenue by day-of-week → table top movers vs prior period.
**Filters:** date range, store, category. **Forecast target:** daily revenue.

**AI prompt focus:** "senior retail analyst — sell-through, basket economics, product mix,
promotion effectiveness, restock recommendations." **Report:** monthly sales review —
summary, KPI table, trend, top/bottom products, store comparison, forecast.

---

## 2. B2B Sales & CRM

**Users & needs:** sales managers, founders. Pipeline health, win rate, rep performance,
deal velocity, quota attainment, forecast accuracy.

**Source systems & data style:** Salesforce/HubSpot/Zoho/Pipedrive deal exports — clean
long CSV, one row per deal/opportunity, stage as text category, two dates (created,
closed), owner names. Occasionally activity exports (calls/emails per row).

| Canonical field | Req | Role | Synonyms |
|---|---|---|---|
| deal_value | ✔ | numeric | amount, deal value, opportunity value, acv, contract value, expected revenue |
| stage | ✔ | categorical | stage, deal stage, status, pipeline stage, phase |
| created_date | ✔ | temporal | created, created date, open date, start date |
| close_date | – | temporal | close date, closed, won date, expected close |
| owner | – | categorical | owner, rep, salesperson, account executive, assigned to |
| account | – | categorical | account, company, customer, client, organization |
| source | – | categorical | source, lead source, channel, campaign |
| is_won | – | binary | won, is won, result, outcome (or derived from stage ∈ {won, closed won}) |

**KPI pack:** pipeline_value (open deals), won_revenue, win_rate (won/closed),
avg_deal_size, sales_cycle_days (close−created, won only), deals_by_stage,
pipeline_coverage (pipeline/target), rep_leaderboard, stage_conversion (funnel %),
new_pipeline_mom, slippage (past-due close dates).

**Dashboard:** tiles [pipeline_value, won_revenue, win_rate, avg_deal_size] → funnel by
stage → bar won revenue by owner → line new pipeline by created month → scatter deal
size vs cycle days → table stale deals (>60 days in stage). **Filters:** date, owner,
stage, source. **Forecast target:** monthly won revenue.

**AI focus:** "sales operations analyst — pipeline risk, funnel leaks, rep coaching,
forecast confidence." **Report:** weekly pipeline review.

---

## 3. Finance & Accounting

**Users & needs:** accountants, CFOs, SMB owners. Cash position, income vs expense,
budget variance, expense drivers, receivables aging, P&L trends.

**Source systems & data style:** Tally/QuickBooks/Xero/Zoho Books ledger & P&L exports —
**the messiest category**: Excel with company-name title rows, account hierarchies as
indented rows, debit/credit as separate columns, bracketed negatives, totals rows,
DD-MM-YYYY, lakh/crore grouping. Bank statements (CSV/Excel, one row per transaction,
separate withdrawal/deposit columns). Pivoted monthly P&L (months as columns) → unpivot.

| Canonical field | Req | Role | Synonyms |
|---|---|---|---|
| txn_date | ✔ | temporal | date, txn date, transaction date, value date, posting date, voucher date |
| amount | ✔ | numeric | amount, value, net; **or derived** = credit − debit / deposit − withdrawal |
| account | ✔ | categorical | account, ledger, account name, category, head, particulars |
| type | – | categorical | type, txn type, dr/cr, voucher type, income/expense |
| party | – | categorical | party, vendor, payee, customer, narration-extracted |
| debit | – | numeric | debit, dr, withdrawal, paid out, expense |
| credit | – | numeric | credit, cr, deposit, paid in, income |
| budget | – | numeric | budget, budgeted, plan, target |

**KPI pack:** net_cashflow, total_inflows, total_outflows, in_out_ratio (exists),
burn_rate (avg monthly net outflow), runway_months (balance/burn), expense_by_category
top-N, mom_expense_growth, budget_variance ((actual−budget)/budget), largest_transactions,
recurring_payment_detection.

**Dashboard:** tiles [net_cashflow, inflows, outflows, burn_rate] → line monthly net
cashflow → stacked bar inflow vs outflow by month → bar top expense categories → table
budget variance (if budget) → table largest/unusual transactions. **Filters:** date,
account/category, type. **Forecast target:** monthly net cashflow.

**AI focus:** "financial analyst — liquidity, cost control, variance explanation, unusual
transaction flags. Conservative tone, no investment advice." **Report:** monthly
finance pack — cash summary, P&L trend, variance, anomalies.

---

## 4. HR & People Analytics

**Users & needs:** HR managers. Headcount & growth, attrition, compensation equity,
diversity, tenure, leave patterns, performance distribution.

**Source systems & data style:** HRMS exports (Keka, Zoho People, Workday, BambooHR,
greytHR) — one row per employee, wide (30–60 columns), mixed PII; or payroll registers
(monthly, pivoted). Dates of joining/exit; salary sometimes as annual CTC string.

| Canonical field | Req | Role | Synonyms |
|---|---|---|---|
| employee_id | ✔ | identifier | employee id, emp id, staff id, employee code |
| department | ✔ | categorical | department, dept, function, team, business unit |
| salary | – | numeric | salary, ctc, gross pay, compensation, annual salary, wage |
| join_date | – | temporal | join date, date of joining, doj, hire date, start date |
| exit_date | – | temporal | exit date, termination date, last working day, resignation date |
| role | – | categorical | designation, role, title, position, grade, band, level |
| gender | – | categorical | gender, sex |
| location | – | categorical | location, office, city, site |
| performance | – | numeric/categorical | rating, performance, appraisal score |
| age / dob | – | numeric/temporal | age, dob, date of birth |

**KPI pack:** headcount, attrition_rate (exits/avg headcount, annualized), avg_tenure_years,
new_hires_period, salary_median & percentiles by dept, salary_gini (exists),
gender_ratio & pay_gap (median by gender within role), span_of_control (if manager field),
performance_distribution, absence_rate (if leave data).

**Dashboard:** tiles [headcount, attrition_rate, avg_tenure, new_hires] → line headcount
over time (from join/exit dates) → bar headcount by department → box salary by
department → bar attrition by department → pie gender mix → table recent exits.
**Filters:** department, location, role. **Forecast target:** headcount.
**Privacy rule:** never send employee names/IDs to the AI; aggregate only (schema summary
already does this — enforce in preset).

**AI focus:** "people-analytics partner — retention risk, comp equity, org shape. Neutral,
compliant language." **Report:** quarterly people review.

---

## 5. Marketing & Digital Advertising

**Users & needs:** growth/performance marketers, agencies. Which channel/campaign is
efficient? CAC, ROAS, funnel conversion, budget reallocation.

**Source systems & data style:** Google Ads / Meta Ads exports — long CSV, one row per
campaign×day, metric columns (impressions, clicks, spend, conversions), currency + percent
strings, sometimes a totals row. GA4 exports (sessions, users by channel/date). Email tools
(Mailchimp: sends, opens, clicks). Grain: entity×day.

| Canonical field | Req | Role | Synonyms |
|---|---|---|---|
| date | ✔ | temporal | date, day, reporting date, week |
| spend | ✔ | numeric | spend, cost, amount spent, ad spend, budget spent |
| impressions | – | numeric | impressions, impr, views, reach |
| clicks | – | numeric | clicks, link clicks, sessions, visits |
| conversions | – | numeric | conversions, results, purchases, leads, signups, installs |
| conversion_value | – | numeric | conversion value, revenue, purchase value, sales |
| campaign | ✔ | categorical | campaign, campaign name, ad set, ad group |
| channel | – | categorical | channel, platform, source, medium, network |

**KPI pack:** total_spend, total_conversions, cpc (spend/clicks), cpm, ctr
(clicks/impressions), cpa (spend/conversions), roas (conversion_value/spend),
conversion_rate, spend_mom, best/worst_campaign_by_cpa, channel_mix.

**Dashboard:** tiles [spend, conversions, cpa, roas] → line spend & conversions by date
(dual axis) → bar CPA by campaign (sorted) → scatter spend vs ROAS by campaign → stacked
area spend by channel → table campaign league (all KPIs). **Filters:** date, channel,
campaign. **Forecast target:** daily conversions.

**AI focus:** "performance-marketing analyst — budget reallocation, fatigue detection,
funnel bottlenecks. Recommend concrete shifts." **Report:** weekly performance report.

---

## 6. Logistics & Supply Chain

**Users & needs:** ops managers, 3PLs, fleet owners. On-time %, delivery cost, route/carrier
performance, returns, inventory position.

**Source systems & data style:** courier/carrier reports (Shiprocket, Delhivery, FedEx) —
one row per shipment, status text categories, promised vs actual dates, weight, COD flags.
WMS/inventory exports — one row per SKU, stock levels, pivoted by warehouse. TMS trip
sheets (Excel, per-trip rows).

| Canonical field | Req | Role | Synonyms |
|---|---|---|---|
| ship_date | ✔ | temporal | ship date, dispatch date, pickup date, order date |
| delivery_date | – | temporal | delivery date, delivered on, pod date |
| promised_date | – | temporal | promised date, edd, expected delivery, eta |
| status | ✔ | categorical | status, delivery status, shipment status |
| carrier | – | categorical | carrier, courier, transporter, partner, 3pl |
| cost | – | numeric | freight, shipping cost, charge, freight amount |
| weight | – | numeric | weight, chargeable weight, kg |
| origin / destination | – | categorical | origin, from, pickup city / destination, to, zone, pincode |
| shipment_id | – | identifier | awb, tracking no, lr no, shipment id, consignment |

**KPI pack:** shipment_count, on_time_rate (delivery≤promised), avg_transit_days,
delivery_success_rate (status=delivered), rto_return_rate, cost_per_shipment,
cost_per_kg, carrier_scorecard (on-time & cost by carrier), lane_performance
(origin→destination), exception_count.

**Dashboard:** tiles [shipments, on_time_rate, avg_transit_days, cost_per_shipment] →
line shipments & on-time % by week → bar carrier scorecard → bar transit days by lane →
pie status mix → table worst lanes/exceptions. **Filters:** date, carrier, origin,
destination, status. **Forecast target:** weekly shipment volume.

**AI focus:** "supply-chain analyst — SLA breaches, carrier mix, cost per lane, RTO
reduction." **Report:** monthly ops review.

---

## 7. Manufacturing & Production

**Users & needs:** plant managers, MSMEs. Output vs plan, quality/defect rates, downtime,
machine utilization (OEE), scrap cost.

**Source systems & data style:** production log sheets (Excel, one row per shift×machine
or batch, often manually keyed with typos), quality registers (defect counts by type), ERP
work-order exports (SAP B1, Odoo — long, coded categories). Pivoted daily-production
sheets (days as columns) are common → unpivot.

| Canonical field | Req | Role | Synonyms |
|---|---|---|---|
| date | ✔ | temporal | date, production date, shift date |
| output_qty | ✔ | numeric | output, produced, quantity, good qty, units produced, actual |
| planned_qty | – | numeric | plan, target, planned, scheduled qty |
| defect_qty | – | numeric | defects, rejects, rework, scrap, ng qty |
| machine | – | categorical | machine, line, equipment, work center, station |
| shift | – | categorical | shift, shift name (A/B/C, day/night) |
| product | – | categorical | product, item, part no, sku, batch |
| downtime_min | – | numeric | downtime, stoppage, breakdown minutes, idle time |
| runtime_min | – | numeric | runtime, operating time, machine hours |

**KPI pack:** total_output, plan_attainment (output/planned), defect_rate
(defects/(output+defects)), first_pass_yield, downtime_hours, availability
(runtime/(runtime+downtime)), oee_proxy (availability × quality × attainment),
output_per_shift, worst_machine_by_downtime, scrap_cost (if cost).

**Dashboard:** tiles [output, plan_attainment, defect_rate, downtime_hours] → line
output vs plan by day → bar output by machine/line → bar defect Pareto by type/product →
heatmap downtime by machine×shift → table worst-performing runs. **Filters:** date,
machine, shift, product. **Forecast target:** daily output.

**AI focus:** "production analyst — bottlenecks, quality Pareto, downtime causes, OEE
improvement." **Report:** weekly production review.

---

## 8. Healthcare (Clinics, Hospitals, Diagnostics)

**Users & needs:** clinic owners, hospital admins, lab managers. Patient volume, revenue by
department/doctor, appointment no-shows, bed/slot utilization, avg length of stay.

**Source systems & data style:** HMS/EMR exports (Practo, HealthPlix, hospital HIS) — one
row per visit/appointment/bill; billing registers (Excel with title rows and totals);
lab LIS exports (one row per test). **PII-heavy — same privacy rule as HR: aggregates
only to AI, never names/MRNs.**

| Canonical field | Req | Role | Synonyms |
|---|---|---|---|
| visit_date | ✔ | temporal | date, visit date, appointment date, admission date, bill date |
| patient_id | – | identifier | patient id, mrn, uhid, reg no |
| department | ✔ | categorical | department, specialty, unit, ward, service |
| doctor | – | categorical | doctor, physician, consultant, provider |
| revenue | – | numeric | amount, bill amount, charges, fee, net amount |
| visit_type | – | categorical | visit type, opd/ipd, new/follow-up, appointment type |
| status | – | categorical | status, appointment status (completed/no-show/cancelled) |
| discharge_date | – | temporal | discharge date, end date |
| test / procedure | – | categorical | test, procedure, service name, investigation |

**KPI pack:** patient_visits, unique_patients, revenue_total, revenue_per_visit,
no_show_rate, new_vs_followup_ratio, avg_length_of_stay (discharge−admission),
visits_by_department, doctor_productivity (visits & revenue per doctor),
peak_hour_analysis, payer_mix (if payment mode).

**Dashboard:** tiles [visits, revenue, no_show_rate, revenue_per_visit] → line visits by
week → bar revenue by department → bar visits by doctor → heatmap visits by day×hour →
pie visit type mix. **Filters:** date, department, doctor, visit type.
**Forecast target:** weekly visits.

**AI focus:** "healthcare operations analyst — capacity, no-show reduction, service-mix
revenue. Clinical-outcome claims out of scope." **Report:** monthly ops & revenue review.

---

## 9. Education (Schools, Colleges, EdTech, Coaching)

**Users & needs:** principals, coaching institutes, edtech ops. Enrollment trends,
attendance, fee collection & dues, exam performance, batch/teacher comparison.

**Source systems & data style:** school ERP exports (Fedena, Teachmint) — student master
(one row per student, wide), attendance registers (**pivoted: students × dates**, needs
unpivot), marks sheets (students × subjects, needs unpivot), fee ledgers (paid/due
columns, totals rows). LMS exports (per-lesson completion rows).

| Canonical field | Req | Role | Synonyms |
|---|---|---|---|
| student_id | ✔ | identifier | student id, roll no, admission no, enrollment no |
| class_group | ✔ | categorical | class, grade, batch, course, section, standard |
| date | – | temporal | date, attendance date, exam date, payment date |
| score | – | numeric | marks, score, percentage, grade points, result |
| subject | – | categorical | subject, paper, module, course name |
| attendance | – | binary/numeric | present, attendance, status (P/A), days present |
| fee_paid | – | numeric | fee paid, amount paid, received |
| fee_due | – | numeric | due, balance, outstanding, pending |
| teacher | – | categorical | teacher, faculty, instructor |

**KPI pack:** enrolled_students, attendance_rate, avg_score, pass_rate (score≥threshold),
score_distribution_by_subject, top/bottom_batches, fee_collection_rate
(paid/(paid+due)), total_outstanding, enrollment_mom, at_risk_students (low attendance ∧
low score — counts only, list stays local).

**Dashboard:** tiles [students, attendance_rate, avg_score, fee_collection_rate] → line
attendance by week → box scores by subject → bar avg score by class/batch → bar
outstanding fees by class → histogram score distribution. **Filters:** class/batch,
subject, date. **Forecast target:** enrollment or monthly fee collection.

**AI focus:** "education analyst — learning outcomes, attendance-performance link,
collection risk. Aggregate only; never name students." **Report:** term report.

---

## 10. Real Estate & Property Management

**Users & needs:** brokers, developers, property managers. Inventory movement, price per
sqft, occupancy, rent collection, lead-to-sale funnel.

**Source systems & data style:** CRM lead exports (long, one row per lead/booking), unit
inventory sheets (Excel, one row per unit: tower/floor/size/price/status — often with
merged tower headers), rent rolls (one row per unit×month, or pivoted months-as-columns).

| Canonical field | Req | Role | Synonyms |
|---|---|---|---|
| unit_id | ✔ | identifier | unit, flat no, unit no, property id, plot no |
| price | ✔ | numeric | price, sale price, rent, agreement value, asking price |
| area_sqft | – | numeric | area, sqft, carpet area, built-up, super area, size |
| status | ✔ | categorical | status, availability (sold/booked/available/rented/vacant) |
| project | – | categorical | project, tower, building, property, society, community |
| unit_type | – | categorical | type, bhk, configuration, layout, category |
| date | – | temporal | booking date, sale date, agreement date, lease start |
| broker / source | – | categorical | broker, agent, channel partner, lead source |
| rent_collected / rent_due | – | numeric | rent received, collected / outstanding, arrears |

**KPI pack:** units_total, units_sold/rented, occupancy_or_absorption_rate,
avg_price_per_sqft, sales_value_total, inventory_aging_days, collection_rate,
arrears_total, sales_velocity (units/month), price_by_type_and_project,
broker_leaderboard.

**Dashboard:** tiles [absorption/occupancy, avg_price_sqft, sales_value, arrears] → bar
inventory status by project → line bookings by month → box price/sqft by unit type →
bar arrears by project → table aging inventory. **Filters:** project, unit type, status,
date. **Forecast target:** monthly bookings or rent collection.

**AI focus:** "real-estate analyst — absorption pace, pricing power, collection risk."
**Report:** monthly inventory & collections review.

---

## 11. Hospitality & Restaurants (F&B, Hotels)

**Users & needs:** restaurant owners, cloud kitchens, hotel managers. Daily sales, item
mix, peak hours, table turnover / occupancy, aggregator vs dine-in mix, food cost.

**Source systems & data style:** restaurant POS (Petpooja, Posist, Toast) — item-wise or
bill-wise daily Excel with title + total rows; Zomato/Swiggy partner exports (one row per
order, commissions & discounts columns); hotel PMS (one row per booking: check-in/out,
room type, ADR).

| Canonical field | Req | Role | Synonyms |
|---|---|---|---|
| date | ✔ | temporal | date, bill date, order date, business date, check-in |
| revenue | ✔ | numeric | amount, net sales, bill amount, total, order value |
| item | – | categorical | item, dish, menu item, product, room type |
| order_id | – | identifier | bill no, order id, kot no, booking id |
| channel | – | categorical | channel, source (dine-in/takeaway/zomato/swiggy/ota/direct) |
| quantity | – | numeric | qty, quantity, covers, nights, rooms |
| discount / commission | – | numeric | discount, promo, aggregator commission, ota commission |
| time | – | temporal | time, bill time, hour, slot |

**KPI pack:** total_revenue, order_count, avg_bill_value, revenue_by_channel,
commission_burden (commission/gross), item_pareto (top items % of sales),
peak_hour_index, day_of_week_pattern, discount_rate; hotels: occupancy_rate, adr
(revenue/rooms sold), revpar.

**Dashboard:** tiles [revenue, orders, avg_bill, commission_burden|occupancy] → line
daily revenue → bar top-15 items → pie channel mix → heatmap revenue by day×hour →
table item movers. **Filters:** date, channel, item category.
**Forecast target:** daily revenue.

**AI focus:** "F&B/hospitality analyst — menu engineering, channel profitability, peak
staffing, pricing." **Report:** weekly trading report.

---

## 12. SaaS & Subscription Businesses

**Users & needs:** founders, product/growth teams. MRR movement, churn, retention cohorts,
activation, plan mix, LTV/CAC.

**Source systems & data style:** Stripe/Chargebee/Razorpay subscription exports — one row
per subscription or invoice, ISO dates, plan names, statuses; product analytics exports
(Mixpanel/Amplitude: one row per user×event or daily aggregates).

| Canonical field | Req | Role | Synonyms |
|---|---|---|---|
| customer_id | ✔ | identifier | customer, customer id, user id, account, email |
| mrr_amount | ✔ | numeric | mrr, amount, plan amount, subscription value, arr |
| start_date | ✔ | temporal | start date, created, subscription date, signup date |
| cancel_date | – | temporal | cancel date, churn date, ended at, cancelled at |
| plan | – | categorical | plan, tier, product, package, sku |
| status | – | categorical | status (active/cancelled/trialing/past_due) |
| billing_period | – | categorical | interval, billing cycle (monthly/annual) |

**KPI pack:** mrr, arr, active_customers, arpa (mrr/customers), new_mrr, churned_mrr,
net_mrr_growth, logo_churn_rate, revenue_churn_rate, avg_customer_lifetime_months,
ltv_estimate (arpa/churn), plan_mix, trial_conversion (if status history).

**Dashboard:** tiles [mrr, net_mrr_growth, churn_rate, arpa] → line MRR by month →
stacked bar MRR movement (new/expansion/churned) → bar customers by plan → cohort
retention heatmap (start_date cohorts × months active) → table biggest churned accounts.
**Filters:** plan, billing period, date. **Forecast target:** MRR.

**AI focus:** "SaaS metrics analyst — NRR, churn drivers, plan-mix shifts, growth
efficiency." **Report:** monthly investor-style metrics summary.

---

## 13. Banking, Fintech & Lending (NBFC, Microfinance)

**Users & needs:** lending ops, NBFCs, fintechs. Disbursement volume, portfolio at risk,
collection efficiency, delinquency buckets, branch/agent performance.

**Source systems & data style:** LMS exports — loan book (one row per loan: amount, rate,
tenure, status, DPD), collection reports (one row per EMI/payment), branch-pivoted summary
sheets. Heavily coded categories (bucket codes), totals rows.

| Canonical field | Req | Role | Synonyms |
|---|---|---|---|
| loan_id | ✔ | identifier | loan id, account no, agreement no, lan |
| principal | ✔ | numeric | loan amount, principal, disbursed amount, sanctioned |
| disbursal_date | ✔ | temporal | disbursal date, disbursement date, sanction date |
| outstanding | – | numeric | outstanding, pos, principal outstanding, balance |
| dpd | – | numeric | dpd, days past due, overdue days |
| bucket | – | categorical | bucket, delinquency bucket, npa class (0/1-30/31-60…) |
| status | – | categorical | status (active/closed/written-off/npa) |
| branch / agent | – | categorical | branch, center, agent, officer, ro |
| emi_due / emi_paid | – | numeric | demand, emi due / collected, received, paid |
| product | – | categorical | product, loan type, scheme |

**KPI pack:** disbursed_total, active_loans, portfolio_outstanding, avg_ticket_size,
collection_efficiency (paid/due), par_30/60/90 (% outstanding with dpd>N),
npa_rate, bucket_migration, branch_scorecard, disbursement_mom, write_off_total.

**Dashboard:** tiles [outstanding, collection_efficiency, par_30, disbursed_mtd] → line
disbursement by month → stacked bar portfolio by bucket over time → bar PAR by branch →
bar collection efficiency by branch → table worst accounts/branches. **Filters:** branch,
product, bucket, date. **Forecast target:** monthly collections.

**AI focus:** "credit-risk analyst — early-warning delinquency trends, branch outliers,
vintage quality. Compliance-neutral wording." **Report:** monthly portfolio review.

---

## 14. Energy & Utilities (Solar, Power, Facilities)

**Users & needs:** solar operators, facility managers, utilities. Generation/consumption
vs target, efficiency (PR), downtime, cost per unit, peak load.

**Source systems & data style:** inverter/SCADA exports — timestamped interval data
(15-min/hourly), one row per timestamp×site, very tall files; utility bills (monthly, one
row per meter/site); BMS exports. Numeric-heavy, few categoricals.

| Canonical field | Req | Role | Synonyms |
|---|---|---|---|
| timestamp | ✔ | temporal | timestamp, date, time, reading time, interval |
| energy_kwh | ✔ | numeric | kwh, generation, consumption, units, energy, mwh |
| site | – | categorical | site, plant, meter, location, building, feeder |
| expected_kwh | – | numeric | expected, target, budget, pr expected, irradiance-based |
| cost | – | numeric | cost, amount, bill amount, tariff cost |
| demand_kw | – | numeric | kw, demand, load, peak demand |

**KPI pack:** total_energy, avg_daily_energy, performance_ratio (actual/expected),
capacity_utilization, peak_demand, cost_per_kwh, energy_mom/yoy, downtime_intervals
(zero-generation daylight periods), site_league_table, load_profile_by_hour.

**Dashboard:** tiles [total_energy, performance_ratio, peak_demand, cost_per_kwh] →
line daily energy vs expected → heatmap hour×day load profile → bar energy by site →
line cumulative month-to-date vs target → table underperforming sites/intervals.
**Filters:** site, date range, granularity (15min/hour/day). **Forecast target:** daily
energy (seasonality-aware).

**AI focus:** "energy analyst — underperformance detection, load shifting, tariff
optimization." **Report:** monthly generation/consumption report.

---

## 15. Nonprofit & NGO

**Users & needs:** program managers, fundraisers. Donation trends, donor retention,
program spend vs budget, beneficiary reach, grant utilization.

**Source systems & data style:** donation exports (Razorpay/GiveIndia/DonorBox — one row
per donation), donor CRMs, program M&E trackers (Excel, often pivoted by month/district),
grant utilization sheets with budget vs actual columns.

| Canonical field | Req | Role | Synonyms |
|---|---|---|---|
| date | ✔ | temporal | date, donation date, transaction date, period |
| amount | ✔ | numeric | amount, donation, contribution, grant amount, spend |
| donor_id | – | identifier | donor, donor id, email, supporter |
| program | – | categorical | program, project, cause, campaign, grant |
| channel | – | categorical | channel, source, platform, mode |
| type | – | categorical | type (one-time/recurring), income/expense |
| beneficiaries | – | numeric | beneficiaries, reach, participants, households |
| budget | – | numeric | budget, allocated, sanctioned |

**KPI pack:** total_raised, donor_count, avg_donation, recurring_share,
donor_retention_rate (repeat donors YoY), top_donor_concentration, program_spend,
budget_utilization, cost_per_beneficiary, raised_mom, channel_effectiveness.

**Dashboard:** tiles [total_raised, donors, avg_donation, budget_utilization] → line
donations by month → bar raised by program → pie channel mix → bar budget vs actual by
program → table top donors (local only). **Filters:** program, channel, date.
**Forecast target:** monthly donations.

**AI focus:** "nonprofit analyst — donor retention, concentration risk, program
efficiency. Donor-privacy safe." **Report:** quarterly impact & fundraising report.

---

## Preset detection & precedence

Detection runs in this order (all signals combined into a confidence score shown to the
user):

1. **Field-match score** — % of the preset's *required* canonical fields that map with
   high confidence (synonym + role + value-shape). Weighted 3×.
2. **Keyword score** — existing `match_score` / `_DOMAIN_TOKENS` token counts. Weighted 1×.
3. **Value-shape signals** — e.g., a `status` column containing {delivered, in transit}
   points to logistics; {closed won, negotiation} points to CRM; {P, A} to education
   attendance. Each preset may declare distinctive value vocabularies. Weighted 2×.
4. **Structural signals** — interval timestamps → energy; students×dates matrix →
   education; debit+credit column pair → finance.

Ties or confidence < 50% → fall back to `general` (today's behavior) and show the preset
picker so the user chooses in one click. **The user can always override**, and the choice
is remembered in the mapping registry.

## Shared KPI building blocks to add to `core/kpi/library.py`

To avoid 15 copies of the same logic, implement these parameterized primitives once and
let preset specs compose them:

| Primitive | Signature (canonical fields) | Used by |
|---|---|---|
| `sum_of(field)` | revenue, spend, amount… | all |
| `distinct_count(field)` | orders, customers, patients, donors | all |
| `ratio(num, den)` | AOV, CPA, ROAS, collection efficiency, PR | all |
| `rate(filter_expr, base)` | win rate, no-show rate, on-time rate, PAR-30 | 10+ presets |
| `period_growth(field, date, period)` | MoM/YoY anything | all |
| `top_n_share(field, by, n)` | product Pareto, donor concentration | 8 presets |
| `date_diff_avg(start, end)` | sales cycle, transit days, LOS, tenure | 7 presets |
| `group_leaderboard(field, by)` | rep/branch/carrier/doctor scorecards | 10 presets |
| `bucketed_share(field, buckets)` | delinquency buckets, score bands | 4 presets |
| `cohort_retention(id, start_date)` | SaaS, nonprofit, retail repeat rate | 3 presets |

With these ten primitives plus the existing 24 formulas, every KPI pack above is
expressible declaratively in the preset YAML — no per-industry Python required.
