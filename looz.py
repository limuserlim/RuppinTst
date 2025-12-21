import streamlit as st
import pandas as pd
import numpy as np
import io

# ================= 1. UTILS =================

def safe_str(val):
    """
    המרה בטוחה ואגרסיבית למחרוזת כדי למנוע קריסות
    """
    if val is None or pd.isna(val):
        return None
    
    # המרה בכוח של אובייקטים מורכבים למחרוזת
    if isinstance(val, (dict, list, tuple, set)):
        return str(val)
        
    s = str(val).strip()
    if s == "" or s.lower() == "nan" or s.lower() == "none":
        return None
    return s

def parse_availability_string(avail_str):
    slots = set()
    if pd.isna(avail_str):
        return slots
    
    s = str(avail_str).replace(';', ',')
    parts = s.split(',')
    
    for part in parts:
        part = part.strip()
        try:
            if '-' in part:
                p_split = part.split('-')
                start = int(float(p_split[0]))
                end = int(float(p_split[1]))
                for h in range(start, end):
                    slots.add(h)
        except (ValueError, IndexError):
            continue
    return slots

def load_uploaded_file(uploaded_file):
    if uploaded_file is None:
        return None
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

# ================= 2. PRE-PROCESSING =================

def preprocess_courses(df):
    """ניקוי ונרמול טבלת קורסים"""
    df = df.dropna(how='all')
    df.columns = df.columns.str.strip()
    
    # מיפוי עמודות
    col_map = {}
    for col in df.columns:
        c_lower = str(col).lower().strip()
        if 'קורס' in c_lower or 'course' in c_lower: col_map[col] = 'Course'
        elif 'מרצה' in c_lower or 'lecturer' in c_lower: col_map[col] = 'Lecturer'
        elif 'סמסטר' in c_lower or 'semester' in c_lower: col_map[col] = 'Semester'
        elif 'משך' in c_lower or 'duration' in c_lower or 'שעות' in c_lower: col_map[col] = 'Duration'
        elif 'מרחב' in c_lower or 'space' in c_lower or 'location' in c_lower: col_map[col] = 'Space'
        elif 'יום' in c_lower or 'day' in c_lower: col_map[col] = 'FixDay'
        elif 'שעה' in c_lower or 'hour' in c_lower: col_map[col] = 'FixHour'
        elif 'שנה' in c_lower or 'year' in c_lower: col_map[col] = 'Year'
        elif 'קישור' in c_lower or 'link' in c_lower: col_map[col] = 'LinkID'
            
    df = df.rename(columns=col_map)
    
    # בדיקת עמודות חובה
    if 'Course' not in df.columns or 'Lecturer' not in df.columns:
        return pd.DataFrame() # החזר ריק

    df = df[df['Course'].notna() & df['Lecturer'].notna()]
    
    # === התיקון הקריטי: המרת כל עמודות המפתח ל-String בלבד ===
    # זה מונע את שגיאת unhashable type dict
    text_cols = ['Course', 'Lecturer', 'Space', 'LinkID', 'Year']
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].apply(safe_str)
        else:
            df[col] = None # יצירת עמודה חסרה

    # המרות מספריות
    for col in ['Duration', 'Semester']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
            
    for col in ['FixDay', 'FixHour']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
    
    # יצירת מפתח ייחודי (בטוח)
    df['UniqueKey'] = df['Year'].astype(str) + "_" + df['Semester'].astype(str) + "_" + df['Course'].astype(str)
    
    return df

def preprocess_availability(df):
    """עיבוד טבלת זמינות"""
    df = df.dropna(how='all')
    df.columns = df.columns.str.strip()
    
    # זיהוי עמודת מרצה
    lecturer_col = None
    for kw in ['מרצה', 'שם', 'lecturer', 'name']:
        matches = [c for c in df.columns if kw.lower() in str(c).lower()]
        if matches:
            lecturer_col = matches[0]
            break
            
    if not lecturer_col:
        st.error(f"לא נמצאה עמודת שם מרצה. העמודות הן: {list(df.columns)}")
        return None, None, None
    
    df = df.rename(columns={lecturer_col: 'Lecturer'})
    df = df[df['Lecturer'].notna()]
    df['Lecturer'] = df['Lecturer'].apply(safe_str)
    
    availability_db = {}
    lecturer_sparsity = {}
    
    for _, row in df.iterrows():
        lecturer = row['Lecturer']
        if not lecturer: continue
        
        availability_db[lecturer] = {}
        total_slots = 0
        
        for col in df.columns:
            if col == 'Lecturer' or 'time' in str(col).lower(): continue
            
            col_str = str(col).strip()
            if len(col_str) >= 2 and col_str[:2].isdigit():
                try:
                    day = int(col_str[0])
                    semester = int(col_str[1])
                    if 1 <= day <= 7:
                        slots = parse_availability_string(row[col])
                        if slots:
                            if semester not in availability_db[lecturer]:
                                availability_db[lecturer][semester] = {}
                            availability_db[lecturer][semester][day] = slots
                            total_slots += len(slots)
                except:
                    continue
        
        lecturer_sparsity[lecturer] = total_slots
        
    return availability_db, lecturer_sparsity, df

