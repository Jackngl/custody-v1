# 📖 Guide de Configuration - Garde Classique (Weekends/Semaines)

Ce guide explique comment configurer la **garde classique** (weekends et semaines alternées) dans l'application Planning de garde.

> ⚠️ **Important** : 
> - Ce guide concerne **uniquement la garde classique** (hors vacances scolaires)
> - Les **vacances scolaires** sont configurées séparément et ont **priorité absolue** sur la garde classique
> - Les **jours fériés** (vendredi/lundi) étendent automatiquement les weekends de garde classique
> - Pour les vacances scolaires, voir la documentation séparée des règles de vacances

---

## 📋 Table des matières

1. [Séparation garde classique / vacances scolaires](#séparation-garde-classique--vacances-scolaires)
2. [Types de garde disponibles](#types-de-garde-disponibles)
3. [Configuration de base](#configuration-de-base)
4. [Types de garde détaillés](#types-de-garde-détaillés)
5. [Gestion des jours fériés](#gestion-des-jours-fériés)
6. [Exemples de configuration](#exemples-de-configuration)

---

## 🔀 Séparation garde classique / vacances scolaires

L'application sépare clairement **deux systèmes de garde indépendants** :

### 1. **Garde classique** (ce guide)
- **Configuration** : Masque de saisie "Garde classique (weekends/semaines)"
- **Période** : Hors vacances scolaires uniquement
- **Fonctionnalités** :
  - Weekends alternés, semaines alternées, rythmes 2-2-3, etc.
  - Extension automatique avec jours fériés (vendredi/lundi)
  - Basé sur cycles ou parité ISO des semaines

### 2. **Vacances scolaires** (documentation séparée)
- **Configuration** : Masque de saisie "Vacances scolaires"
- **Période** : Pendant les vacances scolaires uniquement
- **Fonctionnalités** :
  - Règles par moitié, par semaine, par parité d'année
  - Calcul automatique du milieu exact des vacances
  - Priorité absolue sur la garde classique

### ⚠️ Règle de priorité

```
Vacances scolaires > Jours fériés > Garde classique
```

- **Pendant les vacances** : Seules les règles de vacances s'appliquent
- **Hors vacances** : La garde classique s'applique, avec extension fériée si applicable
- **Jours fériés pendant vacances** : Ignorés (les vacances priment déjà)

---

---

## 🎯 Types de garde disponibles

L'application supporte **6 types de garde** pour les weekends et semaines :

| Type | Code | Description | Cycle | Utilisation |
|------|------|-------------|-------|-------------|
| **Semaines alternées (1/1)** | `alternate_week` | Garde hebdomadaire sur 2 semaines (14j) alternées | 14 jours | Garde hebdomadaire alternée classique (basée sur date de référence) |
| **Semaines alternées** | `alternate_week_parity` | Garde selon parité ISO des semaines (pair/impair via année de référence) | 7 jours | Basé sur la parité ISO des semaines |
| **Week-ends alternés** | `alternate_weekend` | Garde selon parité ISO des semaines (pair/impair via année de référence) | 7 jours | Basé sur la parité ISO des semaines |
| **2-2-3** | `two_two_three` | Garde 2 jours, pause 2 jours, garde 3 jours | 7 jours | Rythme hebdomadaire régulier |
| **2-2-5-5** | `two_two_five_five` | Garde 2 jours, pause 2 jours, garde 5 jours, pause 5 jours | 14 jours | Rythme bi-hebdomadaire |
| **Personnalisé** | `custom` | Règles personnalisées définies manuellement | Variable | Cas spécifiques |

---

## ⚙️ Configuration de base

### Champs obligatoires

#### 1. **Type de garde** (`custody_type`)
- **Description** : Définit le rythme de garde (weekends pairs, alternés, etc.)
- **Valeurs** : Voir [Types de garde disponibles](#types-de-garde-disponibles)
- **Exemple** : `"alternate_weekend"` pour les weekends des semaines paires/impaires

#### 2. **Mon année de garde (parité)** (`reference_year_custody`)
- **Description** : Détermine si vous avez la garde les années paires ou impaires (pour les week-ends/semaines).
- **Valeurs** :
  - `"Paire"` : Vous avez la garde lors des semaines ISO paires (2024, 2026, ...).
  - `"Impaire"` : Vous avez la garde lors des semaines ISO impaires (2025, 2027, ...).
- **Note** : Ce champ calibre l'alternance de base. Les vacances scolaires alternent ensuite automatiquement chaque année à partir de cette base.

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

#### 5. **Jour de départ** (`start_day`)
- **Description** : Jour marquant le début de votre semaine de garde (généralement le lundi).
- **Valeurs** : `"monday"`, `"tuesday"`, `"wednesday"`, `"thursday"`, `"friday"`, `"saturday"`, `"sunday"`
- **Utilisation** : 
  - ✅ **Utilisé pour** : `alternate_week`, `two_two_three`, `two_two_five_five`, `custom`
- ❌ **Non utilisé pour** : `alternate_weekend`, `alternate_week_parity` (basé sur la parité ISO via `reference_year_custody`)
- **Défaut** : `"monday"`
- **Note** : Pour les week-ends/semaines parité ISO, le cycle est **toujours ancré au lundi** (champ masqué dans l'interface)

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

### 1. Week-ends alternés (`alternate_weekend`)

**Fonctionnement** :
- Garde selon la **parité ISO des semaines** (paires ou impaires)
- La parité est déterminée par le champ `reference_year_custody` :
  - `reference_year_custody: "even"` → garde les weekends des semaines ISO **paires** (S2, S4, S6, S8, ...)
  - `reference_year_custody: "odd"` → garde les weekends des semaines ISO **impaires** (S1, S3, S5, S7, ...)
- Basé sur le numéro ISO de la semaine (pas sur un cycle personnalisé)
- **Le champ "Jour de départ du cycle" n'est pas utilisé** (masqué dans l'interface)

**Configuration** :
```yaml
custody_type: "alternate_weekend"
reference_year_custody: "even"  # "even" = weekends semaines paires, "odd" = weekends semaines impaires
arrival_time: "16:15"  # Vendredi sortie école
departure_time: "19:00"  # Dimanche soir
# start_day n'est pas utilisé pour ce type
```

**Exemple** (`reference_year_custody: "even"` = weekends semaines paires) :
- Semaine ISO 18 (paire) → ✅ Garde
- Semaine ISO 19 (impaire) → ❌ Pas de garde
- Semaine ISO 20 (paire) → ✅ Garde

**Calendrier type (Mai 2025, `reference_year_custody: "even"`)** :
- ✅ S18 : Ven 02/05 16:15 → Dim 04/05 19:00
- ❌ S19 : Pas de garde
- ✅ S20 : Ven 16/05 16:15 → Dim 18/05 19:00
- ❌ S21 : Pas de garde
- ✅ S22 : Ven 30/05 16:15 → Dim 01/06 19:00

---

### 2. Semaines alternées (`alternate_week`)

**Fonctionnement** :
- Garde **une semaine complète sur deux** (cycle de 14 jours)
- Cycle : 7 jours "on" + 7 jours "off"
- Utilise le champ `start_day` pour déterminer le jour de départ

**Configuration** :
```yaml
custody_type: "alternate_week"
reference_year_custody: "even"
start_day: "monday"  # Début de la semaine de garde
arrival_time: "08:00"
departure_time: "19:00"
```

**Exemple de cycle** :
- Semaine 1 : ✅ Lun 08:00 → Dim 19:00 (7 jours)
- Semaine 2 : ❌ Pas de garde
- Semaine 3 : ✅ Lun 08:00 → Dim 19:00 (7 jours)

---

### 3. Semaines alternées (`alternate_week_parity`)

**Fonctionnement** :
- Garde selon la **parité ISO des semaines** (paires ou impaires)
- La parité est déterminée par le champ `reference_year_custody` :
  - `reference_year_custody: "even"` → garde les semaines ISO **paires**
  - `reference_year_custody: "odd"` → garde les semaines ISO **impaires**
- Cycle : 7 jours (une semaine complète)
- **Ne nécessite pas** le champ `start_day` (basé sur la parité ISO)

**Configuration** :
```yaml
custody_type: "alternate_week_parity"
reference_year_custody: "even"  # "even" = semaines paires, "odd" = semaines impaires
arrival_time: "08:00"
departure_time: "19:00"
```

**Exemple de cycle** (`reference_year_custody: "even"` = semaines paires) :
- Semaine ISO 2 : ✅ Lun 08:00 → Dim 19:00 (7 jours)
- Semaine ISO 3 : ❌ Pas de garde
- Semaine ISO 4 : ✅ Lun 08:00 → Dim 19:00 (7 jours)
- Semaine ISO 5 : ❌ Pas de garde

**Différence avec `alternate_week`** :
- `alternate_week` : Basé sur une date de référence et un cycle de 14 jours (1 semaine sur 2)
- `alternate_week_parity` : Basé sur la parité ISO des semaines (toutes les semaines paires ou impaires selon `reference_year_custody`)

---

### 5. Rythme 2-2-3 (`two_two_three`)

**Fonctionnement** :
- Garde **2 jours**, pause **2 jours**, garde **3 jours** (cycle de 7 jours)
- Pattern répété chaque semaine
- Utilise le champ `start_day` pour déterminer le jour de départ du cycle

**Configuration** :
```yaml
custody_type: "two_two_three"
reference_year_custody: "even"
start_day: "monday"  # Jour de départ du cycle
arrival_time: "08:00"
departure_time: "19:00"
```

**Exemple de cycle (7 jours)** :
- Jours 1-2 : ✅ Garde (ex: Lun-Mar)
- Jours 3-4 : ❌ Pas de garde (ex: Mer-Jeu)
- Jours 5-7 : ✅ Garde (ex: Ven-Dim)
- Puis le cycle recommence

**Calendrier type** :
```
Semaine 1 :
  ✅ Lun 08:00 → Mar 19:00 (2 jours)
  ❌ Mer-Jeu (pas de garde)
  ✅ Ven 08:00 → Dim 19:00 (3 jours)

Semaine 2 :
  ✅ Lun 08:00 → Mar 19:00 (2 jours)
  ❌ Mer-Jeu (pas de garde)
  ✅ Ven 08:00 → Dim 19:00 (3 jours)
```

---

### 5. Rythme 2-2-5-5 (`two_two_five_five`)

**Fonctionnement** :
- Garde **2 jours**, pause **2 jours**, garde **5 jours**, pause **5 jours** (cycle de 14 jours)
- Pattern répété toutes les 2 semaines
- Utilise le champ `start_day` pour déterminer le jour de départ du cycle

**Configuration** :
```yaml
custody_type: "two_two_five_five"
reference_year_custody: "even"
start_day: "monday"  # Jour de départ du cycle
arrival_time: "08:00"
departure_time: "19:00"
```

**Exemple de cycle (14 jours)** :
- Jours 1-2 : ✅ Garde (ex: Lun-Mar)
- Jours 3-4 : ❌ Pas de garde (ex: Mer-Jeu)
- Jours 5-9 : ✅ Garde (ex: Ven-Mar suivant)
- Jours 10-14 : ❌ Pas de garde
- Puis le cycle recommence

**Calendrier type** :
```
Semaine 1 :
  ✅ Lun 08:00 → Mar 19:00 (2 jours)
  ❌ Mer-Jeu (pas de garde)
  ✅ Ven 08:00 → Mar suivant 19:00 (5 jours)

Semaine 2 :
  ❌ Mer-Dim (pas de garde, 5 jours)

Semaine 3 :
  ✅ Lun 08:00 → Mar 19:00 (2 jours)
  ❌ Mer-Jeu (pas de garde)
  ✅ Ven 08:00 → Mar suivant 19:00 (5 jours)
  ...
```

---

### 6. Personnalisé (`custom`)

**Fonctionnement** :
- Règles de garde définies manuellement via les exceptions ou règles personnalisées
- Permet de créer des patterns spécifiques non couverts par les types standards
- Nécessite une configuration manuelle des périodes

**Configuration** :
```yaml
custody_type: "custom"
# Les périodes sont définies via les règles personnalisées dans les options
```

**Utilisation** :
- Accédez aux options de l'intégration
- Utilisez les règles personnalisées pour définir vos périodes
- Ou utilisez le service `set_manual_dates` pour définir des périodes spécifiques

---

## 🎉 Gestion des jours fériés

L'application **étend automatiquement** les weekends et semaines de garde lorsqu'un jour férié tombe sur un vendredi ou un lundi.

> ⚠️ **Important** : Les extensions de jours fériés **ne s'appliquent PAS** si le weekend ou la semaine tombe pendant une **période de vacances scolaires**. Les vacances scolaires ont priorité absolue et utilisent leur propre logique.

### Règles d'extension

| Situation | Garde normale | Garde avec férié |
|-----------|---------------|------------------|
| **Lundi férié** | Ven 16:15 → Dim 19:00 | Ven 16:15 → **Lun 19:00** |
| **Vendredi férié** | Ven 16:15 → Dim 19:00 | **Jeu 16:15** → Dim 19:00 |
| **Pont (les deux)** | Ven 16:15 → Dim 19:00 | **Jeu 16:15 → Lun 19:00** |

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
- `Garde - Semaines alternées - semaines paires + Lundi férié`
- `Garde - Semaines alternées - semaines paires + Vendredi férié`

---

## 📊 Tableau récapitulatif des types de garde

| Type | Cycle | Utilise start_day | Utilise reference_year_custody | Jours fériés |
|------|-------|-------------------|------------------------|--------------|
| `alternate_week` | 14 jours | ✅ Oui | ✅ Oui | ❌ Non |
| `alternate_week_parity` | 7 jours | ❌ Non | ✅ Oui (détermine parité) | ✅ Oui |
| `alternate_weekend` | 7 jours | ❌ Non | ✅ Oui (détermine parité) | ✅ Oui |
| `two_two_three` | 7 jours | ✅ Oui | ✅ Oui | ❌ Non |
| `two_two_five_five` | 14 jours | ✅ Oui | ✅ Oui | ❌ Non |
| `custom` | Variable | ✅ Oui | ✅ Oui | ❌ Non |

**Note** : Les types de garde basés sur la parité ISO (`alternate_weekend`, `alternate_week_parity`) utilisent `reference_year_custody` pour déterminer la parité (pair/impair) et bénéficient de l'extension automatique avec les jours fériés, **uniquement hors vacances scolaires**.

---

## 📝 Exemples de configuration

### Exemple 1 : Weekends pairs (configuration recommandée)

**Situation** : Vous avez la garde tous les weekends des semaines paires.

```yaml
# Configuration
custody_type: "alternate_weekend"
reference_year_custody: "even"
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

### Exemple 2 : Semaines alternées

**Situation** : Garde une semaine complète sur deux, début le lundi.

```yaml
# Configuration
custody_type: "alternate_week"
reference_year_custody: "even"
start_day: "monday"
arrival_time: "08:00"      # Lundi matin
departure_time: "19:00"    # Dimanche soir
school_level: "primary"

# Résultat (cycle de 14 jours)
# Semaine 1 : ✅ Lun 08:00 → Dim 19:00 (7 jours)
# Semaine 2 : ❌ Pas de garde
# Semaine 3 : ✅ Lun 08:00 → Dim 19:00 (7 jours)
```

### Exemple 3 : Rythme 2-2-3

**Situation** : Garde 2 jours, pause 2 jours, garde 3 jours, cycle hebdomadaire.

```yaml
# Configuration
custody_type: "two_two_three"
reference_year_custody: "even"
start_day: "monday"
arrival_time: "08:00"
departure_time: "19:00"
school_level: "primary"

# Résultat (cycle de 7 jours, répété chaque semaine)
# Semaine 1 :
#   ✅ Lun 08:00 → Mar 19:00 (2 jours)
#   ❌ Mer-Jeu (pas de garde)
#   ✅ Ven 08:00 → Dim 19:00 (3 jours)
# Semaine 2 : Même pattern
```

### Exemple 4 : Rythme 2-2-5-5

**Situation** : Garde 2 jours, pause 2 jours, garde 5 jours, pause 5 jours, cycle bi-hebdomadaire.

```yaml
# Configuration
custody_type: "two_two_five_five"
reference_year_custody: "even"
start_day: "monday"
arrival_time: "08:00"
departure_time: "19:00"
school_level: "primary"

# Résultat (cycle de 14 jours)
# Semaine 1 :
#   ✅ Lun 08:00 → Mar 19:00 (2 jours)
#   ❌ Mer-Jeu (pas de garde)
#   ✅ Ven 08:00 → Mar suivant 19:00 (5 jours)
# Semaine 2 :
#   ❌ Mer-Dim (pas de garde, 5 jours)
# Puis le cycle recommence
```

---

## ⚠️ Notes importantes

### Séparation des configurations

L'application utilise **deux masques de saisie distincts** :

1. **Masque "Garde classique"** :
   - Type de garde (alternate_week, alternate_weekend, etc.)
   - Année de référence
   - Horaires d'arrivée/départ
   - Jour de départ du cycle
   - Niveau scolaire
   - Lieu d'échange
   - **+ Extension automatique avec jours fériés**

2. **Masque "Vacances scolaires"** :
   - Zone scolaire (A/B/C)
   - Répartition des moitiés
   - **L'été est automatiquement divisé selon cette même règle.**

### Priorité des règles

1. **Vacances scolaires** (priorité absolue)
   - Pendant les vacances, les règles de garde classique sont **complètement ignorées**
   - Les jours fériés pendant les vacances sont également ignorés
   - Seules les règles de vacances s'appliquent
   - **Configuré dans le masque "Vacances scolaires"**

2. **Jours fériés** (extension des weekends)
   - S'appliquent uniquement aux weekends de garde classique
   - N'ont aucun effet pendant les vacances scolaires
   - **Géré automatiquement** dans la garde classique

3. **Garde classique** (weekends/semaines)
   - S'applique uniquement hors vacances scolaires
   - Respecte les jours fériés pour l'extension
   - **Configuré dans le masque "Garde classique"**

### Champ "Jour de départ du cycle"

- ✅ **Utilisé pour** : 
  - `alternate_week` (semaines alternées)
  - `two_two_three` (rythme 2-2-3)
  - `two_two_five_five` (rythme 2-2-5-5)
  - `custom` (personnalisé)
- ❌ **Non utilisé pour** : `alternate_weekend`, `alternate_week_parity`
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

**Dernière mise à jour** : Version 1.4.0

 