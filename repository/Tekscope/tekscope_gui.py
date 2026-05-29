import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
 
from mso24 import MSO24
import subprocess
import shutil
 
DEFAULT_IP = "192.168.0.5"
 
 
class MSO24GUI:
    def __init__(self, root):
 
        self.root = root
        self.root.title("Tektronix MSO24 Control")
 
        self.scope = None
        self.save_dir = Path.home() / "Desktop"
 
        # =====================================================
        # Connection
        # =====================================================
 
        tk.Label(root, text="Scope IP").grid(row=0, column=0, padx=5, pady=5)
 
        self.ip_entry = tk.Entry(root, width=20)
 
        self.ip_entry.insert(0, DEFAULT_IP)
 
        self.ip_entry.grid(row=0, column=1, padx=5, pady=5)
 
        tk.Button(root, text="Connect", command=self.connect).grid(
            row=0, column=2, sticky="ew"
        )
        tk.Button(root, text="Open Scope Screen", command=self.open_vnc).grid(
            row=0, column=3, sticky="ew"
        )
        tk.Button(root, text="Choose Save Folder", command=self.choose_folder).grid(
            row=1, column=0, columnspan=3, sticky="ew"
        )
 
        # =====================================================
        # File Operations
        # =====================================================
 
        tk.Button(root, text="Screenshot", command=self.screenshot).grid(
            row=2, column=0, sticky="ew"
        )
 
        tk.Button(root, text="CH1 CSV", command=lambda: self.save_channel("CH1")).grid(
            row=2, column=1, sticky="ew"
        )
 
        tk.Button(root, text="CH2 CSV", command=lambda: self.save_channel("CH2")).grid(
            row=2, column=2, sticky="ew"
        )
 
        tk.Button(root, text="CH3 CSV", command=lambda: self.save_channel("CH3")).grid(
            row=3, column=1, sticky="ew"
        )
 
        tk.Button(root, text="CH4 CSV", command=lambda: self.save_channel("CH4")).grid(
            row=3, column=2, sticky="ew"
        )
 
        tk.Button(root, text="All Channels", command=self.save_all_channels).grid(
            row=3, column=0, sticky="ew"
        )
 
        tk.Button(root, text="Save Setup", command=self.save_setup).grid(
            row=4, column=0, columnspan=3, sticky="ew"
        )
 
        # =====================================================
        # Scope Control
        # =====================================================
 
        tk.Button(root, text="Run", command=self.run_scope).grid(
            row=5, column=0, sticky="ew"
        )
 
        tk.Button(root, text="Stop", command=self.stop_scope).grid(
            row=5, column=1, sticky="ew"
        )
 
        tk.Button(root, text="Single", command=self.single_scope).grid(
            row=5, column=2, sticky="ew"
        )
 
        tk.Button(root, text="Autoset", command=self.autoset_scope).grid(
            row=6, column=0, columnspan=3, sticky="ew"
        )
 
        # =====================================================
        # Experiment Capture
        # =====================================================
 
        tk.Button(
            root, text="Capture Experiment", command=self.capture_experiment
        ).grid(row=7, column=0, columnspan=3, sticky="ew")
 
        # =====================================================
        # Log Window
        # =====================================================
 
        self.log = tk.Text(root, height=20, width=90)
 
        self.log.grid(row=8, column=0, columnspan=3, padx=5, pady=5)
 
    # =====================================================
    # Helpers
    # =====================================================
    def capture_experiment(self):
 
        try:
            self.write_log("Capturing...")
 
            self.scope.screenshot()
 
            self.scope.save_all_channels()
 
            self.scope.save_setup()
 
            self.write_log("Capture complete.")
 
        except Exception as e:
            self.write_log(str(e))
 
    def open_vnc(self):
 
        try:
            viewer = None
 
            for candidate in [
                "vncviewer",  # TigerVNC
                "xtigervncviewer",
                "gvncviewer",  # Vinagre/GNOME
                "remmina",
            ]:
                path = shutil.which(candidate)
 
                if path:
                    viewer = candidate
                    break
 
            if viewer is None:
                self.write_log("No VNC viewer found.")
 
                self.write_log("Install TigerVNC:")
 
                self.write_log("sudo apt install tigervnc-viewer")
 
                return
 
            ip = self.ip_entry.get()
 
            if viewer == "remmina":
                subprocess.Popen(["remmina", "-c", f"vnc://{ip}"])
 
            else:
                subprocess.Popen([viewer, ip])
 
            self.write_log(f"Opening VNC: {ip}")
 
        except Exception as e:
            self.write_log(f"VNC error: {e}")
 
    def write_log(self, text):
 
        self.log.insert(tk.END, str(text) + "\n")
 
        self.log.see(tk.END)
 
    def ensure_connected(self):
 
        if self.scope is None:
            raise RuntimeError("Not connected to scope.")
 
    # =====================================================
    # Connection
    # =====================================================
 
    def connect(self):
 
        try:
            self.scope = MSO24(self.ip_entry.get(), save_dir=self.save_dir)
 
            idn = self.scope.connect()
 
            self.write_log("Connected:")
            self.write_log(idn)
 
        except Exception as e:
            messagebox.showerror("Connection Error", str(e))
 
    def choose_folder(self):
 
        folder = filedialog.askdirectory()
 
        if folder:
            self.save_dir = Path(folder)
 
            if self.scope:
                self.scope.save_dir = self.save_dir
 
            self.write_log(f"Save folder: {self.save_dir}")
 
    # =====================================================
    # File Operations
    # =====================================================
 
    def screenshot(self):
 
        try:
            self.ensure_connected()
 
            outfile = self.scope.screenshot()
 
            self.write_log(f"Screenshot saved:\n{outfile}")
 
        except Exception as e:
            self.write_log(e)
 
    def save_channel(self, channel):
 
        try:
            self.ensure_connected()
 
            outfile = self.scope.save_channel_csv(channel)
 
            self.write_log(f"Saved {channel}:\n{outfile}")
 
        except Exception as e:
            self.write_log(e)
 
    def save_all_channels(self):
 
        try:
            self.ensure_connected()
 
            files = self.scope.save_all_channels()
 
            for f in files:
                self.write_log(f"Saved:\n{f}")
 
        except Exception as e:
            self.write_log(e)
 
    def save_setup(self):
 
        try:
            self.ensure_connected()
 
            outfile = self.scope.save_setup()
 
            self.write_log(f"Setup saved:\n{outfile}")
 
        except Exception as e:
            self.write_log(e)
 
    # =====================================================
    # Scope Controls
    # =====================================================
 
    def run_scope(self):
 
        try:
            self.ensure_connected()
 
            self.scope.run()
 
            self.write_log("RUN")
 
        except Exception as e:
            self.write_log(e)
 
    def stop_scope(self):
 
        try:
            self.ensure_connected()
 
            self.scope.stop()
 
            self.write_log("STOP")
 
        except Exception as e:
            self.write_log(e)
 
    def single_scope(self):
 
        try:
            self.ensure_connected()
 
            self.scope.single()
 
            self.write_log("SINGLE")
 
        except Exception as e:
            self.write_log(e)
 
    def autoset_scope(self):
 
        try:
            self.ensure_connected()
 
            self.scope.autoset()
 
            self.write_log("AUTOSET")
 
        except Exception as e:
            self.write_log(e)
 
    # =====================================================
    # Experiment
    # =====================================================
 
    def capture_experiment(self):
 
        try:
            self.ensure_connected()
 
            self.write_log("Capturing experiment...")
 
            self.screenshot()
 
            self.save_all_channels()
 
            self.save_setup()
 
            self.write_log("Experiment capture complete.")
 
        except Exception as e:
            self.write_log(e)
 
 
if __name__ == "__main__":
    root = tk.Tk()
 
    app = MSO24GUI(root)
 
    root.mainloop()