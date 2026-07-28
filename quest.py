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
        st.error("לא נמצאו סודות (Secrets).")
        return None
    
    creds_dict = dict(st.secrets["gcp_service_account"])
    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    return service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/forms.body"]
    )

def update_form_structure(year, semesters):
    creds = get_creds()
    if not creds: raise Exception("חיבור לגוגל נכשל")
    service = build('forms', 'v1', credentials=creds)

    st.info("⚙️ מתחיל בעדכון מבנה הטופס...")
    
    form_metadata = service.forms().get(formId=FORM_ID).execute()
    delete_requests = []
    if 'items' in form_metadata:
        for i in range(len(form_metadata['items'])):
             delete_requests.append({"deleteItem": {"location": {"index": 0}}})
    
    if delete_requests:
        service.forms().batchUpdate(formId=FORM_ID, body={"requests": delete_requests}).execute()

    create_requests = []
    
    # 1. עדכון כותרת
    create_requests.append({
        "updateFormInfo": {
            "info": {
                "title": f"זמינות ללמד בסמסטר {','.join(semesters)} בשנת {year}",
                "description": "אנא מלאו את זמינותכם בטופס זה."
            },
            "updateMask": "title,description"
        }
    })

    # 2. שם מלא
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

    # 3. גריד שעות
    days = ["יום ראשון", "יום שני", "יום שלישי", "יום רביעי", "יום חמישי"]
    hours = ["08:00-09:00", "09:00-10:00", "10:00-11:00", "11:00-12:00", "12:00-13:00", "13:00-14:00", "14:00-15:00", "15:00-16:00", "16:00-17:00", "17:00-18:00", "18:00-19:00", "19:00-20:00"]

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

    # 4. שאלה אחרונה - קורסים מבוקשים (רשות, טקסט ארוך)
    create_requests.append({
        "createItem": {
            "item": {
                "title": "הקורסים שהיית רוצה ללמד בשנה זו",
                "questionItem": {
                    "question": {
                        "required": False, # מוגדר כרשות
                        "textQuestion": {"paragraph": True} # מוגדר כתיבת טקסט ארוך
                    }
                }
            },
            "location": {"index": current_index}
        }
    })

    service.forms().batchUpdate(formId=FORM_ID, body={"requests": create_requests}).execute()
    return True

# --- הפונקציה הראשית שתופעל ע"י התפריט ---
def run():
    st.header("📝 מחולל השאלונים")
    st.caption("רכיב זה מעדכן את מבנה שאלון הזמינות למרצים.")
    
    st.info(f"מחובר לטופס: `{FORM_ID}`")

    with st.form("quest_form"):
        col1, col2 = st.columns(2)
        with col1:
            year_input = st.text_input("שנה", value="2026")
        with col2:
            semesters_input = st.text_input("סמסטרים", value="1,2")
        
        submitted = st.form_submit_button("עדכן טופס 🚀")

    if submitted:
        is_year_valid, year_msg = validate_year(year_input)
        if not is_year_valid:
            st.error(year_msg)
            return
            
        is_sem_valid, clean_semesters = validate_semesters(semesters_input)
        if not is_sem_valid:
            st.error("שגיאה בסמסטרים")
            return

        with st.spinner("מעדכן את הטופס..."):
            try:
                update_form_structure(year_input, clean_semesters)
                st.success("✅ הטופס עודכן בהצלחה!")
                st.markdown(f"[לחצי כאן לפתיחת הטופס]({f'https://docs.google.com/forms/d/{FORM_ID}/edit'})")
                st.info("זכרי: יש לחבר את האקסל ידנית דרך לשונית Responses בטופס.")
            except Exception as e:
                st.error("❌ שגיאה בעדכון הטופס:")
                st.code(traceback.format_exc())
