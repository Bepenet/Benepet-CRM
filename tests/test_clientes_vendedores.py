from datetime import timedelta

from conftest import login, post_com_csrf, criar_vendedor
from models import db, Cliente, Vendedor, agora_brasil


def test_cadastrar_vendedor(client, app):
    login(client)
    resp = post_com_csrf(client, '/vendedores', {
        'nome': 'Ana',
        'telefone': '11999998888',
        'comissao_pct': '5',
    })
    assert resp.status_code in (200, 302)
    with app.app_context():
        assert Vendedor.query.filter_by(nome='Ana').one().comissao_pct == 5.0


def test_cadastrar_cliente_sincroniza_vendedor_fk(client, app):
    login(client)
    criar_vendedor('Maria')
    resp = post_com_csrf(client, '/clientes', {
        'nome': 'Pet Shop Central',
        'cpf_cnpj': '12345678000199',
        'telefone': '11988887777',
        'vendedor': 'Maria',
        'dias_aviso': '30',
        'periodo_retorno': '30',
    })
    assert resp.status_code in (200, 302)
    with app.app_context():
        c = Cliente.query.filter_by(nome='Pet Shop Central').one()
        assert c.vendedor_id == Vendedor.query.filter_by(nome='Maria').one().id
        assert c.vendedor == 'Maria'


def test_excluir_vendedor_limpa_fk(client, app):
    login(client)
    v = criar_vendedor('Carlos')
    with app.app_context():
        c = Cliente(nome='Loja do Carlos', data_cadastro=agora_brasil())
        c.vendedor = 'Carlos'
        c.vendedor_id = v
        db.session.add(c)
        db.session.commit()
        cliente_id = c.id

    resp = post_com_csrf(client, f'/vendedores/{v}/excluir', {}, url_token='/vendedores')
    assert resp.status_code in (200, 302)

    with app.app_context():
        c = db.session.get(Cliente, cliente_id)
        assert c.vendedor_id is None
        assert Vendedor.query.get(v) is None


def test_cliente_precisa_contato(client, app):
    login(client)
    with app.app_context():
        antigo = agora_brasil() - timedelta(days=60)
        c = Cliente(nome='Cliente Antigo', data_cadastro=antigo,
                    dias_aviso=30, periodo_retorno=30)
        db.session.add(c)
        db.session.commit()
        assert c.precisa_contato is True
