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

# מילות מפתח לזיהוי כותרות (Smart Loading)
KEYWORDS_COURSES = ['שם קורס', 'שם הקורס', 'Course Name']
KEYWORDS_AVAIL = ['שם מלא', 'שם מרצה', 'שם המרצה']

# ================= 1. SMART LOADER (טעינה חכמה) =================

def check_headers(df, keywords):
    """בדיקה האם רשימת הכותרות מכילה את אחת ממילות המפתח"""
    cols = [str(c).strip() for c in df.columns]
    return any(k in cols for k in keywords)

def smart_load_dataframe(file_obj, file_type):
    """
    טוען את הקובץ ומחפש את שורת הכותרת האמיתית ב-10 השורות הראשונות.
    """
    keywords = KEYWORDS_COURSES if file_type == 'courses' else KEYWORDS_AVAIL
    filename = file_obj.name
    
    try:
        # 1. ניסיון טעינה רגיל
        if filename.endswith('.csv'):
            df = pd.read_csv(file_obj)
        else:
            df = pd.read_excel(file_obj)

        if check_headers(df, keywords):
            return df, None

        # 2. חיפוש כותרת בשורות נמוכות יותר (רק לאקסל)
        if not filename.endswith('.csv'):
            for i in range(1, 10):
                file_obj.seek(0)
                df = pd.read_excel(file_obj, header=i)
                if check_headers(df, keywords):
                    df = df.dropna(how='all', axis=1)
                    return df, None

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

    if any(k in courses_cols for k in KEYWORDS_AVAIL) and any(k in avail_cols for k in KEYWORDS_COURSES):
        return "נראה שהחלפת בין קובץ הקורסים לקובץ הזמינות."
        
    return None

def validate_data_content(df_courses):
    """בדיקות שלמות וטווח בקובץ הקורסים"""
    
    # בדיקת ערכים חסרים קריטיים
    critical_missing = df_courses[
        df_courses['מרצה'].isna() | 
        df_courses['שם קורס'].isna() | 
        df_courses['שעות'].isna()
    ]
    if not critical_missing.empty:
        st.error("🛑 **שגיאה: חסרים נתונים קריטיים!**")
        st.write("נא למלא את 'מרצה', 'שם קורס' ו'שעות' בשורות הבאות:")
        st.dataframe(critical_missing)
        return False
        
    # בדיקת טווח שעות (1 עד 7)
    df_courses['שעות'] = pd.to_numeric(df_courses['שעות'], errors='coerce')
    invalid_hours = df_courses[
        (df_courses['שעות'].isna()) | 
        (df_courses['שעות'] < 1) | 
        (df_courses['שעות'] > 7)
    ]
    if not invalid_hours.empty:
        st.error("🛑 **שגיאה: שעות קורס לא תקינות**")
        st.write("שעות קורס חייבות להיות מספר שלם בין 1 ל-7:")
        st.dataframe(invalid_hours)
        return False

    # בדיקת טווח סמסטר (1, 2, 3, 4)
    df_courses['Semester'] = pd.to_numeric(df_courses['Semester'], errors='coerce', downcast='integer')
    valid_semesters = [1, 2, 3, 4]
    invalid_semesters = df_courses[
        (df_courses['Semester'].isna()) | 
        (~df_courses['Semester'].isin(valid_semesters))
    ]
    if not invalid_semesters.empty:
        st.error("🛑 **שגיאה: ערכי סמסטר לא תקינים**")
        st.write("ערך הסמסטר חייב להיות 1, 2, 3 או 4:")
        st.dataframe(invalid_semesters)
        return False

    # בדיקת כפילויות לוגית
    duplicates = df_courses[df_courses.duplicated(subset=['Year', 'Semester', 'שם קורס'], keep=False)]
    if not duplicates.empty:
        st.error("🛑 **שגיאה: נמצאו כפילויות**")
        st.write("הקורסים הבאים מופיעים יותר מפעם אחת באותו סמסטר:")
        st.dataframe(duplicates)
        return False
    
    return True

def validate_lecturer_coverage(df_courses, df_avail):
    """בדיקה אילו מרצים בקורסים חסרים בטבלת הזמינות (אזהרה)"""
    course_lecturers = set(df_courses['מרצה'].dropna().unique())
    avail_lecturers = set(df_avail['שם מלא'].dropna().unique())

    missing_lecturers = list(course_lecturers - avail_lecturers)
    
    if missing_lecturers:
        st.warning("⚠️ **אזהרה: מרצים חסרים בטופס הזמינות!**")
        st.write(f"הקורסים של המרצים הבאים **לא ישובצו**, כי לא נמצא להם טופס זמינות:")
        st.code(", ".join(missing_lecturers))
        
    # מחזירים True כי זו אזהרה, לא שגיאה קריטית
    return True

