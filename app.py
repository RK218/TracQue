
# --- Registration Route ---
from flask import Flask, render_template, request, redirect, url_for, session, flash
import json
# --- User Authentication ---

# --- Login Route -5
import pandas as pd
import numpy as np
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from sklearn.linear_model import LinearRegression
from sklearn.tree import DecisionTreeRegressor
import os
import glob
import datetime
import cv2
import logging
import base64
import json
from werkzeug.utils import secure_filename
import serial
import serial.tools.list_ports
import threading
import queue
import time
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

app = Flask(__name__)
app.secret_key = 'your_super_secret_key_here'
logging.basicConfig(level=logging.INFO)

# --- File & Folder Paths ---
DATA_FILE = 'students_data.csv'
ATTENDANCE_FOLDER = 'attendance'
FACES_FOLDER = 'faces'
MODELS_FOLDER = 'models'
ID_MAP_FILE = os.path.join(MODELS_FOLDER, 'id_map.json')
MODEL_FILE = os.path.join(MODELS_FOLDER, "trainer.yml")
FINGERPRINT_MAP_FILE = os.path.join(MODELS_FOLDER, 'fingerprint_map.json')

# --- Global Models ---
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
recognizer = cv2.face.LBPHFaceRecognizer_create()

# --- Fingerprint Serial Connection ---
fingerprint_serial = None
fingerprint_queue = queue.Queue()
fingerprint_connected = False
fingerprint_enrollment_status = []  # Store real-time enrollment messages
fingerprint_enrollment_active = False  # Flag to prevent attendance during enrollment
fingerprint_sensor_activated = False  # Flag to track if sensor is activated for attendance

# --- Daily Attendance CSV Generation ---
def generate_daily_attendance_csv():
    """Generate a daily CSV file with all enrolled students and their attendance status."""
    try:
        df = get_df()
        if df.empty:
            app.logger.info("No students enrolled. Skipping daily CSV generation.")
            return
        
        # Create daily attendance folder if it doesn't exist
        daily_folder = 'daily_attendance'
        if not os.path.exists(daily_folder):
            os.makedirs(daily_folder)
        
        # Generate CSV with today's date
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        daily_csv_file = os.path.join(daily_folder, f"attendance_{today_str}.csv")
        
        # Check if today's CSV already exists (don't overwrite)
        if os.path.exists(daily_csv_file):
            app.logger.info(f"Daily CSV already exists for {today_str}. Skipping.")
            return
        
        # Get all students and check if they were present today
        attendance_file_today = os.path.join(ATTENDANCE_FOLDER, f"attendance_{today_str}.csv")
        present_students = set()
        
        if os.path.exists(attendance_file_today):
            try:
                daily_attendance_df = pd.read_csv(attendance_file_today, dtype={'Student ID': str})
                present_students = set(daily_attendance_df['Student ID'].str.strip().unique())
            except Exception as e:
                app.logger.error(f"Error reading daily attendance: {e}")
        
        # Create daily CSV with all students
        daily_data = []
        for idx, row in df.iterrows():
            student_id = str(row['student_id']).strip()
            status = 'Present' if student_id in present_students else 'Absent'
            daily_data.append({
                'Student ID': student_id,
                'Name': row['name'],
                'Status': status,
                'Date': today_str,
                'Time': datetime.datetime.now().strftime("%H:%M:%S")
            })
        
        daily_df = pd.DataFrame(daily_data)
        daily_df.to_csv(daily_csv_file, index=False)
        app.logger.info(f"Daily attendance CSV generated: {daily_csv_file}")
    
    except Exception as e:
        app.logger.error(f"Error generating daily attendance CSV: {e}")

# Initialize scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(
    func=generate_daily_attendance_csv,
    trigger=CronTrigger(hour=23, minute=59),  # Run at 11:59 PM daily
    id='daily_attendance_job',
    name='Generate daily attendance CSV',
    replace_existing=True
)

# --- Helper Functions ---
def load_users():
    with open('users.json', 'r') as f:
        return json.load(f)
    
def normalize_phone(phone):
    phone = str(phone).strip()
    if phone.lower() == 'nan' or phone == '':
        return ''
    if phone.endswith('.0'):
        phone = phone[:-2]
    if '.' in phone:
        phone = phone.split('.')[0]
    phone = ''.join(filter(str.isdigit, phone))
    return phone

def normalize_days_present(days):
    try:
        return str(int(float(days)))
    except (ValueError, TypeError):
        return '0'

def authenticate(username, password):
    users = load_users()
    for user in users:
        if user['username'] == username and user['password'] == password:
            return user
    return None
def get_df():
    """Loads student data, critically ensuring 'student_id' is treated as a string."""
    try:
        if os.path.exists(DATA_FILE) and os.path.getsize(DATA_FILE) > 0:
            # This dtype={'student_id': str} is essential for alphanumeric IDs.
            df = pd.read_csv(DATA_FILE, dtype={'student_id': str})
            df['student_id'] = df['student_id'].str.strip()
            # Fix blank total_days for any student
            if 'total_days' in df.columns:
                df['total_days'] = df['total_days'].apply(lambda x: 0 if pd.isna(x) or x == '' else int(float(x)))
            return df
    except Exception as e:
        app.logger.error(f"Error loading CSV: {e}")
    return pd.DataFrame(columns=['student_id', 'name', 'attendance_percentage', 'test_score_1', 'test_score_2', 'assignment_score', 'final_exam_score', 'performance_category'])

def save_df(df):
    """Saves the DataFrame to the CSV file."""
    # Ensure required columns exist and are filled
    if 'days_present' not in df.columns:
        df['days_present'] = 0
    if 'total_days' not in df.columns:
        df['total_days'] = 0
    df['days_present'] = df['days_present'].fillna(0).astype(int)
    df['total_days'] = df['total_days'].fillna(0).astype(int)
    if not df.empty:
        df['attendance_percentage'] = df.apply(
            lambda row: round((int(row['days_present']) / int(row['total_days'])) * 100, 2) if int(row['total_days']) > 0 else 0.0, axis=1
        )
    else:
        df['attendance_percentage'] = []
    df.to_csv(DATA_FILE, index=False)

def _update_attendance_percentages(df):
    if df.empty or not os.path.exists(ATTENDANCE_FOLDER):
        if 'attendance_percentage' not in df.columns:
            df['attendance_percentage'] = 0.0
        return df
        
    attendance_files = glob.glob(os.path.join(ATTENDANCE_FOLDER, 'attendance_*.csv'))
    total_days = len(attendance_files)
    
    df['student_id'] = df['student_id'].astype(str)
    presence_counts = {student_id: 0 for student_id in df['student_id']}

    for file_path in attendance_files:
        try:
            daily_df = pd.read_csv(file_path, dtype={'Student ID': str})
            for student_id in daily_df['Student ID'].str.strip().dropna().unique():
                if student_id in presence_counts:
                    presence_counts[student_id] += 1
        except Exception: continue

    if total_days > 0:
        df['attendance_percentage'] = df['student_id'].apply(
            lambda sid: round((presence_counts.get(sid, 0) / total_days) * 100, 2)
        )
    else:
        df['attendance_percentage'] = 0.0
    return df

def _get_total_attendance_days():
    """Calculates the total number of unique days attendance has been recorded."""
    if not os.path.exists(ATTENDANCE_FOLDER):
        return 0
    # Glob returns a list of all files matching the pattern
    attendance_files = glob.glob(os.path.join(ATTENDANCE_FOLDER, 'attendance_*.csv'))
    # The number of files corresponds to the total number of days recorded
    return len(attendance_files) 

