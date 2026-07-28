import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# --- לוגיקה (פונקציות עזר) ---
def get_gspread_client():
    if "gcp_service_account" not in st.secrets:
        st.error("❌ לא נמצא קובץ secrets.toml או שהוא ריק.")
        return None

    creds_dict = dict(st.secrets["gcp_service_account"])
    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    try:
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"שגיאה ביצירת הרשאות: {e}")
        return None

def update_headers_logic(sheet_name, semesters_str):
    client = get_gspread_client()
    if not client: return

    try:
        with st.spinner(f"⏳ מחפש ומתחבר לגיליון '{sheet_name}'..."):
            # כאן השינוי המרכזי: פתיחה לפי שם הקובץ במקום URL
            sheet = client.open(sheet_name)
            worksheet = sheet.get_worksheet(0)

        semesters = [s.strip() for s in semesters_str.split(',') if s.strip()]
        
        if not semesters:
            st.warning("⚠️ לא הוזנו סמסטרים תקינים.")
            return

        # יצירת הכותרות
        new_headers = []
        for sem in semesters:
            for day in range(1, 6):
                header_name = f"{day}{sem}"
                new_headers.append(header_name)

        st.info(f"✅ עומד לעדכן {len(new_headers)} עמודות.")
        
        # עדכון
        start_row = 1
        start_col = 2
        worksheet.update(
            range_name=f"{gspread.utils.rowcol_to_a1(start_row, start_col)}", 
            values=[new_headers]
        )
            
        st.success(f"🎉 בוצע בהצלחה! הכותרות עודכנו בגיליון.")
        st.balloons()

    # טיפול ספציפי למקרה שהקובץ לא נמצא או לא שותף
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(f"❌ שגיאה: הקובץ '{sheet_name}' לא נמצא! האם שיתפת אותו עם חשבון השירות (Service Account)?")
    except Exception as e:
        st.error(f"❌ שגיאה כללית: {e}")

# --- הפונקציה הראשית שהתפריט יפעיל ---
def run():
    st.header("🛠️ עדכון כותרות בגיליון ציונים")
    st.markdown("כלי זה משנה את שמות העמודות בגיליון (החל מעמודה 2) לפי הסמסטרים המוזנים.")

    with st.form("update_form"):
        # במקום URL, מבקשים את שם הקובץ
        name_input = st.text_input(
            "שם הקובץ ב-Google Drive:",
            value="ROOP", 
            placeholder="למשל: ROOP"
        )
        
        semesters_input = st.text_input("סמסטרים (מופרדים בפסיק):", value="2,3")
        
        submitted = st.form_submit_button("הרץ עדכון 🚀")

    if submitted:
        if not name_input:
            st.error("חסר שם קובץ.")
        else:
            update_headers_logic(name_input, semesters_input)
