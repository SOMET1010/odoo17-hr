# -*- coding: utf-8 -*-
from odoo import _, api, models
from odoo.exceptions import ValidationError

ANSUT_MAX_CUMUL = 45


class HrLeaveAllocation(models.Model):
    _inherit = 'hr.leave.allocation'

    # Règles 7 et 8 (RH-PR-001) : pas plus de 45 jours de congés dus ;
    # le rachat/dépassement ne se fait que sur décision du DG.
    @api.constrains('state', 'number_of_days', 'holiday_status_id', 'employee_id')
    def _ansut_check_cumul(self):
        if self.env.user.has_group('ansut_rh.group_ansut_derogation_dg'):
            return
        for alloc in self:
            if alloc.state != 'validate' or not alloc.employee_id or \
                    not alloc.holiday_status_id.ansut_annual:
                continue
            data = alloc.holiday_status_id.get_employees_days(
                [alloc.employee_id.id])[alloc.employee_id.id]
            remaining = data.get(alloc.holiday_status_id.id, {}).get(
                'remaining_leaves', 0)
            if remaining > ANSUT_MAX_CUMUL:
                raise ValidationError(_(
                    "Procédure ANSUT-RH-PR-001 (règle 7) : %(employee)s "
                    "cumulerait %(days).1f jours de congés dus, au-delà du "
                    "plafond de %(max)s jours.\n\n"
                    "Le dépassement ou le rachat de jours ne peut se faire que "
                    "sur décision du Directeur Général (un utilisateur du groupe "
                    "« ANSUT : dérogation cumul congés » peut valider cette "
                    "allocation).",
                    employee=alloc.employee_id.name,
                    days=remaining, max=ANSUT_MAX_CUMUL))