def mark_attendance(student_id, name):
    student_id_str = str(student_id).strip()
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    now_str = datetime.datetime.now().strftime("%H:%M:%S")
    attendance_file_path = os.path.join(ATTENDANCE_FOLDER, f"attendance_{today_str}.csv")
    already_marked = False
    if os.path.exists(attendance_file_path):
        try:
            daily_df = pd.read_csv(attendance_file_path, dtype={'Student ID': str})
            if student_id_str in daily_df['Student ID'].str.strip().values:
                already_marked = True
        except (pd.errors.EmptyDataError, KeyError): pass
    df = get_df()
    student_index = df.index[df['student_id'] == student_id_str].tolist()

    # --- NEW LOGIC: total_days always equals number of attendance files ---
    attendance_files = glob.glob(os.path.join(ATTENDANCE_FOLDER, 'attendance_*.csv'))
    total_days_count = len(attendance_files)
    # If no attendance files, reset total_days to 0
    if total_days_count == 0:
        df['total_days'] = 0
    else:
        df['total_days'] = total_days_count

    if not already_marked:
        new_entry = pd.DataFrame([{'Student ID': student_id_str, 'Name': name, 'Time': now_str}])
        new_entry.to_csv(attendance_file_path, mode='a', header=not os.path.exists(attendance_file_path), index=False)
        if student_index:
            idx = student_index[0]
            df.loc[idx, 'days_present'] = int(float(df.loc[idx, 'days_present'])) if not pd.isna(df.loc[idx, 'days_present']) else 0
            df.loc[idx, 'days_present'] += 1
            df['attendance_percentage'] = df.apply(
                lambda row: round((row['days_present'] / row['total_days']) * 100, 2) if row['total_days'] > 0 else 0.0, axis=1
            )
            save_df(df)
            return {'status': 'marked', 'percentage': df.loc[idx, 'attendance_percentage']}
        else:
            return {'status': 'not_found', 'percentage': 0.0}
    elif already_marked:
        if student_index:
            idx = student_index[0]
            return {'status': 'already_present', 'percentage': df.loc[idx, 'attendance_percentage']}
        else:
            return {'status': 'already_present', 'percentage': 0.0}

# --- Fingerprint Helper Functions ---
def find_esp32_port():
    """Auto-detect ESP32 port"""
    ports = serial.tools.list_ports.comports()
    for port in ports:
        if ('303A' in port.hwid or 'CP210' in port.hwid or 'CH340' in port.hwid or 'USB Serial' in port.description):
            return port.device
    return None

def init_fingerprint_connection():
    """Initialize connection to ESP32 fingerprint reader"""
    global fingerprint_serial, fingerprint_connected
    try:
        port = find_esp32_port()
        if port:
            fingerprint_serial = serial.Serial(port, 115200, timeout=1)
            time.sleep(2)
            fingerprint_connected = True
            app.logger.info(f"Fingerprint reader connected on {port}")
            # Start listener thread
            threading.Thread(target=fingerprint_listener, daemon=True).start()
            return True
    except Exception as e:
        app.logger.error(f"Error connecting to fingerprint reader: {e}")
        fingerprint_connected = False
    return False

def fingerprint_listener():
    """Background thread to listen for fingerprint scans"""
    global fingerprint_serial, fingerprint_queue, fingerprint_enrollment_status, fingerprint_enrollment_active
    print("🎧 Fingerprint listener started")
    
    while fingerprint_connected and fingerprint_serial:
        try:
            if fingerprint_serial.in_waiting:
                line = fingerprint_serial.readline().decode('utf-8').strip()
                if line:
                    # Print to terminal for debugging
                    print(f"[ESP32 ← ] {line}")
                    try:
                        data = json.loads(line)
                        msg_type = data.get('type')
                        
                        # Handle attendance matches - but only if NOT in enrollment mode
                        if msg_type == 'match':
                            if fingerprint_enrollment_active:
                                print(f"🔍 MATCH DETECTED during enrollment - IGNORING (enrollment active)")
                                continue  # Skip processing match messages during enrollment
                            print(f"🔍 MATCH DETECTED! Adding to queue...")
                            fingerprint_queue.put(data)
                            print(f"✅ Match added to queue (size: {fingerprint_queue.qsize()})")
                        
                        # Handle enrollment messages (status, prompt, info, error, enrolled)
                        elif msg_type in ['status', 'prompt', 'info', 'error', 'enrolled']:
                            msg_text = data.get('message', '')
                            fingerprint_enrollment_status.append({
                                'type': msg_type,
                                'message': msg_text
                            })
                            # Also print to terminal with emoji
                            if msg_type == 'prompt':
                                print(f"         └─ 👆 {msg_text}")
                            elif msg_type == 'status':
                                print(f"         └─ ℹ️  {msg_text}")
                            elif msg_type == 'info':
                                print(f"         └─ 💡 {msg_text}")
                            elif msg_type == 'error':
                                print(f"         └─ ❌ {msg_text}")
                            elif msg_type == 'enrolled':
                                print(f"         └─ ✅ {msg_text}")
                                
                    except json.JSONDecodeError:
                        app.logger.warning(f"Invalid JSON from ESP32: {line}")
        except Exception as e:
            app.logger.error(f"Fingerprint listener error: {e}")
            print(f"❌ Listener error: {e}")
        time.sleep(0.1)  # Small delay to prevent CPU hogging

def send_fingerprint_command(command):
    """Send command to ESP32"""
    global fingerprint_serial
    if fingerprint_serial and fingerprint_connected:
        try:
            # Print to terminal for debugging
            print(f"[ESP32 →] {command}")
            fingerprint_serial.write(f"{command}\n".encode())
            app.logger.info(f"Sent command to ESP32: {command}")
            return True
        except Exception as e:
            app.logger.error(f"Error sending command: {e}")
    return False

def read_fingerprint_response(timeout=30):
    """Read response from ESP32"""
    global fingerprint_serial
    if not fingerprint_serial or not fingerprint_connected:
        return None
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            if fingerprint_serial.in_waiting:
                line = fingerprint_serial.readline().decode('utf-8').strip()
                if line:
                    # Print to terminal for debugging
                    print(f"[ESP32 ← ] {line}")
                    try:
                        data = json.loads(line)
                        # Log the parsed data type
                        msg_type = data.get('type', 'unknown')
                        msg_text = data.get('message', data.get('id', ''))
                        print(f"         └─ Type: {msg_type}, Content: {msg_text}")
                        return data
                    except json.JSONDecodeError:
                        app.logger.warning(f"Invalid JSON in response: {line}")
        except Exception as e:
            app.logger.error(f"Error reading response: {e}")
        time.sleep(0.1)
    return None

def get_fingerprint_slot_for_student(student_id):
    """Get the fingerprint slot number for a student"""
    if os.path.exists(FINGERPRINT_MAP_FILE):
        try:
            with open(FINGERPRINT_MAP_FILE, 'r') as f:
                fp_map = json.load(f)
                return fp_map.get(str(student_id))
        except:
            pass
    return None

def save_fingerprint_mapping(student_id, slot_number):
    """Save student_id to fingerprint slot mapping"""
    fp_map = {}
    if os.path.exists(FINGERPRINT_MAP_FILE):
        try:
            with open(FINGERPRINT_MAP_FILE, 'r') as f:
                fp_map = json.load(f)
        except:
            pass
    
    fp_map[str(student_id)] = slot_number
    
    with open(FINGERPRINT_MAP_FILE, 'w') as f:
        json.dump(fp_map, f, indent=2)

def get_next_available_fingerprint_slot():
    """Get the next available slot number for fingerprint enrollment"""
    if os.path.exists(FINGERPRINT_MAP_FILE):
        try:
            with open(FINGERPRINT_MAP_FILE, 'r') as f:
                fp_map = json.load(f)
                used_slots = list(fp_map.values())
                for i in range(1, 201):  # R307S supports up to 200 fingerprints
                    if i not in used_slots:
                        return i
        except:
            pass
    return 1  # First slot if no mappings exist

