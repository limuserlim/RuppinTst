import importlib
import streamlit as st
import looz           # המוח המקומי החדש
import quest          # בונה השאלונים
import update_headers # עדכון כותרות

# --- הגדרת העמוד ---
st.set_page_config(page_title="מערכת ניהול רופין", page_icon="🎓", layout="centered")

# ==========================================
# ממשק משתמש ראשי (GUI)
# ==========================================

st.title("🎓 ניהול מערכת שעות")

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
            st.toast("התהליך התחיל...", icon="🚦")
            
            # אזור תצוגת לוגים בזמן אמת
            status_box = st.empty()
            status_box.info("🔄 טוען את המוח העדכני...")

            try:
                # 1. רענון כפוי של הקוד (פותר את בעיית הזיכרון)
                importlib.reload(looz)
                status_box.info("✅ המוח נטען בהצלחה. מעבד נתונים...")
                
                # 2. איפוס קבצים
                courses_file.seek(0)
                avail_file.seek(0)
                
                # 3. הרצת המוח עם ספינר
                with st.spinner("🤖 המוח עובד... נא להמתין"):
                    looz.main_process(courses_file, avail_file)
                
                # 4. הודעת סיום (אם המוח לא הדפיס כלום)
                status_box.success("🏁 התהליך הסתיים! (גלול למטה לתוצאות)")
                
            except Exception as e:
                status_box.error("❌ התרחשה שגיאה!")
                st.error(f"שגיאה קריטית: {e}")
                st.exception(e)
        else:
            st.error("⚠️ עצור! חובה להעלות את שני הקבצים לפני ההתחלה.")

# --- אפשרות 2: שאלון ---
elif action == "בנה לי שאלון":
    quest.run()

# --- אפשרות 3: עדכון כותרות ---
elif action == "עדכן שמות שדות קובץ תשובות":
    update_headers.run()
