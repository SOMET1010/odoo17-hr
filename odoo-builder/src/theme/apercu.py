"""Voir le thème avant de l'installer.

Pour un module métier, l'aperçu montre une structure. Pour un thème, l'aperçu
EST le produit : un thème n'est rien d'autre que ce qu'on voit. Livrer une
archive sans rien à regarder revient à faire choisir une peinture sur son nom
de référence.

L'INVARIANT est le même que partout ailleurs dans l'Atelier : cette page est
peinte avec les JETONS QUE LE MODULE EMBARQUE, produits par la même fonction.
Elle ne réplique pas les couleurs à la main. Une page d'aperçu qui recopierait
la charte finirait par montrer autre chose que ce qui s'installe — et c'est
exactement le genre d'écart qu'on ne découvre qu'après la mise en production.

CE QUE CET APERÇU N'EST PAS : une capture d'Odoo. Les proportions, les icônes
et les espacements exacts appartiennent à Odoo. On montre l'IDENTITÉ — la
couleur de la barre, celle des boutons, le contraste du texte, l'allure des
états — parce que c'est ce qu'on valide dans un thème.
"""

from __future__ import annotations

from html import escape

from theme.generateur import (
    DENSITES, POLICES, Charte, contraste, jetons, texte_lisible,
)


def _e(v) -> str:
    return escape(str(v), quote=True)


def _variables(couleurs: dict, prefixe: str = "") -> str:
    return "\n".join(f"  {prefixe}--t-{cle}: {valeur};"
                     for cle, valeur in couleurs.items())


