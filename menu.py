import streamlit as st
import google.generativeai as genai

st.title("🔍 בדיקת מודלים זמינים")

# וידוא שיש מפתח
if "GOOGLE_API_KEY" not in st.secrets:
    st.error("חסר מפתח GOOGLE_API_KEY ב-secrets.toml")
    st.stop()

# התחברות
genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])

try:
    st.write("מתחבר לגוגל ושואל: 'איזה מודלים יש לך?'...")
    
    # שליפת הרשימה
    models = list(genai.list_models())
    
    found_any = False
    st.markdown("### רשימת המודלים שנמצאו:")
    
    for m in models:
        # מסננים רק מודלים שטובים לצ'אט (generateContent)
        if 'generateContent' in m.supported_generation_methods:
            st.code(m.name) # זה השם המדויק שצריך להעתיק!
            found_any = True

    if not found_any:
        st.error("❌ לא נמצאו מודלים תומכי צ'אט. (אולי ה-API לא מופעל בפרויקט הזה?)")

except Exception as e:
    st.error(f"שגיאה בהתחברות: {e}")

