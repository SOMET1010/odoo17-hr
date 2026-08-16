"""La page de l'Atelier. Une seule, en français, sans dépendance.

Séparée du serveur à dessein : `atelier.py` sait ORCHESTRER — conception,
validation, aperçu, archive — et ne contient pas une ligne de HTML. Ce fichier
sait AFFICHER et ne décide de rien. Les mêler ferait qu'une correction de
libellé demanderait de relire du code de sécurité.

AUCUNE RESSOURCE DISTANTE. Ni police, ni cadriciel, ni feuille de style
téléchargée. L'Atelier doit démarrer sur un poste sans Internet — c'est
souvent la situation où l'on travaille sur des modules métier, et un outil qui
attend un CDN pour s'afficher est un outil qui ne démarre pas.
"""

PAGE = r"""<!doctype html>
<html lang="fr" data-theme="clair">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Atelier Odoo</title>
<style>
:root{
  --fond:#F4F6F8; --carte:#FFF; --encre:#151C24; --doux:#5F6B78; --trait:#DDE2E9;
  --violet:#714B67; --violet-clair:#F3EEF2; --ok:#2C6E52; --refus:#A8403A;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root{
  --fond:#0F1419; --carte:#171E26; --encre:#E6EBF1; --doux:#95A1AE; --trait:#29323D;
  --violet:#C79BB6; --violet-clair:#241C22; --ok:#63B48C; --refus:#DE7B74;
}}
*{box-sizing:border-box}
/* « hidden » doit l'emporter sur toute règle d'affichage. Sans cela, une
   classe qui pose « display:flex » rend visible ce que le HTML déclare caché
   — et l'Atelier montrait un bouton de téléchargement avant qu'aucun module
   n'existe. Le défaut ne se voit pas dans la source : il naît de la cascade. */
[hidden]{display:none !important}
body{margin:0;background:var(--fond);color:var(--encre);font-family:var(--sans);
     font-size:15px;line-height:1.5}
.bandeau{background:var(--violet);color:#fff;padding:12px 22px;display:flex;
  justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}
.bandeau b{font-weight:600;letter-spacing:-.01em}
.bandeau .etat{font-family:var(--mono);font-size:.74rem;opacity:.9}
main{max-width:1280px;margin:0 auto;padding:24px 22px 64px;display:grid;
  grid-template-columns:minmax(320px,420px) 1fr;gap:24px;align-items:start}
@media(max-width:900px){main{grid-template-columns:1fr}}
.carte{background:var(--carte);border:1px solid var(--trait);border-radius:5px;
  padding:18px;display:flex;flex-direction:column;gap:12px}
h2{font-size:.95rem;margin:0;letter-spacing:-.01em}
label{font-size:.78rem;color:var(--doux);display:block;margin-bottom:5px}
textarea,input,select{width:100%;font-family:inherit;font-size:.9rem;
  color:var(--encre);background:var(--fond);border:1px solid var(--trait);
  border-radius:4px;padding:9px 11px}
textarea{min-height:150px;resize:vertical;line-height:1.55}
textarea:focus,input:focus,select:focus{outline:2px solid var(--violet);outline-offset:-1px}
.rangee{display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap}
.rangee>div{flex:1;min-width:120px}
button{font-family:inherit;font-size:.86rem;border-radius:4px;padding:9px 16px;
  border:0;background:var(--violet);color:#fff;cursor:pointer;font-weight:500}
button:disabled{opacity:.45;cursor:progress}
button.second{background:transparent;color:var(--violet);border:1px solid var(--violet)}
.exemples{display:flex;flex-wrap:wrap;gap:6px}
.exemples button{background:var(--violet-clair);color:var(--violet);font-size:.76rem;
  padding:5px 10px;font-weight:400}
.journal{font-family:var(--mono);font-size:.74rem;background:var(--violet-clair);
  border-radius:4px;padding:11px;max-height:190px;overflow:auto;white-space:pre-wrap;
  color:var(--doux)}
.erreur{border-left:3px solid var(--refus);padding:11px 14px;background:var(--carte);
  color:var(--refus);font-size:.85rem;border-radius:0 4px 4px 0}
.resume{display:flex;flex-wrap:wrap;gap:8px}
.jeton{font-family:var(--mono);font-size:.72rem;background:var(--violet-clair);
  color:var(--violet);border-radius:3px;padding:3px 9px}
.jeton.ok{color:var(--ok)} .jeton.non{color:var(--refus)}
iframe{width:100%;height:78vh;border:1px solid var(--trait);border-radius:5px;
  background:var(--carte)}
.vide{color:var(--doux);font-size:.88rem;text-align:center;padding:60px 20px;
  border:1px dashed var(--trait);border-radius:5px}
.pied{color:var(--doux);font-size:.76rem;line-height:1.5}
details summary{cursor:pointer;font-size:.8rem;color:var(--doux)}
pre{font-family:var(--mono);font-size:.72rem;overflow:auto;max-height:280px;
  background:var(--violet-clair);padding:11px;border-radius:4px;margin:8px 0 0}
</style>
</head>
<body>

<div class="bandeau">
  <b>Atelier Odoo</b>
  <span class="etat" id="etat">…</span>
</div>

<main>
  <div style="display:flex;flex-direction:column;gap:20px">

    <div class="carte">
      <h2>1 · Décrivez le besoin</h2>
      <div>
        <label for="besoin">En français, comme à un collègue. Qui fait quoi, avec
          quelles informations, et quelles étapes de validation.</label>
        <textarea id="besoin" placeholder="Exemple : je veux suivre les demandes de congé. Chaque demande porte un agent, une date de début, une date de fin et un motif. Le supérieur valide ou refuse en motivant son refus. On doit voir le nombre de jours pris automatiquement."></textarea>
      </div>
      <div class="exemples" id="exemples"></div>
      <div class="rangee">
        <div>
          <label for="cible">Version d'Odoo visée</label>
          <select id="cible"></select>
        </div>
        <button id="concevoir">Concevoir</button>
      </div>
    </div>

    <div class="carte">
      <h2>Ou partez d'un module existant</h2>
      <div>
        <label for="chemin">Chemin d'un dossier de module sur cette machine</label>
        <input id="chemin" placeholder="/chemin/vers/mon_module">
      </div>
      <button class="second" id="convertir">Convertir et afficher</button>
      <p class="pied">Le module est lu, jamais exécuté. Ce qui n'a pas pu être
        porté est listé dans le journal.</p>
    </div>

    <div class="carte" id="carte-journal" hidden>
      <h2>Journal</h2>
      <div class="journal" id="journal"></div>
    </div>

    <div class="carte">
      <h2>Comment ça marche</h2>
      <p class="pied">Le modèle ne produit qu'une <b>spécification</b> : jamais
        de Python, jamais de XML, jamais d'archive. Ce que vous voyez et ce que
        vous téléchargez sortent du générateur déterministe. Une spécification
        refusée repart au modèle avec le motif du refus.</p>
      <p class="pied">La clé du modèle reste dans l'environnement de la commande
        qui a démarré l'Atelier. Cette page ne la reçoit jamais.</p>
    </div>

  </div>

  <div style="display:flex;flex-direction:column;gap:14px">
    <div class="carte" id="carte-resume" hidden>
      <h2 id="titre-module">—</h2>
      <div class="resume" id="resume"></div>
      <div class="rangee">
        <button id="telecharger">Télécharger le module (.zip)</button>
        <button class="second" id="onglet">Ouvrir l'aperçu en pleine page</button>
      </div>
      <details>
        <summary>Voir la spécification</summary>
        <pre id="specification"></pre>
      </details>
    </div>
    <div id="erreur" class="erreur" hidden></div>
    <div id="zone-apercu"><p class="vide">L'aperçu s'affichera ici.<br>
      Décrivez un besoin, ou convertissez un module existant.</p></div>
  </div>
</main>

<script>
const $ = s => document.querySelector(s);
const EXEMPLES = [
  ["Demandes de congé", "Je veux gérer les demandes de congé. Chaque demande porte un agent, une date de début, une date de fin, un motif et le nombre de jours calculé automatiquement. Le circuit va de brouillon à soumise, puis approuvée ou refusée. On ne peut pas soumettre une demande sans motif."],
  ["Suivi du courrier", "Je veux enregistrer le courrier arrivé. Chaque courrier a une référence, un expéditeur, une date de réception, un objet et une direction destinataire. Il passe de reçu à affecté puis traité. On doit pouvoir compter les courriers en attente."],
  ["Demandes de mission", "Je veux suivre les missions. Une mission porte un intitulé, une destination, une date de départ, une date de retour et des lignes de frais. Le total des frais se calcule tout seul. Le circuit va de brouillon à soumise, approuvée, puis remboursée. Une mission sans frais ne peut pas être soumise."],
];

let enCours = false;

function afficherErreur(texte) {
  const boite = $('#erreur');
  boite.hidden = !texte;
  boite.textContent = texte || '';
}

function afficherJournal(lignes) {
  $('#carte-journal').hidden = !(lignes && lignes.length);
  $('#journal').textContent = (lignes || []).join('\n');
}

function afficherResume(r) {
  $('#carte-resume').hidden = false;
  $('#titre-module').textContent = r.nom;
  const jetons = [
    ['jeton', r.technique],
    ['jeton', 'Odoo ' + r.cible],
    ['jeton', 'version ' + r.version],
    ['jeton', r.fichiers + ' fichiers'],
    ['jeton', r.vues + ' vue(s)'],
    ['jeton', r.menus + ' menu(s)'],
    ['jeton ' + (r.valide ? 'ok' : 'non'),
      r.valide ? 'validation passée' : 'validation refusée'],
  ];
  for (const m of r.modeles) {
    jetons.push(['jeton', m.libelle + ' · ' + m.champs + ' champs'
      + (m.cycle ? ' · circuit' : '')]);
  }
  $('#resume').innerHTML = '';
  for (const [classe, texte] of jetons) {
    const s = document.createElement('span');
    s.className = classe; s.textContent = texte;
    $('#resume').appendChild(s);
  }
  $('#specification').textContent = JSON.stringify(r.specification, null, 1);

  /* On recharge l'aperçu avec un paramètre qui change : sinon le navigateur
     réafficherait la page précédente, et on croirait la conception sans effet. */
  $('#zone-apercu').innerHTML =
    '<iframe title="Aperçu du module" src="/apercu.html?t=' + Date.now() + '"></iframe>';
}

async function appeler(route, charge, bouton) {
  if (enCours) return;
  enCours = true;
  const libelle = bouton.textContent;
  bouton.disabled = true; bouton.textContent = 'En cours…';
  afficherErreur('');
  try {
    const reponse = await fetch(route, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(Object.assign({cible: $('#cible').value}, charge)),
    });
    const donnee = await reponse.json();
    afficherJournal(donnee.journal);
    if (!reponse.ok) { afficherErreur(donnee.erreur || 'Échec.'); return; }
    afficherResume(donnee);
  } catch (e) {
    afficherErreur("L'Atelier ne répond pas : " + e.message);
  } finally {
    enCours = false; bouton.disabled = false; bouton.textContent = libelle;
  }
}

$('#concevoir').addEventListener('click', e =>
  appeler('/concevoir', {besoin: $('#besoin').value}, e.target));
$('#convertir').addEventListener('click', e =>
  appeler('/convertir', {chemin: $('#chemin').value}, e.target));
$('#telecharger').addEventListener('click', () => { location.href = '/module.zip'; });
$('#onglet').addEventListener('click', () => window.open('/apercu.html', '_blank'));

for (const [titre, texte] of EXEMPLES) {
  const b = document.createElement('button');
  b.textContent = titre;
  b.addEventListener('click', () => { $('#besoin').value = texte; $('#besoin').focus(); });
  $('#exemples').appendChild(b);
}

fetch('/sante').then(r => r.json()).then(s => {
  for (const c of s.cibles) {
    const o = document.createElement('option');
    o.value = c; o.textContent = 'Odoo ' + c;
    $('#cible').appendChild(o);
  }
  $('#cible').value = s.cibles.includes('17.0') ? '17.0' : s.cibles[0];
  $('#etat').textContent = s.fournisseur
    ? 'modèle configuré' : 'aucun modèle — conversion seule';
  if (!s.fournisseur) {
    $('#concevoir').disabled = true;
    $('#concevoir').title = "Définir BUILDER_IA_CLE ou OPENAI_API_KEY avant de démarrer l'Atelier";
  }
});
</script>
</body>
</html>
"""
