import pandas as pd
import numpy as np
import streamlit as st

# ================= CONFIGURATION =================

NAME_MAPPING = {
    'מיכל רופא': 'מיכל רופא תכנון אקלימי',
    'נעמה ציזר שבתאי': 'נעמה שבתאי-ציזר',
    'אורנה גרופינקל קולמן': 'אורנה גורפינקל קולמן',
    'מתרגל': 'נועה גינו'
}

AVAIL_COLS_MAP = {'12': 1, '22': 2, '32': 3, '42': 4, '52': 5}
HOURS_RANGE = range(8, 22)

# מילות מפתח לזיהוי כותרות
KEYWORDS_COURSES = ['שם קורס', 'שם הקורס', 'Course Name']
KEYWORDS_AVAIL = ['שם מלא', 'שם מרצה', 'שם המרצה']

# ================= 1. SMART LOADER (החלק החדש) =================

def check_headers(df, keywords):
    """בדיקה האם רשימת הכותרות מכילה את אחת ממילות המפתח"""
    cols = [str(c).strip() for c in df.columns]
    return any(k in cols for k in keywords)

def smart_load_dataframe(file_obj, file_type):
    """
    טוען את הקובץ ומחפש את שורת הכותרת האמיתית ב-10 השורות הראשונות.
    file_type: 'courses' או 'avail'
    מחזיר: (DataFrame, ErrorMessage)
    """
    keywords = KEYWORDS_COURSES if file_type == 'courses' else KEYWORDS_AVAIL
    filename = file_obj.name
    
    try:
        # ניסיון טעינה רגיל (שורה ראשונה היא כותרת)
        if filename.endswith('.csv'):
            df = pd.read_csv(file_obj)
        else:
            df = pd.read_excel(file_obj)

        # אם מצאנו את הכותרות מיד - מעולה
        if check_headers(df, keywords):
            return df, None

        # אם זה אקסל, ייתכן שהכותרת נמצאת בשורה נמוכה יותר
        if not filename.endswith('.csv'):
            # סריקה של עד 10 שורות ראשונות
            for i in range(1, 10):
                file_obj.seek(0) # חזרה לתחילת הקובץ
                df = pd.read_excel(file_obj, header=i)
                if check_headers(df, keywords):
                    # מצאנו! ננקה עמודות ריקות שנוצרו בגלל ההזזה
                    df = df.dropna(how='all', axis=1)
                    return df, None

        # אם הגענו לכאן - לא מצאנו כותרות תקינות
        return None, f"❌ קובץ {filename} : מבנה לא תקין (לא נמצאו כותרות מתאימות)"

    except Exception as e:
        return None, f"❌ קובץ {filename} : שגיאה בטעינה ({str(e)})"

# ================= 2. DATA CLEANING UTILS =================

def clean_text(text):
    if pd.isna(text) or str(text).strip() == "":
        return None
    text = str(text).strip()
    return " ".join(text.split())

def parse_availability_string(avail_str):
    slots = set()
    if pd.isna(avail_str) or str(avail_str).strip() == "":
        return slots
    
    parts = str(avail_str).replace(';', ',').split(',')
    for part in parts:
        part = part.strip()
        if '-' in part:
            try:
                start, end = map(int, part.split('-'))
                for h in range(start, end):
                    slots.add(h)
            except ValueError:
                continue
    return slots

# ================= 3. VALIDATION (תוכן) =================

def validate_cross_files(df_courses, df_avail):
    """מוודא שלא הוחלפו הקבצים"""
    courses_cols = df_courses.columns.tolist()
    avail_cols = df_avail.columns.tolist()

    # האם קובץ הקורסים נראה כמו זמינות?
    if any(k in courses_cols for k in KEYWORDS_AVAIL):
        return "נראה שהעלית את קובץ הזמינות במקום קובץ הקורסים."
    
    # האם קובץ הזמינות נראה כמו קורסים?
    if any(k in avail_cols for k in KEYWORDS_COURSES):
        return "נראה שהעלית את קובץ הקורסים במקום קובץ הזמינות."
        
    return None

def validate_data_content(df_courses):
    """בדיקת כפילויות לוגית"""
    # המרת שמות לפני בדיקה
    df_courses = df_courses.rename(columns={'שנה': 'Year', 'סמסטר': 'Semester'})
    
    # וידוא שקיימות העמודות הקריטיות
    required = ['Year', 'Semester', 'שם קורס']
    missing = [col for col in required if col not in df_courses.columns]
    
    if missing:
        # זה לא אמור לקרות בגלל הטעינה החכמה, אבל ליתר ביטחון
        st.error(f"חסרות עמודות קריטיות בקובץ הקורסים: {missing}")
        return False

    duplicates = df_courses[df_courses.duplicated(subset=['Year', 'Semester', 'שם קורס'], keep=False)]
    if not duplicates.empty:
        st.error("🛑 נמצאו כפילויות בקובץ הקורסים! לא ניתן להמשיך.")
        st.dataframe(duplicates)
        return False
    return True

# ================= 4. PROCESSING & SCHEDULING =================

