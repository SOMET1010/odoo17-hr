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
    <button class="lien-clair" id="ouvrir-modele" hidden>Modèle</button>
    <button class="lien-clair" id="ouvrir-comptes" hidden>Comptes</button>
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
    <div id="bloc-code" hidden>
      <label for="p-code">Code d'installation</label>
      <input id="p-code" autocomplete="off">
      <p class="pied">Affiché sur la console du serveur au moment de
        l'installation. Il n'est demandé que pour ce premier compte.</p>
    </div>
    <div id="porte-erreur" class="erreur" hidden></div>
    <button type="submit" id="p-valider">Se connecter</button>
  </form>
</div>

<div id="volet-modele" class="porte" hidden>
  <form class="carte guichet" id="formulaire-modele" style="width:min(560px,100%)">
    <h2>Quel modèle rédige les spécifications</h2>
    <p class="pied" id="modele-actuel"></p>
    <div>
      <label for="m-fournisseur">Fournisseur</label>
      <select id="m-fournisseur"></select>
    </div>
    <div>
      <label for="m-modele">Nom du modèle</label>
      <input id="m-modele" autocomplete="off">
      <p class="pied">Ces noms changent souvent. Si le fournisseur répond
        « modèle inconnu », corrigez ici — c'est un mot, pas une réinstallation.</p>
    </div>
    <div>
      <label for="m-url">Adresse du service</label>
      <input id="m-url" autocomplete="off">
    </div>
    <div>
      <label for="m-cle">Clé</label>
      <input id="m-cle" type="password" autocomplete="off"
             placeholder="collez la clé — elle ne sera jamais réaffichée">
      <p class="pied">Elle reste sur le serveur. Cette page ne peut pas la
        relire : elle n'en revoit que les quatre derniers caractères.</p>
    </div>
    <div id="modele-erreur" class="erreur" hidden></div>
    <div id="modele-bien" class="journal" hidden></div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <button type="submit" id="m-enregistrer">Enregistrer</button>
      <button type="button" class="second" id="m-essai">Éprouver</button>
      <button type="button" class="second" id="m-oublier">Oublier la clé</button>
      <button type="button" class="second" id="m-fermer">Fermer</button>
    </div>
  </form>
</div>

<div id="volet-comptes" class="porte" hidden>
  <form class="carte guichet" id="formulaire-compte" style="width:min(560px,100%)">
    <h2>Qui a accès à cet Atelier</h2>
    <div id="liste-comptes" class="projets"></div>
    <p class="pied">Créer un accès pour quelqu'un. Le mot de passe est choisi
      ici et transmis par vous : il n'existe aucun envoi de courriel, donc
      aucun lien d'activation à intercepter.</p>
    <div class="rangee">
      <div>
        <label for="c-nom">Nom d'utilisateur</label>
        <input id="c-nom" autocomplete="off">
      </div>
      <div>
        <label for="c-mdp">Mot de passe provisoire</label>
        <input id="c-mdp" type="text" autocomplete="off">
      </div>
    </div>
    <p class="pied">Au moins 12 caractères. Une phrase dont on se souvient vaut
      mieux qu'un mot compliqué.</p>
    <div id="compte-erreur" class="erreur" hidden></div>
    <div id="compte-bien" class="journal" hidden></div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <button type="submit" id="c-creer">Créer l'accès</button>
      <button type="button" class="second" id="c-hasard">Proposer un mot de passe</button>
      <button type="button" class="second" id="c-fermer">Fermer</button>
    </div>
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
    /* En ligne, le premier compte demande le code d'installation : sinon le
       premier visiteur venu deviendrait administrateur de l'instance. */
    $('#bloc-code').hidden = !s.code_requis;
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
  /* ICI, et pas seulement au démarrage. Peindre l'état du modèle une seule
     fois au chargement laissait la bannière annoncer « aucun modèle » juste
     après qu'on venait d'en poser un : l'écriture avait bien eu lieu, l'écran
     racontait autre chose. Un état qui change doit se repeindre là où on le
     relit. */
  peindreModele(s);
  return s;
}

