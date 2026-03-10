# -*- coding: utf-8 -*-
import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import os
from io import BytesIO

# ====================== 从环境变量/Streamlit Secrets读取密钥（安全部署） ======================
# 优先读取Streamlit Cloud的Secrets，本地运行时读取系统环境变量
try:
    AIO_USERNAME = st.secrets["AIO_USERNAME"]
    AIO_KEY = st.secrets["AIO_KEY"]
except:
    AIO_USERNAME = os.getenv("AIO_USERNAME", "lyc0519")  # 本地默认值
    AIO_KEY = os.getenv("AIO_KEY", "")  # 本地需手动设置环境变量

# 多区域配置（支持区域一/二/三，可扩展）
REGIONS = {
    "区域一": {
        "temp_feed": "temperature",
        "hum_feed": "humidity",
        "poll_feed": "pollination-status",
        "monitor_img": "https://via.placeholder.com/800x400?text=区域一+监控画面"  # 占位图，替换为实际监控图链接
    },
    "区域二": {
        "temp_feed": "temperature-2",  # 替换为实际Feed Key
        "hum_feed": "humidity-2",
        "poll_feed": "pollination-status-2",
        "monitor_img": "https://via.placeholder.com/800x400?text=区域二+监控画面"
    },
    "区域三": {
        "temp_feed": "temperature-3",  # 替换为实际Feed Key
        "hum_feed": "humidity-3",
        "poll_feed": "pollination-status-3",
        "monitor_img": "https://via.placeholder.com/800x400?text=区域三+监控画面"
    }
}
# 环境阈值配置（可自定义）
THRESHOLDS = {
    "temp": {"min": 18, "max": 30},  # 温度适宜范围
    "hum": {"min": 50, "max": 70}     # 湿度适宜范围
}
# =======================================================================

# 页面配置（标题、图标、布局）
st.set_page_config(
    page_title="智能授粉机器人物联网可视化平台",
    page_icon="🌱",
    layout="wide"
)

# -------------------------- 核心工具函数 --------------------------
def get_adafruit_data(feed_key, limit=30):
    """爬取指定Feed的历史数据（适配多区域）"""
    if not AIO_KEY:
        st.error("未配置Adafruit IO密钥！请在Streamlit Secrets或系统环境变量中设置AIO_KEY")
        return None
    url = f"https://io.adafruit.com/api/v2/{AIO_USERNAME}/feeds/{feed_key}/data?limit={limit}"
    headers = {"X-AIO-Key": AIO_KEY}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        if not data:
            return None
        # 整理数据：时间（转北京时间）+ 数值
        df = pd.DataFrame(data)
        df["value"] = df["value"].astype(float)
        df["created_at"] = pd.to_datetime(df["created_at"]) + timedelta(hours=8)  # UTC转北京时间
        df.rename(columns={"created_at": "时间", "value": "数值"}, inplace=True)
        return df
    except Exception as e:
        st.error(f"爬取数据失败：{e}")
        return None

def get_pollination_status(status_num):
    """将0/1转换为文字+颜色"""
    if status_num == 1:
        return "✅ 已授粉", "#2ecc71"  # 绿色
    elif status_num == 0:
        return "❌ 未授粉", "#e74c3c"   # 红色
    else:
        return "⚠️ 无效状态", "#f39c12"  # 橙色

def check_env_alert(value, type_key):
    """检查环境值是否超出阈值，返回告警信息+颜色"""
    thresholds = THRESHOLDS[type_key]
    if value < thresholds["min"]:
        return f"⚠️ 低于适宜值（{thresholds['min']}）", "#f39c12"
    elif value > thresholds["max"]:
        return f"⚠️ 高于适宜值（{thresholds['max']}）", "#e74c3c"
    else:
        return "✅ 适宜", "#2ecc71"

