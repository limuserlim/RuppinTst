import streamlit as st
import pandas as pd
import numpy as np
import io
import os

# ================= CONFIGURATION =================
# Consts & Mappings
HOURS_RANGE = range(8, 22)

# Keywords to identify file types
KEYWORDS_COURSES = ['שם קורס', 'שם הקורס', 'Course', 'Course Name']
KEYWORDS_AVAIL = ['שם מלא', 'שם מרצה', 'שם המרצה', 'Timestamp']

# Internal Column Mapping
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
    """Check if dataframe contains necessary columns"""
    cols = [str(c).strip() for c in df.columns]
    return any(k in cols for k in keywords)

def clean_text(text):
    """Trim whitespace and handle NaNs"""
    if pd.isna(text) or str(text).strip() == "": return None
    return " ".join(str(text).strip().split())

def parse_availability_string(avail_str):
    """Parse '16-17, 18-19' into a set of hours {16, 18}"""
    slots = set()
    if pd.isna(avail_str) or str(avail_str).strip() == "": return slots
    parts = str(avail_str).replace(';', ',').replace('\n', ',').split(',')
    for part in parts:
        if '-' in part:
            try:
                start, end = map(int, part.strip().split('-'))
                slots.update(range(start, end))
            except: continue
    return slots

def smart_load_dataframe(uploaded_file, file_type):
    """Load CSV or Excel and validate headers"""
    if uploaded_file is None: return None, "לא נבחר קובץ"
    
    filename = uploaded_file.name
    keywords = KEYWORDS_COURSES if file_type == 'courses' else KEYWORDS_AVAIL
    
    try:
        if filename.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
            
        if check_headers(df, keywords): return df, None
        
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
    """Normalize course data"""
    df = df.rename(columns=COLUMN_MAPPING)
    
    cols_to_numeric = ['FixDay', 'FixHour', 'Duration', 'Semester']
    for col in cols_to_numeric:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    if 'Year' not in df.columns: df['Year'] = 1
    
    for col in ['Course', 'Lecturer', 'Space', 'LinkID']:
        if col in df.columns:
            df[col] = df[col].apply(clean_text)
            
    return df

def process_availability_multi_semester(df_avail):
    """Convert availability file to nested dict structure"""
    lecturer_availability = {}
    
    name_col = next((c for c in df_avail.columns if 'שם מרצה' in c or 'שם מלא' in c), None)
    if not name_col: return {}

    df_avail['clean_name'] = df_avail[name_col].apply(clean_text)
    df_avail = df_avail.dropna(subset=['clean_name'])
    df_avail = df_avail.drop_duplicates(subset=['clean_name'], keep='last')

    for _, row in df_avail.iterrows():
        lecturer = row['clean_name']
        lecturer_availability[lecturer] = {}
        for col_name in df_avail.columns:
            col_str = str(col_name).strip()
            if len(col_str) == 2 and col_str.isdigit():
                day_digit = int(col_str[0])
                sem_digit = int(col_str[1])
                if day_digit not in range(1, 7): continue
                if sem_digit not in lecturer_availability[lecturer]:
                    lecturer_availability[lecturer][sem_digit] = {d: set() for d in range(1, 7)}
                slots = parse_availability_string(row[col_name])
                if slots:
                    lecturer_availability[lecturer][sem_digit][day_digit] = slots
    return lecturer_availability

# ================= 3. SCHEDULING ENGINE =================

def run_scheduler(df_courses, lecturer_availability, randomize=False):
    schedule_log = []
    unscheduled_log = []
    
    # Grids
    grid_lecturer = {}
    grid_student = {}
    for l in lecturer_availability:
        grid_lecturer[l] = {d: set() for d in range(1, 7)}
        
    unique_cohorts = df_courses[['Year', 'Semester']].drop_duplicates()
    for _, row in unique_cohorts.iterrows():
        grid_student[(row['Year'], row['Semester'])] = {d: set() for d in range(1, 7)}

    def is_slot_free(lecturer, year, semester, day, start, duration, is_zoom=False):
        if start + duration > 22: return False 
        
        # Whitelist
        lect_sem_data = lecturer_availability.get(lecturer, {}).get(semester, {})
        avail_hours = lect_sem_data.get(day, set())
        needed_hours = set(range(start, start + duration))
        if not needed_hours.issubset(avail_hours): return False

        # Conflicts
        for h in range(start, start + duration):
            if lecturer in grid_lecturer and h in grid_lecturer[lecturer].get(day, set()): return False
            cohort_key = (year, semester)
            if cohort_key in grid_student and h in grid_student[cohort_key].get(day, set()): return False
        return True

    def book_slot(lecturer, year, semester, day, start, duration, course_name, space):
        cohort_key = (year, semester)
        if lecturer not in grid_lecturer: grid_lecturer[lecturer] = {d: set() for d in range(1,7)}
        if cohort_key not in grid_student: grid_student[cohort_key] = {d: set() for d in range(1,7)}

        for h in range(start, start + duration):
            grid_lecturer[lecturer][day].add(h)
            grid_student[cohort_key][day].add(h)
            
        schedule_log.append({
            'Year': year, 'Semester': semester, 'Day': day,
            'Hour': start, 'EndHour': start+duration,
            'Course': course_name, 'Lecturer': lecturer,
            'Space': space, 'Duration': duration
        })

    # Logic
    df_courses['IsLinked'] = df_courses['LinkID'].notna()
    groups = df_courses[df_courses['IsLinked'] == True]
    singles = df_courses[df_courses['IsLinked'] == False]

    # Randomization for iterations
    if randomize:
        singles = singles.sample(frac=1).reset_index(drop=True)
    else:
        singles = singles.sort_values(by='Duration', ascending=False)
    
    # Phase A: Linked
    for lid in groups['LinkID'].unique():
        grp = groups[groups['LinkID'] == lid]
        first = grp.iloc[0]
        duration = int(first['Duration'])
        fix_d = int(first['FixDay']) if pd.notna(first['FixDay']) else None
        fix_h = int(first['FixHour']) if pd.notna(first['FixHour']) else None
        
        days_check = [fix_d] if fix_d else range(1, 6)
        hours_check = [fix_h] if fix_h else HOURS_RANGE
        
        assigned = False
        for d in days_check:
            for h in hours_check:
                fits_all = True
                for _, row in grp.iterrows():
                    if not is_slot_free(row['Lecturer'], row['Year'], row['Semester'], d, h, duration):
                        fits_all = False; break
                if fits_all:
                    for _, row in grp.iterrows():
                        book_slot(row['Lecturer'], row['Year'], row['Semester'], d, h, duration, row['Course'], row['Space'])
                    assigned = True; break
            if assigned: break
        if not assigned:
            for _, row in grp.iterrows():
                unscheduled_log.append({'Course': row['Course'], 'Lecturer': row
