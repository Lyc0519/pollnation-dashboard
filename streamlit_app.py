# -*- coding: utf-8 -*-
import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import os
from io import BytesIO
import json

# ====================== 安全读取密钥 ======================
try:
    # Streamlit Cloud部署时，在Secrets里配置这些密钥
    AIO_USERNAME = st.secrets["AIO_USERNAME"]
    AIO_KEY = st.secrets["AIO_KEY"]
    # 火山方舟豆包API密钥（你拿到的）
    DOUBAO_API_KEY = st.secrets["DOUBAO_API_KEY"]
    # 你的endpoint ID（已替换）
    DOUBAO_MODEL_ENDPOINT = "doubao-1-5-lite-32k-250115"
except:
    # 本地运行时读取系统环境变量
    AIO_USERNAME = os.getenv("AIO_USERNAME", "lyc0519")
    AIO_KEY = os.getenv("AIO_KEY", "")
    DOUBAO_API_KEY = os.getenv("DOUBAO_API_KEY", "")
    DOUBAO_MODEL_ENDPOINT = "doubao-1-5-lite-32k-250115"

# ====================== Feed配置（已修正） ======================
REGIONS = {
    "区域一": {
        "temp_feed": "temperature",
        "hum_feed": "humidity",
        "poll_feed": "pollination-status",
        "monitor_img": "https://via.placeholder.com/800x400?text=区域一监控画面"
    }
}

# 环境阈值（授粉适宜范围）
THRESHOLDS = {
    "temp": {"min": 18, "max": 30},
    "hum": {"min": 50, "max": 70}
}

# 页面配置
st.set_page_config(
    page_title="🌱 智能授粉系统客户端",
    page_icon="🌱",
    layout="wide"
)

# -------------------------- 核心工具函数 --------------------------
def get_adafruit_data(feed_key, limit=30):
    """爬取Adafruit IO数据"""
    if not AIO_KEY:
        st.error("未配置Adafruit IO密钥！")
        return None
    url = f"https://io.adafruit.com/api/v2/{AIO_USERNAME}/feeds/{feed_key}/data?limit={limit}"
    headers = {"X-AIO-Key": AIO_KEY}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        if not data:
            return None
        df = pd.DataFrame(data)
        df["value"] = df["value"].astype(float)
        df["created_at"] = pd.to_datetime(df["created_at"]) + timedelta(hours=8)
        df.rename(columns={"created_at": "时间", "value": "数值"}, inplace=True)
        return df
    except Exception as e:
        st.warning(f"Adafruit数据读取失败：{str(e)}")
        return None

def get_pollination_status(status_num):
    """授粉状态转换"""
    if status_num == 1:
        return "✅ 已授粉", "#2ecc71"
    elif status_num == 0:
        return "❌ 未授粉", "#e74c3c"
    else:
        return "⚠️ 无效状态", "#f39c12"

def check_env_alert(value, type_key):
    """环境阈值检查"""
    thresholds = THRESHOLDS[type_key]
    if value < thresholds["min"]:
        return f"⚠️ 低于适宜值（{thresholds['min']}）", "#f39c12"
    elif value > thresholds["max"]:
        return f"⚠️ 高于适宜值（{thresholds['max']}）", "#e74c3c"
    else:
        return "✅ 适宜", "#2ecc71"

def export_to_excel(df_dict):
    """数据导出Excel（修复时区问题，兼容openpyxl）"""
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for region, df in df_dict.items():
            if df is not None and not df.empty:
                # 核心修复：将带时区的时间转换为无时区的字符串，兼容Excel
                df_export = df.copy()
                df_export["时间"] = df_export["时间"].dt.strftime("%Y-%m-%d %H:%M:%S")
                df_export.to_excel(writer, sheet_name=region, index=False)
    output.seek(0)
    return output