def export_to_excel(df_dict):
    """将多区域数据导出为Excel"""
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for region, df in df_dict.items():
            if df is not None and not df.empty:
                df.to_excel(writer, sheet_name=region, index=False)
    output.seek(0)
    return output

# -------------------------- 主界面逻辑 --------------------------
# 1. 顶部标题+区域选择
st.title("🌱 智能授粉机器人物联网可视化平台")
st.markdown("### 多区域环境监测 | 授粉状态管理 | 实时监控")
st.divider()

# 2. 区域选择标签页
selected_region = st.selectbox("选择监控区域", list(REGIONS.keys()), index=0)
region_config = REGIONS[selected_region]

# 3. 监控图像展示（带标题，下方留空白）
st.subheader(f"📹 {selected_region} 监控图像")
st.image(region_config["monitor_img"], use_container_width=True)
st.markdown("<br><br>", unsafe_allow_html=True)  # 图片下方留白

# 4. 实时数据卡片（三列布局）
st.subheader(f"📊 {selected_region} 实时数据")
col1, col2, col3 = st.columns(3)

# ===== 温度卡片（带异常告警）=====
temp_df = get_adafruit_data(region_config["temp_feed"], limit=1)
if temp_df is not None and not temp_df.empty:
    latest_temp = temp_df["数值"].iloc[0]
    alert_text, alert_color = check_env_alert(latest_temp, "temp")
    col1.metric(
        label=f"当前温度 {alert_text}",
        value=f"{latest_temp:.1f} °C",
        delta=f"{latest_temp-25:.1f} °C",
        delta_color="inverse"
    )
    # 异常告警高亮
    if "⚠️" in alert_text:
        col1.markdown(f"<p style='color:{alert_color};font-weight:bold;'>{alert_text}</p>", unsafe_allow_html=True)
else:
    col1.metric(label="当前温度", value="暂无数据", delta="0 °C")

# ===== 湿度卡片（带异常告警）=====
hum_df = get_adafruit_data(region_config["hum_feed"], limit=1)
if hum_df is not None and not hum_df.empty:
    latest_hum = hum_df["数值"].iloc[0]
    alert_text, alert_color = check_env_alert(latest_hum, "hum")
    col2.metric(
        label=f"当前湿度 {alert_text}",
        value=f"{latest_hum:.1f} %RH",
        delta=f"{latest_hum-60:.1f} %RH",
        delta_color="inverse"
    )
    if "⚠️" in alert_text:
        col2.markdown(f"<p style='color:{alert_color};font-weight:bold;'>{alert_text}</p>", unsafe_allow_html=True)
else:
    col2.metric(label="当前湿度", value="暂无数据", delta="0 %RH")

