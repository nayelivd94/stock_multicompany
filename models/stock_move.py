# -*- coding: utf-8 -*-
from odoo import models, fields, api,_
from odoo.tools.float_utils import float_compare, float_round, float_is_zero
import logging
_logger = logging.getLogger(__name__)


class StockMulticompanyStockMove(models.Model):
    _inherit = 'stock.move'

    state = fields.Selection([
        ('draft', 'New'), ('cancel', 'Cancelled'),
        ('waiting', 'Waiting Another Move'), ('confirmed', 'Waiting Availability'),
        ('assigned', 'Available'), ('done', 'Done'),('consignacion', 'consignacion')], string='Status',
        copy=False, default='draft', index=True, readonly=True,
        help="* New: When the stock move is created and not yet confirmed.\n"
             "* Waiting Another Move: This state can be seen when a move is waiting for another one, for example in a chained flow.\n"
             "* Waiting Availability: This state is reached when the procurement resolution is not straight forward. It may need the scheduler to run, a component to be manufactured...\n"
             "* Available: When products are reserved, it is set to \'Available\'.\n"
             "* Done: When the shipment is processed, the state is \'Done\'.")

    # TDE DECORATOR: internal
    @api.multi
    def check_recompute_pack_op_consignacion(self):
        pickings = self.mapped('picking_id').filtered(lambda picking: picking.state not in ('waiting', 'confirmed'))  # In case of 'all at once' delivery method it should not prepare pack operations sale en blanco cuando no tiene
        # Check if someone was treating the picking already
        pickings_partial = pickings.filtered(lambda picking: not any(operation.qty_done for operation in picking.pack_operation_ids)) #si tiene disponible se pone igual que el otro
        pickings_partial.do_prepare_partial()
        (pickings - pickings_partial).write({'recompute_pack_op': True})

    @api.multi
    def force_assign_consignacion(self):
        # TDE CLEANME: removed return value
        self.write({'state': 'assigned'})
        self.check_recompute_pack_op_consignacion()


    @api.multi
    def _compute_string_qty_information(self):
        sSelf = self.sudo()
        precision = sSelf.env['decimal.precision'].precision_get('Product Unit of Measure')
        void_moves = sSelf.filtered(lambda move: move.state in ('draft', 'done', 'cancel') or move.location_id.usage != 'internal')
        other_moves = sSelf - void_moves
        for move in void_moves:
            move.string_availability_info = ''  # 'not applicable' or 'n/a' could work too
        for move in other_moves:
            total_available = min(move.product_qty, move.reserved_availability + move.availability)
            total_available = move.product_id.uom_id._compute_quantity(total_available, move.product_uom, round=False)
            total_available = float_round(total_available, precision_digits=precision)
            info = str(total_available)
            if sSelf.user_has_groups('product.group_uom'):
                info += ' ' + move.product_uom.name
            if move.reserved_availability:
                if move.reserved_availability != total_available:
                    # some of the available quantity is assigned and some are available but not reserved
                    reserved_available = move.product_id.uom_id._compute_quantity(move.reserved_availability, move.product_uom, round=False)
                    reserved_available = float_round(reserved_available, precision_digits=precision)
                    info += _(' (%s reserved)') % str(reserved_available)
                else:
                    # all available quantity is assigned
                    info += _(' (reserved)')
            move.string_availability_info = info

    @api.multi
    def check_recompute_pack_op(self):
        _logger.info(_("ente check_recompute_pack_op"))
        pickings = self.mapped('picking_id').filtered(lambda picking: picking.state not in ('waiting','confirmed'))  # In case of 'all at once' delivery method it should not prepare pack operations sale en blanco cuando no tiene
        # Check if someone was treating the picking already
        pickings_partial = pickings.filtered(lambda picking: not any(operation.qty_done for operation in picking.pack_operation_ids))  # si tiene disponible se pone igual que el otro
        _logger.info(_("ente check_recompute_pack_op pickings partial ")%(pickings_partial))
        pickings_partial.do_prepare_partial()
        (pickings - pickings_partial).write({'recompute_pack_op': True})


    @api.multi
    def force_assign(self):
        #_logger.info("hola entre a force_Assign")
        # TDE CLEANME: removed return value
        self.write({'state': 'assigned'})
        self.check_recompute_pack_op_consignacion()

    @api.multi
    def action_assign(self, no_prepare=False):
        """ Checks the product type and accordingly writes the state. """
        # TDE FIXME: remove decorator once everything is migrated
        # TDE FIXME: clean me, please
        main_domain = {}
        _logger.info("Hola entre a action assigggggggggggggggn")

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
            valor = False
            _logger.info(_("move.picking_id.origin.find(PO)  %s") % (move.picking_id.origin.find("PO")))
            if move.qty_stock == 0 and move.picking_id.origin.find("PO") == -1:
                valor = True
            _logger.info(_("valor %s") % (valor))
            if move.product_id.type == 'consu' and not ancestors and valor == False:
            #if move.product_id.type == 'consu' and not ancestors:
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
            self.check_recompute_pack_op()


