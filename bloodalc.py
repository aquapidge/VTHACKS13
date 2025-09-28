import tkinter as tk
from tkinter import ttk, messagebox
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
import json
import os
from datetime import datetime, timedelta
from PIL import Image, ImageTk  # put this at the top of your file

# -----------------------------
# Data models
# -----------------------------
@dataclass
class Profile:
    name: str
    age: int
    height_cm: float  # store height in cm
    sex: str          # 'male' or 'female'
    weight_kg: float  # store weight in kg
    eaten_recently: bool = False

@dataclass
class Drink:
    name: str
    volume_ml: float
    percent_abv: float  # e.g., 5 for 5%

@dataclass
class Consumed:
    drink_name: str
    quantity: int
    timestamp_iso: str  # ISO time when consumed (first sip)

# -----------------------------
# Persistence helpers
# -----------------------------
DATA_FILE = os.path.join(os.path.expanduser('~'), 'bloodalc_data.json')


def load_data() -> Dict[str, Any]:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {"profiles": [], "drinks": [], "consumed": []}
    return {"profiles": [], "drinks": [], "consumed": []}


def save_data(data: Dict[str, Any]) -> None:
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        messagebox.showerror("Save error", str(e))

# -----------------------------
# Alcohol math utilities
# -----------------------------
OZ_TO_ML = 29.5735295625
POUNDS_TO_KG = 0.45359237
INCH_TO_CM = 2.54
STANDARD_DRINK_GRAMS = 14.0  # US standard drink
ALCOHOL_DENSITY = 0.79  # g/ml per prompt


def ml_from_volume(value: float, unit: str) -> float:
    return value * OZ_TO_ML if unit == 'oz' else value


def cm_from_height(value: float, unit: str) -> float:
    return value * INCH_TO_CM if unit == 'in' else value


def kg_from_weight(value: float, unit: str) -> float:
    return value * POUNDS_TO_KG if unit == 'lb' else value


# Compute total alcohol (grams) and number of standard drinks

def total_alcohol_grams(consumed: List[Consumed], drinks: List[Drink]) -> float:
    drink_lookup = {d.name: d for d in drinks}
    total = 0.0
    for c in consumed:
        d = drink_lookup.get(c.drink_name)
        if not d:
            continue
        ethanol_ml = d.volume_ml * (d.percent_abv / 100.0)
        grams_per_unit = ethanol_ml * ALCOHOL_DENSITY
        total += grams_per_unit * c.quantity
    return total


def standard_drinks_from_grams(grams: float) -> float:
    return grams / STANDARD_DRINK_GRAMS if STANDARD_DRINK_GRAMS else 0.0


# -----------------------------
# BAC models from user-specified formulas
# All results reported in g/dL; clamp at 0.
# -----------------------------

def hours_since_first_sip(consumed: List[Consumed]) -> float:
    if not consumed:
        return 0.0
    times = [datetime.fromisoformat(c.timestamp_iso) for c in consumed]
    t0 = min(times)
    return max(0.0, (datetime.now() - t0).total_seconds() / 3600.0)


# A as defined by user: total volume (ml) * % * density / 10
# Note: We compute with overall total across consumed list

def ethanol_grams(consumed: List[Consumed], drinks: List[Drink]) -> float:
    # Total ethanol in grams
    return total_alcohol_grams(consumed, drinks)

def widmark_bac_from_grams(grams: float, W_kg: float, r: float, beta60: float, t_hours: float) -> float:
    # BAC g/dL using Widmark (metric): divide by body water in dL ≈ (W_kg * r * 10)
    if W_kg <= 0 or r <= 0:
        return 0.0
    bac = (grams / (W_kg * r * 10.0)) - (beta60 * t_hours)
    return max(0.0, bac)


def matthews_miller(consumed: List[Consumed], drinks: List[Drink], profile: Profile, beta60: float, t_hours: float) -> float:
    grams = ethanol_grams(consumed, drinks)
    c_std = standard_drinks_from_grams(grams)
    GC = 9.0 if profile.sex.lower().startswith('f') else 7.5
    w_lb = profile.weight_kg / POUNDS_TO_KG
    bac = ((c_std / 2.0) * (GC / w_lb)) - (beta60 * t_hours)
    return max(0.0, bac)