$('#guichet').addEventListener('submit', async evenement => {
  evenement.preventDefault();
  const boite = $('#porte-erreur');
  boite.hidden = true;
  const reponse = await fetch(PREMIER ? '/inscription' : '/connexion', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({nom: $('#p-nom').value, motdepasse: $('#p-mdp').value,
                          code: $('#p-code').value}),
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
}

/* -------------------------------------------------------------- comptes */

async function listerComptes() {
  const reponse = await fetch('/comptes');
  if (!reponse.ok) return;
  const donnee = await reponse.json();
  const boite = $('#liste-comptes');
  boite.textContent = '';
  for (const c of donnee.comptes) {
    const ligne = document.createElement('div');
    ligne.className = 'projet';
    const nom = document.createElement('span');
    nom.className = 'nom';
    nom.textContent = c.nom;
    const meta = document.createElement('span');
    meta.className = 'meta';
    meta.textContent = (c.role === 'administrateur' ? 'admin' : 'membre')
      + ' · ' + (c.vu_le ? 'vu le ' + c.vu_le.slice(0, 10) : 'jamais connecté');
    const oter = document.createElement('button');
    oter.className = 'oter'; oter.type = 'button'; oter.textContent = '×';
    oter.title = "Retirer l'accès (les projets sont conservés)";
    oter.addEventListener('click', async () => {
      const reponse = await fetch('/compte/supprimer', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({nom: c.nom}),
      });
      const donnee = await reponse.json();
      if (!reponse.ok) { direCompte(donnee.erreur || 'Échec.', false); return; }
      direCompte(`Accès de « ${c.nom} » retiré. Ses projets sont conservés.`, true);
      listerComptes();
    });
    ligne.append(nom, meta, oter);
    boite.appendChild(ligne);
  }
}

function direCompte(texte, bon) {
  const boite = $(bon ? '#compte-bien' : '#compte-erreur');
  $(bon ? '#compte-erreur' : '#compte-bien').hidden = true;
  boite.textContent = texte; boite.hidden = !texte;
}

$('#ouvrir-comptes').addEventListener('click', () => {
  $('#volet-comptes').hidden = false;
  direCompte('', true); direCompte('', false);
  listerComptes();
});
$('#c-fermer').addEventListener('click', () => { $('#volet-comptes').hidden = true; });

/* Un mot de passe proposé par la machine vaut mieux qu'un mot de passe choisi
   à la hâte pour un collègue — et « crypto » tire vraiment au sort, là où
   Math.random ne le prétend même pas. */
$('#c-hasard').addEventListener('click', () => {
  const mots = ['atelier', 'module', 'chantier', 'registre', 'bordereau',
                'greffe', 'version', 'facture', 'dossier', 'mission'];
  const tirage = new Uint32Array(4);
  crypto.getRandomValues(tirage);
  $('#c-mdp').value = Array.from(tirage.slice(0, 3))
    .map(n => mots[n % mots.length]).join('-') + '-' + (tirage[3] % 100);
});

$('#formulaire-compte').addEventListener('submit', async evenement => {
  evenement.preventDefault();
  const bouton = $('#c-creer'), libelle = bouton.textContent;
  bouton.disabled = true; bouton.textContent = '…';
  try {
    const reponse = await fetch('/inscription', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({nom: $('#c-nom').value, motdepasse: $('#c-mdp').value}),
    });
    const donnee = await reponse.json();
    if (!reponse.ok) { direCompte(donnee.erreur || 'Échec.', false); return; }
    direCompte(`Accès créé pour « ${donnee.compte.nom} ». Transmettez-lui le `
      + `mot de passe : il n'est affiché qu'ici, et jamais réaffiché ensuite.`, true);
    $('#c-nom').value = '';
    listerComptes();
  } finally { bouton.disabled = false; bouton.textContent = libelle; }
});

/* --------------------------------------------------------------- modèle */

let FOURNISSEURS = {};
/* Ce qui est RÉELLEMENT en place, par opposition à ce qui est affiché. Les
   deux se confondent à l'œil, et « Éprouver » essaie le premier. */
let EN_PLACE = null;

