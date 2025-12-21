import streamlit as st
import pandas as pd
import numpy as np
import io
import traceback

# ================= 1. UTILS & SAFE CONVERSIONS =================

def safe_str(val):
    """המרה בטוחה לטקסט"""
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
    """פיענוח שעות מקובץ הזמינות"""
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

# ================= 2. LOGIC ENGINE (THE BRAIN) =================

class SchedulerEngine:
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

    def get_waves(self, shuffle=False):
        df = self.courses.copy()
        df['Sparsity'] = df['Lecturer'].map(self.sparsity).fillna(0).astype(int)
        
        # הפרדה לגלים
        wave_a = df[df['LinkID'].notna() & (df['FixDay'].notna() | df['FixHour'].notna())]
        wave_b = df[df['LinkID'].isna() & (df['FixDay'].notna() | df['FixHour'].notna())]
        wave_c = df[df['LinkID'].notna() & df['FixDay'].isna() & df['FixHour'].isna()]
        
        processed = list(wave_a.index) + list(wave_b.index) + list(wave_c.index)
        wave_d = df[~df.index.isin(processed)].copy()
        
        if shuffle:
            wave_d = wave_d.sample(frac=1).reset_index(drop=True)
        else:
            wave_d = wave_d.sort_values(by=['Sparsity', 'Duration'], ascending=[True, False])
            
        return [wave_a, wave_b, wave_c, wave_d]

    def run(self, shuffle=False):
        self.schedule = []
        self.errors = []
        self.busy = {}
        self.processed_links = set()
        
        waves = self.get_waves(shuffle)
        
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
                    continue
        
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
        
        reason = "No Slot Available"
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

# ================= 3. UI HELPERS =================

def find_default_index(options, keywords):
    """מנסה לנחש אינדקס כדי להקל על המשתמש"""
    for i, opt in enumerate(options):
        for kw in keywords:
            if kw in str(opt).lower():
                return i
    return 0

# ================= 4. MAIN PROCESS =================

