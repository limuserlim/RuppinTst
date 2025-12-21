import streamlit as st
import pandas as pd
import numpy as np
import io

# ================= 1. HELPER FUNCTIONS & CLEANING =================

def clean_text(text):
    """ניקוי רווחים, הסרת רווחים כפולים והמרה למחרוזת"""
    if pd.isna(text) or str(text).strip() == "":
        return None
    text = str(text).strip()
    return " ".join(text.split())

def parse_availability_string(avail_str):
    """
    מפענח מחרוזת כמו '16-17, 17-18' לסט של שעות בודדות.
    Strict Parsing: רק מה שכתוב מפורשות נחשב פנוי.
    """
    slots = set()
    if pd.isna(avail_str):
        return slots
    
    # ניקוי והפרדה
    parts = str(avail_str).replace(';', ',').split(',')
    
    for part in parts:
        part = part.strip()
        if '-' in part:
            try:
                start_s, end_s = part.split('-')
                start = int(start_s)
                end = int(end_s)
                # הטווח הוא [start, end), כלומר 16-17 נותן את שעה 16
                for h in range(start, end):
                    slots.add(h)
            except ValueError:
                continue
    return slots

def load_uploaded_file(uploaded_file):
    """טעינת קובץ שהועלה ב-Streamlit"""
    if uploaded_file is None:
        return None
    
    # מנסה לקרוא כ-Excel או CSV
    try:
        if uploaded_file.name.endswith('.csv'):
            # ניסיון קידודים שונים לקבצי CSV
            try:
                return pd.read_csv(uploaded_file, encoding='utf-8')
            except UnicodeDecodeError:
                uploaded_file.seek(0)
                return pd.read_csv(uploaded_file, encoding='cp1255')
        else:
            return pd.read_excel(uploaded_file)
    except Exception as e:
        st.error(f"שגיאה בטעינת הקובץ: {e}")
        return None

# ================= 2. PRE-PROCESSING & VALIDATION =================

def preprocess_courses(df):
    """ניקוי ונרמול טבלת קורסים"""
    # הסרת שורות רפאים
    df = df.dropna(how='all')
    df = df[df['שם קורס'].notna() & df['שם מרצה'].notna()]
    
    # נרמול שמות
    for col in ['שם קורס', 'שם מרצה', 'מרחב']:
        if col in df.columns:
            df[col] = df[col].apply(clean_text)
            
    # המרת שמות עמודות לאנגלית לשימוש פנימי
    col_map = {
        'שם קורס': 'Course',
        'שם מרצה': 'Lecturer',
        'סמסטר': 'Semester',
        'שעות': 'Duration',
        'מרחב': 'Space',
        'יום': 'FixDay',
        'שעה': 'FixHour',
        'שנה': 'Year',
        'קישור': 'LinkID'
    }
    df = df.rename(columns=col_map)
    
    # המרות טיפוסים
    df['Duration'] = pd.to_numeric(df['Duration'], errors='coerce').fillna(0).astype(int)
    df['Semester'] = pd.to_numeric(df['Semester'], errors='coerce').fillna(0).astype(int)
    df['FixDay'] = pd.to_numeric(df['FixDay'], errors='coerce').astype('Int64') 
    df['FixHour'] = pd.to_numeric(df['FixHour'], errors='coerce').astype('Int64')
    
    # מפתח ייחודי לבדיקת כפילויות
    df['UniqueKey'] = df['Year'].astype(str) + "_" + df['Semester'].astype(str) + "_" + df['Course']
    
    return df

def preprocess_availability(df):
    """עיבוד טבלת זמינות למבנה נח"""
    df = df.dropna(how='all')
    
    # חיפוש עמודת שם מרצה
    lecturer_col = [c for c in df.columns if 'מרצה' in c]
    if not lecturer_col:
        st.error("לא נמצאה עמודת 'שם מרצה' בקובץ הזמינות.")
        return None, None, None
    
    df = df.rename(columns={lecturer_col[0]: 'Lecturer'})
    df = df[df['Lecturer'].notna()]
    df['Lecturer'] = df['Lecturer'].apply(clean_text)
    
    availability_db = {}
    lecturer_sparsity = {} 
    
    for _, row in df.iterrows():
        lecturer = row['Lecturer']
        availability_db[lecturer] = {}
        total_slots = 0
        
        for col in df.columns:
            if col == 'Lecturer' or col == 'TIMESTAMP': continue
            
            # זיהוי עמודות יום-סמסטר (XY)
            if len(str(col)) == 2 and str(col).isdigit():
                day = int(str(col)[0])
                semester = int(str(col)[1])
                
                slots = parse_availability_string(row[col])
                if not slots: continue 
                
                if semester not in availability_db[lecturer]:
                    availability_db[lecturer][semester] = {}
                
                availability_db[lecturer][semester][day] = slots
                total_slots += len(slots)
        
        lecturer_sparsity[lecturer] = total_slots

    return availability_db, lecturer_sparsity, df

