"""Voir l'écran avant de fabriquer le module.

C'est le maillon qui manquait : idée → conception → fabrication → exécution
→ APERÇU → livraison. Sans lui, on demande à quelqu'un de juger un module sur
une liste de champs, ce qui revient à juger une maison sur sa facture de
matériaux.

L'INVARIANT QUI REND CET APERÇU UTILISABLE : il est dérivé de la MÊME
spécification que le générateur. Pas d'une description parallèle, pas d'un
résumé — le même objet, lu par les mêmes propriétés. Un aperçu bâti sur une
seconde source finirait par montrer autre chose que ce qui est fabriqué, et un
aperçu qui ment est pire que pas d'aperçu du tout : il fait valider un écran
qu'on ne livrera pas.

CE QUE CET APERÇU EST : le rendu fidèle de ce que la spécification décrit —
les champs, leur ordre, leur type, les colonnes de liste, les boutons de
transition, la barre d'état, les menus.

CE QU'IL N'EST PAS : une capture d'écran d'Odoo. Odoo ajoute ses propres
éléments — chatter, pièces jointes, boutons de la barre supérieure — et sa
mise en page exacte dépend de la largeur, du thème et des modules installés.
On montre la STRUCTURE de l'écran, qui est ce qu'il y a à valider ; on ne
promet pas le pixel.
"""

from __future__ import annotations

import json as _j
from html import escape

from spec.module_spec import ModuleSpec, Modele, Vue

# Ce qu'Odoo affiche pour chaque type de champ. Le but n'est pas d'imiter le
# widget au pixel près, mais que la personne qui regarde reconnaisse
# immédiatement « ça, c'est une date » et « ça, c'est une liste déroulante ».
APPARENCE = {
    "char": "texte", "text": "texte long", "html": "texte enrichi",
    "integer": "nombre", "float": "nombre", "monetary": "montant",
    "boolean": "case à cocher", "date": "date", "datetime": "date et heure",
    "selection": "liste déroulante", "many2one": "lien vers un enregistrement",
    "one2many": "tableau de lignes", "many2many": "étiquettes",
    "binary": "fichier", "image": "image",
}

EXEMPLES = {
    "char": "Texte de démonstration", "text": "Texte de démonstration…",
    "integer": "42", "float": "1 250,00", "monetary": "1 250 000 F CFA",
    "date": "12/03/2026", "datetime": "12/03/2026 09:30",
    "html": "Texte mis en forme…",
}


def _json(valeur) -> str:
    return _j.dumps(valeur, ensure_ascii=False)


def _echapper(valeur) -> str:
    return escape(str(valeur), quote=True)


