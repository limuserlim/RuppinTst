import streamlit as st
import pandas as pd
import numpy as np
import io
import traceback

# ================= 1. UTILS =================

def safe_str(val):
    """המרה בטוחה לטקסט"""
    if val is None or pd.isna(val):
        return None
    try:
        # טיפול באובייקטים מורכבים
        if isinstance(val, (dict, list, tuple, set)):
            return str(val)
        s = str(val).strip()
        if s.lower() in ['nan', 'none', '', 'null']:
            return None
        return s
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
    """פיענוח זמינות"""
    for col in cols:
        val = row[col]
        if pd.isna(val): continue
        
        s_col = str(col).strip()
        # הנחה: שם העמודה הוא לפחות 2 ספרות (XY)
        if len(s_col) < 2 or not s_col[:2].isdigit(): continue
        
        try:
            # ספרה ראשונה יום, שנייה סמסטר (למשל 12 -> יום 1 סמסטר 2)
            day = int(s_col[0])
            semester = int(s_col[1])
            
            if not (1 <= day <= 7): continue
            
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
    
    col_map = {}
    for col in df.columns:
        c = str(col).lower().strip()
        if 'משך' in c or 'duration' in c or 'ש"ס' in c or c == 'שעות': col_map[col] = 'Duration'
        elif 'קורס' in c or 'course' in c: col_map[col] = 'Course'
        elif 'מרצה' in c or 'lecturer' in c: col_map[col] = 'Lecturer'
        elif 'סמסטר' in c or 'semester' in c: col_map[col] = 'Semester'
        elif 'מרחב' in c or 'space' in c: col_map[col] = 'Space'
        elif 'יום' in c or 'day' in c: col_map[col] = 'FixDay'
        elif 'התחלה' in c or 'start' in c or ('שעה' in c and 'שעות' not in c): col_map[col] = 'FixHour'
        elif 'שנה' in c or 'year' in c: col_map[col] = 'Year'
        elif 'קישור' in c or 'link' in c: col_map[col] = 'LinkID'
            
    df = df.rename(columns=col_map)
    
    if 'Course' not in df.columns or 'Lecturer' not in df.columns:
        return pd.DataFrame()

    df = df[df['Course'].notna() & df['Lecturer'].notna()]
    
    # המרת שדות טקסט
    for col in ['Course', 'Lecturer', 'Space', 'LinkID', 'Year']:
        if col not in df.columns: df[col] = None
        df[col] = df[col].apply(safe_str)

    # המרות מספריות (עם ערכי ברירת מחדל חכמים יותר)
    if 'Duration' in df.columns:
        df['Duration'] = pd.to_numeric(df['Duration'], errors='coerce').fillna(2).astype(int)
    else:
        df['Duration'] = 2 # ברירת מחדל
        
    if 'Semester' in df.columns:
        # אם יש סמסטר "A" או "B", ננסה להמיר
        df['Semester'] = pd.to_numeric(df['Semester'], errors='coerce').fillna(1).astype(int)
    else:
        df['Semester'] = 1
        
    for col in ['FixDay', 'FixHour']:
        if col not in df.columns: df[col] = None
        else: df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
            
    return df

def preprocess_availability(df):
    df = df.dropna(how='all')
    df.columns = df.columns.str.strip()
    
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
    df['Lecturer'] = df['Lecturer'].apply(safe_str)
    df = df[df['Lecturer'].notna()]
    
    avail_db = {}
    sparsity = {}
    
    # חיפוש עמודות זמינות
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

# ================= 3. SCHEDULER ENGINE =================

