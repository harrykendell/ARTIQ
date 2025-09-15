#!/usr/bin/env python3

import sys
from PyQt6.QtWidgets import QApplication, QLabel

if __name__ == "__main__":
    print("Creating QApplication...")
    app = QApplication(sys.argv)
    
    print("Creating QLabel...")
    label = QLabel("Hello World!")
    label.show()
    
    print("Starting event loop...")
    sys.exit(app.exec())