class Apercu:
    """Rend une spécification en pages d'écran lisibles."""

    def __init__(self, spec: ModuleSpec):
        self.spec = spec

    # ------------------------------------------------------------------ menus

    def menus(self) -> str:
        """L'arborescence de menus, telle qu'Odoo la construira.

        Un menu sans action n'ouvre rien : c'est une rubrique. La distinction
        compte à la relecture — c'est souvent là qu'on s'aperçoit qu'un écran
        n'est accessible par aucun chemin.
        """
        enfants: dict[str | None, list] = {}
        for menu in self.spec.menus:
            enfants.setdefault(menu.parent, []).append(menu)
        if not self.spec.menus:
            return '<p class="vide">Ce module n\'ajoute aucun menu.</p>'

        racines = [m for m in self.spec.menus if not m.parent
                   or m.parent not in {x.id for x in self.spec.menus}]

        def brancher(menu, profondeur=0):
            action = next((a for a in self.spec.actions if a.id == menu.action), None)
            cible = (f'<span class="cible">ouvre {_echapper(action.model)}</span>'
                     if action else '<span class="rubrique">rubrique</span>')
            lignes = [
                f'<li class="n{profondeur}"><span class="lib">{_echapper(menu.name)}</span>'
                f'{cible}</li>'
            ]
            for fils in sorted(enfants.get(menu.id, []), key=lambda m: m.sequence):
                lignes.append(brancher(fils, profondeur + 1))
            return "".join(lignes)

        return ('<ul class="menus">'
                + "".join(brancher(m) for m in sorted(racines, key=lambda m: m.sequence))
                + "</ul>")

    # ------------------------------------------------------------------ liste

    def liste(self, modele: Modele, vue: Vue | None) -> str:
        colonnes = self._colonnes(modele, vue)
        if not colonnes:
            return '<p class="vide">Aucune vue liste décrite pour ce modèle.</p>'

        entetes = "".join(
            f'<th class="{self._alignement(c)}">{_echapper(c.string)}</th>' for c in colonnes
        )
        rangs = []
        for numero in range(1, 4):
            cellules = "".join(
                f'<td class="{self._alignement(c)}">{self._valeur(c, numero)}</td>'
                for c in colonnes
            )
            rangs.append(f"<tr>{cellules}</tr>")
        return (f'<div class="defile"><table class="liste">'
                f"<thead><tr>{entetes}</tr></thead>"
                f'<tbody>{"".join(rangs)}</tbody></table></div>')

    def _colonnes(self, modele: Modele, vue: Vue | None):
        champs = {c.name: c for c in modele.tous_les_champs}
        if vue and vue.fields:
            return [champs[n] for n in vue.fields if n in champs]
        return [c for c in modele.tous_les_champs if c.type not in ("text", "html", "binary")][:6]

    @staticmethod
    def _alignement(champ) -> str:
        return "chiffre" if champ.type in ("integer", "float", "monetary") else ""

    def _valeur(self, champ, rang: int) -> str:
        if champ.type == "selection" and champ.selection:
            valeur, libelle = champ.selection[(rang - 1) % len(champ.selection)]
            return f'<span class="etat e{(rang - 1) % 4}">{_echapper(libelle)}</span>'
        if champ.type == "boolean":
            return "✓" if rang % 2 else "—"
        if champ.type == "many2one":
            return f'<span class="lien">{_echapper(champ.comodel)} #{rang}</span>'
        if champ.type in ("one2many", "many2many"):
            return f'<span class="doux">{rang + 1} ligne(s)</span>'
        if champ.type == "monetary":
            return f"{rang * 125:,}".replace(",", " ") + " 000"
        if champ.type in ("integer", "float"):
            return str(rang * 7)
        if champ.type in EXEMPLES:
            return _echapper(f"{EXEMPLES[champ.type]}" if champ.type != "char"
                             else f"{self.spec.name} {rang:03d}")
        return "—"

    # ------------------------------------------------------------- formulaire

    def formulaire(self, modele: Modele, vue: Vue | None) -> str:
        """Un formulaire QU'ON PEUT REMPLIR.

        Les champs se saisissent, les calculs se refont à chaque frappe, les
        contraintes se déclenchent, les boutons de transition refusent ce
        qu'ils doivent refuser. C'est la différence entre valider une capture
        et valider un comportement — et c'est le comportement qui coûte cher
        à corriger après fabrication.
        """
        champs = {c.name: c for c in modele.tous_les_champs}
        noms = [n for n in (vue.fields if vue and vue.fields else list(champs))
                if n in champs]
        for nom in champs:                       # jamais perdre un champ du modèle
            if nom not in noms:
                noms.append(nom)
        cycle = modele.lifecycle

        entete = ""
        if cycle and cycle.states:
            boutons = "".join(
                f'<button type="button" class="bouton" '
                f'data-transition="{_echapper(t.name)}">{_echapper(t.label)}</button>'
                for t in cycle.transitions
            )
            etapes = "".join(
                f'<span class="etape" data-etat="{_echapper(e.value)}">'
                f"{_echapper(e.label)}</span>"
                for e in cycle.states
            )
            entete = (f'<div class="entete-form"><div class="boutons">{boutons}'
                      f'<button type="button" class="bouton fantome" '
                      f'data-role="remise">Nouveau</button></div>'
                      f'<div class="barre-etat">{etapes}</div></div>')
        else:
            entete = ('<div class="entete-form"><div class="boutons">'
                      '<button type="button" class="bouton fantome" '
                      'data-role="remise">Nouveau</button></div></div>')

        lignes = []
        for nom in noms:
            champ = champs[nom]
            if champ.type in ("one2many", "many2many"):
                continue
            if cycle and champ.name == cycle.field_name:
                continue                         # déjà dans la barre d'état
            marques = ""
            if champ.required:
                marques += '<span class="obligatoire" title="obligatoire">*</span>'
            if champ.est_calcule:
                marques += '<span class="calcule">calculé</span>'
            elif champ.readonly:
                marques += '<span class="calcule">lecture seule</span>'
            lignes.append(
                f'<div class="ligne"><label>{_echapper(champ.string)}{marques}</label>'
                f'<div class="saisie">{self._saisie(champ)}</div></div>'
            )

        tableaux = ""
        for nom in noms:
            champ = champs[nom]
            if champ.type not in ("one2many", "many2many"):
                continue
            enfant = next((m for m in self.spec.models if m.name == champ.comodel), None)
            colonnes = [
                {"nom": c.name, "type": c.type, "libelle": c.string}
                for c in (enfant.tous_les_champs if enfant else [])
                if c.name != (champ.inverse_name or "") and not c.est_calcule
            ][:4]
            if not colonnes:
                colonnes = [{"nom": "name", "type": "char", "libelle": "Référence"}]
            json_colonnes = _echapper(_json(colonnes))
            entetes = "".join(f'<th>{_echapper(c["libelle"])}</th>' for c in colonnes)
            tableaux += (
                f'<div class="sous-tableau"><h4>{_echapper(champ.string)}'
                f'<span class="genre">{_echapper(champ.comodel)}</span></h4>'
                f'<div class="defile"><table class="liste">'
                f"<thead><tr>{entetes}<th></th></tr></thead>"
                f'<tbody data-lignes="{_echapper(champ.name)}" '
                f'data-colonnes="{json_colonnes}"></tbody></table></div>'
                f'<button type="button" class="ajouter" '
                f'data-ajouter="{_echapper(champ.name)}" '
                f'data-colonnes="{json_colonnes}">Ajouter une ligne</button></div>'
            )

        journal = ('<div class="journal"><p class="titre-journal">Ce qui se passe</p>'
                   '<ul data-role="journal"></ul></div>')

        return (f'<div class="form" data-modele="{_echapper(modele.name)}">{entete}'
                f'<p class="alerte" data-role="alerte" hidden></p>'
                f'<div class="feuille"><div class="grille">{"".join(lignes)}</div>'
                f"{tableaux}</div>{journal}</div>")

    def _saisie(self, champ) -> str:
        """Un contrôle réellement manipulable, ou une valeur en lecture."""
        nom = _echapper(champ.name)
        if champ.est_calcule or champ.readonly:
            return (f'<span class="controle fige" data-lecture="{nom}">—</span>'
                    f'<span class="genre">{APPARENCE.get(champ.type, champ.type)}</span>')
        if champ.type == "selection" and champ.selection:
            options = "".join(
                f'<option value="{_echapper(v)}">{_echapper(l)}</option>'
                for v, l in champ.selection
            )
            return f'<select data-saisie="{nom}">{options}</select>'
        if champ.type == "boolean":
            return f'<input type="checkbox" data-saisie="{nom}">'
        if champ.type in ("integer", "float", "monetary"):
            pas = 'step="1"' if champ.type == "integer" else 'step="any"'
            return (f'<input type="number" {pas} data-saisie="{nom}" placeholder="0">'
                    f'<span class="genre">{APPARENCE[champ.type]}</span>')
        if champ.type == "date":
            return f'<input type="date" data-saisie="{nom}">'
        if champ.type == "datetime":
            return f'<input type="datetime-local" data-saisie="{nom}">'
        if champ.type in ("text", "html"):
            return f'<textarea rows="2" data-saisie="{nom}"></textarea>'
        if champ.type == "many2one":
            return (f'<input type="text" data-saisie="{nom}" '
                    f'placeholder="{_echapper(champ.comodel)}…">')
        if champ.type in ("binary", "image"):
            return '<span class="controle">Choisir un fichier…</span>'
        return f'<input type="text" data-saisie="{nom}">'

    # ------------------------------------------------------------------ droits

    def droits(self) -> str:
        if not self.spec.access:
            return '<p class="vide">Aucun droit d\'accès déclaré.</p>'
        lignes = []
        for acces in self.spec.access:
            perms = " ".join(
                nom for lettre, nom in
                (("r", "lire"), ("w", "modifier"), ("c", "créer"), ("d", "supprimer"))
                if lettre in acces.perms
            )
            lignes.append(
                f"<tr><td>{_echapper(acces.model)}</td>"
                f'<td class="doux">{_echapper(acces.group)}</td>'
                f"<td>{_echapper(perms)}</td></tr>"
            )
        return ('<div class="defile"><table class="liste">'
                "<thead><tr><th>Objet</th><th>Groupe</th><th>Peut</th></tr></thead>"
                f'<tbody>{"".join(lignes)}</tbody></table></div>')
