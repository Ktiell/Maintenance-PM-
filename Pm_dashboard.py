# pm_dashboard.py
# Full Maintenance PM Dashboard (Streamlit)
# - Clickable KPI filters (Overdue / Due Soon / OK / etc.) + Clear Filter
# - "Assets Maintained" tab (one row per asset; shows components, tasks, earliest due)
# - Time or meter PM with next-due calc, color-coded table
# - Add/Edit PMs, Log Completion, CSV import/export, bulk meter update, printable schedule
# - Optimized: fewer expensive styling passes, cached options, tight layout

import os
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta

import pandas as pd
import streamlit as st

# -----------------------
# Config
# -----------------------
st.set_page_config(page_title="Maintenance PM Dashboard", page_icon="🛠️", layout="wide")
DATA_FILE = "pm_data.csv"
DATE_FMT = "%Y-%m-%d"

PRIORITIES = ["Low", "Medium", "High", "Critical"]
STATUSES = ["Active", "Paused", "Retired"]
INTERVAL_TYPES = ["Days", "Weeks", "Months", "Meter"]
DUE_SOON_DAYS_DEFAULT = 14
METER_SOON_THRESHOLD_DEFAULT = 50

CSS = """
<style>
.block-container { padding-top: 0.75rem !important; }
.badge {display:inline-block;padding:0.25rem 0.6rem;border-radius:999px;font-size:0.75rem;font-weight:600;margin-right:0.4rem;background:#eee;}
.badge.red{background:#ffe5e5;color:#b00020;} .badge.yellow{background:#fff4db;color:#6a4a00;}
.badge.green{background:#e7f7ed;color:#006d3b;} .badge.gray{background:#ececec;color:#333;}
.kpi {width:100%; border:1px solid #eee; border-radius:12px; padding:0.7rem 0.8rem; text-align:center; cursor:pointer;}
.kpi h2 {margin:0;font-size:1.4rem;}
.kpi span {display:block; font-size:0.8rem; opacity:0.8;}
.kpi.overdue{background:#ffe5e5;} .kpi.duesoon{background:#fff4db;}
.kpi.ok{background:#e7f7ed;} .kpi.unknown{background:#f3f3f3;}
.kpi.paused{background:#f3f3f3;} .kpi.retired{background:#f3f3f3;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# -----------------------
# Helpers
# -----------------------
def today_str(): return date.today().strftime(DATE_FMT)

def parse_date(s):
    if pd.isna(s) or s == "": return None
    if isinstance(s, (date, datetime)): return s if isinstance(s, date) else s.date()
    try: return datetime.strptime(str(s), DATE_FMT).date()
    except Exception:
        try: return pd.to_datetime(s).date()
        except Exception: return None

def safe_int(v):
    try:
        if v is None or str(v).strip() == "": return None
        return int(float(v))
    except Exception: return None

def compute_next_due(row):
    t = (row.get("IntervalType") or "").strip()
    iv = safe_int(row.get("IntervalValue"))
    ld = parse_date(row.get("LastDoneDate"))
    lm = safe_int(row.get("LastMeter"))
    cm = safe_int(row.get("CurrentMeter"))
    nd_date, nd_meter = None, None
    if t in ["Days","Weeks","Months"]:
        if not iv or iv <= 0: return None, None
        base = ld or date.today()
        if t=="Days": nd_date = base + timedelta(days=iv)
        elif t=="Weeks": nd_date = base + timedelta(weeks=iv)
        else: nd_date = base + relativedelta(months=iv)
    elif t=="Meter":
        if not iv or iv <= 0: return None, None
        if lm is None:
            base = cm if cm is not None else 0
            nd_meter = base + iv
        else:
            nd_meter = lm + iv
    return nd_date, nd_meter

def compute_status(row, due_soon_days, meter_soon):
    t = (row.get("IntervalType") or "").strip()
    if t in ["Days","Weeks","Months"]:
        nd = parse_date(row.get("NextDueDate"))
        if not nd: s, delta = "Unknown", None
        else:
            days_left = (nd - date.today()).days
            delta = days_left
            if days_left < 0: s = "Overdue"
            elif days_left <= due_soon_days: s = "Due Soon"
            else: s = "OK"
    elif t=="Meter":
        ndm, cm = safe_int(row.get("NextDueMeter")), safe_int(row.get("CurrentMeter"))
        if ndm is None or cm is None: s, delta = "Unknown", None
        else:
            meters_left = ndm - cm
            delta = meters_left
            if meters_left < 0: s = "Overdue"
            elif meters_left <= meter_soon: s = "Due Soon"
            else: s = "OK"
    else:
        s, delta = "Unknown", None
    pm_state = (row.get("PMStatus") or "Active").strip()
    if pm_state in ["Paused","Retired"]: s = pm_state
    return s, delta

def base_columns():
    return [
        "Site","AssetID","AssetName","Component","PMTask",
        "IntervalType","IntervalValue",
        "LastDoneDate","LastMeter","CurrentMeter",
        "NextDueDate","NextDueMeter",
        "Priority","PMStatus","Owner","Notes"
    ]

def ensure_columns(df):
    cols = base_columns()
    for c in cols:
        if c not in df.columns: df[c] = None
    return df[cols]

def recompute_all(df):
    df = df.copy()
    for i, row in df.iterrows():
        nd_date, nd_meter = compute_next_due(row)
        df.at[i,"NextDueDate"] = nd_date.strftime(DATE_FMT) if isinstance(nd_date,(date,datetime)) else None
        df.at[i,"NextDueMeter"] = nd_meter if nd_meter is not None else None
    return df

def sample_data():
    t = date.today()
    return pd.DataFrame([
        dict(Site="Main Plant", AssetID="CMP-401", AssetName="Air Compressor #1",
             Component="Compressor", PMTask="Change oil & filter",
             IntervalType="Months", IntervalValue="6",
             LastDoneDate=(t - relativedelta(months=7)).strftime(DATE_FMT),
             LastMeter="", CurrentMeter="", NextDueDate="", NextDueMeter="",
             Priority="High", PMStatus="Active", Owner="Keith", Notes="Use ISO 68"),
        dict(Site="Main Plant", AssetID="FLT-112", AssetName="Forklift A",
             Component="Engine", PMTask="Service @ every 200 hrs",
             IntervalType="Meter", IntervalValue="200",
             LastDoneDate=(t - relativedelta(months=2)).strftime(DATE_FMT),
             LastMeter="1400", CurrentMeter="1585", NextDueDate="", NextDueMeter="",
             Priority="Medium", PMStatus="Active", Owner="Shop", Notes=""),
        dict(Site="Warehouse", AssetID="FAN-020", AssetName="Exhaust Fan",
             Component="Motor", PMTask="Grease bearings",
             IntervalType="Weeks", IntervalValue="12",
             LastDoneDate=(t - relativedelta(weeks=10)).strftime(DATE_FMT),
             LastMeter="", CurrentMeter="", NextDueDate="", NextDueMeter="",
             Priority="Low", PMStatus="Paused", Owner="Vendor", Notes="Awaiting parts"),
    ])

def load_data():
    if os.path.exists(DATA_FILE): df = pd.read_csv(DATA_FILE, dtype=str)
    else:
        df = sample_data(); df.to_csv(DATA_FILE, index=False)
    df = ensure_columns(df)
    df = recompute_all(df)
    return df

def save_data(df):
    ensure_columns(df).to_csv(DATA_FILE, index=False)

def export_csv_button(df, label="Download CSV"):
    st.download_button(label=label, data=df.to_csv(index=False),
                       file_name=f"pm_export_{today_str()}.csv",
                       mime="text/csv", use_container_width=True)

# -----------------------
# Session State
# -----------------------
if "df" not in st.session_state: st.session_state.df = load_data()
if "due_soon_days" not in st.session_state: st.session_state.due_soon_days = DUE_SOON_DAYS_DEFAULT
if "meter_soon" not in st.session_state: st.session_state.meter_soon = METER_SOON_THRESHOLD_DEFAULT
if "status_filter" not in st.session_state: st.session_state.status_filter = None  # From KPI clicks

# -----------------------
# Sidebar
# -----------------------
with st.sidebar:
    st.header("⚙️ Controls")
    st.subheader("Import CSV")
    up = st.file_uploader("Replace current data with a CSV", type=["csv"])
    if up is not None:
        try:
            nd = pd.read_csv(up, dtype=str)
            nd = ensure_columns(nd)
            st.session_state.df = recompute_all(nd)
            save_data(st.session_state.df)
            st.success("Imported and saved.")
        except Exception as e:
            st.error(f"Import failed: {e}")

    st.subheader("Due Thresholds")
    st.session_state.due_soon_days = st.number_input("Days = 'Due Soon' cutoff",
        min_value=1, max_value=120, value=st.session_state.due_soon_days, step=1)
    st.session_state.meter_soon = st.number_input("Meters = 'Due Soon' cutoff",
        min_value=1, max_value=2000, value=st.session_state.meter_soon, step=5)

    st.subheader("Filters")
    df_all = st.session_state.df
    sites = ["(All)"] + sorted(df_all["Site"].dropna().unique().tolist())
    assets = ["(All)"] + sorted(df_all["AssetName"].dropna().unique().tolist())
    site_f = st.selectbox("Site", sites, index=0)
    asset_f = st.selectbox("Asset", assets, index=0)
    priority_f = st.selectbox("Priority", ["(All)"] + PRIORITIES, index=0)
    pmstatus_f = st.selectbox("PM Status", ["(All)"] + STATUSES, index=0)
    interval_f = st.multiselect("Interval Type(s)", INTERVAL_TYPES, default=INTERVAL_TYPES)

    st.subheader("Search")
    q = st.text_input("Search (task, component, asset, notes)")

    st.subheader("Actions")
    if st.button("💾 Save to pm_data.csv", use_container_width=True):
        save_data(st.session_state.df); st.success("Saved.")
    export_csv_button(st.session_state.df, "⬇️ Export current table")

# -----------------------
# Tabs
# -----------------------
tab1, tab2 = st.tabs(["📊 Dashboard", "📒 Assets Maintained"])

# -----------------------
# Dashboard Tab
# -----------------------
with tab1:
    st.title("🛠️ Maintenance PM Dashboard")
    st.caption("Tap the KPI tiles to filter. ‘Clear Filter’ resets it. Red = late, Yellow = almost due, Green = fine.")

    # # -----------------------
# KPI tiles (fully clickable)
# -----------------------
# Build status counts
counts = {"Overdue":0,"Due Soon":0,"OK":0,"Unknown":0,"Paused":0,"Retired":0}
for _, r in st.session_state.df.iterrows():
    s, _ = compute_status(r, st.session_state.due_soon_days, st.session_state.meter_soon)
    counts[s] = counts.get(s, 0) + 1

c1, c2, c3, c4, c5, c6, c7 = st.columns(7)

def kpi_button(col, label):
    # Big, tap-friendly button that sets the filter
    with col:
        clicked = st.button(f"{label}\n{counts[label]}", key=f"kpi_{label.replace(' ','_')}", use_container_width=True)
        if clicked:
            st.session_state.status_filter = label

kpi_button(c1, "Overdue")
kpi_button(c2, "Due Soon")
kpi_button(c3, "OK")
kpi_button(c4, "Unknown")
kpi_button(c5, "Paused")
kpi_button(c6, "Retired")

with c7:
    if st.button("Clear Filter", use_container_width=True, key="kpi_clear"):
        st.session_state.status_filter = None
sf = st.session_state.status_filter or "(none)"
st.caption(f"Active KPI filter: **{sf}**")

st.divider()

    # Add / Edit
    st.subheader("➕ Add / ✏️ Edit PM")
    with st.expander("Open Form", expanded=False):
        df = st.session_state.df
        mode = st.radio("Mode", ["Add New", "Edit Existing"], horizontal=True)
        idx = None
        if mode == "Edit Existing" and len(df):
            pick = st.selectbox("Select PM row", [f"{i}: {r.AssetName} • {r.PMTask}" for i, r in df.iterrows()], index=0)
            idx = int(pick.split(":")[0])

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            site = st.text_input("Site", value=(df.at[idx,"Site"] if idx is not None else ""))
            asset_id = st.text_input("Asset ID", value=(df.at[idx,"AssetID"] if idx is not None else ""))
            asset_name = st.text_input("Asset Name", value=(df.at[idx,"AssetName"] if idx is not None else ""))
        with c2:
            component = st.text_input("Component", value=(df.at[idx,"Component"] if idx is not None else ""))
            task = st.text_input("PM Task", value=(df.at[idx,"PMTask"] if idx is not None else ""))
            owner = st.text_input("Owner", value=(df.at[idx,"Owner"] if idx is not None else ""))
        with c3:
            interval_type = st.selectbox("Interval Type", INTERVAL_TYPES,
                index=(INTERVAL_TYPES.index(df.at[idx,"IntervalType"]) if idx is not None and df.at[idx,"IntervalType"] in INTERVAL_TYPES else 0))
            interval_value = st.number_input("Interval Value", 0, 100000,
                value=int(float(df.at[idx,"IntervalValue"])) if idx is not None and str(df.at[idx,"IntervalValue"]).strip() not in ["","None","nan"] else 0)
            priority = st.selectbox("Priority", PRIORITIES,
                index=(PRIORITIES.index(df.at[idx,"Priority"]) if idx is not None and df.at[idx,"Priority"] in PRIORITIES else 1))
        with c4:
            pm_status = st.selectbox("PM Status", STATUSES,
                index=(STATUSES.index(df.at[idx,"PMStatus"]) if idx is not None and df.at[idx,"PMStatus"] in STATUSES else 0))
            last_done_date = st.date_input("Last Done Date", value=parse_date(df.at[idx,"LastDoneDate"]) if idx is not None and parse_date(df.at[idx,"LastDoneDate"]) else date.today())
            last_meter = st.text_input("Last Meter", value=(df.at[idx,"LastMeter"] if idx is not None and str(df.at[idx,"LastMeter"])!="nan" else ""))
            current_meter = st.text_input("Current Meter", value=(df.at[idx,"CurrentMeter"] if idx is not None and str(df.at[idx,"CurrentMeter"])!="nan" else ""))

        notes = st.text_area("Notes", value=(df.at[idx,"Notes"] if idx is not None and str(df.at[idx,"Notes"])!="nan" else ""))

        cL, cR = st.columns(2)
        with cL:
            if st.button("✅ Save PM", use_container_width=True):
                row = dict(
                    Site=site.strip(), AssetID=asset_id.strip(), AssetName=asset_name.strip(),
                    Component=component.strip(), PMTask=task.strip(),
                    IntervalType=interval_type, IntervalValue=str(interval_value) if interval_value else "",
                    LastDoneDate=last_done_date.strftime(DATE_FMT) if last_done_date else "",
                    LastMeter=str(last_meter).strip() if last_meter else "",
                    CurrentMeter=str(current_meter).strip() if current_meter else "",
                    NextDueDate="", NextDueMeter="",
                    Priority=priority, PMStatus=pm_status, Owner=owner.strip(), Notes=notes.strip()
                )
                nd_date, nd_meter = compute_next_due(row)
                row["NextDueDate"] = nd_date.strftime(DATE_FMT) if isinstance(nd_date,(date,datetime)) else ""
                row["NextDueMeter"] = nd_meter if nd_meter is not None else ""
                if mode == "Edit Existing" and idx is not None:
                    for k, v in row.items(): st.session_state.df.at[idx, k] = v
                    st.success("PM updated.")
                else:
                    st.session_state.df = pd.concat([st.session_state.df, pd.DataFrame([row])], ignore_index=True)
                    st.success("PM created.")
                save_data(st.session_state.df)
        with cR:
            if mode == "Edit Existing" and idx is not None:
                if st.button("🗑️ Delete PM", use_container_width=True, type="secondary"):
                    st.session_state.df = st.session_state.df.drop(index=idx).reset_index(drop=True)
                    save_data(st.session_state.df); st.success("PM deleted.")

    # Log Completion
    st.subheader("📘 Log Completion")
    with st.expander("Update a PM as completed", expanded=False):
        df = st.session_state.df
        if len(df):
            pick = st.selectbox("Select PM to log", [f"{i}: {r.AssetName} • {r.PMTask}" for i, r in df.iterrows()], index=0)
            i_sel = int(pick.split(":")[0])
            new_date = st.date_input("Completion Date", value=date.today())
            new_meter = st.text_input("Completion Meter (optional)", value="")
            if st.button("✔️ Log Completion", use_container_width=True):
                st.session_state.df.at[i_sel,"LastDoneDate"] = new_date.strftime(DATE_FMT)
                if (st.session_state.df.at[i_sel,"IntervalType"] == "Meter") and new_meter.strip():
                    st.session_state.df.at[i_sel,"LastMeter"] = new_meter.strip()
                    st.session_state.df.at[i_sel,"CurrentMeter"] = new_meter.strip()
                row = st.session_state.df.loc[i_sel].to_dict()
                nd_date, nd_meter = compute_next_due(row)
                st.session_state.df.at[i_sel,"NextDueDate"] = nd_date.strftime(DATE_FMT) if isinstance(nd_date,(date,datetime)) else ""
                st.session_state.df.at[i_sel,"NextDueMeter"] = nd_meter if nd_meter is not None else ""
                save_data(st.session_state.df); st.success("Completion logged.")
        else:
            st.info("No PMs available.")

    # Apply filters
    def apply_filters(df_in):
        out = df_in.copy()
        if site_f != "(All)": out = out[out["Site"] == site_f]
        if asset_f != "(All)": out = out[out["AssetName"] == asset_f]
        if priority_f != "(All)": out = out[out["Priority"] == priority_f]
        if pmstatus_f != "(All)": out = out[out["PMStatus"] == pmstatus_f]
        if interval_f: out = out[out["IntervalType"].isin(interval_f)]
        # KPI status filter (from clicks)
        if st.session_state.status_filter:
            keep = []
            for _, r in out.iterrows():
                s, _ = compute_status(r, st.session_state.due_soon_days, st.session_state.meter_soon)
                keep.append(s == st.session_state.status_filter)
            out = out[pd.Series(keep, index=out.index)]
        # Search
        if q and q.strip():
            ql = q.strip().lower()
            sel = (
                out["PMTask"].fillna("").str.lower().str.contains(ql) |
                out["Component"].fillna("").str.lower().str.contains(ql) |
                out["AssetName"].fillna("").str.lower().str.contains(ql) |
                out["Notes"].fillna("").str.lower().str.contains(ql)
            )
            out = out[sel]
        return out

    filtered = apply_filters(st.session_state.df)

    # Display table with computed status & urgency
    disp = filtered.copy()
    due_statuses, urgency = [], []
    for _, r in disp.iterrows():
        s, d = compute_status(r, st.session_state.due_soon_days, st.session_state.meter_soon)
        due_statuses.append(s); urgency.append(d)
    disp.insert(0, "DueStatus", due_statuses)
    disp.insert(1, "Urgency (days/meter left)", urgency)
    view_cols = ["DueStatus","Urgency (days/meter left)"] + base_columns()
    disp = ensure_columns(disp).reindex(columns=view_cols, fill_value="")

    st.subheader("📋 PM List")
    st.caption("Tip: use the KPI tiles above to jump straight to Overdue/Due Soon/OK.")
    st.dataframe(disp, use_container_width=True, height=520)

    # Bulk meter update
    st.subheader("⛽ Quick Meter Update