# ================= 3. SCHEDULER ENGINE =================

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

    def find_slot(self, row, group_rows=None):
        try:
            duration = int(row['Duration'])
            semester = int(row['Semester'])
        except: return None, None
        
        fixed_days = [int(row['FixDay'])] if pd.notna(row['FixDay']) else [1,2,3,4,5]
        
        hours = list(self.hours_range)
        if str(row.get('Space')).lower() == 'zoom': hours.reverse()
        if pd.notna(row['FixHour']): hours = [int(row['FixHour'])]

        rows_to_check = group_rows if group_rows else [row]

        for day in fixed_days:
            for start_h in hours:
                if start_h + duration > 22: continue
                
                valid = True
                for item in rows_to_check:
                    l_item = item['Lecturer']
                    
                    for h in range(start_h, start_h + duration):
                        # 1. Lecturer Availability
                        if l_item not in self.avail_db or \
                           semester not in self.avail_db[l_item] or \
                           day not in self.avail_db[l_item][semester] or \
                           h not in self.avail_db[l_item][semester][day]:
                            valid = False; break
                        
                        # 2. Lecturer Clash
                        for s in self.schedule:
                            if s['Lecturer'] == l_item and s['Day'] == day and s['Hour'] == h and s['Semester'] == semester:
                                valid = False; break
                        if not valid: break
                        
                        # 3. Student Clash
                        y_item = item.get('Year')
                        if y_item and self.is_student_busy(y_item, semester, day, h):
                            valid = False; break
                    
                    if not valid: break
                
                if valid: return day, start_h
        return None, None

    def commit(self, row, day, start_h):
        dur = int(row['Duration'])
        for h in range(start_h, start_h + dur):
            self.schedule.append({
                'Year': row.get('Year'),
                'Semester': row.get('Semester'),
                'Day': day,
                'Hour': h,
                'Course': row.get('Course'),
                'Lecturer': row.get('Lecturer'),
                'Space': row.get('Space'),
                'LinkID': row.get('LinkID')
            })
            if row.get('Year'):
                self.mark_student_busy(row['Year'], row['Semester'], day, h)

    def run(self):
        waves = get_schedule_waves(self.courses, self.avail_db)
        processed_links = set()
        
        bar = st.progress(0)
        
        for i, wave in enumerate(waves):
            bar.progress((i + 1) / 4)
            for _, row in wave.iterrows():
                try:
                    # מנגנון הגנה משולש מפני dict
                    raw_lid = row.get('LinkID')
                    if isinstance(raw_lid, (dict, list)):
                        lid = str(raw_lid)
                    else:
                        lid = raw_lid
                        
                    if pd.notna(lid) and lid in processed_links:
                        continue
                        
                    group = None
                    if pd.notna(lid):
                        group = self.courses[self.courses['LinkID'] == lid].to_dict('records')
                        processed_links.add(lid)
                        
                    day, start_h = self.find_slot(row, group)
                    
                    if day is not None:
                        if group:
                            for g_item in group: self.commit(g_item, day, start_h)
                        else:
                            self.commit(row, day, start_h)
                    else:
                        items = group if group else [row]
                        reason = "No Slot found"
                        if pd.notna(row['FixDay']): reason += " (Fixed Constraint)"
                        
                        for item in items:
                            if isinstance(item, pd.Series): item = item.to_dict()
                            self.unscheduled.append({
                                'Course': item.get('Course'),
                                'Lecturer': item.get('Lecturer'),
                                'Reason': reason,
                                'LinkID': item.get('LinkID')
                            })
                            
                except Exception:
                    continue
                    
        bar.empty()
        return pd.DataFrame(self.schedule), pd.DataFrame(self.unscheduled)

# ================= 4. MAIN ENTRY POINT =================

def main_process(courses_file, avail_file, iterations=20):
    if not courses_file or not avail_file:
        return

    st.write("---")
    st.info(f"🔄 מעבד נתונים...")

    # Load
    c_raw = load_uploaded_file(courses_file)
    a_raw = load_uploaded_file(avail_file)
    
    if c_raw is None or a_raw is None: return

    # Process
    avail_db, scores, _ = preprocess_availability(a_raw)
    if not avail_db: return
    
    courses_clean = preprocess_courses(c_raw)
    if courses_clean.empty:
        st.error("לא נמצאו קורסים תקינים בקובץ.")
        return

    # Check Intersection
    valid_lecs = set(avail_db.keys())
    # הגנה נוספת לוודא שאין dicts בתוך שם המרצה
    safe_lecs = courses_clean['Lecturer'].apply(lambda x: x if isinstance(x, str) else str(x))
    
    mask = safe_lecs.isin(valid_lecs)
    removed = courses_clean[~mask]
    if not removed.empty:
        st.warning(f"תשומת לב: הוסרו {len(removed)} קורסים כי למרצה אין נתוני זמינות.")
        
    courses_ready = courses_clean[mask].copy()
    
    if courses_ready.empty:
        st.error("אין קורסים לשיבוץ.")
        return

    # Run
    st.success("✅ נתונים תקינים. מריץ שיבוץ...")
    scheduler = SchoolScheduler(courses_ready, avail_db)
    sched_df, err_df = scheduler.run()
    
    # Results
    st.markdown("### 📊 תוצאות")
    col1, col2, col3 = st.columns(3)
    col1.metric("שובצו", len(sched_df))
    col2.metric("נכשלו", len(err_df), delta_color="inverse")
    
    if not sched_df.empty:
        st.dataframe(sched_df)
        st.download_button("📥 הורד מערכת (CSV)", 
                           sched_df.to_csv(index=False).encode('utf-8-sig'), 
                           "schedule.csv", "text/csv")
        
    if not err_df.empty:
        st.error("חלק מהקורסים לא שובצו:")
        st.dataframe(err_df)
        st.download_button("⚠️ הורד שגיאות (CSV)", 
                           err_df.to_csv(index=False).encode('utf-8-sig'), 
                           "errors.csv", "text/csv")

if __name__ == "__main__":
    st.warning("Run via menu.py")
