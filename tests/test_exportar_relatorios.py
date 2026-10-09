from datetime import date, timedelta

from conftest import app_mod, criar_vendedor, login
from models import (Cliente, HistoricoProspeccao, ItemVenda, ParcelaVenda,
                    Prospeccao, Venda, db, agora_brasil)

XLSX_ASSINATURA = b'PK\x03\x04'


def _semear():
    """Cria dados mínimos que alimentam todos os tipos de relatório."""
    with app_mod.app.app_context():
        vendedor = criar_vendedor(nome='Maria', comissao_pct=5)
        cliente = Cliente(nome='Pet Shop Teste', nome_fantasia='Pet Teste',
                          telefone='48999998888', data_cadastro=agora_brasil(),
                          dias_aviso=30, periodo_retorno=30, vendedor='Maria',
                          vendedor_id=vendedor)
        db.session.add(cliente)
        db.session.flush()

        venda = Venda(cliente_id=cliente.id, data=agora_brasil(), valor_total=100.0,
                      prazo_pagamento='Prazo 30 dias', status='Confirmada',
                      vendedor='Maria', vendedor_id=vendedor, paga=True,
                      data_pagamento=agora_brasil(), emitir_nf=True)
        db.session.add(venda)
        db.session.flush()
        db.session.add(ItemVenda(venda_id=venda.id, produto='TAPETE USO INTERNO',
                                 quantidade=2, valor_unitario=50.0, valor_subtotal=100.0))
        db.session.add(ParcelaVenda(venda_id=venda.id, numero=1, valor=100.0,
                                    vencimento=date.today() + timedelta(days=15)))

        prospeccao = Prospeccao(nome='Novo Cliente', telefone='48988887777',
                                status='Em andamento', data_cadastro=agora_brasil())
        db.session.add(prospeccao)
        db.session.flush()
        db.session.add(HistoricoProspeccao(prospeccao_id=prospeccao.id,
                                           data=agora_brasil(), tipo='Telefone',
                                           descricao='Primeiro contato'))
        db.session.commit()
        return cliente.id


def test_exportar_exige_login(app):
    client = app.test_client()
    resp = client.get('/relatorios/exportar?relatorio=vendas_por_mes')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_exportar_sem_relatorio_redireciona(app):
    client = app.test_client()
    login(client)
    resp = client.get('/relatorios/exportar')
    assert resp.status_code == 302
    assert '/relatorios' in resp.headers['Location']


def test_exportar_todos_os_relatorios(app):
    cliente_id = _semear()
    client = app.test_client()
    login(client)

    casos = [
        ('historico_vendas', 'periodo=mes'),
        ('vendas_por_vendedor', 'periodo=mes'),
        ('vendas_por_mes', 'periodo=mes'),
        ('quantidade_produtos', 'periodo=mes'),
        ('comissao', 'periodo=mes'),
        ('historico_matriz', 'periodo=ano'),
        ('proximo_contato', ''),
        ('parcelas', 'periodo=mes'),
        ('vendas_por_cliente', f'periodo=mes&cliente_id={cliente_id}'),
    ]
    for tipo, filtros in casos:
        url = f'/relatorios/exportar?relatorio={tipo}'
        if filtros:
            url += f'&{filtros}'
        resp = client.get(url)
        assert resp.status_code == 200, f'{tipo} -> {resp.status_code}'
        assert resp.data.startswith(XLSX_ASSINATURA), f'{tipo} não gerou um .xlsx'
        assert 'spreadsheetml.sheet' in resp.headers['Content-Type']
        assert '.xlsx' in resp.headers['Content-Disposition']


def test_exportar_vendas_por_cliente_sem_cliente_redireciona(app):
    _semear()
    client = app.test_client()
    login(client)
    resp = client.get('/relatorios/exportar?relatorio=vendas_por_cliente&periodo=mes')
    assert resp.status_code == 302
    assert '/relatorios' in resp.headers['Location']
