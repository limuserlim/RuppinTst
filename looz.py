import streamlit as st
import pandas as pd
import io

def clean_str(val):
    return str(val).strip()

def diagnose_availability(row, cols):
    """מנסה לפענח שורה אחת ומחזירה מה הבינה"""
    log = []
    found_slots = 0
    
    for col in cols:
        val = row[col]
        if pd.isna(val) or str(val).strip() == "": continue
        
        # בדיקת שם העמודה
        s_col = str(col).strip()
        if len(s_col) < 2: continue
        
        # האם זה נראה כמו יום+סמסטר?
        log.append(f"בודק עמודה '{col}' עם ערך '{val}'...")
        
        try:
            # ניסיון חילוץ
            parts = str(val).replace(';', ',').split(',')
            for p in parts:
                if '-' in p:
                    found_slots += 1
        except:
            pass
            
    return found_slots, log

def main_process(courses_file, avail_file, iterations=20):
    st.title("🕵️ מוד אבחון תקלות (Diagnostic Mode)")
    
    if not courses_file or not avail_file:
        st.info("אנא העלה קבצים כדי להתחיל באבחון.")
        return

    # 1. טעינה ראשונית
    try:
        c_df = pd.read_excel(courses_file) if courses_file.name.endswith('.xlsx') else pd.read_csv(courses_file)
        a_df = pd.read_excel(avail_file) if avail_file.name.endswith('.xlsx') else pd.read_csv(avail_file)
    except Exception as e:
        st.error(f"שגיאה בטעינת הקבצים: {e}")
        return

    st.write("---")
    
    # 2. ניתוח קובץ קורסים
    st.header("1. ניתוח קובץ קורסים (Courses)")
    st.write(f"מספר שורות: {len(c_df)}")
    st.write("שמות עמודות שזוהו:", list(c_df.columns))
    
    # זיהוי עמודות קריטיות
    col_map = {}
    found_cols = []
    missing_cols = []
    
    for col in c_df.columns:
        c = str(col).lower().strip()
        if 'מרצה' in c or 'lecturer' in c: 
            col_map['Lecturer'] = col; found_cols.append('Lecturer')
        elif 'משך' in c or 'duration' in c or 'שעות' in c: 
            col_map['Duration'] = col; found_cols.append('Duration')
        elif 'קורס' in c or 'course' in c:
            col_map['Course'] = col; found_cols.append('Course')
            
    st.success(f"✅ עמודות קריטיות שנמצאו: {found_cols}")
    if len(found_cols) < 3:
        st.error(f"❌ חסרות עמודות קריטיות! המערכת צריכה: מרצה, שם קורס, משך/שעות.")
    
    # דגימת תוכן
    if 'Lecturer' in col_map:
        sample_lec = c_df[col_map['Lecturer']].dropna().astype(str).str.strip().unique()
        st.info(f"דוגמה ל-3 מרצים מקובץ הקורסים: {sample_lec[:3]}")
    
    # 3. ניתוח קובץ זמינות
    st.header("2. ניתוח קובץ זמינות (Availability)")
    st.write("שמות עמודות שזוהו:", list(a_df.columns))
    
    a_lec_col = None
    for col in a_df.columns:
        if 'מרצה' in str(col) or 'name' in str(col).lower():
            a_lec_col = col
            break
            
    if not a_lec_col:
        st.error("❌ לא נמצאה עמודת 'שם מרצה' בקובץ הזמינות!")
        return
    else:
        st.success(f"✅ עמודת מרצה בזמינות: '{a_lec_col}'")
        
    avail_lecs = a_df[a_lec_col].dropna().astype(str).str.strip().unique()
    st.info(f"דוגמה ל-3 מרצים מקובץ הזמינות: {avail_lecs[:3]}")
    
    # 4. בדיקת חיתוך (התאמה)
    st.header("3. בדיקת התאמה (Matching)")
    if 'Lecturer' in col_map:
        courses_lecs_set = set(sample_lec)
        avail_lecs_set = set(avail_lecs)
        
        common = courses_lecs_set.intersection(avail_lecs_set)
        st.metric("מרצים משותפים (זוהו בשני הקבצים)", len(common))
        
        if len(common) == 0:
            st.error("❌ 0 התאמות! המערכת לא תצליח לשבץ כלום.")
            st.write("השווה בין השמות:")
            col1, col2 = st.columns(2)
            col1.write("מקובץ קורסים:", sample_lec[:5])
            col2.write("מקובץ זמינות:", avail_lecs[:5])
            return

    # 5. בדיקת פענוח שעות (Parsing)
    st.header("4. בדיקת פענוח שעות")
    # חיפוש עמודות זמינות (מספריות)
    avail_cols = [c for c in a_df.columns if len(str(c))>=2 and str(c)[:2].isdigit()]
    st.write(f"עמודות שנחשדות כעמודות זמן: {avail_cols}")
    
    if not avail_cols:
        st.error("❌ לא נמצאו עמודות זמן (כמו 11, 12, 21...). בדוק את הכותרות.")
    else:
        # בדיקה על השורה הראשונה שיש בה תוכן
        sample_row = None
        for i, row in a_df.iterrows():
            # חפש שורה שיש בה לפחות עמודת זמן אחת מלאה
            has_data = any([pd.notna(row[c]) and str(row[c]).strip() != "" for c in avail_cols])
            if has_data:
                sample_row = row
                break
        
        if sample_row is not None:
            lec_name = sample_row[a_lec_col]
            st.write(f"בדיקת פענוח עבור המרצה: **{lec_name}**")
            slots_count, log = diagnose_availability(sample_row, avail_cols)
            
            if slots_count == 0:
                st.warning("⚠️ לא הצלחתי לחלץ שעות מהמרצה הזה. הנה מה שניסיתי:")
                st.code("\n".join(log[:5]))
                st.write("ודא שהפורמט הוא '08-10' או '8-10' (עם מקף).")
            else:
                st.success(f"✅ הצלחתי לזהות {slots_count} חלונות זמן תקינים אצל המרצה הזה.")
        else:
            st.warning("לא נמצאה אף שורה עם נתוני זמינות לבדיקה.")

if __name__ == "__main__":
    pass