def validate_avail_content(df_avail):
    """בדיקה שכל מרצה בטבלת הזמינות מילא לפחות שעה אחת"""
    df_temp = df_avail.copy()
    
    # יצירת עמודה שתכיל את כל נתוני הזמינות של מרצה מסוים
    avail_cols = [col for col in df_temp.columns if col in AVAIL_COLS_MAP]
    df_temp['All_Avail_Data'] = df_temp[avail_cols].astype(str).agg(' '.join, axis=1).apply(clean_text)
    
    # סינון מרצים שהשם שלהם לא ריק אבל נתוני הזמינות שלהם ריקים
    empty_avail = df_temp[
        (df_temp['שם מלא'].notna()) & 
        (df_temp['All_Avail_Data'].isna())
    ]
    
    if not empty_avail.empty:
        st.error("🛑 **שגיאה קריטית: זמינות ריקה!**")
        st.write("המרצים הבאים מופיעים בטופס הזמינות אך לא מילאו **אף שעה**:")
        st.dataframe(empty_avail[['שם מלא'] + avail_cols])
        return False
        
    return True

# ================= 4. PROCESSING & SCHEDULING =================

def process_availability(df_avail):
    # הפונקציה נשארת כפי שהיא, רק מוודאים שיש 'שם מלא'
    lecturer_availability = {}
    
    df_avail = df_avail[df_avail['שם מלא'].notna()].copy()
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
    # (הקוד של run_scheduler נשאר ללא שינוי מהותי)
    
    # ... (קוד run_scheduler מלא נמצא בגרסה הקודמת)
    # ... (מטעמי קוצר, נשאר כאן ללא שינוי אם עבד קודם)
    
    # החלק שמטפל במרצים שלא שובצו
    df_courses['Is_Zoom'] = df_courses['מרחב'].astype(str).str.contains('זום', case=False, na=False)
    
    # הקוד נשאר כפי שהיה בגרסה הקודמת. הוא תקין לוגית.
    # ... (השארת קוד run_scheduler כפי שהיה)
    
    # (מכיוון שהפונקציה הזו גדולה, אני משאיר אותה כפי שהייתה בגרסה האחרונה שקיבלת ועבדה)
    # לצורך התצוגה המלאה, נשתמש בגרסה האחרונה התקינה.
    
    # אם ברצונך לקבל את run_scheduler המלאה שוב, אנא ציין זאת.
    # נניח שהיא עדיין עובדת תקין...
    
    # =========================================================
    # *** הנחת יסוד: run_scheduler תקין מהגרסה הקודמת ***
    # =========================================================
    
    # דוגמה פשוטה לשם הקיצור:
    # final_schedule = pd.DataFrame(schedule)
    # errors = pd.DataFrame(unscheduled)
    
    # כדי להיות בטוח, נכניס כאן את הקוד של run_scheduler המלא שלך:
    
    sparsity_scores = {}
    for lect, days in lecturer_availability.items():
        total_slots = sum(len(hours) for hours in days.values())
        sparsity_scores[lect] = total_slots
        
    df_courses['Sparsity'] = df_courses['מרצה'].map(sparsity_scores).fillna(0)
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

    if err_courses:
        st.error(err_courses)
        return
    if err_avail:
        st.error(err_avail)
        return

    # 2. ניקוי ושינוי שמות עמודות
    df_courses.columns = df_courses.columns.str.strip()
    df_avail.columns = df_avail.columns.str.strip()
    
    # שינוי שמות קריטי
    df_courses = df_courses.rename(columns={'שנה': 'Year', 'סמסטר': 'Semester'})
    
    # 3. בדיקה אם הוחלפו הקבצים
    cross_error = validate_cross_files(df_courses, df_avail)
    if cross_error:
        st.error(f"🛑 שגיאה: {cross_error}")
        return

    # 4. ניקוי נתונים ראשוני
    for col in ['שם קורס', 'מרצה', 'מרחב']:
        if col in df_courses.columns:
            df_courses[col] = df_courses[col].apply(clean_text)
            
    if 'מרצה' in df_courses.columns:
        df_courses['מרצה'] = df_courses['מרצה'].replace(NAME_MAPPING)

    # 5. בדיקות תקינות נתונים קריטיות (הבדיקות החדשות)
    if not validate_data_content(df_courses):
        return
    
    if not validate_avail_content(df_avail):
        return

    # 6. בדיקת כיסוי מרצים (אזהרה בלבד)
    validate_lecturer_coverage(df_courses, df_avail)

    # 7. הרצת השיבוץ
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
        st.download_button("📥 הורד דוח שגיאות", csv_err, 'errors.csv', 'text/csv', key='dl-err')
