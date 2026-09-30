from datetime import date, timedelta

from conftest import login, post_json_com_csrf, post_com_csrf, obter_token_csrf
from app import validar_e_normalizar_parcelas, OPCAO_PARCELAS
from models import db, Cliente, Venda, ItemVenda, ParcelaVenda, agora_brasil


def criar_cliente(nome='Pet Shop Teste'):
    from conftest import app_mod
    with app_mod.app.app_context():
        cliente = Cliente(nome=nome, data_cadastro=agora_brasil(), dias_aviso=30, periodo_retorno=30)
        db.session.add(cliente)
        db.session.commit()
        return cliente.id


def criar_venda_cliente(app, valor=100.0, parcelas=None, status='Confirmada', prazo=None):
    """Cria uma venda com um item e, opcionalmente, um plano de parcelas."""
    from conftest import app_mod
    with app_mod.app.app_context():
        cliente = Cliente(nome='Pet Shop Teste', data_cadastro=agora_brasil(),
                          dias_aviso=30, periodo_retorno=30)
        db.session.add(cliente)
        db.session.flush()

        venda = Venda(cliente_id=cliente.id, data=agora_brasil(), valor_total=valor,
                      status=status, prazo_pagamento=prazo, emitir_nf=True)
        db.session.add(venda)
        db.session.flush()
        db.session.add(ItemVenda(venda_id=venda.id, produto='TAPETE', quantidade=1,
                                 valor_unitario=valor, valor_subtotal=valor))
        for numero, parcela in enumerate(parcelas or [], start=1):
            db.session.add(ParcelaVenda(venda_id=venda.id, numero=numero,
                                        valor=parcela['valor'],
                                        vencimento=date.fromisoformat(parcela['vencimento'])))
        db.session.commit()
        venda_id = venda.id
        ids_parcelas = [p.id for p in venda.parcelas]
    return venda_id, ids_parcelas


def payload_base(cliente_id, parcelas, prazo=OPCAO_PARCELAS):
    return {
        'cliente_id': cliente_id,
        'data': '2026-08-12',
        'prazo_pagamento': prazo,
        'tipo_venda': 'Normal',
        'vendedor': '',
        'emitir_nf': True,
        'parcelas': parcelas,
        'itens': [
            {'produto': 'TAPETE', 'quantidade': 1, 'valor_unitario': 100.0, 'valor_subtotal': 100.0},
        ],
    }


# --- validação do lado do servidor -------------------------------------------

def test_validar_parcelas_aceita_soma_que_fecha():
    parcelas, erro = validar_e_normalizar_parcelas(
        [{'valor': 34.0, 'vencimento': '2026-10-10'},
         {'valor': 33.0, 'vencimento': '2026-09-10'},
         {'valor': 33.0, 'vencimento': '2026-11-10'}],
        100.0,
    )
    assert erro is None
    # Ordena por vencimento para o número da parcela seguir a ordem de cobrança.
    assert [p['vencimento'] for p in parcelas] == [
        date(2026, 9, 10), date(2026, 10, 10), date(2026, 11, 10)
    ]


def test_validar_parcelas_recusa_soma_divergente():
    parcelas, erro = validar_e_normalizar_parcelas(
        [{'valor': 50.0, 'vencimento': '2026-10-10'}], 100.0
    )
    assert parcelas is None
    assert 'não bate com o total da venda' in erro


def test_validar_parcelas_recusa_valor_e_vencimento_invalidos():
    assert validar_e_normalizar_parcelas([{'valor': 0, 'vencimento': '2026-10-10'}], 0)[1]
    assert validar_e_normalizar_parcelas([{'valor': 'abc', 'vencimento': '2026-10-10'}], 1)[1]
    assert validar_e_normalizar_parcelas([{'valor': 10.0, 'vencimento': '10/10/2026'}], 10)[1]
    assert validar_e_normalizar_parcelas([{'valor': 10.0}], 10)[1]


def test_validar_parcelas_tolera_diferenca_de_centavos():
    parcelas, erro = validar_e_normalizar_parcelas(
        [{'valor': 33.33, 'vencimento': '2026-09-10'},
         {'valor': 33.33, 'vencimento': '2026-10-10'},
         {'valor': 33.34, 'vencimento': '2026-11-10'}],
        100.0,
    )
    assert erro is None
    assert len(parcelas) == 3


# --- lançamento de venda parcelada --------------------------------------------

