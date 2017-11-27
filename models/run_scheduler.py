# -*- coding: utf-8 -*-
from odoo import models, fields, api,_

from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT, float_compare
from openerp.exceptions import UserError, RedirectWarning, ValidationError
import logging
_logger = logging.getLogger(__name__)

class Stockmoves(models.Model):
    _inherit = 'stock.move'

    @api.multi
    def force_assign_consignation(self):
        # TDE CLEANME: removed return value
        self.write({'state': 'assigned'})
        self.check_recompute_pack_op_consignation()

    @api.multi
    def check_recompute_pack_op_consignation(self):
        pickings = self.mapped('picking_id').filtered(lambda picking: picking.state not in ('waiting',
                                                                                            'confirmed'))  # In case of 'all at once' delivery method it should not prepare pack operations sale en blanco cuando no tiene
        # Check if someone was treating the picking already
        pickings_partial = pickings.filtered(lambda picking: not any(operation.qty_done for operation in
                                                                     picking.pack_operation_ids))  # si tiene disponible se pone igual que el otro
        pickings_partial.do_prepare_partial_consignation()
        (pickings - pickings_partial).write({'recompute_pack_op': True})

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.multi
    def validationqty(self):
        picking=self
        for move in picking.move_lines:
            if move.qty_stock < move.product_uom_qty:
                move.write({'state': 'confirmed'})
        for pack in picking.pack_operation_product_ids:
            move_obj = self.env['stock.move']
            moveid = move_obj.search([
                ('picking_id', '=', picking.id),
                ('product_id', '=', pack.product_id.id)])
            _logger.info(_("product_qty %s") % (pack.product_qty))
            _logger.info(_("product_uom_qty %s") % (moveid.product_uom_qty))
            _logger.info(_(" picking.qty_stock  %s") % (pack.qty_stock))
            # if pack.product_qty <> moveid.product_uom_qty and pack.qty_stock < moveid.product_uom_qty:
            if pack.product_qty > moveid.qty_stock:
                pack.write({'product_qty': pack.qty_stock})
    @api.multi
    def do_prepare_partial_consignation(self):
        # TDE CLEANME: oh dear ...
        sSelf = self.sudo()
        PackOperation = self.env['stock.pack.operation']
        _logger.info(_("DO PREPARE PARTIAL"))
        Sale = self.env['sale.order']
        existing_packages = PackOperation.search([('picking_id', 'in', self.ids)])  # TDE FIXME: o2m / m2o ?
        _logger.info(_("DO PREPARE PARTIAL EXISTING PACKAGE %s") % (existing_packages))
        if existing_packages:
            existing_packages.unlink()
            _logger.info(_("existing_packages.unlink() %s") % (existing_packages.unlink()))
        for picking in sSelf:
            forced_qties = {}  # Quantity remaining after calculating reserved quants
            picking_quants = sSelf.env['stock.quant']
            # Calculate packages, reserved quants, qtys of this picking's moves
            _logger.info(_("picking.move_lines %s") % (picking.move_lines))
            for move in picking.move_lines:
                bjh=move.origin
                if move.origin <> False :
                    if move.origin.find('SO') == -1:
                        # move.consignar()
                        if move.state not in ('assigned', 'confirmed', 'waiting'):
                            continue
                        # _logger.info(_("move_quants QUE NO DEBE ENTRAR  %s") % (move_quants))
                        move_quants = move.reserved_quant_ids
                        picking_quants += move_quants
                        forced_qty = 0.0
                        if move.state == 'assigned':
                            qty = move.product_uom._compute_quantity(move.product_uom_qty, move.product_id.uom_id,
                                                                     round=False)
                            forced_qty = qty - sum([x.qty for x in move_quants])
                        if float_compare(forced_qty, 0, precision_rounding=move.product_id.uom_id.rounding) > 0:
                            if forced_qties.get(move.product_id):
                                forced_qties[move.product_id] += forced_qty
                            else:
                                forced_qties[move.product_id] = forced_qty
                    else:
                        _logger.info(_("ELSEEEE DO PREPARE PARTIAL E "))
                        if move.state not in ('assigned', 'confirmed', 'waiting', 'consignacion'):
                            continue
                        move_quants = move.reserved_quant_ids
                        _logger.info(_("move_quants  %s") % (move_quants))
                        picking_quants += move_quants
                        _logger.info(_("picking_quants  %s") % (picking_quants))
                        forced_qty = 0.0
                        if move.state == 'assigned':
                            qty = move.product_uom._compute_quantity(move.product_uom_qty, move.product_id.uom_id,
                                                                     round=False)
                            _logger.info(_("qty %s") % (qty))
                            if move.product_id.qty_available - qty < 0:
                                forced_qty = move.product_id.qty_available
                            else:
                                forced_qty = qty - sum([x.qty for x in move_quants])
                        _logger.info(_("forced_qty  %s") % (forced_qty))
                        # if we used force_assign() on the move, or if the move is incoming, forced_qty > 0
                        if float_compare(forced_qty, 0, precision_rounding=move.product_id.uom_id.rounding) > 0:
                            if forced_qties.get(move.product_id):
                                forced_qties[move.product_id] += forced_qty
                            else:
                                forced_qties[move.product_id] = forced_qty
                else:
                    # move.consignar()
                    if move.state not in ('assigned', 'confirmed', 'waiting'):
                        continue
                    # _logger.info(_("move_quants QUE NO DEBE ENTRAR  %s") % (move_quants))
                    move_quants = move.reserved_quant_ids
                    picking_quants += move_quants
                    forced_qty = 0.0
                    if move.state == 'assigned':
                        qty = move.product_uom._compute_quantity(move.product_uom_qty, move.product_id.uom_id,
                                                                 round=False)
                        forced_qty = qty - sum([x.qty for x in move_quants])
                    if float_compare(forced_qty, 0, precision_rounding=move.product_id.uom_id.rounding) > 0:
                        if forced_qties.get(move.product_id):
                            forced_qties[move.product_id] += forced_qty
                        else:
                            forced_qties[move.product_id] = forced_qty

            _logger.info(_("forced_qties  %s") % (forced_qties))
            _logger.info(_("picking_quants %s") % (picking_quants))
            _logger.info(_("picking._prepare_pack_ops(picking_quants, forced_qties)  %s") % (
                picking._prepare_pack_ops(picking_quants, forced_qties)))
            for vals in picking._prepare_pack_ops(picking_quants, forced_qties):
                vals['fresh_record'] = False
                PackOperation.create(vals)
        self.do_recompute_remaining_quantities()
        self.validationqty()
        self.write({'recompute_pack_op': False})