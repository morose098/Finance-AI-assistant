import streamlit as st
import akshare as ak
import pandas as pd
import datetime
import os
from openai import OpenAI


# ================= 0. 屏蔽系统代理 =================
os.environ['http_proxy'] = ''
os.environ['https_proxy'] = ''
os.environ['HTTP_PROXY'] = ''
os.environ['HTTPS_PROXY'] = ''

# ================= 1. 页面及内存状态设置 =================
st.set_page_config(page_title="AI 财报分析助手", page_icon="📈", layout="wide")
st.title("📈 AI 财报智能分析助手")
st.markdown("输入 A 股公司名称或代码，抓取全量财务数据，自由挑选核心指标生成专属 AI 研报。")

if 'core_data' not in st.session_state:
    st.session_state.core_data = None
if 'stock_info' not in st.session_state:
    st.session_state.stock_info = {}

# ================= 2. 核心引擎：智能名称映射 (本地极速免封锁版) =================
@st.cache_data(ttl=86400) # 缓存一天，极速读取
def load_stock_mapping():
    try:
        # 直接读取咱们刚刚传到云端的本地 CSV 文件，不再跨国联网！
        # 注意：一定要加 dtype=str，防止像 000001 这样的代码开头的 0 被吃掉
        df = pd.read_csv("stock_codes.csv", dtype=str) 
        
        name_to_code = dict(zip(df['name'], df['code']))
        code_to_name = dict(zip(df['code'], df['name']))
        return name_to_code, code_to_name
    except Exception as e:
        print(f"本地股票字典读取失败: {e}")
        return {}, {}

def get_market_prefix(code):
    if code.startswith('6'): return f"SH{code}"
    if code.startswith('0') or code.startswith('3'): return f"SZ{code}"
    if code.startswith('8') or code.startswith('4'): return f"BJ{code}"
    return code

# ================= 3. 侧边栏：获取数据 =================
st.sidebar.header("⚙️ 第一步：获取数据")
name_to_code, code_to_name = load_stock_mapping()
user_input = st.sidebar.text_input("请输入公司名称或代码", value="贵州茅台")
current_year = datetime.datetime.now().year
start_year, end_year = st.sidebar.slider(
    "选择要分析的财报年份范围", 
    min_value=2015, 
    max_value=current_year, 
    value=(2020, current_year), 
    step=1
)

fetch_button = st.sidebar.button("⬇️ 抓取全量财务数据", type="primary")

