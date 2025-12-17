#!/usr/bin/env python3
"""Test sandbox pour vérifier la priorité des règles de vacances avec vraies dates Zone C."""

import json
import urllib.request
from datetime import datetime, time, timedelta
from typing import Any

# Mock des classes nécessaires
class CustodyWindow:
    def __init__(self, start: datetime, end: datetime, label: str, source: str = "pattern"):
        self.start = start
        self.end = end
        self.label = label
        self.source = source
    
    def __repr__(self):
        return f"CustodyWindow({self.start.strftime('%d/%m/%Y %H:%M')} -> {self.end.strftime('%d/%m/%Y %H:%M')}, {self.label}, {self.source})"

# Configuration de test
CONFIG = {
    "custody_type": "even_weekends",  # Weekends pairs chaque année
    "arrival_time": "16:15",  # Vendredi sortie d'école 16:15
    "departure_time": "19:00",  # Dimanche 19:00
    "vacation_rule": "second_half",  # 2ème moitié (calcul du milieu)
    "summer_rule": None,  # Géré séparément (juillet impaire, août paire)
    "zone": "C",
    "reference_year": "even",
    "school_level": "primary",  # Primaire = vendredi sortie d'école
}

def fetch_holidays_from_api(zone: str, year: int) -> list[dict]:
    """Fetch real holidays from API for zone C."""
    url = (
        f"https://data.education.gouv.fr/api/records/1.0/search/"
        f"?dataset=fr-en-calendrier-scolaire"
        f"&refine.annee_scolaire={year-1}-{year}"
        f"&rows=100"
    )
    
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
        holidays = []
        
        for record in data.get("records", []):
            fields = record.get("fields", {})
            zones = fields.get("zones", "")
            # Check if zone C is in the zones field
            if "Zone C" in zones or (zone == "C" and ("C" in zones or "Zone C" in zones)):
                start_str = fields.get("start_date")
                end_str = fields.get("end_date")
                name = fields.get("description", "")
                
                if start_str and end_str:
                    # Parse dates (format: "2025-12-20T00:00:00+01:00")
                    # Remove timezone info and parse as naive datetime
                    start_str_clean = start_str.split("+")[0].split("Z")[0]
                    end_str_clean = end_str.split("+")[0].split("Z")[0]
                    start = datetime.fromisoformat(start_str_clean)
                    end = datetime.fromisoformat(end_str_clean)
                    
                    holidays.append({
                        "name": name,
                        "start": start,
                        "end": end,
                    })
        
        return holidays
    except Exception as e:
        print(f"   Erreur API: {e}")
        return []

def parse_time(time_str: str) -> time:
    """Parse time string like '16:15' to time object."""
    parts = time_str.split(":")
    return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)

def apply_time(dt: datetime, t: time) -> datetime:
    """Apply time to datetime."""
    return dt.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)

def adjust_vacation_start_for_primary(official_start: datetime) -> datetime:
    """Adjust vacation start for primary school: Friday afternoon instead of Saturday.
    
    API returns Saturday 00:00, but for primary school it should be Friday afternoon.
    """
    # Extract date part (already in local time)
    start_date = official_start.date()
    
    # If the date is Saturday (API's Friday 23h UTC became Saturday 00h local), go back to Friday
    if start_date.weekday() == 5:  # Saturday
        start_date = start_date - timedelta(days=1)  # Go to Friday
    
    # Ensure it's Friday
    if start_date.weekday() != 4:  # Not Friday
        # Find the Friday before
        days_back = (start_date.weekday() - 4) % 7
        if days_back == 0:
            days_back = 7
        start_date = start_date - timedelta(days=days_back)
    
    return datetime.combine(start_date, time(16, 15))  # Friday 16:15

def generate_even_weekends_windows(now: datetime, arrival_time: time, departure_time: time, horizon: datetime) -> list[CustodyWindow]:
    """Generate windows for even weekends (weekends pairs)."""
    windows = []
    
    # Trouver le prochain samedi
    days_to_saturday = (5 - now.weekday()) % 7
    if days_to_saturday == 0 and now.time() < arrival_time:
        days_to_saturday = 0
    elif days_to_saturday == 0:
        days_to_saturday = 7
    
    pointer = now + timedelta(days=days_to_saturday)
    pointer = pointer.replace(hour=0, minute=0, second=0, microsecond=0)
    
    while pointer < horizon:
        # Vérifier si c'est une semaine paire (ISO week)
        _, iso_week, _ = pointer.isocalendar()
        if iso_week % 2 == 0:  # Semaine paire
            saturday = pointer
            sunday = saturday + timedelta(days=1)
            windows.append(
                CustodyWindow(
                    start=apply_time(saturday, arrival_time),
                    end=apply_time(sunday, departure_time),
                    label="Weekend semaine paire",
                    source="pattern"
                )
            )
        pointer += timedelta(days=7)
    
    return windows

