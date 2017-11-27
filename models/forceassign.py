# -*- coding: utf-8 -*-
from odoo import models, fields, api, exceptions,_
from odoo.tools.float_utils import float_compare
from openerp.exceptions import UserError, RedirectWarning, ValidationError
from collections import namedtuple
import logging
_logger = logging.getLogger(__name__)

class Forceassign(models.Model):
    _inherit = 'stock.picking'

    @api.multi
    def force_assign2(self):
        """ Changes state of picking to available if moves are confirmed or waiting.
        @return: True
        """
        self.mapped('move_lines').filtered(lambda move: move.state in ['confirmed', 'waiting']).force_assign()
        return True