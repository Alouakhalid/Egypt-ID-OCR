import streamlit as st
import os
import base64
import requests
import json
import sqlite3
import datetime
import io
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

def get_api_key():
    try:
        return st.secrets["GROQ_API_KEY"]
    except Exception:
        return os.environ.get("GROQ_API_KEY", "")

def init_db():
    conn = sqlite3.connect('logs.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  timestamp TEXT,
                  status TEXT,
                  extracted_name TEXT,
                  extracted_id TEXT,
                  details TEXT)''')
    conn.commit()
    conn.close()

init_db()

def log_attempt(status, extracted_name=None, extracted_id=None, details=None):
    try:
        conn = sqlite3.connect('logs.db')
        c = conn.cursor()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO logs (timestamp, status, extracted_name, extracted_id, details) VALUES (?, ?, ?, ?, ?)",
                  (now, status, extracted_name, extracted_id, str(details) if details else None))
        conn.commit()
        conn.close()
    except Exception as e:
        pass

def update_env(key, value):
    env_path = '.env'
    lines = []
    found = False
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            lines = f.readlines()
    
    with open(env_path, 'w') as f:
        for line in lines:
            if line.startswith(f"{key}="):
                f.write(f"{key}={value}\n")
                found = True
            else:
                f.write(line)
        if not found:
            f.write(f"{key}={value}\n")
    os.environ[key] = value

st.set_page_config(page_title="Egypt ID Smart OCR", page_icon="🇪🇬", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Tajawal', sans-serif;
    }
    
    .main {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
    }
    
    .app-header {
        background: linear-gradient(90deg, #1e3c72 0%, #2a5298 100%);
        padding: 2rem 1rem;
        border-radius: 15px;
        color: white;
        text-align: center;
        margin-bottom: 2rem;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    .app-header h1 { color: white; font-weight: 800; font-size: clamp(1.8rem, 4vw, 2.5rem); margin-bottom: 0.5rem;}
    .app-header p { font-size: clamp(1rem, 2vw, 1.2rem); opacity: 0.9; }

    .rtl-container {
        direction: rtl;
        text-align: right;
    }
    
    .result-card {
        background: white;
        border-radius: 12px;
        padding: 1.5rem;
        box-shadow: 0 8px 20px rgba(0,0,0,0.05);
        border-top: 5px solid #2a5298;
        margin-bottom: 1rem;
        width: 100%;
        overflow-x: hidden;
    }
    .data-row {
        display: flex;
        flex-direction: row;
        justify-content: space-between;
        padding: 0.8rem 0;
        border-bottom: 1px solid #eee;
        flex-wrap: wrap;
    }
    .data-row:last-child { border-bottom: none; }
    .data-label { font-weight: 700; color: #555; }
    .data-value { font-weight: 600; color: #1e3c72; font-size: 1.1rem; text-align: left; }
    .null-value { color: #999; font-style: italic; }

    @media (max-width: 600px) {
        .data-row {
            flex-direction: column;
            text-align: right;
            align-items: flex-start;
        }
        .data-value {
            text-align: right;
            margin-top: 4px;
        }
    }
</style>
""", unsafe_allow_html=True)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "qwen/qwen3.6-27b"

def resize_image(image_bytes, max_size=1024):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != 'RGB': img = img.convert('RGB')
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=85)
        return output.getvalue()
    except Exception:
        return image_bytes

def bytes_to_data_url(image_bytes, mime_type="image/jpeg"):
    image_bytes = resize_image(image_bytes)
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{b64}"

def extract_id_data(front_image_bytes, back_image_bytes=None):
    api_key = get_api_key()
    if not api_key:
        return {"error": "API Key missing. Please configure it in the Admin Dashboard."}

    content = []
    prompt = (
        "This is an image of an Egyptian National ID card (Front and optionally Back). "
        "Extract all the visible information from the ID card with extreme accuracy. "
        "CRITICAL INSTRUCTION FOR ARABIC: Arabic text is read from RIGHT to LEFT. You must extract names and words in the exact correct Right-to-Left order as they appear on the card (e.g., First Name, then Father's Name, etc). DO NOT reverse the word order. "
        "CRITICAL ANTI-LOOP RULE: Do NOT overthink. Do NOT repeatedly double-check the text. Think very briefly and immediately output the JSON."
        "Respond ONLY with a valid JSON object containing the following keys in Arabic: "
        "- Name (الاسم) "
        "- Address (العنوان) "
        "- ID_Number (الرقم القومي) "
        "- Governorate (المحافظة) "
        "- Religion (الديانة) "
        "- Marital_Status (الحالة الاجتماعية) "
        "- Profession (المهنة) "
        "- Gender (النوع) - Must be 'ذكر' or 'أنثى' "
        "- Issue_Date (تاريخ الاصدار) "
        "- Expiry_Date (سارية حتى) "
        "- Spouse_Name - IMPORTANT RULE: If the gender is Male (ذكر), use the key 'اسم الزوجة' (Wife's Name). "
        "If the gender is Female (أنثى), use the key 'اسم الزوج' (Husband's Name). "
        "Read all characters carefully, especially the 14-digit national ID number. "
        "If a field is not visible, set its value to null. "
        "Do not include any explanation or think blocks, just the pure JSON string."
    )
    
    content.append({"type": "text", "text": prompt})
    
    if front_image_bytes:
        content.append({"type": "image_url", "image_url": {"url": bytes_to_data_url(front_image_bytes), "detail": "high"}})
    if back_image_bytes:
        content.append({"type": "image_url", "image_url": {"url": bytes_to_data_url(back_image_bytes), "detail": "high"}})

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.2,
        "max_tokens": 4000
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        resp = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        raw_text = resp.json()["choices"][0]["message"]["content"]
        
        import re
        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if json_match:
            raw_text = json_match.group(0)
        else:
            if "<think>" in raw_text and "</think>" in raw_text:
                raw_text = raw_text.split("</think>")[-1].strip()
            if raw_text.startswith("```json"): raw_text = raw_text[7:]
            if raw_text.startswith("```"): raw_text = raw_text[3:]
            if raw_text.endswith("```"): raw_text = raw_text[:-3]
            
        result = json.loads(raw_text.strip())
        log_attempt("Success", result.get("الاسم"), result.get("الرقم القومي"))
        return result
    except Exception as e:
        err_detail = resp.text if 'resp' in locals() else str(e)
        log_attempt("Failed", details=err_detail)
        return {"error": str(e), "details": err_detail}

st.sidebar.title("🛠️ Navigation")
page = st.sidebar.radio("اختر الصفحة (Go to):", ["🖼️ OCR App", "🔐 Admin Dashboard"])

if page == "🖼️ OCR App":
    st.markdown("""
    <div class="app-header">
        <h1>🇪🇬 البوابة الذكية لقراءة البطاقات المصرية</h1>
        <p>استخراج البيانات بدقة متناهية باستخدام تقنيات الذكاء الاصطناعي المتقدمة</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("### 📸 رفع صور البطاقة (Upload ID Images)")
    col1, col2 = st.columns(2)

    with col1:
        front_file = st.file_uploader("الوجه الأمامي (Front Side) *مطلوب", type=["jpg", "jpeg", "png", "webp"], key="front")
        if front_file: st.image(front_file, caption="الوجه الأمامي", use_container_width=True)

    with col2:
        back_file = st.file_uploader("الوجه الخلفي (Back Side) *اختياري", type=["jpg", "jpeg", "png", "webp"], key="back")
        if back_file: st.image(back_file, caption="الوجه الخلفي", use_container_width=True)

    st.markdown("<hr/>", unsafe_allow_html=True)
    
    if st.button("🚀 استخراج البيانات الآن (Extract Data)", type="primary", use_container_width=True):
        if not front_file:
            st.error("⚠️ يرجى رفع صورة الوجه الأمامي على الأقل للبدء.")
        else:
            with st.status("🤖 جاري تحليل البطاقة باستخدام الذكاء الاصطناعي...", expanded=True) as status:
                st.write("قراءة الصورة ومعالجة النصوص...")
                result_json = extract_id_data(front_file.read(), back_file.read() if back_file else None)
                
                if result_json and "error" not in result_json:
                    status.update(label="✅ اكتمل الاستخراج بنجاح!", state="complete", expanded=False)
                    st.markdown("### 📋 النتيجة المستخرجة (Extracted Data)")
                    
                    html_content = "<div class='rtl-container result-card'>"
                    for key, val in result_json.items():
                        display_val = val if val else "<span class='null-value'>غير متوفر</span>"
                        html_content += f"<div class='data-row'><span class='data-label'>{key}</span><span class='data-value'>{display_val}</span></div>"
                    html_content += "</div>"
                    st.markdown(html_content, unsafe_allow_html=True)
                        
                    st.success("✨ دقة القراءة عالية جداً")
                    json_str = json.dumps(result_json, ensure_ascii=False, indent=4)
                    st.download_button("💾 تحميل كملف JSON", file_name="id_data.json", mime="application/json", data=json_str, use_container_width=True)
                            
                else:
                    status.update(label="❌ حدث خطأ أثناء الاستخراج", state="error")
                    st.error(result_json.get("error", "Unknown Error"))
                    if "details" in result_json: st.code(result_json["details"])

elif page == "🔐 Admin Dashboard":
    st.title("🔐 Admin Dashboard")
    st.markdown("إدارة النظام والتحكم في مفاتيح الـ API وسجل العمليات.")
    
    st.subheader("🔑 API Key Configuration")
    current_key = os.environ.get("GROQ_API_KEY", "")
    masked_key = f"{current_key[:8]}...{current_key[-4:]}" if len(current_key) > 12 else "Not Set"
    st.info(f"Current Groq API Key: **{masked_key}**")
    
    new_key = st.text_input("Update Groq API Key", type="password", placeholder="gsk_...")
    if st.button("Save API Key"):
        if new_key:
            update_env("GROQ_API_KEY", new_key)
            st.success("API Key updated successfully!")
            st.rerun()
        else:
            st.warning("Please enter a valid key.")

    st.markdown("<hr/>", unsafe_allow_html=True)
    st.subheader("📜 System Logs")
    
    conn = sqlite3.connect('logs.db')
    import pandas as pd
    try:
        df = pd.read_sql_query("SELECT id, timestamp, status, extracted_name, extracted_id FROM logs ORDER BY id DESC LIMIT 50", conn)
        st.dataframe(df, use_container_width=True)
    except Exception as e:
        st.warning("No logs found yet.")
    conn.close()

