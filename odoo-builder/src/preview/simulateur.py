"""Rendre l'aperçu jouable : calculs, contraintes et circuit, dans la page.

Un aperçu statique montre la structure. Or ce qui fait la valeur d'un module
Odoo, c'est le comportement — le total qui se recalcule, la règle qui bloque,
la transition qui refuse. Le valider sur une capture revient à valider une
voiture sur une photo.

L'INVARIANT, et il est tout :

    le Python installé dans Odoo et le JavaScript joué dans cette page
    descendent du MÊME arbre d'expression, contrôlé par la même liste
    blanche (voir spec/expression.py).

Écrire un second interpréteur à la main les aurait fait diverger, et un
aperçu qui calcule autrement que le module livré est pire qu'aucun aperçu :
il fait valider un comportement qu'on ne livrera pas.

PAS D'« eval » NI DE « new Function ». Chaque expression est écrite comme une
vraie fonction JavaScript dans le corps de la page, au moment de la
génération. La page reste donc lisible, vérifiable, et compatible avec une
politique de sécurité stricte — celle des artefacts en interdit l'évaluation
dynamique, et une page qui en dépend s'y afficherait muette.

CE QUE LE SIMULATEUR NE FAIT PAS : la base de données. Rien n'est enregistré,
aucun droit n'est réellement vérifié, aucune séquence n'est tirée. Il joue ce
que la spécification décrit, ce qui est exactement le périmètre à valider
avant fabrication.
"""

from __future__ import annotations

import json

from spec.module_spec import ModuleSpec

# Les fonctions du langage contrôlé, côté navigateur. Elles vivent dans un
# objet unique plutôt que dispersées dans chaque expression : la protection
# contre la division par zéro d'une moyenne s'oublierait une fois sur deux si
# elle était réécrite à chaque emploi.
RUNTIME = r"""
const A = {
  extraire: (lignes, champ) => (lignes || []).map(l => l[champ]),
  nombres: v => (v || []).map(x => Number(x) || 0),
  sum: v => A.nombres(v).reduce((t, x) => t + x, 0),
  count: v => (v || []).length,
  len: v => (v == null ? 0 : (typeof v === 'string' ? v.length : (v.length || 0))),
  min: v => A.nombres(v).length ? Math.min(...A.nombres(v)) : 0,
  max: v => A.nombres(v).length ? Math.max(...A.nombres(v)) : 0,
  avg: v => A.nombres(v).length ? A.sum(v) / A.nombres(v).length : 0,
  any: v => (v || []).some(Boolean),
  all: v => (v || []).every(Boolean),
  abs: Math.abs,
  round: (x, n) => { const f = Math.pow(10, n || 0); return Math.round(x * f) / f; },
  bool: Boolean, int: x => parseInt(x, 10) || 0, float: x => Number(x) || 0,
  str: x => String(x == null ? '' : x),
};

/* Une valeur vide n'est pas la même selon le type : additionner « » à un
   montant donnerait « NaN », et l'aperçu afficherait une erreur là où Odoo
   afficherait zéro. */
function neutre(type) {
  if (['integer', 'float', 'monetary'].includes(type)) return 0;
  if (type === 'boolean') return false;
  if (['one2many', 'many2many'].includes(type)) return [];
  return '';
}

function creer(modele) {
  const enreg = {};
  for (const champ of modele.champs) {
    enreg[champ.nom] = champ.defaut !== null && champ.defaut !== undefined
      ? champ.defaut : neutre(champ.type);
  }
  return enreg;
}

function recalculer(modele, enreg) {
  /* Deux passes : un champ calculé peut en lire un autre. Au-delà, on
     s'arrête — une dépendance circulaire ne doit pas figer la page. */
  for (let passe = 0; passe < 2; passe++) {
    for (const calcul of modele.calculs) {
      try { enreg[calcul.champ] = calcul.fn(enreg, A); }
      catch (e) { enreg[calcul.champ] = neutre(calcul.type); }
    }
  }
  return enreg;
}

function violations(modele, enreg) {
  const trouvees = [];
  for (const regle of modele.contraintes) {
    let vrai = true;
    try { vrai = Boolean(regle.fn(enreg, A)); } catch (e) { vrai = true; }
    if (!vrai) trouvees.push(regle.message);
  }
  return trouvees;
}

function franchir(modele, enreg, transition) {
  /* Les contrôles dans l'ordre où Odoo les applique : l'état de départ,
     puis les validations. Les intervertir donnerait un message trompeur —
     « montant obligatoire » sur un enregistrement déjà validé. */
  if (!transition.depuis.includes(enreg[modele.cycle.champ])) {
    return { ok: false, message: transition.libelle +
      " : opération impossible depuis l'état courant." };
  }
  for (const controle of transition.validations) {
    let vrai = true;
    try { vrai = Boolean(controle.fn(enreg, A)); } catch (e) { vrai = true; }
    if (!vrai) return { ok: false, message: controle.message };
  }
  const bloquantes = violations(modele, enreg);
  if (bloquantes.length) return { ok: false, message: bloquantes[0] };
  enreg[modele.cycle.champ] = transition.vers;
  return { ok: true, message: transition.libelle + " : effectué." };
}
"""


