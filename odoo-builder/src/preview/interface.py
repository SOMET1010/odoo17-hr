"""Le formulaire jouable : ce que la page affiche, et comment elle réagit.

Séparé du simulateur à dessein. `simulateur.py` sait CALCULER — il ne connaît
ni le HTML ni les événements. Ce fichier sait AFFICHER — il ne recalcule
jamais rien lui-même. Mêler les deux ferait qu'une correction de règle métier
demanderait de relire du code de rendu, et réciproquement.
"""

from __future__ import annotations

LIAISON = r"""
function texteValeur(champ, valeur) {
  if (champ.type === 'boolean') return valeur ? 'Oui' : 'Non';
  if (champ.type === 'monetary')
    return (Number(valeur) || 0).toLocaleString('fr-FR') + ' F CFA';
  if (['float'].includes(champ.type))
    return (Number(valeur) || 0).toLocaleString('fr-FR',
      {minimumFractionDigits: 2, maximumFractionDigits: 2});
  if (champ.type === 'integer') return String(Number(valeur) || 0);
  if (champ.type === 'selection') {
    const trouve = (champ.selection || []).find(c => c[0] === valeur);
    return trouve ? trouve[1] : (valeur || '—');
  }
  return valeur === '' || valeur == null ? '—' : String(valeur);
}

function brancher(bloc) {
  const modele = MODELES.find(m => m.nom === bloc.dataset.modele);
  if (!modele) return;
  const enreg = recalculer(modele, creer(modele));
  const parChamp = Object.fromEntries(modele.champs.map(c => [c.nom, c]));

  const alerte = bloc.querySelector('[data-role="alerte"]');
  const journal = bloc.querySelector('[data-role="journal"]');

  function noter(texte, genre) {
    if (!journal) return;
    const ligne = document.createElement('li');
    ligne.className = genre;
    ligne.textContent = texte;
    journal.prepend(ligne);
    while (journal.children.length > 6) journal.lastElementChild.remove();
  }

  function peindre() {
    recalculer(modele, enreg);

    bloc.querySelectorAll('[data-lecture]').forEach(el => {
      const champ = parChamp[el.dataset.lecture];
      if (champ) el.textContent = texteValeur(champ, enreg[champ.nom]);
    });

    bloc.querySelectorAll('[data-saisie]').forEach(el => {
      const nom = el.dataset.saisie;
      if (document.activeElement === el) return;   /* ne pas voler la frappe */
      if (el.type === 'checkbox') el.checked = Boolean(enreg[nom]);
      else el.value = enreg[nom] == null ? '' : enreg[nom];
    });

    if (modele.cycle) {
      const courant = enreg[modele.cycle.champ];
      bloc.querySelectorAll('[data-etat]').forEach(el => {
        el.classList.toggle('active', el.dataset.etat === courant);
      });
      bloc.querySelectorAll('[data-transition]').forEach(el => {
        const t = modele.cycle.transitions.find(x => x.nom === el.dataset.transition);
        const possible = t && t.depuis.includes(courant);
        el.disabled = !possible;
        el.title = possible ? '' :
          'Impossible depuis « ' + texteValeur(parChamp[modele.cycle.champ], courant) + ' »';
      });
    }

    const soucis = violations(modele, enreg);
    if (alerte) {
      alerte.textContent = soucis.length ? soucis[0] : '';
      alerte.hidden = soucis.length === 0;
    }

    /* Les lignes des tableaux : on redessine, elles sont peu nombreuses. */
    bloc.querySelectorAll('[data-lignes]').forEach(corps => {
      const nom = corps.dataset.lignes;
      const colonnes = JSON.parse(corps.dataset.colonnes);
      corps.textContent = '';
      (enreg[nom] || []).forEach((ligne, index) => {
        const tr = document.createElement('tr');
        colonnes.forEach(col => {
          const td = document.createElement('td');
          const saisie = document.createElement('input');
          saisie.type = col.type === 'integer' || col.type === 'float'
            || col.type === 'monetary' ? 'number' : 'text';
          saisie.value = ligne[col.nom] == null ? '' : ligne[col.nom];
          saisie.className = 'cellule';
          saisie.addEventListener('input', () => {
            ligne[col.nom] = saisie.type === 'number'
              ? (Number(saisie.value) || 0) : saisie.value;
            peindre();
          });
          td.appendChild(saisie);
          tr.appendChild(td);
        });
        const td = document.createElement('td');
        const oter = document.createElement('button');
        oter.type = 'button'; oter.className = 'oter'; oter.textContent = '×';
        oter.title = 'Retirer la ligne';
        oter.addEventListener('click', () => {
          enreg[nom].splice(index, 1); peindre();
        });
        td.appendChild(oter); tr.appendChild(td);
        corps.appendChild(tr);
      });
    });
  }

  bloc.querySelectorAll('[data-saisie]').forEach(el => {
    const champ = parChamp[el.dataset.saisie];
    const lire = () => {
      if (el.type === 'checkbox') return el.checked;
      if (['integer', 'float', 'monetary'].includes(champ.type)) return Number(el.value) || 0;
      return el.value;
    };
    el.addEventListener('input', () => { enreg[champ.nom] = lire(); peindre(); });
    el.addEventListener('change', () => { enreg[champ.nom] = lire(); peindre(); });
  });

  bloc.querySelectorAll('[data-ajouter]').forEach(bouton => {
    bouton.addEventListener('click', () => {
      const nom = bouton.dataset.ajouter;
      const colonnes = JSON.parse(bouton.dataset.colonnes);
      const ligne = {};
      colonnes.forEach(c => { ligne[c.nom] = neutre(c.type); });
      (enreg[nom] = enreg[nom] || []).push(ligne);
      peindre();
    });
  });

  bloc.querySelectorAll('[data-transition]').forEach(bouton => {
    bouton.addEventListener('click', () => {
      const t = modele.cycle.transitions.find(x => x.nom === bouton.dataset.transition);
      const issue = franchir(modele, enreg, t);
      noter(issue.message, issue.ok ? 'ok' : 'refus');
      peindre();
    });
  });

  const remise = bloc.querySelector('[data-role="remise"]');
  if (remise) remise.addEventListener('click', () => {
    Object.assign(enreg, creer(modele));
    for (const c of modele.champs) if (Array.isArray(enreg[c.nom])) enreg[c.nom] = [];
    noter('Nouvel enregistrement.', 'ok');
    peindre();
  });

  peindre();
}

document.querySelectorAll('[data-modele]').forEach(brancher);
"""
