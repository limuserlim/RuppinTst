import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
import re
import importlib.util
import sys
import traceback
import quest          # בונה השאלונים
import update_headers # עדכון כותרות

# --- הגדרת העמוד ---
st.set_page_config(page_title="מערכת ניהול רופין", page_icon="🎓", layout="centered")

# ==========================================
# פונקציות ליבה: קריאה מהמוח והרצה דינמית
# ==========================================

def get_brain_from_docs():
    """מתחבר לגוגל דוקס ושואב את כל הטקסט"""
    # ה-ID של המסמך שלך
    DOCUMENT_ID = '1zg7q93__eHUJ849z1Mi-JOJpS1ImqkeDdipMmTONUfM'

    try:
        # בדיקה שיש לנו את הסודות
        if "gcp_service_account" not in st.secrets:
            st.error("❌ חסרים פרטי התחברות (gcp_service_account) ב-secrets.toml")
            return ""

        # התחברות לגוגל
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        
        creds = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=["https://www.googleapis.com/auth/documents.readonly"]
        )
        service = build('docs', 'v1', credentials=creds)

        # קריאת המסמך
        document = service.documents().get(documentId=DOCUMENT_ID).execute()
        
        # חילוץ הטקסט הנקי
        full_text = ""
        content = document.get('body').get('content')
        for element in content:
            if 'paragraph' in element:
                elements = element.get('paragraph').get('elements')
                for elem in elements:
                    if 'textRun' in elem:
                        full_text += elem.get('textRun').get('content')
        
        return full_text

    except Exception as e:
        st.error(f"שגיאה בקריאת ההוראות מהמסמך: {e}")
        return ""

def execute_code_from_brain(courses_file, avail_file):
    """
    1. קורא את הטקסט מהדוק
    2. מוצא את קוד הפייתון בתוכו
    3. מריץ אותו על הקבצים
    """

    # 1. קריאת הטקסט
    with st.spinner("🧠 יוצר קשר עם המוח (Google Docs)..."):
        doc_content = get_brain_from_docs()

    if not doc_content:
        return 

    # 2. חילוץ קוד הפייתון (החלק החשוב שביקשת!)
    # מחפש טקסט שנמצא בין ```python לבין ```
    code_match = re.search(r'```python(.*?)```', doc_content, re.DOTALL)

    if not code_match:
        st.error("❌ שגיאה: המערכת לא מצאה קוד פייתון תקין במסמך המוח.")
        st.warning("נא לוודא שבמסמך הגוגל דוק, הקוד עטוף ב- ```python בהתחלה ו- ``` בסוף.")
        return

    code_content = code_match.group(1)

    # 3. שמירת הקוד לקובץ זמני מקומי
    brain_filename = "dynamic_brain.py"
    try:
        with open(brain_filename, "w", encoding="utf-8") as f:
            f.write(code_content)
    except Exception as e:
        st.error(f"שגיאה בשמירת קובץ המוח הזמני: {e}")
        return

    # 4. טעינה והרצה של הקוד החדש
    try:
        # טעינה דינמית - גורם לפייתון להכיר את הקובץ החדש שיצרנו
        spec = importlib.util.spec_from_file_location("dynamic_brain", brain_filename)
        dynamic_module = importlib.util.module_from_spec(spec)
        sys.modules["dynamic_brain"] = dynamic_module
        spec.loader.exec_module(dynamic_module)

        # הרצת הפונקציה הראשית (main_process) שנמצאת בתוך הקוד במוח
        st.toast("🚀 המוח נטען בהצלחה! מתחיל עיבוד...", icon="🤖")
        
        if hasattr(dynamic_module, 'main_process'):
            # שליחת הקבצים למוח
            dynamic_module.main_process(courses_file, avail_file)
        else:
            st.error("הקוד במוח תקין, אך חסרה בו הפונקציה 'main_process(courses, avail)'.")

    except Exception as e:
        st.error("💥 שגיאה בזמן הרצת הקוד מהמוח:")
        st.code(str(e))
        with st.expander("פרטי שגיאה מלאים (Traceback)"):
            st.text(traceback.format_exc())

# ==========================================
# ממשק משתמש ראשי (GUI)
# ==========================================

st.title("🎓 מערכת ניהול מערכת שעות")

# תפריט בחירה
action = st.radio("בחר כלי לעבודה:", 
                  ["בנה לי מערכת (LOOZ)", "בנה לי שאלון", "עדכן שמות שדות קובץ תשובות"], 
                  horizontal=True)
st.markdown("---")

# --- אפשרות 1: מערכת שעות (LOOZ) ---
if action == "בנה לי מערכת (LOOZ)":
    st.header("🤖 הבוט LOOZ")
    st.caption("המערכת מושכת את הלוגיקה העדכנית ביותר מגוגל דוקס בזמן אמת.")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 1. קובץ קורסים")
        courses_file = st.file_uploader("העלה קובץ (Excel/CSV)", type=['xlsx', 'csv'], key="courses")
        
    with col2:
        st.markdown("### 2. קובץ זמינות")
        avail_file = st.file_uploader("העלה קובץ (Excel/CSV)", type=['xlsx', 'csv'], key="avail")

    st.markdown("<br>", unsafe_allow_html=True)
    
    # כפתור ההפעלה
    if st.button("התחל בבניית המערכת 🚀", type="primary", use_container_width=True):
        if courses_file and avail_file:
            # קריאה לפונקציה שיצרנו למעלה
            execute_code_from_brain(courses_file, avail_file)
        else:
            st.error("⚠️ עצור! חובה להעלות את שני הקבצים (קורסים וזמינות) לפני ההתחלה.")

# --- אפשרות 2: שאלון ---
elif action == "בנה לי שאלון":
    quest.run()

# --- אפשרות 3: עדכון כותרות ---
elif action == "עדכן שמות שדות קובץ תשובות":
    update_headers.run()
