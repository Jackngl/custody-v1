#!/usr/bin/env python3
"""Test complet du calcul des dates de garde pour alternate_weekend avec reference_year=odd"""

from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

# Configuration
custody_type = "alternate_weekend"
reference_year = "even"  # Années paires
arrival_time = time(16, 15)  # 16:15
departure_time = time(19, 0)  # 19:00
tz = ZoneInfo("Europe/Paris")

def get_french_holidays(year):
    """Simulation simplifiée des jours fériés français"""
    from datetime import date
    holidays = set()
    holidays.add(date(year, 1, 1))    # Jour de l'An
    holidays.add(date(year, 5, 1))     # Fête du Travail
    holidays.add(date(year, 5, 8))     # Victoire 1945
    holidays.add(date(year, 7, 14))    # Fête Nationale
    holidays.add(date(year, 8, 15))    # Assomption
    holidays.add(date(year, 11, 1))    # Toussaint
    holidays.add(date(year, 11, 11))   # Armistice
    holidays.add(date(year, 12, 25))   # Noël
    return holidays

def first_monday_with_week_parity(reference_year_value, target_parity):
    """Trouve le premier lundi de l'année de référence avec la parité cible"""
    base = datetime(reference_year_value, 1, 1, tzinfo=tz)
    # Trouver le premier lundi
    days_until_monday = (7 - base.weekday()) % 7
    if days_until_monday == 0 and base.weekday() != 0:
        days_until_monday = 7
    first_monday = base + timedelta(days=days_until_monday)
    
    # Vérifier la parité de la semaine ISO
    iso_week = first_monday.isocalendar()[1]
    week_parity = iso_week % 2
    
    # Si la parité ne correspond pas, passer à la semaine suivante
    if week_parity != target_parity:
        first_monday += timedelta(days=7)
    
    return first_monday

def generate_weekend_windows(now, reference_year_value, target_parity, arrival_time, departure_time, horizon_days=90):
    """Génère les fenêtres de weekend pour alternate_weekend"""
    windows = []
    
    # Trouver le point de départ (premier lundi avec la parité cible)
    pointer = first_monday_with_week_parity(reference_year_value, target_parity)
    
    # Ajuster pour commencer avant ou à la date actuelle
    while pointer < now - timedelta(days=7):
        pointer += timedelta(days=14)  # Sauter 2 semaines (alternance)
    
    # Générer les fenêtres
    holidays = get_french_holidays(now.year) | get_french_holidays(now.year + 1)
    
    while pointer < now + timedelta(days=horizon_days):
        iso_week = pointer.isocalendar()[1]
        week_parity = iso_week % 2
        
        if week_parity == target_parity:
            # Weekend: Vendredi 16:15 -> Dimanche 19:00
            friday = pointer + timedelta(days=4)
            sunday = pointer + timedelta(days=6)
            monday = pointer + timedelta(days=7)
            thursday = pointer + timedelta(days=3)
            
            window_start = friday.replace(hour=arrival_time.hour, minute=arrival_time.minute, second=0, microsecond=0)
            window_end = sunday.replace(hour=departure_time.hour, minute=departure_time.minute, second=0, microsecond=0)
            label_suffix = ""
            
            # Vérifier les jours fériés
            friday_is_holiday = friday.date() in holidays
            monday_is_holiday = monday.date() in holidays
            
            if friday_is_holiday:
                window_start = thursday.replace(hour=arrival_time.hour, minute=arrival_time.minute, second=0, microsecond=0)
                label_suffix = " + Vendredi férié"
            
            if monday_is_holiday:
                window_end = monday.replace(hour=departure_time.hour, minute=departure_time.minute, second=0, microsecond=0)
                label_suffix = " + Lundi férié" if not label_suffix else " + Pont"
            
            windows.append({
                'start': window_start,
                'end': window_end,
                'label': f"Weekend garde (semaine {iso_week}, parité={'paire' if week_parity == 0 else 'impaire'}){label_suffix}",
                'week_parity': week_parity
            })
        
        pointer += timedelta(days=7)
    
    return windows

def calculate_next_dates(now, windows):
    """Calcule next_arrival et next_departure"""
    # Filtrer les fenêtres passées
    future_windows = [w for w in windows if w['end'] > now]
    future_windows.sort(key=lambda w: w['start'])
    
    # Trouver la fenêtre actuelle
    current_window = next((w for w in future_windows if w['start'] <= now < w['end']), None)
    
    # Trouver la prochaine fenêtre
    next_window = next((w for w in future_windows if w['start'] > now), None)
    
    is_present = current_window is not None
    
    if is_present:
        # En garde actuellement
        next_departure = current_window['end']
        # next_arrival est la prochaine garde APRÈS le départ actuel
        if next_departure and next_departure > now:
            # Chercher la fenêtre qui commence après next_departure
            next_arrival = next((w['start'] for w in future_windows if w['start'] > next_departure), None)
        else:
            next_arrival = next_window['start'] if next_window else None
    else:
        next_arrival = next_window['start'] if next_window else None
        next_departure = next_window['end'] if next_window else None
    
    return {
        'is_present': is_present,
        'next_arrival': next_arrival,
        'next_departure': next_departure,
        'current_window': current_window,
        'next_window': next_window
    }

