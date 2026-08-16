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
.couleur{display:flex;gap:8px;align-items:center}
.couleur input[type=color]{width:44px;height:34px;padding:2px;cursor:pointer;
  border:1px solid var(--trait);border-radius:4px;background:var(--fond)}
.couleur input[type=text]{font-family:var(--mono);font-size:.82rem;
  text-transform:uppercase}
.projets{display:flex;flex-direction:column;gap:4px;max-height:230px;overflow:auto}
.projet{display:flex;align-items:center;gap:9px;padding:7px 9px;border-radius:4px;
  border:1px solid var(--trait);background:var(--fond)}
.projet.actif{border-color:var(--violet);background:var(--violet-clair)}
.projet .nom{flex:1;font-size:.84rem;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.projet .meta{font-family:var(--mono);font-size:.66rem;color:var(--doux);
  white-space:nowrap}
.projet button{padding:3px 9px;font-size:.72rem}
.projet .oter{background:transparent;color:var(--doux);padding:3px 6px}
.porte{position:fixed;inset:0;display:grid;place-items:center;padding:20px;
  background:var(--fond);z-index:10}
.guichet{width:min(400px,100%);gap:14px}
.lien-clair{background:transparent;color:#fff;border:1px solid rgba(255,255,255,.5);
  font-size:.76rem;padding:4px 10px}
pre{font-family:var(--mono);font-size:.72rem;overflow:auto;max-height:280px;
  background:var(--violet-clair);padding:11px;border-radius:4px;margin:8px 0 0}
</style>
</head>
<body>

<div class="bandeau">
  <b>Atelier Odoo</b>
  <span style="margin-left:auto;display:flex;gap:14px;align-items:center">
    <span class="etat" id="etat">…</span>
    <span class="etat" id="qui" hidden></span>
    <button class="lien-clair" id="deconnexion" hidden>Se déconnecter</button>
  </span>
</div>

<div id="porte" class="porte" hidden>
  <form class="carte guichet" id="guichet">
    <h2 id="titre-porte">Connexion</h2>
    <p class="pied" id="mot-porte">Identifiez-vous pour retrouver vos projets.</p>
    <div>
      <label for="p-nom">Nom d'utilisateur</label>
      <input id="p-nom" autocomplete="username" autofocus>
    </div>
    <div>
      <label for="p-mdp">Mot de passe</label>
      <input id="p-mdp" type="password" autocomplete="current-password">
    </div>
    <div id="porte-erreur" class="erreur" hidden></div>
    <button type="submit" id="p-valider">Se connecter</button>
  </form>
</div>

<main id="atelier" hidden>
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
      <div id="zone-envoi">
        <label for="archive" style="margin-top:6px">Ou envoyez une archive ZIP</label>
        <input type="file" id="archive" accept=".zip">
        <button class="second" id="envoyer">Envoyer et convertir</button>
      </div>
      <p class="pied">Le module est lu, jamais exécuté. Ce qui n'a pas pu être
        porté est listé dans le journal.</p>
    </div>

    <div class="carte">
      <h2>Ou fabriquez un thème</h2>
      <p class="pied">Votre charte graphique appliquée au backend. Le contraste
        est mesuré, pas supposé : une charte conçue pour du papier ne dit pas
        si une couleur peut porter du texte à l'écran.</p>
      <div>
        <label for="t-nom">Nom du thème</label>
        <input id="t-nom" value="Mon thème">
      </div>
      <div class="rangee">
        <div>
          <label for="t-primaire">Couleur principale</label>
          <div class="couleur"><input type="color" id="t-primaire" value="#2256A3">
            <input type="text" id="t-primaire-txt" value="#2256A3"></div>
        </div>
        <div>
          <label for="t-accent">Couleur d'accent</label>
          <div class="couleur"><input type="color" id="t-accent" value="#F08224">
            <input type="text" id="t-accent-txt" value="#F08224"></div>
        </div>
      </div>
      <div class="rangee">
        <div><label for="t-police">Police</label><select id="t-police"></select></div>
        <div><label for="t-densite">Densité</label><select id="t-densite"></select></div>
        <div><label for="t-arrondi">Arrondi</label>
          <select id="t-arrondi">
            <option value="0">Angles vifs</option>
            <option value="4px" selected>4 px</option>
            <option value="8px">8 px</option>
            <option value="12px">12 px</option>
          </select></div>
      </div>
      <button id="theme">Prévisualiser le thème</button>
    </div>

    <div class="carte">
      <h2>Mes projets</h2>
      <p class="pied">Tout ce que vous fabriquez est enregistré. Fermez la
        fenêtre, changez de poste : le travail reste.</p>
      <div class="projets" id="projets"><p class="pied">Aucun projet.</p></div>
      <button class="second" id="nouveau">Repartir de zéro</button>
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
  if (r.cible) $('#cible').value = r.cible;   /* le sélecteur suit la pièce */
  $('#titre-module').textContent = r.nom;
  if (r.genre === 'theme') {
    const jetons = [['jeton', r.technique], ['jeton', 'Odoo ' + r.cible],
                    ['jeton', r.fichiers + ' fichiers']];
    for (const m of r.mesures) {
      jetons.push(['jeton ' + (m.ok ? 'ok' : 'non'),
        m.role + ' ' + m.couleur + ' · texte '
        + (m.texte === '#FFFFFF' ? 'blanc' : 'noir') + ' · ' + m.rapport + ':1']);
    }
    $('#resume').innerHTML = '';
    for (const [classe, texte] of jetons) {
      const s = document.createElement('span');
      s.className = classe; s.textContent = texte;
      $('#resume').appendChild(s);
    }
    $('#specification').textContent = JSON.stringify(r, null, 1);
    $('#zone-apercu').innerHTML =
      '<iframe title="Aperçu du thème" src="/apercu.html?t=' + Date.now() + '"></iframe>';
    return;
  }
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
    if (reponse.status === 401) { location.reload(); return; }
    const donnee = await reponse.json();
    afficherJournal(donnee.journal);
    if (!reponse.ok) { afficherErreur(donnee.erreur || 'Échec.'); return; }
    afficherResume(donnee);
    listerProjets();
  } catch (e) {
    afficherErreur("L'Atelier ne répond pas : " + e.message);
  } finally {
    enCours = false; bouton.disabled = false; bouton.textContent = libelle;
  }
}