def forrest(consumed: List[Consumed], drinks: List[Drink], profile: Profile, beta60: float, t_hours: float) -> float:
    # A is grams/10, per definition: total ethanol grams ÷ 10
    grams = ethanol_grams(consumed, drinks)
    A = grams / 10.0

    W = profile.weight_kg
    H_m = profile.height_cm / 100.0
    BMI = (W / (H_m ** 2)) if H_m > 0 else 0.0

    # rf = % body fat from BMI
    if profile.sex.lower().startswith('f'):
        rf_pct = (1.371 * BMI) - 3.467
    else:
        rf_pct = (1.340 * BMI) - 12.469

    # Clamp to avoid absurd or negative values
    rf_pct = max(0.0, min(60.0, rf_pct))

    # Lean body mass (kg) → TBW in liters
    lean_mass_kg = W * (1.0 - rf_pct / 100.0)
    tbw_L = 0.73 * max(0.0, lean_mass_kg)

    if tbw_L <= 0:
        return 0.0

    # A is g/10 → divide by L → g/dL
    bac = (A / tbw_L) - (beta60 * t_hours)
    return max(0.0, bac)

def lewis(consumed: List[Consumed], drinks: List[Drink], profile: Profile, beta60: float, t_hours: float) -> float:
    grams = ethanol_grams(consumed, drinks)
    W = profile.weight_kg
    r = 0.68 if profile.sex.lower().startswith('f') else 0.76
    return widmark_bac_from_grams(grams, W, r, beta60, t_hours)

def nhtsa(consumed: List[Consumed], drinks: List[Drink], profile: Profile, beta60: float, t_hours: float) -> float:
    grams = ethanol_grams(consumed, drinks)
    W = profile.weight_kg
    # Use TBW fraction similar to NHTSA simplification
    r = 0.49 if profile.sex.lower().startswith('f') else 0.58
    return widmark_bac_from_grams(grams, W, r, beta60, t_hours)

# Absorption window & sobriety estimate

def absorption_window(eaten_recently: bool) -> timedelta:
    # rough heuristic, not medical advice
    # No food: 30–90 min; With food: 90–180 min
    return timedelta(minutes=90 if not eaten_recently else 150)


def estimate_sober_time(current_bac: float, beta60: float) -> Optional[datetime]:
    if current_bac <= 0 or beta60 <= 0:
        return None
    hours_to_zero = current_bac / beta60
    return datetime.now() + timedelta(hours=hours_to_zero)

# -----------------------------
# Main Application (Tkinter)
# -----------------------------
class BloodAlcCalcApp(tk.Tk):
    def __init__(self):
        super().__init__()
        # Use your logo as the app window/taskbar icon
        logo_icon = tk.PhotoImage(file="bloodalccalclogo.png")
        self.iconphoto(False, logo_icon)
        self.logo_icon = logo_icon  # keep a reference
        self.title("BloodAlcCalc")
        self.geometry("980x680")
        self.minsize(900, 600)

        # State
        data = load_data()
        self.profiles: List[Profile] = [Profile(**p) for p in data.get("profiles", [])]
        self.drinks: List[Drink] = [Drink(**d) for d in data.get("drinks", [])]
        self.consumed: List[Consumed] = [Consumed(**c) for c in data.get("consumed", [])]

        self.selected_profile: Optional[Profile] = None
        self.beta60 = tk.DoubleVar(value=0.017)

        # Header
        header = ttk.Frame(self)
        header.pack(fill=tk.X, padx=16, pady=12)

        # Load and resize logo
        img = Image.open("bloodalccalclogo.png").resize((200, 60))  # tweak size as needed
        logo = ImageTk.PhotoImage(img)

        ttk.Label(header, image=logo).pack(side=tk.LEFT, padx=8)

        self.header_logo = logo  # keep a reference so image doesn’t vanish

        # Navigation buttons
        nav = ttk.Frame(self)
        nav.pack(fill=tk.X, padx=16, pady=8)
        ttk.Button(nav, text="Profile", command=self.show_profile).pack(side=tk.LEFT, padx=4)
        ttk.Button(nav, text="Drinks", command=self.show_drinks).pack(side=tk.LEFT, padx=4)
        ttk.Button(nav, text="Calculate", command=self.show_calculate).pack(side=tk.LEFT, padx=4)
        ttk.Button(nav, text="Info", command=self.show_info).pack(side=tk.LEFT, padx=4)

        # Content frame
        self.container = ttk.Frame(self)
        self.container.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)

        self.frames: Dict[str, tk.Frame] = {}
        for F in (ProfileFrame, DrinksFrame, CalculateFrame, InfoFrame):
            page_name = F.__name__
            frame = F(parent=self.container, controller=self)
            self.frames[page_name] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        self.show_profile()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def show_profile(self):
        self._show_frame("ProfileFrame")

    def show_drinks(self):
        self._show_frame("DrinksFrame")

    def show_calculate(self):
        self._show_frame("CalculateFrame")

    def show_info(self):
        self._show_frame("InfoFrame")

    def _show_frame(self, name: str):
        frame = self.frames[name]
        frame.event_generate("<<ShowFrame>>")
        frame.tkraise()

    def on_close(self):
        # Persist data
        data = {
            "profiles": [asdict(p) for p in self.profiles],
            "drinks": [asdict(d) for d in self.drinks],
            "consumed": [asdict(c) for c in self.consumed],
        }
        save_data(data)
        self.destroy()


