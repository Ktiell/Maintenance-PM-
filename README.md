# pm_dashboard.py
# Full Interactive Maintenance PM Dashboard (Streamlit)
# Features:
# - Time- or meter-based PM with next-due calculation
# - Color-coded status (Overdue / Due Soon / OK)
# - Global filters (site, asset, priority, status, date/meter windows)
# - Quick search
# - Add/Edit PMs
# - Log completion (updates last done date/meter and recomputes next due)
# - CSV import/export persistence (pm_data.csv)
# - Printable schedule view

import os
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta

import pandas as pd
import streamlit as st

# -----------------------
# Config & Constants
# -----------------------
st.set_page_config(
    page_title="Maintenance PM Dashboard",
    page_icon="🛠️",
    layout="wide"
)

DATA_FILE = "pm_data.csv"
DATE_FMT = "%Y-%m-%d"

PRIORITIES = ["Low", "Medium", "High", "Critical"]
STATUSES = ["Active", "Paused", "Retired"]
INTERVAL_TYPES = ["Days", "Weeks", "Months", "Meter"]

DUE_SOON_DAYS_DEFAULT = 14  # threshold for "Due Soon"
METER_SOON_THRESHOLD_DEFAULT = 50  # threshold for "Due Soon" (meter)

# -----------------------
# Styling
# -----------------------
CSS = """
<style>
/* Clean, modern vibe */
:root { --gap: 0.6rem; }
section [data-testid="stHorizontalBlock"] > div { gap: var(--gap); }

.block-container { padding-top: 1rem !important; }
.sidebar .sidebar-content { padding-top: 1rem !important; }

div[data-testid="stMetricValue"] { font-weight: 700; }
.badge {
  display:inline-block; padding:0.2rem 0.5rem; border-radius:999px;
  font-size:0.75rem; font-weight:600; background:#eee; margin-right:0.4rem;
}
.badge.red { background:#ffe5e5; color:#b00020; }
.badge.yellow { background:#fff4db; color:#6a4a00; }
.badge.green { background:#e7f7ed; color:#006d3b; }
.badge.gray { background:#ececec; color:#333; }
footer {visibility:hidden;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# -----------------------
# Helpers
# -----------------------
def today_str():
    return date.today().strftime(DATE_FMT)

def parse_date(s):
    if pd.isna(s) or s == "":
        return None
    if isinstance(s, (datetime, date)):
        return s
    try:
        return datetime.strptime(str(s), DATE_FMT).date()
    except Exception:
        try:
            return pd.to_datetime(s).date()
        except Exception:
            return None

def safe_int(v):
    try:
        if v is None or v == "":
            return None
        return int(float(v))
    except Exception:
        return None

def compute_next_due(row):
    """Compute next due date or meter based on interval type."""
    interval_type = row.get("IntervalType", "")
    interval_value = safe_int(row.get("IntervalValue"))
    last_done_date = parse_date(row.get("LastDoneDate"))
    last_meter = safe_int(row.get("LastMeter"))
    current_meter = safe_int(row.get("CurrentMeter"))

    next_due_date = None
    next_due_meter = None

    if interval_type in ["Days", "Weeks", "Months"]:
        base_date = last_done_date or date.today()
        if interval_value is None or interval_value <= 0:
            return None, None
        if interval_type == "Days":
            next_due_date = base_date + timedelta(days=interval_value)
        elif interval_type == "Weeks":
            next_due_date = base_date + timedelta(weeks=interval_value)
        else:  # Months
            next_due_date = base_date + relativedelta(months=interval_value)

    elif interval_type == "Meter":
        if interval_value is None or interval_value <= 0:
            return None, None
        if last_meter is None:
            # If we don't have a baseline, assume due at current + interval
            base = current_meter if current_meter is not None else 0
            next_due_meter = base + interval_value
        else:
            next_due_meter = last_meter + interval_value

    return next_due_date, next_due_meter

def compute_status(row, due_soon_days=DUE_SOON_DAYS_DEFAULT, meter_soon=METER_SOON_THRESHOLD_DEFAULT):
    """Return status string and days/meter to due."""
    interval_type = row.get("IntervalType", "")
    status_flag = "OK"
    delta_value = None  # days until due (time) or meters remaining (meter)

    if interval_type in ["Days", "Weeks", "Months"]:
        nd = parse_date(row.get("NextDueDate"))
        if nd is None:
            return "Unknown", None
        days_left = (nd - date.today()).days
        delta_value = days_left
        if days_left < 0:
            status_flag = "Overdue"
        elif days_left <= due_soon_days:
            status_flag = "Due Soon"
        else:
            status_flag = "OK"

    elif interval_type == "Meter":
        ndm = safe_int(row.get("NextDueMeter"))
        cm = safe_int(row.get("CurrentMeter"))
        if ndm is None or cm is None:
            return "Unknown", None
        meters_left = ndm - cm
        delta_value = meters_left
        if meters_left < 0:
            status_flag = "Overdue"
        elif meters_left <= meter_soon:
            status_flag = "Due Soon"
        else:
            status_flag = "OK"
    else:
        status_flag = "Unknown"

    # Respect PM Status (Paused/Retired) – override to gray-ish buckets
    pm_state = (row.get("PMStatus") or "Active").strip()
    if pm_state in ["Paused", "Retired"]:
        status_flag = pm_state

    return status_flag, delta_value

def color_row(row):
    s, _ = compute_status(row)
    if s == "Overdue":
        return ["background-color: #ffe5e5"] * len(row)
    if s == "Due Soon":
        return ["background-color: #fff4db"] * len(row)
    if s in ["Paused", "Retired"]:
        return ["background-color: #f1f1f1"] * len(row)
    if s == "OK":
        return ["background-color: #e7f7ed"] * len(row)
    return [""] * len(row)

def base_columns():
    return [
        "Site", "AssetID", "AssetName", "Component", "PMTask",
        "IntervalType", "IntervalValue",
        "LastDoneDate", "LastMeter", "CurrentMeter",
        "NextDueDate", "NextDueMeter",
        "Priority", "PMStatus", "Owner", "Notes"
    ]

def ensure_columns(df):
    cols = base_columns()
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]

def load_data():
    if os.path.exists(DATA_FILE):
        df = pd.read_csv(DATA_FILE, dtype=str)
    else:
        df = sample_data()
        df.to_csv(DATA_FILE, index=False)

    # Normalize dtypes
    df = ensure_columns(df)
    # Recompute next dues to be safe
    df = recompute_all(df)
    return df

def save_data(df):
    df = ensure_columns(df)
    df.to_csv(DATA_FILE, index=False)

def recompute_all(df):
    df = df.copy()
    for i, row in df.iterrows():
        nd_date, nd_meter = compute_next_due(row)
        df.at[i, "NextDueDate"] = nd_date.strftime(DATE_FMT) if isinstance(nd_date, (date, datetime)) else None
        df.at[i, "NextDueMeter"] = nd_meter if nd_meter is not None else None
    return df

def sample_data():
    today = date.today()
    return pd.DataFrame([
        {
            "Site": "Main Plant",
            "AssetID": "CMP-401",
            "AssetName": "Air Compressor #1",
            "Component": "Compressor",
            "PMTask": "Change oil & filter",
            "IntervalType": "Months",
            "IntervalValue": "6",
            "LastDoneDate": (today - relativedelta(months=7)).strftime(DATE_FMT),
            "LastMeter": "",
            "CurrentMeter": "",
            "NextDueDate": "",
            "NextDueMeter": "",
            "Priority": "High",
            "PMStatus": "Active",
            "Owner": "Keith",
            "Notes": "Use ISO 68"
        },
        {
            "Site": "Main Plant",
            "AssetID": "FLT-112",
            "AssetName": "Forklift A",
            "Component": "Engine",
            "PMTask": "Service @ every 200 hrs",
            "IntervalType": "Meter",
            "IntervalValue": "200",
            "LastDoneDate": (today - relativedelta(months=2)).strftime(DATE_FMT),
            "LastMeter": "1400",
            "CurrentMeter": "1585",
            "NextDueDate": "",
            "NextDueMeter": "",
            "Priority": "Medium",
            "PMStatus": "Active",
            "Owner": "Shop",
            "Notes": ""
        },
        {
            "Site": "Warehouse",
            "AssetID": "FAN-020",
            "AssetName": "Exhaust Fan",
            "Component": "Motor",
            "PMTask": "Grease bearings",
            "IntervalType": "Weeks",
            "IntervalValue": "12",
            "LastDoneDate": (today - relativedelta(weeks=10)).strftime(DATE_FMT),
            "LastMeter": "",
            "CurrentMeter": "",
            "NextDueDate": "",
            "NextDueMeter": "",
            "Priority": "Low",
            "PMStatus": "Paused",
            "Owner": "Vendor",
            "Notes": "Awaiting parts"
        },
    ])

def export_csv_button(df, label="Download CSV"):
    st.download_button(
        label=label,
        data=df.to_csv(index=False),
        file_name=f"pm_export_{today_str()}.csv",
        mime="text/csv",
        use_container_width=True
    )

# -----------------------
# Session init
# -----------------------
if "df" not in st.session_state:
    st.session_state.df = load_data()
if "due_soon_days" not in st.session_state:
    st.session_state.due_soon_days = DUE_SOON_DAYS_DEFAULT
if "meter_soon" not in st.session_state:
    st.session_state.meter_soon = METER_SOON_THRESHOLD_DEFAULT

# -----------------------
# Sidebar - Controls
# -----------------------
with st.sidebar:
    st.header("⚙️ Controls")

    # Import
    st.subheader("Import CSV")
    uploaded = st.file_uploader("Replace current data with a CSV", type=["csv"])
    if uploaded is not None:
        try:
            new_df = pd.read_csv(uploaded, dtype=str)
            new_df = ensure_columns(new_df)
            st.session_state.df = recompute_all(new_df)
            save_data(st.session_state.df)
            st.success("Imported and saved.")
        except Exception as e:
            st.error(f"Import failed: {e}")

    st.subheader("Due Thresholds")
    st.session_state.due_soon_days = st.number_input(
        "Days = 'Due Soon' cutoff",
        min_value=1, max_value=120, value=st.session_state.due_soon_days, step=1
    )
    st.session_state.meter_soon = st.number_input(
        "Meters = 'Due Soon' cutoff",
        min_value=1, max_value=1000, value=st.session_state.meter_soon, step=5
    )

    st.subheader("Filters")
    df = st.session_state.df

    # Dynamic options
    sites = ["(All)"] + sorted([s for s in df["Site"].dropna().unique()])
    assets = ["(All)"] + sorted([s for s in df["AssetName"].dropna().unique()])
    priorities = ["(All)"] + PRIORITIES
    pm_states = ["(All)"] + STATUSES

    site_f = st.selectbox("Site", sites, index=0)
    asset_f = st.selectbox("Asset", assets, index=0)
    priority_f = st.selectbox("Priority", priorities, index=0)
    pmstatus_f = st.selectbox("PM Status", pm_states, index=0)

    interval_f = st.multiselect("Interval Type(s)", INTERVAL_TYPES, default=INTERVAL_TYPES)
    status_focus = st.multiselect("Due Status focus", ["Overdue", "Due Soon", "OK", "Unknown", "Paused", "Retired"], default=["Overdue","Due Soon","OK","Unknown","Paused","Retired"])

    st.subheader("Search")
    q = st.text_input("Search (task, component, notes, asset)")

    st.subheader("Actions")
    if st.button("💾 Save to pm_data.csv", use_container_width=True):
        save_data(st.session_state.df)
        st.success("Saved.")

    export_csv_button(st.session_state.df, "⬇️ Export current table")

# -----------------------
# Header / KPIs
# -----------------------
st.title("🛠️ Maintenance PM Dashboard")
st.caption("Tell it like it is: red = you're late, yellow = it's coming, green = you're fine. Let’s keep assets happy and downtime boring.")

# Recompute statuses for KPI
work_df = st.session_state.df.copy()

status_counts = {"Overdue":0,"Due Soon":0,"OK":0,"Unknown":0,"Paused":0,"Retired":0}
for _, r in work_df.iterrows():
    s, _ = compute_status(r, st.session_state.due_soon_days, st.session_state.meter_soon)
    status_counts[s] = status_counts.get(s,0)+1

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Overdue", status_counts.get("Overdue",0))
c2.metric("Due Soon", status_counts.get("Due Soon",0))
c3.metric("OK", status_counts.get("OK",0))
c4.metric("Unknown", status_counts.get("Unknown",0))
c5.metric("Paused", status_counts.get("Paused",0))
c6.metric("Retired", status_counts.get("Retired",0))

# -----------------------
# Add / Edit Forms
# -----------------------
st.subheader("➕ Add / ✏️ Edit PM")

with st.expander("Open Form", expanded=False):
    form_mode = st.radio("Mode", ["Add New", "Edit Existing"], horizontal=True)

    if form_mode == "Edit Existing":
        key_col = st.selectbox(
            "Select PM row to edit (by Asset / Task)",
            options=[f"{i}: {row.AssetName} • {row.PMTask}" for i, row in st.session_state.df.iterrows()],
            index=0 if len(st.session_state.df) else None
        )
        idx = int(key_col.split(":")[0]) if len(st.session_state.df) else None
    else:
        idx = None

    colA, colB, colC, colD = st.columns(4)
    with colA:
        site = st.text_input("Site", value=(st.session_state.df.at[idx,"Site"] if idx is not None else ""))
        asset_id = st.text_input("Asset ID", value=(st.session_state.df.at[idx,"AssetID"] if idx is not None else ""))
        asset_name = st.text_input("Asset Name", value=(st.session_state.df.at[idx,"AssetName"] if idx is not None else ""))
    with colB:
        component = st.text_input("Component", value=(st.session_state.df.at[idx,"Component"] if idx is not None else ""))
        task = st.text_input("PM Task", value=(st.session_state.df.at[idx,"PMTask"] if idx is not None else ""))
        owner = st.text_input("Owner", value=(st.session_state.df.at[idx,"Owner"] if idx is not None else ""))
    with colC:
        interval_type = st.selectbox("Interval Type", INTERVAL_TYPES, index=(INTERVAL_TYPES.index(st.session_state.df.at[idx,"IntervalType"]) if idx is not None and st.session_state.df.at[idx,"IntervalType"] in INTERVAL_TYPES else 0))
        interval_value = st.number_input("Interval Value", min_value=0, max_value=100000, value=int(float(st.session_state.df.at[idx,"IntervalValue"])) if idx is not None and str(st.session_state.df.at[idx,"IntervalValue"]).strip() not in ["","None","nan"] else 0)
        priority = st.selectbox("Priority", PRIORITIES, index=(PRIORITIES.index(st.session_state.df.at[idx,"Priority"]) if idx is not None and st.session_state.df.at[idx,"Priority"] in PRIORITIES else 1))
    with colD:
        pm_status = st.selectbox("PM Status", STATUSES, index=(STATUSES.index(st.session_state.df.at[idx,"PMStatus"]) if idx is not None and st.session_state.df.at[idx,"PMStatus"] in STATUSES else 0))
        last_done_date = st.date_input("Last Done Date", value=parse_date(st.session_state.df.at[idx,"LastDoneDate"]) if idx is not None and parse_date(st.session_state.df.at[idx,"LastDoneDate"]) else date.today())
        last_meter = st.text_input("Last Meter", value=(st.session_state.df.at[idx,"LastMeter"] if idx is not None and str(st.session_state.df.at[idx,"LastMeter"])!="nan" else ""))
        current_meter = st.text_input("Current Meter", value=(st.session_state.df.at[idx,"CurrentMeter"] if idx is not None and str(st.session_state.df.at[idx,"CurrentMeter"])!="nan" else ""))

    notes = st.text_area("Notes", value=(st.session_state.df.at[idx,"Notes"] if idx is not None and str(st.session_state.df.at[idx,"Notes"])!="nan" else ""))

    colX, colY = st.columns([1,1])
    with colX:
        if st.button("✅ Save PM", use_container_width=True):
            row = {
                "Site": site.strip(),
                "AssetID": asset_id.strip(),
                "AssetName": asset_name.strip(),
                "Component": component.strip(),
                "PMTask": task.strip(),
                "IntervalType": interval_type,
                "IntervalValue": str(interval_value) if interval_value else "",
                "LastDoneDate": last_done_date.strftime(DATE_FMT) if last_done_date else "",
                "LastMeter": str(last_meter).strip() if last_meter else "",
                "CurrentMeter": str(current_meter).strip() if current_meter else "",
                "NextDueDate": "",
                "NextDueMeter": "",
                "Priority": priority,
                "PMStatus": pm_status,
                "Owner": owner.strip(),
                "Notes": notes.strip(),
            }
            nd_date, nd_meter = compute_next_due(row)
            row["NextDueDate"] = nd_date.strftime(DATE_FMT) if isinstance(nd_date, (date, datetime)) else ""
            row["NextDueMeter"] = nd_meter if nd_meter is not None else ""

            if form_mode == "Edit Existing" and idx is not None:
                for k, v in row.items():
                    st.session_state.df.at[idx, k] = v
                st.success("PM updated.")
            else:
                st.session_state.df = pd.concat([st.session_state.df, pd.DataFrame([row])], ignore_index=True)
                st.success("PM created.")

            save_data(st.session_state.df)

    with colY:
        if form_mode == "Edit Existing" and idx is not None:
            if st.button("🗑️ Delete PM", use_container_width=True, type="secondary"):
                st.session_state.df = st.session_state.df.drop(index=idx).reset_index(drop=True)
                save_data(st.session_state.df)
                st.success("PM deleted.")

# -----------------------
# Log Completion
# -----------------------
st.subheader("📘 Log Completion")
with st.expander("Update a PM as completed", expanded=False):
    if len(st.session_state.df):
        target = st.selectbox(
            "Select PM to log",
            options=[f"{i}: {row.AssetName} • {row.PMTask}" for i, row in st.session_state.df.iterrows()],
            index=0
        )
        i_sel = int(target.split(":")[0])

        new_done_date = st.date_input("Completion Date", value=date.today(), key="comp_date")
        new_meter = st.text_input("Completion Meter (optional)", value="", key="comp_meter")

        if st.button("✔️ Log Completion", use_container_width=True):
            st.session_state.df.at[i_sel, "LastDoneDate"] = new_done_date.strftime(DATE_FMT)
            if (st.session_state.df.at[i_sel, "IntervalType"] == "Meter") and (new_meter.strip() != ""):
                st.session_state.df.at[i_sel, "LastMeter"] = new_meter.strip()
                # CurrentMeter should usually be >= last meter
                st.session_state.df.at[i_sel, "CurrentMeter"] = new_meter.strip()

            # Recompute next due
            row = st.session_state.df.loc[i_sel].to_dict()
            nd_date, nd_meter = compute_next_due(row)
            st.session_state.df.at[i_sel, "NextDueDate"] = nd_date.strftime(DATE_FMT) if isinstance(nd_date, (date, datetime)) else ""
            st.session_state.df.at[i_sel, "NextDueMeter"] = nd_meter if nd_meter is not None else ""

            save_data(st.session_state.df)
            st.success("Completion logged and next due recalculated.")
    else:
        st.info("No PMs available.")

# -----------------------
# Filter + Search
# -----------------------
def apply_filters(df):
    out = df.copy()

    if site_f != "(All)":
        out = out[out["Site"] == site_f]
    if asset_f != "(All)":
        out = out[out["AssetName"] == asset_f]
    if priority_f != "(All)":
        out = out[out["Priority"] == priority_f]
    if pmstatus_f != "(All)":
        out = out[out["PMStatus"] == pmstatus_f]
    if interval_f:
        out = out[out["IntervalType"].isin(interval_f)]

    # Status focus
    mask = []
    for _, r in out.iterrows():
        s, _ = compute_status(r, st.session_state.due_soon_days, st.session_state.meter_soon)
        mask.append(s in status_focus)
    out = out[pd.Series(mask, index=out.index)]

    # S
