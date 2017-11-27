# coding=utf-8
from odoo import models, fields, api, _,registry
from collections import defaultdict
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT, float_compare, float_round
from psycopg2 import OperationalError
from datetime import datetime
from dateutil.relativedelta import relativedelta
from odoo.osv import expression
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT, float_compare, float_round
import logging
import threading

_logger = logging.getLogger(__name__)




class StockMulticompanyProcurementOrder(models.Model):
    _name = 'procurement.order'
    _inherit = 'procurement.order'

    @api.model
    def _procure_orderpoint_confirm_supplier(self, use_new_cursor=False, company_id=False, filter_supplier=False):
        """ Create procurements based on orderpoints.
        :param bool use_new_cursor: if set, use a dedicated cursor and auto-commit after processing each procurement.
            This is appropriate for batch jobs only.
        """
        _logger.info("hola entre al metodo")
        if use_new_cursor:
            cr = registry(self._cr.dbname).cursor()
            self = self.with_env(self.env(cr=cr))

        OrderPoint = self.env['stock.warehouse.orderpoint']
        Procurement = self.env['procurement.order']
        domain = self._get_orderpoint_domain(company_id=company_id)
        ProcurementAutorundefer = Procurement.with_context(procurement_autorun_defer=True)
        procurement_list = []
        supplierinfo = self.env['product.supplierinfo'].search([('name', '=', filter_supplier.id)])
        prod = []
        prod2 = []
        for supplier in supplierinfo:
            _logger.info("hola entro a prod2")
            prod2.append(supplier.product_tmpl_id.id)
        _logger.info(_("valor %s")%(prod2))
        for p in range(0, len(prod2)):
            _logger.info(_("hola entro a prod %s")%(prod2[p]))
            product = self.env['product.product'].search([('product_tmpl_id', '=', prod2[p])])
            prod.append(product.id)
            _logger.info(_("REVISAAAAAAAAAAAAAAAAAA entre %s") % (product.id))
        _logger.info(_("valor prod %s") % (prod))
        orderpoints_noprefetch = OrderPoint.with_context(prefetch_fields=False).search(
            company_id and [('company_id', '=', company_id),('product_id', 'in', prod)] or [('product_id', 'in', prod)],
            order=self._procurement_from_orderpoint_get_order())
        _logger.info(_("REVISAAAAAAAAAAAAAAAAAA entre %s") % (orderpoints_noprefetch))

        while orderpoints_noprefetch:
            orderpoints = OrderPoint.browse(orderpoints_noprefetch[:1000].ids)
            orderpoints_noprefetch = orderpoints_noprefetch[1000:]

            # Calculate groups that can be executed together
            location_data = defaultdict(lambda: dict(products=self.env['product.product'], orderpoints=self.env['stock.warehouse.orderpoint'], groups=list()))
            for orderpoint in orderpoints:
                key = self._procurement_from_orderpoint_get_grouping_key([orderpoint.id])
                location_data[key]['products'] += orderpoint.product_id
                location_data[key]['orderpoints'] += orderpoint
                location_data[key]['groups'] = self._procurement_from_orderpoint_get_groups([orderpoint.id])

            for location_id, location_data in location_data.iteritems():
                location_orderpoints = location_data['orderpoints']
                product_context = dict(self._context, location=location_orderpoints[0].location_id.id)
                substract_quantity = location_orderpoints.subtract_procurements_from_orderpoints()

                for group in location_data['groups']:
                    if group['to_date']:
                        product_context['to_date'] = group['to_date'].strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                    product_quantity = location_data['products'].with_context(product_context)._product_available()
                    for orderpoint in location_orderpoints:
                        try:
                            op_product_virtual = product_quantity[orderpoint.product_id.id]['virtual_available']
                            if op_product_virtual is None:
                                continue
                            if float_compare(op_product_virtual, orderpoint.product_min_qty, precision_rounding=orderpoint.product_uom.rounding) <= 0:
                                qty = max(orderpoint.product_min_qty, orderpoint.product_max_qty) - op_product_virtual
                                remainder = orderpoint.qty_multiple > 0 and qty % orderpoint.qty_multiple or 0.0

                                if float_compare(remainder, 0.0, precision_rounding=orderpoint.product_uom.rounding) > 0:
                                    qty += orderpoint.qty_multiple - remainder

                                if float_compare(qty, 0.0, precision_rounding=orderpoint.product_uom.rounding) < 0:
                                    continue

                                qty -= substract_quantity[orderpoint.id]
                                qty_rounded = float_round(qty, precision_rounding=orderpoint.product_uom.rounding)
                                if qty_rounded > 0:
                                    new_procurement = ProcurementAutorundefer.create(
                                        orderpoint._prepare_procurement_values(qty_rounded, **group['procurement_values']))
                                    procurement_list.append(new_procurement)
                                    new_procurement.message_post_with_view('mail.message_origin_link',
                                        values={'self': new_procurement, 'origin': orderpoint},
                                        subtype_id=self.env.ref('mail.mt_note').id)
                                    self._procurement_from_orderpoint_post_process([orderpoint.id])
                                if use_new_cursor:
                                    cr.commit()

                        except OperationalError:
                            if use_new_cursor:
                                orderpoints_noprefetch += orderpoint.id
                                cr.rollback()
                                continue
                            else:
                                raise

            try:
                # TDE CLEANME: use record set ?
                procurement_list.reverse()
                procurements = self.env['procurement.order']
                for p in procurement_list:
                    procurements += p
                procurements.run()
                if use_new_cursor:
                    cr.commit()
            except OperationalError:
                if use_new_cursor:
                    cr.rollback()
                    continue
                else:
                    raise

            if use_new_cursor:
                cr.commit()

        if use_new_cursor:
            cr.commit()
            cr.close()
        return {}

    @api.model
    def _procure_orderpoint_confirm_supplier2(self, use_new_cursor=False, company_id=False,filter_supplier=False):
        """ Create procurements based on orderpoints.
        :param bool use_new_cursor: if set, use a dedicated cursor and auto-commit after processing
            1000 orderpoints.
            This is appropriate for batch jobs only.
        """
        OrderPoint = self.env['stock.warehouse.orderpoint']
        Procurement = self.env['procurement.order']
        domain = self._get_orderpoint_domain(company_id=company_id)
        ProcurementAutorundefer = Procurement.with_context(procurement_autorun_defer=True)
        procurement_list = []
        supplierinfo = self.env['product.supplierinfo'].search([('name', '=', filter_supplier.id)])
        prod = []
        prod2 = []
        for supplier in supplierinfo:
            _logger.info("hola entro a prod2-2  ")
            prod2.append(supplier.product_tmpl_id.id)
        _logger.info(_("valor %s") % (prod2))
        for p in range(0, len(prod2)):
            _logger.info(_("hola entro a prod %s") % (prod2[p]))
            product = self.env['product.product'].search([('product_tmpl_id', '=', prod2[p])])
            prod.append(product.id)
            _logger.info(_("REVISAAAAAAAAAAAAAAAAAA entre %s") % (product.id))
        _logger.info(_("valor prod %s") % (prod))
        for l in range(0, len(prod)):
            orderpoints_noprefetch = OrderPoint.with_context(prefetch_fields=False).search(
                company_id and [('company_id', '=', company_id), ('product_id', '=', prod[l])],
                order=self._procurement_from_orderpoint_get_order())
            _logger.info(_("REVISAAAAAAAAAAAAAAAAAA entre %s") % (orderpoints_noprefetch))

            if use_new_cursor:
                cr = registry(self._cr.dbname).cursor()
                self = self.with_env(self.env(cr=cr))
                orderpoints = OrderPoint.browse(orderpoints_noprefetch[:1000].ids)
                orderpoints_noprefetch = orderpoints_noprefetch[1000:]

                # Calculate groups that can be executed together
                location_data = defaultdict(lambda: dict(products=self.env['product.product'],
                                                         orderpoints=self.env['stock.warehouse.orderpoint'],
                                                         groups=list()))
                for orderpoint in orderpoints:
                    key = self._procurement_from_orderpoint_get_grouping_key([orderpoint.id])
                    location_data[key]['products'] += orderpoint.product_id
                    location_data[key]['orderpoints'] += orderpoint
                    location_data[key]['groups'] = self._procurement_from_orderpoint_get_groups([orderpoint.id])

                for location_id, location_data in location_data.iteritems():
                    location_orderpoints = location_data['orderpoints']
                    product_context = dict(self._context, location=location_orderpoints[0].location_id.id)
                    substract_quantity = location_orderpoints.subtract_procurements_from_orderpoints()

                    for group in location_data['groups']:
                        if group['to_date']:
                            product_context['to_date'] = group['to_date'].strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                        product_quantity = location_data['products'].with_context(product_context)._product_available()
                        for orderpoint in location_orderpoints:
                            try:
                                op_product_virtual = product_quantity[orderpoint.product_id.id]['virtual_available']
                                if op_product_virtual is None:
                                    continue
                                if float_compare(op_product_virtual, orderpoint.product_min_qty,
                                                 precision_rounding=orderpoint.product_uom.rounding) <= 0:
                                    qty = max(orderpoint.product_min_qty,
                                              orderpoint.product_max_qty) - op_product_virtual
                                    remainder = orderpoint.qty_multiple > 0 and qty % orderpoint.qty_multiple or 0.0

                                    if float_compare(remainder, 0.0,
                                                     precision_rounding=orderpoint.product_uom.rounding) > 0:
                                        qty += orderpoint.qty_multiple - remainder

                                    if float_compare(qty, 0.0, precision_rounding=orderpoint.product_uom.rounding) < 0:
                                        continue

                                    qty -= substract_quantity[orderpoint.id]
                                    qty_rounded = float_round(qty, precision_rounding=orderpoint.product_uom.rounding)
                                    if qty_rounded > 0:
                                        new_procurement = ProcurementAutorundefer.create(
                                            orderpoint._prepare_procurement_values(qty_rounded,
                                                                                   **group['procurement_values']))
                                        procurement_list.append(new_procurement)
                                        new_procurement.message_post_with_view('mail.message_origin_link',
                                                                               values={'self': new_procurement,
                                                                                       'origin': orderpoint},
                                                                               subtype_id=self.env.ref(
                                                                                   'mail.mt_note').id)
                                        self._procurement_from_orderpoint_post_process([orderpoint.id])
                                    if use_new_cursor:
                                        cr.commit()

                            except OperationalError:
                                if use_new_cursor:
                                    orderpoints_noprefetch += orderpoint.id
                                    cr.rollback()
                                    continue
                                else:
                                    raise

                try:
                    # TDE CLEANME: use record set ?
                    procurement_list.reverse()
                    procurements = self.env['procurement.order']
                    for p in procurement_list:
                        procurements += p
                    procurements.run()
                    if use_new_cursor:
                        cr.commit()
                except OperationalError:
                    if use_new_cursor:
                        cr.rollback()
                        continue
                    else:
                        raise

            if use_new_cursor:
                cr.commit()
                cr.close()

        return {}
    @api.model
    def run_scheduler(self, use_new_cursor=False, company_id=False):
        ''' Call the scheduler in order to check the running procurements (super method), to check the minimum stock rules
        and the availability of moves. This function is intended to be run for all the companies at the same time, so
        we run functions as SUPERUSER to avoid intercompanies and access rights issues. '''
        super(StockMulticompanyProcurementOrder, self).run_scheduler(use_new_cursor=use_new_cursor, company_id=company_id)
        try:
            if use_new_cursor:
                cr = registry(self._cr.dbname).cursor()
                self = self.with_env(self.env(cr=cr))  # TDE FIXME

            # Minimum stock rules
            self.sudo()._procure_orderpoint_confirm(use_new_cursor=use_new_cursor, company_id=company_id)

            # Search all confirmed stock_moves and try to assign them
            confirmed_moves = self.env['stock.move'].search([('state', '=', 'confirmed')], limit=None, order='priority desc, date_expected asc')
            for x in xrange(0, len(confirmed_moves.ids), 100):
                # TDE CLEANME: muf muf
                _logger.info(_("Run scheduler: "))
                self.env['stock.move'].browse(confirmed_moves.ids[x:x + 100]).action_assign()
                self.env['stock.move'].browse(confirmed_moves.ids[x:x + 100]).force_assign_consignation()
                if use_new_cursor:
                    self._cr.commit()
            if use_new_cursor:
                self._cr.commit()
        finally:
            if use_new_cursor:
                try:
                    self._cr.close()
                except Exception:
                    pass
        return {}

