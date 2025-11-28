"""
Test script to verify ESP32 fingerprint communication
"""
import serial
import time
import json

def find_esp32_port():
    """Try to find ESP32 on COM8 first"""
    import serial.tools.list_ports
    ports = serial.tools.list_ports.comports()
    
    print("Available COM ports:")
    for port in ports:
        print(f"  {port.device}: {port.description}")
        if 'USB' in port.description or 'Serial' in port.description or 'CH340' in port.description:
            print(f"    -> Possible ESP32 port")
    
    # Try COM8 first
    try:
        ser = serial.Serial('COM8', 115200, timeout=1)
        time.sleep(2)
        print("\n✓ Connected to COM8")
        return ser
    except:
        print("\n✗ Could not connect to COM8")
        return None

def test_communication(ser):
    """Test sending commands and receiving responses"""
    print("\n" + "="*50)
    print("Testing ESP32 Fingerprint Communication")
    print("="*50)
    
    # Clear any existing data
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    
    # Wait for startup messages
    print("\nWaiting for ESP32 startup messages (5 seconds)...")
    time.sleep(5)
    
    # Read any startup messages
    print("\nStartup messages:")
    while ser.in_waiting:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line:
            print(f"  <- {line}")
    
    # Test 1: Send COUNT command
    print("\n--- Test 1: Sending COUNT command ---")
    ser.write(b"COUNT\n")
    print("  -> Sent: COUNT")
    
    time.sleep(1)
    responses = []
    while ser.in_waiting:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line:
            print(f"  <- {line}")
            responses.append(line)
    
    # Test 2: Send ACTIVATE command
    print("\n--- Test 2: Sending ACTIVATE command ---")
    ser.write(b"ACTIVATE\n")
    print("  -> Sent: ACTIVATE")
    
    time.sleep(1)
    while ser.in_waiting:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line:
            print(f"  <- {line}")
    
    # Test 3: Try enrollment (will fail without finger, but shows if command works)
    print("\n--- Test 3: Sending ENROLL:99 command ---")
    print("  (This will wait for finger - you can try placing finger or just wait 10 seconds)")
    ser.write(b"ENROLL:99\n")
    print("  -> Sent: ENROLL:99")
    
    print("\nListening for responses (10 seconds)...")
    start = time.time()
    while time.time() - start < 10:
        if ser.in_waiting:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line:
                print(f"  <- {line}")
                try:
                    data = json.loads(line)
                    if data.get('type') == 'prompt':
                        print(f"     >> Prompt: {data.get('message')}")
                except:
                    pass
        time.sleep(0.1)
    
    # Send DEACTIVATE
    print("\n--- Test 4: Sending DEACTIVATE command ---")
    ser.write(b"DEACTIVATE\n")
    print("  -> Sent: DEACTIVATE")
    
    time.sleep(1)
    while ser.in_waiting:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line:
            print(f"  <- {line}")
    
    print("\n" + "="*50)
    print("Test complete!")
    print("="*50)

if __name__ == "__main__":
    ser = find_esp32_port()
    if ser:
        try:
            test_communication(ser)
        except KeyboardInterrupt:
            print("\n\nTest interrupted by user")
        finally:
            ser.close()
            print("\nSerial connection closed")
    else:
        print("\n✗ Could not connect to ESP32. Please check:")
        print("  1. ESP32 is connected to USB")
        print("  2. Arduino Serial Monitor is CLOSED")
        print("  3. No other program is using the COM port")
        print("  4. ESP32 has the fingerprint_to_python.ino code uploaded")
