{
    'name': 'Stock Multi-Company',
    'version': '10.0.1',
    'summary': 'Suma los stock de todas las compañias',
    'description': 'Suma los stock de todas las compañias',
    'category': '',
    'author': 'Raul Ovalle, Nayeli Valencia Díaz',
    'website': '',
    'license': '',
    'depends': ['sale','stock', 'procurement_jit'],
    'data': [
        'views/stock_picking_view.xml',
        'views/sale_order_view.xml',
        'views/procurement_order_compute_all.xml',
        'views/procurement_orderpoint_compute_view.xml',


    ],
    'installable': True,
}