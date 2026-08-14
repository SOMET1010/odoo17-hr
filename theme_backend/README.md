# Thème Backend

Habillage global du backend Odoo 17 : couleurs de marque, typographie,
coins arrondis, ombres douces et densité des tableaux. Purement
cosmétique — aucune logique métier modifiée, désinstallable sans risque.

## Installation

1. Copier `theme_backend/` dans le dossier des addons.
2. Redémarrer Odoo, mettre à jour la liste des applications.
3. Installer **Thème Backend**.
4. Après chaque modification d'un fichier `.scss`, mettre à jour le
   module (ou redémarrer avec `-u theme_backend`) pour recompiler les
   assets.

## Où personnaliser

| Fichier | Rôle | Bundle |
|---|---|---|
| `static/src/scss/primary_variables.scss` | **Vos couleurs** et la taille de police de base | `web._assets_primary_variables` (prepend) |
| `static/src/scss/bootstrap_overrides.scss` | Typo, arrondis, ombres, densité des tableaux | `web._assets_backend_helpers` (prepend) |
| `static/src/scss/theme.scss` | Retouches CSS finales, `@font-face` | `web.assets_backend` |

Depuis Odoo 15, les assets se déclarent dans `__manifest__.py`
(clé `assets`) — il n'y a plus de fichier XML d'assets.

## Variables les plus impactantes

### Couleurs (primary_variables.scss)
- `$o-brand-primary` / `$o-brand-odoo` — couleur principale (boutons,
  éléments actifs) ; devient le `$primary` Bootstrap du backend.
- `$o-community-color` / `$o-enterprise-color` — couleur d'édition,
  utilisée par le client web selon la version installée.
- `$o-action` — couleur des liens et actions cliquables.
- `$o-main-text-color` — texte principal.
- `$o-view-background-color` / `$o-webclient-background-color` — fond
  des vues / fond général.
- `$o-root-font-size` — taille de base de toute l'interface (13px
  par défaut ; 14px aère nettement).

### Arrondis (bootstrap_overrides.scss)
- `$border-radius`, `$border-radius-sm`, `$border-radius-lg`
- `$btn-border-radius*`, `$input-border-radius`
- `$modal-content-border-radius`, `$card-border-radius`,
  `$dropdown-border-radius`, `$badge-border-radius`

### Ombres
- `$box-shadow-sm`, `$box-shadow`, `$box-shadow-lg`
- `$dropdown-box-shadow`, `$modal-content-box-shadow-*`

### Densité des tableaux (vues liste)
- `$table-cell-padding-y` / `$table-cell-padding-x`
- `$table-cell-padding-y-sm` / `$table-cell-padding-x-sm`
- `$input-btn-padding-y` / `$input-btn-padding-x` (hauteur des
  boutons et champs)

### Typographie
- `$font-family-sans-serif` — police de tout le backend.
- `$headings-font-weight` — graisse des titres.
- Police personnalisée : `@font-face` dans `theme.scss` + fichiers
  `.woff2` dans `static/fonts/`.

## Note sur les noms de variables

Les noms `$o-*` proviennent de
`addons/web/static/src/scss/primary_variables.scss` (et
`web_enterprise/static/src/scss/primary_variables.scss` en Enterprise).
Selon la sous-version exacte, certains noms peuvent différer : en cas
de valeur sans effet, vérifiez le nom dans ces fichiers de référence.