# --- Main Flask Routes ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        users = load_users()
        # Prevent duplicate usernames
        if any(u['username'] == username for u in users):
            flash('Username already exists.', 'danger')
            return render_template('register.html')
        users.append({'username': username, 'password': password, 'role': role})
        with open('users.json', 'w') as f:
            json.dump(users, f, indent=2)
        flash('Registration successful! You can now log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = authenticate(username, password)
        if user:
            session['username'] = user['username']
            session['role'] = user['role']
            flash('Login successful!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid credentials', 'danger')
    return render_template('login.html')

# --- Logout Route ---
@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))
@app.route('/')
def index():
    df = get_df()  # Always reload latest CSV
    df = _update_attendance_percentages(df)
    save_df(df)
    total_days = int(df['total_days'].max()) if not df.empty and 'total_days' in df.columns else 0
    if 'username' not in session:
        return redirect(url_for('login'))
    df = get_df()
    df = _update_attendance_percentages(df)
    save_df(df)
    total_days = int(df['total_days'].max()) if not df.empty and 'total_days' in df.columns else 0
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    attendance_file = os.path.join(ATTENDANCE_FOLDER, f"attendance_{today_str}.csv")
    present_ids = set()
    # Automatically create today's attendance file if not exists
    if not os.path.exists(attendance_file):
        pd.DataFrame(columns=['Student ID', 'Name', 'Time']).to_csv(attendance_file, index=False)
    # Update total_days for all students based on number of attendance files
    import glob
    attendance_files = glob.glob(os.path.join(ATTENDANCE_FOLDER, 'attendance_*.csv'))
    total_days_count = len(attendance_files)
    if not df.empty:
        df['total_days'] = total_days_count
        save_df(df)
    try:
        att_df = pd.read_csv(attendance_file, dtype={'Student ID': str})
        present_ids = set(att_df['Student ID'].str.strip())
    except Exception:
        pass
    all_ids = set(df['student_id'].astype(str).str.strip())
    absent_ids = all_ids - present_ids
    students_not_attended = len(absent_ids)
    role = session.get('role')
    username = session.get('username')
    if role == 'student':
        # Only show the logged-in student's ID if they are absent
        if username in absent_ids:
            absent_students = df[df['student_id'] == username][['student_id', 'name']].to_dict(orient='records')
        else:
            absent_students = []
    else:
        absent_students = df[df['student_id'].isin(absent_ids)][['student_id', 'name']].to_dict(orient='records')

    search_query = request.args.get('query', '')
    if 'parent_phone' in df.columns:
        df['parent_phone'] = df['parent_phone'].apply(normalize_phone)
    if role == 'teacher':
        if search_query:
            df_search = df[
                df['name'].str.contains(search_query, case=False, na=False) |
                df['student_id'].astype(str).str.contains(search_query, case=False, na=False)
            ]
        else:
            df_search = df
        students_display = df_search.copy()
        students_display['final_exam_score'] = students_display['final_exam_score'].apply(
            lambda x: f"{x:.2f}" if pd.notna(x) else 'N/A'
        )
        students_display['performance_category'] = students_display['performance_category'].fillna('N/A')
        return render_template('dashboard.html', 
            students=students_display.to_dict(orient='records'), 
            search_query=search_query,
            total_days=total_days,
            students_not_attended=students_not_attended,
            absent_students=absent_students,
            can_edit=True)
    else:
        # Students see only their own record, read-only
        student_row = [s for s in df.to_dict(orient='records') if s.get('student_id') == username]
        return render_template('dashboard.html', 
            students=student_row,
            search_query=search_query,
            total_days=total_days,
            students_not_attended=students_not_attended,
            absent_students=absent_students,
            can_edit=False)

# --- Data Management Routes ---
@app.route('/upload_data', methods=['POST'], endpoint='upload_data')
def upload_data():
    if 'file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('index'))
    file = request.files['file']
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('index'))
    try:
        existing_df = get_df()
        new_data_df = pd.read_csv(file, dtype={'student_id': str})
        
        if not existing_df.empty:
            existing_df['student_id'] = existing_df['student_id'].str.strip()
            new_data_df['student_id'] = new_data_df['student_id'].str.strip()
            existing_df.set_index('student_id', inplace=True)
            new_data_df.set_index('student_id', inplace=True)
            existing_df.update(new_data_df)
            new_students = new_data_df[~new_data_df.index.isin(existing_df.index)]
            combined_df = pd.concat([existing_df, new_students])
            combined_df.reset_index(inplace=True)
        else:
            combined_df = new_data_df

        save_df(combined_df)
        flash('File successfully uploaded and data merged.', 'success')
    except Exception as e:
        flash(f'An error occurred while processing the file: {e}', 'error')
    return redirect(url_for('index'))

@app.route('/add_student', methods=['POST'])
def add_student():
    df = get_df()
    student_id = request.form['student_id'].strip()
    name = request.form['name'].strip()
    if not student_id or not name:
        flash('Student ID and Name cannot be empty!', 'error')
        return redirect(url_for('index'))
    if not df.empty and student_id in df['student_id'].values:
        flash(f'Student ID {student_id} already exists!', 'error')
        return redirect(url_for('index'))
    new_student = {
        'student_id': student_id,
        'name': name,
        'days_present': normalize_days_present(request.form.get('days_present', 0)),
        'total_days': 0,
        'attendance_percentage': 0.0,
        'test_score_1': int(request.form.get('test_score_1', 0)),
        'test_score_2': int(request.form.get('test_score_2', 0)),
        'assignment_score': int(request.form.get('assignment_score', 0)),
        'final_exam_score': np.nan,
        'performance_category': 'N/A',
        'parent_phone': normalize_phone(request.form.get('parent_phone', ''))
    }
    df = pd.concat([df, pd.DataFrame([new_student])], ignore_index=True)
    save_df(df)
    flash(f'Student {name} added successfully.', 'success')
    return redirect(url_for('index'))

@app.route('/edit_student/<string:student_id>', methods=['POST'])
def edit_student(student_id):
    df = get_df()
    student_index = df.index[df['student_id'] == student_id].tolist()
    if not student_index:
        flash(f'Student ID {student_id} not found.', 'error')
        return redirect(url_for('index'))
    idx = student_index[0]
    df.loc[idx, 'name'] = request.form.get('name', df.loc[idx, 'name'])
    df.loc[idx, 'test_score_1'] = int(request.form.get('test_score_1', df.loc[idx, 'test_score_1']))
    df.loc[idx, 'test_score_2'] = int(request.form.get('test_score_2', df.loc[idx, 'test_score_2']))
    df.loc[idx, 'assignment_score'] = int(request.form.get('assignment_score', df.loc[idx, 'assignment_score']))
    # Attendance fields
    days_present = normalize_days_present(request.form.get('days_present', df.loc[idx, 'days_present'] if 'days_present' in df.columns else 0))
    total_days = int(request.form.get('total_days', df.loc[idx, 'total_days'] if 'total_days' in df.columns else 0))
    attendance_percentage = round((int(days_present) / total_days) * 100, 2) if total_days > 0 else 0.0
    df.loc[idx, 'days_present'] = days_present
    df.loc[idx, 'total_days'] = total_days
    df.loc[idx, 'attendance_percentage'] = attendance_percentage
    # Update parent phone
    if 'parent_phone' in df.columns:
        df.loc[idx, 'parent_phone'] = normalize_phone(request.form.get('parent_phone', df.loc[idx, 'parent_phone']))
    save_df(df)
    # Force reload from disk and redirect
    return redirect(url_for('index'))

@app.route('/edit_attendance/<string:student_id>', methods=['POST'])
def edit_attendance(student_id):
    df = get_df()
    student_index = df.index[df['student_id'] == student_id].tolist()
    if not student_index:
        flash(f'Student ID {student_id} not found.', 'error')
        return redirect(url_for('index'))
    idx = student_index[0]
    # Get new days_present and total_days from form
    days_present = int(request.form.get('days_present', df.loc[idx, 'days_present'] if 'days_present' in df.columns else 0))
    total_days = int(request.form.get('total_days', df.loc[idx, 'total_days'] if 'total_days' in df.columns else 0))
    # Update values
    df.loc[idx, 'days_present'] = days_present
    df.loc[idx, 'total_days'] = total_days
    # Calculate percentage
    attendance_percentage = round((days_present / total_days) * 100, 2) if total_days > 0 else 0.0
    df.loc[idx, 'attendance_percentage'] = attendance_percentage
    save_df(df)
    flash(f"Attendance for {df.loc[idx, 'name']} updated: {days_present}/{total_days} days ({attendance_percentage}%)", 'success')
    return redirect(url_for('index'))

