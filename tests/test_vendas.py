from conftest import login, post_json_com_csrf, criar_vendedor, obter_token_csrf
from app import montar_link_whatsapp_nf
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

    resp = client.get('/relatorios?relatorio=vendas_por_vendedor')
    assert resp.status_code == 200
    assert b'Maria' in resp.data
    assert b'Joao' in resp.data


def test_relatorios_rota_antiga_redireciona(client):
    login(client)
    resp = client.get('/relatorios/vendas-por-vendedor')
    assert resp.status_code == 302
    assert '/relatorios?relatorio=vendas_por_vendedor' in resp.headers.get('Location', '')
    resp = client.get('/vendas/relatorio')
    assert resp.status_code == 302
    assert 'relatorio=historico_vendas' in resp.headers.get('Location', '')


def test_relatorios_pagina_unica_lista_tipos(client):
    login(client)
    resp = client.get('/relatorios')
    assert resp.status_code == 200
    assert b'relatorio' in resp.data
    assert b'vendas_por_vendedor' in resp.data
    assert b'vendas_por_cliente' in resp.data
    assert b'proximo_contato' in resp.data


def test_relatorios_vem_vazio_por_padrao(client, app):
    login(client)
    c = criar_cliente('Pet Shop Teste')
    with app.app_context():
        db.session.add(Venda(cliente_id=c, data=agora_brasil(), valor_total=10.0,
                             status='Confirmada', emitir_nf=True))
        db.session.commit()

    resp = client.get('/relatorios')
    assert resp.status_code == 200
    assert b'Escolha um relat' in resp.data
    assert b'R$ 10.00' not in resp.data


def test_relatorios_historico_vendas_com_venda(client, app):
    login(client)
    c = criar_cliente('Pet Shop Teste')
    with app.app_context():
        db.session.add(Venda(cliente_id=c, data=agora_brasil(), valor_total=10.0,
                             status='Confirmada', emitir_nf=True))
        db.session.commit()

    resp = client.get('/relatorios?relatorio=historico_vendas')
    assert resp.status_code == 200
    assert b'Pet Shop Teste' in resp.data
    assert b'R$ 10.00' in resp.data


def test_relatorios_vendas_por_cliente_requer_selecao(client, app):
    login(client)
    c = criar_cliente('Pet Shop Teste')
    resp = client.get('/relatorios?relatorio=vendas_por_cliente')
    assert resp.status_code == 200
    assert b'Selecione um cliente' in resp.data

    resp = client.get(f'/relatorios?relatorio=vendas_por_cliente&cliente_id={c}')
    assert resp.status_code == 200
    assert b'Pet Shop Teste' in resp.data


def test_relatorios_proximo_contato(client, app):
    login(client)
    with app.app_context():
        db.session.add(Cliente(nome='Cliente Antigo', data_cadastro=agora_brasil(),
                               dias_aviso=30, periodo_retorno=30))
        db.session.commit()

    resp = client.get('/relatorios?relatorio=proximo_contato')
    assert resp.status_code == 200
    assert b'Cliente Antigo' in resp.data


def test_relatorios_comissao(client, app):
    login(client)
    with app.app_context():
        db.session.add(Venda(cliente_id=criar_cliente(), data=agora_brasil(), valor_total=100.0,
                             status='Confirmada', paga=True, data_pagamento=agora_brasil()))
        db.session.commit()

    resp = client.get('/relatorios?relatorio=comissao')
    assert resp.status_code == 200
    assert b'Boletos Pagos' in resp.data


def test_mensagem_whatsapp_item_com_unidade_e_preco(client, app):
    from urllib.parse import unquote
    login(client)
    cliente = criar_cliente('Pet Shop Teste')
    with app.app_context():
        venda = Venda(cliente_id=cliente, data=agora_brasil(), valor_total=25.5,
                      status='Confirmada', prazo_pagamento='A Vista (Pix)')
        db.session.add(venda)
        db.session.flush()
        db.session.add(ItemVenda(venda_id=venda.id, produto='TAPETE', quantidade=2,
                                 valor_unitario=10.0, valor_subtotal=20.0))
        db.session.add(ItemVenda(venda_id=venda.id, produto='AREIA', quantidade=1,
                                 valor_unitario=5.5, valor_subtotal=5.5))
        db.session.commit()

        link = unquote(montar_link_whatsapp_nf(venda))
        assert 'TAPETE x2 un x R$ 10,00 = R$ 20,00' in link
        assert 'AREIA x1 un x R$ 5,50 = R$ 5,50' in link
        assert 'Total: R$ 25,50' in link
        assert 'convertida de Consignado' not in link

        link_convertida = unquote(montar_link_whatsapp_nf(venda, convertida_de_consignacao=True))
        assert '✅ *Venda convertida de Consignado para Venda Confirmada*' in link_convertida


def test_mensagem_whatsapp_confirmar_consignacao(client, app):
    login(client)
    cliente = criar_cliente('Pet Shop Teste')
    with app.app_context():
        venda = Venda(cliente_id=cliente, data=agora_brasil(), valor_total=20.0,
                      status='Pendente', tipo='Consignado', emitir_nf=True)
        db.session.add(venda)
        db.session.commit()
        venda_id = venda.id

    token = obter_token_csrf(client, '/consignacoes-pendentes')
    client.post(f'/vendas/{venda_id}/confirmar_consignacao', data={'csrf_token': token},
                follow_redirects=True)

    with app.app_context():
        venda = db.session.get(Venda, venda_id)
        assert venda.status == 'Confirmada'
        assert venda.data_confirmacao is not None