def generate_vacation_windows(now: datetime, vacations: list[dict], arrival_time: time, departure_time: time, school_level: str = "primary") -> list[CustodyWindow]:
    """Generate vacation windows based on rules.
    
    Rules:
    - Année impaire : 1ère semaine des vacances
    - Année paire : 2ème semaine des vacances
    - Juillet : années impaires (tout le mois)
    - Août : années paires (tout le mois)
    """
    windows = []
    
    for vacation in vacations:
        if vacation["end"] < now:
            continue
        
        start = vacation["start"]
        end = vacation["end"]
        name = vacation["name"]
        
        # Adjust start for primary school (Friday instead of Saturday)
        if school_level == "primary":
            start = adjust_vacation_start_for_primary(start)
        
        # Check if it's summer (July/August)
        is_summer = start.month in (7, 8) or end.month in (7, 8)
        
        if is_summer:
            # Règles pour juillet/août : 1 mois complet chacun selon l'année
            # Les vacances d'été peuvent commencer en juillet et finir en août
            # On doit séparer juillet (années impaires) et août (années paires)
            
            # Traiter juillet (années impaires uniquement)
            if start.year % 2 == 1:  # Année impaire -> juillet complet
                july_year = start.year
                july_start = max(start, datetime(july_year, 7, 1))
                july_end = min(end, datetime(july_year, 7, 31, 23, 59, 59))
                if july_start <= july_end:
                    # Generate weekends in July (tout le mois)
                    current = july_start
                    while current <= july_end:
                        days_to_friday = (4 - current.weekday()) % 7
                        if days_to_friday == 0 and current.weekday() == 4:
                            friday = current
                        else:
                            friday = current + timedelta(days=days_to_friday)
                        
                        if friday >= july_start and friday <= july_end:
                            sunday = friday + timedelta(days=2)
                            if sunday <= july_end:
                                windows.append(
                                    CustodyWindow(
                                        start=apply_time(friday, arrival_time),
                                        end=apply_time(sunday, departure_time),
                                        label=f"{name} - Juillet complet (année impaire)",
                                        source="vacation"
                                    )
                                )
                        current += timedelta(days=7)
            
            # Traiter août (années paires uniquement)
            # Si les vacances commencent en juillet d'une année paire, on prend août de la même année
            # Si les vacances commencent en juillet d'une année impaire, on prend août de l'année suivante (paire)
            if start.year % 2 == 0:  # Année paire -> août de cette année
                august_year = start.year
            else:  # Année impaire -> août de l'année suivante (paire)
                august_year = start.year + 1
            
            august_start = max(start, datetime(august_year, 8, 1))
            august_end = min(end, datetime(august_year, 8, 31, 23, 59, 59))
            if august_start <= august_end:
                # Generate weekends in August (tout le mois)
                current = august_start
                while current <= august_end:
                    days_to_friday = (4 - current.weekday()) % 7
                    if days_to_friday == 0 and current.weekday() == 4:
                        friday = current
                    else:
                        friday = current + timedelta(days=days_to_friday)
                    
                    if friday >= august_start and friday <= august_end:
                        sunday = friday + timedelta(days=2)
                        if sunday <= august_end:
                            windows.append(
                                CustodyWindow(
                                    start=apply_time(friday, arrival_time),
                                    end=apply_time(sunday, departure_time),
                                    label=f"{name} - Août complet (année paire)",
                                    source="vacation"
                                )
                            )
                    current += timedelta(days=7)
        else:
            # Règles pour autres vacances (Noël, Hiver, Printemps)
            # Utiliser la 2ème moitié (calcul du milieu) - UNE SEULE fenêtre continue
            vacation_rule = CONFIG.get("vacation_rule")
            if vacation_rule == "second_half":
                # Calculer le milieu des vacances
                midpoint = start + (end - start) / 2
                
                # Générer UNE SEULE fenêtre continue pour toute la 2ème moitié
                # Du milieu (avec heure d'arrivée) à la fin (avec heure de départ)
                window_start = apply_time(midpoint, arrival_time)
                window_end = apply_time(end, departure_time)
                
                if window_end > window_start:
                    windows.append(
                        CustodyWindow(
                            start=window_start,
                            end=window_end,
                            label=f"{name} - 2ème moitié",
                            source="vacation"
                        )
                    )
                
                # Ajouter une fenêtre de filtrage pour toute la période de vacances
                # pour supprimer les weekends normaux pendant toute la durée des vacances
                monday_start_week = start - timedelta(days=start.weekday())
                sunday_end_week = end - timedelta(days=end.weekday()) + timedelta(days=6)
                windows.append(
                    CustodyWindow(
                        start=monday_start_week,
                        end=sunday_end_week + timedelta(days=1),
                        label=f"{name} - Période complète (filtrage)",
                        source="vacation_filter"
                    )
                )
    
    return windows