for (const role of ['primaire', 'accent']) {
  const pastille = $('#t-' + role), texte = $('#t-' + role + '-txt');
  pastille.addEventListener('input', () => { texte.value = pastille.value.toUpperCase(); });
  texte.addEventListener('change', () => {
    if (/^#[0-9A-Fa-f]{6}$/.test(texte.value)) pastille.value = texte.value;
  });
}

function technique(nom) {
  /* Un nom technique se déduit du nom lisible : « Thème ANSUT » donne
     « theme_ansut_backend ». Le demander en plus serait une question de plus
     à quelqu'un qui veut voir des couleurs. */
  const nu = nom.normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  return ((nu || 'mon_theme') + '_backend').slice(0, 60);
}

$('#theme').addEventListener('click', e => appeler('/theme', {
  nom: $('#t-nom').value,
  technique: technique($('#t-nom').value),
  primaire: $('#t-primaire-txt').value,
  accent: $('#t-accent-txt').value,
  police: $('#t-police').value,
  densite: $('#t-densite').value,
  arrondi: $('#t-arrondi').value,
}, e.target));

async function listerProjets() {
  const r = await fetch('/projets'); const d = await r.json();
  const zone = $('#projets');
  zone.innerHTML = '';
  if (!d.projets.length) {
    zone.innerHTML = '<p class="pied">Aucun projet pour l\'instant.</p>';
    return;
  }
  for (const p of d.projets) {
    const ligne = document.createElement('div');
    ligne.className = 'projet' + (p.id === d.courant ? ' actif' : '');
    const nom = document.createElement('span');
    nom.className = 'nom'; nom.textContent = p.nom;
    const meta = document.createElement('span');
    meta.className = 'meta';
    meta.textContent = (p.genre === 'theme' ? 'thème' : 'module')
      + ' · ' + p.cible + ' · ' + p.revisions + ' rév.';
    const ouvrir = document.createElement('button');
    ouvrir.textContent = 'Ouvrir';
    ouvrir.addEventListener('click', e => appeler('/projet/ouvrir', {id: p.id}, e.target));
    const oter = document.createElement('button');
    oter.className = 'oter'; oter.textContent = '×'; oter.title = 'Supprimer';
    oter.addEventListener('click', async () => {
      await fetch('/projet/supprimer', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify({id: p.id})});
      listerProjets();
    });
    ligne.append(nom, meta, ouvrir, oter);
    zone.appendChild(ligne);
  }
}

$('#nouveau').addEventListener('click', async () => {
  await fetch('/projet/nouveau', {method:'POST',
    headers:{'Content-Type':'application/json'}, body:'{}'});
  $('#carte-resume').hidden = true;
  $('#zone-apercu').innerHTML = '<p class="vide">L\'aperçu s\'affichera ici.</p>';
  listerProjets();
});

$('#concevoir').addEventListener('click', e =>
  appeler('/concevoir', {besoin: $('#besoin').value}, e.target));
