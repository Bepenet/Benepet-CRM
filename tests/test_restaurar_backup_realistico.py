import io

from conftest import login, obter_token_csrf
from models import Cliente, Venda, Vendedor, Usuario

DUMP_REALISTA = r"""\
-- PostgreSQL database dump
--
-- Dumped by pg_dump version 16.3

SET statement_timeout = 0;
SET lock_timeout = 0;
SELECT pg_catalog.set_config('search_path', '', false);

BEGIN;

--
-- Name: usuario; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.usuario (
    id integer NOT NULL,
    login character varying(80) NOT NULL,
    senha character varying(256) NOT NULL,
    precisa_trocar_senha boolean,
    admin boolean
);

CREATE TABLE public.vendedor (
    id integer NOT NULL,
    nome character varying(100) NOT NULL,
    telefone character varying(20),
    email character varying(120),
    endereco character varying(255),
    cep character varying(10),
    cidade character varying(100),
    uf character varying(2),
    comissao_pct double precision
);

CREATE TABLE public.cliente (
    id integer NOT NULL,
    nome character varying(100) NOT NULL,
    nome_fantasia character varying(100),
    cpf_cnpj character varying(20),
    endereco character varying(255),
    cep character varying(10),
    cidade character varying(100),
    uf character varying(2),
    telefone character varying(20),
    email character varying(120),
    contato character varying(100),
    vendedor character varying(100),
    data_cadastro timestamp without time zone NOT NULL,
    dias_aviso integer,
    periodo_retorno integer,
    contato_adiado_ate timestamp without time zone,
    contato_desconsiderado boolean,
    vendedor_id integer
);

CREATE SEQUENCE public.cliente_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.cliente_id_seq OWNED BY public.cliente.id;
ALTER TABLE ONLY public.cliente ALTER COLUMN id SET DEFAULT nextval('public.cliente_id_seq'::regclass);

CREATE TABLE public.venda (
    id integer NOT NULL,
    cliente_id integer NOT NULL,
    data timestamp without time zone NOT NULL,
    valor_total double precision NOT NULL,
    prazo_pagamento character varying(50),
    tipo character varying(20),
    status character varying(20),
    data_confirmacao timestamp without time zone,
    vendedor character varying(100),
    paga boolean,
    data_pagamento timestamp without time zone,
    emitir_nf boolean,
    vendedor_id integer
);

CREATE TABLE public.item_venda (
    id integer NOT NULL,
    venda_id integer NOT NULL,
    produto character varying(100) NOT NULL,
    quantidade integer NOT NULL,
    valor_unitario double precision NOT NULL,
    valor_subtotal double precision NOT NULL
);

--
-- Data for Name: usuario; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.usuario (id, login, senha, precisa_trocar_senha, admin) FROM stdin;
1	admin	scrypt:abc	t	f
2	ana	scrypt:def	f	f
\.
COPY public.vendedor (id, nome, telefone, email, endereco, cep, cidade, uf, comissao_pct) FROM stdin;
1	Maria	\N	\N	\N	\N	\N	\N	5
\.
COPY public.cliente (id, nome, nome_fantasia, cpf_cnpj, endereco, cep, cidade, uf, telefone, email, contato, vendedor, data_cadastro, dias_aviso, periodo_retorno, contato_adiado_ate, contato_desconsiderado, vendedor_id) FROM stdin;
1	Atacado Pet	Pet Center	\N	Rua A, 10	\N	Florianopolis	SC	\N	\N	\N	Maria	2026-06-01 10:00:00	30	30	\N	f	1
2	Petshop do Bairro	\N	12.345.678/0001-90	\N	88000-000	\N	\N	48999999999	\N	Joao	\N	2026-07-01 10:00:00	15	15	\N	f	\N
\.
COPY public.venda (id, cliente_id, data, valor_total, prazo_pagamento, tipo, status, data_confirmacao, vendedor, paga, data_pagamento, emitir_nf, vendedor_id) FROM stdin;
1	1	2026-06-10 10:00:00	150	20 dias	Normal	Confirmada	\N	Maria	t	\N	t	1
\.
COPY public.item_venda (id, venda_id, produto, quantidade, valor_unitario, valor_subtotal) FROM stdin;
1	1	TAPETE USO INTERNO	3	50	150
\.
ALTER TABLE ONLY public.item_venda ADD CONSTRAINT item_venda_venda_id_fkey FOREIGN KEY (venda_id) REFERENCES public.venda(id);
ALTER TABLE ONLY public.venda ADD CONSTRAINT venda_cliente_id_fkey FOREIGN KEY (cliente_id) REFERENCES public.cliente(id);

COMMIT;
"""