def filter_windows_by_vacations(pattern_windows: list[CustodyWindow], vacation_windows: list[CustodyWindow]) -> list[CustodyWindow]:
    """Remove pattern windows that overlap with vacation periods.
    
    A pattern window (weekend) is removed if it overlaps (even partially) with any vacation window.
    We use the vacation_filter windows which cover entire weeks.
    """
    if not vacation_windows:
        return pattern_windows
    
    # Get only the filter windows (which cover entire weeks)
    filter_windows = [vw for vw in vacation_windows if vw.source == "vacation_filter"]
    if not filter_windows:
        # Fallback: use all vacation windows
        filter_windows = vacation_windows
    
    filtered = []
    for pattern_window in pattern_windows:
        overlaps = False
        for vw in filter_windows:
            # Check if pattern window overlaps with vacation window
            if pattern_window.start < vw.end and pattern_window.end > vw.start:
                overlaps = True
                break
        
        if not overlaps:
            filtered.append(pattern_window)
    
    return filtered

def main():
    print("🧪 Test de Priorité des Règles de Vacances - Zone C")
    print("=" * 70)
    print()
    print("📋 Configuration:")
    print(f"   Type de garde normale: {CONFIG['custody_type']} (weekends pairs)")
    print(f"   Règle vacances: {CONFIG['vacation_rule']} (2ème moitié, calcul du milieu)")
    print(f"   Juillet: années impaires (mois complet)")
    print(f"   Août: années paires (mois complet)")
    print(f"   Arrivée: {CONFIG['arrival_time']} (vendredi sortie d'école)")
    print(f"   Départ: {CONFIG['departure_time']} (dimanche)")
    print()
    
    # Date de test: mercredi 17 décembre 2025
    now = datetime(2025, 12, 17, 22, 0, 0)
    print(f"📅 Date de test: {now.strftime('%A %d %B %Y à %H:%M')}")
    print(f"   Année: {now.year} ({'impaire' if now.year % 2 == 1 else 'paire'})")
    print()
    
    # Fetch real holidays from API
    print("🌐 Récupération des vacances Zone C depuis l'API...")
    try:
        # Récupérer pour plusieurs années pour avoir toutes les vacances
        # Important: récupérer aussi 2024-2025 pour les vacances d'hiver de février 2025
        # et 2023-2024 pour les vacances d'hiver de février 2026 (si elles existent)
        holidays_2023_2024 = fetch_holidays_from_api("C", 2024)
        holidays_2024_2025 = fetch_holidays_from_api("C", 2025)
        holidays_2025_2026 = fetch_holidays_from_api("C", 2026)
        holidays_2026_2027 = fetch_holidays_from_api("C", 2027)
        all_holidays = holidays_2023_2024 + holidays_2024_2025 + holidays_2025_2026 + holidays_2026_2027
        
        # Remove duplicates and filter future holidays
        unique_holidays = {}
        for h in all_holidays:
            # Use name and start date as key to avoid duplicates
            key = (h["name"], h["start"].date())
            if key not in unique_holidays:
                unique_holidays[key] = h
        
        # L'API retourne les vacances d'hiver Zone C 2025-2026 avec les dates 20/02 -> 08/03
        # Selon le calendrier officiel, c'est 21/02 -> 09/03, mais on utilise les dates de l'API
        # et on les ajuste pour primaire (vendredi au lieu de samedi)
        
        vacations = [h for h in unique_holidays.values() if h["end"] >= now]
        vacations.sort(key=lambda x: x["start"])
        
        # Debug: show all vacations found
        print(f"   Vacances trouvées (après déduplication):")
        for v in vacations:
            print(f"   - {v['name']}: {v['start'].strftime('%d/%m/%Y')} -> {v['end'].strftime('%d/%m/%Y')}")
        
        print(f"   {len(vacations)} périodes de vacances trouvées")
        for v in vacations:
            print(f"   - {v['name']}: {v['start'].strftime('%d/%m/%Y')} -> {v['end'].strftime('%d/%m/%Y')}")
        print()
    except Exception as e:
        print(f"   ❌ Erreur: {e}")
        print("   Utilisation de dates de test...")
        vacations = [
            {
                "name": "Vacances de Noël",
                "start": datetime(2025, 12, 20, 0, 0),
                "end": datetime(2026, 1, 5, 0, 0),
            },
            {
                "name": "Vacances d'Hiver",
                "start": datetime(2026, 2, 14, 0, 0),
                "end": datetime(2026, 3, 2, 0, 0),
            },
            {
                "name": "Vacances de Printemps",
                "start": datetime(2026, 4, 11, 0, 0),
                "end": datetime(2026, 4, 27, 0, 0),
            },
            {
                "name": "Vacances d'Été",
                "start": datetime(2026, 7, 4, 0, 0),
                "end": datetime(2026, 9, 1, 0, 0),
            },
        ]
    
    arrival_time = parse_time(CONFIG["arrival_time"])
    departure_time = parse_time(CONFIG["departure_time"])
    horizon = now + timedelta(days=120)  # 4 mois
    
    # Générer les fenêtres normales (weekends pairs)
    print("🔵 Génération des fenêtres normales (weekends pairs)...")
    pattern_windows = generate_even_weekends_windows(now, arrival_time, departure_time, horizon)
    print(f"   {len(pattern_windows)} fenêtres générées")
    print()
    
    # Générer les fenêtres de vacances
    print("🟢 Génération des fenêtres de vacances (weekends vendredi 16:15 -> dimanche 19:00)...")
    vacation_windows = generate_vacation_windows(now, vacations, arrival_time, departure_time, CONFIG["school_level"])
    print(f"   {len(vacation_windows)} fenêtres de vacances générées")
    for vw in vacation_windows[:10]:  # Show first 10
        print(f"   - {vw.label}: {vw.start.strftime('%d/%m/%Y %H:%M')} -> {vw.end.strftime('%d/%m/%Y %H:%M')}")
    if len(vacation_windows) > 10:
        print(f"   ... et {len(vacation_windows) - 10} autres")
    print()
    
    # Filtrer les fenêtres normales qui chevauchent les vacances
    print("🔴 Filtrage: suppression des weekends normaux pendant les vacances...")
    filtered_pattern = filter_windows_by_vacations(pattern_windows, vacation_windows)
    removed_count = len(pattern_windows) - len(filtered_pattern)
    print(f"   {removed_count} weekends normaux supprimés (chevauchent les vacances)")
    print(f"   {len(filtered_pattern)} weekends normaux conservés")
    print()
    
    # Fusionner toutes les fenêtres (exclure les fenêtres de filtrage de l'affichage)
    vacation_display_windows = [w for w in vacation_windows if w.source != "vacation_filter"]
    all_windows = vacation_display_windows + filtered_pattern
    all_windows.sort(key=lambda w: w.start)
    
    # Afficher les prochaines fenêtres
    print("📊 Prochaines périodes de garde (priorité: Vacances > Weekends normaux):")
    print()
    next_windows = [w for w in all_windows if w.start > now][:15]
    
    for i, window in enumerate(next_windows, 1):
        period_type = "🟢 VACANCES" if window.source == "vacation" else "🔵 NORMAL"
        print(f"{i}. {period_type} - {window.label}")
        print(f"   Début: {window.start.strftime('%A %d %B %Y à %H:%M')}")
        print(f"   Fin:   {window.end.strftime('%A %d %B %Y à %H:%M')}")
        print()

if __name__ == "__main__":
    main()
