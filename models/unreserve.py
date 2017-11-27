# -*- coding: utf-8 -*-
from odoo import models, fields, api, exceptions,_
from odoo.tools.float_utils import float_compare
from openerp.exceptions import UserError, RedirectWarning, ValidationError
from collections import namedtuple
import logging
_logger = logging.getLogger(__name__)

class UnreserveMuticompanyStockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.multi
    def action_assign2(self):
        """ Check availability of picking moves.
        This has the effect of changing the state and reserve quants on available moves, and may
        also impact the state of the picking as it is computed based on move's states.
        @return: True
        """
        self.filtered(lambda picking: picking.state == 'draft').action_confirm()
        moves = self.mapped('move_lines').filtered(lambda move: move.state not in ('draft', 'cancel', 'done') and move.qty_stock > 0)
        if not moves:
            raise UserError(_('Nothing to check the availability for.'))
        moves.action_assign2()
        return True
    @api.one
    def validateqty(self):
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
    def do_prepare_partial2(self):
        # TDE CLEANME: oh dear ...
        PackOperation = self.env['stock.pack.operation']

        # get list of existing operations and delete them
        existing_packages = PackOperation.search([('picking_id', 'in', self.ids)])  # TDE FIXME: o2m / m2o ?
        if existing_packages:
            existing_packages.unlink()
        for picking in self:
            forced_qties = {}  # Quantity remaining after calculating reserved quants
            picking_quants = self.env['stock.quant']
            # Calculate packages, reserved quants, qtys of this picking's moves
            for move in picking.move_lines:
                if move.state not in ('assigned', 'confirmed', 'waiting'):
                    continue
                move_quants = move.reserved_quant_ids
                picking_quants += move_quants
                forced_qty = 0.0
                if move.state == 'assigned':
                    qty = move.product_uom._compute_quantity(move.product_uom_qty, move.product_id.uom_id, round=False)
                    forced_qty = qty - sum([x.qty for x in move_quants])
                # if we used force_assign() on the move, or if the move is incoming, forced_qty > 0
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
        # recompute the remaining quantities all at once
        self.validateqty()
        self.do_recompute_remaining_quantities()
        self.write({'recompute_pack_op': False})

class UnreserveMuticompanyMove(models.Model):
    _inherit = 'stock.move'

    @api.multi
    def action_assign2(self, no_prepare=False):
        """ Checks the product type and accordingly writes the state. """
        # TDE FIXME: remove decorator once everything is migrated
        # TDE FIXME: clean me, please
        main_domain = {}

        Quant = self.env['stock.quant']
        Uom = self.env['product.uom']
        moves_to_assign = self.env['stock.move']
        moves_to_do = self.env['stock.move']
        operations = self.env['stock.pack.operation']
        ancestors_list = {}

        # work only on in progress moves
        moves = self.filtered(lambda move: move.state in ['confirmed', 'waiting', 'assigned'])
        moves.filtered(lambda move: move.reserved_quant_ids).do_unreserve()
        for move in moves:
            if move.location_id.usage in ('supplier', 'inventory', 'production'):
                moves_to_assign |= move
                # TDE FIXME: what ?
                # in case the move is returned, we want to try to find quants before forcing the assignment
                if not move.origin_returned_move_id:
                    continue
            # if the move is preceeded, restrict the choice of quants in the ones moved previously in original move
            ancestors = move.find_move_ancestors()
            if move.product_id.type == 'consu' and not ancestors:
                moves_to_assign |= move
                continue
            else:
                moves_to_do |= move

                # we always search for yet unassigned quants
                main_domain[move.id] = [('reservation_id', '=', False), ('qty', '>', 0)]

                ancestors_list[move.id] = True if ancestors else False
                if move.state == 'waiting' and not ancestors:
                    # if the waiting move hasn't yet any ancestor (PO/MO not confirmed yet), don't find any quant available in stock
                    main_domain[move.id] += [('id', '=', False)]
                elif ancestors:
                    main_domain[move.id] += [('history_ids', 'in', ancestors.ids)]

                # if the move is returned from another, restrict the choice of quants to the ones that follow the returned move
                if move.origin_returned_move_id:
                    main_domain[move.id] += [('history_ids', 'in', move.origin_returned_move_id.id)]
                for link in move.linked_move_operation_ids:
                    operations |= link.operation_id

        # Check all ops and sort them: we want to process first the packages, then operations with lot then the rest
        operations = operations.sorted(
            key=lambda x: ((x.package_id and not x.product_id) and -4 or 0) + (x.package_id and -2 or 0) + (
                x.pack_lot_ids and -1 or 0))
        for ops in operations:
            # TDE FIXME: this code seems to be in action_done, isn't it ?
            # first try to find quants based on specific domains given by linked operations for the case where we want to rereserve according to existing pack operations
            if not (ops.product_id and ops.pack_lot_ids):
                for record in ops.linked_move_operation_ids:
                    move = record.move_id
                    if move.id in main_domain:
                        qty = record.qty
                        domain = main_domain[move.id]
                        if qty:
                            quants = Quant.quants_get_preferred_domain(qty, move, ops=ops, domain=domain,
                                                                       preferred_domain_list=[])
                            Quant.quants_reserve(quants, move, record)
            else:
                lot_qty = {}
                rounding = ops.product_id.uom_id.rounding
                for pack_lot in ops.pack_lot_ids:
                    lot_qty[pack_lot.lot_id.id] = ops.product_uom_id._compute_quantity(pack_lot.qty,
                                                                                       ops.product_id.uom_id)
                for record in ops.linked_move_operation_ids:
                    move_qty = record.qty
                    move = record.move_id
                    domain = main_domain[move.id]
                    for lot in lot_qty:
                        if float_compare(lot_qty[lot], 0, precision_rounding=rounding) > 0 and float_compare(move_qty,
                                                                                                             0,
                                                                                                             precision_rounding=rounding) > 0:
                            qty = min(lot_qty[lot], move_qty)
                            quants = Quant.quants_get_preferred_domain(qty, move, ops=ops, lot_id=lot, domain=domain,
                                                                       preferred_domain_list=[])
                            Quant.quants_reserve(quants, move, record)
                            lot_qty[lot] -= qty
                            move_qty -= qty

        # Sort moves to reserve first the ones with ancestors, in case the same product is listed in
        # different stock moves.
        for move in sorted(moves_to_do, key=lambda x: -1 if ancestors_list.get(x.id) else 0):
            # then if the move isn't totally assigned, try to find quants without any specific domain
            if move.state != 'assigned' and not self.env.context.get('reserve_only_ops'):
                qty_already_assigned = move.reserved_availability
                qty = move.product_qty - qty_already_assigned

                quants = Quant.quants_get_preferred_domain(qty, move, domain=main_domain[move.id],
                                                           preferred_domain_list=[])
                Quant.quants_reserve(quants, move)

        # force assignation of consumable products and incoming from supplier/inventory/production
        # Do not take force_assign as it would create pack operations
        if moves_to_assign:
            moves_to_assign.write({'state': 'assigned'})
        if not no_prepare:
            self.check_recompute_pack_op2()

    @api.multi
    def check_recompute_pack_op2(self):
        pickings = self.mapped('picking_id').filtered(lambda picking: picking.state not in (
        'waiting', 'confirmed'))  # In case of 'all at once' delivery method it should not prepare pack operations
        # Check if someone was treating the picking already
        pickings_partial = pickings.filtered(
            lambda picking: not any(operation.qty_done for operation in picking.pack_operation_ids))
        pickings_partial.do_prepare_partial2()
        (pickings - pickings_partial).write({'recompute_pack_op': True})




