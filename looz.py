import pandas as pd
import numpy as np
import streamlit as st
import io

# ================= CONFIGURATION =================

# 1. מיפוי שמות קשיח (Hardcoded) - מקרים שהאלגוריתם לא ינחש לבד
HARDCODED_MAPPING = {
    'מתרגל': 'נועה גינו',                          # שם גנרי לאדם ספציפי
    'אורנה גרופינקל קולמן': 'אורנה גורפינקל קולמן' # תיקון שגיאת כתיב
}

# 2. מיפוי סמסטרים למספרים (חובה להתאמה לקובץ הזמינות)
SEMESTER_MAP = {
    'א': 1, 'ב': 2, 'ג': 3, 'ד': 4,
    'a': 1, 'b': 2, 'c': 3, 'd': 4, 
    1: 1, 2: 2, 3: 3, 4: 4 
}

# טווח שעות ליום לימודים
HOURS_RANGE = range(8, 22)

# מילות מפתח לזיהוי כותרות
KEYWORDS_COURSES = ['שם קורס', 'שם הקורס', 'Course Name']
KEYWORDS_AVAIL = ['שם מלא', 'שם מרצה', 'שם המרצה']

# ================= 1. UTILS: CLEANING & PARSING =================

def check_headers(df, keywords):
    """בדיקה האם הכותרות תקינות"""
    cols = [str(c).strip() for c in df.columns]
    return any(k in cols for k in keywords)

def smart_load_dataframe(file_input, file_type):
    """
    טעינה חכמה: תומכת גם בנתיב קובץ (str) וגם באובייקט Streamlit.
    """
    keywords = KEYWORDS_COURSES if file_type == 'courses' else KEYWORDS_AVAIL
    
    # זיהוי שם הקובץ לצורך לוגים
    filename = file_input if isinstance(file_input, str) else file_input.name
    
    try:
        # קריאה ראשונית
        if filename.endswith('.csv'):
            df = pd.read_csv(file_input)
        else:
            df = pd.read_excel(file_input)

        if check_headers(df, keywords): return df, None

        # ניסיון תיקון לאקסל (דילוג על שורות לוגו)
        if not filename.endswith('.csv'):
            for i in range(1, 10):
                # אם זה אובייקט של סטרימליט, צריך לאפס את המצביע
                if not isinstance(file_input, str):
                    file_input.seek(0)
                
                df = pd.read_excel(file_input, header=i)
                if check_headers(df, keywords):
                    df = df.dropna(how='all', axis=1)
                    return df, None
                    
        return None, f"❌ קובץ {filename} : מבנה לא תקין (לא נמצאו כותרות מתאימות)"
    except Exception as e:
        return None, f"❌ שגיאה בטעינה ({str(e)})"

def clean_text(text):
    if pd.isna(text) or str(text).strip() == "": return None
    return " ".join(str(text).strip().split())

def parse_availability_string(avail_str):
    slots = set()
    if pd.isna(avail_str) or str(avail_str).strip() == "": return slots
    parts = str(avail_str).replace(';', ',').split(',')
    for part in parts:
        if '-' in part:
            try:
                start, end = map(int, part.strip().split('-'))
                slots.update(range(start, end))
            except: continue
    return slots

def get_tokens(name):
    """פירוק שם למילים לצורך השוואה גנרית"""
    clean = str(name).replace('-', ' ').replace('(', ' ').replace(')', ' ')
    return set(clean.split())

# ================= 2. DATA PROCESSING =================

def process_availability_multi_semester(df_avail):
    """
    בונה מילון זמינות תלת-מימדי: {שם מרצה: {סמסטר: {יום: {שעות}}}}
    תומך בעמודות כמו '12' (יום 1 סמסטר 2)
    """
    lecturer_availability = {}
    df_avail = df_avail[df_avail['שם מלא'].notna()].copy()
    
    for index, row in df_avail.iterrows():
        raw_name = row.get('שם מלא', '')
        lecturer = clean_text(raw_name)
        if not lecturer: continue
        
        lecturer_availability[lecturer] = {}
        
        for col_name in df_avail.columns:
            col_str = str(col_name).strip()
            # זיהוי תבנית XY (יום, סמסטר)
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

