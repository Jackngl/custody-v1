# 👨‍👩‍👧‍👦 Planning de garde (Custody Schedule)

![Version](https://img.shields.io/badge/version-1.0.70-blue.svg)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.12-green.svg)
![License](https://img.shields.io/badge/license-MIT-yellow.svg)

Intégration Home Assistant pour planifier facilement les gardes alternées, suivre les périodes en cours et automatiser la maison (chauffage, notifications, dashboard…).

## 📋 Table des matières

- [Fonctionnalités principales](#fonctionnalités-principales)
- [Installation](#installation)
  - [Installation via HACS (recommandé)](#installation-via-hacs-recommandé)
  - [Installation manuelle](#installation-manuelle)
- [Configuration](#configuration)
- [Services disponibles](#services-disponibles)
- [Événements Home Assistant](#événements-home-assistant)
- [Entités générées](#entités-générées)
- [Automatisations et exemples](#automatisations-et-exemples)
- [API des vacances scolaires](#api-des-vacances-scolaires)
- [Roadmap](#roadmap)
- [Contribution](#contribution)

## ✨ Fonctionnalités principales

- ✅ **Configuration 100% UI** via un flow guidé (enfant ➜ type de garde ➜ vacances ➜ options)
- ✅ **Calcul automatique** des périodes selon plusieurs rythmes :
  - Semaine alternée (1/1)
  - Week-end alterné
  - Week-ends semaines paires/impaires
  - 2-2-3
  - 2-2-5-5
  - Règles personnalisées
- ✅ **Support des zones scolaires françaises** (A/B/C/Corse/DOM-TOM)
- ✅ **API officielle** `data.education.gouv.fr` pour les vacances scolaires
- ✅ **URL d'API personnalisable** dans les options avancées
- ✅ **Test de l'API** via service dédié
- ✅ **Gestion des règles vacances** :
  - 1ère semaine, 2ème semaine
  - 1ère moitié, 2ème moitié
  - Semaines paires/impaires
  - Juillet/Août
  - Règles basées sur années paires/impaires
- ✅ **Règles grandes vacances** (juillet/août avec variantes)
- ✅ **Services** pour exceptions, forcer présence/absence, recalcul
- ✅ **Événements** Home Assistant pour automatisations
- ✅ **Support multi-enfants** avec configurations indépendantes
- ✅ **Calendrier** intégré pour visualisation

## 🚀 Installation

### Installation via HACS (recommandé)

1. **Installer HACS** si ce n'est pas déjà fait : [Documentation HACS](https://hacs.xyz/docs/setup/download)

2. **Ajouter ce dépôt à HACS** :
   - Aller dans **HACS** → **Intégrations**
   - Cliquer sur les **3 points** (⋮) en haut à droite
   - Sélectionner **Dépôts personnalisés**
   - Ajouter l'URL : `https://github.com/Jackngl/custody-v1`
   - Catégorie : **Intégration**
   - Cliquer sur **Ajouter**

3. **Installer l'intégration** :
   - Rechercher "Planning de garde" ou "Custody Schedule"
   - Cliquer sur **Télécharger**
   - Redémarrer Home Assistant

4. **Configurer l'intégration** :
   - Aller dans **Paramètres** → **Appareils & services** → **Ajouter une intégration**
   - Chercher "Planning de garde" et suivre les étapes

### Installation manuelle

1. **Télécharger le code** :
   ```bash
   cd /config
   git clone https://github.com/Jackngl/custody-v1.git
   ```

2. **Copier le dossier** :
   ```bash
   cp -r custody-v1/custom_components/custody_schedule /config/custom_components/
   ```

3. **Redémarrer Home Assistant**

4. **Ajouter l'intégration** :
   - Aller dans **Paramètres** → **Appareils & services** → **Ajouter une intégration**
   - Chercher "Planning de garde" et suivre les étapes

## ⚙️ Configuration

La configuration se fait entièrement via l'interface utilisateur :

1. **Informations de l'enfant** : nom, icône, photo
2. **Type de garde** : choisir le rythme (semaine alternée, week-end, etc.)
3. **Zone scolaire et vacances** : zone (A/B/C/Corse/DOM-TOM) et règles de vacances
4. **Options avancées** :
   - Notes
   - Notifications
   - Synchronisation calendrier
   - Exceptions
   - **URL d'API personnalisée** (optionnel)

### Configuration de l'URL d'API

Si vous souhaitez utiliser une API alternative pour les vacances scolaires :

1. Aller dans **Paramètres** → **Appareils & services** → **Planning de garde** → **Options**
2. Sélectionner **Options avancées**
3. Entrer votre URL personnalisée dans le champ **URL API vacances scolaires**
   - L'URL doit contenir les placeholders `{year}` et `{zone}`
   - Exemple : `https://api.example.com/holidays?year={year}&zone={zone}`

## 🔧 Services disponibles

### `custody_schedule.set_manual_dates`

Ajoute des périodes ponctuelles de présence (vacances, échanges spécifiques).

**Paramètres :**
- `entry_id` (requis) : ID de l'intégration
- `dates` (requis) : Liste de périodes avec `start`, `end`, et optionnellement `label`

**Exemple :**
```yaml
service: custody_schedule.set_manual_dates
data:
  entry_id: "1234567890abcdef1234567890abcdef"
  dates:
    - start: "2024-07-15T08:00:00+02:00"
      end: "2024-07-22T19:00:00+02:00"
      label: "Vacances chez papa"
```

### `custody_schedule.override_presence`

Force l'état présent/absent pour une durée donnée.

**Paramètres :**
- `entry_id` (requis) : ID de l'intégration
- `state` (requis) : `on` (présent) ou `off` (absent)
- `duration` (optionnel) : Durée en minutes

**Exemple :**
```yaml
service: custody_schedule.override_presence
data:
  entry_id: "1234567890abcdef1234567890abcdef"
  state: "on"
  duration: 120  # 2 heures
```

### `custody_schedule.refresh_schedule`

Déclenche immédiatement un recalcul du planning.

**Paramètres :**
- `entry_id` (requis) : ID de l'intégration

**Exemple :**
```yaml
service: custody_schedule.refresh_schedule
data:
  entry_id: "1234567890abcdef1234567890abcdef"
```

### `custody_schedule.test_holiday_api`

Teste la connexion à l'API des vacances scolaires et affiche les résultats dans les logs.

**Paramètres :**
- `entry_id` (optionnel) : ID de l'intégration (utilise la config de cette intégration)
- `zone` (optionnel, défaut: "A") : Zone scolaire à tester
- `year` (optionnel) : Année scolaire au format "2024-2025"

**Exemple :**
```yaml
service: custody_schedule.test_holiday_api
data:
  entry_id: "1234567890abcdef1234567890abcdef"
  zone: "C"
  year: "2024-2025"
```

Les résultats sont disponibles dans les logs Home Assistant.

## 📡 Événements Home Assistant

L'intégration émet automatiquement des événements pour déclencher des automatisations :

### `custody_arrival`

Déclenché quand l'enfant arrive (transition de `off` à `on`).

**Données :**
- `entry_id` : ID de l'intégration
- `child` : Nom de l'enfant
- `next_departure` : Prochain départ (ISO format)
- `next_arrival` : Prochaine arrivée (ISO format)

### `custody_departure`

Déclenché quand l'enfant part (transition de `on` à `off`).

**Données :**
- `entry_id` : ID de l'intégration
- `child` : Nom de l'enfant
- `next_departure` : Prochain départ (ISO format)
- `next_arrival` : Prochaine arrivée (ISO format)

### `custody_vacation_start`

Déclenché au début des vacances scolaires.

**Données :**
- `entry_id` : ID de l'intégration
- `holiday` : Nom de la période de vacances

### `custody_vacation_end`

Déclenché à la fin des vacances scolaires.

**Données :**
- `entry_id` : ID de l'intégration
- `holiday` : Nom de la période de vacances qui se termine

## 📊 Entités générées

Pour chaque enfant configuré, les entités suivantes sont créées automatiquement :

| Entité | Type | Description |
|--------|------|-------------|
| `binary_sensor.<nom>_planning_de_garde_presence` | Binary Sensor | État présent/absent (`on`/`off`) |
| `sensor.<nom>_planning_de_garde_prochaine_arrivee` | Sensor | Prochaine arrivée (datetime) |
| `sensor.<nom>_planning_de_garde_prochain_depart` | Sensor | Prochain départ (datetime) |
| `sensor.<nom>_planning_de_garde_jours_restants` | Sensor | Jours restants avant prochain changement |
| `sensor.<nom>_planning_de_garde_periode_actuelle` | Sensor | Période actuelle (`school`/`vacation`) |
| `calendar.<nom>_planning_de_garde_calendrier` | Calendar | Calendrier avec toutes les périodes |

**Note :** `<nom>` correspond au nom de l'enfant en minuscules avec les espaces remplacés par des underscores. Par exemple, pour un enfant nommé "Lucas", les entités seront :
- `binary_sensor.lucas_planning_de_garde_presence`
- `sensor.lucas_planning_de_garde_prochaine_arrivee`
- etc.

**Attributs disponibles :**
- `vacation_name` : Nom de la période de vacances en cours
- `zone` : Zone scolaire configurée
- `location` : Lieu configuré
- `notes` : Notes configurées

## 🤖 Automatisations et exemples

### 1. Ajuster le chauffage selon la présence

```yaml
automation:
  - alias: "Chauffage chambre enfant"
    description: "Ajuste le chauffage selon la présence de l'enfant"
    trigger:
      - platform: state
        entity_id: binary_sensor.lucas_planning_de_garde_presence
    action:
      - service: climate.set_preset_mode
        target:
          entity_id: climate.chambre_lucas
        data:
          preset_mode: "{{ 'comfort' if trigger.to_state.state == 'on' else 'eco' }}"
      - service: climate.set_temperature
        target:
          entity_id: climate.chambre_lucas
        data:
          temperature: "{{ 20 if trigger.to_state.state == 'on' else 16 }}"
```

### 2. Notification avant l'arrivée

```yaml
automation:
  - alias: "Notification arrivée enfant"
    description: "Notifie 1 jour avant l'arrivée"
    trigger:
      - platform: numeric_state
        entity_id: sensor.lucas_planning_de_garde_jours_restants
        below: 1
        above: 0
    condition:
      - condition: state
        entity_id: binary_sensor.lucas_planning_de_garde_presence
        state: "off"
    action:
      - service: notify.mobile_app_telephone
        data:
          message: "Lucas arrive demain ! N'oublie pas de préparer sa chambre."
          title: "Arrivée prévue"
```

### 3. Allumer les lumières à l'arrivée

```yaml
automation:
  - alias: "Lumières à l'arrivée"
    description: "Allume les lumières quand l'enfant arrive"
    trigger:
      - platform: event
        event_type: custody_arrival
        event_data:
          entry_id: "1234567890abcdef1234567890abcdef"
    action:
      - service: light.turn_on
        target:
          entity_id: light.chambre_lucas
        data:
          brightness: 200
          color_temp: 370
```

### 4. Éteindre les appareils au départ

```yaml
automation:
  - alias: "Économie d'énergie au départ"
    description: "Éteint les appareils quand l'enfant part"
    trigger:
      - platform: event
        event_type: custody_departure
        event_data:
          entry_id: "1234567890abcdef1234567890abcdef"
    action:
      - service: light.turn_off
        target:
          entity_id: 
            - light.chambre_lucas
            - light.bureau_lucas
      - service: climate.set_preset_mode
        target:
          entity_id: climate.chambre_lucas
        data:
          preset_mode: "away"
```

### 5. Notification début de vacances

```yaml
automation:
  - alias: "Notification début vacances"
    description: "Notifie au début des vacances scolaires"
    trigger:
      - platform: event
        event_type: custody_vacation_start
        event_data:
          entry_id: "1234567890abcdef1234567890abcdef"
    action:
      - service: notify.mobile_app_telephone
        data:
          message: "Les vacances de {{ trigger.event.data.holiday }} commencent !"
          title: "Vacances scolaires"
```

### 6. Dashboard conditionnel

```yaml
type: entities
title: Planning de garde
entities:
  - entity: binary_sensor.lucas_planning_de_garde_presence
    name: Présence
  - entity: sensor.lucas_planning_de_garde_prochaine_arrivee
    name: Prochaine arrivée
  - entity: sensor.lucas_planning_de_garde_prochain_depart
    name: Prochain départ
  - entity: sensor.lucas_planning_de_garde_jours_restants
    name: Jours restants
  - entity: sensor.lucas_planning_de_garde_periode_actuelle
    name: Période
  - type: custom:auto-entities
    card:
      type: entities
      title: "Détails"
    filter:
      include:
        - entity_id: sensor.lucas_planning_de_garde_*
          attributes:
            - vacation_name
            - zone
            - location
```

### 7. Script pour forcer présence temporaire

```yaml
script:
  presence_temporaire:
    alias: "Forcer présence temporaire"
    sequence:
      - service: custody_schedule.override_presence
        data:
          entry_id: "1234567890abcdef1234567890abcdef"
          state: "on"
          duration: 180  # 3 heures
      - service: notify.mobile_app_telephone
        data:
          message: "Présence forcée pour 3 heures"
```

### 8. Automatisation basée sur les jours restants

```yaml
automation:
  - alias: "Préparer chambre 2 jours avant"
    description: "Active le chauffage 2 jours avant l'arrivée"
    trigger:
      - platform: numeric_state
        entity_id: sensor.lucas_planning_de_garde_jours_restants
        below: 2.5
        above: 1.5
    condition:
      - condition: state
        entity_id: binary_sensor.lucas_planning_de_garde_presence
        state: "off"
    action:
      - service: climate.set_preset_mode
        target:
          entity_id: climate.chambre_lucas
        data:
          preset_mode: "comfort"
```

## 🌐 API des vacances scolaires

L'intégration utilise l'API officielle du ministère de l'Éducation nationale (`data.education.gouv.fr`) pour récupérer automatiquement les dates des vacances scolaires.

### Fonctionnalités

- ✅ Récupération automatique des vacances par zone (A, B, C, Corse, DOM-TOM)
- ✅ Gestion des années scolaires (format "2024-2025")
- ✅ Cache intelligent pour réduire les appels API
- ✅ Support multi-entrées avec URLs d'API différentes
- ✅ Service de test pour diagnostiquer les problèmes

### Zones supportées

- **Zone A** : Besançon, Bordeaux, Clermont-Ferrand, Dijon, Grenoble, Limoges, Lyon, Poitiers
- **Zone B** : Aix-Marseille, Amiens, Lille, Nancy-Metz, Nantes, Nice, Normandie, Orléans-Tours, Reims, Rennes, Strasbourg
- **Zone C** : Créteil, Montpellier, Paris, Toulouse, Versailles
- **Corse** : Corse
- **DOM-TOM** : Guadeloupe (par défaut), Martinique, Guyane, La Réunion, Mayotte

### Personnalisation de l'API

Vous pouvez configurer une URL d'API personnalisée dans les options avancées. L'URL doit contenir les placeholders `{year}` et `{zone}`.

**Format attendu :**
```
https://api.example.com/holidays?year={year}&zone={zone}
```

### Tester l'API

Utilisez le service `custody_schedule.test_holiday_api` pour tester la connexion :

```yaml
service: custody_schedule.test_holiday_api
data:
  zone: "A"
  year: "2024-2025"
```

Les résultats sont disponibles dans les logs Home Assistant (Paramètres → Système → Logs).

## 🗺️ Roadmap

### v1.0 ✅
- [x] Configuration UI complète
- [x] Calcul automatique des périodes
- [x] API vacances scolaires
- [x] Services et événements
- [x] Support multi-enfants
- [x] URL API personnalisable
- [x] Service de test API

### v1.1 (à venir)
- [ ] Calendrier avancé avec vue mensuelle
- [ ] Synchronisation Google Calendar
- [ ] Notifications natives Home Assistant
- [ ] Gestion d'exceptions avancée
- [ ] Export PDF du planning

### v1.2 (à venir)
- [ ] Statistiques (temps passé, répartition)
- [ ] Internationalisation avancée
- [ ] Templates Lovelace prêts à l'emploi
- [ ] Intégration avec d'autres calendriers

### v2.0 (futur)
- [ ] Mode co-parent avec synchronisation
- [ ] Application mobile companion
- [ ] Journal partagé
- [ ] Gestion financière

## 🤝 Contribution

Les contributions sont les bienvenues ! Pour contribuer :

1. **Fork** le projet
2. **Créer** une branche pour votre fonctionnalité (`git checkout -b feature/AmazingFeature`)
3. **Commit** vos changements (`git commit -m 'Add some AmazingFeature'`)
4. **Push** vers la branche (`git push origin feature/AmazingFeature`)
5. **Ouvrir** une Pull Request

### Développement

Pour développer localement :

```bash
# Cloner le dépôt
git clone https://github.com/Jackngl/custody-v1.git
cd custody-v1

# Installer dans Home Assistant
cp -r custom_components/custody_schedule /config/custom_components/
```

### Tests

Les tests peuvent être effectués via le service de test de l'API :

```yaml
service: custody_schedule.test_holiday_api
data:
  zone: "A"
```

## 📝 Licence

MIT © Custody Schedule

## 🙏 Remerciements

Merci à :
- La communauté Home Assistant pour son support
- Le ministère de l'Éducation nationale pour l'API des vacances scolaires
- Tous les parents en garde alternée qui utilisent cette intégration

## 📞 Support

- **Issues** : [GitHub Issues](https://github.com/Jackngl/custody-v1/issues)
- **Documentation** : Ce README
- **Logs** : Vérifiez les logs Home Assistant pour diagnostiquer les problèmes

---

**Fait avec ❤️ pour les familles en garde alternée**
