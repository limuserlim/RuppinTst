import streamlit as st
import pandas as pd
import numpy as np
import io
import traceback
import google.generativeai as genai  # ספרייה חדשה

# ================= 1. UTILS & SAFETY =================

def safe_str(val):
    if val is None or pd.isna(val): return None
    try:
        if isinstance(val, (dict, list, tuple, set)): return str(val)
        s = str(val).strip()
        if s.lower() in ['nan', 'none', '', 'null']: return None
        return s
    except: return ""

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
        except: continue

# ================= 2. DATA PRE-PROCESSING =================

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
    if 'Course' not in df.columns or 'Lecturer' not in df.columns: return pd.DataFrame()
    df = df[df['Course'].notna() & df['Lecturer'].notna()]
    text_cols = ['Course', 'Lecturer', 'Space', 'LinkID', 'Year']
    for col in text_cols:
        if col not in df.columns: df[col] = None
        df[col] = df[col].apply(safe_str)
    if 'Duration' in df.columns: df['Duration'] = pd.to_numeric(df['Duration'], errors='coerce').fillna(2).astype(int)
    else: df['Duration'] = 2
    if 'Semester' in df.columns: df['Semester'] = pd.to_numeric(df['Semester'], errors='coerce').fillna(1).astype(int)
    else: df['Semester'] = 1
    for col in ['FixDay', 'FixHour']:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
        else: df[col] = None
    return df

def preprocess_availability(df):
    df = df.dropna(how='all')
    df.columns = df.columns.str.strip()
    lecturer_col = None
    for col in df.columns:
        if "שם" in str(col): lecturer_col = col; break
    if not lecturer_col:
        for kw in ['מרצה', 'lecturer', 'name']:
            for col in df.columns:
                if kw in str(col).lower(): lecturer_col = col; break
            if lecturer_col: break
    if not lecturer_col:
        st.error("לא נמצאה עמודת 'שם' או 'מרצה' בקובץ הזמינות."); return None, None
    df = df.rename(columns={lecturer_col: 'Lecturer'})
    df['Lecturer'] = df['Lecturer'].apply(safe_str)
    df = df[df['Lecturer'].notna()]
    avail_db = {}
    sparsity = {}
    avail_cols = [c for c in df.columns if len(str(c))>=2 and str(c)[:2].isdigit()]
    for _, row in df.iterrows():
        lec = row['Lecturer']
        if not lec: continue
        if lec not in avail_db: avail_db[lec] = {}
        count = 0
        for sem, day, h in parse_availability(row, avail_cols):
            if sem not in avail_db[lec]: avail_db[lec][sem] = {}
            if day not in avail_db[lec][sem]: avail_db[lec][sem][day] = set()
            avail_db[lec][sem][day].add(h)
            count += 1
        sparsity[lec] = count
    return avail_db, sparsity

