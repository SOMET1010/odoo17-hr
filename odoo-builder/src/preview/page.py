"""L'aperçu, en une page autonome.

Autonome au sens strict : aucun fichier externe, aucune police distante,
aucun script. La page doit s'ouvrir depuis un courriel, une clé USB ou un
téléphone en zone blanche — c'est souvent là qu'on la regarde, et un aperçu
qui a besoin du réseau pour s'afficher n'est pas un aperçu.

Le rendu vise la RECONNAISSANCE, pas l'imitation. Quelqu'un qui connaît Odoo
doit retrouver ses repères — barre d'état, feuille, groupes, liste — sans
qu'on prétende lui montrer une capture d'écran.
"""

from __future__ import annotations

from html import escape

from preview.apercu import Apercu
from preview.interface import LIAISON
from preview.simulateur import script
from spec.module_spec import ModuleSpec

STYLE = """
:root{
  --fond:#F5F6F8; --carte:#FFFFFF; --encre:#1B222B; --doux:#6B7684;
  --trait:#DFE3E9; --violet:#714B67; --violet-clair:#F3EEF2;
  --ok:#2C6E52; --alerte:#9C6B18;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --fond:#11151A; --carte:#191F26; --encre:#E6EBF1; --doux:#96A2AF;
  --trait:#2A333D; --violet:#C79BB6; --violet-clair:#241C22;
  --ok:#63B48C; --alerte:#D6A44E;
}}
:root[data-theme="dark"]{
  --fond:#11151A; --carte:#191F26; --encre:#E6EBF1; --doux:#96A2AF;
  --trait:#2A333D; --violet:#C79BB6; --violet-clair:#241C22;
  --ok:#63B48C; --alerte:#D6A44E;
}
*{box-sizing:border-box}
body{margin:0;background:var(--fond);color:var(--encre);font-family:var(--sans);
     font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}
.page{max-width:1140px;margin:0 auto;padding:40px 20px 88px;
      display:flex;flex-direction:column;gap:44px}
h1{font-size:1.9rem;margin:0;letter-spacing:-.015em;text-wrap:balance}
h2{font-size:1.2rem;margin:0;letter-spacing:-.01em}
h3{font-size:.95rem;margin:0}
h4{font-size:.85rem;margin:0 0 8px;display:flex;gap:10px;align-items:baseline}
p{margin:0}
.eyebrow{font-family:var(--mono);font-size:.68rem;letter-spacing:.13em;
         text-transform:uppercase;color:var(--doux)}
.chapeau{color:var(--doux);max-width:64ch;font-size:.94rem}
section{display:flex;flex-direction:column;gap:16px}
.bloc{background:var(--carte);border:1px solid var(--trait);border-radius:4px;
      overflow:hidden}
.bandeau{background:var(--violet);color:#fff;padding:9px 16px;font-size:.82rem;
         display:flex;justify-content:space-between;align-items:center;gap:12px}
.bandeau .fil{font-family:var(--mono);font-size:.74rem;opacity:.85}
.corps{padding:20px}
.defile{overflow-x:auto}
table.liste{border-collapse:collapse;width:100%;min-width:520px;
            font-variant-numeric:tabular-nums}
table.liste th,table.liste td{text-align:left;padding:8px 12px;
            border-bottom:1px solid var(--trait);font-size:.85rem}
table.liste thead th{font-size:.7rem;letter-spacing:.06em;text-transform:uppercase;
            color:var(--doux);font-weight:600;background:var(--violet-clair)}
table.liste tbody tr:last-child td{border-bottom:0}
td.chiffre,th.chiffre{text-align:right;font-family:var(--mono)}
.doux{color:var(--doux)}
.vide{color:var(--doux);font-style:italic;font-size:.9rem;padding:4px 0}
.entete-form{display:flex;justify-content:space-between;align-items:center;gap:16px;
     padding:10px 16px;border-bottom:1px solid var(--trait);flex-wrap:wrap}
.boutons{display:flex;gap:8px;flex-wrap:wrap}
.bouton{background:var(--violet);color:#fff;border:0;border-radius:3px;
        padding:5px 13px;font-size:.8rem;font-family:inherit;cursor:default}
.barre-etat{display:flex;gap:2px;flex-wrap:wrap}
.etape{font-size:.72rem;padding:4px 12px;background:var(--violet-clair);
       color:var(--doux);border-radius:2px}
.etape.active{background:var(--violet);color:#fff;font-weight:600}
.feuille{padding:20px}
.grille{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));
        gap:2px 32px}
.ligne{display:grid;grid-template-columns:minmax(120px,38%) 1fr;gap:12px;
       align-items:baseline;padding:6px 0;border-bottom:1px solid var(--trait)}
.ligne label{font-size:.82rem;color:var(--doux);display:flex;gap:5px;align-items:baseline}
.obligatoire{color:#C0392B;font-weight:700}
.calcule{font-size:.62rem;letter-spacing:.06em;text-transform:uppercase;
         color:var(--alerte);border:1px solid currentColor;border-radius:2px;padding:0 4px}
.saisie{display:flex;gap:10px;align-items:baseline;justify-content:space-between}
.controle{font-size:.87rem;border-bottom:1px dotted var(--trait);padding-bottom:1px;
          min-width:60px;display:inline-block}
.controle.fige{color:var(--alerte);font-style:italic}
.deroulant{color:var(--encre)}
.lien{color:var(--violet)}
.case{display:inline-block;width:15px;height:15px;border:1px solid var(--doux);
      border-radius:2px;text-align:center;line-height:13px;font-size:.7rem}
.genre{font-size:.65rem;color:var(--doux);font-family:var(--mono);white-space:nowrap}
.sous-tableau{margin-top:22px;padding-top:16px;border-top:1px solid var(--trait)}
.ajouter{margin-top:8px;background:none;border:0;color:var(--violet);
         font-size:.8rem;font-family:inherit;cursor:default;padding:0}
.etat{font-size:.72rem;padding:2px 8px;border-radius:9px;background:var(--violet-clair);
      color:var(--violet)}
ul.menus{list-style:none;margin:0;padding:0}
ul.menus li{display:flex;gap:12px;align-items:baseline;padding:6px 0;
            border-bottom:1px solid var(--trait);font-size:.87rem}
ul.menus li:last-child{border-bottom:0}
ul.menus .n1{padding-left:22px} ul.menus .n2{padding-left:44px}
ul.menus .lib{font-weight:500}
ul.menus .cible,.rubrique{font-size:.72rem;color:var(--doux);font-family:var(--mono)}
.rubrique{font-style:italic}
.onglets{display:flex;gap:0;border-bottom:1px solid var(--trait);padding:0 16px;
         background:var(--violet-clair)}
.onglet{font-size:.78rem;padding:8px 14px;color:var(--doux);border-bottom:2px solid transparent}
.onglet.actif{color:var(--violet);border-bottom-color:var(--violet);font-weight:600}
.avis{border-left:3px solid var(--alerte);background:var(--carte);padding:16px 20px;
      border-radius:0 4px 4px 0;display:flex;flex-direction:column;gap:8px}
.avis h3{color:var(--alerte)}
footer{border-top:1px solid var(--trait);padding-top:20px;color:var(--doux);
       font-size:.8rem;display:flex;flex-direction:column;gap:5px}
input,select,textarea{font-family:inherit;font-size:.87rem;color:var(--encre);
  background:transparent;border:0;border-bottom:1px solid var(--trait);
  padding:2px 0;width:100%;max-width:220px;border-radius:0}
input:focus,select:focus,textarea:focus{outline:0;border-bottom-color:var(--violet);
  box-shadow:0 1px 0 var(--violet)}
input[type=checkbox]{width:16px;height:16px;accent-color:var(--violet)}
select{max-width:220px}
textarea{resize:vertical}
.bouton:not(:disabled){cursor:pointer}
.bouton:disabled{opacity:.35;cursor:not-allowed}
.bouton.fantome{background:transparent;color:var(--violet);
  border:1px solid var(--violet)}
.alerte{margin:0;padding:9px 16px;background:#FBECEA;color:#8E2F26;
  font-size:.83rem;border-bottom:1px solid var(--trait)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .alerte{
  background:#2E1A18;color:#EFA9A1}}
:root[data-theme="dark"] .alerte{background:#2E1A18;color:#EFA9A1}
.cellule{max-width:none;font-size:.83rem}
.oter{background:none;border:0;color:var(--doux);cursor:pointer;font-size:1rem;
  line-height:1;padding:0 4px}
.ajouter{cursor:pointer}
.journal{border-top:1px solid var(--trait);padding:12px 20px 16px;
  background:var(--violet-clair)}
.titre-journal{font-size:.66rem;letter-spacing:.1em;text-transform:uppercase;
  color:var(--doux);margin-bottom:6px}
.journal ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:3px}
.journal li{font-size:.8rem;font-family:var(--mono)}
.journal li.ok{color:var(--ok)} .journal li.refus{color:#B0392F}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .journal li.refus{color:#EFA9A1}}
:root[data-theme="dark"] .journal li.refus{color:#EFA9A1}
code{font-family:var(--mono);font-size:.85em;background:var(--violet-clair);
     padding:1px 5px;border-radius:2px}
"""


