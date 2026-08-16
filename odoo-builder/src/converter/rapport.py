"""Ce qu'une conversion n'a pas su emporter.

C'est la sortie la plus importante du convertisseur, et de loin.

Un convertisseur qui laisse tomber une méthode en silence produit un module
qui s'installe et se comporte mal. C'est pire que refuser de convertir :
l'échec est visible, la perte silencieuse ne l'est pas. On l'apprend en
production, sur le cas particulier que la méthode traitait.

Le rapport nomme donc chaque perte, avec son fichier et sa ligne, et dit
pourquoi elle n'a pas pu être portée. Il ne cherche pas à rassurer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Ce qui est perdu n'a pas la même gravité selon ce que c'est.
#
#   COMPORTEMENT : du code métier disparaît. Le module fonctionnera « moins »,
#                  et rien à l'écran ne le dira. C'est ce qu'il faut relire.
#   STRUCTURE    : un élément qu'Odoo sait porter mais que la spécification ne
#                  décrit pas encore (rapport PDF, tâche planifiée, règle
#                  d'accès). À refaire, mais on sait quoi.
#   OBSOLETE     : une tournure d'une version ancienne qui n'existe plus. Elle
#                  aurait de toute façon dû être réécrite : la signaler est un
#                  service, pas un aveu.
COMPORTEMENT = "comportement"
STRUCTURE = "structure"
OBSOLETE = "obsolète"

GRAVITE = {COMPORTEMENT: 0, STRUCTURE: 1, OBSOLETE: 2}


@dataclass(frozen=True)
class Manque:
    """Un élément du module d'origine qui n'est pas dans la spécification."""

    genre: str
    fichier: str
    ligne: int
    quoi: str
    pourquoi: str
    # Ce que l'utilisateur peut faire, quand on sait le dire.
    conduite: str = ""

    def texte(self) -> str:
        ou = f"{self.fichier}:{self.ligne}" if self.ligne else self.fichier
        lignes = [f"  {ou} — {self.quoi}", f"      {self.pourquoi}"]
        if self.conduite:
            lignes.append(f"      → {self.conduite}")
        return "\n".join(lignes)


@dataclass
class RapportConversion:
    """Le bilan d'une conversion : ce qui est passé, et ce qui ne l'est pas."""

    module: str = ""
    version_origine: str = ""
    manques: list[Manque] = field(default_factory=list)
    # Ce qui a été repris, pour que le rapport ne soit pas qu'une liste de deuils.
    repris: dict[str, int] = field(default_factory=dict)

    def noter(self, genre, fichier, ligne, quoi, pourquoi, conduite="") -> None:
        self.manques.append(Manque(genre, fichier, ligne, quoi, pourquoi, conduite))

    def compter(self, quoi: str, combien: int = 1) -> None:
        self.repris[quoi] = self.repris.get(quoi, 0) + combien

    @property
    def complet(self) -> bool:
        """Vrai si tout le module d'origine tient dans la spécification.

        Rare, et c'est normal : la spécification est volontairement pauvre.
        """
        return not self.manques

    @property
    def comportements_perdus(self) -> list[Manque]:
        """Les seuls manques qui changent ce que fait le module."""
        return [m for m in self.manques if m.genre == COMPORTEMENT]

    def texte(self) -> str:
        lignes = [f"Conversion de « {self.module} »"]
        if self.version_origine:
            lignes.append(f"  version d'origine : {self.version_origine}")

        if self.repris:
            lignes.append("")
            lignes.append("Repris dans la spécification :")
            for quoi in sorted(self.repris):
                lignes.append(f"  {self.repris[quoi]:>4}  {quoi}")

        if not self.manques:
            lignes.append("")
            lignes.append("Rien n'a été laissé de côté.")
            return "\n".join(lignes)

        perdus = self.comportements_perdus
        lignes.append("")
        if perdus:
            lignes.append(
                f"NON PORTÉ — {len(perdus)} élément(s) de comportement. "
                "Le module converti ne les fera pas."
            )
        else:
            lignes.append("NON PORTÉ — rien qui change le comportement du module.")

        for genre in sorted({m.genre for m in self.manques}, key=lambda g: GRAVITE.get(g, 9)):
            lignes.append("")
            lignes.append(f"[{genre}]")
            for manque in self.manques:
                if manque.genre == genre:
                    lignes.append(manque.texte())
        return "\n".join(lignes)
