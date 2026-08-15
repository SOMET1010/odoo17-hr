# -*- coding: utf-8 -*-
from odoo import api, fields, models

# Règle 3 (RH-PR-004) : pièces administratives à fournir par toute recrue.
DOCUMENTS_STANDARD = [
    "Fiche de renseignements",
    "CV actualisé",
    "Extrait de naissance",
    "Certificat de résidence ou facture CIE/SODECI",
    "Certificat de travail",
    "Copies conformes des diplômes",
    "Copie CNI, carte consulaire ou passeport",
    "Copie du livret de famille ou extrait de mariage",
    "Relevé d'identité bancaire (RIB)",
    "Photo d'identité",
    "Extrait de naissance des enfants",
    "Certificat de fréquentation des enfants",
]

# Étape 3 (RH-PR-004) : kit d'intégration par direction contributrice.
KIT_STANDARD = [
    ("Cartes d'assurance", 'drhcom'),
    ("Carte professionnelle", 'drhcom'),
    ("Règlement intérieur", 'drhcom'),
    ("Code d'éthique et de bonne conduite", 'drhcom'),
    ("Bureau (mobilier et espace de travail)", 'djmg'),
    ("Badge d'accès", 'djmg'),
    ("Carte de carburant (selon la fonction)", 'djmg'),
    ("Fournitures de bureau", 'djmg'),
    ("Cartes de visite", 'djmg'),
    ("Compte de messagerie et accès au SI", 'dsis'),
    ("Ordinateur", 'dsis'),
    ("Carte SIM (puce téléphonique)", 'dsis'),
]


class AnsutIntegration(models.Model):
    _name = 'ansut.integration'
    _description = "Dossier d'intégration d'une recrue (ANSUT-RH-PR-004)"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_prise_fonction desc, id desc'
    _rec_name = 'employee_id'

    employee_id = fields.Many2one(
        'hr.employee', string="Recrue", required=True, tracking=True)
    department_id = fields.Many2one(
        related='employee_id.department_id', string="Direction d'affectation",
        store=True)
    date_prise_fonction = fields.Date(
        string="Date de prise de fonction", tracking=True)
    accompagnateur_id = fields.Many2one(
        'hr.employee', string="Accompagnateur d'intégration", tracking=True,
        help="Ressource interne désignée par le Directeur d'affectation pour "
             "accompagner la recrue (étape 4 de la procédure).")
    state = fields.Selection([
        ('en_cours', "En cours"),
        ('terminee', "Terminée"),
    ], string="Statut", default='en_cours', tracking=True)
    document_ids = fields.One2many(
        'ansut.integration.document', 'integration_id',
        string="Pièces administratives")
    kit_ids = fields.One2many(
        'ansut.integration.kit', 'integration_id', string="Kit d'intégration")
    progress_documents = fields.Integer(
        string="Pièces reçues (%)", compute='_compute_progress')
    progress_kit = fields.Integer(
        string="Kit prêt (%)", compute='_compute_progress')
    note = fields.Text(string="Notes")

    @api.depends('document_ids.done', 'kit_ids.done')
    def _compute_progress(self):
        for rec in self:
            docs = rec.document_ids
            kit = rec.kit_ids
            rec.progress_documents = round(
                100 * len(docs.filtered('done')) / len(docs)) if docs else 0
            rec.progress_kit = round(
                100 * len(kit.filtered('done')) / len(kit)) if kit else 0

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.document_ids:
                rec.document_ids = [
                    (0, 0, {'name': name}) for name in DOCUMENTS_STANDARD]
            if not rec.kit_ids:
                rec.kit_ids = [
                    (0, 0, {'name': name, 'responsable': resp})
                    for name, resp in KIT_STANDARD]
        return records

    def action_terminer(self):
        self.write({'state': 'terminee'})

    def action_rouvrir(self):
        self.write({'state': 'en_cours'})


class AnsutIntegrationDocument(models.Model):
    _name = 'ansut.integration.document'
    _description = "Pièce administrative d'un dossier d'intégration"
    _order = 'id'

    integration_id = fields.Many2one(
        'ansut.integration', required=True, ondelete='cascade')
    name = fields.Char(string="Pièce", required=True)
    done = fields.Boolean(string="Reçue")
    date_reception = fields.Date(string="Reçue le")
    note = fields.Char(string="Remarque")


class AnsutIntegrationKit(models.Model):
    _name = 'ansut.integration.kit'
    _description = "Élément du kit d'intégration"
    _order = 'responsable, id'

    integration_id = fields.Many2one(
        'ansut.integration', required=True, ondelete='cascade')
    name = fields.Char(string="Élément", required=True)
    responsable = fields.Selection([
        ('drhcom', 'DRHCom'),
        ('djmg', 'DJMG'),
        ('dsis', 'DSIS'),
    ], string="Direction responsable", default='drhcom', required=True)
    done = fields.Boolean(string="Prêt")
    note = fields.Char(string="Remarque")