# ================= 3. SCHEDULER ENGINE =================

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
        wave_a = df[df['LinkID'].notna() & (df['FixDay'].notna() | df['FixHour'].notna())]
        wave_b = df[df['LinkID'].isna() & (df['FixDay'].notna() | df['FixHour'].notna())]
        wave_c = df[df['LinkID'].notna() & df['FixDay'].isna() & df['FixHour'].isna()]
        processed = list(wave_a.index) + list(wave_b.index) + list(wave_c.index)
        wave_d = df[~df.index.isin(processed)].copy()
        if shuffle: wave_d = wave_d.sample(frac=1).reset_index(drop=True)
        else: wave_d = wave_d.sort_values(by=['Sparsity', 'Duration'], ascending=[True, False])
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
                    if lid and lid in self.processed_links: continue
                    group = [row]
                    if lid:
                        group_df = self.courses[self.courses['LinkID'] == lid]
                        group = group_df.to_dict('records')
                        self.processed_links.add(lid)
                    self.attempt_schedule(row, group)
                except: continue
        return pd.DataFrame(self.schedule), pd.DataFrame(self.errors)

    def attempt_schedule(self, main_row, group):
        try:
            dur = int(main_row['Duration'])
            sem = int(main_row['Semester'])
        except: self.fail(group, "Invalid Data"); return
        days = [int(main_row['FixDay'])] if pd.notna(main_row['FixDay']) else [1,2,3,4,5]
        hours = list(range(8, 22))
        if str(main_row.get('Space')).lower() == 'zoom': hours.reverse()
        if pd.notna(main_row['FixHour']): hours = [int(main_row['FixHour'])]
        for day in days:
            for start_h in hours:
                if start_h + dur > 22: continue
                if self.check_valid(group, sem, day, start_h, dur):
                    self.commit(group, sem, day, start_h, dur); return
        reason = "No Slot Available"
        if pd.notna(main_row['FixDay']): reason += " [Fixed Day]"
        self.fail(group, reason)

    def check_valid(self, group, sem, day, start_h, dur):
        for item in group:
            lec = item['Lecturer']
            year = item.get('Year')
            for h in range(start_h, start_h + dur):
                if lec not in self.avail_db or sem not in self.avail_db[lec] or \
                   day not in self.avail_db[lec][sem] or h not in self.avail_db[lec][sem][day]: return False
                for s in self.schedule:
                    if s['Lecturer'] == lec and s['Day'] == day and s['Hour'] == h and s['Semester'] == sem: return False
                if year and self.is_student_busy(year, sem, day, h): return False
        return True

    def commit(self, group, sem, day, start_h, dur):
        for item in group:
            for h in range(start_h, start_h + dur):
                self.schedule.append({
                    'Year': item.get('Year'), 'Semester': sem, 'Day': day, 'Hour': h,
                    'Course': item.get('Course'), 'Lecturer': item.get('Lecturer'),
                    'Space': item.get('Space'), 'LinkID': item.get('LinkID')
                })
                if item.get('Year'): self.set_student_busy(item['Year'], sem, day, h)

    def fail(self, group, reason):
        for item in group:
            self.errors.append({'Course': item.get('Course'), 'Lecturer': item.get('Lecturer'), 'Reason': reason, 'LinkID': item.get('LinkID')})

# ================= 4. CHAT BOT INTEGRATION =================

def init_chat_session(schedule_df, errors_df, api_key):
    """מאתחל את השיחה עם ג'מיני בהקשר של הנתונים"""
    if not api_key: return None
    
    # המרה לטקסט לצורך הפרומפט
    sched_csv = schedule_df.to_csv(index=False)
    err_csv = errors_df.to_csv(index=False)
    
    system_prompt = f"""
    You are a Data Analyst assistant for a school scheduling system.
    Your goal is to answer questions strictly based on the provided data.
    
    Data Source 1: SUCCESSFUL SCHEDULE (CSV format)
    {sched_csv}
    
    Data Source 2: FAILED/UNSCHEDULED COURSES (CSV format)
    {err_csv}
    
    Instructions:
    1. Answer only based on the data above. Do not invent information.
    2. If a user asks "Why didn't X course get scheduled?", look at the FAILED data.
    3. If a user asks "When does Y teach?", look at the SCHEDULE data.
    4. Keep answers concise and factual.
    5. The user speaks Hebrew, so answer in Hebrew.
    """
    
    genai.configure(api_key=api_key)
    # שימוש בטמפרטורה 0 ליצירתיות מינימלית ודיוק מקסימלי
    generation_config = genai.types.GenerationConfig(temperature=0.0)
    
    try:
        model = genai.GenerativeModel("gemini-1.5-flash", generation_config=generation_config)
        chat = model.start_chat(history=[
            {"role": "user", "parts": system_prompt},
            {"role": "model", "parts": "הבנתי. אני אנליסט הנתונים שלך. אענה על שאלות בהתבסס אך ורק על טבלאות השיבוץ והשגיאות שסיפקת, בצורה מדויקת ועניינית."}
        ])
        return chat
    except Exception as e:
        st.error(f"שגיאה בחיבור ל-Gemini: {e}")
        return None

# ================= 5. MAIN PROCESS =================