# ================= 4. 数据抓取与解析 =================
if fetch_button:
    if not user_input:
        st.sidebar.warning("请先输入股票名称或代码！")
        st.stop()

    stock_code, stock_name = "", ""
    user_input = user_input.strip()
    
    # --- 升级后的智能匹配逻辑 ---
    if user_input.isdigit() and len(user_input) == 6:
        # 如果输入的是 6 位纯数字，直接当代码处理
        stock_code = user_input
        stock_name = code_to_name.get(user_input, "未知名称")
    else:
        # 如果输入的是汉字，进行名称匹配
        if name_to_code:
            if user_input in name_to_code:
                # 精确匹配成功
                stock_code = name_to_code[user_input]
                stock_name = user_input
            else:
                # 模糊匹配：比如输入"茅台"，自动找"贵州茅台"
                matched = False
                for name, code in name_to_code.items():
                    if user_input in name:
                        stock_code = code
                        stock_name = name
                        matched = True
                        st.sidebar.info(f"💡 模糊搜索成功：已自动匹配为 {stock_name} ({stock_code})")
                        break
                
                if not matched:
                    st.sidebar.error(f"❌ 在A股列表中找不到包含“{user_input}”的股票，请检查是否有错别字。")
                    st.stop()
        else:
            st.sidebar.error("⚠️ 股票代码本加载失败，请尝试刷新页面。")
            st.stop()
        
    full_code = get_market_prefix(stock_code)
    
    with st.spinner(f"正在抓取 {stock_name} 的历年财务大表..."):
        try:
            df = ak.stock_profit_sheet_by_report_em(symbol=full_code)
            df['REPORT_DATE'] = df['REPORT_DATE'].astype(str)
            annual_df = df[df['REPORT_DATE'].str.contains('12-31')].copy()
            annual_df['年份'] = annual_df['REPORT_DATE'].str[:4].astype(int)
            annual_df = annual_df[(annual_df['年份'] >= start_year) & (annual_df['年份'] <= end_year)]
            
            if annual_df.empty:
                st.error(f"⚠️ 未找到相关年报数据。")
                st.session_state.core_data = None
                st.stop()
                
            annual_df = annual_df.sort_values('年份', ascending=False)
            
            core_data = pd.DataFrame()
            core_data['报告期'] = annual_df['REPORT_DATE'].str[:10]
            
            # --- 升级版：动态指标字典（涵盖一般企业与金融类） ---
            metric_mapping = {
                'TOTAL_OPERATE_INCOME': '营业总收入',
                'OPERATE_INCOME': '营业收入',
                'TOTAL_OPERATE_COST': '营业总成本',
                'OPERATE_COST': '营业支出/成本',
                'SALE_EXPENSE': '销售费用',
                'MANAGE_EXPENSE': '管理费用',
                'RESEARCH_EXPENSE': '研发费用',
                'FINANCE_EXPENSE': '财务费用',
                'OPERATE_PROFIT': '营业利润',
                'TOTAL_PROFIT': '利润总额',
                'PARENT_NETPROFIT': '归母净利润',
                'NETPROFIT': '净利润',
                'DEDUCT_PARENT_NETPROFIT': '扣非净利润',
                'BASIC_EPS': '基本每股收益',
                'INVEST_INCOME': '投资收益',
                'FAIR_VALUE_CHANGE_INCOME': '公允价值变动收益',
                'CREDIT_IMPAIRMENT_LOSS': '信用减值损失',
                'INCOME_TAX': '所得税费用',
                # 金融/保险/银行特有
                'EARNED_PREMIUM': '已赚保费',
                'SURRENDER_VALUE': '退保金',
                'NET_COMPENSATE_EXPENSE': '赔付支出净额',
                'INTEREST_INCOME': '利息净收入',
                'FEE_COMMISSION_INCOME': '手续费及佣金净收入'
            }
            
            # 定义一个“黑名单”，把不需要给小白看的系统级无关字段屏蔽掉
            exclude_cols = ['SECUCODE', 'SECURITY_CODE', 'SECURITY_NAME_ABBR', 'ORG_CODE', 
                            'REPORT_DATE', 'NOTICE_DATE', 'UPDATE_DATE', 'CURRENCY', 'REPORT_TYPE', '年份']
            
            # ⭐️ 核心动态逻辑：爬虫抓到什么，只要不在黑名单里，我们就塞进去什么！
            for col in annual_df.columns:
                if col not in exclude_cols:
                    # 如果字典里有翻译，就用中文名；如果没有，就直接原封不动用它的原始字段名！
                    cn_name = metric_mapping.get(col, col) 
                    core_data[cn_name] = annual_df[col]
            
            st.session_state.core_data = core_data
            st.session_state.stock_info = {'name': stock_name, 'code': stock_code, 'start': start_year, 'end': end_year}
            
            st.sidebar.success("🎉 数据抓取成功！请在右侧选择指标并分析。")
            
        except Exception as e:
            st.sidebar.error(f"处理数据时发生错误: {e}")

