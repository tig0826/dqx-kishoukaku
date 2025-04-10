import altair as alt
import streamlit as st
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
# ------------------ キャッシュ関数 ------------------
@st.cache_data(ttl=600)
def get_user_records(_worksheet):
    return _worksheet.get_all_records()
if "spreadsheet" not in st.session_state:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(creds)
    SPREADSHEET_NAME = "輝晶核家計簿"
    spreadsheet = client.open(SPREADSHEET_NAME)
    st.session_state["spreadsheet"] = spreadsheet
else:
    spreadsheet = st.session_state["spreadsheet"]

# ------------------ ユーザー選択 or 新規作成 ------------------
st.sidebar.header("ユーザー選択または新規作成")
if "sheet_titles" not in st.session_state:
    st.session_state["sheet_titles"] = [ws.title for ws in spreadsheet.worksheets() if ws.title != "全体データ"]
selected_user = st.sidebar.selectbox("ユーザーを選択", ["新規作成"] + st.session_state["sheet_titles"])

if selected_user == "新規作成":
    new_user = st.sidebar.text_input("新しいユーザー名を入力")
    if st.sidebar.button("ユーザー作成") and new_user:
        spreadsheet.add_worksheet(title=new_user, rows="1000", cols="20")
        sheet = spreadsheet.worksheet(new_user)
        sheet.append_row(["日付", "欠片45", "欠片75", "核", "全滅回数", "原価", "売値", "利益", "料理の価格", "飯数", "ID"])
        st.cache_data.clear()
        st.success(f"{new_user} を作成しました。")
        st.session_state["sheet_titles"] = [ws.title for ws in spreadsheet.worksheets() if ws.title != "全体データ"]
        st.rerun()