@app.route('/delete_student/<string:student_id>', methods=['POST'])
def delete_student(student_id):
    # --- Step 1: Remove student from the main database ---
    df = get_df()
    if not df.empty:
            # Reset attendance before removing
            if student_id in df['student_id'].values:
                df.loc[df['student_id'] == student_id, 'attendance_percentage'] = 0.0
            df = df[df['student_id'] != student_id]
            save_df(df)
    
    # --- Step 2: Remove student's face images ---
    face_files = glob.glob(os.path.join(FACES_FOLDER, f'{student_id}.*.jpg'))
    for f in face_files:
        try:
            os.remove(f)
        except OSError as e:
            app.logger.error(f"Error removing face image {f}: {e}")

    # --- Step 3 (NEW): Remove student from TODAY'S attendance log ---
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    attendance_file_path = os.path.join(ATTENDANCE_FOLDER, f"attendance_{today_str}.csv")

    if os.path.exists(attendance_file_path):
        try:
            # Read today's attendance file
            att_df = pd.read_csv(attendance_file_path, dtype={'Student ID': str})
            
            # Check if the student is in today's log
            if not att_df.empty and student_id in att_df['Student ID'].values:
                # Filter out the deleted student and keep everyone else
                att_df_updated = att_df[att_df['Student ID'] != student_id]
                
                # Save the updated attendance file, overwriting the old one
                # If this makes the file empty, it will save an empty file with headers
                att_df_updated.to_csv(attendance_file_path, index=False)
                app.logger.info(f"Removed student {student_id} from today's attendance log.")

        except (pd.errors.EmptyDataError, FileNotFoundError) as e:
            app.logger.warning(f"Could not modify today's attendance file during deletion: {e}")

    # --- Step 4 (NEW): Remove student's fingerprint data ---
    slot = get_fingerprint_slot_for_student(student_id)
    if slot:
        print(f"🗑️  Removing fingerprint data for student {student_id} from slot {slot}")
        
        if fingerprint_connected:
            # Send delete command to ESP32 sensor
            send_fingerprint_command(f"DELETE:{slot}")
            response = read_fingerprint_response(timeout=5)
            if response and response.get('success'):
                print(f"✅ Fingerprint deleted from sensor slot {slot}")
            else:
                print(f"⚠️  Failed to delete fingerprint from sensor slot {slot}")
        
        # Always remove from mapping file
        if os.path.exists(FINGERPRINT_MAP_FILE):
            try:
                with open(FINGERPRINT_MAP_FILE, 'r') as f:
                    fp_map = json.load(f)
                if str(student_id) in fp_map:
                    del fp_map[str(student_id)]
                    with open(FINGERPRINT_MAP_FILE, 'w') as f:
                        json.dump(fp_map, f, indent=2)
                    print(f"✅ Fingerprint mapping removed from fingerprint_map.json")
            except Exception as e:
                app.logger.error(f"Error removing fingerprint mapping for student {student_id}: {e}")

    flash(f'Student ID {student_id} has been completely removed from the system, including all biometric data and today\'s attendance.', 'success')
    return redirect(url_for('index'))

# --- Face Recognition and Enrollment Routes ---
@app.route('/enroll')
def enroll_page():
    return render_template('enroll.html')

@app.route('/live_attendance')
def live_attendance_page():
    if not os.path.exists(MODEL_FILE):
        flash('Face recognition model not found. Please enroll students and train the model first.', 'error')
        return redirect(url_for('index'))
    role = session.get('role')
    username = session.get('username')
    df = get_df()
    if role == 'student':
        df = df[df['student_id'] == username]
        return render_template('live_attendance.html', students=df.to_dict(orient='records'))
    return render_template('live_attendance.html')

@app.route('/capture_faces', methods=['POST'])
def capture_faces():
    df = get_df()
    data = request.get_json()
    student_id = str(data['student_id']).strip()
    name = data['name'].strip()
    parent_phone = normalize_phone(data.get('parent_phone', ''))
    if not parent_phone:
        parent_phone = ''
    
    if not student_id or not name:
        return jsonify({'status': 'error', 'message': 'Student ID and Name cannot be empty.'})
        df.loc[idx, 'name'] = request.form.get('name', df.loc[idx, 'name'])
        df.loc[idx, 'test_score_1'] = int(request.form.get('test_score_1', df.loc[idx, 'test_score_1']))
        df.loc[idx, 'test_score_2'] = int(request.form.get('test_score_2', df.loc[idx, 'test_score_2']))
        df.loc[idx, 'assignment_score'] = int(request.form.get('assignment_score', df.loc[idx, 'assignment_score']))
    os.makedirs(FACES_FOLDER, exist_ok=True)
    # Add the student to the main CSV first
    new_student = {
        'student_id': student_id,
        'name': name,
        'attendance_percentage': 0,
        'test_score_1': 0,
        'test_score_2': 0,
        'assignment_score': 0,
        'final_exam_score': np.nan,
        'performance_category': 'N/A',
        'parent_phone': parent_phone
    }
    df = pd.concat([df, pd.DataFrame([new_student])], ignore_index=True)
    save_df(df)

    # Save face images
    for i, image_data in enumerate(data['images']):
        try:
            _, encoded = image_data.split(",", 1)
            nparr = np.frombuffer(base64.b64decode(encoded), np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.3, 5)
            if len(faces) > 0:
                (x, y, w, h) = faces[0]
                face_roi = cv2.resize(gray[y:y+h, x:x+w], (200, 200))
                cv2.imwrite(os.path.join(FACES_FOLDER, f"{student_id}.{i}.jpg"), face_roi)
        except Exception as e: app.logger.error(f"Error processing image {i} for student {student_id}: {e}")
    
    return jsonify({'status': 'success', 'message': f'Successfully enrolled {name}. Remember to train the model!'})

@app.route('/train_model', methods=['POST'])
def train_model_route():
    image_paths = [os.path.join(FACES_FOLDER, f) for f in os.listdir(FACES_FOLDER)]
    if not image_paths:
        return jsonify({'status': 'error', 'message': 'No face images found to train.'})
    
    face_samples, labels = [], []
    # Create a mapping from alphanumeric student_id to an integer label
    student_ids = sorted(list(set([os.path.basename(p).split('.')[0] for p in image_paths])))
    id_map = {sid: i for i, sid in enumerate(student_ids)}
    
    with open(ID_MAP_FILE, 'w') as f:
        json.dump(id_map, f)

    for image_path in image_paths:
        try:
            img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
            student_id_str = os.path.basename(image_path).split('.')[0]
            label = id_map[student_id_str]
            face_samples.append(img)
            labels.append(label)
        except Exception as e:
            app.logger.error(f"Error processing {image_path}: {e}")

    if not labels:
        return jsonify({'status': 'error', 'message': 'No valid face samples could be processed.'})
        
    recognizer.train(face_samples, np.array(labels))
    recognizer.write(MODEL_FILE)
    return jsonify({'status': 'success', 'message': f'Model trained with {len(face_samples)} images from {len(id_map)} students.'})

