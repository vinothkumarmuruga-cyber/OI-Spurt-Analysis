"""NSE F&O — OI Spurts Analyser (Streamlit)

Inputs : the 4 NSE "Spurts in OI" CSVs + the daily F&O BhavCopy CSV
         (upload in the app, or drop them in ./data and commit to GitHub).
"""
import hashlib
import math
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="NSE F&O — OI Spurts Analyser", page_icon="📊", layout="wide")

DATA_DIR = Path(__file__).parent / "data"
INDEX_SYMS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}
RISK_FREE = 0.065

CSS = """<style>
.stApp{background:#0d0f14}
.block-container{max-width:1400px;padding-top:3.5rem;padding-left:2rem;padding-right:2rem}
header[data-testid="stHeader"]{background:#0d0f14;border-bottom:1px solid #232734}
header[data-testid="stHeader"] *{color:#e5e7eb !important}
header[data-testid="stHeader"] svg{fill:#e5e7eb}
section[data-testid="stSidebar"]{background:#11141b}
.stApp label,.stApp [data-testid="stWidgetLabel"] p,.stApp [data-testid="stCaptionContainer"],.stApp [data-testid="stCaptionContainer"] p,section[data-testid="stSidebar"] p,section[data-testid="stSidebar"] small{color:#c9d1dd !important}
[data-testid="stFileUploaderDropzone"]{background:#1a1e2a;border:1px dashed #3a4256}
[data-testid="stFileUploaderDropzone"] *{color:#c9d1dd}
[data-testid="stFileUploaderDropzone"] button{background:#f5c542;color:#111 !important;border:none;font-weight:700}
.stButton>button{background:#f5c542;color:#111 !important;border:none;font-weight:800;font-size:1rem;padding:.6rem 1rem;border-radius:10px}
.stButton>button:hover{background:#ffd75e;color:#111 !important}
.stButton>button p{color:#111 !important;font-weight:800}
.stButton>button:disabled{background:#3b3524;color:#d9c98a !important;opacity:1;cursor:not-allowed}
.stButton>button:disabled p{color:#d9c98a !important}
[data-testid="stSelectbox"] div[data-baseweb="select"]>div{background:#f4f4f2;color:#111}
.card{background:#151821;border:1px solid #232734;border-radius:14px;padding:18px 20px;margin:14px 0}
.card h3{color:#f5c542;font-size:1.02rem;margin:0 0 10px 0;font-weight:700}
.sub{color:#9aa3b2;font-size:.8rem;line-height:1.45;margin:4px 0 10px 0}
.ttl{color:#f5c542;font-size:1.7rem;font-weight:800;margin:0}
.t{width:100%;border-collapse:collapse;font-size:.8rem}
.t th{color:#8b93a3;font-size:.68rem;text-transform:uppercase;text-align:right;padding:8px 6px;border-bottom:1px solid #232734;white-space:nowrap}
.t td{padding:9px 6px;text-align:right;border-bottom:1px solid #1d212c;color:#e5e7eb;white-space:nowrap}
.t th.l,.t td.l{text-align:left}
.t td.w{white-space:normal;min-width:210px;max-width:280px;line-height:1.35;color:#b8c0cc;text-align:left}
.t td.c,.t th.c{text-align:center}
.t tbody tr:hover td{background:#1a1e2a}
.pill{display:inline-block;padding:3px 12px;border-radius:999px;font-size:.72rem;font-weight:700}
.pill.bull{background:#0f3d2a;color:#4ade80}.pill.bear{background:#4a1519;color:#f87171}
.pos{color:#22c55e}.neg{color:#ef4444}
.badge{padding:2px 9px;border-radius:6px;font-size:.7rem;font-weight:700}
.badge.call{background:#0f3d2a;color:#4ade80}.badge.put{background:#4a1519;color:#f87171}
.bar{display:flex;height:24px;border-radius:5px;overflow:hidden;flex:1}
.barrow{display:flex;align-items:center;gap:14px}
.bar .g{background:#22c55e}.bar .r{background:#ef4444}
.barlbl{font-size:.85rem;font-weight:600;white-space:nowrap}
.hl{background:#1b2a4a;border-radius:6px;padding:8px 10px;color:#dbe7ff;font-size:.85rem}
</style>"""
st.markdown(CSS, unsafe_allow_html=True)


