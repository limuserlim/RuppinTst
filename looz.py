import streamlit as st
import pandas as pd
import numpy as np
import io
import traceback

# --- בדיקת ספריית ג'מיני ---
try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

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
    s = str(val).strip().replace("'", "").replace('"', "")
    if s in ['א', 'A', 'a', '1']: return 1
    if s in ['ב', 'B', 'b', '2']: return 2
    if s in ['ג', 'C', 'c', '3']: return 3
    try: return int(float(s))
    except: return 1

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

# ================= 2. PRE-PROCESSING =================

def preprocess_courses(df):
    df = df.dropna(how='all')
    df.columns = df.columns.str.strip()
    col_map = {}
    for col in df.columns:
        c = str(col).strip()
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
    if 'Course' not in df.columns or 'Lecturer' not in df.columns: return pd.DataFrame()
    df = df[df['Course'].notna() & df['Lecturer'].notna()]
    for col in ['Course', 'Lecturer', 'Space', 'LinkID', 'Year']:
        if col not in df.columns: df[col] = None
        df[col] = df[col].apply(safe_str)
    if 'Semester' in df.columns: df['Semester'] = df['Semester'].apply(clean_semester)
    else: df['Semester'] = 1
    if 'Duration' in df.columns: df['Duration'] = pd.to_numeric(df['Duration'], errors='coerce').fillna(2).astype(int)
    else: df['Duration'] = 2
    for col in ['FixDay', 'FixHour']:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
        else: df[col] = None
    return df

def preprocess_availability(df):
    df = df.dropna(how='all')
    df.columns = df.columns.str.strip()
    lecturer_col = None
    for col in df.columns:
        if str(col).strip() == "שם מלא": lecturer_col = col; break
    if not lecturer_col:
        for col in df.columns:
            if "שם" in str(col) or "מרצה" in str(col): lecturer_col = col; break
    if not lecturer_col: st.error("לא נמצאה עמודת 'שם מלא' בקובץ הזמינות."); return None, None
    df = df.rename(columns={lecturer_col: 'Lecturer'})
    df['Lecturer'] = df['Lecturer'].apply(safe_str)
    df = df[df['Lecturer'].notna()]
    avail_db = {}
    sparsity = {}
    avail_cols = [c for c in df.columns if str(c).isdigit()]
    for _, row in df.iterrows():
        lec = row['Lecturer']
        if not lec: continue
        lec = " ".join(lec.split())
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
        self.courses['Lecturer'] = self.courses['Lecturer'].apply(lambda x: " ".join(str(x).split()))
        df = self.courses.copy()
        df['Sparsity'] = df['Lecturer'].map(self.sparsity).fillna(0).astype(int)
        wave_hard = df[df['LinkID'].notna() | df['FixDay'].notna() | df['FixHour'].notna()]
        wave_soft = df[~df.index.isin(wave_hard.index)]
        if shuffle: wave_soft = wave_soft.sample(frac=1).reset_index(drop=True)
        else: wave_soft = wave_soft.sort_values(by=['Sparsity', 'Duration'], ascending=[True, False])
        waves = [wave_hard, wave_soft]
        self.schedule = []
        self.errors = []
        self.busy = {}
        self.processed_links = set()
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
        except: self.fail(group, "נתונים שגויים"); return
        days = [int(main_row['FixDay'])] if pd.notna(main_row['FixDay']) else [1,2,3,4,5]
        hours = list(range(8, 22))
        if str(main_row.get('Space')).lower() == 'zoom': hours.reverse()
        if pd.notna(main_row['FixHour']): hours = [int(main_row['FixHour'])]
        for day in days:
            for start_h in hours:
                if start_h + dur > 22: continue
                if self.check_valid(group, sem, day, start_h, dur):
                    self.commit(group, sem, day, start_h, dur); return
        reason = "לא נמצא חלון זמן"
        if pd.notna(main_row['FixDay']): reason += " [אילוץ יום]"
        self.fail(group, reason)

    def check_valid(self, group, sem, day, start_h, dur):
        for item in group:
            lec = item['Lecturer']
            year = item.get('Year')
            for h in range(start_h, start_h + dur):
                if lec not in self.avail_db: return False
                if sem not in self.avail_db[lec]: return False
                if day not in self.avail_db[lec][sem]: return False
                if h not in self.avail_db[lec][sem][day]: return False
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

# ================= 4. CHAT FUNCTIONS =================

def init_chat_session(schedule_df, errors_df, api_key):
    """מאתחל שיחה עם ג'מיני ובוחר מודל זמין אוטומטית"""
    if not HAS_GENAI or not api_key: return None
    
    genai.configure(api_key=api_key)
    generation_config = genai.types.GenerationConfig(temperature=0.0)
    
    # === תיקון: בחירת מודל דינמית ===
    # אנחנו נותנים למערכת רשימת מודלים מועדפים ונבדוק מי זמין עבורך
    model_name = None
    preferred_models = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-pro", "gemini-1.0-pro"]
    
    try:
        # בקשה מגוגל: תן לי את רשימת המודלים הזמינים למפתח הזה
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # חיפוש ההתאמה הטובה ביותר
        for preferred in preferred_models:
            # בודקים אם המודל המועדף קיים ברשימה (עם או בלי הקידומת models/)
            for available in available_models:
                if preferred in available:
                    model_name = available
                    break
            if model_name: break
            
        # אם לא מצאנו כלום מהמועדפים, ניקח את הראשון שזמין
        if not model_name and available_models:
            model_name = available_models[0]
            
    except Exception as e:
        # במקרה של כישלון בחיפוש, ננסה ברירת מחדל ישנה
        print(f"Error listing models: {e}")
        model_name = "models/gemini-pro"

    if not model_name:
        st.error("❌ לא נמצאו מודלים זמינים של Gemini בחשבון זה.")
        return None

    # הכנת הנתונים לפרומפט
    csv_sched = schedule_df.to_csv(index=False)
    csv_errors = errors_df.to_csv(index=False)
    
    prompt = f"""
    You are a data analyst for a university scheduling system.
    Data:
    SUCCESSFUL SCHEDULE:
    {csv_sched}
    FAILED COURSES:
    {csv_errors}
    Answer ONLY based on this data. Use Hebrew.
    """
    
    try:
        model = genai.GenerativeModel(model_name, generation_config=generation_config)
        return model.start_chat(history=[{"role": "user", "parts": prompt}, {"role": "model", "parts": "אני כאן."}])
    except Exception as e:
        st.error(f"שגיאה בהפעלת המודל ({model_name}): {e}")
        return None
