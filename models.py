from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    login = db.Column(db.String(80), unique=True, nullable=False)
    senha = db.Column(db.String(256), nullable=False) 

class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    cpf_cnpj = db.Column(db.String(20))
    endereco = db.Column(db.String(255))
    telefone = db.Column(db.String(20)) # Whats/Tel
    contato = db.Column(db.String(100)) # Pessoa de contato
    data_cadastro = db.Column(db.DateTime, nullable=False)
    dias_aviso = db.Column(db.Integer, default=30) # 7, 15 ou 30 dias
    periodo_retorno = db.Column(db.Integer, default=30) # Mantido por compatibilidade

class Venda(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)
    data = db.Column(db.DateTime, nullable=False)
    valor_total = db.Column(db.Float, nullable=False)
    
    cliente = db.relationship('Cliente', backref=db.backref('vendas', lazy=True))

class ItemVenda(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    venda_id = db.Column(db.Integer, db.ForeignKey('venda.id'), nullable=False)
    produto = db.Column(db.String(100), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    valor_unitario = db.Column(db.Float, nullable=False)
    valor_subtotal = db.Column(db.Float, nullable=False)
    
    venda = db.relationship('Venda', backref=db.backref('itens', lazy=True))