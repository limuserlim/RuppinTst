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
                # פירוק טווח שעות
                if '-' in part:
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
    
    try:
        # בדיקה אם זהו אובייקט Streamlit UploadedFile
        filename = getattr(uploaded_file, 'name', 'unknown.xlsx')
        
        if filename.endswith('.csv'):
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
    
    # וידוא שמות עמודות נקיים
    df.columns = df.columns.str.strip()
    
    # סינון שורות ללא שם קורס או מרצה
    if 'שם קורס' in df.columns and 'שם מרצה' in df.columns:
        df = df[df['שם קורס'].notna() & df['שם מרצה'].notna()]
    
    # נרמול שמות בתוכן
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
    
    # המרות טיפוסים (רק אם העמודות קיימות)
    if 'Duration' in df.columns:
        df['Duration'] = pd.to_numeric(df['Duration'], errors='coerce').fillna(0).astype(int)
    if 'Semester' in df.columns:
        df['Semester'] = pd.to_numeric(df['Semester'], errors='coerce').fillna(0).astype(int)
    if 'FixDay' in df.columns:
        df['FixDay'] = pd.to_numeric(df['FixDay'], errors='coerce').astype('Int64') 
    if 'FixHour' in df.columns:
        df['FixHour'] = pd.to_numeric(df['FixHour'], errors='coerce').astype('Int64')
    
    # יצירת מפתח ייחודי לבדיקת כפילויות
    if 'Year' in df.columns and 'Semester' in df.columns and 'Course' in df.columns:
        df['UniqueKey'] = df['Year'].astype(str) + "_" + df['Semester'].astype(str) + "_" + df['Course']
    
    return df

def preprocess_availability(df):
    """עיבוד טבלת זמינות למבנה נח"""
    df = df.dropna(how='all')
    df.columns = df.columns.str.strip()
    
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
                try:
                    day = int(str(col)[0])
                    semester = int(str(col)[1])
                    
                    slots = parse_availability_string(row[col])
                    if not slots: continue 
                    
                    if semester not in availability_db[lecturer]:
                        availability_db[lecturer][semester] = {}
                    
                    availability_db[lecturer][semester][day] = slots
                    total_slots += len(slots)
                except ValueError:
                    continue
        
        lecturer_sparsity[lecturer] = total_slots

    return availability_db, lecturer_sparsity, df

# ================= 3. CORE LOGIC & SCHEDULING =================

def check_strict_intersection(courses_df, avail_db):
    valid_lecturers = set(avail_db.keys())
    missing_mask = ~courses_df['Lecturer'].isin(valid_lecturers)
    missing_courses = courses_df[missing_mask]
    
    if not missing_courses.empty:
        st.warning(f"הוסרו {len(missing_courses)} קורסים כי למרצים שלהם אין קובץ זמינות.")
        # אופציונלי: להציג את השמות
        # st.write(missing_courses['Lecturer'].unique())
        
    return courses_df[~missing_mask].copy()

def check_unique_integrity(courses_df):
    if 'UniqueKey' not in courses_df.columns:
        return True
        
    dupes = courses_df[courses_df.duplicated(subset='UniqueKey', keep=False)]
    if not dupes.empty:
        st.error("CRITICAL ERROR: נמצאו קורסים כפולים (אותו שם, שנה וסמסטר):")
        st.dataframe(dupes[['Course', 'Year', 'Semester']])
        return False
    return True

def get_schedule_waves(df, sparsity_scores):
    # וידוא שהעמודות קיימות לפני המיון
    required_cols = ['LinkID', 'FixDay', 'FixHour', 'Lecturer', 'Duration']
    for c in required_cols:
        if c not in df.columns:
            df[c] = None # מילוי בריק אם חסר למניעת קריסה

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
                'UniqueKey': course_row['UniqueKey']
            })
            self.mark_student_busy(course_row['Year'], course_row['Semester'], day, h)

    def run(self):
        waves = get_schedule_waves(self.courses, self.avail_db)
        processed_link_ids = set()
        
        progress_bar = st.progress(0)
        total_waves = len(waves)

        for wave_idx, wave_df in enumerate(waves):
            progress_bar.progress((wave_idx + 1) / total_waves)
            
            for _, row in wave_df.iterrows():
                link_id = row['LinkID']
                if pd.notna(link_id) and link_id in processed_link_ids:
                    continue
                
                group_rows = None
                if pd.notna(link_id):
                    group_rows = self.courses[self.courses['LinkID'] == link_id].to_dict('records')
                    processed_link_ids.add(link_id)
                
                day, start_h = self.find_slot(row, linked_courses=group_rows)
                
                if day is not None:
                    if group_rows:
                        for g_row in group_rows:
                            self.commit_schedule(g_row, day, start_h)
                    else:
                        self.commit_schedule(row, day, start_h)
                else:
                    reason = "No Slot (Constraints/Overlap)"
                    if pd.notna(row['FixDay']): reason += " [Fixed Day]"
                    
                    items_to_fail = []
                    if group_rows:
                        items_to_fail = group_rows
                    else:
                        items_to_fail = [row]
                    
                    for item in items_to_fail:
                        # המרה בטוחה למילון אם צריך
                        if isinstance(item, pd.Series):
                            item = item.to_dict()
                            
                        self.unscheduled.append({
                            'Course': item.get('Course'),
                            'Lecturer': item.get('Lecturer'),
                            'Reason': reason,
                            'LinkID': item.get('LinkID')
                        })
        
        progress_bar.empty()
        return pd.DataFrame(self.schedule), pd.DataFrame(self.unscheduled)

