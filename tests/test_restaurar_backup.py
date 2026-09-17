import io

from conftest import login, obter_token_csrf
from models import Cliente, Vendedor

DUMP_EXEMPLO = r"""\
-- PostgreSQL database dump
SET client_encoding = 'UTF8';
CREATE TABLE public.cliente (
    id integer NOT NULL,
    nome character varying(100) NOT NULL
);
COPY public.cliente (id, nome, data_cadastro) FROM stdin;
1	Atacado Pet	2026-06-01 10:00:00
2	Petshop do Bairro	2026-06-02 11:30:00
\.
COPY public.vendedor (id, nome, comissao_pct) FROM stdin;
1	Maria	5
\.
SELECT pg_catalog.setval('public.cliente_id_seq', 2, true);
"""


def test_restaurar_backup_importa_dados(client):
    login(client)
    token = obter_token_csrf(client, '/restaurar-backup')
    resp = client.post('/restaurar-backup', data={
        'arquivo': (io.BytesIO(DUMP_EXEMPLO.encode('utf-8')), 'backup_teste.sql'),
        'csrf_token': token,
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert b'Backup restaurado com sucesso' in resp.data
    with client.application.app_context():
        assert Cliente.query.count() == 2
        assert Vendedor.query.count() == 1


def test_restaurar_backup_requer_admin(client):
    login(client, 'comum', 'comum123')
    resp = client.get('/restaurar-backup')
    assert resp.status_code == 302


def test_restaurar_backup_sem_arquivo_redireciona(client):
    login(client)
    token = obter_token_csrf(client, '/restaurar-backup')
    resp = client.post('/restaurar-backup', data={
        'csrf_token': token,
    }, follow_redirects=False)
    assert resp.status_code == 302


def test_restaurar_arquivo_invalido_nao_apaga_dados(client):
    from conftest import post_com_csrf
    login(client)
    post_com_csrf(client, '/clientes', {
        'nome': 'Cliente Importante',
        'data_cadastro': '2026-01-01',
    }, url_token='/dashboard')

    token = obter_token_csrf(client, '/restaurar-backup')
    resp = client.post('/restaurar-backup', data={
        'arquivo': (io.BytesIO(b'isto nao e um dump sql de jeito nenhum'), 'garbage.txt'),
        'csrf_token': token,
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert 'não parece ser um dump' in resp.get_data(as_text=True)
    with client.application.app_context():
        assert Cliente.query.filter_by(nome='Cliente Importante').first() is not None