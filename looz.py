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

# ================= 1. DATA CLEANING UTILS =================

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

# ================= 2. VALIDATION (מבנה ותוכן) =================

def validate_file_structure(df_courses, df_avail):
    """
    בדיקה שהקבצים שהועלו הם מהסוג הנכון לפני שמתחילים לעבוד
    """
    # 1. ניקוי שמות העמודות מרווחים כדי שהבדיקה תהיה אמינה
    df_courses.columns = df_courses.columns.str.strip()
    df_avail.columns = df_avail.columns.str.strip()

    # אינדיקטורים לזיהוי קבצים
    # בקובץ קורסים חייבת להיות עמודה של שם הקורס
    is_course_file_valid = any(col in df_courses.columns for col in ['שם קורס', 'שם הקורס', 'Course Name'])
    
    # בקובץ זמינות חייבת להיות עמודה של שם המרצה
    is_avail_file_valid = any(col in df_avail.columns for col in ['שם מלא', 'שם מרצה', 'שם המרצה'])

    # בדיקה האם המשתמש החליף בין הקבצים
    courses_look_like_avail = any(col in df_courses.columns for col in ['שם מלא', 'שם מרצה'])
    avail_looks_like_courses = any(col in df_avail.columns for col in ['שם קורס', 'שם הקורס'])

    if courses_look_like_avail and avail_looks_like_courses:
        st.error("🛑 **שגיאה: נראה שהחלפת בין הקבצים!**")
        st.write("העלית את קובץ הזמינות למקום של קובץ הקורסים (ולהפך). נא להעלות מחדש בסדר הנכון.")
        return False

    if not is_course_file_valid:
        st.error("🛑 **שגיאה בקובץ הקורסים**")
        st.write("לא נמצאה העמודה 'שם קורס'. וודא שהעלית את הקובץ הנכון.")
        st.write(f"העמודות שזוהו בקובץ: {list(df_courses.columns)}")
        return False

    if not is_avail_file_valid:
        st.error("🛑 **שגיאה בקובץ הזמינות**")
        st.write("לא נמצאה העמודה 'שם מלא' (של המרצה). וודא שהעלית את הקובץ הנכון.")
        return False

    return True

def validate_data_content(df_courses):
    """בדיקת כפילויות בתוך הנתונים"""
    duplicates = df_courses[df_courses.duplicated(subset=['Year', 'Semester', 'שם קורס'], keep=False)]
    if not duplicates.empty:
        st.error("🛑 נמצאו כפילויות בקובץ הקורסים! לא ניתן להמשיך.")
        st.dataframe(duplicates)
        return False
    return True

# ================= 3. PROCESSING & SCHEDULING =================

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
    df_courses['
