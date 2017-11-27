# -*- coding: utf-8 -*-
from odoo import models, fields, api,_

from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT, float_compare
from openerp.exceptions import UserError, RedirectWarning, ValidationError
import logging
_logger = logging.getLogger(__name__)
class consStockPicking(models.Model):
    _inherit = 'stock.picking'
    @api.multi
    def consignar2(self):
        """ Changes state of picking to available if moves are confirmed or waiting.
        @return: True
        """
        #_logger.info(_("entro a botron de consitna"))
        sSelf = self.sudo()
        for line in sSelf.move_lines:
            if line.product_id.qty_available > 0:
                if line.state in  ['waiting','confirmed']:
                    line.state = 'consignacion'
        #raise UserError(_("entre ")%(self.mapped('move_lines').filtered(lambda move: move.state in ['consignacion'])))
        self.mapped('move_lines').filtered(lambda move: move.state in ['consignacion']).force_assign_consignacion()
        for pack in self.pack_operation_product_ids:
            move_obj = self.env['stock.move']
            moveid = move_obj.search([
                ('picking_id', '=', self.id),
                ('product_id', '=', pack.product_id.id)])
            packqty=pack.product_qty
            for move in moveid:
                moves=move.qty_stock
                if pack.product_qty > moves:
                    pack.write({'product_qty': pack.qty_stock})
        return True

    @api.multi
    def do_prepare_partial(self):
        # TDE CLEANME: oh dear ...
        sSelf = self.sudo()
        PackOperation = self.env['stock.pack.operation']
        _logger.info(_("DO PREPARE        partial 1"))
        Sale = self.env['sale.order']
        existing_packages = PackOperation.search([('picking_id', 'in', self.ids)])  # TDE FIXME: o2m / m2o ?
        _logger.info(_("DO PREPARE PARTIAL EXISTING 1 PACKAGE %s") % (existing_packages))
        if existing_packages:
            # existing_packages.unlink()
            _logger.info(_("existing_packages.unlink() %s") % (existing_packages.unlink()))
        for picking in sSelf:
            forced_qties = {}  # Quantity remaining after calculating reserved quants
            picking_quants = sSelf.env['stock.quant']
            # Calculate packages, reserved quants, qtys of this picking's moves
            _logger.info(_("picking.move_lines1 %s") % (picking.move_lines))
            for move in picking.move_lines:
                if move.origin is not False or move.origin is not None:
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
                        _logger.info(_("ELSEEEE DO PREPARE PARTIAL E1 "))
                        if move.state not in ('assigned', 'confirmed', 'waiting', 'consignacion'):
                            continue
                        move_quants = move.reserved_quant_ids
                        _logger.info(_("move_quants1  %s") % (move_quants))
                        picking_quants += move_quants
                        _logger.info(_("picking_quants1  %s") % (picking_quants))
                        forced_qty = 0.0
                        if move.state == 'assigned':
                            qty = move.product_uom._compute_quantity(move.product_uom_qty, move.product_id.uom_id,
                                                                     round=False)
                            _logger.info(_("qty1 %s") % (qty))
                            if move.product_id.qty_available - qty < 0:
                                forced_qty = move.product_id.qty_available
                            else:
                                forced_qty = qty - sum([x.qty for x in move_quants])
                        _logger.info(_("forced_qty1  %s") % (forced_qty))
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

            _logger.info(_("forced_qti1es  %s") % (forced_qties))
            _logger.info(_("picking_quants1 %s") % (picking_quants))
            _logger.info(_("picking._prepare_pack_ops(picking_quant1s, forced_qties)  %s") % (
                picking._prepare_pack_ops(picking_quants, forced_qties)))
            for vals in picking._prepare_pack_ops(picking_quants, forced_qties):
                vals['fresh_record'] = False
                PackOperation.create(vals)
        self.do_recompute_remaining_quantities()
        self.write({'recompute_pack_op': False})

class consiStockMove(models.Model):
    _inherit = 'stock.move'

    @api.multi
    def force_assign_consignacion(self):
        # TDE CLEANME: removed return value
        self.write({'state': 'assigned'})
        self.check_recompute_pack_op_consignacion()

    @api.multi
    def check_recompute_pack_op_consignacion(self):
        pickings = self.mapped('picking_id').filtered(lambda picking: picking.state not in ('waiting',
                                                                                            'confirmed'))  # In case of 'all at once' delivery method it should not prepare pack operations sale en blanco cuando no tiene
        # Check if someone was treating the picking already
        pickings_partial = pickings.filtered(lambda picking: not any(operation.qty_done for operation in
                                                                     picking.pack_operation_ids))  # si tiene disponible se pone igual que el otro
        pickings_partial.do_prepare_partial()
        (pickings - pickings_partial).write({'recompute_pack_op': True})