import pandas as pd
import numpy as np
import io
import streamlit as st

# ================= CONFIGURATION =================

# מיפוי שמות ידני לטיפול באי-התאמות (קורסים -> זמינות)
NAME_MAPPING = {
    'מיכל רופא': 'מיכל רופא תכנון אקלימי',
    'נעמה ציזר שבתאי': 'נעמה שבתאי-ציזר',
    'אורנה גרופינקל קולמן': 'אורנה גורפינקל קולמן',
    'מתרגל': 'נועה גינו'
}

# מיפוי עמודות זמינות לימים
AVAIL_COLS_MAP = {'12': 1, '22': 2, '32': 3, '42': 4, '52': 5}
HOURS_RANGE = range(8, 22) # טווח שעות בדיקה

# ================= 1. DATA CLEANING UTILS =================

def clean_text(text):
    """ניקוי רווחים כפולים ושטחים ריקים"""
    if pd.isna(text) or str(text).strip() == "":
        return None
    text = str(text).strip()
    return " ".join(text.split())

def parse_availability_string(avail_str):
    """מפענח מחרוזת כמו '16-17, 17-18' לרשימת שעות"""
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

# ================= 2. VALIDATION =================

def validate_data(df_courses):
    """בדיקת ייחודיות מחמירה"""
    st.info("🔍 מבצע בדיקת תקינות וכפילויות...")
    
    # הערה: שינוי השמות הועבר ל-main_process כדי להיות גלובלי
    
    duplicates = df_courses[df_courses.duplicated(subset=['Year', 'Semester', 'שם קורס'], keep=False)]
    
    if not duplicates.empty:
        st.error("🛑 נמצאו כפילויות בקובץ הקורסים! לא ניתן להמשיך בשיבוץ.")
        st.write("הקורסים הבאים מופיעים יותר מפעם אחת באותו סמסטר:")
        st.dataframe(duplicates)
        return False
        
    return True

# ================= 3. PROCESSING & SCHEDULING =================

def process_availability(df_avail):
    lecturer_availability = {}
    df_avail.columns = df_avail.columns.astype(str)
    
    for index, row in df_avail.iterrows():
        raw_name = row.get('שם מלא', '')
        if pd.isna(raw_name) or str(raw_name).strip() == "":
            continue
            
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
    st.toast("⚙️ המנוע מחשב שיבוץ אופטימלי...", icon="🤖")
    
    schedule = []
    unscheduled = []
    
    # חישוב ציוני גמישות
    sparsity_scores = {}
    for lect, days in lecturer_availability.items():
        total_slots = sum(len(hours) for hours in days.values())
        sparsity_scores[lect] = total_slots
        
    df_courses['Sparsity'] = df_courses['מרצה'].map(sparsity_scores).fillna(0)
    df_courses['Is_Zoom'] = df_courses['מרחב'].astype(str).str.contains('זום', case=False, na=False)
    
    # מיון חכם
    df_courses.sort_values(by=['Sparsity', 'שעות'], ascending=[True, False], inplace=True)
    
    # לולאת השיבוץ
    for idx, course in df_courses.iterrows():
        lecturer = course['מרצה']
        if pd.isna(lecturer): continue
        
        course_name = course['שם קורס']
        duration = int(course['שעות']) if not pd.isna(course['שעות']) else 2
        year = course['Year']
        semester = course['Semester']
        is_zoom = course['Is_Zoom']
        
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
                
                # בדיקת התנגשויות
                conflict = False
                for item in schedule:
                    if item['Day'] == day and item['Semester'] == semester:
                        # חפיפת שעות
                        if max(start_hour, item['Hour']) < min(start_hour + duration, item['Hour'] + item['Duration']):
                            # אותו מרצה או אותו שנתון (Year)
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

# ================= 4. MAIN PROCESS ENTRY POINT =================

def main_process(courses_file, avail_file):
    """זו הפונקציה שהמערכת קוראת לה מבחוץ"""
    
    # טעינת הנתונים
    try:
        if courses_file.name.endswith('.csv'):
            df_courses = pd.read_csv(courses_file)
        else:
            df_courses = pd.read_excel(courses_file)
            
        if avail_file.name.endswith('.csv'):
            df_avail = pd.read_csv(avail_file)
        else:
            df_avail = pd.read_excel(avail_file)
            
    except Exception as e:
        st.error(f"שגיאה בטעינת הקבצים: {e}")
        return

    # ניקוי בסיסי של הכותרות
    df_courses.columns = df_courses.columns.str.strip()
    df_avail.columns = df_avail.columns.str.strip()

    # --- התיקון הקריטי: המרת שמות עמודות כאן, לפני הכל ---