def resolve_lecturer_names(df_courses, avail_lecturer_names):
    """
    נרמול שמות היברידי:
    1. מיפוי קשיח (Hardcoded)
    2. מיפוי גנרי (Fuzzy Matching)
    """
    # שלב 1: החלפה קשיחה
    df_courses['מרצה'] = df_courses['מרצה'].replace(HARDCODED_MAPPING)
    
    avail_names_set = set(avail_lecturer_names)
    current_course_lecturers = df_courses['מרצה'].dropna().unique()
    fuzzy_mapping = {}

    # שלב 2: סריקה גנרית
    for c_name in current_course_lecturers:
        if c_name in avail_names_set: continue
            
        c_tokens = get_tokens(c_name)
        if not c_tokens: continue

        for a_name in avail_names_set:
            a_tokens = get_tokens(a_name)
            common = c_tokens.intersection(a_tokens)
            
            # תנאי התאמה: 2 מילים זהות או מילה יחידה זהה
            if len(common) >= 2 or (len(c_tokens) == 1 and len(common) == 1):
                fuzzy_mapping[c_name] = a_name
                break 

    if fuzzy_mapping:
        df_courses['מרצה'] = df_courses['מרצה'].replace(fuzzy_mapping)
        
    return df_courses

# ================= 3. SCHEDULING ENGINE =================

def attempt_schedule(df_courses, lecturer_availability):
    schedule = []
    unscheduled = []
    
    # גריד תפוסה: (שנה, סמסטר) -> יום -> שעות
    years = df_courses['Year'].unique()
    semesters = df_courses['Semester'].unique()
    
    grid_student = {} 
    grid_lecturer = {l: {d: set() for d in range(1,7)} for l in lecturer_availability}

    for y in years:
        for s in semesters:
            grid_student[(y, s)] = {d: set() for d in range(1,7)}

    def is_slot_free(lecturer, year, semester, day, start, duration, is_zoom=False):
        if start + duration > 22: return False
        
        # 1. בדיקת זמינות בסמסטר הרלוונטי
        lect_sem_data = lecturer_availability.get(lecturer, {}).get(semester, {})
        lect_slots = lect_sem_data.get(day, set())
        
        needed = set(range(start, start + duration))
        if not needed.issubset(lect_slots): return False

        # 2. בדיקת חפיפות
        for h in range(start, start + duration):
            if h in grid_lecturer.get(lecturer, {}).get(day, set()): return False
            if h in grid_student.get((year, semester), {}).get(day, set()): return False
            
        # 3. לוגיקת זום (מרווח לפני שיעור)
        if is_zoom:
            gap_start = max(8, start - 2)
            for h in range(gap_start, start):
                if h in grid_student.get((year, semester), {}).get(day, set()):
                    return False
        return True

    def book_slot(lecturer, year, semester, day, start, duration, course_name, space_type):
        for h in range(start, start + duration):
            if lecturer in grid_lecturer: grid_lecturer[lecturer][day].add(h)
            if (year, semester) in grid_student: grid_student[(year, semester)][day].add(h)
        
        schedule.append({
            'Year': year, 'Semester': semester, 'Day': day,
            'Hour': start, 'Course': course_name,
            'Lecturer': lecturer, 'Duration': duration,
            'Space': space_type, 'EndHour': start + duration
        })

    # הפרדה לקבוצות (Links) ולבודדים
    groups = df_courses[df_courses['קישור'].notna()]
    singles = df_courses[df_courses['קישור'].isna()]

    # שיבוץ קבוצות
    for lid in groups['קישור'].unique():
        grp = groups[groups['קישור'] == lid]
        duration = int(grp.iloc[0]['שעות'])
        fixed_day = grp.iloc[0]['אילוץ יום']
        fixed_hour = grp.iloc[0]['אילוץ שעה']
        
        assigned = False
        days_check = [int(fixed_day)] if pd.notna(fixed_day) else range(1, 6)
        hours_check = [int(fixed_hour)] if pd.notna(fixed_hour) else HOURS_RANGE

        for d in days_check:
            for h in hours_check:
                fits_all = True
                for _, row in grp.iterrows():
                    if not is_slot_free(row['מרצה'], row['Year'], row['Semester'], d, h, duration):
                        fits_all = False; break
                if fits_all:
                    for _, row in grp.iterrows():
                        book_slot(row['מרצה'], row['Year'], row['Semester'], d, h, duration, row['שם קורס'], row['מרחב'])
                    assigned = True; break
            if assigned: break
        
        if not assigned:
            for _, row in grp.iterrows():
                unscheduled.append({'Course': row['שם קורס'], 'Lecturer': row['מרצה'], 'Reason': 'Link Conflict'})

    # שיבוץ בודדים
    for _, row in singles.iterrows():
        lect, course, duration = row['מרצה'], row['שם קורס'], int(row['שעות'])
        year, sem = row['Year'], row['Semester']
        is_zoom = 'זום' in str(row['מרחב'])
        
        fixed_day = row['אילוץ יום']
        fixed_hour = row['אילוץ שעה']
        
        search_hours = list(HOURS_RANGE)
        if is_zoom: search_hours.reverse()
        
        days_check = [int(fixed_day)] if pd.notna(fixed_day) else range(1, 6)
        
        assigned = False
        if pd.notna(fixed_hour):
            h = int(fixed_hour)
            for d in days_check:
                if is_slot_free(lect, year, sem, d, h, duration, is_zoom):
                    book_slot(lect, year, sem, d, h, duration, course, row['מרחב'])
                    assigned = True; break
        else:
            for d in days_check:
                for h in search_hours:
                    if is_slot_free(lect, year, sem, d, h, duration, is_zoom):
                        book_slot(lect, year, sem, d, h, duration, course, row['מרחב'])
                        assigned = True; break
                if assigned: break
        
        if not assigned:
            unscheduled.append({'Course': course, 'Lecturer': lect, 'Reason': 'No Slot Found'})

    return pd.DataFrame(schedule), pd.DataFrame(unscheduled)

