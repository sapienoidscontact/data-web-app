import io
import os
import sys

# Load .env before anything else so GEMINI_KEY_* are in the environment
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# Streamlit Community Cloud: keys live in st.secrets, not .env — bridge them
# into the environment so the Gemini client finds them either way.
try:
    import streamlit as _st_early
    for _k in ("GEMINI_KEY_PRIMARY", "GEMINI_KEY_BACKUP"):
        if not os.getenv(_k) and _k in _st_early.secrets:
            os.environ[_k] = str(_st_early.secrets[_k])
except Exception:
    pass

# Make sure core/ is importable regardless of working directory
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from scipy import stats
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score
from core.ai import get_sentinel
from core.schema import detect_schema, map_domain, register as schema_register
from core.kpi import compute_kpis, kpis_to_context_string
from core.visualization import recommend_charts, render_recommendation
from core.templates import auto_detect_template, get_template
from core.forecast import run_forecast
from core.reports import generate_pdf_report, generate_excel_report
from core.ingest import load_uploaded
from core.presets import build_bundle
from core.dashboard.page import render_dashboard

# ── PAGE CONFIG ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title='Sapienoids Analytics Portal',
    page_icon='📊',
    layout='wide',
    initial_sidebar_state='expanded',
)

# ── CUSTOM CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    [data-testid="stSidebar"] { background: linear-gradient(180deg, #0f0f1a 0%, #1a1a2e 100%); }
    [data-testid="stSidebar"] * { color: #e0e0f0 !important; }
    .metric-card { background: #1e1e2e; border-radius: 10px; padding: 1rem; border: 1px solid #333; }
    .stAlert { border-radius: 8px; }
    h1, h2, h3 { font-family: 'Segoe UI', sans-serif; }
</style>
""", unsafe_allow_html=True)

# ── SESSION STATE INIT ───────────────────────────────────────────────────────
for key, val in [
    ('data', None), ('original_data', None), ('filename', None),
    ('schema', None), ('domain', None), ('kpis', None),
    ('template', None), ('ai_history', []),
    ('bundle', None), ('ingest_receipt', []), ('currency_symbol', ''),
    ('ingest_symbols', {}), ('qa_history', []), ('pinned', []),
]:
    if key not in st.session_state:
        st.session_state[key] = val

# ── SIDEBAR ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('## 📊 Sapienoids™')
    st.markdown('*Analytics Portal*')
    st.divider()

    uploaded = st.file_uploader('Upload CSV or Excel', type=['csv', 'xlsx', 'xls'])
    if uploaded is not None and uploaded.name != st.session_state.filename:
        try:
            # Resilient ingest: messy headers, currency strings, total rows, dates
            try:
                ingest = load_uploaded(uploaded)
                df_raw = ingest.df
                st.session_state.ingest_receipt = ingest.receipt
                st.session_state.currency_symbol = ingest.currency_symbol
                st.session_state.ingest_symbols = ingest.symbols
            except Exception:
                uploaded.seek(0)
                if uploaded.name.endswith('csv'):
                    df_raw = pd.read_csv(uploaded)
                else:
                    df_raw = pd.read_excel(uploaded, engine='openpyxl')
                st.session_state.ingest_receipt = []
                st.session_state.currency_symbol = ''
            st.session_state.data = df_raw.copy()
            st.session_state.original_data = df_raw.copy()
            st.session_state.filename = uploaded.name
            # Auto-run schema detection, domain mapping, KPI computation
            try:
                schema = detect_schema(df_raw)
                domain, _ = map_domain(schema)
                schema_register(uploaded.name, schema, domain)
                kpis = compute_kpis(df_raw, schema, domain)
                tmpl = auto_detect_template(list(df_raw.columns))
                st.session_state.schema   = schema
                st.session_state.domain   = domain
                st.session_state.kpis     = kpis
                st.session_state.template = tmpl.name if tmpl else "general"
                st.session_state.ai_history = []  # reset chat on new file
            except Exception as schema_err:
                st.session_state.schema = None
                st.session_state.domain = "general"
            # Preset pipeline: detection → field mapping → audit → KPIs → insights
            try:
                st.session_state.bundle = build_bundle(
                    df_raw, schema=st.session_state.schema,
                    currency_symbol=st.session_state.currency_symbol,
                    column_symbols=st.session_state.get('ingest_symbols'))
            except Exception as bundle_err:
                st.session_state.bundle = None
        except Exception as e:
            st.error(f'Load error: {e}')

    if st.session_state.data is not None:
        d = st.session_state.data
        st.success(f'✅ {st.session_state.filename}')
        col_a, col_b = st.columns(2)
        col_a.metric('Rows', f'{d.shape[0]:,}')
        col_b.metric('Cols', d.shape[1])
        col_c, col_d = st.columns(2)
        col_c.metric('Missing', d.isnull().sum().sum())
        col_d.metric('Dupes', d.duplicated().sum())

        if st.button('↩ Reset to original', use_container_width=True):
            st.session_state.data = st.session_state.original_data.copy()
            st.rerun()

        st.divider()
        page = st.radio('', [
            '⚡  Dashboard',
            '🏠  Overview',
            '🔍  Explore',
            '🔧  Wrangle',
            '📈  Visualize',
            '📊  GroupBy',
            '🧪  Statistics',
            '🤖  Machine Learning',
            '⏱   Time Series',
            '🧠  AI Insights',
            '⬇   Export',
        ], label_visibility='collapsed')
    else:
        st.info('Upload a file to unlock all features.')
        st.divider()
        page = st.radio('', [
            '🏠  Overview',
            '🧠  AI Insights',
        ], label_visibility='collapsed')

    # ── AI Engine Status + Key Config ─────────────────────────────────────────
    st.divider()
    st.caption('**AI Engine**')
    try:
        ai_status = get_sentinel().get_status()
        any_configured = any(s['configured'] for s in ai_status['keys'])
        for s in ai_status['keys']:
            if not s['configured']:
                st.caption(f"⬜ {s['name']} — not configured")
            elif s['available']:
                tag = ' ◀ active' if s['active'] else ''
                st.caption(f"🟢 {s['name']}{tag} — {s['requests']} requests today")
            else:
                st.caption(f"🔴 {s['name']} — API quota hit (resets midnight)")
        if ai_status['both_down']:
            st.caption("⚠ Both keys hit real API quota — fallback mode")
    except Exception:
        any_configured = False
        st.caption('⬜ AI — unavailable')

    # Key entry expander — open by default when no keys are set
    with st.expander('🔑 Add Gemini API Keys', expanded=not any_configured):
        st.caption('Free keys at [aistudio.google.com](https://aistudio.google.com)')
        key1 = st.text_input('PRIMARY key', type='password', key='sb_key1',
                             placeholder='AIza...')
        key2 = st.text_input('BACKUP key (optional)', type='password', key='sb_key2',
                             placeholder='AIza...')
        if st.button('Save & Activate', key='sb_save_keys', use_container_width=True):
            env_path = os.path.join(os.path.dirname(__file__), '.env')
            # Read existing .env lines, replace or append key lines
            try:
                with open(env_path, 'r') as _f:
                    lines = _f.readlines()
            except FileNotFoundError:
                lines = []
            def _set_env_line(lines, var, val):
                found = False
                for i, ln in enumerate(lines):
                    if ln.startswith(f'{var}=') or ln.startswith(f'{var} ='):
                        lines[i] = f'{var}={val}\n'
                        found = True
                        break
                if not found:
                    lines.append(f'{var}={val}\n')
                return lines
            if key1.strip():
                lines = _set_env_line(lines, 'GEMINI_KEY_PRIMARY', key1.strip())
                os.environ['GEMINI_KEY_PRIMARY'] = key1.strip()
            if key2.strip():
                lines = _set_env_line(lines, 'GEMINI_KEY_BACKUP', key2.strip())
                os.environ['GEMINI_KEY_BACKUP'] = key2.strip()
            with open(env_path, 'w') as _f:
                _f.writelines(lines)
            # Reset sentinel so it picks up the new keys
            import core.ai.gemini_client as _gc
            _gc._sentinel = None
            st.success('Keys saved! Reloading...')
            st.rerun()

# ── HELPERS ──────────────────────────────────────────────────────────────────
def require_data():
    if st.session_state.data is None:
        st.info('Upload a file in the sidebar to get started.')
        st.stop()
    return st.session_state.data

def numeric_cols(df):
    return df.select_dtypes(include=np.number).columns.tolist()

def cat_cols(df):
    return df.select_dtypes(include='object').columns.tolist()

def download_buttons(df, prefix='data'):
    c1, c2 = st.columns(2)
    csv_bytes = df.to_csv(index=False).encode('utf-8')
    c1.download_button('⬇ CSV', csv_bytes, f'{prefix}.csv', 'text/csv', use_container_width=True)
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine='openpyxl')
    c2.download_button('⬇ Excel', buf.getvalue(), f'{prefix}.xlsx',
                       'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                       use_container_width=True)

# ════════════════════════════════════════════════════════════════════════════
# PAGE: AUTO DASHBOARD (preset-driven, end-to-end)
# ════════════════════════════════════════════════════════════════════════════
if page == '⚡  Dashboard':
    st.title('⚡ Auto Dashboard')
    st.caption('Industry preset detected from your data — KPIs, charts and '
               'insights configured automatically.')
    render_dashboard()

# ════════════════════════════════════════════════════════════════════════════
# PAGE: OVERVIEW
# ════════════════════════════════════════════════════════════════════════════
elif page == '🏠  Overview':
    st.title(':rainbow[Sapienoids™ Analytics Portal]')
    st.caption('Upload your CSV or Excel file in the sidebar to begin.')

    if st.session_state.data is None:
        st.image('https://img.icons8.com/color/200/combo-chart.png', width=150)
        st.markdown("""
        ### What you can do here
        | Feature | Description |
        |---|---|
        | 🔍 Explore | Value counts, distributions, correlation heatmap |
        | 🔧 Wrangle | Filter, clean, rename and transform your data |
        | 📈 Visualize | Build any chart with full customisation |
        | 📊 GroupBy | Aggregate and analyse groups |
        | 🧪 Statistics | T-tests, Chi-square, outlier detection |
        | 🤖 ML | K-Means clustering & linear regression |
        | ⏱ Time Series | Timeline charts, rolling averages, resampling |
        | ⬇ Export | Download cleaned data as CSV or Excel |
        """)
        st.stop()

    data = require_data()
    st.dataframe(data, use_container_width=True)

    st.subheader(':green[Basic Info]', divider='rainbow')
    t1, t2, t3, t4 = st.tabs(['Summary', 'Top & Bottom Rows', 'Data Types', 'Columns'])

    with t1:
        st.dataframe(data.describe(include='all'), use_container_width=True)

    with t2:
        top_n = st.slider('Top rows', 1, min(50, data.shape[0]), 5, key='ov_top')
        st.dataframe(data.head(top_n), use_container_width=True)
        bot_n = st.slider('Bottom rows', 1, min(50, data.shape[0]), 5, key='ov_bot')
        st.dataframe(data.tail(bot_n), use_container_width=True)

    with t3:
        dtype_df = pd.DataFrame({'Column': data.dtypes.index,
                                  'Type': data.dtypes.astype(str).values,
                                  'Non-Null': data.count().values,
                                  'Null': data.isnull().sum().values})
        st.dataframe(dtype_df, use_container_width=True)

    with t4:
        st.dataframe(pd.DataFrame({
            '#': range(1, len(data.columns) + 1),
            'Column Name': data.columns.tolist(),
            'Type': data.dtypes.astype(str).tolist()
        }), use_container_width=True)

    # ── Schema & KPI strip (auto-detected, shown after file upload) ──────────
    if st.session_state.schema:
        schema = st.session_state.schema
        domain = st.session_state.domain
        tmpl   = st.session_state.template

        st.subheader(':blue[Auto-Detected Schema & Domain]', divider='rainbow')
        m1, m2, m3, m4 = st.columns(4)
        m1.metric('Domain', domain.upper())
        m2.metric('Template', tmpl.upper() if tmpl else 'GENERAL')
        m3.metric('Numeric Cols', len(schema.numeric_cols))
        m4.metric('Temporal Cols', len(schema.temporal_cols))

        with st.expander('Column Roles (auto-classified)'):
            role_df = pd.DataFrame([{
                'Column': n, 'Role': p.role, 'Cardinality': p.cardinality,
                'Completeness': f"{p.completeness*100:.1f}%", 'Dtype': p.dtype
            } for n, p in schema.columns.items()])
            st.dataframe(role_df, use_container_width=True)

        if st.session_state.kpis:
            st.subheader(':orange[Auto-Computed KPIs]', divider='rainbow')
            kpis = st.session_state.kpis
            cols = st.columns(min(4, len(kpis)))
            for i, kpi in enumerate(kpis[:8]):
                cols[i % 4].metric(kpi.name, kpi.formatted_value(), help=kpi.description)

# ════════════════════════════════════════════════════════════════════════════
# PAGE: EXPLORE
# ════════════════════════════════════════════════════════════════════════════
elif page == '🔍  Explore':
    data = require_data()
    st.title('🔍 Explore')
    num_cols = numeric_cols(data)

    # Value Counts
    with st.expander('Value Count', expanded=True):
        col = st.selectbox('Column', data.columns, key='ex_vc_col')
        top_n = st.number_input('Show top N', 1, len(data), 10, key='ex_vc_n')
        if st.button('Count', key='ex_vc_btn'):
            res = data[col].value_counts().reset_index().head(top_n)
            res.columns = [col, 'count']
            st.dataframe(res, use_container_width=True)
            c1, c2, c3 = st.columns(3)
            with c1:
                st.plotly_chart(px.bar(res, x=col, y='count', text='count',
                                        template='seaborn', title='Bar'), use_container_width=True)
            with c2:
                st.plotly_chart(px.line(res, x=col, y='count', markers=True,
                                         template='seaborn', title='Line'), use_container_width=True)
            with c3:
                st.plotly_chart(px.pie(res, names=col, values='count', title='Pie'),
                                use_container_width=True)

    # Distribution
    with st.expander('Distributions'):
        if num_cols:
            dcol = st.selectbox('Numeric column', num_cols, key='ex_dist_col')
            dtype = st.radio('Chart type', ['Histogram', 'Box Plot', 'Violin Plot'], horizontal=True)
            ccol = st.selectbox('Color by (optional)', [None] + list(data.columns), key='ex_dist_cc')
            if dtype == 'Histogram':
                fig = px.histogram(data, x=dcol, color=ccol, marginal='box', template='seaborn')
            elif dtype == 'Box Plot':
                fig = px.box(data, y=dcol, color=ccol, points='outliers', template='seaborn')
            else:
                fig = px.violin(data, y=dcol, color=ccol, box=True, points='outliers', template='seaborn')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info('No numeric columns.')

    # Correlation Heatmap
    with st.expander('Correlation Heatmap'):
        if len(num_cols) >= 2:
            method = st.selectbox('Method', ['pearson', 'spearman', 'kendall'], key='ex_corr_m')
            corr = data[num_cols].corr(method=method)
            fig = px.imshow(corr, text_auto='.2f', color_continuous_scale='RdBu_r',
                            title=f'{method.title()} Correlation Matrix', aspect='auto')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info('Need at least 2 numeric columns.')

    # Scatter Matrix
    with st.expander('Scatter Matrix (Pair Plot)'):
        if len(num_cols) >= 2:
            selected = st.multiselect('Select columns (max 6)', num_cols,
                                       default=num_cols[:min(4, len(num_cols))], key='ex_scat')
            color_col = st.selectbox('Color by', [None] + cat_cols(data), key='ex_scat_cc')
            if len(selected) >= 2:
                fig = px.scatter_matrix(data, dimensions=selected, color=color_col,
                                         title='Scatter Matrix')
                fig.update_traces(diagonal_visible=False)
                st.plotly_chart(fig, use_container_width=True)

# ════════════════════════════════════════════════════════════════════════════
# PAGE: WRANGLE
# ════════════════════════════════════════════════════════════════════════════
elif page == '🔧  Wrangle':
    data = require_data()
    st.title('🔧 Wrangle')
    st.caption('All changes apply to the working dataset. Use **Reset** in the sidebar to undo everything.')

    # Filter rows
    with st.expander('Filter Rows', expanded=True):
        fc = st.selectbox('Column to filter', data.columns, key='wr_fc')
        ops = ['==', '!=', '>', '>=', '<', '<=', 'contains', 'not contains']
        op = st.selectbox('Operator', ops, key='wr_op')
        fval = st.text_input('Value', key='wr_fval')
        if st.button('Apply Filter', key='wr_apply'):
            try:
                import re
                if op == 'contains':
                    try:
                        mask = data[fc].astype(str).str.contains(re.escape(fval), case=False, na=False)
                    except re.error:
                        st.error('Invalid filter value.')
                        mask = pd.Series([True] * len(data), index=data.index)
                elif op == 'not contains':
                    try:
                        mask = ~data[fc].astype(str).str.contains(re.escape(fval), case=False, na=False)
                    except re.error:
                        st.error('Invalid filter value.')
                        mask = pd.Series([True] * len(data), index=data.index)
                else:
                    col_series = pd.to_numeric(data[fc], errors='ignore')
                    try:
                        fval_cast = type(col_series.iloc[0])(fval)
                    except Exception:
                        fval_cast = fval
                    op_map = {
                        '==': lambda a, b: a == b,
                        '!=': lambda a, b: a != b,
                        '>':  lambda a, b: a > b,
                        '>=': lambda a, b: a >= b,
                        '<':  lambda a, b: a < b,
                        '<=': lambda a, b: a <= b,
                    }
                    mask = op_map[op](col_series, fval_cast)
                filtered = data[mask].reset_index(drop=True)
                st.session_state.data = filtered
                st.success(f'Filter applied — {len(filtered):,} rows remain.')
                st.rerun()
            except Exception as e:
                st.error(f'Filter error: {e}')

    # Handle missing values
    with st.expander('Handle Missing Values'):
        miss = data.isnull().sum()
        miss_cols = miss[miss > 0].index.tolist()
        if not miss_cols:
            st.success('No missing values.')
        else:
            mc = st.selectbox('Column', miss_cols, key='wr_mc')
            method = st.selectbox('Fill method', ['Mean', 'Median', 'Mode', 'Custom value', 'Drop rows'], key='wr_mm')
            custom_val = ''
            if method == 'Custom value':
                custom_val = st.text_input('Value to fill with', key='wr_cv')
            if st.button('Apply', key='wr_miss_apply'):
                df2 = st.session_state.data.copy()
                if method == 'Mean':
                    df2[mc] = df2[mc].fillna(df2[mc].mean())
                elif method == 'Median':
                    df2[mc] = df2[mc].fillna(df2[mc].median())
                elif method == 'Mode':
                    df2[mc] = df2[mc].fillna(df2[mc].mode()[0])
                elif method == 'Custom value':
                    df2[mc] = df2[mc].fillna(custom_val)
                elif method == 'Drop rows':
                    df2 = df2.dropna(subset=[mc]).reset_index(drop=True)
                st.session_state.data = df2
                st.success(f'Done. {method} applied to "{mc}".')
                st.rerun()

    # Remove duplicates
    with st.expander('Remove Duplicates'):
        dupe_count = data.duplicated().sum()
        st.write(f'**{dupe_count}** duplicate rows detected.')
        if dupe_count > 0:
            if st.button('Remove duplicates', key='wr_dupe'):
                st.session_state.data = data.drop_duplicates().reset_index(drop=True)
                st.success(f'Removed {dupe_count} duplicates.')
                st.rerun()

    # Drop columns
    with st.expander('Drop Columns'):
        drop_cols = st.multiselect('Select columns to drop', data.columns, key='wr_drop')
        if drop_cols and st.button('Drop', key='wr_drop_btn'):
            st.session_state.data = data.drop(columns=drop_cols)
            st.success(f'Dropped: {drop_cols}')
            st.rerun()

    # Rename columns
    with st.expander('Rename Column'):
        old_name = st.selectbox('Column to rename', data.columns, key='wr_ren_old')
        new_name = st.text_input('New name', key='wr_ren_new')
        if new_name and st.button('Rename', key='wr_ren_btn'):
            st.session_state.data = data.rename(columns={old_name: new_name})
            st.success(f'Renamed "{old_name}" → "{new_name}"')
            st.rerun()

    # Change data type
    with st.expander('Change Column Type'):
        tc = st.selectbox('Column', data.columns, key='wr_tc')
        new_type = st.selectbox('Convert to', ['int', 'float', 'str', 'datetime'], key='wr_tt')
        if st.button('Convert', key='wr_tt_btn'):
            df2 = st.session_state.data.copy()
            try:
                if new_type == 'datetime':
                    df2[tc] = pd.to_datetime(df2[tc])
                else:
                    df2[tc] = df2[tc].astype(new_type)
                st.session_state.data = df2
                st.success(f'"{tc}" converted to {new_type}.')
                st.rerun()
            except Exception as e:
                st.error(f'Conversion error: {e}')

    st.divider()
    st.subheader('Current Data Preview')
    st.dataframe(st.session_state.data, use_container_width=True)

# ════════════════════════════════════════════════════════════════════════════
# PAGE: VISUALIZE
# ════════════════════════════════════════════════════════════════════════════
elif page == '📈  Visualize':
    data = require_data()
    st.title('📈 Visualize')

    chart_type = st.selectbox('Chart type', [
        'Scatter', 'Line', 'Bar', 'Histogram', 'Box', 'Violin',
        'Area', 'Pie', 'Sunburst', 'Treemap', 'Funnel', 'Heatmap (2D Bin)'
    ], key='viz_ct')

    all_cols = list(data.columns)
    num = numeric_cols(data)
    cats = cat_cols(data)

    c1, c2, c3 = st.columns(3)

    if chart_type == 'Scatter':
        x = c1.selectbox('X', all_cols, key='viz_x')
        y = c2.selectbox('Y', all_cols, key='viz_y')
        color = c3.selectbox('Color', [None] + all_cols, key='viz_c')
        size = c1.selectbox('Size', [None] + num, key='viz_sz')
        facet = c2.selectbox('Facet col', [None] + cats, key='viz_fc')
        trendline = c3.selectbox('Trendline', [None, 'ols', 'lowess'], key='viz_tr')
        fig = px.scatter(data, x=x, y=y, color=color, size=size,
                          facet_col=facet, trendline=trendline, template='seaborn')

    elif chart_type == 'Line':
        x = c1.selectbox('X', all_cols, key='viz_x')
        y = c2.selectbox('Y', all_cols, key='viz_y')
        color = c3.selectbox('Color', [None] + all_cols, key='viz_c')
        fig = px.line(data, x=x, y=y, color=color, markers=True, template='seaborn')

    elif chart_type == 'Bar':
        x = c1.selectbox('X', all_cols, key='viz_x')
        y = c2.selectbox('Y', all_cols, key='viz_y')
        color = c3.selectbox('Color', [None] + all_cols, key='viz_c')
        barmode = c1.selectbox('Mode', ['group', 'stack', 'overlay'], key='viz_bm')
        facet = c2.selectbox('Facet col', [None] + cats, key='viz_fc')
        fig = px.bar(data, x=x, y=y, color=color, barmode=barmode, facet_col=facet, template='seaborn')

    elif chart_type == 'Histogram':
        x = c1.selectbox('Column', all_cols, key='viz_x')
        color = c2.selectbox('Color', [None] + all_cols, key='viz_c')
        bins = c3.slider('Bins', 5, 200, 30, key='viz_bins')
        fig = px.histogram(data, x=x, color=color, nbins=bins,
                            marginal='box', template='seaborn')

    elif chart_type == 'Box':
        y = c1.selectbox('Y (values)', num if num else all_cols, key='viz_y')
        x = c2.selectbox('X (groups)', [None] + all_cols, key='viz_x')
        color = c3.selectbox('Color', [None] + all_cols, key='viz_c')
        fig = px.box(data, x=x, y=y, color=color, points='outliers', template='seaborn')

    elif chart_type == 'Violin':
        y = c1.selectbox('Y (values)', num if num else all_cols, key='viz_y')
        x = c2.selectbox('X (groups)', [None] + all_cols, key='viz_x')
        color = c3.selectbox('Color', [None] + all_cols, key='viz_c')
        fig = px.violin(data, x=x, y=y, color=color, box=True, points='outliers', template='seaborn')

    elif chart_type == 'Area':
        x = c1.selectbox('X', all_cols, key='viz_x')
        y = c2.selectbox('Y', all_cols, key='viz_y')
        color = c3.selectbox('Color', [None] + all_cols, key='viz_c')
        fig = px.area(data, x=x, y=y, color=color, template='seaborn')

    elif chart_type == 'Pie':
        names = c1.selectbox('Labels', all_cols, key='viz_n')
        values = c2.selectbox('Values', num if num else all_cols, key='viz_v')
        hole = c3.slider('Donut hole', 0.0, 0.8, 0.0, 0.05, key='viz_hole')
        fig = px.pie(data, names=names, values=values, hole=hole)

    elif chart_type == 'Sunburst':
        path = c1.multiselect('Hierarchy (order matters)', all_cols, key='viz_path')
        values = c2.selectbox('Values', [None] + num, key='viz_v')
        fig = px.sunburst(data, path=path, values=values) if path else go.Figure()

    elif chart_type == 'Treemap':
        path = c1.multiselect('Hierarchy (order matters)', all_cols, key='viz_path')
        values = c2.selectbox('Values', [None] + num, key='viz_v')
        fig = px.treemap(data, path=path, values=values) if path else go.Figure()

    elif chart_type == 'Funnel':
        x = c1.selectbox('Values', num if num else all_cols, key='viz_x')
        y = c2.selectbox('Stage labels', all_cols, key='viz_y')
        fig = px.funnel(data, x=x, y=y)

    elif chart_type == 'Heatmap (2D Bin)':
        if len(num) >= 2:
            x = c1.selectbox('X', num, key='viz_x')
            y = c2.selectbox('Y', num, key='viz_y')
            fig = px.density_heatmap(data, x=x, y=y, marginal_x='histogram',
                                      marginal_y='histogram', color_continuous_scale='Viridis')
        else:
            st.info('Need at least 2 numeric columns.')
            st.stop()

    st.plotly_chart(fig, use_container_width=True)

# ════════════════════════════════════════════════════════════════════════════
# PAGE: GROUPBY
# ════════════════════════════════════════════════════════════════════════════
elif page == '📊  GroupBy':
    data = require_data()
    st.title('📊 GroupBy')
    st.caption('Summarize data by specific groups and categories.')

    c1, c2, c3 = st.columns(3)
    groupby_col = c1.multiselect('Group by columns', data.columns, key='gb_gc')
    op_col = c2.selectbox('Aggregate column', data.columns, key='gb_oc')
    operation = c3.selectbox('Aggregation', ['sum', 'mean', 'median', 'max', 'min',
                                               'count', 'std', 'var', 'first', 'last', 'nunique'])

    if groupby_col:
        try:
            result = data.groupby(groupby_col).agg(
                newcol=(op_col, operation)
            ).reset_index()
            st.dataframe(result, use_container_width=True)
            download_buttons(result, 'groupby_result')

            st.subheader('Visualize Result')
            graph = st.selectbox('Chart type', ['bar', 'line', 'scatter', 'pie', 'sunburst', 'treemap'], key='gb_gt')
            rc = list(result.columns)

            if graph in ['bar', 'line', 'scatter']:
                cx, cy, cc = st.columns(3)
                x = cx.selectbox('X', rc, key='gb_x')
                y = cy.selectbox('Y', rc, index=len(rc)-1, key='gb_y')
                color = cc.selectbox('Color', [None] + rc, key='gb_c')
                if graph == 'bar':
                    facet = st.selectbox('Facet', [None] + rc, key='gb_f')
                    fig = px.bar(result, x=x, y=y, color=color, facet_col=facet, barmode='group', template='seaborn')
                elif graph == 'line':
                    fig = px.line(result, x=x, y=y, color=color, markers=True, template='seaborn')
                else:
                    fig = px.scatter(result, x=x, y=y, color=color, template='seaborn')
                st.plotly_chart(fig, use_container_width=True)

            elif graph == 'pie':
                pv = st.selectbox('Values', rc, key='gb_pv')
                pn = st.selectbox('Labels', rc, key='gb_pn')
                st.plotly_chart(px.pie(result, values=pv, names=pn), use_container_width=True)

            elif graph in ['sunburst', 'treemap']:
                path = st.multiselect('Hierarchy', rc, key='gb_path')
                if path:
                    fig = (px.sunburst if graph == 'sunburst' else px.treemap)(
                        result, path=path, values='newcol')
                    st.plotly_chart(fig, use_container_width=True)

        except Exception as e:
            st.error(f'Error: {e}')

# ════════════════════════════════════════════════════════════════════════════
# PAGE: STATISTICS
# ════════════════════════════════════════════════════════════════════════════
elif page == '🧪  Statistics':
    data = require_data()
    st.title('🧪 Statistics')
    num = numeric_cols(data)

    # Outlier Detection
    with st.expander('Outlier Detection (Z-Score)', expanded=True):
        if num:
            oc = st.selectbox('Column', num, key='st_oc')
            z_thresh = st.slider('Z-score threshold', 1.5, 4.0, 3.0, 0.1)
            col_data = data[oc].dropna()
            z_scores = np.abs(stats.zscore(col_data))
            outliers = col_data[z_scores > z_thresh]
            st.metric('Outliers found', len(outliers))
            if not outliers.empty:
                c1, c2 = st.columns(2)
                c1.plotly_chart(px.box(data, y=oc, points='all', title='Box with Outliers'),
                                use_container_width=True)
                c2.plotly_chart(px.histogram(data, x=oc, marginal='rug', title='Distribution'),
                                use_container_width=True)
                if st.button('Remove outliers from dataset'):
                    full_z = np.abs(stats.zscore(data[oc].fillna(data[oc].mean())))
                    st.session_state.data = data[full_z <= z_thresh].reset_index(drop=True)
                    st.success(f'Removed {len(outliers)} outlier rows.')
                    st.rerun()
        else:
            st.info('No numeric columns.')

    # T-Tests
    with st.expander('T-Tests'):
        if num:
            ttype = st.radio('Test type', ['One-Sample', 'Two-Sample (Independent)'], horizontal=True)
            if ttype == 'One-Sample':
                tc = st.selectbox('Column', num, key='st_t1c')
                mu = st.number_input('Population mean', value=float(data[tc].mean()), key='st_mu')
                if st.button('Run One-Sample T-Test'):
                    t, p = stats.ttest_1samp(data[tc].dropna(), mu)
                    st.write(f'**T-stat:** {t:.4f} | **P-value:** {p:.4f}')
                    st.success('Significant (p < 0.05)') if p < 0.05 else st.info('Not significant (p ≥ 0.05)')
            else:
                ca = st.selectbox('Column A', num, key='st_t2a')
                cb = st.selectbox('Column B', num, key='st_t2b')
                if st.button('Run Two-Sample T-Test'):
                    t, p = stats.ttest_ind(data[ca].dropna(), data[cb].dropna())
                    st.write(f'**T-stat:** {t:.4f} | **P-value:** {p:.4f}')
                    st.success('Significantly different (p < 0.05)') if p < 0.05 else st.info('Not significant (p ≥ 0.05)')

    # Chi-Square
    with st.expander('Chi-Square Test'):
        cats = cat_cols(data)
        if len(cats) >= 2:
            cx = st.selectbox('Column X', cats, key='st_cx')
            cy = st.selectbox('Column Y', cats, key='st_cy')
            if st.button('Run Chi-Square'):
                ct = pd.crosstab(data[cx], data[cy])
                chi2, p, dof, _ = stats.chi2_contingency(ct)
                st.write(f'**Chi²:** {chi2:.4f} | **P-value:** {p:.4f} | **DoF:** {dof}')
                st.success('Significant association (p < 0.05)') if p < 0.05 else st.info('No significant association (p ≥ 0.05)')
                st.dataframe(ct, use_container_width=True)
        else:
            st.info('Need at least 2 categorical columns.')

    # ANOVA
    with st.expander('One-Way ANOVA'):
        if num and cat_cols(data):
            av = st.selectbox('Numeric (dependent)', num, key='st_av')
            ag = st.selectbox('Categorical (groups)', cat_cols(data), key='st_ag')
            if st.button('Run ANOVA'):
                groups = [grp[av].dropna().values for _, grp in data.groupby(ag)]
                f, p = stats.f_oneway(*groups)
                st.write(f'**F-stat:** {f:.4f} | **P-value:** {p:.4f}')
                st.success('Significant group differences (p < 0.05)') if p < 0.05 else st.info('No significant differences (p ≥ 0.05)')
                st.plotly_chart(px.box(data, x=ag, y=av, color=ag, template='seaborn',
                                        title=f'ANOVA: {av} by {ag}'), use_container_width=True)
        else:
            st.info('Need at least one numeric and one categorical column.')

# ════════════════════════════════════════════════════════════════════════════
# PAGE: MACHINE LEARNING
# ════════════════════════════════════════════════════════════════════════════
elif page == '🤖  Machine Learning':
    data = require_data()
    st.title('🤖 Machine Learning')
    num = numeric_cols(data)

    ml_tab1, ml_tab2 = st.tabs(['K-Means Clustering', 'Linear Regression'])

    with ml_tab1:
        st.subheader('K-Means Clustering')
        if len(num) < 2:
            st.info('Need at least 2 numeric columns.')
        else:
            feat_cols = st.multiselect('Features', num,
                                        default=num[:min(3, len(num))], key='ml_km_feat')
            k = st.slider('Number of clusters (K)', 2, 10, 3, key='ml_km_k')
            color_by = st.selectbox('Visualize X axis', feat_cols if feat_cols else num, key='ml_km_x')
            color_by_y = st.selectbox('Visualize Y axis', feat_cols if feat_cols else num, key='ml_km_y')

            if feat_cols and st.button('Run K-Means', key='ml_km_run'):
                X = data[feat_cols].dropna()
                scaler = StandardScaler()
                X_scaled = scaler.fit_transform(X)
                km = KMeans(n_clusters=k, random_state=42, n_init='auto')
                labels = km.fit_predict(X_scaled)
                result_df = X.copy()
                result_df['Cluster'] = labels.astype(str)

                fig = px.scatter(result_df, x=color_by, y=color_by_y,
                                  color='Cluster', title=f'K-Means (K={k})',
                                  template='seaborn', symbol='Cluster')
                st.plotly_chart(fig, use_container_width=True)

                st.subheader('Cluster Sizes')
                st.dataframe(result_df['Cluster'].value_counts().reset_index()
                              .rename(columns={'Cluster': 'Cluster', 'count': 'Count'}),
                              use_container_width=True)

                st.subheader('Cluster Means')
                st.dataframe(result_df.groupby('Cluster')[feat_cols].mean().round(3),
                              use_container_width=True)

                # Elbow chart
                st.subheader('Elbow Chart (Optimal K)')
                inertias = []
                k_range = range(2, min(11, len(X)))
                with st.spinner('Computing elbow curve...'):
                    for ki in k_range:
                        inertias.append(KMeans(n_clusters=ki, random_state=42, n_init='auto').fit(X_scaled).inertia_)
                elbow_df = pd.DataFrame({'K': list(k_range), 'Inertia': inertias})
                st.plotly_chart(px.line(elbow_df, x='K', y='Inertia', markers=True,
                                         title='Elbow Method — pick K at the bend'),
                                use_container_width=True)

    with ml_tab2:
        st.subheader('Linear Regression')
        if len(num) < 2:
            st.info('Need at least 2 numeric columns.')
        else:
            cx = st.selectbox('X (feature)', num, key='ml_lr_x')
            cy = st.selectbox('Y (target)', num, key='ml_lr_y')
            if st.button('Run Regression', key='ml_lr_run'):
                df_lr = data[[cx, cy]].dropna()
                X_lr = df_lr[[cx]].values
                y_lr = df_lr[cy].values
                model = LinearRegression()
                model.fit(X_lr, y_lr)
                y_pred = model.predict(X_lr)
                r2 = r2_score(y_lr, y_pred)

                fig = px.scatter(df_lr, x=cx, y=cy, opacity=0.6, template='seaborn',
                                  title=f'Linear Regression — R² = {r2:.4f}')
                fig.add_traces(go.Scatter(x=df_lr[cx], y=y_pred, mode='lines',
                                           name='Fit', line=dict(color='red', width=2)))
                st.plotly_chart(fig, use_container_width=True)

                m1, m2, m3 = st.columns(3)
                m1.metric('R² Score', f'{r2:.4f}')
                m2.metric('Coefficient', f'{model.coef_[0]:.4f}')
                m3.metric('Intercept', f'{model.intercept_:.4f}')
                st.caption(f'Equation: **{cy} = {model.coef_[0]:.4f} × {cx} + {model.intercept_:.4f}**')

                # Residuals
                st.subheader('Residual Plot')
                residuals = y_lr - y_pred
                res_df = pd.DataFrame({'Predicted': y_pred, 'Residual': residuals})
                fig2 = px.scatter(res_df, x='Predicted', y='Residual', template='seaborn',
                                   title='Residuals vs Predicted')
                fig2.add_hline(y=0, line_dash='dash', line_color='red')
                st.plotly_chart(fig2, use_container_width=True)

# ════════════════════════════════════════════════════════════════════════════
# PAGE: TIME SERIES
# ════════════════════════════════════════════════════════════════════════════
elif page == '⏱   Time Series':
    data = require_data()
    st.title('⏱ Time Series')

    # Auto-detect datetime columns
    dt_cols = data.select_dtypes(include=['datetime64']).columns.tolist()
    maybe_dt = [c for c in data.columns if 'date' in c.lower() or 'time' in c.lower() or 'year' in c.lower()]
    all_possible = list(dict.fromkeys(dt_cols + maybe_dt + list(data.columns)))

    date_col = st.selectbox('Date/Time column', all_possible, key='ts_dc')
    num = numeric_cols(data)

    if not num:
        st.info('No numeric columns to plot.')
        st.stop()

    value_col = st.selectbox('Value column', num, key='ts_vc')

    try:
        ts_df = data[[date_col, value_col]].copy()
        ts_df[date_col] = pd.to_datetime(ts_df[date_col])
        ts_df = ts_df.dropna().sort_values(date_col)
    except Exception as e:
        st.error(f'Could not parse "{date_col}" as dates: {e}')
        st.stop()

    # Resample
    resample_map = {'None': None, 'Daily': 'D', 'Weekly': 'W', 'Monthly': 'ME', 'Quarterly': 'QE', 'Yearly': 'YE'}
    resample_choice = st.selectbox('Resample / aggregate by', list(resample_map.keys()), key='ts_rs')
    agg_func = st.selectbox('Aggregation', ['mean', 'sum', 'max', 'min', 'count'], key='ts_agg')

    if resample_map[resample_choice]:
        ts_df = ts_df.set_index(date_col).resample(resample_map[resample_choice]).agg({value_col: agg_func}).reset_index()

    # Rolling average
    rolling_window = st.slider('Rolling average window (0 = off)', 0, 90, 0, key='ts_roll')

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ts_df[date_col], y=ts_df[value_col],
                              mode='lines+markers', name=value_col, opacity=0.6))
    if rolling_window > 0:
        ts_df['rolling'] = ts_df[value_col].rolling(rolling_window, min_periods=1).mean()
        fig.add_trace(go.Scatter(x=ts_df[date_col], y=ts_df['rolling'],
                                  mode='lines', name=f'{rolling_window}-period Rolling Avg',
                                  line=dict(color='red', width=2)))

    fig.update_layout(title=f'{value_col} over Time', xaxis_title=date_col,
                       yaxis_title=value_col, template='seaborn', hovermode='x unified')
    st.plotly_chart(fig, use_container_width=True)

    # Stats summary
    s1, s2, s3, s4 = st.columns(4)
    s1.metric('Min', f'{ts_df[value_col].min():.2f}')
    s2.metric('Max', f'{ts_df[value_col].max():.2f}')
    s3.metric('Mean', f'{ts_df[value_col].mean():.2f}')
    s4.metric('Total', f'{ts_df[value_col].sum():.2f}')

    st.subheader('Trend Decomposition (Seasonal Decompose)')
    if len(ts_df) >= 14:
        try:
            from statsmodels.tsa.seasonal import seasonal_decompose
            period = st.slider('Decompose period', 2, min(365, len(ts_df)//2), 7, key='ts_period')
            decomp = seasonal_decompose(ts_df[value_col].ffill(), model='additive', period=period)
            decomp_df = pd.DataFrame({
                'Date': ts_df[date_col].values,
                'Observed': decomp.observed,
                'Trend': decomp.trend,
                'Seasonal': decomp.seasonal,
                'Residual': decomp.resid
            })
            for component in ['Observed', 'Trend', 'Seasonal', 'Residual']:
                fig_d = px.line(decomp_df.dropna(), x='Date', y=component,
                                 title=component, template='seaborn')
                st.plotly_chart(fig_d, use_container_width=True)
        except ImportError:
            st.info('Install `statsmodels` to enable decomposition: `pip install statsmodels`')
        except Exception as e:
            st.warning(f'Decomposition skipped: {e}')
    else:
        st.info('Need at least 14 data points for decomposition.')

# ════════════════════════════════════════════════════════════════════════════
# PAGE: AI INSIGHTS
# ════════════════════════════════════════════════════════════════════════════
elif page == '🧠  AI Insights':
    st.title('🧠 AI Insights')
    sentinel = get_sentinel()
    ai_status = sentinel.get_status()

    if ai_status['both_down']:
        st.warning(
            'Both Gemini API keys are at capacity. '
            'Add keys to your `.env` file to unlock AI features.'
        )

    # Determine mode
    data   = st.session_state.data
    schema = st.session_state.schema
    domain = st.session_state.domain or 'general'
    kpis   = st.session_state.kpis or []

    has_data = data is not None
    if has_data:
        st.success(f'Data-Aware Chat — dataset loaded: **{st.session_state.filename}**')
    else:
        st.info('General Chat — no dataset loaded. You can chat freely or upload a document below for context.')

    # ── Optional document upload (text context, no analytics pipeline) ────────
    with st.expander('Upload a document for AI context (optional)', expanded=not has_data):
        st.caption('Supported: `.txt` `.md` `.py` `.csv` `.xlsx` `.xls` `.json` `.xml` `.html` `.log`')
        doc_file = st.file_uploader(
            'Document for AI context',
            type=['txt', 'md', 'py', 'csv', 'xlsx', 'xls', 'json', 'xml', 'html', 'htm', 'log'],
            key='ai_doc_upload',
            label_visibility='collapsed',
        )
        doc_text_input = st.text_area('Or paste text directly', height=120, key='ai_doc_paste')

    # Build document context string
    _DOC_LIMIT = 20000   # generous — sentinel will hard-cap at 30k if needed
    doc_context = ''
    if doc_file is not None:
        try:
            name = doc_file.name.lower()
            if name.endswith(('.xlsx', '.xls')):
                engine = 'openpyxl' if name.endswith('.xlsx') else 'xlrd'
                xdf = pd.read_excel(doc_file, engine=engine, nrows=500)
                doc_context = (
                    f"Excel file: {doc_file.name}\n"
                    f"Shape: {xdf.shape[0]} rows × {xdf.shape[1]} columns\n"
                    f"Columns: {list(xdf.columns)}\n\n"
                    f"{xdf.to_csv(index=False)}"
                )
            elif name.endswith('.json'):
                import json as _json
                raw = doc_file.read().decode('utf-8', errors='replace')
                parsed = _json.loads(raw)
                doc_context = _json.dumps(parsed, indent=2)
            else:
                raw = doc_file.read()
                doc_context = raw.decode('utf-8', errors='replace')

            if len(doc_context) > _DOC_LIMIT:
                doc_context = doc_context[:_DOC_LIMIT] + f'\n[...truncated at {_DOC_LIMIT:,} chars...]'
            st.success(f'Loaded: **{doc_file.name}** — {len(doc_context):,} chars sent to Gemini')
        except Exception as doc_err:
            st.warning(f'Could not read document: {doc_err}')
    elif doc_text_input.strip():
        doc_context = doc_text_input.strip()[:_DOC_LIMIT]

    # ── Auto-Insights (data-aware mode only) ─────────────────────────────────
    if has_data:
        with st.expander('Auto-Generated Data Insights', expanded=True):
            if st.button('Generate Insights', key='ai_gen'):
                tmpl_cls = get_template(domain)
                prefix   = tmpl_cls().ai_prompt_prefix() if tmpl_cls else 'You are a senior data analyst. '
                ctx = schema.summary_string() if schema else f"Dataset with {len(data)} rows."
                kpi_ctx = kpis_to_context_string(kpis, kpis[0].column if kpis else '') if kpis else ''
                prompt = (
                    f"{prefix}\n\n"
                    f"Here is the dataset context (do NOT repeat these stats verbatim — "
                    f"interpret them):\n\n{ctx}\n\n{kpi_ctx}\n\n"
                    f"Provide 5 specific, actionable business insights. "
                    f"Format as a numbered list. Each insight should be 1-2 sentences."
                )
                with st.spinner('Asking Gemini...'):
                    response = sentinel.generate_insight(prompt)
                st.session_state.ai_history.append({'role': 'assistant', 'content': response})
                st.markdown(response)

        # ── Auto Chart Suggestions ────────────────────────────────────────────
        with st.expander('Auto-Suggested Charts'):
            if schema:
                recs = recommend_charts(data, schema, max_recommendations=4)
                for rec in recs:
                    st.caption(f'**{rec.title}** — {rec.reasoning}')
                    fig = render_recommendation(rec, data)
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.info('Schema not available — re-upload your file.')

    # ── NL Chat ──────────────────────────────────────────────────────────────
    st.subheader('Chat with Gemini')
    if has_data:
        st.caption('Ask any question about your dataset in plain English.')
        placeholder = 'e.g. "Which column has the most outliers?"'
    else:
        st.caption('Ask Gemini anything — data analysis, coding, general questions.')
        placeholder = 'e.g. "What is a p-value?" or "How do I handle missing data?"'

    # Suggested prompts when no data loaded
    if not has_data and not st.session_state.ai_history:
        st.markdown('**Suggested prompts:**')
        suggested = [
            'Explain the difference between mean and median.',
            'What charts work best for time series data?',
            'How do I detect outliers in a dataset?',
            'What is the best way to handle missing values?',
        ]
        cols = st.columns(2)
        for i, s in enumerate(suggested):
            if cols[i % 2].button(s, key=f'sugg_{i}', use_container_width=True):
                st.session_state.ai_history.append({'role': 'user', 'content': s})
                st.rerun()

    for msg in st.session_state.ai_history:
        with st.chat_message(msg['role']):
            st.markdown(msg['content'])

    if prompt_input := st.chat_input(placeholder):
        st.session_state.ai_history.append({'role': 'user', 'content': prompt_input})
        with st.chat_message('user'):
            st.markdown(prompt_input)

        # Build context block
        if has_data:
            ctx = schema.summary_string() if schema else f"Dataset: {len(data)} rows, {len(data.columns)} cols."
            kpi_ctx = kpis_to_context_string(kpis, kpis[0].column if kpis else '') if kpis else ''
            data_block = f"Dataset context:\n{ctx}\n{kpi_ctx}\n\n"
        else:
            data_block = ''

        doc_block = f"Additional context from uploaded document:\n{doc_context}\n\n" if doc_context else ''

        full_prompt = (
            f"You are a helpful data analyst assistant.\n"
            f"{data_block}"
            f"{doc_block}"
            f"User question: {prompt_input}\n\n"
            f"Answer concisely and specifically. Do not repeat context back."
        )
        with st.chat_message('assistant'):
            with st.spinner('Thinking...'):
                reply = sentinel.generate_insight(full_prompt)
            st.markdown(reply)
        st.session_state.ai_history.append({'role': 'assistant', 'content': reply})

    if st.session_state.ai_history:
        if st.button('Clear chat history', key='ai_clear'):
            st.session_state.ai_history = []
            st.rerun()

    # ── Failover Log ─────────────────────────────────────────────────────────
    if sentinel.switch_log():
        with st.expander('Key Failover Log'):
            log_df = pd.DataFrame(sentinel.switch_log())
            st.dataframe(log_df, use_container_width=True)

# ════════════════════════════════════════════════════════════════════════════
# PAGE: EXPORT
# ════════════════════════════════════════════════════════════════════════════
elif page == '⬇   Export':
    data = require_data()
    st.title('⬇ Export')

    st.subheader('Download Current Dataset')
    st.caption('Downloads the working (possibly cleaned/filtered) dataset.')
    download_buttons(data, 'sapienoids_export')

    st.divider()
    st.subheader('Dataset Summary Report')
    orig = st.session_state.original_data
    rows_removed = len(orig) - len(data)
    cols_removed = len(orig.columns) - len(data.columns)
    st.markdown(f"""
    | Metric | Original | Current |
    |---|---|---|
    | Rows | {len(orig):,} | {len(data):,} |
    | Columns | {len(orig.columns)} | {len(data.columns)} |
    | Missing values | {orig.isnull().sum().sum()} | {data.isnull().sum().sum()} |
    | Duplicate rows | {orig.duplicated().sum()} | {data.duplicated().sum()} |
    | Rows removed | — | {rows_removed:,} |
    | Columns removed | — | {cols_removed} |
    """)

    st.divider()
    st.subheader('Full Analytics Report')
    st.caption('Generates a report with schema, KPIs, and AI summary.')
    schema  = st.session_state.schema
    kpis    = st.session_state.kpis or []
    domain  = st.session_state.domain or 'general'
    fname   = st.session_state.filename or 'dataset'

    if schema:
        r1, r2 = st.columns(2)
        with r1:
            if st.button('Generate PDF Report', use_container_width=True):
                with st.spinner('Building PDF...'):
                    try:
                        pdf_bytes = generate_pdf_report(
                            df=data, schema=schema, kpi_results=kpis,
                            domain=domain, filename=fname
                        )
                        st.download_button(
                            '⬇ Download PDF', pdf_bytes,
                            file_name='sapienoids_report.pdf',
                            mime='application/pdf', use_container_width=True
                        )
                    except Exception as e:
                        st.error(f'PDF generation failed: {e}')
        with r2:
            if st.button('Generate Excel Report', use_container_width=True):
                with st.spinner('Building Excel...'):
                    try:
                        xl_bytes = generate_excel_report(
                            df=data, schema=schema, kpi_results=kpis,
                            domain=domain, filename=fname
                        )
                        st.download_button(
                            '⬇ Download Excel', xl_bytes,
                            file_name='sapienoids_report.xlsx',
                            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            use_container_width=True
                        )
                    except Exception as e:
                        st.error(f'Excel generation failed: {e}')
    else:
        st.info('Re-upload your file to enable report generation.')
