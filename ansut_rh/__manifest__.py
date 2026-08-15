# -*- coding: utf-8 -*-
{
    'name': "RH ANSUT — Congés, absences et intégration",
    'version': '17.0.1.0.0',
    'category': 'Human Resources',
    'summary': "Procédures ANSUT : congés (RH-PR-001), absences (RH-PR-002), intégration du personnel (RH-PR-004)",
    'description': """
Implémentation des procédures RH de l'ANSUT
===========================================

**Gérer les congés (ANSUT-RH-PR-001)**

* Délai de dépôt : la demande de congé annuel doit être déposée au plus tard
  la première semaine du mois précédant le départ (contrôle bloquant,
  la DRHCom peut passer outre) ;
* Plafond de cumul : 45 jours de congés dus maximum (blocage à la validation
  d'allocation, dérogation possible sur décision du DG via un groupe dédié) ;
* Attestation de départ en congé et attestation de reprise de service
  (rapports PDF imprimables depuis la demande) ;
* Confirmation de la reprise de service sur la demande de congé ;
* Alerte automatique (activité) au responsable en cas de non-reprise
  après la date de fin du congé ;
* Refus motivé obligatoire (assistant dédié, motif tracé dans le chatter).

**Gérer les absences (ANSUT-RH-PR-002)**

* Deux types d'absence pré-configurés : ≤ 1 jour (validation supérieur
  hiérarchique) et > 1 jour (double validation Directeur + RH) ;
* Contrôle de la durée maximale par type ;
* Registre des absences (menu dédié dans Congés) ;
* Refus motivé obligatoire (même assistant que les congés).

**Gérer l'intégration du personnel (ANSUT-RH-PR-004)**

* Dossier d'intégration par recrue : liste des 12 pièces administratives,
  kit d'intégration réparti par direction responsable (DRHCom / DJMG / DSIS),
  accompagnateur d'intégration, avancement en % ;
* Suivi par chatter et activités.
""",
    'author': 'ANSUT',
    'license': 'LGPL-3',
    'depends': ['hr', 'hr_holidays'],
    'data': [
        'security/ansut_rh_security.xml',
        'security/ir.model.access.csv',
        'data/hr_leave_type_data.xml',
        'data/ir_cron_data.xml',
        'wizard/leave_refuse_wizard_views.xml',
        'report/leave_attestation_reports.xml',
        'views/hr_leave_views.xml',
        'views/ansut_integration_views.xml',
    ],
    'installable': True,
    'application': False,
}
