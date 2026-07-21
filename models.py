from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), unique=True, nullable=False)
    senha = db.Column(db.String(255), nullable=False)

    def criar_senha(self, senha_pura):
        # Transforma a senha em um código seguro
        self.senha = generate_password_hash(senha_pura)

    def verificar_senha(self, senha_pura):
        # Compara a senha digitada com o código seguro do banco
        return check_password_hash(self.senha, senha_pura)

class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    telefone = db.Column(db.String(20))
    cidade = db.Column(db.String(50))
    produto = db.Column(db.String(100))
    data_compra = db.Column(db.String(10))
    proximo_contato = db.Column(db.String(10))
    observacao = db.Column(db.Text)

class Venda(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)
    produto = db.Column(db.String(100), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    data_venda = db.Column(db.String(10), nullable=False)

    cliente = db.relationship('Cliente', backref=db.backref('vendas', lazy=True))