# ───────────────────────── helpers ─────────────────────────
def n0(x):
    return f"{x:,.0f}"


def n2(x):
    return f"{x:,.2f}"


def sgn(x, d=0, suffix=""):
    cls = "pos" if x > 0 else "neg" if x < 0 else ""
    return f'<span class="{cls}">{x:,.{d}f}{suffix}</span>'


def badge(t):
    return f'<span class="badge {t.lower()}">{t}</span>'


def table(headers, rows, left=(), wrap=(), center=()):
    def cls(i, tag):
        c = []
        if i in left or i in wrap:
            c.append("l")
        if i in wrap and tag == "td":
            c.append("w")
        if i in center:
            c.append("c")
        return " ".join(c)

    th = "".join(f'<th class="{cls(i, "th")}">{h}</th>' for i, h in enumerate(headers))
    body = "".join(
        "<tr>" + "".join(f'<td class="{cls(i, "td")}">{c}</td>' for i, c in enumerate(r)) + "</tr>" for r in rows
    )
    return f'<div style="overflow-x:auto"><table class="t"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def card(title, inner):
    st.markdown(f'<div class="card"><h3>{title}</h3>{inner}</div>', unsafe_allow_html=True)


def bar(left_pct, left_txt, right_txt):
    return (
        f'<div class="barrow"><div class="bar"><div class="g" style="width:{left_pct:.1f}%"></div>'
        f'<div class="r" style="width:{100-left_pct:.1f}%"></div></div>'
        f'<div class="barlbl"><span class="pos">{left_txt}</span> / <span class="neg">{right_txt}</span></div></div>'
    )


# ───────────────────────── data loading ─────────────────────────
SPURT_COLS = ["Symbol", "Instrument", "Expiry", "Strike", "OptType", "OI", "OIPrev", "ChngOI",
              "PctChngOI", "LTP", "PrevClose", "PctChngLTP", "Volume", "Value", "Underlying"]
BUCKETS = {
    (True, True): "OI Rise + Price Rise",
    (True, False): "OI Rise + Price Slide",
    (False, True): "OI Slide + Price Rise",
    (False, False): "OI Slide + Price Slide",
}
SIGNAL = {  # bucket -> (raw signal, text)
    "OI Rise + Price Rise": ("Long Buildup", "Fresh buying — buyers ADDED positions (aggressive longs entering)"),
    "OI Rise + Price Slide": ("Short Buildup", "Fresh writing — sellers ADDED positions (aggressive shorts/writers entering)"),
    "OI Slide + Price Rise": ("Short Covering", "Sellers EXITED — short covering, shorts buying back to close"),
    "OI Slide + Price Slide": ("Long Unwinding", "Buyers EXITED — long unwinding, longs selling to close"),
}
# underlying bias (+1 bullish / -1 bearish) by (option type, raw signal)
BIAS = {
    ("Call", "Long Buildup"): 1, ("Call", "Short Buildup"): -1, ("Call", "Short Covering"): 1, ("Call", "Long Unwinding"): -1,
    ("Put", "Long Buildup"): -1, ("Put", "Short Buildup"): 1, ("Put", "Short Covering"): -1, ("Put", "Long Unwinding"): 1,
}


def _bucket_from_name(name):
    n = name.lower().replace("_", "-")
    for (oi_up, px_up), label in BUCKETS.items():
        key = f"{'rise' if oi_up else 'slide'}-in-oi-and-{'rise' if px_up else 'slide'}-in-price"
        if key in n:
            return label
    return None


