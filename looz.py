import streamlit as st
import pandas as pd
import numpy as np
import io
import traceback

# ================= 1. UTILS =================

def force_to_string(val):
    """המרה אגרסיבית לטקסט למניעת קריסות מאובייקטים מורכבים"""
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
    """פיענוח זמינות מוגן"""
    for col in cols:
        val = row[col]
        if pd.isna(val): continue
        
        s_col = str(col).strip()
        # הנחה: שם העמודה מכיל לפחות 2 ספרות (יום+סמסטר)
        if len(s_col) < 2 or not s_col[:2].isdigit(): continue
        
        try:
            day = int(s_col[0])
            semester = int(s_col[1])
            if not (1 <= day <= 7): continue
            
            parts = str(val).replace(';', ',').split(',')
            for p in parts:
                p = p.strip()
                if '-' in p:
                    # טיפול בפורמט "08-10"
                    p_split = p.split('-')
                    start = int(float(p_split[0]))
                    end = int(float(p_split[1]))
                    for h in range(start, end):
                        yield (semester, day, h)
        except (ValueError, IndexError):
            continue

# ================= 2. PRE-PROCESSING =================

def preprocess_courses(df):
    """ניקוי ונרמול קורסים"""
    df = df.dropna(how='all')
    df.columns = df.columns.str.strip()
    
    # מיפוי עמודות
    col_map = {}
    for col in df.columns:
        c = str(col).lower().strip()
        if 'משך' in c or 'duration' in c or 'ש"ס' in c or c == 'שעות' or c == 'hours': 
            col_map[col] = 'Duration'
        elif 'קורס' in c or 'course' in c: col_map[col] = 'Course'
        elif 'מרצה' in c or 'lecturer' in c: col_map[col] = 'Lecturer'
        elif 'סמסטר' in c or 'semester' in c: col_map[col] = 'Semester'
        elif 'מרחב' in c or 'space' in c: col_map[col] = 'Space'
        elif 'יום' in c or 'day' in c: col_map[col] = 'FixDay'
        elif 'התחלה' in c or 'start' in c or ('שעה' in c and 'שעות' not in c): col_map[col] = 'FixHour'
        elif 'שנה' in c or 'year' in c: col_map[col] = 'Year'
        elif 'קישור' in c or 'link' in c: col_map[col] = 'LinkID'
            
    df = df.rename(columns=col_map)
    
    # בדיקת עמודות חובה
    if 'Course' not in df.columns or 'Lecturer' not in df.columns:
        return pd.DataFrame()

    df = df[df['Course'].notna() & df['Lecturer'].notna()]
    
    # השלמת עמודות חסרות (למניעת KeyError)
    for req in ['Duration', 'Semester', 'FixDay', 'FixHour', 'LinkID', 'Space', 'Year']:
        if req not in df.columns:
            df[req] = None

    # === המרה אגרסיבית לטקסט למניעת קריסות ===
    text_cols = ['Course', 'Lecturer', 'Space', 'LinkID', 'Year']
    for col in text_cols:
        df[col] = df[col].apply(force_to_string)

    # המרות מספריות בטוחות
    # Duration: ברירת מחדל 2 אם חסר
    df['Duration'] = pd.to_numeric(df['Duration'], errors='coerce').fillna(2).astype(int)
    
    # Semester: ברירת מחדל 1 אם חסר
    df['Semester'] = pd.to_numeric(df['Semester'], errors='coerce').fillna(1).astype(int)
            
    for col in ['FixDay', 'FixHour']:
        df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
            
    return df

