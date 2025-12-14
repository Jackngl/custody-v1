# 👨‍👩‍👧‍👦 Custody Schedule

Intégration Home Assistant pour planifier facilement les gardes alternées, suivre les périodes en cours et automatiser la maison (chauffage, notifications, dashboard…).

## Fonctionnalités principales
- Configuration 100 % UI via un flow guidé (enfant ➜ type de garde ➜ vacances ➜ options).
- Calcul automatique des périodes selon plusieurs rythmes : semaine alternée, weekend alterné, 2-2-3, 2-2-5-5 ou règles personnalisées (services / options).
- Support des zones scolaires françaises (A/B/C/Corse/DOM-TOM) et récupération des vacances via l’API officielle `fr-en-calendrier-scolaire`.
- Gestion des règles vacances (1re semaine, 2e semaine, moitié, semaines paires/impaires, juillet/août) + règles « grandes vacances ».
- Services pour ajouter des exceptions, forcer une présence/absence ou recalculer le planning.
- Événements Home Assistant `custody_arrival`, `custody_departure`, `custody_vacation_start`, `custody_vacation_end`.
- Entités générées automatiquement :
  - `binary_sensor.custody_<nom>_presence`
  - `sensor.custody_<nom>_next_arrival`
  - `sensor.custody_<nom>_next_departure`
  - `sensor.custody_<nom>_days_remaining`
  - `sensor.custody_<nom>_current_period`
  - `calendar.custody_<nom>`

## Installation
1. Copier `custom_components/custody_schedule/` dans votre dossier Home Assistant.
2. Redémarrer Home Assistant.
3. Aller dans **Paramètres → Appareils & services → Ajouter une intégration**.
4. Chercher « Custody Schedule » et suivre les étapes.

## Services
| Service | Description |
| --- | --- |
| `custody_schedule.set_manual_dates` | Ajoute des périodes ponctuelles (vacances, échanges spécifiques). |
| `custody_schedule.override_presence` | Force l’état présent/absent pour une durée donnée. |
| `custody_schedule.refresh_schedule` | Recalcule immédiatement le planning. |

💡 Vous pouvez également ajouter manuellement des périodes particulières (vacances, échanges…) via le service `custody_schedule.set_manual_dates`.

## Cas d’usage (exemples)
- **Automation chauffage** : adapter le preset d’un climatiseur selon `binary_sensor.custody_name_child_presence` (remplacez `name_child` par l’identifiant choisi).
- **Notification arrivée** : alerter la veille via `sensor.custody_name_child_days_remaining`.
- **Dashboard Lovelace** : afficher les entités principales + attributs (arrivée, départ, période actuelle, vacances).

```yaml
automation:
  - alias: Chauffage chambre enfant
    trigger:
      - platform: state
        entity_id: binary_sensor.custody_name_child_presence
    action:
      - service: climate.set_preset_mode
        target:
          entity_id: climate.chambre_enfant
        data:
          preset_mode: "{{ 'comfort' if trigger.to_state.state == 'on' else 'eco' }}"
```

## Roadmap
- **v1.0** : MVP (config flow, capteurs, API vacances, services).
- **v1.1** : calendrier avancé, synchro Google Calendar, notifications natives, gestion d’exceptions.
- **v1.2** : multi-enfants, statistiques, export PDF, internationalisation avancée.
- **v2.0** : mode co-parent, app mobile companion, journal partagé, gestion financière.

## Licence
MIT © Custody Schedule. Contributions bienvenues (fork, branche feature, PR). Merci à la communauté Home Assistant et aux parents en garde alternée !
# custody-v1
