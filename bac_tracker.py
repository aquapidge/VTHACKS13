#!/usr/bin/env python3
"""
bac_tracker.py

Simple BAC tracker (Widmark-based, per-drink absorption approximation).
Run as a script for an interactive CLI, or import and use the BACSession class.
"""
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime, timedelta
import math

# ---------- Helpers & constants ----------
ML_PER_OUNCE = 29.5735
ALCOHOL_DENSITY_G_PER_ML = 0.789  # g/ml
DEFAULT_BETA = 0.015  # % BAC eliminated per hour (typical average)

SEX_R = {"male": 0.68, "female": 0.55}  # Widmark r-factors (common choices)

def grams_alcohol(ounces: float, alc_percent: float) -> float:
    """Return grams of alcohol in a drink (ounces, percent as 0-100)."""
    ml = ounces * ML_PER_OUNCE
    alc_ml = ml * (alc_percent / 100.0)
    return alc_ml * ALCOHOL_DENSITY_G_PER_ML

# ---------- Data classes ----------
@dataclass
class Drink:
    ounces: float
    alc_percent: float  # 0-100
    time: datetime = field(default_factory=datetime.now)
    # absorption_time in minutes (varies with food)
    absorption_time_min: float = 40.0

    def grams(self) -> float:
        return grams_alcohol(self.ounces, self.alc_percent)

@dataclass
class Person:
    weight_kg: float
    sex: str  # "male" or "female"
    age: int
    eaten: bool = False
    custom_r: Optional[float] = None
    custom_beta: Optional[float] = None

    def r(self) -> float:
        if self.custom_r is not None:
            return self.custom_r
        return SEX_R.get(self.sex.lower(), 0.68)

    def beta(self) -> float:
        """Elimination rate (% BAC per hour). Adjust slightly with age."""
        base = self.custom_beta if self.custom_beta is not None else DEFAULT_BETA
        # small adjustment: older age -> slightly lower metabolism (approx)
        if self.age <= 30:
            return base
        # reduce metabolism by 0.2% per year over 30 (very rough, small effect)
        factor = 1.0 - min(0.25, 0.002 * (self.age - 30))
        return base * factor

# ---------- Session / Calculator ----------
class BACSession:
    def __init__(self, person: Person):
        self.person = person
        self.drinks: List[Drink] = []

    def add_drink(self, ounces: float, alc_percent: float, time: Optional[datetime] = None):
        t = time or datetime.now()
        # adjust absorption_time if eaten
        absorption = 40.0  # default min
        if self.person.eaten:
            absorption *= 1.5  # food slows absorption (approx)
        d = Drink(ounces=ounces, alc_percent=alc_percent, time=t, absorption_time_min=absorption)
        self.drinks.append(d)
        return d

    def _contribution_from_drink(self, drink: Drink, now: datetime) -> float:
        """
        Approximate drink contribution to current BAC (%) using:
        - fraction absorbed based on linear absorption over absorption_time
        - treat absorption midpoint as characteristic time for elimination start
        - subtract elimination (beta * hours since midpoint)
        """
        weight_g = self.person.weight_kg * 1000.0
        r = self.person.r()
        beta = self.person.beta()

        # fraction absorbed so far (linear model)
        minutes_since = (now - drink.time).total_seconds() / 60.0
        if minutes_since <= 0:
            frac_absorbed = 0.0
        else:
            frac_absorbed = min(1.0, minutes_since / drink.absorption_time_min)

        absorbed_grams = drink.grams() * frac_absorbed

        # Estimate effective absorption time point for elimination:
        # use midpoint of absorption of the portion absorbed so far
        # If fully absorbed -> midpoint = drink.time + absorption_time/2
        # If partially absorbed -> midpoint = drink.time + (frac_absorbed * absorption_time)/2
        midpoint_offset_min = (frac_absorbed * drink.absorption_time_min) / 2.0
        midpoint_time = drink.time + timedelta(minutes=midpoint_offset_min)

        hours_since_midpoint = max(0.0, (now - midpoint_time).total_seconds() / 3600.0)

        # Widmark instantaneous BAC contribution from absorbed grams:
        raw_bac = (absorbed_grams / (weight_g * r)) * 100.0  # percent BAC

        # subtract elimination since midpoint:
        elim = beta * hours_since_midpoint

        contrib = raw_bac - elim
        return max(0.0, contrib)

    def current_bac(self, now: Optional[datetime] = None) -> float:
        now = now or datetime.now()
        total = sum(self._contribution_from_drink(d, now) for d in self.drinks)
        return max(0.0, total)

    def time_to_sober(self, now: Optional[datetime] = None) -> Optional[timedelta]:
        """Estimate time until BAC reaches ~0.00. Returns timedelta or None if already sober."""
        now = now or datetime.now()
        bac = self.current_bac(now)
        if bac <= 0.0:
            return None
        beta = self.person.beta()
        hours_needed = bac / beta
        return timedelta(hours=hours_needed)

    def summary(self, now: Optional[datetime] = None) -> str:
        now = now or datetime.now()
        bac = self.current_bac(now)
        tts = self.time_to_sober(now)
        lines = [
            f"Current BAC: {bac:.4f} %",
            f"Elimination rate (beta): {self.person.beta():.4f}% per hour",
            f"Drinks recorded: {len(self.drinks)}",
        ]
        if tts is None:
            lines.append("Estimated time to sober: already sober")
        else:
            sober_at = now + tts
            lines.append(f"Estimated time to sober: {str(tts).split('.')[0]} (at {sober_at.strftime('%Y-%m-%d %H:%M:%S')})")
        return "\n".join(lines)

# ---------- Simple CLI ----------
def run_cli():
    import argparse, sys
    parser = argparse.ArgumentParser(description="Simple BAC tracker CLI")
    parser.add_argument("--weight-kg", type=float, required=True)
    parser.add_argument("--sex", choices=["male", "female"], required=True)
    parser.add_argument("--age", type=int, required=True)
    parser.add_argument("--eaten", action="store_true")
    args = parser.parse_args()

    person = Person(weight_kg=args.weight_kg, sex=args.sex, age=args.age, eaten=args.eaten)
    session = BACSession(person)
    print("BAC tracker started. Type 'help' for commands.\n")
    while True:
        try:
            cmd = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            return
        if cmd in ("q", "quit", "exit"):
            print("Bye.")
            return
        if cmd in ("h", "help"):
            print("Commands:\n add OZ PCT  - add drink (ounces and percent alcohol)\n now - show current BAC\n list - list drinks\n reset - remove all drinks\n quit - exit")
            continue
        if cmd.startswith("add "):
            parts = cmd.split()
            if len(parts) != 3:
                print("Usage: add OZ PCT  (e.g. add 12 5 for a 12 oz 5% beer)")
                continue
            try:
                oz = float(parts[1])
                pct = float(parts[2])
            except ValueError:
                print("Bad numbers.")
                continue
            d = session.add_drink(oz, pct)
            print(f"Added: {oz} oz @ {pct}% at {d.time.strftime('%H:%M:%S')}")
            continue
        if cmd == "now":
            print(session.summary())
            continue
        if cmd == "list":
            for i, d in enumerate(session.drinks, 1):
                print(f"{i}. {d.ounces} oz @ {d.alc_percent}% at {d.time.strftime('%Y-%m-%d %H:%M:%S')}")
            continue
        if cmd == "reset":
            session.drinks.clear()
            print("Drinks cleared.")
            continue
        print("Unknown command. Type 'help'.")

if __name__ == "__main__":
    run_cli()