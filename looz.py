import streamlit as st
import pandas as pd
import io

def clean_text(text):
    if pd.isna(text): return ""
    return str(text).strip()

def analyze_availability_parsing(df, time_cols):
    """בדיקה האם המערכת מצליחה לקרוא את השעות"""
    total_slots = 0
    sample_log = []
    
    # בדיקה על 5 שורות ראשונות שיש בהן תוכן
    for i, row in df.head(10).iterrows():
        lec = row.get('Lecturer', 'Unknown')
        row_slots = 0
        for col in time_cols:
            val = row[col]
            if pd.isna(val) or str(val).strip() == "": continue
            
            # לוגיקה פשוטה לבדיקה
            try:
                parts = str(val).replace(';', ',').split(',')
                for p in parts:
                    if '-' in p:
                        total_slots += 1
                        row_slots += 1
            except:
                pass
        
        if row_slots > 0:
            sample_log.append(f"✅ מרצה '{lec}': זוהו {row_slots} חלונות זמן.")
    
    return total_slots, sample_log

def main_process(courses_file, avail_file, iterations=20):
    st.title("🕵️ כלי אבחון נתונים (Data Doctor)")
    st.info("כלי זה נועד לבדוק מדוע אין שיבוצים. הוא אינו מבצע שיבוץ בפועל.")

    if not courses_file or not avail_file:
        st.warning("אנא העלה את שני הקבצים.")
        return

    # 1. טעינה
    try:
        if courses_file.name.endswith('.csv'):
            c_df = pd.read_csv(courses_file, encoding='utf-8')
        else:
            c_df = pd.read_excel(courses_file)
            
        if avail_file.name.endswith('.csv'):
            a_df = pd.read_csv(avail_file, encoding='utf-8')
        else:
            a_df = pd.read_excel(avail_file)
            
    except UnicodeDecodeError:
        st.error("שגיאת קידוד (Encoding). נסה לשמור את ה-CSV כ-UTF-8 או להעלות אקסל.")
        return
    except Exception as e:
        st.error(f"שגיאה בטעינה: {e}")
        return

    st.divider()

    # 2. זיהוי עמודות - קורסים
    st.header("1. בדיקת קובץ קורסים")
    c_cols = [str(c).strip() for c in c_df.columns]
    st.write(f"עמודות שנקראו: {c_cols}")
    
    # חיפוש עמודות קריטיות
    c_lec_col = next((c for c in c_cols if 'מרצה' in c or 'lecturer' in c.lower()), None)
    c_course_col = next((c for c in c_cols if 'קורס' in c or 'course' in c.lower()), None)
    
    if c_lec_col and c_course_col:
        st.success(f"✅ זוהו עמודות: מרצה='{c_lec_col}', קורס='{c_course_col}'")
        c_df.rename(columns={c_lec_col: 'Lecturer', c_course_col: 'Course'}, inplace=True)
        # ניקוי שמות
        c_df['Lecturer'] = c_df['Lecturer'].apply(clean_text)
        sample_c_lecs = set(c_df['Lecturer'].unique())
        st.write(f"דוגמה לשמות מרצים בקורסים: {list(sample_c_lecs)[:5]}")
    else:
        st.error("❌ לא הצלחתי לזהות עמודת 'שם מרצה' או 'שם קורס'. בדוק את הכותרות בקובץ.")
        return

    st.divider()

    # 3. זיהוי עמודות - זמינות
    st.header("2. בדיקת קובץ זמינות")
    a_cols = [str(c).strip() for c in a_df.columns]
    
    a_lec_col = next((c for c in a_cols if 'מרצה' in c or 'name' in c.lower() or 'lecturer' in c.lower()), None)
    
    if a_lec_col:
        st.success(f"✅ זוהתה עמודת מרצה: '{a_lec_col}'")
        a_df.rename(columns={a_lec_col: 'Lecturer'}, inplace=True)
        a_df['Lecturer'] = a_df['Lecturer'].apply(clean_text)
        sample_a_lecs = set(a_df['Lecturer'].unique())
        st.write(f"דוגמה לשמות מרצים בזמינות: {list(sample_a_lecs)[:5]}")
    else:
        st.error("❌ לא נמצאה עמודת שם מרצה בקובץ הזמינות.")
        return

    # 4. בדיקת חיתוך (Intersection)
    st.header("3. האם השמות תואמים?")
    common = sample_c_lecs.intersection(sample_a_lecs)
    st.metric("מספר מרצים זהים בשני הקבצים", len(common))
    
    if len(common) == 0:
        st.error("😱 אף שם לא תואם! המחשב חושב שאלו אנשים שונים.")
        st.write("אנא בדוק רווחים מיותרים. הנה השוואה:")
        col1, col2 = st.columns(2)
        col1.write("מקובץ הקורסים:", list(sample_c_lecs)[:5])
        col2.write("מקובץ הזמינות:", list(sample_a_lecs)[:5])
        return
    else:
        st.success(f"יש התאמה עבור {len(common)} מרצים. מצוין.")

    # 5. בדיקת פענוח שעות (Parsing Logic)
    st.header("4. האם המערכת מבינה את השעות?")
    time_cols = [c for c in a_df.columns if len(str(c))>=2 and str(c)[:2].isdigit()]
    st.write(f"עמודות שנחשדות כזמן (יום+סמסטר): {time_cols}")
    
    if not time_cols:
        st.error("❌ לא נמצאו עמודות זמן (כגון 11, 12). בדוק את שמות העמודות.")
    else:
        total_slots, log = analyze_availability_parsing(a_df, time_cols)
        if total_slots == 0:
            st.error("❌ המערכת לא הצליחה לחלץ אף שעה פנויה!")
            st.warning("הפורמט הצפוי בתאים הוא: '08-10' או '8:00-10:00'.")
            st.write("דוגמה לתוכן גולמי מהקובץ (מה שהמחשב רואה):")
            # הצגת תוכן גולמי של שורה ראשונה
            st.dataframe(a_df[time_cols].head(3))
        else:
            st.success(f"✅ פענוח תקין! זוהו {total_slots} משבצות זמן.")
            with st.expander("ראה פירוט פענוח"):
                for l in log:
                    st.write(l)

if __name__ == "__main__":
    pass
