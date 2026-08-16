"""Langage d'expression contrôlé du ModuleSpec.

C'est la pièce qui évite de reproduire Python en JSON. La spécification ne
contient jamais de code libre : elle contient des expressions d'un langage
volontairement étroit, que ce module analyse, contrôle, puis traduit en Python
Odoo.

    sum(line_ids.amount)        →  sum(enreg.line_ids.mapped('amount'))
    amount > 0                  →  enreg.amount > 0
    state == 'draft'            →  enreg.state == 'draft'

L'analyse se fait avec `ast.parse` en mode « eval » : rien n'est jamais
exécuté. Tout noeud hors de la liste blanche est refusé, ce qui rend
impossible l'injection de code par une spécification — y compris une
spécification produite par un modèle.

Effet de bord utile : on sait dire quels champs une expression lit, donc
vérifier qu'un `@api.depends` déclaré est complet.
"""

from __future__ import annotations

import ast
import json

# Fonctions d'agrégation admises sur un chemin relationnel.
AGREGATS = {"sum", "count", "min", "max", "avg", "any", "all"}
# Fonctions scalaires admises.
SCALAIRES = {"abs", "len", "round", "bool", "int", "float", "str"}

NOEUDS_AUTORISES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.Call,
    ast.Name, ast.Attribute, ast.Constant, ast.IfExp, ast.Load,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow, ast.FloorDiv,
    ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
    ast.List, ast.Tuple,
)


class ExpressionInvalide(Exception):
    """L'expression sort du langage admis."""