$('#envoyer').addEventListener('click', async evenement => {
  const fichier = $('#archive').files[0];
  if (!fichier) { afficherErreur('Choisissez une archive ZIP.'); return; }
  const bouton = evenement.target, libelle = bouton.textContent;
  bouton.disabled = true; bouton.textContent = 'Envoi…';
  afficherErreur('');
  try {
    const formulaire = new FormData();
    formulaire.append('cible', $('#cible').value);
    formulaire.append('archive', fichier);
    const reponse = await fetch('/televerser', {method: 'POST', body: formulaire});
    if (reponse.status === 401) { location.reload(); return; }
    const donnee = await reponse.json();
    afficherJournal(donnee.journal);
    if (!reponse.ok) { afficherErreur(donnee.erreur || 'Échec.'); return; }
    afficherResume(donnee); listerProjets();
  } catch (e) {
    afficherErreur("L'envoi a échoué : " + e.message);
  } finally { bouton.disabled = false; bouton.textContent = libelle; }
});

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

let PREMIER = false;

async function etat() {
  const s = await (await fetch('/sante')).json();

  /* Trois situations, et une seule doit ouvrir la porte :
     — aucun compte et écoute locale : outil personnel, on entre ;
     — aucun compte et écoute ouverte : il faut d'abord créer l'administrateur ;
     — des comptes existent : il faut se connecter. */
  PREMIER = !s.comptes_existants;
  const ouvrir = s.connecte || (!s.comptes_existants && !s.ouvert);
  $('#porte').hidden = ouvrir;
  $('#atelier').hidden = !ouvrir;

  if (!ouvrir) {
    $('#titre-porte').textContent = PREMIER ? 'Premier compte' : 'Connexion';
    $('#mot-porte').textContent = PREMIER
      ? "Aucun compte n'existe encore. Celui-ci sera administrateur — au moins 12 caractères."
      : 'Identifiez-vous pour retrouver vos projets.';
    $('#p-valider').textContent = PREMIER ? 'Créer le compte' : 'Se connecter';
    $('#p-mdp').autocomplete = PREMIER ? 'new-password' : 'current-password';
    return s;
  }

  if (s.ouvert) {
    /* Le chemin désignerait un dossier du serveur : on ne l'affiche même
       pas, plutôt que de laisser quelqu'un s'y essayer et lire un refus. */
    $('#chemin').closest('div').hidden = true;
    $('#convertir').hidden = true;
  }
  $('#qui').hidden = !s.compte;
  $('#deconnexion').hidden = !s.compte;
  if (s.compte) $('#qui').textContent = s.compte.nom
    + (s.compte.role === 'administrateur' ? ' · admin' : '');
  return s;
}

$('#guichet').addEventListener('submit', async evenement => {
  evenement.preventDefault();
  const boite = $('#porte-erreur');
  boite.hidden = true;
  const reponse = await fetch(PREMIER ? '/inscription' : '/connexion', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({nom: $('#p-nom').value, motdepasse: $('#p-mdp').value}),
  });
  const donnee = await reponse.json();
  if (!reponse.ok) {
    boite.textContent = donnee.erreur || 'Échec.'; boite.hidden = false; return;
  }
  $('#p-mdp').value = '';
  await demarrer();
});

$('#deconnexion').addEventListener('click', async () => {
  await fetch('/deconnexion', {method: 'POST',
    headers: {'Content-Type': 'application/json'}, body: '{}'});
  location.reload();
});

async function demarrer() {
  const s = await etat();
  if ($('#atelier').hidden) return;
  listerProjets();
  if (!$('#cible').options.length) remplirChoix(s);
}

function remplirChoix(s) {
  for (const c of s.cibles || []) {
    const o = document.createElement('option');
    o.value = c; o.textContent = 'Odoo ' + c;
    $('#cible').appendChild(o);
  }
  $('#cible').value = s.cibles.includes('17.0') ? '17.0' : s.cibles[0];
  for (const [champ, source] of [['#t-police', s.polices], ['#t-densite', s.densites]]) {
    for (const [cle, description] of Object.entries(source || {})) {
      const o = document.createElement('option');
      o.value = cle;
      o.textContent = cle.charAt(0).toUpperCase() + cle.slice(1) + ' — ' + description;
      $(champ).appendChild(o);
    }
  }
  if ($('#t-densite').querySelector('[value=normale]')) $('#t-densite').value = 'normale';
  $('#etat').textContent = s.fournisseur
    ? 'modèle configuré' : 'aucun modèle — conversion seule';
  if (!s.fournisseur) {
    $('#concevoir').disabled = true;
    $('#concevoir').title = "Définir BUILDER_IA_CLE ou OPENAI_API_KEY avant de démarrer l'Atelier";
  }
}

demarrer();
</script>
</body>
</html>
"""