def get_waves(df, sparsity, shuffle=False):
    # וידוא עמודות
    for col in ['LinkID', 'FixDay', 'FixHour', 'Duration']:
        if col not in df.columns:
            if col == 'Duration': df[col] = 2
            else: df[col] = None
    
    # מילוי ציון
    df['Sparsity'] = df['Lecturer'].map(sparsity).fillna(0).astype(int)
    
    wave_a = df[df['LinkID'].notna() & (df['FixDay'].notna() | df['FixHour'].notna())].copy()
    wave_b = df[df['LinkID'].isna() & (df['FixDay'].notna() | df['FixHour'].notna())].copy()
    wave_c = df[df['LinkID'].notna() & df['FixDay'].isna() & df['FixHour'].isna()].copy()
    
    processed = list(wave_a.index) + list(wave_b.index) + list(wave_c.index)
    rem = df[~df.index.isin(processed)].copy()
    
    if shuffle:
        wave_d = rem.sample(frac=1).reset_index(drop=True)
    else:
        wave_d = rem.sort_values(by=['Sparsity', 'Duration'], ascending=[True, False])
    
    return [wave_a, wave_b, wave_c, wave_d]

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
        self.busy[year][sem][day][h] = True

    def run(self, shuffle=False):
        waves = get_waves(self.courses, self.sparsity, shuffle=shuffle)
        
        self.schedule = []
        self.errors = []
        self.busy = {}
        self.processed_links = set()
        
        for wave in waves:
            for _, row in wave.iterrows():
                try:
                    lid = row['LinkID']
                    if lid and lid in self.processed_links:
                        continue
                        
                    group = [row]
                    if lid:
                        group_df = self.courses[self.courses['LinkID'] == lid]
                        group = group_df.to_dict('records')
                        self.processed_links.add(lid)
                    
                    self.attempt_schedule(row, group)
                    
                except Exception:
                    self.errors.append({
                        'Course': row.get('Course'),
                        'Lecturer': row.get('Lecturer'),
                        'Reason': "System Error",
                        'Debug': traceback.format_exc()
                    })
        
        return pd.DataFrame(self.schedule), pd.DataFrame(self.errors)

    def attempt_schedule(self, main_row, group):
        try:
            dur = int(main_row['Duration'])
            sem = int(main_row['Semester'])
        except:
            self.fail(group, "Missing Duration/Semester")
            return

        days = [int(main_row['FixDay'])] if pd.notna(main_row['FixDay']) else [1,2,3,4,5]
        hours = list(range(8, 22))
        
        if str(main_row.get('Space')).lower() == 'zoom': hours.reverse()
        if pd.notna(main_row['FixHour']): hours = [int(main_row['FixHour'])]

        for day in days:
            for start_h in hours:
                if start_h + dur > 22: continue
                
                valid, reason = self.check_valid(group, sem, day, start_h, dur)
                if valid:
                    self.commit(group, sem, day, start_h, dur)
                    return
        
        # אם נכשל, נשתמש בסיבה האחרונה שנשמרה (או "אין מקום")
        reason = "No Slot Available (Constraints/Overlap)"
        if pd.notna(main_row['FixDay']): reason += " [Fixed Day]"
        self.fail(group, reason)

    def check_valid(self, group, sem, day, start_h, dur):
        """
        בודק ולידציה ומחזיר (True, "") או (False, "Reason")
        """
        for item in group:
            lec = item['Lecturer']
            year = item.get('Year')
            
            for h in range(start_h, start_h + dur):
                # 1. בדיקת זמינות מרצה (Availability File)
                if lec not in self.avail_db:
                    return False, f"Lecturer '{lec}' not in availability file"
                
                if sem not in self.avail_db[lec]:
                    # ניסיון Fallback: אולי המרצה זמין בסמסטר אחר וזה תופס? 
                    # כרגע נשאיר קשיח, אבל נדווח
                    return False, f"Lecturer '{lec}' has no hours in Semester {sem}"
                
                if day not in self.avail_db[lec][sem]:
                    return False, f"Lecturer '{lec}' unavailable on Day {day} (Sem {sem})"
                
                if h not in self.avail_db[lec][sem][day]:
                    return False, f"Lecturer '{lec}' unavailable at {h}:00"
                
                # 2. בדיקת התנגשות מרצה (כבר שובץ)
                for s in self.schedule:
                    if s['Lecturer'] == lec and s['Day'] == day and s['Hour'] == h and s['Semester'] == sem:
                        return False, f"Lecturer '{lec}' double booked at Day {day} {h}:00"
                
                # 3. בדיקת סטודנטים
                if year and self.is_student_busy(year, sem, day, h):
                    return False, f"Student cohort '{year}' busy at {h}:00"
                    
        return True, ""

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