# ================= 4. OPTIMIZATION LOOP =================

def optimize_schedule(df_courses, lecturer_availability, iterations=30):
    # חישוב Sparsity
    sparsity_scores = {}
    for lect, sem_data in lecturer_availability.items():
        total = 0
        for s_data in sem_data.values():
            total += sum(len(hours) for hours in s_data.values())
        sparsity_scores[lect] = total
    
    df_courses['Sparsity'] = df_courses['מרצה'].map(sparsity_scores).fillna(999)
    
    # דגלי מיון
    df_courses['Constraint'] = df_courses['אילוץ יום'].notna() | df_courses['אילוץ שעה'].notna()
    df_courses['Link'] = df_courses['קישור'].notna()
    df_courses['Zoom'] = df_courses['מרחב'].astype(str).str.contains('זום', na=False)
    
    best_schedule = pd.DataFrame()
    best_unscheduled = pd.DataFrame()
    min_errors = float('inf')
    
    # פרוגרס בר של סטרימליט
    prog_bar = st.progress(0)
    
    for i in range(iterations):
        prog_bar.progress((i + 1) / iterations)
        
        # מיון סטוכסטי (עם רעש אקראי)
        df_courses['Rnd'] = np.random.rand(len(df_courses))
        df_sorted = df_courses.sort_values(
            by=['Constraint', 'Link', 'Zoom', 'Sparsity', 'שעות', 'Rnd'],
            ascending=[False, False, False, True, False, False]
        )
        
        sched, unsched = attempt_schedule(df_sorted, lecturer_availability)
        
        if len(unsched) < min_errors:
            min_errors = len(unsched)
            best_schedule = sched
