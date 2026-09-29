from conftest import login, obter_token_csrf, post_com_csrf


def test_login_ok(client):
    resp = login(client)
    assert resp.status_code == 200
    assert b'Painel Geral Informativo' in resp.data


def test_login_senha_invalida(client):
    resp = login(client, senha='errada', seguir=True)
    assert b'Usu' in resp.data or b'inv' in resp.data


def test_login_ignora_espaco_no_usuario(client, app):
    """Espaço digitado à esquerda ou à direita do login não impede o acesso."""
    from models import db, Usuario
    from werkzeug.security import generate_password_hash

    with app.app_context():
        db.session.add(Usuario(login='fernanda', senha=generate_password_hash('benepet123'),
                               precisa_trocar_senha=False))
        db.session.commit()

    for digitado in (' fernanda', 'fernanda ', '  fernanda  '):
        client.get('/logout')
        resp = login(client, usuario=digitado, senha='benepet123', seguir=False)
        assert resp.status_code == 302, digitado
        assert '/dashboard' in resp.headers.get('Location', ''), digitado


def test_login_ignora_espaco_salvo_no_cadastro(client, app):
    """Login gravado com espaço no fim também deve funcionar."""
    from models import db, Usuario
    from werkzeug.security import generate_password_hash

    with app.app_context():
        db.session.add(Usuario(login='joana ', senha=generate_password_hash('benepet123')))
        db.session.commit()

    resp = login(client, usuario='joana', senha='benepet123', seguir=False)
    assert resp.status_code == 302
    assert '/dashboard' in resp.headers.get('Location', '')


def test_criar_usuario_ignora_espaco_no_login(client, app):
    from models import db, Usuario

    login(client)
    resp = post_com_csrf(client, '/usuarios', {
        'usuario': '  maria.pet  ',
        'senha': 'benepet123',
    }, url_token='/usuarios')
    assert resp.status_code == 302

    with app.app_context():
        assert Usuario.query.filter_by(login='maria.pet').one() is not None


def test_dashboard_exige_login(client):
    resp = client.get('/dashboard')
    assert resp.status_code == 302
    assert '/login' in resp.headers.get('Location', '')


def test_trocar_senha(client):
    login(client)
    token = obter_token_csrf(client, '/trocar-senha')
    resp = client.post('/trocar-senha', data={
        'nova_senha': 'nova1234',
        'confirmar_senha': 'nova1234',
        'csrf_token': token,
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Painel Geral Informativo' in resp.data


def test_usuario_comum_nao_acessa_vendedores(client):
    login(client, usuario='comum', senha='comum123', seguir=False)
    resp = client.get('/vendedores')
    assert resp.status_code == 302
    assert '/login' in resp.headers.get('Location', '')


def test_admin_acessa_vendedores(client):
    login(client)
    resp = client.get('/vendedores')
    assert resp.status_code == 200
