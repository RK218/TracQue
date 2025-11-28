"""
Python script to communicate with ESP32 R307S Fingerprint Sensor
Supports enrollment, verification, and attendance marking
"""

import serial
import serial.tools.list_ports
import json
import time
from datetime import datetime
import pandas as pd
import os

class FingerprintReader:
    def __init__(self, port=None, baudrate=115200):
        """
        Initialize fingerprint reader
        Args:
            port: Serial port (auto-detect if None)
            baudrate: Communication speed (default 115200)
        """
        # Auto-detect port if not specified
        if port is None:
            port = self.find_esp32_port()
            if port is None:
                raise Exception("No ESP32 device found. Make sure it's connected and close Arduino Serial Monitor!")
        
        try:
            self.ser = serial.Serial(port, baudrate, timeout=1)
            time.sleep(2)  # Wait for ESP32 to initialize
            print(f"✓ Connected to ESP32 on {port}")
            
            # Read initial status messages
            time.sleep(1)
            while self.ser.in_waiting:
                line = self.ser.readline().decode('utf-8').strip()
                if line:
                    try:
                        data = json.loads(line)
                        print(f"Status: {data}")
                    except:
                        print(line)
        except serial.SerialException as e:
            if "PermissionError" in str(e) or "Access is denied" in str(e):
                print(f"\n{'='*60}")
                print(f"✗ Error: Port {port} is already in use!")
                print(f"{'='*60}")
                print("\nPlease close:")
                print("  - Arduino IDE Serial Monitor")
                print("  - Any other serial terminal programs")
                print("  - Other Python scripts using this port")
                print(f"{'='*60}\n")
            else:
                print(f"✗ Error connecting to {port}: {e}")
                print("Available ports: Check Device Manager for COM port number")
            raise
    
    @staticmethod
    def find_esp32_port():
        """Auto-detect ESP32 port"""
        print("Searching for ESP32...")
        ports = serial.tools.list_ports.comports()
        
        for port in ports:
            # ESP32-S3 typically has these VID:PID or keywords
            if ('303A' in port.hwid or  # ESP32-S3
                'CP210' in port.hwid or  # CP2102 USB-to-Serial
                'CH340' in port.hwid or  # CH340 USB-to-Serial
                'USB Serial' in port.description):
                
                print(f"  Found ESP32 on {port.device}")
                print(f"  Description: {port.description}")
                return port.device
        
        print("  No ESP32 found")
        return None
    
    def send_command(self, command):
        """Send command to ESP32"""
        self.ser.write(f"{command}\n".encode())
        time.sleep(0.1)
    
    def read_response(self, timeout=30):
        """Read JSON response from ESP32"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.ser.in_waiting:
                line = self.ser.readline().decode('utf-8').strip()
                if line:
                    try:
                        data = json.loads(line)
                        return data
                    except json.JSONDecodeError as e:
                        print(f"Raw (non-JSON): {line}")
                    except Exception as e:
                        print(f"Error parsing response: {e}")
                        print(f"Line: {line}")
            time.sleep(0.1)
        return None
    
    def enroll_fingerprint(self, student_id, student_name):
        """
        Enroll a new fingerprint
        Args:
            student_id: Unique ID for the student (1-200)
            student_name: Name of the student
        """
        print(f"\n{'='*50}")
        print(f"Enrolling: {student_name} (ID: {student_id})")
        print(f"{'='*50}")
        
        self.send_command(f"ENROLL:{student_id}")
        
        # Read enrollment steps
        enrolled = False
        while True:
            response = self.read_response(timeout=60)
            if not response:
                break
            
            msg_type = response.get('type')
            message = response.get('message', '')
            
            if msg_type == 'prompt':
                print(f"→ {message}")
            elif msg_type == 'enrolled':
                if response.get('success'):
                    print(f"✓ Fingerprint enrolled successfully!")
                    enrolled = True
                    # Save to database
                    self.save_student(student_id, student_name)
                    break
            elif msg_type == 'error':
                print(f"✗ Error: {message}")
                break
            elif msg_type == 'status':
                print(f"  {message}")
        
        return enrolled
    
    def verify_fingerprint(self, timeout=10):
        """
        Wait for fingerprint and verify
        Returns: (student_id, confidence) or (None, None)
        """
        print("\n→ Place finger on sensor for verification...")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            response = self.read_response(timeout=1)
            if response:
                msg_type = response.get('type', 'unknown')
                
                # Debug: print the entire response
                print(f"[DEBUG] Response: {response}")
                
                if msg_type == 'match':
                    student_id = response.get('id', None)
                    confidence = response.get('confidence', 0)
                    
                    if student_id is None:
                        print(f"✗ Error: Response missing 'id' field: {response}")
                        return None, None
                    
                    print(f"✓ Match found! ID: {student_id}, Confidence: {confidence}")
                    return student_id, confidence
                    
                elif msg_type == 'nomatch':
                    print("✗ Fingerprint not recognized")
                    return None, None
        
        print("  Timeout - no finger detected")
        return None, None
    
    def get_template_count(self):
        """Get number of stored fingerprints"""
        self.send_command("COUNT")
        response = self.read_response()
        if response and response.get('type') == 'count':
            count = response.get('templates')
            print(f"Templates stored: {count}")
            return count
        return 0
    
    def show_all_fingerprints(self):
        """Show all enrolled fingerprints"""
        print("\n" + "="*60)
        print("ENROLLED FINGERPRINTS")
        print("="*60)
        
        # Load student data
        if not os.path.exists('students_data.csv'):
            print("✗ No student data found")
            print("  Please enroll students first")
            return
        
        try:
            students_df = pd.read_csv('students_data.csv')
            
            if len(students_df) == 0:
                print("No fingerprints enrolled yet")
                return
            
            print(f"\nTotal enrolled: {len(students_df)}\n")
            print(f"{'ID':<10} {'Name':<25} {'Enrolled Date':<25}")
            print("-" * 60)
            
            for _, row in students_df.iterrows():
                student_id = row.get('ID', 'N/A')
                name = row.get('Name', 'N/A')
                enrolled_date = row.get('Enrolled_Date', 'N/A')
                print(f"{student_id:<10} {name:<25} {enrolled_date:<25}")
            
            print("="*60)
            
            # Also show ESP32 template count
            print("\nESP32 Sensor Status:")
            self.get_template_count()
            
        except Exception as e:
            print(f"✗ Error reading student data: {e}")
    
    def delete_fingerprint(self, student_id):
        """Delete a fingerprint by ID"""
        print(f"\nDeleting fingerprint ID: {student_id}")
        self.send_command(f"DELETE:{student_id}")
        response = self.read_response()
        if response and response.get('success'):
            print(f"✓ Deleted successfully from ESP32 sensor")
            
            # Also remove from CSV
            if os.path.exists('students_data.csv'):
                try:
                    df = pd.read_csv('students_data.csv')
                    df = df[df['ID'] != student_id]
                    df.to_csv('students_data.csv', index=False)
                    print(f"✓ Removed from student database")
                except Exception as e:
                    print(f"⚠ Error updating database: {e}")
            
            return True
        else:
            print(f"✗ Delete failed")
            return False
    
    def delete_all_fingerprints(self):
        """Delete all fingerprints from sensor"""
        print("\n" + "="*60)
        print("⚠ WARNING: DELETE ALL FINGERPRINTS")
        print("="*60)
        print("This will remove ALL fingerprints from the ESP32 sensor!")
        confirmation = input("\nType 'DELETE ALL' to confirm: ").strip()
        
        if confirmation != "DELETE ALL":
            print("✗ Cancelled")
            return False
        
        print("\nDeleting all fingerprints from ESP32...")
        self.send_command("EMPTY")
        response = self.read_response(timeout=5)
        
        if response and response.get('success'):
            print(f"✓ All fingerprints deleted from ESP32 sensor")
            
            # Ask if user wants to clear database too
            clear_db = input("\nDo you want to clear the student database too? (yes/no): ").strip().lower()
            
            if clear_db == 'yes':
                if os.path.exists('students_data.csv'):
                    # Keep the file but clear all rows
                    df = pd.DataFrame(columns=['ID', 'Name', 'Enrolled_Date'])
                    df.to_csv('students_data.csv', index=False)
                    print(f"✓ Student database cleared")
            
            print("\n" + "="*60)
            print("✓ RESET COMPLETE")
            print("="*60)
            return True
        else:
            print(f"✗ Delete all failed")
            if response:
                print(f"Response: {response}")
            return False
    
    def save_student(self, student_id, student_name):
        """Save student info to CSV"""
        filename = 'students_data.csv'
        
        # Load existing data or create new
        if os.path.exists(filename):
            try:
                df = pd.read_csv(filename)
                # Check if required columns exist
                if 'ID' not in df.columns:
                    print(f"⚠ Existing {filename} has wrong format. Creating new file...")
                    df = pd.DataFrame(columns=['ID', 'Name', 'Enrolled_Date'])
            except Exception as e:
                print(f"⚠ Error reading {filename}: {e}. Creating new file...")
                df = pd.DataFrame(columns=['ID', 'Name', 'Enrolled_Date'])
        else:
            df = pd.DataFrame(columns=['ID', 'Name', 'Enrolled_Date'])
        
        # Check if student already exists
        if len(df) > 0 and student_id in df['ID'].values:
            df.loc[df['ID'] == student_id, 'Name'] = student_name
            df.loc[df['ID'] == student_id, 'Enrolled_Date'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"✓ Updated existing student ID {student_id}")
        else:
            new_row = pd.DataFrame({
                'ID': [student_id],
                'Name': [student_name],
                'Enrolled_Date': [datetime.now().strftime('%Y-%m-%d %H:%M:%S')]
            })
            df = pd.concat([df, new_row], ignore_index=True)
            print(f"✓ Added new student ID {student_id}")
        
        df.to_csv(filename, index=False)
        print(f"✓ Student data saved to {filename}")
    
    def mark_attendance(self, student_id):
        """Mark attendance for a student"""
        # Validate student_id
        if student_id is None:
            print("✗ Error: Invalid student ID (None)")
            return
        
        # Load student data
        if not os.path.exists('students_data.csv'):
            print("✗ No student data found")
            print("  Please enroll students first (Option 1)")
            return
        
        try:
            students_df = pd.read_csv('students_data.csv')
            student = students_df[students_df['ID'] == student_id]
            
            if student.empty:
                print(f"✗ Student ID {student_id} not found in database")
                print("  Please enroll this fingerprint first")
                return
            
            student_name = student.iloc[0]['Name']
        except Exception as e:
            print(f"✗ Error reading student data: {e}")
            return
        
        # Create attendance record
        today = datetime.now().strftime('%Y-%m-%d')
        attendance_file = f'attendance/attendance_{today}.csv'
        
        # Create attendance directory if it doesn't exist
        os.makedirs('attendance', exist_ok=True)
        
        # Load or create attendance file
        if os.path.exists(attendance_file):
            att_df = pd.read_csv(attendance_file)
            # Check if already marked today
            if student_id in att_df['ID'].values:
                print(f"⚠ {student_name} already marked present today")
                return
        else:
            att_df = pd.DataFrame(columns=['ID', 'Name', 'Time', 'Status'])
        
        # Add attendance record
        new_record = pd.DataFrame({
            'ID': [student_id],
            'Name': [student_name],
            'Time': [datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
            'Status': ['Present']
        })
        att_df = pd.concat([att_df, new_record], ignore_index=True)
        att_df.to_csv(attendance_file, index=False)
        
        print(f"\n{'='*50}")
        print(f"✓ ATTENDANCE MARKED")
        print(f"  Student: {student_name}")
        print(f"  ID: {student_id}")
        print(f"  Time: {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*50}")
    
    def continuous_verification(self):
        """Continuously verify fingerprints and mark attendance"""
        print("\n" + "="*50)
        print("CONTINUOUS ATTENDANCE MODE")
        print("="*50)
        print("Place finger on sensor to mark attendance")
        print("Press Ctrl+C to stop\n")
        
        try:
            while True:
                student_id, confidence = self.verify_fingerprint(timeout=5)
                if student_id:
                    self.mark_attendance(student_id)
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n\nStopped by user")
    
    def close(self):
        """Close serial connection"""
        if self.ser:
            self.ser.close()
            print("Connection closed")


def main():
    print("="*60)
    print("ESP32 R307S Fingerprint Attendance System")
    print("="*60)
    
    try:
        # Auto-detect port
        reader = FingerprintReader(port=None)
        
        while True:
            print("\n" + "="*60)
            print("MENU")
            print("="*60)
            print("1. Enroll new fingerprint")
            print("2. Verify fingerprint (one-time)")
            print("3. Continuous attendance mode")
            print("4. Get template count")
            print("5. Show all enrolled fingerprints")
            print("6. Delete fingerprint")
            print("7. Delete ALL fingerprints (Reset)")
            print("8. Exit")
            print("="*60)
            
            choice = input("\nEnter choice (1-8): ").strip()
            
            if choice == '1':
                try:
                    student_id = int(input("Enter Student ID (1-200): "))
                    if student_id < 1 or student_id > 200:
                        print("✗ Student ID must be between 1 and 200")
                        continue
                    student_name = input("Enter Student Name: ").strip()
                    if not student_name:
                        print("✗ Student name cannot be empty")
                        continue
                    reader.enroll_fingerprint(student_id, student_name)
                except ValueError:
                    print("✗ Please enter a valid number for Student ID")
            
            elif choice == '2':
                student_id, confidence = reader.verify_fingerprint()
                if student_id:
                    reader.mark_attendance(student_id)
            
            elif choice == '3':
                reader.continuous_verification()
            
            elif choice == '4':
                reader.get_template_count()
            
            elif choice == '5':
                reader.show_all_fingerprints()
            
            elif choice == '6':
                try:
                    student_id = int(input("Enter Student ID to delete: "))
                    reader.delete_fingerprint(student_id)
                except ValueError:
                    print("✗ Please enter a valid number for Student ID")
            
            elif choice == '7':
                reader.delete_all_fingerprints()
            
            elif choice == '8':
                break
            
            else:
                print("Invalid choice")
        
        reader.close()
    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