# -------------------------- AI分析核心函数 --------------------------
def get_doubao_analysis(region_name):
    """调用火山方舟豆包API生成农业数据分析报告"""
    # 1. 获取并整理数据
    temp_df = get_adafruit_data(REGIONS[region_name]["temp_feed"], limit=30)
    hum_df = get_adafruit_data(REGIONS[region_name]["hum_feed"], limit=30)
    poll_df = get_adafruit_data(REGIONS[region_name]["poll_feed"], limit=30)
    
    if temp_df is None or hum_df is None or poll_df is None:
        return "❌ 数据不足，无法生成分析报告"
    
    # 数据统计
    real_temp = temp_df["数值"].iloc[0]
    real_hum = hum_df["数值"].iloc[0]
    temp_mean = temp_df["数值"].mean()
    temp_max = temp_df["数值"].max()
    temp_min = temp_df["数值"].min()
    hum_mean = hum_df["数值"].mean()
    hum_max = hum_df["数值"].max()
    hum_min = hum_df["数值"].min()
    poll_status = "已授粉" if poll_df["数值"].iloc[0] == 1 else "未授粉"
    poll_count = len(poll_df)
    poll_complete = len(poll_df[poll_df["数值"] == 1])
    poll_rate = (poll_complete / poll_count) * 100 if poll_count > 0 else 0

    # 2. 构造分析提示词
    prompt = f"""
    你是资深的智能农业分析师，现在需要分析{region_name}的作物授粉环境数据，要求如下：
    1. 基础数据：
       - 实时温度：{real_temp:.1f}℃（授粉适宜范围{THRESHOLDS['temp']['min']}-{THRESHOLDS['temp']['max']}℃）
       - 实时湿度：{real_hum:.1f}%RH（授粉适宜范围{THRESHOLDS['hum']['min']}-{THRESHOLDS['hum']['max']}%RH）
       - 温度历史（近30条）：均值{temp_mean:.1f}℃，最高{temp_max:.1f}℃，最低{temp_min:.1f}℃
       - 湿度历史（近30条）：均值{hum_mean:.1f}%RH，最高{hum_max:.1f}%RH，最低{hum_min:.1f}%RH
       - 授粉状态：最新{poll_status}，近30次完成率{poll_rate:.1f}%
    2. 分析要求：
       - 先判断当前温湿度是否适合作物授粉
       - 分析温湿度历史趋势（如波动幅度、持续偏高/偏低等）
       - 结合授粉完成率，解释环境对授粉效果的影响
       - 给出具体的农业操作建议（如通风、浇水、调整授粉时间等）
       - 语言专业但易懂，分点说明，不超过500字
    """

    # 3. 调用火山方舟豆包API（已替换你的endpoint ID）
    if not DOUBAO_API_KEY:
        return "❌ 豆包API密钥未配置，请检查Streamlit Secrets"
    
    url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
    headers = {
        "Authorization": f"Bearer {DOUBAO_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "doubao-1-5-lite-32k-250115",  # 你的endpoint ID
        "messages": [
            {"role": "system", "content": "你是资深智能农业分析师，专注于作物授粉环境分析，只输出分析内容，不添加无关话术"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,  # 降低随机性，保证分析准确
        "max_tokens": 800
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        return f"❌ AI分析失败：{str(e)}\n请检查API密钥是否正确"

# -------------------------- 主界面逻辑 --------------------------
st.title("🌱 智能授粉系统客户端")
st.markdown("### 多区域环境监测 | 授粉状态管理 | AI牛马🐂🐎智能分析")
st.divider()

# 区域选择
selected_region = st.selectbox("选择监控区域", list(REGIONS.keys()), index=0)
region_config = REGIONS[selected_region]

# 1. 监控画面（抖音解析直链，直接可用）
st.subheader(f"📹 {selected_region} 监控画面")
st.video("https://github.com/Lyc0519/pollnation-dashboard/releases/download/v1/testvideo.mp4")
st.markdown("<br>", unsafe_allow_html=True)
# 2. 实时数据
st.subheader(f"📊 {selected_region} 实时数据")
col1, col2, col3 = st.columns(3)

# 温度卡片
temp_df = get_adafruit_data(region_config["temp_feed"], 1)
if temp_df is not None and not temp_df.empty:
    v = temp_df["数值"].iloc[0]
    alert, color = check_env_alert(v, "temp")
    col1.metric(f"当前温度 {alert}", f"{v:.1f} °C")
else:
    col1.metric("当前温度", "暂无数据")

# 湿度卡片
hum_df = get_adafruit_data(region_config["hum_feed"], 1)
if hum_df is not None and not hum_df.empty:
    v = hum_df["数值"].iloc[0]
    alert, color = check_env_alert(v, "hum")
    col2.metric(f"当前湿度 {alert}", f"{v:.1f} %RH")
else:
    col2.metric("当前湿度", "暂无数据")

# 授粉状态卡片
poll_df = get_adafruit_data(region_config["poll_feed"], 1)
if poll_df is not None and not poll_df.empty:
    v = poll_df["数值"].iloc[0]
    txt, color = get_pollination_status(v)
    col3.markdown(f"""
        <div style="background-color:#f0f2f6;padding:20px;border-radius:8px;text-align:center;">
            <p style="font-size:16px;margin:0;color:#666;">当前授粉状态</p>
            <p style="font-size:24px;margin:10px 0;color:{color};font-weight:bold;">{txt}</p>
            <p style="font-size:12px;color:#999;">更新时间：{poll_df['时间'].iloc[0].strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
    """, unsafe_allow_html=True)
else:
    col3.markdown(f"""
        <div style="background-color:#f0f2f6;padding:20px;border-radius:8px;text-align:center;">
            <p style="font-size:16px;margin:0;color:#666;">当前授粉状态</p>
            <p style="font-size:24px;margin:10px 0;color:#999;font-weight:bold;">暂无数据</p>
        </div>
    """, unsafe_allow_html=True)

st.divider()

# 3. 历史趋势图
st.subheader(f"📈 {selected_region} 历史数据趋势（最近30条）")
temp_history = get_adafruit_data(region_config["temp_feed"], 30)
hum_history = get_adafruit_data(region_config["hum_feed"], 30)
if temp_history is not None and hum_history is not None:
    temp_history.rename(columns={"数值": "温度"}, inplace=True)
    hum_history.rename(columns={"数值": "湿度"}, inplace=True)
    merged_df = pd.merge(temp_history[["时间", "温度"]], hum_history[["时间", "湿度"]], on="时间", how="outer")
    merged_df = merged_df.sort_values("时间")
    st.line_chart(merged_df, x="时间", y=["温度", "湿度"], color=["#FF6B6B", "#4ECDC4"], use_container_width=True)

# 授粉状态趋势
poll_history = get_adafruit_data(region_config["poll_feed"], 30)
if poll_history is not None and not poll_history.empty:
    st.subheader(f"🌸 {selected_region} 授粉状态历史记录")
    poll_history.rename(columns={"数值": "授粉状态"}, inplace=True)
    st.line_chart(poll_history, x="时间", y="授粉状态", color=["#2ecc71"], use_container_width=True, height=300)
    
    # 授粉统计
    poll_count = len(poll_history)
    poll_complete = len(poll_history[poll_history["授粉状态"] == 1])
    completion_rate = (poll_complete / poll_count) * 100 if poll_count > 0 else 0
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("总记录数", poll_count)
    col_b.metric("已授粉次数", poll_complete)
    col_c.metric("授粉完成率", f"{completion_rate:.1f}%")

st.divider()

# -------------------------- 豆包AI分析模块 --------------------------
st.subheader("🤖🐂🐎 AI牛马智能农业数据分析")
if temp_df is not None and hum_df is not None and poll_df is not None:
    if st.button("召唤AI牛马生成智能分析报告", type="primary"):
        with st.spinner("您的AI牛马正在分析农业数据，请稍候..."):
            analysis_report = get_doubao_analysis(selected_region)
        st.markdown("### 📝 分析报告")
        st.markdown(analysis_report)
else:
    st.warning("⚠️ 暂无足够数据生成分析报告，请先确保温湿度和授粉状态数据正常采集")

st.divider()

# 4. 数据导出
st.subheader("💾 数据导出")
export_data = {}
for rname, cfg in REGIONS.items():
    t = get_adafruit_data(cfg["temp_feed"], 100)
    h = get_adafruit_data(cfg["hum_feed"], 100)
    p = get_adafruit_data(cfg["poll_feed"], 100)
    if t is not None and h is not None and p is not None:
        t.rename(columns={"数值": "温度"}, inplace=True)
        h.rename(columns={"数值": "湿度"}, inplace=True)
        p.rename(columns={"数值": "授粉状态"}, inplace=True)
        merged_df = pd.merge(t[["时间", "温度"]], h[["时间", "湿度"]], on="时间", how="outer")
        merged_df = pd.merge(merged_df, p[["时间", "授粉状态"]], on="时间", how="outer")
        export_data[rname] = merged_df

if export_data:
    excel_file = export_to_excel(export_data)
    st.download_button(
        label="📥 导出所有区域数据为Excel",
        data=excel_file,
        file_name=f"智能授粉数据_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
else:
    st.warning("暂无数据可导出")

# 自动刷新
st.markdown(f"""
    <meta http-equiv="refresh" content="30">
    <p style='text-align:center;color:#999;font-size:12px;'>页面每10秒自动刷新 | 最后刷新：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
""", unsafe_allow_html=True)