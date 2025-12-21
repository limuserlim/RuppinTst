import streamlit as st
import pandas as pd
import numpy as np
import io
import os

# ================= CONFIGURATION =================
st.set_page_config(page_title="LOOZ Scheduler", layout="wide", page_icon="📅")

# מיפויים וקבועים
SEMESTER_MAP = {'א': 1, 'ב': 2, 'ג': 3, '1': 1, '2': 2, 1: 1, 2: 2}
HOURS_RANGE = range(8, 22)

# שמות עמודות צפויים (לצורך זיהוי קבצים)
KEYWORDS_COURSES = ['שם קורס', 'שם הקורס', 'Course', 'Course Name']
KEYWORDS_AVAIL = ['שם מלא', 'שם מרצה', 'שם המרצה', 'Timestamp']

# מיפוי עמודות פנימי (נרמול שמות לעבודה נוחה בקוד)
COLUMN_MAPPING = {
    'שם קורס': 'Course', 'שם הקורס': 'Course',
    'מרצה': 'Lecturer', 'שם מרצה': 'Lecturer',
    'סמסטר': 'Semester',
    'שעות': 'Duration', 'משך': 'Duration',
    'מרחב': 'Space', 'מיקום': 'Space',
    'אילוץ יום': 'FixDay', 'יום': 'FixDay',
    'אילוץ שעה': 'FixHour', 'שעה': 'FixHour',
    'שנה': 'Year', 'שנתון': 'Year',
    'קישור': 'LinkID', 'קבוצה': 'LinkID'
}

# ================= 1. UTILS =================

def check_headers(df, keywords):
    """בדיקה האם הקובץ מכיל את העמודות הנדרשות"""
    cols = [str(c).strip() for c in df.columns]
    return any(k in cols for k in keywords)

def clean_text(text):
    """ניקוי רווחים וטיפול בערכים חסרים"""
    if pd.isna(text) or str(text).strip() == "": return None
    return " ".join(str(text).strip().split())

def parse_availability_string(avail_str):
    """פיענוח מחרוזת זמינות (16-17, 18-19)"""
    slots = set()
    if pd.isna(avail_str) or str(avail_str).strip() == "": return slots
    # החלפת מפרידים שונים בפסיק
    parts = str(avail_str).replace(';', ',').replace('\n', ',').split(',')
    for part in parts:
        if '-' in part:
            try:
                start, end = map(int, part.strip().split('-'))
                slots.update(range(start, end))
            except: continue
    return slots

def smart_load_dataframe(uploaded_file, file_type):
    """טעינת קובץ חכמה (CSV/Excel) כולל חיפוש כותרות"""
    if uploaded_file is None: return None, "לא נבחר קובץ"
    
    filename = uploaded_file.name
    keywords = KEYWORDS_COURSES if file_type == 'courses' else KEYWORDS_AVAIL
    
    try:
        if filename.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
            
        # בדיקה ראשונית
        if check_headers(df, keywords): return df, None
        
        # אם לא מצאנו כותרות, ננסה לדלג על שורות ריקות בהתחלה (נפוץ באקסל)
        if not filename.endswith('.csv'):
            for i in range(1, 10):
                uploaded_file.seek(0)
                df = pd.read_excel(uploaded_file, header=i)
                if check_headers(df, keywords):
                    return df.dropna(how='all', axis=1), None
                    
        return None, f"❌ לא נמצאו עמודות מתאימות בקובץ {filename}"
    except Exception as e:
        return None, f"❌ שגיאה בטעינה: {str(e)}"

# ================= 2. DATA PROCESSING =================

def preprocess_courses(df):
    """נרמול נתוני קורסים"""
    # החלפת שמות עמודות לאנגלית
    df = df.rename(columns=COLUMN_MAPPING)
    
    # המרות טיפוסים
    cols_to_numeric = ['FixDay', 'FixHour', 'Duration', 'Semester']
    for col in cols_to_numeric:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # ברירות מחדל
    if 'Year
