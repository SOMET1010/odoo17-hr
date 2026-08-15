# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProjectTask(models.Model):
    _inherit = 'project.task'

    diligence_state = fields.Selection([
        ('todo', 'À faire'),
        ('in_progress', 'En cours'),
        ('validation', 'En validation'),
        ('done', 'Terminé'),
    ], string="Étape", default='todo', index=True, copy=False, tracking=True,
        group_expand='_group_expand_diligence_state')
    diligence_priority = fields.Selection([
        ('normale', 'Normale'),
        ('moyenne', 'Moyenne'),
        ('haute', 'Haute'),
    ], string="Priorité de la diligence", default='normale', index=True, tracking=True)
    diligence_progress = fields.Integer(
        string="Progression (%)", compute='_compute_diligence_progress')
    diligence_subtask_count = fields.Integer(
        string="Nombre de sous-tâches", compute='_compute_diligence_progress')
    diligence_overdue = fields.Boolean(
        string="En retard", compute='_compute_diligence_overdue')

    def _group_expand_diligence_state(self, states, domain, order):
        # Toujours afficher les 4 colonnes du kanban, même vides.
        return [key for key, _val in self._fields['diligence_state'].selection]

    @api.depends('child_ids.diligence_state', 'diligence_state')
    def _compute_diligence_progress(self):
        for task in self:
            subtasks = task.child_ids
            task.diligence_subtask_count = len(subtasks)
            if subtasks:
                done = len(subtasks.filtered(lambda t: t.diligence_state == 'done'))
                task.diligence_progress = round(100 * done / len(subtasks))
            else:
                task.diligence_progress = 100 if task.diligence_state == 'done' else 0

    @api.depends('date_deadline', 'diligence_state')
    def _compute_diligence_overdue(self):
        today = fields.Date.context_today(self)
        for task in self:
            deadline = fields.Date.to_date(task.date_deadline)
            task.diligence_overdue = bool(
                deadline and deadline < today and task.diligence_state != 'done')

    def write(self, vals):
        res = super().write(vals)
        # Garder l'état standard d'Odoo cohérent avec l'étape de la diligence,
        # pour que le module Projet classique reflète la réalité.
        if 'diligence_state' in vals and 'state' not in vals:
            if vals['diligence_state'] == 'done':
                to_close = self.filtered(lambda t: t.state not in ('1_done', '1_canceled'))
                if to_close:
                    super(ProjectTask, to_close).write({'state': '1_done'})
            else:
                to_reopen = self.filtered(lambda t: t.state in ('1_done', '1_canceled'))
                if to_reopen:
                    super(ProjectTask, to_reopen).write({'state': '01_in_progress'})
        return res
