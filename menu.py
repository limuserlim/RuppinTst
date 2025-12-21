import importlib
import streamlit as st
import sys


#***********************************************************DEBUG************************************
import streamlit as st
import sys
import importlib

# --- דיבאג: ניסיון ייבוא עם הצגת שגיאה ---
try:
    import looz
except Exception as e:
    st.error(f"🔍 שגיאה בטעינת הקובץ looz.py: {e}")
    looz = None

try:
    import quest
except ImportError:
    quest = None

try:
    import update_headers
except ImportError:
    update_headers = None
#***********************************************************

# נסיון לייבא את המודולים (כדי למנוע קריסה אם קובץ חסר)
try:
    import looz
except ImportError:
    looz = None

try:
    import quest
except ImportError:
    quest = None

try:
    import update_headers
except ImportError:
    update_headers = None

# --- הגדרת העמוד ---
st.set_page_config(page_title="מערכת ניהול רופין", page_icon="🎓", layout="centered")

# ==========================================
# ממשק משתמש ראשי (GUI)
# ==========================================

st.title("🎓 ניהול מערכת שעות")

# תפריט בחירה - index=None מוודא שאין ברירת מחדל
action = st.radio(
    "בחר כלי לעבודה:",
    ["בנה לי מערכת (LOOZ)", "בנה לי שאלון", "עדכן שמות שדות קובץ תשובות"],
    index=None,
    horizontal=True
)
st.markdown("---")

# --- אפשרות 1: מערכת שעות (LOOZ) ---
if action == "בנה לי מערכת (LOOZ)":
    if looz is None:
        st.error("❌ הקובץ looz.py חסר או מכיל שגיאות.")
    else:
        st.header("🤖 הבוט LOOZ")
        st.caption("המערכת מריצה את הלוגיקה המקומית (קובץ looz.py).")
        
        # === תוספת: בחירת עוצמת אופטימיזציה ===
        iterations = st.slider(
            "מספר איטרציות לאופטימיזציה", 
            min_value=1, max_value=100, value=30, 
            help="מספר גבוה יותר ייתן תוצאה טובה יותר אך ירוץ לאט יותר."
        )
        
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
                    # 1. רענון כפוי של הקוד (חשוב לפיתוח)
                    importlib.reload(looz)
                    status_box.info("✅ המוח נטען בהצלחה. מעבד נתונים...")
                    
                    # 2. איפוס קבצים (חשוב בגלל שימוש חוזר בסטרים)
                    courses_file.seek(0)
                    avail_file.seek(0)
                    
                    # 3. הרצת המוח עם ספינר
                    with st.spinner("🤖 המוח עובד... נא להמתין"):
                        # קריאה לפונקציה הראשית ב-looz
                        looz.main_process(courses_file, avail_file, iterations)
                    
                    # 4. הודעת סיום
                    status_box.success("🏁 התהליך הסתיים! (גלול למטה לתוצאות)")
                    
                except Exception as e:
                    status_box.error("❌ התרחשה שגיאה!")
                    st.error(f"שגיאה קריטית: {e}")
                    # st.exception(e) # אפשר להפעיל לצורך דיבאג
            else:
                st.error("⚠️ חובה להעלות את שני הקבצים לפני ההתחלה.")

# --- אפשרות 2: שאלון ---
elif action == "בנה לי שאלון":
    if quest:
        try:
            quest.run()
        except AttributeError:
            st.warning("המודול quest נטען, אך לא נמצאה פונקציית run().")
    else:
        st.error("המודול 'quest' אינו זמין (קובץ חסר).")

# --- אפשרות 3: עדכון כותרות ---
elif action == "עדכן שמות שדות קובץ תשובות":
    if update_headers:
        try:
            update_headers.run()
        except AttributeError:
            st.warning("המודול update_headers נטען, אך לא נמצאה פונקציית run().")
    else:
        st.error("המודול 'update_headers' אינו זמין (קובץ חסר).")

# --- מקרה ברירת מחדל ---
elif action is None:
    st.info("⬆️ אנא בחר אחת מהאפשרויות למעלה כדי להתחיל לעבוד.")