# ================= 5. 指标勾选、可视化与 AI 分析区 =================
if st.session_state.core_data is not None:
    core_data = st.session_state.core_data
    stock_info = st.session_state.stock_info
    
    st.divider()
    st.subheader(f"📊 第二步：定制 {stock_info['name']} ({stock_info['code']}) 分析维度")
    
    available_metrics = list(core_data.columns)[1:]
    default_selections = [m for m in available_metrics if '收入' in m or '利润' in m][:2]
    if not default_selections:
        default_selections = available_metrics[:2]

    selected_metrics = st.multiselect(
        "👉 请从下方点击或输入，自由挑选你想查看和分析的财务指标：",
        options=available_metrics,
        default=default_selections
    )
    
    if not selected_metrics:
        st.warning("请至少选择一项指标才能进行展示和分析。")
        st.stop()
        
    final_data = core_data[['报告期'] + selected_metrics]
    
    st.markdown("### 📈 选定指标趋势图 (单位：百亿元)")
    chart_data = final_data.set_index('报告期').sort_index(ascending=True)
    chart_data = chart_data / 10000000000
    st.line_chart(chart_data)
    
    st.markdown("### 🧮 数据明细表 (原始金额：元)")
    st.dataframe(final_data, use_container_width=True)
    
    st.divider()
    
    # ---------- 模型选择与切换 ----------
    st.markdown("### 🧠 第三步：选择 AI 大模型并生成研报")
    
    # 【改动1】：在选项里加入 腾讯混元
    selected_model = st.radio(
        "请选择为你撰写研报的 AI 引擎：",
        options=["DeepSeek (深度求索)", "Doubao (字节豆包)", "Qwen (通义千问)", "Hunyuan (腾讯混元)"],
        horizontal=True
    )
    
    ai_button = st.button(f"🤖 使用 {selected_model.split()[0]} 一键生成专属研报", type="primary", use_container_width=True)
    
    if ai_button:
        st.subheader(f"🤖 {selected_model.split()[0]} 深度定制解读")
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            message_placeholder.markdown(f"正在唤醒 **{selected_model}** 进行深度思考，请稍候...")
            
            try:
                data_str = final_data.to_markdown(index=False)
                system_prompt = "你是一位资深的 A 股财务分析师。请用通俗易懂、专业的金融研报风格输出最终报告。必须使用 Markdown 格式排版，重点数据加粗。"
                metrics_str = "、".join(selected_metrics)
                user_prompt = f"""
                请分析以下 {stock_info['name']} ({stock_info['code']}) 从 {stock_info['start']} 年到 {stock_info['end']} 年的定制化财务数据（表格中金额单位为“元”）：
                
                {data_str}
                
                请执行以下深度分析：
                1. 专项趋势解读：重点针对我为你提取的这几个指标：【{metrics_str}】，简述它们的整体变化趋势。
                2. 数据关联挖掘：观察这几个指标之间的相互关系（例如收入与成本比例、或某项费用的突增），发现异常波动或亮点，并推测背后的经营逻辑。
                3. 综合诊断：结合这些特定的指标维度，给出一段专业的总结评价。
                """

                # ================= 【核心逻辑】：If-Else 模型分支 =================
                if selected_model == "DeepSeek (深度求索)":
                    client = OpenAI(
                        api_key=st.secrets["DEEPSEEK_API_KEY"], 
                        base_url="https://api.deepseek.com"
                    )
                    response = client.chat.completions.create(
                        model="deepseek-chat", 
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        temperature=0.1,
                        stream=False
                    )
                    full_response = response.choices[0].message.content

                elif selected_model == "Doubao (字节豆包)":
                    client = OpenAI(
                        api_key=st.secrets["DOUBAO_API_KEY"], # ⚠️ 记得填回你的豆包 API KEY
                        base_url="https://ark.cn-beijing.volces.com/api/v3"
                    )
                    response = client.chat.completions.create(
                        model="doubao-seed-2-0-pro-260215", 
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        temperature=0.1
                    )
                    full_response = response.choices[0].message.content
                
                elif selected_model == "Qwen (通义千问)":
                    client = OpenAI(
                        api_key=st.secrets["QWEN_API_KEY"], # ⚠️ 记得填回你的千问 API KEY
                        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
                    )
                    response = client.chat.completions.create(
                        model="qwen3.5-plus", 
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        temperature=0.1
                    )
                    full_response = response.choices[0].message.content
                    
                elif selected_model == "Hunyuan (腾讯混元)":
                    # --- 【改动2】：新增调用 腾讯混元 ---
                    client = OpenAI(
                        api_key=st.secrets["HUNYUAN_API_KEY"],
                        #api_key="sk-jLsqvGE2zF2WerLLRypTri3lHuSppuXcvv11Ebm4Pr9aKDXq", # ⚠️ 必填：替换为你的混元 API KEY
                        base_url="https://api.hunyuan.cloud.tencent.com/v1"
                    )
                    response = client.chat.completions.create(
                        model="hunyuan-turbos-latest", # 使用你提供的混元模型代号
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        temperature=0.1, # 保持严谨的温度值
                        extra_body={
                            "enable_enhancement": True,  # 混元特有的功能增强参数
                        }
                    )
                    full_response = response.choices[0].message.content
                # =================================================================

                # 最终将获取到的结果展示在网页上
                message_placeholder.markdown(full_response)
                
            except Exception as e:
                message_placeholder.error(f"{selected_model} 调用出错: {str(e)}")
