import altair as alt
import math
import streamlit as st
# from streamlit_autorefresh import st_autorefresh
from supabase import create_client, Client
import time
import pandas as pd
from pytz import timezone
import uuid
# from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timezone as dt_timezone, timedelta
import base64, os


st.set_page_config(
    page_title="輝晶核家計簿", 
    page_icon="https://ドラクエ10.jp/pic5/kisyou3.jpg",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    footer {visibility: hidden;}
    .viewerBadge_container__1QSob {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

class SupabaseDB:
    def __init__(self):
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        self.client: Client = create_client(url, key)
    def add_record(self, record):
        """取引記録を追加"""
        try:
            self.client.table("records").insert(record).execute()
            return True
        except Exception as e:
            print(f"レコード追加失敗: {e}")
            return False
    def create_user(self, username: str):
        # ユーザを作成する
        data = {
                "username": username,
                }
        response = self.client.table("users").insert(data).execute()
        return response
    def get_user(self):
        # ユーザ情報を取得する
        response = self.client.table("users").select("*").order("last_activity", desc=True).execute()
        return pd.DataFrame(response.data)
    def get_records_by_user(self, username: str):
        # ユーザに関連するレコードを取得する
        response = self.client.table("records") \
            .select("*") \
            .eq("username", username) \
            .order("date", desc=False) \
            .execute()
        return pd.DataFrame(response.data)
    def update_record(self, record_id: str, new_values: dict):
        response = self.client.table("records") \
            .update(new_values) \
            .eq("id", record_id) \
            .execute()
        return response
    def delete_record(self, record_id: str):
        response = self.client.table("records") \
            .delete() \
            .eq("id", record_id) \
            .execute()
        return response
    def update_user_last_activity(self, username: str):
        """ユーザーの最終更新時刻を更新"""
        try:
            now = datetime.now(timezone("Asia/Tokyo")).isoformat()
            self.client.table("users").update({"last_activity": now}).eq("username", username).execute()
        except Exception as e:
            print(f"last_activity更新失敗: {e}")
    def get_latest_price(self, item_name: str) -> float | None:
        """
        latest_prices から item_id の最新 p5_price を Gold 単位で返す（なければ None）
        """
        try:
            res = self.client.table("mrt_price_hourly") \
                .select("p5_price") \
                .eq("item_id", item_name) \
                .single() \
                .execute()
            if res.data and "p5_price" in res.data:
                return float(res.data["p5_price"])
        except Exception as e:
            print(f"最新価格取得失敗({item_name}): {e}")
        return None

def calculate_profit(frag_45, frag_75, core, wipes, meal_cost, meal_num, cost, price):
    commission = 0.05
    profit = price * (frag_45 * 45/99 + frag_75 * 75/99 + core) * (1 - commission)
    profit -= cost * 30 * (frag_45 + frag_75 + core + wipes) / 4
    profit -= meal_cost * (meal_num / 5)
    return int(profit * 10000)

def reset_count():
    """_reset_counts=Trueなら次のランで実際に初期化してからフラグを戻す"""
    for k, v in [("frag_45",0), ("frag_75",0), ("core",0), ("wipes",0)]:
        st.session_state[k] = v
    st.session_state._last_total = 0
    st.session_state._last_45 = 0
    st.session_state._last_75 = 0
    st.session_state._last_core = 0
    st.session_state._last_wipes = 0
    st.session_state.count_logs = []
    st.session_state._flash_msg = ("info", "カウントと履歴をクリアしました")

def record_count(now):
    """合計が増えたときだけログを追加（減った時は無視）"""
    cur = st.session_state.frag_45 + st.session_state.frag_75 + st.session_state.core + st.session_state.wipes
    prev = st.session_state._last_total
    prev_45 = st.session_state._last_45
    prev_75 = st.session_state._last_75
    prev_core = st.session_state._last_core
    prev_wipes = st.session_state._last_wipes
    if cur > prev:
        # prev_45, prev_75, prev_core, prev_wipesの内変化したものを更新
        if st.session_state.frag_45 != prev_45:
            st.session_state._last_45 = st.session_state.frag_45
            kind = "欠片45"
        if st.session_state.frag_75 != prev_75:
            st.session_state._last_75 = st.session_state.frag_75
            kind = "欠片75"
        if st.session_state.core != prev_core:
            st.session_state._last_core = st.session_state.core
            kind = "核"
        if st.session_state.wipes != prev_wipes:
            st.session_state._last_wipes = st.session_state.wipes
            kind = "全滅"
        st.session_state.count_logs.append({"ts": now, "合計": cur, "kind": kind})
        st.session_state._last_total = cur


def _lerp(a, b, t):
    return a + (b - a) * max(0.0, min(1.0, float(t)))

def _hex(r,g,b):
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"

def _mix(c1, c2, t):
    """#rrggbb 同士を t∈[0,1] でブレンド"""
    c1 = c1.lstrip("#"); c2 = c2.lstrip("#")
    r1,g1,b1 = int(c1[0:2],16), int(c1[2:4],16), int(c1[4:6],16)
    r2,g2,b2 = int(c2[0:2],16), int(c2[2:4],16), int(c2[4:6],16)
    return _hex(_lerp(r1,r2,t), _lerp(g1,g2,t), _lerp(b1,b2,t))

def _color_by_minutes(mins: float) -> str:
    """
    1分以下 → 濃い緑（かなりいい）
    2分以下 → 明るい緑（問題なし）
    3分以下 → アンバー（ちょい遅い）
    4分以下 → オレンジ（事故気味）
    5分以下 → 赤（かなり遅い）
    5分超   → 深赤（入力忘れ疑い）
    """
    m = max(0.0, float(mins))
    GREEN_GOOD_DARK = "#16a34a"  # green-600
    GREEN_OK_LIGHT  = "#4ade80"  # green-400
    AMBER           = "#f59e0b"  # amber-500
    ORANGE          = "#fb923c"  # orange-400
    RED             = "#ef4444"  # red-500
    DEEP_RED        = "#991b1b"  # red-900
    if m <= 1:
        t = m / 1.0
        return _mix(GREEN_GOOD_DARK, GREEN_OK_LIGHT, t*0.2)
    if m <= 2:
        t = (m - 1.0) / 1.0
        return _mix(GREEN_GOOD_DARK, GREEN_OK_LIGHT, t)
    if m <= 3:
        t = (m - 2.0) / 1.0
        return _mix(GREEN_OK_LIGHT, AMBER, t)
    if m <= 4:
        t = (m - 3.0) / 1.0
        return _mix(AMBER, ORANGE, t)
    if m <= 5:
        t = (m - 4.0) / 1.0
        return _mix(ORANGE, RED, t)
    # 5分超: 深赤（固定）
    return DEEP_RED



ICON_PATHS = {
    "欠片": "image/icons/kakera.png",
    "核":   "image/icons/kaku.png",
    "全滅": "image/icons/wipe.png",
}

_cache_data_uri = {}
def _img_to_data_uri(path: str) -> str | None:
    if not path or not os.path.exists(path):
        return None
    if path in _cache_data_uri:
        return _cache_data_uri[path]
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    uri = f"data:image/png;base64,{b64}"
    _cache_data_uri[path] = uri
    return uri

_BADGE_STYLE = {
    "欠片45": {"bg":"#22d3ee", "fg":"#0b1020", "label":"45"},
    "欠片75": {"bg":"#a78bfa", "fg":"#20102b", "label":"75"},
    "核":     {"bg":None,      "fg":None,      "label":None},
    "全滅":   {"bg":None,      "fg":None,      "label":None},
}

def _marker_svg(x: float, y: float, size: float, kind: str, title_text: str) -> str:
    """
    マーカーを描画するSVGを返す
    """
    base_kind = "欠片" if kind in ("欠片45", "欠片75") else kind
    img_uri = _img_to_data_uri(ICON_PATHS.get(base_kind, ""))
    # アイコン画像
    IMG_SCALE = 6
    w = h = size * IMG_SCALE
    x0 = x - w/2
    y0 = y - h/2
    plate = (
        f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" '
        f'rx="{size*0.45}" fill="#0b0f1a" fill-opacity="0.55" />'
    )
    if img_uri:
        image = f'<image href="{img_uri}" x="{x0}" y="{y0}" width="{w}" height="{h}" preserveAspectRatio="xMidYMid meet" />'
    else:
        image = f'<circle cx="{x}" cy="{y}" r="{size*1.1}" fill="#475569" />'
    bs = _BADGE_STYLE.get(kind, {})
    badge_svg = ""
    if bs.get("label"):
        badge_bg = bs["bg"]; badge_fg = bs["fg"]; label = bs["label"]

        # バッジサイズ
        r  = size * 1.5
        bh = r * 1.05
        bw = r * 2.15
        # 右下に配置
        bx = x0 + w - bw - r*0.25
        by = y0 + h - bh - r*0.20
        rx = bh / 2 # 楕円の縦半径

        stroke_w = max(1.0, size * 0.16)
        badge_shadow = (
            f'<rect x="{bx+1.2}" y="{by+1.2}" width="{bw}" height="{bh}" '
            f'rx="{rx}" fill="#000" fill-opacity="0.35"/>'
        )
        badge_body = (
            f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="{rx}" '
            f'fill="{badge_bg}" stroke="rgba(255,255,255,0.35)" stroke-width="{stroke_w}"/>'
        )
        tx = bx + bw/2
        ty = by + bh*0.70
        font_size = bh * 0.80
        text_outline = (
            f'<text x="{tx}" y="{ty}" text-anchor="middle" '
            f'font-size="{font_size}" font-weight="900" '
            f'stroke="#000" stroke-width="{max(0.8, stroke_w*0.9)}" '
            f'fill="none" paint-order="stroke fill" '
            f'font-family="system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial">{label}</text>'
        )
        text_fill = (
            f'<text x="{tx}" y="{ty}" text-anchor="middle" '
            f'font-size="{font_size}" font-weight="900" '
            f'fill="{badge_fg}" '
            f'font-family="system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial">{label}</text>'
        )
        badge_svg = badge_shadow + badge_body + text_outline + text_fill
    return f'<g><title>{title_text}</title>{plate}{image}{badge_svg}</g>'

def render_count_logs(logs, min_span_min=5, warn_minutes=5, title="⏱ カウント履歴"):
    if not logs or not isinstance(logs, list) or not all(isinstance(x, dict) and "ts" in x for x in logs):
        st.subheader(title)
        st.caption("まだカウント履歴はありません。")
        # ここで開始ボタンを表示（何もカウントがない時）
        if st.button("⏱ カウント開始", type="secondary"):
            now_jst = pd.Timestamp.now(tz="Asia/Tokyo")
            st.session_state.count_logs = [{"ts": now_jst, "kind": "start", "合計": 0}]
            st.success("カウントを開始しました")
            st.rerun()
        return
    df = pd.DataFrame(logs).copy()
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    df = df.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    if df.empty:
        st.subheader(title); st.caption("有効なタイムスタンプがありません。"); return
    t0 = df["ts"].iloc[0]
    tzinfo = df["ts"].dt.tz  # tzinfo または None（Series ではない）
    now = pd.Timestamp.now(tz=tzinfo) if tzinfo is not None else pd.Timestamp.now()
    df["min_from_start"] = (df["ts"] - t0).dt.total_seconds() / 60.0
    # 次の入力までの区間（最後は now まで）
    next_ts = list(df["ts"].iloc[1:]) + [now]
    df["delta_min"] = (pd.Series(next_ts, dtype="datetime64[ns, UTC]" if tzinfo is not None else "datetime64[ns]") - df["ts"]).dt.total_seconds() / 60.0
    df["delta_min"] = df["delta_min"].clip(lower=0)
    total_span = max(float(min_span_min), float(df["min_from_start"].iloc[-1] + df["delta_min"].iloc[-1]))
    # ---- SVG パラメータ ----
    W, H = 2000, 70
    PAD_L, PAD_R = 48, 12
    Y, BAR_H, MARK_R = H/2, 8, 5
    def sx(mins): return PAD_L + (W - PAD_L - PAD_R) * (mins / total_span)
    # 目盛り
    ticks = []
    for m in range(0, int(math.ceil(total_span)) + 1):
        x = sx(m)
        is_major = m % 5 == 0
        h = 12 if is_major else 6
        sw = 2 if is_major else 1.2
        col = "#f3f4f6" if is_major else "#6b7280"  # 明度を上げる
        # 目盛り線
        ticks.append(
            f'<line x1="{x}" y1="{Y+BAR_H+10}" x2="{x}" y2="{Y+BAR_H+10+h}" stroke="{col}" stroke-width="{sw}" />'
        )
        if is_major:
            ticks.append(
                f'<text x="{x}" y="{Y+BAR_H+35}" fill="#f9fafb" font-size="18" font-weight="700" text-anchor="middle">{m}</text>'
            )

    axis = "\n".join(ticks)
    axis_label = (
        f'<text x="{PAD_L-36}" y="{Y+BAR_H+35}" fill="#e5e7eb" font-size="17" font-weight="600">分</text>'
    )
    # 区間色
    segs = []
    for i in range(len(df)):
        x0 = sx(df["min_from_start"].iloc[i])
        x1 = sx(min(df["min_from_start"].iloc[i] + df["delta_min"].iloc[i], total_span))
        w = max(0.5, x1 - x0)
        col = _color_by_minutes(df["delta_min"].iloc[i])
        BAR_OPACITY = 0.45
        segs.append(
            f'<rect x="{x0}" y="{Y-BAR_H/2}" width="{w}" height="{BAR_H}" fill="{col}" fill-opacity="{BAR_OPACITY}" />'
        )
    # マーカー
    marks = []
    for i, r in df.iterrows():
        x = sx(r["min_from_start"]); y = Y
        info = f'{r["ts"].strftime("%H:%M:%S")}｜先頭から{r["min_from_start"]:.1f}分｜合計{int(r["合計"])}｜kind:{r.get("kind","-")}'
        marks.append(_marker_svg(x, y, MARK_R, r.get("kind",""), info))
    # レジェンド
    legend_defs = [
        ("欠片45", "欠片45"),
        ("欠片75", "欠片75"),
        ("核",     "核"),
        ("全滅",   "全滅"),
    ]
    legend_x = PAD_L
    legend_y = 12
    lg = []
    for label, kind_name in legend_defs:
        # アイコン
        base_kind = "欠片" if kind_name in ("欠片45","欠片75") else kind_name
        uri = _img_to_data_uri(ICON_PATHS.get(base_kind, ""))
        w = h = 14
        if uri:
            lg.append(f'<image href="{uri}" x="{legend_x}" y="{legend_y-10}" width="{w}" height="{h}" />')
        else:
            lg.append(f'<rect x="{legend_x}" y="{legend_y-10}" width="{w}" height="{h}" rx="3" fill="#475569" />')

        # バッジ
        bs = _BADGE_STYLE.get(kind_name, {})
        if bs.get("label"):
            r = 5.2
            bx = legend_x + w - r*0.6
            by = legend_y - 10 + h - r*0.6
            lg.append(f'<circle cx="{bx}" cy="{by}" r="{r}" fill="{bs["bg"]}" />')
            lg.append(f'<text x="{bx}" y="{by+1.6}" text-anchor="middle" font-size="7" font-weight="700" fill="{bs["fg"]}">{bs["label"]}</text>')
        # ラベル文字
        lg.append(f'<text x="{legend_x + 20}" y="{legend_y+1}" fill="#d1d5db" font-size="12">{label}</text>')
        legend_x += 90


    svg = f'''
<svg viewBox="0 0 {W} {H+28}" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="0" width="{W}" height="{H+28}" fill="transparent"/>
  <line x1="{PAD_L}" y1="{Y}" x2="{W-PAD_R}" y2="{Y}" stroke="#52525b" stroke-width="1"/>
  {"".join(segs)}
  {"".join(marks)}
  {axis}
  {axis_label}
  {"".join(lg)}
</svg>
    '''
    st.subheader(title)
    st.markdown(svg, unsafe_allow_html=True)

    # フッタ
    df = df.sort_values("ts").reset_index(drop=True)
    if df.iloc[0]["kind"] != "start":
        df = pd.concat([
            pd.DataFrame([{"ts": df.iloc[0]["ts"], "kind": "start", "合計": 0}]),
            df
        ], ignore_index=True)

    # 合計経過時間
    total_elapsed_min = (df["ts"].iloc[-1] - df["ts"].iloc[0]).total_seconds() / 60

    # 平均時間
    intervals_min = df["ts"].diff().iloc[1:].dt.total_seconds().div(60)
    avg_interval_min = float(intervals_min.mean()) if len(intervals_min) else 0.0

    # 表示
    st.caption(
        f"⏳ 合計経過時間: **{total_elapsed_min:.1f} 分**　｜　"
        f"⏱ 平均時間: **{avg_interval_min:.1f} 分/回**"
    )


if "supabase" not in st.session_state:
    st.session_state["supabase"] = SupabaseDB()
# ------------------ ユーザー選択 or 新規作成 ------------------
st.sidebar.header("ユーザー選択または新規作成")
if "usernames" not in st.session_state:
    st.session_state["usernames"] = st.session_state.supabase.get_user()["username"].tolist()
selected_user = st.sidebar.selectbox("ユーザーを選択", ["新規作成"] + st.session_state["usernames"])

# 初期化：前回値と更新時刻をセッションステートに保存
if "inputs" not in st.session_state:
    st.session_state.inputs = {}
if "last_modified" not in st.session_state:
    st.session_state.last_modified = None
    # ---- セッション初期値（初回だけ） ----
    if "frag_45" not in st.session_state: st.session_state.frag_45 = 0
    if "frag_75" not in st.session_state: st.session_state.frag_75 = 0
    if "core"    not in st.session_state: st.session_state.core    = 0
    if "wipes"   not in st.session_state: st.session_state.wipes   = 0
    if "meal_cost" not in st.session_state: st.session_state.meal_cost = 0.0
    if "meal_num"  not in st.session_state: st.session_state.meal_num  = 0
    if "cost"      not in st.session_state: st.session_state.cost      = 7.00
    if "price"     not in st.session_state: st.session_state.price     = 100.00
# カウントログの初期化
if "count_logs" not in st.session_state:
    st.session_state.count_logs = []
if "_reset_counts" not in st.session_state:
    st.session_state._reset_counts = False
if "_last_total" not in st.session_state:
    st.session_state._last_total = 0
if "_last_45" not in st.session_state:
    st.session_state._last_45 = 0
if "_last_75" not in st.session_state:
    st.session_state._last_75 = 0
if "_last_core" not in st.session_state:
    st.session_state._last_core = 0
if "_last_wipes" not in st.session_state:
    st.session_state._last_wipes = 0


# カウントのリセット
if st.session_state._reset_counts:
    reset_count()
    st.session_state._reset_counts = False

# 現在時刻
now = datetime.now(timezone("Asia/Tokyo"))

if selected_user == "新規作成":
    new_user = st.sidebar.text_input("新しいユーザー名を入力")
    if st.sidebar.button("ユーザー作成") and new_user:
        st.success(f"{new_user} を作成しました。")
        st.session_state.supabase.create_user(new_user)
        st.cache_data.clear()
        st.session_state["usernames"] = st.session_state.supabase.get_user()["username"].tolist()
        st.rerun()
else:
    st.header(f"{selected_user} の輝晶核家計簿")
    # 通知表示
    msg = st.session_state.pop("_flash_msg", None)
    if msg:
        getattr(st, msg[0])(msg[1])
    # ------------------ 入力フォーム ------------------
    date = st.date_input("日付", datetime.now(timezone("Asia/Tokyo")).date())
    col1, col2, col3, col4 = st.columns(4)
    with col1: frag_45 = st.number_input("欠片45", min_value=0, step=1, key="frag_45")
    with col2: frag_75 = st.number_input("欠片75", min_value=0, step=1, key="frag_75")
    with col3: core = st.number_input("核", min_value=0, step=1, key="core")
    with col4: wipes = st.number_input("全滅回数", min_value=0, step=1, key="wipes")
    col1, col2, col3, col4 = st.columns(4)
    with col1: meal_cost = st.number_input("料理の価格(万G)", min_value=0.00, step=1.0, key="meal_cost")
    with col2: meal_num = st.number_input("飯数", min_value=0, step=1, key="meal_num")
    with col3: cost = st.number_input("細胞の価格(万G)", min_value=0.0, step=0.01, key="cost")
    with col4: price = st.number_input("核の価格(万G)", min_value=0.0, step=0.1, key="price")

    # -------- 相場の自動投入ボタン --------
    def _apply_market(kaku_item: str, saibou_item: str):
        # Gold -> 万G へ
        kaku = st.session_state.supabase.get_latest_price(kaku_item)
        saibou = st.session_state.supabase.get_latest_price(saibou_item)
        kakera_item = saibou_item + "のかけら"
        kakera = st.session_state.supabase.get_latest_price(kakera_item)
        if kaku is not None:
            st.session_state.price = round(kaku / 10000, 1)
        if saibou is not None:
            saibou = min(saibou, kakera * 20) if kakera is not None else saibou
            st.session_state.cost = round(saibou / 10000, 2)
        else:
            st.warning("相場データが見つかりませんでした。")


    # 最新価格の取得ボタン
    st.markdown(
        "<div style='color:#999; padding-top:6px;'>このボタンを押すと最新の相場の細胞・核の価格が入力されます</div>",
        unsafe_allow_html=True
    )
    col1, col2 = st.columns([2, 2])
    with col1:
        st.button(
            "輝晶核",
            on_click=_apply_market,
            kwargs={"kaku_item": "輝晶核", "saibou_item": "魔因細胞"},
            use_container_width=True,
        )
    with col2:
        st.button(
            "閃輝晶核",
            on_click=_apply_market,
            kwargs={"kaku_item": "閃輝晶核", "saibou_item": "閃魔細胞"},
            use_container_width=True,
        )

    current_inputs = {
        "frag_45": st.session_state.frag_45,
        "frag_75": st.session_state.frag_75,
        "core":    st.session_state.core,
        "wipes":   st.session_state.wipes,
        "meal_cost": st.session_state.meal_cost,
        "meal_num":  st.session_state.meal_num,
        "cost":      st.session_state.cost,
        "price":     st.session_state.price,
    }

    commission = 0.05
    profit = (
        st.session_state.price * (st.session_state.frag_45 * 45/99 + st.session_state.frag_75 * 75/99 + st.session_state.core) * (1 - commission)
        - st.session_state.cost * 30 * (st.session_state.frag_45 + st.session_state.frag_75 + st.session_state.core + st.session_state.wipes) / 4
        - st.session_state.meal_cost * (st.session_state.meal_num / 5)
    )
    profit = int(profit * 10000)
    record_count(now)
    count = st.session_state._last_total

    html = """
    <div style="display: flex; gap: 2rem;">
      <div style="flex: 1; background-color: #2b2b2b; padding: 1rem; border-radius: 1rem; border: 1px solid #555;">
        <div style="color: #e0b973; font-size: 1.2rem; font-weight: bold; display: flex; align-items: center;">
          現在の利益
        </div>
        <div style="font-size: 2rem; color: #66cc99; font-weight: bold;">
          {profit} G
        </div>
      </div>
      <div style="flex: 1; background-color: #2b2b2b; padding: 1rem; border-radius: 1rem; border: 1px solid #555;">
        <div style="color: #a3d0ff; font-size: 1.2rem; font-weight: bold; display: flex; align-items: center;">
          現在の周回数
        </div>
        <div style="font-size: 2rem; color: #80bfff; font-weight: bold;">
          {count} 周 ({cycles} 餅目)
        </div>
      </div>
    </div>
    """.format(
        profit=f"{profit:,}",
        count=f"{count:,}",
        cycles = math.ceil(count / 4)
    )
    st.markdown(html, unsafe_allow_html=True)


    # カウント履歴の表示
    render_count_logs(st.session_state.count_logs)


    st.markdown(
        "<div style='margin-top:1em;margin-bottom:0.3em;color:#ffcc00;'>⚠️ 入力したデータは、このボタンを押さないと保存されません。</div>",
        unsafe_allow_html=True
    )
    if st.button("データを追加", use_container_width=True):
        new_id = str(uuid.uuid4())
        record = {
            "id": new_id,
            "username": selected_user,
            "date": date.strftime("%Y-%m-%d"),
            "frag_45": st.session_state.frag_45,
            "frag_75": st.session_state.frag_75,
            "core": st.session_state.core,
            "wipes": st.session_state.wipes,
            "cost": st.session_state.cost,
            "price": st.session_state.price,
            "profit": profit,
            "meal_cost": st.session_state.meal_cost,
            "meal_num": st.session_state.meal_num,
        }
        st.session_state.supabase.add_record(record)
        st.session_state.supabase.update_user_last_activity(selected_user)
        st.success("データを追加しました！")
        st.session_state._flash_msg = ("success", "データを追加しました！")
        st.rerun()

    # 前回カウントを変更した際の時刻を表示
    # 45, 75 , core, wipesを変更したときのみ更新
    current_count_inputs = {
        "frag_45": st.session_state.frag_45,
        "frag_75": st.session_state.frag_75,
        "core":    st.session_state.core,
        "wipes":   st.session_state.wipes,
    }
    if current_count_inputs != {k: st.session_state.inputs.get(k, None) for k in current_count_inputs}:
        st.session_state.last_modified = now
        st.session_state.inputs.update(current_count_inputs)
    # if st.session_state.last_modified:
    #     st.info(f"最後にカウントを入力した時間: {st.session_state.last_modified.strftime('%H:%M:%S')}")


    # カウンターと履歴のクリア
    if st.button("カウントと履歴の表示をクリア", type="secondary"):
        st.session_state._reset_counts = True
        st.session_state.count_logs = []
        # st.session_state._flash_msg = ("info", "カウントと履歴をクリアしました")
        st.rerun()

    # ------------------ データ表示 ------------------
    st.divider()
    st.subheader("投入済みデータ")
    st.caption("※表の編集後は『更新内容を保存』ボタンで反映されます（利益・日付は編集不可）")
    df = st.session_state.supabase.get_records_by_user(selected_user)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["month"] = df["date"].dt.to_period("M").astype(str)
        months = sorted(df["month"].unique(), reverse=True)
        selected_month = st.selectbox("表示する月を選択", months + ["すべて表示"])
        filtered_df = df if selected_month == "すべて表示" else df[df["month"] == selected_month]
        filtered_df = filtered_df.sort_values("created_at", ascending=False).reset_index(drop=True)
        editable_df = filtered_df.drop(columns=["month"])
        editable_df["date"] = editable_df["date"].dt.date
        editable_df["profit"] = editable_df["profit"].apply(lambda x: f"{x:,}")

        edited_df = st.data_editor(
            editable_df,
            column_config={
                "id": st.column_config.Column(width=0.001, disabled=True),
                "username": st.column_config.Column(width=0.001, disabled=True),
                "date": st.column_config.Column("日付", disabled=True),
                "frag_45": "欠片45",
                "frag_75": "欠片75",
                "core": "核",
                "wipes": "全滅",
                "cost": "細胞価格",
                "price": "核売値",
                "profit": st.column_config.Column("利益", disabled=True),
                "meal_cost": "料理価格",
                "meal_num": "飯数",
                "created_at": st.column_config.Column("", width=0.01, disabled=True),
            },
            use_container_width=False,
            hide_index=True,
            num_rows="dynamic"
        )
        st.markdown(
            "<div style='margin-top:1em;margin-bottom:0.3em;color:#ffcc00;'>⚠️ 修正したデータは、このボタンを押さないと保存されません。</div>",
            unsafe_allow_html=True
        )
        if st.button("更新内容を保存", use_container_width=True):
            before_ids = set(filtered_df["id"])
            after_ids = set(edited_df["id"])
            deleted_ids = before_ids - after_ids
            # 更新処理
            for idx, row in edited_df.iterrows():
                record_id = row["id"]
                new_values = row.to_dict()
                new_values["date"] = row["date"].strftime("%Y-%m-%d")
                new_values["profit"] = calculate_profit(
                    new_values["frag_45"],
                    new_values["frag_75"],
                    new_values["core"],
                    new_values["wipes"],
                    new_values["meal_cost"],
                    new_values["meal_num"],
                    new_values["cost"],
                    new_values["price"]
                )
                try:
                    res = st.session_state.supabase.update_record(record_id, new_values)
                    st.session_state.supabase.update_user_last_activity(selected_user)
                except Exception as e:
                    st.error(f"更新失敗: {e}")
            # 削除処理
            for del_id in deleted_ids:
                try:
                    st.session_state.supabase.delete_record(del_id)
                except Exception as e:
                    st.error(f"削除失敗: {e}")
            st.rerun()
            # st.success("保存しました")

        # グラフの描画
        sum_45 = filtered_df["frag_45"].astype(int).sum()
        sum_75 = filtered_df["frag_75"].astype(int).sum()
        sum_core = filtered_df["core"].astype(int).sum()
        sum_profit = filtered_df["profit"].astype(int).sum()
        st.markdown("### 📊 集計結果")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            left, right = st.columns([1, 5])
            with left:
                st.image("https://dqx-souba.game-blog.app/images/6578b09786230929d05e139c837fd666bb8652ec.png", width=40)
            with right:
                st.metric(label="欠片45 合計", value=f"{sum_45:,}")
        with col2:
            left, right = st.columns([1, 5])
            with left:
                st.image("https://dqx-souba.game-blog.app/images/6578b09786230929d05e139c837fd666bb8652ec.png", width=40)
            with right:
                st.metric(label="欠片75 合計", value=f"{sum_75:,}")
        with col3:
            left, right = st.columns([1, 5])
            with left:
                st.image("https://dqx-souba.game-blog.app/images/334b68b0abdd5d6c0a5cc7e7522674c5fd7a74bf.png", width=40)
            with right:
                st.metric(label="輝晶核 合計", value=f"{sum_core:,}")
        with col4:
            st.metric(label="💰 利益 合計", value=f"{sum_profit:,} G")

    # ------------------ グラフ ------------------
        st.divider()
        st.write(f"### 累積利益推移")
        df["週"] = df["date"].dt.to_period("W").apply(lambda r: r.start_time)
        df["月"] = df["date"].dt.to_period("M").dt.to_timestamp()
        available_years = sorted(df["月"].dt.year.unique(), reverse=True)
        selected_year = st.selectbox("表示する年を選択", available_years)
        df_selected_year = df[df["月"].dt.year == selected_year]
        weekly_profit = df_selected_year.groupby("週")["profit"].sum().reset_index()

        # 欠けている週を補完
        min_week = weekly_profit["週"].min()
        max_week = weekly_profit["週"].max()
        all_weeks = pd.date_range(start=min_week, end=max_week, freq="W-MON")

        df_weeks = pd.DataFrame({"週": all_weeks})
        weekly_profit = df_weeks.merge(weekly_profit, on="週", how="left").fillna(0)

        weekly_profit["累積利益"] = weekly_profit["profit"].cumsum()

        line_chart = alt.Chart(weekly_profit).mark_line(point=True).encode(
            x=alt.X("週:T", title="日付"),
            y=alt.Y("累積利益:Q", title="累積利益（G）"),
            tooltip=["週", "累積利益"]
        ).properties(width=700, height=300)

        st.altair_chart(line_chart, use_container_width=True)

