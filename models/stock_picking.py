# -*- coding: utf-8 -*-
from odoo import models, fields, api, exceptions,_
from odoo.tools.float_utils import float_compare
from openerp.exceptions import UserError, RedirectWarning, ValidationError
from collections import namedtuple
import logging
_logger = logging.getLogger(__name__)

class StockMuticompanyStockPicking(models.Model):
    _inherit = 'stock.picking'

    state = fields.Selection([
        ('draft', 'Draft'), ('cancel', 'Cancelled'),
        ('waiting', 'Waiting Another Operation'),
        ('confirmed', 'Waiting Availability'),
        ('partially_available', 'Partially Available'),
        ('assigned', 'Available'), ('done', 'Done'),('consignacion', 'consignacion')], string='Status', compute='_compute_state',
        copy=False, index=True, readonly=True, store=True, track_visibility='onchange',
        help=" * Draft: not confirmed yet and will not be scheduled until confirmed\n"
             " * Waiting Another Operation: waiting for another move to proceed before it becomes automatically available (e.g. in Make-To-Order flows)\n"
             " * Waiting Availability: still waiting for the availability of products\n"
             " * Partially Available: some products are available and reserved\n"
             " * Ready to Transfer: products reserved, simply waiting for confirmation.\n"
             " * Transferred: has been processed, can't be modified or cancelled anymore\n"
             " * Cancelled: has been cancelled, can't be confirmed anymore")
    @api.one
    def _compute_value(self):
        if self.origin is  not False:
            self.valor= self.origin[0:2]
        else:
            self.valor=""
    valor= fields.Char(string="Valor", compute='_compute_value')

    @api.one
    def _compute_hiddestate(self):
        if self.state=='confirmed' or  self.state=='waiting' or self.state=='partially_available' and self.valor=='SO':
            self.hiddestate=True
        else:
            self.hiddestate=False

    hiddestate = fields.Boolean(string="Valor", compute='_compute_hiddestate')



    def do_prepare_partial_consignacion(self):
        #_logger.info(_("entro a botron de prepararr         consitna"))
        sSelf = self.sudo()
        PackOperation = self.env['stock.pack.operation']
        Sale = self.env['sale.order']

        existing_packages = PackOperation.search([('picking_id', 'in', self.ids)])  # TDE FIXME: o2m / m2o ?
        if existing_packages:
            existing_packages.unlink()
        for picking in sSelf:
            forced_qties = {}  # Quantity remaining after calculating reserved quants

            picking_quants = sSelf.env['stock.quant']
            # Calculate packages, reserved quants, qtys of this picking's moves
            for move in picking.move_lines:
                if move.state not in ('assigned', 'confirmed', 'waiting','consignacion'):
                    continue
                move_quants = move.reserved_quant_ids
                picking_quants += move_quants
                forced_qty = 0.0
                if move.state == 'assigned':
                    qty = move.product_uom._compute_quantity(move.product_uom_qty, move.product_id.uom_id, round=False)
                    if move.product_id.qty_available - qty < 0:

                        forced_qty = move.product_id.qty_available

                    else:

                        forced_qty = qty - sum([x.qty for x in move_quants])

                # if we used force_assign() on the move, or if the move is incoming, forced_qty > 0
                if float_compare(forced_qty, 0, precision_rounding=move.product_id.uom_id.rounding) > 0:
                    if forced_qties.get(move.product_id):
                        forced_qties[move.product_id] += forced_qty
                    else:
                        forced_qties[move.product_id] = forced_qty
            for vals in picking._prepare_pack_ops(picking_quants, forced_qties):
                vals['fresh_record'] = False
                PackOperation.create(vals)
        self.do_recompute_remaining_quantities()
        self.write({'recompute_pack_op': False})




    @api.multi
    def consignar(self):
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
    def force_assign(self):
        """ Changes state of picking to available if moves are confirmed or waiting.
        @return: True
        """
        #_logger.info(_("entro a botron de  force assign"))
        sSelf = self.sudo()
        for line in sSelf.move_lines:
            if line.product_id.qty_available > 0:
                if line.state in ['waiting', 'confirmed']:
                    line.state = 'consignacion'
        self.mapped('move_lines').filtered(lambda move: move.state in ['consignacion']).force_assign_consignacion()
        return True



    # TDE DECORATOR: internal
    @api.multi
    def check_recompute_pack_op_consignacion(self):
        pickings = self.mapped('picking_id').filtered(lambda picking: picking.state not in ('waiting', 'confirmed'))  # In case of 'all at once' delivery method it should not prepare pack operations sale en blanco cuando no tiene
        pickings_partial = pickings.filtered(lambda picking: not any(operation.qty_done for operation in picking.pack_operation_ids)) #si tiene disponible se pone igual que el otro
        pickings_partial.do_prepare_partial()
        (pickings - pickings_partial).write({'recompute_pack_op': True})

    @api.multi
    def check_recompute_pack_op(self):
        #_logger.info("entre al check recompute de stock picking")
        pickings = self.mapped('picking_id').filtered(lambda picking: picking.state not in ('waiting',
                                                                                            'confirmed'))  # In case of 'all at once' delivery method it should not prepare pack operations sale en blanco cuando no tiene
        # Check if someone was treating the picking already
        pickings_partial = pickings.filtered(lambda picking: not any(operation.qty_done for operation in
                                                                     picking.pack_operation_ids))  # si tiene disponible se pone igual que el otro
        pickings_partial.do_prepare_partial()
        (pickings - pickings_partial).write({'recompute_pack_op': True})



    @api.depends('move_type', 'launch_pack_operations', 'move_lines.state', 'move_lines.picking_id',
                 'move_lines.partially_available')
    @api.one
    def _compute_state(self):
        ''' State of a picking depends on the state of its related stock.move
         - no moves: draft or assigned (launch_pack_operations)
         - all moves canceled: cancel
         - all moves done (including possible canceled): done
         - All at once picking: least of confirmed / waiting / assigned
         - Partial picking
          - all moves assigned: assigned
          - one of the move is assigned or partially available: partially available
          - otherwise in waiting or confirmed state
        '''
        if not self.move_lines and self.launch_pack_operations:
            self.state = 'assigned'
        elif not self.move_lines:
            self.state = 'draft'
        elif any(move.state == 'draft' for move in self.move_lines):  # TDE FIXME: should be all ?
            self.state = 'draft'
        elif all(move.state == 'cancel' for move in self.move_lines):
            self.state = 'cancel'
        elif all(move.state in ['cancel', 'done'] for move in self.move_lines):
            self.state = 'done'
        elif any(move.qty_stock< move.product_uom_qty and move.qty_stock > 0  for move in self.move_lines):
           self.state= 'partially_available'
        else:
            # We sort our moves by importance of state: "confirmed" should be first, then we'll have
            # "waiting" and finally "assigned" at the end.
            moves_todo = self.move_lines \
                .filtered(lambda move: move.state not in ['cancel', 'done']) \
                .sorted(key=lambda move: (move.state == 'assigned' and 2) or (move.state == 'waiting' and 1) or 0)
            if self.move_type == 'one':
                self.state = moves_todo[0].state
            elif moves_todo[0].state != 'assigned' and any(
                            x.partially_available or x.state == 'assigned' for x in moves_todo):
                self.state = 'partially_available'
            else:
                self.state = moves_todo[-1].state


    def _prepare_pack_ops(self, quants, forced_qties):
        """ Prepare pack_operations, returns a list of dict to give at create """
        # TDE CLEANME: oh dear ...
        valid_quants = quants.filtered(lambda quant: quant.qty > 0)
        _Mapping = namedtuple('Mapping', ('product', 'package', 'owner', 'location', 'location_dst_id'))

        all_products = valid_quants.mapped('product_id') | self.env['product.product'].browse(p.id for p in forced_qties.keys()) | self.move_lines.mapped('product_id')
        computed_putaway_locations = dict(
            (product, self.location_dest_id.get_putaway_strategy(product) or self.location_dest_id.id) for product in all_products)

        product_to_uom = dict((product.id, product.uom_id) for product in all_products)
        picking_moves = self.move_lines.filtered(lambda move: move.state not in ('done', 'cancel'))
        for move in picking_moves:
            # If we encounter an UoM that is smaller than the default UoM or the one already chosen, use the new one instead.
            if move.product_uom != product_to_uom[move.product_id.id] and move.product_uom.factor > product_to_uom[move.product_id.id].factor:
                product_to_uom[move.product_id.id] = move.product_uom
        if len(picking_moves.mapped('location_id')) > 1:
            raise UserError(_('The source location must be the same for all the moves of the picking.'))
        if len(picking_moves.mapped('location_dest_id')) > 1:
            raise UserError(_('The destination location must be the same for all the moves of the picking.'))

        pack_operation_values = []
        # find the packages we can move as a whole, create pack operations and mark related quants as done
        top_lvl_packages = valid_quants._get_top_level_packages(computed_putaway_locations)
        for pack in top_lvl_packages:
            _logger.info(_('entro al 1 er for '))
            pack_quants = pack.get_content()
            pack_operation_values.append({
                'picking_id': self.id,
                'package_id': pack.id,
                'product_qty': 1.0,
                'location_id': pack.location_id.id,
                'location_dest_id': computed_putaway_locations[pack_quants[0].product_id],
                'owner_id': pack.owner_id.id,
            })
            valid_quants -= pack_quants

        # Go through all remaining reserved quants and group by product, package, owner, source location and dest location
        # Lots will go into pack operation lot object
        qtys_grouped = {}
        lots_grouped = {}
        for quant in valid_quants:
            _logger.info(_('entro al 2er for '))
            key = _Mapping(quant.product_id, quant.package_id, quant.owner_id, quant.location_id, computed_putaway_locations[quant.product_id])
            qtys_grouped.setdefault(key, 0.0)
            qtys_grouped[key] += quant.qty
            _logger.info(_('qtys_grouped[key] %s')%(quant.qty))
            if quant.product_id.tracking != 'none' and quant.lot_id:
                lots_grouped.setdefault(key, dict()).setdefault(quant.lot_id.id, 0.0)
                lots_grouped[key][quant.lot_id.id] += quant.qty
        # Do the same for the forced quantities (in cases of force_assign or incomming shipment for example)
        for product, qty in forced_qties.items():
            _logger.info(_('for de force_qties %s') % ( qty ))
            if qty <= 0.0:
                continue
            key = _Mapping(product, self.env['stock.quant.package'], self.owner_id, self.location_id, computed_putaway_locations[product])
            qtys_grouped.setdefault(key, 0.0)
            qtys_grouped[key] += qty
        _logger.info(_('qtys_grouped[key] %s') % (qtys_grouped.items()))

        # Create the necessary operations for the grouped quants and remaining qtys
        Uom = self.env['product.uom']
        product_id_to_vals = {}  # use it to create operations using the same order as the picking stock moves
        for mapping, qty in qtys_grouped.items():
            uom = product_to_uom[mapping.product.id]
            _logger.info(_('qty  %s')%(qty))
            _logger.info(_(' mapping.product.uom_id._compute_quantity(qty, uom) %s') % ( mapping.product.uom_id._compute_quantity(qty, uom)))
            val_dict = {
                'picking_id': self.id,
                'product_qty': mapping.product.uom_id._compute_quantity(qty, uom),
                'product_id': mapping.product.id,
                'package_id': mapping.package.id,
                'owner_id': mapping.owner.id,
                'location_id': mapping.location.id,
                'location_dest_id': mapping.location_dst_id,
                'product_uom_id': uom.id,
                'pack_lot_ids': [
                    (0, 0, {'lot_id': lot, 'qty': 0.0, 'qty_todo': lots_grouped[mapping][lot]})
                    for lot in lots_grouped.get(mapping, {}).keys()],
            }
            product_id_to_vals.setdefault(mapping.product.id, list()).append(val_dict)

        for move in self.move_lines.filtered(lambda move: move.state not in ('done', 'cancel')):
            values = product_id_to_vals.pop(move.product_id.id, [])
            pack_operation_values += values
        _logger.info(_('pack_operation_values %s') % (pack_operation_values))
        return pack_operation_values

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
            existing_packages.unlink()
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
                        #_logger.info(_("move_quants QUE NO DEBE ENTRAR  %s") % (move_quants))
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
                        _logger.info(_("ELSEEEE DO PREPARE PARTIAL E1 ") )
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