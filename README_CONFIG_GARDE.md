# 📖 Guide de Configuration - Gestion de Garde Normale

Ce guide explique comment configurer la **garde normale** (weekends et semaines alternées) dans l'application Planning de garde.

> ⚠️ **Note** : Ce guide concerne uniquement la garde normale. Pour les vacances scolaires, voir la documentation des règles de vacances.

---

## 📋 Table des matières

1. [Types de garde disponibles](#types-de-garde-disponibles)
2. [Configuration de base](#configuration-de-base)
3. [Types de garde détaillés](#types-de-garde-détaillés)
4. [Gestion des jours fériés](#gestion-des-jours-fériés)
5. [Exemples de configuration](#exemples-de-configuration)

---

## 🎯 Types de garde disponibles

L'application supporte plusieurs types de garde pour les weekends et semaines :

| Type | Description | Utilisation |
|------|-------------|-------------|
| **Week-ends semaines paires** | Garde tous les weekends des semaines ISO paires | Garde régulière basée sur la parité des semaines |
| **Week-ends semaines impaires** | Garde tous les weekends des semaines ISO impaires | Alternative aux weekends pairs |
| **Week-ends alternés** | Garde un weekend sur deux (cycle de 14 jours) | Garde alternée classique |
| **Semaines alternées** | Garde une semaine sur deux (cycle de 14 jours) | Garde hebdomadaire alternée |

---

## ⚙️ Configuration de base

### Champs obligatoires

#### 1. **Type de garde** (`custody_type`)
- **Description** : Définit le rythme de garde (weekends pairs, alternés, etc.)
- **Valeurs** : Voir [Types de garde disponibles](#types-de-garde-disponibles)
- **Exemple** : `"even_weekends"` pour les weekends semaines paires

#### 2. **Année de référence** (`reference_year`)
- **Description** : Année de référence pour déterminer la parité (paire ou impaire)
- **Valeurs** :
  - `"even"` : Année paire (2024, 2026, ...)
  - `"odd"` : Année impaire (2025, 2027, ...)
- **Utilisation** : Détermine quel parent a la garde selon la parité de l'année
- **Exemple** : Si `"odd"` et que nous sommes en 2025 (impaire), vous avez la garde

#### 3. **Heure d'arrivée** (`arrival_time`)
- **Description** : Heure à laquelle vous récupérez l'enfant
- **Format** : `HH:MM` (ex: `16:15`)
- **Utilisation** : Vendredi après l'école pour les weekends
- **Exemple** : `"16:15"` (sortie d'école primaire)

#### 4. **Heure de départ** (`departure_time`)
- **Description** : Heure à laquelle vous ramenez l'enfant
- **Format** : `HH:MM` (ex: `19:00`)
- **Utilisation** : Dimanche soir pour les weekends
- **Exemple** : `"19:00"` (dimanche soir)

### Champs optionnels

#### 5. **Jour de départ du cycle** (`start_day`)
- **Description** : Jour de la semaine qui marque le début du cycle de garde
- **Valeurs** : `"monday"`, `"tuesday"`, `"wednesday"`, `"thursday"`, `"friday"`, `"saturday"`, `"sunday"`
- **Utilisation** : 
  - ✅ **Utilisé pour** : `alternate_weekend`, `alternate_week`
  - ❌ **Non utilisé pour** : `even_weekends`, `odd_weekends` (basé sur la parité ISO)
- **Défaut** : `"monday"` (ou `"friday"` pour les weekends)
- **Note** : Pour les weekends pairs/impairs, ce champ est masqué car non applicable

#### 6. **Niveau scolaire** (`school_level`)
- **Description** : Niveau scolaire de l'enfant (affecte les horaires de sortie)
- **Valeurs** :
  - `"primary"` : Primaire (sortie généralement 16:15)
  - `"middle"` : Collège
  - `"high"` : Lycée
- **Défaut** : `"primary"`

#### 7. **Lieu d'échange** (`location`)
- **Description** : Lieu où se fait l'échange de garde
- **Format** : Texte libre
- **Exemple** : `"École élémentaire"`, `"Domicile"`

---

## 📅 Types de garde détaillés

### 1. Week-ends semaines paires (`even_weekends`)

**Fonctionnement** :
- Garde tous les weekends des **semaines ISO paires** (S2, S4, S6, S8, ...)
- Basé sur le numéro ISO de la semaine (pas sur un cycle personnalisé)
- **Le champ "Jour de départ du cycle" n'est pas utilisé** (masqué dans l'interface)

**Exemple** :
- Semaine ISO 18 (paire) → ✅ Garde
- Semaine ISO 19 (impaire) → ❌ Pas de garde
- Semaine ISO 20 (paire) → ✅ Garde

**Configuration** :
```yaml
custody_type: "even_weekends"
reference_year: "odd"  # ou "even" selon votre situation
arrival_time: "16:15"  # Vendredi sortie école
departure_time: "19:00"  # Dimanche soir
# start_day n'est pas utilisé pour ce type
```

**Calendrier type (Mai 2025)** :
- ✅ S18 : Ven 02/05 16:15 → Dim 04/05 19:00
- ❌ S19 : Pas de garde
- ✅ S20 : Ven 16/05 16:15 → Dim 18/05 19:00
- ❌ S21 : Pas de garde
- ✅ S22 : Ven 30/05 16:15 → Dim 01/06 19:00

---

### 2. Week-ends semaines impaires (`odd_weekends`)

**Fonctionnement** :
- Garde tous les weekends des **semaines ISO impaires** (S1, S3, S5, S7, ...)
- Complémentaire de `even_weekends`
- **Le champ "Jour de départ du cycle" n'est pas utilisé**

**Configuration** :
```yaml
custody_type: "odd_weekends"
reference_year: "even"  # ou "odd"
arrival_time: "16:15"
departure_time: "19:00"
```

---

### 3. Week-ends alternés (`alternate_weekend`)

**Fonctionnement** :
- Garde **un weekend sur deux** (cycle de 14 jours)
- Cycle : 12 jours "off" + 2 jours "on" (weekend)
- Utilise le champ `start_day` pour déterminer le vendredi de départ
- Utilise `reference_year` pour déterminer la phase du cycle

**Configuration** :
```yaml
custody_type: "alternate_weekend"
reference_year: "even"  # ou "odd"
start_day: "friday"  # Jour de départ du cycle
arrival_time: "16:15"
departure_time: "19:00"
```

**Exemple de cycle** :
- Semaine 1 : ❌ Pas de garde
- Semaine 2 : ✅ Ven 16:15 → Dim 19:00
- Semaine 3 : ❌ Pas de garde
- Semaine 4 : ✅ Ven 16:15 → Dim 19:00

---

### 4. Semaines alternées (`alternate_week`)

**Fonctionnement** :
- Garde **une semaine complète sur deux** (cycle de 14 jours)
- Cycle : 7 jours "on" + 7 jours "off"
- Utilise le champ `start_day` pour déterminer le jour de départ

**Configuration** :
```yaml
custody_type: "alternate_week"
reference_year: "even"
start_day: "monday"  # Début de la semaine de garde
arrival_time: "08:00"
departure_time: "19:00"
```

---

## 🎉 Gestion des jours fériés

L'application **étend automatiquement** les weekends de garde lorsqu'un jour férié tombe sur un vendredi ou un lundi.

### Règles d'extension

| Situation | Garde normale | Garde avec férié |
|-----------|---------------|------------------|
| **Lundi férié** | Ven 16:15 → Dim 19:00 | Ven 16:15 → **Lun 19:00** |
| **Vendredi férié** | Ven 16:15 → Dim 19:00 | **Jeu 16:15** → Dim 19:00 |
| **Pont (les deux)** | Ven 16:15 → Dim 19:00 | **Jeu 16:15 → Lun 19:00** |

### Jours fériés pris en compte

**Jours fixes** :
- 1er janvier (Jour de l'An)
- 1er mai (Fête du Travail)
- 8 mai (Victoire 1945)
- 14 juillet (Fête Nationale)
- 15 août (Assomption)
- 1er novembre (Toussaint)
- 11 novembre (Armistice)
- 25 décembre (Noël)

**Jours variables** (basés sur Pâques) :
- Lundi de Pâques
- Jeudi de l'Ascension
- Lundi de Pentecôte

### Exemples

**Exemple 1 : Lundi de Pâques (21 avril 2025)**
```
Weekend S16 (semaine paire) :
- Normal : Ven 18/04 16:15 → Dim 20/04 19:00
- Avec férié : Ven 18/04 16:15 → Lun 21/04 19:00 ✅
```

**Exemple 2 : Vendredi 15 août (Assomption)**
```
Weekend S33 (semaine paire) :
- Normal : Ven 15/08 16:15 → Dim 17/08 19:00
- Avec férié : Jeu 14/08 16:15 → Dim 17/08 19:00 ✅
```

**Exemple 3 : Pont (Vendredi + Lundi fériés)**
```
Weekend avec pont :
- Normal : Ven 16:15 → Dim 19:00
- Avec pont : Jeu 16:15 → Lun 19:00 ✅ (4 jours de garde)
```

### Labels dans le calendrier

Les événements de garde affichent automatiquement les extensions :
- `Garde - Week-ends semaines paires + Lundi férié`
- `Garde - Week-ends semaines paires + Vendredi férié`
- `Garde - Week-ends semaines paires + Pont`

---

## 📝 Exemples de configuration

### Exemple 1 : Weekends pairs (configuration recommandée)

**Situation** : Vous avez la garde tous les weekends des semaines paires, année de référence impaire.

```yaml
# Configuration
custody_type: "even_weekends"
reference_year: "odd"
arrival_time: "16:15"      # Vendredi sortie école
departure_time: "19:00"    # Dimanche soir
school_level: "primary"
location: "École élémentaire"

# Résultat (Mai 2025)
# ✅ S18 : Ven 02/05 16:15 → Dim 04/05 19:00
# ❌ S19 : Pas de garde
# ✅ S20 : Ven 16/05 16:15 → Dim 18/05 19:00
# ❌ S21 : Pas de garde
# ✅ S22 : Ven 30/05 16:15 → Dim 01/06 19:00
```

### Exemple 2 : Weekends alternés

**Situation** : Garde un weekend sur deux, cycle commençant le vendredi.

```yaml
# Configuration
custody_type: "alternate_weekend"
reference_year: "even"
start_day: "friday"
arrival_time: "16:15"
departure_time: "19:00"
school_level: "primary"

# Résultat (cycle de 14 jours)
# Semaine 1 : ❌ Pas de garde
# Semaine 2 : ✅ Ven 16:15 → Dim 19:00
# Semaine 3 : ❌ Pas de garde
# Semaine 4 : ✅ Ven 16:15 → Dim 19:00
```

### Exemple 3 : Semaines alternées

**Situation** : Garde une semaine complète sur deux, début le lundi.

```yaml
# Configuration
custody_type: "alternate_week"
reference_year: "even"
start_day: "monday"
arrival_time: "08:00"      # Lundi matin
departure_time: "19:00"    # Dimanche soir
school_level: "primary"

# Résultat (cycle de 14 jours)
# Semaine 1 : ✅ Lun 08:00 → Dim 19:00 (7 jours)
# Semaine 2 : ❌ Pas de garde
# Semaine 3 : ✅ Lun 08:00 → Dim 19:00 (7 jours)
```

---

## ⚠️ Notes importantes

### Priorité des règles

1. **Vacances scolaires** (priorité absolue)
   - Pendant les vacances, les règles de garde normale sont **complètement ignorées**
   - Les jours fériés pendant les vacances sont également ignorés
   - Seules les règles de vacances s'appliquent

2. **Jours fériés** (extension des weekends)
   - S'appliquent uniquement aux weekends de garde normale
   - N'ont aucun effet pendant les vacances scolaires

3. **Garde normale** (weekends/semaines)
   - S'applique uniquement hors vacances scolaires
   - Respecte les jours fériés pour l'extension

### Champ "Jour de départ du cycle"

- ✅ **Utilisé pour** : `alternate_weekend`, `alternate_week`
- ❌ **Non utilisé pour** : `even_weekends`, `odd_weekends`
  - Ces types utilisent la parité ISO des semaines
  - Le champ est masqué dans l'interface pour ces types

### Format des heures

- **Format attendu** : `HH:MM` (ex: `16:15`, `19:00`)
- **Format accepté** : `HH:MM:SS` (les secondes sont ignorées)
- **Validation** : Heures 00-23, Minutes 00-59

---

## 🔍 Vérification de la configuration

### Comment vérifier que votre configuration est correcte ?

1. **Vérifiez les weekends générés** :
   - Allez dans le calendrier Home Assistant
   - Les événements de garde doivent apparaître aux bons weekends
   - Les labels doivent indiquer les extensions fériées si applicable

2. **Vérifiez les attributs** :
   - `next_arrival` : Prochaine date/heure de garde
   - `next_departure` : Prochaine date/heure de fin de garde
   - `custody_type` : Type de garde configuré

3. **Testez avec un jour férié** :
   - Vérifiez qu'un weekend avec lundi férié s'étend bien au lundi
   - Vérifiez qu'un weekend avec vendredi férié commence bien le jeudi

---

## 📞 Support

Pour toute question sur la configuration de la garde normale :
- Consultez la documentation complète dans le README principal
- Vérifiez les logs Home Assistant pour les erreurs
- Les règles de vacances sont documentées séparément

---

**Dernière mise à jour** : Version 1.0.54