else:
    worksheet = st.session_state.get("worksheet")
    if worksheet is None or st.session_state.get("selected_user") != selected_user:
        st.cache_data.clear()
        worksheet = spreadsheet.worksheet(selected_user)
        st.session_state["worksheet"] = worksheet
        st.session_state["selected_user"] = selected_user
        st.session_state["records"] = get_user_records(worksheet)
        st.rerun()


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
        worksheet.append_row([
            date.strftime("%Y-%m-%d"), frag_45, frag_75, core, wipes, cost, price,
            profit, meal_cost, meal_num, new_id
        ])
        st.session_state["records"] = get_user_records(worksheet)
        st.success("データを追加しました！")
        st.cache_data.clear()
        st.session_state["worksheet"] = worksheet
        st.session_state["selected_user"] = selected_user
        st.session_state["records"] = get_user_records(worksheet)
        st.rerun()



    records = st.session_state.get("records", [])
    if records:
        # ------------------ 表示と編集 ------------------
        st.write("### 過去のデータ")
        st.text("※投入済みのデータの修正も可能です。修正後は保存ボタンを押さないと反映されません。利益と日付は手動変更出来ません。")
        df = pd.DataFrame(records)
        df["日付"] = pd.to_datetime(df["日付"], errors="coerce")
        df["月"] = df["日付"].dt.to_period("M").astype(str)
        months = sorted(df["月"].unique(), reverse=True)
        selected_month = st.selectbox("表示する月を選択", months + ["すべて表示"])
        if st.session_state.get("last_selected_month") != selected_month:
            st.cache_data.clear()
            st.session_state["worksheet"] = worksheet
            st.session_state["selected_user"] = selected_user
            st.session_state["records"] = get_user_records(worksheet)
            st.session_state["last_selected_month"] = selected_month
            st.rerun()
        filtered_df = df if selected_month == "すべて表示" else df[df["月"] == selected_month]
        filtered_df = filtered_df.reset_index(drop=True)
        filtered_df["日付"] = filtered_df["日付"].dt.date
        filtered_df_display = filtered_df.style.format({"利益": lambda x : '{:,} G'.format(x),},thousands=',')
        edited_df = st.data_editor(
            filtered_df_display,
            num_rows="dynamic",
            use_container_width=False,
            column_config={
                "ID": st.column_config.Column(label="", width=0.01, disabled=True),
                "月": st.column_config.Column(label="", width=0.01, disabled=True),
                "日付": st.column_config.Column(disabled=True),
                "利益": st.column_config.Column(width=100, disabled=True),
            },
            hide_index=True,
        )
        if st.button("更新内容を保存"):
            df_all = pd.DataFrame(get_user_records(worksheet))
            df_all["日付"] = pd.to_datetime(df_all["日付"], errors="coerce")
            df_all["月"] = df_all["日付"].dt.to_period("M").astype(str)
            id_to_rownum = {row["ID"]: idx + 2 for idx, row in df_all.iterrows()}
            for _, edited_row in edited_df.iterrows():
                # 利益を再計算する
                frag_45 = int(edited_row["欠片45"])
                frag_75 = int(edited_row["欠片75"])
                core = int(edited_row["核"])
                wipes = int(edited_row["全滅回数"])
                cost = float(edited_row["原価"])
                price = float(edited_row["売値"])
                meal_cost = float(edited_row["料理の価格"])
                meal_num = int(edited_row["飯数"])
                profit_new = price * (frag_45 * 45/99 + frag_75 * 75/99 + core) * (1 - commission)
                profit_new -= cost * 30 * (frag_45 + frag_75 + core + wipes) / 4
                profit_new -= meal_cost * (meal_num / 5)
                profit_new =  int(profit_new * 10000)
                edited_row["利益"] = profit_new

                edited_row["日付"] = edited_row["日付"].strftime("%Y-%m-%d")
                row_data = edited_row[df_all.columns.drop("月")].tolist()
                
                if edited_row["ID"] in id_to_rownum:
                    row_number = id_to_rownum[edited_row["ID"]]
                    for col_idx, val in enumerate(row_data, start=1):
                        worksheet.update_cell(row_number, col_idx, val)
                else:
                    worksheet.append_row(row_data)
            # 削除対象の特定と削除
            df_target_month = df_all[df_all["月"] == selected_month]
            existing_ids = set(df_target_month["ID"])
            edited_ids = set(edited_df["ID"])
            deleted_ids = existing_ids - edited_ids
            rows_to_delete = [id_to_rownum[del_id] for del_id in deleted_ids if del_id in id_to_rownum]
            for row_num in sorted(rows_to_delete, reverse=True):
                worksheet.delete_rows(row_num)
            st.session_state["records"] = get_user_records(worksheet)
            st.success("保存しました")
            st.cache_data.clear()
            st.session_state["worksheet"] = worksheet
            st.session_state["selected_user"] = selected_user
            st.session_state["records"] = get_user_records(worksheet)
            st.session_state["last_selected_month"] = selected_month
            st.rerun()
        sum_45 = filtered_df["欠片45"].astype(int).sum()
        sum_75 = filtered_df["欠片75"].astype(int).sum()
        sum_core = filtered_df["核"].astype(int).sum()
        sum_profit = filtered_df["利益"].astype(int).sum()

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
        df["月"] = df["日付"].dt.to_period("M").dt.to_timestamp()
        available_years = sorted(df["月"].dt.year.unique(), reverse=True)
        selected_year = st.selectbox("表示する年を選択", available_years)
        df_selected_year = df[df["月"].dt.year == selected_year]
        monthly_profit = df_selected_year.groupby("月")["利益"].sum().reset_index()
        monthly_profit["累積利益"] = monthly_profit["利益"].cumsum()

        line_chart = alt.Chart(monthly_profit).mark_line(point=True).encode(
            x=alt.X("月:T", title="月"),
            y=alt.Y("累積利益:Q", title="累積利益（G）"),
            tooltip=["月", "累積利益"]
        ).properties(width=700, height=300)

        st.altair_chart(line_chart, use_container_width=True)