def test_salvar_venda_parcelada_grava_parcelas(client, app):
    login(client)
    cliente = criar_cliente()
    resp = post_json_com_csrf(client, '/salvar_venda_multipla', payload_base(cliente, [
        {'valor': 60.0, 'vencimento': '2026-10-10'},
        {'valor': 40.0, 'vencimento': '2026-11-10'},
    ]))
    assert resp.status_code == 200

    with app.app_context():
        venda = Venda.query.one()
        assert venda.parcelada is True
        assert venda.valor_parcelado == 100.0
        assert venda.valor_em_aberto == 100.0
        assert venda.parcelas_pendentes == 2
        assert venda.paga is False
        assert [p.numero for p in venda.parcelas] == [1, 2]
        assert [p.valor for p in venda.parcelas] == [60.0, 40.0]
        assert 'Parcelado 2x' in venda.prazo_pagamento


def test_salvar_venda_parcelada_sem_parcelas_falha(client):
    login(client)
    cliente = criar_cliente()
    resp = post_json_com_csrf(client, '/salvar_venda_multipla', payload_base(cliente, []))
    assert resp.status_code == 400
    assert 'parcela' in resp.get_json()['erro'].lower()


def test_salvar_venda_parcelada_soma_divergente_falha(client, app):
    login(client)
    cliente = criar_cliente()
    resp = post_json_com_csrf(client, '/salvar_venda_multipla', payload_base(cliente, [
        {'valor': 10.0, 'vencimento': '2026-10-10'},
    ]))
    assert resp.status_code == 400
    with app.app_context():
        assert Venda.query.count() == 0


def test_salvar_venda_sem_plano_de_parcelas_mantém_prazo(client, app):
    login(client)
    cliente = criar_cliente()
    resp = post_json_com_csrf(client, '/salvar_venda_multipla',
                              payload_base(cliente, [], prazo='A Vista (Pix)'))
    assert resp.status_code == 200
    with app.app_context():
        venda = Venda.query.one()
        assert venda.parcelada is False
        assert venda.prazo_pagamento == 'A Vista (Pix)'


# --- baixa individual ---------------------------------------------------------

def test_baixar_parcela_individual(client, app):
    login(client)
    venda_id, parcela_ids = criar_venda_cliente(app, parcelas=[
        {'valor': 60.0, 'vencimento': '2026-10-10'},
        {'valor': 40.0, 'vencimento': '2026-11-10'},
    ])

    resp = post_com_csrf(client, f'/parcelas/{parcela_ids[0]}/baixar', {},
                         url_token=f'/venda/detalhar/{venda_id}')
    assert resp.status_code == 302

    with app.app_context():
        venda = db.session.get(Venda, venda_id)
        assert venda.parcelas[0].paga is True
        assert venda.parcelas[0].data_pagamento is not None
        assert venda.parcelas[1].paga is False
        # A venda só fica paga quando todas as parcelas forem quitadas.
        assert venda.paga is False
        assert venda.data_pagamento is None
        assert venda.valor_em_aberto == 40.0


def test_ultima_parcela_baixa_marca_venda_como_paga(client, app):
    login(client)
    venda_id, parcela_ids = criar_venda_cliente(app, parcelas=[
        {'valor': 60.0, 'vencimento': '2026-10-10'},
        {'valor': 40.0, 'vencimento': '2026-11-10'},
    ])

    for parcela_id in parcela_ids:
        post_com_csrf(client, f'/parcelas/{parcela_id}/baixar', {},
                      url_token=f'/venda/detalhar/{venda_id}')

    with app.app_context():
        venda = db.session.get(Venda, venda_id)
        assert venda.paga is True
        assert venda.data_pagamento is not None
        assert venda.valor_em_aberto == 0


def test_reverter_baixa_de_parcela(client, app):
    login(client)
    venda_id, parcela_ids = criar_venda_cliente(app, parcelas=[
        {'valor': 100.0, 'vencimento': '2026-10-10'},
    ])
    post_com_csrf(client, f'/parcelas/{parcela_ids[0]}/baixar', {},
                  url_token=f'/venda/detalhar/{venda_id}')

    post_com_csrf(client, f'/parcelas/{parcela_ids[0]}/reverter', {},
                  url_token=f'/venda/detalhar/{venda_id}')

    with app.app_context():
        venda = db.session.get(Venda, venda_id)
        assert venda.parcelas[0].paga is False
        assert venda.parcelas[0].data_pagamento is None
        assert venda.paga is False


def test_marcar_venda_paga_recusa_venda_parcelada(client, app):
    login(client)
    venda_id, _ = criar_venda_cliente(app, parcelas=[
        {'valor': 60.0, 'vencimento': '2026-10-10'},
        {'valor': 40.0, 'vencimento': '2026-11-10'},
    ])

    resp = post_com_csrf(client, f'/vendas/{venda_id}/marcar_paga', {},
                         url_token=f'/venda/detalhar/{venda_id}')
    assert resp.status_code == 302

    with app.app_context():
        venda = db.session.get(Venda, venda_id)
        assert venda.paga is False