def rendre(charte: Charte, cible: str = "17.0") -> str:
    """La page d'aperçu du thème, claire et sombre."""
    charte.valider()
    clair, obscur = jetons(charte), jetons(charte, sombre=True)
    famille, description_police = POLICES[charte.police]
    taille, description_densite = DENSITES[charte.densite]

    # Le contraste s'affiche : c'est le seul chiffre qui distingue une charte
    # utilisable d'une charte qui l'était sur papier.
    mesures = []
    for nom, couleur in (("Primaire", charte.primaire), ("Accent", charte.accent)):
        texte = texte_lisible(couleur)
        rapport = contraste(couleur, texte)
        mesures.append((nom, couleur, texte, rapport))

    alertes = "".join(
        f'<p class="alerte">{_e(a)}</p>' for a in charte.avertissements
    ) or ""

    return f"""<title>{_e(charte.nom)}</title>
<style>
:root {{
{_variables(clair)}
  --t-radius: {charte.arrondi};
  --t-police: {famille};
  --t-taille: {taille}rem;
}}
.sombre {{
{_variables(obscur)}
}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:var(--t-police);background:#EEF1F4;color:#151C24;
font-size:15px;line-height:1.5}}
@media (prefers-color-scheme:dark){{body{{background:#0C1015;color:#E7ECF2}}}}
.page{{max-width:1180px;margin:0 auto;padding:36px 20px 80px;display:flex;
flex-direction:column;gap:34px}}
h1{{font-size:1.85rem;margin:0;letter-spacing:-.02em}}
h2{{font-size:1.1rem;margin:0}}
p{{margin:0}}
.oeil{{font-family:ui-monospace,Menlo,monospace;font-size:.68rem;letter-spacing:.13em;
text-transform:uppercase;opacity:.6}}
.chapeau{{opacity:.72;max-width:64ch;font-size:.93rem}}

/* --- Les nuanciers, avec leur contraste mesuré */
.nuancier{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}}
.nuance{{border-radius:6px;overflow:hidden;border:1px solid rgba(128,128,128,.25)}}
.aplat{{height:96px;display:flex;align-items:flex-end;padding:12px;
font-family:ui-monospace,Menlo,monospace;font-size:.8rem}}
.pied-nuance{{padding:10px 12px;font-size:.78rem;background:rgba(128,128,128,.08);
display:flex;justify-content:space-between;gap:10px}}
.ok{{color:#2C6E52;font-weight:600}} .non{{color:#A8403A;font-weight:600}}
.alerte{{border-left:3px solid #9C6B18;padding:10px 14px;font-size:.85rem;
background:rgba(156,107,24,.09);border-radius:0 4px 4px 0}}

/* --- La maquette Odoo. Tout vient des jetons, aucune couleur en dur. */
.ecran{{border-radius:10px;overflow:hidden;border:1px solid var(--t-bordure);
background:var(--t-fond);color:var(--t-texte);font-size:var(--t-taille);
box-shadow:0 12px 32px -22px rgba(0,0,0,.5)}}
.barre{{background:var(--t-barre);color:var(--t-texte-barre);padding:0 14px;
display:flex;align-items:center;gap:18px;height:44px;font-size:.86rem}}
.barre .marque{{font-weight:600;letter-spacing:.01em}}
.barre .onglets{{display:flex;gap:16px;opacity:.9}}
.barre .droite{{margin-left:auto;display:flex;gap:14px;align-items:center;opacity:.9}}
.pastille{{width:26px;height:26px;border-radius:50%;background:rgba(255,255,255,.22);
display:grid;place-items:center;font-size:.7rem}}
.souscoup{{background:var(--t-surface);border-bottom:1px solid var(--t-bordure);
padding:9px 14px;display:flex;align-items:center;gap:10px}}
.recherche{{flex:1;background:var(--t-fond);border:1px solid var(--t-bordure);
border-radius:var(--t-radius);padding:5px 10px;font-size:.82rem;opacity:.7}}
.corps{{display:grid;grid-template-columns:200px 1fr;gap:0;min-height:340px}}
@media(max-width:760px){{.corps{{grid-template-columns:1fr}} .flanc{{display:none}}}}
.flanc{{background:var(--t-surface);border-right:1px solid var(--t-bordure);
padding:10px 8px;display:flex;flex-direction:column;gap:2px}}
.flanc a{{display:flex;align-items:center;gap:10px;padding:8px 11px;
border-radius:var(--t-radius);font-size:.85rem;color:var(--t-texte-doux);
text-decoration:none}}
.flanc a.on{{background:color-mix(in srgb, var(--t-primaire) 12%, transparent);
color:var(--t-primaire);font-weight:600}}
.flanc .pic{{width:16px;text-align:center;opacity:.85}}
.flanc .reduire{{margin-top:auto;font-size:.78rem;color:var(--t-texte-doux);
padding:8px 11px;border-top:1px solid var(--t-bordure)}}
.principal{{display:flex;flex-direction:column}}
.bloc{{background:var(--t-surface);border-bottom:1px solid var(--t-bordure);
padding:14px 18px}}
.bloc:last-child{{border-bottom:0}}
.bouton{{background:var(--t-primaire);color:{_e(texte_lisible(charte.primaire))};
border:0;border-radius:var(--t-radius);padding:5px 13px;font-size:.82rem;
font-family:inherit}}
.bouton.accent{{background:var(--t-accent);color:{_e(texte_lisible(charte.accent))}}}
.bouton.vide{{background:transparent;color:var(--t-primaire);
border:1px solid var(--t-primaire)}}
.etats{{display:flex;gap:3px;margin-left:auto}}
.etat{{font-size:.72rem;padding:4px 12px;border-radius:var(--t-radius);
background:rgba(128,128,128,.14);color:var(--t-texte-doux)}}
.etat.on{{background:var(--t-primaire);color:{_e(texte_lisible(charte.primaire))};
font-weight:600}}
table{{width:100%;border-collapse:collapse;font-size:.84rem}}
th{{text-align:left;font-size:.7rem;letter-spacing:.05em;text-transform:uppercase;
color:var(--t-texte-doux);padding:8px 10px;border-bottom:1px solid var(--t-bordure)}}
td{{padding:8px 10px;border-bottom:1px solid var(--t-bordure)}}
tr:last-child td{{border-bottom:0}}
.badge{{font-size:.7rem;padding:3px 11px;border-radius:20px;font-weight:600;
background:var(--t-accent);color:{_e(texte_lisible(charte.accent))}}}
.lien{{color:var(--t-primaire);font-weight:500}}
.champ{{display:grid;grid-template-columns:150px 1fr;gap:12px;padding:7px 0;
border-bottom:1px solid var(--t-bordure);align-items:baseline}}
.champ:last-child{{border-bottom:0}}
.champ .lib{{color:var(--t-texte-doux);font-size:.8rem}}
.champ .val{{border-bottom:1px dotted var(--t-bordure);padding-bottom:2px}}
.duo{{display:grid;grid-template-columns:1fr 1fr;gap:22px}}
@media(max-width:880px){{.duo{{grid-template-columns:1fr}}}}
.etiq{{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;
opacity:.55;margin-bottom:8px}}
footer{{border-top:1px solid rgba(128,128,128,.3);padding-top:18px;opacity:.7;
font-size:.8rem;display:flex;flex-direction:column;gap:5px}}
code{{font-family:ui-monospace,Menlo,monospace;font-size:.85em;
background:rgba(128,128,128,.12);padding:1px 5px;border-radius:3px}}
</style>

<div class="page">
  <header style="display:flex;flex-direction:column;gap:12px">
    <p class="oeil">Aperçu de thème · {_e(charte.technical_name)} · Odoo {_e(cible)}</p>
    <h1>{_e(charte.nom)}</h1>
    <p class="chapeau">Voici ce que votre charte donne dans le backend d'Odoo.
      Les deux écrans ci-dessous sont peints avec <strong>les jetons que le
      module embarque</strong> — pas avec des couleurs recopiées à la main.</p>
  </header>

  <section>
    <h2>Votre charte, et sa lisibilité</h2>
    <p class="chapeau">Une charte est conçue pour du papier. Un fond de barre
      n'est pas un logo : ce qui compte à l'écran, c'est le contraste avec le
      texte qu'il portera. Le seuil du WCAG est 4,5:1.</p>
    <div class="nuancier">
      {"".join(f'''
      <div class="nuance">
        <div class="aplat" style="background:{_e(c)};color:{_e(t)}">{_e(c)}</div>
        <div class="pied-nuance">
          <span>{_e(n)} · texte {_e('blanc' if t == '#FFFFFF' else 'noir')}</span>
          <span class="{'ok' if r >= 4.5 else 'non'}">{r:.2f}:1</span>
        </div>
      </div>''' for n, c, t, r in mesures)}
    </div>
    {alertes}
  </section>

  <section>
    <h2>Mode clair</h2>
    {_maquette(charte)}
  </section>

  <section>
    <h2>Mode sombre</h2>
    <p class="chapeau">Odoo 17 a introduit son propre mécanisme de mode sombre
      (<code>$o-webclient-color-scheme</code>). Le thème s'aligne dessus plutôt
      que d'en inventer un second.</p>
    <div class="sombre">{_maquette(charte)}</div>
  </section>

  <footer>
    <p>Police : {_e(description_police.lower())} · densité
      {_e(charte.densite)} ({_e(description_densite.lower())}) · arrondi
      {_e(charte.arrondi)}</p>
    <p>Ce n'est pas une capture d'Odoo : les proportions et les icônes exactes
      lui appartiennent. On montre l'identité — couleurs, contrastes, allure des
      états — parce que c'est ce qu'on valide dans un thème.</p>
  </footer>
</div>
"""


