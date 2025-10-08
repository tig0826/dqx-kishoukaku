import altair as alt
import math
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from supabase import create_client, Client
import time
import pandas as pd
from pytz import timezone
import uuid
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timezone as dt_timezone, timedelta

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
    # ------------------ 入力フォーム ------------------
    date = st.date_input("日付", datetime.now(timezone("Asia/Tokyo")).date())
    col1, col2, col3, col4 = st.columns(4)
    with col1: frag_45 = st.number_input("欠片45", min_value=0, step=1, key="frag_45")
    with col2: frag_75 = st.number_input("欠片75", min_value=0, step=1, key="frag_75")
    with col3: core = st.number_input("核", min_value=0, step=1, key="core")
    with col4: wipes = st.number_input("全滅回数", min_value=0, step=1, key="wipes")
    col1, col2, col3, col4 = st.columns(4)
    with col1: meal_cost = st.number_input("料理の価格(万G)", min_value=0.00, step=0.1, key="meal_cost")
    with col2: meal_num = st.number_input("飯数", min_value=0, step=1, key="meal_num")
    with col3: cost = st.number_input("細胞の価格(万G)", min_value=0.0, step=0.1, key="cost")
    with col4: price = st.number_input("核の価格(万G)", min_value=0.0, step=1.0, key="price")

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
    count = st.session_state.frag_45 + st.session_state.frag_75 + st.session_state.core + st.session_state.wipes


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
    if st.session_state.last_modified:
        st.info(f"最後にカウントを入力した時間: {st.session_state.last_modified.strftime('%H:%M:%S')}")


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
        filtered_df = filtered_df.reset_index(drop=True)
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

