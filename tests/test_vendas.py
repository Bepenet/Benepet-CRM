from conftest import login, post_json_com_csrf, criar_vendedor
from models import db, Cliente, Venda, ItemVenda, Vendedor, agora_brasil


def criar_cliente(nome='Pet Shop Teste', dias_aviso=30, vendedor=None, data_cadastro=None):
    from conftest import app_mod
    with app_mod.app.app_context():
        c = Cliente(
            nome=nome,
            data_cadastro=data_cadastro or agora_brasil(),
            dias_aviso=dias_aviso,
            periodo_retorno=dias_aviso,
        )
        if vendedor:
            c.vendedor = vendedor
            vend = Vendedor.query.filter_by(nome=vendedor).first()
            if vend:
                c.vendedor_id = vend.id
        db.session.add(c)
        db.session.commit()
        return c.id



def test_salvar_venda_total_recalculado(client, app):
    login(client)
    criar_vendedor('Maria')
    cliente = criar_cliente()

    payload = {
        'cliente_id': cliente,
        'data': '2026-08-12',
        'valor_total': 1.0,  # valor adulterado: o servidor deve ignorar
        'prazo_pagamento': 'A Vista (Pix)',
        'tipo_venda': 'Normal',
        'vendedor': 'Maria',
        'emitir_nf': True,
        'itens': [
            {'produto': 'TAPETE BAG REVENDA', 'quantidade': 2, 'valor_unitario': 10.0, 'valor_subtotal': 999.0},
            {'produto': 'AREIA SILICA', 'quantidade': 1, 'valor_unitario': 5.5, 'valor_subtotal': 999.0},
        ],
    }
    resp = post_json_com_csrf(client, '/salvar_venda_multipla', payload)
    assert resp.status_code == 200

    with app.app_context():
        venda = Venda.query.one()
        assert venda.valor_total == 25.5  # 2*10 + 1*5.5, ignorando o valor adulterado
        assert venda.vendedor_id is not None
        assert all(item.valor_subtotal == item.quantidade * item.valor_unitario for item in venda.itens)


def test_salvar_venda_sem_itens_falha(client):
    login(client)
    cliente = criar_cliente()
    resp = post_json_com_csrf(client, '/salvar_venda_multipla', {
        'cliente_id': cliente,
        'data': '2026-08-12',
        'tipo_venda': 'Normal',
        'itens': [],
    })
    assert resp.status_code == 400


def test_salvar_venda_quantidade_invalida(client):
    login(client)
    cliente = criar_cliente()
    resp = post_json_com_csrf(client, '/salvar_venda_multipla', {
        'cliente_id': cliente,
        'data': '2026-08-12',
        'tipo_venda': 'Normal',
        'itens': [{'produto': 'X', 'quantidade': 0, 'valor_unitario': 5.0}],
    })
    assert resp.status_code == 400


def test_editar_venda_recalcula_total(client, app):
    login(client)
    cliente = criar_cliente()
    with app.app_context():
        venda = Venda(cliente_id=cliente, data=agora_brasil(), valor_total=10.0,
                      status='Confirmada', emitir_nf=True)
        db.session.add(venda)
        db.session.flush()
        db.session.add(ItemVenda(venda_id=venda.id, produto='X', quantidade=1,
                                 valor_unitario=10.0, valor_subtotal=10.0))
        db.session.commit()
        venda_id = venda.id

    resp = post_json_com_csrf(client, f'/vendas/{venda_id}/editar', {
        'cliente_id': cliente,
        'data': '2026-08-12',
        'prazo_pagamento': 'Prazo 15 dias',
        'tipo_venda': 'Normal',
        'status': 'Confirmada',
        'vendedor': '',
        'emitir_nf': True,
        'itens': [
            {'produto': 'Y', 'quantidade': 3, 'valor_unitario': 7.0, 'valor_subtotal': 1.0},
        ],
    })
    assert resp.status_code == 200

    with app.app_context():
        venda = db.session.get(Venda, venda_id)
        assert venda.valor_total == 21.0
        assert len(venda.itens) == 1
        assert venda.itens[0].produto == 'Y'


def test_relatorio_vendas_por_vendedor(client, app):
    login(client)
    maria = criar_vendedor('Maria')
    joao = criar_vendedor('Joao')
    c1 = criar_cliente('Cliente A', vendedor='Maria')
    c2 = criar_cliente('Cliente B', vendedor='Joao')

    with app.app_context():
        db.session.add(Venda(cliente_id=c1, data=agora_brasil(), valor_total=100.0,
                             status='Confirmada', vendedor='Maria', vendedor_id=maria))
        db.session.add(Venda(cliente_id=c2, data=agora_brasil(), valor_total=50.0,
                             status='Confirmada', vendedor='Joao', vendedor_id=joao))
        db.session.commit()

    resp = client.get('/relatorios/vendas-por-vendedor')
    assert resp.status_code == 200
    assert b'Maria' in resp.data
    assert b'Joao' in resp.data

