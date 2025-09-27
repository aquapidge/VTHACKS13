#!/usr/bin/env python3
"""
bac_tracker.py

Simple BAC tracker (Widmark-based).
Run as a script for an interactive CLI, or import and use the BACSession class.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
import math

# ---------- Helpers & constants ----------
ML_PER_OUNCE = 29.5735
ALCOHOL_DENSITY_G_PER_ML = 0.789  # g/ml

SEX_R = {"male": 0.73, "female": 0.66}  # Widmark r-factors

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

    def grams(self) -> float:
        return grams_alcohol(self.ounces, self.alc_percent)

@dataclass
class Person:
    weight_kg: float
    sex: str  # "male" or "female"
    age: int
    eaten: bool = False

    def r(self) -> float:
        return SEX_R.get(self.sex.lower(), 0.73)

# ---------- Session / Calculator ----------
class BACSession:
    def __init__(self, person: Person):
        self.person = person
        self.drinks: List[Drink] = []

    def add_drink(self, ounces: float, alc_percent: float, time: Optional[datetime] = None):
        t = time or datetime.now()
        d = Drink(ounces=ounces, alc_percent=alc_percent, time=t)
        self.drinks.append(d)
        return d

    def current_bac(self, now: Optional[datetime] = None) -> float:
        now = now or datetime.now()
        if not self.drinks:
            return 0.0

        # Convert kg → pounds
        weight_lbs = self.person.weight_kg * 2.20462
        r = self.person.r()

        # Total alcohol consumed (in grams)
        total_alc_g = sum(d.grams() for d in self.drinks)

        # Convert grams → standard drinks (14g = 1 standard)
        std_drinks = total_alc_g / 14.0

        # Hours since first drink
        hours = (now - self.drinks[0].time).total_seconds() / 3600.0

        # Widmark formula
        bac = (std_drinks * 5.14 / (weight_lbs * r)) - (0.015 * hours)
        return max(0.0, bac)

    def summary(self) -> str:
        bac = self.current_bac()
        return f"Current BAC: {bac:.3f}%"

# ---------- Simple CLI ----------
def run_cli():
    import argparse
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
            print("Commands:\n add OZ PCT  - add drink (ounces and percent alcohol)"
                  "\n now - show current BAC"
                  "\n list - list drinks"
                  "\n reset - remove all drinks"
                  "\n quit - exit")
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