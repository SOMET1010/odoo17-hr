# Où en est l'Atelier

Mis à jour le 17 août 2026.

Ce fichier existe parce que les sessions se terminent et que les machines
changent. Il dit ce qui est fait **et prouvé**, ce qui reste, et dans quel
ordre — pour qu'on puisse reprendre sans relire une conversation.

La règle de lecture : « fait » ne veut pas dire « écrit ». Il veut dire
installé dans un vrai Odoo, mis à jour, et appelé. Tout le reste est marqué.

---

## Ce qui est fait, et prouvé

| | Preuve |
|---|---|
| **Générateur multi-versions** — une spécification, trois modules | Généré, installé, **mis à jour**, exécuté dans Odoo 17, 18 et 19 réels (forge, à chaque envoi) |
| **Convertisseur** — un module existant devient une spécification | 10 modules de production sur 10 ; le module d'exemple v12 installé sur les trois versions |
| **Apports par version** — ce que 18 ou 19 apportent à *ce* module | Ancré dans le code lu, jamais générique |
| **Diagnostic de migration** — désigner sans régénérer | Éprouvé sur deux thèmes v14 réels |
| **Aperçu jouable** — calculs, contraintes, circuit | Piloté au navigateur : total à 125 000, transitions refusées puis franchies |
| **Atelier local** — décrire, convertir, thème → aperçu → ZIP | Piloté au navigateur, du clic à l'archive |
| **Générateur de thème** — charte → module + aperçu | Contraste WCAG mesuré ; couleurs vérifiées dans la page rendue |
| **Déploiement** — installeur, HTTPS, dépôt privé, addons Enterprise | Instance réelle montée puis suspendue |
| **Comptes et isolation** — chacun ses projets | Filtre dans le SQL, pas dans le Python ; piloté au navigateur |
| **Atelier en ligne** — pile HTTPS sans Odoo ni base | Recette jouée à chaque envoi : TLS vérifié, porte fermée, dépôt durable |
| **Choix du modèle depuis la page** — clé posée, éprouvée, oubliée | Piloté au navigateur ; la clé ne redescend jamais |
| **Héritage de vues** — greffer un champ sur l'écran d'un autre module | Installé dans Odoo 17, 18 et 19 réels ; le champ est **présent dans la vue servie** |

251 tests.

---

## Ce qui reste, par ordre d'utilité

### 1. Élargir le vocabulaire de la spécification — le gros morceau

C'est **la** limite. Sur le parc de production, 232 comportements ne sont pas
portés, et ils tiennent presque tous à ce que la spécification ne sait pas
encore dire. Le premier de la liste vient de tomber — l'héritage de vues est
livré et éprouvé — et il était le plus rentable :

| Manquant | Ce qu'il débloque |
|---|---|
| **Assistants** (wizards) | Refus motivé, assistants de saisie |
| **Rapports PDF** (QWeb) | Attestations, bordereaux |
| **Tâches planifiées** (`ir.cron`) | Relances, contrôles automatiques |
| **Groupes et règles d'accès** | Droits fins, au-delà du minimum inventé |
| **Mixins** (`mail.thread`) | Discussion, suivi, activités |
| **Données initiales** | Types de congés, catégories livrées avec le module |
| **Vues gantt, pivot, graphe, calendrier** | Écrans d'analyse |

Chacun est un chantier indépendant.

### 2. Mode extension — la moitié est faite

Un module qui hérite d'un module tiers et l'enrichit sans en copier une ligne :
**ça marche**, pour les champs et les écrans. `specs/extension_employe.json`
ajoute deux champs à la fiche employé d'Odoo et les greffe dans son formulaire,
sur les trois versions.

Ce qui manque pour que le mode soit complet : greffer des **boutons** et des
**onglets** (donc des ancres qui ne sont pas des champs), et surcharger une
méthode existante. C'est la suite naturelle, et elle est bien plus petite
maintenant que la première marche est franchie.

### 3. Assembleur pour `addons_odoo17_mtnd`

Le parc est rangé en `produit/version/module`, avec des ZIP et des dossiers
mêlés, et un même module en deux exemplaires (`mails_tracker` 1.1.0 et v1.2,
quatre comportements d'écart). L'assembleur produirait un dossier d'addons
plat et cohérent. **En attente** : les versions v18/v19 sous la convention
`17.0.1.0.0` / `18.0.1.0.0` / `19.0.1.0.0` — que la matrice a confirmée
obligatoire, pas décorative.

### 4. Barre latérale du thème (LOT 07)

Le seul élément de la maquette que le générateur ne fournit pas. Demande un
composant OWL, donc du JavaScript, donc trois branches et un entretien à
chaque version d'Odoo. **Ne sera pas livré sans avoir tourné dans un vrai
Odoo** — c'est cette règle qui a fait apparaître le refus de démarrage
d'Odoo 18 et le dossier écarté par la 19.

---

## Ce qui n'est pas encore prouvé

- **Le bouton « Concevoir » de l'Atelier**, avec un vrai modèle. La chaîne
  besoin → spécification a été prouvée en recette avec un fournisseur réel,
  mais pas encore à travers cette interface. L'instance en ligne existe
  désormais, et le fournisseur s'y choisit depuis la page : il ne manque
  qu'une clé.
- **Les modules du parc converti** : ils passent la validation statique, ils
  ne sont pas installés. Le banc existe (`.docker/verifier-parc.sh`) ; il
  demande un Odoo.

---

## Décisions qui n'appartiennent qu'à vous

1. **La licence** — accepter l'AGPL et bâtir sur l'OCA, ou rester
   propriétaire. À trancher **avant** d'industrialiser l'assembleur : elle
   détermine ce qu'on a le droit de reprendre.
2. **Le serveur** — tout est prêt côté logiciel ; il ne manque qu'une machine.

   Pour l'Atelier seul : **un CX22 à ~4 €/mois suffit**. Il n'a besoin ni
   d'Odoo ni de base de données — le CPX32 à 35 €/mois était dimensionné pour
   Odoo. Une commande, sur une Ubuntu neuve :

   ```
   bash deployer/installer-atelier.sh --domaine atelier.exemple.fr \
                                      --courriel vous@exemple.fr
   ```

   Sans domaine, un nom dérivé de l'adresse IP est employé (sslip.io) et le
   certificat s'obtient dessus : rien à acheter. Le script affiche à la fin le
   **code d'installation** du premier compte — à utiliser tout de suite, car
   tant qu'aucun compte n'existe, l'instance attend le sien.

   Une seconde machine reste utile pour ce qui demande un vrai Odoo : les
   modules du parc converti, et la barre latérale du thème.
3. **Deux points d'hygiène** — révoquer l'ancienne clé Moonshot, et passer
   `odoo17-hr` en privé (la clé de déploiement est prête et vérifiée).

---

## Ce qu'on ne fera pas, et pourquoi

- **Cloner un module payant pour le revendre.** L'extraction reprend les noms
  de modèles, de champs et l'organisation des vues : c'est une œuvre dérivée,
  pas une réimplémentation. Pour un usage propre, la licence OPL-1 autorise
  déjà la modification — il n'y a rien à contourner.
- **Inférer les circuits depuis le Python existant.** Reconnaître
  `def action_valider` et en déduire une transition marche sur les cas simples
  et fabrique du faux sur les autres. Perdre visiblement vaut mieux que gagner
  par hasard.
- **Livrer du JavaScript non éprouvé dans un vrai Odoo.**