@app.route('/recognize', methods=['POST'])
def recognize():
    if not os.path.exists(MODEL_FILE) or not os.path.exists(ID_MAP_FILE):
        return jsonify({'error': 'Model or ID map not found'}), 500
    try:
        recognizer.read(MODEL_FILE)
        with open(ID_MAP_FILE, 'r') as f: id_map = json.load(f)
        rev_id_map = {v: k for k, v in id_map.items()}
    except Exception as e:
        return jsonify({'error': 'Failed to load recognition model or ID map'}), 500

    df = get_df()
    student_info = {row['student_id']: row['name'] for _, row in df.iterrows()}

    try:
        image_data = request.json['image'].split(',')[1]
        nparr = np.frombuffer(base64.b64decode(image_data), np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame is None: return jsonify({'error': 'Invalid image data'}), 400
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        recognized_faces = []

        for (x, y, w, h) in faces:
            label_pred, conf = recognizer.predict(gray[y:y+h, x:x+w])
            name = "Unknown"
            attendance = {'percentage': 0.0, 'status': ''}
            status = ''
            # Using a confidence threshold of 80
            if conf < 80:
                student_id = rev_id_map.get(label_pred)
                if student_id and student_id in student_info:
                    name = student_info[student_id]
                    attendance = mark_attendance(student_id, name)
                    status = attendance.get('status', '')
            recognized_faces.append({
                'name': name,
                'box': [int(x), int(y), int(w), int(h)],
                'attendance': float(attendance.get('percentage', 0.0)),
                'confidence': float(conf),
                'status': status
            })
        return jsonify({'recognized_faces': recognized_faces})
    except Exception as e:
        app.logger.error(f"Error in recognition: {str(e)}")
        return jsonify({'error': f'Recognition failed: {str(e)}'}), 500

# --- Barcode and Attendance Routes ---
@app.route('/barcode_attendance')
def barcode_attendance_page():
    role = session.get('role')
    username = session.get('username')
    df = get_df()
    if role == 'student':
        df = df[df['student_id'] == username]
        return render_template('barcode_attendance.html', students=df.to_dict(orient='records'))
    return render_template('barcode_attendance.html')

@app.route('/mark_barcode_attendance', methods=['POST'])
def mark_barcode_attendance():
    """Mark attendance via barcode scan with robust error handling."""
    try:
        data = request.get_json()
        scanned_id = str(data['student_id']).strip()
        
        df = get_df()
        if df.empty:
            return jsonify({'success': False, 'message': 'Student database is empty.'}), 404

        student_row = df[df['student_id'] == scanned_id]
        
        if student_row.empty:
            return jsonify({'success': False, 'message': f"Student ID '{scanned_id}' not found."}), 404
        
        student_name = student_row.iloc[0]['name']
        result = mark_attendance(scanned_id, student_name)
        if result['status'] == 'already_present':
            return jsonify({
                'success': False,
                'student': {'id': scanned_id, 'name': student_name},
                'timestamp': datetime.datetime.now().strftime("%H:%M:%S"),
                'message': f'Attendance already marked for {student_name}'
            }), 200
        elif result['status'] == 'marked':
            return jsonify({
                'success': True,
                'student': {'id': scanned_id, 'name': student_name},
                'timestamp': datetime.datetime.now().strftime("%H:%M:%S"),
                'message': f'Attendance marked for {student_name}'
            })
        else:
            return jsonify({'success': False, 'message': 'Unknown error'}), 500
    except Exception as e:
        app.logger.error(f"Error in barcode attendance: {str(e)}")
        return jsonify({'success': False, 'message': 'Internal server error'}), 500

# --- Fingerprint Attendance Routes ---
@app.route('/fingerprint_attendance')
def fingerprint_attendance_page():
    """Fingerprint attendance page"""
    role = session.get('role')
    username = session.get('username')
    df = get_df()
    if role == 'student':
        df = df[df['student_id'] == username]
        return render_template('fingerprint_attendance.html', students=df.to_dict(orient='records'), fingerprint_connected=fingerprint_connected)
    return render_template('fingerprint_attendance.html', fingerprint_connected=fingerprint_connected)

@app.route('/fingerprint_status')
def fingerprint_status():
    """Check if fingerprint reader is connected"""
    return jsonify({'connected': fingerprint_connected})

@app.route('/enroll_fingerprint', methods=['POST'])
def enroll_fingerprint_route():
    """Enroll a fingerprint for a student"""
    global fingerprint_enrollment_status, fingerprint_enrollment_active
    fingerprint_enrollment_status = []  # Clear previous messages
    fingerprint_enrollment_active = True  # Set enrollment flag to prevent attendance during enrollment
    
    if not fingerprint_connected:
        fingerprint_enrollment_active = False  # Reset flag on early exit
        return jsonify({'success': False, 'message': 'Fingerprint reader not connected'}), 503
    
    data = request.get_json()
    student_id = str(data.get('student_id', '')).strip()
    
    print("\n" + "="*60)
    print(f"🔵 FINGERPRINT ENROLLMENT STARTED for Student ID: {student_id}")
    print("="*60)
    
    df = get_df()
    student_row = df[df['student_id'] == student_id]
    
    if student_row.empty:
        print(f"❌ Student ID {student_id} not found in database")
        return jsonify({'success': False, 'message': f'Student ID {student_id} not found'}), 404
    
    # Check if already enrolled
    existing_slot = get_fingerprint_slot_for_student(student_id)
    if existing_slot:
        print(f"⚠️  Student already enrolled in slot {existing_slot}")
        return jsonify({'success': False, 'message': f'Student already has fingerprint enrolled in slot {existing_slot}'}), 400
    
    # Get next available slot
    slot = get_next_available_fingerprint_slot()
    print(f"📍 Using fingerprint slot: {slot}")
    
    # Send enrollment command to ESP32
    fingerprint_enrollment_status.append({'type': 'info', 'message': f'Starting enrollment in slot {slot}...'})
    print(f"\n🔄 Sending enrollment command: ENROLL:{slot}")
    send_fingerprint_command(f"ENROLL:{slot}")
    
    # Read enrollment responses
    responses = []
    enrollment_complete = False
    start_time = time.time()
    
    print("\n📥 Listening for ESP32 responses...")
    while time.time() - start_time < 60:  # 60 second timeout
        # Read multiple responses if available (ESP32 sends them quickly)
        response = read_fingerprint_response(timeout=0.2)
        if response:
            responses.append(response)
            msg_type = response.get('type')
            msg_text = response.get('message', '')
            
            # Store ALL message types for real-time updates
            fingerprint_enrollment_status.append({
                'type': msg_type,
                'message': msg_text
            })
            
            # Terminal output based on type
            if msg_type == 'prompt':
                print(f"👆 USER ACTION REQUIRED: {msg_text}")
            elif msg_type == 'status':
                print(f"ℹ️  Status: {msg_text}")
            elif msg_type == 'info':
                print(f"💡 Info: {msg_text}")
            elif msg_type == 'enrolled':
                if response.get('success'):
                    save_fingerprint_mapping(student_id, slot)
                    enrollment_complete = True
                    fingerprint_enrollment_status.append({'type': 'success', 'message': 'Enrollment complete!'})
                    fingerprint_enrollment_active = False  # Reset enrollment flag
                    
                    # Clear the fingerprint queue to remove any match messages from enrollment
                    while not fingerprint_queue.empty():
                        try:
                            fingerprint_queue.get_nowait()
                        except queue.Empty:
                            break
                    print("🗑️  Cleared fingerprint queue (removed enrollment matches)")
                    
                    # Deactivate sensor after successful enrollment
                    print("🔌 Deactivating sensor after enrollment...")
                    send_fingerprint_command("DEACTIVATE")
                    
                    print(f"\n✅ ENROLLMENT SUCCESSFUL!")
                    print(f"   Student: {student_id}")
                    print(f"   Slot: {slot}")
                    print(f"   Sensor deactivated")
                    print("="*60 + "\n")
                    return jsonify({
                        'success': True,
                        'message': f'Fingerprint enrolled successfully in slot {slot}',
                        'slot': slot,
                        'responses': responses
                    })
            elif msg_type == 'error':
                fingerprint_enrollment_status.append({'type': 'error', 'message': msg_text})
                fingerprint_enrollment_active = False  # Reset enrollment flag on error
                
                # Clear the fingerprint queue
                while not fingerprint_queue.empty():
                    try:
                        fingerprint_queue.get_nowait()
                    except queue.Empty:
                        break
                
                # Deactivate sensor on error
                print("🔌 Deactivating sensor after enrollment error...")
                send_fingerprint_command("DEACTIVATE")
                
                print(f"\n❌ ENROLLMENT FAILED: {msg_text}")
                print("="*60 + "\n")
                return jsonify({
                    'success': False,
                    'message': msg_text,
                    'responses': responses
                }), 400
            else:
                # Capture any other message types
                print(f"📨 ESP32 Message [{msg_type}]: {msg_text}")
        
        # Show timeout countdown every 10 seconds
        elapsed = int(time.time() - start_time)
        if elapsed > 0 and elapsed % 10 == 0:
            remaining = 60 - elapsed
            if remaining > 0 and elapsed % 10 < 1:  # Print only once per 10-second interval
                print(f"⏳ Waiting... ({remaining} seconds remaining)")
    
    fingerprint_enrollment_status.append({'type': 'error', 'message': 'Enrollment timeout - please try again'})
    fingerprint_enrollment_active = False  # Reset enrollment flag on timeout
    
    # Clear the fingerprint queue on timeout
    while not fingerprint_queue.empty():
        try:
            fingerprint_queue.get_nowait()
        except queue.Empty:
            break
    
    # Deactivate sensor on timeout
    print("🔌 Deactivating sensor after enrollment timeout...")
    send_fingerprint_command("DEACTIVATE")
    
    print(f"\n⏱️  ENROLLMENT TIMEOUT (60 seconds elapsed)")
    print(f"   Responses received: {len(responses)}")
    print("="*60 + "\n")
    return jsonify({
        'success': False,
        'message': 'Enrollment timeout - did you place your finger on the sensor?',
        'responses': responses
    }), 408

@app.route('/enrollment_status')
def get_enrollment_status():
    """Get real-time enrollment status messages"""
    global fingerprint_enrollment_status
    return jsonify({'messages': fingerprint_enrollment_status})

@app.route('/get_fingerprint_matches')
def get_fingerprint_matches():
    """Get fingerprint matches from queue - only processes if sensor is activated"""
    global fingerprint_sensor_activated
    matches = []
    queue_size = fingerprint_queue.qsize()
    
    print(f"\n🔍 Checking fingerprint queue (size: {queue_size})")
    
    # Only process matches if sensor is activated for attendance
    if not fingerprint_sensor_activated:
        print(f"   ⏸️  Sensor not activated - skipping match processing")
        # Clear any old matches from queue
        while not fingerprint_queue.empty():
            try:
                fingerprint_queue.get_nowait()
                print(f"   🗑️  Removed old match from queue")
            except queue.Empty:
                break
        print(f"   📤 Returning 0 matches (sensor not activated)")
        return jsonify({'matches': []})
    
    while not fingerprint_queue.empty():
        try:
            data = fingerprint_queue.get_nowait()
            slot_id = data.get('id')
            confidence = data.get('confidence')
            
            print(f"   � Processing match: Slot {slot_id}, Confidence {confidence}")
            
            # Find student by fingerprint slot
            if not os.path.exists(FINGERPRINT_MAP_FILE):
                print(f"   ❌ fingerprint_map.json not found!")
                print(f"   Please enroll fingerprints through the enrollment page first.")
                continue
                
            with open(FINGERPRINT_MAP_FILE, 'r') as f:
                fp_map = json.load(f)
                print(f"   📋 Current mappings: {fp_map}")
                
                # Reverse lookup: slot -> student_id
                student_found = False
                for student_id, mapped_slot in fp_map.items():
                    if mapped_slot == slot_id:
                        student_found = True
                        print(f"   ✅ Matched to Student ID: {student_id}")
                        
                        df = get_df()
                        student_row = df[df['student_id'] == student_id]
                        
                        if not student_row.empty:
                            name = student_row.iloc[0]['name']
                            print(f"   👤 Student Name: {name}")
                            print(f"   📝 Marking attendance...")
                            
                            attendance = mark_attendance(student_id, name)
                            match_info = {
                                'student_id': student_id,
                                'name': name,
                                'confidence': confidence,
                                'attendance': attendance,
                                'timestamp': datetime.datetime.now().strftime("%H:%M:%S"),
                                'status': attendance.get('status', '')
                            }
                            matches.append(match_info)
                            if attendance.get('status') == 'already_present':
                                print(f"   ⚠️ Attendance already marked for {name}")
                            else:
                                print(f"   ✅ Attendance marked successfully!")
                            print(f"   Status: {attendance}\n")
                        else:
                            print(f"   ❌ Student ID {student_id} not found in database!")
                        break
                
                if not student_found:
                    print(f"   ❌ Slot {slot_id} not mapped to any student")
                    print(f"   Available mappings: {fp_map}")
                    
        except queue.Empty:
            break
        except Exception as e:
            print(f"   ❌ Error: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"   📤 Returning {len(matches)} matches to frontend")
    return jsonify({'matches': matches})

@app.route('/delete_fingerprint/<string:student_id>', methods=['POST'])
def delete_fingerprint(student_id):
    """Delete a student's fingerprint"""
    slot = get_fingerprint_slot_for_student(student_id)
    if not slot:
        return jsonify({'success': False, 'message': 'No fingerprint found for this student'}), 404
    
    if not fingerprint_connected:
        # Just remove from mapping
        if os.path.exists(FINGERPRINT_MAP_FILE):
            with open(FINGERPRINT_MAP_FILE, 'r') as f:
                fp_map = json.load(f)
            if str(student_id) in fp_map:
                del fp_map[str(student_id)]
                with open(FINGERPRINT_MAP_FILE, 'w') as f:
                    json.dump(fp_map, f, indent=2)
        return jsonify({'success': True, 'message': 'Fingerprint mapping removed (reader offline)'}), 200
    
    # Send delete command
    send_fingerprint_command(f"DELETE:{slot}")
    response = read_fingerprint_response(timeout=5)
    
    if response and response.get('success'):
        # Remove from mapping
        if os.path.exists(FINGERPRINT_MAP_FILE):
            with open(FINGERPRINT_MAP_FILE, 'r') as f:
                fp_map = json.load(f)
            if str(student_id) in fp_map:
                del fp_map[str(student_id)]
                with open(FINGERPRINT_MAP_FILE, 'w') as f:
                    json.dump(fp_map, f, indent=2)
        return jsonify({'success': True, 'message': f'Fingerprint deleted from slot {slot}'})
    
    return jsonify({'success': False, 'message': 'Failed to delete fingerprint from sensor'}), 500

@app.route('/fingerprint_activate', methods=['POST'])
def fingerprint_activate():
    """Activate fingerprint sensor for attendance verification"""
    global fingerprint_sensor_activated
    
    if not fingerprint_connected:
        return jsonify({'success': False, 'message': 'Fingerprint reader not connected'}), 503
    
    print("\n🔌 Activating fingerprint sensor for attendance...")
    fingerprint_sensor_activated = True  # Set flag to allow attendance marking
    
    # Send activation command to ESP32
    send_fingerprint_command("ACTIVATE")
    
    # Wait a moment for activation
    time.sleep(0.5)
    
    # Start continuous verification mode
    print("🔍 Starting continuous verification...")
    send_fingerprint_command("VERIFY")
    
    print("✅ Sensor activated and verification started")
    print(f"   Attendance marking: ENABLED")
    app.logger.info("Fingerprint sensor activated and verification started")
    return jsonify({'success': True, 'message': 'Fingerprint sensor activated and ready for scanning'})

@app.route('/fingerprint_deactivate', methods=['POST'])
def fingerprint_deactivate():
    """Deactivate fingerprint sensor to save power"""
    global fingerprint_sensor_activated
    
    if not fingerprint_connected:
        return jsonify({'success': False, 'message': 'Fingerprint reader not connected'}), 503
    
    fingerprint_sensor_activated = False  # Disable attendance marking
    
    # Send deactivation command to ESP32
    send_fingerprint_command("DEACTIVATE")
    
    print("🔌 Sensor deactivated - Attendance marking: DISABLED")
    app.logger.info("Fingerprint sensor deactivated to save power")
    return jsonify({'success': True, 'message': 'Fingerprint sensor deactivated'})

@app.route('/get_today_attendance_list')
def get_today_attendance_list():
    """
    Gets today's attendance, BUT filters it to only show records for students
    who currently exist in the main students_data.csv file.
    """
    # First, get the list of currently valid student IDs
    main_df = get_df()
    if main_df.empty:
        return jsonify([]) # If there are no students, there's no valid attendance
    valid_student_ids = main_df['student_id'].tolist()

    # Now, read today's attendance log
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    attendance_file = os.path.join(ATTENDANCE_FOLDER, f"attendance_{today_str}.csv")

    if os.path.exists(attendance_file):
        try:
            att_df = pd.read_csv(attendance_file, dtype={'Student ID': str})
            # Filter the attendance records to only include valid students
            att_df_filtered = att_df[att_df['Student ID'].isin(valid_student_ids)]

            # Rename columns for the frontend
            att_df_filtered = att_df_filtered.rename(columns={'Student ID': 'id', 'Name': 'name', 'Time': 'timestamp'})
            
            # Return the filtered list
            return jsonify(att_df_filtered.to_dict(orient='records'))
        except (pd.errors.EmptyDataError, KeyError):
            # Handles cases where the attendance file is empty or malformed
            return jsonify([])
            
    return jsonify([]) # No attendance file for today

@app.route('/get_today_attendance', methods=['GET'])
def get_today_attendance():
    """A dedicated route for live_attendance page to get today's data."""
    df = get_df()
    total_students = len(df)
    
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    attendance_file = os.path.join(ATTENDANCE_FOLDER, f"attendance_{today_str}.csv")
    present_list = []
    present_count = 0
    
    if os.path.exists(attendance_file):
        try:
            att_df = pd.read_csv(attendance_file, dtype={'Student ID': str})
            present_list = att_df.to_dict(orient='records')
            present_count = len(att_df)
        except pd.errors.EmptyDataError:
            pass # File is empty, which is fine
            
    return jsonify({
        'total_students': total_students,
        'present_today_count': present_count,
        'present_today': present_list
    })

# --- Analysis, Visualization and Stats Routes ---
def get_trained_model_and_data(df):
    """Helper function to train the model required for analysis and intervention."""
    feature_cols = ['attendance_percentage', 'test_score_1', 'test_score_2', 'assignment_score']
    
    # Ensure columns are numeric for calculation
    for col in feature_cols + ['final_exam_score']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    train_df = df.dropna(subset=feature_cols + ['final_exam_score'])
    
    if len(train_df) < 2:
        return None, None, "Not enough complete student records (with final scores) to train a prediction model."
    
    # Use Decision Tree for better non-linear prediction in this context
    model = DecisionTreeRegressor(random_state=42)
    model.fit(train_df[feature_cols], train_df['final_exam_score'])
    
    return model, feature_cols, None

def send_parent_notification(student):
    parent_phone = student.get('parent_phone', None)
    if not parent_phone:
        return
    # Placeholder notification (print to server log)
    message_body = f"Alert: Your child {student['name']} (ID: {student['student_id']}) is classified as AT RISK. Please contact the school."
    print(f"Notification (placeholder) to {parent_phone}: {message_body}")

@app.route('/analyze_performance', methods=['POST'], endpoint='analyze_performance_route')
def analyze_performance_route():
    df = get_df()
    model, feature_cols, error = get_trained_model_and_data(df)
    
    if error:
        flash(error, 'warning')
        return redirect(url_for('index'))
    
    model_choice = request.form.get('model_choice', 'DecisionTreeRegressor')
    # Re-train with user choice if needed (defaulting to DT here for consistency)
    if model_choice == 'LinearRegression':
        model = LinearRegression()
        model.fit(df.dropna(subset=feature_cols + ['final_exam_score'])[feature_cols], df.dropna(subset=feature_cols + ['final_exam_score'])['final_exam_score'])

    to_predict_mask = df['final_exam_score'].isnull() & df[feature_cols].notnull().all(axis=1)
    if to_predict_mask.any():
        predicted_scores = model.predict(df.loc[to_predict_mask, feature_cols])
        df.loc[to_predict_mask, 'final_exam_score'] = np.clip(predicted_scores, 0, 100)
    
    def categorize(score):
        if pd.isna(score): return "N/A"
        if score < 50: return "At Risk"
        if score < 70: return "Average"
        if score < 85: return "Good"
        return "Excellent"
    df['performance_category'] = df['final_exam_score'].apply(categorize)
    save_df(df)
    
    flash(f"Performance analysis complete using {model_choice} model.", "success")
    role = session.get('role')
    username = session.get('username')
    at_risk_students = df[df['performance_category'] == 'At Risk']
    if role == 'student':
        at_risk_students = at_risk_students[at_risk_students['student_id'] == username]
    at_risk_students = at_risk_students.to_dict(orient='records')
    for student in at_risk_students:
        send_parent_notification(student)
    return render_template('analysis_results.html', at_risk_students=at_risk_students)


@app.route('/get_intervention_suggestion', methods=['POST'])
def get_intervention_suggestion():
    """NEW ROUTE: Calculates the most impactful intervention for a specific student."""
    try:
        student_id = request.json.get('student_id')
        df = get_df()
        
        student_data = df[df['student_id'] == student_id].iloc[0]
        
        # Check if the student has any incomplete data that would make prediction impossible
        if student_data[['test_score_1', 'test_score_2', 'assignment_score', 'attendance_percentage']].isnull().any():
            return jsonify({'suggestion': 'Data incomplete. Please ensure all assessment scores are entered to run a personalized analysis.'})

        model, feature_cols, error = get_trained_model_and_data(df)
        
        if error:
            return jsonify({'suggestion': f'Cannot generate suggestion: {error}'})

        # Base data for prediction
        base_data = student_data[feature_cols].to_dict()
        base_score = model.predict(pd.DataFrame([base_data], columns=feature_cols))[0]
        
        # Define scenarios for testing impact
        scenarios = {
            'attendance': {
                'label': 'Improve Attendance',
                'change': {'attendance_percentage': min(100, base_data['attendance_percentage'] + 15)}, # 15% boost
                'message': 'Focus on improving attendance by 15%.'
            },
            'test1': {
                'label': 'Improve Test 1 Score',
                'change': {'test_score_1': min(100, base_data['test_score_1'] + 15)}, # 15 point boost
                'message': 'Target a 15 point improvement on Test 1.'
            },
            'assignment': {
                'label': 'Improve Assignment Score',
                'change': {'assignment_score': min(100, base_data['assignment_score'] + 15)}, # 15 point boost
                'message': 'Focus on raising the Assignment score by 15 points.'
            }
        }
        
        max_boost = -1
        best_scenario = None
        
        for key, scenario in scenarios.items():
            test_data = base_data.copy()
            test_data.update(scenario['change'])
            
            predicted_score = model.predict(pd.DataFrame([test_data], columns=feature_cols))[0]
            boost = predicted_score - base_score
            
            if boost > max_boost:
                max_boost = boost
                best_scenario = scenario

        if best_scenario and max_boost > 0:
            final_suggestion = f"The most impactful action is to **{best_scenario['message']}**! This is predicted to increase the final score by **{max_boost:.2f} points** (from {base_score:.2f} to {base_score + max_boost:.2f})."
        else:
            final_suggestion = f"No single intervention yielded a significant boost. Current predicted score is {base_score:.2f}. Suggest a holistic review of all scores."
        
        return jsonify({'suggestion': final_suggestion, 'student_name': student_data['name']})

    except IndexError:
        return jsonify({'suggestion': 'Student not found.'})
    except Exception as e:
        app.logger.error(f"Error generating intervention: {e}")
        return jsonify({'suggestion': f'An error occurred: {str(e)}'})

@app.route('/what_if_analysis', methods=['POST'])
def what_if_analysis():
    df = get_df()
    data = request.json

    # UPDATED: The model now requires all four features from the sliders.
    hypothetical_data = pd.DataFrame([{
        'attendance_percentage': float(data['attendance']), 
        'test_score_1': float(data['test1']), 
        'test_score_2': float(data['test2']),
        'assignment_score': float(data['assignment'])
    }])
    feature_cols = ['attendance_percentage', 'test_score_1', 'test_score_2', 'assignment_score']

    for col in feature_cols + ['final_exam_score']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    train_df = df.dropna(subset=feature_cols + ['final_exam_score'])
    if len(train_df) < 2:
        return jsonify({'error': 'Not enough data to train a model.'}), 400
    
    model = LinearRegression()
    model.fit(train_df[feature_cols], train_df['final_exam_score'])
    predicted_score = model.predict(hypothetical_data[feature_cols])[0]
    predicted_score = np.clip(predicted_score, 0, 100)

    def categorize(score):
        if pd.isna(score): return "N/A"
        if score < 50: return "At Risk"
        if score < 70: return "Average"
        if score < 85: return "Good"
        return "Excellent"
    category = categorize(predicted_score)

    return jsonify({'predicted_score': round(predicted_score, 2), 'category': category})
@app.route('/visualizations')
def visualizations():
    return render_template('visualizations.html')

@app.route('/get_chart_data')
def get_chart_data():
    df = get_df()
    for col in ['attendance_percentage', 'test_score_1', 'test_score_2', 'assignment_score', 'final_exam_score']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    performance_counts = df['performance_category'].value_counts().to_dict()
    final_scores = df['final_exam_score'].dropna()
    bins = pd.cut(final_scores, bins=[0, 50, 60, 70, 80, 90, 101], right=False)
    score_distribution = {str(k): v for k, v in bins.value_counts().sort_index().to_dict().items()}
    scatter_data = df[['attendance_percentage', 'final_exam_score']].dropna().to_dict(orient='records')
    category_order = ['At Risk', 'Average', 'Good', 'Excellent', 'N/A']
    grouped_scores = df.groupby('performance_category')[['test_score_1', 'test_score_2', 'assignment_score']].mean()
    grouped_scores = grouped_scores.reindex(category_order, fill_value=0).to_dict()
    return jsonify({'performance_counts': performance_counts, 'score_distribution': score_distribution, 'scatter_data': scatter_data, 'grouped_scores': grouped_scores})

@app.route('/get_complete_stats')
def get_complete_stats():
    # Get the main student list to get percentages and a list of valid IDs
    df = get_df()
    df = _update_attendance_percentages(df.copy()) # Use a copy to avoid side effects
    
    valid_student_ids = df['student_id'].tolist() if not df.empty else []
    total_students = len(df)

    # Determine today's present count by filtering the attendance log
    today = datetime.date.today().strftime("%Y-%m-%d")
    attendance_file = os.path.join(ATTENDANCE_FOLDER, f"attendance_{today}.csv")
    present_today_count = 0
    if os.path.exists(attendance_file):
        try:
            att_df = pd.read_csv(attendance_file, dtype={'Student ID': str})
            # THIS IS THE FIX: Filter attendance log to only include valid, existing students
            att_df_filtered = att_df[att_df['Student ID'].isin(valid_student_ids)]
            # Count the unique IDs from the *filtered* list
            present_today_count = len(att_df_filtered['Student ID'].dropna().unique())
        except (pd.errors.EmptyDataError, KeyError):
            pass  # If file is empty or malformed, count remains 0

    if df.empty:
        return jsonify({
            'total_students': 0, 'present_today': 0, 'avg_attendance': 0,
            'at_risk_count': 0, 'excellent_count': 0, 'good_count': 0,
            'average_count': 0, 'student_data': {}
        })

    # Calculate other stats from the main DataFrame
    valid_attendance = pd.to_numeric(df['attendance_percentage'], errors='coerce').dropna()
    avg_attendance = valid_attendance.mean() if not valid_attendance.empty else 0
    performance_counts = df['performance_category'].value_counts().to_dict()

    student_data = {row['student_id']: row.to_dict() for _, row in df.iterrows()}

    return jsonify({
        'total_students': total_students,
        'present_today': present_today_count,
        'avg_attendance': round(avg_attendance, 1),
        'at_risk_count': performance_counts.get('At Risk', 0),
        'excellent_count': performance_counts.get('Excellent', 0),
        'good_count': performance_counts.get('Good', 0),
        'average_count': performance_counts.get('Average', 0),
        'student_data': student_data
    })
@app.route('/get_live_attendance_stats')
def get_live_attendance_stats():
    """
    Provides a filtered list of today's attendees and total student count,
    specifically for the live_attendance.html page.
    """
    # Get the list of all currently valid students
    main_df = get_df()
    if main_df.empty:
        return jsonify({
            'total_students': 0,
            'present_count': 0,
            'present_list': []
        })
        
    total_students = len(main_df)
    valid_student_ids = main_df['student_id'].tolist()

    # Read and filter today's attendance log
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    attendance_file = os.path.join(ATTENDANCE_FOLDER, f"attendance_{today_str}.csv")
    present_list = []
    present_count = 0

    if os.path.exists(attendance_file):
        try:
            att_df = pd.read_csv(attendance_file, dtype={'Student ID': str})
            # The crucial step: filter the log against valid student IDs
            att_df_filtered = att_df[att_df['Student ID'].isin(valid_student_ids)]
            present_count = len(att_df_filtered)
            # Rename columns for the frontend
            att_df_filtered = att_df_filtered.rename(columns={'Student ID': 'id', 'Name': 'name', 'Time': 'timestamp'})
            present_list = att_df_filtered.to_dict(orient='records')
        except (pd.errors.EmptyDataError, KeyError):
            pass # File is empty or malformed, defaults are fine

    return jsonify({
        'total_students': total_students,
        'present_count': present_count,
        'present_list': present_list
    })
# --- EWS Helper Function ---
def get_at_risk_students():
    df = get_df()
    # Criteria: attendance < 75% or any score < 40
    at_risk = df[(df['attendance_percentage'] < 75) |
                 (df[['test_score_1', 'test_score_2', 'assignment_score', 'final_exam_score']].fillna(0).lt(40).any(axis=1))]
    return at_risk

@app.route('/ews', endpoint='ews_dashboard')
def ews_dashboard():
    role = session.get('role')
    username = session.get('username')
    at_risk_students = get_at_risk_students()
    if role == 'student':
        at_risk_students = at_risk_students[at_risk_students['student_id'] == username]
    return render_template('ews_dashboard.html', students=at_risk_students)

if __name__ == '__main__':
    for folder in [ATTENDANCE_FOLDER, FACES_FOLDER, MODELS_FOLDER, 'daily_attendance']:
        os.makedirs(folder, exist_ok=True)
    
    # Start the scheduler
    if not scheduler.running:
        scheduler.start()
        app.logger.info("Background scheduler started for daily attendance CSV generation")
    
    # Initialize fingerprint reader connection only in main process (not in reloader)
    import os as os_module
    if os_module.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        # This is the first run (before reloader kicks in)
        pass
    else:
        # This is the reloader process - initialize fingerprint
        app.logger.info("Initializing fingerprint reader...")
        if init_fingerprint_connection():
            app.logger.info("Fingerprint reader connected successfully")
        else:
            app.logger.warning("Fingerprint reader not connected - will run without fingerprint support")
    
    app.run(debug=True, host='0.0.0.0', use_reloader=True)
    