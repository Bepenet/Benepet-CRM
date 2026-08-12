import os
import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

os.environ['PETCRM_DISABLE_BACKGROUND'] = '1'
os.environ['SECRET_KEY'] = 'chave-de-teste'
if 'DATABASE_URL' not in os.environ:
    os.environ['DATABASE_URL'] = 'sqlite:///' + str(RAIZ / 'instance' / 'test_petcrm.db')

import app as app_mod
from models import db, Usuario, Vendedor
from werkzeug.security import generate_password_hash


@pytest.fixture(scope='session')
def app():
    app_mod.app.config['TESTING'] = True
    return app_mod.app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def banco_limpo(app):
    """Esvazia o banco antes de cada teste e garante os usuários básicos."""
    with app.app_context():
        db.drop_all()
        db.create_all()
        admin = Usuario(login='admin', senha=generate_password_hash('admin123'),
                        precisa_trocar_senha=False, admin=True)
        comum = Usuario(login='comum', senha=generate_password_hash('comum123'),
                        precisa_trocar_senha=False, admin=False)
        db.session.add_all([admin, comum])
        db.session.commit()
    yield
    with app.app_context():
        db.session.remove()


def obter_token_csrf(client, url):
    """Extrai o token CSRF de uma página (formulário ou meta-tag) para POSTs."""
    resp = client.get(url)
    m = re.search(rb'name="csrf_token" value="([^"]+)"', resp.data)
    if not m:
        m = re.search(rb'<meta name="csrf-token" content="([^"]+)"', resp.data)
    return m.group(1).decode() if m else None


def login(client, usuario='admin', senha='admin123', seguir=True):
    """Faz login retornando o client com a sessão ativa."""
    token = obter_token_csrf(client, '/login')
    return client.post('/login', data={
        'usuario': usuario,
        'senha': senha,
        'csrf_token': token,
    }, follow_redirects=seguir)


def post_com_csrf(client, url, dados, url_token='/dashboard'):
    """POST de formulário comum incluindo o token CSRF da sessão."""
    token = obter_token_csrf(client, url_token)
    dados = dict(dados)
    dados['csrf_token'] = token
    return client.post(url, data=dados)


def post_json_com_csrf(client, url, payload, url_token='/dashboard'):
    """POST em JSON incluindo o token CSRF no header (como o front faz)."""
    token = obter_token_csrf(client, url_token)
    return client.post(url, json=payload, headers={'X-CSRFToken': token})


def criar_vendedor(nome='Maria', comissao_pct=5):
    """Cria um vendedor e devolve o id (o objeto fica fora de contexto após retornar)."""
    with app_mod.app.app_context():
        v = Vendedor(nome=nome, comissao_pct=comissao_pct)
        db.session.add(v)
        db.session.commit()
        return v.id