def process_availability(df_avail):
    lecturer_availability = {}
    df_avail.columns = df_avail.columns.astype(str)
    
    for index, row in df_avail.iterrows():
        raw_name = row.get('שם מלא', '')
        lecturer = clean_text(raw_name)
        if not lecturer: continue
        
        lecturer_availability[lecturer] = {day: set() for day in range(1, 6)}
        
        for col_name, day_num in AVAIL_COLS_MAP.items():
            if col_name in df_avail.columns:
                val = row[col_name]
                slots = parse_availability_string(val)
                if slots:
                    lecturer_availability[lecturer][day_num] = slots
    return lecturer_availability

def run_scheduler(df_courses, lecturer_availability):
    schedule = []
    unscheduled = []
    
    # חישוב ציוני גמישות
    sparsity_scores = {}
    for lect, days in lecturer_availability.items():
        total_slots = sum(len(hours) for hours in days.values())
        sparsity_scores[lect] = total_slots
        
    df_courses['Sparsity'] = df_courses['מרצה'].map(sparsity_scores).fillna(0)
    df_courses['Is_Zoom'] = df_courses['מרחב'].astype(str).str.contains('זום', case=False, na=False)
    
    df_courses.sort_values(by=['Sparsity', 'שעות'], ascending=[True, False], inplace=True)
    
    for idx, course in df_courses.iterrows():
        lecturer = course['מרצה']
        course_name = course['שם קורס']
        duration = int(course['שעות']) if not pd.isna(course['שעות']) else 2
        year = course['Year']
        semester = course['Semester']
        is_zoom = course['Is_Zoom']
        
        if pd.isna(lecturer): continue

        if lecturer not in lecturer_availability:
            unscheduled.append({'Course': course_name, 'Lecturer': lecturer, 'Reason': "חסרה טופס זמינות"})
            continue
            
        placed = False
        hours_order = list(HOURS_RANGE)
        if is_zoom: hours_order.reverse()
        
        for day in range(1, 6):
            if placed: break
            lect_slots = lecturer_availability[lecturer].get(day, set())
            
            for start_hour in hours_order:
                if start_hour + duration > 22: continue
                needed_slots = set(range(start_hour, start_hour + duration))
                if not needed_slots.issubset(lect_slots): continue
                
                conflict = False
                for item in schedule:
                    if item['Day'] == day and item['Semester'] == semester:
                        if max(start_hour, item['Hour']) < min(start_hour + duration, item['Hour'] + item['Duration']):
                            if item['Lecturer'] == lecturer or item['Year'] == year:
                                conflict = True; break
                
                if not conflict:
                    schedule.append({
                        'Year': year, 'Semester': semester, 'Day': day,
                        'Hour': start_hour, 'Course': course_name,
                        'Lecturer': lecturer, 'Duration': duration,
                        'Space': 'Zoom' if is_zoom else 'Class'
                    })
                    placed = True; break
        
        if not placed:
            unscheduled.append({'Course': course_name, 'Lecturer': lecturer, 'Reason': 'אין חלון זמן פנוי מתאים'})
            
    return pd.DataFrame(schedule), pd.DataFrame(unscheduled)

# ================= 5. MAIN PROCESS ENTRY POINT =================

def main_process(courses_file, avail_file):
    
    # 1. טעינה חכמה (זיהוי שורת כותרת)
    df_courses, err_courses = smart_load_dataframe(courses_file, 'courses')
    df_avail, err_avail = smart_load_dataframe(avail_file, 'avail')

    # הצגת שגיאות מבנה אם יש
    if err_courses:
        st.error(err_courses)
        return
    if err_avail:
        st.error(err_avail)
        return

    # 2. ניקוי רווחים בשמות העמודות
    df_courses.columns = df_courses.columns.str.strip()
    df_avail.columns = df_avail.columns.str.strip()

    # 3. בדיקה אם הוחלפו הקבצים
    cross_error = validate_cross_files(df_courses, df_avail)
    if cross_error:
        st.error(f"🛑 שגיאה: {cross_error}")
        return

    # 4. המרת שמות עמודות וניקוי נתונים
    df_courses = df_courses.rename(columns={'שנה': 'Year', 'סמסטר': 'Semester'})

    for col in ['שם קורס', 'מרצה', 'מרחב']:
        if col in df_courses.columns:
            df_courses[col] = df_courses[col].apply(clean_text)
            
    if 'מרצה' in df_courses.columns:
        df_courses['מרצה'] = df_courses['מרצה'].replace(NAME_MAPPING)

    # 5. בדיקת תוכן (כפילויות)
    if not validate_data_content(df_courses):
        return

    # 6. הרצת השיבוץ
    lect_avail = process_availability(df_avail)
    final_schedule, errors = run_scheduler(df_courses, lect_avail)

    st.markdown("---")
    st.markdown("### 📊 סיכום ריצה")
    
    if not final_schedule.empty:
        st.success(f"✅ הצלחנו לשבץ {len(final_schedule)} הרצאות!")
        st.dataframe(final_schedule, use_container_width=True)
        
        csv = final_schedule.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 הורד את הטבלה כקובץ CSV", csv, 'final_schedule.csv', 'text/csv', key='dl-success')
    else:
        st.warning("⚠️ המערכת רצה, אך לא הצליחה לשבץ אף הרצאה.")
        
    if not errors.empty:
        st.markdown("#### ❌ שגיאות שיבוץ (לא שובצו)")
        st.dataframe(errors)
        csv_err = errors.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 הורד דוח ש