@st.cache_data(show_spinner=False)
def parse_file(name: str, content: bytes):
    """Returns ('spurt', date, df) | ('bhav', date, df) | (None, None, msg)."""
    import io
    head = content[:600].decode("utf-8-sig", errors="ignore")
    try:
        if "TckrSymb" in head:
            use = ["TradDt", "FinInstrmTp", "TckrSymb", "XpryDt", "StrkPric", "OptnTp", "OpnPric", "HghPric", "LwPric",
                   "ClsPric", "PrvsClsgPric", "UndrlygPric", "OpnIntrst", "ChngInOpnIntrst", "TtlTradgVol", "NewBrdLotQty"]
            df = pd.read_csv(io.BytesIO(content), usecols=use)
            df = df[df["FinInstrmTp"].isin(["IDO", "STO"])].copy()
            df["XpryDt"] = pd.to_datetime(df["XpryDt"]).dt.date
            d = pd.to_datetime(df["TradDt"].iloc[0]).date()
            df = df.rename(columns={"TckrSymb": "Symbol", "StrkPric": "Strike", "OpnPric": "Open", "ClsPric": "Close",
                                    "PrvsClsgPric": "Prev", "UndrlygPric": "Spot", "OpnIntrst": "OI",
                                    "ChngInOpnIntrst": "ChngOI", "TtlTradgVol": "Vol", "NewBrdLotQty": "Lot",
                                    "XpryDt": "Expiry"})
            df["Type"] = df["OptnTp"].map({"CE": "Call", "PE": "Put"})
            return "bhav", d, df.drop(columns=["TradDt", "OptnTp"])
        if "Symbol" in head and "Instrument" in head:
            df = pd.read_csv(io.BytesIO(content), header=0, skiprows=0, encoding="utf-8-sig")
            df.columns = SPURT_COLS
            df = df[df["Instrument"].isin(["Index Options", "Stock Options"])].copy()
            df["Expiry"] = pd.to_datetime(df["Expiry"], format="%d-%b-%Y").dt.date
            df["Type"] = df["OptType"].map({"Call": "Call", "Put": "Put", "CE": "Call", "PE": "Put"})
            bk = _bucket_from_name(name)
            df["Bucket"] = bk if bk else [BUCKETS[(a > 0, b > 0)] for a, b in zip(df["ChngOI"], df["PctChngLTP"])]
            m = re.search(r"(\d{2})(\d{2})(\d{4})\.csv$", name, re.I)
            if not m:
                return None, None, f"{name}: can't read date (expected …DDMMYYYY.csv)"
            d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            return "spurt", d, df
    except Exception as e:  # noqa
        return None, None, f"{name}: {e}"
    return None, None, f"{name}: unrecognised file"


def collect_files(uploads):
    files = []
    if DATA_DIR.exists():
        files += [(p.name, p.read_bytes()) for p in sorted(DATA_DIR.glob("*.csv"))]
    files += [(u.name, u.getvalue()) for u in (uploads or [])]
    spurts, bhavs, errs, seen = {}, {}, [], set()
    for name, content in files:
        h = hashlib.md5(content).hexdigest()
        if h in seen:
            continue
        seen.add(h)
        kind, d, obj = parse_file(name, content)
        if kind == "spurt":
            spurts.setdefault(d, []).append(obj)
        elif kind == "bhav":
            bhavs[d] = obj
        else:
            errs.append(obj)
    spurts = {d: pd.concat(v, ignore_index=True) for d, v in spurts.items()}
    return spurts, bhavs, errs


