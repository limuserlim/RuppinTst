import streamlit as st
import pandas as pd
import numpy as np
import io
import traceback

# ================= 1. UTILS =================

def force_to_string(val):
    """המרה אגרסיבית לטקסט למניעת שגיאות אובייקטים"""
    if val is None or pd.isna(val):
        return None
    try:
        return str(val).strip()
    except:
        return ""

def load_uploaded_file(uploaded_file):
    if uploaded_file is None: return None
    try:
        filename = getattr(uploaded_file, 'name', 'unknown.xlsx')
        if filename.endswith('.csv'):
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

def parse_availability(row, cols):
    """פונקציה מוגנת לפיענוח זמינות"""
    for col in cols:
        val = row[col]
        if pd.isna(val): continue
        
        s_col = str(col).strip()
        # הנחה: שם העמודה הוא XY (למשל 12)
        if len(s_col) < 2 or not s_col[:2].isdigit(): continue
        
        try:
            day = int(s_col[0])
            semester = int(s_col[1])
            if not (1 <= day <= 7): continue
            
            parts = str(val).replace(';', ',').split(',')
            for p in parts:
                p = p.strip()
                if '-' in p:
                    start_s, end_s = p.split('-')
                    start = int(float(start_s))
                    end = int(float(end_s))
                    for h in range(start, end):
                        yield (semester, day, h)
        except:
            continue

# ================= 2. PRE-PROCESSING =================

def preprocess_courses(df):
    df = df.dropna(how='all')
    df.columns = df.columns.str.strip()
    
    # מיפוי עמודות חכם ומורחב
    col_map = {}
    for col in df.columns:
        c = str(col).lower().strip()
        
        # זיהוי משך קורס (כולל שעות, ש"ס)
        if 'משך' in c or 'duration' in c or 'ש"ס' in c: 
            col_map[col] = 'Duration'
        # זיהוי שעות ספציפיות אם המילה "שעות" מופיעה לבד (בזהירות)
        elif c == 'שעות' or c == 'hours':
            col_map[col] = 'Duration'
            
        elif 'קורס' in c or 'course' in c: col_map[col] = 'Course'
        elif 'מרצה' in c or 'lecturer' in c: col_map[col] = 'Lecturer'
        elif 'סמסטר' in c or 'semester' in c: col_map[col] = 'Semester'
        elif 'מרחב' in c or 'space' in c: col_map[col] = 'Space'
        
        # זיהוי אילוצים קשיחים
        elif 'יום' in c or 'day' in c: col_map[col] = 'FixDay'
        elif 'התחלה' in c or 'start' in c or ('שעה' in c and 'שעות' not in c): col_map[col] = 'FixHour'
        
        elif 'שנה' in c or 'year' in c: col_map[col] = 'Year'
        elif 'קישור' in c or 'link' in c: col_map[col] = 'LinkID'
            
    df = df.rename(columns=col_map)
    
    # בדיקת חובה
    if 'Course' not in df.columns or 'Lecturer' not in df.columns:
        return pd.DataFrame()

    df = df[df['Course'].notna() & df['Lecturer'].notna()]
    
    # === מילוי ברירות מחדל קריטיות למניעת קריסה ===
    
    # 1. משך: אם לא זוהה, נניח שעתיים
    if 'Duration' not in df.columns:
        df['Duration'] = 2 
    else:
        df['Duration'] = pd.to_numeric(df['Duration'], errors='coerce').fillna(2).astype(int)

    # 2. שדות טקסט: המרה בטוחה
    for col in ['Course', 'Lecturer', 'LinkID', 'Space', 'Year']:
        if col not in df.columns:
            df[col] = None
        df[col] = df[col].apply(force_to_string)

    # 3. שדות מספריים: המרה בטוחה
    if 'Semester' not in df.columns:
        df['Semester'] = 1
    else:
        df['Semester'] = pd.to_numeric(df['Semester'], errors='coerce').fillna(1).astype(int)
            
    for col in ['FixDay', 'FixHour']:
        if col not in df.columns:
            df[col] = None
        else:
            df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
            
    return df

