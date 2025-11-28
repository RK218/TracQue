"""
List all available COM ports
"""

import serial.tools.list_ports

print("="*60)
print("Available COM Ports")
print("="*60)

ports = serial.tools.list_ports.comports()

if not ports:
    print("No COM ports found!")
    print("\nMake sure:")
    print("- ESP32 is connected via USB")
    print("- Drivers are installed")
else:
    for port in ports:
        print(f"\nPort: {port.device}")
        print(f"  Description: {port.description}")
        print(f"  Hardware ID: {port.hwid}")
        
        # Check if it's likely an ESP32
        if 'USB' in port.description or 'CP210' in port.hwid or 'CH340' in port.hwid:
            print(f"  >>> This is likely your ESP32! <<<")

print("\n" + "="*60)
print("Use the 'Port' value (e.g., COM3) when running the script")
print("="*60)
