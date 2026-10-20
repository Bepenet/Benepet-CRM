from app import (
    formatar_moeda,
    nome_canonico_produto,
    normalizar_uri_banco,
    validar_e_normalizar_itens,
)
from models import agora_brasil


def test_formatar_moeda():
    assert formatar_moeda(1234.5) == '1.234,50'
    assert formatar_moeda(0) == '0,00'
    assert formatar_moeda(None) == '0,00'


def test_nome_canonico_produto():
    assert nome_canonico_produto('AREIA SILICA') in ('AREIA SILICA', 'AREIA SILICADA')
    assert nome_canonico_produto('   ') == 'SEM NOME'
    assert nome_canonico_produto('PRODUTO NOVO X') == 'PRODUTO NOVO X'


def test_validar_e_normalizar_itens():
    itens, total = validar_e_normalizar_itens([
        {'produto': 'A', 'quantidade': 2, 'valor_unitario': 10.0, 'valor_subtotal': 999.0},
        {'produto': 'B', 'quantidade': 1, 'valor_unitario': 5.5, 'valor_subtotal': 999.0},
    ])
    assert total == 25.5
    assert itens[0]['valor_subtotal'] == 20.0

    _, erro = validar_e_normalizar_itens([])
    assert erro is not None

    _, erro = validar_e_normalizar_itens([{'produto': 'A', 'quantidade': 0, 'valor_unitario': 5.0}])
    assert erro is not None

    _, erro = validar_e_normalizar_itens([{'produto': 'A', 'quantidade': 'x', 'valor_unitario': 5.0}])
    assert erro is not None


def test_agora_brasil_e_naive_local():
    agora = agora_brasil()
    assert agora.tzinfo is None
    # deve refletir o fuso de Brasília: em hora local do servidor (ou GMT)
    import datetime
    diff = abs((datetime.datetime.now() - agora).total_seconds())
    assert diff < 3600  # tolerância ampla para o fuso, mas longe de 12h


def test_normalizar_uri_banco_completa_dominio_render():
    assert normalizar_uri_banco(
        'postgres://u:p@dpg-dalg4k65vjqs73f9gmug-a:5432/db'
    ) == 'postgresql://u:p@dpg-dalg4k65vjqs73f9gmug-a.oregon-postgres.render.com:5432/db'
    assert normalizar_uri_banco(
        'postgresql://u:p@dpg-dalg4k65vjqs73f9gmug-a/db'
    ) == 'postgresql://u:p@dpg-dalg4k65vjqs73f9gmug-a.oregon-postgres.render.com/db'


def test_normalizar_uri_banco_nao_mexe_em_host_completo():
    completa = 'postgresql://u:p@dpg-abc-a.oregon-postgres.render.com/db'
    assert normalizar_uri_banco(completa) == completa
    assert normalizar_uri_banco('sqlite:///petcrm.db') == 'sqlite:///petcrm.db'
    assert normalizar_uri_banco('') == ''
    assert normalizar_uri_banco(None) is None