def test_restaurar_dump_realista(client):
    login(client)
    token = obter_token_csrf(client, '/restaurar-backup')
    resp = client.post('/restaurar-backup', data={
        'arquivo': (io.BytesIO(DUMP_REALISTA.encode('utf-8')), 'backup_real.sql'),
        'csrf_token': token,
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert b'Backup restaurado com sucesso' in resp.data, resp.data[-2000:]
    with client.application.app_context():
        assert Cliente.query.count() == 2
        assert Vendedor.query.count() == 1
        assert Venda.query.count() == 1
        assert Usuario.query.count() == 2


def test_analisar_dump_realista(client):
    import backup as backup_mod
    instrucoes, blocos_copy = backup_mod.analisar_dump(DUMP_REALISTA)
    nomes_copy = [b[0] for b in blocos_copy]
    assert 'public.cliente' in nomes_copy
    assert 'public.venda' in nomes_copy
    assert 'public.item_venda' in nomes_copy
    assert len(nomes_copy) == len(set(nomes_copy))


def test_dump_real_carrega_controle_de_transacao(banco_limpo):
    import backup as backup_mod
    instrucoes, _ = backup_mod.analisar_dump(DUMP_REALISTA)
    em_uma_linha = ' '.join(i.replace('\n', ' ') for i in instrucoes)
    assert 'BEGIN' in em_uma_linha
    assert 'COMMIT' in em_uma_linha
    assert 'SELECT' in em_uma_linha


def test_instrucao_para_ignorar():
    import backup as backup_mod
    ignorar = [
        'BEGIN;', 'COMMIT;', 'END;', 'ROLLBACK;',
        'START TRANSACTION;',
        'SET statement_timeout = 0;',
        'SET\n  client_encoding = \'UTF8\';',
        'COPY public.cliente (id, nome) FROM stdin;',
    ]
    manter = [
        'CREATE TABLE public.cliente (id integer NOT NULL);',
        'ALTER TABLE ONLY public.cliente ALTER COLUMN id SET DEFAULT nextval(\'public.cliente_id_seq\'::regclass);',
        'CREATE SEQUENCE public.cliente_id_seq AS integer;',
        'SELECT pg_catalog.setval(\'public.cliente_id_seq\', 2, true);',
        'CREATE INDEX cliente_nome_idx ON public.cliente USING btree (nome);',
        'ALTER TABLE ONLY public.venda ADD CONSTRAINT venda_cliente_id_fkey FOREIGN KEY (cliente_id) REFERENCES public.cliente(id);',
    ]
    for sql in ignorar:
        assert backup_mod._instrucao_para_ignorar(sql), f'deveria ignorar: {sql}'
    for sql in manter:
        assert not backup_mod._instrucao_para_ignorar(sql), f'deveria manter: {sql}'


def test_analisar_dump_separa_instrucoes_consecutivas():
    """Dois comandos de uma linha seguidos (sem linha em branco) não podem virar uma instrução só."""
    import backup as backup_mod
    dump = (
        "SET statement_timeout = 0;\n"
        "SET lock_timeout = 0;\n"
        "SELECT pg_catalog.set_config('search_path', '', false);\n"
        "CREATE TABLE public.cliente (id integer NOT NULL);\n"
        "SELECT pg_catalog.setval('public.cliente_id_seq', 2, true);\n"
        "SELECT pg_catalog.setval('public.vendedor_id_seq', 1, true);\n"
    )
    instrucoes, _ = backup_mod.analisar_dump(dump)
    assert len(instrucoes) == 6, [i for i in instrucoes]
    assert 'CREATE TABLE public.cliente' in instrucoes[3]
    assert 'set_config' in instrucoes[2]
    assert instrucoes[4].count('setval') == 1