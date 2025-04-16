import altair as alt
import streamlit as st
from supabase import create_client, Client
import pandas as pd
from pytz import timezone
import uuid
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

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
        response = self.client.table("users").select("*").execute()
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
    with col1: frag_45 = st.number_input("欠片45", min_value=0, step=1)
    with col2: frag_75 = st.number_input("欠片75", min_value=0, step=1)
    with col3: core = st.number_input("核", min_value=0, step=1)
    with col4: wipes = st.number_input("全滅回数", min_value=0, step=1)
    col1, col2, col3, col4 = st.columns(4)
    with col1: meal_cost = st.number_input("料理の価格(万G)", min_value=0.0, step=10.0)
    with col2: meal_num = st.number_input("飯数", min_value=0, step=1)
    with col3: cost = st.number_input("細胞の価格(万G)", min_value=0.0, step=1.0)
    with col4: price = st.number_input("核の価格(万G)", min_value=0.0, step=100.0)

    commission = 0.05
    profit = price * (frag_45 * 45/99 + frag_75 * 75/99 + core) * (1 - commission)
    profit -= cost * 30 * (frag_45 + frag_75 + core + wipes) / 4
    profit -= meal_cost * (meal_num / 5)
    profit = int(profit * 10000)
    st.markdown(f"💰 **利益の見込み**: `{int(profit):,} G`")

    if st.button("データを追加"):
        new_id = str(uuid.uuid4())
        record = {
            "id": new_id,
            "username": selected_user,
            "date": date.strftime("%Y-%m-%d"),
            "frag_45": frag_45,
            "frag_75": frag_75,
            "core": core,
            "wipes": wipes,
            "cost": cost,
            "price": price,
            "profit": profit,
            "meal_cost": meal_cost,
            "meal_num": meal_num,
        }
        st.session_state.supabase.add_record(record)
        st.success("データを追加しました！")
        st.rerun()
    # ------------------ データ表示 ------------------
    df = st.session_state.supabase.get_records_by_user(selected_user)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["month"] = df["date"].dt.to_period("M").astype(str)
        months = sorted(df["month"].unique(), reverse=True)
        selected_month = st.selectbox("表示する月を選択", months + ["すべて表示"])
        filtered_df = df if selected_month == "すべて表示" else df[df["month"] == selected_month]
        filtered_df = filtered_df.reset_index(drop=True)
        st.text("※編集後は保存ボタンで反映されます。利益と日付は編集不可です")
        editable_df = filtered_df.drop(columns=["month"])
        editable_df["date"] = editable_df["date"].dt.date

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
        if st.button("更新内容を保存"):
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
        st.write(f"### 累積利益推移")
        df["週"] = df["date"].dt.to_period("W").apply(lambda r: r.start_time)
        df["月"] = df["date"].dt.to_period("M").dt.to_timestamp()
        available_years = sorted(df["月"].dt.year.unique(), reverse=True)
        selected_year = st.selectbox("表示する年を選択", available_years)
        df_selected_year = df[df["月"].dt.year == selected_year]
        weekly_profit = df_selected_year.groupby("週")["profit"].sum().reset_index()
        weekly_profit["累積利益"] = weekly_profit["profit"].cumsum()

        line_chart = alt.Chart(weekly_profit).mark_line(point=True).encode(
            x=alt.X("週:T", title="日付"),
            y=alt.Y("累積利益:Q", title="累積利益（G）"),
            tooltip=["週", "累積利益"]
        ).properties(width=700, height=300)

        st.altair_chart(line_chart, use_container_width=True)