def preprocess_availability(df):
    df = df.dropna(how='all')
    df.columns = df.columns.str.strip()
    
    # זיהוי מרצה
    lecturer_col = None
    for kw in ['מרצה', 'שם', 'lecturer', 'name']:
        matches = [c for c in df.columns if kw in str(c).lower()]
        if matches:
            lecturer_col = matches[0]
            break
            
    if not lecturer_col:
        st.error("לא נמצאה עמודת שם מרצה.")
        return None, None
    
    df = df.rename(columns={lecturer_col: 'Lecturer'})
    df = df[df['Lecturer'].notna()]
    
    # המרה לטקסט בטוח
    df['Lecturer'] = df['Lecturer'].apply(force_to_string)
    
    avail_db = {}
    sparsity = {}
    
    # זיהוי עמודות זמינות (מספריות)
    avail_cols = [c for c in df.columns if len(str(c))>=2 and str(c)[:2].isdigit()]
    
    for _, row in df.iterrows():
        lec = row['Lecturer']
        if not lec: continue
        
        if lec not in avail_db:
            avail_db[lec] = {}
            
        count = 0
        for sem, day, h in parse_availability(row, avail_cols):
            if sem not in avail_db[lec]: avail_db[lec][sem] = {}
            if day not in avail_db[lec][sem]: avail_db[lec][sem][day] = set()
            avail_db[lec][sem][day].add(h)
            count += 1
            
        sparsity[lec] = count
        
    return avail_db, sparsity

# ================= 3. SCHEDULER =================

def get_waves(df, sparsity):
    # וידוא סופי שהעמודות קיימות לפני המיון (למניעת KeyError)
    for c in ['LinkID', 'FixDay', 'FixHour', 'Sparsity', 'Duration']:
        if c not in df.columns:
            if c == 'Duration': df[c] = 2
            elif c == 'Sparsity': df[c] = 0
            else: df[c] = None
        
    df['Sparsity'] = df['Lecturer'].map(sparsity).fillna(0)
    
    # חלוקה לגלים
    wave_a = df[df['LinkID'].notna() & (df['FixDay'].notna() | df['FixHour'].notna())].copy()
    wave_b = df[df['LinkID'].isna() & (df['FixDay'].notna() | df['FixHour'].notna())].copy()
    wave_c = df[df['LinkID'].notna() & df['FixDay'].isna() & df['FixHour'].isna()].copy()
    
    rem = df.drop(wave_a.index).drop(wave_b.index).drop(wave_c.index)
    
    # המיון שגרם לשגיאה - כעת מוגן כי Duration בטוח קיים
    wave_d = rem.sort_values(by=['Sparsity', 'Duration'], ascending=[True, False])
    
    return [wave_a, wave_b, wave_c, wave_d]

class Scheduler:
    def __init__(self, courses, avail_db):
        self.courses = courses
        self.avail_db = avail_db
        self.schedule = []
        self.errors = []
        self.busy = {} 
        
    def is_student_busy(self, year, sem, day, h):
        return self.busy.get(year, {}).get(sem, {}).get(day, {}).get(h, False)
    
    def set_student_busy(self, year, sem, day, h):
        if year not in self.busy: self.busy[year] = {}
        if sem not in self.busy[year]: self.busy[year][sem] = {}
        if day not in self.busy[year][sem]: self.busy[year][sem][day] = {}
        self.busy[year][sem][day][h] = True

    def run(self):
        # קריאה לפונקציה המוגנת
        waves = get_waves(self.courses, self.avail_db)
        processed_links = set()
        
        bar = st.progress(0)
        
        for idx, wave in enumerate(waves):
            bar.progress((idx+1)/4)
            for _, row in wave.iterrows():
                try:
                    lid = row
