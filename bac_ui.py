import tkinter as tk
from tkinter import messagebox
from datetime import datetime
from bac_tracker import Person, BACSession  # re-use your logic from bac_tracker.py

class BACApp:
    def __init__(self, root):
        self.root = root
        self.root.title("BAC Tracker")

        # Person setup
        self.person = None
        self.session = None

        # Input fields
        tk.Label(root, text="Weight (kg):").grid(row=0, column=0, sticky="w")
        self.weight_entry = tk.Entry(root)
        self.weight_entry.grid(row=0, column=1)

        tk.Label(root, text="Sex (male/female):").grid(row=1, column=0, sticky="w")
        self.sex_entry = tk.Entry(root)
        self.sex_entry.grid(row=1, column=1)

        tk.Label(root, text="Age:").grid(row=2, column=0, sticky="w")
        self.age_entry = tk.Entry(root)
        self.age_entry.grid(row=2, column=1)

        self.eaten_var = tk.BooleanVar()
        tk.Checkbutton(root, text="Eaten recently", variable=self.eaten_var).grid(row=3, column=0, columnspan=2)

        tk.Button(root, text="Start Session", command=self.start_session).grid(row=4, column=0, columnspan=2, pady=5)

        # Drink input
        tk.Label(root, text="Drink (oz):").grid(row=5, column=0, sticky="w")
        self.oz_entry = tk.Entry(root)
        self.oz_entry.grid(row=5, column=1)

        tk.Label(root, text="Alcohol %:").grid(row=6, column=0, sticky="w")
        self.pct_entry = tk.Entry(root)
        self.pct_entry.grid(row=6, column=1)

        tk.Button(root, text="Add Drink", command=self.add_drink).grid(row=7, column=0, columnspan=2, pady=5)

        # Output area
        self.output = tk.Text(root, height=10, width=40, state="disabled")
        self.output.grid(row=8, column=0, columnspan=2, pady=10)

        tk.Button(root, text="Show BAC", command=self.show_bac).grid(row=9, column=0, columnspan=2)

    def start_session(self):
        try:
            weight = float(self.weight_entry.get())
            sex = self.sex_entry.get().strip().lower()
            age = int(self.age_entry.get())
            eaten = self.eaten_var.get()
            self.person = Person(weight_kg=weight, sex=sex, age=age, eaten=eaten)
            self.session = BACSession(self.person)
            self.log("Session started!")
        except ValueError:
            messagebox.showerror("Error", "Please enter valid info.")

    def add_drink(self):
        if not self.session:
            messagebox.showerror("Error", "Start a session first.")
            return
        try:
            oz = float(self.oz_entry.get())
            pct = float(self.pct_entry.get())
            self.session.add_drink(oz, pct, datetime.now())
            self.log(f"Added: {oz} oz @ {pct}%")
        except ValueError:
            messagebox.showerror("Error", "Enter valid numbers for drink.")

    def show_bac(self):
        if not self.session:
            messagebox.showerror("Error", "Start a session first.")
            return
        result = self.session.summary()
        self.log(result)

    def log(self, msg):
        self.output.config(state="normal")
        self.output.insert(tk.END, msg + "\n")
        self.output.config(state="disabled")

if __name__ == "__main__":
    root = tk.Tk()
    app = BACApp(root)
    root.mainloop()