# -----------------------------
# Profile UI
# -----------------------------
class ProfileFrame(ttk.Frame):
    def __init__(self, parent, controller: BloodAlcCalcApp):
        super().__init__(parent)
        self.controller = controller

        # Form
        frm = ttk.LabelFrame(self, text="Create / Edit Profile")
        frm.pack(fill=tk.X, padx=8, pady=8)

        self.name = tk.StringVar()
        self.age = tk.IntVar()
        self.height = tk.DoubleVar()
        self.height_unit = tk.StringVar(value='cm')
        self.sex = tk.StringVar(value='male')
        self.weight = tk.DoubleVar()
        self.weight_unit = tk.StringVar(value='kg')
        self.eaten_recently = tk.BooleanVar(value=False)

        # Layout
        r = 0
        ttk.Label(frm, text="Name").grid(row=r, column=0, sticky='w', padx=6, pady=6)
        ttk.Entry(frm, textvariable=self.name, width=24).grid(row=r, column=1, padx=6, pady=6)

        r += 1
        ttk.Label(frm, text="Age (years)").grid(row=r, column=0, sticky='w', padx=6, pady=6)
        ttk.Entry(frm, textvariable=self.age, width=10).grid(row=r, column=1, sticky='w', padx=6, pady=6)

        r += 1
        ttk.Label(frm, text="Height").grid(row=r, column=0, sticky='w', padx=6, pady=6)
        hrow = ttk.Frame(frm)
        hrow.grid(row=r, column=1, sticky='w')
        ttk.Entry(hrow, textvariable=self.height, width=10).pack(side=tk.LEFT)
        ttk.Combobox(hrow, values=['cm', 'in'], width=5, state='readonly', textvariable=self.height_unit).pack(side=tk.LEFT, padx=4)

        r += 1
        ttk.Label(frm, text="Sex").grid(row=r, column=0, sticky='w', padx=6, pady=6)
        ttk.Combobox(frm, values=['male', 'female'], state='readonly', textvariable=self.sex, width=10).grid(row=r, column=1, sticky='w', padx=6, pady=6)

        r += 1
        ttk.Label(frm, text="Weight").grid(row=r, column=0, sticky='w', padx=6, pady=6)
        wrow = ttk.Frame(frm)
        wrow.grid(row=r, column=1, sticky='w')
        ttk.Entry(wrow, textvariable=self.weight, width=10).pack(side=tk.LEFT)
        ttk.Combobox(wrow, values=['kg', 'lb'], width=5, state='readonly', textvariable=self.weight_unit).pack(side=tk.LEFT, padx=4)

        r += 1
        ttk.Checkbutton(frm, text="Eaten recently (slows absorption)", variable=self.eaten_recently).grid(row=r, column=0, columnspan=2, sticky='w', padx=6, pady=6)

        # Buttons
        btns = ttk.Frame(self)
        btns.pack(fill=tk.X, padx=8, pady=8)
        ttk.Button(btns, text="Add / Update Profile", command=self.add_profile).pack(side=tk.LEFT)
        ttk.Button(btns, text="Delete Selected", command=self.delete_profile).pack(side=tk.LEFT, padx=6)

        # Profiles list
        self.tree = ttk.Treeview(
            self,
            columns=("name", "age", "height", "sex", "weight", "eaten"),
            show='headings',
            height=10
)

        # Define headers
        self.tree.heading("name", text="Name")
        self.tree.heading("age", text="Age")
        self.tree.heading("height", text="Height (cm)")
        self.tree.heading("sex", text="Sex")
        self.tree.heading("weight", text="Weight (kg)")
        self.tree.heading("eaten", text="Ate")

        # Set column widths
        self.tree.column("name", width=120, anchor="center")
        self.tree.column("age", width=60, anchor="center")
        self.tree.column("height", width=100, anchor="center")
        self.tree.column("sex", width=80, anchor="center")
        self.tree.column("weight", width=100, anchor="center")
        self.tree.column("eaten", width=60, anchor="center")

        self.tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.tree.bind('<<TreeviewSelect>>', self.on_select)

    def refresh(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for p in self.controller.profiles:
            self.tree.insert(
                '',
                tk.END,
                iid=p.name,
                values=(p.name, p.age, f"{p.height_cm:.1f}", p.sex, f"{p.weight_kg:.1f}", 'Yes' if p.eaten_recently else 'No')
        )

    def add_profile(self):
        try:
            name = self.name.get().strip()
            if not name:
                raise ValueError("Name required")
            age = int(self.age.get())
            height_cm = cm_from_height(float(self.height.get()), self.height_unit.get())
            weight_kg = kg_from_weight(float(self.weight.get()), self.weight_unit.get())
            sex = self.sex.get()
            eaten = bool(self.eaten_recently.get())
            # Replace or add
            existing = next((p for p in self.controller.profiles if p.name == name), None)
            new_p = Profile(name=name, age=age, height_cm=height_cm, sex=sex, weight_kg=weight_kg, eaten_recently=eaten)
            if existing:
                idx = self.controller.profiles.index(existing)
                self.controller.profiles[idx] = new_p
            else:
                self.controller.profiles.append(new_p)
            self.refresh()
        except Exception as e:
            messagebox.showerror("Invalid input", str(e))

    def delete_profile(self):
        sel = self.tree.selection()
        if not sel:
            return
        name = sel[0]
        self.controller.profiles = [p for p in self.controller.profiles if p.name != name]
        if self.controller.selected_profile and self.controller.selected_profile.name == name:
            self.controller.selected_profile = None
        self.refresh()

    def on_select(self, _):
        sel = self.tree.selection()
        if not sel:
            return
        name = sel[0]
        p = next((p for p in self.controller.profiles if p.name == name), None)
        self.controller.selected_profile = p


# -----------------------------
# Drinks UI
# -----------------------------
class DrinksFrame(ttk.Frame):
    def __init__(self, parent, controller: BloodAlcCalcApp):
        super().__init__(parent)
        self.controller = controller

        # Add drink form
        frm = ttk.LabelFrame(self, text="Add / Edit Drink")
        frm.pack(fill=tk.X, padx=8, pady=8)

        self.drink_name = tk.StringVar()
        self.volume = tk.DoubleVar()
        self.vol_unit = tk.StringVar(value='oz')
        self.abv = tk.DoubleVar()

        r = 0
        ttk.Label(frm, text="Name").grid(row=r, column=0, sticky='w', padx=6, pady=6)
        ttk.Entry(frm, textvariable=self.drink_name, width=24).grid(row=r, column=1, padx=6, pady=6)

        r += 1
        ttk.Label(frm, text="Volume").grid(row=r, column=0, sticky='w', padx=6, pady=6)
        vrow = ttk.Frame(frm)
        vrow.grid(row=r, column=1, sticky='w')
        ttk.Entry(vrow, textvariable=self.volume, width=10).pack(side=tk.LEFT)
        ttk.Combobox(vrow, values=['oz', 'ml'], state='readonly', width=5, textvariable=self.vol_unit).pack(side=tk.LEFT, padx=4)

        r += 1
        ttk.Label(frm, text="Alcohol % ABV").grid(row=r, column=0, sticky='w', padx=6, pady=6)
        ttk.Entry(frm, textvariable=self.abv, width=10).grid(row=r, column=1, sticky='w', padx=6, pady=6)

        btns = ttk.Frame(self)
        btns.pack(fill=tk.X, padx=8, pady=4)
        ttk.Button(btns, text="Add / Update", command=self.add_drink).pack(side=tk.LEFT)
        ttk.Button(btns, text="Delete Selected", command=self.delete_drink).pack(side=tk.LEFT, padx=6)

        # Drinks list
        self.tree = ttk.Treeview(self, columns=("Drink Name", "volume", "abv"), show='headings', height=12)
        self.tree.heading("Drink Name", text="Drink Name")
        self.tree.heading("volume", text="Volume (ml)")
        self.tree.heading("abv", text="ABV %")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.tree.bind('<<TreeviewSelect>>', self.on_select)

        self.bind('<<ShowFrame>>', lambda e: self.refresh())

    def refresh(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for d in self.controller.drinks:
            self.tree.insert('', tk.END, iid=d.name, values=(d.name, f"{d.volume_ml:.0f}", f"{d.percent_abv:.2f}"))

    def add_drink(self):
        try:
            name = self.drink_name.get().strip()
            if not name:
                raise ValueError("Name required")
            volume_ml = ml_from_volume(float(self.volume.get()), self.vol_unit.get())
            abv = float(self.abv.get())
            existing = next((d for d in self.controller.drinks if d.name == name), None)
            nd = Drink(name=name, volume_ml=volume_ml, percent_abv=abv)
            if existing:
                idx = self.controller.drinks.index(existing)
                self.controller.drinks[idx] = nd
            else:
                self.controller.drinks.append(nd)
            self.refresh()
        except Exception as e:
            messagebox.showerror("Invalid input", str(e))

    def delete_drink(self):
        sel = self.tree.selection()
        if not sel:
            return
        name = sel[0]
        self.controller.drinks = [d for d in self.controller.drinks if d.name != name]
        self.refresh()

    def on_select(self, _):
        sel = self.tree.selection()
        if not sel:
            return
        name = sel[0]
        d = next((d for d in self.controller.drinks if d.name == name), None)
        if d:
            self.drink_name.set(d.name)
            self.volume.set(d.volume_ml / OZ_TO_ML)
            self.vol_unit.set('oz')
            self.abv.set(d.percent_abv)


# -----------------------------
# Calculate UI
# -----------------------------
class CalculateFrame(ttk.Frame):
    def __init__(self, parent, controller: BloodAlcCalcApp):
        super().__init__(parent)
        self.controller = controller

        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=8, pady=8)

        ttk.Label(top, text="Profile:").pack(side=tk.LEFT)
        self.profile_cb = ttk.Combobox(top, state='readonly')
        self.profile_cb.pack(side=tk.LEFT, padx=6)
        self.profile_cb.bind('<<ComboboxSelected>>', lambda e: self.on_profile_change())

        ttk.Label(top, text="β60 (g/dL per hour):").pack(side=tk.LEFT, padx=12)
        self.beta_entry = ttk.Entry(top, width=8, textvariable=self.controller.beta60)
        self.beta_entry.pack(side=tk.LEFT)

        ttk.Button(top, text="Clear Consumed", command=self.clear_consumed).pack(side=tk.RIGHT)

        # Add consumed drink
        add = ttk.LabelFrame(self, text="Log drink consumption")
        add.pack(fill=tk.X, padx=8, pady=8)

        self.drink_cb = ttk.Combobox(add, state='readonly')
        self.drink_cb.pack(side=tk.LEFT, padx=4)
        self.qty_var = tk.IntVar(value=1)
        ttk.Spinbox(add, from_=1, to=20, textvariable=self.qty_var, width=5).pack(side=tk.LEFT, padx=4)
        ttk.Button(add, text="Add (now)", command=self.add_consumed_now).pack(side=tk.LEFT, padx=4)

        # Custom time
        self.custom_time_var = tk.StringVar()
        ttk.Entry(add, textvariable=self.custom_time_var, width=20).pack(side=tk.LEFT, padx=4)
        ttk.Label(add, text="YYYY-MM-DD HH:MM").pack(side=tk.LEFT)
        ttk.Button(add, text="Add (custom time)", command=self.add_consumed_custom).pack(side=tk.LEFT, padx=4)

        # Consumed list
        self.tree = ttk.Treeview(self, columns=("drink", "qty", "time"), show='headings', height=10)
        for col, txt in zip(self.tree["columns"], ["Drink", "Qty", "Time"]):
            self.tree.heading(col, text=txt)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        rm_frame = ttk.Frame(self)
        rm_frame.pack(fill=tk.X, padx=8)
        ttk.Button(rm_frame, text="Remove Selected", command=self.remove_selected).pack(side=tk.LEFT)

        # Calculate button and output
        ttk.Button(self, text="Calculate BAC", command=self.calculate).pack(pady=8)

        self.output = tk.Text(self, height=12)
        self.output.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.output.configure(state='disabled')

        self.bind('<<ShowFrame>>', lambda e: self.refresh())

    def refresh(self):
        self.profile_cb['values'] = [p.name for p in self.controller.profiles]
        if self.controller.selected_profile:
            self.profile_cb.set(self.controller.selected_profile.name)
        else:
            self.profile_cb.set('')
        self.drink_cb['values'] = [d.name for d in self.controller.drinks]
        self.refresh_consumed_tree()

    def refresh_consumed_tree(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for idx, c in enumerate(self.controller.consumed):
            self.tree.insert('', tk.END, iid=str(idx), values=(c.drink_name, c.quantity, c.timestamp_iso.replace('T', ' ')))

    def on_profile_change(self):
        name = self.profile_cb.get()
        self.controller.selected_profile = next((p for p in self.controller.profiles if p.name == name), None)

    def add_consumed_now(self):
        self._add_consumed(timestamp=datetime.now())

    def add_consumed_custom(self):
        try:
            ts = datetime.strptime(self.custom_time_var.get().strip(), '%Y-%m-%d %H:%M')
        except Exception:
            messagebox.showerror("Invalid time", "Use format YYYY-MM-DD HH:MM")
            return
        self._add_consumed(timestamp=ts)

    def _add_consumed(self, timestamp: datetime):
        drink_name = self.drink_cb.get()
        if not drink_name:
            messagebox.showerror("Missing", "Select a drink")
            return
        qty = int(self.qty_var.get())
        self.controller.consumed.append(Consumed(drink_name=drink_name, quantity=qty, timestamp_iso=timestamp.isoformat(timespec='minutes')))
        self.refresh_consumed_tree()

    def remove_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(self.controller.consumed):
            del self.controller.consumed[idx]
        self.refresh_consumed_tree()

    def clear_consumed(self):
        if messagebox.askyesno("Confirm", "Clear all consumed drinks?"):
            self.controller.consumed.clear()
            self.refresh_consumed_tree()

    def calculate(self):
        p = self.controller.selected_profile
        if not p:
            messagebox.showerror("Profile", "Select a profile")
            return
        if not self.controller.consumed:
            messagebox.showerror("Consumed", "Log at least one drink")
            return
        beta = float(self.controller.beta60.get())
        t_hours = hours_since_first_sip(self.controller.consumed)

        # Use the profile's eaten flag unless user wants to override in Profile screen
        ate = p.eaten_recently
        absorp_done_at = None
        if self.controller.consumed:
            first_time = min(datetime.fromisoformat(c.timestamp_iso) for c in self.controller.consumed)
            absorp_done_at = first_time + absorption_window(ate)

        # Compute BAC by models
        mm = matthews_miller(self.controller.consumed, self.controller.drinks, p, beta, t_hours)
        fr = forrest(self.controller.consumed, self.controller.drinks, p, beta, t_hours)
        lw = lewis(self.controller.consumed, self.controller.drinks, p, beta, t_hours)
        nh = nhtsa(self.controller.consumed, self.controller.drinks, p, beta, t_hours)

        # Aggregate (simple mean) for overall estimate
        values = [mm, fr, lw, nh]
        current_bac = max(0.0, sum(values) / len(values))

        # Sober time estimate
        sober_time = estimate_sober_time(current_bac, beta)

        grams = total_alcohol_grams(self.controller.consumed, self.controller.drinks)
        std_drinks = standard_drinks_from_grams(grams)

        # Output
        lines = []
        lines.append(f"Profile: {p.name} (age {p.age}, {p.sex}, {p.weight_kg:.1f} kg, {p.height_cm:.0f} cm)")
        lines.append(f"Logged drinks: {len(self.controller.consumed)} entries; total alcohol ≈ {grams:.1f} g (~{std_drinks:.2f} US standard drinks)")
        lines.append("")
        lines.append("Models (g/dL):")
        lines.append(f"  Matthews & Miller (1979): {mm:.4f}")
        lines.append(f"  Forrest (1986):          {fr:.4f}")
        lines.append(f"  Lewis (1986):            {lw:.4f}")
        lines.append(f"  NHTSA (1994):            {nh:.4f}")
        lines.append("")
        lines.append(f"Estimated BAC (mean): {current_bac:.4f} g/dL")
        lines.append(f"First sip: {min(datetime.fromisoformat(c.timestamp_iso) for c in self.controller.consumed):%Y-%m-%d %H:%M}")
        lines.append(f"Hours since first sip: {t_hours:.2f} h")
        if absorp_done_at:
            lines.append(f"Estimated absorption complete by: {absorp_done_at:%Y-%m-%d %H:%M} ({'ate' if ate else 'no food'})")
        if sober_time:
            lines.append(f"Estimated time to BAC 0.0000: {sober_time:%Y-%m-%d %H:%M}")
        else:
            lines.append("Estimated time to BAC 0.0000: N/A")
        lines.append("")
        lines.append("Disclaimer: Estimates only. Do NOT drive after drinking. This tool is not medical or legal advice.")

        self.output.configure(state='normal')
        self.output.delete('1.0', tk.END)
        self.output.insert(tk.END, "\n".join(lines))
        self.output.configure(state='disabled')


# -----------------------------
# Info UI
# -----------------------------
class InfoFrame(ttk.Frame):
    def __init__(self, parent, controller: BloodAlcCalcApp):
        super().__init__(parent)
        txt = tk.Text(self, wrap='word')
        txt.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        txt.insert(tk.END, (
    "Models used:\n\n"
    "• Matthews & Miller (1979): BAC = [(c/2) * (GC/w)] - (β60*t)\n"
    "    c: standard drinks (US 14 g per drink). GC: gender constant (9.0 female, 7.5 male).\n"
    "    w: weight (lb). β60: metabolism per hour (g/dL). t: hours since first sip.\n\n"
    "• Forrest (1986): BAC = A/TBW − (β60*t)\n"
    "    BMI = W/H² (kg, m). For males: %fat = 1.340*BMI − 12.469;\n"
    "    females: %fat = 1.371*BMI − 3.467.\n"
    "    Lean mass = W × (1 − %fat/100).\n"
    "    TBW ≈ 0.73 × Lean mass (liters).\n\n"
    "• Lewis (1986): BAC = A/(W*rl) - (β60*t), where rl = 0.76 (men), 0.68 (women).\n\n"
    "• NHTSA (1994): BAC = (A*0.806)/(W*TBW*1000)*100 - (β60*t), TBW = 0.58 (men), 0.49 (women).\n\n"
    "Units: A = total volume (ml) × %ABV × density (0.79 g/ml) ÷ 10.\n"
    "W in kg, h in cm, y in years.\n\n"
    "Important health info: Alcohol affects people differently. Eating can delay absorption.\n"
    "Never drink and drive. Use this only as a rough estimate, not for safety-critical decisions.\n"
))
        txt.configure(state='disabled')


# -----------------------------
# Run
# -----------------------------
if __name__ == '__main__':
    app = BloodAlcCalcApp()
    app.mainloop()
