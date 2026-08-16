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
        champs = {c.name: c for c in modele.tous_les_champs}
        noms = [n for n in (vue.fields if vue and vue.fields else list(champs))
                if n in champs]
        cycle = modele.lifecycle

        entete = ""
        if cycle and cycle.states:
            boutons = "".join(
                f'<button type="button" class="bouton">{_echapper(t.label)}</button>'
                for t in cycle.transitions
            )
            etapes = "".join(
                f'<span class="etape{" active" if i == 0 else ""}">{_echapper(e.label)}</span>'
                for i, e in enumerate(cycle.states)
            )
            entete = (f'<div class="entete-form"><div class="boutons">{boutons}</div>'
                      f'<div class="barre-etat">{etapes}</div></div>')

        lignes = []
        for nom in noms:
            champ = champs[nom]
            if champ.type in ("one2many", "many2many"):
                continue                      # rendus à part, en tableau
            marques = []
            if champ.required:
                marques.append('<span class="obligatoire" title="obligatoire">*</span>')
            if champ.readonly or champ.est_calcule:
                marques.append('<span class="calcule">calculé</span>'
                               if champ.est_calcule else
                               '<span class="calcule">lecture seule</span>')
            lignes.append(
                f'<div class="ligne"><label>{_echapper(champ.string)}'
                f'{"".join(marques)}</label>'
                f'<div class="saisie t-{champ.type}">{self._saisie(champ)}'
                f'<span class="genre">{APPARENCE.get(champ.type, champ.type)}</span></div></div>'
            )

        tableaux = ""
        for nom in noms:
            champ = champs[nom]
            if champ.type not in ("one2many", "many2many"):
                continue
            enfant = next((m for m in self.spec.models if m.name == champ.comodel), None)
            colonnes = ([c.string for c in enfant.tous_les_champs[:4]] if enfant
                        else ["Référence", "Valeur"])
            entetes = "".join(f"<th>{_echapper(c)}</th>" for c in colonnes)
            corps = "".join(
                "<tr>" + "".join(f'<td class="doux">…</td>' for _ in colonnes) + "</tr>"
                for _ in range(2)
            )
            tableaux += (
                f'<div class="sous-tableau"><h4>{_echapper(champ.string)}'
                f'<span class="genre">{_echapper(champ.comodel)}</span></h4>'
                f'<div class="defile"><table class="liste">'
                f"<thead><tr>{entetes}</tr></thead><tbody>{corps}</tbody></table></div>"
                f'<button type="button" class="ajouter">Ajouter une ligne</button></div>'
            )

        return (f'<div class="form">{entete}'
                f'<div class="feuille"><div class="grille">{"".join(lignes)}</div>'
                f"{tableaux}</div></div>")

    def _saisie(self, champ) -> str:
        if champ.type == "selection" and champ.selection:
            defaut = champ.default or champ.selection[0][0]
            libelle = dict(champ.selection).get(defaut, champ.selection[0][1])
            return f'<span class="controle deroulant">{_echapper(libelle)} ▾</span>'
        if champ.type == "boolean":
            coche = "✓" if champ.default else ""
            return f'<span class="case">{coche}</span>'
        if champ.type == "many2one":
            return f'<span class="controle lien">{_echapper(champ.comodel)} …</span>'
        if champ.type in ("binary", "image"):
            return '<span class="controle">Choisir un fichier…</span>'
        if champ.est_calcule:
            return '<span class="controle fige">calculé automatiquement</span>'
        exemple = EXEMPLES.get(champ.type, "")
        if champ.default is not None and champ.type not in ("boolean",):
            exemple = str(champ.default)
        return f'<span class="controle">{_echapper(exemple)}</span>'

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
