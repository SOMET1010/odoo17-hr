"""Le diagnostic, en une page qu'on peut lire et transmettre.

Une liste de deux cents lignes dans un terminal ne se relit pas, ne se
transmet pas, et ne se hiérarchise pas. Or ce rapport a un ordre de lecture
précis : d'abord ce qui empêche Odoo de démarrer, ensuite ce qui disparaît
sans prévenir, enfin ce qui demande un développeur.

Page autonome : aucune ressource distante. On la relit dans l'avion, on la
transmet par courriel, on l'ouvre sur un poste sans Internet.
"""

from __future__ import annotations

from html import escape

from migration.regles import BLOQUANT, MANUEL, ORDRE, SILENCIEUX

TITRES = {
    BLOQUANT: ("Bloquant", "Odoo refuse le module, ou refuse de démarrer. "
                           "Ça se voit tout de suite."),
    SILENCIEUX: ("Silencieux", "Odoo accepte le module et le comportement "
                               "disparaît. Rien ne le signale — on l'apprend en "
                               "production, le jour où la règle aurait dû jouer."),
    MANUEL: ("Manuel", "Hors de portée d'un outil : il faut un développeur. "
                       "Le dire vaut mieux que de laisser croire que la liste "
                       "est complète."),
}

STYLE = """
:root{--fond:#F5F6F8;--carte:#FFF;--encre:#151C24;--doux:#5F6B78;--trait:#DDE2E9;
--bloc:#A8403A;--sil:#9C6B18;--man:#42566B;--ok:#2C6E52;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
--mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace}
@media(prefers-color-scheme:dark){:root{--fond:#0F1419;--carte:#171E26;
--encre:#E6EBF1;--doux:#95A1AE;--trait:#29323D;--bloc:#DE7B74;--sil:#D6A44E;
--man:#8FA6BC;--ok:#63B48C}}
*{box-sizing:border-box}
body{margin:0;background:var(--fond);color:var(--encre);font-family:var(--sans);
font-size:15px;line-height:1.55}
.page{max-width:1080px;margin:0 auto;padding:44px 22px 90px;display:flex;
flex-direction:column;gap:44px}
h1{font-size:2rem;margin:0;letter-spacing:-.02em}
h2{font-size:1.25rem;margin:0;letter-spacing:-.01em}
h3{font-size:.95rem;margin:0;font-family:var(--mono)}
p{margin:0}
.oeil{font-family:var(--mono);font-size:.68rem;letter-spacing:.13em;
text-transform:uppercase;color:var(--doux)}
.chapeau{color:var(--doux);max-width:66ch;font-size:.95rem}
.chiffres{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
gap:1px;background:var(--trait);border:1px solid var(--trait);border-radius:4px;
overflow:hidden}
.chiffre{background:var(--carte);padding:18px 20px}
.chiffre b{display:block;font-family:var(--mono);font-size:2rem;font-weight:500;
line-height:1;font-variant-numeric:tabular-nums}
.chiffre span{font-size:.8rem;color:var(--doux);display:block;margin-top:7px}
.b b{color:var(--bloc)} .s b{color:var(--sil)} .m b{color:var(--man)}
section{display:flex;flex-direction:column;gap:16px}
.bloc{background:var(--carte);border:1px solid var(--trait);border-radius:4px;
overflow:hidden}
.tete{padding:14px 18px;border-bottom:1px solid var(--trait);display:flex;
justify-content:space-between;align-items:baseline;gap:14px;flex-wrap:wrap}
.tete .src{font-family:var(--mono);font-size:.72rem;color:var(--doux)}
.item{padding:14px 18px;border-bottom:1px solid var(--trait);display:flex;
flex-direction:column;gap:6px}
.item:last-child{border-bottom:0}
.ou{font-family:var(--mono);font-size:.74rem;color:var(--doux)}
.quoi{font-weight:500;font-size:.92rem}
.code{font-family:var(--mono);font-size:.76rem;background:var(--fond);
padding:6px 9px;border-radius:3px;overflow-x:auto;white-space:pre}
.faire{font-size:.88rem}
.faire::before{content:"→ ";color:var(--ok);font-weight:700}
.pourquoi{font-size:.8rem;color:var(--doux)}
.puce{display:inline-block;font-family:var(--mono);font-size:.65rem;
letter-spacing:.08em;text-transform:uppercase;padding:2px 8px;border-radius:2px;
border:1px solid currentColor}
.p-b{color:var(--bloc)} .p-s{color:var(--sil)} .p-m{color:var(--man)}
.avis{border-left:3px solid var(--sil);background:var(--carte);padding:16px 20px;
border-radius:0 4px 4px 0;display:flex;flex-direction:column;gap:8px}
.avis h3{color:var(--sil);font-family:var(--sans);font-size:1rem}
.rien{color:var(--ok);font-size:.9rem;padding:14px 18px}
footer{border-top:1px solid var(--trait);padding-top:20px;color:var(--doux);
font-size:.8rem;display:flex;flex-direction:column;gap:5px}
"""