def main_process(courses_file, avail_file, iterations=30):
    if not courses_file or not avail_file: return
    
    st.write("---")
    st.info("🔄 טוען נתונים...")
    
    try:
        # 1. טעינה
        c_raw = load_uploaded_file(courses_file)
        a_raw = load_uploaded_file(avail_file)
        
        if c_raw is None or a_raw is None: return
        
        # 2. עיבוד זמינות
        avail_db, sparsity = preprocess_availability(a_raw)
        if not avail_db: return
        
        # 3. עיבוד קורסים
        courses = preprocess_courses(c_raw)
        if courses.empty:
            st.error("קובץ קורסים ריק/לא תקין.")
            return

        # === DIAGNOSTICS: הצגת נתונים למשתמש ===
        with st.expander("🔍 נתוני אבחון (לחץ לפתיחה)"):
            st.write(f"מספר קורסים שנקלטו: {len(courses)}")
            st.write(f"מספר מרצים עם זמינות: {len(avail_db)}")
            
            # בדיקת התאמת סמסטרים
            sem_courses = courses['Semester'].unique()
            st.write(f"סמסטרים בקובץ קורסים: {sem_courses}")
            
            # בדיקת דוגמה למרצה
            sample_lec = courses.iloc[0]['Lecturer']
            st.write(f"בדיקת מרצה לדוגמה: '{sample_lec}'")
            if sample_lec in avail_db:
                st.success(f"נמצא בזמינות! סמסטרים זמינים: {list(avail_db[sample_lec].keys())}")
            else:
                st.error("לא נמצא בזמינות (ודא שאין רווחים מיותרים בשם בקובץ המקור)")

        # 4. חיתוך (רק אזהרה)
        valid_lecs = set(avail_db.keys())
        mask = courses['Lecturer'].isin(valid_lecs)
        removed = len(courses) - mask.sum()
        if removed > 0:
            st.warning(f"⚠️ שים לב: {removed} קורסים עם מרצים שלא נמצאו בקובץ הזמינות.")
            
        final_courses = courses[mask].copy()
        if final_courses.empty:
            st.error("אין קורסים ברי שיבוץ.")
            return
            
        # 5. אופטימיזציה
        st.success(f"✅ מתחיל אופטימיזציה ({iterations} חזרות)...")
        
        best_sched = pd.DataFrame()
        best_errors = pd.DataFrame()
        min_errors = float('inf')
        
        bar = st.progress(0)
        status = st.empty()
        
        for i in range(iterations + 1):
            is_shuffle = (i > 0)
            bar.progress(i / (iterations + 1))
            status.text(f"הרצה {i}...")
            
            sched = Scheduler(final_courses, avail_db, sparsity)
            curr_s, curr_e = sched.run(shuffle=is_shuffle)
            
            if len(curr_e) < min_errors:
                min_errors = len(curr_e)
                best_sched = curr_s
                best_errors = curr_e
                if min_errors == 0: break
                
        bar.empty()
        status.empty()
        
        # 6. תוצאות
        st.markdown(f"### 🏆 תוצאות (שגיאות: {min_errors})")
        c1, c2 = st.columns(2)
        c1.metric("שובצו", len(best_sched))
        c2.metric("נכשלו", len(best_errors), delta_color="inverse")
        
        if not best_sched.empty:
            st.dataframe(best_sched)
            st.download_button("📥 הורד מערכת", best_sched.to_csv(index=False).encode('utf-8-sig'), "schedule.csv")
            
        if not best_errors.empty:
            st.error("דוח שגיאות מפורט:")
            st.dataframe(best_errors)
            st.download_button("⚠️ הורד שגיאות", best_errors.to_csv(index=False).encode('utf-8-sig'), "errors.csv")
            
    except Exception:
        st.error("שגיאה קריטית:")
        st.code(traceback.format_exc())

if __name__ == "__main__":
    st.warning("Run via menu.py")
