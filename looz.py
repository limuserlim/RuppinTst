import streamlit as st
import pandas as pd
import numpy as np
import io
import traceback

# ================= 1. UTILS =================

def safe_str(val):
    if val is None or pd.isna(val): return None
    try:
        if isinstance(val, (dict, list, tuple, set)): return str(val)
        s = str(val).strip()
        if s.lower() in ['nan', 'none', '', 'null']: return None
        return s
    except: return ""

def clean_semester(val):
    """המרה חכמה של סמסטר (ב -> 2, א -> 1)"""
    s = str(val).strip().replace("'", "").replace('"', "")
    if s in ['א', 'A', 'a', '1']: return 1
    if s in ['ב', 'B', 'b', '2']: return 2
    if s in ['ג', 'C', 'c', '3']: return 3
    # ניסיון המרה למספר רגיל
    try:
        return int(float(s))
    except:
        return 1 # ברירת מחדל

def load_uploaded_file(uploaded_file):
    if uploaded_file is None: return None
    try:
        filename = getattr(uploaded_file, 'name', 'unknown.xlsx')
        if filename.endswith('.csv'):
            try: return pd.read_csv(uploaded_file, encoding='utf-8')
            except: return pd.read_csv(uploaded_file, encoding='cp1255')
        else: return pd.read_excel(uploaded_file)
    except Exception as e:
        st.error(f"שגיאה בטעינת הקובץ: {e}")
        return None

def parse_availability(row, cols):
    """
    מפענח עמודות זמן כמו '12', '22'.
    הנחה: ספרה ראשונה = יום, ספרה שנייה = סמסטר.
    """
    for col in cols:
        val = row[col]
        if pd.isna(val): continue
        
        s_col = str(col).strip()
        # וידוא שזה פורמט תקין (למשל 12)
        if len(s_col) < 2 or not s_col[:2].isdigit(): continue
        
        try:
            day = int(s_col[0])      # הספרה הראשונה
            semester = int(s_col[1]) # הספרה השנייה
            
            if not (1 <= day <= 7): continue
            
            # פירוק השעות (למשל "8-9, 9-10")
            parts = str(val).replace(';', ',').split(',')
            for p in parts:
                p = p.strip()
                if '-' in p:
                    p_split = p.split('-')
                    start = int(float(p_split[0]))
                    end = int(float(p_split[1]))
                    for h in range(start, end):
                        yield (semester, day, h)
        except:
            continue

# ================= 2. PRE-PROCESSING =================

def preprocess_courses(df):
    df = df.dropna(how='all')
    df.columns = df.columns.str.strip()
    
    # מיפוי מדויק לפי מה ששלחת
    col_map = {}
    for col in df.columns:
        c = str(col).strip() # רגישות לאותיות ולרווחים
        if c == 'מרצה': col_map[col] = 'Lecturer'
        elif c == 'שם קורס': col_map[col] = 'Course'
        elif c == 'שעות': col_map[col] = 'Duration'
        elif c == 'סמסטר': col_map[col] = 'Semester'
        elif c == 'קישור': col_map[col] = 'LinkID'
        elif c == 'אילוץ יום': col_map[col] = 'FixDay'
        elif c == 'אילוץ שעה': col_map[col] = 'FixHour'
        elif c == 'מרחב': col_map[col] = 'Space'
        elif c == 'שנה': col_map[col] = 'Year'
            
    df = df.rename(columns=col_map)
    
    if 'Course' not in df.columns or 'Lecturer' not in df.columns:
        return pd.DataFrame()

    df = df[df['Course'].notna() & df['Lecturer'].notna()]
    
    # המרות
    for col in ['Course', 'Lecturer', 'Space', 'LinkID', 'Year']:
        if col not in df.columns: df[col] = None
        df[col] = df[col].apply(safe_str)

    # תיקון קריטי: המרת סמסטר עברי למספר
    if 'Semester' in df.columns:
        df['Semester'] = df['Semester'].apply(clean_semester)
    else:
        df['Semester'] = 1
        
    if 'Duration' in df.columns:
        df['Duration'] = pd.to_numeric(df['Duration'], errors='coerce').fillna(2).astype(int)
    else:
        df['Duration'] = 2

    for col in ['FixDay', 'FixHour']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
        else:
            df[col] = None
            
    return df

def preprocess_availability(df):
    df = df.dropna(how='all')
    df.columns = df.columns.str.strip()
    
    lecturer_col = None
    # זיהוי מדויק לפי "שם מלא"
    for col in df.columns:
        if str(col).strip() == "שם מלא":
            lecturer_col = col
            break
            
    # Fallback
    if not lecturer_col:
        for col in df.columns:
            if "שם" in str(col) or "מרצה" in str(col):
                lecturer_col = col
                break
    
    if not lecturer_col:
        st.error("לא נמצאה עמודת 'שם מלא' בקובץ הזמינות.")
        return None, None
    
    df = df.rename(columns={lecturer_col: 'Lecturer'})
    df['Lecturer'] = df['Lecturer'].apply(safe_str)
    df = df[df['Lecturer'].notna()]
    
    avail_db = {}
    sparsity = {}
    
    # זיהוי עמודות זמן (מספרים כמו 12, 22)
    avail_cols = [c for c in df.columns if str(c).isdigit()]
    
    for _, row in df.iterrows():
        lec = row['Lecturer']
        if not lec: continue
        
        # נרמול שם מרצה (הסרת רווחים כפולים)
        lec = " ".join(lec.split())
        
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

# ================= 3. SCHEDULER ENGINE =================

class Scheduler:
    def __init__(self, courses, avail_db, sparsity):
        self.courses = courses
        self.avail_db = avail_db
        self.sparsity = sparsity
        self.schedule = []
        self.errors = []
        self.busy = {} 
        self.processed_links = set()
        
    def is_student_busy(self, year, sem, day, h):
        return self.busy.get(year, {}).get(sem, {}).get(day, {}).get(h, False)
    
    def set_student_busy(self, year, sem, day, h):
        if not year: return
        if year not in self.busy: self.busy[year] = {}
        if sem not in self.busy[year]: self.busy[year][sem] = {}
        if day not in self.busy[year][sem]: self.busy[year][sem][day] = {}
        self.busy[year][sem][day][h]
