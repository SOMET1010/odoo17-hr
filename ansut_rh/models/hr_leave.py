# -*- coding: utf-8 -*-
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    ansut_reprise_date = fields.Date(
        string="Reprise de service le", copy=False, tracking=True,
        help="Date de reprise effective, confirmée au retour du salarié "
             "(procédure ANSUT-RH-PR-001, étapes 9 à 12).")
    ansut_refuse_reason = fields.Text(
        string="Motif du refus", copy=False, tracking=True)
    ansut_alerte_reprise = fields.Boolean(
        string="Alerte de non-reprise envoyée", copy=False)

    # ------------------------------------------------------------------
    # Règle 3 (RH-PR-001) : délai de dépôt de la demande de congé annuel
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        leaves = super().create(vals_list)
        # La DRHCom (officier congés) peut encoder hors délai (régularisations).
        if not self.env.user.has_group('hr_holidays.group_hr_holidays_user'):
            for leave in leaves:
                leave._ansut_check_deadline()
        return leaves

    def _ansut_check_deadline(self):
        self.ensure_one()
        if not self.holiday_status_id.ansut_annual or not self.date_from:
            return
        start = self.date_from.date()
        # Au plus tard la première semaine du mois précédant le mois de départ.
        limit = (start.replace(day=1) - relativedelta(months=1)).replace(day=7)
        today = fields.Date.context_today(self)
        if today > limit:
            raise ValidationError(_(
                "Procédure ANSUT-RH-PR-001 : la demande de congé annuel doit "
                "parvenir à la DRHCom au plus tard la première semaine du mois "
                "précédant le mois de départ.\n\n"
                "Pour un départ le %(depart)s, la demande devait être déposée "
                "avant le %(limite)s. Rapprochez-vous de la DRHCom pour toute "
                "dérogation.",
                depart=start.strftime('%d/%m/%Y'),
                limite=limit.strftime('%d/%m/%Y')))

    # ------------------------------------------------------------------
    # Règle 1 (RH-PR-002) : durée maximale selon le type d'absence
    # ------------------------------------------------------------------
    @api.constrains('holiday_status_id', 'number_of_days')
    def _ansut_check_absence_duration(self):
        for leave in self:
            leave_type = leave.holiday_status_id
            if leave_type.ansut_max_days and \
                    leave.number_of_days > leave_type.ansut_max_days + 0.001:
                raise ValidationError(_(
                    "Procédure ANSUT-RH-PR-002 : le type « %(type)s » est limité "
                    "à %(max)g jour(s) (validation par le supérieur hiérarchique). "
                    "Pour une absence plus longue, utilisez le type prévu pour "
                    "les absences de plus d'une journée (validation par le "
                    "Directeur).",
                    type=leave_type.name, max=leave_type.ansut_max_days))

    # ------------------------------------------------------------------
    # Étapes 9 à 12 (RH-PR-001) : reprise de service
    # ------------------------------------------------------------------
    def action_ansut_confirmer_reprise(self):
        for leave in self:
            if leave.state != 'validate':
                raise UserError(_(
                    "La reprise ne peut être confirmée que sur un congé validé."))
            if not leave.ansut_reprise_date:
                leave.ansut_reprise_date = fields.Date.context_today(self)
            leave.activity_feedback(['mail.mail_activity_data_todo'])
            leave.message_post(body=_(
                "Reprise de service confirmée le %s. L'attestation de reprise "
                "peut être imprimée depuis le menu Imprimer.",
                leave.ansut_reprise_date.strftime('%d/%m/%Y')))
        return True

    # Règle 6 (RH-PR-001) : alerte si non-reprise après congé
    @api.model
    def _cron_ansut_controle_reprise(self):
        today = fields.Date.context_today(self)
        leaves = self.search([
            ('state', '=', 'validate'),
            ('holiday_status_id.ansut_annual', '=', True),
            ('ansut_reprise_date', '=', False),
            ('ansut_alerte_reprise', '=', False),
            ('date_to', '<', fields.Datetime.now()),
        ])
        for leave in leaves:
            # Un jour de tolérance après la fin du congé.
            if leave.date_to.date() + timedelta(days=1) >= today:
                continue
            users = leave.employee_id.leave_manager_id
            if not users and leave.employee_id.parent_id.user_id:
                users = leave.employee_id.parent_id.user_id
            for user in users:
                leave.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=user.id,
                    summary=_("Reprise de service non confirmée"),
                    note=_(
                        "Le congé de %s s'est terminé le %s et la reprise de "
                        "service n'a pas été confirmée. Conformément à la "
                        "procédure ANSUT-RH-PR-001, veuillez vérifier la "
                        "situation et informer la DRHCom.",
                        leave.employee_id.name,
                        leave.date_to.date().strftime('%d/%m/%Y')))
            leave.ansut_alerte_reprise = True
