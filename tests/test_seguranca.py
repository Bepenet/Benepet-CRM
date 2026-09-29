from conftest import login, obter_token_csrf


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


def test_admin_define_senha_inicial_e_exige_troca(client, app):
    from models import db, Usuario
    from werkzeug.security import check_password_hash
    with app.app_context():
        comum_id = Usuario.query.filter_by(login='comum').one().id

    login(client)
    token = obter_token_csrf(client, '/usuarios')
    resp = client.post(f'/usuarios/{comum_id}/senha-inicial',
                       data={'senha_inicial': 'provisoria1', 'csrf_token': token})
    assert resp.status_code == 302

    with app.app_context():
        alvo = db.session.get(Usuario, comum_id)
        assert check_password_hash(alvo.senha, 'provisoria1')
        assert alvo.precisa_trocar_senha is True

    # o usuário entra com a senha inicial e é levado para a troca obrigatória
    client.get('/logout')
    login(client, usuario='comum', senha='provisoria1', seguir=False)
    resp = client.get('/dashboard')
    assert '/trocar-senha' in resp.headers.get('Location', '')

    # depois de trocar, volta a acessar o sistema normalmente
    token = obter_token_csrf(client, '/trocar-senha')
    client.post('/trocar-senha', data={'nova_senha': 'definitiva9',
                                       'confirmar_senha': 'definitiva9',
                                       'csrf_token': token})
    resp = client.get('/dashboard')
    assert resp.status_code == 200

    with app.app_context():
        assert db.session.get(Usuario, comum_id).precisa_trocar_senha is False


def test_senha_inicial_curta_e_recusada(client, app):
    from models import Usuario
    with app.app_context():
        comum_id = Usuario.query.filter_by(login='comum').one().id

    login(client)
    token = obter_token_csrf(client, '/usuarios')
    resp = client.post(f'/usuarios/{comum_id}/senha-inicial',
                       data={'senha_inicial': '12', 'csrf_token': token},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert b'pelo menos 4 caracteres' in resp.data

    with app.app_context():
        assert Usuario.query.get(comum_id).precisa_trocar_senha is False


def test_usuario_comum_nao_define_senha_inicial(client, app):
    from models import Usuario
    with app.app_context():
        admin_id = Usuario.query.filter_by(login='admin').one().id

    login(client, usuario='comum', senha='comum123', seguir=False)
    token = obter_token_csrf(client, '/dashboard')
    resp = client.post(f'/usuarios/{admin_id}/senha-inicial',
                       data={'senha_inicial': 'invadida1', 'csrf_token': token})
    assert resp.status_code == 302

    with app.app_context():
        assert Usuario.query.get(admin_id).precisa_trocar_senha is False
