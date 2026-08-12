from conftest import login, post_com_csrf, obter_token_csrf


def test_criar_admin_forcado_removido(client):
    resp = client.get('/criar_admin_forcado')
    assert resp.status_code == 404


def test_csrf_bloqueia_post_sem_token(client):
    resp = client.post('/login', data={'usuario': 'admin', 'senha': 'admin123'})
    assert resp.status_code == 400


def test_csrf_aceita_post_com_token(client):
    login(client)
    token = obter_token_csrf(client, '/dashboard')
    resp = client.post('/login', data={
        'usuario': 'comum',
        'senha': 'comum123',
        'csrf_token': token,
    })
    assert resp.status_code in (200, 302)


def test_usuario_padrao_admin_no_banco_vazio(client, app):
    """Usuário padrão criado com flag admin=True."""
    login(client)
    from models import db, Usuario
    with app.app_context():
        assert Usuario.query.filter_by(login='admin').one().admin is True


def test_toggle_admin(client, app):
    login(client)
    from models import db, Usuario
    with app.app_context():
        comum_id = Usuario.query.filter_by(login='comum').one().id

    token = obter_token_csrf(client, '/usuarios')
    resp = client.post(f'/usuarios/{comum_id}/admin', data={'csrf_token': token},
                       follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        assert Usuario.query.get(comum_id).admin is True

    # não pode remover o próprio admin
    with app.app_context():
        admin_id = Usuario.query.filter_by(login='admin').one().id
    resp = client.post(f'/usuarios/{admin_id}/admin', data={'csrf_token': token})
    with app.app_context():
        assert Usuario.query.get(admin_id).admin is True