# --- edição ------------------------------------------------------------------

def test_editar_venda_atualiza_parcelas(client, app):
    login(client)
    venda_id, _ = criar_venda_cliente(app, parcelas=[
        {'valor': 60.0, 'vencimento': '2026-10-10'},
        {'valor': 40.0, 'vencimento': '2026-11-10'},
    ])
    cliente_id = None
    with app.app_context():
        cliente_id = db.session.get(Venda, venda_id).cliente_id

    resp = post_json_com_csrf(client, f'/vendas/{venda_id}/editar', {
        'cliente_id': cliente_id,
        'data': '2026-08-12',
        'prazo_pagamento': OPCAO_PARCELAS,
        'tipo_venda': 'Normal',
        'status': 'Confirmada',
        'vendedor': '',
        'emitir_nf': True,
        'parcelas': [
            {'valor': 50.0, 'vencimento': '2026-09-10'},
            {'valor': 50.0, 'vencimento': '2026-12-10'},
        ],
        'itens': [
            {'produto': 'TAPETE', 'quantidade': 1, 'valor_unitario': 100.0, 'valor_subtotal': 100.0},
        ],
    })
    assert resp.status_code == 200

    with app.app_context():
        venda = db.session.get(Venda, venda_id)
        assert [p.valor for p in venda.parcelas] == [50.0, 50.0]
        assert venda.prazo_pagamento == 'Parcelado 2x (personalizado)'


def test_editar_venda_preserva_baixa_da_parcela_inalterada(client, app):
    login(client)
    venda_id, parcela_ids = criar_venda_cliente(app, parcelas=[
        {'valor': 60.0, 'vencimento': '2026-10-10'},
        {'valor': 40.0, 'vencimento': '2026-11-10'},
    ])
    post_com_csrf(client, f'/parcelas/{parcela_ids[0]}/baixar', {},
                  url_token=f'/venda/detalhar/{venda_id}')

    with app.app_context():
        cliente_id = db.session.get(Venda, venda_id).cliente_id
        data_baixa = db.session.get(ParcelaVenda, parcela_ids[0]).data_pagamento

    resp = post_json_com_csrf(client, f'/vendas/{venda_id}/editar', {
        'cliente_id': cliente_id,
        'data': '2026-08-12',
        'prazo_pagamento': OPCAO_PARCELAS,
        'tipo_venda': 'Normal',
        'status': 'Confirmada',
        'vendedor': '',
        'emitir_nf': True,
        # A segunda parcela muda de valor; a primeira continua idêntica.
        'parcelas': [
            {'valor': 60.0, 'vencimento': '2026-10-10'},
            {'valor': 40.0, 'vencimento': '2026-12-10'},
        ],
        'itens': [
            {'produto': 'TAPETE', 'quantidade': 1, 'valor_unitario': 100.0, 'valor_subtotal': 100.0},
        ],
    })
    assert resp.status_code == 200

    with app.app_context():
        venda = db.session.get(Venda, venda_id)
        assert venda.parcelas[0].paga is True
        assert venda.parcelas[0].data_pagamento == data_baixa
        assert venda.parcelas[1].paga is False


def test_editar_venda_remove_plano_de_parcelas(client, app):
    login(client)
    venda_id, _ = criar_venda_cliente(app, parcelas=[
        {'valor': 100.0, 'vencimento': '2026-10-10'},
    ])
    with app.app_context():
        cliente_id = db.session.get(Venda, venda_id).cliente_id

    resp = post_json_com_csrf(client, f'/vendas/{venda_id}/editar', {
        'cliente_id': cliente_id,
        'data': '2026-08-12',
        'prazo_pagamento': 'A Vista (Pix)',
        'tipo_venda': 'Normal',
        'status': 'Confirmada',
        'vendedor': '',
        'emitir_nf': True,
        'parcelas': [],
        'itens': [
            {'produto': 'TAPETE', 'quantidade': 1, 'valor_unitario': 100.0, 'valor_subtotal': 100.0},
        ],
    })
    assert resp.status_code == 200

    with app.app_context():
        venda = db.session.get(Venda, venda_id)
        assert venda.parcelas == []
        assert venda.prazo_pagamento == 'A Vista (Pix)'


