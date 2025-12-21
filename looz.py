import streamlit as st
import pandas as pd
import numpy as np
import io
import traceback

# ================= 1. UTILS =================

def force_to_string(val):
    """המרה אגרסיבית לטקסט למניעת קריסות"""
    if val is None or pd.isna(val):
        return None
    try:
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
        if len(s_col) < 2 or not s_col[:2].isdigit(): continue
        
        try:
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
    
    # המרות בטוחות
    text_cols = ['Course', 'Lecturer', 'Space', 'LinkID', 'Year']
    for col in text_cols:
        if col not in df.columns: df[col] = None
        df[col] = df[col].apply(force_to_string)

    if 'Duration' in df.columns:
        df['Duration'] = pd.to_numeric(df['Duration'], errors='coerce').fillna(2).astype(int)
    else:
        df['Duration'] = 2
        
    if 'Semester' in df.columns:
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
    df['Lecturer'] = df['Lecturer'].apply(force_to_string)
    df = df[df['Lecturer'].notna()]
    
    avail_db = {}
    sparsity = {}
    
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

def get_waves(df, sparsity, shuffle=False):
    # וידוא עמודות
    for col in ['LinkID', 'FixDay', 'FixHour', 'Duration']:
        if col not in df.columns:
            if col == 'Duration': df[col] = 2
            else: df[col] = None
    
    # מילוי ציון (חשוב: המרה ל-int רק אחרי מילוי 0)
    df['Sparsity'] = df['Lecturer'].map(sparsity).fillna(0).astype(int)
    
    # חלוקה לגלים
    wave_a = df[df['LinkID'].notna() & (df['FixDay'].notna() | df['FixHour'].notna())].copy()
    wave_b = df[df['LinkID'].isna() & (df['FixDay'].notna() | df['FixHour'].notna())].copy()
    wave_c = df[df['LinkID'].notna() & df['FixDay'].isna() & df['FixHour'].isna()].copy()
    
    processed = list(wave_a.index) + list(wave_b.index) + list(wave_c.index)
    rem = df[~df.index.isin(processed)].copy()
    
    # גל D: מיון או ערבוב
    if shuffle:
        # ערבוב רנדומלי לניסיון שיפור
        wave_d = rem.sample(frac=1).reset_index(drop=True)
    else:
        # מיון דטרמיניסטי (היגיון בסיסי)
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
                        'LinkID': row.get('LinkID')
                    })
        
        return pd.DataFrame(self.schedule), pd.DataFrame(self.errors)

    def attempt_schedule(self, main_row, group):
        try:
            dur = int(main_row['Duration'])
            sem = int(main_row['Semester'])
        except:
            self.fail(group, "Invalid Data")
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
            year = item.get('Year')
            
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
                self.set_student_busy(item.get('Year'), sem, day, h)

    def fail(self, group, reason):
        for item in group:
            self.errors.append({
                'Course': item.get('Course'),
                'Lecturer': item.get('Lecturer'),
                'Reason': reason,
                'LinkID': item.get('LinkID')
            })

# ================= 4. MAIN =================

def main_process(courses_file, avail_file, iterations=30): # Default = 30
    if not courses_file or not avail_file: return
    
    st.write("---")
    st.info("🔄 טוען נתונים...")
    
    try:
        c_raw = load_uploaded_file(courses_file)
        a_raw = load_uploaded_file(avail_file)
        
        if c_raw is None or a_raw is None: return
        
        avail_db, sparsity = preprocess_availability(a_raw)
        if not avail_db: return
        
        courses = preprocess_courses(c_raw)
        if courses.empty:
            st.error("קובץ הקורסים ריק או לא תקין.")
            return

        valid_lecs = set(avail_db.keys())
        mask = courses['Lecturer'].isin(valid_lecs)
        removed = len(courses) - mask.sum()
        if removed > 0:
            st.warning(f"הוסרו {removed} קורסים (מרצה לא נמצא).")
            
        final_courses = courses[mask].copy()
        if final_courses.empty:
            st.error("אין קורסים לשיבוץ.")
            return
            
        # --- אופטימיזציה (החלק המעודכן) ---
        st.success(f"✅ מתחיל אופטימיזציה ({iterations} חזרות)...")
        
        best_sched = pd.DataFrame()
        best_errors = pd.DataFrame()
        min_errors = float('inf')
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # לולאת הרצות
        # הרצה 0 = דטרמיניסטית (בסיס)
        # הרצות 1+ = רנדומליות
        total_runs = iterations + 1
        
        for i in range(total_runs):
            is_shuffle = (i > 0)
            progress_bar.progress((i + 1) / total_runs)
            status_text.text(f"הרצה {i+1} מתוך {total_runs}...")
            
            # יצירת מופע חדש בכל ריצה כדי לאפס זיכרון
            sched = Scheduler(final_courses, avail_db, sparsity)
            curr_sched, curr_err = sched.run(shuffle=is_shuffle)
            
            err_count = len(curr_err)
            
            # שמירת התוצאה הטובה ביותר
            if err_count < min_errors:
                min_errors = err_count
                best_sched = curr_sched
                best_errors = curr_err
                
                # אם הגענו ל-0 שגיאות, עוצרים (אי אפשר לשפר יותר)
                if min_errors == 0:
                    status_text.success("נמצא פתרון מושלם!")
                    break
        
        progress_bar.empty()
        status_text.empty()
        
        # --- תוצאות ---
        st.markdown(f"### 🏆 התוצאה הטובה ביותר (שגיאות: {min_errors})")
        c1, c2 = st.columns(2)
        c1.metric("שובצו", len(best_sched))
        c2.metric("לא שובצו", len(best_errors), delta_color="inverse")
        
        if not best_sched.empty:
            st.dataframe(best_sched)
            st.download_button("📥 הורד מערכת (CSV)", best_sched.to_csv(index=False).encode('utf-8-sig'), "final_schedule.csv")
            
        if not best_errors.empty:
            st.error("קורסים שלא נמצא להם פתרון:")
            st.dataframe(best_errors)
            st.download_button("⚠️ הורד שגיאות (CSV)", best_errors.to_csv(index=False).encode('utf-8-sig'), "unscheduled_report.csv")
            
    except Exception:
        st.error("שגיאה כללית במערכת:")
        st.code(traceback.format_exc())

if __name__ == "__main__":
    st.warning("Run via menu.py")