def _e(valeur) -> str:
    return escape(str(valeur), quote=True)


def rendre(spec: ModuleSpec, titre: str | None = None) -> str:
    """La page d'aperçu complète d'un module."""
    apercu = Apercu(spec)
    vues = {(v.model, v.type): v for v in spec.views}
    blocs = []

    for modele in spec.models:
        if not modele.tous_les_champs:
            continue
        etiquette = modele.description or modele.name
        liste = apercu.liste(modele, vues.get((modele.name, "tree")))
        form = apercu.formulaire(modele, vues.get((modele.name, "form")))
        extension = (' <span class="genre">extension d\'un modèle existant</span>'
                     if modele.est_extension else "")
        blocs.append(f"""
  <section>
    <h2>{_e(etiquette)}{extension}</h2>
    <div class="bloc">
      <div class="bandeau"><span>{_e(etiquette)}</span>
        <span class="fil">{_e(modele.name)}</span></div>
      <div class="onglets"><span class="onglet actif">Liste</span></div>
      <div class="corps">{liste}</div>
    </div>
    <div class="bloc">
      <div class="bandeau"><span>{_e(etiquette)}</span>
        <span class="fil">nouveau</span></div>
      {form}
    </div>
  </section>""")

    entete_menus = f"""
  <section>
    <h2>Où l'utilisateur trouvera ces écrans</h2>
    <div class="bloc"><div class="corps">{apercu.menus()}</div></div>
  </section>"""

    droits = f"""
  <section>
    <h2>Qui peut faire quoi</h2>
    <div class="bloc">{apercu.droits()}</div>
  </section>"""

    return f"""<title>{_e(titre or spec.name)}</title>
<style>{STYLE}</style>
<div class="page">
  <header style="display:flex;flex-direction:column;gap:12px">
    <p class="eyebrow">Aperçu · {_e(spec.technical_name)} · Odoo {_e(spec.cible)}
      · version {_e(spec.version)}</p>
    <h1>{_e(spec.name)}</h1>
    <p class="chapeau">{_e(spec.summary) or "Aperçu des écrans que ce module ajoutera."}</p>
  </header>
{entete_menus}
{"".join(blocs)}
{droits}
  <div class="avis">
    <h3>Ce que cet aperçu montre, et ce qu'il ne montre pas</h3>
    <p class="chapeau">Les formulaires ci-dessus sont <strong>jouables</strong> : remplissez-les,
      ajoutez des lignes, cliquez les boutons. Les champs calculés se recalculent, les
      contraintes bloquent, et une transition refuse ce qu'elle doit refuser. Le calcul joué
      ici et le calcul installé dans Odoo descendent de la même expression, traduite une fois
      en Python et une fois en JavaScript — ils ne peuvent pas diverger.</p>
    <p class="chapeau">Ce n'est pas Odoo : rien n'est enregistré, aucune donnée ne persiste
      d'un rechargement à l'autre, aucun droit n'est réellement vérifié, et Odoo ajoute ses
      propres éléments — discussion, pièces jointes, barre supérieure. On joue ce que la
      spécification décrit, ce qui est exactement le périmètre à valider avant fabrication.</p>
  </div>
  <footer>
    <p>{len(spec.models)} objet(s) · {sum(len(m.fields) for m in spec.models)} champ(s)
      · {len(spec.views)} vue(s) · {len(spec.menus)} menu(s) · licence {_e(spec.license)}</p>
    <p>Rendu déterministe depuis la spécification. Aucun modèle de langage n'intervient.</p>
  </footer>
</div>
<script>
{script(spec)}
{LIAISON}
</script>
"""
