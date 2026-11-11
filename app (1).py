import re
import time
from urllib.parse import quote

import numpy as np
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(page_title="PChome 商品價格分析", page_icon="🛒", layout="wide")

API = "https://ecshweb.pchome.com.tw/search/v3.3/all/results?q={q}&page={page}&sort={sort}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
SORT_OPTIONS = {
    "銷量高到低": "sale/dc",
    "價格低到高": "prc/ac",
    "價格高到低": "prc/dc",
    "相關度": "rnk/dc",
}


# ---------- 爬蟲（CODE01）----------
def fetch_page(keyword: str, page: int, sort: str) -> dict:
    url = API.format(q=quote(keyword), page=page, sort=sort)
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


@st.cache_data(show_spinner=False, ttl=600)
def crawl(keyword: str, pages: int, sort: str, delay: float):
    frames, total_page = [], None
    progress = st.progress(0.0, text="開始爬取…")
    for i in range(1, pages + 1):
        data = fetch_page(keyword, i, sort)
        total_page = data.get("totalPage", total_page)
        prods = data.get("prods") or []
        if not prods:
            break
        frames.append(pd.DataFrame(prods))
        progress.progress(i / pages, text=f"已爬取第 {i}/{pages} 頁")
        if total_page and i >= total_page:
            break
        if i < pages:
            time.sleep(delay)  # 避免請求過快
    progress.empty()
    if not frames:
        return pd.DataFrame(), total_page
    return pd.concat(frames, ignore_index=True), total_page


# ---------- 資料處理（CODE02）----------
def extract_brand(name: str) -> str:
    m = re.search(r"[【\[](.+?)[】\]]", name)
    if m:
        return m.group(1).strip()[:12]
    return (name.split() or ["未知"])[0][:8]


def add_price_band(df: pd.DataFrame, bins: int = 5) -> pd.DataFrame:
    lo, hi = df["price"].min(), df["price"].max()
    edges = np.unique(np.linspace(lo, hi, bins + 1).round().astype(int))
    if len(edges) < 2:
        df["價格區間"] = f"{int(lo)}"
        return df
    edges[-1] = max(edges[-1], hi)
    labels = [f"{edges[i]}–{edges[i + 1]}" for i in range(len(edges) - 1)]
    df["價格區間"] = pd.cut(df["price"], bins=edges, labels=labels, include_lowest=True).astype(str)
    return df


# ---------- 介面 ----------
st.title("🛒 PChome 商品價格爬取與視覺化")

with st.sidebar:
    st.header("搜尋設定")
    keyword = st.text_input("產品名稱", value="行動電源")
    pages = st.number_input("爬取頁數", min_value=1, max_value=50, value=3, step=1)
    sort_label = st.selectbox("排序方式", list(SORT_OPTIONS.keys()))
    delay = st.slider("每頁間隔秒數", 0.0, 10.0, 1.0, 0.5)
    run = st.button("開始爬取", type="primary", use_container_width=True)

if run:
    if not keyword.strip():
        st.warning("請輸入產品名稱")
        st.stop()
    try:
        raw, total_page = crawl(keyword.strip(), int(pages), SORT_OPTIONS[sort_label], delay)
    except requests.RequestException as e:
        st.error(f"請求失敗：{e}")
        st.stop()
    except ValueError:
        st.error("回傳內容不是有效的 JSON，可能被網站阻擋或 API 已變更。")
        st.stop()

    if raw.empty:
        st.warning("查無資料，請換個關鍵字試試。")
        st.stop()

    df = raw[[c for c in ["name", "price"] if c in raw.columns]].copy()
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df = df.dropna(subset=["price"]).reset_index(drop=True)
    df["品牌"] = df["name"].map(extract_brand)
    df = add_price_band(df)
    st.session_state["df"] = df
    st.session_state["keyword"] = keyword.strip()
    st.session_state["total_page"] = total_page

if "df" not in st.session_state:
    st.info("請在左側輸入產品名稱與頁數，然後按「開始爬取」。")
    st.stop()

df = st.session_state["df"]
kw = st.session_state["keyword"]
mean_price = df["price"].mean()

st.subheader(f"「{kw}」共 {len(df)} 筆商品")
c1, c2, c3, c4 = st.columns(4)
c1.metric("平均價格", f"{mean_price:,.0f}")
c2.metric("最高價格", f"{df['price'].max():,.0f}")
c3.metric("最低價格", f"{df['price'].min():,.0f}")
c4.metric("網站總頁數", st.session_state.get("total_page") or "—")

tab_line, tab_pie, tab_sun, tab_data = st.tabs(["📈 折線圖", "🥧 圓餅圖", "☀️ 旭日圖", "📄 資料"])

with tab_line:
    show_n = st.slider("顯示前幾筆商品", 10, max(len(df), 11), min(70, len(df)))
    sub = df.head(show_n).copy()
    sub["序號"] = range(1, len(sub) + 1)
    fig = px.line(sub, x="序號", y="price", markers=True, hover_name="name",
                  labels={"序號": "商品序號", "price": "價格"},
                  title=f"PChome 電商網站上「{kw}」價格")
    fig.add_hline(y=mean_price, line_dash="dash", line_color="red",
                  annotation_text=f"平均 {mean_price:,.0f}")
    st.plotly_chart(fig, use_container_width=True)

with tab_pie:
    counts = df["價格區間"].value_counts().reset_index()
    counts.columns = ["價格區間", "商品數"]
    fig = px.pie(counts, names="價格區間", values="商品數", hole=0.3,
                 title="價格區間商品數占比")
    fig.update_traces(textinfo="percent+label")
    st.plotly_chart(fig, use_container_width=True)

with tab_sun:
    top_brands = df["品牌"].value_counts().head(10).index
    sdf = df.copy()
    sdf["品牌"] = sdf["品牌"].where(sdf["品牌"].isin(top_brands), "其他")
    grouped = sdf.groupby(["價格區間", "品牌"]).size().reset_index(name="商品數")
    fig = px.sunburst(grouped, path=["價格區間", "品牌"], values="商品數",
                      title="價格區間 → 品牌 分布（品牌取前 10，其餘歸為「其他」）")
    st.plotly_chart(fig, use_container_width=True)

with tab_data:
    st.dataframe(df, use_container_width=True)
    st.download_button(
        "下載 CSV",
        df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
        file_name=f"PCHOME_{kw}.csv",
        mime="text/csv",
    )
