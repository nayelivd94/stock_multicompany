# -*- coding: utf-8 -*-
from odoo import models, fields, api,_

from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT, float_compare
from openerp.exceptions import UserError, RedirectWarning, ValidationError
import logging
_logger = logging.getLogger(__name__)

class StockMultiCompanySaleOrderLine(models.Model):
    _name = 'sale.order.line'
    _inherit = 'sale.order.line'

    @api.multi
    def _action_procurement_create(self):
        res = super(StockMultiCompanySaleOrderLine, self)._action_procurement_create()
        orders = list(set(x.order_id for x in self.sudo()))
        for order in orders:
            reassigns = order.picking_ids.filtered(
                lambda x: x.state == 'confirmed' or ((x.state in ['partially_available', 'waiting']) and not x.printed))
            #_logger.info(_("entre sales order_ %s")%(reassign.id))
            if reassigns:
                #raise UserError(_("entra aqui al if de reasssssssssssssssssssssign..state %s")%(reassign.state))
                for reassign in reassigns:
                    reassign.do_unreserve()
                    reassign.action_assign()
                    reassign.consignar2()
                    for l in order.order_line:
                        for picking in  order.picking_ids:
                            for move in picking.move_lines:
                                if move.qty_stock < move.product_uom_qty:
                                    move.write({'state': 'confirmed'})
                            for pack in picking.pack_operation_product_ids:
                                move_obj = self.env['stock.move']
                                moveid = move_obj.search([
                                    ('picking_id', '=', picking.id),
                                    ('product_id', '=', pack.product_id.id)])
                                #_logger.info(_("product_qty %s")%(pack.product_qty))
                                #_logger.info(_(" picking.qty_stock  %s") % ( pack.qty_stock ))
                                #if pack.product_qty <> moveid.product_uom_qty and pack.qty_stock < moveid.product_uom_qty:
                                for move in moveid:
                                    moves = move.qty_stock
                                    if pack.product_qty > moves:
                                        pack.write({'product_qty': pack.qty_stock})


                    #self._cr.execute("delete from stock_pack_operation  where id in (select id from stock_pack_operation where product_id in(select product_id from stock_pack_operation where picking_id=%s  group by product_id having count(*)>1 )and picking_id=%s and package_id is null);",(picking.id,picking.id))

        return res




    @api.onchange('product_uom_qty', 'product_uom', 'route_id')
    def _onchange_product_id_check_availability(self):

        #res = super(StockMultiCompanySaleOrderLine,self)._onchange_product_id_check_availability()

        if not self.product_id or not self.product_uom_qty or not self.product_uom:
            self.product_packaging = False
            return {}#res
        if self.product_id.type == 'product':
            self.sudo()
            precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
            product_qty = self.product_uom._compute_quantity(self.product_uom_qty, self.product_id.uom_id)

            sSelf = self.sudo()
            sProduct = sSelf.env['product.template'].search([('id', '=', self.product_id.product_tmpl_id.id)])

            if float_compare(sProduct.virtual_available, product_qty, precision_digits=precision) == -1:
                is_available = self._check_routing()
                if not is_available:
                    warning_mess = {
                        'title': _('Not enough inventory!'),
                        'message' : _('You Plan to sell %s %s but you only have %s %s available!\nThe stock on hand is %s %s.') % \
                            (self.product_uom_qty, self.product_uom.name, sProduct.virtual_available, sProduct.uom_id.name, sProduct.qty_available, sProduct.uom_id.name)
                    }
                    #res.update({'warning': warning_mess})
                    return {'warning': warning_mess}
        return {}

        # 'You plan to sell %s %s but you only have %s %s available!\nThe stock on hand is %s %s.') % \