def main_process(courses_file, avail_file, iterations=30):
    if not courses_file or not avail_file: return
    
    st.write("---")
    
    # Sidebar for API Key
    with st.sidebar:
        st.header("🤖 הגדרות צ'אט (Gemini)")
        api_key = st.text_input("Google Gemini API Key", type="password", help="נדרש כדי לשוחח על התוצאות")
        st.caption("ללא מפתח, הצ'אט לא יופעל.")

    st.info("🔄 טוען נתונים...")
    
    try:
        c_raw = load_uploaded_file(courses_file)
        a_raw = load_uploaded_file(avail_file)
        if c_raw is None or a_raw is None: return
        
        avail_db, sparsity = preprocess_availability(a_raw)
        if not avail_db: return
        courses = preprocess_courses(c_raw)
        if courses.empty: st.error("קובץ הקורסים לא תקין."); return

        valid_lecs = set(avail_db.keys())
        mask = courses['Lecturer'].isin(valid_lecs)
        if not mask.all(): st.warning(f"⚠️ {len(courses)-mask.sum()} מרצים חסרים בזמינות.")
        final_courses = courses[mask].copy()
        if final_courses.empty: st.error("אין קורסים לשיבוץ."); return

        st.success(f"✅ מבצע אופטימיזציה ({iterations} איטרציות)...")
        
        best_sched = pd.DataFrame()
        best_errors = pd.DataFrame()
        min_errors = float('inf')
        
        bar = st.progress(0)
        for i in range(iterations + 1):
            bar.progress(i / (iterations + 1))
            sched = SchedulerEngine(final_courses, avail_db, sparsity)
            s, e = sched.run(shuffle=(i > 0))
            if len(e) < min_errors:
                min_errors = len(e)
                best_sched = s
                best_errors = e
                if min_errors == 0: break
        bar.empty()
        
        st.divider()
        c1, c2 = st.columns(2)
        # ספירת קורסים ייחודיים במקום שעות
        unique_sched = len(best_sched.drop_duplicates(subset=['Course', 'Lecturer'])) if not best_sched.empty else 0
        c1.metric("✅ קורסים שובצו", unique_sched)
        c2.metric("❌ לא שובצו", len(best_errors), delta_color="inverse")
        
        if not best_sched.empty:
            st.dataframe(best_sched)
            st.download_button("📥 הורד מערכת", best_sched.to_csv(index=False).encode('utf-8-sig'), "schedule.csv")
            
        if not best_errors.empty:
            st.error("שגיאות:")
            st.dataframe(best_errors)
            st.download_button("⚠️ הורד דוח שגיאות", best_errors.to_csv(index=False).encode('utf-8-sig'), "errors.csv")

        # --- CHAT INTERFACE ---
        if api_key:
            st.divider()
            st.subheader("💬 שוחח עם הנתונים (AI Analyst)")
            
            # אתחול Session State לצ'אט
            if "chat_history" not in st.session_state:
                st.session_state.chat_history = []
            if "gemini_chat" not in st.session_state:
                st.session_state.gemini_chat = init_chat_session(best_sched, best_errors, api_key)

            # הצגת היסטוריה
            for message in st.session_state.chat_history:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

            # קלט משתמש
            if prompt := st.chat_input("שאל אותי על השיבוץ (למשל: למה קורס X לא שובץ? מתי מלמד יוסי?)"):
                # הצגת הודעת משתמש
                st.session_state.chat_history.append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)

                # שליחה למודל
                if st.session_state.gemini_chat:
                    try:
                        response = st.session_state.gemini_chat.send_message(prompt)
                        reply = response.text
                        
                        st.session_state.chat_history.append({"role": "assistant", "content": reply})
                        with st.chat_message("assistant"):
                            st.markdown(reply)
                    except Exception as e:
                        st.error(f"שגיאה בקבלת תשובה: {e}")

    except Exception:
        st.error("שגיאה כללית במערכת:")
        st.code(traceback.format_exc())

if __name__ == "__main__":
    pass
