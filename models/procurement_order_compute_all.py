# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import threading

from odoo import api, models, tools, _, registry
from openerp.exceptions import UserError, RedirectWarning, ValidationError
import logging
_logger = logging.getLogger(__name__)



# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import threading

from odoo import api, models, tools, registry

_logger = logging.getLogger(__name__)


class ProcurementComputeAll(models.TransientModel):
    _inherit = 'procurement.order.compute.all'

    @api.multi
    def _procure_calculation_all2(self):
        with api.Environment.manage():
            _logger.info("hola entre back")
            # As this function is in a new thread, i need to open a new cursor, because the old one may be closed
            new_cr = registry(self._cr.dbname).cursor()
            self = self.with_env(self.env(cr=new_cr))  # TDE FIXME
            scheduler_cron = self.sudo().env.ref('procurement.ir_cron_scheduler_action')
            # Avoid to run the scheduler multiple times in the same time
            try:
                with tools.mute_logger('odoo.sql_db'):
                    self._cr.execute("SELECT id FROM ir_cron WHERE id = %s FOR UPDATE NOWAIT", (scheduler_cron.id,))
            except Exception:
                _logger.info('Attempt to run procurement scheduler aborted, as already running')
                self._cr.rollback()
                self._cr.close()
                return {}

            Procurement = self.env['procurement.order']
            #for company in self.env.user.company_ids:
            Procurement.run_scheduler(use_new_cursor=self._cr.dbname, company_id=False)
            # close the new cursor
            self._cr.close()
            return {}

    @api.multi
    def procure_calculation2(self):
        threaded_calculation = threading.Thread(target=self._procure_calculation_all2, args=())
        threaded_calculation.start()
        return {'type': 'ir.actions.act_window_close'}