# ───────────────────────── Black-Scholes (constant IV) ─────────────────────────
def _N(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _phi(x):
    return math.exp(-x * x / 2) / math.sqrt(2 * math.pi)


def bs_price(S, K, T, s, cp):
    if T <= 0 or s <= 0:
        return max(S - K, 0) if cp == "Call" else max(K - S, 0)
    d1 = (math.log(S / K) + (RISK_FREE + s * s / 2) * T) / (s * math.sqrt(T))
    d2 = d1 - s * math.sqrt(T)
    df = math.exp(-RISK_FREE * T)
    return S * _N(d1) - K * df * _N(d2) if cp == "Call" else K * df * _N(-d2) - S * _N(-d1)


def implied_vol(price, S, K, T, cp):
    if T <= 0 or price <= 0:
        return None
    lo, hi = 0.005, 4.0
    if price < bs_price(S, K, T, lo, cp) or price > bs_price(S, K, T, hi, cp):
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if bs_price(S, K, T, mid, cp) < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def greeks(S, K, T, s, cp):
    d1 = (math.log(S / K) + (RISK_FREE + s * s / 2) * T) / (s * math.sqrt(T))
    delta = _N(d1) if cp == "Call" else _N(d1) - 1
    gamma = _phi(d1) / (S * s * math.sqrt(T))
    vega = S * _phi(d1) * math.sqrt(T) / 100
    theta = bs_price(S, K, max(T - 1 / 365, 1e-6), s, cp) - bs_price(S, K, T, s, cp)
    return delta, gamma, theta, vega


# ───────────────────────── UI: inputs ─────────────────────────
st.markdown('<p class="ttl" style="font-size:1.5rem">NSE F&amp;O — OI Spurts Analyser</p>', unsafe_allow_html=True)
st.markdown('<p class="sub">Based on the day\'s 4 "Spurts in OI" bucket files, plus the full BhavCopy when available</p>',
            unsafe_allow_html=True)

with st.sidebar:
    uploads = []
    for title, label in [
        ("Spurts in OI — Rise in OI &amp; Rise in Price", "Upload Rise OI + Rise Price CSV"),
        ("Spurts in OI — Rise in OI &amp; Slide in Price", "Upload Rise OI + Slide Price CSV"),
        ("Spurts in OI — Slide in OI &amp; Rise in Price", "Upload Slide OI + Rise Price CSV"),
        ("Spurts in OI — Slide in OI &amp; Slide in Price", "Upload Slide OI + Slide Price CSV"),
        ("BhavCopy (Full F&amp;O)", "Upload F&amp;O BhavCopy CSV"),
    ]:
        st.markdown(f"**{title}**", unsafe_allow_html=True)
        f = st.file_uploader(label.replace("&amp;", "&"), type="csv", key=label)
        if f:
            uploads.append(f)
        st.divider()

spurts, bhavs, errs = collect_files(uploads)
for e in errs:
    st.warning(e)
if not spurts and not bhavs:
    st.info("Upload the 4 Spurts-in-OI CSVs and the BhavCopy CSV to begin.")
    st.stop()

if "run" not in st.session_state:
    st.session_state.run = None

if st.session_state.run is None:
    dates = sorted(spurts, reverse=True)
    if not dates:
        st.error("No Spurts files found — upload the 4 Spurts-in-OI CSVs.")
        st.stop()
    rdate = st.selectbox("Report date (files available)", dates, format_func=lambda d: d.strftime("%d-%m-%Y"))
    sp = spurts[rdate]
    bh_date = max([d for d in bhavs if d <= rdate], default=max(bhavs, default=None))
    syms = set(sp["Symbol"])
    if bh_date:
        syms |= set(bhavs[bh_date]["Symbol"])
    syms = sorted(syms, key=lambda s: (s not in INDEX_SYMS, s))
    sym = st.selectbox("Symbol", syms, index=None, placeholder="e.g. NIFTY, RELIANCE, TCS")
    st.caption("If symbol is NIFTY / BANKNIFTY / FINNIFTY etc. — Index Options is used automatically, otherwise Stock Options.")
    exps = set()
    if sym:
        exps |= set(sp.loc[sp["Symbol"] == sym, "Expiry"])
        if bh_date:
            b = bhavs[bh_date]
            exps |= set(b.loc[b["Symbol"] == sym, "Expiry"])
    exp = st.selectbox("Expiry date", sorted(exps), index=None, placeholder="Pick a symbol first",
                       format_func=lambda d: d.strftime("%d-%m-%Y"), disabled=not sym)
    if st.button("Generate Report", type="primary", use_container_width=True, disabled=not (sym and exp)):
        st.session_state.run = (rdate, sym, exp)
        st.rerun()
    st.caption("Educational / informational tool only. Built from NSE's published OI-spurt buckets and, where provided, "
               "the full daily BhavCopy — not investment advice.")
    st.stop()

# ───────────────────────── report ─────────────────────────
rdate, sym, exp = st.session_state.run
if st.button("← back"):
    st.session_state.run = None
    st.rerun()

kind = "Index Options" if sym in INDEX_SYMS else "Stock Options"
sp_all = spurts.get(rdate, pd.DataFrame(columns=SPURT_COLS + ["Type", "Bucket"]))
sp = sp_all[(sp_all["Symbol"] == sym) & (sp_all["Instrument"] == kind) & (sp_all["Expiry"] == exp)].copy()

bh_date = max([d for d in bhavs if d <= rdate], default=max(bhavs, default=None))
chain = pd.DataFrame()
if bh_date:
    b = bhavs[bh_date]
    chain = b[(b["Symbol"] == sym) & (b["Expiry"] == exp)].copy()
    chain["Prev OI"] = chain["OI"] - chain["ChngOI"]

spot = sp["Underlying"].iloc[0] if len(sp) else (chain["Spot"].iloc[0] if len(chain) else float("nan"))
st.markdown(f'<p class="ttl">{sym} · {kind}</p>', unsafe_allow_html=True)
st.markdown(f'<p class="sub">Expiry: {exp.strftime("%d-%b-%Y")} · Underlying Value: {spot:,.2f} · '
            f'Report date: {rdate.strftime("%d%m%Y")}</p>', unsafe_allow_html=True)

# ── Spurts-based sections ──
if sp.empty:
    st.info("No spurt rows for this symbol/expiry on the selected date — showing BhavCopy sections only.")
else:
    sp["Raw"] = sp["Bucket"].map(lambda x: SIGNAL[x][0])
    sp["Read"] = sp["Bucket"].map(lambda x: SIGNAL[x][1])
    sp["Bias"] = [BIAS[(t, r)] for t, r in zip(sp["Type"], sp["Raw"])]

    # 1. directional bias
    tot = sp["Value"].sum()
    bull = sp.loc[sp["Bias"] > 0, "Value"].sum() / tot * 100 if tot else 50
    card("Next-day directional bias (heuristic, from today's OI spurts only)",
         bar(bull, f"{bull:.1f}% Bullish", f"{100-bull:.1f}% Bearish")
         + '<p class="sub">Derived by weighting each strike\'s OI-buildup/unwind signal (Call vs Put, Long vs Short) by its '
           'turnover (Value) share within today\'s spurt rows for this symbol/expiry. This is a heuristic tilt indicator, '
           'not a statistical probability or a trade recommendation.</p>')

    # 2. call vs put
    c, p = sp[sp["Type"] == "Call"], sp[sp["Type"] == "Put"]
    cd, pd_ = c["ChngOI"].sum(), p["ChngOI"].sum()
    pcr = (pd_ / cd) if cd else float("nan")
    inner = table(["", "Call", "Put"],
                  [["Net Chng in OI", sgn(cd), sgn(pd_)],
                   ["Turnover (Value, ₹ lakh)", n2(c["Value"].sum()), n2(p["Value"].sum())]], left=(0,))
    inner += f'<p class="sub">PCR of OI-change (Put Δ / Call Δ) among spurt rows: {pcr:.2f}</p>'
    card("Call vs Put OI change &amp; turnover (within spurt rows)", inner)

    # 3. top by volume / value
    top = sp.sort_values("Volume", ascending=False).head(5)
    card("Top strikes by Volume", table(
        ["Strike", "Type", "Bucket", "OI (Cur)", "OI (Prev)", "Chng OI", "LTP", "%Chng LTP", "Volume", "Value"],
        [[n0(r.Strike), badge(r.Type), r.Bucket, n0(r.OI), n0(r.OIPrev), sgn(r.ChngOI), n2(r.LTP).rstrip("0").rstrip("."),
          sgn(r.PctChngLTP, 2, "%"), n0(r.Volume), n2(r.Value)] for r in top.itertuples()], left=(2,)))
    topv = sp.sort_values("Value", ascending=False).head(5)
    card("Top strikes by Value (₹ turnover)", table(
        ["Strike", "Type", "Bucket", "Value", "Volume", "Chng OI", "%Chng LTP"],
        [[n0(r.Strike), badge(r.Type), r.Bucket, n2(r.Value), n0(r.Volume), sgn(r.ChngOI), sgn(r.PctChngLTP, 2, "%")]
         for r in topv.itertuples()], left=(2,)))

    # 4. highest OI
    mx = sp.loc[sp["OI"].idxmax()]
    zone = "resistance zone" if mx["Type"] == "Call" else "support zone"
    card("Highest absolute Open Interest strike in today's spurt rows",
         f'<div class="hl">Strike <b>{mx["Strike"]:,.0f} {mx["Type"]}</b> currently carries the largest OI ({mx["OI"]:,.0f}) '
         f'among the rows that showed a spurt today. Heavy Call OI at a strike is traditionally read as a resistance zone; '
         f'heavy Put OI as a support zone — here it reads as a <b>{zone}</b>, but since this data is only the "spurt" subset, '
         f'treat this as a partial view, not the full chain\'s max-OI support/resistance map.</div>')

    # 5. full interpretation
    full = sp.sort_values("Value", ascending=False)
    card("Full strike-level interpretation (Open Interest &amp; buyer/seller read)", table(
        ["Strike", "Type", "Bucket", "Chng OI", "%Chng OI", "Raw signal", "Underlying bias", "Buyer / Seller read"],
        [[n0(r.Strike), badge(r.Type), r.Bucket, sgn(r.ChngOI), sgn(r.PctChngOI, 2, "%"), r.Raw,
          f'<span class="pill {"bull" if r.Bias > 0 else "bear"}">{"Bullish" if r.Bias > 0 else "Bearish"}</span>', r.Read]
         for r in full.itertuples()], left=(2, 5), wrap=(7,), center=(6,)))

# ── BhavCopy-based sections ──
if chain.empty:
    st.info("No BhavCopy data for this symbol/expiry (upload the BhavCopy CSV to unlock the full-chain sections).")
    st.stop()

note = "" if bh_date == rdate else " (this may be a different date than the Spurts report above)"
n_strikes = len(chain)

# 6. heavy sellers added
hs = chain[(chain["ChngOI"] > 0) & (chain["Close"] < chain["Prev"]) & (chain["Vol"] > 0)].sort_values("ChngOI", ascending=False).head(10)
rows = []
for r in hs.to_dict("records"):
    pct_oi = r["ChngOI"] / r["Prev OI"] * 100 if r["Prev OI"] else float("nan")
    pct_px = (r["Close"] / r["Prev"] - 1) * 100 if r["Prev"] else float("nan")
    prem = r["Vol"] * r["Lot"] * r["Close"] / 1e5
    rows.append([n0(r["Strike"]), badge(r["Type"]), n0(r["OI"]), n0(r["Prev OI"]), sgn(r["ChngOI"]),
                 sgn(pct_oi, 2, "%"), sgn(pct_px, 2, "%"), n2(prem)])
card("BhavCopy (full chain) — Heavy Sellers Added vs Previous Day",
     f'<p class="sub">Using latest available BhavCopy: {bh_date.strftime("%d-%m-%Y")}{note}</p>'
     f'<p class="sub">From the full NSE BhavCopy ({n_strikes} contracts for this symbol/expiry, not just the spurt subset). '
     f'Previous day\'s OI is derived as today\'s OI minus today\'s change-in-OI. Rows below show OI ADDED while price fell vs '
     f'previous close — i.e. fresh writing/selling — ranked by OI added.</p>'
     + (table(["Strike", "Type", "OI (Cur)", "OI (Prev)", "Chng OI", "%Chng OI", "%Chng LTP", "Premium Value (₹ lakh)"], rows)
        if rows else '<p class="sub">No strikes with OI added and price down.</p>'))

# 7. seller power
w = chain[(chain["ChngOI"] > 0) & (chain["Open"] > 0) & (chain["Close"] < chain["Open"]) & (chain["Vol"] > 0)].copy()
w["Power"] = w["ChngOI"] * w["Close"]
ce_p, pe_p = w.loc[w["Type"] == "Call", "Power"].sum(), w.loc[w["Type"] == "Put", "Power"].sum()
if ce_p + pe_p > 0:
    ce_pct = ce_p / (ce_p + pe_p) * 100
    if pe_p >= ce_p:
        dom = "PE (Put) — Put writers dominant — support building, bullish tilt on the underlying"
    else:
        dom = "CE (Call) — Call writers dominant — resistance building, bearish tilt on the underlying"
    tops = w.sort_values("Power", ascending=False).head(8)
    inner = (f'<p class="sub">A strike is counted as "writing" when OI was added AND the option\'s price fell from its own Open '
             f'price today. Seller power = OI added × close price, summed by side — a relative ranking score, not a cash figure.</p>'
             + bar(100 - ce_pct, f"{100-ce_pct:.1f}% PE writing", f"{ce_pct:.1f}% CE writing")
             + f'<p style="margin:10px 0 4px"><b>Dominant side:</b> <span class="sub">{dom}</span></p>'
             + table(["", "Call (CE)", "Put (PE)"], [["Seller Power (relative ranking score)", n2(ce_p), n2(pe_p)]], left=(0,))
             + '<p style="color:#f5c542;font-weight:700;margin:14px 0 4px;font-size:.85rem">Top strikes by writing/seller power</p>'
             + table(["Strike", "Type", "Open", "Close", "Chng OI", "Seller Power"],
                     [[n0(r.Strike), badge(r.Type), n2(r.Open), n2(r.Close), sgn(r.ChngOI), n2(r.Power)] for r in tops.itertuples()]))
    # put-writers = bullish => show PE share on the green (left) side
else:
    inner = '<p class="sub">No writing detected (no strike with OI added and price below its Open).</p>'
card("Option Strike Seller Power — CE vs PE (from today's Open price)", inner)

# 8. Greeks-based buy/sell levels
S0 = float(chain["Spot"].iloc[0])
T0 = (exp - bh_date).days / 365
strikes = sorted(set(chain.loc[chain["Type"] == "Call", "Strike"]) & set(chain.loc[chain["Type"] == "Put", "Strike"]))
if strikes and T0 > 0 and S0 > 0:
    K = min(strikes, key=lambda k: abs(k - S0))
    ce = chain[(chain["Type"] == "Call") & (chain["Strike"] == K)].iloc[0]
    pe = chain[(chain["Type"] == "Put") & (chain["Strike"] == K)].iloc[0]
    ivs = {"Call": implied_vol(ce["Close"], S0, K, T0, "Call"), "Put": implied_vol(pe["Close"], S0, K, T0, "Put")}
    cc, pp = chain[chain["Type"] == "Call"], chain[chain["Type"] == "Put"]
    res_pool, sup_pool = cc[cc["Strike"] >= S0], pp[pp["Strike"] <= S0]
    if all(ivs.values()) and len(res_pool) and len(sup_pool):
        res = float(res_pool.loc[res_pool["OI"].idxmax(), "Strike"])
        sup = float(sup_pool.loc[sup_pool["OI"].idxmax(), "Strike"])
        T1 = max(T0 - 1 / 365, 1e-6)

        def proj(cp, level):
            return max(bs_price(level, K, T1, ivs[cp], cp), 0.05)

        gk = {cp: greeks(S0, K, T0, ivs[cp], cp) for cp in ("Call", "Put")}
        pc, pq = float(ce["Close"]), float(pe["Close"])
        atm_rows = []
        for lbl, cp, px in (("CE (ATM)", "Call", pc), ("PE (ATM)", "Put", pq)):
            d, g, t, v = gk[cp]
            atm_rows.append([f'<span class="badge {cp.lower()}">{lbl}</span>', n0(K), n2(px), f"{ivs[cp]*100:.1f}",
                             f"{d:.3f}", f"{g:.5f}", sgn(t, 2), f"{v:.2f}"])
        lv = lambda a, b, c: [a, b, n2(c[0]), f'<span class="neg">{n2(c[1])}</span>', f'<span class="pos">{n2(c[2])}</span>']  # noqa
        ce_s, ce_r, pe_s, pe_r = proj("Call", sup), proj("Call", res), proj("Put", sup), proj("Put", res)
        # (entry, stoploss, target)
        levels = [
            ("Buy CE", "(breakout play)", (pc, ce_s, ce_r)),
            ("Buy PE", "(breakdown play)", (pq, pe_r, pe_s)),
            ("Sell CE", "(resistance-holds play)", (pc, ce_r, ce_s)),
            ("Sell PE", "(support-holds play)", (pq, pe_s, pe_r)),
        ]
        lvl_rows = []
        for nm, desc, (en, sl, tg) in levels:
            cls = "call" if "CE" in nm and "Buy" in nm or "PE" in nm and "Sell" in nm else "put"
            lvl_rows.append([f'<span class="badge {cls}">{nm}</span> {desc}', n2(en),
                             f'<span class="neg">{n2(sl)}</span>', f'<span class="pos">{n2(tg)}</span>'])
        card("CE / PE Buy &amp; Sell Levels with SL &amp; Target (Greeks-based estimate)",
             f'<p class="sub">A simplified, constant-IV model: implied volatility is solved once from each ATM strike\'s '
             f'previous-session close ({(exp-bh_date).days} days to expiry), then Delta/Gamma/Theta/Vega are computed from that IV '
             f'and used to project the option\'s price at the support and resistance underlying levels below, including one day of '
             f'theta decay forward. Heuristic only — actual IV can shift (vega risk) and change these estimates materially.</p>'
             f'<p class="sub">Spot (BhavCopy): <b>{S0:,.2f}</b> · Support (max Put OI ≤ spot): <b>{sup:,.0f}</b> · '
             f'Resistance (max Call OI ≥ spot): <b>{res:,.0f}</b></p>'
             + table(["", "Strike", "Price", "IV%", "Delta", "Gamma", "Theta/Day", "Vega"], atm_rows, left=(0,))
             + '<p style="color:#f5c542;font-weight:700;margin:14px 0 4px">Buy / Sell levels</p>'
             + table(["Strategy", "Entry", "Stoploss", "Target"], lvl_rows, left=(0,))
             + '<p class="sub">"Sell" rows are option-writing strategies (undefined/margin-heavy risk if the SL side isn\'t '
               'respected) — shown for informational/educational comparison only, not a recommendation to write uncovered options.</p>')
    else:
        card("CE / PE Buy &amp; Sell Levels with SL &amp; Target (Greeks-based estimate)",
             '<p class="sub">Could not solve implied volatility / find OI levels for the ATM strike (illiquid or stale close).</p>')
