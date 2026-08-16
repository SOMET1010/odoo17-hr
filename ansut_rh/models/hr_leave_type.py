# -*- coding: utf-8 -*-
from odoo import fields, models


class HrLeaveType(models.Model):
    _inherit = 'hr.leave.type'

    ansut_annual = fields.Boolean(
        string="Congé annuel (règles ANSUT)",
        help="Soumet ce type de congé aux règles de la procédure ANSUT-RH-PR-001 : "
             "délai de dépôt (première semaine du mois précédant le départ), "
             "plafond de cumul de 45 jours, attestations de départ et de reprise, "
             "alerte en cas de non-reprise.")
    ansut_absence = fields.Boolean(
        string="Autorisation d'absence (règles ANSUT)",
        help="Marque ce type comme autorisation d'absence au sens de la procédure "
             "ANSUT-RH-PR-002 (registre des absences, refus motivé).")
    ansut_max_days = fields.Float(
        string="Durée maximale (jours)",
        help="Durée maximale d'une demande pour ce type (0 = illimitée). "
             "Exemple : 1 jour pour les absences validées par le seul supérieur "
             "hiérarchique ; au-delà, utiliser le type à double validation.")