# ================= 3. CORE LOGIC & SCHEDULING =================

def check_strict_intersection(courses_df, avail_db):
    valid_lecturers = set(avail_db.keys())
    missing_mask = ~courses_df['Lecturer'].isin(valid_lecturers)
    missing_courses = courses_df[missing_mask]
    
    if not missing_courses.empty:
        st.warning(f"הוסרו {len(missing_courses)} קורסים כי למרצים שלהם אין קובץ זמינות:")
        st.write(missing_courses['Lecturer'].unique())
        
    return courses_df[~missing_mask].copy()

def check_unique_integrity(courses_df):
    dupes = courses_df[courses_df.duplicated(subset='UniqueKey', keep=False)]
    if not dupes.empty:
        st.error("CRITICAL ERROR: נמצאו קורסים כפולים (אותו שם, שנה וסמסטר):")
        st.dataframe(dupes[['Course', 'Year', 'Semester']])
        return False
    return True

def get_schedule_waves(df, sparsity_scores):
    df['Sparsity'] = df['Lecturer'].map(sparsity_scores).fillna(0)
    
    wave_a = df[df['LinkID'].notna() & (df['FixDay'].notna() | df['FixHour'].notna())].copy()
    wave_b = df[df['LinkID'].isna() & (df['FixDay'].notna() | df['FixHour'].notna())].copy()
    wave_c = df[df['LinkID'].notna() & df['FixDay'].isna() & df['FixHour'].isna()].copy()
    
    remaining = df.drop(wave_a.index).drop(wave_b.index).drop(wave_c.index)
    wave_d_e = remaining.sort_values(by=['Sparsity', 'Duration'], ascending=[True, False])

    return [wave_a, wave_b, wave_c, wave_d_e]

class SchoolScheduler:
    def __init__(self, courses, avail_db):
        self.courses = courses
        self.avail_db = avail_db
        self.schedule = []
        self.unscheduled = []
        self.student_busy = {} 
        self.hours_range = range(8, 22)
        
    def is_student_busy(self, year, semester, day, hour):
        return self.student_busy.get(year, {}).get(semester, {}).get(day, {}).get(hour, False)
    
    def mark_student_busy(self, year, semester, day, hour):
        if year not in self.student_busy: self.student_busy[year] = {}
        if semester not in self.student_busy[year]: self.student_busy[year][semester] = {}
        if day not in self.student_busy[year][semester]: self.student_busy[year][semester][day] = {}
        self.student_busy[year][semester][day][hour] = True

    def is_lecturer_available(self, lecturer, semester, day, hour):
        if lecturer not in self.avail_db: return False
        if semester not in self.avail_db[lecturer]: return False
        if day not in self.avail_db[lecturer][semester]: return False
        return hour in self.avail_db[lecturer][semester][day]
    
    def is_lecturer_busy_in_schedule(self, lecturer, semester, day, hour):
        for s in self.schedule:
            if s['Lecturer'] == lecturer and s['Semester'] == semester and s['Day'] == day and s['Hour'] == hour:
                return True
        return False

    def find_slot(self, course_row, linked_courses=None):
        lecturer = course_row['Lecturer']
        duration = int(course_row['Duration'])
        semester = int(course_row['Semester'])
        year = course_row['Year']
        space = course_row['Space']
        fix_day = course_row['FixDay']
        fix_hour = course_row['FixHour']
        
        days_to_check = [1, 2, 3, 4, 5]
        if pd.notna(fix_day):
            days_to_check = [int(fix_day)]
            
        hours_search = list(self.hours_range)
        if str(space).lower() == 'zoom':
            hours_search = sorted(hours_search, reverse=True)
            
        if pd.notna(fix_hour):
            hours_search = [int(fix_hour)]

        for day in days_to_check:
            for start_h in hours_search:
                if start_h + duration > 22: continue

                valid_slot = True
                group_to_check = [course_row] if linked_courses is None else linked_courses
                
                for current_course in group_to_check:
                    c_lecturer = current_course['Lecturer']
                    c_year = current_course['Year']
                    
                    for h in range(start_h, start_h + duration):
                        if not self.is_lecturer_available(c_lecturer, semester, day, h):
                            valid_slot = False; break
                        if self.is_lecturer_busy_in_schedule(c_lecturer, semester, day, h):
                            valid_slot = False; break
                        if self.is_student_busy(c_year, semester, day, h):
                            valid_slot = False; break
                    if not valid_slot: break
                
                if valid_slot:
                    return day, start_h
        return None, None

    def commit_schedule(self, course_row, day, start_hour):
        duration = int(course_row['Duration'])
        for h in range(start_hour, start_hour + duration):
            self.schedule.append({
                'Year': course_row['Year'],
                'Semester': course_row['Semester'],
                'Day': day,
                'Hour': h,
                'Course': course_row['Course'],
                'Lecturer': course_row['Lecturer'],
                'Space': course_row['Space'],
                'Unique