def _fonction(expression, variable: str = "enreg") -> str:
    """Une expression contrôlée, écrite comme fonction JavaScript."""
    return f"(enreg, A) => ({expression.compiler(variable).en_javascript()})"


def script(spec: ModuleSpec) -> str:
    """Le JavaScript de la page : les modèles, puis le moteur.

    Tout est écrit à la génération. Aucune chaîne n'est évaluée à l'exécution.
    """
    modeles = []
    for modele in spec.models:
        champs = [
            {
                "nom": c.name, "type": c.type, "libelle": c.string,
                "obligatoire": bool(c.required),
                "calcule": bool(c.est_calcule),
                "lecture_seule": bool(c.readonly),
                "defaut": c.default,
                "selection": [list(v) for v in c.selection],
                "comodele": c.comodel,
            }
            for c in modele.tous_les_champs
        ]
        cycle = modele.lifecycle
        modeles.append({
            "nom": modele.name,
            "libelle": modele.description or modele.name,
            "champs": champs,
            "_calculs": [
                {"champ": c.name, "type": c.type, "fn": _fonction(c.compute)}
                for c in modele.fields if c.est_calcule
            ],
            "_contraintes": [
                {"message": k.message, "fn": _fonction(k)}
                for k in modele.constraints
            ],
            "cycle": None if not cycle else {
                "champ": cycle.field_name,
                "etats": [[e.value, e.label, bool(e.is_final)] for e in cycle.states],
                "_transitions": [
                    {
                        "nom": t.name, "libelle": t.label,
                        "depuis": list(t.from_states), "vers": t.to_state,
                        "groupes": list(t.allowed_groups),
                        "_validations": [
                            {"message": v["message"],
                             "fn": f"(enreg, A) => ("
                                   f"{__import__('spec.expression', fromlist=['Expression']).Expression(v['condition'], 'enreg').en_javascript()})"}
                            for v in t.validations
                        ],
                    }
                    for t in cycle.transitions
                ],
            },
        })

    # Les fonctions doivent rester du CODE : passer par json.dumps les
    # transformerait en chaînes, qu'il faudrait ensuite évaluer — ce qu'on
    # s'interdit. On sérialise donc en deux temps.
    corps = json.dumps(modeles, ensure_ascii=False, indent=1)
    for modele in modeles:
        for calcul in modele["_calculs"]:
            corps = corps.replace(json.dumps(calcul["fn"], ensure_ascii=False), calcul["fn"])
        for regle in modele["_contraintes"]:
            corps = corps.replace(json.dumps(regle["fn"], ensure_ascii=False), regle["fn"])
        if modele["cycle"]:
            for transition in modele["cycle"]["_transitions"]:
                for controle in transition["_validations"]:
                    corps = corps.replace(
                        json.dumps(controle["fn"], ensure_ascii=False), controle["fn"]
                    )
    corps = (corps.replace('"_calculs"', '"calculs"')
                  .replace('"_contraintes"', '"contraintes"')
                  .replace('"_transitions"', '"transitions"')
                  .replace('"_validations"', '"validations"'))
    return f"const MODELES = {corps};\n{RUNTIME}"
