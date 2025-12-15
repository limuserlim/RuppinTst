from google.generativeai.types import HarmCategory, HarmBlockThreshold
from google.oauth2 import service_account
from googleapiclient.discovery import build
import streamlit as st
import google.generativeai as genai
import quest  # הקובץ השני
import pandas as pd
import traceback
import update_headers
# --- הגדרת העמוד ---
st.set_page_config(page_title="מערכת ניהול רופין", page_icon="🎓", layout="centered")


def get_brain_from_docs():
    # 👇 כאן תדביקי את ה-ID שהעתקת בשלב 1
    DOCUMENT_ID = '1zg7q93__eHUJ849z1Mi-JOJpS1ImqkeDdipMmTONUfM'

    try:
        # בדיקה שיש לנו את הסודות
        if "gcp_service_account" not in st.secrets:
            st.error("❌ חסרים פרטי התחברות ב-secrets.toml")
            return "הוראות ברירת מחדל: ענה בנימוס."

        # התחברות לגוגל
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        
        creds = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=["https://www.googleapis.com/auth/documents.readonly"]
        )
        service = build('docs', 'v1', credentials=creds)

        # קריאת המסמך
        document = service.documents().get(documentId=DOCUMENT_ID).execute()
        
        # חילוץ הטקסט הנקי מתוך המבנה של גוגל (החלק הטריקי)
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
        return "שגיאה בטעינת המוח."

# --- הגדרת המוח של LOOZ ---
def configure_gemini():
    if "GOOGLE_API_KEY" not in st.secrets:
        st.error("חסר מפתח GOOGLE_API_KEY")
        return None
    
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])

    # טעינת המוח
    brain_instructions = get_brain_from_docs()
    
    config = {
        "temperature": 0.0,
        "top_p": 0.95,
        "top_k": 40,
        "max_output_tokens": 8192,
    }

    # הגדרות בטיחות אגרסיביות - מבטלות את כל החסימות
    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    return genai.GenerativeModel(
        model_name="models/gemini-flash-latest",
        system_instruction=brain_instructions,
        generation_config=config,
        safety_settings=safety_settings
    )# --- ממשק המשתמש ---
st.title("🎓 מערכת ניהול מערכת שעות")

if "messages" not in st.session_state:
    st.session_state.messages = []

action = st.radio("בחר פעולה:", ["בנה לי מערכת (LOOZ)", "בנה לי שאלון", "עדכן שמות שדות קובץ תשובות"], horizontal=True)
st.markdown("---")

# === לוגיקה של LOOZ ===
if action == "בנה לי מערכת (LOOZ)":
    st.header("🤖 הבוט LOOZ")
    st.info("ניתן להעלות קבצי Excel, PDF ותמונות.")
    
    with st.expander("📂 טעינת קבצים", expanded=(len(st.session_state.messages) == 0)):
        uploaded_files = st.file_uploader(
            "קבצי קלט", 
            accept_multiple_files=True,
            type=['pdf', 'csv', 'txt', 'png', 'jpg', 'xlsx']
        )
        user_notes = st.text_area("הערות:", "בנה מערכת לפי הקבצים.")
        start_btn = st.button("התחל 🚀", type="primary")

    if start_btn and uploaded_files:
        model = configure_gemini()
        if model:
            # רשימת החלקים שתשלח לג'מיני
            content_parts = [user_notes]
            
            for file in uploaded_files:
                try:
                    # === טיפול באקסל ===
                    if file.name.endswith('.xlsx'):
                        # המרה לטקסט (CSV)
                        df = pd.read_excel(file)
                        # המרה למחרוזת טקסט ארוכה
                        csv_text = df.to_csv(index=False)
                        
                        # הוספה כטקסט רגיל (לא כקובץ!)
                        content_parts.append(f"\n--- נתונים מקובץ אקסל: {file.name} ---\n{csv_text}\n")
                        st.caption(f"✅ קובץ {file.name} עובד והומר לטקסט.")
                    
                    # === טיפול בקבצים אחרים (PDF/תמונות) ===
                    elif file.type in ["application/pdf", "image/png", "image/jpeg", "image/jpg"]:
                        content_parts.append({
                            "mime_type": file.type,
                            "data": file.getvalue()
                        })
                    
                    # === טיפול בקבצי טקסט/CSV ===
                    else:
                        string_data = file.getvalue().decode("utf-8")
                        content_parts.append(f"\n--- תוכן קובץ {file.name} ---\n{string_data}\n")

                except Exception as e:
                    st.error(f"שגיאה בעיבוד הקובץ {file.name}: {e}")
                    st.stop()

            # שליחה לג'מיני
            st.session_state.messages = [{"role": "user", "parts": content_parts, "display_text": user_notes}]
            
            with st.spinner("LOOZ מעבד את הנתונים..."):
                try:
                    response = model.generate_content(content_parts)
                    st.session_state.messages.append({"role": "model", "parts": [response.text]})
                    st.rerun() # רענון כדי להציג את התשובה מיד
                except Exception as e:
                    st.error(f"שגיאה בתקשורת עם גוגל: {str(e)}")

    # הצגת היסטוריה
    for msg in st.session_state.messages:
        role = "user" if msg["role"] == "user" else "assistant"
        with st.chat_message(role):
            if "display_text" in msg:
                st.write(msg["display_text"])
                if role == "user": st.caption("📎 (קבצים צורפו ונוחתו)")
            else:
                st.write(msg["parts"][0])

    # צ'אט המשך
    if prompt := st.chat_input("תגובה לבוט..."):
        st.session_state.messages.append({"role": "user", "parts": [prompt]})
        with st.chat_message("user"):
            st.write(prompt)

        model = configure_gemini()
        if model:
            history = []
            for m in st.session_state.messages:
                # סינון שדות תצוגה
                history.append({"role": m["role"], "parts": m["parts"]})
            
            with st.chat_message("assistant"):
                with st.spinner("חושב..."):
                    try:
                        response = model.generate_content(history)
                        st.write(response.text)
                        st.session_state.messages.append({"role": "model", "parts": [response.text]})
                    except Exception as e:
                        st.error(f"שגיאה: {e}")

elif action == "בנה לי שאלון":
    quest.run()
elif action == "עדכן שמות שדות קובץ תשובות":
    update_headers.run()









