import streamlit as st
import looz           # המוח המקומי החדש
import quest          # בונה השאלונים
import update_headers # עדכון כותרות

# --- הגדרת העמוד ---
st.set_page_config(page_title="מערכת ניהול רופין", page_icon="🎓", layout="centered")

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
    st.caption("המערכת מריצה את הלוגיקה המקומית (קובץ looz.py).")
    
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
            # --- קריאה ישירה לקובץ המקומי ---
            try:
                looz.main_process(courses_file, avail_file)
            except Exception as e:
                st.error(f"שגיאה בהרצת המערכת: {e}")
                st.write("פרטי שגיאה למפתח:")
                st.exception(e)
        else:
            st.error("⚠️ עצור! חובה להעלות את שני הקבצים (קורסים וזמינות) לפני ההתחלה.")

# --- אפשרות 2: שאלון ---
elif action == "בנה לי שאלון":
    quest.run()

# --- אפשרות 3: עדכון כותרות ---
elif action == "עדכן שמות שדות קובץ תשובות":
    update_headers.run()