def _e(v) -> str:
    return escape(str(v), quote=True)


def ecrire(modules, cible: str, racine: str, chemin: str) -> None:
    total = {g: sum(len(m.par_gravite(g)) for m in modules)
             for g in (BLOQUANT, SILENCIEUX, MANUEL)}
    classes = {BLOQUANT: "b", SILENCIEUX: "s", MANUEL: "m"}

    blocs = []
    for module in modules:
        if module.erreur:
            blocs.append(f'<div class="bloc"><div class="tete"><h3>{_e(module.nom)}'
                         f'</h3><span class="src">{_e(module.erreur)}</span></div></div>')
            continue
        items = []
        for gravite in sorted({t.gravite for t in module.trouvailles},
                              key=lambda g: ORDRE[g]):
            for t in sorted((x for x in module.trouvailles if x.gravite == gravite),
                            key=lambda x: (x.fichier, x.ligne)):
                place = f"{t.fichier}:{t.ligne}" if t.ligne else t.fichier
                items.append(f"""
        <div class="item">
          <div><span class="puce p-{classes[gravite]}">{_e(TITRES[gravite][0])}</span>
            <span class="ou"> {_e(place)}</span></div>
          <div class="quoi">{_e(t.regle.quoi)}</div>
          <div class="code">{_e(t.texte)}</div>
          <div class="faire">{_e(t.regle.faire)}</div>
          <div class="pourquoi">{_e(t.regle.source)}</div>
        </div>""")
        corps = "".join(items) or (
            '<p class="rien">Rien de reconnu à changer pour cette version.</p>')
        js = (f' · {module.fichiers_js} fichier(s) JavaScript'
              if module.fichiers_js else "")
        blocs.append(f"""
    <div class="bloc">
      <div class="tete">
        <h3>{_e(module.nom)}</h3>
        <span class="src">{_e(module.origine)} · version {_e(module.version or '—')}
          · {_e(module.licence or 'licence non déclarée')}{js}</span>
      </div>{corps}
    </div>""")

    page = f"""<title>Diagnostic de migration</title>
<style>{STYLE}</style>
<div class="page">
  <header style="display:flex;flex-direction:column;gap:14px">
    <p class="oeil">Diagnostic de migration · cible Odoo {_e(cible)}</p>
    <h1>{len(modules)} module(s) à faire passer en {_e(cible)}</h1>
    <p class="chapeau">Chaque ligne désigne un endroit à corriger dans
      <strong>votre</strong> code. Rien n'est régénéré : vous gardez vos méthodes,
      vos assistants et votre JavaScript.</p>
    <div class="chiffres">
      <div class="chiffre b"><b>{total[BLOQUANT]}</b>
        <span>bloquants — Odoo refuse le module ou refuse de démarrer</span></div>
      <div class="chiffre s"><b>{total[SILENCIEUX]}</b>
        <span>silencieux — Odoo accepte, le comportement disparaît sans message</span></div>
      <div class="chiffre m"><b>{total[MANUEL]}</b>
        <span>manuels — hors de portée d'un outil</span></div>
    </div>
  </header>

  <section>
    <div class="tete" style="border:0;padding:0">
      <h2>Par où commencer</h2>
    </div>
    <div class="avis" style="border-left-color:var(--bloc)">
      <h3>Les bloquants d'abord — ils se voient</h3>
      <p class="chapeau">Un module refusé ne trompe personne. Le corriger est
        mécanique : renommer une balise, supprimer un décorateur, réécrire une
        version de manifeste.</p>
    </div>
    <div class="avis">
      <h3>Les silencieux ensuite — et ce sont eux qui coûtent</h3>
      <p class="chapeau">Odoo accepte le module, l'installe, et une règle cesse
        d'exister. Aucune erreur, aucun écran. C'est le cas de
        <code>_sql_constraints</code> en Odoo 19 : la contrainte d'unicité qui
        protégeait vos données depuis des années disparaît, et vous l'apprendrez
        le jour d'un doublon.</p>
    </div>
  </section>

  <section>
    <h2>Module par module</h2>
    {"".join(blocs)}
  </section>

  <div class="avis" style="border-left-color:var(--man)">
    <h3>Ce que ce diagnostic ne dit pas</h3>
    <p class="chapeau">Il liste ce qu'il <strong>sait</strong> reconnaître. Ce
      qu'il ignore, il ne le voit pas — un diagnostic vide ne signifie pas
      « ça marchera », mais « je n'ai rien reconnu ». La seule preuve reste
      l'installation dans un vrai Odoo de la version visée.</p>
  </div>

  <footer>
    <p>Parc examiné : <code>{_e(racine)}</code></p>
    <p>Le code est lu, jamais exécuté. Chaque règle porte sa source, vérifiée
      dans la documentation officielle d'Odoo ou dans son code.</p>
  </footer>
</div>
"""
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(page)