def preprocess_availability(df):
    """עיבוד טבלת זמינות"""
    df = df.dropna(how='all')
    df.columns = df.columns.str.strip()
    
    # זיהוי עמודת שם מרצה
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
    
    # המרה לטקסט
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
    # וידוא שכל העמודות קיימות (רשת ביטחון נוספת)
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
    
    # מיון
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
        waves = get_waves(self.courses, self.avail_db)
        processed_links = set()
        
        bar = st.progress(0)
        
        for idx, wave in enumerate(waves):
            bar.progress((idx+1)/4)
            for _, row in wave.iterrows():
                try:
                    lid = row['LinkID']
                    if lid and lid in processed_links:
                        continue
                        
                    group = [row]
                    if lid:
                        group_df = self.courses[self.courses['LinkID'] == lid]
                        group = group_df.to_dict('records')
                        processed_links.add(lid)
                    
                    self.attempt_schedule(row, group)
                    
                except Exception:
                    # דיווח על שגיאה במקום קריסה
                    self.errors.append({
                        'Course': row.get('Course'),
                        'Lecturer': row.get('Lecturer'),
                        'Reason': "System Error (Row Processing)",
                        'LinkID': row.get('LinkID')
                    })
        
        bar.empty()
        return pd.DataFrame(self.schedule), pd.DataFrame(self.errors)

    def attempt_schedule(self, main_row, group):
        try:
            dur = int(main_row['Duration'])
            sem = int(main_row['Semester'])
        except:
            self.fail(group, "Invalid Duration/Semester")
            return

        days = [int(main_row['FixDay'])] if pd.notna(main_row['FixDay']) else [1,2,3,4,5]
        hours = list(range(8, 22))
        
        if str(main_row.get('Space')).lower() == 'zoom': hours.reverse()
        if pd.notna(main_row['FixHour']): hours = [int(main_row['FixHour'])]

        for day in days:
            for start_h in hours:
                if start_h + dur > 22: continue
                
                if self.check_valid(group, sem, day, start_h, dur):
                    self.commit(group, sem, day, start_h, dur)
                    return
                    
        reason = "No Slot"
        if pd.notna(main_row['FixDay']): reason += " (Fixed Day)"
        self.fail(group, reason)

    def check_valid(self, group, sem, day, start_h, dur):
        for item in group:
            lec = item['Lecturer']
            year = item['Year']
            
            for h in range(start_h, start_h + dur):
                if lec not in self.avail_db or sem not in self.avail_db[lec] or \
                   day not in self.avail_db[lec][sem] or h not in self.avail_db[lec][sem][day]:
                    return False
                
                for s in self.schedule:
                    if s['Lecturer'] == lec and s['Day'] == day and s['Hour'] == h and s['Semester'] == sem:
                        return False
                
                if year and self.is_student_busy(year, sem, day, h):
                    return False
        return True

    def commit(self, group, sem, day, start_h, dur):
        for item in group:
            for h in range(start_h, start_h + dur):
                self.schedule.append({
                    'Year': item.get('Year'),
                    'Semester': sem,
                    'Day': day,
                    'Hour': h,
                    'Course': item.get('Course'),
                    'Lecturer': item.get('Lecturer'),
                    'Space': item.get('Space'),
                    'LinkID': item.get('LinkID')
                })
                if item.get('Year'):
                    self.set_student_busy(item['Year'], sem, day, h)

    def fail(self, group, reason):
        for item in group:
            self.errors.append({
                'Course': item.get('Course'),
                'Lecturer': item.get('Lecturer'),
                'Reason': reason,
                'LinkID': item.get('LinkID')
            })

# ================= 4. MAIN =================

def main_process(courses_file, avail_file, iterations=20):
    if not courses_file or not avail_file: return
    
    st.write("---")
    st.info("🔄 טוען נתונים...")
    
    try:
        c_raw = load_uploaded_file(courses_file)
        a_raw = load_uploaded_file(avail_file)
        
        if c_raw is None or a_raw is None: return
        
        # 1. עיבוד זמינות
        avail_db, sparsity = preprocess_availability(a_raw)
        if not avail_db: return
        
        # 2. עיבוד קורסים
        courses = preprocess_courses(c_raw)
        if courses.empty:
            st.error("לא נמצאו נתונים תקינים בקובץ הקורסים (בדוק שמות עמודות).")
            return

        # 3. בדיקת חיתוך מרצים
        valid_lecs = set(avail_db.keys())
        mask = courses['Lecturer'].isin(valid_lecs)
        removed = len(courses) - mask.sum()
        if removed > 0:
            st.warning(f"הוסרו {removed} קורסים (מרצה לא נמצא בקובץ זמינות).")
            
        final_courses = courses[mask].copy()
        
        if final_courses.empty:
            st.error("אין קורסים לשיבוץ.")
            return
            
        # 4. הרצה
        st.success("✅ נתונים תקינים. מתחיל שיבוץ...")
        sched = Scheduler(final_courses, avail_db)
        df_res, df_err = sched.run()
        
        # 5. תוצאות
        st.markdown("### 📊 תוצאות")
        c1, c2 = st.columns(2)
        c1.metric("שובצו", len(df_res))
        c2.metric("לא שובצו", len(df_err), delta_color="inverse")
        
        if not df_res.empty:
            st.dataframe(df_res)
            st.download_button("📥 הורד מערכת", df_res.to_csv(index=False).encode('utf-8-sig'), "schedule.csv")
            
        if not df_err.empty:
            st.error("פירוט שגיאות:")
            st.dataframe(df_err)
            st.download_button("⚠️ הורד שגיאות", df_err.to_csv(index=False).encode('utf-8-sig'), "errors.csv")
            
    except Exception:
        st.error("שגיאה כללית במערכת:")
        st.code(traceback.format_exc())

if __name__ == "__main__":
    st.warning("Run via menu.py")