# Dates de test
test_dates = [
    datetime(2026, 1, 15, 17, 55, 0, tzinfo=tz),  # Jeudi 15 janvier 2026, 17:55
    datetime(2026, 1, 17, 10, 0, 0, tzinfo=tz),   # Samedi 17 janvier 2026, 10:00
    datetime(2026, 1, 19, 20, 0, 0, tzinfo=tz),   # Lundi 19 janvier 2026, 20:00
    datetime(2026, 1, 24, 16, 30, 0, tzinfo=tz),  # Vendredi 24 janvier 2026, 16:30
]

# Configuration
reference_year_value = 2024  # Année de référence paire
target_parity = 0  # 0 = paire (car reference_year="even")

print("=" * 100)
print("TEST CALCUL DES DATES DE GARDE - alternate_weekend avec reference_year=even")
print("=" * 100)
print(f"\nConfiguration:")
print(f"  - Type de garde: {custody_type}")
print(f"  - Année de référence: {reference_year} (impaire)")
print(f"  - Parité cible: {'Paire' if target_parity == 0 else 'Impaire'}")
print(f"  - Heure d'arrivée: {arrival_time.strftime('%H:%M')}")
print(f"  - Heure de départ: {departure_time.strftime('%H:%M')}")
print()

# Générer toutes les fenêtres pour 2026
all_windows = generate_weekend_windows(
    datetime(2026, 1, 1, tzinfo=tz),
    reference_year_value,
    target_parity,
    arrival_time,
    departure_time,
    horizon_days=180
)

print(f"Fenêtres générées: {len(all_windows)} weekends de garde")
print("\nPremières fenêtres de garde en 2026:")
print("-" * 100)
for i, window in enumerate(all_windows[:6], 1):
    iso_week = window['start'].isocalendar()[1]
    print(f"{i}. {window['start'].strftime('%A %d %B %Y à %H:%M')} → {window['end'].strftime('%A %d %B %Y à %H:%M')}")
    print(f"   Semaine ISO {iso_week} ({'paire' if iso_week % 2 == 0 else 'impaire'})")
print()

# Tester pour chaque date
for test_date in test_dates:
    print("=" * 100)
    print(f"TEST - Date actuelle: {test_date.strftime('%A %d %B %Y à %H:%M:%S')}")
    print(f"Jour de la semaine: {test_date.strftime('%A')} (ISO semaine {test_date.isocalendar()[1]}, parité {'paire' if test_date.isocalendar()[1] % 2 == 0 else 'impaire'})")
    print("-" * 100)
    
    result = calculate_next_dates(test_date, all_windows)
    
    print(f"Statut: {'EN GARDE' if result['is_present'] else 'PAS EN GARDE'}")
    
    if result['current_window']:
        print(f"Fenêtre actuelle: {result['current_window']['start'].strftime('%d %B %H:%M')} → {result['current_window']['end'].strftime('%d %B %H:%M')}")
    
    print()
    print("RÉSULTATS:")
    if result['next_arrival']:
        arrival_str = result['next_arrival'].strftime('%A %d %B %Y à %H:%M:%S')
        days_until = (result['next_arrival'] - test_date).days
        hours_until = (result['next_arrival'] - test_date).total_seconds() / 3600
        print(f"  ✅ Next arrival:  {arrival_str}")
        print(f"     (dans {days_until} jours, {hours_until:.1f} heures)")
    else:
        print(f"  ❌ Next arrival:  Aucune")
    
    if result['next_departure']:
        departure_str = result['next_departure'].strftime('%A %d %B %Y à %H:%M:%S')
        days_until = (result['next_departure'] - test_date).days
        hours_until = (result['next_departure'] - test_date).total_seconds() / 3600
        print(f"  ✅ Next departure: {departure_str}")
        print(f"     (dans {days_until} jours, {hours_until:.1f} heures)")
    else:
        print(f"  ❌ Next departure: Aucune")
    
    # Vérifier la cohérence
    if result['next_arrival'] and result['next_departure']:
        if result['next_departure'] < result['next_arrival']:
            print(f"\n  ❌ ERREUR: next_departure ({departure_str}) est AVANT next_arrival ({arrival_str})")
        elif result['next_departure'] == result['next_arrival']:
            print(f"\n  ⚠️  ATTENTION: next_departure est égal à next_arrival")
        else:
            delta = result['next_departure'] - result['next_arrival']
            print(f"\n  ✅ Cohérence OK: next_departure est {delta.total_seconds() / 3600:.1f} heures après next_arrival")
    
    if result['next_window']:
        print(f"\nProchaine fenêtre complète:")
        print(f"  Début: {result['next_window']['start'].strftime('%A %d %B %Y à %H:%M:%S')}")
        print(f"  Fin:   {result['next_window']['end'].strftime('%A %d %B %Y à %H:%M:%S')}")
        print(f"  Label: {result['next_window']['label']}")
    
    print()

print("=" * 100)
print("RÉSUMÉ DES PROCHAINES DATES DE GARDE (2026, semaines paires)")
print("=" * 100)
print()
future_windows_2026 = [w for w in all_windows if w['start'].year == 2026 and w['start'] > datetime(2026, 1, 1, tzinfo=tz)]
for i, window in enumerate(future_windows_2026[:4], 1):
    iso_week = window['start'].isocalendar()[1]
    iso_week = window['start'].isocalendar()[1]
    week_parity_label = "paire" if iso_week % 2 == 0 else "impaire"
    print(f"{i}. {window['start'].strftime('%A %d %B %Y à %H:%M')} → {window['end'].strftime('%A %d %B %Y à %H:%M')}")
    print(f"   Semaine ISO {iso_week} ({week_parity_label}) - Durée: {(window['end'] - window['start']).total_seconds() / 3600:.1f} heures")
print()
