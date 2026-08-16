# -*- coding: utf-8 -*-
from openerp import api, fields, models


class Dossier(models.Model):
    _name = 'suivi.dossier'
    _description = 'Dossier'
    _order = 'name desc'
    _sql_constraints = [('nom_unique', 'unique(name)', 'Nom déjà pris')]

    name = fields.Char('Référence', required=True)
    client_id = fields.Many2one('res.partner', 'Client')
    montant = fields.Float('Montant', group_operator='sum')
    total = fields.Float('Total', compute='_compute_total', store=True)
    etiquette = fields.Char('Étiquette', default=lambda self: self._defaut())
    state = fields.Selection([('brouillon', 'Brouillon'), ('valide', 'Validé')],
                            'État', default='brouillon')

    @api.multi
    def _compute_total(self):
        for enreg in self:
            enreg.total = enreg.montant * 1.18

    def name_get(self):
        return [(enreg.id, enreg.name) for enreg in self]

    def action_valider(self):
        self.write({'state': 'valide'})
        return True
