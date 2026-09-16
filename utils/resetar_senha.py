"""Redefine a senha de todos os usuários cadastrados.

Uso (no Render, dentro da aba Shell do serviço):
    python utils/resetar_senha.py <nova_senha>

Se não houver nenhum usuário, cria o usuário 'admin' com essa senha.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault('PETCRM_DISABLE_BACKGROUND', '1')

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app import app, db, garantir_colunas_novas
from models import Usuario
from werkzeug.security import generate_password_hash


def principal():
    if len(sys.argv) != 2:
        print('Uso: python utils/resetar_senha.py <nova_senha>')
        sys.exit(1)
    nova_senha = sys.argv[1]
    with app.app_context():
        db.create_all()
        garantir_colunas_novas()
        usuarios = Usuario.query.order_by(Usuario.id).all()
        if not usuarios:
            usuarios = [Usuario(login='admin')]
        for usuario in usuarios:
            usuario.senha = generate_password_hash(nova_senha)
            usuario.precisa_trocar_senha = False
            db.session.add(usuario)
        db.session.commit()
        print('Senha redefinida para os usuários: ' + ', '.join(u.login for u in usuarios))
        print('Agora entre usando um desses logins e a nova senha.')


if __name__ == '__main__':
    principal()