# ================= 5. MAIN =================

def main_process(courses_file, avail_file, iterations=30):
    if not courses_file or not avail_file: return
    
    # --- קבלת API KEY מה-Secrets או מהמשתמש ---
    api_key = None
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
    
    # אזור צדדי - להציג סטטוס או לבקש מפתח אם חסר
    with st.sidebar:
        st.header("🤖 הגדרות צ'אט")
        
        if not HAS_GENAI:
            st.error("⚠️ ספריית Gemini חסרה (google-generativeai).")
        elif api_key:
            st.success("✅ מפתח API נטען מה-Secrets")
        else:
            api_key = st.text_input("Google API Key", type="password", help="נדרש רק אם לא מוגדר ב-Secrets")

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
            st.error("קובץ הקורסים לא תקין.")
            return

        courses['Lecturer'] = courses['Lecturer'].apply(lambda x: " ".join(str(x).split()))
        valid_lecs = set(avail_db.keys())
        mask = courses['Lecturer'].isin(valid_lecs)
        
        if not mask.all():
            missing = courses[~mask]['Lecturer'].unique()
            st.warning(f"⚠️ {len(missing)} מרצים חסרים בקובץ הזמינות (דוגמה: {missing[:3]})")
            
        final_courses = courses[mask].copy()
        if final_courses.empty:
            st.error("אין קורסים לשיבוץ (0 התאמות). בדוק שהשמות זהים בשני הקבצים.")
            return

        st.success(f"✅ מתחיל שיבוץ ({iterations} איטרציות)...")
        best_sched = pd.DataFrame(); best_errors = pd.DataFrame(); min_errors = float('inf')
        bar = st.progress(0)
        
        for i in range(iterations + 1):
            bar.progress(i/(iterations+1))
            sched = Scheduler(final_courses, avail_db, sparsity)
            s, e = sched.run(shuffle=(i > 0))
            
            if len(e) < min_errors:
                min_errors = len(e); best_sched = s; best_errors = e
                if min_errors == 0: break
        
        bar.empty()
        
        st.divider()
        c1, c2 = st.columns(2)
        unique_sched = len(best_sched.drop_duplicates(subset=['Course', 'Lecturer'])) if not best_sched.empty else 0
        c1.metric("✅ קורסים שובצו", unique_sched)
        c2.metric("❌ לא שובצו", len(best_errors), delta_color="inverse")
        
        if not best_sched.empty:
            st.dataframe(best_sched)
            st.download_button("📥 הורד מערכת", best_sched.to_csv(index=False).encode('utf-8-sig'), "schedule.csv")
            
        if not best_errors.empty:
            st.error("פירוט שגיאות:")
            st.dataframe(best_errors)
            st.download_button("⚠️ הורד שגיאות", best_errors.to_csv(index=False).encode('utf-8-sig'), "errors.csv")

        # --- CHAT SECTION ---
        st.divider()
        st.subheader("💬 ניתוח תוצאות (AI Analyst)")

        if not HAS_GENAI:
            st.error("❌ ספריית הצ'אט לא מותקנת בשרת.")
        elif not api_key:
            st.info("👈 כדי להפעיל את הצ'אט, יש להגדיר GOOGLE_API_KEY ב-Secrets או להזין אותו בצד.")
        else:
            if "gemini_chat" not in st.session_state:
                st.session_state.gemini_chat = init_chat_session(best_sched, best_errors, api_key)
                st.session_state.chat_history = []
            
            # אם מפתח השתנה
            if "last_key" not in st.session_state or st.session_state.last_key != api_key:
                st.session_state.last_key = api_key
                st.session_state.gemini_chat = init_chat_session(best_sched, best_errors, api_key)
                st.session_state.chat_history = []

            for msg in st.session_state.chat_history:
                st.chat_message(msg["role"]).write(msg["content"])

            if prompt := st.chat_input("שאל אותי על השיבוץ (למשל: למה קורס X לא שובץ?)"):
                st.session_state.chat_history.append({"role": "user", "content": prompt})
                st.chat_message("user").write(prompt)
                
                if st.session_state.gemini_chat:
                    try:
                        resp = st.session_state.gemini_chat.send_message(prompt)
                        st.session_state.chat_history.append({"role": "assistant", "content": resp.text})
                        st.chat_message("assistant").write(resp.text)
                    except Exception as ex:
                        st.error(f"שגיאה בצ'אט: {ex}")

    except Exception:
        st.error("שגיאה כללית במערכת:")
        st.code(traceback.format_exc())

if __name__ == "__main__":
    pass


