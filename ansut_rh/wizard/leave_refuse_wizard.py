# -*- coding: utf-8 -*-
from odoo import _, fields, models


class AnsutLeaveRefuseWizard(models.TransientModel):
    _name = 'ansut.leave.refuse.wizard'
    _description = "Refus motivé d'une demande (congé ou absence)"

    leave_id = fields.Many2one('hr.leave', string="Demande", required=True)
    reason = fields.Text(string="Motif du refus", required=True)

    def action_refuse(self):
        self.ensure_one()
        leave = self.leave_id
        leave.ansut_refuse_reason = self.reason
        # Règle 3 (RH-PR-002) / étape 7 (RH-PR-001) : tout rejet est motivé,
        # le motif est archivé dans le chatter et communiqué au salarié.
        leave.message_post(
            body=_("Demande refusée. Motif : %s", self.reason),
            subtype_xmlid='mail.mt_comment')
        leave.action_refuse()
        return {'type': 'ir.actions.act_window_close'}