# ================= 4. MAIN PROCESS WRAPPER =================

def main_process(courses_file, avail_file, iterations=20):
    """
    פונקציית הכניסה הראשית.
    נקראת מקובץ menu.py.
    """
    
    if not courses_file or not avail_file:
        st.info("אנא העלה את קבצי הקורסים והזמינות בתפריט למעלה ולחץ על התחל.")
        return

    st.write("---")
    st.info(f"מתחיל בעיבוד נתונים... (איטרציות אופטימיזציה: {iterations})")
    
    # Load Data
    courses_raw = load_uploaded_file(courses_file)
    avail_raw = load_uploaded_file(avail_file)
    
    if courses_raw is not None and avail_raw is not None:
        
        # Clean Data
        avail_db, sparsity, avail_cleaned_df = preprocess_availability(avail_raw)
        
        if avail_db is None: # שגיאה בטעינת המרצים
            return
            
        courses_processed = preprocess_courses(courses_raw)
        
        # Sanity Check
        st.subheader("🛠️ בדיקת שפיות (Sanity Check)")
        try:
            sample = avail_raw.sample(n=min(3, len(avail_raw)))
            for _, row in sample.iterrows():
                lect = row.get('Lecturer', row.get('שם מרצה', 'Unknown'))
                st.text(f"נקלט מרצה: {lect}")
        except:
            pass

        # Validation
        if check_unique_integrity(courses_processed):
            courses_ready = check_strict_intersection(courses_processed, avail_db)
            
            # Run Scheduler
            st.success("✅ הנתונים תקינים. מריץ אלגוריתם שיבוץ...")
            scheduler = SchoolScheduler(courses_ready, avail_db)
            final_schedule, unscheduled_report = scheduler.run()
            
            # ================== DISPLAY RESULTS ==================
            
            # 1. Metrics
            st.markdown("### 📊 סיכום שיבוץ")
            col_m1, col_m2, col_m3 = st.columns(3)
            
            num_scheduled = len(final_schedule)
            num_failed = len(unscheduled_report)
            total_items = num_scheduled + num_failed
            success_rate = (num_scheduled / total_items * 100) if total_items > 0 else 0
            
            col_m1.metric("שיעורים ששובצו", num_scheduled)
            col_m2.metric("שיעורים שנכשלו", num_failed, delta_color="inverse")
            col_m3.metric("אחוז הצלחה", f"{success_rate:.1f}%")

            # 2. Main Schedule Display
            st.markdown("### 🗓️ מערכת שעות סופית")
            st.dataframe(final_schedule, use_container_width=True)

            # 3. Download Buttons
            col_d1, col_d2 = st.columns(2)
            
            with col_d1:
                if not final_schedule.empty:
                    csv_sched = final_schedule.to_csv(index=False).encode('utf-8-sig')
                    st.download_button(
                        label="📥 הורד קובץ מערכת סופי (CSV)",
                        data=csv_sched,
                        file_name="Final_Schedule.csv",
                        mime="text/csv",
                        key='dl_sched'
                    )
            
            with col_d2:
                if not unscheduled_report.empty:
                    csv_err = unscheduled_report.to_csv(index=False).encode('utf-8-sig')
                    st.download_button(
                        label="⚠️ הורד דוח שגיאות (CSV)",
                        data=csv_err,
                        file_name="Unscheduled_Report.csv",
                        mime="text/csv",
                        key='dl_err'
                    )
            
            # 4. Error Display
            if not unscheduled_report.empty:
                st.markdown("---")
                st.error("⚠️ פירוט שגיאות (קורסים שלא שובצו)")
                st.dataframe(unscheduled_report, use_container_width=True)

if __name__ == "__main__":
    st.warning("הפעל את המערכת דרך menu.py")