function peindreModele(s) {
  FOURNISSEURS = s.fournisseurs || {};
  $('#etat').textContent = s.fournisseur
    ? 'modèle configuré' : 'aucun modèle — conversion seule';
  $('#concevoir').disabled = !s.fournisseur;
  $('#concevoir').title = s.fournisseur ? ''
    : "Aucun modèle : ouvrez « Modèle » en haut de la page.";
  /* Changer de modèle, c'est décider où partent les besoins qu'on décrit :
     réservé aux administrateurs, et le bouton ne s'affiche pas autrement. */
  const patron = !!(s.compte && s.compte.role === 'administrateur');
  $('#ouvrir-modele').hidden = !patron;
  $('#ouvrir-comptes').hidden = !patron;

  const choix = $('#m-fournisseur');
  if (!choix.options.length) {
    for (const [cle, f] of Object.entries(FOURNISSEURS)) {
      const o = document.createElement('option');
      o.value = cle; o.textContent = f.nom;
      choix.appendChild(o);
    }
  }
  const m = s.modele;
  EN_PLACE = m;
  $('#modele-actuel').textContent = m
    ? `En place : ${m.modele} (${m.fournisseur}), clé …${m.fin_de_cle}.`
    : (s.fournisseur
        ? "En place : le modèle défini à l'installation du serveur. En poser un ici le remplacera."
        : "Aucun modèle. La conversion d'un module et les thèmes fonctionnent sans.");
  if (m) {
    choix.value = m.fournisseur;
    $('#m-modele').value = m.modele;
    $('#m-url').value = m.url;
  } else {
    remplirDepuisFournisseur();
  }
}

function remplirDepuisFournisseur() {
  const f = FOURNISSEURS[$('#m-fournisseur').value];
  if (!f) return;
  $('#m-modele').value = f.modele;
  $('#m-url').value = f.url;
}

$('#m-fournisseur').addEventListener('change', remplirDepuisFournisseur);
$('#ouvrir-modele').addEventListener('click', () => {
  $('#volet-modele').hidden = false;
  $('#modele-erreur').hidden = true; $('#modele-bien').hidden = true;
});
$('#m-fermer').addEventListener('click', () => { $('#volet-modele').hidden = true; });

function direModele(texte, bon) {
  const boite = $(bon ? '#modele-bien' : '#modele-erreur');
  const autre = $(bon ? '#modele-erreur' : '#modele-bien');
  autre.hidden = true;
  boite.textContent = texte; boite.hidden = !texte;
}

async function appelerModele(route, corps, bouton, succes) {
  const libelle = bouton.textContent;
  bouton.disabled = true; bouton.textContent = '…';
  try {
    const reponse = await fetch(route, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(corps || {}),
    });
    if (reponse.status === 401) { location.reload(); return null; }
    const donnee = await reponse.json();
    if (!reponse.ok) { direModele(donnee.erreur || 'Échec.', false); return null; }
    direModele(succes(donnee), true);
    await etat();
    return donnee;
  } catch (e) {
    direModele("L'appel a échoué : " + e.message, false);
    return null;
  } finally { bouton.disabled = false; bouton.textContent = libelle; }
}

$('#formulaire-modele').addEventListener('submit', async evenement => {
  evenement.preventDefault();
  await appelerModele('/modele', {
    fournisseur: $('#m-fournisseur').value,
    modele: $('#m-modele').value,
    url: $('#m-url').value,
    cle: $('#m-cle').value,
  }, $('#m-enregistrer'), () => {
    $('#m-cle').value = '';
    return "Enregistré. Éprouvez-le : « configuré » ne veut pas dire « répond ».";
  });
});

/* « Éprouver » essaie CE QUI EST EN PLACE, pas ce qui est à l'écran. Choisir
   un fournisseur dans la liste remplit les champs sans rien changer au
   serveur : on éprouvait donc l'ancien réglage en croyant essayer le nouveau,
   et le refus qui s'affichait n'avait aucun rapport avec ce qu'on lisait. */
function nonEnregistre() {
  if ($('#m-cle').value) return true;
  if (!EN_PLACE) return true;
  return EN_PLACE.modele !== $('#m-modele').value
      || EN_PLACE.url !== $('#m-url').value
      || EN_PLACE.fournisseur !== $('#m-fournisseur').value;
}

$('#m-essai').addEventListener('click', () => {
  if (nonEnregistre()) {
    direModele("Enregistrez d'abord. « Éprouver » essaie le réglage en place "
      + "sur le serveur, pas celui affiché ici — sans quoi le refus que vous "
      + "liriez porterait sur l'ancien.", false);
    return;
  }
  appelerModele('/modele/essai', {}, $('#m-essai'),
    () => 'Le fournisseur répond. Le bouton « Concevoir » est utilisable.');
});

$('#m-oublier').addEventListener('click', () =>
  appelerModele('/modele/oublier', {}, $('#m-oublier'), donnee =>
    donnee.fournisseur
      ? "Clé oubliée. L'Atelier retombe sur le modèle défini à l'installation."
      : 'Clé oubliée. Plus aucun modèle : conversion et thèmes seulement.'));

demarrer();
</script>
</body>
</html>
"""