def main_process(courses_file, avail_file, iterations=20):
    if not courses_file or not avail_file: return
    
    st.write("---")
    
    # 1. טעינת קבצים גולמיים
    try:
        c_raw = load_uploaded_file(courses_file)
        a_raw = load_uploaded_file(avail_file)
        if c_raw is None or a_raw is None: return
    except:
        st.error("שגיאה בטעינת הקבצים.")
        return

    # 2. ממשק מיפוי עמודות (הפתרון לבעיית השמות)
    st.info("⬇️ אנא בחר את העמודות המתאימות מהקבצים שלך:")
    
    c1, c2 = st.columns(2)
    
    # מיפוי קורסים
    with c1:
        st.subheader("קובץ קורסים")
        c_cols = list(c_raw.columns)
        
        c_lec_col = st.selectbox("עמודת שם מרצה:", c_cols, index=find_default_index(c_cols, ['מרצה', 'lecturer']))
        c_name_col = st.selectbox("עמודת שם קורס:", c_cols, index=find_default_index(c_cols, ['קורס', 'course']))
        c_dur_col = st.selectbox("עמודת משך/שעות:", c_cols, index=find_default_index(c_cols, ['משך', 'duration', 'שעות', 'ש"ס']))
        
        # שדות אופציונליים
        with st.expander("עמודות נוספות (מתקדם)"):
            c_sem_col = st.selectbox("סמסטר:", [None] + c_cols, index=find_default_index(c_cols, ['סמסטר']) + 1)
            c_day_col = st.selectbox("יום אילוץ:", [None] + c_cols, index=find_default_index(c_cols, ['יום', 'day']) + 1)
            c_hour_col = st.selectbox("שעת אילוץ:", [None] + c_cols, index=find_default_index(c_cols, ['שעה', 'hour']) + 1)
            c_link_col = st.selectbox("קבוצת קישור:", [None] + c_cols, index=find_default_index(c_cols, ['קישור', 'link']) + 1)
            c_year_col = st.selectbox("שנתון (Year):", [None] + c_cols, index=find_default_index(c_cols, ['שנה', 'year']) + 1)
            c_space_col = st.selectbox("מרחב/זום:", [None] + c_cols, index=find_default_index(c_cols, ['מרחב', 'space']) + 1)

    # מיפוי זמינות
    with c2:
        st.subheader("קובץ זמינות")
        a_cols = list(a_raw.columns)
        a_lec_col = st.selectbox("עמודת שם מרצה (זמינות):", a_cols, index=find_default_index(a_cols, ['מרצה', 'lecturer', 'name']))

    # כפתור הפעלה אחרי שהמשתמש בחר
    if st.button("🚀 התחל שיבוץ עם העמודות שנבחרו"):
        
        # --- שלב העיבוד ---
        with st.spinner("מעבד נתונים ומנרמל..."):
            
            # 1. הכנת נתוני קורסים
            courses = pd.DataFrame()
            courses['Lecturer'] = c_raw[c_lec_col].apply(safe_str)
            courses['Course'] = c_raw[c_name_col].apply(safe_str)
            
            # משך
            courses['Duration'] = pd.to_numeric(c_raw[c_dur_col], errors='coerce').fillna(2).astype(int)
            
            # אופציונליים
            courses['Semester'] = pd.to_numeric(c_raw[c_sem_col], errors='coerce').fillna(1).astype(int) if c_sem_col else 1
            courses['FixDay'] = pd.to_numeric(c_raw[c_day_col], errors='coerce').astype('Int64') if c_day_col else None
            courses['FixHour'] = pd.to_numeric(c_raw[c_hour_col], errors='coerce').astype('Int64') if c_hour_col else None
            courses['LinkID'] = c_raw[c_link_col].apply(safe_str) if c_link_col else None
            courses['Year'] = c_raw[c_year_col].apply(safe_str) if c_year_col else None
            courses['Space'] = c_raw[c_space_col].apply(safe_str) if c_space_col else None
            
            courses = courses.dropna(subset=['Lecturer', 'Course'])
            
            # 2. הכנת נתוני זמינות
            a_raw = a_raw.rename(columns={a_lec_col: 'Lecturer'})
            a_raw['Lecturer'] = a_raw['Lecturer'].apply(safe_str)
            a_raw = a_raw.dropna(subset=['Lecturer'])
            
            avail_db = {}
            sparsity = {}
            avail_time_cols = [c for c in a_raw.columns if len(str(c))>=2 and str(c)[:2].isdigit()]
            
            for _, row in a_raw.iterrows():
                lec = row['Lecturer']
                if not lec: continue
                if lec not in avail_db: avail_db[lec] = {}
                
                count = 0
                for sem, day, h in parse_availability(row, avail_time_cols):
                    if sem not in avail_db[lec]: avail_db[lec][sem] = {}
                    if day not in avail_db[lec][sem]: avail_db[lec][sem][day] = set()
                    avail_db[lec][sem][day].add(h)
                    count += 1
                sparsity[lec] = count

            # 3. בדיקת חיתוך מרצים
            valid_lecs = set(avail_db.keys())
            mask = courses['Lecturer'].isin(valid_lecs)
            
            # הצגת דוח חיתוך
            if not mask.all():
                missing = courses[~mask]['Lecturer'].unique()
                st.warning(f"⚠️ {len(missing)} מרצים מקובץ הקורסים לא נמצאו בקובץ הזמינות:")
                with st.expander("רשימת המרצים החסרים"):
                    st.write(missing)
            
            final_courses = courses[mask].copy()
            
            if final_courses.empty:
                st.error("לא נותרו קורסים לשיבוץ (0 התאמות בין קורסים לזמינות).")
                return

        # --- שלב השיבוץ ---
        st.success(f"מתחיל אופטימיזציה ({iterations} חזרות)...")
        
        best_sched = pd.DataFrame()
        best_errors = pd.DataFrame()
        min_errors = float('inf')
        
        progress_bar = st.progress(0)
        
        for i in range(iterations + 1):
            progress_bar.progress(i / (iterations + 1))
            engine = SchedulerEngine(final_courses, avail_db, sparsity)
            curr_s, curr_e = engine.run(shuffle=(i > 0))
            
            if len(curr_e) < min_errors:
                min_errors = len(curr_e)
                best_sched = curr_s
                best_errors = curr_e
                if min_errors == 0: break
        
        progress_bar.empty()
        
        # תוצאות
        st.divider()
        c1, c2 = st.columns(2)
        c1.metric("✅ שובצו בהצלחה", len(best_sched))
        c2.metric("❌ לא שובצו", len(best_errors), delta_color="inverse")
        
        if not best_sched.empty:
            st.dataframe(best_sched)
            st.download_button("📥 הורד מערכת (CSV)", best_sched.to_csv(index=False).encode('utf-8-sig'), "schedule.csv")
            
        if not best_errors.empty:
            st.error("קורסים שלא שובצו:")
            st.dataframe(best_errors)
            st.download_button("⚠️ הורד דוח שגיאות", best_errors.to_csv(index=False).encode('utf-8-sig'), "errors.csv")

if __name__ == "__main__":
    pass
