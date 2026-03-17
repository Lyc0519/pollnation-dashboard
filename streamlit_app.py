import streamlit as st
import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import json
import time
import os
from io import BytesIO

# ===================== 基础配置 =====================
# 页面配置
st.set_page_config(
    page_title="智能授粉机器人物联网可视化平台",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 设置中文字体和图表样式
plt.rcParams['font.sans-serif'] = ['SimHei']  # 解决中文显示
plt.rcParams['axes.unicode_minus'] = False
plt.style.use('seaborn-v0_8-bright')

# ===================== 密钥配置（从Secrets/环境变量读取） =====================
# Adafruit IO配置
ADAFRUIT_USERNAME = st.secrets.get("ADAFRUIT_USERNAME") or os.getenv("ADAFRUIT_USERNAME")
ADAFRUIT_KEY = st.secrets.get("ADAFRUIT_KEY") or os.getenv("ADAFRUIT_KEY")
ADAFRUIT_FEEDS = {
    "temperature": "temperature",
    "humidity": "humidity",
    "pollination-status": "pollination-status"
}

# 豆包AI配置
DOUBAO_CLIENT_ID = st.secrets.get("DOUBAO_CLIENT_ID") or os.getenv("DOUBAO_CLIENT_ID")
DOUBAO_CLIENT_SECRET = st.secrets.get("DOUBAO_CLIENT_SECRET") or os.getenv("DOUBAO_CLIENT_SECRET")
DOUBAO_API_URL = "https://www.doubao.com/api/v1/chat/completions"

# 环境阈值配置
TEMP_RANGE = (18, 30)  # 温度适宜范围
HUMID_RANGE = (50, 70)  # 湿度适宜范围

# ===================== 核心函数 =====================
def get_adafruit_feed_data(feed_key, limit=30):
    """
    从Adafruit IO获取指定Feed的历史数据
    :param feed_key: Feed名称（temperature/humidity/pollination-status）
    :param limit: 获取数据条数，默认30条
    :return: 包含value和created_at的DataFrame
    """
    if not ADAFRUIT_USERNAME or not ADAFRUIT_KEY:
        st.error("❌ Adafruit IO密钥未配置！请在Streamlit Secrets中设置ADAFRUIT_USERNAME和ADAFRUIT_KEY")
        return pd.DataFrame()
    
    url = f"https://io.adafruit.com/api/v2/{ADAFRUIT_USERNAME}/feeds/{feed_key}/data"
    params = {"limit": limit}
    headers = {"X-AIO-Key": ADAFRUIT_KEY}
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()  # 抛出HTTP错误
        data = response.json()
        
        # 转换为DataFrame并处理数据类型
        df = pd.DataFrame(data)
        if df.empty:
            return df
        
        # 时间格式转换
        df["created_at"] = pd.to_datetime(df["created_at"])
        # 数据类型转换
        if feed_key == "pollination-status":
            df["value"] = df["value"].astype(int)  # 0/1格式
        else:
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
        
        # 按时间升序排列（最新数据在最后）
        df = df.sort_values("created_at").reset_index(drop=True)
        return df[["created_at", "value"]]
    
    except requests.exceptions.ConnectionError:
        st.error("❌ 无法连接到Adafruit IO，请检查网络或API地址")
        return pd.DataFrame()
    except requests.exceptions.HTTPError as e:
        st.error(f"❌ Adafruit IO请求失败：{e.response.status_code} - {e.response.reason}")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"❌ 获取{feed_key}数据失败：{str(e)}")
        return pd.DataFrame()

def merge_adafruit_data(limit=30):
    """
    合并三个Feed的数据，按时间对齐
    :param limit: 获取数据条数
    :return: 合并后的DataFrame（time, temperature, humidity, pollination_status）
    """
    # 获取各Feed数据
    temp_df = get_adafruit_feed_data("temperature", limit)
    humid_df = get_adafruit_feed_data("humidity", limit)
    poll_df = get_adafruit_feed_data("pollination-status", limit)
    
    # 检查数据是否为空
    if temp_df.empty or humid_df.empty or poll_df.empty:
        st.warning("⚠️ 部分数据源为空，无法合并完整数据")
        return pd.DataFrame()
    
    # 重命名列
    temp_df.rename(columns={"value": "temperature"}, inplace=True)
    humid_df.rename(columns={"value": "humidity"}, inplace=True)
    poll_df.rename(columns={"value": "pollination_status"}, inplace=True)
    
    # 合并数据（按时间左连接）
    merged_df = temp_df.merge(humid_df, on="created_at", how="outer")
    merged_df = merged_df.merge(poll_df, on="created_at", how="outer")
    
    # 填充缺失值（前向填充+后向填充）
    merged_df = merged_df.sort_values("created_at").fillna(method="ffill").fillna(method="bfill")
    merged_df.rename(columns={"created_at": "time"}, inplace=True)
    
    # 只保留最近limit条数据
    merged_df = merged_df.tail(limit).reset_index(drop=True)
    return merged_df