# ===== 授粉状态卡片（增强版）=====
poll_df = get_adafruit_data(region_config["poll_feed"], limit=1)
if poll_df is not None and not poll_df.empty:
    latest_poll = poll_df["数值"].iloc[0]
    poll_text, poll_color = get_pollination_status(latest_poll)
    col3.markdown(f"""
        <div style="background-color:#f0f2f6;padding:20px;border-radius:8px;text-align:center;">
            <p style="font-size:16px;margin:0;color:#666;">当前授粉状态</p>
            <p style="font-size:24px;margin:10px 0;color:{poll_color};font-weight:bold;">{poll_text}</p>
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

# 5. 历史趋势图（分两行）
st.subheader(f"📈 {selected_region} 历史数据趋势（最近30条）")
# 5.1 温湿度趋势
temp_history = get_adafruit_data(region_config["temp_feed"], limit=30)
hum_history = get_adafruit_data(region_config["hum_feed"], limit=30)
if temp_history is not None and hum_history is not None:
    # 合并数据
    temp_history.rename(columns={"数值": "温度"}, inplace=True)
    hum_history.rename(columns={"数值": "湿度"}, inplace=True)
    merged_df = pd.merge(temp_history[["时间", "温度"]], hum_history[["时间", "湿度"]], on="时间", how="outer")
    merged_df = merged_df.sort_values("时间")
    st.line_chart(
        merged_df,
        x="时间",
        y=["温度", "湿度"],
        color=["#FF6B6B", "#4ECDC4"],
        use_container_width=True
    )
else:
    st.warning("暂无温湿度历史数据")

# 5.2 授粉状态趋势
st.subheader(f"🌸 {selected_region} 授粉状态历史记录")
poll_history = get_adafruit_data(region_config["poll_feed"], limit=30)
if poll_history is not None and not poll_history.empty:
    # 授粉状态趋势图
    poll_history.rename(columns={"数值": "授粉状态"}, inplace=True)
    st.line_chart(
        poll_history,
        x="时间",
        y="授粉状态",
        color=["#2ecc71"],
        use_container_width=True,
        height=300
    )
    # 授粉状态统计
    poll_count = len(poll_history)
    poll_complete = len(poll_history[poll_history["授粉状态"] == 1])
    completion_rate = (poll_complete / poll_count) * 100 if poll_count > 0 else 0
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("总记录数", poll_count)
    col_b.metric("已授粉次数", poll_complete)
    col_c.metric("授粉完成率", f"{completion_rate:.1f}%")
    # 原始数据表格
    poll_history["授粉状态说明"] = poll_history["授粉状态"].apply(lambda x: get_pollination_status(x)[0])
    with st.expander("📋 查看授粉状态原始数据"):
        st.dataframe(
            poll_history[["时间", "授粉状态", "授粉状态说明"]],
            use_container_width=True
        )
else:
    st.warning("暂无授粉状态历史数据")

st.divider()

# 6. 数据导出功能
st.subheader("💾 数据导出")
# 收集所有区域数据
export_data = {}
for region, config in REGIONS.items():
    temp_df = get_adafruit_data(config["temp_feed"], limit=100)
    hum_df = get_adafruit_data(config["hum_feed"], limit=100)
    poll_df = get_adafruit_data(config["poll_feed"], limit=100)
    if temp_df is not None and hum_df is not None and poll_df is not None:
        # 合并为该区域完整数据
        temp_df.rename(columns={"数值": "温度"}, inplace=True)
        hum_df.rename(columns={"数值": "湿度"}, inplace=True)
        poll_df.rename(columns={"数值": "授粉状态"}, inplace=True)
        region_df = pd.merge(temp_df[["时间", "温度"]], hum_df[["时间", "湿度"]], on="时间", how="outer")
        region_df = pd.merge(region_df, poll_df[["时间", "授粉状态"]], on="时间", how="outer")
        export_data[region] = region_df

if export_data:
    excel_file = export_to_excel(export_data)
    st.download_button(
        label="导出所有区域数据为Excel",
        data=excel_file,
        file_name=f"授粉机器人数据_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
else:
    st.warning("暂无数据可导出")

# 7. 环境智能小结
st.subheader("🤖 环境智能小结")
if temp_df is not None and hum_df is not None and poll_df is not None:
    temp_alert = check_env_alert(latest_temp, "temp")[0]
    hum_alert = check_env_alert(latest_hum, "hum")[0]
    poll_text = get_pollination_status(latest_poll)[0]
    summary = f"""
    {selected_region} 环境小结：
    温度 {latest_temp:.1f}°C（{temp_alert}），
    湿度 {latest_hum:.1f}%RH（{hum_alert}），
    授粉状态：{poll_text}。
    {'当前环境适宜授粉，建议保持监测。' if '✅' in temp_alert and '✅' in hum_alert else '当前环境不适宜授粉，请调整环境参数。'}
    """
    st.info(summary)

# 8. 自动刷新（每10秒刷新，可自定义）
st.markdown(f"""
    <meta http-equiv="refresh" content="10">
    <p style='text-align:center;color:#999;font-size:12px;'>页面将每10秒自动刷新 | 最后刷新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
""", unsafe_allow_html=True)