def test_editar_venda_sem_parcelas_mantem_plano(client, app):
    """Payload sem o campo parcelas não deve apagar o plano já existente."""
    login(client)
    venda_id, _ = criar_venda_cliente(app, parcelas=[
        {'valor': 100.0, 'vencimento': '2026-10-10'},
    ])
    with app.app_context():
        cliente_id = db.session.get(Venda, venda_id).cliente_id

    resp = post_json_com_csrf(client, f'/vendas/{venda_id}/editar', {
        'cliente_id': cliente_id,
        'data': '2026-08-12',
        'prazo_pagamento': 'Parcelado 1x (personalizado)',
        'tipo_venda': 'Normal',
        'status': 'Confirmada',
        'vendedor': '',
        'emitir_nf': True,
        'itens': [
            {'produto': 'TAPETE', 'quantidade': 1, 'valor_unitario': 100.0, 'valor_subtotal': 100.0},
        ],
    })
    assert resp.status_code == 200

    with app.app_context():
        venda = db.session.get(Venda, venda_id)
        assert len(venda.parcelas) == 1


def test_excluir_venda_remove_parcelas(client, app):
    login(client)
    venda_id, _ = criar_venda_cliente(app, parcelas=[
        {'valor': 60.0, 'vencimento': '2026-10-10'},
        {'valor': 40.0, 'vencimento': '2026-11-10'},
    ])

    post_com_csrf(client, f'/vendas/{venda_id}/excluir', {}, url_token='/dashboard')

    with app.app_context():
        assert ParcelaVenda.query.count() == 0


# --- telas --------------------------------------------------------------------

def test_detalhe_venda_mostra_parcelas_e_botao_de_baixa(client, app):
    login(client)
    venda_id, parcela_ids = criar_venda_cliente(app, parcelas=[
        {'valor': 60.0, 'vencimento': '2026-10-10'},
        {'valor': 40.0, 'vencimento': '2026-11-10'},
    ])

    resp = client.get(f'/venda/detalhar/{venda_id}')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8')
    assert '1/2' in html and '2/2' in html
    assert f'/parcelas/{parcela_ids[0]}/baixar' in html
    # Venda parcelada não oferece a baixa única da venda inteira.
    assert f'/vendas/{venda_id}/marcar_paga' not in html


def test_formulario_edicao_preenche_parcelas(client, app):
    login(client)
    venda_id, _ = criar_venda_cliente(app, parcelas=[
        {'valor': 60.0, 'vencimento': '2026-10-10'},
        {'valor': 40.0, 'vencimento': '2026-11-10'},
    ])

    resp = client.get(f'/vendas/{venda_id}/editar')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8')
    assert '2026-10-10' in html
    assert '2026-11-10' in html


def test_formulario_nova_venda_oferece_opcao_de_parcelas(client):
    login(client)
    resp = client.get('/vendas')
    assert resp.status_code == 200
    assert OPCAO_PARCELAS.encode('utf-8') in resp.data
    assert b'bloco_parcelas' in resp.data


def test_relatorio_parcelas_a_receber(client, app):
    login(client)
    hoje = date.today()
    criar_venda_cliente(app, parcelas=[
        {'valor': 50.0, 'vencimento': (hoje - timedelta(days=10)).isoformat()},
        {'valor': 50.0, 'vencimento': (hoje + timedelta(days=20)).isoformat()},
    ])

    resp = client.get(f'/relatorios?relatorio=parcelas&periodo=periodo'
                      f'&data_inicio={(hoje - timedelta(days=60)).isoformat()}'
                      f'&data_fim={(hoje + timedelta(days=60)).isoformat()}')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8')
    assert 'Parcelas a Receber' in html
    assert 'Vencida' in html
    assert 'R$ 100,00' in html


def test_relatorio_parcelas_filtra_apenas_pagas(client, app):
    login(client)
    hoje = date.today()
    venda_id, parcela_ids = criar_venda_cliente(app, parcelas=[
        {'valor': 50.0, 'vencimento': (hoje - timedelta(days=10)).isoformat()},
        {'valor': 50.0, 'vencimento': (hoje + timedelta(days=20)).isoformat()},
    ])
    post_com_csrf(client, f'/parcelas/{parcela_ids[0]}/baixar', {},
                  url_token=f'/venda/detalhar/{venda_id}')

    intervalo = (f'periodo=periodo&data_inicio={(hoje - timedelta(days=60)).isoformat()}'
                 f'&data_fim={(hoje + timedelta(days=60)).isoformat()}')

    pendentes = client.get(f'/relatorios?relatorio=parcelas&situacao=pendentes&{intervalo}')
    assert pendentes.data.decode('utf-8').count('/baixar') == 1
    assert '/reverter' not in pendentes.data.decode('utf-8')

    pagas = client.get(f'/relatorios?relatorio=parcelas&situacao=pagas&{intervalo}')
    assert pagas.data.decode('utf-8').count('/reverter') == 1
    assert '/baixar' not in pagas.data.decode('utf-8')