def call_doubao_ai(data_df):
    """
    调用豆包AI API生成农业分析报告
    :param data_df: 合并后的传感器数据DataFrame
    :return: AI分析结果字符串
    """
    if not DOUBAO_CLIENT_ID or not DOUBAO_CLIENT_SECRET:
        st.error("❌ 豆包API密钥未配置！请在Streamlit Secrets中设置DOUBAO_CLIENT_ID和DOUBAO_CLIENT_SECRET")
        return ""
    
    if data_df.empty:
        st.warning("⚠️ 数据为空，无法生成AI分析报告")
        return ""
    
    # 数据统计整理
    latest_temp = data_df["temperature"].iloc[-1]
    latest_humid = data_df["humidity"].iloc[-1]
    total_records = len(data_df)
    pollinated_count = data_df["pollination_status"].sum()
    pollination_rate = (pollinated_count / total_records) * 100 if total_records > 0 else 0
    avg_temp = data_df["temperature"].mean()
    avg_humid = data_df["humidity"].mean()
    
    # 构造提示词
    prompt = f"""
    你是专业的农业物联网分析师，现在需要分析作物授粉环境数据，要求如下：
    1. 分析范围：基于最近{total_records}条传感器数据
    2. 核心数据：
       - 实时温度：{latest_temp}℃（适宜范围{TEMP_RANGE[0]}-{TEMP_RANGE[1]}℃）
       - 实时湿度：{latest_humid}%RH（适宜范围{HUMID_RANGE[0]}-{HUMID_RANGE[1]}%RH）
       - 平均温度：{avg_temp:.1f}℃，平均湿度：{avg_humid:.1f}%RH
       - 授粉总记录数：{total_records}，已授粉次数：{pollinated_count}，授粉完成率：{pollination_rate:.1f}%
    3. 输出要求：
       - 分4个部分：环境适宜性判断、温湿度趋势解读、授粉效果分析、农业操作建议
       - 每部分用分点说明，总字数≤500字
       - 语言专业但易懂，符合农业生产实际
       - 重点指出异常数据和改进方向
    """
    
    # 构造API请求参数
    headers = {
        "Content-Type": "application/json",
        "Client-ID": DOUBAO_CLIENT_ID,
        "Client-Secret": DOUBAO_CLIENT_SECRET
    }
    payload = {
        "model": "doubao-pro",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1000,
        "temperature": 0.7
    }
    
    try:
        response = requests.post(DOUBAO_API_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()
    
    except requests.exceptions.ConnectionError:
        st.error("❌ 无法连接到豆包API，请检查网络")
        return ""
    except KeyError:
        st.error("❌ 豆包API返回格式异常，请检查响应内容")
        return ""
    except Exception as e:
        st.error(f"❌ 调用豆包AI失败：{str(e)}")
        return ""

def export_to_excel(data_df):
    """
    将数据导出为Excel文件
    :param data_df: 要导出的DataFrame
    :return: BytesIO对象（Excel文件）
    """
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        # 主数据sheet
        data_df.to_excel(writer, sheet_name="授粉环境数据", index=False)
        # 统计数据sheet
        stats_df = pd.DataFrame({
            "指标": ["总记录数", "已授粉次数", "授粉完成率(%)", "平均温度(℃)", "平均湿度(%RH)"],
            "数值": [
                len(data_df),
                data_df["pollination_status"].sum(),
                round((data_df["pollination_status"].sum()/len(data_df))*100, 1) if len(data_df) > 0 else 0,
                round(data_df["temperature"].mean(), 1) if len(data_df) > 0 else 0,
                round(data_df["humidity"].mean(), 1) if len(data_df) > 0 else 0
            ]
        })
        stats_df.to_excel(writer, sheet_name="数据统计", index=False)
    output.seek(0)
    return output

def get_status_style(value, min_range, max_range):
    """
    根据数值和阈值返回状态样式（颜色/提示）
    :param value: 监测值
    :param min_range: 最小值阈值
    :param max_range: 最大值阈值
    :return: 状态文本、文本颜色、背景色
    """
    if pd.isna(value):
        return "数据缺失", "#666666", "#f0f0f0"
    elif value < min_range:
        return f"偏低（适宜{min_range}-{max_range}）", "#ff6b6b", "#ffebee"
    elif value > max_range:
        return f"偏高（适宜{min_range}-{max_range}）", "#ff6b6b", "#ffebee"
    else:
        return f"适宜（{min_range}-{max_range}）", "#2e7d32", "#e8f5e9"

# ===================== 页面渲染 =====================
def main():
    # 页面标题
    st.title("🌱 智能授粉机器人物联网可视化平台")
    st.markdown("---")
    
    # 自动刷新（每10秒）
    st_autorefresh = st.empty()
    st_autorefresh.markdown(f"""
        <meta http-equiv="refresh" content="10">
        <p style="color:#666; font-size:12px;">最后刷新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}（页面每10秒自动刷新）</p>
    """, unsafe_allow_html=True)
    
    # 1. 实时数据区
    st.subheader("📊 实时环境数据")
    data_df = merge_adafruit_data(limit=30)
    
    if not data_df.empty:
        # 获取最新数据
        latest_data = data_df.iloc[-1]
        latest_temp = latest_data["temperature"]
        latest_humid = latest_data["humidity"]
        latest_poll = latest_data["pollination_status"]
        
        # 实时数据卡片（三列布局）
        col1, col2, col3 = st.columns(3)
        
        # 温度卡片
        temp_status, temp_color, temp_bg = get_status_style(latest_temp, TEMP_RANGE[0], TEMP_RANGE[1])
        with col1:
            st.markdown(f"""
                <div style="background-color:{temp_bg}; padding:20px; border-radius:10px; box-shadow:0 2px 4px rgba(0,0,0,0.1);">
                    <h4 style="margin:0; color:#333;">🌡️ 实时温度</h4>
                    <p style="font-size:32px; margin:10px 0; color:#e53935;">{latest_temp:.1f} ℃</p>
                    <p style="margin:0; color:{temp_color}; font-weight:500;">{temp_status}</p>
                </div>
            """, unsafe_allow_html=True)
        
        # 湿度卡片
        humid_status, humid_color, humid_bg = get_status_style(latest_humid, HUMID_RANGE[0], HUMID_RANGE[1])
        with col2:
            st.markdown(f"""
                <div style="background-color:{humid_bg}; padding:20px; border-radius:10px; box-shadow:0 2px 4px rgba(0,0,0,0.1);">
                    <h4 style="margin:0; color:#333;">💧 实时湿度</h4>
                    <p style="font-size:32px; margin:10px 0; color:#00acc1;">{latest_humid:.1f} %RH</p>
                    <p style="margin:0; color:{humid_color}; font-weight:500;">{humid_status}</p>
                </div>
            """, unsafe_allow_html=True)
        
        # 授粉状态卡片
        poll_text = "已授粉" if latest_poll == 1 else "未授粉"
        poll_color = "#2e7d32" if latest_poll == 1 else "#e53935"
        poll_bg = "#e8f5e9" if latest_poll == 1 else "#ffebee"
        with col3:
            st.markdown(f"""
                <div style="background-color:{poll_bg}; padding:20px; border-radius:10px; box-shadow:0 2px 4px rgba(0,0,0,0.1);">
                    <h4 style="margin:0; color:#333;">🌼 授粉状态</h4>
                    <p style="font-size:32px; margin:10px 0; color:{poll_color};">{poll_text}</p>
                    <p style="margin:0; color:#666; font-weight:500;">状态码：{int(latest_poll)}（1=已授粉/0=未授粉）</p>
                </div>
            """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # 2. 趋势图表区
        st.subheader("📈 数据趋势分析")
        chart_col1, chart_col2 = st.columns(2)
        
        # 温湿度趋势图
        with chart_col1:
            fig, ax1 = plt.subplots(figsize=(10, 6))
            
            # 温度折线（左轴）
            ax1.plot(data_df["time"], data_df["temperature"], color="#e53935", linewidth=2, label="温度(℃)")
            ax1.set_xlabel("时间", fontsize=10)
            ax1.set_ylabel("温度 (℃)", color="#e53935", fontsize=10)
            ax1.tick_params(axis="y", labelcolor="#e53935")
            ax1.axhline(y=TEMP_RANGE[0], color="#e53935", linestyle="--", alpha=0.5, label=f"适宜下限{TEMP_RANGE[0]}℃")
            ax1.axhline(y=TEMP_RANGE[1], color="#e53935", linestyle="--", alpha=0.5, label=f"适宜上限{TEMP_RANGE[1]}℃")
            
            # 湿度折线（右轴）
            ax2 = ax1.twinx()
            ax2.plot(data_df["time"], data_df["humidity"], color="#00acc1", linewidth=2, label="湿度(%RH)")
            ax2.set_ylabel("湿度 (%RH)", color="#00acc1", fontsize=10)
            ax2.tick_params(axis="y", labelcolor="#00acc1")
            ax2.axhline(y=HUMID_RANGE[0], color="#00acc1", linestyle="--", alpha=0.5, label=f"适宜下限{HUMID_RANGE[0]}%RH")
            ax2.axhline(y=HUMID_RANGE[1], color="#00acc1", linestyle="--", alpha=0.5, label=f"适宜上限{HUMID_RANGE[1]}%RH")
            
            # 图表样式优化
            fig.autofmt_xdate()  # 旋转x轴标签
            ax1.grid(True, alpha=0.3)
            ax1.set_title("温湿度变化趋势（最近30条）", fontsize=12, fontweight="bold")
            
            # 合并图例
            lines1, labels1 = ax1.get_legend_handles_labels()
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right", fontsize=8)
            
            st.pyplot(fig)
        
        # 授粉状态趋势图
        with chart_col2:
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.plot(data_df["time"], data_df["pollination_status"], color="#43a047", linewidth=2, marker="o", markersize=4)
            ax.set_xlabel("时间", fontsize=10)
            ax.set_ylabel("授粉状态（1=已授粉/0=未授粉）", color="#43a047", fontsize=10)
            ax.set_ylim(-0.1, 1.1)
            ax.set_yticks([0, 1])
            ax.set_yticklabels(["未授粉", "已授粉"])
            ax.grid(True, alpha=0.3)
            ax.set_title("授粉状态变化（最近30条）", fontsize=12, fontweight="bold")
            fig.autofmt_xdate()
            st.pyplot(fig)
        
        st.markdown("---")
        
        # 3. 数据统计区
        st.subheader("📊 核心数据统计")
        total_records = len(data_df)
        pollinated_count = int(data_df["pollination_status"].sum())
        pollination_rate = (pollinated_count / total_records) * 100 if total_records > 0 else 0
        
        stat_col1, stat_col2, stat_col3 = st.columns(3)
        with stat_col1:
            st.metric(label="总记录数", value=total_records)
        with stat_col2:
            st.metric(label="已授粉次数", value=pollinated_count)
        with stat_col3:
            st.metric(label="授粉完成率", value=f"{pollination_rate:.1f}%")
        
        st.markdown("---")
        
        # 4. 豆包AI分析区
        st.subheader("🤖 豆包AI智能分析报告")
        if st.button("生成豆包智能分析报告", type="primary"):
            with st.spinner("AI正在分析数据，请稍候..."):
                ai_result = call_doubao_ai(data_df)
                if ai_result:
                    st.markdown("### 分析结果：")
                    st.write(ai_result)
                else:
                    st.warning("⚠️ 未能生成AI分析报告，请检查配置或数据")
        
        st.markdown("---")
        
        # 5. 数据导出区
        st.subheader("💾 数据导出")
        export_col1, export_col2 = st.columns([1, 0.2])
        with export_col1:
            st.write("导出所有温湿度和授粉状态数据为Excel文件（包含原始数据和统计信息）")
        with export_col2:
            excel_file = export_to_excel(data_df)
            filename = f"授粉环境数据_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            st.download_button(
                label="导出Excel",
                data=excel_file,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    else:
        st.warning("⚠️ 暂无有效数据，请检查Adafruit IO连接或数据源")

if __name__ == "__main__":
    main()