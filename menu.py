import importlib
import streamlit as st
import sys
import traceback

# --- אתחול Session State ---
if "looz_active" not in st.session_state:
    st.session_state.looz_active = False

# --- ייבוא מודולים בטוח ---
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

# --- הגדרת העמוד ---
st.set_page_config(page_title="מערכת ניהול רופין", page_icon="🎓", layout="centered")

# ==========================================
# ממשק משתמש ראשי (GUI)
# ==========================================

st.title("🎓 ניהול מערכת שעות")

# תפריט בחירה
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
        
        # בחירת עוצמת אופטימיזציה
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
        
        # כפתור ההפעלה - מפעיל את הדגל ב-Session State
        if st.button("התחל בבניית המערכת 🚀", type="primary", use_container_width=True):
            if courses_file and avail_file:
                st.session_state.looz_active = True
                # איפוס היסטוריית צ'אט בהרצה חדשה
                if "gemini_chat" in st.session_state:
                    del st.session_state.gemini_chat
                if "chat_history" in st.session_state:
                    del st.session_state.chat_history
            else:
                st.error("⚠️ חובה להעלות את שני הקבצים לפני ההתחלה.")

        # לוגיקה שרצה אם הדגל פעיל (גם אחרי רענון של הצ'אט)
        if st.session_state.looz_active:
            if courses_file and avail_file:
                try:
                    # טעינה מחדש ליתר ביטחון
                    importlib.reload(looz)
                    
                    # הרצת המוח (הפונקציה ב-looz.py)
                    # הפונקציה ב-looz.py צריכה לדעת לנהל את ה-UI שלה בעצמה,
                    # כולל הצגת הצ'אט בסוף.
                    looz.main_process(courses_file, avail_file, iterations)
                    
                except Exception as e:
                    st.error("❌ התרחשה שגיאה בזמן הריצה:")
                    st.error(e)
                    st.session_state.looz_active = False # כיבוי במקרה תקלה
            else:
                st.warning("נראה שהקבצים הוסרו. אנא העלה אותם מחדש ולחץ על התחל.")
                st.session_state.looz_active = False

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
    try:
        import update_headers
        importlib.reload(update_headers)

        if hasattr(update_headers, 'run'):
            update_headers.run()
        elif hasattr(update_headers, 'main_process'):
            update_headers.main_process()
        elif hasattr(update_headers, 'main'):
            update_headers.main()
        else:
            st.warning("הקובץ update_headers.py נטען בהצלחה, אך לא נמצאה בו פונקציית הפעלה.")

    except ImportError as e:
        st.error(f"❌ שגיאת ייבוא: {e}")
        st.info("ודאי שכל הספריות הנדרשות בקובץ זה מותקנות ב-requirements.txt.")
        
    except SyntaxError as e:
        st.error("❌ יש שגיאת תחביר (Syntax Error) בתוך הקובץ update_headers.py:")
        st.code(e)
        
    except Exception as e:
        st.error("❌ שגיאה כללית בטעינת הקובץ:")
        st.code(traceback.format_exc())

# --- מקרה ברירת מחדל ---
elif action is None:
    st.info("⬆️ אנא בחר אחת מהאפשרויות למעלה כדי להתחיל לעבוד.")
