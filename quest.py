import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
import traceback

# --- הגדרות ---
FORM_ID = "1-EsH0ZzHgPQFwZxkcSJdhB8jTHB9HcGwL7nTYkxUXIM"

# --- פונקציות ולידציה ---
def validate_year(year_str):
    if not year_str.isdigit():
        return False, "השנה חייבת להכיל ספרות בלבד."
    year = int(year_str)
    if 2025 <= year <= 2050:
        return True, ""
    return False, "יש להזין שנה בין 2025 לבין 2050."

def validate_semesters(semesters_str):
    if not semesters_str.strip():
        return False, "חובה להזין לפחות סמסטר אחד."
    parts = [p.strip() for p in semesters_str.split(',')]
    if len(parts) > 4:
        return False, "יש להזין עד 4 סמסטרים בלבד."
    return True, parts

# --- פונקציות גוגל ---
def get_creds():
    if "gcp_service_account" not in st.secrets:
        st.error("לא נמצא קובץ secrets.toml")
        return None
    
    creds_dict = dict(st.secrets["gcp_service_account"])
    
    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    return service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=[
            "https://www.googleapis.com/auth/forms.body", 
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/spreadsheets"
        ]
    )

def manage_response_sheet(year, semesters):
    creds = get_creds()
    if not creds: return None, None
    
    drive_service = build('drive', 'v3', credentials=creds)

    sem_str = "".join(semesters)
    file_name = f"Arch{year}{sem_str}"
    
    st.info(f"⚙️ מטפל בקובץ התשובות: `{file_name}`...")

    try:
        query = f"name = '{file_name}' and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        existing_files = results.get('files', [])

        if existing_files:
            for f in existing_files:
                drive_service.files().delete(fileId=f['id']).execute()
                st.caption(f"🗑️ נמחק קובץ ישן: {f['name']}")
    except Exception as e:
        st.warning(f"הערה: לא הצלחתי לבדוק אם קיים קובץ ישן ({e}), ממשיך ליצירת חדש.")

    file_metadata = {
        'name': file_name,
        'mimeType': 'application/vnd.google-apps.spreadsheet'
    }
    
    file = drive_service.files().create(body=file_metadata, fields='id, webViewLink').execute()
    new_id = file.get('id')
    new_url = file.get('webViewLink')

    try:
        drive_service.permissions().create(
            fileId=new_id,
            body={'type': 'anyone', 'role': 'writer'}
        ).execute()
    except:
        pass

    return new_url, file_name

def update_form_structure(year, semesters):
    creds = get_creds()
    if not creds: raise Exception("חיבור לגוגל נכשל")
    service = build('forms', 'v1', credentials=creds)

    form_metadata = service.forms().get(formId=FORM_ID).execute()
    delete_requests = []
    if 'items' in form_metadata:
        for item in form_metadata['items']:
            delete_requests.append({"deleteItem": {"location": {"index": 0}}})
    
    if delete_requests:
        service.forms().batchUpdate(formId=FORM_ID, body={"requests": delete_requests}).execute()

    create_requests = []

    create_requests.append({
        "updateFormInfo": {
            "info": {
                "title": f"זמינות ללמד בסמסטר {','.join(semesters)} בשנת {year}",
                "description": "אנא מלאו את זמינותכם בטופס זה."
            },
            "updateMask": "title,description"
        }
    })

    create_requests.append({
        "createItem": {
            "item": {
                "title": "שם מלא",
                "questionItem": {
                    "question": {
                        "required": True,
                        "textQuestion": {"paragraph": False}
                    }
                }
            },
            "location": {"index": 0}
        }
    })

    days = ["יום ראשון", "יום שני", "יום שלישי", "יום רביעי", "יום חמישי"]
    hours = [
        "08:00-09:00", "09:00-10:00", "10:00-11:00", "11:00-12:00",
        "12:00-13:00", "13:00-14:00", "14:00-15:00", "15:00-16:00",
        "16:00-17:00", "17:00-18:00", "18:00-19:00", "19:00-20:00"
    ]

    current_index = 1
    for sem in semesters:
        row_questions = []
        for day in days:
            row_questions.append({"rowQuestion": {"title": day}})

        create_requests.append({
            "createItem": {
                "item": {
                    "title": f"זמינות בסמסטר {sem}",
                    "questionGroupItem": {
                        "questions": row_questions,
                        "grid": {
                            "columns": {
                                "type": "CHECKBOX",
                                "options": [{"value": h} for h in hours]
                            }
                        }
                    }
                },
                "location": {"index": current_index}
            }
        })
        current_index += 1

    service.forms().batchUpdate(formId=FORM_ID, body={"requests": create_requests}).execute()
    return True

# --- ממשק המשתמש ---
st.set_page_config(page_title="בדיקת quest.py", page_icon="🧪", layout="centered")

st.title("🧪 בדיקת רכיב השאלונים")
st.write("כלי זה מבודד את הלוגיקה של בניית הטופס והאקסל כדי לוודא שהכל תקין.")

st.info(f"מחובר לטופס: `{FORM_ID}`")

with st.form("test_form"):
    col1, col2 = st.columns(2)
    with col1:
        year_input = st.text_input("שנה", value="2026")
    with col2:
        semesters_input = st.text_input("סמסטרים", value="1,2")
    
    submitted = st.form_submit_button("הרץ בדיקה 🚀")

if submitted:
    is_year_valid, year_msg = validate_year(year_input)
    if not is_year_valid:
        st.error(year_msg)
        st.stop()
        
    is_sem_valid, clean_semesters = validate_semesters(semesters_input)
    if not is_sem_valid:
        st.error("שגיאה בסמסטרים")
        st.stop()

    with st.spinner("מתחבר לרובוט ומבצע פעולות..."):
        try:
            excel_url, excel_name = manage_response_sheet(year_input, clean_semesters)
            st.success(f"✅ שלב 1 עבר: נוצר קובץ אקסל ({excel_name})")
            
            update_form_structure(year_input, clean_semesters)
            st.success("✅ שלב 2 עבר: הטופס עודכן בהצלחה")
            
            st.balloons()
            
            st.markdown("---")
            st.markdown("### 🎉 הבדיקה עברה בהצלחה!")
            st.markdown(f"1. **[לחצי כאן לפתיחת הטופס]({f'https://docs.google.com/forms/d/{FORM_ID}/edit'})**")
            st.markdown(f"2. **[לחצי כאן לפתיחת האקסל החדש]({excel_url})**")
            st.warning(f"בתוך הטופס: Responses -> Link to Sheets -> Select existing spreadsheet -> בחרי את **{excel_name}**")

        except Exception as e:
            st.error("❌ הבדיקה נכשלה עם השגיאה הבאה:")
            st.code(traceback.format_exc())
