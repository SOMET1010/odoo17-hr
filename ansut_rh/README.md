# RH ANSUT — Congés, absences et intégration

Module Odoo 17 qui implémente les procédures RH de l'ANSUT dans les
modules standard **Employés** (`hr`) et **Congés** (`hr_holidays`).

## Correspondance procédure → fonctionnalité

### ANSUT-RH-PR-001 — Gérer les congés

| Règle de la procédure | Implémentation |
|---|---|
| Demande déposée au plus tard la 1ère semaine du mois précédant le départ (règle 3) | Contrôle bloquant à la création d'une demande de type « congé annuel ANSUT ». Les officiers Congés (DRHCom) ne sont pas bloqués (régularisations). |
| Validation hiérarchie puis RH (étapes 6-7) | Type « Congés annuels (ANSUT) » configuré en **double validation** (responsable + RH). |
| Refus motivé et communiqué (étape 7) | Bouton **Refuser avec motif** : motif obligatoire, archivé dans le chatter et sur la demande. |
| Attestation de départ en congé (étape 8) | Rapport PDF **Attestation de départ en congé** (menu Imprimer de la demande). |
| Reprise de service (étapes 9-12) | Bouton **Confirmer la reprise** (date de reprise effective) + rapport PDF **Attestation de reprise de service**. |
| Alerte non-reprise (règle 6) | Cron quotidien : congé terminé sans reprise confirmée → activité au responsable congés du salarié. |
| Cumul maximum de 45 jours (règle 7) | Blocage à la validation d'une allocation dépassant 45 jours restants. |
| Rachat/dépassement sur décision DG (règle 8) | Groupe « **ANSUT : dérogation cumul congés (décision DG)** » qui lève le blocage. |
| Planning annuel des congés (étapes 1-5) | Utiliser les vues standard (calendrier/planning des congés par département) ; les demandes validées alimentent automatiquement le planning. |

### ANSUT-RH-PR-002 — Gérer les absences

| Règle | Implémentation |
|---|---|
| Absence ≤ 1 jour autorisée par le supérieur (règle 1) | Type « Autorisation d'absence (≤ 1 jour) », validation **responsable**, durée max contrôlée (1 jour). |
| Absence > 1 jour autorisée par le Directeur (règle 1) | Type « Autorisation d'absence (> 1 jour) », **double validation**. |
| Rejets motivés et archivés (règle 3) | Même assistant « Refuser avec motif » que les congés. |
| Registre des absences (étape 6) | Menu **Congés → Registre des absences** (liste + tableau croisé, réservé aux officiers). |
| Prise en compte dans la paie (étape 7) | Les types d'absence sont visibles de la paie via les entrées de travail standard ; configurer le caractère payé/non payé sur le type selon votre politique. |

### ANSUT-RH-PR-004 — Gérer l'intégration du personnel

| Règle | Implémentation |
|---|---|
| Liste des 12 pièces administratives (règle 3) | Dossier d'intégration pré-rempli avec la liste officielle, cases « Reçue » + date. |
| Kit d'intégration DRHCom / DJMG / DSIS (étape 3) | Liste pré-remplie des 12 éléments du kit, chacun rattaché à sa direction responsable. |
| Accompagnateur d'intégration (étape 4) | Champ dédié sur le dossier. |
| Suivi et relances | Chatter + activités sur chaque dossier ; avancement en % (pièces et kit). Menu **Employés → Intégrations (ANSUT)**. |

## Installation

1. Copier `ansut_rh` dans le chemin des addons (nécessite `hr` et `hr_holidays`).
2. Mettre à jour la liste des applications et installer **RH ANSUT**.
3. Vérifier les trois types de congé créés (Configuration → Types de congés)
   et adapter si besoin (payé/non payé, plafonds…).
4. Attribuer le groupe « ANSUT : dérogation cumul congés » aux personnes
   habilitées à porter les décisions du DG.

## Limites connues / volontaires

- Le circuit « papier » (visa physique de l'attestation) reste possible :
  les attestations sont générées en PDF, les visas peuvent être apposés
  manuellement ou via le module Signature si vous le déployez.
- L'élaboration du planning annuel (collecte par direction avant le 15
  décembre) utilise les écrans standard de planification des congés ;
  un rappel automatique annuel peut être ajouté sur demande.
