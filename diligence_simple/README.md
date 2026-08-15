# Diligences — gestion de tâches simplifiée

Application Odoo 17 qui offre une interface **volontairement épurée** pour gérer
les diligences (tâches), sans la complexité du module Projet complet.

## Pourquoi ?

Le module Projet standard d'Odoo est puissant mais chargé : étapes par projet,
feuilles de temps, jalons, dépendances… Pour un usage quotidien de type
« liste de diligences », ce module propose une expérience proche des
gestionnaires de tâches simples du marché, tout en restant 100 % Odoo.

## Ce que ça change

| Besoin | Réponse du module |
|---|---|
| Voir ce qui presse | Menu **Aujourd'hui** : retards + échéances du jour, en liste |
| Suivre visuellement | **Kanban 4 colonnes fixes** : À faire / En cours / En validation / Terminé |
| Prioriser | Priorité **Haute 🔴 / Moyenne 🟠 / Normale 🟢** visible sur chaque carte |
| Créer vite | Création rapide dans le kanban : titre + responsable + échéance |
| Suivre l'avancement | **Progression %** calculée automatiquement depuis les sous-tâches |
| Ne rien perdre | Le **chatter** (messages, activités, pièces jointes) est conservé |

## Points importants

- **Aucune donnée dupliquée** : ce sont les tâches standard (`project.task`).
  Le module Projet classique reste utilisable en parallèle.
- Quand une diligence passe à « Terminé », l'état standard de la tâche Odoo
  est marqué « Fait » (et inversement rouvert si on la reprend).
- Les diligences peuvent exister **sans projet** (tâches personnelles).

## Installation

1. Placer le dossier `diligence_simple` dans le chemin des addons.
2. Mettre à jour la liste des applications puis installer **Diligences**.
3. Le menu est visible pour les utilisateurs du groupe *Projet / Utilisateur*.
