from conftest import login, obter_token_csrf, post_com_csrf


def test_login_ok(client):
    resp = login(client)
    assert resp.status_code == 200
    assert b'Painel Geral Informativo' in resp.data


def test_login_senha_invalida(client):
    resp = login(client, senha='errada', seguir=True)
    assert b'Usu' in resp.data or b'inv' in resp.data


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
