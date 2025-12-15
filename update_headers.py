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

def update_headers_logic(sheet_url, semesters_str):
    client = get_gspread_client()
    if not client: return

    try:
        with st.spinner("⏳ מתחבר לגיליון בגוגל..."):
            sheet = client.open_by_url(sheet_url)
            worksheet = sheet.get_worksheet(0)

        semesters = [s.strip() for s in semesters_str.split(',') if s.strip()]
        
        if not semesters:
            st.warning("⚠️ לא הוזנו סמסטרים תקינים.")
            return

        # יצירת הכותרות
        new_headers = []
        for sem in semesters:
            for day in range(1, 6):
                # הפורמט: 1 [2]
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

    except Exception as e:
        st.error(f"❌ שגיאה: {e}")

# --- הפונקציה הראשית שהתפריט יפעיל ---
def run():
    st.header("🛠️ עדכון כותרות בגיליון ציונים")
    st.markdown("כלי זה משנה את שמות העמודות בגיליון (החל מעמודה 2) לפי הסמסטרים המוזנים.")

    with st.form("update_form"):
        # כאן שמתי את הקישור שלך כברירת מחדל כדי לחסוך לך זמן
        url_input = st.text_input(
            "קישור לגיליון (Google Sheet URL):",
            value="https://docs.google.com/spreadsheets/d/1ogjseuZBeJ4ukYA6Xi6NjLNlUri5alAe0RufpDix6ic/edit?gid=1468782916#gid=1468782916", # <-- החליפי בקישור האמיתי שלך
            placeholder="..."
        )
        
        semesters_input = st.text_input("סמסטרים (מופרדים בפסיק):", value="2,3")
        
        submitted = st.form_submit_button("הרץ עדכון 🚀")

    if submitted:
        if not url_input:
            st.error("חסר קישור.")
        else:
            update_headers_logic(url_input, semesters_input)