class Expression:
    """Une expression analysée : traduisible, et dont on connaît les lectures."""

    def __init__(self, source: str, variable: str = "enreg"):
        self.source = source
        self.variable = variable
        try:
            self._arbre = ast.parse(source, mode="eval")
        except SyntaxError as erreur:
            raise ExpressionInvalide(f"« {source} » : {erreur.msg}")
        self._controler(self._arbre)

    # --------------------------------------------------------------- analyse

    def _controler(self, noeud) -> None:
        for enfant in ast.walk(noeud):
            if not isinstance(enfant, NOEUDS_AUTORISES):
                raise ExpressionInvalide(
                    f"« {self.source} » : construction interdite "
                    f"({type(enfant).__name__}). Le langage n'admet ni "
                    "affectation, ni appel arbitraire, ni compréhension."
                )
            if isinstance(enfant, ast.Call):
                if not isinstance(enfant.func, ast.Name):
                    raise ExpressionInvalide(
                        f"« {self.source} » : seul l'appel d'une fonction "
                        "nommée est admis."
                    )
                nom = enfant.func.id
                if nom not in AGREGATS | SCALAIRES:
                    raise ExpressionInvalide(
                        f"« {self.source} » : fonction « {nom} » non autorisée. "
                        f"Admises : {', '.join(sorted(AGREGATS | SCALAIRES))}."
                    )
                if enfant.keywords:
                    raise ExpressionInvalide(
                        f"« {self.source} » : arguments nommés non admis."
                    )

    def chemins(self) -> set[str]:
        """Chemins de champs lus par l'expression, en notation pointée.

        C'est la matière d'un `@api.depends` : « line_ids.amount » plutôt que
        « line_ids » seul.
        """
        trouves: set[str] = set()
        # Le nom d'une fonction appelée n'est pas un champ lu : sans cela,
        # « sum » et « abs » finiraient dans le @api.depends généré.
        fonctions = {
            n.func for n in ast.walk(self._arbre)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }

        def chemin_de(noeud) -> str | None:
            if isinstance(noeud, ast.Name):
                return noeud.id
            if isinstance(noeud, ast.Attribute):
                base = chemin_de(noeud.value)
                return f"{base}.{noeud.attr}" if base else None
            return None

        for enfant in ast.walk(self._arbre):
            if enfant in fonctions:
                continue
            if isinstance(enfant, (ast.Name, ast.Attribute)):
                # On ne retient que les chemins complets : « a.b » et non « a ».
                parent_est_attribut = any(
                    isinstance(p, ast.Attribute) and p.value is enfant
                    for p in ast.walk(self._arbre)
                )
                if parent_est_attribut:
                    continue
                chemin = chemin_de(enfant)
                if chemin:
                    trouves.add(chemin)
        return trouves

    def racines(self) -> set[str]:
        """Premiers segments des chemins lus : les champs du modèle courant."""
        return {c.split(".")[0] for c in self.chemins()}

    # ------------------------------------------------------------ traduction

    def en_python(self) -> str:
        self._cible = "python"
        return self._rendre(self._arbre.body)

    def en_javascript(self) -> str:
        """La même expression, pour l'aperçu jouable.

        DEUX SORTIES, UN SEUL ANALYSEUR. C'est l'invariant qui rend l'aperçu
        digne de confiance : le Python installé dans Odoo et le JavaScript
        joué dans la page descendent du MÊME arbre, contrôlé par la même
        liste blanche. Écrire un second interpréteur à la main l'aurait fait
        diverger — et un aperçu qui calcule autrement que le module livré est
        pire qu'aucun aperçu, puisqu'il fait valider un comportement qu'on ne
        livrera pas.

        Les différences ci-dessous sont des différences de LANGAGE, jamais de
        sémantique : « and » s'écrit « && », l'exponentiation « ** », et une
        moyenne se protège de la division par zéro des deux côtés.
        """
        self._cible = "javascript"
        return self._rendre(self._arbre.body)

    @property
    def _js(self) -> bool:
        return getattr(self, "_cible", "python") == "javascript"

    def _rendre(self, noeud) -> str:
        if isinstance(noeud, ast.Constant):
            if self._js:
                if noeud.value is True:
                    return "true"
                if noeud.value is False:
                    return "false"
                if noeud.value is None:
                    return "null"
                return json.dumps(noeud.value)
            return repr(noeud.value)

        if isinstance(noeud, ast.Name):
            return f"{self.variable}.{noeud.id}"

        if isinstance(noeud, ast.Attribute):
            chemin = self._chemin_texte(noeud)
            return f"{self.variable}.{chemin}"

        if isinstance(noeud, ast.Call):
            return self._rendre_appel(noeud)

        if isinstance(noeud, ast.BinOp):
            return (
                f"({self._rendre(noeud.left)} {self._operateur(noeud.op)} "
                f"{self._rendre(noeud.right)})"
            )

        if isinstance(noeud, ast.UnaryOp):
            symbole = ({ast.USub: "-", ast.UAdd: "+", ast.Not: "!"} if self._js
                       else {ast.USub: "-", ast.UAdd: "+", ast.Not: "not "})[type(noeud.op)]
            return f"({symbole}{self._rendre(noeud.operand)})"

        if isinstance(noeud, ast.BoolOp):
            if self._js:
                liant = " && " if isinstance(noeud.op, ast.And) else " || "
            else:
                liant = " and " if isinstance(noeud.op, ast.And) else " or "
            return "(" + liant.join(self._rendre(v) for v in noeud.values) + ")"

        if isinstance(noeud, ast.Compare):
            if self._js:
                # « x in [a, b] » n'a pas d'équivalent direct : JavaScript
                # utilise includes(), et l'ordre des opérandes s'inverse.
                gauche = self._rendre(noeud.left)
                morceaux = []
                for operateur, droite in zip(noeud.ops, noeud.comparators):
                    rendu_droite = self._rendre(droite)
                    if isinstance(operateur, ast.In):
                        morceaux.append(f"{rendu_droite}.includes({gauche})")
                    elif isinstance(operateur, ast.NotIn):
                        morceaux.append(f"!{rendu_droite}.includes({gauche})")
                    else:
                        morceaux.append(
                            f"{gauche} {self._operateur(operateur)} {rendu_droite}"
                        )
                    gauche = rendu_droite
                return "(" + " && ".join(morceaux) + ")"
            morceaux = [self._rendre(noeud.left)]
            for operateur, droite in zip(noeud.ops, noeud.comparators):
                morceaux.append(self._operateur(operateur))
                morceaux.append(self._rendre(droite))
            return "(" + " ".join(morceaux) + ")"

        if isinstance(noeud, ast.IfExp):
            if self._js:
                return (f"({self._rendre(noeud.test)} ? {self._rendre(noeud.body)}"
                        f" : {self._rendre(noeud.orelse)})")
            return (
                f"({self._rendre(noeud.body)} if {self._rendre(noeud.test)} "
                f"else {self._rendre(noeud.orelse)})"
            )

        if isinstance(noeud, (ast.List, ast.Tuple)):
            elements = ", ".join(self._rendre(e) for e in noeud.elts)
            if self._js:
                return f"[{elements}]"
            return f"[{elements}]" if isinstance(noeud, ast.List) else f"({elements})"

        raise ExpressionInvalide(  # pragma: no cover - filtré en amont
            f"« {self.source} » : noeud non traduisible {type(noeud).__name__}."
        )

    def _rendre_appel(self, noeud: ast.Call) -> str:
        nom = noeud.func.id
        if nom in AGREGATS:
            if len(noeud.args) != 1:
                raise ExpressionInvalide(
                    f"« {self.source} » : {nom}() attend exactement un chemin."
                )
            argument = noeud.args[0]
            if isinstance(argument, ast.Attribute):
                chemin = self._chemin_texte(argument)
                relation, _, champ = chemin.rpartition(".")
                cible = (f"A.extraire({self.variable}.{relation}, {champ!r})" if self._js
                         else f"{self.variable}.{relation}.mapped('{champ}')")
            elif isinstance(argument, ast.Name):
                cible = f"{self.variable}.{argument.id}"
            else:
                raise ExpressionInvalide(
                    f"« {self.source} » : {nom}() n'accepte qu'un chemin de champs."
                )
            if self._js:
                # Les agrégats vivent dans un objet « A » fourni par le
                # simulateur : les écrire en ligne ici disperserait la même
                # règle dans chaque expression, et la division par zéro de la
                # moyenne y serait oubliée une fois sur deux.
                return f"A.{nom}({cible})"
            if nom == "count":
                return f"len({cible})"
            if nom == "avg":
                # Moyenne : on protège la division par zéro plutôt que de
                # laisser exploser le calcul sur un enregistrement vide.
                return f"(sum({cible}) / len({cible}) if {cible} else 0.0)"
            return f"{nom}({cible})"

        arguments = ", ".join(self._rendre(a) for a in noeud.args)
        if self._js:
            return f"A.{nom}({arguments})"
        return f"{nom}({arguments})"

    def _chemin_texte(self, noeud: ast.Attribute) -> str:
        morceaux = []
        courant = noeud
        while isinstance(courant, ast.Attribute):
            morceaux.append(courant.attr)
            courant = courant.value
        if not isinstance(courant, ast.Name):
            raise ExpressionInvalide(
                f"« {self.source} » : chemin de champ non reconnu."
            )
        morceaux.append(courant.id)
        return ".".join(reversed(morceaux))

    def _operateur(self, operateur) -> str:
        if self._js:
            # « // » et « ** » n'existent pas tels quels ; le reste coïncide.
            if isinstance(operateur, ast.FloorDiv):
                return "/*plancher*/"
            if isinstance(operateur, ast.Pow):
                return "**"
        return {
            ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
            ast.Mod: "%", ast.Pow: "**", ast.FloorDiv: "//",
            ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=",
            ast.Gt: ">", ast.GtE: ">=", ast.In: "in", ast.NotIn: "not in",
        }[type(operateur)]