def _maquette(charte: Charte) -> str:
    """Un écran d'Odoo reconnaissable : barre, liste, formulaire."""
    return """
    <div class="ecran">
      <div class="barre">
        <span class="marque">Missions</span>
        <span class="onglets"><span>Vue d'ensemble</span><span>Demandes</span>
          <span>Rapports</span><span>Configuration</span></span>
        <span class="droite"><span>⌘K</span><span class="pastille">FR</span>
          <span class="pastille">HP</span></span>
      </div>
      <div class="souscoup">
        <span class="recherche">Rechercher…</span>
        <button class="bouton">Nouveau</button>
        <button class="bouton vide">Exporter</button>
      </div>
      <div class="corps">
        <nav class="flanc">
          <a class="on"><span class="pic">⌂</span>Accueil</a>
          <a><span class="pic">✈</span>Missions</a>
          <a><span class="pic">◫</span>Partenaires</a>
          <a><span class="pic">☰</span>RH &amp; Équipe</a>
          <a><span class="pic">₣</span>Finances</a>
          <a><span class="pic">▤</span>Rapports</a>
          <a><span class="pic">⚙</span>Configuration</a>
          <div class="reduire">‹ Réduire</div>
        </nav>
        <div class="principal">
        <div class="bloc">
          <div class="etiq">Vue liste</div>
          <table>
            <thead><tr><th>Référence</th><th>Destination</th><th>Agent</th>
              <th>Montant</th><th>État</th></tr></thead>
            <tbody>
              <tr><td class="lien">MIS/2026/0041</td><td>Bouaké</td>
                <td>K. Traoré</td><td>125 000 F CFA</td>
                <td><span class="badge">Soumise</span></td></tr>
              <tr><td class="lien">MIS/2026/0040</td><td>Korhogo</td>
                <td>A. Koné</td><td>318 000 F CFA</td>
                <td><span class="badge">Approuvée</span></td></tr>
              <tr><td class="lien">MIS/2026/0039</td><td>San-Pédro</td>
                <td>M. Diallo</td><td>92 500 F CFA</td>
                <td><span class="badge">Remboursée</span></td></tr>
            </tbody>
          </table>
        </div>
        <div class="bloc">
          <div class="etiq">Vue formulaire</div>
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;
                      margin-bottom:14px">
            <button class="bouton">Soumettre</button>
            <button class="bouton accent">Approuver</button>
            <button class="bouton vide">Refuser</button>
            <span class="etats"><span class="etat on">Brouillon</span>
              <span class="etat">Soumise</span><span class="etat">Approuvée</span>
              <span class="etat">Remboursée</span></span>
          </div>
          <div class="duo">
            <div>
              <div class="champ"><span class="lib">Référence</span>
                <span class="val">MIS/2026/0042</span></div>
              <div class="champ"><span class="lib">Destination</span>
                <span class="val">Yamoussoukro</span></div>
              <div class="champ"><span class="lib">Date de départ</span>
                <span class="val">12/03/2026</span></div>
            </div>
            <div>
              <div class="champ"><span class="lib">Agent</span>
                <span class="val lien">K. Traoré</span></div>
              <div class="champ"><span class="lib">Total des frais</span>
                <span class="val">125 000 F CFA</span></div>
              <div class="champ"><span class="lib">Nombre de lignes</span>
                <span class="val">2</span></div>
            </div>
          </div>
        </div>
        </div>
      </div>
    </div>"""
